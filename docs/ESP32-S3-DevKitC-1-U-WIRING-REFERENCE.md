# ESP32-S3-DevKitC-1-U Wiring Reference

**For AI-agent-guided hardware test setup. All pin numbers are cross-referenced against
the official Espressif user guide (v1.0 and v1.1) and ESP-IDF GPIO documentation.**

> SAFETY NOTE: The ESP32-S3 operates at 3.3 V logic. Do NOT apply 5 V signals to any GPIO.
> Applying 5 V to a GPIO will permanently damage the chip.

---

## 1. Board Orientation and Header Layout

The board has two 22-pin headers:

- **J1** — left side (when USB ports face down), pins numbered 1–22 top to bottom
- **J3** — right side, pins numbered 1–22 top to bottom

J1 pin 1 and J3 pin 1 are at the **same end** of the board (the end with the two USB ports).

```
                     [USB-to-UART]  [USB-OTG]
                     ┌─────────────────────────┐
          J1-1  3V3  │  ●                   ●  │  G    J3-1
          J1-2  3V3  │  ●                   ●  │  TX   J3-2
          J1-3  RST  │  ●                   ●  │  RX   J3-3
          J1-4   4   │  ●                   ●  │   1   J3-4
          J1-5   5   │  ●                   ●  │   2   J3-5
          J1-6   6   │  ●                   ●  │  42   J3-6
          J1-7   7   │  ●                   ●  │  41   J3-7
          J1-8  15   │  ●                   ●  │  40   J3-8
          J1-9  16   │  ●                   ●  │  39   J3-9
         J1-10  17   │  ●                   ●  │  38   J3-10
         J1-11  18   │  ●                   ●  │  37   J3-11
         J1-12   8   │  ●                   ●  │  36   J3-12
         J1-13   3   │  ●                   ●  │  35   J3-13
         J1-14  46   │  ●                   ●  │   0   J3-14
         J1-15   9   │  ●                   ●  │  45   J3-15
         J1-16  10   │  ●                   ●  │  48   J3-16
         J1-17  11   │  ●                   ●  │  47   J3-17
         J1-18  12   │  ●                   ●  │  21   J3-18
         J1-19  13   │  ●                   ●  │  20   J3-19  ← USB_D+  DO NOT USE
         J1-20  14   │  ●                   ●  │  19   J3-20  ← USB_D-  DO NOT USE
         J1-21  5V   │  ●                   ●  │   G   J3-21
         J1-22   G   │  ●                   ●  │   G   J3-22
                     └─────────────────────────┘
```

---

## 2. Power Pins

| Header Pin | Label | Voltage | Notes |
|------------|-------|---------|-------|
| J1-1 | 3V3 | 3.3 V output | Regulated output from onboard LDO; also accepts 3.3 V input |
| J1-2 | 3V3 | 3.3 V output | Same rail as J1-1; two pads for convenience |
| J1-21 | 5V | 5 V input/output | USB-sourced 5 V bus; also accepts external 5 V in |
| J1-22 | G | GND | Ground |
| J3-1 | G | GND | Ground |
| J3-21 | G | GND | Ground |
| J3-22 | G | GND | Ground |

**Power supply rules (mutually exclusive — choose exactly one):**

1. Power via USB (USB-to-UART port or USB-OTG port) — recommended for development
2. Apply 5 V to J1-21 (5V pin) with J1-22 or J3-1 as GND — for external supply
3. Apply 3.3 V to J1-1 or J1-2 (3V3 pin) with a GND pin — bypasses onboard LDO

Do NOT connect more than one power source simultaneously.

---

## 3. EN / RESET Pin

| Header Pin | Label | GPIO | Notes |
|------------|-------|------|-------|
| J1-3 | RST | CHIP_PU (EN) | Active LOW. Internal pull-up present. Pull to GND momentarily to reset the chip. |

The EN pin is not a GPIO number — it is the chip enable line. It resets the entire SoC when pulled low.

---

## 4. Full Header Pinout Table

### J1 (Left Side, 22 pins)

| J1 Pin | Board Label | GPIO | Type | All Functions |
|--------|-------------|------|------|---------------|
| 1 | 3V3 | — | P | 3.3 V power supply |
| 2 | 3V3 | — | P | 3.3 V power supply |
| 3 | RST | — | I | EN (chip enable, active low) |
| 4 | 4 | GPIO4 | I/O/T | RTC_GPIO4, TOUCH4, ADC1_CH3 |
| 5 | 5 | GPIO5 | I/O/T | RTC_GPIO5, TOUCH5, ADC1_CH4 |
| 6 | 6 | GPIO6 | I/O/T | RTC_GPIO6, TOUCH6, ADC1_CH5 |
| 7 | 7 | GPIO7 | I/O/T | RTC_GPIO7, TOUCH7, ADC1_CH6 |
| 8 | 15 | GPIO15 | I/O/T | RTC_GPIO15, U0RTS, ADC2_CH4, XTAL_32K_P |
| 9 | 16 | GPIO16 | I/O/T | RTC_GPIO16, U0CTS, ADC2_CH5, XTAL_32K_N |
| 10 | 17 | GPIO17 | I/O/T | RTC_GPIO17, U1TXD, ADC2_CH6 |
| 11 | 18 | GPIO18 | I/O/T | RTC_GPIO18, U1RXD, ADC2_CH7, CLK_OUT3 |
| 12 | 8 | GPIO8 | I/O/T | RTC_GPIO8, TOUCH8, ADC1_CH7, SUBSPICS1 |
| 13 | 3 | GPIO3 | I/O/T | RTC_GPIO3, TOUCH3, ADC1_CH2 ⚠ STRAPPING PIN |
| 14 | 46 | GPIO46 | I/O/T | ⚠ STRAPPING PIN — see Section 6 |
| 15 | 9 | GPIO9 | I/O/T | RTC_GPIO9, TOUCH9, ADC1_CH8, FSPIHD, SUBSPIHD |
| 16 | 10 | GPIO10 | I/O/T | RTC_GPIO10, TOUCH10, ADC1_CH9, FSPICS0, FSPIIO4, SUBSPICS0 |
| 17 | 11 | GPIO11 | I/O/T | RTC_GPIO11, TOUCH11, ADC2_CH0, FSPID, FSPIIO5, SUBSPID |
| 18 | 12 | GPIO12 | I/O/T | RTC_GPIO12, TOUCH12, ADC2_CH1, FSPICLK, FSPIIO6, SUBSPICLK |
| 19 | 13 | GPIO13 | I/O/T | RTC_GPIO13, TOUCH13, ADC2_CH2, FSPIQ, FSPIIO7, SUBSPIQ |
| 20 | 14 | GPIO14 | I/O/T | RTC_GPIO14, TOUCH14, ADC2_CH3, FSPIWP, FSPIDQS, SUBSPIWP |
| 21 | 5V | — | P | 5 V power supply |
| 22 | G | — | G | Ground |

### J3 (Right Side, 22 pins)

| J3 Pin | Board Label | GPIO | Type | All Functions |
|--------|-------------|------|------|---------------|
| 1 | G | — | G | Ground |
| 2 | TX | GPIO43 | I/O/T | **U0TXD** (UART0 TX default), CLK_OUT1 |
| 3 | RX | GPIO44 | I/O/T | **U0RXD** (UART0 RX default), CLK_OUT2 |
| 4 | 1 | GPIO1 | I/O/T | RTC_GPIO1, TOUCH1, ADC1_CH0 |
| 5 | 2 | GPIO2 | I/O/T | RTC_GPIO2, TOUCH2, ADC1_CH1 |
| 6 | 42 | GPIO42 | I/O/T | MTMS (JTAG) |
| 7 | 41 | GPIO41 | I/O/T | MTDI (JTAG), CLK_OUT1 |
| 8 | 40 | GPIO40 | I/O/T | MTDO (JTAG), CLK_OUT2 |
| 9 | 39 | GPIO39 | I/O/T | MTCK (JTAG), CLK_OUT3, SUBSPICS1 |
| 10 | 38 | GPIO38 | I/O/T | FSPIWP, SUBSPIWP ⚠ RGB LED on v1.1 boards |
| 11 | 37 | GPIO37 | I/O/T | SPIDQS, FSPIQ, SUBSPIQ ⚠ PSRAM on -N8R8/-N16R16 |
| 12 | 36 | GPIO36 | I/O/T | SPIIO7, FSPICLK, SUBSPICLK ⚠ PSRAM on -N8R8/-N16R16 |
| 13 | 35 | GPIO35 | I/O/T | SPIIO6, FSPID, SUBSPID ⚠ PSRAM on -N8R8/-N16R16 |
| 14 | 0 | GPIO0 | I/O/T | RTC_GPIO0 ⚠ STRAPPING PIN — see Section 6 |
| 15 | 45 | GPIO45 | I/O/T | ⚠ STRAPPING PIN — see Section 6 |
| 16 | 48 | GPIO48 | I/O/T | SPICLK_N_DIFF, SUBSPICLK_N_DIFF ⚠ RGB LED on v1.0 boards |
| 17 | 47 | GPIO47 | I/O/T | SPICLK_P_DIFF, SUBSPICLK_P_DIFF |
| 18 | 21 | GPIO21 | I/O/T | RTC_GPIO21 |
| 19 | 20 | GPIO20 | I/O/T | RTC_GPIO20, U1CTS, ADC2_CH9, CLK_OUT1, **USB_D+** |
| 20 | 19 | GPIO19 | I/O/T | RTC_GPIO19, U1RTS, ADC2_CH8, CLK_OUT2, **USB_D-** |
| 21 | G | — | G | Ground |
| 22 | G | — | G | Ground |

---

## 5. GPIO Safety Classification

### 5a. DO NOT USE — Reserved / Dangerous

| GPIO | Header Pin | Reason |
|------|------------|--------|
| GPIO19 | J3-20 | USB D- (USB-JTAG). Using this as GPIO disables USB debug interface. |
| GPIO20 | J3-19 | USB D+ (USB-JTAG). Using this as GPIO disables USB debug interface. |
| GPIO26 | Not exposed | SPI0/1 (internal flash). Not broken out on DevKitC-1. |
| GPIO27 | Not exposed | SPI0/1 (internal flash). Not broken out on DevKitC-1. |
| GPIO28 | Not exposed | SPI0/1 (internal flash). Not broken out on DevKitC-1. |
| GPIO29 | Not exposed | SPI0/1 (internal flash). Not broken out on DevKitC-1. |
| GPIO30 | Not exposed | SPI0/1 (internal flash). Not broken out on DevKitC-1. |
| GPIO31 | Not exposed | SPI0/1 (internal flash). Not broken out on DevKitC-1. |
| GPIO32 | Not exposed | SPI0/1 (internal flash). Not broken out on DevKitC-1. |
| GPIO22–GPIO25 | Not exposed | These GPIO numbers do not exist on ESP32-S3. |

### 5b. AVOID — PSRAM Pins (variant-dependent)

These pins are physically broken out on the header but are **internally wired to PSRAM** on boards with the -N8R8 (8 MB PSRAM) or -N16R16 (16 MB PSRAM) module variants. Using them as general GPIO on those variants causes memory corruption.

| GPIO | Header Pin | Reserved on which variant |
|------|------------|--------------------------|
| GPIO33 | Not exposed on DevKitC-1 | Octal PSRAM variants |
| GPIO34 | Not exposed on DevKitC-1 | Octal PSRAM variants |
| GPIO35 | J3-13 | -N8R8, -N16R16, and -N32R16V (Octal PSRAM) |
| GPIO36 | J3-12 | -N8R8, -N16R16, and -N32R16V (Octal PSRAM) |
| GPIO37 | J3-11 | -N8R8, -N16R16, and -N32R16V (Octal PSRAM) |

**How to determine your variant:** Check the module label silkscreened on the metal shield. Look for "ESP32-S3-WROOM-1-N8R8", "N16R16", etc. If the label contains "R8" or "R16" or "R16V", avoid GPIO35/36/37.

### 5c. CAUTION — Strapping Pins (usable but require attention)

These pins are sampled at power-on/reset to configure boot mode. They are usable as GPIO during normal operation but require care:

| GPIO | Header Pin | Strapping Effect | Default State |
|------|------------|------------------|---------------|
| GPIO0 | J3-14 | LOW at boot = UART Download mode; HIGH = normal boot | Internal pull-up → HIGH (normal boot) |
| GPIO3 | J1-13 | Controls JTAG signal source | — |
| GPIO45 | J3-15 | Controls VDD_SPI voltage (0 = 3.3 V, 1 = 1.8 V) | Pulled LOW externally on DevKitC-1 |
| GPIO46 | J1-14 | LOW disables ROM serial output on UART0 during boot | Pulled LOW → disabled |

**Rule:** If you attach anything to GPIO0, GPIO45, or GPIO46, use a resistor (10 kΩ) so the line can still be driven to the correct boot state. Never hard-wire GPIO0 low through a device without providing a way to release it.

### 5d. CAUTION — Shared with Onboard RGB LED

| GPIO | Header Pin | Board Version | Conflict |
|------|------------|---------------|---------|
| GPIO38 | J3-10 | v1.1 (most current production) | RGB LED is on GPIO38 in v1.1 |
| GPIO48 | J3-16 | v1.0 (older boards) | RGB LED is on GPIO48 in v1.0 |

If you are not using the RGB LED in firmware, this GPIO is free. The LED will simply illuminate if you drive the pin.

### 5e. SAFE — Recommended General-Purpose GPIOs

These GPIOs have no reserved function on the DevKitC-1-U and are safe for general use:

| GPIO | Header Pin | Key Functions Available |
|------|------------|------------------------|
| GPIO1 | J3-4 | ADC1_CH0, TOUCH1, RTC |
| GPIO2 | J3-5 | ADC1_CH1, TOUCH2, RTC |
| GPIO4 | J1-4 | ADC1_CH3, TOUCH4, RTC |
| GPIO5 | J1-5 | ADC1_CH4, TOUCH5, RTC |
| GPIO6 | J1-6 | ADC1_CH5, TOUCH6, RTC |
| GPIO7 | J1-7 | ADC1_CH6, TOUCH7, RTC |
| GPIO8 | J1-12 | ADC1_CH7, TOUCH8, RTC |
| GPIO9 | J1-15 | ADC1_CH8, TOUCH9, RTC |
| GPIO10 | J1-16 | ADC1_CH9, TOUCH10, RTC |
| GPIO17 | J1-10 | ADC2_CH6, U1TXD |
| GPIO18 | J1-11 | ADC2_CH7, U1RXD |
| GPIO21 | J3-18 | RTC; note: may affect Wi-Fi on some modules |
| GPIO38 | J3-10 | General I/O (v1.0 boards); LED pin on v1.1 |
| GPIO39 | J3-9 | JTAG MTCK (JTAG disabled in normal use) |
| GPIO40 | J3-8 | JTAG MTDO (JTAG disabled in normal use) |
| GPIO41 | J3-7 | JTAG MTDI (JTAG disabled in normal use) |
| GPIO42 | J3-6 | JTAG MTMS (JTAG disabled in normal use) |
| GPIO43 | J3-2 | UART0 TX — free if UART0 is redirected |
| GPIO44 | J3-3 | UART0 RX — free if UART0 is redirected |
| GPIO47 | J3-17 | General I/O |
| GPIO48 | J3-16 | General I/O (v1.1 boards); LED pin on v1.0 |

---

## 6. Peripheral Default Pin Assignments

All ESP32-S3 peripherals are fully mux-able to any GPIO via the GPIO Matrix. The values below are the firmware defaults used by ESP-IDF and the Arduino framework unless overridden.

### UART

| Peripheral | Signal | GPIO | Header Pin | Notes |
|-----------|--------|------|------------|-------|
| UART0 | TX | GPIO43 | J3-2 (labeled TX) | Default console output; used by bootloader |
| UART0 | RX | GPIO44 | J3-3 (labeled RX) | Default console input |
| UART0 | RTS | GPIO15 | J1-8 | Optional hardware flow control |
| UART0 | CTS | GPIO16 | J1-9 | Optional hardware flow control |
| UART1 | TX | GPIO17 | J1-10 | ESP-IDF default; reassignable |
| UART1 | RX | GPIO18 | J1-11 | ESP-IDF default; reassignable |

Note: UART0 (GPIO43/GPIO44) is used by the bootloader during flash and reset. Any device connected to these pins will receive bootloader output. Use UART1 or reassign UART0 in firmware if you need a clean UART line.

### I2C

The ESP32-S3 has no fixed I2C pins — any GPIO can be used. ESP-IDF and Arduino framework defaults:

| Peripheral | Signal | GPIO | Header Pin |
|-----------|--------|------|------------|
| I2C0 (Wire) | SDA | GPIO8 | J1-12 |
| I2C0 (Wire) | SCL | GPIO9 | J1-15 |

These are software defaults only. Any free GPIO can serve as SDA or SCL.

### SPI

| Peripheral | Signal | GPIO | Header Pin | Notes |
|-----------|--------|------|------------|-------|
| SPI2 (HSPI) | MOSI | GPIO11 | J1-17 | ESP-IDF default |
| SPI2 (HSPI) | MISO | GPIO13 | J1-19 | ESP-IDF default |
| SPI2 (HSPI) | SCLK | GPIO12 | J1-18 | ESP-IDF default |
| SPI2 (HSPI) | CS | GPIO10 | J1-16 | ESP-IDF default |
| SPI3 (VSPI) | MOSI | GPIO35 | J3-13 | ⚠ Conflicts with PSRAM on R8/R16 variants |
| SPI3 (VSPI) | MISO | GPIO37 | J3-11 | ⚠ Conflicts with PSRAM on R8/R16 variants |
| SPI3 (VSPI) | SCLK | GPIO36 | J3-12 | ⚠ Conflicts with PSRAM on R8/R16 variants |
| SPI3 (VSPI) | CS | GPIO39 | J3-9 | — |

### TWAI (CAN Bus)

The ESP32-S3 has no fixed TWAI pins. Common ESP-IDF example defaults:

| Signal | GPIO | Header Pin | Notes |
|--------|------|------------|-------|
| TWAI TX | GPIO5 | J1-5 | Reassignable to any GPIO |
| TWAI RX | GPIO4 | J1-4 | Reassignable to any GPIO |

---

## 7. ADC-Capable Pins

### ADC1 — Safe to use with Wi-Fi active

ADC1 does not conflict with Wi-Fi. Use ADC1 for all analog measurements when Wi-Fi or BLE is in use.

| ADC1 Channel | GPIO | Header Pin | Also Functions As |
|-------------|------|------------|-------------------|
| ADC1_CH0 | GPIO1 | J3-4 | TOUCH1, RTC_GPIO1 |
| ADC1_CH1 | GPIO2 | J3-5 | TOUCH2, RTC_GPIO2 |
| ADC1_CH2 | GPIO3 | J1-13 | TOUCH3, RTC_GPIO3 ⚠ strapping pin |
| ADC1_CH3 | GPIO4 | J1-4 | TOUCH4, RTC_GPIO4 |
| ADC1_CH4 | GPIO5 | J1-5 | TOUCH5, RTC_GPIO5 |
| ADC1_CH5 | GPIO6 | J1-6 | TOUCH6, RTC_GPIO6 |
| ADC1_CH6 | GPIO7 | J1-7 | TOUCH7, RTC_GPIO7 |
| ADC1_CH7 | GPIO8 | J1-12 | TOUCH8, RTC_GPIO8 |
| ADC1_CH8 | GPIO9 | J1-15 | TOUCH9, RTC_GPIO9 |
| ADC1_CH9 | GPIO10 | J1-16 | TOUCH10, RTC_GPIO10 |

**Best ADC1 pins for general use:** GPIO4 (J1-4), GPIO5 (J1-5), GPIO6 (J1-6), GPIO7 (J1-7) — no competing strapping or touch concerns, clean ADC1.

### ADC2 — Conflicts with Wi-Fi; use only when Wi-Fi is off

| ADC2 Channel | GPIO | Header Pin | Notes |
|-------------|------|------------|-------|
| ADC2_CH0 | GPIO11 | J1-17 | Also SPI2 MOSI default |
| ADC2_CH1 | GPIO12 | J1-18 | Also SPI2 SCLK default |
| ADC2_CH2 | GPIO13 | J1-19 | Also SPI2 MISO default |
| ADC2_CH3 | GPIO14 | J1-20 | — |
| ADC2_CH4 | GPIO15 | J1-8 | Also U0RTS |
| ADC2_CH5 | GPIO16 | J1-9 | Also U0CTS |
| ADC2_CH6 | GPIO17 | J1-10 | Also U1TXD |
| ADC2_CH7 | GPIO18 | J1-11 | Also U1RXD |
| ADC2_CH8 | GPIO19 | J3-20 | **DO NOT USE — USB_D-** |
| ADC2_CH9 | GPIO20 | J3-19 | **DO NOT USE — USB_D+** |

---

## 8. PWM-Capable Pins (LEDC)

All ESP32-S3 GPIOs can generate PWM via the LEDC (LED Control) peripheral. There are 8 PWM channels, each configurable for frequency and duty cycle. Any output-capable GPIO can be assigned to any LEDC channel.

**Restrictions:** Avoid using strapping pins (GPIO0, GPIO3, GPIO45, GPIO46) and USB pins (GPIO19, GPIO20) for PWM.

**Recommended PWM pins** (clean, no conflicts):
- GPIO4 (J1-4), GPIO5 (J1-5), GPIO6 (J1-6), GPIO7 (J1-7)
- GPIO8 (J1-12), GPIO9 (J1-15), GPIO10 (J1-16)
- GPIO17 (J1-10), GPIO18 (J1-11)
- GPIO40 (J3-8), GPIO41 (J3-7), GPIO42 (J3-6), GPIO47 (J3-17)

---

## 9. Wiring Guide for Common Test Configurations

> GENERAL RULE: Always connect grounds first, power last.
> GENERAL RULE: All signal levels must be 3.3 V or lower. The ESP32-S3 is NOT 5 V tolerant.

---

### 9a. DPS-150 PSU → ESP32 Power

The DPS-150 is a DC programmable power supply. Two options:

**Option A — Power via 5V pin (recommended for standalone bench use):**
```
DPS-150 V+ (set to 5.0 V)  →  J1-21  (5V pin)
DPS-150 V-                  →  J1-22 or J3-1 or J3-21 or J3-22  (any GND pin)
```
The onboard LDO converts 5 V to 3.3 V for the chip. Maximum input: do not exceed 6 V.

**Option B — Power via 3V3 pin (bypasses LDO; use when measuring LDO-free power):**
```
DPS-150 V+ (set to 3.30 V)  →  J1-1 or J1-2  (3V3 pin)
DPS-150 V-                   →  J1-22 or J3-1  (GND pin)
```
When using Option B: the DPS-150 becomes the voltage regulator. Set output to exactly 3.30 V. Current limit to 500 mA. The onboard LDO is bypassed — do NOT simultaneously apply 5 V to J1-21.

---

### 9b. Analog Discovery Scope Probe → ESP32 3V3 Rail

Used to monitor power rail noise and confirm supply voltage.

```
Analog Discovery  W1+ (orange)  →  J1-1 or J1-2  (3V3 pin)
Analog Discovery  W1- (orange/white)  →  J1-22 or J3-1  (GND pin, same ground as board)
```

Connect the scope ground to the same GND pin used for the DPS-150 (single-point grounding — see Section 9f). Set the Analog Discovery scope channel to 0–5 V range, DC coupling, to display the 3.3 V rail.

---

### 9c. Analog Discovery UART Decoder → ESP32 TX Pin

Capture UART0 console output from the ESP32 to the Analog Discovery digital logic analyzer.

```
Analog Discovery  DIO 0 (digital channel 0)  →  J3-2  (TX pin = GPIO43 = U0TXD)
Analog Discovery  GND (any)                  →  J3-1  (GND pin, adjacent to TX pin)
```

Configure in Waveforms software:
- Protocol: UART
- Channel: DIO 0
- Baud rate: 115200 (default ESP-IDF console rate)
- Data bits: 8, Parity: None, Stop bits: 1
- Polarity: Standard (idle high)
- Voltage threshold: 1.65 V (midpoint of 3.3 V logic)

Do NOT connect the Analog Discovery DIO pin to the RX pin (GPIO44 / J3-3) unless you are also transmitting data to the ESP32. The TX pin carries data from the ESP32 to your capture device; no power is supplied from the DIO pin.

---

### 9d. Two ESP32 Boards — I2C Bus (SDA ↔ SDA, SCL ↔ SCL)

One board is the I2C master (fixture), one is the I2C slave (DUT). Both run at 3.3 V.

```
Fixture Board  J1-12  (GPIO8 / SDA)  →  DUT Board  J1-12  (GPIO8 / SDA)
Fixture Board  J1-15  (GPIO9 / SCL)  →  DUT Board  J1-15  (GPIO9 / SCL)
Fixture Board  J1-22  (GND)          →  DUT Board  J1-22  (GND)
```

**Pull-up resistors:** I2C requires pull-ups on both SDA and SCL. Add:
```
SDA line  →  4.7 kΩ  →  3.3 V (J1-1 on either board; one resistor total per line)
SCL line  →  4.7 kΩ  →  3.3 V (J1-1 on either board; one resistor total per line)
```

Use 4.7 kΩ for standard mode (100 kHz) and fast mode (400 kHz). Use 2.2 kΩ for fast-plus mode (1 MHz). Only one pull-up resistor per line is needed — do not install pull-ups on both boards simultaneously unless the combined parallel resistance is within spec.

Do NOT cross SDA and SCL. SDA is the data line; SCL is the clock. Swapping them causes the bus to lock up silently.

---

### 9e. Fixture Board GPIO → DUT EN Pin (Reset Control)

The fixture board controls the DUT's reset line using a GPIO output.

```
Fixture Board  (any free GPIO output)  →  DUT Board  J1-3  (RST / EN pin)
Fixture Board  J1-22 (GND)             →  DUT Board  J1-22 (GND)
```

Recommended fixture GPIO for reset control: **GPIO42 (J3-6)** — clean, no ADC or UART conflicts.

**Drive logic:**
- Fixture GPIO HIGH (3.3 V) = DUT running normally (EN has internal pull-up, chip enabled)
- Fixture GPIO LOW (0 V) = DUT held in reset

**Important:** The EN pin has an internal pull-up. You do not need a separate pull-up resistor on the DUT side. The fixture GPIO can directly drive the EN pin. Do not use an open-drain output without a pull-up — the pin must be actively driven high or there must be a pull-up to release reset.

**Reset pulse timing:** Hold EN low for at minimum 100 µs to guarantee a clean reset. A 10 ms pulse is conventional and robust.

**Optional: 100 Ω series resistor** between fixture GPIO and DUT EN pin — protects against shoot-through if both pins are driven simultaneously during a wiring error.

---

### 9f. Scope Ground → ESP32 Ground (Single-Point Grounding)

Single-point grounding (SPG) prevents ground loops that cause measurement noise and false readings.

**Rule:** All instruments (DPS-150, Analog Discovery, logic analyzer, etc.) and both ESP32 boards must connect their ground to a single physical node.

**Procedure:**

1. Choose one GND pin as the star point — J3-1 on the fixture board is convenient (adjacent to TX/RX).
2. Connect the DPS-150 V- to this star point.
3. Connect the Analog Discovery GND to this star point.
4. Connect the DUT board's GND (J3-22 or J3-1) to this star point.
5. Do NOT run separate ground wires from each instrument back to different board GND pins.

```
DPS-150 V-               ──┐
Analog Discovery GND     ──┼──  Fixture Board J3-1 (GND)
Fixture Board J1-22 (GND)──┘         │
                                      └── DUT Board J3-22 (GND)
```

For analog measurements: keep the scope ground wire as short as possible. Long ground leads act as antennas and add noise to ADC readings. If using the Analog Discovery differential inputs (W1+/W1-), the measurement is inherently floating and a separate GND wire is not needed for the scope probes themselves — but the digital DIO grounds must still share the common ground.

---

## 10. Quick-Reference Cheat Sheet

```
┌─────────────────────────────────────────────────────────────┐
│  POWER                                                       │
│  5V input      → J1-21                                      │
│  3V3 output    → J1-1 or J1-2                               │
│  GND           → J1-22, J3-1, J3-21, J3-22                 │
│  EN/RESET      → J1-3  (pull LOW to reset)                  │
├─────────────────────────────────────────────────────────────┤
│  DO NOT USE                                                  │
│  USB_D+  GPIO20  J3-19                                      │
│  USB_D-  GPIO19  J3-20                                      │
│  GPIO26–GPIO32   (not exposed; internal flash)              │
├─────────────────────────────────────────────────────────────┤
│  STRAPPING PINS (use with care)                             │
│  GPIO0   J3-14  (LOW at boot = download mode)               │
│  GPIO3   J1-13  (JTAG source select)                        │
│  GPIO45  J3-15  (VDD_SPI voltage select)                    │
│  GPIO46  J1-14  (UART ROM log enable)                       │
├─────────────────────────────────────────────────────────────┤
│  UART0 (console / bootloader)                               │
│  TX  GPIO43  J3-2  (labeled TX)                             │
│  RX  GPIO44  J3-3  (labeled RX)                             │
├─────────────────────────────────────────────────────────────┤
│  I2C defaults (reassignable)                                │
│  SDA  GPIO8   J1-12                                         │
│  SCL  GPIO9   J1-15                                         │
├─────────────────────────────────────────────────────────────┤
│  ADC1 (Wi-Fi safe) — GPIO1–GPIO10                           │
│  Best safe choices: GPIO4 J1-4, GPIO5 J1-5,                │
│                     GPIO6 J1-6, GPIO7 J1-7                  │
├─────────────────────────────────────────────────────────────┤
│  ADC2 (conflicts with Wi-Fi) — GPIO11–GPIO18                │
│  (GPIO19/GPIO20 are USB; never use for ADC)                 │
├─────────────────────────────────────────────────────────────┤
│  PWM (LEDC): any GPIO — 8 independent channels              │
│  Best choices: GPIO4–GPIO10, GPIO17, GPIO18,                │
│               GPIO40–GPIO42, GPIO47                         │
├─────────────────────────────────────────────────────────────┤
│  RGB LED                                                     │
│  v1.0 boards: GPIO48  J3-16                                 │
│  v1.1 boards: GPIO38  J3-10                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 11. Sources and Revision Notes

- Espressif ESP32-S3-DevKitC-1 User Guide v1.0:
  https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.0.html
- Espressif ESP32-S3-DevKitC-1 User Guide v1.1 (current):
  https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html
- ESP-IDF GPIO Reference (stable, ESP32-S3):
  https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/gpio.html
- Community cross-reference pinout:
  https://github.com/atomic14/esp32-s3-pinouts/blob/main/ESP32-S3-DevKitC-1.md

**Hardware revision note:** The v1.0 and v1.1 header pinouts are identical except for the RGB LED assignment:
- v1.0: RGB LED on GPIO48 (J3-16)
- v1.1: RGB LED on GPIO38 (J3-10)

All other pin positions and functions are unchanged between v1.0 and v1.1.

Document generated: 2026-03-21
