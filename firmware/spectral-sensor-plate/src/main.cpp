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

String action;
int req_index, req_gain, req_atime, req_astep;
float req_power, req_voltage, req_current;

// ------ Prototypes ------
void setHeaterPower(int heater, int power);

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

  Serial.println("# Ready!");
}

// ---------------- Loop ----------------
void loop() {
  delay(100);
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
        Serial.printf("[DATA] F1=%u,F2=%u,F3=%u,F4=%u,F5=%u,F6=%u,F7=%u,F8=%u,CLR=%u,NIR=%u\n",
                      d.F1, d.F2, d.F3, d.F4, d.F5, d.F6, d.F7, d.F8, d.CLEAR, d.NIR);
      } else {
        Serial.println("Read failed.");
      }
      
      Serial.println("#");
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