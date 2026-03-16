"""Workflow for the experiment"""

import logging
import pandas as pd
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from control_lib.experiment import Experiment
from control_lib.params import DATA_PATH, HDF5_FILE
from gamry import recipe
from control_lib.tools import (
    save_dataset_to_HDF5,
    timer,
    try_fit_function,
    save_overview_data,
)
from control_lib.gamry_plot import gamry_plot
from plotly import express as px
from control_lib.recipes import (
    get_platinum_eis,
    get_platinum_potential,
    get_reference_electrode_potential,
)
import h5py


def timeout_handler(signum, frame):
    raise TimeoutError("Timeout occurred")


def run_cv_and_save_data(
    measurement_number: int,
    init_voltage: float,
    apex1: float,
    apex2: float,
    final_voltage: float,
    stepsize: float,
    scanrate: float,
    cycles: int,
    group_name: str,
    data_set_name: str = "",
    DATA_path: str = DATA_PATH,
    HDF5_file: str = HDF5_FILE,
) -> None:
    """Run CV and save the raw data and plot. TODO plot should be moved

    Args:
        measurement_number (int): Index of the current measurement.
        init_voltage (float): Initial voltage in V.
        apex1 (float): Max voltage to reach in V.
        apex2 (float): Min voltage to reach in V.
        final_voltage (float): Final voltage in V.
        stepsize (float): Stepszie for the increament of voltage.
        scanrate (float): Scanrate in V/s.
        cycles (float): Number of cycles of CV.
        group_name (str): Group name or sample name to save the data.
        data_set_name (str, optional): Name of the data set. Defaults to "".
        DATA_path (str, optional): Path to store the .jpg at. Defaults to DATA_PATH.
        HDF5_file (str, optional): Path of HDF5 file for saving the data. Defaults to HDF5_FILE.

    """
    logging.info(f"# {measurement_number}  {scanrate} mV/s activation #")
    if data_set_name == "":
        data_set_name = f"{measurement_number}CV{scanrate}mVsx{cycles}"

    logging.info(f"Starting CV on sample {group_name}  -Please wait")

    cv = recipe.CV(
        init_voltage=init_voltage,
        final_voltage=final_voltage,
        apex1=apex1,
        apex2=apex2,
        scanrate1=scanrate,
        stepsize=stepsize,
        cycles=cycles,
    )
    with timer():
        cv.run()
    data = cv.get_data()

    logging.info(f"Saving CSV: {data_set_name}")
    data.to_csv(f"{DATA_path}{group_name}_{data_set_name}.csv", sep="\t", decimal=",")
    save_dataset_to_HDF5(data, group_name, data_set_name)
    # plot_CV(data, group_name, data_set_name, file_path)  # XXX Not used?

    # Make a CV plot of specified CV's in the HDF5 file
    filename_jpg = f"{DATA_path}{group_name}_{data_set_name}.jpg"
    cv_plot = gamry_plot(HDF5_file)
    cv_plot.search(
        [group_name],
        [data_set_name],
    )
    last_cycle = int((abs(apex1 - apex2) / stepsize) * 2)
    cv_plot.plot_CV(
        select_subset_of_data=[-last_cycle, -1],
        select_data=True,
        title=data_set_name + " no ohmic correction",
        xlabel="Potential [V]",
        ylabel="Current [A]",
        ohmic_corrected=False,
        figure_name=filename_jpg,
    )


# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(DATA_PATH + "workflow_pure_nickel_pt_study.log", mode="a"),
        logging.StreamHandler(sys.stdout),
    ],
)
time_now = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")

if __name__ == "__main__":
    # Home robot
    experiment_obj = Experiment()
    experiment_obj.set_experiment_parameters([0, 0, 0, 0, 0, 0, 0, 0])
    experiment_obj.ultrasound_cleaning = False
    experiment_obj.ultrasound_during_experiment = False
    experiment_obj.ultrasound_oxide_remov = False
    experiment_obj.homing()
    experiment_obj.ARDUINO = experiment_obj.define_arduino_port()
    experiment_obj.prime_pumps()

    try:
        experiment_obj.uid = experiment_obj.get_uid()
        uid = experiment_obj.uid
        experiment_obj.sample_rack_no = experiment_obj.get_sample_rack_number()
        experiment_obj.group_name = f"{experiment_obj.uid}_Ni_foam_vs_Pt_wire_unstable_ref"
        group_name = experiment_obj.group_name
        logging.info("Initiating Arduino")
        experiment_obj.save_hdf5_arduino_sensors("before", HDF5_FILE)
        experiment_obj.drain_ecell()
        # experiment_obj.clean_ecell()
        experiment_obj.controller.dispense_ml("KOH", 9)

        #########################################################################################
        # Experiment on dry electrode
        #########################################################################################
        # Make a platinum EIS to find ohmic resistance
        pt_ohmic_resistance, df_pt_eis = get_platinum_eis()
        if pt_ohmic_resistance >= 7.0:
            logging.info(f"Ohmic resistance too large of pt wire being {pt_ohmic_resistance} ohm")

            # Drain cell
            experiment_obj.controller.dispense_ml("Drain", 12)

            # Fill cell
            experiment_obj.controller.dispense_ml("KOH", 9)

            # Redo the measurement
            pt_ohmic_resistance, df_pt_eis = get_platinum_eis()

            if pt_ohmic_resistance >= 7.0:
                logging.warning("Ohmic resistance too large of pt wire after refilling with KOH.")
                logging.warning(f"Ohmic resistance is {pt_ohmic_resistance} ohm")
                raise Exception("Terminating script. Why isn't ohmic resistance around 5 ohms?")

        # Save df_pt_eis to HDF5
        save_dataset_to_HDF5(df_pt_eis, group_name, "Pt_EIS_initial")

        ##################################
        # Get first platinum CV
        try:
            # Get platinum CV to find platinum peak potential
            df_pt_smoothed, pt_peak_potential_smooth, df_pt = get_platinum_potential(
                pt_ohmic_resistance
            )

            # Find the r_squared of the fit
            r_squared, pt_peak_potential_fit, df_pt_fitted = try_fit_function(
                df_pt
            )  # Not really used, only for debugging and logging

            # Plot the smoothing
            df_merged = pd.concat(
                [df_pt[df_pt["Scan cycle"] == 19], df_pt_smoothed, df_pt_fitted], ignore_index=True
            )
            df_merged.reset_index()
            fig = px.scatter(
                df_merged,
                x="Corrected potential (WE vs. RHE) [V]",
                y="Current [A]",
                color="Category",
                title=f"Sample {uid} - Platinum CV peak finding",
            )
            fig.write_html(DATA_PATH + f"{uid}_Platinum_CV_fitting_{1}.html")
            # Store platinum peak potential initial for later use

        except Exception as e:
            logging.warning("Tried to make CV scan and find peak potential of Platinum.")
            logging.warning("Recieved error: ", e)

        platinum_peak_potential_initial_ohmic_corr = pt_peak_potential_smooth
        platinum_peak_potential_fitted_initial_ohmic_corr = pt_peak_potential_fit
        r_squared_initial = r_squared

        # Drop the specified columns from the dataframe,
        # ignoring any errors if columns are not present
        columns_to_drop = ["Category"]
        df_pt = df_pt.drop(columns=columns_to_drop, errors="ignore")

        # Save to HDF5
        save_dataset_to_HDF5(df_pt, experiment_obj.group_name, "Pt_CV_accepted")

        experiment_obj.place_sample_in_cell()

        # Get resistance
        ni_ohmic_resistance, _ = get_platinum_eis()
        logging.info(f"Resistance of nickel sample is: {ni_ohmic_resistance}")
        save_overview_data(
            uid,
            0,
            0,
            0,
            ni_ohmic_resistance,
        )

        run_cv_and_save_data(
            measurement_number=0,
            init_voltage=0.8,
            apex1=1.6,
            apex2=0.8,
            final_voltage=0.8,
            stepsize=0.01,
            scanrate=0.1,
            cycles=100,
            group_name=group_name,
        )

        run_cv_and_save_data(
            measurement_number=16,
            init_voltage=0.8,
            apex1=1.6,
            apex2=0.8,
            final_voltage=0.8,
            stepsize=0.002,
            scanrate=0.01,
            cycles=2,
            group_name=group_name,
        )

        experiment_obj.remove_sample_from_ecell()

        # Log the potential of the reference electrode
        pt_peak_post_measurements = get_reference_electrode_potential(
            group_name, pt_ohmic_resistance
        )

        ##################################
        # Save data to HDF5
        with h5py.File(HDF5_FILE, "a") as f:
            # Save platinum initial and accepted peak as well as reference electrode rest
            # time and pt_ohmic_resistance as attributes in HDF5
            f[group_name].attrs[
                "platinum_peak_potential_smoothed_initial"
            ] = platinum_peak_potential_initial_ohmic_corr
            f[group_name].attrs["platinum_fitted_r_squared_initial"] = r_squared_initial
            f[group_name].attrs[
                "platinum_peak_potential_fitted_initial"
            ] = platinum_peak_potential_fitted_initial_ohmic_corr
            f[group_name].attrs["reference_electrode_rest_time"] = 0
            f[group_name].attrs["pt_ohmic_resistance"] = pt_ohmic_resistance

        experiment_obj.save_hdf5_arduino_sensors("after")

        #########################################################################################
        # Experiment on wet electrode
        #########################################################################################
        # experiment_obj.uid = experiment_obj.get_uid()
        # uid = experiment_obj.uid
        # experiment_obj.sample_rack_no = experiment_obj.get_sample_rack_number()
        # experiment_obj.group_name = f"{experiment_obj.uid}_Ni_foam_vs_Pt_wire_stable_ref"
        # group_name = experiment_obj.group_name
        # experiment_obj.controller.dispense_ml("Drain", 12)
        # experiment_obj.controller.dispense_ml("KOH", 9)
        # experiment_obj.save_hdf5_arduino_sensors("before")

        # # Wait until electrode is at the right spot
        # accept_lower_limit_pt_pot = 0.809 - 0.005
        # accept_upper_limit_pt_pot = 0.809 + 0.01
        # (
        #     pt_peak_intial_ohmic_corr,
        #     pt_peak_accepted_ohmic_corr,
        #     ohmic_resistance_pt,
        #     reference_electrode_rest_time,
        # ) = check_for_reference_electrode_drift(
        #     controller=experiment_obj.controller,
        #     group_name=group_name,
        #     lower_limit_pt_pot=accept_lower_limit_pt_pot,
        #     upper_limit_pt_pot=accept_upper_limit_pt_pot,
        #     uid=uid,
        # )
        # experiment_obj.place_sample_in_cell()

        # # Get resistance
        # ni_ohmic_resistance, _ = get_platinum_eis()
        # logging.info(f"Resistance of nickel sample is now: {ni_ohmic_resistance}")
        # save_overview_data(
        #     uid,
        #     0,
        #     0,
        #     0,
        #     ni_ohmic_resistance,
        # )

        # run_cv_and_save_data(
        #     measurement_number=1,
        #     init_voltage=0.8,
        #     apex1=1.6,
        #     apex2=0.8,
        #     final_voltage=0.8,
        #     stepsize=0.01,
        #     scanrate=0.1,
        #     cycles=100,
        #     group_name=group_name,
        # )

        # run_cv_and_save_data(
        #     measurement_number=17,
        #     init_voltage=0.8,
        #     apex1=1.6,
        #     apex2=0.8,
        #     final_voltage=0.8,
        #     stepsize=0.002,
        #     scanrate=0.01,
        #     cycles=2,
        #     group_name=group_name,
        # )

        # experiment_obj.remove_sample_from_ecell()
        # experiment_obj.save_hdf5_arduino_sensors("after")
        # pt_peak_post_measurements = get_reference_electrode_potential(
        #     group_name, ohmic_resistance_pt
        # )
        experiment_obj.clean_ecell()
        experiment_obj.dispense_electrolyte(9)

        logging.info("Workflow ended with success. Left ECELL full of electrolyte.")

    except Exception as e:
        logging.warning("ERROR!")
        message = f"Sample {experiment_obj.uid} failed with the error following error: \n\n" + str(e)
        experiment_obj.send_mail(message, "N9 robot failed", ["nis@dosan.dk", "enzomo@dtu.dk"])
        experiment_obj.delete_sample_hdf5()
        logging.exception("message")
