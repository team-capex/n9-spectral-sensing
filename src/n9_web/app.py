"""
app.py
======
FastAPI application factory and `n9-web` CLI entry point.

Run:
    n9-web                       # real hardware per config.yaml
    n9-web --sim                 # force simulation for robot/fluidic/boards
    n9-web --port 8080 --host 0.0.0.0

The GUI is served at http://<host>:<port>/ ; the JSON API under /api.
"""

from __future__ import annotations

import argparse
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from n9_web.echem_service import EchemService
from n9_web.experiment_service import ExperimentService
from n9_web.hardware import (
    DeviceBusy,
    DeviceUnavailable,
    ExperimentActive,
    HardwareManager,
)
from n9_web.routers import (
    calibrate,
    echem,
    experiment,
    holders,
    pumps,
    robot,
    sequences,
    spectral,
    status,
    temperature,
)
from n9_web.sequence_service import SequenceService

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(config_path: str = "config.yaml", force_sim: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hw = HardwareManager(config_path, force_sim=force_sim)
        app.state.hw = hw
        app.state.experiment_service = ExperimentService(hw)
        app.state.echem_service = EchemService(hw)
        app.state.sequence_service = SequenceService(hw, app.state.echem_service)
        logger.info(
            "n9-web ready (config=%s, sim: robot=%s fluidic=%s boards=%s)",
            config_path, hw.robot_sim, hw.fluidic_sim, hw.boards_sim,
        )
        yield
        # Shutdown: abort a running experiment, then close device handles.
        # Firmware PID heater targets are intentionally left untouched —
        # use the GUI's "all heaters off" before shutting down if desired...
        # BUT note release_all() closes boards, whose close() clears heater
        # targets anyway (matches CLI behaviour).
        exp = app.state.experiment_service
        if exp.status()["running"]:
            try:
                exp.abort(hard=False)
            except Exception:
                pass
        hw.release_all()

    app = FastAPI(title="N9 Spectral Sensing Control", lifespan=lifespan)

    # Map hardware-layer exceptions to HTTP status codes.
    def _handler(status_code: int):
        def handle(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status_code, content={"detail": str(exc)})
        return handle

    app.add_exception_handler(ExperimentActive, _handler(409))
    app.add_exception_handler(DeviceBusy, _handler(423))
    app.add_exception_handler(DeviceUnavailable, _handler(503))
    app.add_exception_handler(KeyError, _handler(400))
    app.add_exception_handler(ValueError, _handler(400))

    for router in (status, temperature, spectral, robot, pumps, echem,
                   experiment, holders, calibrate, sequences):
        app.include_router(router.router, prefix="/api")

    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    # Static files carry no Cache-Control header by default, so browsers cache
    # them heuristically and keep serving stale JS/CSS after code changes.
    # no-cache = revalidate on every request (cheap: StaticFiles sends ETags).
    @app.middleware("http")
    async def _no_stale_static(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        if not request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="N9 web control GUI")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--sim", action="store_true",
        help="Force simulation mode for robot, fluidic pumps, and spectral boards",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Persist logs (incl. full tracebacks of failed measurements/sequences) so
    # errors survive the console: data/n9-web.log, rotated at 2 MB × 3 files.
    from logging.handlers import RotatingFileHandler

    os.makedirs("data", exist_ok=True)
    fh = RotatingFileHandler("data/n9-web.log", maxBytes=2_000_000,
                             backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    logging.getLogger().addHandler(fh)

    # Resolve host/port: CLI flag > config.yaml web: block > default
    import yaml

    web_cfg = {}
    if os.path.exists(args.config):
        with open(args.config, encoding="utf-8") as f:
            web_cfg = (yaml.safe_load(f) or {}).get("web", {}) or {}
    host = args.host or web_cfg.get("host", "127.0.0.1")
    port = args.port or int(web_cfg.get("port", 8000))

    app = create_app(config_path=args.config, force_sim=args.sim)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
