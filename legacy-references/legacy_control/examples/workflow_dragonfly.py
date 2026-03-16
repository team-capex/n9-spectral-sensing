"""Workflow for the experiment"""

import logging
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from argparse import Namespace
from dragonfly import minimize_function, load_config
from control_lib.params import (
    DILUTION_CHEMICAL_ECELL,
    PUMP_CONCENTRATIONS,
    ECELL_VOLUME,
    DATA_PATH,
)
from control_lib.tools import (
    ConcentrationConverter as CC,
)
from control_lib.experiment import Experiment

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
    #experiment_obj.homing()
    #experiment_obj.prime_pumps()

    # Load configuration
    domain_constraints = [{"constraint": "Cr + Al + Fe + Co + Mn + Ni + Cu + Zn == 1.0"}]
    domain_vars = [
        {"name": "Cr", "type": "discrete_numeric", "items": "0.0:0.05:1.0"},
        {"name": "Al", "type": "discrete_numeric", "items": "0.0:0.05:1.0"},
        {"name": "Fe", "type": "discrete_numeric", "items": "0.0:0.05:1.0"},
        {"name": "Co", "type": "discrete_numeric", "items": "0.0:0.05:1.0"},
        {"name": "Mn", "type": "discrete_numeric", "items": "0.0:0.05:1.0"},
        {"name": "Ni", "type": "discrete_numeric", "items": "0.0:0.05:1.0"},
        {"name": "Cu", "type": "discrete_numeric", "items": "0.0:0.05:1.0"},
        {"name": "Zn", "type": "discrete_numeric", "items": "0.0:0.05:1.0"},
    ]
    config_params = {"domain": domain_vars, "domain_constraints": domain_constraints}
    config = load_config(config_params)

    samples_to_run = 18  # Number of samples to proccess, maximum is 71
    options = Namespace(
        init_capital=0,  # Number of initial random samples
        build_new_model_every=1,
        report_results_every=1,
        progress_load_from_and_save_to=DATA_PATH + "dragonfly_progress_30-01-2025.pkl",
        progress_save_every=1,
    )

    try:
        min_val, min_x_list, history = minimize_function(
            experiment_obj.experiment,
            config.domain,
            samples_to_run,
            config=config,
            options=options,
        )
        logging.info(
            f"Best combination found so far: {min_x_list=}, with the potential {min_val=} V"
        )

    except Exception as e:
        logging.warning("ERROR!")
        message = "Your robot failed with the error following error: \n\n" + str(e)
        logging.exception(f"{message}")
        # Move the carousel down to avoid spilling
        experiment_obj.controller.c9.move_carousel(0, 105)

    # Move the carousel down to avoid spilling
    experiment_obj.controller.c9.move_carousel(0, 105)

    # Fill Ecell with 1M KOH for resting the ref. electrode
    experiment_obj.controller.dispense_ml("Drain", 12)
    converter_electrolyte = CC(
        {"KOH": PUMP_CONCENTRATIONS["KOH"]},
        {"KOH": 1},  # ratio, 100% of chemical
        1.0,  # mol/L
        DILUTION_CHEMICAL_ECELL,
        ECELL_VOLUME,
    )
    volumes = converter_electrolyte.calculate_volumes()
    for key, value in volumes.items():
        pass
        experiment_obj.controller.dispense_ml(key, value)
    volumes = None

    logging.info("Workflow ended. Filling of ECELL was successfull.")
