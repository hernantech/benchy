# Digilent Analog Discovery (Original / AD1) — Wiring Reference

This document covers the **original Analog Discovery (AD1, Rev C)**, not the Analog Discovery 2 or 3.
Source: Digilent official pinout document (October 11, 2012, Rev C).

---

## Physical Connector

The AD1 has a single **2×15 (30-pin) 100-mil MTE header** on the device edge.
The included fly-wire cable is a color-coded 30-wire assembly that breaks each pin out to an individual jumper wire.

The connector is read as two rows of 15 pins each:

- **Top row** (odd side, labeled on device): pins `1+  2+  GND  V+  W1  GND  TI  0  1  2  3  4  5  6  7`
- **Bottom row** (even side, labeled on device): pins `1-  2-  GND  V-  W2  GND  TO  8  9  10  11  12  13  14  15`

> Pin 1 is at the end of the connector closest to the USB port.

---

## Complete Pin/Signal/Wire-Color Table

The connector labels use short names that map to the signal groups below.

| Row | Position | Label | Function | Wire Color |
|-----|----------|-------|----------|------------|
| Top | 1 | 1+ | Scope CH1 positive | Orange |
| Top | 2 | 2+ | Scope CH2 positive | Blue |
| Top | 3 | GND | Ground | Black |
| Top | 4 | V+ | Power supply +5 V DC | Red |
| Top | 5 | W1 | Waveform Generator 1 | Yellow |
| Top | 6 | GND | Ground | Black |
| Top | 7 | TI | Trigger In | Gray |
| Top | 8 | 0 | Digital I/O DIO 0 | Pink |
| Top | 9 | 1 | Digital I/O DIO 1 | Green |
| Top | 10 | 2 | Digital I/O DIO 2 | Purple |
| Top | 11 | 3 | Digital I/O DIO 3 | Brown |
| Top | 12 | 4 | Digital I/O DIO 4 | Pink |
| Top | 13 | 5 | Digital I/O DIO 5 | Green |
| Top | 14 | 6 | Digital I/O DIO 6 | Purple |
| Top | 15 | 7 | Digital I/O DIO 7 | Brown |
| Bot | 1 | 1- | Scope CH1 negative | Orange/White stripe |
| Bot | 2 | 2- | Scope CH2 negative | Blue/White stripe |
| Bot | 3 | GND | Ground | Black |
| Bot | 4 | V- | Power supply −5 V DC | White |
| Bot | 5 | W2 | Waveform Generator 2 | Yellow/White stripe |
| Bot | 6 | GND | Ground | Black |
| Bot | 7 | TO | Trigger Out | Gray/White stripe |
| Bot | 8 | 8 | Digital I/O DIO 8 | Pink/White stripe |
| Bot | 9 | 9 | Digital I/O DIO 9 | Green/White stripe |
| Bot | 10 | 10 | Digital I/O DIO 10 | Purple/White stripe |
| Bot | 11 | 11 | Digital I/O DIO 11 | Brown/White stripe |
| Bot | 12 | 12 | Digital I/O DIO 12 | Pink/White stripe |
| Bot | 13 | 13 | Digital I/O DIO 13 | Green/White stripe |
| Bot | 14 | 14 | Digital I/O DIO 14 | Purple/White stripe |
| Bot | 15 | 15 | Digital I/O DIO 15 | Brown/White stripe |

> The digital I/O colors cycle Pink → Green → Purple → Brown for DIO 0–3, then repeat for DIO 4–7.
> The bottom-row DIO wires (DIO 8–15) are the same colors but each has a white stripe.

---

## Signal Groups Summary

### Oscilloscope Inputs (differential)

Both channels are **fully differential**. Always connect at least one GND wire from the AD1 to circuit ground.

| Signal | Label | Wire Color |
|--------|-------|------------|
| CH1 positive | 1+ | Orange |
| CH1 negative | 1− | Orange / White stripe |
| CH2 positive | 2+ | Blue |
| CH2 negative | 2− | Blue / White stripe |

- Input impedance: 1 MΩ ‖ 24 pF
- Input range: ±25 V (±50 V differential)
- Resolution: 14-bit, 100 MS/s
- Bandwidth with fly-wire: ~5 MHz (−3 dB)

**Typical single-ended use:** Connect `1+` to the signal you want to measure and `1−` to circuit ground (or any GND wire).

### Waveform Generators (AWG)

| Signal | Label | Wire Color |
|--------|-------|------------|
| AWG output 1 | W1 | Yellow |
| AWG output 2 | W2 | Yellow / White stripe |

- Output range: ±5 V
- Output impedance: ~22 Ω (low)
- Resolution: 14-bit, 100 MS/s
- Bandwidth: ~5 MHz with fly-wire

Each AWG output is single-ended; the circuit under test must share a GND with the AD1.

### Power Supplies

| Signal | Label | Wire Color | Voltage (AD1) |
|--------|-------|------------|----------------|
| Positive supply | V+ | Red | Fixed +5 V DC |
| Negative supply | V− | V− | Fixed −5 V DC |

- Maximum current: 50 mA per rail (USB-powered)
- **AD1 supplies are fixed at ±5 V** (not adjustable). This is the primary hardware difference from the AD2.

### Ground Pins

There are **4 ground wires** total, all black:

| Position | Row |
|----------|-----|
| Top row position 3 | Between 2+ and V+ |
| Top row position 6 | Between W1 and TI |
| Bottom row position 3 | Between 2− and V− |
| Bottom row position 6 | Between W2 and TO |

Use any GND wire to establish a common reference. For the oscilloscope to work correctly at least one GND must be connected to the circuit being measured.

### Trigger Pins

| Signal | Label | Wire Color |
|--------|-------|------------|
| Trigger In | TI | Gray |
| Trigger Out | TO | Gray / White stripe |

- Trigger In: accepts an external trigger signal
- Trigger Out: outputs a trigger signal to synchronize other equipment
- Logic levels: 3.3 V CMOS

### Digital I/O (DIO 0–15)

All 16 channels are bidirectional and software-configurable as logic analyzer inputs or pattern generator outputs.

| DIO | Row | Wire Color |
|-----|-----|------------|
| DIO 0 | Top | Pink |
| DIO 1 | Top | Green |
| DIO 2 | Top | Purple |
| DIO 3 | Top | Brown |
| DIO 4 | Top | Pink |
| DIO 5 | Top | Green |
| DIO 6 | Top | Purple |
| DIO 7 | Top | Brown |
| DIO 8 | Bottom | Pink / White stripe |
| DIO 9 | Bottom | Green / White stripe |
| DIO 10 | Bottom | Purple / White stripe |
| DIO 11 | Bottom | Brown / White stripe |
| DIO 12 | Bottom | Pink / White stripe |
| DIO 13 | Bottom | Green / White stripe |
| DIO 14 | Bottom | Purple / White stripe |
| DIO 15 | Bottom | Brown / White stripe |

- Logic: 3.3 V CMOS, inputs are 5 V tolerant
- Rate: up to 100 MS/s

---

## Quick-Connect Guide: AD1 to ESP32 Dev Board

### Typical oscilloscope measurement

```
AD1  →  ESP32
1+   →  Signal to measure (e.g. GPIO output)
1−   →  GND (ESP32 GND pin)
GND  →  GND (ESP32 GND pin)  ← also tie AD1 ground to circuit
```

### Waveform generator driving ESP32 input

```
AD1  →  ESP32
W1   →  Target GPIO (input mode, or signal source)
GND  →  GND
```

> W1 output is ±5 V capable — ESP32 GPIOs are 3.3 V max. Add a voltage divider or clamp if driving a GPIO directly, or keep the AWG output ≤ 3.3 V in WaveForms.

### Power supply to ESP32 breadboard circuit (3.3 V logic circuit)

```
AD1  →  Breadboard
V+   →  VCC rail (the AD1 fixed +5 V; use a regulator for 3.3 V circuits)
GND  →  GND rail
```

> The AD1 V+ is fixed at +5 V, 50 mA max. It cannot power an ESP32 module directly (ESP32 draws more current at startup). Use it only for small peripheral circuits.

### Logic analyzer / digital capture

```
AD1 DIO 0–7  →  ESP32 GPIO signals to monitor (3.3 V)
AD1 GND      →  ESP32 GND
```

---

## AD1 vs AD2: Key Differences

| Feature | AD1 (Original) | AD2 |
|---------|---------------|-----|
| Power supplies | Fixed ±5 V only | Variable 0.5–5 V / −0.5 to −5 V |
| External power input | No | Yes (5 V barrel jack, up to 700 mA) |
| Max supply current (USB) | 50 mA per rail | 150 mA per rail |
| Enclosure | Small, black plastic (fragile) | Larger, durable polycarbonate |
| Analog bandwidth | ~5 MHz (fly-wire) | ~5 MHz (fly-wire) |
| Pinout layout | Identical 2×15 header | Identical 2×15 header |
| Wire colors | Same scheme | Same scheme |
| WaveForms software | Compatible | Compatible |

The **pinout connector layout and wire colors are identical** between AD1 and AD2. Any wiring diagram for one applies to the other for all signals except power supply behavior.

---

## Wire Color Quick-Reference Card

| Color | Signal |
|-------|--------|
| Orange | CH1+ (scope) |
| Orange/White | CH1− (scope) |
| Blue | CH2+ (scope) |
| Blue/White | CH2− (scope) |
| Yellow | W1 (waveform gen) |
| Yellow/White | W2 (waveform gen) |
| Red | V+ (+5 V supply) |
| White | V− (−5 V supply) |
| Black | GND (×4 wires) |
| Gray | Trigger In |
| Gray/White | Trigger Out |
| Pink, Green, Purple, Brown | DIO 0–3 (repeating for 4–7) |
| Pink/W, Green/W, Purple/W, Brown/W | DIO 8–15 |
