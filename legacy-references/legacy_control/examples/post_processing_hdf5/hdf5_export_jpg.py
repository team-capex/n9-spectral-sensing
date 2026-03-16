import matplotlib.pyplot as plt
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
        if group == "keyParameters":
            break
        try:
            # Loop through datasets
            for dset in f[group].keys():
                try:
                    print("")
                    print(group + "_" + dset)
                    print("--------------------------------------------------")
                    data = pd.DataFrame(f[group][dset][:])  # adding [:] returns a matrix
                    print(data)
                    filename_jpg = DATA_PATH + group + "_" + dset + ".jpg"
                    group_name = str(group)
                    uid = group_name.split("_")[0]

                    # TODO: Increase index by one after sample 569
                    if "CV" or "ECSA" in dset:
                        voltage = data[2]
                        ampere = data[4]
                        if int(uid) > 569:
                            voltage = data[3]
                            ampere = data[5]
                        plt.figure()
                        plt.title(group + "_" + dset)
                        plt.xlabel("Potential (WE vs. RHE) [V]")
                        plt.ylabel("Current [A]")
                        plt.plot(voltage, ampere)
                        plt.savefig(filename_jpg)
                        plt.close()
                    if "CP" in dset:
                        voltage = data[2]
                        ampere = data[4]
                        t = data[1]
                        if int(uid) > 569:
                            voltage = data[3]
                            ampere = data[5]
                            t = data[2]
                        plt.figure()
                        plt.title(group + "_" + dset)
                        plt.xlabel("Time [s]")
                        plt.ylabel("Voltage [V]")
                        plt.plot(t, voltage)
                        plt.savefig(filename_jpg)
                        plt.close()
                    if "EIS" in dset:
                        frequency = 1
                        resistance = 1
                        Zreal = data[3]
                        Zimag = -data[4]
                        if int(uid) > 569:
                            Zreal = data[4]
                            Zimag = -data[5]
                        plt.figure()
                        plt.title(group + "_" + dset)
                        plt.xlabel("Zreal [ohm]")
                        plt.ylabel("Zimag [ohm]")
                        plt.scatter(Zreal, Zimag)
                        plt.savefig(filename_jpg)
                        plt.close()

                except Exception as e:
                    print(f"Couldn't open dataset {dset} because of error {e}")
        except Exception:
            print("Couldn't open group", group)

        # Print samples recorded metadata
        text = ""
        for m in f[group].attrs:
            print(m, "=", f[group].attrs[m])
            text = text + m + "=" + str(f[group].attrs[m]) + "\n"
            print(" ")
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
    print(" ")
    print("Saving keyParameters to file ")
    print(df)

    # Save data to file
    filename_txt = dset + ".csv"
    df.to_csv(filename_txt, index=False, sep="\t", decimal=",")
