"""
dispenser.py
============
Placeholder for the liquid dispensing system that adds dye solutions to PCB
sensor wells.

Hardware specifics are not yet defined. All methods raise NotImplementedError
when simulate=False, with guidance on next steps.

When simulate=True, all actions are logged without touching any hardware.

Usage (simulation):
    d = LiquidDispenser(simulate=True)
    d.dispense(volume_ul=50.0, dye_type="congo_red", x=100, y=50, z=8)

Usage (hardware — not yet implemented):
    d = LiquidDispenser(simulate=False)   # raises NotImplementedError on first call
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LiquidDispenser:
    """
    Placeholder for liquid dispensing hardware.

    To integrate real hardware:
        1. Set simulate=False in config.yaml (dispenser.simulate)
        2. Replace the NotImplementedError bodies below with your hardware driver calls
        3. Add any hardware-specific config keys to the 'dispenser:' section of config.yaml
           and accept them via the 'config' dict parameter.

    Args:
        simulate:   If True, log actions instead of calling hardware.
        config:     Raw dict from config.yaml 'dispenser:' section (for hardware params).
    """

    def __init__(self, simulate: bool = True, config: dict[str, Any] | None = None) -> None:
        self.simulate = simulate
        self.config = config or {}
        self._volume_ul: float = float(self.config.get("volume_per_dispense_ul", 50.0))

        if not simulate:
            logger.warning(
                "LiquidDispenser: hardware driver is not yet implemented. "
                "All non-simulate calls will raise NotImplementedError. "
                "Set dispenser.simulate: true in config.yaml to run without hardware."
            )
        else:
            logger.info("LiquidDispenser: simulation mode — no hardware calls will be made.")

    # ── Public interface ──────────────────────────────────────────────────────

    def dispense(
        self,
        volume_ul: float,
        dye_type: str,
        x: float,
        y: float,
        z: float,
    ) -> None:
        """
        Move the dispenser to (x, y, z) and dispense the specified volume of dye.

        Args:
            volume_ul:  Volume to dispense in microlitres.
            dye_type:   Reagent identifier string (e.g. "congo_red").
            x, y, z:    Robot coordinates (mm) of the dispense target.

        Raises:
            NotImplementedError: Always raised unless simulate=True.
        """
        if self.simulate:
            logger.info(
                "[SIM] dispense %.1f µl of '%s' at (x=%.2f, y=%.2f, z=%.2f)",
                volume_ul, dye_type, x, y, z,
            )
            return

        raise NotImplementedError(
            f"LiquidDispenser.dispense() is not yet implemented — hardware driver is pending. "
            f"Requested: {volume_ul} µl of '{dye_type}' at (x={x:.2f}, y={y:.2f}, z={z:.2f}). "
            f"Set 'dispenser.simulate: true' in config.yaml to run in simulation mode, "
            f"or implement the hardware driver in dispenser.py."
        )

    def prime(self, dye_type: str) -> None:
        """
        Prime the dispenser line for the given dye before dispensing.

        Args:
            dye_type: Reagent identifier string.

        Raises:
            NotImplementedError: Always raised unless simulate=True.
        """
        if self.simulate:
            logger.info("[SIM] prime dispenser for dye '%s'", dye_type)
            return

        raise NotImplementedError(
            f"LiquidDispenser.prime() is not yet implemented. "
            f"Dye type: '{dye_type}'."
        )

    def flush(self) -> None:
        """
        Flush the dispenser line (cleanup after dispensing session).

        Raises:
            NotImplementedError: Always raised unless simulate=True.
        """
        if self.simulate:
            logger.info("[SIM] flush dispenser line")
            return

        raise NotImplementedError(
            "LiquidDispenser.flush() is not yet implemented. "
            "Implement the hardware driver or set dispenser.simulate: true."
        )

    def home_dispenser(self) -> None:
        """
        Return the dispenser to its home/park position.

        Raises:
            NotImplementedError: Always raised unless simulate=True.
        """
        if self.simulate:
            logger.info("[SIM] home dispenser")
            return

        raise NotImplementedError(
            "LiquidDispenser.home_dispenser() is not yet implemented."
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def default_volume_ul(self) -> float:
        """Default dispense volume from config (µl)."""
        return self._volume_ul
