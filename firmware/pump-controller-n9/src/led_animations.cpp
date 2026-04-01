#include "led_animations.h"
#include <Adafruit_NeoPixel.h>

namespace {

struct RGB { uint8_t r, g, b; };

static const RGB COLOR_MAP[] = {
  {255, 255, 255},  // BRIGHT_WHITE
  {84, 139, 227},   // BLUE (spinner)
  {189, 84, 227},   // PURPLE
  {227, 84, 84},    // RED
  {84, 227, 125},   // GREEN
  {250, 239, 27},   // YELLOW
  {255, 166, 51},   // ORANGE
  {0, 0, 0}         // OFF
};

struct SpinnerPulse {
  enum State { SPIN } state = SPIN;

  Adafruit_NeoPixel* strip = nullptr;
  uint8_t outer[8];      // enough for your 6-led ring
  uint8_t outerCount = 0;
  uint8_t centerIdx  = 0;

  LedColor spinColor = BLUE;

  // Tuning
  uint16_t stepIntervalMs = 68;
  uint8_t  tailLen        = 3;

  // Internals
  uint8_t head = 0;
  uint32_t tLast = 0;

  static uint8_t tailLevel(uint8_t d) {
    static const uint8_t levels[6] = {255, 140, 60, 25, 10, 4};
    return (d < 6) ? levels[d] : 0;
  }

  static uint32_t mkColor(Adafruit_NeoPixel* s, const RGB& c, uint8_t scale = 255) {
    uint8_t r = (uint16_t)c.r * scale / 255;
    uint8_t g = (uint16_t)c.g * scale / 255;
    uint8_t b = (uint16_t)c.b * scale / 255;
    return s->Color(r, g, b);
  }

  void begin(Adafruit_NeoPixel* s,
             const uint8_t* outerIdx, uint8_t nOuter,
             uint8_t center,
             LedColor spinC)
  {
    strip      = s;
    outerCount = nOuter > 8 ? 8 : nOuter;
    for (uint8_t i = 0; i < outerCount; ++i) outer[i] = outerIdx[i];
    centerIdx  = center;
    spinColor  = spinC;

    head = 0;
    tLast = millis();

    for (uint16_t i = 0; i < strip->numPixels(); ++i) strip->setPixelColor(i, 0);
    strip->show();
  }

  void run() {
    if ((millis() - tLast) < stepIntervalMs) return;
    tLast = millis();

    head = (head + 1) % outerCount;

    // clear ring
    for (uint8_t i = 0; i < outerCount; ++i) strip->setPixelColor(outer[i], 0);

    // head + tail
    for (uint8_t t = 0; t < tailLen; ++t) {
      uint8_t idx = (head + outerCount - t) % outerCount;
      uint8_t lvl = tailLevel(t);
      if (lvl == 0) break;
      strip->setPixelColor(outer[idx], mkColor(strip, COLOR_MAP[spinColor], lvl));
    }

    // center off during spin
    strip->setPixelColor(centerIdx, 0);
    strip->show();
  }
};

struct LedImpl {
  Adafruit_NeoPixel* strip = nullptr;
  SpinnerPulse       anim;

  void begin(uint8_t pin,
             uint16_t n,
             uint8_t centerIdx,
             const uint8_t* outerIdx,
             uint8_t outerCount,
             LedColor spinColor)
  {
    strip = new Adafruit_NeoPixel(n, pin);
    strip->begin();
    strip->show();

    anim.begin(strip, outerIdx, outerCount, centerIdx, spinColor);
  }

  void run() { anim.run(); }

  static void fillPulse(Adafruit_NeoPixel* s, const RGB& target, uint8_t level) {
    for (uint16_t j = 0; j < s->numPixels(); ++j) {
      uint8_t r = (uint16_t)target.r * level / 255;
      uint8_t g = (uint16_t)target.g * level / 255;
      uint8_t b = (uint16_t)target.b * level / 255;
      s->setPixelColor(j, s->Color(r, g, b));
    }
    s->show();
  }

  void pulse(LedColor color, int pulses, int stepDelay) {
    RGB target = COLOR_MAP[color];
    for (int p = 0; p < pulses; ++p) {
      for (int i = 0; i <= 255; i += 5) { fillPulse(strip, target, i); delay(stepDelay); }
      for (int i = 255; i >= 0; i -= 5) { fillPulse(strip, target, i); delay(stepDelay); }
    }
  }

  void spinnerTimer(float seconds, LedColor pulseColor) {
    uint32_t startS = (uint32_t)ceil(millis() / 1000.0);
    uint32_t dur    = (uint32_t)ceil(seconds);
    while (((uint32_t)ceil(millis() / 1000.0) - startS) < dur) {
      run();
      // keep this tight but cooperative
      delay(1);
    }
    pulse(pulseColor, 1, 5);
  }
};

} // namespace

struct LedAnimations::Impl : public LedImpl {};

void LedAnimations::begin(uint8_t pin,
                          uint16_t numPixels,
                          uint8_t centerIdx,
                          const uint8_t* outerIdx,
                          uint8_t outerCount,
                          LedColor spinColor)
{
  if (!impl_) impl_ = new Impl();
  impl_->begin(pin, numPixels, centerIdx, outerIdx, outerCount, spinColor);
}

void LedAnimations::run() { if (impl_) impl_->run(); }

void LedAnimations::pulse(LedColor color, int pulses, int stepDelay) {
  if (impl_) impl_->pulse(color, pulses, stepDelay);
}

void LedAnimations::spinnerTimer(float seconds, LedColor pulseColor) {
  if (impl_) impl_->spinnerTimer(seconds, pulseColor);
}
