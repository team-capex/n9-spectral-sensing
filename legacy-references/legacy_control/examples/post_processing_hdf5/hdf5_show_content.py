import h5py
import pandas as pd
import re
from control_lib.params import HDF5_FILE

# HDF5_FILE = "/Users/nisfi/Sync_C9_measurements/storedMeasurements.hdf5"


def set_column_headers_KeyParameters(data: pd.DataFrame) -> pd.DataFrame:
    """Set column headers for CV data

    Args:
        data (pd.DataFrame): Dataframe containing CV data in the order [Index, Time (s), Potential (WE vs. RHE) [V], Vu (V), Current [A],
        Vsig, Ach (V), IERange, Overbit1, Stop Test, Scan cycle, Temperature (C)]

    Returns:
        pd.DataFrame: Dataframe with new column headers
    """

    # Define the desired column names
    column_names = [
        "Unique ID",
        "Current [A]",
        "Raw potential [V]",
        "Corrected potential [V]",
        "Resistivity [ohm]",
    ]

    # Assign the new column names to the dataframe
    data.columns = column_names

    return data


with h5py.File(HDF5_FILE, "r") as f:
    print("Content of HDF5 file", HDF5_FILE)
    print(" ")

    # Print content of the file
    for group in f:
        if group == "keyParameters":
            break

        # Print group name
        print("")
        print(f"{group}")

        # Print chemical content of the group (floats only)
        input_str = str(group)
        parts = input_str.split("_")
        gruppe = parts[0]

        float_values = []
        for string in parts:
            match = re.match(r"[A-Za-z]+(\d+(\.\d+)?)", string)
            if match:
                float_value = float(match.group(1))
                float_values.append(float_value)

        # Print content in the format: "group, [float_values]"
        # print(f"{gruppe}, {float_values}")

        # Print content of the group
        for dset in f[group].keys():
            print(f"   {dset}")
            pass

    # Print content of keyParameters
    data = pd.DataFrame(f["keyParameters"])
    data = set_column_headers_KeyParameters(data)
    print("")
    print("keyParameters")
    print(data)
