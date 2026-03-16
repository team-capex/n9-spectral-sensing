# This script is used to run individual procedures on the robot.
# It allows to perform the sequential movements of the robot
# to perform individual steps of the workflow.
# The user can choose which step to run by entering the corresponding number.
# The script will run the step and wait for the user to enter the next step.

import logging
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from control_lib.params import (
    DATA_PATH,
    ECELL_VOLUME,
    PERISTALTIC_PUMP_INDICES,
    PUMP_SPEEDS,
    ECELL_INDICES,
)
from control_lib.experiment import Experiment
from control_lib.locator import (
    VIAL_CLAMP,
    CAP_HOLDER_ON_POS,
    VIAL_CLAMP_CAP_POS,
    vial_rack,
    SAMPLE_TEST_POS,
    SAMPLE_CLEAN_POS,
    SAMPLE_INSERT_POS,
    HOME,
)

# Define the experiment
experiment_obj = Experiment()
experiment_obj.set_experiment_parameters(
    chemical_ratios=[0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12],
    synth1_time=0,
    synth2_time=0,
    oh_dip_time=3,
    activation_time=0,
    oxide_remov_time=0,
    ultrasound_cleaning=True
)
# XXX Change this number:
experiment_obj.sample_rack_no = 0
experiment_obj.vial_position_number = experiment_obj.get_vial_position_number(2, 0)

if __name__ == "__main__":
    time_now = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(DATA_PATH + "workflow_cleanup_individual.log", mode="a"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    while True:
        print("")
        print("")
        print("Choose what you want to do:")
        print("0: Exit")
        print("1: Home robot")
        print("2: Home pumps")
        print("3: Home carousel")

        print("")
        print("### 1 CLAMP, GRIPPER, ECELL ###")
        print("21: Open everything to relaxed state (pneumatics and relays)")
        print("22: Open Clamp")
        print("23: Close Clamp")
        print("27: Open ecell piston")
        print("28: Close ecell piston")

        print("")
        print("### 2 CAROUSEL ###")
        print("25: Carousel is down, take it up")
        print("26: Turn carousel 180 degrees")
        print("29: Rotate carousel to specified angle/height")

        print("")
        print("### 3 PUMPS ###")
        print("31: Prime pumps")
        print("32: Fill the ecell with KOH")
        print("33: Dispense ml from pump (and rotate carousel accordingly)")
        print("34: Drain ecell for X ml")
        print("35: Clean ecell with HCl")

        print("")
        print("### 4 POTENTIOSTAT ###")
        print("41: Run CV")

        print("")
        print("### 5 CLEANING ###")
        print("51: Clean vials")
        print("52: Clean every second vial")
        print("53: Clean ECELL with HCL and water")

        print("")
        print("### 6 VIAL COMMANDS ###")
        print("61: Grip vial no X and put in clamp and uncap it")
        print("62: Uncap vial")
        print("63: Cap vial")
        print("64: Capped vial is in gripper, put it back to it's place")
        print("65: Cap vial and put it back in rack")

        print("")
        print("### 7 SAMPLE COMMANDS ###")
        print("71: Sample is in the ecell. Return sample from ecell")
        print("72: Sample is in gripper. Put it back to the rack.")
        print("73: Sample from rack to ecell")

        print("")
        print("### 8 Others")
        print("80: Ultrasound ON for 30 seconds")

        number = int(input("Pick the process: "))
        if number == 0:  # Exit
            print("Exiting...")
            exit()

        elif number == 1:  # Home robot arm
            print("Process 1 chosen")
            experiment_obj.controller.c9.home_robot(wait=True)

        elif number == 2:  # Home pumps
            print("Process 2 chosen")
            experiment_obj.controller.home_pumps(
                pump_indices=experiment_obj.pump_indices, wait=False
            )

        elif number == 3:  # Home carousel
            experiment_obj.controller.c9.home_carousel()

        elif number == 21:  # Open everything to relaxed state (pneumatics and relays)
            print("Process 21 chosen")
            experiment_obj.controller.c9.open_clamp()
            experiment_obj.controller.c9.open_gripper()
            experiment_obj.controller.c9.set_output(ECELL_INDICES["piston"], True)
            experiment_obj.controller.c9.set_output(ECELL_INDICES["ultrasound"], False)
            experiment_obj.controller.c9.set_output(ECELL_INDICES["pump"], False)
            experiment_obj.controller.c9.set_output(ECELL_INDICES["piston"], False)

        elif number == 22:  # Open Clamp
            print("Process 22 chosen")
            experiment_obj.controller.c9.open_clamp()

        elif number == 23:  # Close clamp
            print("Process 23 chosen")
            experiment_obj.controller.c9.close_clamp()

        elif number == 25:  # Carousel is down, take it up
            print("Process 25 chosen")
            experiment_obj.controller.c9.move_carousel(0, 0)

        elif number == 26:
            print("Process 26 chosen")
            experiment_obj.controller.c9.move_carousel(180, 0)

        elif number == 27:  # Open ecell piston
            print("Process 27 chosen")
            experiment_obj.controller.c9.set_output(ECELL_INDICES["piston"], True)

        elif number == 28:  # Close ecell piston
            print("Process 28 chosen")
            experiment_obj.controller.c9.set_output(ECELL_INDICES["piston"], False)

        elif number == 29:  # Move carousel
            print("Process 29 chosen")
            angle = float(input("Specify angle in degrees:"))
            height = int(input("Specify height in mm:"))
            experiment_obj.controller.c9.move_carousel(angle, height)

        elif number == 31:  # Prime pumps
            print("Process 31 chosen")
            experiment_obj.set_pump_volumes()

            print("Lower carousel to make sure it doesn't spill")
            experiment_obj.controller.c9.move_carousel(0, 110)
            volume = 2

            print(f"Priming pump Co with {volume} ml")
            experiment_obj.controller.dispense_ml("Co", volume)

            print(f"Priming pump Mn with {volume} ml")
            experiment_obj.controller.dispense_ml("Mn", volume)

            print(f"Priming pump Cr with {volume} ml")
            experiment_obj.controller.dispense_ml("Cr", volume)

            print(f"Priming pump Al with {volume} ml")
            experiment_obj.controller.dispense_ml("Al", volume)

            print(f"Priming pump Fe with {volume} ml")
            experiment_obj.controller.dispense_ml("Fe", volume)

            print(f"Priming pump Zn with {volume} ml")
            experiment_obj.controller.dispense_ml("Zn", volume)

            print(f"Priming pump Cu with {volume} ml")
            experiment_obj.controller.dispense_ml("Cu", volume)

            print(f"Priming pump Ni with {volume} ml")
            experiment_obj.controller.dispense_ml("Ni", volume)

            print(f"Priming pump NaOH with {volume} ml")
            experiment_obj.controller.dispense_ml("NaOH", volume)

            print(f"Priming pump H2O with {volume} ml")
            experiment_obj.controller.dispense_ml("H2O", volume)

            print(f"Priming cell with DRAIN with {12} ml")
            experiment_obj.controller.dispense_ml("Drain", 12)

            print(f"Priming cell with H2O_ECELL with {12} ml")
            experiment_obj.controller.dispense_ml("H2O_ECELL", 12)

            print(f"Priming cell with DRAIN with {12} ml")
            experiment_obj.controller.dispense_ml("Drain", 12)

            print(f"Priming cell with HCl with {10} ml")
            experiment_obj.controller.dispense_ml("HCl_ECELL", 10)

            print(f"Priming cell with DRAIN with {12} ml")
            experiment_obj.controller.dispense_ml("Drain", 12)

            print(f"Priming cell with H2O_ECELL with {12} ml")
            experiment_obj.controller.dispense_ml("H2O_ECELL", 12)

            print(f"Priming cell with DRAIN with {12} ml")
            experiment_obj.controller.dispense_ml("Drain", 12)

            print(f"Priming cell with KOH with {10} ml")
            experiment_obj.controller.dispense_ml("KOH", 10)

            print("Skipping HCl priming on the carousel")
            # print(f"Priming pump HCl with {volume} ml")
            # experiment_obj.controller.dispense_ml("HCl", volume)

        elif number == 32:  # Fill the ecell with KOH
            print("Process 32 chosen")
            experiment_obj.dispense_electrolyte(9)

        elif number == 33:
            print("Process 33 chosen")
            print("Choose between the following pump names")
            for key, value in PUMP_SPEEDS.items():
                print(key)
            for key, value in PERISTALTIC_PUMP_INDICES.items():
                print(key)
            pump_name = str(input("Type pump name: "))
            ml = float(input("Type dispense volume [ml]: "))
            # experiment_obj.controller.c9.move_carousel(0, 105)
            experiment_obj.controller.dispense_ml(pump_name, ml)

        elif number == 34:
            print("Drain cell for X ml")
            ml = float(input("Type drain time [ml]: "))
            experiment_obj.controller.dispense_ml("Drain", ml)

        elif number == 35:  # Clean Ecell
            print("Process 35 chosen")

            print(f"Priming cell with DRAIN with {12} ml")
            experiment_obj.controller.dispense_ml("Drain", 12)

            print(f"Priming cell with H2O_ECELL with {16} ml")
            experiment_obj.controller.dispense_ml("H2O_ECELL", 16)

            experiment_obj.controller.c9.delay(120)

            print(f"Priming cell with DRAIN with {16} ml")
            experiment_obj.controller.dispense_ml("Drain", 16)

            print(f"Priming cell with HCl with {16} ml")
            experiment_obj.controller.dispense_ml("HCl_ECELL", 16)

            experiment_obj.controller.c9.delay(120)
            print("Ultrasound on for 30 seconds")
            experiment_obj.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], 30)
            print("Ultrasound off")
            experiment_obj.controller.c9.delay(1)

            print(f"Priming cell with DRAIN with {16} ml")
            experiment_obj.controller.dispense_ml("Drain", 16)

            print(f"Priming cell with H2O_ECELL with {16} ml")
            experiment_obj.controller.dispense_ml("H2O_ECELL", 16)

            print(f"Priming cell with DRAIN with {16} ml")
            experiment_obj.controller.dispense_ml("Drain", 16)

            print(f"Priming cell with KOH with {10} ml")
            experiment_obj.controller.dispense_ml("KOH", 10)


        # elif number == 41:  # Run CV
        #     print("Process 41 chosen")
        #     # .csv and .jpg storage path:
        #     file_path = "C:/Users/Robot-C9/Nextcloud/C9_robot/Measurements/nisfi/"
        #     measurement_number = 99
        #     init_voltage = 0.8
        #     apex1 = 1.9
        #     apex2 = 0.8
        #     final_voltage = 0.8
        #     stepsize = 0.01
        #     scanrate1 = 0.3
        #     cycles = 1
        #     print(f"# {measurement_number}  {scanrate1} V/s for {cycles} cycles")
        #     data_set = f"{measurement_number}TestCV-{scanrate1}mVsx{cycles}"

        #     print("Starting CV on sample  -Please wait")
        #     cv = recipe.CV(
        #         init_voltage=init_voltage,
        #         final_voltage=final_voltage,
        #         apex1=apex1,
        #         apex2=apex2,
        #         scanrate1=scanrate1,
        #         stepsize=stepsize,
        #         cycles=cycles,
        #     )
        #     with timer():
        #         cv.run()
        #     data = cv.get_data()
        #     print(f"Saving data to .csv file: {data_set}.csv")
        #     # data = np.array(data)
        #     # data = pd.DataFrame(data)

        #     filename_txt = file_path + data_set + ".csv"
        #     data.rename(
        #         columns={
        #             0: "Time (s)",
        #             1: "Vf (V vs Ref)",
        #             2: "Vu (V)",
        #             3: "Im (A)",
        #             4: "Vsig",
        #             5: "Ach (V)",
        #             6: "IERange",
        #             7: "Overbit1",
        #             8: "Stop Test",
        #             9: "Cycle",
        #             10: "Temperature (C)",
        #         },
        #         inplace=True,
        #     )
        #     data.to_csv(filename_txt, index=False, sep="\t", decimal=",")
        #     print(f"Saving plot of dataset:{data_set}")
        #     print(data)

        #     filename_jpg = file_path + data_set + ".jpg"
        #     voltage = data["Vf (V vs Ref)"][0]  # data[1]
        #     ampere = data["Im (A)"][0]  # data[3]
        #     plt.figure()
        #     ax = plt.gca()
        #     plt.title(data_set)
        #     plt.xlabel("Potential (WE vs. RHE) [V]")
        #     plt.ylabel("Current [A]")
        #     data.plot(kind="line", x="Vf (V vs Ref)", y="Im (A)", ax=ax)

        #     plt.plot(voltage, ampere)
        #     plt.savefig(filename_jpg)
        #     plt.close()

        elif number == 51:  # Clean vials
            print("Process 51 chosen")
            experiment_obj.controller.c9.home_robot(wait=True)
            experiment_obj.controller.c9.home_carousel()
            vial_start = int(input("Vial number to start with [0-144]: "))
            vial_end = int(input("Vial number to end with [0-144]: "))

            for i in range(vial_start, vial_end + 1):
                print("Cleaning vial ", i)

                experiment_obj.place_vial_to_clamp(i)
                experiment_obj.clean_vial()
                experiment_obj.place_vial_to_rack(i)
            print("Done with cleaning")

        elif number == 52:  # Clean every second vial
            print("Process 52 chosen")
            experiment_obj.controller.c9.home_robot(wait=True)
            experiment_obj.controller.c9.home_carousel()
            vial_start = int(input("Vial number to start with [0-144]: "))
            vial_end = int(input("Vial number to end with [0-144]: "))

            for i in range(vial_start, vial_end + 1, 2):
                print("Cleaning vial ", i)

                experiment_obj.place_vial_to_clamp(i)
                experiment_obj.clean_vial()
                experiment_obj.place_vial_to_rack(i)

            print("Done with cleaning")

        elif number == 53:  # Clean ecell with HCl and water
            experiment_obj.drain_ecell()
            experiment_obj.clean_ecell()

        elif number == 61:  # Place vial in clamp and uncap it
            print("Process 61 chosen")
            vial_position_number = int(
                input("Pick vial number to place in clamp and uncap [0-151]? ")
            )
            experiment_obj.place_vial_to_clamp(vial_position_number)

        elif number == 62:
            print("62: Uncap vial in clamp")
            experiment_obj.controller.c9.goto_safe(VIAL_CLAMP)
            experiment_obj.controller.c9.close_clamp()
            experiment_obj.controller.c9.uncap(pitch=2.75)
            experiment_obj.z_position_clamp_uncapped = (
                experiment_obj.controller.c9.get_axis_position(experiment_obj.controller.c9.Z_AXIS)
            )  # Z pos. uncapped cap (in counts)
            experiment_obj.gripper_position = experiment_obj.controller.c9.get_axis_position(
                0
            )  # Uncapped cap rotation position (in counts)

        elif number == 63:
            print("63: Cap Vial")
            trigger = False
            try:
                z_position_stored_cap = experiment_obj.z_position_stored_cap
            except NameError:
                trigger = True
            try:
                z_position_clamp_uncapped = experiment_obj.z_position_clamp_uncapped
            except NameError:
                trigger = True
            try:
                gripper_position = experiment_obj.gripper_position
            except NameError:
                trigger = True

            if trigger is True:
                z_position_stored_cap = 25279
                z_position_clamp_uncapped = 16866
                gripper_position = -3580
            experiment_obj.controller.recap(
                CAP_HOLDER_ON_POS,
                VIAL_CLAMP_CAP_POS,
                z_position_stored_cap,
                z_position_clamp_uncapped,
                gripper_position,
            )

        elif number == 64:  # Vial is in gripper, put it back to it's place
            vial_position_number = int(
                input("Enter the vial position number to return to [0-144]: ")
            )
            experiment_obj.controller.goto_safe_vial_rack(vial_position_number)
            experiment_obj.controller.c9.open_gripper()
            experiment_obj.controller.c9.delay(0.3)
            vial_rack_pos = vial_rack[vial_position_number]
            experiment_obj.controller.c9.move_z(vial_rack_pos[2] - 1)

        # elif number == 65:
        #     print("65: Cap vial and put it back in rack")
        #     try:
        #         z_position_stored_cap
        #     except NameError:
        #         z_position_stored_cap = None
        #     try:
        #         z_position_clamp_uncapped
        #     except NameError:
        #         z_position_clamp_uncapped = None
        #     try:
        #         gripper_position
        #     except NameError:
        #         gripper_position = None
        #     if z_position_stored_cap or z_position_clamp_uncapped or gripper_position is None:
        #         z_position_stored_cap = 25279
        #         z_position_clamp_uncapped = 16866
        #         gripper_position = -3580
        #     vial_position_number = int(
        #         input("Enter the vial position number to return to [0-144]: ")
        #     )
        #     # Experiment.place_vial_to_rack(
        #     #    vial_rack[vial_position_number],
        #     # )

        elif number == 71:  # Sample is in the ecell. Return sample from ecell and clean the ecell
            print("Process 71 chosen")
            sample_number = int(input("Enter position in sample rack to return sample to [0-75]: "))
            choice = int(
                input(
                    "Pick sample in ecell at lowest cleaning position (1)\
                        or highest testing position (2)? "
                )
            )

            logging.info("Remove sample from ecell")
            experiment_obj.controller.c9.default_vel = 5000  # Go slow
            if choice == 2:
                experiment_obj.controller.c9.goto_safe(SAMPLE_TEST_POS)
            else:
                experiment_obj.controller.c9.goto_safe(SAMPLE_CLEAN_POS)
            experiment_obj.controller.c9.close_gripper()
            experiment_obj.controller.c9.set_output(ECELL_INDICES["piston"], False)
            experiment_obj.controller.c9.default_vel = 1000  # Go slow
            experiment_obj.controller.c9.goto(SAMPLE_INSERT_POS)
            experiment_obj.controller.c9.default_vel = 30000
            experiment_obj.controller.goto_safe_sample_rack(sample_number)
            experiment_obj.controller.c9.open_gripper()
            experiment_obj.controller.c9.goto_safe(HOME)

        elif number == 72:  # Sample is in gripper. Put it back to the rack.
            print("Proccess 72 chosen.")
            sample_number = int(input("Enter position in sample rack to return sample to [0-75]: "))
            experiment_obj.controller.goto_safe_sample_rack(sample_number)
            experiment_obj.controller.c9.open_gripper()
            experiment_obj.controller.c9.goto_safe(HOME)

        elif number == 73:  # Put sample to ecell
            print("Process 73 chosen")
            # Place sample in ecell
            sample_number = int(input("Enter the sample position number to pick from [0-77]: "))
            experiment_obj.sample_rack_no = sample_number
            experiment_obj.place_sample_in_cell()

        elif number == 80:
            print("Ultrasound on for 30 seconds")
            experiment_obj.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], 30)
            print("Ultrasound off")
            experiment_obj.controller.c9.delay(1)

        else:
            print("Invalid input. Try again.")
