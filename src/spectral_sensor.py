import logging
import time
import os
import serial

logging.basicConfig(level = logging.INFO)

def skip_if_sim(default_return = None):
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            if self.sim:
                return default_return
            return func(self, *args, **kwargs)
        return wrapper
    return decorator

class SpectralSensor:
    def __init__(self, COM: str, baud: int = 115200, sim: bool = False, timeout: float = 60.0):
        self.sim = sim
        self.timeout = timeout

        if self.sim:
            logging.info("Simulated connection to spectral sensor board established.")

        else:
            logging.info("Configuring spectral sensor board serial port..")
            self.ser = serial.Serial(
                port=COM,
                baudrate=baud,
                timeout=self.timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )

            # Turn ESP ON (active low)
            self.ser.setDTR(False)  # False = inactive = HIGH (because DTR is active-low)
            self.ser.setRTS(False)

            logging.info("Attempting to open spectral sensor board serial port..")

            if self.ser.isOpen() is False:
                self.ser.open()
            else:
                self.ser.close()
                time.sleep(0.05)
                self.ser.open()

            # Give time for controller to wake up
            time.sleep(2)

            # Check connection (blocking)
            self.check_response()
            logging.info("Serial connection to spectral sensor board established.")

    @skip_if_sim(default_return="0")
    def get_data(self) -> str:
        start = time.time()

        while(time.time() - start < self.timeout):
            if self.ser.in_waiting > 0:
                break

            time.sleep(0.1)
        
        if self.ser.in_waiting == 0:
             raise RuntimeError("Timed out waiting for response.")
        else:
            return self.ser.readline().decode().rstrip().replace("\x00", "")
        
    @skip_if_sim()
    def check_response(self) -> None:
        while True:
            data = self.get_data()

            if data.startswith("ESP-ROM:"):
                continue

            if '#' in data:
                return
            if "Unknown command" in data:
                raise RuntimeError("Controller board failed to recognise command: " + data)

            logging.info(data)

    def extract_readings(self) -> str:
        while True:
            data = self.get_data()

            if data.startswith("ESP-ROM:"):
                continue

            if "[DATA]" in data:
                return data
            if "Unknown command" in data:
                raise RuntimeError("Controller board failed to recognise command: " + data)

    @skip_if_sim()
    def close_ser(self) -> None:
        logging.info("Closing serial connection to spectral sensor board.")
        if self.ser.isOpen():
            self.ser.close()

    #Serial.println("setHeaterPower(int heater, int power)");
    #Serial.println("setVoltage(float volts) 0-10V");
    #Serial.println("setCurrent(float mA) 0-20mA");

    #Serial.println("Sensors:");
    #Serial.println("readSensor(int sensor)");
    #Serial.println("fullShutdown()");
    #Serial.println("wakeAll()");

    @skip_if_sim(default_return = "F1=0,F2=0,F3=0,F4=0,F5=0,F6=0,F7=0,F8=0,CLR=0,NIR=0")
    def read_sensor(self, no: int) -> str:
        self.ser.write(f"readSensor({no})".encode())
        return self.extract_readings()
    
    @skip_if_sim()
    def shutdown_sensors(self) -> None:
        self.ser.write("fullShutdown()".encode())
        self.check_response()

    @skip_if_sim()
    def wake_sensors(self) -> None:
        self.ser.write("wakeAll()".encode())
        self.check_response()

    @skip_if_sim()
    def set_heater_power(self, no: int, power: float) -> None:
        self.ser.write(f"setHeaterPower({no},{power})".encode())
        self.check_response()

    @skip_if_sim()
    def set_control_voltage(self, voltage: float) -> None:
        self.ser.write(f"setVoltage({voltage})".encode())
        self.check_response()
        
    @skip_if_sim()
    def set_control_current(self, ma: float) -> None:
        self.ser.write(f"setCurrent({ma})".encode())
        self.check_response()

    @skip_if_sim()
    def set_sensor_settings(self, gain: int, atime: int, astep: int) -> None:
        self.ser.write(f"changeSettings({gain},{atime},{astep})".encode())
        self.check_response()

    @skip_if_sim()
    def set_leds_on_during_measurements(self, mode: bool = False) -> None:
        self.ser.write(f"changeLedMode({1 if mode else 0})".encode())
        self.check_response()



       
        
        
    