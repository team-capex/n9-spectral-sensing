"""
robot.py
========
Thin wrapper around the N9 robot for high-level experiment control.

Provides:
  - Simulation mode (logs all moves without calling hardware)
  - High-level pick/place/transfer helpers with automatic post-move homing
  - Consistent safe-height travel pattern for all XY moves
  - Encoder-count goto() for test-cell positioning
  - Test-cell piston deposit/retrieval helpers

Wire protocol (legacy, confirmed working on Windows with D2XX driver):
    Packet: addr_byte + 0x20 + command + [' ' + str(arg)]... + 0x20 + CRC16-LE
    Response: length_byte + addr_byte + 0x20 + cmd_echo + args... + 0x20 + CRC16-LE
    The CRC is a standard CRC-16/ARC (Modbus variant).

Commands used:
    HORO                                — home all main axes
    SYNC  ax0 ax1 c0 c1 vel accel       — synchronous 2-axis move (elbow + shoulder)
    MOAX  axis counts vel accel         — single-axis move (used for Z)
    MORO  g e s z vel accel             — simultaneous 4-axis move (encoder counts)
    GRPR  0|1                           — open (0) / close (1) gripper
    SETO  output_num 0|1                — set digital output
    ROST                                — query robot busy/free status
    AXST  axis                          — query single-axis state

Test-cell insert workflow (XYZ-based):
    1. robot.pick_from(rack_x, rack_y, 44.0)           — pick sample from legacy rack
    2. robot.move_to_test_cell(xyz)                    — travel to test cell position
    3. pump_ctrl.engage_piston()                       — clamp sample (before releasing gripper)
    4. robot.release_at_test_cell()                    — open gripper, home arm
    5. pump_ctrl.fill_peristaltic("H2O_ECELL", vol)   — fill cell
    6. pump_ctrl.drain(vol)                            — drain cell (Drain peristaltic pump)
    7. pump_ctrl.release_piston()                      — unclamp
    8. robot.retrieve_from_test_cell(xyz)              — move to pos, close gripper, home
    9. robot.place_at(rack_x, rack_y, 44.0)            — return to rack

Usage (simulation):
    robot = N9RobotController(simulate=True)
    robot.home()
    robot.transfer(from_xyz=(100, 50, 2), to_xyz=(300, 50, 2))

Usage (hardware, Windows + FTDI D2XX driver):
    robot = N9RobotController(simulate=False, device_serial="FT5SJ5LG")
    robot.home()
"""

from __future__ import annotations

import logging
import math
import time
from typing import Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# _LegacyN9 — self-contained legacy wire-protocol implementation
#
# Reproduces the FTDISerialControllerNetwork + NorthC9.send_packet() protocol
# from legacy-references/north_c9/north_c9.py verbatim, including:
#   • CRC-16/ARC (Modbus variant) appended to every outgoing packet
#   • flush + sleep(0.1) before each write  (RS-485 half-duplex bus settling)
#   • length-prefixed response with CRC verification
#   • Inverse kinematics from n9_kinematics.py for XY → encoder-count conversion
#
# Only the commands required by N9RobotController are implemented.
# ══════════════════════════════════════════════════════════════════════════════

# ── CRC-16/ARC (identical to legacy build_crc / build_crc16_table) ─────────

def _build_crc16_table() -> list:
    result = []
    for byte in range(256):
        crc = 0x0000
        for _ in range(8):
            if (byte ^ crc) & 0x0001:
                crc = (crc >> 1) ^ 0xa001
            else:
                crc >>= 1
            byte >>= 1
        result.append(crc)
    return result

_CRC16_TABLE = _build_crc16_table()

def _build_crc(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        idx = _CRC16_TABLE[(crc ^ byte) & 0xFF]
        crc = ((crc >> 8) & 0xFF) ^ idx
    return crc.to_bytes(2, "little")


# ── Kinematics (from legacy n9_kinematics.py) ───────────────────────────────
# Axis indices
_GRIPPER  = 0
_ELBOW    = 1
_SHOULDER = 2
_Z_AXIS   = 3

# Counts per unit
_GRIPPER_COUNTS_PER_REV  = 4000    # from legacy n9_kinematics.py line 8
_ELBOW_COUNTS_PER_REV    = 51000
_SHOULDER_COUNTS_PER_REV = 101000
_Z_AXIS_COUNTS_PER_MM    = 100

# Offsets / limits
_ELBOW_OFFSET    = 21250
_SHOULDER_OFFSET = 33667
_Z_AXIS_MAX_COUNTS = 26200
_Z_AXIS_OFFSET     = 30   # mm

# Default tool orientation for move_xy.
# Legacy n9_kinematics.py defines POS_Y=0 and POS_X=-pi/2.  ik() subtracts
# pi/2 internally, so the value here must compensate for that AND for any
# physical gripper zero offset.  Testing showed the gripper was 90° off when
# using POS_Y=0, so we use pi/2 here which shifts all gripper angles by +90°.
# If the gripper corrects in the wrong direction, flip the sign to -pi/2.
_DEFAULT_TOOL_ORIENTATION = math.pi / 2   # corrected: was 0.0 (POS_Y), 90° off

# Arm link lengths (mm)
_L1 = _L2 = 170.0


def _rad_to_counts_gripper(rad: float) -> int:
    """Verbatim port of rad_to_counts(GRIPPER, rad) from n9_kinematics.py (note negation)."""
    return -int((rad / math.tau) * _GRIPPER_COUNTS_PER_REV + 0.5)


def _rad_to_counts_elbow(rad: float) -> int:
    return int(_ELBOW_OFFSET - (rad / math.tau) * _ELBOW_COUNTS_PER_REV + 0.5)


def _rad_to_counts_shoulder(rad: float) -> int:
    return int((rad / math.tau) * _SHOULDER_COUNTS_PER_REV + _SHOULDER_OFFSET + 0.5)


def _mm_to_counts_z(z_mm: float) -> int:
    return int(_Z_AXIS_MAX_COUNTS - _Z_AXIS_COUNTS_PER_MM * (z_mm - _Z_AXIS_OFFSET) + 0.5)


def _ik(x: float, y: float, tool_length: float = 0.0) -> tuple[float, float, float]:
    """
    Inverse kinematics: (x, y) mm → (gripper_rad, elbow_rad, shoulder_rad).

    Verbatim port of n9_kinematics.ik() with tool_orientation=DEFAULT_TOOL_ORIENTATION,
    shoulder_preference=SHOULDER_CENTER.

    tool_length: extra reach beyond L2 (mm). When tool_length > 0, the IK solves
    for the joint angles that place a point tool_length mm beyond the gripper at (x, y)
    — used for pipette dispensing where L2' = L2 + pipette_offset_mm. Callers that
    omit tool_length (or pass 0.0) get standard gripper IK, unchanged from before.
    """
    tool_orientation = _DEFAULT_TOOL_ORIENTATION - math.pi / 2  # = -pi/2

    # IK convention: swap axes  (arm 'home' is along +Y robot axis)
    x, y = y, -x

    l2_eff = _L2 + tool_length

    # Elbow angle (cosine rule for the triangle formed by l1, l2_eff, reach)
    cos_e = (x**2 + y**2 - _L1**2 - l2_eff**2) / (-2.0 * _L1 * l2_eff)
    cos_e = max(-1.0, min(1.0, cos_e))  # clamp for numerical safety
    elbow_inside = math.acos(cos_e)
    e1 = math.pi - elbow_inside
    e2 = -e1

    # Shoulder angle
    pseudo_line  = math.sqrt(x**2 + y**2)
    pseudo_angle = math.atan2(y, x)
    cos_s = (_L1**2 + pseudo_line**2 - l2_eff**2) / (2.0 * _L1 * pseudo_line)
    cos_s = max(-1.0, min(1.0, cos_s))
    shoulder_inside = math.acos(cos_s)
    s1 = pseudo_angle - shoulder_inside
    s2 = pseudo_angle + shoulder_inside

    # SHOULDER_CENTER preference: smallest absolute shoulder angle
    if abs(s1) <= abs(s2):
        shoulder_final, elbow_final = s1, e1
    else:
        shoulder_final, elbow_final = s2, e2

    gripper_final = tool_orientation - (shoulder_final + elbow_final)
    return gripper_final, elbow_final, shoulder_final


# ── _LegacyN9 class ─────────────────────────────────────────────────────────

class _LegacyN9:
    """
    Minimal reimplementation of the legacy NorthC9 wire protocol.

    Uses the same bytes-on-wire format as FTDISerialControllerNetwork (Windows)
    from legacy-references/north_c9/north_c9.py so commands are actually
    understood by the firmware running on the N9.

    Required Python package: ftdi_serial  (installed as a dependency of north_c9)
    Required system driver:  FTDI D2XX     (Windows only)
    """

    _FREE          = 0
    _MOVE_COMPLETE = 7

    _DEFAULT_VEL   = 10000   # 10000 c9 default 
    _DEFAULT_ACCEL = 10000  # 200000 c9 default 

    _RESP_TIMEOUT  = 0.6   # s — matches legacy TIMEOUT = 0.6
    _TAIL_TIMEOUT  = 0.2   # s — for the remainder after the length byte
    _PRE_WRITE_SLEEP = 0.1 # s — legacy sleep(0.1) before every write
    _POLL_INTERVAL = 0.05  # s — status-polling cadence while waiting

    def __init__(
        self,
        device_serial: "str | None",
        address: str = "A",
        connect_settle_time: float = 0.5,
    ) -> None:
        try:
            from ftdi_serial import Serial as _FtdiSerial
        except ImportError as exc:
            raise ImportError(
                "The 'ftdi_serial' package is required for N9 hardware control. "
                "Install north_c9 from the project GitLab to get it, or install "
                "ftdi_serial directly."
            ) from exc

        self.c9_addr = ord(address)
        self._serial = _FtdiSerial(  # type: ignore[call-arg]
            device_serial=device_serial,
            read_timeout=self._RESP_TIMEOUT,
            write_timeout=self._RESP_TIMEOUT,
            connect_settle_time=connect_settle_time,
            connect=True,
        )
        # Track current Z encoder counts so XY MORO moves can hold Z steady.
        # Updated by move_arm(z=…) and reset to 0 by _home_joints().
        self._z_cts: int = 0

    # ── Wire-level send/receive ───────────────────────────────────────────────

    def send_packet(
        self,
        command: str,
        args: list = [],
        expect_response: bool = True,
    ) -> list:
        """
        Build, send, and receive one legacy-protocol packet.

        Frame format (outgoing):
            addr_byte  0x20  payload  0x20  CRC16_LE(2)
        where payload = command + ' ' + ' '.join(str(a) for a in args)

        Frame format (response):
            length_byte  addr_byte  0x20  cmd_echo  args...  0x20  CRC16_LE(2)
        The length byte counts all bytes including itself.

        Returns a list of integer arguments from the response.
        """
        payload = " ".join([command] + [str(a) for a in args])
        request = bytes([self.c9_addr]) + b"\x20" + payload.encode("charmap") + b"\x20"
        request += _build_crc(request)

        self._serial.flush()
        time.sleep(self._PRE_WRITE_SLEEP)
        self._serial.write(request)

        if not expect_response:
            return []

        # Read length byte first, then the rest of the frame
        pkt_len_b = self._serial.read(1, self._RESP_TIMEOUT)
        if not pkt_len_b:
            raise TimeoutError(
                f"No response from N9 to '{command}' command "
                f"(waited {self._RESP_TIMEOUT}s). "
                "Check robot power, e-stop, and USB connection."
            )
        pkt_len = int.from_bytes(pkt_len_b, "big")
        rest = self._serial.read(pkt_len - 1, self._TAIL_TIMEOUT)
        response = pkt_len_b + rest

        if len(response) < 4:
            raise IOError(f"Response to '{command}' too short: {response!r}")

        # Verify CRC
        if _build_crc(response[:-2]) != response[-2:]:
            raise IOError(
                f"CRC error in response to '{command}': {response!r}"
            )

        # Parse args: strip length byte and CRC, split on spaces
        # Format: addr_byte SP cmd_echo SP [arg SP]... (trailing SP before CRC)
        inner = response[1:-2]         # strip length + CRC
        terms = inner.split(b" ")      # [addr, cmd, arg1, arg2, ..., b'']
        if len(terms) >= 2 and terms[1] == b"ERR!":
            raise RuntimeError(f"C9 reported ERR! in response to '{command}': {response!r}")
        try:
            return [int(t.decode()) for t in terms[2:] if t]
        except (ValueError, TypeError):
            return []

    # ── Status polling ────────────────────────────────────────────────────────

    def _wait_robot_free(self) -> None:
        """Poll ROST until the robot reports FREE (0). Used after axis-move commands (MORO/MOAX)."""
        while True:
            status = self.send_packet("ROST")
            if status and status[0] == self._FREE:
                return
            time.sleep(self._POLL_INTERVAL)

    def _wait_sequence_free(self) -> None:
        """Poll SQST until the sequence reports FREE (0). Used after sequence commands (HORO)."""
        while True:
            status = self.send_packet("SQST")
            if status and status[0] == self._FREE:
                return
            time.sleep(self._POLL_INTERVAL)

    def _wait_axis_done(self, axis: int) -> None:
        """Poll AXST for the given axis until MOVE_COMPLETE (7)."""
        while True:
            status = self.send_packet("AXST", [axis])
            if status and status[0] == self._MOVE_COMPLETE:
                return
            time.sleep(self._POLL_INTERVAL)

    # ── Command interface (matches what N9RobotController calls) ──────────────

    def home(self) -> None:
        """Send HORO and block until the sequence reports FREE via SQST.

        HORO is a firmware sequence command — its completion must be polled with
        SQST (sequence status), not ROST (robot/axis status). Legacy code uses
        get_sequence_status() → SQST for this exact reason.
        """
        self.send_packet("HORO")
        self._wait_sequence_free()

    def move_arm(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        z: Optional[float] = None,
        wait: bool = True,
        tool_length: float = 0.0,
    ) -> None:
        """
        Move the arm.
          move_arm(x=..., y=...) — XY cartesian move using inverse kinematics
                                   → MORO [gripper, elbow, shoulder, z_hold]
                                   Gripper angle tracks IK for constant tool orientation.
          move_arm(z=...)        — Z-only move
                                   → MOAX Z_AXIS
        """
        if x is not None and y is not None:
            # Full 4-axis MORO (matches legacy move_xy → move_robot_cts → MORO).
            # Gripper angle is computed from IK so tool orientation stays constant
            # across the workspace (DEFAULT_TOOL_ORIENTATION = POS_Y = 0 rad).
            # Z is held at the last tracked position so this is a pure XY travel.
            theta_g, theta_e, theta_s = _ik(x, y, tool_length)
            g_cts = _rad_to_counts_gripper(theta_g)
            e_cts = _rad_to_counts_elbow(theta_e)
            s_cts = _rad_to_counts_shoulder(theta_s)
            self.send_packet(
                "MORO",
                [g_cts, e_cts, s_cts, self._z_cts, self._DEFAULT_VEL, self._DEFAULT_ACCEL],
            )
            if wait:
                self._wait_robot_free()

        elif z is not None:
            z_cts = _mm_to_counts_z(z)
            self._z_cts = z_cts   # keep Z tracking in sync
            self.send_packet(
                "MOAX",
                [_Z_AXIS, z_cts, self._DEFAULT_VEL, self._DEFAULT_ACCEL],
            )
            if wait:
                self._wait_axis_done(_Z_AXIS)

    def move(self, axis_positions: dict) -> None:
        """
        Simultaneous 4-axis move (MORO) in encoder counts.
        axis_positions: {0: gripper_cts, 1: elbow_cts, 2: shoulder_cts, 3: z_cts}
        """
        g = int(axis_positions.get(0, 0))
        e = int(axis_positions.get(1, 0))
        s = int(axis_positions.get(2, 0))
        z = int(axis_positions.get(3, 0))
        self.send_packet(
            "MORO",
            [g, e, s, z, self._DEFAULT_VEL, self._DEFAULT_ACCEL],
        )
        self._wait_robot_free()

    def _home_joints(self) -> None:
        """MORO all joints to zero encoder counts (physical home position).

        This is a software move — it positions all axes at counts = 0 without
        re-zeroing the encoders. Call home() afterwards to run the firmware
        HORO homing sequence if encoder re-zeroing is also required.

        Resets _z_cts to 0 because after this move Z is at its home position.
        """
        self.send_packet("MORO", [0, 0, 0, 0, self._DEFAULT_VEL, self._DEFAULT_ACCEL])
        self._wait_robot_free()
        self._z_cts = 0

    def request_command(self, name: str, args: list = []) -> list:
        """Low-level pass-through: send any named command."""
        return self.send_packet(name, args)

    def output(self, output_num: int, state: bool) -> None:
        """Set a digital output on/off (SETO)."""
        self.send_packet("SETO", [output_num, int(state)])


# ══════════════════════════════════════════════════════════════════════════════
# N9RobotController — public API
# ══════════════════════════════════════════════════════════════════════════════

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
        velocity:           Default move velocity in encoder counts/s.
                            Overrides _LegacyN9._DEFAULT_VEL (default 10000).
                            Set higher (e.g. 30000) to match legacy params.py speed.
        acceleration:       Default move acceleration in encoder counts/s².
                            Overrides _LegacyN9._DEFAULT_ACCEL (default 200000).
        home_interval:      Run home_after_move() only every N completed place_at()
                            calls instead of after every single move.  Between homes
                            the arm travels directly to the next pick location without
                            returning to the physical home position first, which cuts
                            cycle time significantly for batch transfers.
                            1 = home after every move (legacy behaviour).
                            4 = home every 4 moves (recommended default).
                            home_after_move() is always executed unconditionally for
                            release_at_test_cell() and when force_home() is called
                            explicitly (e.g. at the end of a batch).
    """

    def __init__(
        self,
        simulate: bool = True,
        safe_travel_z_mm: float = 80.0,
        device_serial: "str | None" = None,
        velocity: "int | None" = None,
        acceleration: "int | None" = None,
        home_interval: int = 1,
    ) -> None:
        self.simulate = simulate
        self.safe_travel_z_mm = safe_travel_z_mm
        self.home_interval: int = max(1, int(home_interval))
        self._place_count: int = 0          # incremented by every place_at() call
        self._c9: "_LegacyN9 | None" = None

        if not simulate:
            try:
                self._c9 = _LegacyN9(device_serial=device_serial)
            except Exception as exc:
                raise ConnectionError(
                    f"Failed to connect to N9 robot (device_serial={device_serial!r}). "
                    f"Check that the robot is powered, the USB cable is connected, and "
                    f"the FTDI D2XX driver is installed. Underlying error: {exc}"
                ) from exc
            if velocity is not None:
                self._c9._DEFAULT_VEL = velocity
            if acceleration is not None:
                self._c9._DEFAULT_ACCEL = acceleration
            logger.info(
                "N9RobotController: connected to hardware (device_serial=%s, vel=%s, accel=%s).",
                device_serial,
                self._c9._DEFAULT_VEL,
                self._c9._DEFAULT_ACCEL,
            )
        else:
            logger.info("N9RobotController: simulation mode — no hardware calls will be made.")

    # ── Low-level wrappers ────────────────────────────────────────────────────

    def goto(self, counts: list) -> None:
        """
        Direct encoder-count move via MORO.

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
        self._c9.request_command("GRPR", [0])  # type: ignore[union-attr]

    def close_gripper(self) -> None:
        """Close the gripper."""
        if self.simulate:
            logger.info("[SIM] close_gripper()")
            return
        self._c9.request_command("GRPR", [1])  # type: ignore[union-attr]

    # ── High-level helpers ────────────────────────────────────────────────────

    def raise_to_safe(self) -> None:
        """Move Z to safe travel height."""
        self.move_z(self.safe_travel_z_mm)

    def return_to_joint_zero(self) -> None:
        """
        Move all joints to zero encoder counts (MORO [0,0,0,0]) without running
        the firmware HORO homing sequence.

        Pre-positions the arm at the physical home location so the next HORO
        sequence completes faster. Called automatically at experiment shutdown.
        Safe to call in simulate mode — logs only, no hardware call.
        """
        if self.simulate:
            logger.info("[SIM] return_to_joint_zero()")
            return
        self._c9._home_joints()  # type: ignore[union-attr]

    def move_xy_pipette(self, x: float, y: float, tool_length: float) -> None:
        """
        Move so the pipette tip (tool_length mm beyond the gripper along L2)
        lands at (x, y). Uses _ik() with extended L2' = L2 + tool_length — exact,
        single IK call, no approximation or forward-kinematics step.

        Pure math — safe to call in both simulate and real modes.
        """
        if self.simulate:
            logger.info(
                "[SIM] move_xy_pipette(x=%.2f, y=%.2f, tool_length=%.2f)",
                x, y, tool_length,
            )
        else:
            self._c9.move_arm(x=x, y=y, tool_length=tool_length, wait=True)  # type: ignore[union-attr]
        self._place_count += 1
        if self._place_count % self.home_interval == 0:
            self.home_after_move()

    def home_after_move(self) -> None:
        """
        Two-step homing to correct robot drift after every high-level move.

        Step 1: MORO all joints to zero encoder counts (joint-space home).
                This avoids the IK singularity at XY=(0,0) that move_xy would hit.
        Step 2: Full firmware HORO homing sequence — re-zeros encoders precisely.

        Called automatically at the end of pick_from(), place_at(),
        release_at_test_cell(), and retrieve_from_test_cell().
        """
        logger.info("Homing after move: MORO to joint zero then running HORO.")
        if self.simulate:
            logger.info("[SIM] home_after_move()")
            return
        self._c9._home_joints()   # type: ignore[union-attr]
        self._c9.home()           # type: ignore[union-attr]

    def pick_from(self, x: float, y: float, pick_z: float) -> None:
        """
        Full pick sequence:
          1. Open gripper
          2. Travel to (x, y) at safe height
          3. Lower to pick_z
          4. Close gripper (grip sample)
          5. Raise to safe travel height

        Does NOT home after picking — the robot holds the sample and the caller
        is expected to immediately call place_at() or move_to_test_cell().
        Homing while gripping would disrupt the hold and run HORO unnecessarily.
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
          5. home_after_move() — only every home_interval placements
             (call force_home() explicitly after the last sample in a batch)
        """
        self.move_xy(x, y)
        self.move_z(place_z)
        self.open_gripper()
        self.raise_to_safe()
        self._place_count += 1
        if self._place_count % self.home_interval == 0:
            self.home_after_move()

    def force_home(self) -> None:
        """
        Unconditionally run home_after_move() and reset the place counter.

        Call this at the end of every batch transfer (e.g. after the last
        pick_from/place_at pair in load_from_legacy_rack_to_pcb or
        run_ni_test_cell_loop) so the arm always ends each workflow step in
        the homed position regardless of home_interval.
        """
        self._place_count = 0
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

    # ── Test-cell helpers (XYZ-based) ─────────────────────────────────────────

    def move_to_test_cell(self, xyz: tuple) -> None:
        """
        Move to the test cell position while holding the sample in the gripper.

        Call pump_ctrl.engage_piston() AFTER this returns (before releasing gripper).

        Sequence:
          1. raise_to_safe()  — ensure safe Z before XY travel
          2. move_xy(x, y)    — travel over test cell
          3. move_z(z)        — lower to insertion depth

        Args:
            xyz: (x, y, z) robot coordinates (mm) of the test cell position.
        """
        x, y, z = xyz
        logger.info("Moving to test cell position xyz=(%.2f, %.2f, %.2f)", x, y, z)
        self.raise_to_safe()
        self.move_xy(x, y)
        self.move_z(z)

    def release_at_test_cell(self) -> None:
        """
        Open the gripper and clear the arm safely after the piston has been engaged.

        Call pump_ctrl.engage_piston() BEFORE this method.

        Sequence:
          1. open_gripper()   — release sample (piston already clamping it)
          2. raise_to_safe()  — move Z up clear of the sample before any XY motion
          3. home_after_move() — arm is now clear; safe to return to home
        """
        logger.info("Releasing sample at test cell: opening gripper, raising, then homing")
        self.open_gripper()
        self.raise_to_safe()
        self.home_after_move()

    def retrieve_from_test_cell(self, xyz: tuple) -> None:
        """
        Retrieve a sample from the test cell after the piston has been released.

        Call pump_ctrl.release_piston() BEFORE this method.

        Sequence:
          1. raise_to_safe()  — ensure safe Z before XY travel
          2. move_xy(x, y)    — travel over test cell
          3. move_z(z)        — lower to grip depth
          4. close_gripper()  — grip sample
          5. raise_to_safe()  — lift sample clear

        Does NOT home after retrieving — the robot holds the sample and the
        caller is expected to immediately call place_at() to return it to the
        rack.  Homing while gripping would drop the sample before it is placed.

        Args:
            xyz: (x, y, z) same coordinates used in move_to_test_cell().
        """
        x, y, z = xyz
        logger.info("Retrieving sample from test cell xyz=(%.2f, %.2f, %.2f)", x, y, z)
        self.raise_to_safe()
        self.move_xy(x, y)
        self.move_z(z)
        self.close_gripper()
