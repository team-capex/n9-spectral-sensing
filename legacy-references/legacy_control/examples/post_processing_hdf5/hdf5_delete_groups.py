import h5py
# from control_lib.params import HDF5_FILE
# HDF5_FILE = data file, e.g. storedMeasurements.hdf5

# Dependent on which computer this is performed on, the path can be manually set:
HDF5_FILE = "/Users/nisfi/Sync_C9_measurements/storedMeasurements.hdf5"


def get_all(name: str) -> str():
    """Print function to show the content of the HDF5 file"""
    print(name)


groups_to_delete = [
    "1425_Cr0.1_Al0_Fe0.45_Co0.1_Mn0_Ni0.2_Cu0_Zn0.15",
    # "946_Cr0_Al0_Fe0_Co0_Mn0_Ni0.5_Cu0_Zn0.5",
    # "963_Cr0.0_Al0.0_Fe0.5_Co0.0_Mn0.0_Ni0.0_Cu0.5_Zn0.0",
    # "922_Cr0_Al0_Fe0_Co0_Mn0_Ni0.5_Cu0.5_Zn0",
    # "924_Cr0_Al0_Fe0_Co0_Mn0_Ni0.5_Cu0_Zn0.5",
    # "920_Cr0_Al0_Fe0_Co0_Mn0_Ni0.5_Cu0_Zn0.5",
    # "890_Cr0.6_Al0.0_Fe0.4_Co0.0_Mn0.0_Ni0.0_V0.0_FeCl0.0",
    # "891_Cr0.6_Al0.0_Fe0.4_Co0.0_Mn0.0_Ni0.0_V0.0_FeCl0.0",
    # "892_Cr0.6_Al0.0_Fe0.4_Co0.0_Mn0.0_Ni0.0_V0.0_FeCl0.0",
    # "901_Cr0.26_Al0.12_Fe0.18_Co0.1_Mn0.02_Ni0.16_V0.0_FeCl0.1",
    # "915_Cr0_Al1_Fe0_Co0_Mn0_Ni0_V0_FeCl0",
    # "918_Cr0_Al0_Fe0_Co0_Mn0_Ni1_V0_FeCl0",
    # "888_Cr0.8_Al0.0_Fe0.2_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "887_Cr0.45_Al0.0_Fe0.55_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "871_Cr0.25_Al0.0_Fe0.55_Co0.2_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "872_Cr0.25_Al0.0_Fe0.6_Co0.15_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "533_Cr0.05_Al0.05_Fe0.9_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "372_Cr0.5_Al0.0_Fe0.0_Co0.0_Mn0.5_Ni0.0_Cu0.0_Zn0.0",
    # "739_Cr0.125_Al0.125_Fe0.125_Co0.125_Mn0.125_Ni0.125_Cu0.125_Zn0.125",
    # "743_Cr0.0_Al0.5_Fe0.0_Co0.0_Mn0.5_Ni0.0_Cu0.0_Zn0.0",
    # "814_Cr0.032_Al0.283_Fe0.062_Co0.623_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "815_Cr0.35_Al0.18_Fe0.291_Co0.179_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "834_Cr0.25_Al0.25_Fe0.25_Co0.25_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "835_Cr0.25_Al0.25_Fe0.25_Co0.25_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "842_Cr0.25_Al0.25_Fe0.25_Co0.25_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "847_Cr0.25_Al0.25_Fe0.25_Co0.25_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "301_Cr0.0_Al0.0_Fe0.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "241_Cr0.0_Al0.0_Fe0.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "303_Cr0.0_Al0.0_Fe0.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "647_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "727_Cr0.0_Al0.0_Fe0.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn1.0",
    # "712_Cr0.0_Al0.5_Fe0.0_Co0.0_Mn0.5_Ni0.0_Cu0.0_Zn0.0",
    # "669_Cr0.5_Al0.0_Fe0.0_Co0.0_Mn0.0_Ni0.5_Cu0.0_Zn0.0",
    # "714_Cr0.0_Al0.0_Fe0.0_Co0.0_Mn1.0_Ni0.0_Cu0.0_Zn0.0",
    # "705_Cr0.0_Al0.5_Fe0.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.5",
    # "646_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "568_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "536_Cr0.1_Al0.1_Fe0.8_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "447_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "537_Cr0.15_Al0.15_Fe0.7_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "532_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "539_Cr0.25_Al0.25_Fe0.5_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "538_Cr0.2_Al0.2_Fe0.6_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "540_Cr0.3_Al0.3_Fe0.4_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "541_Cr0.35_Al0.35_Fe0.3_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "227_Cr0.0_Al0.0_Fe0.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "534_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "728_Cr0.0_Al0.5_Fe0.0_Co0.0_Mn0.5_Ni0.0_Cu0.0_Zn0.0",
    # "693_Cr0.0_Al0.0_Fe0.0_Co0.5_Mn0.0_Ni0.0_Cu0.5_Zn0.0",
    # "535_Cr0.05_Al0.05_Fe0.9_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "813_Cr0.032_Al0.283_Fe0.062_Co0.623_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "690_Cr0.0_Al0.5_Fe0.5_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "602_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "713_Cr0.0_Al1.0_Fe0.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "848_Cr0.375_Al0.125_Fe0.375_Co0.125_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "601_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "600_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "597_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "608_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "596_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "573_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "599_Cr0.0_Al0.0_Fe1.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "846_Cr0.25_Al0.25_Fe0.25_Co0.25_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "348_Cr0.0_Al0.0_Fe0.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
    # "326_Cr0.0_Al0.0_Fe0.0_Co0.0_Mn0.0_Ni0.0_Cu0.0_Zn0.0",
]

print(groups_to_delete)

with h5py.File(HDF5_FILE, "a") as f:
    print("***** Plotter program for HDF5 files *****")
    print("Content of HDF5 file", HDF5_FILE)
    print(" ")
    f.visit(get_all)
    print(" ")
    print(" ")
    print(" ")
    print(" ")
    # Loop through groups to plot all data
    for group in groups_to_delete:
        try:
            print("Deleting", group)
            del f[group]
        except:
            print("No dataset", group, "found")

    print("")
    print("")
    print("Done with deleting groups.")
    print("Now the file contains:")
    f.visit(get_all)
