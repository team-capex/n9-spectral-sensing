#include <Arduino.h>

#include "AS7341Array.h"
#include "analog_out.h"

AS7341Array sensors;

// ---------------- Pinout ----------------
#define RESET1 GPIO_NUM_16 // For Mux #1
#define RESET2 GPIO_NUM_15 // For Mux #2

#define HEATER1 GPIO_NUM_40 
#define HEATER2 GPIO_NUM_39 

#define SDA GPIO_NUM_8
#define SCL GPIO_NUM_9

#define USER_BUTTON GPIO_NUM_48

// Mux Mapping
// Mux #1 0x70
// Channel: 0, 1, 2, 3, 4, 5, 6, 7
// Sensor#: 8, 6, 4, 2, 1, 3, 5, 7

// Mux #2 0x71
// Channel: 0, 1, 2, 3, 4, 5, 6, 7
// Sensor#: 16, 14, 12, 10, 9, 11, 13, 15

// ---------------- NTC ----------------
// Calibrated thermistor parameters (MOLEX 2152722603):
// R0 at T0 (Kelvin), and Beta in Kelvin.
struct ThermistorBeta {
    float invT0;   // 1/T0
    float invB;    // 1/B
    float lnR0;    // ln(R0)
};

constexpr float R0   = 10000.0f;
constexpr float T0_K = 298.15f;    // 25°C
constexpr float B    = 3892.0f;

// Build once (constexpr) from your datasheet values.
constexpr ThermistorBeta make_thermistor(float R0, float T0_K, float B) {
    return ThermistorBeta{
        1.0f / T0_K,
        1.0f / B,
        std::log(R0)
    };
}

constexpr auto TH = make_thermistor(R0, T0_K, B);

constexpr uint32_t ADC_MAX = 4095;   // 12-bit ADC
constexpr float Rp = 10000.0f;       // 10k pull-up

// ---------------- NTC ----------------

String action;
int req_index, req_gain, req_atime, req_astep;
float req_power, req_voltage, req_current;

// ── PID temperature control ──────────────────────────────────────────────────
constexpr float PID_KP           = 8.0f;
constexpr float PID_KI           = 0.05f;
constexpr float PID_KD           = 0.5f;
constexpr float PID_DT_MS        = 500.0f;   // update interval (ms)
constexpr float PID_OUT_MIN      = 0.0f;     // heaters cannot cool
constexpr float PID_OUT_MAX      = 100.0f;
// Anti-windup: clamp integral so KI*integral alone cannot exceed output limits
constexpr float PID_INTEGRAL_MAX = PID_OUT_MAX / PID_KI;

float         pid_target   = NAN;
float         pid_integral = 0.0f;
float         pid_prev_err = 0.0f;
unsigned long pid_last_ms  = 0;

// ------ Prototypes ------
void setHeaterPower(int heater, int power);
void pid_step();
inline float ntc_temp_c_from_resistance(float R_ohm, const ThermistorBeta& th);
inline float ntc_resistance_from_adc(uint32_t adc_raw, uint32_t adc_max, float Rp);
float temperature_c(uint32_t adc_raw);
float getProbeTemp(int pin);

// ---------------- Setup ----------------
void setup() {
  Serial.begin(115200);

  ledcSetup(0, 1000, 10);
  ledcAttachPin(HEATER1, 0);

  ledcSetup(1, 1000, 10);
  ledcAttachPin(HEATER2, 1);

  if (!sensors.begin()) {
    Serial.println("Failed to init muxes/I2C.");
    while (1) delay(100);
  }

  AnalogOut::init();

  Serial.println("**Available functions**");

  Serial.println("Signals:");
  Serial.println("setHeaterPower(int heater, int power)");
  Serial.println("setVoltage(float volts) 0-10V");
  Serial.println("setCurrent(float mA) 0-20mA");

  Serial.println("Sensors:");
  Serial.println("readSensor(int sensor)");
  Serial.println("fullShutdown()");
  Serial.println("wakeAll()");

  Serial.println("getTemperature(int pin)");
  Serial.println("setTemperatureTarget(float celsius)");
  Serial.println("clearTemperatureTarget()");
  Serial.println("# Ready!");
}

// ---------------- Loop ----------------
void loop() {
  delay(100);
  pid_step();
  AS7341SpectralData d;

  // Wait until data received from PC, via Serial (USB)
  if (Serial.available() > 0) {
    // data structure to receive = action(var1, var2..)

    // Read until open bracket to extract action, continue based on which action was requested
    action = Serial.readStringUntil('(');

    if (action == "setHeaterPower") {
      req_index = Serial.readStringUntil(',').toInt();
      req_power = Serial.readStringUntil(')').toFloat();

      setHeaterPower(req_index, req_power);
      Serial.println("#");
    }
    else if (action == "readSensor") {
      req_index = Serial.readStringUntil(')').toInt();

      if (sensors.readSpectral(req_index, d)) {
        Serial.printf("[DATA] F1=%u,F2=%u,F3=%u,F4=%u,F5=%u,F6=%u,F7=%u,F8=%u,CLR=%u,NIR=%u,SENSOR=%u\n",
                      d.F1, d.F2, d.F3, d.F4, d.F5, d.F6, d.F7, d.F8, d.CLEAR, d.NIR, req_index);
      } else {
        Serial.println("Read failed.");
      }
    }
    else if (action == "setVoltage") {
      req_voltage = Serial.readStringUntil(')').toFloat();

      if (AnalogOut::setVoltage_V(req_voltage)) {Serial.println("#");}
      else {Serial.println("Voltage set failed.");}
    }
    else if (action == "setCurrent") {
      req_current = Serial.readStringUntil(')').toFloat();

      if (AnalogOut::setCurrent_mA(req_current)) {Serial.println("#");}
      else {Serial.println("Current set failed.");}
    }
    else if (action == "closeMuxes") {
      (void)Serial.readStringUntil(')');
      
      sensors.closeAll();
      Serial.println("#");
    }
    else if (action == "changeSettings") {
      req_gain = Serial.readStringUntil(',').toInt();
      req_atime = Serial.readStringUntil(',').toInt();
      req_astep = Serial.readStringUntil(')').toInt();
      
      sensors.setSensorSettings(req_gain, req_atime, req_astep);
      Serial.println("#");
    }
    else if (action == "changeLedMode") {
      req_index = Serial.readStringUntil(')').toInt();
      if (req_index == 0) {
        sensors.setLedMode(false);
      }
      else if (req_index == 1) {
        sensors.setLedMode(true);
      }
      Serial.println("#");
    }
    else if (action == "getTemperature") {
      req_index = Serial.readStringUntil(')').toInt();
      Serial.println(getProbeTemp(req_index));
    }
    else if (action == "setTemperatureTarget") {
      float target  = Serial.readStringUntil(')').toFloat();
      pid_target    = target;
      pid_integral  = 0.0f;   // reset integral on new setpoint
      pid_prev_err  = 0.0f;
      pid_last_ms   = millis();
      Serial.println("#");
    }
    else if (action == "clearTemperatureTarget") {
      (void)Serial.readStringUntil(')');
      pid_target    = NAN;
      pid_integral  = 0.0f;
      pid_prev_err  = 0.0f;
      setHeaterPower(1, 0);
      setHeaterPower(2, 0);
      Serial.println("#");
    }
    else {
      Serial.println("UNKNOWN COMMAND");
    }
  }
}

// ---------------- Implementation ----------------

void setHeaterPower(int heater, int power) {
  power = constrain(power, 0, 100);

  if (heater < 1 || heater > 2) {
    Serial.println("Error: Invalid heater index. Must be 1 or 2.");
    return;
  }

  ledcWrite(heater-1, map(power, 0, 100, 0, 1023));
}

// Fast path: R in ohms -> Temperature in Celsius.
inline float ntc_temp_c_from_resistance(float R_ohm, const ThermistorBeta& th) {
    // 1/T = 1/T0 + (1/B)*ln(R/R0)  ->  invT = invT0 + invB*(lnR - lnR0)
    const float lnR = std::log(R_ohm);
    const float invT = th.invT0 + th.invB * (lnR - th.lnR0);
    const float T_K  = 1.0f / invT;        // Kelvin
    return T_K - 273.15f;                  // Celsius
}

inline float ntc_resistance_from_adc(uint32_t adc_raw, uint32_t adc_max, float Rp) {
    // Vout/Vref = adc_raw/adc_max
    // Rntc = Rp * (adc_raw) / (adc_max - adc_raw)
    const float num = static_cast<float>(adc_raw);
    const float den = static_cast<float>(adc_max) - num;
    // Clamp to avoid div-by-zero at rails.
    const float safe_den = (den <= 0.5f) ? 0.5f : den;
    return Rp * (num / safe_den);
}

float temperature_c(uint32_t adc_raw) {
    const float R = ntc_resistance_from_adc(adc_raw, ADC_MAX, Rp);
    return ntc_temp_c_from_resistance(R, TH);
}

float getProbeTemp(int pin) {
  if (pin < 1 || pin > 5 || pin == 3) {
    Serial.println("Error: Invalid probe pin index. Must be GPIO 1, 2, 4 or 5.");
    return -99;
  }

  return temperature_c(analogRead(pin));
}

void pid_step() {
    if (isnan(pid_target)) return;

    unsigned long now = millis();
    if ((now - pid_last_ms) < (unsigned long)PID_DT_MS) return;
    float dt = (now - pid_last_ms) / 1000.0f;
    pid_last_ms = now;

    // Read NTC pins 1 and 2 directly to avoid Serial side-effects from getProbeTemp()
    float avg_temp = (temperature_c(analogRead(1)) + temperature_c(analogRead(2))) * 0.5f;

    float error      = pid_target - avg_temp;
    pid_integral    += error * dt;
    pid_integral     = constrain(pid_integral, -PID_INTEGRAL_MAX, PID_INTEGRAL_MAX);
    float derivative = (error - pid_prev_err) / dt;
    pid_prev_err     = error;

    int duty = (int)constrain(
        PID_KP * error + PID_KI * pid_integral + PID_KD * derivative,
        PID_OUT_MIN, PID_OUT_MAX
    );
    setHeaterPower(1, duty);
    setHeaterPower(2, duty);
}
