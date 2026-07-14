"""
experiment_service.py
=====================
Runs ExperimentRunner in a background thread for the web GUI and exposes
progress, logs, and abort control.

Design notes:
- The web layer NEVER touches the runner's in-memory ExperimentState (not
  thread-safe); the dashboard reads the atomically-written JSON files on disk.
- Soft abort sets an event checked between steps (the current step finishes
  first). Hard abort additionally injects KeyboardInterrupt into the worker
  thread — it only fires between Python bytecodes, so it cannot interrupt a
  blocking serial read; it is a last resort.
- Port handover: HardwareManager.release_all() is called (under all device
  locks) before constructing the runner, because the runner opens the same
  COM ports itself.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import threading
import time
import traceback
from collections import deque
from typing import Optional

from n9_web.hardware import HardwareManager

logger = logging.getLogger(__name__)


class RingBufferLogHandler(logging.Handler):
    """Keeps the last N log records in memory with monotonically increasing
    sequence numbers so the UI can poll incrementally."""

    def __init__(self, maxlen: int = 3000) -> None:
        super().__init__(level=logging.INFO)
        self._buf: deque = deque(maxlen=maxlen)
        self._seq = 0
        self._lock2 = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        with self._lock2:
            self._seq += 1
            self._buf.append(
                (self._seq, record.created, record.levelname, record.name, msg)
            )

    def entries_since(self, since_seq: int) -> "tuple[list, int]":
        with self._lock2:
            entries = [e for e in self._buf if e[0] > since_seq]
            return entries, self._seq


class ExperimentService:
    """Starts, monitors, and aborts experiment runs."""

    def __init__(self, hw: HardwareManager) -> None:
        self.hw = hw
        self.log_handler = RingBufferLogHandler()
        self.log_handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(self.log_handler)

        self._thread: Optional[threading.Thread] = None
        self._abort_event = threading.Event()
        self._status_lock = threading.Lock()
        self._status: dict = {
            "running": False,
            "run_id": None,
            "experiment_path": None,
            "experiment_id": None,
            "step": None,
            "step_index": None,
            "n_steps": None,
            "started_at": None,
            "finished_at": None,
            "outcome": None,   # completed | aborted | error
            "error": None,
        }

    # ── Control ───────────────────────────────────────────────────────────────

    def start(self, experiment_path: str, resume: bool = False) -> str:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("An experiment is already running.")
        if not os.path.exists(experiment_path):
            raise FileNotFoundError(f"Experiment file not found: {experiment_path}")

        # Port handover: close all manual handles under the device locks, then
        # claim experiment mode so no manual op can reconnect before the runner
        # opens the ports.
        locks = self.hw.acquire_all_for_handover()
        try:
            self.hw.start_experiment_mode()   # raises if not IDLE
            self.hw.release_all()
        finally:
            for l in reversed(locks):
                l.release()

        run_id = time.strftime("%Y%m%d_%H%M%S")
        self._abort_event = threading.Event()
        with self._status_lock:
            self._status.update(
                running=True, run_id=run_id, experiment_path=experiment_path,
                experiment_id=None, step=None, step_index=None, n_steps=None,
                started_at=time.time(), finished_at=None, outcome=None, error=None,
            )
        self._thread = threading.Thread(
            target=self._worker, args=(experiment_path, resume), daemon=True,
            name=f"experiment-{run_id}",
        )
        self._thread.start()
        return run_id

    def abort(self, hard: bool = False) -> None:
        if self._thread is None or not self._thread.is_alive():
            raise RuntimeError("No experiment is running.")
        self._abort_event.set()
        logger.info("Experiment abort requested (%s).", "hard" if hard else "soft")
        if hard:
            # Ctrl+C equivalent: raise KeyboardInterrupt in the worker thread.
            # Only fires between bytecodes — cannot interrupt a blocking
            # serial read until it returns.
            tid = self._thread.ident
            if tid is not None:
                res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                    ctypes.c_long(tid), ctypes.py_object(KeyboardInterrupt)
                )
                if res > 1:  # pragma: no cover — undo on over-delivery
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(
                        ctypes.c_long(tid), None
                    )

    # ── Worker ────────────────────────────────────────────────────────────────

    def _worker(self, experiment_path: str, resume: bool) -> None:
        # Import here so app startup does not need robot deps resolved.
        from n9_controller.experiment_runner import (
            ExperimentAborted,
            ExperimentRunner,
        )

        outcome, error = "completed", None
        runner = None
        try:
            runner = ExperimentRunner(
                self.hw.config_path, experiment_path, resume=resume
            )
            with self._status_lock:
                self._status["experiment_id"] = runner.exp_cfg.experiment_id
                self._status["n_steps"] = len(runner.exp_cfg.steps)

            def on_step(name: str, idx: int, total: int) -> None:
                with self._status_lock:
                    self._status["step"] = name
                    self._status["step_index"] = idx
                    self._status["n_steps"] = total

            runner.run(abort_event=self._abort_event, on_step=on_step)

        except (ExperimentAborted, KeyboardInterrupt) as exc:
            outcome, error = "aborted", str(exc) or "aborted"
            logger.info("Experiment aborted: %s", error)
        except Exception as exc:
            outcome, error = "error", f"{exc}\n{traceback.format_exc()}"
            logger.error("Experiment failed: %s", exc, exc_info=True)
        finally:
            if runner is not None:
                try:
                    runner.shutdown()
                except Exception:
                    logger.warning("runner.shutdown() failed", exc_info=True)
                self._close_runner_ports(runner)
            self.hw.end_experiment_mode()
            with self._status_lock:
                self._status.update(
                    running=False, finished_at=time.time(),
                    outcome=outcome, error=error,
                )
            logger.info("Experiment finished: %s", outcome)

    @staticmethod
    def _close_runner_ports(runner) -> None:
        """Close the serial ports the runner opened. runner.shutdown() closes
        the spectral boards but not the robot FTDI handle or fluidic port —
        fine for a CLI process that exits, but a long-lived server must
        release them or the next run/manual op gets a connect timeout."""
        try:
            c9 = getattr(runner.robot, "_c9", None)
            ser = getattr(c9, "_serial", None) if c9 is not None else None
            if ser is not None:
                if hasattr(ser, "disconnect"):
                    ser.disconnect()
                elif hasattr(ser, "close"):
                    ser.close()
        except Exception:
            logger.warning("Failed to close runner robot port", exc_info=True)
        try:
            runner.fluidic_pump_ctrl.close_ser()
        except Exception:
            logger.warning("Failed to close runner fluidic port", exc_info=True)

    # ── Read model ────────────────────────────────────────────────────────────

    def status(self) -> dict:
        with self._status_lock:
            return dict(self._status)

    def get_log(self, since_seq: int = 0) -> dict:
        entries, last_seq = self.log_handler.entries_since(since_seq)
        return {
            "entries": [
                {"seq": s, "ts": ts, "level": lvl, "logger": name, "msg": msg}
                for (s, ts, lvl, name, msg) in entries
            ],
            "last_seq": last_seq,
        }

    def read_state_json(self) -> dict:
        """Read experiment_state.json + holder_state.json from disk only.

        State writes are atomic (temp file + rename) so a single retry covers
        the rename window.
        """
        data_dir = self.hw.raw_cfg.get("data_dir", "data")
        state_path = os.path.join(data_dir, "state", "experiment_state.json")
        holder_path = "holder_state.json"

        def _read(path: str) -> "dict | None":
            for _ in range(2):
                try:
                    with open(path, encoding="utf-8") as f:
                        return json.load(f)
                except FileNotFoundError:
                    return None
                except (json.JSONDecodeError, OSError):
                    time.sleep(0.05)
            return None

        return {
            "experiment_state": _read(state_path),
            "holder_state": _read(holder_path),
        }
