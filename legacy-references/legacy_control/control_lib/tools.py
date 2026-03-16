import time
from typing import Tuple
import logging
from contextlib import contextmanager
import numpy as np
import pandas as pd
import h5py
import pickle
from params import OHMIC_CORRECTION_FACTOR, HDF5_FILE
import statsmodels.api as sm
from lmfit.models import GaussianModel
from lmfit.models import StepModel
from scipy.signal import savgol_filter

# from lmfit.models import ExponentialModel

__all__ = (
    "timer",
    "fit_function",
    "smooth_data_lowess",
    "smooth_data_savitzky_golay",
    "filter_data",
    "save_dataset_to_HDF5",
    "correct_for_ohmic_resistance",
    "find_ohmic_resistance",
    "save_overview_data",
    "normalize_ratios",
    "ConcentrationConverter",
    "make_dragonfly_save_file",
    "set_column_headers_cv",
    "try_fit_function",
)

@contextmanager
def timer():
    """log execution time of a measurement"""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        logging.info(f"Execution time: {duration:.2f} s.")


def fit_function(df: pd.DataFrame):
    """Fit function

    Args:
        data (pd.DataFrame): Dataframe containing the data to fit. Must contain a
        column named "Corrected potential (WE vs. RHE) [V]" and a column named "Current [A]".

    Returns:
        pd.DataFrame: Dataframe with fitted data
        potential_pt_peak (float): Potential at which the oxidation peak on Pt occurs
        r_squared (float): R-squared error
    """
    # Convert data to numpy arrays
    x = np.array(df["Corrected potential (WE vs. RHE) [V]"])
    x_uncorrected = np.array(df["Potential (WE vs. RHE) [V]"])
    y = np.array(df["Current [A]"])

    # Fit data to step model
    logging.debug("Fitting: Step model")
    step_mod = StepModel(form="logistic", prefix="log_")
    pars = step_mod.guess(y, x=x)

    # Fit data to gaussian model
    logging.debug("Fitting: Gaussian model")
    gauss_mod = GaussianModel(prefix="g1_")
    pars.update(gauss_mod.guess(y, x=x))

    # Combining models
    mod = gauss_mod + step_mod  # + exp_mod
    mod.eval(pars, x=x)
    y_log_gaus = mod.fit(y, pars, x=x)
    # print(y_exp_gaus.fit_report(correl_mode="table"))  # Correleation of parameters

    # Locating peak of fitted data
    potential_pt_peak = y_log_gaus.params["g1_center"].value

    # Get R-squared error
    r_squared = y_log_gaus.rsquared

    # Combining x and y values and add labels
    fitted_data = pd.DataFrame(
        {
            "Corrected potential (WE vs. RHE) [V]": x,
            "Potential (WE vs. RHE) [V]": x_uncorrected,
            "Current [A]": y_log_gaus.best_fit,
        }
    )

    return fitted_data, potential_pt_peak, r_squared


def smooth_data_lowess(df: pd.DataFrame, frac: float = 0.1):
    """Smooth data using Lowess smoothing

    Args:
        df (pd.DataFrame): Dataframe containing the data to smooth. Must contain a
        column named "Current [A]" and a column named "Corrected potential (WE vs. RHE) [V]".
        frac (float, optional): Fraction of the data used for smoothing. Defaults to 0.1.

    Returns:
        pd.DataFrame: Dataframe with smoothed data
        peak_value (float): Peak value of the smoothed data
    """
    logging.info("Smoothing CV data")
    # Smooth data using Lowess smoothing
    lowess = sm.nonparametric.lowess
    smoothed_current = lowess(
        df["Current [A]"], df["Corrected potential (WE vs. RHE) [V]"], frac=frac
    )
    df["Current [A]"] = smoothed_current[:, 1]

    # Find the peak value of the smoothed data
    logging.info("Finding platinum oxidation peak in selected potential window")
    peak_current = df["Current [A]"].max()

    # Find the potential at which the peak value occurs
    logging.debug("Finding corresponding potential at which the peak in current occurs")
    peak_value = df[df["Current [A]"] == peak_current][
        "Corrected potential (WE vs. RHE) [V]"
    ].values[0]

    df["Category"] = f"Fit: smoothed_data pt_peak = {round(peak_value, 3)} V"

    return df, peak_value


def smooth_data_savitzky_golay(df: pd.DataFrame, window: float = 75) -> Tuple[pd.DataFrame, float]:
    # Your function code here
    """Smooth data using Lowess smoothing

    Args:
        df (pd.DataFrame): Dataframe containing the data to smooth. Must contain a
        column named "Current [A]" and a column named "Corrected potential (WE vs. RHE) [V]".
        window (float, optional): Window size for smoothing. Defaults to 75.

    Returns:
        pd.DataFrame: Dataframe with smoothed data
        peak_value (float): Peak value of the smoothed data
    """
    logging.info("Smoothing CV data")
    # Smooth data using Savitzky-Golay filter
    if len(df) < window:
        pass
    else:
        smoothed_current = savgol_filter(df["Current [A]"], window, 3)
        df["Current [A]"] = smoothed_current
    # Select part of the data
    df = filter_data(
        df,
        lower_potential=0.65,
        upper_potential=0.85,
        first_cycle=19,
        last_cycle=19,
        apply_row_removal_for_prettyness=False,
    )

    # Find the maximum value of the smoothed data (pandas data series)
    logging.info("Finding platinum oxidation peak in selected potential window")
    peak_current = df["Current [A]"].max()

    # Find the potential at which the peak value occurs
    logging.debug("Finding corresponding potential at which the peak in current occurs")
    peak_value = df[df["Current [A]"] == peak_current][
        "Corrected potential (WE vs. RHE) [V]"
    ].values[0]

    df["Category"] = f"Fit: smoothed_data pt_peak = {round(peak_value, 3)} V"

    return df, peak_value


def filter_data(
    df: pd.DataFrame,
    lower_potential: float = 0.65,
    upper_potential: float = 0.85,
    first_cycle: int = 10,
    last_cycle: int = 19,
    apply_row_removal_for_prettyness=True,
) -> pd.DataFrame:
    """Filters a dataframe containing a cyclic voltammetry scan of a Pt catalyst with many cycles.


    Args:
        data (pd.DataFrame): Dataframe containing the data to filter. Must contain a
        the columns "Scan cycle" and "Corrected potential (WE vs. RHE) [V]".
        lower_potential (float, optional): Lower potential to select data from. Defaults to 0.7.
        upper_potential (float, optional): Upper potential to select data to. Defaults to 0.93.
        first_cycle (int, optional): First scan cycle to select data from. Defaults to 10.
        last_cycle (int, optional): Last scan cycle to select data to. Defaults to 19.

    Returns:
        pd.DataFrame: Dataframe with filtered data
    """
    logging.debug("Selecting part of the platinum CV scan to find peak")
    # Select data that for "Scan cycle" column in range (first_cycle, last_cycle)
    filtered_data = df[(df["Scan cycle"] >= first_cycle) & (df["Scan cycle"] <= last_cycle)]

    # Select data only within specified "Corrected potential (WE vs. RHE) [V]"
    filtered_data = filtered_data[
        (filtered_data["Corrected potential (WE vs. RHE) [V]"] >= lower_potential)
        & (filtered_data["Corrected potential (WE vs. RHE) [V]"] <= upper_potential)
    ]

    # Create a mask to check if the "Corrected potential" values are increasing
    mask = filtered_data["Corrected potential (WE vs. RHE) [V]"] > filtered_data[
        "Corrected potential (WE vs. RHE) [V]"
    ].shift(1)

    # Apply the mask to select the rows where the "Corrected potential" increases
    filtered_data = filtered_data[mask]

    if apply_row_removal_for_prettyness is True:
        # For each "Scan cycle", remove the last row of filtered_data to
        # avoid negative "Current" values
        filtered_data = filtered_data.groupby("Scan cycle").apply(lambda x: x.iloc[:-1])

    return filtered_data


def save_dataset_to_HDF5(
    data_set, group_name: str, data_set_name: str, HDF5_file: str = HDF5_FILE
) -> None:
    """Saves pandas dataframe to HDF5 file.

    Args:
        data_set (list): Pandas, list or Numpy array
        group_name (str): Group/Sample name in database
        data_set_name (str): Name of the data set
        HDF5_file (str): Path to the HDF5 file
    """
    logging.info(f"Saving dataset to HDF5: {data_set_name}")
    with h5py.File(HDF5_file, "a") as file:
        group = file[group_name]
        if data_set_name in str(group):
            logging.warning("Dataset already exists")
        else:
            logging.info(f"Creating dataset: {data_set_name}")
            group.create_dataset(data_set_name, data=data_set)
    logging.info("Dataset saved to HDF5")


def correct_for_ohmic_resistance(
    df: pd.DataFrame,
    ohmic_resistance: float,
    ohmic_correction_factor: float = OHMIC_CORRECTION_FACTOR,
) -> pd.DataFrame:
    """Correct potential for ohmic resistance

    Args:
        df (pd.DataFrame): Dataframe containing the data to correct. Must contain a
        column named "Current [A]" and a column named "Potential (WE vs. RHE) [V]".
        ohmic_resistance (float): Ohmic resistance in ohm

    Returns:
        pd.DataFrame: Dataframe with corrected potential
    """
    logging.info("Correcting platinum scan for ohmic resistance")
    df["Corrected potential (WE vs. RHE) [V]"] = (
        df["Potential (WE vs. RHE) [V]"]
        - ohmic_correction_factor * ohmic_resistance * df["Current [A]"]
    )
    return df


def find_ohmic_resistance(data: pd.DataFrame) -> float:
    """Find the ohmic resistance from the EIS data

    Args:
        data (pd.DataFrame): EIS data

    Returns:
        float: Ohmic resistance
    """
    # Select the first 10 rows of data dataframe to avoid a negative
    # tail of the ohmic resistance at higher frequencies
    data = data.iloc[:10]

    # Finding ohmic resistance
    logging.info("Finding ohmic resistance")
    row_index = data["Zimag [ohm]"].abs().idxmin(skipna=True)
    if row_index is None:
        raise ValueError("EIS data does not contain valid impedance values.")
    ohmic_resistance = round(float(data.loc[row_index, "Zreal [ohm]"]), 3)
    logging.info(f"Ohmic resistance: {ohmic_resistance}")
    return ohmic_resistance


def save_overview_data(
    uid: int,
    current: float,
    potential_at_10mA: float,
    potential_at_10mA_corr: float,
    resistivity: float,
    HDF5_file: str = HDF5_FILE,
) -> None:
    """Saves the overview table used for machine learning and
    optimization to a specific dataset 'keyParameters' in the root of the HDF5 file.
    'keyParameters' has the columns:
    [uniqeID, Current (A), Overpotential (V), Overpotential Corrected (V), Ohmic resistance (Ohm)]


    Args:
        uniqueID (int): ID of the sample
        current (float): Ampere current
        potential_at_10mA (float): Potential at 10 mA
        potential_at_10mA_corr (float): Potential at 10 mA corrected for ohmic resistance
        resistivity (float): Ohmic resistance in the setup
        HDF5_file (str): Path to the HDF5 file
    """
    data_set_name = "keyParameters"
    with h5py.File(HDF5_file, "r") as file:
        if data_set_name in file:
            logging.debug("Existing keyParameters table found in hdf5 file.")
            data = np.array(file[data_set_name][:])
        else:
            logging.warning(
                f"{data_set_name} is not found in hdf5 file. Empty dataset \
                        created with 0's."
            )
            data = np.array([0, 0, 0, 0, 0])

        logging.debug(f"Existing keyParameters table contains {data}")

    data_set = np.vstack(
        (
            data,
            np.array([uid, current, potential_at_10mA, potential_at_10mA_corr, resistivity]),
        )
    )

    with h5py.File(HDF5_file, "a") as file:
        try:
            del file[data_set_name]
        except Exception:
            logging.warning(f"{data_set_name} couldn't be deleted in hdf5 file.")
        file.create_dataset(data_set_name, data=data_set)


def normalize_ratios(ratios: dict):
    """Normalize the ratios to the sum of ratios

    Args:
        ratios (dict): Dictionary of ratios

    Returns:
        dict: Dictionary of normalized ratios
    """
    sum_ratio = sum(ratios.values())
    for key in ratios.keys():
        ratios[key] = ratios[key] / sum_ratio
    return ratios


class ConcentrationConverter:
    """Class for converting concentrations to volumes"""

    def __init__(
        self,
        start_conc: dict,
        ratios: dict,
        overall_target_conc: float,
        dilution: str,
        vol: float,
    ):
        """Converts concentrations to volumes

        Args:
            start_conc (dict): Dictionary of starting concentrations of each
            component stated as molarity (mol/L)
            ratios (dict): Dictionary of chemicals in ratios of the final
            solution e.g. {"A": 0.5, "B": 0.5}
            overall_target_conc (float): Target concentrations of solution
            stated as molarity (mol/L)
            dilution (str): Name/key of component to dilute with
            vol (float): Volume to normalize to (mL)
        """
        self.start_conc = start_conc
        self.ratios = self._normalize_ratios(ratios)
        self.vol = vol
        self.dilution = dilution
        self.overall_target_conc = overall_target_conc
        self._check_values()

    def _check_values(self):
        """Check that the values in the start_conc and target_conc
        dictionaries are positive and that start is larger than
        or equal to target

        Raises:
            ValueError: If any of the values are negative
            ValueError: If any of the starting concentrations are smaller
            than the target concentrations
        """

        if self.overall_target_conc < 0:
            logging.warning(f"""overall_target_conc value: {self.start_conc}""")
            raise ValueError("Target concentrations must be positive")
        for key, value in self.start_conc.items():
            if value < 0:
                logging.warning(f"""{key} value: {value}""")
                raise ValueError("Starting concentrations must be positive")
            if self.start_conc[key] < self.overall_target_conc:
                logging.warning(
                    f"""{key} start concentration: {value}
                < {self.overall_target_conc}"""
                )
                raise ValueError(
                    """Starting concentrations must be larger than or
                    equal to target concentration"""
                )

    def _calculate_ratios(self):
        """Calculate the mixing ratios of the ingredients

        Returns:
            dict: Dictionary of ratios
        """
        mixing_ratios = {}
        for key in self.start_conc.keys():
            mixing_ratios[key] = self.ratios[key] * (self.overall_target_conc / self.start_conc[key])
        return mixing_ratios

    def _normalize_ratios(self, ratios: dict):
        """Normalize the ratios to the sum of ratios

        Args:
            ratios (dict): Dictionary of ratios

        Returns:
            dict: Dictionary of normalized ratios
        """
        sum_ratio = sum(ratios.values())
        for key in ratios.keys():
            ratios[key] = ratios[key] / sum_ratio
        return ratios

    def calculate_volumes(self):
        """Calculate the volumes of each component

        Returns:
            dict: Dictionary of volumes
        """
        volumes = {}
        ratios = self._calculate_ratios()
        dilution_ratio = 1 - sum(ratios.values())
        for key in ratios.keys():
            volumes[key] = self.vol * ratios[key]
        # Add dilution volume
        updict = {self.dilution: self.vol * dilution_ratio}
        # Merge dictionaries and make sure dilutant is first
        volumes = {**updict, **volumes}
        return volumes


def make_dragonfly_save_file(input_data, filename, constraints):
    """
    Makes a pickl (.pkl) file in the right save file format for use in Dragonfly

    input_data: array
        array with results obtained previously
        [[x0, y0, z0, score0],
         [x1, y1, z1, score1]]
    filename: string
        The name you want for the save file
    constraints: array
        array with constraints for x ,y z,
        [[x_min, x_max],[y_min, y_max],[z_min, z_max]]
    """

    output = {}

    input_data0 = np.array(input_data.copy())

    for dims in range(len(constraints)):
        scale = constraints[dims][1] - constraints[dims][0]
        input_data0[:, dims] = input_data0[:, dims] / scale

    # print(input_data0)
    points_list = []
    for data in input_data0:
        # print(data[:-1])
        points_list.append(np.array(data[:-1]))

    output["points"] = points_list
    true_vals = -input_data0[:, -1]
    output["true_vals"] = true_vals
    output["vals"] = true_vals

    with open(filename, "wb") as handle:
        pickle.dump(output, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return


def set_column_headers_cv(df: pd.DataFrame) -> pd.DataFrame:
    """Set column headers for CV data

    Args:
        data (pd.DataFrame): Dataframe containing CV data in the order
        [Index, Time (s), Potential (WE vs. RHE) [V], Vu (V), Current [A],
        Vsig, Ach (V), IERange, Overbit1, Stop Test, Scan cycle, Temperature (C)]

    Returns:
        pd.DataFrame: Dataframe with new column headers
    """

    # Define the desired column names
    column_names = [
        "Time (s)",
        "Potential (WE vs. RHE) [V]",
        "Vu (V)",
        "Current [A]",
        "Vsig",
        "Ach (V)",
        "IERange",
        "Overbit1",
        "Stop Test",
        "Scan cycle",
        "Temperature (C)",
    ]

    # Check if the number of columns is 12 and insert "Index" at the beginning of the column names
    if len(df.columns) == 12:
        column_names.insert(0, "Index")

    # Assign the new column names to the dataframe
    df.columns = column_names

    # Specify the columns to drop from the dataframe
    columns_to_drop = [
        "Time (s)",
        "Vu (V)",
        "Vsig",
        "Ach (V)",
        "IERange",
        "Overbit1",
        "Stop Test",
        "Temperature (C)",
    ]

    # Drop the specified columns from the dataframe, ignoring any errors if columns are not present
    df = df.drop(columns=columns_to_drop, errors="ignore")

    # If "Index" column exists in the dataframe, drop it as well
    if "Index" in df.columns:
        df = df.drop(columns=["Index"])

    return df


def try_fit_function(df_pt: pd.DataFrame):
    """Try to fit a function to the data

    Args:
        df_pt (pd.DataFrame): Dataframe with the data to fit

    Returns:
        r_squared (float): R-squared value of the fit
        potential_pt_peak (float): Potential of the platinum peak
        df (pd.DataFrame): Dataframe with the fit and original data
    """

    # Get the R-sqared value of a peak fit (Fit not used, this is a
    # compromise between what Nis and Enzo wanted, and Enzo
    # insisted on using the R-squared value as a metric)
    try:
        # Select part of the data
        df_pt_filtered = filter_data(
            df_pt,
            lower_potential=0.65,
            upper_potential=0.90,
            first_cycle=19,
            last_cycle=19,
        )
        df, potential_pt_peak, r_squared = fit_function(df_pt_filtered)
        logging.debug(f"DEBUG: R-squared value of the fit: {r_squared}")
        logging.debug(f"DEBUG: Potential of the platinum peak fit: {potential_pt_peak}")
        logging.debug(f"DEBUG: Dataframe with the fit: {df}")

    except Exception as e:
        logging.debug("Exception in try_fit_function")
        logging.debug(f"Dataframe df_pt: {df_pt}")
        logging.debug(f"Dataframe df_pt_filtered: {df_pt_filtered}")
        logging.info(e)
        r_squared = 0
        potential_pt_peak = 0
        df = pd.DataFrame()

    return r_squared, potential_pt_peak, df
