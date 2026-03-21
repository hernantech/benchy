"""BenchAgent Pi Worker — FastAPI server controlling lab instruments.

Runs on RPi 5, port 8420. Vercel calls it over Tailscale.
Controls: Analog Discovery (dwfpy), DPS-150 PSU, two ESP32-S3 boards.
"""

from __future__ import annotations

import json
import logging
import os
import time
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import serial
import base64

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

# ── Constants ────────────────────────────────────────────────────
PSU_MAX_VOLTAGE = 5.5
PSU_MAX_CURRENT = 1.0
ARTIFACTS_DIR = Path("/tmp/benchagent/artifacts")
SERIAL_BAUD = 115200
SERIAL_TIMEOUT = 2.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("benchagent")

# ── Global device handles ────────────────────────────────────────
_ad2 = None       # DigilentDwfClient
_psu = None       # DPS150
_esp: dict[str, serial.Serial] = {}  # "a" / "b" -> Serial

# Camera frame buffer — latest JPEG from the Flutter app
_camera_lock = threading.Lock()
_camera_frame: bytes | None = None
_camera_last_ts: float = 0.0
_camera_connected = False


def _find_esp32_ports() -> dict[str, str]:
    """Find ESP32 serial ports by querying status. Returns {"a": "/dev/...", "b": "/dev/..."}."""
    import glob
    ports = sorted(glob.glob("/dev/ttyACM*"))
    result = {}
    for port in ports:
        try:
            ser = serial.Serial(port, SERIAL_BAUD, timeout=2)
            time.sleep(0.3)
            ser.reset_input_buffer()
            ser.write(b'{"cmd":"status"}\n')
            time.sleep(0.5)
            resp = b""
            while ser.in_waiting:
                resp += ser.readline()
            ser.close()
            text = resp.decode("utf-8", errors="replace").strip()
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("{"):
                    data = json.loads(line)
                    board = data.get("board", "")
                    if board == "dut":
                        result["a"] = port
                    elif board == "fixture":
                        result["b"] = port
                    break
        except Exception as e:
            log.warning("Could not identify %s: %s", port, e)
    return result


def _connect_esp32s():
    global _esp
    ports = _find_esp32_ports()
    for name, port in ports.items():
        try:
            ser = serial.Serial(port, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
            time.sleep(0.3)
            ser.reset_input_buffer()
            _esp[name] = ser
            log.info("ESP32 %s connected on %s", name, port)
        except Exception as e:
            log.warning("Failed to open ESP32 %s on %s: %s", name, port, e)


def _connect_psu():
    """Connect to DPS-150 PSU using the dps150 library."""
    global _psu
    try:
        from dps150 import DPS150
        _psu = DPS150()
        _psu.open()
        log.info("DPS-150 connected: %s (fw %s)", _psu.model_name, _psu.firmware_version)
    except Exception as e:
        log.warning("DPS-150 not available: %s", e)
        _psu = None


def _connect_ad2():
    """Connect to Analog Discovery using the daemon-clean wrapper."""
    global _ad2
    try:
        from galois_edge.sdk_wrappers.digilent_dwf_wrapper import DigilentDwfClient
        _ad2 = DigilentDwfClient()
        _ad2.connect()
        log.info("Analog Discovery connected")
    except Exception as e:
        log.warning("Analog Discovery not available: %s", e)
        _ad2 = None


# ── Lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    _connect_ad2()
    _connect_psu()
    _connect_esp32s()
    yield
    for ser in _esp.values():
        try:
            ser.close()
        except Exception:
            pass
    if _psu:
        try:
            _psu.disable()
            _psu.close()
        except Exception:
            pass
    if _ad2:
        try:
            _ad2.disconnect()
        except Exception:
            pass


app = FastAPI(title="BenchAgent", lifespan=lifespan)

# Allow all origins — demo, Tailscale is the security boundary
from starlette.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Helpers ──────────────────────────────────────────────────────
def _require_psu():
    if _psu is None:
        raise HTTPException(503, "DPS-150 not connected")
    return _psu


def _require_ad2():
    if _ad2 is None:
        raise HTTPException(503, "Analog Discovery not connected")
    return _ad2


def _require_esp(board: str):
    if board not in _esp:
        raise HTTPException(503, f"ESP32 '{board}' not connected (available: {list(_esp.keys())})")
    return _esp[board]


def _esp_cmd(ser: serial.Serial, cmd: dict, timeout_ms: int = 5000) -> dict:
    """Send JSON command to ESP32, return parsed response."""
    ser.reset_input_buffer()
    ser.write((json.dumps(cmd) + "\n").encode())
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if ser.in_waiting:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if line.startswith("{"):
                return json.loads(line)
        time.sleep(0.01)
    raise HTTPException(504, "ESP32 command timeout")


def _render_chart(
    data: list[float],
    sample_rate: float,
    title: str = "Scope Capture",
    ylabel: str = "Voltage (V)",
    annotations: dict | None = None,
) -> str:
    """Render waveform to PNG, return filename."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = np.arange(len(data)) / sample_rate * 1000  # ms
    fig, ax = plt.subplots(figsize=(8, 4), facecolor="#1a1a2e")
    ax.set_facecolor("#16213e")
    ax.plot(t, data, color="#00ff88", linewidth=0.5)
    ax.set_xlabel("Time (ms)", color="white")
    ax.set_ylabel(ylabel, color="white")
    ax.set_title(title, color="white")
    ax.tick_params(colors="white")
    ax.grid(True, alpha=0.3, color="#444")
    for spine in ax.spines.values():
        spine.set_color("#444")

    if annotations:
        text_parts = []
        for k, v in annotations.items():
            if isinstance(v, float):
                text_parts.append(f"{k}: {v:.3f}")
            else:
                text_parts.append(f"{k}: {v}")
        ax.text(
            0.02, 0.98, "\n".join(text_parts),
            transform=ax.transAxes, fontsize=8, color="#00ff88",
            verticalalignment="top", fontfamily="monospace",
            bbox=dict(boxstyle="round", facecolor="#1a1a2e", alpha=0.8),
        )

    fname = f"scope_{int(time.time()*1000)}.png"
    fpath = ARTIFACTS_DIR / fname
    fig.savefig(fpath, dpi=100, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return fname


def _psu_state_dict(psu) -> dict:
    """Read current PSU state as a dict."""
    return {
        "output_voltage": psu.output_voltage or 0,
        "output_current": psu.output_current or 0,
        "output_power": psu.output_power or 0,
        "mode": psu.mode or "CV",
        "temperature": psu.temperature or 0,
        "protection_state": psu.protection_state or "",
        "output_enabled": psu.output_closed or False,
    }


# ── Pydantic models ──────────────────────────────────────────────
class PsuConfigureReq(BaseModel):
    voltage: float
    current_limit: float = 0.5
    output: bool = True


class PsuSweepReq(BaseModel):
    start: float
    stop: float
    step: float
    dwell: float = 0.5


class ScopeCaptureReq(BaseModel):
    channel: int = 0
    v_range: float = 5.0
    samples: int = 8192
    sample_rate: float = 1_000_000
    trigger_level: float = 1.5
    trigger_channel: int = -1
    offset: float = 0.0


class ScopeMeasureReq(BaseModel):
    channel: int = 0
    measurement: str = "dc"
    v_range: float = 5.0


class ScopePulseReq(BaseModel):
    channel: int = 0
    trigger_level: float = 1.5
    trigger_edge: str = "rising"
    timeout_ms: int = 5000
    v_range: float = 5.0
    sample_rate: float = 10_000_000


class UartCaptureReq(BaseModel):
    rx_pin: int = 0
    baud: int = 115200
    duration_ms: int = 3000


class I2cCaptureReq(BaseModel):
    sda_pin: int = 0
    scl_pin: int = 1
    duration_ms: int = 1000


class SignalIntegrityReq(BaseModel):
    channel: int = 0
    samples: int = 8192
    sample_rate: float = 10_000_000
    v_range: float = 5.0


class EspSerialSendReq(BaseModel):
    command: str
    timeout_ms: int = 5000


class EspSerialReadReq(BaseModel):
    timeout_ms: int = 3000
    until: str = "\n"


class EspFlashReq(BaseModel):
    project_path: str
    target: str = "esp32s3"
    port: str = "/dev/ttyACM0"


class DebugRunReq(BaseModel):
    psu_voltage: float = 3.3
    psu_current_limit: float = 0.15
    scope_channel: int = 0
    scope_v_range: float = 5.0
    scope_samples: int = 8192
    scope_sample_rate: float = 1_000_000
    scope_trigger_level: float = 1.5
    uart_rx_pin: int = 0
    uart_baud: int = 115200
    capture_duration_ms: int = 3000
    reset_before: bool = True


class BenchmarkRunReq(BaseModel):
    kernel: str = "baseline"
    iterations: int = 1000
    scope_channel: int = 0
    scope_trigger_level: float = 1.5
    measure_power: bool = True


# ── Capabilities (tool discovery for the LLM agent) ─────────────
CAPABILITIES = {
    "bench_id": "benchagent-pi",
    "description": "BenchCI hardware test bench — RPi 5 controlling lab instruments for automated hardware testing",
    "tools": [
        {
            "name": "psu_configure",
            "endpoint": "POST /psu/configure",
            "description": "Set DPS-150 power supply voltage and current limit. Enables/disables output.",
            "parameters": {
                "voltage": {"type": "number", "unit": "V", "min": 0, "max": 5.5, "required": True},
                "current_limit": {"type": "number", "unit": "A", "min": 0, "max": 1.0, "default": 0.5},
                "output": {"type": "boolean", "default": True, "description": "Enable output"},
            },
        },
        {
            "name": "psu_state",
            "endpoint": "GET /psu/state",
            "description": "Read live PSU telemetry: voltage, current, power, temperature, mode, protection state.",
            "parameters": {},
        },
        {
            "name": "psu_sweep",
            "endpoint": "POST /psu/sweep",
            "description": "Sweep voltage from start to stop, measuring at each step. Find brownout thresholds.",
            "parameters": {
                "start": {"type": "number", "unit": "V", "required": True},
                "stop": {"type": "number", "unit": "V", "required": True},
                "step": {"type": "number", "unit": "V", "required": True},
                "dwell": {"type": "number", "unit": "s", "default": 0.5},
            },
        },
        {
            "name": "psu_off",
            "endpoint": "POST /psu/off",
            "description": "Immediately disable PSU output (safety).",
            "parameters": {},
        },
        {
            "name": "scope_capture",
            "endpoint": "POST /scope/capture",
            "description": "Oscilloscope single-shot capture. Returns waveform data, stats (Vmin/Vmax/Vpp/Vrms), and rendered chart PNG.",
            "parameters": {
                "channel": {"type": "integer", "min": 0, "max": 1, "default": 0, "description": "0=CH1, 1=CH2"},
                "v_range": {"type": "number", "unit": "V", "default": 5.0},
                "samples": {"type": "integer", "default": 8192},
                "sample_rate": {"type": "number", "unit": "Hz", "default": 1000000},
                "trigger_level": {"type": "number", "unit": "V", "default": 1.5},
                "trigger_channel": {"type": "integer", "default": -1, "description": "-1 = auto trigger"},
                "offset": {"type": "number", "unit": "V", "default": 0.0},
            },
        },
        {
            "name": "scope_measure",
            "endpoint": "POST /scope/measure",
            "description": "Quick scalar measurement without full capture.",
            "parameters": {
                "channel": {"type": "integer", "default": 0},
                "measurement": {"type": "enum", "values": ["dc", "peak_to_peak", "rms", "frequency"], "required": True},
                "v_range": {"type": "number", "unit": "V", "default": 5.0},
            },
        },
        {
            "name": "scope_pulse_width",
            "endpoint": "POST /scope/pulse_width",
            "description": "Capture and measure a GPIO timing pulse width. Used for benchmarking execution time.",
            "parameters": {
                "channel": {"type": "integer", "default": 0},
                "trigger_level": {"type": "number", "unit": "V", "default": 1.5},
                "v_range": {"type": "number", "unit": "V", "default": 5.0},
                "sample_rate": {"type": "number", "unit": "Hz", "default": 10000000},
            },
        },
        {
            "name": "scope_signal_integrity",
            "endpoint": "POST /scope/signal_integrity",
            "description": "Analyze signal integrity: rise/fall time (ns), overshoot/undershoot (%). Use 10MHz+ sample rate.",
            "parameters": {
                "channel": {"type": "integer", "default": 0},
                "samples": {"type": "integer", "default": 8192},
                "sample_rate": {"type": "number", "unit": "Hz", "default": 10000000},
                "v_range": {"type": "number", "unit": "V", "default": 5.0},
            },
        },
        {
            "name": "uart_capture",
            "endpoint": "POST /uart/capture",
            "description": "Capture UART data from a DIO pin using the Analog Discovery protocol decoder.",
            "parameters": {
                "rx_pin": {"type": "integer", "default": 0, "description": "AD2 DIO pin number for UART RX"},
                "baud": {"type": "integer", "default": 115200},
                "duration_ms": {"type": "integer", "default": 3000},
            },
        },
        {
            "name": "i2c_capture",
            "endpoint": "POST /i2c/capture",
            "description": "Capture I2C bus traffic using the Analog Discovery protocol decoder.",
            "parameters": {
                "sda_pin": {"type": "integer", "default": 0, "description": "AD2 DIO pin for SDA"},
                "scl_pin": {"type": "integer", "default": 1, "description": "AD2 DIO pin for SCL"},
                "duration_ms": {"type": "integer", "default": 1000},
            },
        },
        {
            "name": "esp32_dut_command",
            "endpoint": "POST /esp32/a/serial/send",
            "description": "Send a JSON command to ESP32-S3 DUT board. Supports: pwm, i2c_init/scan/write/read, uart_init/send/recv, can_init/send/recv, gpio_mode/write/read, adc_read, wifi_connect/disconnect, status, ping, reset.",
            "parameters": {
                "command": {"type": "string", "required": True, "description": "JSON command string, e.g. {\"cmd\":\"pwm\",\"pin\":4,\"freq\":1000,\"duty\":50}"},
                "timeout_ms": {"type": "integer", "default": 5000},
            },
        },
        {
            "name": "esp32_fixture_command",
            "endpoint": "POST /esp32/b/serial/send",
            "description": "Send a JSON command to ESP32-S3 fixture board. Supports: i2c_slave_init/set_resp/set_mode/log, reset_dut, load (PWM→MOSFET), can_init/send/recv, gpio, adc, status.",
            "parameters": {
                "command": {"type": "string", "required": True, "description": "JSON command string"},
                "timeout_ms": {"type": "integer", "default": 5000},
            },
        },
        {
            "name": "esp32_reset",
            "endpoint": "POST /esp32/{board}/reset",
            "description": "Reset an ESP32 board. Board A reset via fixture GPIO (EN pin), Board B via DTR.",
            "parameters": {
                "board": {"type": "enum", "values": ["a", "b"], "required": True},
            },
        },
        {
            "name": "run_debug",
            "endpoint": "POST /run/debug",
            "description": "Full debug cycle: configure PSU → reset DUT → capture scope + UART simultaneously → detect brownout. Returns PSU state, scope stats + chart, UART log, brownout flag.",
            "parameters": {
                "psu_voltage": {"type": "number", "unit": "V", "default": 3.3},
                "psu_current_limit": {"type": "number", "unit": "A", "default": 0.15},
                "scope_channel": {"type": "integer", "default": 0},
                "capture_duration_ms": {"type": "integer", "default": 3000},
                "reset_before": {"type": "boolean", "default": True},
            },
        },
        {
            "name": "run_benchmark",
            "endpoint": "POST /run/benchmark",
            "description": "Run firmware benchmark: send kernel to ESP32, capture timing pulse on scope, measure power via PSU. Returns execution time, per-iteration timing, power consumption.",
            "parameters": {
                "kernel": {"type": "string", "required": True},
                "iterations": {"type": "integer", "default": 1000},
                "scope_channel": {"type": "integer", "default": 0},
                "scope_trigger_level": {"type": "number", "default": 1.5},
                "measure_power": {"type": "boolean", "default": True},
            },
        },
    ],
}


@app.get("/capabilities")
async def capabilities():
    """Return structured tool catalog for LLM agent discovery."""
    # Merge static capability definitions with live device status
    health = {}
    if _ad2:
        health["ad2"] = True
    if _psu:
        health["psu"] = True
    for name in ("a", "b"):
        if name in _esp and _esp[name].is_open:
            health[f"esp32_{name}"] = True

    return {**CAPABILITIES, "connected_devices": health}


# ── Health ───────────────────────────────────────────────────────
@app.get("/health")
async def health():
    devices = {}
    if _ad2:
        try:
            info = json.loads(_ad2.get_device_info())
            devices["ad2"] = {"connected": True, "serial": info.get("serial", "unknown")}
        except Exception:
            devices["ad2"] = {"connected": False}
    else:
        devices["ad2"] = {"connected": False}

    if _psu:
        try:
            devices["psu"] = {
                "connected": True,
                "model": _psu.model_name or "DPS-150",
                "input_voltage": _psu.output_voltage,
            }
        except Exception:
            devices["psu"] = {"connected": False}
    else:
        devices["psu"] = {"connected": False}

    for name in ("a", "b"):
        key = f"esp32_{name}"
        if name in _esp and _esp[name].is_open:
            devices[key] = {"connected": True, "port": _esp[name].port}
        else:
            devices[key] = {"connected": False}

    return {"status": "ok", "devices": devices}


# ── PSU ──────────────────────────────────────────────────────────
@app.post("/psu/configure")
async def psu_configure(req: PsuConfigureReq):
    psu = _require_psu()
    if req.voltage > PSU_MAX_VOLTAGE:
        raise HTTPException(400, f"Voltage {req.voltage}V exceeds safety limit {PSU_MAX_VOLTAGE}V")
    if req.current_limit > PSU_MAX_CURRENT:
        raise HTTPException(400, f"Current {req.current_limit}A exceeds safety limit {PSU_MAX_CURRENT}A")
    try:
        psu.set_voltage(req.voltage)
        psu.set_current(req.current_limit)
        if req.output:
            psu.enable()
        else:
            psu.disable()
        time.sleep(0.2)  # let telemetry update
        return {
            "ok": True,
            "voltage_setpoint": req.voltage,
            "current_limit": req.current_limit,
            "output_enabled": req.output,
        }
    except Exception as e:
        try:
            psu.disable()
        except Exception:
            pass
        raise HTTPException(500, str(e))


@app.get("/psu/state")
async def psu_state():
    psu = _require_psu()
    try:
        psu.get_all()
        time.sleep(0.15)
        return _psu_state_dict(psu)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/psu/sweep")
async def psu_sweep(req: PsuSweepReq):
    psu = _require_psu()
    if max(abs(req.start), abs(req.stop)) > PSU_MAX_VOLTAGE:
        raise HTTPException(400, f"Sweep voltage exceeds safety limit {PSU_MAX_VOLTAGE}V")
    try:
        psu.enable()
        points = psu.sweep_voltage(req.start, req.stop, abs(req.step), dwell=req.dwell)
        result = []
        for pt in points:
            result.append({
                "voltage_set": pt.voltage_set,
                "voltage_meas": pt.voltage_measured,
                "current": pt.current,
                "power": pt.power,
                "temp": pt.temperature,
            })
        return {"points": result}
    except Exception as e:
        try:
            psu.disable()
        except Exception:
            pass
        raise HTTPException(500, str(e))


@app.post("/psu/off")
async def psu_off():
    psu = _require_psu()
    psu.disable()
    return {"ok": True}


# ── Scope ────────────────────────────────────────────────────────
@app.post("/scope/capture")
async def scope_capture(req: ScopeCaptureReq):
    ad2 = _require_ad2()
    try:
        raw = ad2.scope_acquire(
            channel=req.channel,
            v_range=req.v_range,
            samples=req.samples,
            sample_rate=req.sample_rate,
            trigger_level=req.trigger_level,
            trigger_channel=req.trigger_channel,
            offset=req.offset,
        )
        data = json.loads(raw)
        arr = np.array(data)
        stats = {
            "v_min": float(arr.min()),
            "v_max": float(arr.max()),
            "v_mean": float(arr.mean()),
            "v_pp": float(arr.max() - arr.min()),
            "v_rms": float(np.sqrt(np.mean(arr ** 2))),
        }
        fname = _render_chart(
            data, req.sample_rate,
            title=f"Ch{req.channel} Capture",
            annotations=stats,
        )
        return {
            "data": data[:500] if len(data) > 500 else data,  # truncate for JSON size
            "sample_rate": req.sample_rate,
            "sample_count": len(data),
            "stats": stats,
            "chart_url": f"/artifacts/{fname}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/scope/measure")
async def scope_measure(req: ScopeMeasureReq):
    ad2 = _require_ad2()
    try:
        measure_fn = {
            "dc": ad2.scope_measure_dc,
            "peak_to_peak": ad2.scope_measure_peak_to_peak,
            "rms": ad2.scope_measure_rms,
            "frequency": ad2.scope_measure_frequency,
        }.get(req.measurement)
        if not measure_fn:
            raise HTTPException(400, f"Unknown measurement: {req.measurement}")
        val = float(measure_fn(req.channel, req.v_range))
        unit = "Hz" if req.measurement == "frequency" else "V"
        return {"channel": req.channel, "measurement": req.measurement, "value": val, "unit": unit}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/scope/pulse_width")
async def scope_pulse_width(req: ScopePulseReq):
    ad2 = _require_ad2()
    try:
        raw = ad2.scope_acquire(
            channel=req.channel,
            v_range=req.v_range,
            samples=8192,
            sample_rate=req.sample_rate,
            trigger_level=req.trigger_level,
            trigger_channel=req.channel,
        )
        data = json.loads(raw)
        arr = np.array(data)
        threshold = req.trigger_level
        above = arr > threshold
        transitions = np.diff(above.astype(int))
        rising = np.where(transitions == 1)[0]
        falling = np.where(transitions == -1)[0]

        pulse_width_s = 0.0
        if len(rising) > 0 and len(falling) > 0:
            start_idx = rising[0]
            end_candidates = falling[falling > start_idx]
            if len(end_candidates) > 0:
                end_idx = end_candidates[0]
                pulse_width_s = (end_idx - start_idx) / req.sample_rate

        fname = _render_chart(
            data, req.sample_rate,
            title="Pulse Capture",
            annotations={"pulse_ms": pulse_width_s * 1000},
        )
        return {
            "pulse_width_ms": pulse_width_s * 1000,
            "pulse_width_us": pulse_width_s * 1_000_000,
            "v_high": float(arr.max()),
            "v_low": float(arr.min()),
            "chart_url": f"/artifacts/{fname}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/scope/signal_integrity")
async def scope_signal_integrity(req: SignalIntegrityReq):
    ad2 = _require_ad2()
    try:
        raw = ad2.scope_acquire(
            channel=req.channel,
            v_range=req.v_range,
            samples=req.samples,
            sample_rate=req.sample_rate,
        )
        data = json.loads(raw)
        arr = np.array(data)
        dt = 1.0 / req.sample_rate

        v_min, v_max = float(arr.min()), float(arr.max())
        v_range = v_max - v_min
        if v_range < 0.01:
            return {"rise_time_ns": 0, "fall_time_ns": 0, "overshoot_pct": 0, "undershoot_pct": 0, "chart_url": ""}

        lo = v_min + 0.1 * v_range
        hi = v_min + 0.9 * v_range

        rise_ns = 0.0
        for i in range(1, len(arr)):
            if arr[i - 1] <= lo < arr[i]:
                for j in range(i, len(arr)):
                    if arr[j] >= hi:
                        rise_ns = (j - i) * dt * 1e9
                        break
                break

        fall_ns = 0.0
        for i in range(1, len(arr)):
            if arr[i - 1] >= hi > arr[i]:
                for j in range(i, len(arr)):
                    if arr[j] <= lo:
                        fall_ns = (j - i) * dt * 1e9
                        break
                break

        overshoot_pct = max(0, (v_max - hi) / v_range * 100)
        undershoot_pct = max(0, (lo - v_min) / v_range * 100)

        fname = _render_chart(
            data, req.sample_rate,
            title="Signal Integrity",
            annotations={"rise_ns": rise_ns, "fall_ns": fall_ns, "overshoot_%": overshoot_pct},
        )
        return {
            "rise_time_ns": rise_ns,
            "fall_time_ns": fall_ns,
            "overshoot_pct": overshoot_pct,
            "undershoot_pct": undershoot_pct,
            "chart_url": f"/artifacts/{fname}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Protocol Decoders ────────────────────────────────────────────
@app.post("/uart/capture")
async def uart_capture(req: UartCaptureReq):
    ad2 = _require_ad2()
    try:
        ad2.uart_setup(pin_rx=req.rx_pin, baud=req.baud)
        time.sleep(req.duration_ms / 1000)
        result = json.loads(ad2.uart_read())
        hex_data = result.get("data", "")
        text = bytes.fromhex(hex_data).decode("utf-8", errors="replace") if hex_data else ""
        return {"data": text, "bytes_received": len(hex_data) // 2}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/i2c/capture")
async def i2c_capture(req: I2cCaptureReq):
    ad2 = _require_ad2()
    try:
        ad2.i2c_setup(pin_scl=req.scl_pin, pin_sda=req.sda_pin)
        time.sleep(req.duration_ms / 1000)
        return {"transactions": [], "bus_errors": 0, "note": "I2C capture requires active bus traffic"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── ESP32 Control ────────────────────────────────────────────────
@app.post("/esp32/{board}/serial/send")
async def esp32_serial_send(board: str, req: EspSerialSendReq):
    ser = _require_esp(board)
    try:
        cmd = json.loads(req.command) if req.command.strip().startswith("{") else {"cmd": req.command}
        return {"response": _esp_cmd(ser, cmd, req.timeout_ms)}
    except json.JSONDecodeError:
        ser.reset_input_buffer()
        ser.write((req.command + "\n").encode())
        time.sleep(0.5)
        resp = ""
        while ser.in_waiting:
            resp += ser.readline().decode("utf-8", errors="replace")
        return {"response": resp.strip()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/esp32/{board}/serial/read")
async def esp32_serial_read(board: str, req: EspSerialReadReq):
    ser = _require_esp(board)
    data = b""
    deadline = time.time() + req.timeout_ms / 1000
    while time.time() < deadline:
        if ser.in_waiting:
            chunk = ser.readline()
            data += chunk
            if req.until.encode() in chunk:
                break
        time.sleep(0.01)
    text = data.decode("utf-8", errors="replace")
    return {"data": text, "bytes": len(data)}


@app.post("/esp32/{board}/reset")
async def esp32_reset(board: str):
    ser = _require_esp(board)
    if board == "a" and "b" in _esp:
        _esp_cmd(_esp["b"], {"cmd": "reset_dut", "hold_ms": 100})
        return {"ok": True, "method": "gpio_en_pin"}
    else:
        ser.dtr = False
        time.sleep(0.1)
        ser.dtr = True
        time.sleep(1)
        ser.reset_input_buffer()
        return {"ok": True, "method": "dtr"}


@app.post("/esp32/{board}/flash")
async def esp32_flash(board: str, req: EspFlashReq):
    ser = _require_esp(board)
    port = ser.port
    ser.close()
    try:
        import subprocess
        start = time.time()
        result = subprocess.run(
            ["pio", "run", "-t", "upload", "--upload-port", port],
            cwd=req.project_path,
            capture_output=True, text=True, timeout=300,
        )
        build_time = time.time() - start
        if result.returncode != 0:
            raise HTTPException(500, f"Flash failed: {result.stderr[-500:]}")
        time.sleep(2)
        _esp[board] = serial.Serial(port, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
        time.sleep(1)
        _esp[board].reset_input_buffer()
        return {"ok": True, "build_time_s": round(build_time, 1)}
    except HTTPException:
        raise
    except Exception as e:
        try:
            _esp[board] = serial.Serial(port, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
        except Exception:
            pass
        raise HTTPException(500, str(e))


# ── Artifacts ────────────────────────────────────────────────────
@app.get("/artifacts/{filename}")
async def get_artifact(filename: str):
    fpath = ARTIFACTS_DIR / filename
    if not fpath.exists():
        raise HTTPException(404, "Artifact not found")
    return FileResponse(fpath)


# ── Compound: Debug Run ──────────────────────────────────────────
@app.post("/run/debug")
async def run_debug(req: DebugRunReq):
    psu = _require_psu()
    ad2 = _require_ad2()

    try:
        # Safety check
        if req.psu_voltage > PSU_MAX_VOLTAGE:
            raise HTTPException(400, f"Voltage exceeds safety limit {PSU_MAX_VOLTAGE}V")

        # Configure PSU
        psu.set_voltage(req.psu_voltage)
        psu.set_current(req.psu_current_limit)
        psu.enable()
        time.sleep(0.3)

        # Reset DUT if requested
        if req.reset_before and "a" in _esp:
            if "b" in _esp:
                _esp_cmd(_esp["b"], {"cmd": "reset_dut", "hold_ms": 100})
            else:
                _esp["a"].dtr = False
                time.sleep(0.1)
                _esp["a"].dtr = True
            time.sleep(0.3)

        # Start UART capture and scope capture concurrently
        uart_text = ""
        uart_bytes = 0

        def _capture_uart():
            nonlocal uart_text, uart_bytes
            try:
                ad2.uart_setup(pin_rx=req.uart_rx_pin, baud=req.uart_baud)
                time.sleep(req.capture_duration_ms / 1000)
                result = json.loads(ad2.uart_read())
                hex_data = result.get("data", "")
                uart_text = bytes.fromhex(hex_data).decode("utf-8", errors="replace") if hex_data else ""
                uart_bytes = len(hex_data) // 2
            except Exception as e:
                uart_text = f"[UART capture error: {e}]"

        # Run UART capture in a thread while we do the scope capture
        # Note: AD2 can do scope + UART simultaneously on different subsystems
        uart_thread = threading.Thread(target=_capture_uart)
        uart_thread.start()

        # Give UART a moment to start, then capture scope
        time.sleep(0.2)
        raw = ad2.scope_acquire(
            channel=req.scope_channel,
            v_range=req.scope_v_range,
            samples=req.scope_samples,
            sample_rate=req.scope_sample_rate,
            trigger_level=req.scope_trigger_level,
            trigger_channel=req.scope_channel,
        )
        scope_data = json.loads(raw)
        arr = np.array(scope_data)
        stats = {
            "v_min": float(arr.min()),
            "v_max": float(arr.max()),
            "v_pp": float(arr.max() - arr.min()),
            "v_mean": float(arr.mean()),
        }

        # Wait for UART thread
        uart_thread.join(timeout=req.capture_duration_ms / 1000 + 2)

        # PSU state
        psu.get_all()
        time.sleep(0.15)

        # Render chart
        fname = _render_chart(
            scope_data, req.scope_sample_rate,
            title="Debug Capture",
            annotations=stats,
        )

        brownout = "brownout" in uart_text.lower() or stats["v_min"] < 2.7

        return {
            "psu": _psu_state_dict(psu),
            "scope": {
                "stats": stats,
                "data": scope_data[:500] if len(scope_data) > 500 else scope_data,
                "chart_url": f"/artifacts/{fname}",
            },
            "uart": {
                "data": uart_text,
                "bytes": uart_bytes,
            },
            "brownout_detected": brownout,
        }
    except HTTPException:
        raise
    except Exception as e:
        try:
            psu.disable()
        except Exception:
            pass
        raise HTTPException(500, str(e))


# ── Compound: Benchmark Run ──────────────────────────────────────
@app.post("/run/benchmark")
async def run_benchmark(req: BenchmarkRunReq):
    """Run a benchmark kernel on the DUT and measure execution time + power."""
    ad2 = _require_ad2()
    dut = _require_esp("a")

    try:
        # Tell ESP32 to run the kernel — it should toggle a GPIO pin during execution
        cmd = {"cmd": "benchmark", "kernel": req.kernel, "iterations": req.iterations}
        dut.reset_input_buffer()
        dut.write((json.dumps(cmd) + "\n").encode())

        # Small delay for ESP32 to set up, then capture the timing pulse
        time.sleep(0.1)

        raw = ad2.scope_acquire(
            channel=req.scope_channel,
            v_range=5.0,
            samples=8192,
            sample_rate=10_000_000,
            trigger_level=req.scope_trigger_level,
            trigger_channel=req.scope_channel,
        )
        data = json.loads(raw)
        arr = np.array(data)

        # Measure pulse width
        threshold = req.scope_trigger_level
        above = arr > threshold
        transitions = np.diff(above.astype(int))
        rising = np.where(transitions == 1)[0]
        falling = np.where(transitions == -1)[0]

        pulse_width_s = 0.0
        if len(rising) > 0 and len(falling) > 0:
            start_idx = rising[0]
            end_candidates = falling[falling > start_idx]
            if len(end_candidates) > 0:
                end_idx = end_candidates[0]
                pulse_width_s = (end_idx - start_idx) / 10_000_000

        total_ms = pulse_width_s * 1000
        per_iter_us = (pulse_width_s * 1_000_000) / max(req.iterations, 1)

        # Read ESP32's own timing report
        esp_report = {}
        deadline = time.time() + 5
        while time.time() < deadline:
            if dut.in_waiting:
                line = dut.readline().decode("utf-8", errors="replace").strip()
                if line.startswith("{"):
                    esp_report = json.loads(line)
                    break
            time.sleep(0.01)

        # Power measurement
        power_data = {}
        if req.measure_power and _psu:
            _psu.get_all()
            time.sleep(0.15)
            avg_current_ma = (_psu.output_current or 0) * 1000
            avg_power_mw = (_psu.output_power or 0) * 1000
            energy_per_iter_uj = (avg_power_mw * per_iter_us) / 1000 if per_iter_us > 0 else 0
            power_data = {
                "avg_current_ma": round(avg_current_ma, 2),
                "avg_power_mw": round(avg_power_mw, 2),
                "energy_per_iter_uj": round(energy_per_iter_uj, 3),
            }

        fname = _render_chart(
            data, 10_000_000,
            title=f"Benchmark: {req.kernel} ({req.iterations} iters)",
            annotations={"pulse_ms": total_ms, "per_iter_us": per_iter_us},
        )

        return {
            "kernel": req.kernel,
            "iterations": req.iterations,
            "execution": {
                "total_ms": round(total_ms, 3),
                "per_iteration_us": round(per_iter_us, 3),
                "chart_url": f"/artifacts/{fname}",
            },
            "power": power_data,
            "esp32_report": esp_report,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Camera (video stream from Flutter app) ───────────────────────

class CameraAnalyzeReq(BaseModel):
    prompt: str = "Describe what you see on this lab bench. Identify instruments, wiring, and any issues."
    model: str = "gemini-3.1-flash-lite-preview"


@app.websocket("/camera/ws")
async def camera_ws(ws: WebSocket):
    """Receive JPEG frames from the Flutter app over WebSocket."""
    global _camera_frame, _camera_last_ts, _camera_connected
    await ws.accept()
    _camera_connected = True
    log.info("Camera connected")

    try:
        while True:
            # Expect binary JPEG frames
            data = await ws.receive_bytes()
            if len(data) < 100:
                continue  # skip tiny/invalid frames

            with _camera_lock:
                _camera_frame = data
                _camera_last_ts = time.time()

    except WebSocketDisconnect:
        log.info("Camera disconnected")
    except Exception as e:
        log.warning("Camera WebSocket error: %s", e)
    finally:
        _camera_connected = False


@app.get("/camera/latest")
async def camera_latest():
    """Return the latest camera frame as JPEG."""
    with _camera_lock:
        frame = _camera_frame
        ts = _camera_last_ts

    if frame is None:
        raise HTTPException(404, "No camera frame available. Connect the Flutter app first.")

    age = time.time() - ts
    if age > 30:
        raise HTTPException(410, f"Camera frame is stale ({age:.0f}s old). Is the app still streaming?")

    return Response(content=frame, media_type="image/jpeg",
                    headers={"X-Frame-Age-Ms": str(int(age * 1000))})


@app.post("/camera/snapshot")
async def camera_snapshot():
    """Save the latest camera frame to artifacts and return the URL."""
    with _camera_lock:
        frame = _camera_frame
        ts = _camera_last_ts

    if frame is None:
        raise HTTPException(404, "No camera frame available")

    fname = f"camera_{int(ts * 1000)}.jpg"
    fpath = ARTIFACTS_DIR / fname
    fpath.write_bytes(frame)

    return {
        "ok": True,
        "artifact_url": f"/artifacts/{fname}",
        "frame_age_ms": int((time.time() - ts) * 1000),
        "size_bytes": len(frame),
    }


@app.post("/camera/analyze")
async def camera_analyze(req: CameraAnalyzeReq):
    """Send the latest camera frame to Gemini vision for analysis."""
    with _camera_lock:
        frame = _camera_frame
        ts = _camera_last_ts

    if frame is None:
        raise HTTPException(404, "No camera frame available. Connect the Flutter app first.")

    age = time.time() - ts
    if age > 30:
        raise HTTPException(410, f"Camera frame is stale ({age:.0f}s old)")

    # Save snapshot as artifact
    fname = f"camera_{int(ts * 1000)}.jpg"
    fpath = ARTIFACTS_DIR / fname
    fpath.write_bytes(frame)

    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", ""))
        model = genai.GenerativeModel(req.model)

        # Send image to Gemini vision
        import PIL.Image
        import io as _io
        img = PIL.Image.open(_io.BytesIO(frame))

        response = model.generate_content([req.prompt, img])

        return {
            "ok": True,
            "analysis": response.text,
            "model": req.model,
            "artifact_url": f"/artifacts/{fname}",
            "frame_age_ms": int(age * 1000),
        }
    except Exception as e:
        log.error("Camera analysis failed: %s", e)
        raise HTTPException(500, f"Vision analysis failed: {e}")


@app.get("/camera/status")
async def camera_status():
    """Check camera connection status."""
    with _camera_lock:
        has_frame = _camera_frame is not None
        age = time.time() - _camera_last_ts if has_frame else None

    return {
        "connected": _camera_connected,
        "has_frame": has_frame,
        "frame_age_ms": int(age * 1000) if age is not None else None,
    }


# ── Firmware Management (used by firmware pipeline) ──────────────

class FirmwareWriteReq(BaseModel):
    project_path: str
    files: dict  # {filename: code_string}


class FirmwareCompileReq(BaseModel):
    project_path: str
    target: str = "esp32s3"


@app.post("/firmware/write")
async def firmware_write(req: FirmwareWriteReq):
    """Write firmware source files to disk for compilation."""
    project = Path(req.project_path)
    project.mkdir(parents=True, exist_ok=True)

    written = []
    for filename, code in req.files.items():
        fpath = project / filename
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(code)
        written.append(filename)

    return {"ok": True, "files_written": written, "project_path": str(project)}


@app.post("/firmware/compile")
async def firmware_compile(req: FirmwareCompileReq):
    """Compile firmware using PlatformIO. Returns build result."""
    import subprocess

    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(404, f"Project path does not exist: {req.project_path}")

    try:
        start = time.time()
        result = subprocess.run(
            ["pio", "run"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=180,
        )
        build_time = time.time() - start

        if result.returncode == 0:
            # Try to find binary size
            size_bytes = 0
            for line in result.stdout.split("\n"):
                if "bytes" in line.lower() and ("flash" in line.lower() or "program" in line.lower()):
                    import re as _re
                    m = _re.search(r"(\d+)\s*bytes", line)
                    if m:
                        size_bytes = int(m.group(1))
                        break

            return {
                "ok": True,
                "build_time_s": round(build_time, 1),
                "size_bytes": size_bytes,
                "output": result.stdout[-2000:],
            }
        else:
            return {
                "ok": False,
                "build_time_s": round(build_time, 1),
                "output": result.stdout[-2000:],
                "errors": result.stderr[-2000:],
            }
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Build timed out (180s)")
    except FileNotFoundError:
        raise HTTPException(503, "PlatformIO (pio) not found. Install with: pip install platformio")
    except Exception as e:
        raise HTTPException(500, str(e))


# ── RCA Module ───────────────────────────────────────────────────
try:
    from rca.rca_endpoints import rca_router
    app.include_router(rca_router, prefix="/rca")
    log.info("RCA module loaded — /rca/* endpoints available")
except ImportError:
    log.warning("RCA module not found — /rca/* endpoints unavailable")


# ── Main ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8420)
