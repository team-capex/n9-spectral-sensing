"""Workflow for the experiment"""

import logging
import time
import h5py
from pathlib import Path
from contextlib import contextmanager
import numpy as np
import pandas as pd
import serial
import serial.tools.list_ports
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from north_c9 import NorthC9
from controller import C9Controller
from gamry import recipe
from params import (
    PUMP_INDICES,
    CAROUSEL_ANGLES,
    PUMP_VOLUMES,
    VIAL_VOLUME,
    DILUTION_CHEMICAL,
    DILUTION_CHEMICAL_ECELL,
    PUMP_CONCENTRATIONS,
    ECELL_VOLUME,
    ECELL_INDICES,
    HDF5_FILE,
    DATA_PATH,
    VEL,
    ACC,
    PERISTALTIC_PUMP_INDICES,
    NUMBER_OF_SAMPLES,
    ARDUINO,
)
from recipes import (
    electrochemical_measurements,
    get_reference_electrode_potential,
    check_for_reference_electrode_drift,
)
from measurements import (
    run_EIS_and_save_data,
)
from tools import (
    ConcentrationConverter as CC,
)
from locator import (
    VIAL_CLAMP,
    CAP_HOLDER_OFF_POS,
    CAP_HOLDER_ON_POS,
    VIAL_CLAMP_CAP_POS,
    vial_rack,
    DIPPING_POS,
    SAMPLE_TEST_POS,
    SAMPLE_INSERT_POS,
    HOME,
)

__all__ = ("timer", "Experiment")

@contextmanager
def timer():
    """log execution time of a measurement"""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        logging.info(f"Execution time: {duration:.2f} s.")


class Experiment:
    def __init__(self):
        logging.debug("Initialized new instance of Experiment class")
        self.c9 = NorthC9(
            "A",
            network_serial="FT5SJ5LG",
            experiment_log=True,
        )  # create a controller object with address A
        self.start_time = time.time()
        self.controller = C9Controller(
            self.c9, start_time=self.start_time, velocity=VEL, acceleration=ACC
        )
        self.pump_indices = list(PUMP_INDICES.values())
        self.set_pump_volumes(PUMP_VOLUMES, PUMP_INDICES)

    def set_pump_volumes(
        self, pump_volumes: dict = PUMP_VOLUMES, pump_indices: dict = PUMP_INDICES
    ) -> None:
        """Set the pump volumes of the pumps provided in the dictionaries

        Args:
            pump_volumes(dict): With values from 0 to 12 ml in the form of: {"H2O": 12}
            pump_indices (dict): List of attached pumps and position numbers
            in the form: {"H2O": 0} .... {"H2O": 9}
        """

        for key, volume in pump_volumes.items():
            self.controller.c9.pumps[pump_indices[key]]["volume"] = volume

    def set_experiment_parameters(
        self,
        chemical_ratios: list,
        oxide_remov_time: int = 60,  # seconds
        oxide_remov_chemical: str = "HCl_ECELL",
        oxide_remov_concentration: float = 1,  # mol/L
        synth1_time: int = 600 - (64 + 3),  # 600 seconds - 64s for vial cleaning, 3s for movements
        synth2_time: int = 300 - (64 + 3),  # 300 seconds - 64s for vial cleaning, 3s for movements
        oh_dip_time: int = 10,
        oh_chemical: str = "NaOH",
        oh_concentration: float = 2.5,
        cleaning_time: int = 10,
        activation_time: int = 1,
        electrolyte_chemical: str = "KOH",
        electrolyte_concentration: float = 1,
        ultrasound_oxide_remov: bool = True,
        ultrasound_cleaning: bool = True,
        ultrasound_during_experiment: bool = False,
        threshold_max_tries_per_sample: int = 3,
        threshold_lowest_accepted_potential: float = 1.229,  # Volt
        threshold_highest_accepted_potential: float = 2.5,  # Volt
        threshold_lowest_accepted_resistance: float = 0,  # Ohm
        threshold_highest_accepted_resistance: float = 1.5,  # ohm
        mix_concentration: float = 0.4,  # mol/L
        acceptance_avg_pt_potential: float = 0.809,  # V
        acceptance_lower_limit_pt_pot: float = 0.804,  # V
        acceptance_upper_limit_pt_pot: float = 0.820,  # V
        mail_recipents: list = ["nis@dosan.dk"],
        no_chemicals: bool = False,
    ):
        """Set experiment parameters.

        Args:
            chemical_ratios (list): List of chemical ratios to be mixed.
            oxide_remov_time (int, optional): Seconds of oxide removal. Defaults to 60.
            oxide_remov_chemical (str, optional): Chemical for oxide removal.
            Defaults to "HCl_ECELL".
            oxide_remov_concentration (float, optional): Concentration (mol/L) of
            oxide removal chemical. Defaults to 1.
            synth1_time (int, optional): Seconds for synthesis 1. Defaults to 600 - (64 + 3).
            synth2_time (int, optional): Seconds for synthesis 2. Defaults to 300 - (64 + 3).
            oh_dip_time (int, optional): Seconds for dipping in NaOH. Defaults to 10.
            oh_chemical (str, optional): Chemical for dipping in NaOH. Defaults to "NaOH".
            oh_concentration (float, optional): Concentration of NaOH. Defaults to 2.5.
            cleaning_time (int, optional): Seconds for cleaning. Defaults to 10.
            activation_time (int, optional): Seconds for activation. Defaults to 60.
            electrolyte_chemical (str, optional): Chemical for electrolyte. Defaults to "KOH".
            electrolyte_concentration (float, optional): Concentration of electrolyte. Defaults to 1.
            ultrasound_oxide_remov (bool, optional): Ultrasound for oxide removal. Defaults to True.
            ultrasound_cleaning (bool, optional): Ultrasound for cleaning. Defaults to True.
            ultrasound_during_experiment (bool, optional): Ultrasound during experiment.
            Defaults to False.
            threshold_max_tries_per_sample (int, optional): Maximum tries per sample. Defaults to 3.
            threshold_lowest_accepted_potential (float, optional): Lowest accepted potential.
            Defaults to 1.229.
            threshold_highest_accepted_potential (float, optional): Highest accepted potential.
            Defaults to 2.5.
            threshold_lowest_accepted_resistance (float, optional): Lowest accepted resistance.
            Defaults to 0.
            threshold_highest_accepted_resistance (float, optional): Highest accepted resistance.
            Defaults to 1.5.
            mix_concentration (float, optional): Concentration of mixture. Defaults to 0.4.
            acceptance_avg_pt_potential (float, optional): Average platinum potential accepted.
            Defaults to 0.809 V.
            acceptance_lower_limit_pt_pot (float, optional): Lower limit of platinum potential
            acceptance range. Defaults to 0.804 V.
            acceptance_upper_limit_pt_pot (float, optional): Upper limit of platinum potential
            acceptance range. Defaults to 0.819 V.
            mail_recipents (list, optional): List of email recipents. Defaults to
            ["nis@dosan.dk"].
            no_chemicals (bool, optional): If True, no chemicals are dispensed. Defaults to False.
        """
        self.oxide_remov_time = oxide_remov_time  # seconds
        self.oxide_remov_chemical = oxide_remov_chemical
        self.oxide_remov_concentration = oxide_remov_concentration  # mol/L
        self.synth1_time = synth1_time  # 600 seconds - 64s for vial cleaning, 3s for movements
        self.synth2_time = synth2_time  # 300 seconds - 64s for vial cleaning, 3s for movements
        self.oh_dip_time = oh_dip_time
        self.oh_chemical = oh_chemical
        self.oh_concentration = oh_concentration
        self.cleaning_time = cleaning_time
        self.activation_time = activation_time
        self.electrolyte_chemical = electrolyte_chemical
        self.electrolyte_concentration = electrolyte_concentration
        self.ultrasound_oxide_remov = ultrasound_oxide_remov
        self.ultrasound_cleaning = ultrasound_cleaning
        self.ultrasound_during_experiment = ultrasound_during_experiment
        self.threshold_max_tries_per_sample = threshold_max_tries_per_sample
        self.threshold_lowest_accepted_potential = threshold_lowest_accepted_potential  # Volt
        self.threshold_highest_accepted_potential = threshold_highest_accepted_potential  # Volt
        self.threshold_lowest_accepted_resistance = threshold_lowest_accepted_resistance  # Ohm
        self.threshold_highest_accepted_resistance = threshold_highest_accepted_resistance  # ohm
        self.mix_concentration = mix_concentration  # mol/L
        self.metal_ratios = {
            "Cr": np.around(chemical_ratios[0], 3),
            "Al": np.around(chemical_ratios[1], 3),
            "Fe": np.around(chemical_ratios[2], 3),
            "Co": np.around(chemical_ratios[3], 3),
            "Mn": np.around(chemical_ratios[4], 3),
            "Ni": np.around(chemical_ratios[5], 3),
            "Cu": np.around(chemical_ratios[6], 3),
            # "V": np.around(chemical_ratios[6], 3),
            "Zn": np.around(chemical_ratios[7], 3),
            # "FeCl": np.around(chemical_ratios[3], 3),
        }

        # Define platinum peak potential acceptance range
        self.accept_avg_pt_potential = acceptance_avg_pt_potential  # V
        self.accept_lower_limit_pt_pot = acceptance_lower_limit_pt_pot  # V
        self.accept_upper_limit_pt_pot = acceptance_upper_limit_pt_pot  # V

        self.mail_recipents = mail_recipents
        self.ARDUINO = ARDUINO
        self.no_chemicals = no_chemicals

    def experiment(self, chemical_ratios: list[float], no_chemicals: bool = False) -> float:
        """Run the experiment with the given chemical ratios.

        Args:
            chemical_ratios (list): List of chemical ratios.
            no_chemicals (bool, optional): If True, no chemicals are dispensed and
            it skips the synthesis and consumption of vials. Defaults to False.
        Returns:
            float: Overpotential
        """
        logging.info(" ")
        logging.info(" ")
        logging.info(" ")
        logging.info(" ")
        logging.info("Starting new experiment")
        self.set_experiment_parameters(chemical_ratios=chemical_ratios, no_chemicals=no_chemicals)
        logging.info(f"{self.metal_ratios}")

        self.run_experiment()
        logging.info(f"Potential = {self.corrected_potential_at_10_mA} V")
        logging.info(f"Ohmic resistance = {self.ohmic_resistance} Ohm")

        # Evaluate if the experiment should be redone because of faulty measurements
        counter = 0
        while (
            self.corrected_potential_at_10_mA < self.threshold_lowest_accepted_potential
            or self.corrected_potential_at_10_mA > self.threshold_highest_accepted_potential
            or self.ohmic_resistance > self.threshold_highest_accepted_resistance
            or self.ohmic_resistance < self.threshold_lowest_accepted_resistance
        ) and counter < self.threshold_max_tries_per_sample:
            # Redo experiment
            logging.warning("Redoing experiment")
            self.run_experiment()
            counter += 1

        return float(self.corrected_potential_at_10_mA)

    ################################################################################################
    # Helper functions
    ################################################################################################
    def homing(self):
        """Homing of the robot."""
        logging.info("Homing carousel")
        self.controller.c9.home_carousel()
        logging.info("Homing robot arm")
        self.controller.c9.home_robot(wait=True)
        self.controller.home_pumps(pump_indices=self.pump_indices, wait=False)
        self.controller.c9.open_clamp()
        self.controller.c9.open_gripper()
        self.controller.c9.set_output(ECELL_INDICES["piston"], False)
        self.controller.c9.set_output(ECELL_INDICES["drain_piston"], False)
        self.controller.c9.set_output(ECELL_INDICES["ultrasound"], False)
        logging.info("Homing ended with success.")

    def prime_pumps(self):
        """Priming of pumps used in experiment."""
        logging.info("Priming pumps")
        self.controller.c9.move_carousel(0, 105)
        self.controller.dispense_ml("Cr", 0.4)
        self.controller.dispense_ml("Al", 0.4)
        self.controller.dispense_ml("Fe", 0.4)
        self.controller.dispense_ml("Co", 0.4)
        self.controller.dispense_ml("NaOH", 2)
        self.controller.dispense_ml("Mn", 0.5)
        self.controller.dispense_ml("Ni", 0.5)
        self.controller.dispense_ml("Cu", 0.5)
        self.controller.dispense_ml("Zn", 0.5)
        self.controller.dispense_ml("H2O", 1)
        # self.controller.dispense_ml("V", 0.2)
        # self.controller.dispense_ml("FeCl", 0.2)
        logging.info("Priming of pumps ended with success.")

    def drain_ecell(self):
        """Drain the ecell."""
        logging.info("Draining ecell")
        self.controller.dispense_ml("Drain", 15)
        logging.info("Draining of ecell ended with success.")

    def define_arduino_port(self) -> str:
        """Find the port of the Arduino.

        Returns:
            str: Port of the Arduino.
        """
        # List Arduinos on computer
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            logging.debug(f"List of USB ports: {p}")
        arduino_ports = [
            p.device
            for p in ports
            if "CH340" in p.description  # Replace string to find other Arduinos
        ]
        if not arduino_ports:
            logging.error("No Arduino found")
            raise IOError("No Arduino found")
        if len(arduino_ports) > 1:
            logging.warning("Multiple Arduinos found - using the first")

        # Automatically find Arduino
        arduino = str(serial.Serial(arduino_ports[0]).port)
        logging.info(f"Arduino found on port: {arduino}")
        return arduino

    def send_mail(self, msg: str, title: str, receivers: list):
        """Send an email to the specified receivers

        Args:
            msg (str): Message to send
            title (str): Title of the email
            receivers (list): List of receivers
        """
        smtp = smtplib.SMTP("smtp.simply.com", port=587)

        sender = "robot@dosan.dk"

        message = MIMEText(f"{msg}")
        message["Subject"] = title
        message["From"] = "robot@dosan.dk"
        message["To"] = "Nis"

        try:
            smtp.ehlo()  # send the extended hello to our server
            smtp.starttls()  # tell server we want to communicate with TLS encryption
            smtp.login("robot@dosan.dk", "abc12345678")  # login to our email server
            smtp.sendmail(sender, receivers, message.as_string())
            smtp.quit()  # close the connection
            logging.info("Successfully sent email")
        except Exception:
            logging.warning("Error: unable to send email")

    def send_mail_results(self):
        title = f"N9 - Successfull experiment sample {self.uid}"
        text = f"""
        Successfully ran the following sample:

        Unique sample ID: {self.uid}
        Ohmic resistance: {self.ohmic_resistance} ohm
        Potential at 10 mA : {self.corrected_potential_at_10_mA} V
        Sample mixture name: {self.group_name}

        Reference electrode stabilization time: {self.reference_electrode_rest_time} s
        Reference electrode drift (smoothing): {round(self.pt_peak_intial_ohmic_corr, 4)} V\
        -> {round(self.pt_peak_accepted_ohmic_corr, 4)} V
        Reference electrode potential after experiment: {round(self.pt_peak_post_measurements, 4)} V


        Start time: {datetime.fromtimestamp(self.start_time).strftime("%Y-%m-%d %H:%M:%S")}
        End time: {datetime.fromtimestamp(self.end_time).strftime("%Y-%m-%d %H:%M:%S")}
        Sample number in physical rack: {self.sample_rack_no}
        mix_ratios: {self.metal_ratios}
        mix_concentrations: {self.mix_concentration}
        oxide_remov_time: {self.oxide_remov_time}
        oxide_remov_chemical: {self.oxide_remov_chemical}
        oxide_remov_concentration: {self.oxide_remov_concentration}
        synth1_time: {self.synth1_time}
        synth2_time: {self.synth2_time}
        oh_dip_time: {self.oh_dip_time}
        oh_chemical: {self.oh_chemical}
        oh_concentration: {self.oh_concentration}
        cleaning_time: {self.cleaning_time}
        activation_time: {self.activation_time}
        electrolyte_chemical: {self.electrolyte_chemical}
        electrolyte_concentration: {self.electrolyte_concentration}
        ultrasound_oxide_remov: {self.ultrasound_oxide_remov}
        ultrasound_cleaning: {self.ultrasound_cleaning}
        ultrasound_during_experiment: {self.ultrasound_during_experiment}
        """
        try:
            self.send_mail(text, title, self.mail_recipents)
        except Exception:
            logging.warning("Failed to send email")

    def send_mail_start_of_experiment(self, title: str = "", text: str = ""):
        """Send email at the start of the experiment.

        Args:
            title (str, optional): Title of the email. Defaults to:
            "N9 - Starting experiment, sample {self.uid}"
            text (str, optional): Text of the email. Defaults to:
            "A new experiment has been started.
            Unique sample ID: {self.uid}
            Start time: %Y-%m-%d %H:%M:%S
            "
        """
        if title == "":
            title = f"N9 - Starting experiment, sample {self.uid}"
        if text == "":
            text = f"""
            A new experiment has been started.
            Unique sample ID: {self.uid}
            Start time: {datetime.fromtimestamp(self.start_time).strftime("%Y-%m-%d %H:%M:%S")}
            """
        try:
            self.send_mail(text, title, self.mail_recipents)
        except Exception:
            logging.warning("Failed to send email")

    def remove_sample_from_ecell(self, sample_rack_no: int = -1):
        """Removes sample from ecell and cleans the ecell.

        Args:
            sample_rack_no (int, optional): Rack number of the sample. Defaults to -1.
            If -1, the current rack number is used (self.sample_rack_no).

        """
        if sample_rack_no == -1:
            sample_rack_no = self.sample_rack_no
        logging.info("Remove sample from ecell")
        self.controller.c9.default_vel = 5000  # Go slow
        self.controller.c9.goto_safe(SAMPLE_TEST_POS)
        self.controller.c9.close_gripper()
        self.controller.c9.delay(0.5)
        self.controller.c9.set_output(ECELL_INDICES["piston"], False)
        self.controller.c9.default_vel = 1000  # Go slow
        self.controller.c9.goto(SAMPLE_INSERT_POS)
        self.controller.c9.default_vel = VEL
        self.controller.goto_safe_sample_rack(self.sample_rack_no)
        self.controller.c9.open_gripper()
        self.controller.c9.goto_safe(HOME)

    def oxide_removal(
        self,
    ) -> None:
        """Pre-clean the sample using HCl solution, followed by MilliQ water.

        Initial state:
            The gripper is empty.

        Final state:
            The gripper is holding the sample above the HOME position.

        Args:
            controller (C9Controller): Instance of C9Controller.
            sample_number (int): Sample number corresponding to the index number in sample rack.
            oxide_remov_time (int): Time in seconds to dip the sample in the oxide removal solution.
            oxide_remov_chemical (str): Chemical used for oxide removal.
            oxide_remov_concentration (float): Concentration of the oxide removal solution.
            std_velocity (int): the standard speed of the robot arm to move at
        """
        if not self.ultrasound_oxide_remov and self.oxide_remov_time == 0:
            pass
        else:
            logging.info(f"""Removing oxide from the sample with {self.oxide_remov_chemical}""")

            # Dip sample in HCl
            logging.info("Removing oxide from sample")
            self.controller.goto_safe_sample_rack(self.sample_rack_no)
            self.controller.c9.close_gripper()
            self.controller.c9.goto_safe(SAMPLE_INSERT_POS)
            self.controller.c9.default_vel = 1000  # Go slow
            self.controller.c9.goto(SAMPLE_TEST_POS)
            self.controller.c9.default_vel = VEL
            self.controller.c9.set_output(ECELL_INDICES["piston"], True)
            self.controller.c9.delay(0.5)
            self.controller.c9.open_gripper()
            self.controller.c9.goto_safe(HOME)
            if self.oxide_remov_time > 0:
                # TODO Implement concentration dilution here
                self.controller.dispense_ml("HCl_ECELL", 9)
                if self.ultrasound_oxide_remov:
                    logging.info("Ultrasound on")
                    logging.info(f"Waiting {self.oxide_remov_time} seconds")
                    self.controller.c9.set_output_time(
                        ECELL_INDICES["ultrasound"], self.oxide_remov_time
                    )
                    self.controller.c9.delay(1)
                    self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], True)
                    self.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], 8)
                    logging.debug("Ultrasound off")
                    self.controller.c9.delay(1)
                    self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], False)
                else:
                    logging.info(f"Waiting {self.oxide_remov_time} seconds")
                    self.controller.c9.delay(self.oxide_remov_time)
                    self.controller.dispense_ml("Drain", ECELL_VOLUME)

            # Flush with water
            logging.info("Flushing with water 3 times")
            self.controller.dispense_ml("H2O_ECELL", ECELL_VOLUME)
            if self.ultrasound_oxide_remov:
                logging.info("Ultrasound on")
                self.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], 30)
                self.controller.c9.delay(1)
                self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], True)
                self.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], 8)
                logging.debug("Ultrasound off")
                self.controller.c9.delay(1)
                self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], False)
            else:
                self.controller.dispense_ml("Drain", ECELL_VOLUME + 3 + 2)

            self.controller.dispense_ml("H2O_ECELL", ECELL_VOLUME)
            if self.ultrasound_oxide_remov:
                logging.info("Ultrasound on")
                self.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], 30)
                self.controller.c9.delay(1)
                self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], True)
                self.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], 8)
                logging.debug("Ultrasound off")
                self.controller.c9.delay(1)
                self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], False)
            else:
                self.controller.dispense_ml("Drain", ECELL_VOLUME + 3 + 2)

            self.controller.dispense_ml("H2O_ECELL", ECELL_VOLUME)
            if self.ultrasound_oxide_remov:
                logging.info("Ultrasound on")
                self.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], 30)
                self.controller.c9.delay(1)
                self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], True)
                self.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], 8)
                logging.debug("Ultrasound off")
                self.controller.c9.delay(1)
                self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], False)
            else:
                self.controller.dispense_ml("Drain", ECELL_VOLUME + 3 + 2)

            # Return to rack with the sample
            logging.info("Returning sample to rack")
            self.controller.c9.goto_safe(SAMPLE_INSERT_POS)
            self.controller.c9.default_vel = 1000  # Go slow
            # controller.c9.goto(SAMPLE_CLEAN_POS)
            self.controller.c9.goto(SAMPLE_TEST_POS)
            self.controller.c9.close_gripper()
            self.controller.c9.set_output(ECELL_INDICES["piston"], False)
            self.controller.c9.delay(0.5)
            self.controller.c9.default_vel = VEL
            self.controller.goto_safe_sample_rack(self.sample_rack_no)
            self.controller.c9.open_gripper()

    def clean_ecell(self, vol: float = ECELL_VOLUME, delay: float = 3.0, num_flush: int = 2) -> None:
        """
        Cleaning sequence of the e-cell, which dispenses H2O and runs ultrasonic cleaning
        for a presribed number of times and flushes the cell.

        Args:
            vol (float, optional): volume of water to fill the cell in ml. Defaults to 11.5.
            delay (float, optional): delay in sec after the filling the cell for ultrasonic cleaning.
                Defaults to 3.0.
            num_flush (int, optional): number of flushes to perform. Defaults to 2.
        """
        logging.info("Starting e-cell cleaning sequence.")

        logging.info("Flushing e-cell prior to HCL:")
        self.controller.dispense_ml("H2O_ECELL", vol)
        if self.ultrasound_cleaning:
            logging.info("Ultrasound on")
            self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], True)
            self.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], 15)
            logging.debug("Ultrasound off")
            self.controller.c9.delay(1)
            self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], False)
        else:
            self.controller.dispense_ml("Drain", vol + 1)

        logging.info("Flushing e-cell with HCL:")
        self.controller.dispense_ml("HCl_ECELL", vol + 3)
        logging.info(f"Waiting {delay} seconds")
        self.controller.c9.delay(delay)
        logging.info("Draining ECELL")
        if self.ultrasound_cleaning:
            logging.info("Ultrasound on")
            self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], True)
            self.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], 15)
            logging.debug("Ultrasound off")
            self.controller.c9.delay(1)
            self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], False)
        else:
            self.controller.dispense_ml("Drain", vol + 3)

        for flush in range(num_flush):
            logging.info(f"Flushing e-cell: {flush+1} of {num_flush}")
            self.controller.dispense_ml("H2O_ECELL", vol + 4)
            logging.info("Waiting 10 seconds")
            self.controller.c9.delay(10)
            logging.info("Draining ECELL")
            if self.ultrasound_cleaning:
                logging.info("Ultrasound on")
                self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], True)
                self.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], 15)
                logging.debug("Ultrasound off")
                self.controller.c9.delay(1)
                self.controller.c9.set_output(PERISTALTIC_PUMP_INDICES["Drain"], False)
            else:
                self.controller.dispense_ml("Drain", vol + 4)

        logging.info("Cleaning e-cell completed.")

    def clean_vial(self) -> None:
        """Empties and wash a vial 2 times to clean it.
        First it is emtied, then washed with water, then emtied again and washed with water.
        Finally it is emtied a third time.
        """

        logging.info("Cleaning vial: Emtying and filling vial 2 times to clean it")
        for i in range(0, 2):
            angle = CAROUSEL_ANGLES["Air"]
            self.controller.c9.move_carousel(angle, 79)
            self.controller.dispense_ml("Air", VIAL_VOLUME + 2)

            angle = CAROUSEL_ANGLES["H2O"]
            self.controller.c9.move_carousel(angle, 70)
            self.controller.dispense_ml("H2O", VIAL_VOLUME)

        angle = CAROUSEL_ANGLES["Air"]
        self.controller.c9.move_carousel(angle, 79)
        self.controller.dispense_ml("Air", VIAL_VOLUME + 2)

        self.controller.c9.move_carousel(0, 105)

    def clean_and_activate_sample(
        self,
    ) -> None:
        """
        Cleaning procedure for a sample in e-cell. The sequence starts by applying ultrasonic sound,
        filling KOH solution and applying ChronoPotentiometry, followed by draining of the e-cell.
        """
        logging.info("Starting sequence for cleaning a sample in e-cell.")

        logging.info("Starting ChronoPotentiometry")
        init_ampere = 0
        tinit = 0
        ampere_step1 = 0
        tstep1 = 0
        ampere_step2 = 0.2
        tstep2 = self.activation_time
        cp = recipe.CP(
            init_voltage=init_ampere,
            tinit=tinit,
            vstep1=ampere_step1,
            tstep1=tstep1,
            vstep2=ampere_step2,
            tstep2=tstep2,
            sample=0.5,
        )
        with timer():
            logging.debug("Entered the with timer loop")
            cp.run()
        logging.debug("Finished activation. Retrieving data.")
        _ = cp.get_data()
        logging.debug("Throwing away data by setting it to Null.")

        if self.cleaning_time > 0 and self.ultrasound_cleaning:
            logging.info(f"Ultrasound on for {self.cleaning_time} seconds")
            self.controller.c9.set_output_time(ECELL_INDICES["ultrasound"], self.cleaning_time)
            logging.debug("Ultrasound off")
            self.controller.c9.delay(1)

        logging.info("Cleaning procedure of sample finished successfully")

    def place_vial_to_rack(
        self,
        vial_number: int = -1,
    ) -> None:
        """
        Take the screw cap from the holder and put it on the vial in the clamp.
        The vial is then placed on the rack in its position number.

        Initial state:
            The gripper is empty.

        Final state:
            The gripper is empty.

        Args:
            vial_number (int): Vial number corresponding to the index number in vial rack.
        """
        # If inputs, use that, otherwise use the stored value
        if vial_number == -1:
            vial_number = self.vial_position_number

        logging.info("Close and remove vial")
        vial_rack_pos = vial_rack[vial_number]
        self.controller.recap(
            CAP_HOLDER_ON_POS,
            VIAL_CLAMP_CAP_POS,
            self.z_position_stored_cap,
            self.z_position_clamp_uncapped,
            self.gripper_position,
        )
        self.controller.goto_safe_vial_rack(vial_number)
        self.controller.c9.open_gripper()
        self.controller.c9.move_z(vial_rack_pos[2] + 4)
        self.controller.spin(6, 1)  # Make sure vial doesn't stick
        self.controller.c9.goto_safe(HOME)

    def get_group_name(self, volumes: dict, unique_id=1) -> str:
        """Generate the group name based on the volumes of liquids for a sample to save the data.

        Args:
            volumes (dict): Dictionary which contains the liquids names and corresponding volumes
            unique_id (int, optional): _description_. Defaults to 1.

        Returns:
            str: Returns the group name.
        """
        name = str(unique_id)
        for key in volumes.keys():
            name = name + "_" + key + str(round(volumes[key], 3))
        return name

    def get_sample_rack_number(
        self,
        max_sample_number: int = NUMBER_OF_SAMPLES,
        filename: str = "last_proccessed_rack_number.txt",
        DATA_path: str = DATA_PATH,
    ) -> int:
        """
        Read the sample number from file 'sample_rack_number.txt'. If the
        file does not exist set 'sample_rack_number' to 0.
        If the sample_rack_number > max_sample number then also set 'sample_rack_number' to 0.

        Args:
            max_sample_number (int): Maximum available number of racks in the sample rack.
            filename (str): Name of the txt file
            DATA_path (str): Path of where the file is stored

        Returns:
            int: Currenty available number of sample rack
        """
        file = DATA_path + filename
        p = Path(file)
        try:
            p.open("r")
            sample_rack_number = int(p.read_text())
            logging.debug(
                f"Found previous sample number sample_rack_number={sample_rack_number} in file {p}"
            )
            sample_rack_number = sample_rack_number + 1
            logging.info(f"Setting current sample_rack_number={sample_rack_number}")
        except Exception:
            logging.warning(f"Didn't find file at location {p}. Setting sample_rack_number=0")
            sample_rack_number = 0

        if sample_rack_number > max_sample_number:
            logging.error(
                f"""sample_rack_number is larger than {max_sample_number}.
                Aborting script. Clean the robot, delete sample_rack_number.txt"""
            )
            raise Exception(
                "sample_rack_number is larger than max_sample_number. Aborting ",
                "script to avoid reuse and crosscontamination of vials. Please ",
                "clean the robot, delete sample_rack_number.txt and restart the script.",
            )

        return sample_rack_number

    def get_uid(self, HDF5_file: str = HDF5_FILE) -> int:
        """
        Get last unique ID of the sample from HDF5 file and add 1

        Args:
            HDF5_file (str): Path to the HDF5 file where the attribute
            'lastSampleID' is stored. This is an integer which is the last
            unique ID of previous sample.

        Returns:
            int: Unique ID number
        """
        p = Path(HDF5_file)
        with h5py.File(p, "a") as file:
            try:
                old_id = str(file.attrs["lastSampleID"])
                old_id = int(old_id)
            except Exception:
                logging.warning("Could not find lastSampleID in HDF5 file. Setting ID to 0")
                old_id = 0
            new_id = old_id + 1
            file.attrs["lastSampleID"] = new_id
        return new_id

    def get_arduino_sensor_readings(self) -> list[str]:
        """
        Method to read Arduino sensors, currently it includes readings from:
        MCP9600
        BME280
        TMP117
        AHT20

        Args:
            com (str): com-port for the Arduino. For example /dev/cu.usbserial-1110 on a Mac.
            On Windows it is COM3 or similar.

        Returns:
            list: List of sensor readings
            [tempSample_mcp9600 (C);
            tempSampleUncertainty_mcp9600 (+-C);
            tempAmbient_mcp9600 (C);
            tempAmbientUncertainty_mcp9600 (+-C);
            humidity_bme280 (%);
            humidityUncertainty_bme280 (+-%);
            pressure_bme280 (Pa);
            pressureUncertainty_bme280 (+-Pa);
            temp_bme280 (C);
            tempUncertainty_bme280 (+-C);
            temp_tmp117 (C);
            tempUncertainty_tmp117 (+-C);
            temp_aht20 (C);
            tempUncertainty_aht20 (+-C);
            humidity_aht20 (%);
            humidityUncertainty (+-%)]
        """
        arduino = serial.Serial(port=self.ARDUINO, baudrate=115200, timeout=0.1)
        data = []
        for _ in range(5):
            line = arduino.readline()  # read a byte string
            time.sleep(2)
            if line:
                string = line.decode()  # convert the byte string to a unicode string
                text = string.split("; ")
                data = np.array(text)

        return data

    def get_vial_position_number(self, vial_per_sample: int, current: int) -> int:
        """
        For the cases where multiple vials are used per sample, increment the vial position number
        of the rack accordingly based on the sample number and the number of vials used per sample.

        Args:
            vial_per_sample (int): Number of vials used per sample.
            current (int): Current vial being tested (out of N, where N is the vial_per_sample)
        """
        assert current < vial_per_sample
        return self.sample_rack_no * vial_per_sample + current

    def save_hdf5_arduino_sensors(
        self,
        trailing_string: str,
        HDF5_file: str = HDF5_FILE,
    ) -> None:
        """get the sensor data, display on console, and save it to a h5py file.
        Args:
            HDF5_file (str): h5py file where the data is saved.
            trailing_string (str): Trailing string after sensor data, eg.:
            temperature_sample_'start'
        """
        p = Path(HDF5_file)
        logging.info(
            "Measuring room temperature, pressure, humidity and sample temperature - Please wait"
        )
        try:
            [
                temperature_sample,
                temperature_sample_uncertainty,
                temperature_mcp9600,
                temperature_uncertainty_mcp9600,
                humidity_bme280,
                humidity_uncertainty_bme280,
                pressure_bme280,
                pressure_uncertainty_bme280,
                temperature_bme280,
                temperature_uncertainty_bme280,
                temperature_tmp117,
                temperature_uncertainty_tmp117,
                temperature_aht20,
                temperature_uncertainty_aht20,
                humidity_aht20,
                humidity_uncertainty_aht20,
            ] = self.get_arduino_sensor_readings()
        except Exception:
            raise Exception("Could not read from Arduino. Check the connection.")

        logging.info(f"Room temperature: {temperature_tmp117}C")
        logging.info(f"Humidity:{humidity_aht20}")
        logging.info(f"Sample temperature: {temperature_sample}C")

        # Save environmental data before starting measurements #
        logging.info("Saving sensor data")
        with h5py.File(p, "a") as file:
            try:
                group = file[self.group_name]
            except Exception:
                group = file.create_group(self.group_name)

            group.attrs["Room_temperature_tmp117_" + trailing_string] = (
                temperature_tmp117 + " ±" + temperature_uncertainty_tmp117 + " C"
            )
            group.attrs["Room_temperature_aht20_" + trailing_string] = (
                temperature_aht20 + " ±" + temperature_uncertainty_aht20 + " C"
            )
            group.attrs["Room_temperature_bme280_" + trailing_string] = (
                temperature_bme280 + " ±" + temperature_uncertainty_bme280 + " C"
            )
            group.attrs["Room_temperature_mcp9600_" + trailing_string] = (
                temperature_mcp9600 + " ±" + temperature_uncertainty_mcp9600 + " C"
            )
            group.attrs["Room_humidity_aht20_" + trailing_string] = (
                humidity_aht20 + " ±" + humidity_uncertainty_aht20 + " %"
            )
            group.attrs["Room_humidity_bme280_" + trailing_string] = (
                humidity_bme280 + " ±" + humidity_uncertainty_bme280 + " %"
            )
            group.attrs["Room_atmospheric_pressure_" + trailing_string] = (
                pressure_bme280 + " ±" + pressure_uncertainty_bme280 + " Pa"
            )
            group.attrs["Sample_temperature_" + trailing_string] = (
                temperature_sample + " ±" + temperature_sample_uncertainty + " C"
            )
            group.attrs["Date"] = time.strftime("%Y-%m-%d %H:%M:%S")

    def save_txt_sample_no(
        self,
        sample_number: int,
        file_name: str = "last_proccessed_rack_number.txt",
        DATA_path: str = DATA_PATH,
    ) -> None:
        """Write the current sample number processed to a file

        Args:
            sample_number (int): Index number of the sample being tested.
            file_name (str): Name of the file. Defaults to "sample_rack_number.txt"
            DATA_path (str): Path of where the file is stored
        """
        file_path = DATA_path + file_name
        p = Path(file_path)
        with p.open("w", encoding="utf-8") as f:
            f.write(str(sample_number))

    def save_csv_dataset(
        self,
        data_set_name: str,
        column_names: list,
        HDF5_file: str = HDF5_FILE,
        DATA_path: str = DATA_PATH,
    ) -> None:
        """Saves content of a dataset in a HDF5 file to a .csv of the same name as the dataset.

        Args:
        file_name (str): Path and name of the HDF5 file
        path (str): Path to place the .csv file at
        data_set_name (str): Name of the dataset to store as a .csv
        column_names (list): List of column names for the .csv
        """
        with h5py.File(HDF5_file, "r") as file:
            try:
                data = file[data_set_name]
                data = np.array(data)
                df = pd.DataFrame(data)
                df.columns = column_names

                filename_txt = DATA_path + data_set_name + ".csv"
                df.to_csv(filename_txt, index=False, sep="\t", decimal=",")
            except Exception:
                raise Exception(f"{data_set_name} is not found in hdf5 file and no csv is saved.")

    def save_hdf5_metadata(
        self,
    ) -> None:
        """Store metadata about the experiment in HDF5 file."""

        p = Path(HDF5_FILE)
        logging.info("Storing metadata about the experiment")

        with h5py.File(p, "a") as file:
            try:
                group = file[self.group_name]
            except Exception:
                group = file.create_group(self.group_name)

            group.attrs["UID"] = self.uid
            group.attrs["rack_position_of_sample"] = self.sample_rack_no
            group.attrs["vials_used"] = (
                f"[{self.vial_position_number}, {self.vial_position_number + 1}]"
            )
            group.attrs["mix_ratios"] = str(self.metal_ratios)
            group.attrs["mix_concentration"] = str(self.mix_concentration)
            group.attrs["oxide_remov_time"] = self.oxide_remov_time
            group.attrs["oxide_remov_chemical"] = self.oxide_remov_chemical
            group.attrs["oxide_remov_concentration"] = self.oxide_remov_concentration
            group.attrs["synthesis_1_time"] = self.synth1_time
            group.attrs["synthesis_2_time"] = self.synth2_time
            group.attrs["oh_dip_time"] = self.oh_dip_time
            group.attrs["oh_chemical"] = self.oh_chemical
            group.attrs["oh_concentration"] = self.oh_concentration
            group.attrs["cleaning_time"] = self.cleaning_time
            group.attrs["activation_time"] = self.activation_time
            group.attrs["electrolyte_chemical"] = self.electrolyte_chemical
            group.attrs["electrolyte_concentration"] = self.electrolyte_concentration
            group.attrs["ultrasound_oxide_remov"] = self.ultrasound_oxide_remov
            group.attrs["ultrasound_cleaning"] = self.ultrasound_cleaning
            group.attrs["ultrasound_during_experiment"] = self.ultrasound_during_experiment

    def save_txt_sample_rack_no(
        self,
        file_name: str = "sample_and_rack_number_history.txt",
    ) -> None:
        """Write the unique UD and the rack position as well as other parameters
        to a file for history.

        Args:
            file_name (str, optional): Name of the file.
            Defaults to "sample_and_rack_number_history.txt".
        """

        file_path = DATA_PATH + file_name
        p = Path(file_path)
        with p.open("a", encoding="utf-8") as f:
            f.write(
                "\nSample: "
                + str(self.uid)
                + "\tRack position: "
                + str(self.sample_rack_no)
                + "\tMix ratios: "
                + str(self.metal_ratios)
                + "\tMix concentration: "
                + str(self.mix_concentration)
                + "\tOxide removal time: "
                + str(self.oxide_remov_time)
                + "\tOxide removal chemical: "
                + str(self.oxide_remov_chemical)
                + "\tOxide removal concentration: "
                + str(self.oxide_remov_concentration)
                + "\tSynthesis 1 time: "
                + str(self.synth1_time)
                + "\tSynthesis 2 time: "
                + str(self.synth2_time)
                + "\tOH dip time: "
                + str(self.oh_dip_time)
                + "\tOH chemical: "
                + str(self.oh_chemical)
                + "\tOH concentration: "
                + str(self.oh_concentration)
                + "\tCleaning time: "
                + str(self.cleaning_time)
                + "\tActivation time: "
                + str(self.activation_time)
                + "\tElectrolyte chemical: "
                + str(self.electrolyte_chemical)
                + "\tElectrolyte concentration: "
                + str(self.electrolyte_concentration)
                + "\tUltrasound oxide removal: "
                + str(self.ultrasound_oxide_remov)
                + "\tUltrasound cleaning: "
                + str(self.ultrasound_cleaning)
                + "\tUltrasound during experiment: "
                + str(self.ultrasound_during_experiment)
            )

    def log_metadata(self):
        """Log metadata of the experiment."""
        # Store data in log
        logging.info(f"Unique sample ID: {self.uid}")
        logging.info(f"Starting mixing of sample with mixture name: {self.group_name}")
        logging.info(f"Sample number in physical rack: {self.sample_rack_no}")
        logging.info(f"mix_ratios: {self.metal_ratios}")
        logging.info(f"mix_concentrations: {self.mix_concentration}")
        logging.info(f"oxide_remov_time: {self.oxide_remov_time}")
        logging.info(f"oxide_remov_chemical: {self.oxide_remov_chemical}")
        logging.info(f"oxide_remov_concentration: {self.oxide_remov_concentration}")
        logging.info(f"synth1_time: {self.synth1_time}")
        logging.info(f"synth2_time: {self.synth2_time}")
        logging.info(f"oh_dip_time: {self.oh_dip_time}")
        logging.info(f"oh_chemical: {self.oh_chemical}")
        logging.info(f"oh_concentration: {self.oh_concentration}")
        logging.info(f"cleaning_time: {self.cleaning_time}")
        logging.info(f"activation_time: {self.activation_time}")
        logging.info(f"electrolyte_chemical: {self.electrolyte_chemical}")
        logging.info(f"electrolyte_concentration: {self.electrolyte_concentration}")
        logging.info(f"ultrasound_oxide_remov: {self.ultrasound_oxide_remov}")
        logging.info(f"ultrasound_cleaning: {self.ultrasound_cleaning}")
        logging.info(f"ultrasound_during_experiment: {self.ultrasound_during_experiment}")

    def mix_liquids(
        self,
        carousel_dispense_height: float = 70,
        dispense_volume: float = VIAL_VOLUME,
    ) -> None:
        """Mix the liquids based on the ordered composition listed in self.metal_ratios.
        Adjust them to the concentration self.mix_concentration.
        Dispense in total a volume as defined in VIAL_VOLUME.

        Args:
            carousel_dispense_height (float, optional): Height of the carousel. Defaults to 70 mm.
            dispense_volume (float, optional): Volume to dispense in ml. Defaults to VIAL_VOLUME.

        """
        logging.info("Mixing liquids.")
        logging.debug(f"mix_liquids() received {self.metal_ratios}")

        # Building dict with concentrations of the chemicals
        pump_concentrations = {key: PUMP_CONCENTRATIONS[key] for key in self.metal_ratios}

        # Calculate the volumes to dispense of each chemical
        converter_mix = CC(
            pump_concentrations,
            self.metal_ratios,
            self.mix_concentration,
            DILUTION_CHEMICAL,
            dispense_volume,
        )
        volumes = converter_mix.calculate_volumes()

        # Angles of tubes on the carousel
        carousel_angles = CAROUSEL_ANGLES

        # Dispense the chemicals
        dispense_commands = [(key, value) for key, value in volumes.items() if value != 0]
        for key, value in dispense_commands:
            self.controller.c9.move_carousel(carousel_angles[key], carousel_dispense_height)
            self.controller.dispense_ml(key, value)

        # Move carousel back to the start position
        self.controller.c9.move_carousel(0, 105)

    def dispense_electrolyte(self, volume_of_ecell: float = ECELL_VOLUME) -> None:
        # Define concentration of electrolyte
        converter_electrolyte = CC(
            {self.electrolyte_chemical: PUMP_CONCENTRATIONS[self.electrolyte_chemical]},
            {self.electrolyte_chemical: self.electrolyte_concentration},
            self.electrolyte_concentration,
            DILUTION_CHEMICAL_ECELL,
            volume_of_ecell,
        )

        # Define mixture of water and electrolyte dependent on concentration
        volumes = converter_electrolyte.calculate_volumes()

        # Fill ecell with electrolyte
        for key, value in volumes.items():
            self.controller.dispense_ml(key, value)
        volumes = None

    def sample_to_ecell_and_clean(
        self,
    ) -> None:
        """Take sample from sample rack and place it in test cell."""

        # Place sample in ecell
        logging.info("Placing sample in ecell in cleaning position")
        self.controller.goto_safe_sample_rack(self.sample_rack_no)
        self.controller.c9.close_gripper()
        self.controller.c9.goto_safe(SAMPLE_INSERT_POS)
        self.controller.c9.default_vel = 1000  # Go slow
        self.controller.c9.goto(SAMPLE_TEST_POS)
        self.controller.c9.default_vel = VEL
        self.controller.c9.set_output(ECELL_INDICES["piston"], True)
        self.controller.c9.delay(0.5)
        self.controller.c9.open_gripper()
        self.controller.c9.goto_safe(HOME)

    def dispense_oh_to_vial(self) -> None:
        """Dispense NaOH to a vial in the clamp.
        It dispenses 2 ml more than the defined VIAL_VOLUME.
        """
        dispense_volume = VIAL_VOLUME + 2
        converter_oh = CC(
            {self.oh_chemical: PUMP_CONCENTRATIONS[self.oh_chemical]},
            {self.oh_chemical: 1},  # ratio, 100% of chemical
            self.oh_concentration,
            DILUTION_CHEMICAL,
            dispense_volume,
        )
        volumes = converter_oh.calculate_volumes()
        for key, value in volumes.items():
            if value != 0:
                self.controller.c9.move_carousel(CAROUSEL_ANGLES[key], 70)
                self.controller.dispense_ml(key, value)
        self.controller.c9.move_carousel(0, 105)

    def place_vial_to_clamp(
        self,
        vial_position_number: int = -1,
    ):
        """
        Sequence for taking a vial in the `vial_position_number` from the rack and place it
        in a clamp. The screw cap of the vial is then removed and placed on the cap holder.

        Args:
            vial_position_number (int): Position number of the vial in the rack.
            Defaults to -1. If -1, the current vial position number is used.

        Initial state:
            The gripper and clamp are not holding anything (are empty).

        Final state:
            The gripper does not hold anything, and the clamp is
            holding the empty vial.

        Returns:
            z_position_clamp_uncapped (int): z-position of the cap (in counts) when vial was
            uncapped in the clamp
            z_position_stored_cap (int): z-position of the stored cap
            once capped into place (in counts)
            gripper_position (int): Rotational gripper position (in counts) of the cap when vial
            was uncapped in the clamp
        """
        if vial_position_number < 0:
            vial_position_number = self.vial_position_number
        logging.info(f"Placing vial {vial_position_number} to clamp.")
        self.controller.goto_safe_vial_rack(vial_position_number)
        self.controller.c9.close_gripper()
        self.controller.c9.goto_safe(VIAL_CLAMP)
        self.controller.c9.close_clamp()
        logging.debug("Uncapping vial in cial clamp")
        self.controller.c9.uncap(pitch=2.75)
        self.z_position_clamp_uncapped = self.controller.c9.get_axis_position(
            self.controller.c9.Z_AXIS
        )  # Z pos. uncapped cap (in counts)
        self.gripper_position = self.controller.c9.get_axis_position(
            0
        )  # Uncapped cap rotation position (in counts)
        logging.info("Store cap")
        self.z_position_stored_cap = self.controller.store_cap(
            CAP_HOLDER_OFF_POS
        )  # Stored and capped cap z pos. (in counts)
        self.controller.clamp_empty = False
        return self.z_position_clamp_uncapped, self.z_position_stored_cap, self.gripper_position

    def place_sample_in_cell(self):
        self.controller.goto_safe_sample_rack(self.sample_rack_no)
        self.controller.c9.close_gripper()
        self.controller.c9.goto_safe(SAMPLE_INSERT_POS)
        self.controller.c9.default_vel = 1000  # Go slow
        self.controller.c9.goto(SAMPLE_TEST_POS)
        self.controller.c9.default_vel = VEL
        self.controller.c9.set_output(ECELL_INDICES["piston"], True)
        self.controller.c9.delay(0.5)
        self.controller.c9.open_gripper()
        self.controller.c9.goto_safe(HOME)

    def dip_sample(
        self,
        sample_rack_no: int,
        spin: bool = True,
        dipping_pos: list[int] = DIPPING_POS,
        dip_time: int = 0,
    ) -> None:
        """Dip the sample in the soultion in vial and place the sample on sample rack

        Initial state:
            The gripper is holding the sample.

        Final state:
            The gripper is empty.

        Args:
            sample_rack_no (int): The position number of the sample in the sample rack.
            spin (bool) : Whether the sample need to be spin in solution.
            dipping_pos (list[int]) : The position of the sample in the solution.
            dip_time (int) : The time (in sec) which the sample is kept in solution. Defaults to 0.
        """
        logging.info(f"Dipping sample {sample_rack_no}")
        self.controller.c9.goto_safe(dipping_pos)
        if spin:
            self.controller.spin(2, 10)
        if dip_time > 0:
            self.controller.c9.delay(dip_time)
        self.controller.goto_safe_sample_rack(sample_rack_no)
        self.controller.c9.open_gripper()
        self.controller.c9.goto_safe(HOME)

    def check_ohmic_resistance(
        self,
        group_name: str,
        threshold_ohmic_resistance: float,
    ) -> bool:
        """Check the ohmic resistance of the ecell. If it is too high, the ecell needs to be cleaned.

        Args:
            controller (C9Controller): Instance of C9Controller.
            group_name (str): Group name or sample name to save the data
            threshold_ohmic_resistance (float): Threshold for the ohmic resistance

        Returns:
            continue_mesurements (bool): Whether to continue the measurements or not
        """
        logging.info(
            "Finding ohmic resistance of sample to verify if it has a good electric connection"
        )
        time.sleep(3)
        make_another_scan_attempt = True
        while make_another_scan_attempt is True:
            try:
                ohmic_resistance = run_EIS_and_save_data(
                    measurement_number=0,
                    init_freq=100000.0,
                    final_freq=10000,
                    pts_per_decade=10,
                    dc=1.5,  # DC potential (V)
                    ac=0.01,  # AC potential (V)
                    group_name=group_name,
                )
                make_another_scan_attempt = False
            except Exception as e:
                logging.error(f"Error in EIS measurement: {e}")
                if "name already exists" in str(e):
                    logging.error("Name already exists in HDF5 file. Continueing with experiment.")
                    make_another_scan_attempt = False
                else:
                    logging.info("Trying to scan again.")
                    make_another_scan_attempt = True
                    time.sleep(10)

        time.sleep(3)

        if ohmic_resistance > threshold_ohmic_resistance:
            continue_mesurements = False
        else:
            continue_mesurements = True

        return continue_mesurements

    def delete_sample_hdf5(self, group_name: str = "", HDF5_file: str = HDF5_FILE) -> None:
        """Delete the group from the HDF5 file.

        Args:
            group_name (str): Name of the group to delete. Defaults to self.group_name.
            HDF5_file (str): Path to the HDF5 file. Defaults to HDF5_FILE.
        """
        if group_name == "":
            group_name = self.group_name

        # Delete group from HDF5 file
        logging.warning("Deleting group from HDF5 file")
        with h5py.File(HDF5_FILE, "a") as f:
            del f[self.group_name]

    ################################################################################################
    # Main experiment
    ################################################################################################
    def run_experiment(
        self,
    ):
        """Run experiment."""

        # Start time
        self.start_time = time.time()
        logging.info("Finding UID, sample number and group_name for sample")
        self.uid = self.get_uid()  # Unique ID
        self.send_mail_start_of_experiment()

        logging.info("Finding sample number")
        self.sample_rack_no = self.get_sample_rack_number()

        logging.info("Finding group name")
        self.group_name = self.get_group_name(self.metal_ratios, self.uid)  # Group name

        # Find and test if Arduino is responding
        logging.info("Initiating Arduino")
        self.ARDUINO = self.define_arduino_port()

        self.save_hdf5_arduino_sensors(trailing_string="init")

        # Log metadata to promt
        self.log_metadata()

        # Store metadata in txt file for easy access by us
        self.save_txt_sample_rack_no()

        self.vial_position_number = self.get_vial_position_number(2, 0)

        # Store metadata in HDF5 file
        self.save_hdf5_metadata()

        # Save sample number to make sure we don't process it again ever
        self.save_txt_sample_no(self.sample_rack_no)

        # Drain ecell
        self.controller.dispense_ml("Drain", 15)

        # Flush with water
        self.controller.dispense_ml("H2O_ECELL", 12)
        self.controller.dispense_ml("Drain", 15)

        # HCl dip
        self.oxide_removal()

        # Prime ecells electrolyte peristaltic pump and drain content
        logging.info("Priming ecell with electrolyte and draining it.")
        self.controller.dispense_ml("KOH", 3)
        self.controller.dispense_ml("Drain", 7)

        # Fill ecell with electrolyte
        self.dispense_electrolyte(volume_of_ecell=9)

        # Check if there are no chemicals to mix
        if self.no_chemicals == False:
            # Dip sample in metal solution
            _ = self.place_vial_to_clamp()
            self.mix_liquids()
            self.controller.goto_safe_sample_rack(self.sample_rack_no)
            self.controller.c9.close_gripper()
            self.dip_sample(self.sample_rack_no)
            self.clean_vial()
            self.place_vial_to_rack()

            # Synthesis 1
            if self.synth1_time > 0:
                logging.info(f"Waiting for {self.synth1_time} seconds to synthesise")
                self.controller.c9.delay(self.synth1_time)

        # Get position number of 2nd clean vial (2 of 2) in experiment
        self.vial_position_number = self.get_vial_position_number(2, 1)

        # Check if there are no chemicals to mix
        if self.no_chemicals == False:
            # Move vial to clamp
            _ = self.place_vial_to_clamp()

            # Fill vial with NaOH
            self.dispense_oh_to_vial()

            # Dip sample in NaOH and put vial back in rack
            self.controller.goto_safe_sample_rack(self.sample_rack_no)
            self.controller.c9.close_gripper()
            self.dip_sample(self.sample_rack_no, spin=False, dip_time=self.oh_dip_time)
            self.clean_vial()
            self.place_vial_to_rack()

            # Synthesis 2
            if self.synth2_time > 0:
                logging.info(f"Waiting for {self.synth2_time} seconds to synthesise")
                self.controller.c9.delay(self.synth2_time)

        # Check for reference electrode drift
        (
            self.pt_peak_intial_ohmic_corr,
            self.pt_peak_accepted_ohmic_corr,
            self.ohmic_resistance_pt,
            self.reference_electrode_rest_time,
        ) = check_for_reference_electrode_drift(
            controller=self.controller,
            group_name=self.group_name,
            lower_limit_pt_pot=self.accept_lower_limit_pt_pot,
            upper_limit_pt_pot=self.accept_upper_limit_pt_pot,
            uid=self.uid,
        )

        # Move the sample into the ecell
        self.sample_to_ecell_and_clean()

        # clean it with ultrasound and activation
        self.clean_and_activate_sample()

        # Check if sample has ohmic resistance lower than threshold
        if (
            self.check_ohmic_resistance(
                group_name=self.group_name,
                threshold_ohmic_resistance=3.0,
            )
            is True
        ):
            logging.info("Ohmic resistance is below threshold. Continuing with experiment.")

            # Perform electrochemical measurements
            self.save_hdf5_arduino_sensors(trailing_string="start")
            [
                self.corrected_potential_at_10_mA,
                self.ohmic_resistance,
            ] = electrochemical_measurements(
                group_name=self.group_name,
                unique_id=self.uid,
                controller=self.controller,
                ultrasound=self.ultrasound_during_experiment,
            )
            self.save_hdf5_arduino_sensors(trailing_string="end")

            # Remove sample from cell
            self.remove_sample_from_ecell()

            # Log the potential of the reference electrode
            self.pt_peak_post_measurements = get_reference_electrode_potential(
                self.group_name, self.ohmic_resistance_pt
            )
            self.controller.dispense_ml("Drain", 12)

            # Cleanup ecell
            self.clean_ecell(
                vol=11.5,
                delay=5,
                num_flush=2,
            )

            # Save data in a readable file (even though it has already been stored to HDF5)
            self.save_csv_dataset(
                "keyParameters",
                [
                    "Unique ID",
                    "Current [A]",
                    "Raw potential [V]",
                    "Corrected potential [V]",
                    "Resistivity [ohm]",
                ],
            )

            # End time of experiment
            self.end_time = time.time()

            self.send_mail_results()
            logging.info("Done. Ready for next sample.")

        else:  # Overpotential larger than threshold
            logging.warning("Ohmic resistance is above threshold. Skipping sample.")

            # Cleanup ecell
            self.remove_sample_from_ecell()
            self.clean_ecell(
                vol=11.5,
                delay=5,
                num_flush=2,
            )

            # Delete group from HDF5 file
            logging.warning("Deleting group from HDF5 file")
            with h5py.File(HDF5_FILE, "a") as f:
                del f[self.group_name]

            self.corrected_potential_at_10_mA = 999.99
            self.ohmic_resistance = 999.99

        # Define concentration of electrolyte
        logging.info("Filling ecell with electrolyte to not leave it empty.")
        self.dispense_electrolyte(volume_of_ecell=9)

    def run_emergency_experiment(self):
        """Assumes nickel foam sample was made. Proceeding with experiments again.
        Pick up sample from sample rack."""

        # Start time
        self.start_time = time.time()
        logging.info("Finding UID, sample number and group_name for sample")
        self.uid = self.get_uid()  # Unique ID
        self.send_mail_start_of_experiment()

        logging.info("Finding sample number")
        self.sample_rack_no = self.get_sample_rack_number()

        logging.info("Finding group name")
        self.group_name = self.get_group_name(self.metal_ratios, self.uid)  # Group name

        # Find and test if Arduino is responding
        logging.info("Initiating Arduino")
        self.ARDUINO = self.define_arduino_port()

        self.save_hdf5_arduino_sensors(trailing_string="init")

        # Log metadata to promt
        self.log_metadata()

        # Store metadata in txt file for easy access by us
        self.save_txt_sample_rack_no()

        self.vial_position_number = self.get_vial_position_number(2, 0)

        # Store metadata in HDF5 file
        self.save_hdf5_metadata()

        # Save sample number to make sure we don't process it again ever
        self.save_txt_sample_no(self.sample_rack_no)

        # Drain ecell
        self.controller.dispense_ml("Drain", 15)

        # Fill ecell with electrolyte
        self.dispense_electrolyte(volume_of_ecell=9)

        # Check for reference electrode drift
        (
            self.pt_peak_intial_ohmic_corr,
            self.pt_peak_accepted_ohmic_corr,
            self.ohmic_resistance_pt,
            self.reference_electrode_rest_time,
        ) = check_for_reference_electrode_drift(
            controller=self.controller,
            group_name=self.group_name,
            lower_limit_pt_pot=self.accept_lower_limit_pt_pot,
            upper_limit_pt_pot=self.accept_upper_limit_pt_pot,
            uid=self.uid,
        )

        # Move the sample into the ecell
        self.sample_to_ecell_and_clean()

        # clean it with ultrasound and activation
        self.clean_and_activate_sample()

        # Check if sample has ohmic resistance lower than threshold
        if (
            self.check_ohmic_resistance(
                group_name=self.group_name,
                threshold_ohmic_resistance=3.0,
            )
            is True
        ):
            logging.info("Ohmic resistance is below threshold. Continuing with experiment.")

            # Perform electrochemical measurements
            self.save_hdf5_arduino_sensors(trailing_string="start")
            [
                self.corrected_potential_at_10_mA,
                self.ohmic_resistance,
            ] = electrochemical_measurements(
                group_name=self.group_name,
                unique_id=self.uid,
                controller=self.controller,
                ultrasound=self.ultrasound_during_experiment,
            )
            self.save_hdf5_arduino_sensors(trailing_string="end")

            # Remove sample from cell
            self.remove_sample_from_ecell()

            # Log the potential of the reference electrode
            self.pt_peak_post_measurements = get_reference_electrode_potential(
                self.group_name, self.ohmic_resistance_pt
            )
            self.controller.dispense_ml("Drain", 12)

            # Cleanup ecell
            self.clean_ecell(
                vol=11.5,
                delay=5,
                num_flush=2,
            )

            # Save data in a readable file (even though it has already been stored to HDF5)
            self.save_csv_dataset(
                "keyParameters",
                [
                    "Unique ID",
                    "Current [A]",
                    "Raw potential [V]",
                    "Corrected potential [V]",
                    "Resistivity [ohm]",
                ],
            )

            # End time of experiment
            self.end_time = time.time()

            self.send_mail_results()
            logging.info("Done. Ready for next sample.")

        else:  # Overpotential larger than threshold
            logging.warning("Ohmic resistance is above threshold. Skipping sample.")

            # Cleanup ecell
            self.remove_sample_from_ecell()
            self.clean_ecell(
                vol=11.5,
                delay=5,
                num_flush=2,
            )

            # Delete group from HDF5 file
            logging.warning("Deleting group from HDF5 file")
            with h5py.File(HDF5_FILE, "a") as f:
                del f[self.group_name]

            self.corrected_potential_at_10_mA = 999.99
            self.ohmic_resistance = 999.99

        # Define concentration of electrolyte
        logging.info("Filling ecell with electrolyte to not leave it empty.")
        self.dispense_electrolyte(volume_of_ecell=9)
