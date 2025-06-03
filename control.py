# control.py
from simple_pid import PID
import drone_control as drone
import time

# ---------- PID ve hız sabitleri ----------
MAX_SPEED = 1        # m/s
MAX_YAW = 15         # derece/saniye

# YAW PID parametreleri
P_YAW, I_YAW, D_YAW = 0.18, 0.018, 0.0

# ROLL (pozisyon) PID parametreleri
P_ROLL, I_ROLL, D_ROLL = 0.135, 0.182, 0.0036

# PID objeleri
pidYaw = None
pidRoll = None

# Hedef irtifa (sistemde kullanılmak üzere)
flight_altitude = 1.0

# dx ve area geçmişi (filtre için)
__dx_history = []
__area_history = []

# ---------- Ortalama Filtreler ----------
def smooth_dx(dx, window=5):
    __dx_history.append(dx)
    if len(__dx_history) > window:
        __dx_history.pop(0)
    return sum(__dx_history) / len(__dx_history)

def smooth_area(area, window=5):
    __area_history.append(area)
    if len(__area_history) > window:
        __area_history.pop(0)
    return sum(__area_history) / len(__area_history)

# ---------- PID Ayarları ----------
def configure_PID(mode="PID"):
    global pidYaw, pidRoll
    print("⚙️ PID ayarlanıyor...")

    if mode == "PID":
        pidYaw = PID(P_YAW, I_YAW, D_YAW, setpoint=0)
        pidRoll = PID(P_ROLL, I_ROLL, D_ROLL, setpoint=0)
    else:
        pidYaw = PID(P_YAW, 0, 0, setpoint=0)
        pidRoll = PID(P_ROLL, 0, 0, setpoint=0)

    pidYaw.output_limits = (-MAX_YAW, MAX_YAW)
    pidRoll.output_limits = (-MAX_SPEED, MAX_SPEED)

# ---------- Drone Kontrolleri ----------
def connect_drone(connection_str):
    drone.connect_drone(connection_str)

def arm_and_takeoff(height):
    drone.arm_and_takeoff(height)

def land():
    drone.land()

def rtl():
    drone.rtl()

def stop_drone():
    drone.send_ned_velocity(0, 0, 0, duration=1)

# ---------- PID ile YAW (Yön) Kontrolü ----------
def send_yaw_control(dx):
    """
    dx: merkez ile hedef arasındaki yatay fark (piksel)
    """
    dx_smooth = smooth_dx(dx)
    if pidYaw is not None:
        yaw_speed = pidYaw(dx_smooth)
        yaw_speed = max(min(yaw_speed, MAX_YAW), -MAX_YAW)
        drone.yaw_relative(yaw_speed)
        print(f"🧭 PID YAW: dx={dx:.1f} (smoothed={dx_smooth:.1f}) → {yaw_speed:.2f}°/s")

# ---------- Pozisyon (VX, VY, VZ) Kontrolü ----------
def send_position_control(dx, dy, area, area_ref=3000):
    """
    dx, dy: hedefin merkezden sapması (piksel)
    area: hedef bounding box alanı
    area_ref: ideal alan (hedefin ideal uzaklığına göre)
    """
    vx, vy, vz = 0, 0, 0
    Kx, Ky, Kz = 0.004, 0.006, 0.0005

    if abs(dx) > 20:
        vy = dx * Kx  # +sağ, -sol

    if abs(dy) > 15:
        vz = -dy * Ky  # -yukarı, +aşağı (NED sistemine göre)

    area_smooth = smooth_area(area)
    delta_area = area_ref - area_smooth
    if abs(delta_area) > 400:
        vx = delta_area * Kz  # +ileri, -geri

    # 🔸 Limit uygula
    vx = max(min(vx, MAX_SPEED), -MAX_SPEED)
    vy = max(min(vy, MAX_SPEED), -MAX_SPEED)
    vz = max(min(vz, MAX_SPEED), -MAX_SPEED)

    print(f"🎯 PID Pozisyon: dx={dx}, dy={dy}, alan={area} → smooth={area_smooth:.1f} → vx={vx:.2f}, vy={vy:.2f}, vz={vz:.2f}")
    drone.send_ned_velocity(vx, vy, vz, duration=1)
