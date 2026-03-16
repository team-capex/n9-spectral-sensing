"""Module for measurements such as CP, CV and EIS. Data are saved in h5PY and jpg images"""

import logging
import numpy as np
import pandas as pd
from gamry import recipe
from tools import (
    save_dataset_to_HDF5,
    save_overview_data,
    timer,
    find_ohmic_resistance,
)
from gamry_plot import gamry_plot
from params import DATA_PATH, HDF5_FILE
from wrapt_timeout_decorator import timeout

__all__ = (
    "run_cv_and_save_data",
    "run_EIS_and_save_data",
    "run_cp_and_save_data",
    "get_EIS",
    "get_platinum_cv",
)

def timeout_handler(signum, frame):
    raise TimeoutError("Timeout occurred")


@timeout(60 * 30)
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


@timeout(300)
def get_platinum_cv(
    init_voltage: float = 0.45,
    apex1: float = 1.4,
    apex2: float = 0,
    final_voltage: float = 0.45,
    stepsize: float = 0.001,
    scanrate: float = 1.0,
    cycles: int = 20,
) -> pd.DataFrame:
    """Run CV and return data

    Args:
        measurement_number (int): Index of the current measurement.
        init_voltage (float): Initial voltage in V.
        apex1 (float): Max voltage to reach in V.
        apex2 (float): Min voltage to reach in V.
        final_voltage (float): Final voltage in V.
        stepsize (float): Stepszie for the increament of voltage.
        scanrate (float): Scanrate in V/s.
        cycles (float): Number of cycles of CV.

    Returns:
        pd.DataFrame: Data from the CV measurement
    """

    logging.info(f"# Platinum CV scan at {scanrate}V/s x {cycles} cycles #")

    cv = recipe.CV(
        init_voltage=init_voltage,
        final_voltage=final_voltage,
        apex1=apex1,
        apex2=apex2,
        scanrate1=scanrate,
        stepsize=stepsize,
        cycles=cycles,
        VchRange=2,  # volt
        current_cap=0.020,  # ampere
    )
    with timer():
        cv.run()
    data = cv.get_data()

    return data


@timeout(300)
def run_EIS_and_save_data(
    measurement_number: int,
    init_freq: float,
    final_freq: float,
    pts_per_decade: int,
    dc: float,
    ac: float,
    # sdc: float,  # Galvanostatic EIS
    # zguess: float,  # Galvanostatic EIS
    group_name: str,
    data_set_name: str = "",
    DATA_path: str = DATA_PATH,
) -> float:
    """Run EIS, get ohmic resistance and save the raw data and plot. TODO plot should be moved

    Args:
        measurement_number (int): Index of the current measurement.
        init_freq (float): Initial frequency in Hertz.
        final_freq (float): Final frequency in Hertz.
        pts_per_dec (int): TODO Ask Enzo
        dc (float): DC voltage in V
        ac (float): AC voltage in V
        # sdc (float): DC voltage, only for galvanostat mode. Defaults to 0.0.
        # zguess (float): Initial guess for impedance, only for galvanostat mode.
        #     Defaults to 100.0.
        group_name (str): Group name or sample name to save the data.
        data_set_name (str, optional): Name of the data set. Defaults to "EIS".
        DATA_path (str, optional): Path to store the .jpg at. Defaults to DATA_PATH.

    """
    logging.info(f"# {measurement_number} EIS ACV #")
    if data_set_name == "":
        data_set_name = f"{measurement_number}EISacv"
    logging.info(f"Starting EIS on sample {group_name}  -Please wait")

    # Potentiostatic EIS:
    eis = recipe.EIS(
        init_freq=init_freq,
        final_freq=final_freq,
        pts_per_dec=pts_per_decade,
        dc=dc,
        ac=ac,
    )

    # Galvanostatic EIS can alternatively be used:
    # eis = recipe.EISG(
    #     init_freq=init_freq,
    #     final_freq=final_freq,
    #     pts_per_dec=pts_per_decade,
    #     dc=dc,
    #     ac=ac,
    #     sdc=sdc,
    #     zguess=zguess,  # Initial guess for impedance, Only for galvanostat
    # )

    with timer():
        eis.run()
    data = eis.get_data()

    # Change column names to be more descriptive
    column_names = [
        "Point",
        "Time [s]",
        "Freq",
        "Zreal [ohm]",
        "Zimag [ohm]",
        "Zsig",
        "Zmod",
        "Zphz",
        "Idc",
        "Vdc",
        "IERange",
    ]
    data.columns = column_names

    logging.info(f"Saving CSV: {data_set_name}")
    data.to_csv(f"{DATA_path}{group_name}_{data_set_name}.csv", sep="\t", decimal=",")

    ohmic_resistance = find_ohmic_resistance(data)
    save_dataset_to_HDF5(data, group_name, data_set_name)

    # Make a EIS plot
    logging.info(f"Saving plot of dataset:{data_set_name}")
    filename_jpg = f"{DATA_path}{group_name}_{data_set_name}.jpg"
    eis_plot = gamry_plot(HDF5_FILE)
    eis_plot.search(
        [group_name],
        [data_set_name],
    )
    eis_plot.plot_EIS(
        title=data_set_name,
        xlabel="Zreal [ohm]",
        ylabel="Zimag [ohm]",
        figure_name=filename_jpg,
    )

    return ohmic_resistance


@timeout(300)
def get_EIS(
    init_freq: float,
    final_freq: float,
    pts_per_decade: int,
    dc: float,
    ac: float,
) -> pd.DataFrame:
    """Run EIS and return the data

    Args:
        init_freq (float): Initial frequency in Hertz.
        final_freq (float): Final frequency in Hertz.
        pts_per_dec (int): TODO Ask Enzo
        dc (float): DC voltage in V
        ac (float): AC voltage in V
    """
    logging.info("# Running EIS #")

    # Potentiostatic EIS:
    eis = recipe.EIS(
        init_freq=init_freq,
        final_freq=final_freq,
        pts_per_dec=pts_per_decade,
        dc=dc,
        ac=ac,
    )

    with timer():
        eis.run()
    data = eis.get_data()
    column_names = [
        "Point",
        "Time [s]",
        "Freq",
        "Zreal [ohm]",
        "Zimag [ohm]",
        "Zsig",
        "Zmod",
        "Zphz",
        "Idc",
        "Vdc",
        "IERange",
    ]
    data.columns = column_names
    return data


@timeout(300)
def run_cp_and_save_data(
    measurement_number: int,
    ampere_step2: float,
    tstep2: int,
    sample_rate: float,
    group_name: str,
    ohmic_resistance: float = 0,
    ohmic_correction_factor: float = 0,
    init_ampere: float = 0.0,
    tinit: int = 0,
    ampere_step1: float = 0.0,
    tstep1: int = 0,
    save_overview_table: bool = False,
    unique_id: int = 0,
    DATA_path: str = DATA_PATH,
    HDF5_file: str = HDF5_FILE,
) -> float:
    """Run CP and save the rawdata and plot TODO: Plot should move to postprocess

    Args:
        measurement_number (int): Measurement step of the experiment to save data and logging
        ampere_step2 (float): Current at step 2 in Ampere
        tstep2 (int): Time duration for 2nd step in seconds.
        sample_rate (float): Interval of recording data
        ohmic_resistance (float): Ohmic resistance to correct overpotential.
        ohmic_correction_factor (float): Ohmic correction factor for overpotential
        group_name (str): Group name or sample name to save the data
        init_ampere (float, optional): Current at step 1 in Ampere. Defaults to 0.0.
        tinit (int, optional): Time duration for initial step in seconds. Defaults to 0.
        ampere_step1 (float, optional): Current at step 1 in Ampere. Defaults to 0.0.
        tstep1 (int, optional): Time duration for 1st step in seconds. Defaults to 0.
        save_overview_table (bool, optional): Whether to save overview data for ML optimization.
        Defaults to False.
        unique_id  (int): Unique ID for the sample to save overview data. Defaults to None
        DATA_path (str, optional): Path to store the .jpg at. Defaults to DATA_PATH.
        HDF5_file (str, optional): Path of HDF5 file for saving the data. Defaults to HDF5_FILE.

    Returns:
        float: Overpotential
    """
    ampere_step2_mA = ampere_step2 * 1000
    logging.info(f"# {measurement_number} CP {ampere_step2_mA} mA #")
    data_set = f"{measurement_number}CP{ampere_step2_mA}mA"

    logging.info("Starting CP")
    cp = recipe.CP(
        init_voltage=init_ampere,
        tinit=tinit,
        vstep1=ampere_step1,
        tstep1=tstep1,
        vstep2=ampere_step2,
        tstep2=tstep2,
        sample=sample_rate,
    )
    with timer():
        cp.run()
    data = cp.get_data()
    data.to_csv(f"{DATA_path}{group_name}_{data_set}.csv", sep="\t", decimal=",")
    data = data.to_numpy()

    logging.info(f"Saving dataset:{data_set}")
    save_dataset_to_HDF5(data, group_name, data_set)

    # Finding the overpotential
    # "keyParameters"
    index_to_subtract = round(0.2 * (tstep2 / sample_rate))
    logging.debug("Index to subtract:", index_to_subtract)
    raw_potential = float(np.round(np.average(data[-index_to_subtract:-1, 1]), 3))
    logging.info(f"Raw potential: {raw_potential}V")
    if ohmic_resistance is None:
        logging.info("No potential correction added")

        overpotential_to_return = raw_potential
    else:
        potential_corr = raw_potential - (ampere_step2 * ohmic_resistance * ohmic_correction_factor)
        corrected_potential = np.round_(potential_corr, 3)
        logging.info(f"Corrected potential: {corrected_potential}V")
        overpotential_to_return = corrected_potential

        if save_overview_table:
            logging.info("Saving potential and ohmic resistance to database")
            save_overview_data(
                unique_id,
                ampere_step2,
                raw_potential,
                potential_corr,
                ohmic_resistance,
            )
            logging.info("Done saving")

    # Make a CP plot of specified CP's in the HDF5 file
    logging.info(f"Saving plot of dataset:{data_set}")
    filename_jpg = f"{DATA_path}{group_name}_{data_set}.jpg"
    cp_plot = gamry_plot(HDF5_file)
    cp_plot.search(
        [group_name],
        [data_set],
    )
    seconds_to_plot = 20
    cycle_to_plot = int(abs(seconds_to_plot) / sample_rate)
    cp_plot.plot_CP(
        select_subset_of_data=[-cycle_to_plot, -1],
        select_data=False,
        title=data_set + " no ohmic correction",
        xlabel="Time [s]",
        ylabel="Voltage [V]",
        ohmic_corrected=False,
        figure_name=filename_jpg,
    )

    return overpotential_to_return
