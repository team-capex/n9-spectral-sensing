import wandb
import h5py
import pandas as pd
import numpy as np
import plotly.express as px
import re
from control_lib.params import HDF5_FILE

# HDF5_FILE = "/Users/nisfi/Sync_C9_measurements/storedMeasurements.hdf5"

NAME_OF_PROJECT = "N9_OER_2024_NIS_TEST"
OHMIC_CORRECTION = 0.95
AN_OVERVIEW = "An overview"

list_of_sample_UIDs = [1000, 1003]


def get_all(name: str) -> str():
    """Print function to show the content of the HDF5 file"""
    print(name)


def plot_potential(
    keyParameters: pd.DataFrame,
    project_name: str = NAME_OF_PROJECT,
    name: str = AN_OVERVIEW,
    title_of_plot: str = "Potential at 10 mA/cm2 vs. uid",
) -> None:
    """Plot potential at 10 mA/cm2 vs. uid to wandb.ai

    Args:
        keyParameters (pd.DataFrame): Dataframe containing the key parameters
        for each sample
        [uid, current, raw potential, corrected potential, resistance]
        project_name (str, optional): Project name on wandb.ai. Defaults
        to "N9_OER_2023".
        title_of_plot (str, optional): Title of plot.. Defaults to
        "Potential at 10 mA/cm2 vs. uid".
    """

    print("Plotting potential for all samples.")
    wandb.init(
        # set the wandb project where this run will be logged
        project=project_name,
        name=name,
    )

    fig = px.scatter(
        keyParameters,
        x="Unique ID",
        y="Corrected potential [V]",
        title=title_of_plot,
        template="plotly_white",
    )

    # Log plot to wandb.ai
    print("Uploading to wandb.ai")
    wandb.log({"Potential vs. UID": fig})
    fig = None


def scrub_data(data: pd.DataFrame) -> pd.DataFrame:
    """Scrub data to remove unwanted data

    Args:
        data (pd.DataFrame): keyParameter dataframe, which contains
        ["Unique ID", "Current [A]", "Raw potential [V]",
        "Corrected potential [V]", "Resistance [ohm]"]

    Returns:
        pd.DataFrame: Scrubbed keyParameter dataframe
    """
    print("Scrubbing keyParameters dataframe")

    # Drop rows where data is equal to 0
    data = data.loc[(data["Current [A]"] != 0) & (data["Raw potential [V]"] != 0)]

    # Drop rows where column "Resistance [ohm]" is larger than 2 or equal to 0
    data = data.loc[(data["Resistance [ohm]"] <= 2) & (data["Resistance [ohm]"] != 0)]

    # Drop rows where "Corrected potential [V]" is smaller than 1.3
    data = data.loc[data["Corrected potential [V]"] >= 1.3]

    return data


def plot_ohmic_resistance(
    keyParameters: pd.DataFrame,
    project_name: str = NAME_OF_PROJECT,
    name: str = AN_OVERVIEW,
    title_of_plot: str = "Resistance vs. uid",
) -> None:
    """Plot ohmic resistance vs. uid to wandb.ai

    Args:
        keyParameters (pd.DataFrame): Dataframe containing the key parameters
        for each sample
        [uid, current, raw potential, corrected potential, resistance]
        project_name (str, optional): Project name on wandb.ai.
        name_of_plot (str, optional): Plot name on wandb.ai. Defaults to
        "Resistance vs. uid".
    """

    print("Plotting ohmic resistance for all samples.")
    wandb.init(
        resume=name,
        project=project_name,
    )

    fig = px.scatter(
        keyParameters,
        x="Unique ID",
        y="Resistance [ohm]",
        title=title_of_plot,
        template="plotly_white",
    )

    # Log plot to wandb.ai
    print("Uploading to wandb.ai")
    wandb.log({"Resistance vs. UID": fig})
    fig = None


def plot_all_cv(
    df: pd.DataFrame,
    project_name: str = NAME_OF_PROJECT,
    title_of_plot: str = "Cyclic voltametry, 200mV/s, 24th cycle",
    name: str = AN_OVERVIEW,
):
    """Plot all CVs in one plot

    Args:
        df (pd.DataFrame): Dataframe containing CV data
        project_name (str, optional): Project name on wandb.ai.
        name_of_plot (str, optional): Plot name on wandb.ai. Defaults to
        "Cyclic voltametry, 200mV/s, 24th cycle".
    """
    print("Plotting cyclic voltammetry of all samples at 200 mV/s, cycle 24.")
    wandb.init(
        resume=name,
        project=project_name,
    )

    fig = px.line(
        df,
        x="Corrected potential (WE vs. RHE) [V]",
        y="Current [A]",
        title=title_of_plot,
        color="UID",
        template="plotly_white",
    )

    # Log plot to wandb.ai
    print("Uploading to wandb.ai")
    wandb.log({"CV all samples": fig})
    fig = None


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


def set_column_headers_cp(data: pd.DataFrame) -> pd.DataFrame:
    """Set column headers for CP data

    Args:
        data (pd.DataFrame): Dataframe containing CP data

    Returns:
        pd.DataFrame: Dataframe with correct column headers
    """

    # Define the desired column names
    column_names = [
        "Time [s]",
        "Potential (WE vs. RHE) [V]",
        "Vu (V)",
        "Current [A]",
        "Charge Q",
        "Vsig",
        "Ach (V)",
        "IERange",
        "Overbit1",
        "Stop Test",
    ]

    # Check if the data has an extra column ("Index")
    if len(data.columns) == 11:
        column_names.insert(0, "Index")

    # Set the column names of the dataframe
    data.columns = column_names

    # Specify the columns to be dropped
    columns_to_drop = [
        "Time (s)",
        "Vu (V)",
        "Vsig",
        "Charge Q",
        "Ach (V)",
        "IERange",
        "Overbit1",
        "Stop Test",
        "Temperature (C)",
    ]

    # Drop the specified columns from the dataframe, ignoring any errors
    data = data.drop(columns=columns_to_drop, errors="ignore")

    # Drop the "Index" column if it exists
    if "Index" in data.columns:
        data = data.drop(columns=["Index"])

    return data


def find_ohmic_and_potential(keyParameters: pd.DataFrame, uid: str) -> list:
    """Find ohmic resistance and potential at 10 mA/cm2

    Args:
        keyParameters (pd.DataFrame): Dataframe containing the key parameters
        for each sample
        [uid, current, raw potential, corrected potential, resistance]
        uid (str): Unique ID of sample

    Returns:
        list: [ohmic resistance,
        potential at 10 mA/cm2,
        ohmic corrected potential at 10 mA/cm2,
        successfull run]

    """
    ohmic_resistance = keyParameters.loc[
        keyParameters["Unique ID"] == int(uid), "Resistance [ohm]"
    ].iloc[0]
    print(f"ohmic_resistance: {ohmic_resistance}")

    potential_raw_at_10mAcm2 = keyParameters.loc[
        keyParameters["Unique ID"] == int(uid), "Raw potential [V]"
    ].iloc[0]
    print(f"potential_raw_at_10mAcm2: {potential_raw_at_10mAcm2}")

    potential_ohmic_corrected_at_10mAcm2 = keyParameters.loc[
        keyParameters["Unique ID"] == int(uid), "Corrected potential [V]"
    ].iloc[0]
    successfull_run = True

    return (
        ohmic_resistance,
        potential_raw_at_10mAcm2,
        potential_ohmic_corrected_at_10mAcm2,
        successfull_run,
    )


def set_legend_cp(dset: str) -> str:
    """Set legend for CP plots

    Args:
        dset (str): Dataset name in HDF5 file

    Returns:
        str: Legend for CP plots
    """

    if "CP1.0" in str(dset):
        legend = "1 mA/cm2"
    elif "CP1mA" in str(dset):
        legend = "1 mA/cm2"
    elif "CP2.0" in str(dset):
        legend = "2 mA/cm2"
    elif "CP2mA" in str(dset):
        legend = "2 mA/cm2"
    elif "CP5.0" in str(dset):
        legend = "5 mA/cm2"
    elif "CP5mA" in str(dset):
        legend = "5 mA/cm2"
    elif "CP10.0" in str(dset):
        legend = "10 mA/cm2"
    elif "CP10mA" in str(dset):
        legend = "10 mA/cm2"
    elif "CP20.0" in str(dset):
        legend = "20 mA/cm2"
    elif "CP20mA" in str(dset):
        legend = "20 mA/cm2"
    elif "CP50.0" in str(dset):
        legend = "50 mA/cm2"
    elif "CP50mA" in str(dset):
        legend = "50 mA/cm2"
    elif "CP100.0" in str(dset):
        legend = "100 mA/cm2"
    elif "CP100mA" in str(dset):
        legend = "100 mA/cm2"
    elif "CP200.0" in str(dset):
        legend = "200 mA/cm2"
    elif "CP200mA" in str(dset):
        legend = "200 mA/cm2"
    else:
        print("No CP data found")
        legend = None

    return legend


def set_column_headers_cv(data: pd.DataFrame) -> pd.DataFrame:
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
    if len(data.columns) == 12:
        column_names.insert(0, "Index")

    # Assign the new column names to the dataframe
    data.columns = column_names

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
    data = data.drop(columns=columns_to_drop, errors="ignore")

    # If "Index" column exists in the dataframe, drop it as well
    if "Index" in data.columns:
        data = data.drop(columns=["Index"])

    return data


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
        print(f"    String to proccess was: {some_string}")
        value = None
        pass

    return element, value


def get_float_from_string(some_string: str, max_count: int) -> float:
    """Get floats from string

    Args:
        some_string (str): String containing a string and a float
        max_count (int): Number of characters to read from string

    Returns:
        float: Float from string
    """
    # Get floats from string
    floats = str()
    try:
        for i in range(0, max_count):
            floats = floats + some_string[i]
    except Exception:
        pass
    floats = float(floats)
    return floats


def find_overpotential(data: pd.DataFrame) -> float:  # XXX This function is never used
    ampere_step2 = 0.01
    tstep2 = 60
    sample_rate = 0.5
    data_column = data["Potential (WE vs. RHE) [V]"]

    index_to_subtract = round(0.2 * (tstep2 / sample_rate))
    print("Index to subtract:", index_to_subtract)

    raw_potential = data_column.iloc[-index_to_subtract:-1].mean().round(3)
    print(f"Raw potential: {raw_potential}V")

    if ohmic_resistance is None:
        print("No potential correction added")
        overpotential_to_return = raw_potential
    else:
        potential_corr = raw_potential - (ampere_step2 * ohmic_resistance * OHMIC_CORRECTION)
        corrected_potential = round(potential_corr, 3)
        print(f"Corrected potential: {corrected_potential}V")
        overpotential_to_return = corrected_potential

    print(f"Overpotential: {overpotential_to_return}V")
    return overpotential_to_return


def write_recipe_and_summary(
    uid,
    mix_ratios,
    potential_corrected_at_10mAcm2,
    Sample_temperature_init,
    Room_temperature_aht20_init,
    Room_humidity_aht20_init,
    Room_atmospheric_pressure_init,
    rack_position_of_sample,
    oxide_remov_concentration,
    oxide_remov_chemical,
    oxide_remov_time,
    ultrasound_oxide_remov,
    ultrasound_rinsing,
    synthesis_1_time,
    oh_chemical,
    oh_concentration,
    oh_dip_time,
    synthesis_2_time,
    electrolyte,
    activation_time,
    cleaning_time,
    Sample_temperature_end,
    Room_temperature_aht20_end,
    mix_concentration,
) -> str:
    """Write recipe and summary of experiment to a string"""

    print("Writing recipe and summary of experiment to a string")
    txt = f"""Experiment {uid}
    Material: {mix_ratios}
    Ohmic corrected potential at 10 mA/cm2: {potential_corrected_at_10mAcm2}V

    DESCRIPTION OF EXPERIMENT
    1. Temperature measured in empty cell. Sample temperature
    {Sample_temperature_init}C.
    Atmospheric/room temperature: {Room_temperature_aht20_init}C
    Atmospheric relative humidity: {Room_humidity_aht20_init}%
    Atmospheric pressure: {Room_atmospheric_pressure_init}Pa


    2. Oxide removal on nickel foam (rack pos. {rack_position_of_sample})
    of 1 cm2 was carried out in {oxide_remov_concentration} mol/L
    {oxide_remov_chemical} for {oxide_remov_time}s. 9 ml of 
    {oxide_remov_chemical} was used and the dip was done in the test cell. 
    During the dip ultrasound was = {ultrasound_oxide_remov}.

    3. The foam was rinsed in deionized water by flushing with water 3 times.
    Ultrasound = {ultrasound_rinsing} was used 30s during each flushing.
    Fill level of water was 12 ml.

    4. A vial was filled with 6 ml of of a combination of:
    {mix_ratios} with a concentration of {mix_concentration} mol/L.
    and the nickel foam was dipped and rotated slowly in the vial for
    10 seconds.

    5. The foam was removed and the vial was cleaned and flushed with water 2 times.

    6. The foam was put to rest in its rack for {synthesis_1_time} seconds.

    7. A second vial was filled with 6 ml of {oh_chemical} with a concentration of
    {oh_concentration} mol/L. The foam was dipped (not rotated) in the vial for
    {oh_dip_time} seconds.

    8. The foam was removed and put to rest for the synthesis for 
    {synthesis_2_time} seconds.

    9. The foam was put in the test cell and the cell was filled with 12 ml of
    {electrolyte}. The sample was activated using Chronopotentiometry at
    200 mA/cm2 for {activation_time} seconds. After activation the sample was
    rinsed with ultrasound for {cleaning_time} seconds. The cell was then
    drained, filled with 9 ml of demineralized water 2 times and drained again.

    10. Temperature readings before the experiment (taken in in air in
    the cell) was {Sample_temperature_init}C and room temperature
    was {Room_temperature_aht20_init}C.

    11. Electrochemical measurements were done in the cell with the following
    datasets recorded:
    0 - Cyclic voltammetry at 200 mV/s, 25 cycles, 0.8-1.6V
    1 - Cyclic voltammetry at 10 mV/s, 1 cycle, 0.8-1.6V
    8 - Electrochemical impedance spectroscopy in potentiostatic mode,
    100kHz - 1Hz, 10 mV AC amplitude, 1.5V DC potential
    9 - Chronopotentiometry at 100 mA/cm2, 70 seconds
    10 - Chronopotentiometry at 50 mA/cm2, 70 seconds
    11 - Chronopotentiometry at 20 mA/cm2, 70 seconds
    12 - Chronopotentiometry at 10 mA/cm2, 70 seconds (last 20 seconds used to
    find potential at 10 mA/cm2)
    13 - Chronopotentiometry at 5 mA/cm2, 70 seconds
    14 - Chronopotentiometry at 2 mA/cm2, 70 seconds
    15 - Chronopotentiometry at 1 mA/cm2, 70 seconds
    16 - Cycling at 10 mV/s, 1 cycles, 0.8-1.6V

    12. Temperature readings after the experiment (taken in electrolyte in the cell)
    was {Sample_temperature_end}C and room temperature was {Room_temperature_aht20_end}C.

    13. The foam was removed to its rack position, and the cell was drained and cleaned 
    with {oxide_remov_chemical} for 20 seconds of which the 15 seconds was with ultrasound.
    The cell was then drained, rinsed with water 2 times while applying ultrasound for
    15 seconds each time. The cell was left empty.

    END OF EXPERIMENT
    """

    return txt


with h5py.File(HDF5_FILE, "r") as f:
    # Init variables
    CV_df = pd.DataFrame()

    # Read general data from HDF5 file into pandas dataframe
    keyParameters = pd.DataFrame(f["keyParameters"])
    keyParameters.columns = [
        "Unique ID",
        "Current [A]",
        "Raw potential [V]",
        "Corrected potential [V]",
        "Resistance [ohm]",
    ]
    keyParameters["index"] = keyParameters["Unique ID"]
    keyParameters.set_index("index", inplace=True)
    keyParameters = scrub_data(keyParameters)
    print("Loaded keyParameters")
    # print(f"{keyParameters.to_markdown()}")

    # Plot corrected potential at 10 mA/cm2 vs. uid
    plot_potential(keyParameters)

    # Plot ohmic resistance vs. uid
    plot_ohmic_resistance(keyParameters)

    # TODO Upload keyParameters to wandb.ai as a csv file
    wandb.finish()

    ###########################################
    # Make individual plots for each sample
    ###########################################
    # Loop through HDF5 groups (samples) to plot all data
    for group in f:
        print(" ")

        # Skip the keyParameters dataset in the root of HDF5 file
        group_name = str(group)
        if group == "keyParameters":
            print("Skipping keyParameters dataset")
            break

        # Init variables
        uid = group_name.split("_")[0]
        if int(uid) not in list_of_sample_UIDs:
            print(f"Skipping UID {uid}")
        else:
            CP_df = pd.DataFrame()
            print(f"UID: {uid}")

            # Loop through attributes in HDF5 group and
            # fill name and value into a dictionary, later stored in wandb.ai
            dict_attributes = {}
            date = None
            for m in f[group].attrs:
                dict_attributes.update({m: f[group].attrs[m]})
                if m == "Date":
                    date = f[group].attrs[m]
                if m == "mix_ratios":
                    mix_ratios = f[group].attrs[m]
                if m == "Sample_temperature_init":
                    Sample_temperature_init = f[group].attrs[m]
                if m == "Room_temperature_aht20_init":
                    Room_temperature_aht20_init = f[group].attrs[m]
                if m == "Room_humidity_aht20_init":
                    Room_humidity_aht20_init = f[group].attrs[m]
                if m == "Room_atmospheric_pressure_init":
                    Room_atmospheric_pressure_init = f[group].attrs[m]
                if m == "rack_position_of_sample":
                    rack_position_of_sample = f[group].attrs[m]
                if m == "oxide_remov_concentration":
                    oxide_remov_concentration = f[group].attrs[m]
                if m == "oxide_remov_chemical":
                    oxide_remov_chemical = f[group].attrs[m]
                if m == "oxide_remov_time":
                    oxide_remov_time = f[group].attrs[m]
                if m == "ultrasound_oxide_remov":
                    ultrasound_oxide_remov = f[group].attrs[m]
                if m == "ultrasound_cleaning":
                    ultrasound_cleaning = f[group].attrs[m]
                if m == "synthesis_1_time":
                    synthesis_1_time = f[group].attrs[m]
                if m == "oh_chemical":
                    oh_chemical = f[group].attrs[m]
                if m == "oh_concentration":
                    oh_concentration = f[group].attrs[m]
                if m == "oh_dip_time":
                    oh_dip_time = f[group].attrs[m]
                if m == "synthesis_2_time":
                    synthesis_2_time = f[group].attrs[m]
                if m == "electrolyte_chemical":
                    electrolyte_chemical = f[group].attrs[m]
                if m == "activation_time":
                    activation_time = f[group].attrs[m]
                if m == "cleaning_time":
                    cleaning_time = f[group].attrs[m]
                if m == "Sample_temperature_end":
                    Sample_temperature_end = f[group].attrs[m]
                if m == "Room_temperature_aht20_end":
                    Room_temperature_aht20_end = f[group].attrs[m]
                if m == "mix_concentration":
                    mix_concentration = f[group].attrs[m]

            # Split group name into list of elements and amount of each element
            new_name_list = group_name.split("_")
            new_name_list.pop(0)  # remove uid from list
            for element_and_value in new_name_list:
                element, value = get_floats_and_element_from_string(element_and_value)
                dict_attributes.update({element: value})

            # Read key parameters from HDF5 file
            try:
                [
                    ohmic_resistance,
                    potential_raw_at_10mAcm2,
                    potential_ohmic_corrected_at_10mAcm2,
                    successfull_run,
                ] = find_ohmic_and_potential(keyParameters, uid)

            except Exception:
                ohmic_resistance = 0
                potential_raw_at_10mAcm2 = 0
                potential_ohmic_corrected_at_10mAcm2 = 0
                successfull_run = False

            # Add ohmic resistance, potential at 10 mA/cm2 and ohmic corrected to dict_attributes
            dict_attributes.update(
                {
                    "ohmic_resistance": ohmic_resistance,
                    "potential_raw_at_10mAcm2": potential_raw_at_10mAcm2,
                    "potential_ohmic_corrected_at_10mAcm2": potential_ohmic_corrected_at_10mAcm2,
                    "successfull_run": successfull_run,
                }
            )

            # Write recipe and summary of experiment to a string
            recipe_and_summary = write_recipe_and_summary(
                str(uid),
                str(mix_ratios),
                str(potential_ohmic_corrected_at_10mAcm2),
                str(Sample_temperature_init),
                str(Room_temperature_aht20_init),
                str(Room_humidity_aht20_init),
                str(Room_atmospheric_pressure_init),
                str(rack_position_of_sample),
                str(oxide_remov_concentration),
                str(oxide_remov_chemical),
                str(oxide_remov_time),
                str(ultrasound_oxide_remov),
                str(ultrasound_cleaning),
                str(synthesis_1_time),
                str(oh_chemical),
                str(oh_concentration),
                str(oh_dip_time),
                str(synthesis_2_time),
                str(electrolyte_chemical),
                str(activation_time),
                str(cleaning_time),
                str(Sample_temperature_end),
                str(Room_temperature_aht20_end),
                str(mix_concentration),
            )

            # Trim dict attribute and ditch the uncertainty and unit to get a float
            # eg. Sample_temperature_init = 24.5 +- 1.5C should be
            # Sample_temperature_init = 24.5
            print("Trimming dict_attributes")
            for key, value in dict_attributes.items():
                if key.startswith("Room_") or key.startswith("Sample_temperature_"):
                    # Extract the float value from the string
                    float_value = float(value.split()[0])
                    # Update the value in the dictionary with the converted float
                    dict_attributes[key] = float_value
            print("dict_attributes:")
            for key, value in dict_attributes.items():
                print("   " + key + ": " + str(value))

            # Initiate wandb.ai for plotting and logging attributes from HDF5
            configuration = {
                **{
                    "uid": uid,
                    "successfull_run": successfull_run,
                    "potential_corrected_at_10mAcm2": potential_ohmic_corrected_at_10mAcm2,
                    "ohmic_resistance": ohmic_resistance,
                    "potential_raw_at_10mAcm2": potential_raw_at_10mAcm2,
                },
                **dict_attributes,
            }

            # set the wandb project where this run will be logged
            run = wandb.init(
                project=NAME_OF_PROJECT,
                name=str(uid),
                config=configuration,
                notes=recipe_and_summary,
            )
            try:
                # Loop through datasets in HDF5 group
                for dset in f[group].keys():
                    try:
                        print("")
                        print(group + "_" + dset)
                        print("--------------------------------------------------")
                        data = pd.DataFrame(f[group][dset][:])  # adding [:] returns a matrix

                        ##########################################
                        # Plot Cyclic Voltammetry (CV) measurements
                        ##########################################
                        if "CVact" in str(dset):
                            print(f"    CV {str(dset)}")

                            # Add names to columns in dataframe
                            data = set_column_headers_cv(data)

                            # Add column with ohmic corrected potential
                            data = correct_for_ohmic_resistance(
                                data, ohmic_resistance, OHMIC_CORRECTION
                            )
                            print("    Ohmic correction was applied")

                            # Find number of cycles
                            number_of_cycles = int(max(data["Scan cycle"])) + 1
                            print(f"    Number of scan cycles: {number_of_cycles}")

                            # Make colors for different cycles
                            rgb = px.colors.convert_colors_to_same_type(
                                px.colors.sequential.Viridis_r
                            )[0]
                            colorscale = []
                            if number_of_cycles <= 5:
                                fig = px.line(
                                    data,
                                    x="Corrected potential (WE vs. RHE) [V]",
                                    y="Current [A]",
                                    title=f"Cyclic Voltammetry, sample {uid}, {str(dset)}",
                                    color="Scan cycle",
                                    template="plotly_white",
                                )
                            else:
                                n_steps = 4  # Control the number of colors in the final colorscale
                                for i in range(len(rgb) - 1):
                                    for step in np.linspace(0, 1, n_steps):
                                        colorscale.append(
                                            px.colors.find_intermediate_color(
                                                rgb[i],
                                                rgb[i + 1],
                                                step,
                                                colortype="rgb",
                                            )
                                        )
                                fig = px.line(
                                    data,
                                    x="Corrected potential (WE vs. RHE) [V]",
                                    y="Current [A]",
                                    title=f"Cyclic Voltammetry, sample {uid}, {str(dset)}",
                                    color="Scan cycle",
                                    color_discrete_sequence=colorscale,
                                    template="plotly_white",
                                )

                            # fig.show()

                            # Store CV data in dataframe for later plotting
                            print("    Storing CV data in shared dataframe")
                            if "0.2mVsx25" in str(dset):
                                # Select data for times after 0 seconds
                                selected_data = data[data["Scan cycle"] == 23]
                                # Add column with legend string to dataframe
                                selected_data["UID"] = str(uid)
                                # Add to dataframe with all CV data
                                CV_df = pd.concat(
                                    [
                                        CV_df,
                                        selected_data,
                                    ],
                                    ignore_index=True,
                                )
                            elif "200mVsx25" in str(dset):
                                # Select data for times after 0 seconds
                                selected_data = data[data["Scan cycle"] == 23]
                                # Add column with legend string to dataframe
                                selected_data["UID"] = str(uid)
                                # Add to dataframe with all CV data
                                CV_df = pd.concat(
                                    [
                                        CV_df,
                                        selected_data,
                                    ],
                                    ignore_index=True,
                                )

                            print(f"    Finished concationation CV_df successfully")

                        ##########################################
                        # Plot Chronopotentiometry/Galvanostatic measurements (CP)
                        ##########################################
                        if "CP" in str(dset):
                            print(f"    Chronopotentiometry {str(dset)}")
                            fig = None

                            # Add names to columns in dataframe
                            data = set_column_headers_cp(data)

                            # Add column with ohmic corrected potential
                            data = correct_for_ohmic_resistance(
                                data, ohmic_resistance, OHMIC_CORRECTION
                            )
                            print("    Ohmic correction was applied")

                            # Prepare correct legend to plot
                            legend = set_legend_cp(dset)

                            # Add column with legend string to dataframe
                            print(f"    Legend: {legend}")
                            data["Scan current"] = legend

                            # Select data for times after 0 seconds
                            selected_data = data[data["Time [s]"] >= 0]
                            # print(f"    Selected data: {selected_data}")

                            # Add to dataframe with all CP data
                            # print(f"    CP_df: {CP_df}")
                            CP_df = pd.concat(
                                [
                                    CP_df,
                                    selected_data,
                                ],
                                ignore_index=True,
                            )
                            legend = None
                            print(f"    Finished concationation CP_df successfully")

                        ##########################################
                        # Plot Electrochemical Impedance Spectroscopy (EIS) measurements
                        ##########################################
                        if "EIS" in dset:
                            print(f"    EIS {str(dset)}")
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
                            # Drop data that is not needed
                            data = data.drop(
                                columns=[
                                    "Point",
                                    "Time [s]",
                                    "Zsig",
                                    "Zmod",
                                    "Zphz",
                                    "Idc",
                                    "Vdc",
                                    "IERange",
                                ]
                            )
                            data["Zimag [ohm]"] = -data["Zimag [ohm]"]

                            fig = px.scatter(
                                data,
                                x="Zreal [ohm]",
                                y="Zimag [ohm]",
                                title=f"EIS, sample {uid}, {str(dset)}",
                            )
                            # fig.show()

                        if fig is not None:
                            # Log plot to wandb.ai
                            print("    Uploading plot to wandb.ai")
                            run.log({f"{str(dset)}": fig})
                        fig = None

                        # Convert data to wandb table and upload to wandb.ai
                        print("    Uploading table to wandb.ai")
                        tbl = wandb.Table(dataframe=data)
                        run.log({f"{str(dset)}": tbl})

                    except Exception as e:
                        print(f"Couldn't open dataset {str(dset)} because of error {e}")
                        # Close connection to wandb.ai
                        wandb.finish()

                print(" ")
                print("Done with all datasets in group")

                try:
                    ##########################################
                    # Plot staircase CP measurements
                    ##########################################
                    print("Plotting staircase CP")
                    fig = px.line(
                        CP_df,
                        x="Time [s]",
                        y="Corrected potential (WE vs. RHE) [V]",
                        title=f"Staircase Chronopotentiometry, sample {uid}",
                        color="Scan current",
                        template="plotly_white",
                    )
                    # fig.show()

                    # Log plot to wandb.ai
                    print("Uploading to wandb.ai")
                    wandb.log({"CP staircase": fig})
                    fig = None

                except Exception as e:
                    print(f"Couldn't plot CP staircase because of error {e}")
                    # Close connection to wandb.ai
                    wandb.finish()

            except Exception as e:
                print("Couldn't open group", str(group), "because of error", e)
                # Close connection to wandb.ai
                wandb.finish()

        # Close connection to wandb.ai
        wandb.finish()

    ##########################################
    # Plot all CVs in one plot
    ##########################################
    plot_all_cv(CV_df)
    wandb.finish()
