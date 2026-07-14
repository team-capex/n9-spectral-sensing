"""Electrochemistry (Gamry potentiostat) endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from n9_web.routers.deps import get_echem_service
from n9_web.schemas import EchemRunRequest

router = APIRouter()


@router.get("/echem/techniques")
def techniques(request: Request) -> dict:
    return get_echem_service(request).techniques()


@router.post("/echem/run")
def run(body: EchemRunRequest, request: Request) -> dict:
    svc = get_echem_service(request)
    run_id = svc.run(body.technique, body.params, sample_id=body.sample_id)
    return {"ok": True, "run_id": run_id}


@router.post("/echem/abort")
def abort(request: Request) -> dict:
    svc = get_echem_service(request)
    try:
        svc.abort()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True}


@router.get("/echem/status")
def status(request: Request) -> dict:
    return get_echem_service(request).status()


@router.get("/echem/result/{run_id}")
def result(run_id: str, request: Request) -> dict:
    svc = get_echem_service(request)
    try:
        return svc.result(run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@router.get("/echem/runs")
def runs(request: Request) -> dict:
    return {"runs": get_echem_service(request).list_runs()}
