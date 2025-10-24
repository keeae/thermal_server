# server.py
import os, time, base64, io, sqlite3, json
from flask import Flask, request, jsonify, send_file, render_template, abort
import numpy as np
import cv2
from functools import wraps
from collections import defaultdict

# ====== تكوينات ======
API_KEY = os.environ.get("THERMAL_API_KEY", "CHANGE_ME")
UPLOAD_DIR = os.path.join(os.getcwd(), "data")
DB_PATH = os.path.join(os.getcwd(), "data", "frames.db")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# تنبيه عبر WEBHOOK (اختياري)
ALERT_WEBHOOK = os.environ.get("ALERT_WEBHOOK")  # https://hooks.example.com/...

# حدود
MAX_B64_SIZE = 250000  # ~250 KB
W = 80
H = 62

app = Flask(__name__, static_folder='static', template_folder='templates')

# ==== Rate limiting بسيط per-IP ====
RATE = defaultdict(lambda: {"t": time.time(), "count": 0})
MAX_PER_SECOND = 5

def check_rate_limit(ip):
    s = RATE[ip]
    now = time.time()
    if now - s["t"] > 1:
        s["t"] = now
        s["count"] = 1
        return True
    else:
        s["count"] += 1
        return s["count"] <= MAX_PER_SECOND

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = None
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            key = auth.split(" ",1)[1]
        if not key:
            key = request.args.get("api_key")
        if key != API_KEY:
            return jsonify({"error":"unauthorized"}), 401
        ip = request.remote_addr or "unknown"
        if not check_rate_limit(ip):
            return jsonify({"error":"rate_limited"}), 429
        return f(*args, **kwargs)
    return decorated

# ====== قاعدة البيانات ======
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS frames (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL,
        filename TEXT,
        min REAL,
        max REAL,
        avg REAL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL,
        frame_id INTEGER,
        msg TEXT
    )""")
    con.commit()
    con.close()

init_db()

def db_insert_frame(filename, min_t, max_t, avg_t):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT INTO frames (ts,filename,min,max,avg) VALUES (?,?,?,?,?)",
                (time.time(), filename, min_t, max_t, avg_t))
    fid = cur.lastrowid
    con.commit()
    con.close()
    return fid

def db_insert_alert(frame_id, msg):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT INTO alerts (ts,frame_id,msg) VALUES (?,?,?)",
                (time.time(), frame_id, msg))
    con.commit()
    con.close()

# ====== تنبيه خارجي (webhook) اختياري ======
def send_webhook(payload):
    if not ALERT_WEBHOOK:
        return
    try:
        import requests
        requests.post(ALERT_WEBHOOK, json=payload, timeout=3)
    except Exception as e:
        print("Webhook error:", e)

# ====== حالة أخيرة ======
last_info = {}

# helper لتحويل base64->numpy temps
def decode_frame_from_b64(b64, w=W, h=H):
    raw = base64.b64decode(b64)
    arr = np.frombuffer(raw, dtype=np.int16)
    if arr.size != w*h:
        raise ValueError(f"size mismatch {arr.size} != {w*h}")
    temps = arr.astype(np.float32) / 100.0
    return temps.reshape((h, w))

# تحليل وتنبيه بسيط: كشف انخفاض/ارتفاع مفاجئ مقارنةً بالإطار السابق
prev_avg = None
ALERT_THRESHOLD_DELTA = 5.0  # درجة مئوية للاختلاف المفاجئ

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/history")
def history():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id, ts, filename, min, max, avg FROM frames ORDER BY ts DESC LIMIT 200")
    rows = cur.fetchall()
    con.close()
    items = [{"id":r[0],"ts":r[1],"filename":r[2],"min":r[3],"max":r[4],"avg":r[5]} for r in rows]
    return render_template("history.html", items=items)

@app.route("/download/<int:fid>")
def download(fid):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT filename FROM frames WHERE id=?", (fid,))
    r = cur.fetchone()
    con.close()
    if not r:
        abort(404)
    path = os.path.join(UPLOAD_DIR, r[0])
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="image/jpeg", as_attachment=True, download_name=r[0])

@app.route("/alerts")
def alerts():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id, ts, frame_id, msg FROM alerts ORDER BY ts DESC LIMIT 200")
    rows = cur.fetchall()
    con.close()
    return jsonify([{"id":r[0],"ts":r[1],"frame_id":r[2],"msg":r[3]} for r in rows])

@app.route("/status")
def status():
    return jsonify(last_info or {})

@app.route("/image")
def image():
    p = os.path.join(UPLOAD_DIR, "thermal_detected.jpg")
    if os.path.exists(p):
        return send_file(p, mimetype="image/jpeg")
    return jsonify({"error":"no_image"}), 404

@app.route("/upload", methods=["POST"])
@require_api_key
def upload():
    global last_info, prev_avg
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error":"no json"}), 400
    b64 = data.get("frame_b64")
    w = int(data.get("w", W))
    h = int(data.get("h", H))
    if not b64:
        return jsonify({"error":"no frame_b64"}), 400
    if len(b64) > MAX_B64_SIZE:
        return jsonify({"error":"payload too large"}), 413
    try:
        temps2d = decode_frame_from_b64(b64, w, h)
        min_t = float(np.min(temps2d))
        max_t = float(np.max(temps2d))
        avg_t = float(np.mean(temps2d))
        # generate heatmap and save
        norm = cv2.normalize(temps2d, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        heatmap = cv2.applyColorMap(cv2.resize(norm, (w*4, h*4)), cv2.COLORMAP_JET)
        filename = f"frame_{int(time.time())}.jpg"
        dst = os.path.join(UPLOAD_DIR, filename)
        cv2.imwrite(dst, heatmap, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        # update current image (also save as thermal_detected.jpg)
        cv2.imwrite(os.path.join(UPLOAD_DIR, "thermal_detected.jpg"), heatmap, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        # store to DB
        fid = db_insert_frame(filename, min_t, max_t, avg_t)
        # check alerts
        if prev_avg is not None:
            delta = avg_t - prev_avg
            if abs(delta) >= ALERT_THRESHOLD_DELTA:
                msg = f"Sudden temp change: {delta:+.2f}°C (avg now {avg_t:.2f})"
                db_insert_alert(fid, msg)
                send_webhook({"type":"alert","msg":msg,"frame_id":fid,"avg":avg_t})
        prev_avg = avg_t
        last_info = {"ts": time.time(), "min": min_t, "max": max_t, "avg": avg_t, "frame_id": fid}
        return jsonify({"status":"ok","min":min_t,"max":max_t,"avg":avg_t, "frame_id": fid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
