import pandas as pd
import matplotlib.pyplot as plt
import h5py
import logging
import numpy as np

__all__ = ("gamry_plot",)


class gamry_plot:
    def __init__(self, file_name: str):
        logging.info("")
        logging.info("")
        logging.debug("Initializing hdf5_plot class")
        self.file_name = file_name
        self.datasets = dict()
        self.group_array = dict()

        logging.debug(f"Opening HDF5 file: {self.file_name}")
        with h5py.File(self.file_name, "r") as f:
            dset = None
            dset = "keyParameters"
            data = f.get(dset)
            self.potential_table = pd.DataFrame(
                data,
                columns=[
                    "unique_id",
                    "ampere",
                    "potential",
                    "potential_corr",
                    "ohmic_resistance",
                ],
            )

    def _get_all(self, name: str) -> str():
        """Function to show the content of the HDF5 file"""
        self.group_array[name] = name

    def search(self, search_key_groups, search_key_dataset) -> None:
        """Search for a specific group and dataset within the HDF5 file

        args:
            search_key_groups: list of sample name search strings
            search_key_dataset: list of dataset search strings
        """
        logging.info("Searching for groups and datasets within HDF5 file")
        self.search_key_groups = search_key_groups
        with h5py.File(self.file_name, "r") as f:
            logging.debug(f"Loading content of HDF5 file {self.file_name}")
            f.visit(self._get_all)

            logging.debug("Searching within groups: ")
            logging.debug(f"{self.search_key_groups}")
            logging.debug("Searching within datasets containing: ")
            logging.debug(f"{search_key_dataset}")
            logging.debug("")
            logging.debug("Results:")
            logging.debug("_" * 50)

            for group in self.search_key_groups:
                res = [val for key, val in self.group_array.items() if group in key]
                for keys in res:
                    for dataset_search_string in search_key_dataset:
                        index_of_slash = keys.find(dataset_search_string)
                        if index_of_slash > 0:
                            logging.info("\t" + keys)
                            self.datasets[keys] = pd.DataFrame(f[keys][:])
                        else:
                            # Nothing found that matches search_key_dataset
                            pass
            logging.info("")

    def _get_ohmic_resistance(self, key: str) -> float:
        """Extracts ohmic resistance from the potential table

        Args:
            key (str): unique_ID of the sample
        """
        logging.info(f"Extracting ohmic resistance from potential table on sample {key}")
        # extract first digits in a string up until the symbol "_"
        unique_id = int("".join(filter(str.isdigit, str(key).split("_"))))
        row_num = self.potential_table[self.potential_table["unique_id"] == unique_id].index
        ohmic_resistance = self.potential_table.loc[
            row_num[0],
            "ohmic_resistance",
        ]
        logging.info(f"Sample {unique_id} has ohmic resistance {ohmic_resistance} ohm")
        return ohmic_resistance

    def plot_CV(
        self,
        select_subset_of_data: list[int],
        select_data: bool = False,
        title="CV",
        xlabel="Voltage[V]",
        ylabel="Current [A]",
        ohmic_corrected: bool = False,
        figure_name: str = "CV.jpg",
    ) -> None:
        """Generates plot of selected CV's. Remember to call search() first.

        Args:
            select_subset_of_data (list, optional): Follows Pandas Dataframe structure.
            If set, and select_data=True and ditch_first_cycle=False, the data is selected from
            the list, eg. row [-80:-1]. Defaults to None.
            select_data (bool): True means use the values in select_subset_of_data. Default is False.
            title (str, optional): Title of the plot. Defaults to "CV".
            xlabel (str, optional): X-axis legend on the plot. Defaults
            to "Voltage[V]".
            ylabel (str, optional): Y-axis legend on the plot. Defaults
            to "Current [A]".
            ohmic_corrected (bool, optional): If True, the ohmic potential
            is subtracted from the potential. Defaults to False.
        """
        logging.info("Plotting CV")
        list_with_legends = []
        fig = plt.figure()
        ax = plt.subplot(111)
        # Load color map
        n = len(self.datasets)
        colors = plt.cm.jet(np.linspace(0, 1, n))
        i = 0

        if select_data:
            logging.debug("Selecting data")
            for key in self.datasets:
                logging.info(
                    f"In dataset {key} selecting data row [{int(select_subset_of_data[0])}, {int(select_subset_of_data[1])}]",
                )
                self.datasets[key] = self.datasets[key].iloc[
                    int(select_subset_of_data[0]) : int(select_subset_of_data[1]), :
                ]
                logging.debug("Resetting index, so that it starts at 0")
                self.datasets[key].reset_index(level=None, drop=False)
                logging.debug(f"Dataset {key} contains {self.datasets[key]}")
        if ohmic_corrected:  # Correct for ohmic resistance
            logging.debug("Ohmic correction chosen")
            for key, val in self.datasets.items():
                try:
                    ohmic_resistance = self._get_ohmic_resistance(key)
                    ax.plot(
                        val[1] - val[3] * ohmic_resistance,
                        val[3],
                        color=colors[i],
                    )
                    list_with_legends.append(key)
                    i += 1
                except Exception:  # No ohmic resistance found
                    logging.warning("Entered Exception - we should not be here")
                    logging.exception("message")
                    for key, val in self.datasets.items():
                        ax.plot(val[1], val[3], color=colors[i])
                        list_with_legends.append(key)
                        i += 1
        else:  # Don't correct for ohmic resistance
            for key, val in self.datasets.items():
                logging.debug("No ohmic correction chosen")
                ax.plot(val[1], val[3], color=colors[i])
                list_with_legends.append(key)
                i += 1

        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        box = ax.get_position()
        ax.set_position([box.x0, box.y0, box.width * 0.8, box.height])
        ax.legend(list_with_legends, loc="center left", bbox_to_anchor=(1, 0.5))
        fig.savefig(figure_name, bbox_inches="tight")
        plt.close()

    def plot_CP(
        self,
        select_subset_of_data: list[int],
        select_data: bool = False,
        title="CP",
        xlabel="Time [s]",
        ylabel="Voltage [V]",
        ohmic_corrected: bool = True,
        skip_data_before_seconds: float = 2,
        figure_name: str = "CP.jpg",
    ) -> None:
        """Generates plot of selected CP's. Remember to call search() first.

        Args:
            select_subset_of_data (list, optional): Follows Pandas Dataframe structure.
            If set, and select_data=True and ditch_first_cycle=False, the data is
            selected from the list, eg. row [-80:-1]. Defaults to None.
            select_data (bool): True means use the values in select_subset_of_data. Default is False.
            title (str, optional): Title of the plot. Defaults to "CP".
            xlabel (str, optional): X-axis legend on the plot. Defaults
            to "Time [s]".
            ylabel (str, optional): Y-axis legend on the plot. Defaults
            to "Voltage [V]".
            ohmic_corrected (bool, optional): If True, the ohmic potential
            is subtracted from the potential. Defaults to True.
            skip_data_before_seconds (float, optional): Skips the first
            seconds of data. Defaults to 2.
            figure_name (str, optional): Name of the figure. Defaults to
            "CP.jpg".
        """
        logging.info("Plotting CP's")
        list_with_legends = []
        fig = plt.figure()
        ax = plt.subplot(111)
        # Load color map
        n = len(self.datasets)
        colors = plt.cm.jet(np.linspace(0, 1, n))
        i = 0

        if select_data:
            logging.debug("Selecting data")
            for key in self.datasets:
                logging.info(
                    f"In dataset {key} selecting data row [{int(select_subset_of_data[0])}, {int(select_subset_of_data[1])}]",
                )
                self.datasets[key] = self.datasets[key].iloc[
                    int(select_subset_of_data[0]) : int(select_subset_of_data[1]), :
                ]
                logging.debug("Resetting index, so that it starts at 0")
                self.datasets[key].reset_index(level=None, drop=False)
                logging.debug(f"Dataset {key} contains {self.datasets[key]}")
        if ohmic_corrected:  # Correct for ohmic resistance
            for key, val in self.datasets.items():
                # Make ohmic correction
                ohmic_resistance = self._get_ohmic_resistance(key)
                # Plot
                ax.plot(val[0], val[1] - val[3] * ohmic_resistance, color=colors[i])
                list_with_legends.append(key)
                i += 1
        else:  # Don't correct for ohmic resistance
            for key, val in self.datasets.items():
                # Plot
                ax.plot(val[0], val[1], color=colors[i])
                list_with_legends.append(key)
                i += 1

        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        box = ax.get_position()
        ax.set_position([box.x0, box.y0, box.width * 0.8, box.height])
        ax.legend(list_with_legends, loc="center left", bbox_to_anchor=(1, 0.5))
        fig.savefig(figure_name, bbox_inches="tight")
        plt.close()

    def plot_EIS(
        self,
        title="EIS",
        xlabel="Zreal [ohm]",
        ylabel="Zimag [ohm]",
        figure_name: str = "EIS.jpg",
    ) -> None:
        """Plots the EIS measurement.

        Args:
            title (str, optional): Title of the plot. Defaults to "EIS".
            xlabel (str, optional): X-axis legend on the plot. Defaults
            to "Zreal [ohm]".
            ylabel (str, optional): Y-axis legend on the plot. Defaults
            to "Zimag [ohm]".
            figure_name (str, optional): Name of the figure. Defaults to
            "EIS.jpg".
        """

        logging.info("Plotting EIS")
        list_with_legends = []
        fig = plt.figure()
        ax = plt.subplot(111)
        # Load color map
        n = len(self.datasets)
        colors = plt.cm.jet(np.linspace(0, 1, n))
        i = 0

        # XXX REMOVE THIS TRY IF IT WORKS
        try:
            for key, val in self.datasets.items():
                logging.debug(f"Plotting EIS for dataset {key}")
                ax.scatter(val[3], np.abs(val[4]), color=colors[i])
                list_with_legends.append(key)
                i += 1

            plt.title(title)
            plt.xlabel(xlabel)
            plt.ylabel(ylabel)
            box = ax.get_position()
            ax.set_position([box.x0, box.y0, box.width * 0.8, box.height])
            ax.legend(list_with_legends, loc="center left", bbox_to_anchor=(1, 0.5))
            fig.savefig(figure_name, bbox_inches="tight")
            plt.close()
        except Exception as e:
            logging.warning("Entered Exception - we should not be here")
            logging.warning(f"Error: {e}")
            logging.exception("message")

    def plot_overpotential(
        self,
        title: str = "Corrected Potential at 10 mA",
        xlabel: str = "Sample ID",
        ylabel: str = "Corrected potential [V]",
        corrected_overpotential: bool = True,
        sample_range: list = [5, 10000],
        figure_name: str = "Potential.jpg",
    ) -> None:
        """Generates plot of Potential. Remember to call search() first.

        Args:
            title (str, optional): Title of the plot. Defaults
            to "Corrected Potential at 10 mA".
            xlabel (str, optional): X-axis legend on the plot. Defaults
            to "Sample ID".
            ylabel (str, optional): Y-axis legend on the plot. Defaults
            to "Corrected Potential [V]".
            corrected_overpotential (bool, optional): If True, the
            ohmic potential is subtracted from the raw potential. Defaults to True.
            sample_range (list, optional): Range of samples to be plotted.
            This is the number in the array and not the sample unique ID.
            Defaults to [5, 10000].
            figure_name (str, optional): Name of the figure. Defaults to
            "Potential.jpg".
        """
        logging.info("Plotting potentials")
        fig = plt.figure()

        # Remove overpotential values where the overpotential is less than 0 (garbage data)
        logging.debug(f"overpotential_table before data scrubbing: {self.potential_table}")
        logging.debug("Removing overpotential_corr smaller than 0,001 V")
        self.potential_table = self.potential_table[self.potential_table["potential_corr"] > 0.001]
        logging.debug(f"overpotential_table after data scrubbing: {self.potential_table}")

        # Check if overpotential is corrected
        if corrected_overpotential:
            overpotential_table_reduced = self.potential_table.iloc[
                sample_range[0] : sample_range[1], :
            ]
            plt.scatter(
                overpotential_table_reduced["unique_id"],
                overpotential_table_reduced["potential_corr"],
            )
        else:
            overpotential_table_reduced = self.potential_table.iloc[
                sample_range[0] : sample_range[1],
                :,
            ]
            plt.scatter(
                overpotential_table_reduced["unique_id"],
                overpotential_table_reduced["potential"],
            )

        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        fig.savefig(figure_name, bbox_inches="tight")
        plt.close()

    def plot_CP_staircase(
        self,
        select_subset_of_data: list = [int],
        select_data: bool = False,
        title="CP staircase",
        xlabel="Time [s]",
        ylabel="Voltage [V]",
        ohmic_corrected: bool = True,
        skip_data_before_seconds: float = 2,
        figure_name: str = "CP_staircase.jpg",
    ) -> None:
        """Generates plot of selected CP's as a stair_case. Remember to
        call search() first.

        Args:
            select_subset_of_data (list, optional): Select a subset of
            the data. Defaults to [int].
            select_data (bool, optional): If True, the data is selected.
            Defaults to False.
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
                    if select_data:  # Select a subset of the data
                        logging.debug("Selecting data")
                        for key in self.datasets:
                            logging.info(
                                f"In dataset {key} selecting data row [{int(select_subset_of_data[0])}, {int(select_subset_of_data[1])}]",
                            )
                            self.datasets[key] = self.datasets[key].iloc[
                                int(select_subset_of_data[0]) : int(select_subset_of_data[1]), :
                            ]
                            logging.debug("Resetting index, so that it starts at 0")
                            self.datasets[key].reset_index(level=None, drop=False)
                            logging.debug(f"Dataset {key} contains {self.datasets[key]}")

                    if ohmic_corrected:  # Subtract ohmic resistance
                        logging.debug("Ohmic correction applied.")
                        try:
                            ohmic_resistance = self._get_ohmic_resistance(key)
                            val["potential_to_plot"] = val[1] - val[3] * ohmic_resistance
                        except Exception:
                            # No ohmic resistance found, passß
                            pass
                    else:
                        logging.debug("Ohmic correction not applied.")
                        val["potential_to_plot"] = val[1]

                    if first_run:
                        logging.debug("First run, preparing empty array to stack data on.")
                        # Append current dataset to extended dataset
                        # (see in else loop)
                        data = pd.DataFrame(val)
                        first_run = False
                    else:
                        logging.debug("Not first run, stacking to previous data.")
                        # Add the last time value of the previous dataset to
                        # the first value of the current dataset
                        val[1] = val[1] + data[1].iloc[-1]
                        val[0] = val[0] + data[0].iloc[-1]
                        # Append the current dataset to the previous dataset
                        data = pd.concat([data, val], ignore_index=True)

            data_to_plot.append(data)

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
        fig.savefig(figure_name, bbox_inches="tight")
        plt.close()

    def _ditch_first_seconds_CP_data(
        self, dataset: pd.DataFrame, skip_data_before_seconds: float = 2
    ):
        """Ditches the first seconds of data from the CP data. Remember to call
        search() first. Remember this only works on CP data."""

        dataset = dataset[dataset[1] > skip_data_before_seconds]
        return dataset

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
