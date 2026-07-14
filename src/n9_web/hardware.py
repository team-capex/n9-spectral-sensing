"""
hardware.py
===========
Singleton HardwareManager for the web GUI.

Owns lazily-connected device handles with per-device locks so concurrent HTTP
requests (and a running experiment) can never collide on a serial port.

Device slots and locking:
    robot    — N9RobotController; shares ONE lock with the peristaltic
               PumpController because the latter drives the robot's digital
               outputs through the same serial connection.
    fluidic  — fluidic_hardware.PumpController (ESP32 stepper pumps), own lock.
    boards   — BoardManager (spectral PCBs), own lock.
    gamry    — potentiostat worker, own lock (managed by EchemService).

Global mode:
    IDLE               — nothing running; manual ops and experiment start allowed.
    MANUAL             — >=1 manual hardware endpoint executing; experiment
                         start rejected (409).
    EXPERIMENT_RUNNING — ExperimentRunner owns the hardware; every mutating
                         manual endpoint rejected (409).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

import yaml

from n9_controller.coordinate_map import CoordinateMap
from n9_controller.pump_controller import PumpController as PeristalticPumpController
from n9_controller.robot import N9RobotController
from fluidic_hardware.pump_controller import PumpController as FluidicPumpController
from spectral_board_manager.board_manager import BoardManager

logger = logging.getLogger(__name__)

MODE_IDLE = "IDLE"
MODE_MANUAL = "MANUAL"
MODE_EXPERIMENT = "EXPERIMENT_RUNNING"

LOCK_TIMEOUT_S = 0.5


class DeviceBusy(Exception):
    """A device lock could not be acquired — another operation is running."""


class ExperimentActive(Exception):
    """Manual operation rejected because an experiment is running."""


class DeviceUnavailable(Exception):
    """Connecting to a device failed."""


class HardwareManager:
    """Owns hardware handles, per-device locks, and the global mode."""

    def __init__(self, config_path: str, force_sim: bool = False) -> None:
        self.config_path = config_path
        self.force_sim = force_sim

        with open(config_path, encoding="utf-8") as f:
            self.raw_cfg: dict = yaml.safe_load(f)

        if force_sim:
            # Boards read this env var inside BoardManager._load_config;
            # ExperimentRunner reads N9_SIM_HARDWARE for robot + fluidic pumps.
            # Together these guarantee a --sim server can never move hardware,
            # even when config.yaml says simulate: false.
            os.environ["N9_SIM_BOARDS"] = "1"
            os.environ["N9_SIM_HARDWARE"] = "1"

        self.coord_map = CoordinateMap.from_config(self.raw_cfg)

        # Handles (lazy)
        self.boards_generation = 0   # bumped on each board (re)connect
        self._robot: Optional[N9RobotController] = None
        self._peristaltic: Optional[PeristalticPumpController] = None
        self._fluidic: Optional[FluidicPumpController] = None
        self._boards: Optional[BoardManager] = None

        # Locks — robot and peristaltic intentionally share one lock.
        self.robot_lock = threading.Lock()
        self.fluidic_lock = threading.Lock()
        self.boards_lock = threading.Lock()
        self.gamry_lock = threading.Lock()
        self._locks = {
            "robot": self.robot_lock,
            "fluidic": self.fluidic_lock,
            "boards": self.boards_lock,
            "gamry": self.gamry_lock,
        }

        # Mode state
        self._mode_lock = threading.Lock()
        self._mode = MODE_IDLE
        self._manual_ops = 0

        # Board enable/disable: defaults from config.yaml `enabled:` per board,
        # overridden by toggles persisted in data/web_settings.json.
        self._web_settings_path = os.path.join(
            self.raw_cfg.get("data_dir", "data"), "web_settings.json"
        )
        self._board_enabled: dict = {
            str(b["board_id"]): bool(b.get("enabled", True))
            for b in self.raw_cfg.get("PCBs", [])
        }
        try:
            with open(self._web_settings_path, encoding="utf-8") as f:
                overrides = json.load(f).get("board_enabled", {})
            for k, v in overrides.items():
                if k in self._board_enabled:
                    self._board_enabled[k] = bool(v)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    # ── Sim flags ──────────────────────────────────────────────────────────────

    @property
    def robot_sim(self) -> bool:
        return self.force_sim or bool(
            self.raw_cfg.get("robot", {}).get("simulate", True)
        )

    @property
    def fluidic_sim(self) -> bool:
        return self.force_sim or bool(
            self.raw_cfg.get("fluidic_pump_controller", {}).get("simulate", True)
        )

    @property
    def boards_sim(self) -> bool:
        if self.force_sim:
            return True
        return all(
            bool(b.get("simulate", False)) for b in self.raw_cfg.get("PCBs", [])
        )

    # ── Mode management ───────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        with self._mode_lock:
            return self._mode

    def start_experiment_mode(self) -> None:
        """Transition IDLE → EXPERIMENT_RUNNING (raises if not IDLE)."""
        with self._mode_lock:
            if self._mode != MODE_IDLE:
                raise ExperimentActive(
                    f"Cannot start experiment: system is {self._mode}."
                )
            self._mode = MODE_EXPERIMENT

    def end_experiment_mode(self) -> None:
        with self._mode_lock:
            if self._mode == MODE_EXPERIMENT:
                self._mode = MODE_IDLE

    def _enter_manual(self) -> None:
        with self._mode_lock:
            if self._mode == MODE_EXPERIMENT:
                raise ExperimentActive(
                    "Manual control is disabled while an experiment is running. "
                    "Abort the experiment first."
                )
            self._manual_ops += 1
            self._mode = MODE_MANUAL

    def _exit_manual(self) -> None:
        with self._mode_lock:
            self._manual_ops = max(0, self._manual_ops - 1)
            if self._manual_ops == 0 and self._mode == MODE_MANUAL:
                self._mode = MODE_IDLE

    @contextmanager
    def manual_op(self, *slots: str) -> Iterator[None]:
        """Guard a manual hardware operation: mode check + device locks.

        Raises ExperimentActive (→409) or DeviceBusy (→423).
        """
        self._enter_manual()
        acquired: list[threading.Lock] = []
        try:
            for slot in slots:
                lock = self._locks[slot]
                if not lock.acquire(timeout=LOCK_TIMEOUT_S):
                    raise DeviceBusy(
                        f"Device '{slot}' is busy with another operation."
                    )
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()
            self._exit_manual()

    # ── Lazy device handles ───────────────────────────────────────────────────
    # Callers must hold the corresponding lock (i.e. call inside manual_op()).

    def get_robot(self) -> N9RobotController:
        if self._robot is None:
            robot_cfg = self.raw_cfg.get("robot", {})
            try:
                self._robot = N9RobotController(
                    simulate=self.robot_sim,
                    safe_travel_z_mm=float(robot_cfg.get("safe_travel_z_mm", 80.0)),
                    device_serial=robot_cfg.get("device_serial") or None,
                    velocity=int(robot_cfg["velocity"]) if "velocity" in robot_cfg else None,
                    acceleration=int(robot_cfg["acceleration"]) if "acceleration" in robot_cfg else None,
                    home_interval=int(robot_cfg.get("home_interval", 1)),
                )
            except Exception as exc:
                raise DeviceUnavailable(f"Robot connection failed: {exc}") from exc
        return self._robot

    def get_peristaltic(self) -> PeristalticPumpController:
        if self._peristaltic is None:
            robot = self.get_robot()
            self._peristaltic = PeristalticPumpController(
                simulate=self.robot_sim,
                robot=None if self.robot_sim else robot,
                pump_cfg=self.raw_cfg.get("peristaltic_pumps", {}),
                test_cell_cfg=self.raw_cfg.get("test_cell", {}),
            )
        return self._peristaltic

    def get_fluidic(self) -> FluidicPumpController:
        if self._fluidic is None:
            cfg = self.raw_cfg.get("fluidic_pump_controller", {})
            try:
                self._fluidic = FluidicPumpController(
                    COM=str(cfg.get("com_port", "COM1")),
                    baud=int(cfg.get("baud", 115200)),
                    sim=self.fluidic_sim,
                    timeout=float(cfg.get("timeout", 60.0)),
                    invert_pumps=cfg.get("invert_pumps"),
                )
            except Exception as exc:
                raise DeviceUnavailable(
                    f"Fluidic pump controller connection failed: {exc}"
                ) from exc
        return self._fluidic

    def get_boards(self) -> BoardManager:
        """Connect to all ENABLED spectral boards (see set_board_enabled).
        Disabled boards are never opened — endpoints that want a subset filter
        the connected runtimes instead.

        auto_heat=False: the web GUI ALWAYS connects with heaters off; heating
        is only ever started by an explicit operator action.
        boards_generation increments on every (re)connect so callers can reset
        connection-scoped bookkeeping (e.g. heater setpoint display)."""
        if self._boards is None:
            enabled = self.enabled_boards
            if not enabled:
                raise DeviceUnavailable("All spectral boards are disabled.")
            try:
                self._boards = BoardManager(
                    self.config_path, board_ids=enabled, auto_heat=False
                )
                self.boards_generation += 1
            except Exception as exc:
                raise DeviceUnavailable(
                    f"Spectral board connection failed (enabled: {sorted(enabled)}): {exc}. "
                    f"If one board is unplugged, disable it in the Spectral tab."
                ) from exc
        return self._boards

    # ── Board enable/disable ──────────────────────────────────────────────────

    @property
    def enabled_boards(self) -> set:
        return {k for k, v in self._board_enabled.items() if v}

    def board_enabled_map(self) -> dict:
        return dict(self._board_enabled)

    def set_board_enabled(self, board_id: str, enabled: bool) -> None:
        """Enable/disable a board, persist the choice, and drop the current
        board connections so the next use reconnects with the new set.
        Caller must hold the boards lock (use manual_op("boards")).

        NOTE: reconnecting re-applies config.yaml temperature targets —
        runtime setpoint overrides from the Temperature tab are reset.
        """
        if board_id not in self._board_enabled:
            raise KeyError(
                f"Unknown board '{board_id}'. Known: {sorted(self._board_enabled)}"
            )
        self._board_enabled[board_id] = bool(enabled)
        try:
            os.makedirs(os.path.dirname(self._web_settings_path), exist_ok=True)
            tmp = self._web_settings_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"board_enabled": self._board_enabled}, f, indent=2)
            os.replace(tmp, self._web_settings_path)
        except OSError:
            logger.warning("Could not persist web_settings.json", exc_info=True)
        if self._boards is not None:
            try:
                self._boards.close()
            except Exception:
                logger.warning("Board close during toggle failed", exc_info=True)
            self._boards = None
        logger.info("Board %s %s.", board_id, "enabled" if enabled else "disabled")

    def reload_config(self) -> None:
        """Re-read config.yaml into raw_cfg and rebuild the coordinate map.
        Called after calibration writes new origins to the file."""
        with open(self.config_path, encoding="utf-8") as f:
            self.raw_cfg = yaml.safe_load(f)
        self.coord_map = CoordinateMap.from_config(self.raw_cfg)
        logger.info("Config reloaded from %s.", self.config_path)

    # ── Release / handover ────────────────────────────────────────────────────

    def release_all(self) -> None:
        """Close every open device handle (port handover to ExperimentRunner,
        or app shutdown). Caller should hold or not need the locks.

        NOTE: closing boards clears their firmware temperature targets
        (BoardManager.close() → clear_temperature_target); this matches the
        CLI behaviour when an experiment takes over.
        """
        if self._boards is not None:
            try:
                self._boards.close()
            except Exception:
                logger.warning("release_all: boards close failed", exc_info=True)
            self._boards = None
        if self._fluidic is not None:
            try:
                self._fluidic.close_ser()
            except Exception:
                logger.warning("release_all: fluidic close failed", exc_info=True)
            self._fluidic = None
        if self._robot is not None:
            try:
                c9 = getattr(self._robot, "_c9", None)
                ser = getattr(c9, "_serial", None) if c9 is not None else None
                if ser is not None:
                    # ftdi_serial.Serial exposes disconnect(); fall back to close().
                    if hasattr(ser, "disconnect"):
                        ser.disconnect()
                    elif hasattr(ser, "close"):
                        ser.close()
            except Exception:
                logger.warning("release_all: robot close failed", exc_info=True)
            self._robot = None
        self._peristaltic = None
        logger.info("HardwareManager: all device handles released.")

    def acquire_all_for_handover(self) -> "list[threading.Lock]":
        """Acquire robot/fluidic/boards locks (blocking, generous timeout) for
        the release-all-before-experiment handover. Returns acquired locks;
        caller must release them."""
        acquired = []
        for name in ("robot", "fluidic", "boards"):
            lock = self._locks[name]
            if not lock.acquire(timeout=10.0):
                for l in reversed(acquired):
                    l.release()
                raise DeviceBusy(
                    f"Device '{name}' is busy — cannot start experiment now."
                )
            acquired.append(lock)
        return acquired

    # ── Status ────────────────────────────────────────────────────────────────

    def status_snapshot(self) -> dict:
        return {
            "mode": self.mode,
            "devices": {
                "robot": {
                    "connected": self._robot is not None,
                    "sim": self.robot_sim,
                },
                "fluidic": {
                    "connected": self._fluidic is not None,
                    "sim": self.fluidic_sim,
                },
                "boards": {
                    "connected": self._boards is not None,
                    "sim": self.boards_sim,
                    "board_ids": [
                        b["board_id"] for b in self.raw_cfg.get("PCBs", [])
                    ],
                    "enabled": self.board_enabled_map(),
                },
            },
        }
