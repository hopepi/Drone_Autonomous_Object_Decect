import socket
import struct
import cv2
import time
import json
import threading
from flask import Flask, Response, request, jsonify, redirect
import random
import atexit

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
current_altitude = 1.0  # Varsayılan 1m

def log(msg, level="info"):
    renk = {"info": "\033[94m", "warning": "\033[93m", "danger": "\033[91m", "success": "\033[92m", "end": "\033[0m"}
    print(f"{renk.get(level, '')}{msg}{renk['end']}")

def takeoff_and_hover(target_altitude=1.0):
    # Sınırla
    if target_altitude < 1.0:
        target_altitude = 1.0
    if target_altitude > 5.0:
        target_altitude = 5.0
    log(f"🚁 Kalkış! {target_altitude:.1f} metreye yükseliyor...", "success")
    # Burada gerçek drone kalkış komutunu çağırabilirsin!
    # Örnek: tello.takeoff(); tello.go_up((target_altitude-1.0)*100)
    global current_altitude
    current_altitude = target_altitude

def land_drone():
    log("🛬 Drone iniş yapıyor...", "danger")
    # Gerçek drone için: tello.land()
    global current_altitude
    current_altitude = 0.0

atexit.register(land_drone)

def send_to_pc():
    global latest_frame, hedef_etiketi, drone_state, emergency_flag
    while True:
        try:
            log("🔄 PC'ye bağlanmayı deniyor...", "warning")
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((SERVER_IP, SERVER_PORT))
            log("🟢 Kamera client PC'ye bağlı", "success")

            while True:
                start_time = time.time()
                ret, frame = cap.read()
                if not ret:
                    continue
                _, img_encoded = cv2.imencode('.jpg', frame)
                data = img_encoded.tobytes()
                client_socket.sendall(struct.pack(">L", len(data)) + data)
                latest_frame = frame.copy()

                if emergency_flag:
                    log("🚨 ACİL DURUM: Sadece yayın, hedef takibi/hareket yok. (iniş/hover modda!)", "danger")
                    elapsed = time.time() - start_time
                    if elapsed < FRAME_DELAY:
                        time.sleep(FRAME_DELAY - elapsed)
                    continue

                cmd_len_bytes = client_socket.recv(4)
                if not cmd_len_bytes:
                    break
                cmd_len = struct.unpack(">L", cmd_len_bytes)[0]
                command_json = client_socket.recv(cmd_len).decode('utf-8')

                try:
                    command = json.loads(command_json)
                    if command.get("status") == "hedefler":
                        hedefler = command.get("hedefler", [])
                        acil_durum = False
                        for hedef in hedefler:
                            etiket = hedef.get("etiket")
                            dx = hedef.get("dx")
                            dy = hedef.get("dy")
                            alan = hedef.get("alan")
                            if etiket == "person":
                                log("İnsan tespit edildi – uzak duruluyor", "danger")
                                if alan < 8000:
                                    log("Geri git – kişiye çok yakınsın", "danger")
                                else:
                                    log("Mesafe güvenli, kişi izlenmiyor", "warning")
                                acil_durum = True
                                drone_state = "emergency"
                                continue
                            if not hedef_etiketi:
                                log("🛬 Hedef tanımsız – LAND modunda bekleniyor", "warning")
                                drone_state = "land"
                                break
                            if hedef_etiketi and etiket != hedef_etiketi:
                                continue
                            if acil_durum:
                                break
                            hedef_x = FRAME_CENTER_X + dx
                            hedef_y = FRAME_CENTER_Y + dy
                            cv2.circle(frame, (FRAME_CENTER_X, FRAME_CENTER_Y), 8, (0, 0, 255), -1)
                            cv2.circle(frame, (hedef_x, hedef_y), 8, (0, 255, 0), -1)
                            cv2.line(frame, (FRAME_CENTER_X, FRAME_CENTER_Y), (hedef_x, hedef_y), (255, 0, 0), 2)
                            log(f"🎯 {etiket} | dx: {dx}, dy: {dy}, alan: {alan}", "info")
                            if abs(dx) > 50:
                                log("Sağa dön" if dx > 0 else "⬅️ Sola dön", "warning")
                            else:
                                log("Yatayda merkezde", "success")
                            if abs(dy) > 30:
                                log("Aşağı in" if dy > 0 else "⬆️ Yukarı çık", "warning")
                            else:
                                log("Dikeyde merkezde", "success")
                            if alan > 7000:
                                log("Geri git – çok yakın", "danger")
                            elif alan < 1500:
                                log("İleri git – çok uzak", "warning")
                            else:
                                log("Mesafe ideal", "success")
                            drone_state = "track"
                            break

                except json.JSONDecodeError:
                    log("⚠️ JSON çözümlenemedi!", "danger")

                elapsed = time.time() - start_time
                if elapsed < FRAME_DELAY:
                    time.sleep(FRAME_DELAY - elapsed)
        except Exception as e:
            log(f"⛔ Bağlantı hatası veya başka hata: {e}", "danger")
            try:
                client_socket.close()
            except:
                pass
            log("5 saniye sonra tekrar denenecek...", "warning")
            time.sleep(5)

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
    log(f"📥 Komut alındı | Mod: {mode}, İrtifa: {altitude}, Hedef: {target}", "info")
    hedef_etiketi = target

    try:
        alt = float(altitude)
    except (ValueError, TypeError):
        alt = 1.0
    if alt < 1.0:
        alt = 1.0
    if alt > 5.0:
        alt = 5.0
    if current_altitude != alt:
        takeoff_and_hover(alt)

    drone_state = "track" if target else "land"
    if mode not in ["el", "obje"]:
        return jsonify({"status": "geçersiz mod"}), 400
    return jsonify({
        "status": f"{mode} modu başlatıldı (hedef: {target}, irtifa: {alt:.1f} m)",
        "id": random.randint(10000, 99999)
    })

@app.route("/reset", methods=["POST"])
def reset():
    global hedef_etiketi, drone_state
    hedef_etiketi = None
    drone_state = "land"
    log("🔄 Hedef filtresi sıfırlandı", "warning")
    return jsonify({"status": "filtre sıfırlandı, tüm objeler dikkate alınacak"})

@app.route("/emergency", methods=["POST"])
def emergency():
    global emergency_flag, drone_state
    emergency_flag = True
    drone_state = "emergency"
    log("‼️ ACİL DURDURMA KOMUTU ALINDI", "danger")
    return jsonify({"status": "acil durdurma tamamlandı"})

@app.route("/resume", methods=["POST"])
def resume():
    global emergency_flag, drone_state
    emergency_flag = False
    drone_state = "land"
    log("✅ Emergency bitti, sistem tekrar aktif", "success")
    return jsonify({"status": "emergency sıfırlandı, devam edebilirsiniz"})

cap = cv2.VideoCapture(0)
if not cap.isOpened():
    log("Kamera açılamadı!", "danger")
    exit()

# KALKIŞ! (Program başında 1 metreye çıkar)
takeoff_and_hover(1.0)

threading.Thread(target=send_to_pc, daemon=True).start()

if __name__ == "__main__":
    log("🚁 Drone sunucu başlatılıyor...", "info")
    app.run(host="0.0.0.0", port=5000)
