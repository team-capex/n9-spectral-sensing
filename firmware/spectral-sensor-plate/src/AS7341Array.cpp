#include "AS7341Array.h"

// ------------------------------------------------------------
// Your mapping (from prompt) expressed as lookup tables.
// Index is mux channel 0..7, value is sensor index.
// We invert this mapping at runtime in mapSensorToMux().
// ------------------------------------------------------------

// Mux #1 (0x70): ch 0..7 -> sensor 8,6,4,2,1,3,5,7
static const uint8_t MUX1_CH_TO_SENSOR[8] = {8, 6, 4, 2, 1, 3, 5, 7};

// Mux #2 (0x71): ch 0..7 -> sensor 16,14,12,10,9,11,13,15
static const uint8_t MUX2_CH_TO_SENSOR[8] = {16, 14, 12, 10, 9, 11, 13, 15};

bool AS7341Array::begin() {
  // Setup I2C on specified pins
  Wire.begin((int)SDA_PIN, (int)SCL_PIN);
  Wire.setClock(I2C_FREQ);

  // Setup mux reset pins
  pinMode((int)RESET1, OUTPUT);
  pinMode((int)RESET2, OUTPUT);

  digitalWrite((int)RESET1, LOW);
  digitalWrite((int)RESET2, LOW);

  if (!resetMuxes()) {
    return false;
  }

  // Verify muxes are present
  if (!pingI2C(MUX1_ADDR)) return false;
  if (!pingI2C(MUX2_ADDR)) return false;

  // Start in safe state: all channels off
  closeAll();

  // Show board is active
  loopLEDs();

  return true;
}

bool AS7341Array::resetMuxes() {
  // Active-low reset is typical; but your hardware might differ.
  // Most TCA9548A boards: RESET low = reset, high = run.
  // We'll pulse low briefly on each reset pin.
  digitalWrite((int)RESET1, HIGH);
  digitalWrite((int)RESET2, HIGH);
  delay(5);
  digitalWrite((int)RESET1, LOW);
  digitalWrite((int)RESET2, LOW);
  delay(5);
  return true;
}

bool AS7341Array::pingI2C(uint8_t addr) {
  Wire.beginTransmission(addr);
  uint8_t err = Wire.endTransmission();
  return (err == 0);
}

void AS7341Array::closeAll() {
  muxDisableAll(MUX1_ADDR);
  muxDisableAll(MUX2_ADDR);
  _channelOpen = false;
  _activeMuxAddr = 0;
  _activeChannel = 0;
}

bool AS7341Array::muxDisableAll(uint8_t muxAddr) {
  Wire.beginTransmission(muxAddr);
  Wire.write((uint8_t)0x00); // no channels enabled
  return (Wire.endTransmission() == 0);
}

bool AS7341Array::muxWriteChannel(uint8_t muxAddr, uint8_t channel) {
  if (channel > 7) return false;

  // Safety: disable ALL first so only one channel is ever open across both muxes
  closeAll();

  // Enable a single channel bit
  Wire.beginTransmission(muxAddr);
  Wire.write((uint8_t)(1U << channel));
  if (Wire.endTransmission() != 0) {
    // Failed to write channel selection
    closeAll();
    return false;
  }

  _channelOpen = true;
  _activeMuxAddr = muxAddr;
  _activeChannel = channel;
  delay(1); // small settle time
  return true;
}

bool AS7341Array::mapSensorToMux(uint8_t sensorIndex, uint8_t &muxAddrOut, uint8_t &channelOut) {
  if (sensorIndex < 1 || sensorIndex > 16) return false;

  // Search mux #1 mapping
  for (uint8_t ch = 0; ch < 8; ch++) {
    if (MUX1_CH_TO_SENSOR[ch] == sensorIndex) {
      muxAddrOut = MUX1_ADDR;
      channelOut = ch;
      return true;
    }
  }

  // Search mux #2 mapping
  for (uint8_t ch = 0; ch < 8; ch++) {
    if (MUX2_CH_TO_SENSOR[ch] == sensorIndex) {
      muxAddrOut = MUX2_ADDR;
      channelOut = ch;
      return true;
    }
  }

  return false; // should never happen if 1..16 are fully mapped
}

bool AS7341Array::selectSensor(uint8_t sensorIndex) {
  uint8_t muxAddr = 0;
  uint8_t channel = 0;

  if (!mapSensorToMux(sensorIndex, muxAddr, channel)) {
    return false;
  }

  // Open the channel (and close everything else first)
  if (!muxWriteChannel(muxAddr, channel)) {
    return false;
  }

  return true;
}

bool AS7341Array::initAS7341OnActiveChannel() {
  // We assume the mux channel is already selected and stable.
  // Initialize Adafruit object at address 0x39.
  // NOTE: Calling begin() repeatedly is not super efficient, but it's simple,
  // robust for student code, and avoids state confusion across sensors.
  if (!_as7341.begin(AS7341_ADDR, &Wire)) {
    return false;
  }

  // Apply requested fixed settings
  _as7341.setATIME(AS_ATIME);
  _as7341.setASTEP(AS_ASTEP);
  _as7341.setGain(AS_GAIN);
  _as7341.setLEDCurrent(LED_CURRENT);

  // Ensure LED off in idle
  ensureLedOff();

  return true;
}

void AS7341Array::flashLedBeforeMeasurement() {
  // Visual indication that this sensor is about to be read.
  // Turn on, wait 50ms, then off BEFORE we actually measure.
  // (Exact LED control depends on board wiring; Adafruit lib supports this on their breakout.)
  _as7341.enableLED(true);
  delay(LED_FLASH_MS);
  _as7341.enableLED(false);
}

void AS7341Array::ensureLedOff() {
  _as7341.enableLED(false);
}

bool AS7341Array::readSpectral(uint8_t sensorIndex, AS7341SpectralData &out) {
  // 1) Select the requested sensor (opens only one channel total)
  if (!selectSensor(sensorIndex)) {
    return false;
  }

  // 2) Initialize the AS7341 on this channel
  if (!initAS7341OnActiveChannel()) {
    closeAll();
    return false;
  }

  // 3) Flash LED briefly BEFORE measurement, then keep it OFF during measurement
  flashLedBeforeMeasurement();
  ensureLedOff();

  // 4) Read all 10 channels: F1..F8 + CLEAR + NIR
  // Adafruit library provides readAllChannels() which fills an internal buffer,
  // then you fetch each channel value via getChannel().
  if (!_as7341.readAllChannels()) {
    closeAll();
    return false;
  }

  out.F1    = _as7341.getChannel(AS7341_CHANNEL_415nm_F1);
  out.F2    = _as7341.getChannel(AS7341_CHANNEL_445nm_F2);
  out.F3    = _as7341.getChannel(AS7341_CHANNEL_480nm_F3);
  out.F4    = _as7341.getChannel(AS7341_CHANNEL_515nm_F4);
  out.F5    = _as7341.getChannel(AS7341_CHANNEL_555nm_F5);
  out.F6    = _as7341.getChannel(AS7341_CHANNEL_590nm_F6);
  out.F7    = _as7341.getChannel(AS7341_CHANNEL_630nm_F7);
  out.F8    = _as7341.getChannel(AS7341_CHANNEL_680nm_F8);
  out.CLEAR = _as7341.getChannel(AS7341_CHANNEL_CLEAR);
  out.NIR   = _as7341.getChannel(AS7341_CHANNEL_NIR);

  // 5) Leave system in safe state (optional but recommended)
  // If you want to keep the channel open for repeated reads, remove this.
  closeAll();

  return true;
}

void AS7341Array::loopLEDs() {
  for (int i=1; i<=16; i++) {
    // 1) Select the requested sensor (opens only one channel total)
    if (!selectSensor(i)) {
      return;
    }

    // 2) Initialize the AS7341 on this channel
    if (!initAS7341OnActiveChannel()) {
      closeAll();
      return;
    }

    // 3) Turn LED ON
    _as7341.enableLED(true);
    delay(LED_FLASH_MS);
  }

  for (int i=1; i<=16; i++) {
    // 1) Select the requested sensor (opens only one channel total)
    if (!selectSensor(i)) {
      return;
    }

    // 2) Initialize the AS7341 on this channel
    if (!initAS7341OnActiveChannel()) {
      closeAll();
      return;
    }

    // 3) Turn LED OFF
    _as7341.enableLED(false);
    delay(LED_FLASH_MS);
  }

  closeAll();
}

void AS7341Array::setSensorSettings(uint8_t gain, uint8_t atime, uint8_t astep) {
  switch (gain) {
    case 1:
      AS_GAIN = AS7341_GAIN_1X;
      break;
    case 2:
      AS_GAIN = AS7341_GAIN_2X;
      break;
    case 4:
      AS_GAIN = AS7341_GAIN_4X;
      break;
    case 8:
      AS_GAIN = AS7341_GAIN_8X;
      break;
  }

  if (atime > 1 && atime < 100) {
    AS_ATIME = atime;
  }

  if (astep > 1 && astep < 1000) {
    AS_ASTEP = astep;
  }

}
