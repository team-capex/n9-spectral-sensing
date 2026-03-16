# This script is used to run the workflow for a video shoot.
# It basically just allows to perform the sequential movements of the robot
# to record the different steps of the workflow.
# The user can choose which step to run by entering the corresponding number.
# The script will run the step and wait for the user to enter the next step.
# The user can also run the whole workflow by entering 11.

sample_rack_no = 69  # XXX Change this number
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from control_lib.experiment import Experiment
import time

# Define the experiment
experiment_obj = Experiment()
experiment_obj.homing()
experiment_obj.prime_pumps()
experiment_obj.set_experiment_parameters(
    chemical_ratios=[0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12],
    synth1_time=0,
    synth2_time=0,
    oh_dip_time=3,
    activation_time=0,
    oxide_remov_time=0,
)

experiment_obj.sample_rack_no = sample_rack_no
experiment_obj.vial_position_number = experiment_obj.get_vial_position_number(2, 0)

user_input = 99
while user_input > 0:
    user_input = int(input("Choose sequence to run (1-10 or 0 for exit): "))
    if user_input == 1:
        # Scene 1
        experiment_obj.place_sample_in_cell()
        time.sleep(5)
        experiment_obj.remove_sample_from_ecell()

    if user_input == 2:
        # Scene 2
        # Dip sample in metal solution
        _ = experiment_obj.place_vial_to_clamp()
        experiment_obj.mix_liquids()
        experiment_obj.controller.goto_safe_sample_rack(experiment_obj.sample_rack_no)
        experiment_obj.controller.c9.close_gripper()
        experiment_obj.dip_sample(experiment_obj.sample_rack_no)
        experiment_obj.clean_vial()

    if user_input == 3:
        # Scene 3
        experiment_obj.place_vial_to_rack(experiment_obj.vial_position_number)

    if user_input == 4:
        # Scene 4
        # Get position number of 2nd clean vial (2 of 2) in experiment
        experiment_obj.vial_position_number = experiment_obj.get_vial_position_number(2, 1)
        # Move vial to clamp
        _ = experiment_obj.place_vial_to_clamp()

    if user_input == 5:
        # Scene 5
        # Fill vial with NaOH
        experiment_obj.dispense_oh_to_vial()

    if user_input == 6:
        # Scene 6
        experiment_obj.controller.goto_safe_sample_rack(experiment_obj.sample_rack_no)
        experiment_obj.controller.c9.close_gripper()
        experiment_obj.dip_sample(experiment_obj.sample_rack_no, spin=False, dip_time=2)

    if user_input == 7:
        # Scene 7
        # Dip sample in NaOH
        # experiment_obj.clean_vial()
        experiment_obj.place_vial_to_rack(
            experiment_obj.vial_position_number,
        )
    if user_input == 8:
        # Scene 8
        # Move the sample into the ecell
        experiment_obj.place_sample_in_cell()
        time.sleep(5)
        experiment_obj.remove_sample_from_ecell()

    if user_input == 10:
        experiment_obj.homing()

    if user_input == 11:
        # Total demo
        experiment_obj.place_sample_in_cell()
        time.sleep(5)
        experiment_obj.remove_sample_from_ecell()
        _ = experiment_obj.place_vial_to_clamp()
        experiment_obj.mix_liquids()
        experiment_obj.controller.goto_safe_sample_rack(experiment_obj.sample_rack_no)
        experiment_obj.controller.c9.close_gripper()
        experiment_obj.dip_sample(experiment_obj.sample_rack_no)
        experiment_obj.clean_vial()
        experiment_obj.place_vial_to_rack(experiment_obj.vial_position_number)
        # Get position number of 2nd clean vial (2 of 2) in experiment
        experiment_obj.vial_position_number = experiment_obj.get_vial_position_number(2, 1)
        # Move vial to clamp
        _ = experiment_obj.place_vial_to_clamp()
        # Fill vial with NaOH
        experiment_obj.dispense_oh_to_vial()
        experiment_obj.controller.goto_safe_sample_rack(experiment_obj.sample_rack_no)
        experiment_obj.controller.c9.close_gripper()
        experiment_obj.dip_sample(experiment_obj.sample_rack_no, spin=False, dip_time=2)
        # Dip sample in NaOH
        experiment_obj.clean_vial()
        experiment_obj.place_vial_to_rack(experiment_obj.vial_position_number)
        # Move the sample into the ecell
        experiment_obj.place_sample_in_cell()
        time.sleep(5)
        experiment_obj.remove_sample_from_ecell()

    if user_input == 12:  # minute show
        for i in range(0, 10):
            # Total demo
            experiment_obj.place_sample_in_cell()
            time.sleep(5)
            experiment_obj.remove_sample_from_ecell()
            _ = experiment_obj.place_vial_to_clamp()
            experiment_obj.mix_liquids()
            experiment_obj.controller.goto_safe_sample_rack(experiment_obj.sample_rack_no)
            experiment_obj.controller.c9.close_gripper()
            experiment_obj.dip_sample(experiment_obj.sample_rack_no)
            experiment_obj.clean_vial()
            experiment_obj.place_vial_to_rack(experiment_obj.vial_position_number)
            # Get position number of 2nd clean vial (2 of 2) in experiment
            experiment_obj.vial_position_number = experiment_obj.get_vial_position_number(2, 1)
            # Move vial to clamp
            _ = experiment_obj.place_vial_to_clamp()
            # Fill vial with NaOH
            experiment_obj.dispense_oh_to_vial()
            experiment_obj.controller.goto_safe_sample_rack(experiment_obj.sample_rack_no)
            experiment_obj.controller.c9.close_gripper()
            experiment_obj.dip_sample(experiment_obj.sample_rack_no, spin=False, dip_time=2)
            # Dip sample in NaOH
            experiment_obj.clean_vial()
            experiment_obj.place_vial_to_rack(experiment_obj.vial_position_number)
            # Move the sample into the ecell
            experiment_obj.place_sample_in_cell()
            time.sleep(5)
            experiment_obj.remove_sample_from_ecell()


print("Exiting script - Goodbye.")
