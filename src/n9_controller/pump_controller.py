"""
pump_controller.py
==================
Peristaltic pump control and digital output (piston/drain) wrapper for the N9 platform.

Pump calibration uses a linear model derived from the legacy C9 system:
    volume_ml = flow_rate_ml_per_s * time_s + offset_ml
    → time_s = (volume_ml - offset_ml) / flow_rate_ml_per_s

Pump indices (from legacy params.py):
    Drain        12      flow_rate 2.2326 ml/s
    KOH          13      flow_rate 0.3363 ml/s  offset +0.0626
    H2O_ECELL    14      flow_rate 0.7518 ml/s  offset -0.2341
    H2O          15      flow_rate 0.6104 ml/s  offset +0.0638
    Air          16      flow_rate 0.6    ml/s  offset +0.1
    HCl_ECELL    17      flow_rate 0.3555 ml/s  offset -0.0795
    H2O_suction  18      flow_rate 0.6    ml/s  offset +0.1
    HCl          19      flow_rate 0.6    ml/s  offset +0.1
    NaOH         20      flow_rate 0.4474 ml/s  offset +0.0702

Digital outputs (from legacy params.py):
    index 2  – hydraulic piston (on = engage/clamp)
    index 3  – drain valve (on = open drain)
    index 6  – ultrasound (on = agitate)
"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# north package is optional: same pattern as robot.py.
try:
    import north as _north
    _NORTH_AVAILABLE = True
except ImportError:
    _north = None  # type: ignore[assignment]
    _NORTH_AVAILABLE = False


class PumpController:
    """
    Controls peristaltic pumps and digital outputs (piston, drain) on the N9.

    When simulate=True (default), all commands are logged only.  In real mode
    the 'north' package must be available.

    Args:
        simulate:  If True, log operations without calling hardware.
        robot:     Live north robot instance (passed in from ExperimentRunner).
                   Only required when simulate=False.
        pump_cfg:  Dict parsed from config.yaml ``peristaltic_pumps:`` section.
                   Format: { name: {index, flow_rate_ml_per_s, offset_ml}, … }
        test_cell_cfg: Dict parsed from config.yaml ``test_cell:`` section,
                   used to look up piston_output_index and drain_output_index.
    """

    def __init__(
        self,
        simulate: bool = True,
        robot: Optional[object] = None,
        pump_cfg: Optional[dict] = None,
        test_cell_cfg: Optional[dict] = None,
    ) -> None:
        self.simulate = simulate
        self._robot = robot

        if not simulate and not _NORTH_AVAILABLE:
            raise ImportError(
                "The 'north' package is required for pump hardware control but is not "
                "installed. Set robot.simulate: true in config.yaml to run without hardware."
            )

        # Build pump lookup: name → {index, flow_rate_ml_per_s, offset_ml}
        self._pumps: dict[str, dict] = {}
        for name, entry in (pump_cfg or {}).items():
            self._pumps[name] = {
                "index": int(entry["index"]),
                "flow_rate_ml_per_s": float(entry["flow_rate_ml_per_s"]),
                "offset_ml": float(entry.get("offset_ml", 0.0)),
            }

        # Digital output indices
        tc = test_cell_cfg or {}
        self._piston_index: int = int(tc.get("piston_output_index", 2))
        self._drain_index: int = int(tc.get("drain_output_index", 3))

        if simulate:
            logger.info("PumpController: simulation mode — no hardware calls will be made.")

    # ── Peristaltic pump helpers ───────────────────────────────────────────────

    def fill_peristaltic(self, pump_name: str, volume_ml: float) -> None:
        """
        Run a named peristaltic pump long enough to dispense ``volume_ml`` mL.

        Duration is computed from the linear calibration:
            time_s = (volume_ml - offset_ml) / flow_rate_ml_per_s

        Args:
            pump_name:  Key from config.yaml peristaltic_pumps (e.g. "H2O_ECELL").
            volume_ml:  Target volume in millilitres.
        """
        pump = self._get_pump(pump_name)
        duration_s = self._volume_to_time(pump, volume_ml)

        logger.info(
            "Pump '%s' (idx %d): dispense %.2f mL → run for %.2f s",
            pump_name, pump["index"], volume_ml, duration_s,
        )

        if self.simulate:
            logger.info("[SIM] set_output(%d, True); sleep(%.2f); set_output(%d, False)",
                        pump["index"], duration_s, pump["index"])
            return

        self._hw_set_output(pump["index"], True)
        time.sleep(duration_s)
        self._hw_set_output(pump["index"], False)

    def drain(self, volume_ml: Optional[float] = None) -> None:
        """
        Run the drain pump.

        Args:
            volume_ml:  If given, run drain pump for the calculated time.
                        If None, open drain valve briefly (5 s) to ensure cell is empty.
        """
        pump = self._get_pump("Drain")
        if volume_ml is not None:
            duration_s = self._volume_to_time(pump, volume_ml)
        else:
            duration_s = 5.0   # default flush time

        logger.info(
            "Drain pump (idx %d): run for %.2f s (%.1f mL)",
            pump["index"], duration_s, volume_ml or 0.0,
        )

        if self.simulate:
            logger.info("[SIM] drain: set_output(%d, True); sleep(%.2f); set_output(%d, False)",
                        pump["index"], duration_s, pump["index"])
            return

        self._hw_set_output(pump["index"], True)
        time.sleep(duration_s)
        self._hw_set_output(pump["index"], False)

    # ── Digital output helpers ─────────────────────────────────────────────────

    def set_output(self, index: int, on: bool) -> None:
        """Set a digital output (0 = off, 1 = on)."""
        logger.info("[%s] set_output(%d, %s)", "SIM" if self.simulate else "HW", index, on)
        if self.simulate:
            return
        self._hw_set_output(index, on)

    def engage_piston(self) -> None:
        """Engage the hydraulic piston to clamp a sample in the test cell."""
        logger.info("Engaging test cell piston (output index %d)", self._piston_index)
        self.set_output(self._piston_index, True)

    def release_piston(self) -> None:
        """Release the hydraulic piston."""
        logger.info("Releasing test cell piston (output index %d)", self._piston_index)
        self.set_output(self._piston_index, False)

    def open_drain(self) -> None:
        """Open the test cell drain valve."""
        logger.info("Opening drain valve (output index %d)", self._drain_index)
        self.set_output(self._drain_index, True)

    def close_drain(self) -> None:
        """Close the test cell drain valve."""
        logger.info("Closing drain valve (output index %d)", self._drain_index)
        self.set_output(self._drain_index, False)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _get_pump(self, name: str) -> dict:
        pump = self._pumps.get(name)
        if pump is None:
            raise KeyError(
                f"Pump '{name}' not found in config. "
                f"Available: {list(self._pumps)}"
            )
        return pump

    @staticmethod
    def _volume_to_time(pump: dict, volume_ml: float) -> float:
        """Convert a target volume to pump run time using linear calibration."""
        flow_rate = pump["flow_rate_ml_per_s"]
        offset = pump["offset_ml"]
        if flow_rate <= 0:
            raise ValueError(f"Pump flow_rate_ml_per_s must be > 0, got {flow_rate}")
        duration = (volume_ml - offset) / flow_rate
        if duration < 0:
            logger.warning(
                "Computed negative pump duration (%.2f s) for volume %.2f mL — clamping to 0.",
                duration, volume_ml,
            )
            duration = 0.0
        return duration

    def _hw_set_output(self, index: int, on: bool) -> None:
        """Call north API set_output."""
        if _north is None:
            raise RuntimeError("north package not available")
        _north.set_output(index, 1 if on else 0)
