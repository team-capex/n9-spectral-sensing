#pragma once
#include <Arduino.h>

// Initialize BLE command channel
// Example names/UUIDs can be reused from your original sketch.
void ble_begin(const char* deviceName,
               const char* serviceUuid,
               const char* characteristicUuid);

// Call regularly in loop() for connection/advertising housekeeping.
void ble_loop();

// Query BLE state
bool   ble_is_connected();
bool   ble_message_received();

// When a message is received via BLE, this returns the parsed action
// (the part before '('). Stable until you call ble_clear_message().
String ble_get_action();

// Read next argument for the current BLE message, delimited by `delim`.
// Safe to call only if ble_message_received() is true.
String ble_read_arg(char delim = ',');

// Send a response back over Serial and BLE notify (if subscribed).
void ble_respond(const String& s);

// Clear the current BLE message parse state after you've handled it.
void ble_clear_message();
