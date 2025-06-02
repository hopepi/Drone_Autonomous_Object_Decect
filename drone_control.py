from dronekit import connect, VehicleMode
import time
from pymavlink import mavutil

vehicle = None

def connect_drone(connection_string, waitready=True, baudrate=57600):
    global vehicle
    if vehicle is None:
        print(f"🚁 Bağlanılıyor: {connection_string}")
        vehicle = connect(connection_string, wait_ready=waitready, baud=baudrate)
    print("✅ Drone bağlı")

def disconnect_drone():
    global vehicle
    if vehicle is not None:
        vehicle.close()
        print("✋ Bağlantı kapatıldı")

def arm_and_takeoff(target_altitude):
    global vehicle
    print("🚦 Pre-arm kontrolü yapılıyor...")
    while not vehicle.is_armable:
        print("⏳ Araç başlatılıyor...")
        time.sleep(1)

    print("🔑 Arming motors")
    vehicle.mode = VehicleMode("GUIDED")
    vehicle.armed = True
    while not vehicle.armed:
        print("⏳ Arming bekleniyor...")
        time.sleep(1)

    print(f"🛫 Kalkış! Hedef irtifa: {target_altitude} m")
    vehicle.simple_takeoff(target_altitude)
    while True:
        alt = vehicle.location.global_relative_frame.alt
        print(f"✈️ Yükseliyor: {alt:.2f} m")
        if alt >= target_altitude * 0.95:
            print("✅ Hedef irtifaya ulaşıldı!")
            break
        time.sleep(1)

def land():
    global vehicle
    print("🛬 LAND moduna geçiliyor...")
    vehicle.mode = VehicleMode("LAND")

def send_ned_velocity(vx, vy, vz, duration=1):
    """
    vx: ileri/geri (+ileri)
    vy: sağ/sol (+sağ)
    vz: aşağı/yukarı (+aşağı)
    duration: kaç saniye boyunca gönderilecek
    """
    global vehicle
    msg = vehicle.message_factory.set_position_target_local_ned_encode(
        0, 0, 0,
        mavutil.mavlink.MAV_FRAME_BODY_NED,
        0b0000111111000111,
        0, 0, 0,    # x, y, z pos
        vx, vy, vz, # hızlar
        0, 0, 0,    # ivmeler
        0, 0
    )
    for _ in range(duration * 10):  # 0.1 sn arayla tekrar gönder
        vehicle.send_mavlink(msg)
        time.sleep(0.1)

def yaw_relative(angle, speed=15):
    """
    angle: derece (+ sağa, - sola)
    speed: derece/saniye
    """
    global vehicle
    is_relative = 1
    msg = vehicle.message_factory.command_long_encode(
        0, 0,
        mavutil.mavlink.MAV_CMD_CONDITION_YAW,
        0,
        abs(angle), speed,
        1 if angle >= 0 else -1,
        is_relative,
        0, 0, 0
    )
    vehicle.send_mavlink(msg)
    print(f"↪️ YAW komutu gönderildi: {angle} derece, hız: {speed}")

def rtl():
    global vehicle
    print("🔄 RTL moduna geçiliyor...")
    vehicle.mode = VehicleMode("RTL")
