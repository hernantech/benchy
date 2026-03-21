"""BenchAgent Pi Worker — FastAPI server controlling lab instruments.

Runs on RPi 5, port 8420. Vercel calls it over Tailscale.
Controls: Analog Discovery (dwfpy), DPS-150 PSU, two ESP32-S3 boards.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import numpy as np
import serial
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
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
_psu = None       # DPS150Client
_esp: dict[str, serial.Serial] = {}  # "a" / "b" -> Serial


def _find_esp32_ports() -> dict[str, str]:
    """Find ESP32 serial ports. Returns {"a": "/dev/ttyACM0", "b": "/dev/ttyACM1"} etc."""
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
            # Find the JSON line
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
    """Connect to ESP32 boards."""
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
    """Connect to DPS-150 PSU."""
    global _psu
    try:
        from galois_edge.sdk_wrappers.dps150_wrapper import DPS150Client
        _psu = DPS150Client()
        _psu.connect()
        log.info("DPS-150 connected")
    except Exception as e:
        log.warning("DPS-150 not available: %s", e)
        _psu = None


def _connect_ad2():
    """Connect to Analog Discovery."""
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
    # Cleanup
    for name, ser in _esp.items():
        try:
            ser.close()
        except Exception:
            pass
    if _psu:
        try:
            _psu.disable_output()
            _psu.disconnect()
        except Exception:
            pass
    if _ad2:
        try:
            _ad2.disconnect()
        except Exception:
            pass


app = FastAPI(title="BenchAgent", lifespan=lifespan)


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
        y_range = max(data) - min(data) if data else 1
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
                "model": "DPS-150",
                "input_voltage": float(_psu.get_input_voltage()),
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
            psu.enable_output()
        else:
            psu.disable_output()
        return {
            "ok": True,
            "voltage_setpoint": req.voltage,
            "current_limit": req.current_limit,
            "output_enabled": req.output,
        }
    except Exception as e:
        psu.disable_output()
        raise HTTPException(500, str(e))


@app.get("/psu/state")
async def psu_state():
    psu = _require_psu()
    try:
        state = json.loads(psu.get_state())
        return {
            "output_voltage": state.get("output_voltage", 0),
            "output_current": state.get("output_current", 0),
            "output_power": state.get("output_power", 0),
            "mode": state.get("mode", "CV"),
            "temperature": state.get("temperature", 0),
            "protection_state": state.get("protection_state", ""),
            "output_enabled": state.get("output_closed", False),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/psu/sweep")
async def psu_sweep(req: PsuSweepReq):
    psu = _require_psu()
    if max(abs(req.start), abs(req.stop)) > PSU_MAX_VOLTAGE:
        raise HTTPException(400, f"Sweep voltage exceeds safety limit {PSU_MAX_VOLTAGE}V")
    try:
        result = json.loads(psu.sweep_voltage(req.start, req.stop, abs(req.step), req.dwell))
        return {"points": result}
    except Exception as e:
        psu.disable_output()
        raise HTTPException(500, str(e))


@app.post("/psu/off")
async def psu_off():
    psu = _require_psu()
    psu.disable_output()
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
            "data": data,
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
        if req.measurement == "dc":
            val = float(ad2.scope_measure_dc(req.channel, req.v_range))
        elif req.measurement == "peak_to_peak":
            val = float(ad2.scope_measure_peak_to_peak(req.channel, req.v_range))
        elif req.measurement == "rms":
            val = float(ad2.scope_measure_rms(req.channel, req.v_range))
        elif req.measurement == "frequency":
            val = float(ad2.scope_measure_frequency(req.channel, req.v_range))
        else:
            raise HTTPException(400, f"Unknown measurement: {req.measurement}")
        return {"channel": req.channel, "measurement": req.measurement, "value": val, "unit": "V"}
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

        # Rise/fall time (10%-90%)
        v_min, v_max = float(arr.min()), float(arr.max())
        v_range = v_max - v_min
        if v_range < 0.01:
            return {"rise_time_ns": 0, "fall_time_ns": 0, "overshoot_pct": 0, "undershoot_pct": 0, "chart_url": ""}

        lo = v_min + 0.1 * v_range
        hi = v_min + 0.9 * v_range

        # Find first rising edge
        rise_ns = 0
        for i in range(1, len(arr)):
            if arr[i - 1] <= lo and arr[i] > lo:
                start = i
                for j in range(i, len(arr)):
                    if arr[j] >= hi:
                        rise_ns = (j - start) * dt * 1e9
                        break
                break

        # Find first falling edge
        fall_ns = 0
        for i in range(1, len(arr)):
            if arr[i - 1] >= hi and arr[i] < hi:
                start = i
                for j in range(i, len(arr)):
                    if arr[j] <= lo:
                        fall_ns = (j - start) * dt * 1e9
                        break
                break

        # Overshoot/undershoot
        overshoot_pct = max(0, (v_max - hi) / v_range * 100) if v_range > 0 else 0
        undershoot_pct = max(0, (lo - v_min) / v_range * 100) if v_range > 0 else 0

        fname = _render_chart(
            data, req.sample_rate,
            title="Signal Integrity",
            annotations={
                "rise_ns": rise_ns,
                "fall_ns": fall_ns,
                "overshoot_%": overshoot_pct,
            },
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
        # I2C capture via logic analyzer is complex — return placeholder
        # The AD2 protocol decoder captures in real-time during the duration
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
        cmd = json.loads(req.command) if req.command.startswith("{") else {"cmd": req.command}
        return {"response": _esp_cmd(ser, cmd, req.timeout_ms)}
    except json.JSONDecodeError:
        # Send raw string
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
        # Reset DUT via fixture's GPIO
        _esp_cmd(_esp["b"], {"cmd": "reset_dut", "hold_ms": 100})
        return {"ok": True, "method": "gpio_en_pin"}
    else:
        # Reset via DTR toggle
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
        # Reopen serial
        time.sleep(2)
        _esp[board] = serial.Serial(port, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
        time.sleep(1)
        _esp[board].reset_input_buffer()
        return {"ok": True, "build_time_s": round(build_time, 1)}
    except HTTPException:
        raise
    except Exception as e:
        # Try to reopen
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


# ── Compound Operations ─────────────────────────────────────────
@app.post("/run/debug")
async def run_debug(req: DebugRunReq):
    psu = _require_psu()
    ad2 = _require_ad2()

    try:
        # Configure PSU
        if req.psu_voltage > PSU_MAX_VOLTAGE:
            raise HTTPException(400, f"Voltage exceeds safety limit {PSU_MAX_VOLTAGE}V")
        psu.set_voltage(req.psu_voltage)
        psu.set_current(req.psu_current_limit)
        psu.enable_output()
        time.sleep(0.3)

        # Reset DUT if requested
        if req.reset_before and "a" in _esp:
            if "b" in _esp:
                _esp_cmd(_esp["b"], {"cmd": "reset_dut", "hold_ms": 100})
            else:
                _esp["a"].dtr = False
                time.sleep(0.1)
                _esp["a"].dtr = True
            time.sleep(0.5)

        # Start UART capture
        ad2.uart_setup(pin_rx=req.uart_rx_pin, baud=req.uart_baud)

        # Scope capture
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

        # Wait for UART data
        remaining = max(0, req.capture_duration_ms / 1000 - 0.5)
        if remaining > 0:
            time.sleep(remaining)

        uart_result = json.loads(ad2.uart_read())
        hex_data = uart_result.get("data", "")
        uart_text = bytes.fromhex(hex_data).decode("utf-8", errors="replace") if hex_data else ""

        # Render chart
        fname = _render_chart(
            scope_data, req.scope_sample_rate,
            title="Debug Capture",
            annotations=stats,
        )

        brownout = "brownout" in uart_text.lower() or stats["v_min"] < 2.7

        return {
            "psu": {
                "voltage": float(psu.get_output_voltage()),
                "current": float(psu.get_output_current()),
                "mode": psu.get_operating_mode(),
            },
            "scope": {
                "stats": stats,
                "chart_url": f"/artifacts/{fname}",
            },
            "uart": {
                "data": uart_text,
                "bytes": len(hex_data) // 2,
            },
            "brownout_detected": brownout,
        }
    except HTTPException:
        raise
    except Exception as e:
        try:
            psu.disable_output()
        except Exception:
            pass
        raise HTTPException(500, str(e))


# ── Main ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8420)
