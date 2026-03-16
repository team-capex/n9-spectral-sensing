import h5py
import pandas as pd
import numpy as np
import pickle
# from control_lib.params import HDF5_FILE, DATA_PATH

HDF5_FILE = "/Users/nisfi/Sync_C9_measurements/storedMeasurements.hdf5"
DATA_PATH = "/Users/nisfi/Sync_C9_measurements/"


list_of_sample_uids_to_store_in_dragonfly = [
    1293,
    1294,
    1295,
    1296,
    1297,
    1298,
    1299,
    1300,
    1301,
    1302,
    1303,
    1306,
    1307,
    1308,
    1309,
    1311,
    1312,
    1313,
    1314,
    1316,
    1317,
    1318,
    1319,
    1320,
    1321,
    1322,
    1323,
    1324,
    1325,
    1326,
    1327,
    1328,
    1329,
    1330,
    1331,
    1332,
    1333,
    1334,
    1335,
    1336,
    1337,
    1338,
    1339,
    1340,
    1341,
    1342,
    1343,
    1344,
    1345,
    1346,
    1347,
    1348,
    1349,
    1350,
    1351,
    1352,
    1353,
    1354,
    1355,
    1356,
    1357,
    1358,
    1369,
    1370,
    1374,
    1384,
    1388,
    1389,
    1393,
    1394,
    1405,
    1411,
    1415,
    1422,
    1423,
    1426,
    1427,
    1433,
    1434,
    1444,
    1452,
    1453,
    1456,
]


def get_all(name: str) -> str():
    """Print function to show the content of the HDF5 file"""
    print(name)


def get_chemical_formula_from_uid(uid: int) -> list:
    """
    Returns chemical formula from uid

    uid: int
        uid of sample
    """
    with h5py.File(HDF5_FILE, "r") as f:
        for group in f.keys():
            # Read group name to string
            group_name = str(group)
            if group_name == "keyParameters":
                break
            group_name_list = group_name.split("_")
            # print(f"Getting chemical formula for uid: {uid} and group name: {group_name}")
            if int(group_name_list[0]) == uid:
                print(f"Group name: {group_name_list}")
                # Load all numbers to each element
                # The order is important!
                chrome = ""
                aluminum = ""
                iron = ""
                cobolt = ""
                manganese = ""
                nickel = ""
                # copper = ""
                # zinc = ""
                vanadium = ""
                ironchloride = ""

                try:
                    for i in range(2, 7):
                        chrome = chrome + group_name_list[1][i]
                except Exception as e:
                    # print("Error in locating chrome composition: ", e)
                    pass
                try:
                    for i in range(2, 7):
                        aluminum = aluminum + group_name_list[2][i]
                except Exception as e:
                    # print("Error in locating aluminum composition: ", e)
                    pass
                try:
                    for i in range(2, 7):
                        iron = iron + group_name_list[3][i]
                except Exception as e:
                    # print("Error in locating iron composition: ", e)
                    pass
                try:
                    for i in range(2, 7):
                        cobolt = cobolt + group_name_list[4][i]
                except Exception as e:
                    # print("Error in locating cobolt composition: ", e)
                    pass
                try:
                    for i in range(2, 7):
                        manganese = manganese + group_name_list[5][i]
                except Exception as e:
                    # print("Error in locating manganese composition: ", e)
                    pass
                try:
                    for i in range(2, 7):
                        nickel = nickel + group_name_list[6][i]
                except Exception as e:
                    # print("Error in locating nickel composition: ", e)
                    pass
                try:
                    for i in range(2, 7):
                        # copper = copper + group_name_list[7][i]
                        vanadium = vanadium + group_name_list[7][i]
                except Exception as e:
                    # print("Error in locating copper composition: ", e)
                    pass
                try:
                    for i in range(2, 7):
                        # zinc = zinc + group_name_list[8][i]
                        ironchloride = ironchloride + group_name_list[8][i]
                except Exception as e:
                    # print("Error in locating zinc composition: ", e)
                    pass

                # Convert to floats
                chrome = float(chrome)
                aluminum = float(aluminum)
                iron = float(iron)
                cobolt = float(cobolt)
                manganese = float(manganese)
                nickel = float(nickel)
                # copper = float(copper)
                # zinc = float(zinc)
                vanadium = float(vanadium)
                ironchloride = float(ironchloride)

                chemical_formula = [
                    chrome,
                    aluminum,
                    iron,
                    cobolt,
                    manganese,
                    nickel,
                    # copper,
                    # zinc,
                    vanadium,
                    ironchloride,
                ]
                return chemical_formula
            else:
                pass


def make_dragonfly_save_file(input_data, filename, constraints):
    """
    Makes a pickl (.pkl) file in the right save file format for use in Dragonfly

    input_data: array
        array with results obtained previously
        [[x0, y0, z0, score0],
         [x1, y1, z1, score1]]
    filename: string
        The name you want for the save file
    constraints: array
        array with constraints for x ,y z,
        [[x_min, x_max],[y_min, y_max],[z_min, z_max]]
    """

    output = {}

    input_data0 = np.array(input_data.copy())

    for dims in range(len(constraints)):
        scale = constraints[dims][1] - constraints[dims][0]
        input_data0[:, dims] = input_data0[:, dims] / scale

    # print(input_data0)
    points_list = []
    config_points_list = []
    for data in input_data0:
        # print(data[:-1])
        points_list.append([np.array(data[:-1]).tolist()])
        config_points_list.append(np.array(data[:-1]).tolist())

    output["points"] = points_list
    true_vals = -input_data0[:, -1]
    output["true_vals"] = true_vals.tolist()
    output["vals"] = true_vals.tolist()
    output["config_points"] = config_points_list

    with open(filename, "wb") as handle:
        pickle.dump(output, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return


with h5py.File(HDF5_FILE, "r") as f:
    # Print content of keyParameters
    f.visit(get_all)
    data = pd.DataFrame(f["keyParameters"])
    data.columns = [
        "Uniqe ID",
        "Current [A]",
        "Raw potential [V]",
        "Corrected potential [V]",
        "Resistance [ohm]",
    ]
    print("Content of keyParameters table:")
    print(data)
    zipped_data = []
    uids_not_found = []
    for uid in list_of_sample_uids_to_store_in_dragonfly:
        print(" ")
        print(f"Processing sample no. {uid}")

        # Get chemical formula
        chemical_formula = get_chemical_formula_from_uid(uid)
        print(f"Chemical formula: {chemical_formula}")

        if chemical_formula is None:
            print(f"Chemical formula for uid: {uid} is None")
            uids_not_found.append(uid)
            continue
        else:
            # Get corrected potential
            corrected_potential = np.around(
                data.loc[data["Uniqe ID"] == uid, "Corrected potential [V]"].iloc[0], 3
            )
            print(f"Corrected potential: {corrected_potential}")

            # Save data in right format for Dragonfly
            zipped_data.append(
                [
                    chemical_formula[0],
                    chemical_formula[1],
                    chemical_formula[2],
                    chemical_formula[3],
                    chemical_formula[4],
                    chemical_formula[5],
                    chemical_formula[6],
                    chemical_formula[7],
                    corrected_potential,
                ],
            )
    print(" ")
    print(f"Zipped data: {zipped_data}")
    print(" ")
    if len(uids_not_found) > 0:
        print(
            f"Uids not found in HDF5 file, but listed in keyParameters. Please clean up!: {uids_not_found}"
        )
    # Save data to pickle file
    constrains = [[0, 1], [0, 1], [0, 1], [0, 1], [0, 1], [0, 1], [0, 1], [0, 1]]
    make_dragonfly_save_file(zipped_data, DATA_PATH + "dragonfly_progress.pkl", constrains)
    print(f"Data saved to {DATA_PATH + 'dragonfly_progress.pkl'}")
