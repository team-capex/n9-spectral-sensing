"""
robot.py
========
Thin wrapper around the 'north' Python package for N9 robot control.

Provides:
  - Simulation mode (logs all moves without calling hardware)
  - High-level pick/place/transfer helpers
  - Consistent safe-height travel pattern for all XY moves

north API functions used:
    home_robot()
    goto_xy_safe(x, y)
    goto_z_safe(z)
    open_gripper()
    close_gripper()

Usage (simulation):
    robot = N9RobotController(simulate=True)
    robot.home()
    robot.transfer(from_xyz=(100, 50, 2), to_xyz=(300, 50, 2))

Usage (hardware):
    robot = N9RobotController(simulate=False)  # requires 'north' package
    robot.home()
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# north package is optional: only required when not in simulation mode.
try:
    import north as _north
    _NORTH_AVAILABLE = True
except ImportError:
    _north = None  # type: ignore[assignment]
    _NORTH_AVAILABLE = False


class N9RobotController:
    """
    Controls the N9 North Robotics platform.

    When simulate=True (default), all commands are logged but no hardware calls
    are made. This allows the full experiment workflow to be tested without
    a connected robot.

    Args:
        simulate:           If True, log moves without calling hardware.
        safe_travel_z_mm:   Z height (mm) used for all XY travel moves.
    """

    def __init__(self, simulate: bool = True, safe_travel_z_mm: float = 80.0) -> None:
        self.simulate = simulate
        self.safe_travel_z_mm = safe_travel_z_mm

        if not simulate and not _NORTH_AVAILABLE:
            raise ImportError(
                "The 'north' package is required for N9 robot hardware control but is not "
                "installed. Install it following North Robotics instructions. "
                "To run without hardware, set robot.simulate: true in config.yaml."
            )

        if simulate:
            logger.info("N9RobotController: simulation mode — no hardware calls will be made.")

    # ── Low-level wrappers ────────────────────────────────────────────────────

    def home(self) -> None:
        """Run the robot homing sequence."""
        if self.simulate:
            logger.info("[SIM] home_robot()")
            return
        _north.home_robot()

    def move_xy(self, x: float, y: float) -> None:
        """Move to (x, y) at the current safe travel height."""
        if self.simulate:
            logger.info("[SIM] goto_xy_safe(x=%.2f, y=%.2f)", x, y)
            return
        _north.goto_xy_safe(x, y)

    def move_z(self, z: float) -> None:
        """Move the Z axis to the given height (mm)."""
        if self.simulate:
            logger.info("[SIM] goto_z_safe(z=%.2f)", z)
            return
        _north.goto_z_safe(z)

    def open_gripper(self) -> None:
        """Open the gripper."""
        if self.simulate:
            logger.info("[SIM] open_gripper()")
            return
        _north.open_gripper()

    def close_gripper(self) -> None:
        """Close the gripper."""
        if self.simulate:
            logger.info("[SIM] close_gripper()")
            return
        _north.close_gripper()

    # ── High-level helpers ────────────────────────────────────────────────────

    def raise_to_safe(self) -> None:
        """Move Z to safe travel height."""
        self.move_z(self.safe_travel_z_mm)

    def pick_from(self, x: float, y: float, pick_z: float) -> None:
        """
        Full pick sequence:
          1. Open gripper
          2. Travel to (x, y) at safe height
          3. Lower to pick_z
          4. Close gripper (grip sample)
          5. Raise to safe travel height
        """
        self.open_gripper()
        self.move_xy(x, y)
        self.move_z(pick_z)
        self.close_gripper()
        self.raise_to_safe()

    def place_at(self, x: float, y: float, place_z: float) -> None:
        """
        Full place sequence (gripper already holding a sample):
          1. Travel to (x, y) at safe height
          2. Lower to place_z
          3. Open gripper (release sample)
          4. Raise to safe travel height
        """
        self.move_xy(x, y)
        self.move_z(place_z)
        self.open_gripper()
        self.raise_to_safe()

    def transfer(
        self,
        from_xyz: tuple[float, float, float],
        to_xyz: tuple[float, float, float],
        from_pick_z: Optional[float] = None,
        to_place_z: Optional[float] = None,
    ) -> None:
        """
        Pick from one location and place at another in one call.

        Args:
            from_xyz:     (x, y, z) of source location. z is used as pick_z
                          unless from_pick_z is specified.
            to_xyz:       (x, y, z) of destination. z is used as place_z
                          unless to_place_z is specified.
            from_pick_z:  Override Z for the pick descent (mm).
            to_place_z:   Override Z for the place descent (mm).
        """
        fx, fy, fz = from_xyz
        tx, ty, tz = to_xyz
        self.pick_from(fx, fy, from_pick_z if from_pick_z is not None else fz)
        self.place_at(tx, ty, to_place_z if to_place_z is not None else tz)

    # ── Test-cell helpers ─────────────────────────────────────────────────────

    def move_to_test_cell(
        self,
        from_xyz: tuple[float, float, float],
        test_cell_xyz: tuple[float, float, float],
        from_pick_z: Optional[float] = None,
    ) -> None:
        """
        Pick a sample from from_xyz and place it in the test cell.
        Raises to safe height between moves.
        """
        self.transfer(from_xyz, test_cell_xyz, from_pick_z=from_pick_z)

    def return_from_test_cell(
        self,
        test_cell_xyz: tuple[float, float, float],
        to_xyz: tuple[float, float, float],
        to_place_z: Optional[float] = None,
    ) -> None:
        """
        Pick a sample from the test cell and return it to to_xyz.
        """
        self.transfer(test_cell_xyz, to_xyz, to_place_z=to_place_z)
