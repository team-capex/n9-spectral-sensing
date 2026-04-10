"""
development/temperature_monitor.py

Connect to a single spectral sensor board and live-plot NTC probe temperature.

Edit COM_PORT and SENSOR_PIN before running:
    python development/temperature_monitor.py

Ctrl-C exits cleanly and closes the serial port.
"""

import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from spectral_board_manager.spectral_sensor import SpectralSensor

# --- Configuration ---
COM_PORT = "/dev/cu.wchusbserial110"   # Serial port of the spectral sensor board
SENSOR_PIN = 5      # NTC probe pin (1 or 2 on board; firmware default is 5)
INTERVAL_S = 5      # Seconds between readings
HEATER_POWER = 100.0 # Heater power for both heaters (0–100 %)
# ---------------------

sensor = SpectralSensor(COM=COM_PORT)
sensor.set_heater_power(1, HEATER_POWER)
sensor.set_heater_power(2, HEATER_POWER)

times: list[float] = []
temps: list[float] = []

fig, ax = plt.subplots()
(line,) = ax.plot([], [], "b-o", markersize=4, linewidth=1)
ax.set_xlabel("Elapsed time (s)")
ax.set_ylabel("Temperature (°C)")
ax.set_title(f"Live temperature  —  {COM_PORT}, pin {SENSOR_PIN}")
plt.ion()
plt.show()

start = time.time()
try:
    while True:
        temp = sensor.get_temperature(sensor_pin=SENSOR_PIN)
        elapsed = time.time() - start
        times.append(elapsed)
        temps.append(temp)
        print(f"t={elapsed:7.1f}s  T={temp:.2f}°C")

        line.set_data(times, temps)
        ax.relim()
        ax.autoscale_view()
        fig.canvas.draw_idle()
        plt.pause(0.05)

        time.sleep(INTERVAL_S)
finally:
    sensor.close_ser()
