"""Workflow for the experiment"""

import logging
import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from north_c9 import NorthC9
from control_lib.controller import C9Controller
from control_lib.params import (
    PUMP_INDICES,
    PUMP_VOLUMES,
    ECELL_INDICES,
    DATA_PATH,
    VEL,
    ACC,
)


class Experiment:
    def __init__(self):
        """Initialize the experiment."""
        logging.debug("Initialized new instance of Experiment class")
        self.c9 = NorthC9(
            "A", network_serial="FT5SJ5LG"
        )  # create a controller object with address A
        self.start_time = time.time()
        self.controller = C9Controller(
            self.c9, start_time=self.start_time, velocity=VEL, acceleration=ACC
        )
        self.pump_indices = []
        for key, val in PUMP_INDICES.items():
            self.pump_indices.append(val)
        self.set_pump_volumes(PUMP_VOLUMES, PUMP_INDICES)

    def set_pump_volumes(
        self, pump_volumes: dict = PUMP_VOLUMES, pump_indices: dict = PUMP_INDICES
    ) -> None:
        """Set the pump volumes of the pumps provided in the dictionaries

        Args:
            pump_volumes(dict): With values from 0 to 12 ml in the form of: {"H2O": 12}
            pump_indices (dict): List of attached pumps and position numbers
            in the form: {"H2O": 0} .... {"H2O": 9}
        """

        for key, volume in pump_volumes.items():
            self.controller.c9.pumps[pump_indices[key]]["volume"] = volume

    def homing(self):
        """Homing of the robot."""
        logging.info("Homing robot")
        self.controller.c9.home_carousel()
        self.controller.c9.home_robot(wait=False)
        self.controller.home_pumps(pump_indices=self.pump_indices, wait=False)
        self.controller.c9.open_clamp()
        self.controller.c9.open_gripper()
        self.controller.c9.set_output(ECELL_INDICES["piston"], False)
        self.controller.c9.set_output(ECELL_INDICES["drain_piston"], False)
        self.controller.c9.set_output(ECELL_INDICES["ultrasound"], False)
        logging.info("Homing ended with success.")

    def prime_pumps(self):
        """Priming of pumps used in experiment."""
        logging.info("Priming pumps")
        self.controller.c9.move_carousel(0, 105)
        self.controller.dispense_ml("Cr", 2)
        self.controller.dispense_ml("Al", 2)
        self.controller.dispense_ml("Fe", 2)
        self.controller.dispense_ml("Co", 2)
        self.controller.dispense_ml("NaOH", 7)
        self.controller.dispense_ml("Mn", 2)
        self.controller.dispense_ml("Ni", 2)
        self.controller.dispense_ml("Cu", 2)  # 15
        self.controller.dispense_ml("Zn", 2)
        self.controller.dispense_ml("H2O", 8)
        self.controller.dispense_ml("Drain", 11)
        self.controller.dispense_ml("H2O_ECELL", 10)
        self.controller.dispense_ml("Drain", 11)
        self.controller.dispense_ml("HCl_ECELL", 10)
        self.controller.dispense_ml("Drain", 11)
        self.controller.dispense_ml("H2O_ECELL", 10)
        self.controller.dispense_ml("Drain", 11)
        self.controller.dispense_ml("KOH", 9)
        logging.info("Priming of pumps ended with success.")

    def drain_ecell(self):
        """Drain the ecell."""
        logging.info("Draining ecell")
        self.controller.dispense_ml("Drain", 15)
        logging.info("Draining of ecell ended with success.")


if __name__ == "__main__":
    # Initialize logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(DATA_PATH + "workflow_prime_pumps.log", mode="a"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info("\n\n\n\n\n\nStarting new run")
    time_now = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")

    # Home robot
    experiment_obj = Experiment()
    # experiment_obj.homing()
    # experiment_obj.drain_ecell()
    experiment_obj.prime_pumps()
    logging.info("Workflow ended.")
