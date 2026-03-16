import h5py
import pandas as pd
# from control_lib.params import DATA_PATH, HDF5_FILE

# DATA_PATH = data folder with many files
# HDF5_FILE = data file, e.g. storedMeasurements.hdf5

# Dependent on which computer this is performed on, the path can be manually set:
HDF5_FILE = "/Users/nisfi/Sync_C9_measurements/storedMeasurements.hdf5"
DATA_PATH = "/Users/nisfi/Sync_C9_measurements/"

uids_to_delete = [
    1425,
    # 0,
    # 1,
    # 2,
    # 3,
    # 4,
    # 1134,
    # 1137,
    # 1138,
    # 1139,
    # 1140,
    # 1141,
    # 1142,
    # 1143,
    # 1144,
    # 1145,
    # 1146,
    # 1147,
    # 1148,
    # 1149,
    # 1150,
    # 1151,
    # 1152,
    # 1153,
    # 1154,
    # 1155,
    # 1156,
    # 1157,
    # 1158,
    # 1159,
    # 1160,
    # 1161,
    # 1162,
    # 1163,
    # 1164,
    # 1165,
    # 1166,
    # 1167,
    # 1168,
    # 1169,
    # 1170,
    # 1171,
    # 1172,
    # 1173,
    # 1174,
    # 1175,
    # 1176,
    # 1177,
    # 1178,
    # 1179,
    # 1180,
    # 1181,
    # 1182,
    # 1183,
    # 1184,
    # 1185,
    # 1186,
    # 1187,
    # 1188,
    # 1189,
    # 1190,
    # 1191,
    # 1192,
    # 1193,
    # 1279,
    # 1232,
    # 1233,
    # 1237,
    # 1239,
    # 1240,
    # 1244,
    # 1257,
    # 1109,
    # 1363,
    # 1360,
    # 739,
    # 0,
    # 920,
    # 922,
    # 924,
    # 946,
    # 963,
    # 890,
    # 891,
    # 892,
    # 901,
    # 915,
    # 918,
    # 888,
    # 887,
    # 739,
    # 743,
    # 814,
    # 815,
    # 834,
    # 835,
    # 842,
    # 847,
    # 751,
    # 752,
    # 753,
    # 754,
    # 755,
    # 756,
    # 758,
    # 759,
    # 760,
    # 761,
    # 762,
    # 763,
    # 764,
    # 765,
    # 766,
    # 767,
    # 769,
    # 770,
    # 772,
    # 773,
    # 774,
    # 775,
    # 776,
    # 777,
    # 778,
    # 779,
    # 780,
    # 781,
    # 782,
    # 783,
    # 784,
    # 785,
    # 786,
    # 787,
    # 788,
    # 789,
    # 790,
    # 791,
    # 793,
    # 794,
    # 795,
    # 796,
    # 797,
    # 798,
    # 800,
    # 801,
]

with h5py.File(HDF5_FILE, "a") as f:
    # Print content of keyParameters
    data = pd.DataFrame(f["keyParameters"])
    data.columns = [
        "Uniqe ID",
        "Current [A]",
        "Raw potential [V]",
        "Corrected potential [V]",
        "Resistance [ohm]",
    ]
    # Reset index counter, to start rows from 0
    data.reset_index(drop=True, inplace=True)

    print("Data before deletion:")
    print(data.to_markdown())

    # Delete rows with specified Uniqe ID
    for val in uids_to_delete:
        print(f"Deleting row with Uniqe ID: {val}")
        data.drop(data[data["Uniqe ID"] == val].index, inplace=True)

    # Reset index counter, to start rows from 0
    data.reset_index(drop=True, inplace=True)

    # Write to HDF5 file
    del f["keyParameters"]
    f.create_dataset("keyParameters", data=data)

print(" ")
print(" ")
# Confirm data content after deletion
with h5py.File(HDF5_FILE, "r") as f:
    data = pd.DataFrame(f["keyParameters"])
    data.columns = [
        "Uniqe ID",
        "Current [A]",
        "Raw potential [V]",
        "Corrected potential [V]",
        "Resistance [ohm]",
    ]
    print("Data after deletion:")
    print(data.to_markdown())
