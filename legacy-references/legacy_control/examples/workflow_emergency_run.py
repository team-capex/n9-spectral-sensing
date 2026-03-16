"""Workflow for the experiment"""

import logging
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from control_lib.experiment import Experiment
from control_lib.params import (
    DATA_PATH,
)

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(DATA_PATH + "workflow_basic.log", mode="a"),
        logging.StreamHandler(sys.stdout),
    ],
)
time_now = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")

if __name__ == "__main__":
    # Home robot
    experiment_obj = Experiment()
    experiment_obj.homing()
    experiment_obj.prime_pumps()

    # Prepare grid search chemical space
    # [Cr, Al, Fe, Co, Mn, Ni, Zn, Cu]
    chemical_combination = [0, 0, 0, 0.5, 0, 0.5, 0, 0]  # CoNi

    try:
        experiment_obj.set_experiment_parameters(chemical_combination)
        experiment_obj.ARDUINO = experiment_obj.define_arduino_port()
        experiment_obj.run_emergency_experiment()
        logging.info("Workflow ended with success. Left ECELL full of electrolyte.")

    except Exception as e:
        logging.warning("ERROR!")
        message = f"Sample {experiment_obj.uid} failed with the error following error: \n\n" + str(e)
        experiment_obj.send_mail(message, "N9 robot failed", ["nis@dosan.dk", "enzomo@dtu.dk"])
        # experiment_obj.delete_sample_hdf5()
        logging.exception("message")
