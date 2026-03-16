import h5py
import numpy as np
from control_lib.params import HDF5_FILE

# HDF5_FILE = "/Users/nisfi/Sync_C9_measurements/storedMeasurements.hdf5"


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


list_normalized = []
list_groups = []
with h5py.File(HDF5_FILE, "r") as f:
    print("***** Renaming program for HDF5 files *****")
    print("Content of HDF5 file", HDF5_FILE)
    print(" ")
    print(" ")
    # f.visit(get_all)
    print(" ")
    print(" ")
    # Loop through groups to plot all data
    for group in f.keys():
        # Read group name to string
        group_name = str(group)
        if group_name == "keyParameters":
            break
        group_name_list = group_name.split("_")
        new_name = None
        a = search_list(group_name_list, "Chromium", True, "Cr")
        b = search_list(group_name_list, "Aluminium", True, "Al")
        c = search_list(group_name_list, "Iron", True, "Fe")
        d = search_list(group_name_list, "Manganese", True, "Mn")
        e = search_list(group_name_list, "Cr", False, "")
        f = search_list(group_name_list, "Al", False, "")
        g = search_list(group_name_list, "Fe", False, "")
        h = search_list(group_name_list, "Co", False, "")
        i = search_list(group_name_list, "Mn", False, "")
        j = search_list(group_name_list, "Ni", False, "")
        k = search_list(group_name_list, "Cu", False, "")
        ll = search_list(group_name_list, "Zn", False, "")

        # Chromium
        if a:
            new_name = group_name_list[0] + "_" + a
        elif e:
            new_name = group_name_list[0] + "_" + e
        else:
            new_name = group_name_list[0] + "_" + "Cr0.0"

        # Aluminium
        if b:
            new_name = new_name + "_" + b
        elif f:
            new_name = new_name + "_" + f
        else:
            new_name = new_name + "_" + "Al0.0"

        # Iron
        if c:
            new_name = new_name + "_" + c
        elif g:
            new_name = new_name + "_" + g
        else:
            new_name = new_name + "_" + "Fe0.0"

        # Cobalt
        if h:
            new_name = new_name + "_" + h
        else:
            new_name = new_name + "_" + "Co0.0"

        # Manganese
        if i:
            new_name = new_name + "_" + i
        elif d:
            new_name = new_name + "_" + d
        else:
            new_name = new_name + "_" + "Mn0.0"

        # Nickel
        if j:
            new_name = new_name + "_" + j
        else:
            new_name = new_name + "_" + "Ni0.0"

        # Copper
        if k:
            new_name = new_name + "_" + k
        else:
            new_name = new_name + "_" + "Cu0.0"

        # Zinc
        if ll:
            new_name = new_name + "_" + ll
        else:
            new_name = new_name + "_" + "Zn0.0"

        # Load all numbers to each element
        # print("new_name: ", new_name)
        new_name_list = new_name.split("_")
        chrome = ""
        aluminum = ""
        iron = ""
        cobolt = ""
        manganese = ""
        nickel = ""
        copper = ""
        zinc = ""
        try:
            for i in range(2, 7):
                chrome = chrome + new_name_list[1][i]
        except:
            pass
        try:
            for i in range(2, 7):
                aluminum = aluminum + new_name_list[2][i]
        except:
            pass
        try:
            for i in range(2, 7):
                iron = iron + new_name_list[3][i]
        except:
            pass
        try:
            for i in range(2, 7):
                cobolt = cobolt + new_name_list[4][i]
        except:
            pass
        try:
            for i in range(2, 7):
                manganese = manganese + new_name_list[5][i]
        except:
            pass
        try:
            for i in range(2, 7):
                nickel = nickel + new_name_list[6][i]
        except:
            pass
        try:
            for i in range(2, 7):
                copper = copper + new_name_list[7][i]
        except:
            pass
        try:
            for i in range(2, 7):
                zinc = zinc + new_name_list[8][i]
        except:
            pass

        chrome = float(chrome)
        aluminum = float(aluminum)
        iron = float(iron)
        cobolt = float(cobolt)
        manganese = float(manganese)
        nickel = float(nickel)
        copper = float(copper)
        zinc = float(zinc)

        # Normalize elements to sum to 1
        sum = chrome + aluminum + iron + cobolt + manganese + nickel + copper + zinc
        if sum == 0:
            sum = 1
        chrome_new_fraction = np.around(chrome / sum, 3)
        aluminum_new_fraction = np.around(aluminum / sum, 3)
        iron_new_fraction = np.around(iron / sum, 3)
        cobolt_new_fraction = np.around(cobolt / sum, 3)
        manganese_new_fraction = np.around(manganese / sum, 3)
        nickel_new_fraction = np.around(nickel / sum, 3)
        copper_new_fraction = np.around(copper / sum, 3)
        zinc_new_fraction = np.around(zinc / sum, 3)

        # print(
        #     "Cr: ",
        #     chrome_new_fraction,
        #     "Al: ",
        #     aluminum_new_fraction,
        #     "Fe: ",
        #     iron_new_fraction,
        #     "Co: ",
        #     cobolt_new_fraction,
        #     "Mn: ",
        #     manganese_new_fraction,
        #     "Ni: ",
        #     nickel_new_fraction,
        #     "Cu: ",
        #     copper_new_fraction,
        #     "Zn: ",
        #     zinc_new_fraction,
        # )

        new_name_normalized = (
            str(new_name_list[0])
            + "_"
            + "Cr"
            + str(chrome_new_fraction)
            + "_Al"
            + str(aluminum_new_fraction)
            + "_Fe"
            + str(iron_new_fraction)
            + "_Co"
            + str(cobolt_new_fraction)
            + "_Mn"
            + str(manganese_new_fraction)
            + "_Ni"
            + str(nickel_new_fraction)
            + "_Cu"
            + str(copper_new_fraction)
            + "_Zn"
            + str(zinc_new_fraction)
        )
        print("new_name_normalized: ", new_name_normalized)

        list_normalized.append(new_name_normalized)
        list_groups.append(group_name)

        # Rename group and delete old group if new_name is different
        # if new_name_normalized != group_name:
        #     print("Renaming group: ", group_name, " to: ", new_name_normalized)
        #     f[new_name_normalized] = f[group]
        #     del f[group]

    print("")
    print("")
    print("Done with renaming groups.")

# print("list_normalized: ", list_normalized)
# print("list_groups: ", list_groups)

for i in range(len(list_normalized)):
    if list_normalized[i] == list_groups[i]:
        pass
    else:
        print("Renaming group: ", list_groups[i], " to: ", list_normalized[i])
        with h5py.File(HDF5_FILE, "r+") as f:
            f[list_normalized[i]] = f[list_groups[i]]
            del f[list_groups[i]]
