# control.py
from simple_pid import PID
import drone_control as drone
import time

MAX_SPEED = 0.6       # m/s
MAX_YAW = 15          # derece/s
P_YAW = 0.01
P_ROLL = 0.18
I_YAW = 0
D_YAW = 0
I_ROLL = 0
D_ROLL = 0

pidYaw = None
pidRoll = None
flight_altitude = 2

def configure_PID(control="PID"):
    global pidYaw, pidRoll
    print("Configuring control")
    if control == "PID":
        pidYaw = PID(P_YAW, I_YAW, D_YAW, setpoint=0)
        pidYaw.output_limits = (-MAX_YAW, MAX_YAW)
        pidRoll = PID(P_ROLL, I_ROLL, D_ROLL, setpoint=0)
        pidRoll.output_limits = (-MAX_SPEED, MAX_SPEED)
    else:
        pidYaw = PID(P_YAW, 0, 0, setpoint=0)
        pidYaw.output_limits = (-MAX_YAW, MAX_YAW)
        pidRoll = PID(P_ROLL, 0, 0, setpoint=0)
        pidRoll.output_limits = (-MAX_SPEED, MAX_SPEED)

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

def send_yaw_control(dx):
    # dx = merkezden sapma
    if pidYaw is not None:
        yaw_speed = pidYaw(dx)   # PID ile hesaplanan açı (derece/s)
        # Sabit limit uygula
        yaw_speed = max(min(yaw_speed, MAX_YAW), -MAX_YAW)
        drone.yaw_relative(yaw_speed)
        print(f"PID YAW: {dx:.1f} → {yaw_speed:.2f}")

def send_position_control(dx, dy, area, area_ref=3000):
    # PID kullanmıyorsan doğrudan hareket komutu ver
    # dx: yatay, dy: dikey, area: mesafe kontrolü için obje alanı
    vx, vy, vz = 0, 0, 0
    # Aşağıdaki katsayıları uçuşa göre ayarlayabilirsin
    Kx = 0.004
    Ky = 0.006
    Kz = 0.0005

    if abs(dx) > 20:
        vy = dx * Kx  # sağ (+), sol (-)
    if abs(dy) > 15:
        vz = -dy * Ky # yukarı (-), aşağı (+)
    delta_area = area_ref - area
    if abs(delta_area) > 400:
        vx = delta_area * Kz

    # Limitler
    vx = max(min(vx, MAX_SPEED), -MAX_SPEED)
    vy = max(min(vy, MAX_SPEED), -MAX_SPEED)
    vz = max(min(vz, MAX_SPEED), -MAX_SPEED)

    print(f"PID Pozisyon: dx={dx} dy={dy} alan={area} | vx={vx:.2f} vy={vy:.2f} vz={vz:.2f}")
    drone.send_ned_velocity(vx, vy, vz, duration=1)
