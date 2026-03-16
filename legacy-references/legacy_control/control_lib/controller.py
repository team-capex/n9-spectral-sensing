import logging
import time
from locator import vial_rack, sample_rack
from params import (
    PUMP_INDICES,
    PUMP_SPEEDS,
    PUMP_VOLUMES,
    PERISTALTIC_PUMP_INDICES,
    PERISTALTIC_PUMP_CONST_A,
    PERISTALTIC_PUMP_CONST_B,
)
import numpy as np
from north_c9 import NorthC9

__all__ = ("C9Controller",)


class C9Controller:
    """
    A collection of fuctions for C9 arm and pump

    Parameters:

    c9obj: obj
        NorthC9 object.

    velocity: int
        Velocity of the c9 arm

    acceleration: int
        Acceleration of the c9 arm

    start_time : float
        start time of running experiment.
    """

    def __init__(
        self,
        c9obj: NorthC9,
        start_time: float,
        ecell_index=dict,
        velocity: int = 10000,
        acceleration: int = 200000,
    ) -> None:
        self.c9 = c9obj
        self.velocity = velocity
        self.acceleration = acceleration
        self.ecell_index = ecell_index

        self.clamp_empty = True
        self.gripper_empty = True

        self.c9.default_vel = self.velocity
        self.c9.default_accel = self.acceleration
        self.start_time = start_time

    def pump_connected(self, pump_num: int, max_try: int = 20) -> bool:
        """
        Ensure the connection with the pump.

        Args:
            pump_num (int): Position number of the pump
            max_try (int, optional): Maximum number of attempt to establish a
            connection before giving up. Defaults to 20.

        Returns:
            bool: Indicates whether or not the connection has been established.
        """
        # TODO: Temporary fix. To be removed after hardware update.
        count = 0
        while count < max_try:
            try:
                args = self.c9.send_packet("PMST", [pump_num])
                assert args[0] == 0  # 0 means that the pump is free
                elapsed_time = time.time() - self.start_time
                logging.debug(f"Pump #{pump_num} connected at time {elapsed_time}")
                return True
            except Exception as err:
                logging.debug(f"Pump connection failed {count} times with error type {err=}")
                self.c9.delay(0.5)
                count += 1
        return False

    def spin(self, rps: int, seconds: float) -> None:
        """
        Spin robot gripper.

        Args:
            rps (int): Rounds per second
            seconds (float): How many seconds to keep spinning
        """
        self.c9.spin_axis(0, rps * 4000)
        self.c9.delay(seconds / 2)
        self.c9.spin_axis(0, -rps * 4000)
        self.c9.delay(seconds / 2)
        self.c9.spin_axis(0, 0)

    def home_pumps(self, pump_indices: list[int], max_try: int = 20, wait=True) -> None:
        """
        Home pumps based on the index numbers passed.

        Args:
            pump_indices (list[int]): List of indices of the pump numbers
            max_try (int): number of tries to home pumps
            wait (bool): Should it wait for the pump to home before continueing?
        """
        logging.info("Homing pumps")
        if not isinstance(pump_indices, list):
            raise TypeError(f"Pump indices should be a list of integers. Received {pump_indices}.")
        for pump_index in pump_indices:
            if self.pump_connected(pump_index):
                # TODO: Temporary fix. To be removed after hardware update.
                count = 0
                while count < max_try:
                    try:
                        logging.debug(f"Trying to home #{pump_index}")
                        self.c9.home_pump(pump_index, wait=wait)
                        break
                    except Exception as err:
                        logging.warning(
                            f"Error: Failing to home pump #{pump_index} \
                                      with error: {err}"
                        )
                        self.c9.delay(0.5)
                        count += 1
            else:
                raise RuntimeError(
                    f"Cannot connect to the pump during `homing pump` for pump number {pump_index}."
                )
            logging.debug(f"Homing done for pump #{pump_index}")

    def dispense_no_check(
        self, pump_index: int, vol: float, pump_speed: float, max_try: int = 20
    ) -> None:
        """
        Take the volume that is less than the capacity of the pump and dispense without checking
        feasibility.

        Args:
            pump_index (int): Index of pump
            vol (float): volume of liquid in ml.
            pump_speed (float): Pump speed from 0-40
            max_try (int): number of tries to dispense
        """
        pump_name = list(PUMP_INDICES.keys())[list(PUMP_INDICES.values()).index(pump_index)]

        logging.debug(f"despense_no_check() recieved vol: {vol}, pump_speed: {pump_speed}")
        if not self.pump_connected(pump_index):
            raise RuntimeError(
                f"Cannot connect to pump index {pump_index} while trying to dispense {vol} ml."
            )

        # Prepare aspiration
        count = 0
        while count < max_try:
            try:
                logging.debug(f"Turn pump #{pump_index}'s valve RIGHT")
                self.c9.set_pump_valve(pump_index, self.c9.PUMP_VALVE_RIGHT)
                self.c9.delay(0.1)
                break
            except Exception as err:
                logging.warning(
                    f"Error: Pump #{pump_index}'s valve did NOT turn \
                              right with error: {err}"
                )
                self.c9.delay(1)
                count += 1

        # Set pump speed
        count = 0
        while count < max_try:
            try:
                logging.debug(f"Pump #{pump_index}'s speed set")
                self.c9.set_pump_speed(pump_index, pump_speed)
                self.c9.delay(0.1)
                break
            except Exception as err:
                logging.warning(f"Error: Pump #{pump_index}'s speed set failed with error: {err}")
                self.c9.delay(1)
                count += 1

        # Aspirate
        try:
            logging.debug(f"Pump #{pump_index}'s aspirating")
            self.c9.aspirate_ml(pump_index, vol)
            self.c9.delay(0.1)
            if PUMP_VOLUMES[pump_name] > 1.5:
                logging.debug("Pump syringe size was larger than 1.5 mL, so wait 10 seconds")
                self.c9.delay(10)
        except Exception as err:
            logging.warning(f"Error: Pump #{pump_index}'s aspiration failed with error: {err}")
            logging.warning("Please check if the pump aspirated twice the volume requested.")
            if PUMP_VOLUMES[pump_name] > 1.5:
                logging.debug("Pump syringe size was larger than 1.5 mL, so wait 10 seconds")
                self.c9.delay(10)
            self.c9.delay(1)

        # Turn valve
        count = 0
        while count < max_try:
            try:
                logging.debug(f"Turn pump #{pump_index}' valve LEFT")
                self.c9.set_pump_valve(pump_index, self.c9.PUMP_VALVE_LEFT)
                self.c9.delay(0.1)
                break
            except Exception as err:
                logging.warning(
                    f"Error: Pump #{pump_index}'s valve turning LEFT \
                              failed with error: {err}"
                )
                self.c9.delay(1)
                count += 1

        # Set pump speed
        count = 0
        while count < max_try:
            try:
                logging.debug(f"Pump #{pump_index}'s speed set")
                self.c9.set_pump_speed(pump_index, pump_speed)
                self.c9.delay(0.1)
                break
            except Exception as err:
                logging.warning(f"Error: Pump #{pump_index}'s speed set failed with error: {err}")
                self.c9.delay(0.5)
                count += 1

        # Dispense
        try:
            logging.debug(f"Pump #{pump_index} dispensing")
            self.c9.dispense_ml(pump_index, vol)
            self.c9.delay(0.1)
            if PUMP_VOLUMES[pump_name] > 1.5:
                logging.debug("Pump syringe size was larger than 1.5 mL, so wait 10 seconds")
                self.c9.delay(10)
        except Exception as err:
            logging.warning(f"Error: Pump #{pump_index} dispensing failed with error: {err}")
            logging.warning("Please check if the pump dispensed twice the volume requested.")
            self.c9.delay(1)
            if PUMP_VOLUMES[pump_name] > 1.5:
                logging.debug("Pump syringe size was larger than 1.5 mL, so wait 10 seconds")
                self.c9.delay(10)

        logging.debug(f"Dispensed {vol} mL.")

    def dispense_ml(self, pump_name: str, vol: float) -> None:
        """
        Dispense a specified amount of milliliters from a specific peristaltic
        pump.

        Args:
            pump_name (str): Name of the pump/liquid.
            vol (float): volume of liquid to dispense in ml.
        """
        if not vol <= 0:  # Handle 0 ml inputs
            # Check if the pump is a peristaltic or syringe pump
            if pump_name in PERISTALTIC_PUMP_INDICES.keys():  # Peristaltic
                logging.debug("It is a peristaltic pump")
                pump_index = PERISTALTIC_PUMP_INDICES[pump_name]
                logging.info(
                    f"Dispensing {vol} ml of {pump_name} using peristaltic pump {pump_index}."
                )

                const_a = PERISTALTIC_PUMP_CONST_A[pump_name]
                const_b = PERISTALTIC_PUMP_CONST_B[pump_name]
                run_time_seconds = (vol - const_b) / const_a

                self.c9.set_output(pump_index, True)  # on the pump
                self.c9.delay(run_time_seconds)
                self.c9.set_output(pump_index, False)  # off the pump

                logging.info("Dispensing sequence complete.")
            else:  # Syringe pump
                logging.debug("It is a syringe pump")
                pump_index = PUMP_INDICES[pump_name]
                pump_speed = PUMP_SPEEDS[pump_name]
                v = self.c9.pumps[pump_index]["volume"]
                logging.info(
                    f"""Starting sequence for dispensing {vol} ml of {pump_name}
                    using pump index {pump_index}."""
                )
                if vol > v:
                    logging.debug(
                        f"Requested volume is larger than max capacity of pump syringe {v} ml."
                    )
                else:
                    logging.debug(
                        f"Requested volume is larger than max capacity of pump syringe {v} ml."
                    )
                while vol > v:
                    logging.info(f"{vol} ml left.")
                    self.dispense_no_check(pump_index, v, pump_speed)
                    self.c9.delay(0.5)
                    vol -= v
                self.dispense_no_check(pump_index, vol, pump_speed)
                logging.debug("Dispensing sequence complete.")

    def goto_xyz_safe(self, coordinates: list[float], orientation=90.0) -> None:
        """Travel robot arm in a safe manner to a position (go up, go horisontal, go down)

        Args:
            coordinates (list[float]): Coordinates in mm
            orientation (float): The angle of the gripper compared to the
            x-axis/the front of the robot
        """
        if len(coordinates) != 3:
            raise TypeError(f"Length of the coordinates should be 3 (received {len(coordinates)}).")
        logging.debug("Trying to move robot arm z axis to mm position 292")
        self.c9.move_z(292)
        logging.debug(
            "Trying to move robot arm xy axis to target mm position (x,y,z,orientation) = ",
            f"{coordinates[0], coordinates[1], 292, orientation}",
        )
        self.c9.move_xyz(coordinates[0], coordinates[1], 292, tool_orientation=orientation)
        logging.debug(f"Trying to move robot arm z axis to mm position {coordinates[2]}")
        self.c9.move_z(coordinates[2])

    def goto_safe_sample_rack(self, pos: int) -> None:
        """
        Move the robot arm to the specified position number of the sample holder in a in a safe
        manner (up, horisontal movement, down).

        Args:
            pos (int): position number of the sample.
        """
        shift_x = 37.5  # mm in x
        shift_y = 37.0  # mm in x
        shift_z = -12.0 # mm in z
        sample_rack_shifted = [[rp[0] + shift_x, rp[1] + shift_y, rp[2] + shift_z] for rp in sample_rack]
        logging.debug("Go to sample rack")
        self.goto_xyz_safe(sample_rack_shifted[pos])

    def goto_safe_vial_rack(self, n: int) -> None:
        """Moves robot arm to the vial rack, position n,
        in a safe manner (up, horisontal movement, down)
        Args:
            n (int): sample number in question
        """
        self.goto_xyz_safe(vial_rack[n])

    def store_cap(self, holder_coord: list[float]) -> int:
        """
        Store the cap from the vial currently in the vial clamp.
        Can be used after self.c9.uncap().

        Args:
            holder_coord (list[float]): Coordinate of the cap holder in mm.

        Returns:
            z_store (int): The z position of the stored cap (in counts)
        """
        self.goto_xyz_safe(holder_coord)
        gripper_p = self.c9.get_axis_position(0)
        z_p = self.c9.get_axis_position(self.c9.Z_AXIS)
        n_revs = 1.8
        self.c9.move_sync(
            self.c9.GRIPPER,
            self.c9.Z_AXIS,
            int(gripper_p + np.round_(n_revs * self.c9.GRIPPER_COUNTS_PER_REV)),
            int(z_p + np.round_(n_revs * 275)),
            vel=5000,
            accel=40000,
        )
        z_store = self.c9.get_axis_position(self.c9.Z_AXIS)
        self.c9.open_gripper()
        self.c9.move_z(292)
        return z_store

    def recap(
        self,
        holder_coord: list[float],
        vial_coord: list[float],
        z_position_stored_cap: int,
        z_position_clamp_uncapped: int,
        gripper_position,
    ) -> None:
        """
        Put the cap stored on the holder on the vial in the vial clamp.
        Can only be used if there is a stored cap and a vial without cap in the vial clamp.

        Args:
            holder_coord (list[float]): Coordinate of the cap holder in mm.
            vial_coord (list[float]): Coordinate the vial in the vial clamp in mm.
            z_position_stored_cap (int): z position of the stored cap when capped into
            position (in counts)
            z_position_clamp_uncapped (int): z position of the cap when the vial was
            uncapped in the clamp
            gripper_position (int): Rotational position of the cap/ gripper when the vial was
            uncapped in the clamp (in counts)
        """

        # TODO: Have flags to indicate (1) where the cap is and (2) whether the vial is
        # placed in the vial clamp
        self.goto_xyz_safe(holder_coord)
        self.c9.move_axis(self.c9.Z_AXIS, z_position_stored_cap)
        self.c9.close_gripper()
        self.c9.uncap(pitch=2.75)
        self.goto_xyz_safe(vial_coord)
        self.c9.move_axis(self.c9.GRIPPER, gripper_position)
        self.c9.move_axis(self.c9.Z_AXIS, z_position_clamp_uncapped)
        self.c9.cap(pitch=2.75)
        self.c9.open_clamp()
