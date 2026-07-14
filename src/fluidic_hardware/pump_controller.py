import logging
import time
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

class PumpController:
    def __init__(self, COM: str, baud: int = 115200, sim: bool = False, timeout: float = 60.0,
                 invert_pumps: "list[int] | None" = None):
        self.sim = sim
        self.timeout = timeout
        # Pumps wired with reversed rotation: their volumes are sign-flipped
        # here so positive ml always means "dispense" for every pump.
        self.invert_pumps = set(invert_pumps or [])

        if self.sim:
            logging.info("Simulated connection to pump controller established.")

        else:
            logging.info("Configuring pump controller serial port..")
            self.ser = serial.Serial(
                port=COM,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            self.ser.baudrate = baud
            self.ser.bytesize = 8 
            self.ser.parity = 'N' # No parity
            self.ser.stopbits = 1
            self.ser.timeout = self.timeout

            # Turn ESP ON (active low)
            self.ser.setDTR(False)  # False = inactive = HIGH (because DTR is active-low)
            self.ser.setRTS(False)

            logging.info("Attempting to open pump controller serial port..")

            if self.ser.isOpen() is False:
                self.ser.open()
            else:
                self.ser.close()
                time.sleep(0.05)
                self.ser.open()

            # Give time for controller to wake up
            time.sleep(2)

            # Check connection (blocking)
            if self.check_status():
                logging.info("Serial connection to pump controller established.")

    @skip_if_sim(default_return="0")
    def get_data(self) -> str:
        while self.ser.in_waiting == 0:
            pass

        return self.ser.readline().decode().rstrip().replace("\x00", "")
        
    @skip_if_sim()
    def check_response(self) -> None:
        start = time.time()
        while(time.time() - start < self.timeout):
            data = self.get_data()
            if data is None:
                logging.warning("Timed out waiting for response")
                break
            if '#' in data:
                break
            elif "Unknown command" in data:
                raise RuntimeError("Pump controller failed to recognise command: " + data)
            else:
                logging.info("Response from pump controller: " + data)

    @skip_if_sim()
    def close_ser(self) -> None:
        logging.info("Closing serial connection to pump controller.")
        if self.ser.isOpen():
            self.ser.close()

    @skip_if_sim(default_return = True)
    def check_status(self) -> bool:
        self.ser.write("statusCheck()".encode())
        self.check_response()
        
    @skip_if_sim()
    def display_oled_message(self, message: str) -> None:
        self.ser.write(f"displayMessage({message})".encode())
        self.check_response()

    @skip_if_sim(default_return = 25)
    def get_temperature(self) -> float:
        self.ser.write("getTemperature()".encode())
        return float(self.get_data())
        
    @skip_if_sim(default_return = 50)
    def get_humidity(self) -> float:
        self.ser.write("getHumidity()".encode())
        return float(self.get_data())
        
    @skip_if_sim()
    def stepper_pump(self, pump_no: int, ml: float, flow_rate: float = 0.05, check: bool = True) -> None:
        if pump_no < 0 or pump_no > 4:
            raise ValueError("Incorrect stepper pump index; must be 1 -> 4")

        if pump_no in self.invert_pumps:
            ml = -ml

        self.ser.write(f"singleStepperPump({pump_no},{ml:.3f},{flow_rate:.3f})".encode())
        if check:
            self.check_response()

    @skip_if_sim()
    def multi_stepper_pump(self, ml: list[float], flow_rate: float = 0.05, check: bool = True) -> None:
        if len(ml) != 4:
            raise ValueError("Exactly 4 volumes are required")

        ml = [
            -float(v) if (i + 1) in self.invert_pumps else float(v)
            for i, v in enumerate(ml)
        ]
        args = ",".join(f"{v:.3f}" for v in ml)
        self.ser.write(f"multiStepperPump({args},{flow_rate:.3f})".encode())

        if check:
            self.check_response()

    @skip_if_sim()
    def dc_pump(self, pump_no: int, pwm: float, seconds: float, check: bool) -> None:
        if pump_no < 0 or pump_no > 4:
            raise ValueError("Incorrect dc pump index; must be 1 -> 4")

        self.ser.write(f"transferPump({pump_no},{pwm},{seconds})".encode())
        if check:
            self.check_response()

    @skip_if_sim()
    def emergency_stop(self) -> None:
        """Reset the ESP32 via RTS pin to immediately halt all stepper motors.

        Asserts the active-low EN (enable) pin by driving RTS high, which holds
        the ESP32 in reset and stops all pump motion instantly. After a brief
        delay the reset is released and the controller is allowed to reboot before
        re-checking the connection.

        Safe to call from a finally block — any serial errors are logged but not
        re-raised.
        """
        logging.info("Emergency stop: asserting ESP32 reset via RTS pin ...")
        try:
            self.ser.setRTS(True)   # RTS high → EN pin low → ESP32 held in reset
            time.sleep(0.1)
            self.ser.setRTS(False)  # Release reset
            time.sleep(2.0)         # Wait for ESP32 to reboot
            self.ser.reset_input_buffer()
            if self.check_status():
                logging.info("Pump controller rebooted successfully after emergency stop.")
            else:
                logging.warning("Pump controller did not acknowledge after emergency stop reset.")
        except Exception as exc:
            logging.warning("emergency_stop: error during reset sequence: %s", exc)