"""Status + sanitized config endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from n9_web.routers.deps import get_hw
from n9_web import trace

router = APIRouter()


@router.get("/trace")
def sample_trace(request: Request, n: int = 100) -> dict:
    """Last n sample-trace events (audit trail)."""
    hw = get_hw(request)
    return {"events": trace.tail(hw.raw_cfg.get("data_dir", "data"),
                                 min(max(n, 1), 1000))}


@router.get("/status")
def status(request: Request) -> dict:
    hw = get_hw(request)
    snap = hw.status_snapshot()
    exp = request.app.state.experiment_service
    snap["experiment"] = exp.status()
    echem = getattr(request.app.state, "echem_service", None)
    snap["echem"] = echem.status() if echem is not None else {"available": False}
    seq = getattr(request.app.state, "sequence_service", None)
    snap["sequence"] = seq.status() if seq is not None else {"running": False}
    return snap


@router.get("/config")
def config(request: Request) -> dict:
    hw = get_hw(request)
    cfg = hw.raw_cfg

    stations = [
        {
            "id": s["id"],
            "board_id": s["board_id"],
            "n_cols": 2,
            "n_rows": 8,
            "origin_xyz": s.get("origin_xyz"),
            "col_spacing_mm": float(s.get("col_spacing_mm", 31.2)),
            "row_spacing_mm": float(s.get("row_spacing_mm", -15.0)),
        }
        for s in cfg.get("sensing_stations", [])
    ]
    holders = [
        {
            "holder_id": h["holder_id"],
            "n_cols": int(h.get("n_cols", 5)),
            "n_rows": int(h.get("n_rows", 18)),
            "origin_xyz": h.get("origin_xyz"),
            "col_spacing_mm": float(h.get("col_spacing_mm", 11.5)),
            "row_spacing_mm": float(h.get("row_spacing_mm", 5.75)),
        }
        for h in cfg.get("sample_holders", [])
    ]
    enabled_map = hw.board_enabled_map()
    boards = [
        {
            "board_id": b["board_id"],
            "enabled": enabled_map.get(b["board_id"], True),
            "sensors_in_use": int(b.get("sensors_in_use", 16)),
            "target_temp_c": b.get("target_temp_c"),
            "max_power_pct": float(b.get("max_power_%", 50.0)),
            "sensor_pin": int(b.get("sensor_pin", 5)),
            "sensor_settings": b.get("sensor_settings", {}),
            "simulate": bool(b.get("simulate", False)),
        }
        for b in cfg.get("PCBs", [])
    ]
    web = cfg.get("web", {})
    tc = cfg.get("test_cell", {})

    echem = getattr(request.app.state, "echem_service", None)

    return {
        "sensing_stations": stations,
        "sample_holders": holders,
        "boards": boards,
        "peristaltic_pumps": list(cfg.get("peristaltic_pumps", {}).keys()),
        "stepper_pumps": [1, 2, 3, 4],
        "test_cell": {
            "fill_pump": tc.get("fill_pump"),
            "drain_pump": tc.get("drain_pump"),
            "fill_volume_ml": tc.get("fill_volume_ml"),
            "xyz": tc.get("xyz"),
        },
        "workspace_limits": web.get("workspace_limits"),
        "max_manual_volume_ml": float(web.get("max_manual_volume_ml", 25.0)),
        "echem_techniques": echem.techniques() if echem is not None else {},
    }
