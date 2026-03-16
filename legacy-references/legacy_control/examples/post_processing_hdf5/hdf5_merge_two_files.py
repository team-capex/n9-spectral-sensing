import h5py
import numpy as np

DATA_PATH = "/Users/nisfi/Sync_C9_measurements/"

FIRST_FILE = DATA_PATH + "file1.hdf5"  # Numering continues from here
SECOND_FILE = DATA_PATH + "file2.hdf5"  # Numbering is overwritten
OUTPUT_FILE = DATA_PATH + "output.hdf5"  # New output file with merged data


def get_all(name: str) -> str():
    """Print function to show the content of the HDF5 file"""
    print(name)


def search_list(word_list: list, wanted: str, replace: bool, replacement: str) -> str:
    """Search for wanted string in list and replace it with replacement string"""
    result = list(filter(lambda x: wanted in x, word_list))
    if result:
        if replace is False:
            return str(result[0])
        else:
            return str(result[0]).replace(wanted, replacement)
    else:
        return ""


with h5py.File(FIRST_FILE, "r") as f1:
    print("***** Merging program for HDF5 files *****")
    # print("Content of HDF5 file", FIRST_FILE)
    print(" ")
    print(" ")
    # f1.visit(get_all)
    print(" ")
    print(" ")
    group_name_list_FIRST_FILE = []

    # Loop through groups to plot all data
    for group in f1.keys():
        # Read group name to string
        group_name = str(group)
        if group_name == "keyParameters":
            break
        group_name_list_FIRST_FILE.append(group_name)

    # Load lastSampleID from attribute in first file
    lastSampleID = f1.attrs["lastSampleID"]

    # Load second file
    with h5py.File(SECOND_FILE, "r") as f2:
        # print("Content of HDF5 file", SECOND_FILE)
        print(" ")
        print(" ")
        # f2.visit(get_all)
        print(" ")
        print(" ")
        group_name_list_SECOND_FILE = []
        group_name_list_SECOND_FILE_new_name = []
        new_sampleID = lastSampleID
        for group in f2.keys():
            # Read group name to string
            group_name = str(group)

            if group_name == "keyParameters":
                break

            group_name_list_SECOND_FILE_splitted = group_name.split("_")
            new_name = str(new_sampleID + 1)
            for elements in group_name_list_SECOND_FILE_splitted:
                # skip first element
                if elements == group_name_list_SECOND_FILE_splitted[0]:
                    continue
                else:
                    new_name = new_name + "_" + elements

            group_name_list_SECOND_FILE.append(group_name)
            group_name_list_SECOND_FILE_new_name.append(new_name)
            new_sampleID = new_sampleID + 1

        # Save lastSampleID attribute
        with h5py.File(OUTPUT_FILE, "w") as of:
            of.attrs["lastSampleID"] = new_sampleID

        for i in range(len(group_name_list_FIRST_FILE)):
            with h5py.File(OUTPUT_FILE, "r+") as of:
                # new_group = of.create_group(group_name_list_FIRST_FILE[i])
                group_path = f1[group_name_list_FIRST_FILE[i]].parent.name
                group_id = of.require_group(group_path)
                f1.copy(group_name_list_FIRST_FILE[i], group_id)

        list_old_UID = []
        list_new_UID = []
        for i in range(len(group_name_list_SECOND_FILE)):
            with h5py.File(OUTPUT_FILE, "r+") as of:
                group_path = f2[group_name_list_SECOND_FILE[i]].parent.name
                group_id = of.require_group(group_path)

                # TODO - fix this so that there isnt two layer of groups in the final file
                f2.copy(group_name_list_SECOND_FILE[i], group_id)
                print(
                    f"Copying {group_name_list_SECOND_FILE[i]} to {group_name_list_SECOND_FILE_new_name[i]}"
                )

                # Rename groups by copying them to new name
                of[group_name_list_SECOND_FILE_new_name[i]] = of[group_name_list_SECOND_FILE[i]]
                # Delete group that was renamed
                del of[group_name_list_SECOND_FILE[i]]

                old_group_name = str(group_name_list_SECOND_FILE[i])
                list_old_UID.append(old_group_name.split("_")[0])
                new_group_name = str(group_name_list_SECOND_FILE_new_name[i])
                list_new_UID.append(new_group_name.split("_")[0])

                # TODO - change attribute UID in new_group to new UID (latest addition to list_new_UID)
                of[group_name_list_SECOND_FILE_new_name[i]].attrs["UID"] = str(list_new_UID[-1])

        print(f"List of old UID: {list_old_UID}")
        print(f"List of new UID: {list_new_UID}")

        # Load keyParameters from first file
        keyParameters = f1["keyParameters"]
        keyParameters = keyParameters[:]

        # Load keyParameters from second file
        keyParameters2 = f2["keyParameters"]
        keyParameters2 = keyParameters2[:]

        # loop through the rows in keyParameters2 and add 1 to the first cell in the first column
        for i in range(len(keyParameters2)):
            if keyParameters2[i, 0] == 0:
                # keyParameters2[i, 0] = 1
                pass

            # Print index number of keyParameters2 in list_old_UID
            for k in range(len(list_old_UID)):
                if int(list_old_UID[k]) == int(keyParameters2[i, 0]):
                    print(
                        f"Found KeyParameters UID {int(keyParameters2[i, 0])} == list_old_UID {int(list_old_UID[k])}. New UID is {int(list_new_UID[k])}."
                    )
                    new_sampleID2 = list_new_UID[k]
                    keyParameters2[i, 0] = new_sampleID2
                else:
                    pass

        # Merge keyParameters
        keyParameters_merged = np.concatenate((keyParameters, keyParameters2), axis=0)

        # Save merged keyParameters to output file
        with h5py.File(OUTPUT_FILE, "r+") as of:
            of.create_dataset("keyParameters", data=keyParameters_merged)
