#pragma once
#include <Arduino.h>

// Forward declaration avoids leaking Adafruit types to users of the header.
enum LedColor : uint8_t {
  BRIGHT_WHITE,
  BLUE,
  PURPLE,
  RED,
  GREEN,
  YELLOW,
  ORANGE,
  OFF
};

// Simple wrapper that owns a NeoPixel strip and provides:
// - non-blocking spinner (run() each loop)
// - pulse() blocking fade in/out
// - spinnerTimer() which runs spinner for N seconds then does a pulse
class LedAnimations {
public:
  // Setup the strip and spinner layout.
  // - pin: GPIO for the NeoPixel data
  // - numPixels: total count
  // - centerIdx: index of the center LED
  // - outerIdx: pointer to array of outer ring indices (clockwise)
  // - outerCount: number of indices in outerIdx
  // - spinColor: color used for the spinner
  void begin(uint8_t pin,
             uint16_t numPixels,
             uint8_t centerIdx,
             const uint8_t* outerIdx,
             uint8_t outerCount,
             LedColor spinColor);

  // Call frequently for non-blocking spinner updates.
  void run();

  // Blocking pulse fade for status indications.
  void pulse(LedColor color, int pulses = 1, int stepDelay = 5);

  // Run spinner for `seconds`, then overwrite with a pulse of `pulseColor`.
  void spinnerTimer(float seconds, LedColor pulseColor = ORANGE);

private:
  // Opaque impl to keep header light
  struct Impl;
  Impl* impl_ = nullptr;
};
