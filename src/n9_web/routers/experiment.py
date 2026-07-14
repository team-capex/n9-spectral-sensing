"""Experiment run/monitor endpoints."""

from __future__ import annotations

import glob
import os

import yaml
from fastapi import APIRouter, HTTPException, Request

from n9_web.routers.deps import get_experiment_service, get_hw
from n9_web.schemas import ExperimentAbortRequest, ExperimentStartRequest

router = APIRouter()


@router.get("/experiment/files")
def list_files(request: Request) -> dict:
    """List experiment YAML files (repo root + web.experiments_dir)."""
    hw = get_hw(request)
    exp_dir = hw.raw_cfg.get("web", {}).get("experiments_dir", "experiment-database")

    candidates: "list[str]" = []
    for pattern in ("*.yaml", os.path.join(exp_dir, "*.yaml")):
        candidates.extend(sorted(glob.glob(pattern)))

    files = []
    for path in candidates:
        if os.path.basename(path) == "config.yaml":
            continue
        try:
            with open(path, encoding="utf-8") as f:
                doc = yaml.safe_load(f)
        except Exception:
            continue
        if not isinstance(doc, dict) or "steps" not in doc:
            continue
        files.append({
            "path": path.replace("\\", "/"),
            "experiment_id": doc.get("experiment_id"),
            "description": doc.get("description"),
            "steps": [
                s if isinstance(s, str) else s.get("action")
                for s in (doc.get("steps") or [])
            ],
            "samples": doc.get("samples"),
        })
    return {"files": files}


@router.post("/experiment/start")
def start(body: ExperimentStartRequest, request: Request) -> dict:
    svc = get_experiment_service(request)
    # Restrict to files inside the repo working directory
    path = os.path.normpath(body.experiment_path)
    if os.path.isabs(path) or path.startswith(".."):
        raise HTTPException(400, "experiment_path must be relative to the repo root.")
    try:
        run_id = svc.start(path, resume=body.resume)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True, "run_id": run_id}


@router.post("/experiment/abort")
def abort(body: ExperimentAbortRequest, request: Request) -> dict:
    svc = get_experiment_service(request)
    try:
        svc.abort(hard=body.hard)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True, "hard": body.hard}


@router.get("/experiment/status")
def status(request: Request) -> dict:
    return get_experiment_service(request).status()


@router.get("/experiment/log")
def log(request: Request, since: int = 0) -> dict:
    return get_experiment_service(request).get_log(since)


@router.get("/experiment/state")
def state(request: Request) -> dict:
    return get_experiment_service(request).read_state_json()
