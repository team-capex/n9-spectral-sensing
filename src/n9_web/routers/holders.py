"""Sample holder content editing.

Edits write holder_state.json (the declared initial contents that seed every
new experiment) and, when no experiment is running, also patch the on-disk
experiment_state.json so the dashboard reflects the change immediately.

sample_id convention (matches holder_state.json docs):
    {holder_id}_c{col:02d}_r{row:02d}
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from n9_web.routers.deps import get_experiment_service, get_hw
from n9_web.schemas import AddSamplesRequest, SlotEditRequest

logger = logging.getLogger(__name__)

router = APIRouter()

HOLDER_STATE_PATH = "holder_state.json"


def _guard_not_running(request: Request) -> None:
    if get_experiment_service(request).status()["running"]:
        raise HTTPException(
            409, "Holder contents cannot be edited while an experiment is running."
        )


def _load_holder_state() -> dict:
    try:
        with open(HOLDER_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"holder_state.json is invalid JSON: {exc}")


def _save_holder_state(doc: dict) -> None:
    tmp = HOLDER_STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    os.replace(tmp, HOLDER_STATE_PATH)


def _sample_id(holder_id: str, col: int, row: int) -> str:
    return f"{holder_id}_c{col:02d}_r{row:02d}"


def _holder_layout(hw, holder_id: str):
    try:
        return hw.coord_map.holder_layout(holder_id)
    except KeyError:
        raise HTTPException(404, f"Unknown holder '{holder_id}'.")


def _set_slot_in_doc(doc: dict, holder_id: str, col: int, row: int,
                     state: str, sample_type: str) -> None:
    """Set one slot in the holder_state.json document (in place).
    EMPTY removes the entry (unlisted slots default to EMPTY)."""
    slots = [
        s for s in doc.get(holder_id, [])
        if not (int(s.get("col", -1)) == col and int(s.get("row", -1)) == row)
    ]
    if state != "EMPTY":
        slots.append({
            "col": col,
            "row": row,
            "state": state,
            "sample_type": sample_type,
            "sample_id": _sample_id(holder_id, col, row),
        })
    slots.sort(key=lambda s: (int(s["row"]), int(s["col"])))
    doc[holder_id] = slots


def _sync_experiment_state(hw, holder_id: str,
                           edits: "list[tuple[int, int, str, str]]",
                           clear_all: bool = False) -> None:
    """Patch holder_slots in the persisted experiment_state.json (if any) so
    the dashboard shows the edit immediately. Records: (col, row, state, type).
    """
    path = os.path.join(hw.raw_cfg.get("data_dir", "data"),
                        "state", "experiment_state.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return

    slots = data.get("holder_slots", {})
    now = datetime.now(timezone.utc).isoformat()

    def _write(col: int, row: int, state: str, sample_type: str) -> None:
        key = f"{holder_id}_c{col}_r{row}"
        empty = state == "EMPTY"
        slots[key] = {
            "holder_id": holder_id,
            "col": col,
            "row": row,
            "state": state,
            "sample_id": None if empty else _sample_id(holder_id, col, row),
            "sample_type": None if empty else sample_type,
            "last_updated": now,
        }

    if clear_all:
        for key, rec in list(slots.items()):
            if rec.get("holder_id") == holder_id:
                _write(int(rec["col"]), int(rec["row"]), "EMPTY", "")
    for col, row, state, sample_type in edits:
        _write(col, row, state, sample_type)

    data["holder_slots"] = slots
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        logger.warning("Could not sync experiment_state.json", exc_info=True)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/holders")
def get_holders(request: Request) -> dict:
    doc = _load_holder_state()
    doc.pop("_comment", None)
    return {"holders": doc}


@router.post("/holders/{holder_id}/clear")
def clear_holder(holder_id: str, request: Request) -> dict:
    """Set every slot of the holder to EMPTY."""
    _guard_not_running(request)
    hw = get_hw(request)
    _holder_layout(hw, holder_id)
    doc = _load_holder_state()
    removed = len(doc.get(holder_id, []))
    doc[holder_id] = []
    _save_holder_state(doc)
    _sync_experiment_state(hw, holder_id, edits=[], clear_all=True)
    logger.info("Holder %s cleared (%d slots emptied).", holder_id, removed)
    return {"ok": True, "holder_id": holder_id, "slots_cleared": removed}


@router.post("/holders/{holder_id}/slot")
def set_slot(holder_id: str, body: SlotEditRequest, request: Request) -> dict:
    """Set one slot's state/sample (EMPTY removes the sample)."""
    _guard_not_running(request)
    hw = get_hw(request)
    layout = _holder_layout(hw, holder_id)
    if not (body.col < layout.n_cols and body.row < layout.n_rows):
        raise HTTPException(
            400,
            f"Slot (col={body.col}, row={body.row}) outside holder grid "
            f"{layout.n_cols}×{layout.n_rows}.",
        )
    doc = _load_holder_state()
    _set_slot_in_doc(doc, holder_id, body.col, body.row, body.state, body.sample_type)
    _save_holder_state(doc)
    _sync_experiment_state(
        hw, holder_id, edits=[(body.col, body.row, body.state, body.sample_type)]
    )
    return {"ok": True, "holder_id": holder_id, "col": body.col, "row": body.row,
            "state": body.state}


@router.post("/holders/{holder_id}/add")
def add_samples(holder_id: str, body: AddSamplesRequest, request: Request) -> dict:
    """Add N FRESH samples into the first empty slots (row by row)."""
    _guard_not_running(request)
    hw = get_hw(request)
    layout = _holder_layout(hw, holder_id)
    doc = _load_holder_state()
    occupied = {
        (int(s["col"]), int(s["row"]))
        for s in doc.get(holder_id, [])
        if s.get("state") != "EMPTY"
    }
    edits = []
    for row in range(layout.n_rows):
        for col in range(layout.n_cols):
            if len(edits) >= body.count:
                break
            if (col, row) not in occupied:
                edits.append((col, row, "FRESH", body.sample_type))
        if len(edits) >= body.count:
            break
    if len(edits) < body.count:
        raise HTTPException(
            400,
            f"Only {len(edits)} empty slots available in {holder_id} "
            f"(requested {body.count}).",
        )
    for col, row, state, stype in edits:
        _set_slot_in_doc(doc, holder_id, col, row, state, stype)
    _save_holder_state(doc)
    _sync_experiment_state(hw, holder_id, edits=edits)
    logger.info("Added %d × '%s' to %s.", len(edits), body.sample_type, holder_id)
    return {"ok": True, "holder_id": holder_id, "added": len(edits),
            "slots": [{"col": c, "row": r} for c, r, _, _ in edits]}
