from __future__ import annotations

import os
os.environ["MPLBACKEND"] = "Agg" # Must happen before any matplotlib imports (allows plotting with multiple threads)

from dataclasses import dataclass
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import yaml

from spectral_board_manager.spectral_sensor import SpectralSensor
from spectral_board_manager.data_parser import SpectralAnalysis


# ----------------------------
# Config models
# ----------------------------

@dataclass(frozen=True)
class SensorSettings:
    gain: int
    atime: int
    astep: int


@dataclass(frozen=True)
class BoardConfig:
    board_id: str
    com_port: str
    sensors_in_use: int
    sensor_settings: SensorSettings
    sample_type: str = "liquid"         # "solid" or "liquid"
    control_voltage: float = 0.0        # 0..10


@dataclass(frozen=True)
class ManagerConfig:
    data_dir: str
    boards: List[BoardConfig]


# ----------------------------
# Board runtime wrapper
# ----------------------------

class _BoardRuntime:
    """
    Holds the live objects for one board: SpectralSensor + SpectralAnalysis
    """
    def __init__(self, cfg: BoardConfig, data_dir: str):
        self.cfg = cfg

        self.sensor = SpectralSensor(cfg.com_port)
        self.analyser = SpectralAnalysis(data_dir)

        self._apply_settings()

        # Always start in a safe state: 0V when idle
        self._safe_set_voltage(0.0)

    def _apply_settings(self) -> None:
        leds_on = (self.cfg.sample_type or "liquid").strip().lower() == "solid"
        self.sensor.set_leds_on_during_measurements(leds_on)

        s = self.cfg.sensor_settings
        self.sensor.set_sensor_settings(s.gain, s.atime, s.astep)

    def _safe_set_voltage(self, v: float) -> None:
        # Clamp and set. If your SpectralSensor already validates, this is still fine.
        v = max(0.0, min(10.0, float(v)))
        self.sensor.set_control_voltage(v)

    def run_once(self, experiment_id: str | None = None) -> None:
        """
        One full scan of all active sensors (1..sensors_in_use).
        Control voltage is applied ONLY during this scan, then returned to 0V.
        """
        # Control ON for the duration of the scan
        self._safe_set_voltage(self.cfg.control_voltage)

        try:
            for i in range(1, self.cfg.sensors_in_use + 1):
                # Get data string from sensor readings
                data = self.sensor.read_sensor(i)

                # Parse to extract and label data
                self.analyser.parse_new_data(data, self.cfg.board_id, experiment_id)

                # Plot and estimate HEX colour
                _, hex_color = self.analyser.plot_normalised_spectrum()

                # Append labelled data to CSV
                self.analyser.append_to_csv(hex_color)

        finally:
            # Absolutely ensure default safe state between runs
            self._safe_set_voltage(0.0)

    def close(self) -> None:
        """
        Make a best effort to return to safe state and close serial.
        """
        try:
            self._safe_set_voltage(0.0)
        except Exception:
            pass

        self.sensor.close_ser()


# ----------------------------
# BoardManager
# ----------------------------

class BoardManager:
    """
    Manages up to 5 SpectralSensor boards and runs them concurrently.
    """
    MAX_BOARDS = 5

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.cfg = self._load_config(config_path)

        # Populated by CLI
        self.experiment_id = None

        if len(self.cfg.boards) > self.MAX_BOARDS:
            raise ValueError(f"config has {len(self.cfg.boards)} boards; max is {self.MAX_BOARDS}")

        os.makedirs(self.cfg.data_dir, exist_ok=True)

        self._boards: List[_BoardRuntime] = [
            _BoardRuntime(bcfg, data_dir=self.cfg.data_dir) for bcfg in self.cfg.boards
        ]

        # Optional: lock if you later decide to share a single analyser/file across boards.
        self._lock = threading.Lock()

    @staticmethod
    def _load_config(path: str) -> ManagerConfig:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        data_dir = raw.get("data_dir", "./data")
        boards_raw = raw.get("boards", [])
        boards: List[BoardConfig] = []

        for b in boards_raw:
            ss = b.get("sensor_settings", {})
            boards.append(
                BoardConfig(
                    board_id=str(b["board_id"]),
                    com_port=str(b["com_port"]),
                    sensors_in_use=int(b["sensors_in_use"]),
                    sensor_settings=SensorSettings(
                        gain=int(ss["gain"]),
                        atime=int(ss["atime"]),
                        astep=int(ss["astep"]),
                    ),
                    sample_type=str(b.get("sample_type", "liquid")),
                    control_voltage=float(b.get("control_voltage", 0.0)),
                )
            )

        # Basic validation
        for bc in boards:
            if not (1 <= bc.sensors_in_use <= 16):
                raise ValueError(f"{bc.board_id}: sensors_in_use must be 1..16")
            if bc.sensor_settings.gain not in (1, 2, 4, 8):
                raise ValueError(f"{bc.board_id}: gain must be 1,2,4,8")
            if not (0 <= bc.sensor_settings.atime <= 255):
                raise ValueError(f"{bc.board_id}: atime must be 0..255")
            if not (0 <= bc.sensor_settings.astep <= 65535):
                raise ValueError(f"{bc.board_id}: astep must be 0..65535")
            if not (0.0 <= bc.control_voltage <= 10.0):
                raise ValueError(f"{bc.board_id}: control_voltage must be 0..10")

            st = (bc.sample_type or "liquid").strip().lower()
            if st not in ("solid", "liquid"):
                raise ValueError(f"{bc.board_id}: sample_type must be 'solid' or 'liquid'")

        return ManagerConfig(data_dir=data_dir, boards=boards)

    def run(self) -> None:
        """
        Trigger all boards to scan simultaneously.
        Blocks until all boards are finished.
        """
        if not self._boards:
            return

        # One thread per board is ideal here (serial I/O bound).
        with ThreadPoolExecutor(max_workers=len(self._boards)) as ex:
            futures = {ex.submit(b.run_once(self.experiment_id)): b.cfg.board_id for b in self._boards}

            # If any board fails, we surface the exception.
            # Each board still guarantees voltage->0V due to finally block.
            for fut in as_completed(futures):
                board_id = futures[fut]
                try:
                    fut.result()
                except Exception as e:
                    raise RuntimeError(f"Board {board_id} failed during run(): {e}") from e

    def close(self) -> None:
        for b in self._boards:
            b.close()
