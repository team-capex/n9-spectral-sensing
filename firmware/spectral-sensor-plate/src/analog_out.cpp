#include "analog_out.h"

// ---------------------------
// Low-level bitbang utilities
// ---------------------------
//
// SPI mode 0 behavior:
//  - SCLK idle LOW
//  - Data (MOSI) is latched by DAC on SCLK rising edge
//  - DAC shifts SDO out on SCLK falling edge, so we sample MISO after we drive SCLK HIGH
//
// Frame format is always 24 bits:
//   [ADDR (8 bits, MSB first)] [DATA (16 bits, MSB first)]
// After exactly 24 SCLK pulses, we toggle LATCH HIGH, then LOW again.
// Ref: DAC8760 Section 8.5.1 SPI, Table 8-12, Figure 7-1. :contentReference[oaicite:9]{index=9}

static inline void setLatchLow()  { digitalWrite(PIN_DAC_LATCH, LOW);  }
static inline void pulseLatch()   {
    // rising edge latches the 24-bit frame internally
    digitalWrite(PIN_DAC_LATCH, HIGH);
    // short hold; even a few ns spec, but we'll give a couple of cycles
    delayMicroseconds(1);
    digitalWrite(PIN_DAC_LATCH, LOW);
}

static uint16_t spiTransferFrame(uint8_t addr, uint16_t data, bool captureMISO)
{
    uint32_t frame = ((uint32_t)addr << 16) | (uint32_t)data;

    uint16_t misoWord = 0;

    // chip-select style active LOW during shift
    setLatchLow();

    // shift out 24 bits, MSB first (bit 23 down to 0)
    for (int bit = 23; bit >= 0; --bit) {
        // drive MOSI
        uint8_t outBit = (frame >> bit) & 0x01;
        digitalWrite(PIN_DAC_MOSI, outBit ? HIGH : LOW);

        // clock HIGH
        digitalWrite(PIN_DAC_SCLK, HIGH);

        // sample MISO on rising edge (data valid for previous falling edge)
        misoWord <<= 1;
        if (captureMISO) {
            int inBit = digitalRead(PIN_DAC_MISO);
            if (inBit) misoWord |= 0x0001;
        }

        // clock LOW
        digitalWrite(PIN_DAC_SCLK, LOW);
    }

    // latch frame into target register on rising edge of LATCH
    pulseLatch();

    return misoWord;
}

// Write any register (or DAC data) with a single frame
static void dacSpiWrite(uint8_t addr, uint16_t word)
{
    // captureMISO = false, we don't care about SDO during a write
    spiTransferFrame(addr, word, false);
}

// Readback helper:
// Per Figure 7-2: do a "read command" frame (addr=0x02) with 16-bit data containing
// the read address code (Table 8-15), then immediately send a NOP (addr=0x00)
// frame while clocking out the response on MISO. :contentReference[oaicite:10]{index=10}
static uint16_t dacReadRegister(uint8_t readAddr6bits)
{
    // First frame: issue read request
    uint16_t requestData = (uint16_t)(readAddr6bits & 0x3F); // bits5:0 = register code
    spiTransferFrame(0x02, requestData, false);

    // Second frame: NOP while capturing MISO -> returns the addressed register
    uint16_t result = spiTransferFrame(0x00, 0x0000, true);

    return result;
}

// ---------------------------
// Register word builder utils
// ---------------------------
//
// CONTROL REGISTER (addr 0x55, Table 8-17) bits: :contentReference[oaicite:11]{index=11}
// DB15 CLRSEL
// DB14 OVR
// DB13 REXT
// DB12 OUTEN
// DB11:DB8 SRCLK[3:0]
// DB7:DB5  SRSTEP[2:0]
// DB4      SREN
// DB3      Reserved (must be 0)
// DB2:DB0  RANGE[2:0]
//
// RANGE codes for normal (non-dual) mode, Table 8-7: :contentReference[oaicite:12]{index=12}
// 000 = 0-5V
// 001 = 0-10V
// 010 = ±5V
// 011 = ±10V
// 100 = not allowed
// 101 = 4-20mA
// 110 = 0-20mA
// 111 = 0-24mA
//
// We'll keep:
//  - CLRSEL=0 (clear -> 0V / low-end)
//  - OVR=0 (no 10% overrange)
//  - REXT=0 (assume internal RSET is used for current scaling)
//  - OUTEN=0 or 1 depending on enable
//  - Slew disabled (SREN=0, SRCLK/SRSTEP=0)
//  - RANGE according to mode

static uint16_t buildControlWord(uint8_t rangeBits, bool outEnable)
{
    uint16_t w = 0x0000;

    // DB12 OUTEN:
    if (outEnable) {
        w |= (1u << 12);
    }

    // RANGE[2:0] => DB2:DB0
    w |= (rangeBits & 0x07);

    // All other bits (CLRSEL, OVR, REXT, slew stuff) left 0 for now.
    return w;
}

// CONFIG REGISTER (addr 0x57, Table 8-18) bits: :contentReference[oaicite:13]{index=13}
// DB15:DB11 Reserved = 0
// DB10:DB9  IOUT_RANGE (used only in dual-output mode)
// DB8       DUAL_OUTEN
// DB7       APD
// DB6       Reserved = 0
// DB5       CALEN
// DB4       HARTEN
// DB3       CRCEN
// DB2       WDEN
// DB1:DB0   WDPD[1:0]
//
// We'll default to 0x0000: watchdog disabled, dual-output disabled, etc.

static const uint16_t DAC_CONFIG_DEFAULT = 0x0000;

// ---------------------------
// Public API
// ---------------------------

void AnalogOut::init()
{
    // Setup pins
    pinMode(PIN_DAC_LATCH, OUTPUT);
    pinMode(PIN_DAC_MOSI,  OUTPUT);
    pinMode(PIN_DAC_SCLK,  OUTPUT);
    pinMode(PIN_DAC_MISO,  INPUT);        // DAC drives SDO (MISO to us)
    pinMode(PIN_DAC_CLR,   OUTPUT);

    // Safe idle levels
    digitalWrite(PIN_DAC_SCLK, LOW);      // SPI mode 0 idle low
    digitalWrite(PIN_DAC_MOSI, LOW);
    digitalWrite(PIN_DAC_LATCH, HIGH);    // idle HIGH after last pulseLatch()
    digitalWrite(PIN_DAC_CLR, LOW);       // do not force clear unless requested

    // 1) Write config register = 0x0000 (watchdog off, dual-output off, etc.)
    dacSpiWrite(0x57, DAC_CONFIG_DEFAULT);

    // 2) Disable outputs: OUTEN=0, RANGE=001 (arbitrary sane voltage range)
    uint16_t ctrlSafe = buildControlWord(/*rangeBits=*/0b001, /*outEnable=*/false);
    dacSpiWrite(0x55, ctrlSafe);

    // 3) Optionally write DAC data 0x0000 to be explicit
    dacSpiWrite(0x01, 0x0000);
}

void AnalogOut::disableOutput()
{
    // OUTEN=0, keep some defined range (0-10V)
    uint16_t ctrl = buildControlWord(/*rangeBits=*/0b001, /*outEnable=*/false);
    dacSpiWrite(0x55, ctrl);
}

// Helper: write DAC code (16-bit) AFTER programming control register.
// This assumes OUTEN=1 and RANGE already match what you want.
static void writeDacCode(uint16_t code)
{
    dacSpiWrite(0x01, code);
}

// Current output helper
// For 0-20mA (RANGE=110b), equation (0mA→20mA):
// Iout = 20mA * CODE / 2^N  => CODE = Iout/20mA * 65535 for 16-bit DAC8760. :contentReference[oaicite:14]{index=14}
bool AnalogOut::setCurrent_mA(float milliamps)
{
    if (milliamps < 0.0f)  milliamps = 0.0f;
    if (milliamps > 20.0f) milliamps = 20.0f;

    // Program control register to 0-20mA range, OUTEN=1
    // RANGE = 0b110 (0-20mA), OUTEN=1 -> buildControlWord(0b110, true)
    uint16_t ctrl = buildControlWord(0b110, true);
    dacSpiWrite(0x55, ctrl);

    // Convert mA -> DAC code
    // scale = 65535 / 20.0
    float scale = 65535.0f / 20.0f;
    uint32_t code = (uint32_t)roundf(milliamps * scale);
    if (code > 0xFFFFu) code = 0xFFFFu;

    writeDacCode((uint16_t)code);

    return true;
}

// Voltage output helper
// For 0-10V (RANGE=001b), unipolar mode eqn:
// Vout = (CODE / 2^N) * VREF * GAIN
// For this range, GAIN=2 and VREF=5V, so Vout = CODE * (5*2)/65535 ≈ CODE * 10/65535.
// Rearranged: CODE = Vout * 65535 / 10.0. :contentReference[oaicite:15]{index=15}
bool AnalogOut::setVoltage_V(float volts)
{
    if (volts < 0.0f)  volts = 0.0f;
    if (volts > 10.0f) volts = 10.0f;

    // Program control register to 0-10V range, OUTEN=1
    // RANGE = 0b001 (0-10V), OUTEN=1
    uint16_t ctrl = buildControlWord(0b001, true);
    dacSpiWrite(0x55, ctrl);

    // Convert volts -> DAC code
    // scale = 65535 / 10.0
    float scale = 65535.0f / 10.0f;
    uint32_t code = (uint32_t)roundf(volts * scale);
    if (code > 0xFFFFu) code = 0xFFFFu;

    writeDacCode((uint16_t)code);

    return true;
}

// ----- Safety / diagnostics -----

void AnalogOut::assertCLR(bool enableHigh)
{
    digitalWrite(PIN_DAC_CLR, enableHigh ? HIGH : LOW);
    // Note: While CLR is held HIGH, the DAC output is forced to the defined clear level
    // (0V or low-end of range if current mode). Releasing CLR LOW keeps that level
    // until you send a new LATCH pulse with data, per datasheet Section 8.3.6. :contentReference[oaicite:16]{index=16}
}

bool AnalogOut::readStatus(DACStatus &outStatus)
{
    // Status register read address code:
    // Table 8-15 says "XX XX00" => last 2 bits 00, so 0x00 is valid. :contentReference[oaicite:18]{index=18}
    uint16_t raw = dacReadRegister(0x00);

    outStatus.raw           = raw;
    outStatus.crcFault      = (raw & (1u << 4)) != 0;
    outStatus.watchdogFault = (raw & (1u << 3)) != 0;
    outStatus.loadFault     = (raw & (1u << 2)) != 0; // I-FLT = open circuit / compliance violation on IOUT load
    outStatus.slewActive    = (raw & (1u << 1)) != 0; // SR-ON
    outStatus.overTemp      = (raw & (1u << 0)) != 0; // T-FLT = die > ~142°C
    return true;
}

void AnalogOut::softwareReset()
{
    // Reset register (addr 0x56), DB0 = 1 triggers software reset of all regs and clears ALARM flags.
    // After reset, outputs are disabled and registers return to POR defaults. :contentReference[oaicite:19]{index=19}
    dacSpiWrite(0x56, 0x0001);

    // Give it a moment to settle
    delay(5);

    // Re-init safe state after reset
    init();
}