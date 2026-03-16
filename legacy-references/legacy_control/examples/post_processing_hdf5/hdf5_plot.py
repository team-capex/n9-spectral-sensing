import pandas as pd
import matplotlib.pyplot as plt
import h5py
from datetime import datetime, date
import logging
import time
import sys
import numpy as np
import re
import plotly.express as px
from scipy.signal import savgol_filter
# from control_lib.params import HDF5_FILE

# Manually set the path to the HDF5 file:
HDF5_FILE = "/Users/nisfi/Sync_C9_measurements/storedMeasurements.hdf5"
DATA_PATH = "/Users/nisfi/Sync_C9_measurements/"

OHMIC_CORRECTION = 0.95


class hdf5_plot:

    def __init__(
        self,
        file_name: str,
        list_of_uids_to_plot: list = None,
        list_of_dataset_search_strings: list = None,
        plot_type: int = None,
        cycles_to_plot: list = None,
        title: str = "Title of the plot",
        smoothing_savitzky_golay: bool = False,
        savitzky_golay_window: int = 150,
        smoothing_mov_avg: bool = False,
        mov_avg_window: int = 7,
    ):
        """Initialize the hdf5_plot class

        Args:
            file_name (str): Name of the HDF5 file to plot
            list_of_uids_to_plot (list, optional): List of UIDs to plot. Defaults to None.
            list_of_dataset_search_strings (list, optional): List of dataset search strings. Defaults to None.
            plot_type (int, optional): Type of plot to make. Defaults to None. 1 = Cyclic Voltammetry, 2 = Chrono Potentiostatic, 4 = Overpotential
            cycles_to_plot (list, optional): List of cycles to plot. Defaults to None. 0 = all cycles
            title (str, optional): Title of the plot. Defaults to "Title of the plot".
            smoothing_savitzky_golay (bool, optional): Use Savitzky-Golay smoothing. Defaults to False.
            savitzky_golay_window (int, optional): Window size for Savitzky-Golay smoothing. Defaults to 150.
            smoothing_mov_avg (bool, optional): Use moving average smoothing. Defaults to False.
            mov_avg_window (int, optional): Window size for moving average smoothing. Defaults to 7.
        """

        logging.debug("Initializing hdf5_plot class")
        self.file_name = file_name
        self.datasets = dict()
        self.group_array = dict()
        self.plot_type = plot_type
        self.cycles_to_plot = cycles_to_plot
        self.title = title
        self.smoothing_savitzky_golay = smoothing_savitzky_golay
        self.smoothing_mov_avg = smoothing_mov_avg
        self.savitzky_golay_window = savitzky_golay_window
        self.mov_avg_window = mov_avg_window

        # Print content of HDF5 file
        self.load_HDF5_dataset_names()

        # Ask for a list of uids to plot
        self.set_uids_to_plot(list_of_uids_to_plot)

        # Load ohmic resistance for uids to plot
        self.load_keyParameters()

        # Check that al given uids exists in the HDF5 file and delete the ones that do not exist
        self._remove_uids()

        # Print content of chosen uids
        self._print_list_of_datasets_in_uids()

        # Ask for plot type
        self.set_plot_types(self.plot_type)

        if self.plot_type == 4:  # Overpotential plot
            # Plot overpotential
            self.plot_overpotential()
            self.make_list_with_potentials()
        else:
            # Set list of search strings in datasets to plot
            self.set_dataset_search_strings(list_of_dataset_search_strings)

            # Search for data on the chosen uids
            # and correct for ohmic resistance
            self.search(
                search_key_groups=self.list_of_uids_to_plot,
                search_key_dataset=self.list_of_dataset_search_strings,
            )

            if self.plot_type == 1:  # CV
                # Ask for which cycles to plot
                self.set_cycles_to_plot(self.cycles_to_plot)
                # Filter cycles to plot
                self._filter_cycles_to_plot()

                # Smooth data
                if self.smoothing_savitzky_golay is True:
                    for key, val in self.datasets.items():
                        self.datasets[key] = self.smooth_data_SavitzkyGolay(
                            val, window=self.savitzky_golay_window
                        )
                if self.smoothing_mov_avg is True:
                    for key, val in self.datasets.items():
                        self.datasets[key] = self.smooth_data_mov_avg(
                            val, window=self.mov_avg_window
                        )

                # Plot data
                self.plot_CV(
                    title=self.title,
                )

            elif self.plot_type == 2:  # CP
                # Smooth data
                if self.smoothing_savitzky_golay is True:
                    for key, val in self.datasets.items():
                        self.datasets[key] = self.smooth_data_SavitzkyGolay(
                            val, window=self.savitzky_golay_window
                        )
                if self.smoothing_mov_avg is True:
                    for key, val in self.datasets.items():
                        self.datasets[key] = self.smooth_data_mov_avg(
                            val, window=self.mov_avg_window
                        )

                # Plot data
                self.plot_CP(
                    title=self.title,
                )

            self.export_to_excel()
        self.store_metadata_to_excel()

    def make_list_with_potentials(self):
        # Make a pandas dataframe with the uids in self.list_of_uids_to_plot, the group name and the corrected potential from keyParameters
        df = pd.DataFrame()
        for uid in self.list_of_uids_to_plot:
            try:
                group = self.list_of_group_names[uid]
                # Remove "uid_" from the beginning of the group name
                group = group.replace(str(uid) + "_", "")
                potential = self.keyParameters.loc[
                    self.keyParameters["unique_id"] == uid, "overpotential_corr"
                ].values[0]
                new_row = pd.DataFrame(
                    {"UID": uid, "Group": group, "Potential": potential}, index=[0]
                )
                df = pd.concat([df, new_row], ignore_index=True)
            except Exception:
                pass

        # Save it to an Excel file without the index
        df.to_excel(DATA_PATH + "list_of_potentials.xlsx", index=False)

    def _filter_cycles_to_plot(self) -> None:
        """Filter dataframes to only include the cycles to plot"""

        for name, df in self.datasets.items():
            # Assuming df is your DataFrame containing the data
            if self.cycles_to_plot[0] == "All":
                logging.info("Plotting all cycles")
                break
            else:
                filtered_data = df[df["Scan cycle"].isin(self.cycles_to_plot)]
                self.datasets[name] = filtered_data

        logging.info(f"Filtered data to only include cycles {self.cycles_to_plot}")

    def set_cycles_to_plot(self, cycles_to_plot: list = None) -> None:
        """Ask for a list of cycles to plot"""
        logging.info("Asking for a list of cycles to plot")

        if cycles_to_plot is None:
            user_input = input("Enter cycles to plot, separated by comma (0 = all): ")

            # convert user input to list
            self.cycles_to_plot = user_input.split(",")

            # Convert user input to integers
            self.cycles_to_plot = [int(x) for x in self.cycles_to_plot]
        else:
            logging.info("List of cycles to plot is already set. Skipping user input.")
            self.cycles_to_plot = cycles_to_plot

        # If first element is 0, plot all cycles
        if self.cycles_to_plot[0] == 0:
            pass

        logging.info(f"List of cycles to plot: {self.cycles_to_plot}")

    def smooth_data_SavitzkyGolay(self, df: pd.DataFrame, window: int = 150) -> pd.DataFrame:
        """Smooth data using Savitzky-Golay filter

        Args:
            df (pd.DataFrame): Dataframe containing the data to smooth. Must contain a
            column named "Current [A]" and a column named "Potential (WE vs. RHE) [V]".
            window (int, optional): Window size for smoothing. Defaults to 7.

        Returns:
            pd.DataFrame: Dataframe with smoothed data
        """

        # Smooth data using Savitzky-Golay filter
        smoothed_current = savgol_filter(df["Current [A]"], window, 3)

        df["Current [A]"] = smoothed_current

        return df

    def smooth_data_mov_avg(self, df: pd.DataFrame, window: int = 7) -> pd.DataFrame:
        """Smooth data using Lowess smoothing

        Args:
            df (pd.DataFrame): Dataframe containing the data to smooth. Must contain a
            column named "Current [A]" and a column named "Potential (WE vs. RHE) [V]".
            frac (float, optional): Fraction of the data used for smoothing. Defaults to 0.1.

        Returns:
            pd.DataFrame: Dataframe with smoothed data
        """

        # Smooth data using moving average
        smoothed_current = df["Current [A]"].rolling(window=window).mean()

        df["Current [A]"] = smoothed_current

        return df

    def set_plot_types(self, plot_type: int = None) -> None:
        """Set list of plot types to plot
        1 = CV
        2 = CP
        3 = EIS
        4 = Overpotential
        5 = CP staircase
        """
        logging.info("Setting list of plot types to plot")

        if plot_type is None:
            print("Chose plot type to plot:")
            print("1 = CV")
            print("2 = CP")
            print("3 = EIS")
            print("4 = Overpotential")
            print("5 = CP staircase")

            user_input = input("Enter plot types to plot (integer): ")

            # convert user input to integer
            self.plot_type = int(user_input)

        else:
            logging.info("List of plot types to plot is already set. Skipping user input.")
            self.plot_type = plot_type

        logging.info(f"List of plot types to plot: {self.plot_type}")

    def load_keyParameters(self) -> None:
        """Load keyParameters table from HDF5 file

        Returns:
            pd.DataFrame: Dataframe containing keyParameters table
        """
        logging.debug(f"Opening HDF5 file: {self.file_name}")
        with h5py.File(self.file_name, "r") as f:
            dset = None
            dset = "keyParameters"
            # Load keyParameters table from HDF5 file
            data = f.get(dset)
            self.keyParameters = pd.DataFrame(
                data,
                columns=[
                    "unique_id",
                    "ampere",
                    "overpotential",
                    "overpotential_corr",
                    "ohmic_resistance",
                ],
            )
            # Change the column "unique_id" to integer
            self.keyParameters["unique_id"] = self.keyParameters["unique_id"].astype(int)

            logging.debug(f"KeyParameters: {self.keyParameters}")

    def _remove_uids(self) -> None:
        # Clean UID list and leave only valid ones found in keyParameters table
        valid_uids = [
            uid for uid in self.list_of_uids_to_plot if uid in self.keyParameters["unique_id"].values
        ]
        # Print removed UIDs
        removed_uids = [
            uid for uid in self.list_of_uids_to_plot if uid not in self.list_of_group_names
        ]
        if removed_uids:
            print("Removed UIDs:")
            print(f"{removed_uids}")

        self.list_of_uids_to_plot = valid_uids
        self.list_of_uids_to_plot.sort(reverse=False)

        # Print valid UIDs
        print("Valid UIDs:")
        print(f"{self.list_of_uids_to_plot}")

    def _print_list_of_datasets_in_uids(self) -> None:
        # Print content of list_of_datasets_in_uids line by line
        print("Content of chosen uids:")
        self.list_of_uids_to_plot.sort(reverse=False)
        for i in self.list_of_uids_to_plot:
            try:
                print(f"{self.list_of_group_names[i]}")
                for j in self.list_of_datasets_in_uids[i]:
                    print(f"    {j}")
            except Exception:
                pass

    def set_dataset_search_strings(self, list_of_dataset_search_strings: list = None) -> None:
        """Set list of search strings in datasets to plot"""
        logging.info("Setting list of search strings in datasets to plot")

        if list_of_dataset_search_strings is None:
            user_input = input(
                "Enter search strings in datasets to plot, separated by comma (eg. CV200mV, CP10, CP20): "
            )

            # convert user input to list
            self.list_of_dataset_search_strings = user_input.split(",")

        else:
            logging.info(
                "List of search strings in datasets to plot is already set. Skipping user input."
            )
            self.list_of_dataset_search_strings = list_of_dataset_search_strings

        logging.info(
            f"List of search strings in datasets to plot: {self.list_of_dataset_search_strings}"
        )

    def set_uids_to_plot(self, list_of_uids_to_plot: list) -> None:
        """Ask for a list of uids to plot"""
        logging.info("Asking for a list of groups and datasets to plot")

        if list_of_uids_to_plot is None:
            user_input = input("Enter uids to plot, separated by comma (0 = all): ")

            # convert user input to list
            self.list_of_uids_to_plot = user_input.split(",")

            # Convert user input to integers
            self.list_of_uids_to_plot = [int(x) for x in self.list_of_uids_to_plot]
        else:
            logging.info("List of uids to plot is already set. Skipping user input.")
            self.list_of_uids_to_plot = list_of_uids_to_plot

        # If first element is 0, plot all uids
        if self.list_of_uids_to_plot[0] == 0:
            self.list_of_uids_to_plot = self.list_of_uids

        logging.info(f"List of uids to plot: {self.list_of_uids_to_plot}")

    def _get_all(self, name: str) -> str():
        """Function to show the content of the HDF5 file"""
        self.group_array[name] = name

    def _get_number_from_string(self, dset: str, platinum_counter=0) -> int:
        """Find integer in the string dset for sorting order"""
        if "Pt" in dset:  # Special case for Pt that has no
            # leading number
            platinum_counter = platinum_counter + 1
            number_in_dset = 90 + platinum_counter
        else:  # Find integer of in the string dset
            number_in_dset = int(re.search(r"\d+", dset).group(0))

        return number_in_dset, platinum_counter

    def load_HDF5_dataset_names(self) -> None:
        # Print content of the file
        print("Content of HDF5 file", HDF5_FILE)
        print(" ")
        self.list_of_uids = []
        self.list_of_datasets_in_uids = dict()
        self.list_of_chemical_content = dict()
        self.list_of_group_names = dict()
        with h5py.File(HDF5_FILE, "r") as f:
            for group in f:
                if group == "keyParameters":
                    break

                # Print chemical content of the group (floats only)
                input_str = str(group)
                parts = input_str.split("_")

                # Make list of groups / uids
                uid = int(parts[0])
                self.list_of_uids.append(uid)

                float_values = []
                for string in parts:
                    match = re.match(r"[A-Za-z]+(\d+(\.\d+)?)", string)
                    if match:
                        float_value = float(match.group(1))
                        float_values.append(float_value)

                # Append to chemical contentlist
                self.list_of_chemical_content[uid] = float_values

                # Append to group name list as strings
                self.list_of_group_names[uid] = input_str

                # Make a temporary dictionary of datasets
                list_temporary = dict()

                # Make a counter for platinum scans
                platinum_counter = 0
                # Print content of the group
                for dset in f[group].keys():
                    dset = str(dset)

                    number_in_dset, platinum_counter = self._get_number_from_string(
                        dset, platinum_counter
                    )

                    # Append to temporary dictionary
                    list_temporary[number_in_dset] = str(dset)

                # Append the temporary dictionary to the dictionary of datasets
                list_temporary_sorted = dict(sorted(list_temporary.items()))

                # Convert list_temporary_sorted to a list
                list_temporary_sorted = list(list_temporary_sorted.values())
                self.list_of_datasets_in_uids[uid] = list_temporary_sorted

            # Print all UIDs
            print("")
            print("")
            print("Group UID's in HDF5 file")
            self.list_of_uids.sort(reverse=True)
            print(self.list_of_uids)

    def search(self, search_key_groups: list = None, search_key_dataset: list = None) -> None:
        """Search for a specific group and dataset within the HDF5 file

        args:
            search_key_groups: list of sample name search strings eg. [1215, 1216, ...]
            search_key_dataset: list of dataset search strings eg. ["0CV", "CP10", ...]
        """
        logging.info("Searching for groups and datasets within HDF5 file")
        if search_key_groups is None:
            search_key_groups = self.list_of_uids_to_plot

        if search_key_dataset is None:
            search_key_dataset = self.list_of_dataset_search_strings

        with h5py.File(self.file_name, "r") as f:
            # Loop through all values in search_key_groups
            for uid in search_key_groups:
                group = self.list_of_group_names[uid]
                logging.debug(f"Searching in {group}")

                # Loop through all values in search_key_dataset
                for search_key in search_key_dataset:
                    logging.debug(f"Searching for {search_key}")
                    for dset in f[group].keys():
                        dset_str = str(dset)
                        if search_key in dset_str:
                            logging.info(f"Dataset found: {dset_str}")
                            name = f"{group}/{dset_str}"
                            df = pd.DataFrame(f[group][dset][:])
                            df = self.set_column_headers(df, dset_str, uid)
                            self.datasets[name] = df

                        else:
                            logging.debug(f"Dataset {search_key} not found in {dset_str}")
                            pass

                    logging.debug(f"datasets: {self.datasets}")

    def set_column_headers_cv_pt(self, df: pd.DataFrame) -> pd.DataFrame:
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

        # Assign the new column names to the dataframe
        df.columns = column_names

        return df

    def set_column_headers_cv(self, df: pd.DataFrame) -> pd.DataFrame:
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

    def set_column_headers_eis(self, df: pd.DataFrame) -> pd.DataFrame:
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
        df.columns = column_names
        df["Zimag [ohm]"] = -df["Zimag [ohm]"]

        # Drop data that is not needed
        df = df.drop(
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

        return df

    def set_column_headers_cp(self, df: pd.DataFrame) -> pd.DataFrame:
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
        if len(df.columns) == 11:
            column_names.insert(0, "Index")

        # Set the column names of the dataframe
        df.columns = column_names

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
        df = df.drop(columns=columns_to_drop, errors="ignore")

        # Drop the "Index" column if it exists
        if "Index" in df.columns:
            df = df.drop(columns=["Index"])

        return df

    def set_column_headers(self, df: pd.DataFrame, dset: str, uid: int) -> pd.DataFrame:
        """Set column headers for the data

        Args:
            df (pd.DataFrame): Dataframe containing the data
            dset (str): Name of the dataset
            uid (int): Unique ID of the sample

        """

        logging.info("Setting column headers for the data")

        if "Pt_CV" in dset:
            # Set column headers and drop unnecessary columns
            df = self.set_column_headers_cv_pt(df)

        elif "CV" in dset:
            # Set column headers and drop unnecessary columns
            df = self.set_column_headers_cv(df)

            # Add column with ohmic corrected potential
            df = self.correct_for_ohmic_resistance(
                df,
                uid,
            )
        elif "CP" in dset:
            # Set column headers and drop unnecessary columns
            df = self.set_column_headers_cp(df)

            # Add column with ohmic corrected potential
            df = self.correct_for_ohmic_resistance(
                df,
                uid,
            )
        elif "EIS" in dset:
            # Set column headers and drop unnecessary columns
            df = self.set_column_headers_eis(df)
        elif "Pt" in dset:
            # Set column headers and drop unnecessary columns
            df = self.set_column_headers_cv(df)

            # Add column with ohmic corrected potential
            df = self.correct_for_ohmic_resistance(
                df,
                uid,
            )
        else:
            logging.warning("No column headers set for the data")
            pass

        return df

    def store_metadata_to_excel(self, file_name: str = "metadata.xlsx") -> None:
        """Get metadata from the HDF5 file for each uid in list_of_uids_to_plot
        and store it in an Excel file

        Args:
            file_name (str, optional): Name of the Excel file to store the metadata. Defaults to "metadata.xlsx".

        """
        self.df_metadata = pd.DataFrame()
        # Get attributes from each group in the HDF5 file
        with h5py.File(self.file_name, "r") as f:
            for uid in self.list_of_uids_to_plot:
                # If the UID doesn't exist in keyParameters table, skip it
                if uid not in self.keyParameters["unique_id"].values:
                    logging.warning(f"UID {uid} not found in keyParameters table. Skipping.")
                    continue
                else:
                    group = self.list_of_group_names[uid]
                    logging.info(f"Getting attributes from group: {group}")
                    date = None
                    mix_ratios = None
                    Sample_temperature_init = None
                    Sample_temperature_start = None
                    Sample_temperature_end = None
                    Room_temperature_aht20_init = None
                    Room_temperature_aht20_start = None
                    Room_temperature_aht20_end = None
                    Room_humidity_aht20_init = None
                    Room_humidity_aht20_start = None
                    Room_humidity_aht20_end = None
                    Room_atmospheric_pressure_init = None
                    Room_atmospheric_pressure_start = None
                    Room_atmospheric_pressure_end = None
                    rack_position_of_sample = None
                    oxide_remov_concentration = None
                    oxide_remov_chemical = None
                    oxide_remov_time = None
                    ultrasound_oxide_remov = None
                    ultrasound_cleaning = None
                    synthesis_1_time = None
                    oh_chemical = None
                    oh_concentration = None
                    oh_dip_time = None
                    synthesis_2_time = None
                    electrolyte_chemical = None
                    activation_time = None
                    cleaning_time = None
                    mix_concentration = None
                    platinum_peak_potential_fitted_r_squared_initial = None
                    platinum_peak_potential_fitted_r_squared_accepted = None
                    platinum_peak_potential_fitted_r_squared_after_tests = None
                    platinum_peak_potential_fitted_initial = None
                    platinum_peak_potential_fitted_accepted = None
                    platinum_peak_potential_fitted_after_tests = None
                    platinum_peak_potential_smoothed_accepted = None
                    platinum_peak_potential_smoothed_initial = None
                    platinum_peak_potential_smoothed_after_tests = None
                    reference_electrode_rest_time = None
                    pt_ohmic_resistance = None

                    for key, val in f[group].attrs.items():
                        logging.debug(f"{key}: {val}")

                        if key == "Date":
                            date = f[group].attrs[key]
                        if key == "mix_ratios":
                            mix_ratios = f[group].attrs[key]
                        if key == "Sample_temperature_init":
                            Sample_temperature_init = f[group].attrs[key]
                        if key == "Sample_temperature_start":
                            Sample_temperature_start = f[group].attrs[key]
                        if key == "Sample_temperature_end":
                            Sample_temperature_end = f[group].attrs[key]
                        if key == "Room_temperature_aht20_init":
                            Room_temperature_aht20_init = f[group].attrs[key]
                        if key == "Room_temperature_aht20_start":
                            Room_temperature_aht20_start = f[group].attrs[key]
                        if key == "Room_temperature_aht20_end":
                            Room_temperature_aht20_end = f[group].attrs[key]
                        if key == "Room_humidity_aht20_init":
                            Room_humidity_aht20_init = f[group].attrs[key]
                        if key == "Room_humidity_aht20_start":
                            Room_humidity_aht20_start = f[group].attrs[key]
                        if key == "Room_humidity_aht20_end":
                            Room_humidity_aht20_end = f[group].attrs[key]
                        if key == "Room_atmospheric_pressure_init":
                            Room_atmospheric_pressure_init = f[group].attrs[key]
                        if key == "Room_atmospheric_pressure_start":
                            Room_atmospheric_pressure_start = f[group].attrs[key]
                        if key == "Room_atmospheric_pressure_end":
                            Room_atmospheric_pressure_end = f[group].attrs[key]
                        if key == "rack_position_of_sample":
                            rack_position_of_sample = f[group].attrs[key]
                        if key == "oxide_remov_concentration":
                            oxide_remov_concentration = f[group].attrs[key]
                        if key == "oxide_remov_chemical":
                            oxide_remov_chemical = f[group].attrs[key]
                        if key == "oxide_remov_time":
                            oxide_remov_time = f[group].attrs[key]
                        if key == "ultrasound_oxide_remov":
                            ultrasound_oxide_remov = f[group].attrs[key]
                        if key == "ultrasound_cleaning":
                            ultrasound_cleaning = f[group].attrs[key]
                        if key == "synthesis_1_time":
                            synthesis_1_time = f[group].attrs[key]
                        if key == "oh_chemical":
                            oh_chemical = f[group].attrs[key]
                        if key == "oh_concentration":
                            oh_concentration = f[group].attrs[key]
                        if key == "oh_dip_time":
                            oh_dip_time = f[group].attrs[key]
                        if key == "synthesis_2_time":
                            synthesis_2_time = f[group].attrs[key]
                        if key == "electrolyte_chemical":
                            electrolyte_chemical = f[group].attrs[key]
                        if key == "activation_time":
                            activation_time = f[group].attrs[key]
                        if key == "cleaning_time":
                            cleaning_time = f[group].attrs[key]
                        if key == "mix_concentration":
                            mix_concentration = f[group].attrs[key]
                        if key == "platinum_peak_potential_fitted_r_squared_initial":
                            platinum_peak_potential_fitted_r_squared_initial = f[group].attrs[key]
                        if key == "platinum_peak_potential_fitted_r_squared_accepted":
                            platinum_peak_potential_fitted_r_squared_accepted = f[group].attrs[key]
                        if key == "platinum_r_squared_after_tests":
                            platinum_peak_potential_fitted_r_squared_after_tests = f[group].attrs[
                                key
                            ]
                        if key == "platinum_peak_potential_fitted_initial":
                            platinum_peak_potential_fitted_initial = f[group].attrs[key]
                        if key == "platinum_peak_potential_fitted_accepted":
                            platinum_peak_potential_fitted_accepted = f[group].attrs[key]
                        if key == "platinum_peak_potential_fitted_after_tests":
                            platinum_peak_potential_fitted_after_tests = f[group].attrs[key]
                        if key == "platinum_peak_potential_smoothed_accepted":
                            platinum_peak_potential_smoothed_accepted = f[group].attrs[key]
                        if key == "platinum_peak_potential_smoothed_initial":
                            platinum_peak_potential_smoothed_initial = f[group].attrs[key]
                        if key == "platinum_peak_potential_smoothed_after_tests":
                            platinum_peak_potential_smoothed_after_tests = f[group].attrs[key]
                        if key == "reference_electrode_rest_time":
                            reference_electrode_rest_time = f[group].attrs[key]
                        if key == "pt_ohmic_resistance":
                            pt_ohmic_resistance = f[group].attrs[key]

                    # Load the attributes from the keyParameters table
                    ampere = None
                    potential = None
                    potential_corr = None
                    ohmic_resistance = None
                    try:
                        ampere = float(
                            self.keyParameters.loc[
                                self.keyParameters["unique_id"] == uid, "ampere"
                            ].values
                        )
                        potential = float(
                            self.keyParameters.loc[
                                self.keyParameters["unique_id"] == uid, "overpotential"
                            ].values
                        )
                        potential_corr = float(
                            self.keyParameters.loc[
                                self.keyParameters["unique_id"] == uid, "overpotential_corr"
                            ].values
                        )
                        ohmic_resistance = float(
                            self.keyParameters.loc[
                                self.keyParameters["unique_id"] == uid, "ohmic_resistance"
                            ].values
                        )
                    except Exception:
                        logging.warning("No attributes found in keyParameters table")

                    # Append the attributes to the dataframe
                    metadata = {
                        "UID": uid,
                        "Date": date,
                        "mix_ratios": mix_ratios,
                        "Group_name": group,
                        "Current [A]": ampere,
                        "Potential [V]": potential,
                        "Potential_corr [V]": potential_corr,
                        "ohmic_resistance [ohm]": ohmic_resistance,
                        "Sample_temperature_init [C]": Sample_temperature_init,
                        "Sample_temperature_start [C]": Sample_temperature_start,
                        "Sample_temperature_end [C]": Sample_temperature_end,
                        "Room_temperature_aht20_init [C]": Room_temperature_aht20_init,
                        "Room_temperature_aht20_start [C]": Room_temperature_aht20_start,
                        "Room_temperature_aht20_end [C]": Room_temperature_aht20_end,
                        "Room_humidity_aht20_init [%]": Room_humidity_aht20_init,
                        "Room_humidity_aht20_start [%]": Room_humidity_aht20_start,
                        "Room_humidity_aht20_end [%]": Room_humidity_aht20_end,
                        "Room_atmospheric_pressure_init [Pa]": Room_atmospheric_pressure_init,
                        "Room_atmospheric_pressure_start [Pa]": Room_atmospheric_pressure_start,
                        "Room_atmospheric_pressure_end [Pa]": Room_atmospheric_pressure_end,
                        "rack_position_of_sample": rack_position_of_sample,
                        "oxide_remov_concentration [M]": oxide_remov_concentration,
                        "oxide_remov_chemical": oxide_remov_chemical,
                        "oxide_remov_time": oxide_remov_time,
                        "ultrasound_oxide_remov": ultrasound_oxide_remov,
                        "ultrasound_cleaning": ultrasound_cleaning,
                        "synthesis_1_time [s]": synthesis_1_time,
                        "oh_chemical": oh_chemical,
                        "oh_concentration [M]": oh_concentration,
                        "oh_dip_time [s]": oh_dip_time,
                        "synthesis_2_time [s]": synthesis_2_time,
                        "electrolyte_chemical": electrolyte_chemical,
                        "activation_time [s]": activation_time,
                        "cleaning_time [s]": cleaning_time,
                        "mix_concentration [M]": mix_concentration,
                        "reference_electrode_rest_time [s]": reference_electrode_rest_time,
                        "pt_ohmic_resistance": pt_ohmic_resistance,
                        "platinum_peak_potential_smoothed_initial [V]": platinum_peak_potential_smoothed_initial,
                        "platinum_peak_potential_smoothed_accepted [V]": platinum_peak_potential_smoothed_accepted,
                        "platinum_peak_potential_smoothed_after_tests [V]": platinum_peak_potential_smoothed_after_tests,
                        "platinum_peak_potential_fitted_r_squared_initial": platinum_peak_potential_fitted_r_squared_initial,
                        "platinum_peak_potential_fitted_r_squared_accepted": platinum_peak_potential_fitted_r_squared_accepted,
                        "platinum_peak_potential_fitted_r_squared_after_tests": platinum_peak_potential_fitted_r_squared_after_tests,
                        "platinum_peak_potential_fitted_initial [V]": platinum_peak_potential_fitted_initial,
                        "platinum_peak_potential_fitted_accepted [V]": platinum_peak_potential_fitted_accepted,
                        "platinum_peak_potential_fitted_after_tests [V]": platinum_peak_potential_fitted_after_tests,
                    }
                    new_row = pd.DataFrame(metadata, index=[0])
                    self.df_metadata = pd.concat([self.df_metadata, new_row], ignore_index=True)

        logging.debug(self.df_metadata)
        print(self.df_metadata)

        # Save metadata to Excel file
        self.df_metadata.to_excel(DATA_PATH + file_name)

    def export_to_excel(self, filename: str = "dataset.xlsx") -> None:
        """Export datasets to Excel file

        Args:
            file_name (str, optional): Name of the Excel file to store the data. Defaults to "data.xlsx".
        """
        logging.info("Exporting data to Excel file")

        # Loop through datasets and save them to Excel file
        for key, val in self.datasets.items():
            val = pd.DataFrame(val)
            filename = f"{key}.xlsx"
            # Replace / in filename with _
            filename = filename.replace("/", "_")
            logging.info(f"Saving Excel file {filename}")

            val.to_excel(DATA_PATH + filename, index=False)

    def correct_for_ohmic_resistance(
        self,
        df: pd.DataFrame,
        uid: int,
        ohmic_correction_factor: float = OHMIC_CORRECTION,
    ) -> pd.DataFrame:
        """Correct potential for ohmic resistance

        Args:
            df (pd.DataFrame): Dataframe containing the data to correct. Must contain a
            column named "Current [A]" and a column named "Potential (WE vs. RHE) [V]".
            ohmic_resistance (float): Ohmic resistance in ohm
            ohmic_correction_factor (float, optional): Correction factor for ohmic resistance.
            Defaults to 0.95.
            uid (int): Unique ID of the sample

        Returns:
            pd.DataFrame: Dataframe with corrected potential
        """
        # Load ohmic resistance from keyParameters table
        try:
            logging.debug("Trying to load ohmic resistance from keyParameters table")
            df_kp = self.keyParameters
            ohmic_resistance = df_kp.loc[df_kp["unique_id"] == uid, "ohmic_resistance"].values[0]
            logging.debug(f"ohmic_resistance: {ohmic_resistance}")
        except Exception:
            logging.warning("No ohmic resistance found in keyParameters table")
            ohmic_resistance = 0

        # Correct potential for ohmic resistance
        logging.info("Correcting potential for ohmic resistance")
        df["Corrected potential (WE vs. RHE) [V]"] = (
            df["Potential (WE vs. RHE) [V]"]
            - ohmic_correction_factor * ohmic_resistance * df["Current [A]"]
        )
        return df

    def load_ohmic_resistance(self, key: str) -> float:
        """Extracts ohmic resistance from the overpotential table

        Args:
            key (str): unique_ID of the sample
        """
        logging.info(f"Extracting ohmic resistance from overpotential table on sample {key}")
        # extract first digits in a string up until the symbol "_"
        unique_id = int("".join(filter(str.isdigit, str(key).split("_"))))
        row_num = self.keyParameters[self.keyParameters["unique_id"] == unique_id].index
        ohmic_resistance = self.keyParameters.loc[
            row_num[0],
            "ohmic_resistance",
        ]
        logging.info(f"Sample {unique_id} has ohmic resistance {ohmic_resistance} ohm")
        return ohmic_resistance

    def plot_CV(
        self,
        title="CV",
        xlabel="Voltage[V]",
        ylabel="Current [A]",
    ) -> None:
        """Generates plot of selected CV's. Remember to call search() first.

        Args:
            title (str, optional): Title of the plot. Defaults to "CV".
            xlabel (str, optional): X-axis legend on the plot. Defaults
            to "Voltage[V]".
            ylabel (str, optional): Y-axis legend on the plot. Defaults
            to "Current [A]".
        """
        logging.info("Plotting CV's")

        # Plot using plotly
        fig = px.scatter()
        for key, val in self.datasets.items():
            fig.add_scatter(
                x=val["Potential (WE vs. RHE) [V]"], y=val["Current [A]"], mode="lines", name=key
            )
        fig.update_layout(title=title, xaxis_title=xlabel, yaxis_title=ylabel)
        fig.update_traces(mode="lines+markers")
        fig.update_layout(
            font_family="Arial Black",
            font_color="grey",
            font_size=14,
            title_font_family="Arial Black",
            title_font_color="grey",
            title_font_size=20,
            legend_title_font_color="white",
            legend_title_font_family="Arial",
            legend_font_size=16,
            legend_font_family="Arial",
            legend_font_color="grey",
        )
        fig.update_layout(
            yaxis=dict(tickfont=dict(family="Arial", size=16, color="black")),
            xaxis=dict(tickfont=dict(family="Arial", size=16, color="black")),
            title_x=0.5,
        )
        fig.show()

    def plot_CP(
        self,
        title="CP",
        xlabel="Time [s]",
        ylabel="Voltage [V]",
        ohmic_corrected: bool = True,
        skip_data_before_seconds: float = 2,
        smooth_data: bool = False,
    ) -> None:
        """Generates plot of selected CP's. Remember to call search() first.

        Args:
            title (str, optional): Title of the plot. Defaults to "CP".
            xlabel (str, optional): X-axis legend on the plot. Defaults to "Time [s]".
            ylabel (str, optional): Y-axis legend on the plot. Defaults to "Voltage [V]".
            ohmic_corrected (bool, optional): If True, the overpotential is subtracted from the potential. Defaults to True.
        """
        logging.info("Plotting CP's")

        fig = px.line(title=title, labels={xlabel, ylabel})

        if ohmic_corrected:
            for key, val in self.datasets.items():
                # Due to measurement voltage drops, skip the first seconds of data
                val = self._ditch_first_seconds_CP_data(val, skip_data_before_seconds)
                # Make ohmic correction
                ohmic_resistance = self.load_ohmic_resistance(key)
                # Plot
                fig.add_scatter(
                    x=val["Time [s]"],
                    y=val["Potential (WE vs. RHE) [V]"] - val["Current [A]"] * ohmic_resistance,
                    name=key,
                )
        else:
            for key, val in self.datasets.items():
                # Due to measurement voltage drops, skip the first seconds of data
                val = self._ditch_first_seconds_CP_data(val, skip_data_before_seconds)
                # Plot
                fig.add_scatter(x=val["Time [s]"], y=val["Potential (WE vs. RHE) [V]"], name=key)

        fig.update_layout(title=title, xaxis_title=xlabel, yaxis_title=ylabel)
        fig.update_traces(mode="lines+markers")
        fig.update_layout(
            font_family="Arial Black",
            font_color="grey",
            font_size=14,
            title_font_family="Arial Black",
            title_font_color="grey",
            title_font_size=20,
            legend_title_font_color="white",
            legend_title_font_family="Arial",
            legend_font_size=16,
            legend_font_family="Arial",
            legend_font_color="grey",
        )
        fig.update_layout(
            yaxis=dict(tickfont=dict(family="Arial", size=16, color="black")),
            xaxis=dict(tickfont=dict(family="Arial", size=16, color="black")),
            title_x=0.5,
        )
        # figure_name = DATA_PATH + "CP " + str(date.today()) + ".html"
        fig.show()

    def plot_overpotential(
        self,
        title: str = "Potential",
        xlabel: str = "Sample ID",
        ylabel: str = "Potential [V]",
    ) -> None:
        """Generates plot of overpotential. Remember to call search() first.

        Args:
            title (str, optional): Title of the plot. Defaults
            to "Overpotential".
            xlabel (str, optional): X-axis legend on the plot. Defaults
            to "Sample ID".
            ylabel (str, optional): Y-axis legend on the plot. Defaults
            to "Overpotential [V]".
        """
        logging.info("Plotting overpotential")

        # Remove overpotential values where the overpotential is less than 0 (garbage data)
        logging.debug(f"Potentials before data scrubbing: {self.keyParameters}")
        logging.debug("Removing overpotential_corr smaller than 0,001 V")
        self.keyParameters = self.keyParameters[self.keyParameters["overpotential_corr"] > 0.001]
        logging.debug(f"Potential table after data scrubbing: {self.keyParameters}")

        for uid in self.list_of_uids_to_plot:
            overpotential_table_reduced = self.keyParameters[self.keyParameters["unique_id"] == uid]

            plt.scatter(
                overpotential_table_reduced["unique_id"],
                overpotential_table_reduced["overpotential_corr"],
            )

        plt.xlabel(xlabel, fontsize=12, fontweight="bold")
        plt.ylabel(ylabel, fontsize=12, fontweight="bold")
        plt.title(title, fontsize=16, fontweight="bold")
        # Change axis font size
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        figure_name = DATA_PATH + "Overpotential " + str(date.today()) + ".jpg"
        plt.savefig(figure_name, bbox_inches="tight")
        plt.show()

    def plot_CP_staircase(
        self,
        title="CP staircase",
        xlabel="Time [s]",
        ylabel="Voltage [V]",
        ohmic_corrected: bool = True,
        skip_data_before_seconds: float = 2,
    ) -> None:
        """Generates plot of selected CP's as a stair_case. Remember to
        call search() first.

        Args:
            title (str, optional): Title of the plot. Defaults to "CP".
            xlabel (str, optional): X-axis legend on the plot. Defaults
            to "Time [s]".
            ylabel (str, optional): Y-axis legend on the plot. Defaults
            to "Voltage [V]".
            ohmic_corrected (bool, optional): If True, the overpotential
            is subtracted from the potential. Defaults to True.
        """
        logging.info("Plotting CP staircase")
        data = None
        data = pd.DataFrame()
        data_to_plot = None
        data_to_plot = list()
        # Sort the datasets by voltage
        sorted_dict_means = self._sort_by_voltage()

        # groups are the unique_id's from search
        for groups in self.search_key_groups:
            logging.debug(f"groups: {groups}")
            data = None
            data = pd.DataFrame()
            first_run = True
            # key is the path/name of the dataset, val is the dataset
            for key, potential in sorted_dict_means.items():
                val = self.datasets[key]
                if groups in key:  # Merge datasets with the same unique_id
                    if ohmic_corrected:
                        logging.debug("Ohmic correction applied.")
                        try:
                            ohmic_resistance = self.load_ohmic_resistance(key)
                            val["potential_to_plot"] = val[2] - val[4] * ohmic_resistance
                        except Exception:
                            # No ohmic resistance found, passß
                            pass
                    else:
                        logging.debug("Ohmic correction not applied.")
                        val["potential_to_plot"] = val[2]

                    if first_run:
                        logging.debug("First run, preparing empty array to stack data on.")
                        # Due to measurement voltage drops, skip the first s
                        # econds of data
                        val = self._ditch_first_seconds_CP_data(val, skip_data_before_seconds)
                        # Append current dataset to extended dataset
                        # (see in else loop)
                        data = pd.DataFrame(val)
                        first_run = False
                    else:
                        logging.debug("Not first run, stacking to previous data.")
                        # Due to measurement voltage drops, skip the first
                        # seconds of data
                        val = self._ditch_first_seconds_CP_data(val, skip_data_before_seconds)
                        # Add the last time value of the previous dataset to
                        # the first value of the current dataset
                        val[1] = val[1] + data[1].iloc[-1]
                        val[0] = val[0] + data[0].iloc[-1]
                        # Append the current dataset to the previous dataset
                        data = pd.concat([data, val], ignore_index=True)

            data_to_plot = pd.concat([data_to_plot, data], ignore_index=True)

        list_with_legends = []
        fig = plt.figure()
        ax = plt.subplot(111)
        # Load color map
        n = len(self.search_key_groups)
        colors = plt.cm.jet(np.linspace(0, 1, n))

        i = 0
        for sub_data in data_to_plot:
            try:
                ax.plot(
                    sub_data[1],
                    sub_data["potential_to_plot"],
                    color=colors[i],
                )
                list_with_legends.append(self.search_key_groups[i])
            except Exception:
                pass
            i += 1
        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        box = ax.get_position()
        ax.set_position([box.x0, box.y0, box.width * 0.8, box.height])
        ax.legend(
            list_with_legends,
            loc="center left",
            bbox_to_anchor=(1, 0.5),
        )
        figure_name = DATA_PATH + "CP_staircase " + str(date.today()) + ".jpg"
        fig.savefig(figure_name, bbox_inches="tight")
        plt.show()

    def _ditch_first_seconds_CP_data(
        self, dataset: pd.DataFrame, skip_data_before_seconds: float = 2
    ):
        """Ditches the first seconds of data from the CP data. Remember to call
        search() first. Remember this only works on CP data."""

        dataset = dataset[dataset["Time [s]"] > skip_data_before_seconds]
        return dataset

    def _ditch_first_cycle_CV_data(self, dataset: pd.DataFrame):
        """Ditches the first cycle from the CV data. Remember to call
        search() first. Remember this only works on CV data.
        """
        dataset["min"] = dataset[2][
            (dataset[2].shift(1) > dataset[2]) & (dataset[2].shift(-1) > dataset[2])
        ]
        dataset["max"] = dataset[2][
            (dataset[2].shift(1) < dataset[2]) & (dataset[2].shift(-1) < dataset[2])
        ]
        try:
            second_cycle_index_row = (
                dataset["min"].iloc[[dataset["min"].first_valid_index()]].index[0]
            )
        except Exception:
            logging.warning(
                "Error when trying to ditch first cycle on dataset, maybe because there was only one cycle?"
            )
            second_cycle_index_row = 0

        return dataset, second_cycle_index_row

    def _sort_by_voltage(self) -> dict():
        """Sorts the datasets by mean potential. Remember to call search() first.

        Returns:
            sorted_array_means dict(): Sorted datasets by mean potential."""
        array_means = dict()
        for (
            key,
            val,
        ) in self.datasets.items():
            # Find means of datasets
            array_means[key] = val[2].mean()

        logging.debug(f"array_means: {array_means}")

        # Sort datasets by mean
        sorted_array_means = dict(sorted(array_means.items(), key=lambda x: x[1]))
        logging.debug(f"sorted_array_means: {sorted_array_means}")

        return sorted_array_means


# Initialize logging
time_now = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("hdf5_plot.log", mode="a"),
        logging.StreamHandler(sys.stdout),
    ],
)
start = time.time()
logging.info("\n\n\n\n")
logging.info("Starting hdf5_plot.py")

# plot_obj = hdf5_plot(file_name=FILE_NAME,
#                      list_of_uids_to_plot=[1239, 1244],
#                      list_of_dataset_search_strings=["Pt_CV_accepted"],
#                      plot_type=1,
#                      cycles_to_plot=[19],
#                      title="Pt vs Pt cyclic voltammetry before/after stabilisation",
#                      smoothing_savitzky_golay=True,
#                      savitzky_golay_window=150,
#                      )

# plot_obj = hdf5_plot(file_name=FILE_NAME,
#                      list_of_uids_to_plot=[1239, 1244],
#                      list_of_dataset_search_strings=["CV0.01"],
#                      plot_type=1,
#                      cycles_to_plot=[0],
#                      title="Pt vs Pt cyclic voltammetry before/after stabilisation",
#                      smoothing_mov_avg=True,
#                      mov_avg_window=5,
# )

# plot_obj = hdf5_plot(
#     file_name=HDF5_FILE,
#     list_of_uids_to_plot=[1251, 1255, 1258, 1260, 1261, 1262, 1263, 1265, 1266, 1267, 1268, 1269],
#     list_of_dataset_search_strings=["16CV"],
#     plot_type=1,
#     cycles_to_plot=["All"],
#     title="Latest grid search",
#     smoothing_mov_avg=False,
#     mov_avg_window=5,
# )

# Range of samples to plot
sample_list = []
# sample_list.append(int(983))
# sample_list.append(int(1004))
# sample_list.append(str(1206))
# sample_list.append(str(1215))
for i in range(305, 1009):
    sample_list.append(int(i))
for i in range(1194, 1400):
    sample_list.append(int(i))
logging.info(f"sample_list: {sample_list}")

### Make a plot of overpotential for specified interval in the HDF5 file
overpotential_plot = hdf5_plot(
    HDF5_FILE, list_of_uids_to_plot=sample_list, list_of_dataset_search_strings="CP10.", plot_type=4
)

### Make a CV plot of specified CV's in the HDF5 file
# cycles = []
# for i in range(0, 100):
#     cycles.append(i)

# cv_plot = hdf5_plot(
#     HDF5_FILE,
#     list_of_uids_to_plot=sample_list,
#     list_of_dataset_search_strings=["0CV", "1CV", "16CV", "17CV"],
#     cycles_to_plot=cycles,
#     smoothing_savitzky_golay=False,
#     plot_type=1,
#     title="Cyclic voltammetry ohmic corrected",
# )

# ## Make a CP plot of specified CP's in the HDF5 file
cp_plot = hdf5_plot(
    HDF5_FILE,
    list_of_uids_to_plot=sample_list,
    list_of_dataset_search_strings=["CP10.", "CP20.", "CP50."],
    plot_type=2,
    title="CP ohmic corrected",
)

# ## Make a CP staircase plot of specified CP's in the HDF5 file
# cp_staircase_plot = hdf5_plot(FILE_NAME)
# cp_staircase_plot.search(
#     sample_list,
#     [
#         "CP1.",
#         "CP2.",
#         "CP5.",
#         "CP10.",
#         "CP20.",
#         "CP50.",
#         "CP100.",
#         "CP200.",
#         "CP500.",
#     ],
# )
# cp_staircase_plot.plot_CP_staircase(
#     title="CP staircase ohmic corrected",
#     xlabel="Time [s]",
#     ylabel="Voltage [V]",
#     ohmic_corrected=True,
# )
