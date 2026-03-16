"""
This script adds a new attribute "Status" to the group that contains the UID and sets it to "Failed".
It is done after the experiment has been completed and the data has been stored in the HDF5 file.
Visual inspection of the data and especially the samples is done to determine if the experiment was successful or not.
"""

import h5py
import re

HDF5_FILE = "/Users/nisfi/Sync_C9_measurements/storedMeasurements.hdf5"

list_of_uids = [
    1445,
    1446,
    1447,
    1448,
    1449,
    1450,
    1451,
    1455,
    1457,
]

# For each UID, add a new attribute "Status" to the group and set it to "Failed"
for uid in list_of_uids:
    with h5py.File(HDF5_FILE, "a") as f:
        print(f"Processing UID: {uid}")
        # Match the group name (a string with numbers, characters etc) that contains the UID (an integer)
        pattern = re.compile(f"{uid}_")

        # Find the group name that contains the UID
        group_name = [group for group in f.keys() if pattern.search(group)][0]

        # Check if the attribute "Status" already exists in the group
        if "Status" in f[group_name].attrs:
            print(f"Attribute 'Status' already exists in group '{group_name}'")
            print("Setting 'Status' to 'Failed'")
            f[group_name].attrs["Status"] = "Failed"
        else:
            print(f"Adding attribute 'Status' = Failed to group '{group_name}'")

            # Add the attribute "Status" to the group and set it to "Failed"
            f[group_name].attrs["Status"] = "Failed"
