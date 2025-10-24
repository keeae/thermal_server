import base64
import numpy as np
import requests
import time

SERVER = "http://127.0.0.1:5000/upload"

WIDTH = 80
HEIGHT = 62

while True:
    # Random temperature test data
    temps = (np.random.rand(HEIGHT, WIDTH) * 40 + 20).astype(np.int16) * 100

    raw = temps.tobytes()
    frame_b64 = base64.b64encode(raw).decode('utf-8')

    payload = {
        "frame_b64": frame_b64,
        "w": WIDTH,
        "h": HEIGHT
    }

    r = requests.post(SERVER, json=payload)
    print("Server:", r.text)

    time.sleep(1)  # 1 frame per second
