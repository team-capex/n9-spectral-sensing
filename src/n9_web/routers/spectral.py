"""Spectral scanning endpoints."""

from __future__ import annotations

import math
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from n9_web.routers.deps import get_hw
from n9_web.schemas import (
    BoardEnabledRequest,
    LedRequest,
    ScanRequest,
    SensorSettingsRequest,
)

router = APIRouter()


def _csv_path(hw) -> str:
    return os.path.join(hw.raw_cfg.get("data_dir", "data"), "spectral_log.csv")


def _tail_rows(path: str, n: int, board_id: "str | None" = None) -> list:
    """Return the last n rows of spectral_log.csv as JSON-safe dicts."""
    import pandas as pd

    if not os.path.exists(path):
        return []
    df = pd.read_csv(path)
    if board_id:
        df = df[df["board_id"] == board_id]
    df = df.tail(n)
    rows = df.to_dict(orient="records")
    for row in rows:  # NaN → None for JSON
        for k, v in row.items():
            if isinstance(v, float) and math.isnan(v):
                row[k] = None
    return rows


@router.get("/spectral/latest")
def latest(request: Request, board_id: Optional[str] = None, n: int = 50) -> dict:
    hw = get_hw(request)
    return {"rows": _tail_rows(_csv_path(hw), min(max(n, 1), 500), board_id)}


@router.post("/spectral/scan")
def scan(body: ScanRequest, request: Request) -> dict:
    hw = get_hw(request)
    path = _csv_path(hw)

    def _line_count(p: str) -> int:
        if not os.path.exists(p):
            return 0
        with open(p, "rb") as f:
            return sum(1 for _ in f)

    before = _line_count(path)
    with hw.manual_op("boards"):
        mgr = hw.get_boards()
        # get_boards() may already hold connections to more boards than
        # requested (first caller decides) — filter to the requested subset.
        targets = [
            b for b in mgr._boards
            if not body.board_ids or b.cfg.board_id in body.board_ids
        ]
        if body.board_ids:
            missing = set(body.board_ids) - {b.cfg.board_id for b in targets}
            if missing:
                raise HTTPException(404, f"Boards not connected: {sorted(missing)}")
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=max(len(targets), 1)) as ex:
            futures = {
                ex.submit(b.run_once, mgr.experiment_id): b.cfg.board_id
                for b in targets
            }
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as exc:
                    raise RuntimeError(
                        f"Board {futures[fut]} failed during scan: {exc}"
                    ) from exc
    after = _line_count(path)
    new_rows = max(0, after - before)
    return {"ok": True, "new_rows": new_rows,
            "rows": _tail_rows(path, new_rows) if new_rows else []}


@router.get("/spectral/boards")
def boards_status(request: Request) -> dict:
    """Per-board enabled + connected flags for the boards panel."""
    hw = get_hw(request)
    connected = set()
    if hw._boards is not None:
        connected = {b.cfg.board_id for b in hw._boards._boards}
    return {
        "boards": [
            {"board_id": bid, "enabled": en, "connected": bid in connected}
            for bid, en in hw.board_enabled_map().items()
        ]
    }


@router.post("/spectral/boards/{board_id}/enabled")
def set_board_enabled(board_id: str, body: BoardEnabledRequest, request: Request) -> dict:
    hw = get_hw(request)
    with hw.manual_op("boards"):
        hw.set_board_enabled(board_id, body.enabled)
    return {"ok": True, "board_id": board_id, "enabled": body.enabled}


@router.post("/spectral/led")
def set_led_panel(body: LedRequest, request: Request) -> dict:
    """Turn the LED panel on/off.

    There is one physical panel, driven by a board's 0-10 V output; applying
    the configured control voltage to all connected boards is harmless for
    boards not wired to the panel. Pass board_id to target one board only.
    """
    hw = get_hw(request)
    with hw.manual_op("boards"):
        mgr = hw.get_boards()
        targets = [
            b for b in mgr._boards
            if body.board_id is None or b.cfg.board_id == body.board_id
        ]
        if body.board_id and not targets:
            raise HTTPException(404, f"Board '{body.board_id}' is not connected.")
        for b in targets:
            b._safe_set_voltage(b.cfg.control_voltage if body.on else 0.0)
    return {
        "ok": True,
        "on": body.on,
        "boards": [b.cfg.board_id for b in targets],
    }


@router.post("/spectral/settings/{board_id}")
def set_settings(board_id: str, body: SensorSettingsRequest, request: Request) -> dict:
    if body.gain not in (1, 2, 4, 8, 16, 32, 64, 128, 256):
        raise HTTPException(400, "gain must be one of 1,2,4,...,256")
    hw = get_hw(request)
    with hw.manual_op("boards"):
        mgr = hw.get_boards()
        runtimes = {b.cfg.board_id: b for b in mgr._boards}
        rt = runtimes.get(board_id)
        if rt is None:
            raise HTTPException(404, f"Unknown board '{board_id}'. "
                                     f"Connected: {list(runtimes)}")
        rt.sensor.set_sensor_settings(body.gain, body.atime, body.astep)
    return {"ok": True, "board_id": board_id}
