import h5py
import pandas as pd
import numpy as np
from control_lib.params import DATA_PATH, HDF5_FILE

# DATA_PATH = data folder with many files
# HDF5_FILE = data file, e.g. storedMeasurements.hdf5

# Dependent on which computer this is performed on, the path can be manually set:
# HDF5_FILE = "/Users/nisfi/Sync_C9_measurements/storedMeasurements.hdf5"
# DATA_PATH = "/Users/nisfi/Sync_C9_measurements/"


def get_all(name: str) -> str():
    """Print function to show the content of the HDF5 file"""
    print(name)


with h5py.File(HDF5_FILE, "r") as f:
    print("***** Plotter program for HDF5 files *****")
    print("Content of HDF5 file", HDF5_FILE)
    print(" ")
    f.visit(get_all)
    print(" ")
    print(" ")
    print(" ")
    print(" ")
    # Loop through groups to plot all data
    for group in f:
        try:
            # Loop through datasets
            for dset in f[group].keys():
                try:
                    print("")
                    print(group + "_" + dset)
                    print("--------------------------------------------------")
                    data = pd.DataFrame(f[group][dset][:])  # adding [:] returns a matrix

                    if "CV" or "ECSA" in dset:
                        data.rename(
                            columns={
                                0: "Time (s)",
                                1: "Vf (V vs Ref)",
                                2: "Vu (V)",
                                3: "Im (A)",
                                4: "Vsig",
                                5: "Ach (V)",
                                6: "IERange",
                                7: "Overbit1",
                                8: "Stop Test",
                                9: "Cycle",
                                10: "Temperature (C)",
                            },
                            inplace=True,
                        )
                    if "CP" in dset:
                        data.rename(
                            columns={
                                0: "Time (s)",
                                1: "Vf (V vs Ref)",
                                2: "Vu (V)",
                                3: "Im (A)",
                                4: "Charge Q",
                                5: "Vsig",
                                6: "Ach (V)",
                                7: "IERange",
                                8: "Overbit1",
                                9: "Stop Test",
                            },
                            inplace=True,
                        )
                    if "EIS" in dset:
                        pass

                    # Save data to file
                    filename_txt = DATA_PATH + group + "_" + dset + ".csv"
                    data.to_csv(
                        filename_txt,
                        index=False,
                        sep="\t",
                        decimal=",",
                    )
                except Exception:
                    print("Couldn't open dataset", dset)
        except Exception:
            print("Couldn't open group", group)

        # Print samples recorded metadata
        text = ""
        for m in f[group].attrs:
            print(m, "=", f[group].attrs[m])
            text = text + m + "=" + f[group].attrs[m] + "\n"
        with open(group + "_environmentalData.txt", "w") as output:
            output.write(text)

    dset = None
    dset = "keyParameters"
    # print(data)
    data = f.get(dset)
    data = np.array(data)
    df = pd.DataFrame(
        data,
        columns=[
            "unique_id",
            "ampere",
            "overpotential",
            "overpotential_corr",
            "ohmic_resistance",
        ],
    )

    # Save data to file
    filename_txt = DATA_PATH + dset + ".csv"
    df.to_csv(filename_txt, index=False, sep="\t", decimal=",")
