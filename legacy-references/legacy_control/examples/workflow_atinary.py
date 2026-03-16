"""Workflow for the experiment"""

import logging
from sdlabs_wrapper.wrapper import SDLabsWrapper, initialize_optimization
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from control_lib.experiment import Experiment
from control_lib.params import (
    DILUTION_CHEMICAL_ECELL,
    PUMP_CONCENTRATIONS,
    ECELL_VOLUME,
    DATA_PATH,
)
from control_lib.tools import (
    ConcentrationConverter as CC,
)
import numpy as np


def objective_function(ratios: dict):
    # ratios = [Cr, Al, Fe, Co, Mn, Ni, Cu, Zn]
    # sum the ratios
    print(ratios)
    return np.random.rand()


API_KEY = (
    "eyJhbGciOiJIUzUxMiIsImtpZCI6ImtleV9mZjFhZDE0MmQ1YTU0OWE1Yj",
    "MyMmUwNDZhOTZmYTRkOCIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczo",
    "vL2F1dGguYXRpbmFyeS5jb20iLCJzdWIiOiJiODQ1MzQ4Yy0yYWNjLTQ1N",
    "DAtYTg5ZC0xY2U1NTNhODE5MzgiLCJjb2duaXRvOmdyb3VwcyI6WyJBdXR",
    "vcHJvYnJlIl0sImlhdCI6MTY5MjAwNzQyMiwibmJmIjoxNjkyMDA3NDIyf",
    "Q.tFi89KZPbh93EmJJSal2PwCPKTlzgYRyAn_yT0XiW3N8hq0Bg89cTXQF",
    "BuN_Ia5-jB8fU5areT2POnA7ZZicMA",
)
if __name__ == "__main__":
    # Initialize logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(DATA_PATH + "workflow_dragonfly.log", mode="a"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info("\n\n\n\n\n\nStarting new run")
    time_now = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
    experiment_obj = Experiment()
    experiment_obj.homing()
    experiment_obj.drain_ecell()
    # experiment_obj.prime_pumps()

    CONFIG_FILE = "optimization_config.json"
    # export USER_API_KEY="your_api"

    try:
        wrapper: SDLabsWrapper = initialize_optimization(
            spec_file_path=CONFIG_FILE, inherit_data=True, always_restart=False, api_key=API_KEY
        )

        for iteration in range(wrapper.config.budget):
            suggestions = wrapper.get_new_suggestions(max_retries=5)
            logging.info(suggestions)
            for suggestion in suggestions:
                #    suggestion.measurements = experiment_obj.experiment(suggestion.param_values)
                measurements = objective_function(suggestion.param_values)
                wrapper.send_measurements(measurements)
            logging.info("Suggestions sent")

    except Exception as e:
        logging.warning("ERROR!")
        message = "Your robot failed with the error following error: \n\n" + str(e)
        logging.exception("message")
        # Move the carousel down to avoid spilling
        experiment_obj.controller.c9.move_carousel(0, 105)

    # Move the carousel down to avoid spilling
    experiment_obj.controller.c9.move_carousel(0, 105)

    # Fill Ecell with 1M KOH for resting the ref. electrode
    converter_electrolyte = CC(
        {"KOH": PUMP_CONCENTRATIONS["KOH"]},
        {"KOH": 1},  # ratio, 100% of chemical
        1.0,  # mol/L
        DILUTION_CHEMICAL_ECELL,
        ECELL_VOLUME,
    )
    volumes = converter_electrolyte.calculate_volumes()
    for key, value in volumes.items():
        experiment_obj.controller.dispense_ml(key, value)
    volumes = None

    logging.info("Workflow ended. Filling of ECELL was successfull.")
