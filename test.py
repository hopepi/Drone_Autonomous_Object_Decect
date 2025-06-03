from pymavlink import mavutil
import time

master = mavutil.mavlink_connection('/dev/serial0', baud=57600)

master.wait_heartbeat()
print(f"✅ Bağlantı sağlandı! Sistem ID: {master.target_system}, Komponent ID: {master.target_component}")

print("📜 Desteklenen modlar:")
print(master.mode_mapping())

mode = 'GUIDED'
mode_id = master.mode_mapping()[mode]
master.set_mode(mode_id)
print(f"🧭 {mode} moduna geçildi")

master.arducopter_arm()
master.motors_armed_wait()
print("🚀 Drone arm edildi (hareketsiz)")

time.sleep(5)

master.arducopter_disarm()
master.motors_disarmed_wait()
print("Drone disarm edildi (güvenli)")
