# drone_server.py (güvenli ve hataya dayanıklı versiyon)
import socket
import struct
import cv2
import time
import json
import threading
from flask import Flask, Response, request, jsonify, redirect
import random
import atexit
import drone_control
import control
import signal
import sys

# ---------- AYARLAR ----------
SERVER_IP = '127.0.0.1'
SERVER_PORT = 8000
PC_STREAM_IP = '10.245.198.73'
PC_STREAM_PORT = 8080
FPS = 15
FRAME_DELAY = 1 / FPS
FRAME_WIDTH = 640
FRAME_HEIGHT = 320
FRAME_CENTER_X = FRAME_WIDTH // 2
FRAME_CENTER_Y = FRAME_HEIGHT // 2

# ---------- GLOBAL DEĞİŞKENLER ----------
latest_frame = None
hedef_etiketi = None
drone_state = "land"
emergency_flag = False
current_altitude = 1.0
cap = None

# ---------- LOG ----------
def log(msg, level="info"):
    renk = {
        "info": "\033[94m[INFO] ", "warning": "\033[93m[WARN] ",
        "danger": "\033[91m[ERROR] ", "success": "\033[92m[SUCCESS] ",
        "end": "\033[0m"
    }
    print(f"{renk.get(level, '')}{msg}{renk['end']}")

# ---------- ACİL DURUM VE GÜVENLİ ÇIKIŞ ----------
def land_drone():
    global current_altitude
    try:
        log("\U0001f6ec Drone iniş yapıyor...", "danger")
        control.land()
        current_altitude = 0.0
    except Exception as e:
        log(f"Drone iniş hatası: {e}", "danger")

def handle_exit(signum=None, frame=None):
    log("\U0001f6d1 Program sonlandırılıyor, iniş yapılıyor...", "warning")
    land_drone()
    if cap: cap.release()
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)
atexit.register(land_drone)

# ---------- KAMERA GÖNDERİM VE KOMUT ALIMI ----------
def send_to_pc():
    global latest_frame, hedef_etiketi, drone_state, emergency_flag, cap
    last_target_time = time.time()

    while True:
        try:
            log("\U0001f501 PC'ye bağlanılıyor...", "warning")
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((SERVER_IP, SERVER_PORT))
            log("\U0001f7e2 Kamera client PC'ye bağlı", "success")

            while True:
                start_time = time.time()
                ret, frame = cap.read()
                if not ret:
                    log("Kamera verisi okunamadı", "danger")
                    continue

                _, img_encoded = cv2.imencode('.jpg', frame)
                data = img_encoded.tobytes()
                client_socket.sendall(struct.pack(">L", len(data)) + data)
                latest_frame = frame.copy()

                if emergency_flag or drone_state == "emergency":
                    log("\U0001f6a8 ACİL DURUM: Drone hareketi durduruluyor", "danger")
                    control.stop_drone()
                    time.sleep(max(0, FRAME_DELAY - (time.time() - start_time)))
                    continue

                cmd_len_bytes = client_socket.recv(4)
                if not cmd_len_bytes:
                    log("Sunucu komut uzunluğu boş geldi", "danger")
                    break
                cmd_len = struct.unpack(">L", cmd_len_bytes)[0]
                command_json = client_socket.recv(cmd_len).decode('utf-8')

                try:
                    command = json.loads(command_json)
                    if command.get("status") == "hedefler":
                        hedefler = command.get("hedefler", [])
                        hedef_bulundu = False

                        for hedef in hedefler:
                            etiket = hedef.get("etiket")
                            dx = hedef.get("dx")
                            dy = hedef.get("dy")
                            alan = hedef.get("alan")

                            if etiket == "person":
                                log("‼️ İnsan tespit edildi - kaçın", "danger")
                                drone_state = "emergency"
                                break

                            if hedef_etiketi and etiket != hedef_etiketi:
                                continue

                            hedef_bulundu = True
                            last_target_time = time.time()

                            control.send_yaw_control(dx)
                            control.send_position_control(dx, dy, alan)
                            drone_state = "track"
                            break

                        if not hedef_bulundu and (time.time() - last_target_time) > 30:
                            log("⏳ 30 sn hedef yok - iniliyor", "warning")
                            land_drone()
                            drone_state = "land"
                            last_target_time = time.time()

                except json.JSONDecodeError:
                    log("\u26a0️ Komut JSON hatası!", "danger")

                time.sleep(max(0, FRAME_DELAY - (time.time() - start_time)))

        except Exception as e:
            log(f"\u274c Bağlantı hatası: {e}", "danger")
            try: client_socket.close()
            except: pass
            log("5 saniye sonra yeniden deneniyor...", "warning")
            time.sleep(5)

# ---------- FLASK API ----------
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
    data = request.json
    mode = data.get("mode")
    altitude = data.get("altitude")
    target = data.get("target")
    log(f"\U0001f4e5 Komut: Mod={mode}, İrtifa={altitude}, Hedef={target}", "info")
    hedef_etiketi = target

    try:
        alt = float(altitude)
    except (ValueError, TypeError):
        alt = 1.0
    alt = max(1.0, min(5.0, alt))
    if current_altitude != alt:
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
    log("\U0001f504 Hedef sıfırlandı", "warning")
    return jsonify({"status": "Tüm objeler izlenecek"})

@app.route("/emergency", methods=["POST"])
def emergency():
    global emergency_flag, drone_state
    emergency_flag = True
    log("‼️ ACİL DURDURMA", "danger")
    try:
        control.stop_drone()
        time.sleep(3)
        land_drone()
    except Exception as e:
        log(f"Emergency hata: {e}", "danger")
    drone_state = "emergency"
    return jsonify({"status": "Drone durdu ve iniyor"})

@app.route("/resume", methods=["POST"])
def resume():
    global emergency_flag, drone_state
    emergency_flag = False
    land_drone()
    drone_state = "land"
    log("\u2705 Emergency modu sona erdi", "success")
    return jsonify({"status": "Sistem normale döndü"})

# ---------- SETUP ----------
def setup():
    global cap
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        log("\U0001f4f7 Kamera açılamadı!", "danger")
        handle_exit()
    else:
        log("\U0001f4f7 Kamera aktif", "success")

    try:
        drone_control.connect_drone('/dev/serial0')
        log("\u2705 Drone bağlandı", "success")
    except Exception as e:
        log(f"Drone bağlantı hatası: {e}", "danger")
        handle_exit()

    control.configure_PID()
    threading.Thread(target=send_to_pc, daemon=True).start()

# ---------- MAIN ----------
if __name__ == "__main__":
    setup()
    log("\U0001f681 Drone sunucu başlatılıyor...", "info")
    app.run(host="0.0.0.0", port=5000)
