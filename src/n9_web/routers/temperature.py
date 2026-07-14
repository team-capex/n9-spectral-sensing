"""Temperature control endpoints for the spectral boards.

Setpoints apply immediately (no confirm step per the agreed safety policy).
Reads are cached for 1 s server-side so the UI poll doesn't hammer serial.
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, HTTPException, Request

from n9_web.routers.deps import get_hw
from n9_web.schemas import TemperatureTarget

router = APIRouter()

_cache_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "data": None}
_CACHE_TTL_S = 1.0

# Active setpoints, board_id → {target_c, max_power_pct}.
# Boards ALWAYS connect with heaters off (auto_heat=False), so a board with no
# entry here has no target. Cleared whenever the boards reconnect.
_targets: dict = {}
_seen_generation: dict = {"gen": -1}


def _board_runtimes(hw):
    mgr = hw.get_boards()
    if hw.boards_generation != _seen_generation["gen"]:
        # Fresh connection: firmware targets were cleared — reset bookkeeping.
        _seen_generation["gen"] = hw.boards_generation
        _targets.clear()
        _invalidate_cache()
    return {b.cfg.board_id: b for b in mgr._boards}


@router.get("/temperature")
def read_temperatures(request: Request) -> list:
    hw = get_hw(request)
    now = time.monotonic()
    with _cache_lock:
        if _cache["data"] is not None and now - _cache["ts"] < _CACHE_TTL_S:
            return _cache["data"]

    with hw.manual_op("boards"):
        out = []
        for board_id, rt in _board_runtimes(hw).items():
            try:
                # Each board has 4 NTC probes on pins 1, 2, 4, 5. The firmware
                # PID (multi mode, used by set_temperature_target) regulates on
                # their average — report both the probes and that average.
                probes = {
                    str(pin): rt.sensor.get_temperature(pin, multi=False)
                    for pin in (1, 2, 4, 5)
                }
                temp = sum(probes.values()) / len(probes)
                duty = rt.sensor.get_duty_pct()
            except Exception as exc:
                out.append({"board_id": board_id, "error": str(exc)})
                continue
            override = _targets.get(board_id)
            target = override["target_c"] if override is not None else None
            if target is None:
                status = "off"
            elif abs(temp - target) <= 1.0:
                status = "at_target"
            else:
                status = "heating"
            out.append({
                "board_id": board_id,
                "temp_c": temp,
                "probes": probes,
                "duty_pct": duty,
                "target_temp_c": target,
                "max_power_pct": (
                    override["max_power_pct"] if override is not None
                    else rt.cfg.max_power_pct
                ),
                "status": status,
            })

    with _cache_lock:
        _cache["ts"] = now
        _cache["data"] = out
    return out


@router.post("/temperature/{board_id}/target")
def set_target(board_id: str, body: TemperatureTarget, request: Request) -> dict:
    hw = get_hw(request)
    with hw.manual_op("boards"):
        runtimes = _board_runtimes(hw)
        rt = runtimes.get(board_id)
        if rt is None:
            raise HTTPException(404, f"Unknown board '{board_id}'. "
                                     f"Connected: {list(runtimes)}")
        max_power = body.max_power_pct if body.max_power_pct is not None else rt.cfg.max_power_pct
        sensor_pin = body.sensor_pin if body.sensor_pin is not None else rt.cfg.sensor_pin
        rt.sensor.set_temperature_target(body.target_c, max_power, sensor_pin)
        _targets[board_id] = {"target_c": body.target_c, "max_power_pct": max_power}
    _invalidate_cache()
    return {"ok": True, "board_id": board_id, "target_c": body.target_c,
            "max_power_pct": max_power}


@router.delete("/temperature/{board_id}/target")
def clear_target(board_id: str, request: Request) -> dict:
    hw = get_hw(request)
    with hw.manual_op("boards"):
        runtimes = _board_runtimes(hw)
        rt = runtimes.get(board_id)
        if rt is None:
            raise HTTPException(404, f"Unknown board '{board_id}'.")
        rt.sensor.clear_temperature_target()
        _targets[board_id] = {"target_c": None, "max_power_pct": rt.cfg.max_power_pct}
    _invalidate_cache()
    return {"ok": True, "board_id": board_id, "target_c": None}


@router.post("/temperature/all-off")
def all_heaters_off(request: Request) -> dict:
    hw = get_hw(request)
    with hw.manual_op("boards"):
        for board_id, rt in _board_runtimes(hw).items():
            rt.sensor.clear_temperature_target()
            _targets[board_id] = {
                "target_c": None, "max_power_pct": rt.cfg.max_power_pct,
            }
    _invalidate_cache()
    return {"ok": True}


def _invalidate_cache() -> None:
    with _cache_lock:
        _cache["data"] = None
