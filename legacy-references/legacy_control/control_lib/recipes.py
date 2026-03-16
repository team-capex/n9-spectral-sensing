import logging
import pandas as pd
import h5py
import time
import plotly.express as px
from controller import C9Controller
import smtplib
from email.mime.text import MIMEText
from params import (
    OHMIC_CORRECTION_FACTOR,
    DATA_PATH,
    HDF5_FILE,
)
from measurements import (
    run_cp_and_save_data,
    run_cv_and_save_data,
    run_EIS_and_save_data,
    get_platinum_cv,
    get_EIS,
)
from tools import (
    find_ohmic_resistance,
    correct_for_ohmic_resistance,
    filter_data,
    smooth_data_savitzky_golay,
    set_column_headers_cv,
    save_dataset_to_HDF5,
    try_fit_function,
)
from gamry_plot import gamry_plot

__all__ = (
    "get_platinum_eis",
    "get_platinum_potential",
    "electrochemical_measurements",
    "check_for_reference_electrode_drift",
    "get_reference_electrode_potential",
)


def send_mail( msg: str, title: str, receivers: list):
    """Send an email to the specified receivers

    Args:
        msg (str): Message to send
        title (str): Title of the email
        receivers (list): List of receivers
    """
    smtp = smtplib.SMTP("smtp.simply.com", port=587)

    sender = "robot@dosan.dk"

    message = MIMEText(f"{msg}")
    message["Subject"] = title
    message["From"] = "robot@dosan.dk"
    message["To"] = "Nis"

    try:
        smtp.ehlo()  # send the extended hello to our server
        smtp.starttls()  # tell server we want to communicate with TLS encryption
        smtp.login("robot@dosan.dk", "abc12345678")  # login to our email server
        smtp.sendmail(sender, receivers, message.as_string())
        smtp.quit()  # close the connection
        logging.info("Successfully sent email")
    except Exception:
        logging.warning("Error: unable to send email")


def get_platinum_eis():
    """Measure the potential of the platinum electrode

    Returns:
        ohmic_resistance (float): Ohmic resistance of the platinum electrode
        df_eis (pd.DataFrame): EIS data of the platinum electrode

    """
    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        logging.info("Testing for reference electrode drift.")
        try:
            # Get EIS measurements to find ohmic resistance
            df_eis = get_EIS(
                init_freq=100000.0,
                final_freq=10,
                pts_per_decade=10,
                dc=1.5,  # DC potential (V)
                ac=0.01,  # AC potential (V)
            )
            make_another_scan_attempt = False

        except Exception as e:
            logging.error(f"Error in reference electrode drift test: {e}")
            logging.info("Trying to scan again.")
            make_another_scan_attempt = True
            time.sleep(10)

    # Find the ohmic resistance of the EIS
    ohmic_resistance = find_ohmic_resistance(df_eis)

    return ohmic_resistance, df_eis


def get_platinum_potential(ohmic_resistance: float):
    """Measure the potential of the platinum electrode

    Args:
        ohmic_resistance (float): Ohmic resistance of the platinum electrode

    Returns:
        df_pt (pd.DataFrame): Original data of the platinum electrode
    """
    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        try:
            # Get the platinum CV
            df_pt = get_platinum_cv(
                init_voltage=0,
                final_voltage=0,
                apex1=1.4,
                apex2=0,
                stepsize=0.001,
                scanrate=1,
                cycles=20,
            )
            make_another_scan_attempt = False
        except Exception as e:
            logging.error(f"Error in platinum CV measurement: {e}")
            logging.info("Trying to scan again after a little waiting.")
            make_another_scan_attempt = True
            time.sleep(60)

    # Set column headers
    df_pt = set_column_headers_cv(df_pt)
    logging.debug(f"df_pt: {df_pt.to_string}")

    # Correct for ohmic resistance
    df_pt = correct_for_ohmic_resistance(df_pt, ohmic_resistance, OHMIC_CORRECTION_FACTOR)

    return df_pt


def electrochemical_measurements(
    group_name: str,
    unique_id: int,
    controller: C9Controller,
    ultrasound: bool,
    HDF5_file: str = HDF5_FILE,
    DATA_path: str = DATA_PATH,
):
    """Measurement protocol for the current experiment

    Args:
        group_name (str): Group name or sample name to save the data in the .hdf5 file
        unique_id (int): Unique ID of the sample
        controller (C9Controller): Instance of C9Controller.
        ultrasound (bool): Whether to turn on the ultrasound or not
        HDF5_file (str, optional): Path to the HDF5 file to store the data. Defaults to HDF5_FILE.
        DATA_path (str, optional): Path to store the .jpg of the electrochemical activation.
        Defaults to DATA_PATH.

    Returns:
        overpotential_to_return (float): Overpotential of the sample at 10 mA
        ohmic_resistance (float): Ohmic resistance of the sample
    """

    logging.info("Starting electrochemical measurements. Please wait - this takes a long time.")

    # homing gripper to avoid potential accumulated error messing up gripper alignment,
    # needs more investigation
    gripper_home_cmd = controller.c9.home_axis(controller.c9.GRIPPER, wait=False)

    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        try:
            run_cv_and_save_data(
                measurement_number=0,
                init_voltage=0,
                apex1=1.6,
                apex2=0,
                final_voltage=0,
                stepsize=0.01,
                scanrate=0.4,
                cycles=100,
                group_name=group_name,
            )
            make_another_scan_attempt = False
        except Exception as e:
            logging.error(f"Error in CV measurement: {e}")
            logging.info("Trying to scan again.")
            make_another_scan_attempt = True
            time.sleep(10)

    controller.c9.delay(3)

    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        try:
            run_cv_and_save_data(
                measurement_number=1,
                init_voltage=0.8,
                apex1=1.6,
                apex2=0.8,
                final_voltage=1.5,
                stepsize=0.002,
                scanrate=0.01,
                cycles=2,
                group_name=group_name,
            )
            make_another_scan_attempt = False
        except Exception as e:
            logging.error(f"Error in CV measurement: {e}")
            logging.info("Trying to scan again.")
            make_another_scan_attempt = True
            time.sleep(10)

    # Potentiostatic EIS mode goes here:
    controller.c9.delay(3)
    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        try:
            ohmic_resistance = run_EIS_and_save_data(
                measurement_number=8,
                init_freq=100000.0,
                final_freq=1,
                pts_per_decade=10,
                dc=1.5,  # DC potential (V)
                ac=0.01,  # AC potential (V)
                group_name=group_name,
            )
            make_another_scan_attempt = False
        except Exception as e:
            logging.error(f"Error in EIS measurement: {e}")
            if "timed out" in f"{e}":
                logging.warning("Trying to continue code even though the EIS gave a timeout.")
                make_another_scan_attempt = False
            if "name already exists" in f"{e}":
                logging.warning("Dataset name already exist. Trying to proceed with measurements.")
                make_another_scan_attempt = False
            else:
                logging.info("Trying to scan again.")
                make_another_scan_attempt = True
                time.sleep(10)

    # EIS Galvanostatic mode goes here (remember to correct in
    # run_EIS_and_sava_data function):
    # controller.c9.delay(3)
    # ohmic_resistance = run_EIS_and_save_data(
    #     measurement_number=8,
    #     init_freq=200000.0,
    #     final_freq=1,
    #     pts_per_decade=12,
    #     dc=0.01,  # DC current (Ampere)
    #     ac=0.001,  # AC current (Ampere)
    #     sdc=0.0,  # DC voltage XXX May be the area cm2
    #     zguess=1.0,  # Initial guess for impedance
    #     group_name=group_name,
    # )

    # block here until gripper homing is done
    # - should be long done, this is just for safety
    gripper_home_cmd.wait()

    controller.c9.delay(3)
    if ultrasound:
        pass
        # controller.c9.set_output(ECELL_INDICES["ultrasound"], True)
    else:
        pass

    controller.c9.delay(3)
    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        try:
            _ = run_cp_and_save_data(
                measurement_number=10,
                init_ampere=0.05,
                tinit=10,
                ampere_step2=0.05,
                tstep2=60,
                sample_rate=0.5,
                group_name=group_name,
                ohmic_resistance=ohmic_resistance,
                ohmic_correction_factor=OHMIC_CORRECTION_FACTOR,
            )
            make_another_scan_attempt = False
        except Exception as e:
            logging.error(f"Error in CP measurement: {e}")
            logging.info("Trying to scan again.")
            make_another_scan_attempt = True
            time.sleep(10)

    controller.c9.delay(3)
    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        try:
            _ = run_cp_and_save_data(
                measurement_number=11,
                init_ampere=0.02,
                tinit=10,
                ampere_step2=0.02,
                tstep2=60,
                sample_rate=0.5,
                group_name=group_name,
                ohmic_resistance=ohmic_resistance,
                ohmic_correction_factor=OHMIC_CORRECTION_FACTOR,
            )
            make_another_scan_attempt = False
        except Exception as e:
            logging.error(f"Error in CP measurement: {e}")
            logging.info("Trying to scan again.")
            make_another_scan_attempt = True
            time.sleep(10)

    controller.c9.delay(3)
    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        try:
            overpotential_to_return = run_cp_and_save_data(
                measurement_number=12,
                init_ampere=0.01,
                tinit=10,
                ampere_step2=0.01,
                tstep2=60,
                sample_rate=0.5,
                group_name=group_name,
                ohmic_resistance=ohmic_resistance,
                ohmic_correction_factor=OHMIC_CORRECTION_FACTOR,
                save_overview_table=True,
                unique_id=unique_id,
            )
            make_another_scan_attempt = False
        except Exception as e:
            logging.error(f"Error in CP measurement: {e}")
            logging.info("Trying to scan again.")
            make_another_scan_attempt = True
            time.sleep(10)

    controller.c9.delay(3)
    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        try:
            _ = run_cp_and_save_data(
                measurement_number=13,
                init_ampere=0.005,
                tinit=10,
                ampere_step2=0.005,
                tstep2=60,
                sample_rate=0.5,
                group_name=group_name,
                ohmic_resistance=ohmic_resistance,
                ohmic_correction_factor=OHMIC_CORRECTION_FACTOR,
            )
            make_another_scan_attempt = False
        except Exception as e:
            logging.error(f"Error in CP measurement: {e}")
            logging.info("Trying to scan again.")
            make_another_scan_attempt = True
            time.sleep(10)

    controller.c9.delay(3)
    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        try:
            _ = run_cp_and_save_data(
                measurement_number=14,
                init_ampere=0.002,
                tinit=10,
                ampere_step2=0.002,
                tstep2=60,
                sample_rate=0.5,
                group_name=group_name,
                ohmic_resistance=ohmic_resistance,
                ohmic_correction_factor=OHMIC_CORRECTION_FACTOR,
            )
            make_another_scan_attempt = False
        except Exception as e:
            logging.error(f"Error in CP measurement: {e}")
            logging.info("Trying to scan again.")
            make_another_scan_attempt = True
            time.sleep(10)

    controller.c9.delay(3)
    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        try:
            _ = run_cp_and_save_data(
                measurement_number=15,
                init_ampere=0.001,
                tinit=10,
                ampere_step2=0.001,
                tstep2=60,
                sample_rate=0.5,
                group_name=group_name,
                ohmic_resistance=ohmic_resistance,
                ohmic_correction_factor=OHMIC_CORRECTION_FACTOR,
            )
            make_another_scan_attempt = False
        except Exception as e:
            logging.error(f"Error in CP measurement: {e}")
            logging.info("Trying to scan again.")
            make_another_scan_attempt = True
            time.sleep(10)

    controller.c9.delay(3)
    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        try:
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
            make_another_scan_attempt = False
        except Exception as e:
            logging.error(f"Error in CV measurement: {e}")
            logging.info("Trying to scan again.")
            make_another_scan_attempt = True
            time.sleep(10)

    controller.c9.delay(3)
    if ultrasound:
        pass
        # controller.c9.set_output(ECELL_INDICES["ultrasound"], False)
    else:
        pass

    controller.c9.delay(3)

    make_another_scan_attempt = True
    while make_another_scan_attempt is True:
        try:
            run_cv_and_save_data(
                measurement_number=17,
                init_voltage=0.8,
                apex1=1.6,
                apex2=0,
                final_voltage=0,
                stepsize=0.002,
                scanrate=0.4,
                cycles=2,
                group_name=group_name,
            )
            make_another_scan_attempt = False
        except Exception as e:
            logging.error(f"Error in CV measurement: {e}")
            logging.info("Trying to scan again.")
            make_another_scan_attempt = True
            time.sleep(10)

    controller.c9.delay(3)

    # Plot overpotential vs sample number overview
    filename_jpg = f"{DATA_path}Potentials.jpg"

    overpotential_plot = gamry_plot(HDF5_file)
    overpotential_plot.plot_overpotential(
        title="Corrected potentials at 10 mA CP",
        xlabel="Unique ID",
        ylabel="Potential [V]",
        corrected_overpotential=True,
        sample_range=[5, 10000],
        figure_name=filename_jpg,
    )

    # Wrap it up and return data
    return overpotential_to_return, ohmic_resistance


def check_for_reference_electrode_drift(
    controller: C9Controller,
    lower_limit_pt_pot: float,
    upper_limit_pt_pot: float,
    group_name: str,
    uid: int,
    HDF5_file: str = HDF5_FILE,
):
    """Check for reference electrode drift by measuring the
    platinum peak potential and ohmic resistance

    Args:
        controller (C9Controller): Instance of C9Controller.
        lower_limit_pt_pot (float): Lower limit of the platinum peak potential
        upper_limit_pt_pot (float): Upper limit of the platinum peak potential
        group_name (str): Group name or sample name to save the data
        uid (int): Unique ID of the sample
        HDF5_file (str): Path to HDF5 file to store the data

    Returns:
        platinum_peak_potential_initial_ohmic_corr (float): Initial platinum peak potential
        platinum_peak_potential_accepted_ohmic_corr (float): Accepted platinum peak potential
        pt_ohmic_resistance (float): Ohmic resistance of the platinum electrode
        reference_electrode_rest_time (int): Time to rest the reference electrode
    """

    # Make a platinum EIS to find ohmic resistance
    pt_ohmic_resistance, df_pt_eis = get_platinum_eis()

    if pt_ohmic_resistance >= 7.0:
        logging.info(f"Ohmic resistance too large of pt wire being {pt_ohmic_resistance} ohm")

        # Drain cell
        controller.dispense_ml("Drain", 12)

        # Fill cell
        controller.dispense_ml("KOH", 9)

        # Redo the measurement
        pt_ohmic_resistance, df_pt_eis = get_platinum_eis()

        if pt_ohmic_resistance >= 7.0:
            logging.warning("Ohmic resistance too large of pt wire after refilling with KOH.")
            logging.warning(f"Ohmic resistance is {pt_ohmic_resistance} ohm")
            raise Exception("Terminating script. Why isn't ohmic resistance around 5 ohms?")

    # Save df_pt_eis to HDF5
    save_dataset_to_HDF5(df_pt_eis, group_name, "Pt_EIS_initial")

    # Get platinum CV to find platinum peak potential
    reference_electrode_rest_time = 0
    continue_reference_scan = True
    platinum_peak_potential_initial_ohmic_corr = 0
    counter = -1
    while continue_reference_scan is True:
        counter += 1
        logging.info(f"Testing for reference electrode drift try no. {counter}.")
        controller.c9.home_robot(
            wait=False
        )  # XXX This is a temporary fix to avoid the robot from malfunctioning

        try:
            # Get platinum CV to find platinum peak potential
            df_pt = get_platinum_potential(pt_ohmic_resistance)

            # Select part of the data
            df_pt_filtered = filter_data(
                df_pt,
                lower_potential=0.65,
                upper_potential=1.2,  # It is cut further in the smoothing function
                first_cycle=19,
                last_cycle=19,
            )
            logging.debug(f"df_pt: {df_pt_filtered.to_string}")

            # Smooth data
            df_pt_smoothed, pt_peak_potential_smooth = smooth_data_savitzky_golay(df_pt_filtered)
            logging.debug(f"pt_peak_potential_smooth: {pt_peak_potential_smooth}")
            logging.debug(f"df_pt_smoothed: {df_pt_smoothed.to_string}")
            df_pt_smoothed["Category"] = f"Smoothed: Peak at {round(pt_peak_potential_smooth, 3)}V"

            # Find the r_squared of the fit
            r_squared, pt_peak_potential_fit, df_pt_fitted = try_fit_function(df_pt)
            df_pt_fitted["Category"] = f"Fitted: Peak at {round(pt_peak_potential_fit, 3)}V"

            # Give a name to the measurements
            df_pt["Category"] = "Cycle 19"

            # Plot the smoothing
            df_merged = pd.concat(
                [df_pt[df_pt["Scan cycle"] == 19], df_pt_fitted, df_pt_smoothed], ignore_index=True
            )
            df_merged.reset_index()
            fig = px.scatter(
                df_merged,
                x="Corrected potential (WE vs. RHE) [V]",
                y="Current [A]",
                color="Category",
                title=f"Sample {uid} - Platinum CV peak finding",
            )
            fig.write_html(DATA_PATH + f"{uid}_Platinum_CV_fitting_{counter}.html")

        except Exception as e:
            logging.warning("Tried to make CV scan and find peak potential of Platinum.")
            logging.warning("Recieved error: ", e)
            logging.warning("Continuing loop. If this error keeps occuring please terminate script")
            time.sleep(10)
        logging.info(f"Platinum oxidation peak - Smoothing: {round(pt_peak_potential_smooth, 3)}V")
        logging.info(f"Platinum oxidation peak - Fitting: {round(pt_peak_potential_fit, 3)}V")
        logging.info(f"r_squared: {round(r_squared, 3)}")
        logging.info(
            f"Peak acceptance range: \
[{round(lower_limit_pt_pot, 3)}; {round(upper_limit_pt_pot, 3)}]V.",
        )

        # If peak doesn't drift closer to acceptance, change electrolyte
        if counter % 24 == 0 and counter != 0:
            logging.info(f"No peak found after {reference_electrode_rest_time} seconds.")
            logging.info("Changing electrolyte to make sure fill level is ok.")
            controller.dispense_ml("Drain", 12)
            controller.dispense_ml("H2O_ECELL", 16)
            controller.c9.delay(120)
            controller.dispense_ml("Drain", 16)
            controller.dispense_ml("HCl_ECELL", 16)
            controller.c9.delay(120)
            controller.dispense_ml("Drain", 16)
            controller.dispense_ml("H2O_ECELL", 16)
            controller.dispense_ml("Drain", 16)
            controller.dispense_ml("KOH", 3)
            controller.dispense_ml("Drain", 5)
            controller.dispense_ml("KOH", 9)
            message = f"Pt vs Pt scan not stabilising after {counter} scans. Flushing cell and replacing KOH."
            send_mail(message, "N9 robot replacing electrolyte", ["nis@dosan.dk"])

        # Track time and save first variables
        if reference_electrode_rest_time == 0:
            # Store platinum peak potential initial for later use
            platinum_peak_potential_initial_ohmic_corr = pt_peak_potential_smooth
            platinum_peak_potential_fitted_initial_ohmic_corr = pt_peak_potential_fit
            r_squared_initial = r_squared

        # Logic to check if the platinum peak potential is within the acceptance range
        reference_electrode_rest_time += 60  # time of the CV scan
        ##########################
        # FIRST verification
        ##########################
        if lower_limit_pt_pot <= pt_peak_potential_smooth <= upper_limit_pt_pot or (
            r_squared >= 0.97 and lower_limit_pt_pot <= pt_peak_potential_fit <= upper_limit_pt_pot
        ):
            # pt_peak_potential is within acceptance range
            # See if this is also true in two minutes
            logging.info(
                "Platinum oxidation peak potential is within range. Waiting 2 minutes to confirm."
            )
            reference_electrode_rest_time += 120  # Rest time
            controller.c9.delay(120)

            # Get platinum CV to find platinum peak potential
            df_pt = get_platinum_potential(pt_ohmic_resistance)

            # Select part of the data
            df_pt_filtered = filter_data(
                df_pt,
                lower_potential=0.65,
                upper_potential=1.2,  # It is cut further in the smoothing function
                first_cycle=19,
                last_cycle=19,
            )
            logging.debug(f"df_pt: {df_pt_filtered.to_string}")

            # Smooth data
            df_pt_smoothed, pt_peak_potential_smooth = smooth_data_savitzky_golay(df_pt_filtered)
            logging.debug(f"pt_peak_potential_smooth: {pt_peak_potential_smooth}")
            logging.debug(f"df_pt_smoothed: {df_pt_smoothed.to_string}")
            df_pt_smoothed["Category"] = f"Smoothed: Peak at {round(pt_peak_potential_smooth, 3)}V"

            # Find the r_squared of the fit
            r_squared, pt_peak_potential_fit, df_pt_fitted = try_fit_function(df_pt)
            df_pt_fitted["Category"] = f"Fitted: Peak at {round(pt_peak_potential_fit, 3)}V"

            # Give a name to the original measurements
            df_pt["Category"] = "Cycle 19"

            # Plot the smoothing
            df_merged = pd.concat(
                [df_pt[df_pt["Scan cycle"] == 19], df_pt_fitted, df_pt_smoothed], ignore_index=True
            )
            df_merged.reset_index()

            fig = px.scatter(
                df_merged,
                x="Corrected potential (WE vs. RHE) [V]",
                y="Current [A]",
                color="Category",
                title=f"Sample {uid} - Platinum CV with peak finding",
            )
            fig.write_html(DATA_PATH + f"{uid}_Platinum_CV_fitting_{counter}_2nd_confirmation.html")

            logging.info(f"Platinum oxidation peak potential: {round(pt_peak_potential_smooth, 3)}V")
            logging.info(
                f"Peak acceptance range: \
[{round(lower_limit_pt_pot, 3)}; {round(upper_limit_pt_pot, 3)}]V.",
            )

            reference_electrode_rest_time += 60  # Time of CV run

            ##########################
            # SECOND verification
            ##########################
            logging.info(f"r_squared: {r_squared}")
            logging.info(f"pt_peak_potential_fit: {pt_peak_potential_fit}")
            logging.info(f"pt_peak_potential_smooth: {pt_peak_potential_smooth}")
            if lower_limit_pt_pot <= pt_peak_potential_smooth <= upper_limit_pt_pot or (
                r_squared >= 0.97
                and lower_limit_pt_pot <= pt_peak_potential_fit <= upper_limit_pt_pot
            ):
                # Peak is within acceptance range
                logging.info("Platinum oxidation peak potential is within acceptance range.")

                # Proceed with experiment and break loop
                logging.info("Continuing with experiment.")
                continue_reference_scan = False

            else:
                # pt_peak_potential is not within acceptance range
                # Continue the loop
                logging.info("Platinum oxidation peak outside acceptable range.")
                logging.info("Waiting 5 minutes before next test.")
                controller.c9.delay(300)
                reference_electrode_rest_time += 300  # Rest time

        else:
            logging.info("Platinum oxidation peak is outside acceptable range.")
            logging.info("Continuing to test for reference electrode drift.")
            logging.info("Waiting 5 minutes before next test.")
            controller.c9.delay(300)
            reference_electrode_rest_time += 300  # Rest time

    r_squared_accepted = r_squared
    platinum_peak_potential_accepted_ohmic_corr = pt_peak_potential_smooth
    platinum_peak_potential_accepted_fitted_ohmic_corr = pt_peak_potential_fit
    logging.info(f"Reference electrode rest time: {reference_electrode_rest_time} seconds")
    logging.info(
        f"Platinum oxidation peak drifted from: \
{round(platinum_peak_potential_initial_ohmic_corr, 3)}V"
    )
    logging.info(f"to {round(platinum_peak_potential_accepted_ohmic_corr, 3)}V")

    with h5py.File(HDF5_file, "a") as f:
        # Save platinum initial and accepted peak as well as reference electrode rest
        # time and pt_ohmic_resistance as attributes in HDF5
        f[group_name].attrs[
            "platinum_peak_potential_smoothed_initial"
        ] = platinum_peak_potential_initial_ohmic_corr
        f[group_name].attrs["platinum_fitted_r_squared_initial"] = r_squared_initial
        f[group_name].attrs[
            "platinum_peak_potential_fitted_initial"
        ] = platinum_peak_potential_fitted_initial_ohmic_corr
        f[group_name].attrs[
            "platinum_peak_potential_smoothed_accepted"
        ] = platinum_peak_potential_accepted_ohmic_corr
        f[group_name].attrs["platinum_fitted_r_squared_accepted"] = r_squared_accepted
        f[group_name].attrs[
            "platinum_peak_potential_fitted_accepted"
        ] = platinum_peak_potential_accepted_fitted_ohmic_corr
        f[group_name].attrs["reference_electrode_rest_time"] = reference_electrode_rest_time
        f[group_name].attrs["pt_ohmic_resistance"] = pt_ohmic_resistance

    # Specify the columns to drop from the dataframe to be able save it to HDF5
    columns_to_drop = [
        "Category",
    ]

    # Drop the specified columns from the dataframe, ignoring any errors if columns are not present
    df_pt = df_pt.drop(columns=columns_to_drop, errors="ignore")

    # Save df_pt to HDF5
    save_dataset_to_HDF5(df_pt, group_name, "Pt_CV_accepted")

    return (
        platinum_peak_potential_initial_ohmic_corr,
        platinum_peak_potential_accepted_ohmic_corr,
        pt_ohmic_resistance,
        reference_electrode_rest_time,
    )


def get_reference_electrode_potential(
    group_name: str,
    ohmic_resistance: float,
    HDF5_file: str = HDF5_FILE,
) -> float:
    """Measure the potential of the platinum oxidation peak
    used to calibrate the reference electrode

    Args:
        HDF5_file (str): File name of the .hdf5 file.
        group_name (str): Group name or sample name to save the data in the .hdf5 file

    Returns:
        ref_peak_potential_ohmic_corrected (float): Peak potential of the platinum peak
    """
    # Get platinum CV to find platinum peak potential
    df_pt = get_platinum_potential(ohmic_resistance)

    # Select part of the data
    df_pt_filtered = filter_data(
        df_pt,
        lower_potential=0.65,
        upper_potential=1.2,  # It is cut further in the smoothing function
        first_cycle=19,
        last_cycle=19,
    )
    logging.debug(f"df_pt: {df_pt_filtered.to_string}")

    # Smooth data
    df_pt_smoothed, pt_peak_potential_smooth = smooth_data_savitzky_golay(df_pt_filtered)
    logging.debug(f"pt_peak_potential_smooth: {pt_peak_potential_smooth}")
    logging.debug(f"df_pt_smoothed: {df_pt_smoothed.to_string}")
    df_pt_smoothed["Category"] = f"Smoothed: Peak at {round(pt_peak_potential_smooth, 3)}V"

    # Find the r_squared of the fit
    r_squared, pt_peak_potential_fit, df_pt_fitted = try_fit_function(df_pt)
    df_pt_fitted["Category"] = f"Fitted: Peak at {round(pt_peak_potential_fit, 3)}V"

    # Give a name to the original measurements
    df_pt["Category"] = "Cycle 19"

    # Plot the smoothing
    df_merged = pd.concat(
        [df_pt[df_pt["Scan cycle"] == 19], df_pt_fitted, df_pt_smoothed], ignore_index=True
    )
    df_merged.reset_index()

    logging.info(
        "Platinum smoothed peak potential after measurements: "
        f"{round(pt_peak_potential_smooth, 3)} V",
    )
    r_squared, pt_peak_potential_fit, df_pt_fitted = try_fit_function(df_pt)

    fig = px.scatter(
        df_merged,
        x="Corrected potential (WE vs. RHE) [V]",
        y="Current [A]",
        color="Category",
        title=f"{group_name} - Platinum CV peak after tests",
    )
    fig.write_html(DATA_PATH + f"{group_name}_Platinum_CV_fitting_after_tests.html")

    # Save pt_peak_potential to HDF5 file as an attribute
    with h5py.File(HDF5_file, "a") as f:
        f[group_name].attrs[
            "platinum_peak_potential_smoothed_after_tests"
        ] = pt_peak_potential_smooth
        f[group_name].attrs["platinum_peak_potential_fitted_after_tests"] = pt_peak_potential_fit
        f[group_name].attrs["platinum_r_squared_after_tests"] = r_squared

    return pt_peak_potential_smooth
