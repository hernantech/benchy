# BenchAgent Wiring Cheatsheet

## Board: ESP32-S3-DevKitC-1-U (two boards: DUT + Fixture)

### Default Pin Assignments (from DUT firmware)
| Function | DUT GPIO | Fixture GPIO | AD2 Pin |
|----------|----------|-------------|---------|
| I2C SDA | GPIO8 (J1-12) | GPIO8 (J1-12) | DIO0 |
| I2C SCL | GPIO9 (J1-15) | GPIO9 (J1-15) | DIO1 |
| UART TX | GPIO17 (J1-10) | GPIO17 (J1-10) | — |
| UART RX | GPIO18 (J1-11) | GPIO18 (J1-11) | — |
| CAN TX | GPIO5 (J1-5) | GPIO5 (J1-5) | — |
| CAN RX | GPIO6 (J1-6) | GPIO6 (J1-6) | — |
| DUT Reset | — | GPIO7 (J1-7) → DUT EN (J1-3) | — |
| Timing GPIO | GPIO4 (J1-4) | — | Scope CH1 |

### Power Wiring
- **DPS-150 → DUT**: PSU (+) → J1-1 (3V3 pin), PSU (-) → J1-22 (GND)
  - Direct 3.3V power, bypasses onboard LDO
  - NEVER exceed 3.6V — will fry the ESP32
- **Fixture**: powered via USB (separate from DUT power)
- **AD2 GND**: connect to J1-22 (same GND bus as DPS-150)

### Scope Probe Wiring
- **AD2 Scope CH1+ (1+)** → DUT GPIO4 (J1-4) — timing measurement
- **AD2 Scope CH2+ (2+)** → DUT J1-1 (3V3 rail) — voltage monitoring
- **AD2 Scope GND (1- or 2-)** → DUT J1-22 (GND) — single-point ground

### UART Monitoring
- **AD2 DIO0** → DUT GPIO17/TX (J1-10) — captures boot messages + debug output
- AD2 UART decoder: baud=115200, DIO0 as RX

### I2C Bus (two boards)
- DUT GPIO8 (SDA) ↔ Fixture GPIO8 (SDA) — direct wire
- DUT GPIO9 (SCL) ↔ Fixture GPIO9 (SCL) — direct wire
- External pull-ups: 4.7kΩ to 3.3V on each line (or use internal pull-ups if wires are short)
- AD2 DIO0 → SDA bus, AD2 DIO1 → SCL bus — for scope/protocol analysis

### Reset Control
- Fixture GPIO7 (J1-7) → DUT RST/EN (J1-3)
- Fixture pulls LOW for 100ms to reset DUT, then releases to high-Z
- DUT has internal pull-up on EN — will boot when released

### Analog Discovery (Original) Wire Colors
| Color | Signal | Use |
|-------|--------|-----|
| Orange | 1+ (Scope CH1+) | Timing pulse (GPIO4) or voltage measurement |
| Orange/White | 1- (Scope CH1-) | Connect to GND for single-ended measurement |
| Blue | 2+ (Scope CH2+) | Second channel (3V3 rail monitoring) |
| Blue/White | 2- (Scope CH2-) | Connect to GND |
| Yellow | W1 (Waveform Gen 1) | Inject test signals (keep ≤3.3V for ESP32!) |
| Red | V+ (+5V fixed) | NOT for powering ESP32 (50mA limit) |
| Black (×4) | GND | Common ground — connect at least one to circuit |
| Pink | DIO 0 | UART RX capture / I2C SDA monitor |
| Green | DIO 1 | I2C SCL monitor |
| Purple | DIO 2 | General digital capture |
| Brown | DIO 3 | General digital capture |

### Safety Rules
- ESP32-S3 is 3.3V logic — NEVER apply 5V to any GPIO
- DPS-150 safety clamps: max 5.5V, max 1.0A (enforced in software)
- Don't use GPIO19/20 (USB), GPIO0/3/45/46 (strapping)
- ADC1 pins (GPIO1-10): safe with WiFi. ADC2 pins: conflict with WiFi
- Single-point ground: all GNDs connect at one physical point
