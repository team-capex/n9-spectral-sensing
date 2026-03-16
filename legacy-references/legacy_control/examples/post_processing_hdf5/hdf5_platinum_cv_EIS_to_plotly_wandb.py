import h5py
import pandas as pd
import plotly.express as px
import re
from lmfit.models import GaussianModel
from lmfit.models import ExponentialModel
import numpy as np
import wandb
from scipy.signal import savgol_filter
from pykalman import KalmanFilter
import statsmodels.api as sm

# Dependent on which computer this is performed on, the path can be manually set:
from control_lib.params import HDF5_FILE, DATA_PATH

# HDF5_FILE = "/Users/nisfi/Sync_C9_measurements/storedMeasurements.hdf5"
# DATA_PATH = "/Users/nisfi/Sync_C9_measurements/"

OHMIC_CORRECTION = 0.95
NAME_OF_PROJECT = "N9_platinum_characterization_smooth"
AN_OVERVIEW = "An overview"

sample_uid_to_plot = [
    1048,
    1049,
    1050,
    1051,
    1052,
    1053,
    1054,
    1056,
    1057,
    1058,
    1059,
    1060,
    1061,
    1062,
    1063,
    1064,
    1065,
    1068,
    1069,
    1071,
    1072,
    1074,
    1075,
    1076,
    1077,
    1078,
    1079,
    1080,
    1081,
    1083,
    1084,
    1085,
    1086,
    1087,
    1088,
    1089,
    1090,
    1091,
    1092,
    1093,
    1094,
]


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

    # Fit data to exponential and gaussian model
    print("Fitting: Exponential model")
    exp_mod = ExponentialModel(prefix="exp_")
    pars = exp_mod.guess(y, x=x)
    print("Fitting: Gaussian model")
    gauss1 = GaussianModel(prefix="g1_")
    pars.update(gauss1.guess(y, x=x))

    # Combining models
    mod = gauss1 + exp_mod
    mod.eval(pars, x=x)
    y_exp_gaus = mod.fit(y, pars, x=x)
    # print(y_exp_gaus.fit_report(correl_mode="table"))  # Correleation of parameters

    # Locating peak of fitted data
    potential_pt_peak = y_exp_gaus.params["g1_center"].value

    # Get R-squared error
    r_squared = y_exp_gaus.rsquared

    # Combining x and y values and add labels
    fitted_data_exp_gauss = pd.DataFrame(
        {
            "Corrected potential (WE vs. RHE) [V]": x,
            "Potential (WE vs. RHE) [V]": x_uncorrected,
            "Current [A]": y_exp_gaus.best_fit,
        }
    )
    fitted_data_exp_gauss["Category"] = "Fit: gauss+exp"

    return fitted_data_exp_gauss, potential_pt_peak, r_squared


def filter_data(
    df: pd.DataFrame,
    lower_potential: float = 0.7,
    upper_potential: float = 0.93,
    first_cycle: int = 10,
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


def smooth_data_savgol(df: pd.DataFrame, window_length: int = 7) -> pd.DataFrame:
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
    df["Category"] = "Fit: smothed_data"

    # Find the peak value of the smoothed data
    peak_current = df["Current [A]"].max()

    # Find the potential at which the peak value occurs
    peak_value = df[df["Current [A]"] == peak_current][
        "Corrected potential (WE vs. RHE) [V]"
    ].values[0]

    # Remove the first 5 points of the smoothed data to avoid fluctuations
    df = df.iloc[5:]

    # Remove the last 5 points of the smoothed data to avoid fluctuations
    df = df.iloc[:-5]

    return df, peak_value


df_all_cv = pd.DataFrame()
df_peaks = pd.DataFrame()
columns = [
    "UID",
    "Peak potential [V]",
    "Dataset",
    "R-squared",
    "Ohmic resistance end [Ohm]",
    "Ohmic resistance start [Ohm]",
    "Acid concentration [mol/L]",
    "Electrolyte concentration [mol/L]",
    "Delay acid [s]",
    "Delay air [s]",
    "Delay between cycles [s]",
    "Delay prior rest in electrolyte [s]",
    "Delay water [s]",
]
df_peaks = pd.DataFrame(columns=columns)

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
            wandb.init(
                name=uid,
                project=NAME_OF_PROJECT,
            )
            try:
                # Get attributes from group
                dict_attributes = {
                    "Pt": None,
                    "Date": None,
                    "ohmic_resistance_end": None,
                    "ohmic_resistance_start": None,
                    "acid_concentration": None,
                    "electrolyte_concentration": None,
                    "delay_acid": None,
                    "delay_air": None,
                    "delay_between_cycles": None,
                    "delay_electrolyte_cycle": None,
                    "delay_water": None,
                }

                for m in f[group].attrs.keys():
                    attr_name = str(m)

                    if attr_name in dict_attributes:
                        dict_attributes[attr_name] = f[group].attrs[m]

                ohmic_resistance = dict_attributes["ohmic_resistance_start"]

                # Print attributes line by line
                print("Attributes:")
                for key in dict_attributes:
                    print(f"    {key}: {dict_attributes[key]}")

                # Get data from group
                for dset in f[group].keys():
                    print("")
                    print(f"Dataset: {str(dset)}")

                    # Get data from dataset
                    df = pd.DataFrame(f[group][dset][:])

                    # If dset contains "CV", then it is CV data
                    if "CV" in str(dset):
                        # Find integer of in the string dset
                        number_in_dset = int(re.search(r"\d+", dset).group())

                        # Find largest number in dset
                        if highest_count_cv_scan < number_in_dset:
                            highest_count_cv_scan = number_in_dset

                        # Set column headers of CV data
                        df = set_column_headers_cv(df)

                        # Correct for ohmic resistance
                        df = correct_for_ohmic_resistance(
                            df,
                            ohmic_resistance,
                            OHMIC_CORRECTION,
                        )

                        # Make individual labels
                        df["Category"] = (
                            f"{uid} {dset}, Acid {dict_attributes['delay_acid']}s, water {dict_attributes['delay_water']}s, air {dict_attributes['delay_air']}s, electrolyte {dict_attributes['delay_electrolyte_cycle']}s, between cycles {dict_attributes['delay_between_cycles']}s, HCl {dict_attributes['acid_concentration']}mol/L, KOH {dict_attributes['electrolyte_concentration']}mol/L"
                        )

                        ###########################################################################
                        # In this section we make a fit to the measurements and then deduct the
                        # potential at which the oxidation peak on pt occurs
                        ###########################################################################

                        # Filter data to select only the relevant cycles,
                        # potential range and forward scans
                        df_filtered = filter_data(
                            df,
                            lower_potential=0.65,
                            upper_potential=0.85,
                            first_cycle=19,
                            last_cycle=19,
                        )

                        try:
                            # # Fit model to selected data
                            # df_fit, potential_pt_peak, r_squared = fit_function(
                            #     df_filtered
                            # )
                            # print(
                            #     f"potential_pt_peak: {round(potential_pt_peak, 4)}V, r_squared: {r_squared}"
                            # )
                            # # Rename fitted_data where ["Category"] = "Fit: gauss+exp"
                            # df_fit.loc[
                            #     df_fit["Category"] == "Fit: gauss+exp", "Category"
                            # ] = f"{uid} {dset} fit, peak {round(potential_pt_peak, 3)}V"

                            df_fit, potential_pt_peak = smooth_data_lowess(df_filtered)
                            r_squared = "Smoothed data"
                            print(f"potential_pt_peak: {round(potential_pt_peak, 4)}V")

                            df_fit.loc[df_fit["Category"] == "Fit: smothed_data", "Category"] = (
                                f"{uid} {dset} smoothed, peak {round(potential_pt_peak, 3)}V"
                            )
                        except Exception as e:
                            print(f"WARNING: Couldn't fit data. Error: {e}")
                            potential_pt_peak = None
                            r_squared = None
                            df_fit = pd.DataFrame()

                        ###########################################################################
                        # In this section we store data in different dataframes to make
                        # combined plots
                        ###########################################################################
                        # Select only second last cycle to plot
                        df_second_last_cycle = df[df["Scan cycle"] == df["Scan cycle"].max() - 1]

                        # Add data to combined dataframe for all CV scans
                        df_group_cv = pd.concat(
                            [df_group_cv, df_second_last_cycle], ignore_index=True
                        )

                        # Add data to combined dataframe for initial scan
                        if number_in_dset == 1:
                            print("First CV scan storing")
                            df_first_cv = df_second_last_cycle
                            df_fit_first_cv = df_fit
                            fit_first_potential_pt_peak = potential_pt_peak

                        # Add data from last run to combined dataframe
                        if (number_in_dset - 1) % 5 == 0 and f"{highest_count_cv_scan}" in str(dset):
                            print("Last CV scan storing")
                            df_last_cv = df_second_last_cycle
                            df_fit_last_cv = df_fit
                            fit_last_potential_pt_peak = potential_pt_peak

                        # Add data to df_peaks
                        df_peaks = df_peaks.append(
                            {
                                "UID": uid,
                                "Peak potential [V]": potential_pt_peak,
                                "Dataset": str(dset),
                                "R-squared": r_squared,
                                "Ohmic resistance end [Ohm]": dict_attributes[
                                    "ohmic_resistance_end"
                                ],
                                "Ohmic resistance start [Ohm]": dict_attributes[
                                    "ohmic_resistance_start"
                                ],
                                "Acid concentration [mol/L]": dict_attributes["acid_concentration"],
                                "Electrolyte concentration [mol/L]": dict_attributes[
                                    "electrolyte_concentration"
                                ],
                                "Delay acid [s]": dict_attributes["delay_acid"],
                                "Delay air [s]": dict_attributes["delay_air"],
                                "Delay between cycles [s]": dict_attributes["delay_between_cycles"],
                                "Delay prior rest in electrolyte [s]": dict_attributes[
                                    "delay_electrolyte_cycle"
                                ],
                                "Delay water [s]": dict_attributes["delay_water"],
                            },
                            ignore_index=True,
                        )

                    else:
                        print("WARNING: Not CV data - skipping")

                # Merge first and last CV scan data and fitted data
                df_first_last_cv = pd.concat(
                    [df_first_cv, df_fit_first_cv, df_last_cv, df_fit_last_cv],
                    ignore_index=True,
                )

                df_all_cv = pd.concat([df_all_cv, df_first_cv, df_last_cv], ignore_index=True)

                fig = px.scatter(
                    df_first_last_cv,
                    x="Corrected potential (WE vs. RHE) [V]",
                    y="Current [A]",
                    color="Category",
                    title=f"{uid} First and last CV scan",
                )
                # fig.show()

                # Upload dict_attributes, fit_last_potential_pt_peak and
                # fit_first_potential_pt_peak to wandb.ai as attributes
                wandb.config.update(dict_attributes)
                wandb.config.update(
                    {
                        "fit_last_potential_pt_peak": fit_last_potential_pt_peak,
                        "fit_first_potential_pt_peak": fit_first_potential_pt_peak,
                    }
                )

                # Upload figure to wandb.ai
                print("Uploading first/last scans to wandb.ai")
                wandb.log({f"{uid} First and last CV scan": fig})

                # Upload table to wandb.ai
                tbl = wandb.Table(dataframe=df_first_last_cv)
                wandb.log({f"{str(uid)} first/last CV data": tbl})

                print("")
                print("")

            # Throw exception with error message
            except Exception as e:
                print("Couldn't open group", group_name, "and error was:", e)

            # Sort dataframe by "Category"
            df_group_cv.sort_values("Category")

            # Plot all CV scans
            fig = px.scatter(
                df_group_cv,
                x="Corrected potential (WE vs. RHE) [V]",
                y="Current [A]",
                color="Category",
                title=f"{uid} CV scans",
            )
            # fig.show()

            # Upload figure to wandb.ai
            print("Uploading group scans to wandb.ai")
            wandb.log({f"{uid} platinum CV scans": fig})

            # Upload table to wandb.ai
            # Limit the number of rows to 20000
            if len(df_group_cv) > 20000:
                print("WARNING: Too many rows in table to upload.")
                print("Saving to csv instead locally")
                df_group_cv.to_csv(f"{uid}_platinum_CV_data.csv")

                while len(df_group_cv) > 20000:
                    # Remove every second row to reduce the number of rows
                    print("Reducing number of rows")
                    df_group_cv = df_group_cv.iloc[::2, :]

                print(f"Reduced number of rows to {len(df_group_cv)}")
            tbl = wandb.Table(dataframe=df_group_cv)
            wandb.log({f"{str(uid)} platinum CV data": tbl})

            wandb.finish()

# Sort dataframe by "Category"
df_all_cv.sort_values("Category")

# Plot all CV scans
fig = px.scatter(
    df_all_cv,
    x="Corrected potential (WE vs. RHE) [V]",
    y="Current [A]",
    color="Category",
    title="All platinum CV scans",
)
fig.write_html("all_platinum_CV_scans.html")
# fig.show()

# Upload figure to wandb.ai
wandb.init(
    name=AN_OVERVIEW,
    project=NAME_OF_PROJECT,
)
print("Uploading all platinum CV scans to wandb.ai")
wandb.log({"All platinum CV scans": fig})

# Upload table to wandb.ai
# Limit the number of rows to 20000
if len(df_all_cv) > 20000:
    print("WARNING: Too many rows in table to upload.")
    print("Saving to csv instead locally")
    df_all_cv.to_csv("all_platinum_CV_data.csv")

    while len(df_all_cv) > 20000:
        # Remove every second row to reduce the number of rows
        print("Reducing number of rows")
        df_all_cv = df_all_cv.iloc[::2, :]
    print(f"Reduced number of rows to {len(df_all_cv)}")

tbl1 = wandb.Table(dataframe=df_all_cv)
wandb.log({"all_platinum_CV_data": tbl1})

# Upload table to wandb.ai
# Limit the number of rows to 20000
if len(df_peaks) > 20000:
    print("WARNING: Too many rows in table to upload. ")
    print("Saving to csv locally")
    df_peaks.to_csv("all_platinum_peaks.csv")

    while len(df_peaks) > 20000:
        # Remove every second row to reduce the number of rows
        print("Reducing number of rows")
        df_peaks = df_peaks.iloc[::2, :]
    print(f"Reduced number of rows to {len(df_peaks)}")

tbl2 = wandb.Table(dataframe=df_peaks)
wandb.log({"all_platinum_peaks": tbl2})

wandb.finish()
