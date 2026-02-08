#ifndef ANALOG_OUT_H
#define ANALOG_OUT_H

#include <Arduino.h>

// ==== Board pin mapping ====
// SPI-style interface to DAC8760
// NOTE: DAC8760 uses "LATCH" instead of CS. A rising edge after 24 SCLKs latches the frame.
// We'll emulate this with CS-style LOW during frame, then HIGH pulse after.

#define PIN_DAC_LATCH GPIO_NUM_34
#define PIN_DAC_MOSI GPIO_NUM_35
#define PIN_DAC_SCLK GPIO_NUM_36
#define PIN_DAC_MISO GPIO_NUM_37

// Control / diagnostics
#define PIN_DAC_CLR GPIO_NUM_12

// ===== Status structure pulled from DAC status register (Table 8-23) =====
// DB4 CRC-FLT : SPI CRC error
// DB3 WD-FLT  : watchdog timeout
// DB2 I-FLT   : load fault (open circuit / compliance violation on IOUT)
// DB1 SR-ON   : slewing in progress
// DB0 T-FLT   : overtemp (>142°C)
struct DACStatus {
    bool crcFault;
    bool watchdogFault;
    bool loadFault;
    bool slewActive;
    bool overTemp;
    uint16_t raw; // full 16-bit status word for debugging
};

namespace AnalogOut {

    // Call once at startup.
    // - Sets pinMode on LATCH/MOSI/MISO/SCLK/CLR/ALARM
    // - Brings interface to a safe known state:
    //   * CLR low (not forcing clear)
    //   * LATCH high (idle)
    //   * Output disabled (OUTEN=0)
    //   * Configuration register = 0x0000 (watchdog disabled, etc.)
    void init();

    // Put DAC in high-Z (OUTEN = 0). Range is set to 0-10V by default but OUTEN=0 means VOUT/IOUT Hi-Z.
    void disableOutput();

    // ----- Main setters -----

    // Drive the current output (IOUT pin) in the 0 mA → 20 mA range.
    // Automatically:
    //   * programs Control Register: RANGE=110b (0-20mA), OUTEN=1
    //   * writes the DAC code corresponding to `milliamps`
    //
    // milliamps is clamped to [0.0, 20.0]
    // returns true on success
    bool setCurrent_mA(float milliamps);

    // Drive the voltage output (VOUT pin) in the 0 V → 10 V range.
    // Automatically:
    //   * programs Control Register: RANGE=001b (0-10V), OUTEN=1
    //   * writes the DAC code corresponding to `volts`
    //
    // volts is clamped to [0.0, 10.0]
    // returns true on success
    bool setVoltage_V(float volts);

    // ----- Housekeeping / safety -----

    // Assert or deassert CLR.
    // CLR high forces output to a defined safe level (0 V / bottom of range)
    // CLR low returns control to normal SPI-updated code.
    void assertCLR(bool enableHigh);

    // Read full DAC status register over SPI and decode it.
    // Also usable even if ALARM isn't active, for polling.
    // returns true if SPI read succeeded.
    bool readStatus(DACStatus &outStatus);

    // Software reset: writes 0x56 with RESET=1.
    // WARNING: This resets registers and clears alarms, and disables outputs.
    void softwareReset();

} // namespace AnalogOut

#endif // ANALOG_OUT_H
