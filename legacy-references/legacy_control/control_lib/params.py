__all__ = (
    "PUMP_INDICES",
    "ECELL_INDICES",
    "CAROUSEL_ANGLES",
    "VIAL_VOLUME",
    "ECELL_VOLUME",
    "OHMIC_CORRECTION_FACTOR",
    "DILUTION_CHEMICAL",
    "DILUTION_CHEMICAL_ECELL",
    "ARDUINO",
    "HDF5_FILE",
    "DATA_PATH",
    "VEL",
    "ACC",
    "NUMBER_OF_SAMPLES",
    "PUMP_VOLUMES",
    "PUMP_SPEEDS",
    "PUMP_CONCENTRATIONS",
    "PERISTALTIC_PUMP_INDICES",
    "PERISTALTIC_PUMP_CONST_A",
    "PERISTALTIC_PUMP_CONST_B",
)
# pump numbers corresponding to the liquids
PUMP_INDICES = {
    "Co": 0,
    "Mn": 1,
    "Cr": 2,
    "Al": 3,
    "Fe": 4,
    "Zn": 5,
    # "FeCl": 5,
    "Cu": 6,
    # "V": 6,
    "Ni": 7,
}
PUMP_VOLUMES = {  # From 1 to 12 ml
    "Co": 1.5,
    "Mn": 1.5,
    "Cr": 1.0,
    "Al": 1.0,
    "Fe": 1.0,
    "Zn": 1.0,
    # "FeCl": 1.0,
    "Ni": 1.0,
    "Cu": 1.0,
    # "V": 1.0,
}
PUMP_SPEEDS = {  # From 0 (fast) to 40 (slow)
    "Co": 10,
    "Mn": 10,
    "Cr": 10,
    "Al": 10,
    "Fe": 10,
    "Zn": 10,
    # "FeCl": 0,
    "Cu": 10,
    # "V": 0,
    "Ni": 10,
}
PUMP_CONCENTRATIONS = {  # molarity (mol/L)
    "KOH": 1,
    "Co": 0.4,
    "Mn": 0.4,
    "Cr": 0.4,
    "Al": 0.4,
    "Fe": 0.4,
    "Zn": 0.4,
    # "FeCl": 0.4,
    "Cu": 0.4,
    # "V": 0.4,
    "Ni": 0.4,
    "HCl": 1,
    "HCl_ECELL": 1,
    "NaOH": 2.5,
}
PERISTALTIC_PUMP_INDICES = {
    "Drain": 12,
    "KOH": 13,
    "H2O_ECELL": 14,
    "H2O": 15,
    "Air": 16,
    "H2O_suction": 18,
    "HCl_ECELL": 17,
    "HCl": 19,
    "NaOH": 20,
}
# To dispense correctly on peristaltic pumps, based on time
# prior measurements was done on how many ml the pumps dispensed
# over different runtimes. A linear fit was made.
# Based on y = ax + b  --> avg. ml = a * seconds + b
# --> ml = (y-b)/a
PERISTALTIC_PUMP_CONST_A = {
    "Drain": 2.2326,
    "KOH": 0.3363,
    "H2O_ECELL": 0.7518,
    "H2O": 0.6104,
    "Air": 0.6,  # Assumed
    "H2O_suction": 0.6,  # Assumed
    "HCl_ECELL": 0.3555,
    "HCl": 0.6,  # Assumed
    "NaOH": 0.4474,
}
PERISTALTIC_PUMP_CONST_B = {
    "Drain": 0,
    "KOH": 0.0626,
    "H2O_ECELL": -0.2341,
    "H2O": 0.0638,
    "Air": 0.1,  # Assumed
    "H2O_suction": 0.1,  # Assumed
    "HCl_ECELL": -0.0795,
    "HCl": 0.1,  # Assumed
    "NaOH": 0.0702,
}
# Connection numbers correspond to the ECELL
ECELL_INDICES = {"piston": 2, "drain_piston": 3, "ultrasound": 6}
CAROUSEL_ANGLES = {
    "Cr": 45,
    "Zn": 67.5,
    # "FeCl": 67.5,
    "Al": 90,
    "Mn": 112.5,
    "Fe": 135,
    "HCl": 157,
    "Air": 180,
    "H2O": 225,
    "Ni": 247.5,
    "Cu": 270,
    # "V": 270,
    "Co": 292.5,
    "NaOH": 315,
}
VIAL_VOLUME = 5.0  # mL
ECELL_VOLUME = 11.5  # mL
OHMIC_CORRECTION_FACTOR = 0.95  # %
DILUTION_CHEMICAL = "H2O"
DILUTION_CHEMICAL_ECELL = "H2O_ECELL"

ARDUINO = "COM5"  # Arduino Port on the computer
HDF5_FILE = "C:/Users/Robot-C9/Nextcloud/C9_robot/Measurements/nisfi/storedMeasurements.hdf5"
DATA_PATH = "C:/Users/Robot-C9/Nextcloud/C9_robot/Measurements/nisfi/"
VEL = 30000  # Velocity of the robotic arm (0-100.000)
ACC = 300000  # Acceleration of the robotic arm (0-500.000)
NUMBER_OF_SAMPLES = 71  # Number of samples in the sample rack
