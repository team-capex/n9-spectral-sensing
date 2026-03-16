# This script is used to calibrate the peristaltic pump.
# The script will ask the user to input the weight of the liquid dispensed by
# the pump for 2, 5, 10 and 20 seconds. The script will output a dataframe
# with the seconds and the weight measured. The user can then use this data
# to calibrate the pump in the params.py file.
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from control_lib.params import (
    PERISTALTIC_PUMP_INDICES,
)
from control_lib.experiment import Experiment

# Define the experiment
experiment_obj = Experiment()
experiment_obj.set_experiment_parameters(
    chemical_ratios=[0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12],
    synth1_time=0,
    synth2_time=0,
    oh_dip_time=3,
    activation_time=0,
    oxide_remov_time=0,
)
# XXX Change this number:
experiment_obj.sample_rack_no = 0
experiment_obj.vial_position_number = experiment_obj.get_vial_position_number(2, 0)


print("This is a peristaltic pump calibration script.\n\n")
print("Peristaltic pumps registered in params.py:")
print(f"{PERISTALTIC_PUMP_INDICES}")
pump_chosen = input("Choose pump name to calibrate: ")

print("\nThe series of seconds for the relay will be: 2, 5, 10 & 20 seconds")
print(
    "Please Tare scale with empty container in it and the hose from the pump "
    "connected to the container."
)

df = pd.DataFrame({"Seconds": [0], "Weight": [0]})

input("Press Enter to continue with the 2 seconds dispensing: ")
experiment_obj.c9.set_output(pump_chosen, True)  # on the pump
experiment_obj.c9.delay(2)
experiment_obj.c9.set_output(pump_chosen, False)  # off the pump
df.loc[len(df.index)] = [2, float(input("Weight in grams measured: "))]

input("Press Enter to continue with the 5 seconds dispensing (remember to tare): ")
experiment_obj.c9.set_output(pump_chosen, True)  # on the pump
experiment_obj.c9.delay(5)
experiment_obj.c9.set_output(pump_chosen, False)  # off the pump
df.loc[len(df.index)] = [5, float(input("Weight in grams measured: "))]

input("Press Enter to continue with the 10 seconds dispensing (remember to tare): ")
experiment_obj.c9.set_output(pump_chosen, True)  # on the pump
experiment_obj.c9.delay(10)
experiment_obj.c9.set_output(pump_chosen, False)  # off the pump
df.loc[len(df.index)] = [10, float(input("Weight in grams measured: "))]

input("Press Enter to continue with the 20 seconds dispensing (remember to tare): ")
experiment_obj.c9.set_output(pump_chosen, True)  # on the pump
experiment_obj.c9.delay(20)
experiment_obj.c9.set_output(pump_chosen, False)  # off the pump
df.loc[len(df.index)] = [20, float(input("Weight in grams measured: "))]

print("Experiment is done")
print(f"{df}")
