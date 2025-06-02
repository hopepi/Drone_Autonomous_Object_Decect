import socket
import struct
import cv2
import numpy as np
import json
import threading
from flask import Flask, Response
from ultralytics import YOLO

FRAME_WIDTH = 640
FRAME_HEIGHT = 320
FRAME_CENTER_X = FRAME_WIDTH // 2
FRAME_CENTER_Y = FRAME_HEIGHT // 2
HOST = '0.0.0.0'
PORT = 8000

model = YOLO("yolov8s.pt")
labels = model.names
latest_frame = None

app = Flask(__name__)

@app.route("/stream")
def stream():
    def generate():
        global latest_frame
        while True:
            if latest_frame is None:
                continue
            _, buffer = cv2.imencode('.jpg', latest_frame)
            frame = buffer.tobytes()
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n'
            )
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

def yolo_server():
    global latest_frame
    while True:  # Sonsuz tekrar döngüsü (bağlantı koparsa tekrar accept)
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((HOST, PORT))
        server_socket.listen(1)
        print(f"🚀 Server başlatıldı: {HOST}:{PORT}, bağlantı bekleniyor...")

        conn, addr = server_socket.accept()
        print(f"📡 Bağlantı alındı: {addr}")
        buffer = b""

        try:
            while True:
                while len(buffer) < 4:
                    recv_data = conn.recv(4096)
                    if not recv_data:
                        raise ConnectionError("Bağlantı koptu!")
                    buffer += recv_data
                img_size = struct.unpack(">L", buffer[:4])[0]
                buffer = buffer[4:]

                while len(buffer) < img_size:
                    recv_data = conn.recv(4096)
                    if not recv_data:
                        raise ConnectionError("Bağlantı koptu!")
                    buffer += recv_data
                img_data = buffer[:img_size]
                buffer = buffer[img_size:]

                np_data = np.frombuffer(img_data, dtype=np.uint8)
                frame = cv2.imdecode(np_data, cv2.IMREAD_COLOR)

                results = model(frame, verbose=False)[0]
                hedef_listesi = []
                for box in results.boxes:
                    if box.conf.item() > 0.4:
                        cls = int(box.cls.item())
                        label = labels[cls]
                        xmin, ymin, xmax, ymax = map(int, box.xyxy.squeeze())
                        x_center = (xmin + xmax) // 2
                        y_center = (ymin + ymax) // 2
                        area = (xmax - xmin) * (ymax - ymin)
                        dx = x_center - FRAME_CENTER_X
                        dy = y_center - FRAME_CENTER_Y
                        hedef = {
                            "etiket": label,
                            "conf": round(float(box.conf.item()), 2),
                            "dx": dx,
                            "dy": dy,
                            "alan": area
                        }
                        hedef_listesi.append(hedef)
                        cv2.rectangle(frame, (xmin, ymin), (xmax, ymax), (0, 255, 0), 2)
                        cv2.putText(frame, f"{label} ({hedef['conf']})", (xmin, ymin - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                cv2.circle(frame, (FRAME_CENTER_X, FRAME_CENTER_Y), 5, (0, 0, 255), -1)
                latest_frame = frame.copy()
                response = {"status": "hedefler", "hedefler": hedef_listesi}
                response_json = json.dumps(response).encode('utf-8')
                conn.sendall(struct.pack(">L", len(response_json)) + response_json)
                cv2.imshow("YOLO Server - PC", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    raise KeyboardInterrupt

        except Exception as e:
            print("⛔ Hata veya bağlantı koptu:", e)
        finally:
            try:
                conn.close()
            except:
                pass
            try:
                server_socket.close()
            except:
                pass
            print("⏳ Tekrar bağlantı bekleniyor...\n")

threading.Thread(target=yolo_server, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
