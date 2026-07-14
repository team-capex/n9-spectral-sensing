"""Peristaltic and stepper pump endpoints."""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, HTTPException, Request

from n9_web.routers.deps import get_hw
from n9_web.schemas import (
    MultiStepperRequest,
    PeristalticRequest,
    PrimeRequest,
    StepperRequest,
)

router = APIRouter()

STEPPER_ROLES = {1: "dose", 2: "water", 3: "dye 1", 4: "dye 2"}

_env_cache_lock = threading.Lock()
_env_cache: dict = {"ts": 0.0, "data": None}
_ENV_TTL_S = 10.0


@router.get("/pumps")
def pumps_info(request: Request) -> dict:
    hw = get_hw(request)
    peristaltic = {
        name: {
            "index": int(entry["index"]),
            "flow_rate_ml_per_s": float(entry["flow_rate_ml_per_s"]),
            "offset_ml": float(entry.get("offset_ml", 0.0)),
        }
        for name, entry in hw.raw_cfg.get("peristaltic_pumps", {}).items()
    }
    # Environment readings are cached and only refreshed when the fluidic
    # controller is already connected — never trigger a connect from a poll.
    env = None
    now = time.monotonic()
    with _env_cache_lock:
        if _env_cache["data"] is not None and now - _env_cache["ts"] < _ENV_TTL_S:
            env = _env_cache["data"]
    if env is None and hw._fluidic is not None and hw.fluidic_lock.acquire(blocking=False):
        try:
            fl = hw._fluidic
            env = {"temp_c": fl.get_temperature(), "humidity_pct": fl.get_humidity()}
            with _env_cache_lock:
                _env_cache["ts"] = now
                _env_cache["data"] = env
        except Exception:
            env = None
        finally:
            hw.fluidic_lock.release()
    return {
        "peristaltic": peristaltic,
        "steppers": [{"no": n, "role": role} for n, role in STEPPER_ROLES.items()],
        "environment": env,
        "max_manual_volume_ml": float(
            hw.raw_cfg.get("web", {}).get("max_manual_volume_ml", 25.0)
        ),
    }


@router.post("/pumps/peristaltic/{name}")
def run_peristaltic(name: str, body: PeristalticRequest, request: Request) -> dict:
    hw = get_hw(request)
    if name not in hw.raw_cfg.get("peristaltic_pumps", {}):
        raise HTTPException(404, f"Unknown pump '{name}'.")
    max_ml = float(hw.raw_cfg.get("web", {}).get("max_manual_volume_ml", 25.0))
    if body.volume_ml > max_ml:
        raise HTTPException(400, f"volume_ml exceeds manual cap of {max_ml} mL.")
    with hw.manual_op("robot"):  # peristaltic pumps run through the robot outputs
        hw.get_peristaltic().fill_peristaltic(name, body.volume_ml)
    return {"ok": True, "pump": name, "volume_ml": body.volume_ml}


@router.post("/pumps/stepper/multi")
def run_multi_stepper(body: MultiStepperRequest, request: Request) -> dict:
    hw = get_hw(request)
    max_ml = float(hw.raw_cfg.get("web", {}).get("max_manual_volume_ml", 25.0))
    if any(abs(v) > max_ml for v in body.volumes):
        raise HTTPException(400, f"volumes exceed manual cap of {max_ml} mL.")
    with hw.manual_op("fluidic"):
        hw.get_fluidic().multi_stepper_pump(body.volumes, body.flow_rate)
    return {"ok": True, "volumes": body.volumes}


@router.post("/pumps/stepper/{no}")
def run_stepper(no: int, body: StepperRequest, request: Request) -> dict:
    if not (1 <= no <= 4):
        raise HTTPException(400, "Stepper pump number must be 1-4.")
    hw = get_hw(request)
    max_ml = float(hw.raw_cfg.get("web", {}).get("max_manual_volume_ml", 25.0))
    if abs(body.ml) > max_ml:
        raise HTTPException(400, f"|ml| exceeds manual cap of {max_ml} mL.")
    with hw.manual_op("fluidic"):
        hw.get_fluidic().stepper_pump(no, body.ml, body.flow_rate)
    return {"ok": True, "pump_no": no, "ml": body.ml}


@router.post("/pumps/prime")
def prime_all(body: PrimeRequest, request: Request) -> dict:
    """Prime all pumps: run each peristaltic pump for peristaltic_ml, then all
    four stepper pumps together for stepper_ml each (multiStepperPump runs
    them concurrently, so the stepper phase takes stepper_ml/stepper_flow s)."""
    hw = get_hw(request)
    primed = []
    with hw.manual_op("robot", "fluidic"):
        peristaltic = hw.get_peristaltic()
        for name in hw.raw_cfg.get("peristaltic_pumps", {}):
            peristaltic.fill_peristaltic(name, body.peristaltic_ml)
            primed.append(name)
        hw.get_fluidic().multi_stepper_pump(
            [body.stepper_ml] * 4, body.stepper_flow
        )
        primed.extend([f"stepper-{n}" for n in range(1, 5)])
    return {"ok": True, "primed": primed}


@router.post("/pumps/stop")
def emergency_stop(request: Request) -> dict:
    """Reset the fluidic ESP32 to halt all stepper motion immediately.

    Not available during an experiment (the runner owns the port) — abort the
    experiment instead; its cleanup calls emergency_stop itself.
    """
    hw = get_hw(request)
    with hw.manual_op("fluidic"):
        if hw._fluidic is None:
            raise HTTPException(400, "Fluidic controller is not connected — nothing to stop.")
        hw._fluidic.emergency_stop()
    return {"ok": True}
