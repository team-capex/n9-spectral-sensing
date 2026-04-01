#include "ble.h"
#include <NimBLEDevice.h>

namespace {

// BLE internals
static NimBLECharacteristic* pCharacteristic = nullptr;

static bool g_msgReceived = false;
static String g_action;
static String g_params;
static size_t g_pos = 0;

static bool g_connected = false;
static bool g_wasConnected = false;

static bool     advRestartPending = false;
static uint32_t advRetryAt        = 0;

// Helpers
static inline void scheduleAdvRestart(uint32_t delayMs = 400) {
  advRestartPending = true;
  advRetryAt = millis() + delayMs;
}

static String nextToken(char delim) {
  if (g_pos >= g_params.length()) return String("");
  int end = g_params.indexOf(delim, g_pos);
  String token;
  if (end < 0) { token = g_params.substring(g_pos); g_pos = g_params.length(); }
  else { token = g_params.substring(g_pos, end); g_pos = end + 1; }
  token.trim();
  return token;
}

struct CommandCallback : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* pChar, NimBLEConnInfo& /*connInfo*/) override {
    std::string value = pChar->getValue();
    if (value.empty()) return;

    String payload(value.c_str());
    payload.trim();

    int open  = payload.indexOf('(');
    int close = payload.lastIndexOf(')');
    if (open <= 0 || close < 0 || close <= open) return;

    g_action = payload.substring(0, open);
    g_params = payload.substring(open + 1, close);
    g_pos    = 0;
    g_msgReceived = true;
  }
};

struct ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* /*s*/) {
    Serial.println("BLE Connected");
  }
  void onDisconnect(NimBLEServer* /*s*/) {
    Serial.println("BLE Disconnected; re-advertising");
    NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
    bool ok = adv->start();
    Serial.println(ok ? "[BLE] Advertising restarted" : "[BLE] Advertising restart FAILED");
  }
};

} // namespace

void ble_begin(const char* deviceName,
               const char* serviceUuid,
               const char* characteristicUuid)
{
  Serial.println("Attempting to start BLE command channel..");

  NimBLEDevice::init(deviceName);
  NimBLEDevice::setPower(ESP_PWR_LVL_P9);
  NimBLEDevice::setSecurityAuth(false, false, true);

  NimBLEServer*    server  = NimBLEDevice::createServer();
  NimBLEService*   service = server->createService(serviceUuid);
  server->setCallbacks(new ServerCallbacks());

  pCharacteristic = service->createCharacteristic(
      characteristicUuid,
      NIMBLE_PROPERTY::READ |
      NIMBLE_PROPERTY::WRITE |
      NIMBLE_PROPERTY::WRITE_NR |
      NIMBLE_PROPERTY::NOTIFY
  );
  pCharacteristic->setCallbacks(new CommandCallback());

  service->start();

  NimBLEAdvertising* ad = NimBLEDevice::getAdvertising();
  ad->addServiceUUID(serviceUuid);
  ad->setAppearance(0x00);

  NimBLEAdvertisementData advData; advData.addServiceUUID(serviceUuid);
  NimBLEAdvertisementData scanResp; scanResp.setName(deviceName);
  ad->setAdvertisementData(advData);
  ad->setScanResponseData(scanResp);

  bool ok = ad->start();
  Serial.println(ok ? "[BLE] Initial advertising started" : "[BLE] Advertising start FAILED");
}

void ble_loop() {
  NimBLEServer* srv = NimBLEDevice::getServer();
  g_connected = (srv && srv->getConnectedCount() > 0);

  if (g_wasConnected && !g_connected) {
    Serial.println("[BLE] Detected disconnect; scheduling re-advertise");
    scheduleAdvRestart();
  }
  if (!g_wasConnected && g_connected) {
    advRestartPending = false;
  }
  g_wasConnected = g_connected;

  if (advRestartPending && (int32_t)(millis() - advRetryAt) >= 0) {
    NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
    if (adv && !adv->isAdvertising() && !g_connected) {
      bool ok = adv->start();
      Serial.println(ok ? "[BLE] Advertising restarted" : "[BLE] Advertising restart FAILED");
    }
    advRestartPending = false;
  }
}

bool ble_is_connected()            { return g_connected; }
bool ble_message_received()        { return g_msgReceived; }
String ble_get_action()            { return g_action; }
String ble_read_arg(char delim)    { return nextToken(delim); }

void ble_respond(const String& s) {
  Serial.println(s);
  if (!pCharacteristic) return;
  pCharacteristic->setValue(s.c_str());
  pCharacteristic->notify();
}

void ble_clear_message() {
  g_msgReceived = false;
  g_action      = "";
  g_params      = "";
  g_pos         = 0;
}
