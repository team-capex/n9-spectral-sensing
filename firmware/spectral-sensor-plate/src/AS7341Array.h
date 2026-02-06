#pragma once
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_AS7341.h>

// ============================================================
// Hard-coded pinout
// ============================================================
#define RESET1 GPIO_NUM_16 // Mux #1 reset
#define RESET2 GPIO_NUM_15 // Mux #2 reset
#define SDA_PIN GPIO_NUM_8
#define SCL_PIN GPIO_NUM_9

// ============================================================
// Hard-coded I2C addresses
// ============================================================
static const uint8_t MUX1_ADDR = 0x70;
static const uint8_t MUX2_ADDR = 0x71;
static const uint8_t AS7341_ADDR = 0x39; // fixed for all sensors
// Optional: if you want I2C to run faster (AS7341 + mux usually fine at 400k)
static const uint32_t I2C_FREQ = 400000;

// ============================================================
// Hard-coded AS7341 settings (as requested)
// ============================================================
static const as7341_gain_t AS_GAIN = AS7341_GAIN_1X;
static const uint8_t AS_ATIME = 29;
static const uint16_t AS_ASTEP = 599;

// LED flash behavior (visual scan feedback)
// "Low current" here means: LED on briefly; Adafruit lib doesn't provide
// direct current setting for arbitrary boards, but this is typically safe.
// ============================================================
static const uint16_t LED_FLASH_MS = 50;

// ============================================================
// Data container returned to higher-level code
// ============================================================
struct AS7341SpectralData {
  // 10-channel reading: F1..F8 + Clear + NIR
  uint16_t F1;
  uint16_t F2;
  uint16_t F3;
  uint16_t F4;
  uint16_t F5;
  uint16_t F6;
  uint16_t F7;
  uint16_t F8;
  uint16_t CLEAR;
  uint16_t NIR;
};

// ============================================================
// Simple driver for 16x AS7341 behind 2x TCA9548A
// ============================================================
class AS7341Array {
public:
  AS7341Array() = default;

  // Initializes Wire, resets muxes, verifies mux presence.
  // Does NOT scan all sensors (by design).
  bool begin();

  // Selects mux+channel for sensor index (1..16).
  // Guarantees all other channels are off first.
  bool selectSensor(uint8_t sensorIndex);

  // Reads one sensor: flashes onboard LED for 50ms, LED off, then reads.
  // Returns raw band intensities (no normalization).
  bool readSpectral(uint8_t sensorIndex, AS7341SpectralData &out);

  // Turns OFF all channels on both muxes (safe idle state).
  void closeAll();

private:
  // Single Adafruit object reused for all sensors (address always 0x39).
  Adafruit_AS7341 _as7341;

  // Tracks currently-open path (for sanity/protection).
  bool _channelOpen = false;
  uint8_t _activeMuxAddr = 0;
  uint8_t _activeChannel = 0;

private:
  // Low-level helpers
  bool resetMuxes();
  bool muxWriteChannel(uint8_t muxAddr, uint8_t channel); // channel 0..7
  bool muxDisableAll(uint8_t muxAddr);
  bool pingI2C(uint8_t addr);

  // Mapping: sensorIndex (1..16) -> muxAddr + channel
  bool mapSensorToMux(uint8_t sensorIndex, uint8_t &muxAddrOut, uint8_t &channelOut);

  // Initialize AS7341 on currently-selected channel
  bool initAS7341OnActiveChannel();

  // LED flash + ensure off during measurement
  void flashLedBeforeMeasurement();
  void ensureLedOff();
};
