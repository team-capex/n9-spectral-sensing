"""Robot movement, sample transfer, and test-cell endpoints.

All motion endpoints validate their targets before touching hardware:
grid locations resolve through CoordinateMap (which enforces known IDs), and
grid indices are checked against the layout dimensions; raw XYZ moves are
checked against web.workspace_limits from config.yaml.
"""

from __future__ import annotations

import logging
import math

from fastapi import APIRouter, HTTPException, Request

from n9_web.routers.deps import get_hw
from n9_web.trace import log_event, loc_str
from n9_web.schemas import (
    DrainRequest,
    FillRequest,
    GripperRequest,
    Location,
    MoveXYZ,
    PickPlaceRequest,
    PistonRequest,
    TestCellInsert,
    TestCellRetrieve,
    TransferRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_location(hw, loc: Location) -> "tuple[float, float, float]":
    """Map a logical grid location to robot XYZ (mm), validating indices."""
    cm = hw.coord_map
    if loc.type == "test_cell":
        return cm.test_cell_xyz()

    if loc.id is None or loc.col is None or loc.row is None:
        raise HTTPException(400, f"Location type '{loc.type}' needs id, col, row.")

    if loc.type == "holder":
        layout = cm.holder_layout(loc.id)   # KeyError → 400 via app exception handler
        if not (0 <= loc.col < layout.n_cols and 0 <= loc.row < layout.n_rows):
            raise HTTPException(
                400,
                f"Slot (col={loc.col}, row={loc.row}) outside holder grid "
                f"{layout.n_cols}×{layout.n_rows}.",
            )
        return cm.holder_slot_xyz(loc.id, loc.col, loc.row)

    # pcb
    if not (0 <= loc.col <= 1 and 0 <= loc.row <= 7):
        raise HTTPException(
            400, f"PCB position (col={loc.col}, row={loc.row}) outside 2×8 grid."
        )
    return cm.pcb_sensor_xyz(loc.id, loc.col, loc.row)


def _describe(loc: Location) -> str:
    if loc.type == "test_cell":
        return "test cell"
    return f"{loc.id} (col {loc.col}, row {loc.row})"


def _check_workspace(hw, x: float, y: float, z: float) -> None:
    limits = hw.raw_cfg.get("web", {}).get("workspace_limits")
    if not limits:
        raise HTTPException(
            400,
            "Raw XYZ moves are disabled: no web.workspace_limits in config.yaml.",
        )
    for axis, val in (("x", x), ("y", y), ("z", z)):
        lo, hi = limits[axis]
        if not (lo <= val <= hi):
            raise HTTPException(
                400, f"{axis}={val} outside workspace limit [{lo}, {hi}] mm."
            )


def _tc_angle_rad(hw) -> float:
    return math.radians(hw.coord_map.test_cell.gripper_angle_deg)


def _sample_at(loc: Location) -> "tuple[str, str]":
    """Best-effort sample lookup for manual moves: holder slots resolve via
    holder_state.json; other locations return empty (unknown)."""
    if loc.type != "holder":
        return "", ""
    import json
    try:
        with open("holder_state.json", encoding="utf-8") as f:
            doc = json.load(f)
        for s in doc.get(loc.id, []):
            if int(s.get("col", -1)) == loc.col and int(s.get("row", -1)) == loc.row:
                return s.get("sample_id", ""), s.get("sample_type", "")
    except Exception:
        pass
    return "", ""


def _trace_move(hw, event: str, from_loc: "Location | None",
                to_loc: "Location | None") -> None:
    src_loc = from_loc or Location(type="test_cell")
    sid, stype = _sample_at(src_loc) if from_loc else ("", "")
    log_event(
        hw.raw_cfg.get("data_dir", "data"), event,
        sample_id=sid, sample_type=stype,
        src=loc_str(from_loc.model_dump()) if from_loc else "test_cell",
        dst=loc_str(to_loc.model_dump()) if to_loc else "test_cell",
        context="manual",
    )


# ── Basic motions ──────────────────────────────────────────────────────────────

@router.post("/robot/home")
def home(request: Request) -> dict:
    hw = get_hw(request)
    with hw.manual_op("robot"):
        hw.get_robot().home()
    return {"ok": True}


@router.post("/robot/gripper")
def gripper(body: GripperRequest, request: Request) -> dict:
    hw = get_hw(request)
    with hw.manual_op("robot"):
        robot = hw.get_robot()
        if body.action == "open":
            robot.open_gripper()
        else:
            robot.close_gripper()
    return {"ok": True, "action": body.action}


@router.post("/robot/safe-z")
def safe_z(request: Request) -> dict:
    hw = get_hw(request)
    with hw.manual_op("robot"):
        hw.get_robot().raise_to_safe()
    return {"ok": True}


@router.post("/robot/move")
def move_xyz(body: MoveXYZ, request: Request) -> dict:
    hw = get_hw(request)
    _check_workspace(hw, body.x, body.y, body.z)
    with hw.manual_op("robot"):
        robot = hw.get_robot()
        robot.raise_to_safe()
        robot.move_xy(body.x, body.y)
        robot.move_z(body.z)
    return {"ok": True}


# ── Sample transfers ──────────────────────────────────────────────────────────

@router.post("/robot/transfer")
def transfer(body: TransferRequest, request: Request) -> dict:
    """Generic transfer. Test-cell endpoints are special-cased: the cell needs
    the rotated gripper approach (gripper_angle_deg) and piston actuation —
    a plain transfer would place the sample 90° off with the piston idle."""
    hw = get_hw(request)
    if body.from_.type == "test_cell" and body.to.type == "test_cell":
        raise HTTPException(400, "'from' and 'to' are both the test cell.")
    from_xyz = _resolve_location(hw, body.from_)
    to_xyz = _resolve_location(hw, body.to)
    logger.info(
        "Manual transfer: %s → %s", _describe(body.from_), _describe(body.to)
    )
    with hw.manual_op("robot"):
        robot = hw.get_robot()
        if body.to.type == "test_cell":
            pumps = hw.get_peristaltic()
            robot.pick_from(from_xyz[0], from_xyz[1], from_xyz[2])
            robot.move_to_test_cell(
                to_xyz, gripper_angle_offset_rad=_tc_angle_rad(hw)
            )
            pumps.engage_piston()
            robot.release_at_test_cell()
        elif body.from_.type == "test_cell":
            pumps = hw.get_peristaltic()
            pumps.release_piston()
            robot.retrieve_from_test_cell(
                from_xyz, gripper_angle_offset_rad=_tc_angle_rad(hw)
            )
            robot.place_at(to_xyz[0], to_xyz[1], to_xyz[2])
            robot.force_home()
        else:
            robot.transfer(from_xyz, to_xyz)
            robot.force_home()
    _trace_move(hw, "transfer", body.from_, body.to)
    return {"ok": True, "from_xyz": from_xyz, "to_xyz": to_xyz}


@router.post("/robot/pick")
def pick(body: PickPlaceRequest, request: Request) -> dict:
    hw = get_hw(request)
    x, y, z = _resolve_location(hw, body.location)
    logger.info("Manual pick from %s", _describe(body.location))
    with hw.manual_op("robot"):
        hw.get_robot().pick_from(x, y, z)
    return {"ok": True, "xyz": (x, y, z)}


@router.post("/robot/place")
def place(body: PickPlaceRequest, request: Request) -> dict:
    hw = get_hw(request)
    x, y, z = _resolve_location(hw, body.location)
    logger.info("Manual place at %s", _describe(body.location))
    with hw.manual_op("robot"):
        hw.get_robot().place_at(x, y, z)
    return {"ok": True, "xyz": (x, y, z)}


# ── Test cell ──────────────────────────────────────────────────────────────────

@router.post("/testcell/insert")
def testcell_insert(body: TestCellInsert, request: Request) -> dict:
    """Pick a sample and insert it into the test cell:
    pick → move to test cell → engage piston → release gripper + home."""
    hw = get_hw(request)
    from_xyz = _resolve_location(hw, body.from_)
    tc_xyz = hw.coord_map.test_cell_xyz()
    logger.info("Manual test-cell insert from %s", _describe(body.from_))
    with hw.manual_op("robot"):
        robot = hw.get_robot()
        pumps = hw.get_peristaltic()
        robot.pick_from(from_xyz[0], from_xyz[1], from_xyz[2])
        robot.move_to_test_cell(tc_xyz, gripper_angle_offset_rad=_tc_angle_rad(hw))
        pumps.engage_piston()
        robot.release_at_test_cell()
    _trace_move(hw, "testcell_insert", body.from_, None)
    return {"ok": True}


@router.post("/testcell/retrieve")
def testcell_retrieve(body: TestCellRetrieve, request: Request) -> dict:
    """Retrieve the sample from the test cell and return it:
    release piston → retrieve → place at destination → home."""
    hw = get_hw(request)
    to_xyz = _resolve_location(hw, body.to)
    tc_xyz = hw.coord_map.test_cell_xyz()
    logger.info("Manual test-cell retrieve to %s", _describe(body.to))
    with hw.manual_op("robot"):
        robot = hw.get_robot()
        pumps = hw.get_peristaltic()
        pumps.release_piston()
        robot.retrieve_from_test_cell(
            tc_xyz, gripper_angle_offset_rad=_tc_angle_rad(hw)
        )
        robot.place_at(to_xyz[0], to_xyz[1], to_xyz[2])
        robot.force_home()
    _trace_move(hw, "testcell_retrieve", None, body.to)
    return {"ok": True}


@router.post("/testcell/piston")
def testcell_piston(body: PistonRequest, request: Request) -> dict:
    hw = get_hw(request)
    with hw.manual_op("robot"):
        pumps = hw.get_peristaltic()
        if body.engage:
            pumps.engage_piston()
        else:
            pumps.release_piston()
    return {"ok": True, "engaged": body.engage}


@router.post("/testcell/fill")
def testcell_fill(body: FillRequest, request: Request) -> dict:
    hw = get_hw(request)
    max_ml = float(hw.raw_cfg.get("web", {}).get("max_manual_volume_ml", 25.0))
    if body.volume_ml > max_ml:
        raise HTTPException(400, f"volume_ml exceeds manual cap of {max_ml} mL.")
    pump_name = body.pump or hw.coord_map.test_cell.fill_pump
    with hw.manual_op("robot"):
        hw.get_peristaltic().fill_peristaltic(pump_name, body.volume_ml)
    return {"ok": True, "pump": pump_name, "volume_ml": body.volume_ml}


@router.post("/testcell/drain")
def testcell_drain(body: DrainRequest, request: Request) -> dict:
    hw = get_hw(request)
    max_ml = float(hw.raw_cfg.get("web", {}).get("max_manual_volume_ml", 25.0))
    if body.volume_ml is not None and body.volume_ml > max_ml:
        raise HTTPException(400, f"volume_ml exceeds manual cap of {max_ml} mL.")
    with hw.manual_op("robot"):
        pumps = hw.get_peristaltic()
        pumps.open_drain()
        try:
            pumps.drain(body.volume_ml)
        finally:
            pumps.close_drain()
    return {"ok": True, "volume_ml": body.volume_ml}
