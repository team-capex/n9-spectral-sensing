"""
robot.py
========
Thin wrapper around the 'north' Python package for N9 robot control.

Provides:
  - Simulation mode (logs all moves without calling hardware)
  - High-level pick/place/transfer helpers with automatic post-move homing
  - Consistent safe-height travel pattern for all XY moves
  - Encoder-count goto() for test-cell positioning
  - Test-cell piston deposit/retrieval helpers

north_c9 API used (via C9Controller instance):
    home()                — home all main axes
    move_arm(x, y)        — XY cartesian move at current Z
    move_arm(z=z)         — Z-only move
    move({0..3: count})   — direct encoder-count move [gripper, elbow, shoulder, z_axis]
    request_command('GRPR', [0])  — open gripper
    request_command('GRPR', [1])  — close gripper

Test-cell workflow (encoder-count based):
    1. robot.pick_from(rack_x, rack_y, 44.0)          — pick sample from legacy rack
    2. robot.lower_into_test_cell(insert_counts)       — goto insert pos, open gripper
    3. pump_ctrl.engage_piston()                       — clamp sample
    4. pump_ctrl.fill_peristaltic("H2O_ECELL", vol)   — fill cell
    5. time.sleep(wait_s)
    6. pump_ctrl.drain()                               — empty cell
    7. pump_ctrl.release_piston()                      — unclamp
    8. robot.retrieve_from_test_cell(insert_counts)    — goto insert pos, close gripper
    9. robot.place_at(rack_x, rack_y, 44.0)            — return to rack

Usage (simulation):
    robot = N9RobotController(simulate=True)
    robot.home()
    robot.transfer(from_xyz=(100, 50, 2), to_xyz=(300, 50, 2))

Usage (hardware):
    robot = N9RobotController(simulate=False)  # requires 'north_c9' package
    robot.home()
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# north_c9 package is optional: only required when not in simulation mode.
try:
    from north_c9.controller import C9Controller as _C9Controller
    _NORTH_AVAILABLE = True
except ImportError:
    _C9Controller = None  # type: ignore[assignment]
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
        device_serial:      FTDI device serial number to connect to (e.g. "FT5SJ5LG").
                            If None, connects to the first available FTDI device.
                            Only used when simulate=False.
    """

    def __init__(
        self,
        simulate: bool = True,
        safe_travel_z_mm: float = 80.0,
        device_serial: "str | None" = None,
    ) -> None:
        self.simulate = simulate
        self.safe_travel_z_mm = safe_travel_z_mm
        self._c9: "object | None" = None

        if not simulate and not _NORTH_AVAILABLE:
            raise ImportError(
                "The 'north_c9' package is required for N9 robot hardware control but is not "
                "installed. Install it with: pip install north_c9 @ git+https://gitlab.com/north-robotics/north_c9 "
                "To run without hardware, set robot.simulate: true in config.yaml."
            )

        if not simulate:
            try:
                # Two-step connection that mirrors the legacy NorthC9 pattern:
                #
                # Step 1 — open the FTDI serial port directly via ftdi_serial.Serial.
                #   Legacy: FTDISerialControllerNetwork(network_serial="FT5SJ5LG")
                #           → Serial(device_serial="FT5SJ5LG")  [connect=True, port opens now]
                #   We reproduce this exactly, using the same timeouts:
                #     read_timeout/write_timeout=0.6  — legacy TIMEOUT=0.6 s
                #     connect_settle_time=0.5         — brief settle before first command
                #                                       (legacy had implicit settle from NorthC9 init)
                #
                # Step 2 — wrap with C9Controller, passing the pre-opened Serial as
                #   `connection=`.  Because the port is already live, we set connect=False
                #   to skip the startup ping sequence (10 retries × 1 s) that the legacy
                #   code never ran.
                #
                # This cleanly separates "open port" from "send startup ping", avoiding:
                #   • connect=False alone  → port never opened → "cannot write, device is
                #                            not connected"
                #   • connect=True alone   → ping retries spam logs for 10 s on startup
                from ftdi_serial import Serial as _FtdiSerial  # bundled with north_c9

                _conn = _FtdiSerial(  # type: ignore[call-arg]
                    device_serial=device_serial,
                    read_timeout=0.6,
                    write_timeout=0.6,
                    connect_settle_time=0.5,
                    connect=True,
                )
                self._c9 = _C9Controller(  # type: ignore[call-arg]
                    connection=_conn,
                    home=False,
                    connect=False,       # port already open; skip startup ping
                    command_delay=0.1,   # 100 ms inter-command delay (RS485 half-duplex)
                    use_joystick=False,
                )
            except Exception as exc:
                # C9Controller has a known bug: if ftdi_serial.Serial() raises
                # SerialException before self.connection is assigned, the except block
                # crashes with AttributeError. Catch everything and surface a clear message.
                raise ConnectionError(
                    f"Failed to connect to N9 robot (device_serial={device_serial!r}). "
                    f"Check that the robot is powered, the USB cable is connected, and "
                    f"the FTDI D2XX driver is installed. Underlying error: {exc}"
                ) from exc
            logger.info("N9RobotController: connected to hardware (device_serial=%s).", device_serial)
        else:
            logger.info("N9RobotController: simulation mode — no hardware calls will be made.")

    # ── Low-level wrappers ────────────────────────────────────────────────────

    def goto(self, counts: list) -> None:
        """
        Direct encoder-count move via north API's goto().

        Used for test-cell positions where precise kinematic positioning is
        required and the coordinates are defined in encoder space.

        Args:
            counts: [gripper, elbow, shoulder, z_axis] encoder count values.
        """
        if self.simulate:
            logger.info("[SIM] goto(%s)", counts)
            return
        self._c9.move({0: counts[0], 1: counts[1], 2: counts[2], 3: counts[3]})  # type: ignore[union-attr]

    def home(self) -> None:
        """Run the robot homing sequence."""
        if self.simulate:
            logger.info("[SIM] home_robot()")
            return
        self._c9.home()  # type: ignore[union-attr]

    def move_xy(self, x: float, y: float) -> None:
        """Move to (x, y) at the current safe travel height."""
        if self.simulate:
            logger.info("[SIM] goto_xy_safe(x=%.2f, y=%.2f)", x, y)
            return
        self._c9.move_arm(x=x, y=y, wait=True)  # type: ignore[union-attr]

    def move_z(self, z: float) -> None:
        """Move the Z axis to the given height (mm)."""
        if self.simulate:
            logger.info("[SIM] goto_z_safe(z=%.2f)", z)
            return
        self._c9.move_arm(z=z, wait=True)  # type: ignore[union-attr]

    def open_gripper(self) -> None:
        """Open the gripper."""
        if self.simulate:
            logger.info("[SIM] open_gripper()")
            return
        self._c9.request_command('GRPR', [0])  # type: ignore[union-attr]

    def close_gripper(self) -> None:
        """Close the gripper."""
        if self.simulate:
            logger.info("[SIM] close_gripper()")
            return
        self._c9.request_command('GRPR', [1])  # type: ignore[union-attr]

    # ── High-level helpers ────────────────────────────────────────────────────

    def raise_to_safe(self) -> None:
        """Move Z to safe travel height."""
        self.move_z(self.safe_travel_z_mm)

    def home_after_move(self) -> None:
        """
        Two-step homing to correct robot drift after every high-level move.

        Step 1: Fast XY travel to origin (0, 0) via goto_xy_safe — quick.
        Step 2: Full home sequence via home_robot() — slow but precise.

        Called automatically at the end of pick_from(), place_at(),
        lower_into_test_cell(), and retrieve_from_test_cell().
        """
        logger.info("Homing after move: returning to origin then running home sequence.")
        self.move_xy(0.0, 0.0)
        self.home()

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
        self.home_after_move()

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
        self.home_after_move()

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

    # ── Test-cell helpers (encoder-count based) ───────────────────────────────

    def lower_into_test_cell(self, insert_counts: list) -> None:
        """
        Deposit a sample (already gripped) into the test cell at the insert position.

        Sequence:
          1. goto(insert_counts)  — move to test cell insertion depth
          2. open_gripper()       — release sample; piston will clamp it next
          3. raise_to_safe()      — withdraw to safe Z

        Call pump_ctrl.engage_piston() AFTER this method returns.

        Args:
            insert_counts: Encoder counts for the insertion position
                           (e.g. SAMPLE_INSERT_POS from legacy locator.py).
        """
        logger.info("Lowering sample into test cell (counts=%s)", insert_counts)
        self.goto(insert_counts)
        self.open_gripper()
        self.raise_to_safe()
        self.home_after_move()

    def retrieve_from_test_cell(self, insert_counts: list) -> None:
        """
        Retrieve a sample from the test cell after the piston has been released.

        Sequence:
          1. goto(insert_counts)  — move to test cell insertion depth
          2. close_gripper()      — grip sample
          3. raise_to_safe()      — lift sample clear of test cell

        Call pump_ctrl.release_piston() BEFORE this method.

        Args:
            insert_counts: Same encoder counts used in lower_into_test_cell().
        """
        logger.info("Retrieving sample from test cell (counts=%s)", insert_counts)
        self.goto(insert_counts)
        self.close_gripper()
        self.raise_to_safe()
        self.home_after_move()
