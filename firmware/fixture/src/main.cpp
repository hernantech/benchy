// ═══════════════════════════════════════════════════════════════════
// BenchCI Fixture Firmware — ESP32-S3 DevKitC-1
// ═══════════════════════════════════════════════════════════════════
//
// Test partner / fault injector for the DUT board.
// Provides: I2C slave, CAN partner, DUT reset control, load injection.
// All via newline-delimited JSON over USB Serial.
//
// Pin Defaults (ESP32-S3 DevKitC-1):
//   I2C Slave: SDA=8, SCL=9 (default addr 0x55)
//   CAN:       TX=5, RX=6
//   DUT Reset: GPIO 7 → DUT EN pin
//   Load PWM:  GPIO 4 → MOSFET gate
//   UART:      TX=17, RX=18
//   ADC:       GPIO 1-10 (ADC1)
//
// Wiring to DUT:
//   Fixture GPIO 7  → DUT EN pin  (reset control)
//   Fixture GPIO 4  → MOSFET gate (load injection)
//   Fixture SDA/SCL → DUT SDA/SCL (I2C bus, shared)
//   Fixture CAN TX  → transceiver → bus ← transceiver ← DUT CAN TX
//   Fixture UART RX → DUT UART TX (cross-wired)
//
// Example commands:
//   {"cmd":"status"}
//   {"cmd":"i2c_slave_init","addr":85}
//   {"cmd":"i2c_slave_set_resp","data":[66,67,68]}
//   {"cmd":"i2c_slave_set_mode","mode":"delay","delay_us":500}
//   {"cmd":"i2c_slave_log"}
//   {"cmd":"reset_dut","hold_ms":100}
//   {"cmd":"load","pin":4,"duty":50}
//   {"cmd":"can_init","mode":"no_ack","baud":500}
//   {"cmd":"can_recv","timeout":1000}
//   {"cmd":"gpio_write","pin":10,"value":1}
//   {"cmd":"adc_read","pin":1}
// ═══════════════════════════════════════════════════════════════════

#include <Arduino.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include "driver/twai.h"

// ── Pin Defaults ────────────────────────────────────────────────
namespace Pins {
    constexpr int I2C_SDA   = 8;
    constexpr int I2C_SCL   = 9;
    constexpr int CAN_TX    = 5;
    constexpr int CAN_RX    = 6;
    constexpr int DUT_EN    = 7;     // connected to DUT's EN pin
    constexpr int LOAD_PWM  = 4;     // MOSFET gate for load injection
    constexpr int UART_TX   = 17;
    constexpr int UART_RX   = 18;
}

// ── Board State ─────────────────────────────────────────────────
static struct {
    bool i2c_slave  = false;
    bool can        = false;
    bool uart       = false;
    bool load_on    = false;

    int pwm_ch[8] = {-1,-1,-1,-1,-1,-1,-1,-1};  // channel → pin
} S;

// Returns LEDC channel for `pin`, allocating one if needed. -1 = full.
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

// ── I2C Slave State ─────────────────────────────────────────────
enum I2CSlaveMode : uint8_t { SLAVE_NORMAL, SLAVE_DELAY, SLAVE_NACK };

static volatile I2CSlaveMode i2c_mode       = SLAVE_NORMAL;
static volatile uint32_t     i2c_delay_us   = 0;
static uint8_t               i2c_resp_buf[32] = {};
static uint8_t               i2c_resp_len   = 0;
static uint8_t               i2c_rx_buf[256] = {};
static volatile int          i2c_rx_len     = 0;
static volatile uint32_t     i2c_rx_count   = 0;
static volatile uint32_t     i2c_tx_count   = 0;

static void IRAM_ATTR onI2cReceive(int numBytes) {
    i2c_rx_len = 0;
    while (Wire.available() && i2c_rx_len < 256) {
        i2c_rx_buf[i2c_rx_len++] = Wire.read();
    }
    i2c_rx_count++;
}

static void IRAM_ATTR onI2cRequest() {
    if (i2c_mode == SLAVE_NACK) return;       // simulate absent device
    if (i2c_mode == SLAVE_DELAY && i2c_delay_us > 0) {
        delayMicroseconds(i2c_delay_us);      // clock stretching
    }
    if (i2c_resp_len > 0) {
        Wire.write(i2c_resp_buf, i2c_resp_len);
    }
    i2c_tx_count++;
}

// ── Globals ─────────────────────────────────────────────────────
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

// ── I2C Slave ───────────────────────────────────────────────────
static void cmdI2cSlaveInit(JsonDocument& c) {
    if (S.i2c_slave) Wire.end();

    uint8_t addr = c["addr"] | 0x55;
    int sda = c["sda"] | Pins::I2C_SDA;
    int scl = c["scl"] | Pins::I2C_SCL;
    uint32_t freq = c["freq"] | 100000;

    i2c_mode     = SLAVE_NORMAL;
    i2c_rx_count = 0;
    i2c_tx_count = 0;
    i2c_rx_len   = 0;

    Wire.onReceive(onI2cReceive);
    Wire.onRequest(onI2cRequest);
    Wire.begin(addr, sda, scl, freq);
    S.i2c_slave = true;

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "i2c_slave_init";
    r["addr"] = addr;
    r["addr_hex"] = String("0x") + String(addr, HEX);
    r["sda"] = sda;
    r["scl"] = scl;
    send(r);
}

static void cmdI2cSlaveDeinit(JsonDocument& c) {
    if (S.i2c_slave) { Wire.end(); S.i2c_slave = false; }
    sendOk("i2c_slave_deinit");
}

static void cmdI2cSlaveSetResp(JsonDocument& c) {
    JsonArray data = c["data"];
    if (data.isNull()) return sendErr("i2c_slave_set_resp", "missing data array");

    i2c_resp_len = (data.size() < 32) ? data.size() : 32;
    for (int i = 0; i < i2c_resp_len; i++) {
        i2c_resp_buf[i] = data[i].as<uint8_t>();
    }

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "i2c_slave_set_resp";
    r["len"] = i2c_resp_len;
    send(r);
}

static void cmdI2cSlaveSetMode(JsonDocument& c) {
    const char* mode = c["mode"] | "normal";

    if (strcmp(mode, "normal") == 0) {
        i2c_mode = SLAVE_NORMAL;
    } else if (strcmp(mode, "delay") == 0) {
        i2c_mode = SLAVE_DELAY;
        i2c_delay_us = c["delay_us"] | 500;
    } else if (strcmp(mode, "nack") == 0) {
        i2c_mode = SLAVE_NACK;
    } else {
        return sendErr("i2c_slave_set_mode", "mode: normal/delay/nack");
    }

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "i2c_slave_set_mode";
    r["mode"] = mode;
    if (i2c_mode == SLAVE_DELAY) r["delay_us"] = i2c_delay_us;
    send(r);
}

static void cmdI2cSlaveLog(JsonDocument& c) {
    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "i2c_slave_log";
    r["rx_count"] = i2c_rx_count;
    r["tx_count"] = i2c_tx_count;
    r["last_rx_len"] = i2c_rx_len;

    if (i2c_rx_len > 0) {
        JsonArray data = r["last_rx_data"].to<JsonArray>();
        for (int i = 0; i < i2c_rx_len; i++) data.add(i2c_rx_buf[i]);
    }

    bool clear = c["clear"] | false;
    if (clear) { i2c_rx_count = 0; i2c_tx_count = 0; i2c_rx_len = 0; }

    send(r);
}

// ── DUT Reset ───────────────────────────────────────────────────
static void cmdResetDut(JsonDocument& c) {
    int pin = c["pin"] | Pins::DUT_EN;
    int hold_ms = c["hold_ms"] | 100;

    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);     // pull EN low = reset
    delay(hold_ms);
    digitalWrite(pin, HIGH);    // release
    pinMode(pin, INPUT);        // return to high-Z

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "reset_dut";
    r["pin"] = pin;
    r["hold_ms"] = hold_ms;
    send(r);
}

// ── Load Injection (PWM → MOSFET, core 2.x channel API) ────────
static void cmdLoad(JsonDocument& c) {
    int pin = c["pin"] | Pins::LOAD_PWM;
    float duty = c["duty"] | 0.0f;     // 0-100%
    uint32_t freq = c["freq"] | 10000;

    if (duty <= 0) {
        // Find channel and release
        for (int i = 0; i < 8; i++) {
            if (S.pwm_ch[i] == pin) { ledcWrite(i, 0); ledcDetachPin(pin); S.pwm_ch[i] = -1; break; }
        }
        S.load_on = false;
        sendOk("load");
        return;
    }

    int ch = pwmChannel(pin);
    if (ch < 0) return sendErr("load", "no free LEDC channels");

    ledcSetup(ch, freq, 10);
    ledcAttachPin(pin, ch);
    uint32_t raw = (uint32_t)((duty / 100.0f) * 1023);
    ledcWrite(ch, raw);
    S.load_on = true;

    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "load";
    r["pin"] = pin;
    r["channel"] = ch;
    r["duty_pct"] = duty;
    r["freq"] = freq;
    send(r);
}

// ── PWM (general purpose, core 2.x channel API) ────────────────
static void cmdPwm(JsonDocument& c) {
    int pin = c["pin"] | -1;
    if (pin < 0 || pin > 48) return sendErr("pwm", "invalid pin");

    uint32_t freq = c["freq"] | 1000;
    uint8_t  res  = c["res"]  | 10;
    float duty_pct = c["duty"] | 50.0f;

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
    uint32_t baud = c["baud"] | 500;

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
    bool self   = c["self"] | false;
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

// ── System ──────────────────────────────────────────────────────
static void cmdStatus(JsonDocument& c) {
    JsonDocument r;
    r["ok"] = true;
    r["cmd"] = "status";
    r["board"] = "fixture";
    r["chip"] = "ESP32-S3";
    r["uptime_ms"] = millis();
    r["free_heap"] = ESP.getFreeHeap();
    r["min_free_heap"] = ESP.getMinFreeHeap();

    JsonObject p = r["peripherals"].to<JsonObject>();
    p["i2c_slave"] = S.i2c_slave;
    p["can"]       = S.can;
    p["uart"]      = S.uart;
    p["load"]      = S.load_on;
    p["pwm_count"] = pwmCount();

    if (S.i2c_slave) {
        JsonObject i2c = p["i2c_detail"].to<JsonObject>();
        i2c["rx_count"] = i2c_rx_count;
        i2c["tx_count"] = i2c_tx_count;
        const char* modes[] = {"normal", "delay", "nack"};
        i2c["mode"] = modes[i2c_mode];
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

    if      (strcmp(cmd, "ping") == 0)                 cmdPing(doc);
    else if (strcmp(cmd, "status") == 0)               cmdStatus(doc);
    // I2C Slave
    else if (strcmp(cmd, "i2c_slave_init") == 0)       cmdI2cSlaveInit(doc);
    else if (strcmp(cmd, "i2c_slave_deinit") == 0)     cmdI2cSlaveDeinit(doc);
    else if (strcmp(cmd, "i2c_slave_set_resp") == 0)   cmdI2cSlaveSetResp(doc);
    else if (strcmp(cmd, "i2c_slave_set_mode") == 0)   cmdI2cSlaveSetMode(doc);
    else if (strcmp(cmd, "i2c_slave_log") == 0)        cmdI2cSlaveLog(doc);
    // DUT control
    else if (strcmp(cmd, "reset_dut") == 0)            cmdResetDut(doc);
    else if (strcmp(cmd, "load") == 0)                 cmdLoad(doc);
    // PWM
    else if (strcmp(cmd, "pwm") == 0)                  cmdPwm(doc);
    else if (strcmp(cmd, "pwm_stop") == 0)             cmdPwmStop(doc);
    // CAN
    else if (strcmp(cmd, "can_init") == 0)             cmdCanInit(doc);
    else if (strcmp(cmd, "can_deinit") == 0)           cmdCanDeinit(doc);
    else if (strcmp(cmd, "can_send") == 0)             cmdCanSend(doc);
    else if (strcmp(cmd, "can_recv") == 0)             cmdCanRecv(doc);
    // UART
    else if (strcmp(cmd, "uart_init") == 0)            cmdUartInit(doc);
    else if (strcmp(cmd, "uart_deinit") == 0)          cmdUartDeinit(doc);
    else if (strcmp(cmd, "uart_send") == 0)            cmdUartSend(doc);
    else if (strcmp(cmd, "uart_recv") == 0)            cmdUartRecv(doc);
    // GPIO
    else if (strcmp(cmd, "gpio_mode") == 0)            cmdGpioMode(doc);
    else if (strcmp(cmd, "gpio_write") == 0)           cmdGpioWrite(doc);
    else if (strcmp(cmd, "gpio_read") == 0)            cmdGpioRead(doc);
    // ADC
    else if (strcmp(cmd, "adc_read") == 0)             cmdAdcRead(doc);
    // System
    else if (strcmp(cmd, "reset") == 0)                ESP.restart();
    else                                              sendErr(cmd, "unknown command");
}

// ── Arduino Entry Points ────────────────────────────────────────
void setup() {
    Serial.begin(115200);

    unsigned long start = millis();
    while (!Serial && millis() - start < 3000) delay(10);

    // Ensure DUT EN pin starts as high-Z (not pulling DUT into reset)
    pinMode(Pins::DUT_EN, INPUT);

    JsonDocument boot;
    boot["event"]     = "boot";
    boot["board"]     = "fixture";
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
