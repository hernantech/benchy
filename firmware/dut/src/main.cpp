// ═══════════════════════════════════════════════════════════════════
// BenchCI DUT Firmware — ESP32-S3 DevKitC-1
// ═══════════════════════════════════════════════════════════════════
//
// Configurable test interface for AI-driven hardware testing.
// All peripherals controlled via newline-delimited JSON over USB Serial.
// No peripherals active at boot — everything initialized on demand.
//
// Pin Defaults (ESP32-S3 DevKitC-1):
//   I2C:  SDA=8, SCL=9
//   UART: TX=17, RX=18
//   CAN:  TX=5, RX=6
//   PWM:  any GPIO
//   ADC:  GPIO 1-10 (ADC1, safe with WiFi active)
//
// Example commands:
//   {"cmd":"status"}
//   {"cmd":"ping"}
//   {"cmd":"pwm","pin":4,"freq":1000,"duty":50}
//   {"cmd":"pwm_stop","pin":4}
//   {"cmd":"i2c_init","sda":8,"scl":9,"freq":400000}
//   {"cmd":"i2c_scan"}
//   {"cmd":"i2c_write","addr":85,"data":[1,2,3]}
//   {"cmd":"i2c_read","addr":85,"len":2}
//   {"cmd":"uart_init","tx":17,"rx":18,"baud":115200}
//   {"cmd":"uart_send","text":"hello"}
//   {"cmd":"uart_recv","timeout":200}
//   {"cmd":"can_init","tx":5,"rx":6,"baud":500,"mode":"no_ack"}
//   {"cmd":"can_send","id":256,"data":[1,2,3,4]}
//   {"cmd":"can_recv","timeout":500}
//   {"cmd":"gpio_mode","pin":10,"mode":"output"}
//   {"cmd":"gpio_write","pin":10,"value":1}
//   {"cmd":"gpio_read","pin":10}
//   {"cmd":"adc_read","pin":1,"samples":10}
//   {"cmd":"wifi_connect","ssid":"test","pass":"12345678"}
//   {"cmd":"wifi_disconnect"}
//   {"cmd":"wifi_status"}
//   {"cmd":"reset"}
//
// Responses:
//   Success: {"ok":true,"cmd":"...","field":"value",...}
//   Error:   {"ok":false,"cmd":"...","error":"description"}
//   Boot:    {"event":"boot","board":"dut","chip":"ESP32-S3",...}
// ═══════════════════════════════════════════════════════════════════

#include <Arduino.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <WiFi.h>
#include "driver/twai.h"

// ── Pin Defaults ────────────────────────────────────────────────
namespace Pins {
    constexpr int I2C_SDA = 8;
    constexpr int I2C_SCL = 9;
    constexpr int UART_TX = 17;
    constexpr int UART_RX = 18;
    constexpr int CAN_TX  = 5;
    constexpr int CAN_RX  = 6;
}

// ── Board State ─────────────────────────────────────────────────
// pwm_ch[i] = pin assigned to LEDC channel i, or -1 if free.
// ESP32-S3 has 8 LEDC channels (0-7).
static struct {
    bool i2c  = false;
    bool uart = false;
    bool can  = false;
    bool wifi = false;

    int pwm_ch[8] = {-1,-1,-1,-1,-1,-1,-1,-1};
} S;

// Returns the LEDC channel for `pin`, allocating one if needed. -1 = full.
static int pwmChannel(int pin) {
    for (int i = 0; i < 8; i++) if (S.pwm_ch[i] == pin) return i;
    for (int i = 0; i < 8; i++) if (S.pwm_ch[i] == -1)  { S.pwm_ch[i] = pin; return i; }
    return -1;
}

static int pwmCount() {
    int n = 0;
    for (int i = 0; i < 8; i++) if (S.pwm_ch[i] != -1) n++;
    return n;
}

static HardwareSerial UartBus(1);
static String cmdBuf;

// ── Response Helpers ────────────────────────────────────────────
static void send(JsonDocument& doc) {
    serializeJson(doc, Serial);
    Serial.println();
}

static void sendOk(const char* cmd) {
    JsonDocument d;
    d["ok"] = true;
    d["cmd"] = cmd;
    send(d);
}

static void sendErr(const char* cmd, const char* msg) {
    JsonDocument d;
    d["ok"] = false;
    d["cmd"] = cmd;
    d["error"] = msg;
    send(d);
}

// ── PWM (Arduino ESP32 core 2.x — channel-based LEDC API) ──────
static void cmdPwm(JsonDocument& c) {
    int pin = c["pin"] | -1;
    if (pin < 0 || pin > 48) return sendErr("pwm", "invalid pin");

    uint32_t freq = c["freq"] | 1000;
    uint8_t  res  = c["res"]  | 10;         // 10-bit = 0-1023
    float duty_pct = c["duty"] | 50.0f;     // 0-100%

    int ch = pwmChannel(pin);
    if (ch < 0) return sendErr("pwm", "no free LEDC channels (max 8)");

    ledcSetup(ch, freq, res);
    ledcAttachPin(pin, ch);

    uint32_t max_duty = (1 << res) - 1;
    uint32_t duty_raw = (uint32_t)((duty_pct / 100.0f) * max_duty);
    ledcWrite(ch, duty_raw);

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "pwm";
    r["pin"] = pin;
    r["channel"] = ch;
    r["freq"] = freq;
    r["duty_pct"] = duty_pct;
    r["duty_raw"] = duty_raw;
    r["max_duty"] = max_duty;
    r["resolution"] = res;
    send(r);
}

static void cmdPwmStop(JsonDocument& c) {
    int pin = c["pin"] | -1;
    if (pin < 0) return sendErr("pwm_stop", "missing pin");

    ledcDetachPin(pin);
    for (int i = 0; i < 8; i++) {
        if (S.pwm_ch[i] == pin) {
            ledcWrite(i, 0);
            S.pwm_ch[i] = -1;
            break;
        }
    }
    sendOk("pwm_stop");
}

// ── I2C (Master) ────────────────────────────────────────────────
static void cmdI2cInit(JsonDocument& c) {
    if (S.i2c) Wire.end();

    int sda = c["sda"] | Pins::I2C_SDA;
    int scl = c["scl"] | Pins::I2C_SCL;
    uint32_t freq = c["freq"] | 100000;

    Wire.begin(sda, scl, freq);
    S.i2c = true;

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "i2c_init";
    r["sda"] = sda;
    r["scl"] = scl;
    r["freq"] = freq;
    send(r);
}

static void cmdI2cDeinit(JsonDocument& c) {
    if (S.i2c) { Wire.end(); S.i2c = false; }
    sendOk("i2c_deinit");
}

static void cmdI2cScan(JsonDocument& c) {
    if (!S.i2c) return sendErr("i2c_scan", "i2c not initialized — send i2c_init first");

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "i2c_scan";
    JsonArray devs = r["devices"].to<JsonArray>();

    for (uint8_t a = 1; a < 127; a++) {
        Wire.beginTransmission(a);
        if (Wire.endTransmission() == 0) devs.add(a);
    }
    r["count"] = devs.size();
    send(r);
}

static void cmdI2cWrite(JsonDocument& c) {
    if (!S.i2c) return sendErr("i2c_write", "i2c not initialized");

    uint8_t addr = c["addr"] | 0;
    if (addr == 0) return sendErr("i2c_write", "missing addr");

    JsonArray data = c["data"];
    if (data.isNull()) return sendErr("i2c_write", "missing data array");

    Wire.beginTransmission(addr);
    // Optional register byte
    if (!c["reg"].isNull()) Wire.write((uint8_t)c["reg"].as<int>());
    for (JsonVariant v : data) Wire.write((uint8_t)v.as<int>());
    uint8_t err = Wire.endTransmission();

    JsonDocument r;
    r["ok"] = (err == 0);
    r["cmd"] = "i2c_write";
    r["addr"] = addr;
    r["bytes_sent"] = data.size() + (c["reg"].isNull() ? 0 : 1);
    r["wire_status"] = err;
    if (err != 0) {
        const char* msgs[] = {"ok","data_too_long","nack_addr","nack_data","other","timeout"};
        r["error"] = (err < 6) ? msgs[err] : "unknown";
    }
    send(r);
}

static void cmdI2cRead(JsonDocument& c) {
    if (!S.i2c) return sendErr("i2c_read", "i2c not initialized");

    uint8_t addr = c["addr"] | 0;
    uint8_t len  = c["len"]  | 1;
    if (addr == 0) return sendErr("i2c_read", "missing addr");

    // Optional register address (write reg, then repeated start + read)
    if (!c["reg"].isNull()) {
        Wire.beginTransmission(addr);
        Wire.write((uint8_t)c["reg"].as<int>());
        Wire.endTransmission(false);  // repeated start
    }

    uint8_t got = Wire.requestFrom(addr, len);

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "i2c_read";
    r["addr"] = addr;
    r["requested"] = len;
    r["received"] = got;
    JsonArray data = r["data"].to<JsonArray>();
    while (Wire.available()) data.add(Wire.read());
    send(r);
}

// ── UART (via UART1) ────────────────────────────────────────────
static void cmdUartInit(JsonDocument& c) {
    if (S.uart) UartBus.end();

    int tx = c["tx"] | Pins::UART_TX;
    int rx = c["rx"] | Pins::UART_RX;
    uint32_t baud = c["baud"] | 9600;

    UartBus.begin(baud, SERIAL_8N1, rx, tx);
    S.uart = true;

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "uart_init";
    r["tx"] = tx;
    r["rx"] = rx;
    r["baud"] = baud;
    send(r);
}

static void cmdUartDeinit(JsonDocument& c) {
    if (S.uart) { UartBus.end(); S.uart = false; }
    sendOk("uart_deinit");
}

static void cmdUartSend(JsonDocument& c) {
    if (!S.uart) return sendErr("uart_send", "uart not initialized");

    if (c["text"].is<const char*>()) {
        const char* text = c["text"];
        UartBus.print(text);
        JsonDocument r;
        r["ok"] = true;
        r["cmd"] = "uart_send";
        r["bytes"] = strlen(text);
        send(r);
    } else if (c["data"].is<JsonArray>()) {
        JsonArray data = c["data"];
        for (JsonVariant v : data) UartBus.write((uint8_t)v.as<int>());
        JsonDocument r;
        r["ok"] = true;
        r["cmd"] = "uart_send";
        r["bytes"] = data.size();
        send(r);
    } else {
        sendErr("uart_send", "provide 'text' string or 'data' byte array");
    }
}

static void cmdUartRecv(JsonDocument& c) {
    if (!S.uart) return sendErr("uart_recv", "uart not initialized");

    uint32_t timeout = c["timeout"] | 100;
    int max_bytes = c["max"] | 256;

    // Wait for first byte or timeout
    unsigned long start = millis();
    while (!UartBus.available() && (millis() - start) < timeout) delay(1);

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "uart_recv";
    JsonArray data = r["data"].to<JsonArray>();
    String text;

    while (UartBus.available() && (int)data.size() < max_bytes) {
        uint8_t b = UartBus.read();
        data.add(b);
        text += (b >= 32 && b < 127) ? (char)b : '.';
    }

    r["bytes"] = data.size();
    r["text"] = text;
    send(r);
}

// ── CAN / TWAI ──────────────────────────────────────────────────
static bool getTwaiTiming(uint32_t kbps, twai_timing_config_t& out) {
    switch (kbps) {
        case 1000: { twai_timing_config_t t = TWAI_TIMING_CONFIG_1MBITS();   out = t; return true; }
        case 800:  { twai_timing_config_t t = TWAI_TIMING_CONFIG_800KBITS(); out = t; return true; }
        case 500:  { twai_timing_config_t t = TWAI_TIMING_CONFIG_500KBITS(); out = t; return true; }
        case 250:  { twai_timing_config_t t = TWAI_TIMING_CONFIG_250KBITS(); out = t; return true; }
        case 125:  { twai_timing_config_t t = TWAI_TIMING_CONFIG_125KBITS(); out = t; return true; }
        case 100:  { twai_timing_config_t t = TWAI_TIMING_CONFIG_100KBITS(); out = t; return true; }
        case 50:   { twai_timing_config_t t = TWAI_TIMING_CONFIG_50KBITS();  out = t; return true; }
        case 25:   { twai_timing_config_t t = TWAI_TIMING_CONFIG_25KBITS();  out = t; return true; }
        default:   return false;
    }
}

static void cmdCanInit(JsonDocument& c) {
    if (S.can) {
        twai_stop();
        twai_driver_uninstall();
        S.can = false;
    }

    int tx = c["tx"] | Pins::CAN_TX;
    int rx = c["rx"] | Pins::CAN_RX;
    uint32_t baud = c["baud"] | 500;  // kbps

    const char* mode_str = c["mode"] | "normal";
    twai_mode_t mode = TWAI_MODE_NORMAL;
    if (strcmp(mode_str, "no_ack") == 0) mode = TWAI_MODE_NO_ACK;
    else if (strcmp(mode_str, "listen") == 0) mode = TWAI_MODE_LISTEN_ONLY;

    twai_general_config_t g = TWAI_GENERAL_CONFIG_DEFAULT((gpio_num_t)tx, (gpio_num_t)rx, mode);
    g.rx_queue_len = 32;
    g.tx_queue_len = 16;

    twai_timing_config_t t;
    if (!getTwaiTiming(baud, t))
        return sendErr("can_init", "unsupported baud — use 25/50/100/125/250/500/800/1000 kbps");

    twai_filter_config_t f = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    esp_err_t err = twai_driver_install(&g, &t, &f);
    if (err != ESP_OK) return sendErr("can_init", "driver_install failed");

    err = twai_start();
    if (err != ESP_OK) {
        twai_driver_uninstall();
        return sendErr("can_init", "twai_start failed");
    }

    S.can = true;

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "can_init";
    r["tx"] = tx;
    r["rx"] = rx;
    r["baud_kbps"] = baud;
    r["mode"] = mode_str;
    send(r);
}

static void cmdCanDeinit(JsonDocument& c) {
    if (S.can) {
        twai_stop();
        twai_driver_uninstall();
        S.can = false;
    }
    sendOk("can_deinit");
}

static void cmdCanSend(JsonDocument& c) {
    if (!S.can) return sendErr("can_send", "can not initialized");

    uint32_t id = c["id"] | 0;
    bool ext    = c["ext"] | false;
    bool self   = c["self"] | false;  // self-reception for loopback testing
    JsonArray data = c["data"];

    twai_message_t msg = {};
    msg.identifier = id;
    msg.extd = ext ? 1 : 0;
    msg.self = self ? 1 : 0;
    msg.data_length_code = data.isNull() ? 0 : (data.size() < 8 ? data.size() : 8);
    for (int i = 0; i < msg.data_length_code; i++) {
        msg.data[i] = data[i].as<uint8_t>();
    }

    esp_err_t err = twai_transmit(&msg, pdMS_TO_TICKS(100));

    JsonDocument r;
    r["ok"] = (err == ESP_OK);
    r["cmd"] = "can_send";
    r["id"] = id;
    r["dlc"] = msg.data_length_code;
    if (err != ESP_OK) r["error"] = "transmit failed (timeout or bus error)";
    send(r);
}

static void cmdCanRecv(JsonDocument& c) {
    if (!S.can) return sendErr("can_recv", "can not initialized");

    uint32_t timeout = c["timeout"] | 100;
    int max_frames = c["max"] | 10;

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "can_recv";
    JsonArray frames = r["frames"].to<JsonArray>();

    for (int i = 0; i < max_frames; i++) {
        twai_message_t msg;
        TickType_t wait = (i == 0) ? pdMS_TO_TICKS(timeout) : 0;
        if (twai_receive(&msg, wait) != ESP_OK) break;

        JsonObject f = frames.add<JsonObject>();
        f["id"]  = msg.identifier;
        f["ext"] = (bool)msg.extd;
        f["rtr"] = (bool)msg.rtr;
        f["dlc"] = msg.data_length_code;
        JsonArray d = f["data"].to<JsonArray>();
        for (int j = 0; j < msg.data_length_code; j++) d.add(msg.data[j]);
    }

    r["count"] = frames.size();
    send(r);
}

// ── GPIO ────────────────────────────────────────────────────────
static void cmdGpioMode(JsonDocument& c) {
    int pin = c["pin"] | -1;
    if (pin < 0 || pin > 48) return sendErr("gpio_mode", "invalid pin");

    const char* mode = c["mode"] | "output";
    if      (strcmp(mode, "output") == 0)         pinMode(pin, OUTPUT);
    else if (strcmp(mode, "input") == 0)          pinMode(pin, INPUT);
    else if (strcmp(mode, "input_pullup") == 0)   pinMode(pin, INPUT_PULLUP);
    else if (strcmp(mode, "input_pulldown") == 0) pinMode(pin, INPUT_PULLDOWN);
    else return sendErr("gpio_mode", "mode: output/input/input_pullup/input_pulldown");

    sendOk("gpio_mode");
}

static void cmdGpioWrite(JsonDocument& c) {
    int pin = c["pin"] | -1;
    int val = c["value"] | 0;
    if (pin < 0) return sendErr("gpio_write", "missing pin");

    digitalWrite(pin, val ? HIGH : LOW);
    sendOk("gpio_write");
}

static void cmdGpioRead(JsonDocument& c) {
    int pin = c["pin"] | -1;
    if (pin < 0) return sendErr("gpio_read", "missing pin");

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "gpio_read";
    r["pin"] = pin;
    r["value"] = digitalRead(pin);
    send(r);
}

// ── ADC ─────────────────────────────────────────────────────────
static void cmdAdcRead(JsonDocument& c) {
    int pin = c["pin"] | -1;
    if (pin < 0) return sendErr("adc_read", "missing pin");

    int samples = c["samples"] | 1;
    if (samples < 1) samples = 1;
    if (samples > 64) samples = 64;

    uint32_t raw_sum = 0;
    uint32_t mv_sum  = 0;
    for (int i = 0; i < samples; i++) {
        raw_sum += analogRead(pin);
        mv_sum  += analogReadMilliVolts(pin);
        if (samples > 1) delayMicroseconds(200);
    }

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "adc_read";
    r["pin"] = pin;
    r["raw"] = raw_sum / samples;
    r["millivolts"] = mv_sum / samples;
    r["voltage"] = (mv_sum / samples) / 1000.0f;
    r["samples"] = samples;
    send(r);
}

// ── WiFi ────────────────────────────────────────────────────────
static void cmdWifiConnect(JsonDocument& c) {
    const char* ssid = c["ssid"] | nullptr;
    if (!ssid) return sendErr("wifi_connect", "missing ssid");
    const char* pass = c["pass"] | "";
    uint32_t timeout = c["timeout"] | 10000;

    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, pass);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - start) < timeout) {
        delay(100);
    }

    S.wifi = WiFi.isConnected();

    JsonDocument r;
    r["ok"] = S.wifi;
    r["cmd"] = "wifi_connect";
    r["ssid"] = ssid;
    if (S.wifi) {
        r["ip"] = WiFi.localIP().toString();
        r["rssi"] = WiFi.RSSI();
    } else {
        r["error"] = "connection timeout";
    }
    send(r);
}

static void cmdWifiDisconnect(JsonDocument& c) {
    WiFi.disconnect(true);
    WiFi.mode(WIFI_MODE_NULL);
    S.wifi = false;
    sendOk("wifi_disconnect");
}

static void cmdWifiStatus(JsonDocument& c) {
    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "wifi_status";
    r["connected"] = WiFi.isConnected();
    if (WiFi.isConnected()) {
        r["ssid"] = WiFi.SSID();
        r["ip"]   = WiFi.localIP().toString();
        r["rssi"] = WiFi.RSSI();
    }
    r["mac"] = WiFi.macAddress();
    send(r);
}

// ── System ──────────────────────────────────────────────────────
static void cmdStatus(JsonDocument& c) {
    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "status";
    r["board"] = "dut";
    r["chip"] = "ESP32-S3";
    r["uptime_ms"] = millis();
    r["free_heap"] = ESP.getFreeHeap();
    r["min_free_heap"] = ESP.getMinFreeHeap();

    JsonObject p = r["peripherals"].to<JsonObject>();
    p["i2c"]  = S.i2c;
    p["uart"] = S.uart;
    p["can"]  = S.can;
    p["wifi"] = S.wifi;
    p["pwm_count"] = pwmCount();
    if (pwmCount() > 0) {
        JsonArray pins = p["pwm_pins"].to<JsonArray>();
        for (int i = 0; i < 8; i++) if (S.pwm_ch[i] != -1) pins.add(S.pwm_ch[i]);
    }

    send(r);
}

static void cmdPing(JsonDocument& c) {
    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "pong";
    r["uptime_ms"] = millis();
    send(r);
}

// ── Command Dispatch ────────────────────────────────────────────
static void processCommand(const String& line) {
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, line);
    if (err) {
        JsonDocument r;
        r["ok"] = false;
        r["error"] = "json_parse_error";
        r["detail"] = err.c_str();
        send(r);
        return;
    }

    const char* cmd = doc["cmd"] | "";

    if      (strcmp(cmd, "ping") == 0)            cmdPing(doc);
    else if (strcmp(cmd, "status") == 0)          cmdStatus(doc);
    // PWM
    else if (strcmp(cmd, "pwm") == 0)             cmdPwm(doc);
    else if (strcmp(cmd, "pwm_stop") == 0)        cmdPwmStop(doc);
    // I2C
    else if (strcmp(cmd, "i2c_init") == 0)        cmdI2cInit(doc);
    else if (strcmp(cmd, "i2c_deinit") == 0)      cmdI2cDeinit(doc);
    else if (strcmp(cmd, "i2c_scan") == 0)        cmdI2cScan(doc);
    else if (strcmp(cmd, "i2c_write") == 0)       cmdI2cWrite(doc);
    else if (strcmp(cmd, "i2c_read") == 0)        cmdI2cRead(doc);
    // UART
    else if (strcmp(cmd, "uart_init") == 0)       cmdUartInit(doc);
    else if (strcmp(cmd, "uart_deinit") == 0)     cmdUartDeinit(doc);
    else if (strcmp(cmd, "uart_send") == 0)       cmdUartSend(doc);
    else if (strcmp(cmd, "uart_recv") == 0)       cmdUartRecv(doc);
    // CAN
    else if (strcmp(cmd, "can_init") == 0)        cmdCanInit(doc);
    else if (strcmp(cmd, "can_deinit") == 0)      cmdCanDeinit(doc);
    else if (strcmp(cmd, "can_send") == 0)        cmdCanSend(doc);
    else if (strcmp(cmd, "can_recv") == 0)        cmdCanRecv(doc);
    // GPIO
    else if (strcmp(cmd, "gpio_mode") == 0)       cmdGpioMode(doc);
    else if (strcmp(cmd, "gpio_write") == 0)      cmdGpioWrite(doc);
    else if (strcmp(cmd, "gpio_read") == 0)       cmdGpioRead(doc);
    // ADC
    else if (strcmp(cmd, "adc_read") == 0)        cmdAdcRead(doc);
    // WiFi
    else if (strcmp(cmd, "wifi_connect") == 0)    cmdWifiConnect(doc);
    else if (strcmp(cmd, "wifi_disconnect") == 0) cmdWifiDisconnect(doc);
    else if (strcmp(cmd, "wifi_status") == 0)     cmdWifiStatus(doc);
    // System
    else if (strcmp(cmd, "reset") == 0)           ESP.restart();
    else                                         sendErr(cmd, "unknown command");
}

// ── Arduino Entry Points ────────────────────────────────────────
void setup() {
    Serial.begin(115200);

    // Wait for USB CDC connection (up to 3s)
    unsigned long start = millis();
    while (!Serial && millis() - start < 3000) delay(10);

    // Boot announcement
    JsonDocument boot;
    boot["event"]     = "boot";
    boot["board"]     = "dut";
    boot["chip"]      = "ESP32-S3";
    boot["version"]   = "1.0.0";
    boot["free_heap"] = ESP.getFreeHeap();
    send(boot);

    cmdBuf.reserve(512);
}

void loop() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n') {
            if (cmdBuf.length() > 0) {
                processCommand(cmdBuf);
                cmdBuf = "";
            }
        } else if (c != '\r') {
            cmdBuf += c;
            if (cmdBuf.length() > 2048) {
                sendErr("", "command too long (>2048 bytes)");
                cmdBuf = "";
            }
        }
    }
}
