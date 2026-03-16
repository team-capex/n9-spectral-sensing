import h5py
import pandas as pd
import plotly.express as px
import re
from lmfit.models import GaussianModel
from lmfit.models import StepModel
import numpy as np
from scipy.signal import savgol_filter
from pykalman import KalmanFilter
import statsmodels.api as sm

# Dependent on which computer this is performed on, the path can be manually set:
HDF5_FILE = "/Users/nisfi/Sync_C9_measurements/storedMeasurements.hdf5"
DATA_PATH = "/Users/nisfi/Sync_C9_measurements/"

OHMIC_CORRECTION = 0.95
NAME_OF_PROJECT = "N9_platinum_characterization_smooth"
AN_OVERVIEW = "An overview"

sample_uid_to_plot = [1287, 1288, 1290]


def get_all(name: str) -> str():
    """Print function to show the content of the HDF5 file"""
    print(name)


def set_column_headers_cv(df: pd.DataFrame) -> pd.DataFrame:
    """Set column headers for CV data

    Args:
        data (pd.DataFrame): Dataframe containing CV data in the order [Index, Time (s), Potential (WE vs. RHE) [V], Vu (V), Current [A],
        Vsig, Ach (V), IERange, Overbit1, Stop Test, Scan cycle, Temperature (C)]

    Returns:
        pd.DataFrame: Dataframe with new column headers
    """

    # Define the desired column names
    column_names = [
        "Potential (WE vs. RHE) [V]",
        "Current [A]",
        "Scan cycle",
        "Corrected potential (WE vs. RHE) [V]",
    ]

    # Check if the number of columns is 12 and insert "Index" at the beginning of the column names
    if len(df.columns) == 5:
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


def get_floats_and_element_from_string(some_string: str) -> list:
    """Get floats from string

    Args:
        some_string (str): String containing a string and a float

    Returns:
        list: List of a string and a float
    """

    m = re.search(r"\d", some_string)
    if m:
        # print("Digit found at position", m.start())
        key = int(m.start())
    else:
        print("No digit in that string")

    # Get floats from string
    value = str()
    element = str()
    try:
        # Define element (material name)
        for j in range(0, key):
            element = element + some_string[j]
        # define value (% used in experiment)
        for i in range(key, len(some_string)):
            value = value + some_string[i]
        value = float(value)
    except Exception as e:
        print(f"    WARNING: Couldn't get floats from string. Error: {e}")
        print(f"    key of first integer was: {key}")
        print(f"    String to proccess was: {some_string}")
        value = None
        pass

    return element, value


def correct_for_ohmic_resistance(
    df: pd.DataFrame,
    ohmic_resistance: float,
    ohmic_correction_factor: float = OHMIC_CORRECTION,
) -> pd.DataFrame:
    """Correct potential for ohmic resistance

    Args:
        df (pd.DataFrame): Dataframe containing the data to correct. Must contain a
        column named "Current [A]" and a column named "Potential (WE vs. RHE) [V]".
        ohmic_resistance (float): Ohmic resistance in ohm

    Returns:
        pd.DataFrame: Dataframe with corrected potential
    """
    df["Corrected potential (WE vs. RHE) [V]"] = (
        df["Potential (WE vs. RHE) [V]"]
        - ohmic_correction_factor * ohmic_resistance * df["Current [A]"]
    )

    return df


def get_float_from_string(some_string: str, max_count: int) -> float:
    """Get floats from string

    Args:
        some_string (str): String containing a string and a float
        max_count (int): Number of characters to read from string

    Returns:
        float: Float from string
    """
    try:
        floats = float(some_string[:max_count])
    except Exception as e:
        print(f"    WARNING: Couldn't get floats from string. Error: {e}")
        floats = None
    return floats


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
    print("   Fitting: Step model")
    step_mod = StepModel(form="logistic", prefix="log_")
    pars = step_mod.guess(y, x=x)

    # Fit data to gaussian model
    print("   Fitting: Gaussian model")
    gauss_mod = GaussianModel(prefix="g1_")
    pars.update(gauss_mod.guess(y, x=x))

    # Combining models
    mod = gauss_mod + step_mod  # + exp_mod
    mod.eval(pars, x=x)
    y_log_gaus = mod.fit(y, pars, x=x)
    # print(y_log_gaus.fit_report(correl_mode="table"))  # Correleation of parameters

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


def filter_data(
    df: pd.DataFrame,
    lower_potential: float = 0.65,
    upper_potential: float = 0.9,
    first_cycle: int = 19,
    last_cycle: int = 19,
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

    # For each "Scan cycle", remove the last row of filtered_data to
    # avoid negative "Current" values
    filtered_data = filtered_data.groupby("Scan cycle").apply(lambda x: x.iloc[:-1])

    return filtered_data


def smooth_data(df: pd.DataFrame, window_length: int = 7) -> pd.DataFrame:
    """Smooth data

    Args:
        df (pd.DataFrame): Dataframe containing the data to smooth. Must contain a
        column named "Current [A]" and a column named "Potential (WE vs. RHE) [V]".
        window_length (int, optional): Length of the window to smooth. Defaults to 5.

    Returns:
        pd.DataFrame: Dataframe with smoothed data
        peak_value (float): Peak value of the smoothed data
    """
    # Smooth data
    df["Current [A]"] = df["Current [A]"].rolling(window=window_length).mean()
    df["Category"] = "Fit: smothed_data"

    # Find the peak value of the smoothed data
    peak_current = df["Current [A]"].max()

    # Find the potential at which the peak value occurs
    peak_value = df[df["Current [A]"] == peak_current][
        "Corrected potential (WE vs. RHE) [V]"
    ].values[0]

    # Remove the first 5 points of the smoothed data to avoid fluctuations
    df = df.iloc[5:]

    return df, peak_value


def smooth_data_lowess(df: pd.DataFrame, frac: float = 0.1) -> pd.DataFrame:
    """Smooth data using Lowess smoothing

    Args:
        df (pd.DataFrame): Dataframe containing the data to smooth. Must contain a
        column named "Current [A]" and a column named "Potential (WE vs. RHE) [V]".
        frac (float, optional): Fraction of the data used for smoothing. Defaults to 0.1.

    Returns:
        pd.DataFrame: Dataframe with smoothed data
        peak_value (float): Peak value of the smoothed data
    """
    # Smooth data using Lowess smoothing
    lowess = sm.nonparametric.lowess
    smoothed_current = lowess(df["Current [A]"], df["Potential (WE vs. RHE) [V]"], frac=frac)
    df["Current [A]"] = smoothed_current[:, 1]
    df["Category"] = "Fit: smothed_data"

    # Find the peak value of the smoothed data
    peak_current = df["Current [A]"].max()

    # Find the potential at which the peak value occurs
    peak_value = df[df["Current [A]"] == peak_current]["Potential (WE vs. RHE) [V]"].values[0]

    return df, peak_value


def smooth_data_kalman(df: pd.DataFrame) -> pd.DataFrame:
    """Smooth data using Kalman Filtering

    Args:
        df (pd.DataFrame): Dataframe containing the data to smooth. Must contain a
        column named "Current [A]" and a column named "Potential (WE vs. RHE) [V]".

    Returns:
        pd.DataFrame: Dataframe with smoothed data
        peak_value (float): Peak value of the smoothed data
    """
    measurements = df["Current [A]"].values.reshape(-1, 1)

    # Define initial state mean and covariance
    initial_state_mean = measurements[0]
    initial_state_covariance = 1

    # Define transition matrix
    transition_matrix = 1

    # Define observation matrix
    observation_matrix = 1

    # Define Kalman filter
    kf = KalmanFilter(
        initial_state_mean=initial_state_mean,
        initial_state_covariance=initial_state_covariance,
        transition_matrices=transition_matrix,
        observation_matrices=observation_matrix,
    )

    # Smooth measurements using Kalman filter
    smoothed_state_means, _ = kf.smooth(measurements)

    # Update the dataframe with the smoothed values
    df["Current [A]"] = smoothed_state_means.flatten()
    df["Category"] = "Fit: smothed_data"

    # Find the peak value of the smoothed data
    peak_current = df["Current [A]"].max()

    # Find the potential at which the peak value occurs
    peak_value = df[df["Current [A]"] == peak_current][
        "Corrected potential (WE vs. RHE) [V]"
    ].values[0]

    return df, peak_value


def smooth_data_savgol(df: pd.DataFrame, window_length: int = 7):
    """Smooth data using Savitzky-Golay filtering.

    Args:
        df (pd.DataFrame): DataFrame containing the data to smooth.
                           Must contain columns named "Current [A]" and "Potential (WE vs. RHE) [V]".
        window_length (int, optional): Length of the window for smoothing. Defaults to 7.

    Returns:
        pd.DataFrame: DataFrame with smoothed data.
        peak_value (float): Peak value of the smoothed data.
    """
    # Smooth data using Savitzky-Golay filter
    df["Current [A]"] = savgol_filter(df["Current [A]"], window_length, 2)

    # Find the peak value of the smoothed data
    idx_peak = df["Current [A]"].idxmax()
    peak_value = df.at[idx_peak, "Corrected potential (WE vs. RHE) [V]"]

    # Remove the first and last 5 points of the smoothed data to avoid fluctuations
    df = df.iloc[5:-5]

    return df, float(peak_value)


with h5py.File(HDF5_FILE, "r") as f:
    for group in f.keys():
        group_name = str(group)
        uid = group_name.split("_")[0]
        df_first_last_cv = pd.DataFrame()
        df_group_cv = pd.DataFrame()
        highest_count_cv_scan = 0

        if uid.isdigit() and int(uid) in sample_uid_to_plot:
            print("")
            print("")
            print(f"UID: {uid}")

            # Get attributes from group
            dict_attributes = {
                "platinum_fitted_r_squared_accepted": 0.0,
                "platinum_fitted_r_squared_initial": 0.0,
                "platinum_peak_potential_fitted_accepted": 0.0,
                "platinum_peak_potential_fitted_initial": 0.0,
                "platinum_peak_potential_fitted_after_tests": 0.0,
                "platinum_peak_potential_smoothed_accepted": 0.0,
                "platinum_peak_potential_smoothed_after_tests": 0.0,
                "platinum_peak_potential_smoothed_initial": 0.0,
                "platinum_r_squared_after_tests": 0.0,
                "pt_ohmic_resistance": 0.0,
                "UID": 0,
                "Date": "Date goes here",
            }

            for m in f[group].attrs.keys():
                attr_name = str(m)

                if attr_name in dict_attributes:
                    dict_attributes[attr_name] = f[group].attrs[m]

            ohmic_resistance = dict_attributes["pt_ohmic_resistance"]

            # Print attributes line by line
            print("Attributes:")
            for key in dict_attributes:
                print(f"    {key}: {dict_attributes[key]}")

            # Get data from group
            for dset in f[group].keys():
                # Get data from dataset
                df = pd.DataFrame(f[group][dset][:])

                # If dset contains "CV", then it is CV data
                if "Pt_CV_accepted" in str(dset):
                    print(f"Plotting dataset: {str(dset)}")

                    # Set column headers of CV data
                    df = set_column_headers_cv(df)

                    # Correct for ohmic resistance # XXX NOT NEEDED, data has already been corrected
                    # df = correct_for_ohmic_resistance(
                    #     df,
                    #     ohmic_resistance,
                    #     OHMIC_CORRECTION,
                    # )

                    try:
                        ###########################################################################
                        # Filter data
                        ###########################################################################
                        df_pt_filtered = filter_data(
                            df,
                            lower_potential=0.65,
                            upper_potential=0.90,
                            first_cycle=19,
                            last_cycle=19,
                        )

                        #########################################################################
                        # Smooth data using Savitzky-Golay filter
                        #########################################################################
                        df_smoothed, pt_peak_smoothed = smooth_data_savgol(df_pt_filtered)
                        df_smoothed = df_smoothed.copy()
                        df_smoothed["Category"] = f"Smoothed: Peak {round(pt_peak_smoothed, 3)}V"
                        print(f"   Peak potential of smoothed data: {round(pt_peak_smoothed, 3)}V")

                        #########################################################################
                        # Fit data to a step model and a gaussian model
                        #########################################################################
                        df_fitted, pt_peak_fitted, r_squared_fitted = fit_function(df_pt_filtered)
                        print(f"   R-squared value of the fit: {r_squared_fitted}")
                        print(f"   Potential of the platinum peak fit: {pt_peak_fitted}")

                        df_fitted["Category"] = (
                            f"Fit Gaus/Logistic: Peak {round(pt_peak_fitted, 3)}V"
                        )

                    except Exception as e:
                        print(f"   WARNING: Couldn't fit data. Error: {e}")
                        pt_peak_fitted = None
                        r_squared_fitted = None
                        df_fitted = pd.DataFrame()

                    ###########################################################################
                    # Select only second last cycle to plot
                    ###########################################################################
                    # Select only second last cycle to plot
                    df_second_last_cycle = df[df["Scan cycle"] == df["Scan cycle"].max() - 1]
                    df_second_last_cycle = df_second_last_cycle.copy()
                    df_second_last_cycle["Category"] = f"Cycle {int(df['Scan cycle'].max() - 1)}"

                    # Add data to combined dataframe for all CV scans
                    df_group_cv = pd.concat(
                        [df_second_last_cycle, df_smoothed, df_fitted], ignore_index=True
                    )

                    ###########################################################################
                    # Plot
                    ###########################################################################
                    # Make the plot using plotly
                    fig = px.scatter(
                        df_group_cv,
                        x="Corrected potential (WE vs. RHE) [V]",
                        y="Current [A]",
                        color="Category",
                        title=f"{uid} Pt peak potential",
                    )

                    # Save the plot to html
                    fig.write_html(f"{DATA_PATH}{uid}_Pt_peak_potential.html")
                else:
                    print(f"Skipping dataset: {str(dset)}")
