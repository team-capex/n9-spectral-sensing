"""Sequence builder endpoints (echem sequences + experiment procedures)."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()

Kind = Literal["echem", "procedure"]


class SaveRequest(BaseModel):
    kind: Kind
    name: str
    sequence: dict


class RunRequest(BaseModel):
    kind: Kind
    sequence: dict


class EstimateRequest(BaseModel):
    kind: Kind
    sequence: dict


def _svc(request: Request):
    return request.app.state.sequence_service


@router.get("/sequences/actions")
def actions(request: Request, kind: Optional[Kind] = None) -> dict:
    svc = _svc(request)
    allowed = (
        {"echem", "flow"} if kind == "echem" else
        {"echem", "flow", "robot", "testcell", "pumps", "spectral"}
    )
    return {
        "actions": {
            name: spec for name, spec in svc.actions.items()
            if spec["group"] in allowed
        }
    }


@router.get("/sequences/list")
def list_sequences(request: Request, kind: Kind) -> dict:
    return {"names": _svc(request).list_sequences(kind)}


@router.get("/sequences/load")
def load(request: Request, kind: Kind, name: str) -> dict:
    try:
        return {"sequence": _svc(request).load_sequence(kind, name)}
    except FileNotFoundError:
        raise HTTPException(404, f"Sequence '{name}' not found.")


@router.post("/sequences/save")
def save(body: SaveRequest, request: Request) -> dict:
    name = _svc(request).save_sequence(body.kind, body.name, body.sequence)
    return {"ok": True, "name": name}


@router.delete("/sequences/{kind}/{name}")
def delete(kind: Kind, name: str, request: Request) -> dict:
    try:
        _svc(request).delete_sequence(kind, name)
    except FileNotFoundError:
        raise HTTPException(404, f"Sequence '{name}' not found.")
    return {"ok": True}


@router.post("/sequences/run")
def run(body: RunRequest, request: Request) -> dict:
    try:
        run_id = _svc(request).start(body.sequence, body.kind)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True, "run_id": run_id}


@router.post("/sequences/estimate")
def estimate(body: EstimateRequest, request: Request) -> dict:
    """Rough duration estimate for a (possibly unfinished) sequence."""
    return _svc(request).estimate(body.sequence)


@router.post("/sequences/abort")
def abort(request: Request) -> dict:
    try:
        _svc(request).abort()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True}


@router.get("/sequences/status")
def status(request: Request) -> dict:
    return _svc(request).status()


@router.get("/sequences/reports")
def reports(request: Request) -> dict:
    from n9_web import echem_analysis

    return {"reports": echem_analysis.list_reports(_svc(request).echem.echem_dir)}


@router.get("/sequences/report/{run_id}")
def report(run_id: str, request: Request) -> dict:
    from n9_web import echem_analysis

    try:
        return echem_analysis.load_or_rebuild(
            _svc(request).echem.echem_dir, run_id
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc))
