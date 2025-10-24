from flask import Flask, request, jsonify, send_file
import numpy as np
import cv2
import base64
import os
import time

app = Flask(__name__, template_folder='templates', static_folder='static')

WIDTH = 80
HEIGHT = 62

last_info = {}

@app.route('/')
def index():
    return "Thermal server (ready)"


@app.route('/upload', methods=['POST'])
def upload():
    global last_info
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error":"no json"}), 400

    w = int(data.get("w", WIDTH))
    h = int(data.get("h", HEIGHT))
    b64 = data.get("frame_b64")

    if not b64:
        return jsonify({"error":"no frame_b64"}), 400

    try:
        raw = base64.b64decode(b64)
        arr = np.frombuffer(raw, dtype=np.int16)
        if arr.size != w*h:
            return jsonify({"error":"size mismatch", "got": arr.size, "exp": w*h}), 400

        temps = arr.astype(np.float32) / 100.0
        temps2d = temps.reshape((h, w))

        min_t = float(np.min(temps2d))
        max_t = float(np.max(temps2d))
        avg_t = float(np.mean(temps2d))

        import cv2
        norm = cv2.normalize(temps2d, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        heatmap = cv2.applyColorMap(cv2.resize(norm, (w*4, h*4)), cv2.COLORMAP_JET)

        os.makedirs('static', exist_ok=True)
        img_path = os.path.join('static', 'thermal_detected.jpg')
        cv2.imwrite(img_path, heatmap)

        last_info = {"timestamp": time.time(), "min":min_t, "max":max_t, "avg":avg_t}
        return jsonify({"status":"ok","min":min_t,"max":max_t,"avg":avg_t})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/image')
def image():
    path = 'static/thermal_detected.jpg'
    if os.path.exists(path):
        return send_file(path, mimetype='image/jpeg')
    return "No image", 404

@app.route('/status')
def status():
    return jsonify(last_info)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
