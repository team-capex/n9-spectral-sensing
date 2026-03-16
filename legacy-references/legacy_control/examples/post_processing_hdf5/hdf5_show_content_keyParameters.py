import h5py
import pandas as pd
from control_lib.params import HDF5_FILE

# HDF5_FILE = "/Users/nisfi/Sync_C9_measurements/storedMeasurements.hdf5"


def get_all(name: str) -> str():
    """Print function to show the content of the HDF5 file"""
    print(name)


with h5py.File(HDF5_FILE, "r") as f:
    # Print content of keyParameters
    data = pd.DataFrame(f["keyParameters"])
    data.columns = [
        "Uniqe ID",
        "Current [A]",
        "Raw potential [V]",
        "Corrected potential [V]",
        "Resistance [ohm]",
    ]
    # Print all dataframe
    print(data.to_markdown())
