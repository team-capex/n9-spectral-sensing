"""Origin calibration for sample holders and sensing stations.

Workflow (all robot motion, so everything mutating is mode/lock guarded):
  1. POST /calibrate/start  — robot moves over the target's slot (col 0, row 0)
     at the configured origin, stopping CLEARANCE_MM above pick height.
  2. POST /calibrate/jog    — small absolute XY/Z steps; the server tracks the
     accumulated offset (the robot has no position readback, so all moves are
     absolute from the known start pose).
  3. POST /calibrate/save   — writes origin_xyz (+ pick_z_mm if Z was jogged)
     into config.yaml via a comment-preserving text edit, reloads the config,
     and raises the arm.
  4. POST /calibrate/cancel — raise arm, discard the session.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Literal, Optional

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from n9_web.routers.deps import get_hw

logger = logging.getLogger(__name__)

router = APIRouter()

CLEARANCE_MM = 20.0        # initial hover height above pick_z
MAX_STEP_MM = 5.0          # per-jog limit
MAX_TOTAL_OFFSET_MM = 30.0 # sanity limit on |offset| per axis

_session_lock = threading.Lock()
_session: dict = {}        # {type, id, base: [x,y,z], offset: [dx,dy,dz]}


class CalibrateStart(BaseModel):
    type: Literal["holder", "pcb"]
    id: str


class JogRequest(BaseModel):
    dx: float = Field(default=0.0, ge=-MAX_STEP_MM, le=MAX_STEP_MM)
    dy: float = Field(default=0.0, ge=-MAX_STEP_MM, le=MAX_STEP_MM)
    dz: float = Field(default=0.0, ge=-MAX_STEP_MM, le=MAX_STEP_MM)


def _session_state() -> dict:
    with _session_lock:
        if not _session:
            return {"active": False}
        return {"active": True, **{k: v for k, v in _session.items()}}


def _current_target(hw) -> "tuple[float, float, float]":
    base, off = _session["base"], _session["offset"]
    return base[0] + off[0], base[1] + off[1], base[2] + off[2]


@router.get("/calibrate/status")
def status(request: Request) -> dict:
    return _session_state()


@router.post("/calibrate/start")
def start(body: CalibrateStart, request: Request) -> dict:
    hw = get_hw(request)
    if body.type == "holder":
        x, y, pick_z = hw.coord_map.holder_slot_xyz(body.id, 0, 0)
    else:
        x, y, pick_z = hw.coord_map.pcb_sensor_xyz(body.id, 0, 0)

    with hw.manual_op("robot"):
        robot = hw.get_robot()
        robot.raise_to_safe()
        robot.move_xy(x, y)
        robot.move_z(pick_z + CLEARANCE_MM)

    with _session_lock:
        _session.clear()
        _session.update({
            "type": body.type, "id": body.id,
            "base": [x, y, pick_z + CLEARANCE_MM],
            "pick_z": pick_z,
            "offset": [0.0, 0.0, 0.0],
        })
    logger.info("Calibration started for %s '%s' at (%.2f, %.2f, z=%.2f+%.0f).",
                body.type, body.id, x, y, pick_z, CLEARANCE_MM)
    return _session_state()


@router.post("/calibrate/jog")
def jog(body: JogRequest, request: Request) -> dict:
    hw = get_hw(request)
    with _session_lock:
        if not _session:
            raise HTTPException(409, "No calibration session — start one first.")
        off = _session["offset"]
        new_off = [off[0] + body.dx, off[1] + body.dy, off[2] + body.dz]
        if any(abs(v) > MAX_TOTAL_OFFSET_MM for v in new_off):
            raise HTTPException(
                400, f"Total offset would exceed ±{MAX_TOTAL_OFFSET_MM} mm — "
                     f"if the origin is that far off, edit config.yaml directly."
            )
        _session["offset"] = new_off
        base = _session["base"]
        tx, ty, tz = (base[0] + new_off[0], base[1] + new_off[1],
                      base[2] + new_off[2])

    with hw.manual_op("robot"):
        robot = hw.get_robot()
        if body.dx or body.dy:
            robot.move_xy(tx, ty)
        if body.dz:
            robot.move_z(tz)
    return _session_state()


@router.post("/calibrate/cancel")
def cancel(request: Request) -> dict:
    hw = get_hw(request)
    with _session_lock:
        _session.clear()
    with hw.manual_op("robot"):
        hw.get_robot().raise_to_safe()
    return {"ok": True}


@router.post("/calibrate/save")
def save(request: Request) -> dict:
    hw = get_hw(request)
    with _session_lock:
        if not _session:
            raise HTTPException(409, "No calibration session — start one first.")
        target_type = _session["type"]
        target_id = _session["id"]
        dx, dy, dz = _session["offset"]

    # Current config entry
    section, id_key = (
        ("sample_holders", "holder_id") if target_type == "holder"
        else ("sensing_stations", "id")
    )
    entry = next(
        (e for e in hw.raw_cfg.get(section, []) if e[id_key] == target_id), None
    )
    if entry is None:
        raise HTTPException(404, f"'{target_id}' not found in config.")

    old_origin = [float(v) for v in entry["origin_xyz"]]
    new_origin = [
        round(old_origin[0] + dx, 3),
        round(old_origin[1] + dy, 3),
        round(old_origin[2] + dz, 3),
    ]
    new_pick_z = round(float(entry["pick_z_mm"]) + dz, 3)

    _write_config_origin(hw.config_path, id_key, target_id,
                         new_origin, new_pick_z if dz else None)
    hw.reload_config()

    with _session_lock:
        _session.clear()
    with hw.manual_op("robot"):
        hw.get_robot().raise_to_safe()

    logger.info(
        "Calibration saved: %s origin %s → %s%s (offset dx=%.2f dy=%.2f dz=%.2f)",
        target_id, old_origin, new_origin,
        f", pick_z → {new_pick_z}" if dz else "", dx, dy, dz,
    )
    return {"ok": True, "id": target_id, "old_origin": old_origin,
            "new_origin": new_origin,
            "new_pick_z": new_pick_z if dz else None}


def _write_config_origin(path: str, id_key: str, id_value: str,
                         origin: "list[float]", pick_z: "float | None") -> None:
    """Update origin_xyz (and optionally pick_z_mm) of one entry in
    config.yaml via targeted line edits, preserving comments. Verifies the
    result parses back to the expected values."""
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    ent_pat = re.compile(rf'-\s*{id_key}:\s*"?{re.escape(id_value)}"?\s*(#.*)?$')
    ent = next((i for i, ln in enumerate(lines) if ent_pat.search(ln.rstrip())), None)
    if ent is None:
        raise HTTPException(500, f"Could not locate '{id_value}' in {path}.")

    origin_str = f"[{origin[0]}, {origin[1]}, {origin[2]}]"
    did_origin = did_z = False
    for j in range(ent + 1, len(lines)):
        # Stop at the next list entry or a new top-level section
        if re.match(r"\s*-\s", lines[j]) or re.match(r"\S", lines[j]):
            break
        if not did_origin and "origin_xyz:" in lines[j]:
            lines[j] = re.sub(r"origin_xyz:\s*\[[^\]]*\]",
                              f"origin_xyz: {origin_str}", lines[j])
            did_origin = True
        elif pick_z is not None and not did_z and re.search(r"\bpick_z_mm:", lines[j]):
            lines[j] = re.sub(r"pick_z_mm:\s*[-+0-9.eE]+",
                              f"pick_z_mm: {pick_z}", lines[j])
            did_z = True
    if not did_origin:
        raise HTTPException(500, f"origin_xyz line not found for '{id_value}'.")

    text = "".join(lines)
    # Verify before committing to disk
    doc = yaml.safe_load(text)
    section = "sample_holders" if id_key == "holder_id" else "sensing_stations"
    check = next(e for e in doc[section] if e[id_key] == id_value)
    if [round(float(v), 3) for v in check["origin_xyz"]] != [round(v, 3) for v in origin]:
        raise HTTPException(500, "Config verification failed — file not modified.")

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
