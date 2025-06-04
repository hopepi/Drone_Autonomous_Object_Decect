# drone_server_v2.py (FPS hatası giderilmiş stabil sürüm)
import socket
import struct
import time
import json
import threading
from flask import Flask, request, jsonify, redirect
import random
import atexit
import drone_control
import control
import signal
import sys
from datetime import datetime
sys.path.append("/usr/lib/python3/dist-packages")
from picamera2 import Picamera2
from libcamera import Transform
import cv2
import numpy as np

# ---------- AYARLAR ----------
SERVER_IP = '10.245.198.73'
SERVER_PORT = 8000
PC_STREAM_IP = '10.245.198.73'
PC_STREAM_PORT = 8080
FPS = 7
FRAME_DELAY = 1 / FPS
FRAME_WIDTH = 640
FRAME_HEIGHT = 320

# ---------- GLOBAL DEĞİŞKENLER ----------
latest_frame = None
hedef_etiketi = None
drone_state = "land"
emergency_flag = False
current_altitude = 1.0
picam2 = None
lock = threading.Lock()
system_ready = False

# ---------- LOG ----------
def log_to_file(msg):
    with open("drone_server.log", "a") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")

def log(msg, level="info"):
    renk = {
        "info": "\033[94m[INFO] ", "warning": "\033[93m[WARN] ",
        "danger": "\033[91m[ERROR] ", "success": "\033[92m[SUCCESS] ",
        "end": "\033[0m"
    }
    formatted = f"{renk.get(level, '')}{msg}{renk['end']}"
    print(formatted)
    log_to_file(f"[{level.upper()}] {msg}")

# ---------- ACİL DURUM ----------
def land_drone():
    global current_altitude
    try:
        log("🛬 Drone iniş yapıyor...", "danger")
        control.land()
        current_altitude = 0.0
    except Exception as e:
        log(f"Drone iniş hatası: {e}", "danger")

def handle_exit(signum=None, frame=None):
    log("🛑 Program sonlandırılıyor, iniş yapılıyor...", "warning")
    land_drone()
    if picam2: picam2.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)
atexit.register(land_drone)

# ---------- KAMERA THREAD ----------
def update_camera():
    global latest_frame
    prev_frame = None
    while True:
        try:
            frame = picam2.capture_array()
            if frame is None or (prev_frame is not None and np.array_equal(frame, prev_frame)):
                continue
            prev_frame = frame.copy()
            with lock:
                latest_frame = frame.copy()
            time.sleep(0.01)
        except Exception as e:
            log(f"Kamera yakalama hatası: {e}", "danger")
            time.sleep(1)

# ---------- PC'ye GÖNDER ----------
def send_to_pc():
    global latest_frame, hedef_etiketi, drone_state, emergency_flag
    last_target_time = time.time()
    while True:
        try:
            log("🔁 PC'ye bağlanılıyor...", "warning")
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((SERVER_IP, SERVER_PORT))
            log("🟢 Kamera client PC'ye bağlı", "success")

            while True:
                start_time = time.time()
                with lock:
                    frame = latest_frame.copy() if latest_frame is not None else None
                if frame is None:
                    continue

                _, img_encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                data = img_encoded.tobytes()
                client_socket.sendall(struct.pack(">L", len(data)) + data)

                cmd_len_bytes = client_socket.recv(4)
                if not cmd_len_bytes:
                    break
                cmd_len = struct.unpack(">L", cmd_len_bytes)[0]
                command_json = client_socket.recv(cmd_len).decode('utf-8')

                try:
                    command = json.loads(command_json)
                    log(f"📥 Gelen komut JSON: {command}", "info")
                    if command.get("status") == "hedefler":
                        hedefler = command.get("hedefler", [])
                        hedef_bulundu = False

                        for hedef in hedefler:
                            etiket = hedef.get("etiket")
                            dx = hedef.get("dx")
                            dy = hedef.get("dy")
                            alan = hedef.get("alan")

                            if etiket == "person":
                                log("‼️ İnsan tespit edildi - drone durdu", "danger")
                                emergency_flag = True
                                drone_state = "emergency"
                                break

                            if emergency_flag:
                                continue

                            if hedef_etiketi and etiket != hedef_etiketi:
                                continue

                            hedef_bulundu = True
                            last_target_time = time.time()

                            control.send_yaw_control(dx)
                            control.send_position_control(dx, dy, alan)
                            drone_state = "track"
                            break

                        if not hedef_bulundu and (time.time() - last_target_time) > 30:
                            log("⏳ 30 sn hedef yok - iniş", "warning")
                            land_drone()
                            drone_state = "land"
                            last_target_time = time.time()

                except json.JSONDecodeError:
                    log("⚠️ Komut JSON hatası!", "danger")

                if emergency_flag or drone_state == "emergency":
                    control.stop_drone()

                time.sleep(max(0, FRAME_DELAY - (time.time() - start_time)))

        except Exception as e:
            log(f"❌ Bağlantı hatası: {e}", "danger")
            try: client_socket.close()
            except: pass
            log("5 saniye sonra yeniden deneniyor...", "warning")
            time.sleep(5)

# ---------- FLASK ----------
app = Flask(__name__)

@app.route("/stream")
def stream():
    return redirect(f"http://{PC_STREAM_IP}:{PC_STREAM_PORT}/stream", code=302)

@app.route("/ping")
def ping():
    return "pong", 200

@app.route("/command", methods=["POST"])
def command():
    global hedef_etiketi, drone_state, current_altitude

    if not system_ready:
        return jsonify({"status": "Sistem hazır değil"}), 503

    data = request.json
    mode = data.get("mode")
    altitude = data.get("altitude")
    target = data.get("target")
    hedef_etiketi = target

    try:
        alt = float(altitude)
    except:
        alt = 1.0
    alt = max(1.0, min(5.0, alt))

    if drone_state == "land" or current_altitude != alt:
        control.arm_and_takeoff(alt)
        current_altitude = alt

    drone_state = "track" if target else "land"
    if mode != "obje":
        return jsonify({"status": "geçersiz mod"}), 400
    return jsonify({
        "status": f"{mode} başlatıldı (hedef: {target}, irtifa: {alt:.1f} m)",
        "id": random.randint(10000, 99999)
    })

@app.route("/reset", methods=["POST"])
def reset():
    global hedef_etiketi, drone_state
    hedef_etiketi = None
    drone_state = "land"
    return jsonify({"status": "Tüm objeler izlenecek"})

@app.route("/emergency", methods=["POST"])
def emergency():
    global emergency_flag, drone_state
    emergency_flag = True
    control.stop_drone()
    drone_state = "emergency"
    return jsonify({"status": "Drone acil durduruldu"})

@app.route("/resume", methods=["POST"])
def resume():
    global emergency_flag, drone_state, current_altitude, hedef_etiketi
    emergency_flag = False

    if hedef_etiketi:
        try:
            control.arm_and_takeoff(current_altitude)
            drone_state = "track"
            return jsonify({"status": f"Takibe devam ediliyor: {hedef_etiketi}"}), 200
        except:
            return jsonify({"status": "Kalkış yapılamadı"}), 500
    else:
        land_drone()
        drone_state = "land"
        return jsonify({"status": "Hedef yok, sadece emergency bitti"}), 200

# ---------- SETUP ----------
def setup():
    global picam2, system_ready
    try:
        picam2 = Picamera2()
        config = picam2.create_video_configuration(
            main={"size": (FRAME_WIDTH, FRAME_HEIGHT), "format": "RGB888"},
            transform=Transform(hflip=1)
        )
        picam2.configure(config)
        picam2.start()
        time.sleep(2)
        log("📷 Picamera2 aktif", "success")
    except Exception as e:
        log(f"Kamera hatası: {e}", "danger")
        handle_exit()

    try:
        drone_control.connect_drone('/dev/serial0')
        log("✅ Drone bağlandı", "success")
    except Exception as e:
        log(f"Drone bağlantı hatası: {e}", "danger")
        handle_exit()

    control.configure_PID()
    threading.Thread(target=update_camera, daemon=True).start()
    threading.Thread(target=send_to_pc, daemon=True).start()
    system_ready = True
    log("🚀 Sistem hazır, komut alınabilir", "success")

# ---------- MAIN ----------
if __name__ == "__main__":
    setup()
    log("🛰️ Drone sunucu başlatıldı", "info")
    app.run(host="0.0.0.0", port=5000, threaded=True)
