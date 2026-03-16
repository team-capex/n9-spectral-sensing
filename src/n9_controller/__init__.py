"""
n9_controller
=============
Robot automation layer for the N9 North Robotics platform, integrating with
the spectral_board_manager package to run autonomous multi-day experiments.

Key classes:
    N9RobotController     - wraps the 'north' API (robot.py)
    PumpController        - peristaltic pump and digital output control (pump_controller.py)
    LiquidDispenser       - placeholder for dispenser hardware (dispenser.py)
    CoordinateMap         - converts grid positions to robot XYZ (coordinate_map.py)
    LegacySampleRackLayout - layout for the legacy white sample rack
    ExperimentState       - state machines for PCB/holder/rack tracking (state_machine.py)
    ExperimentConfig      - loads experiment.yaml (experiment_config.py)
    ExperimentRunner      - orchestrates the full workflow (experiment_runner.py)
"""

from n9_controller.coordinate_map import CoordinateMap, LegacySampleRackLayout
from n9_controller.robot import N9RobotController
from n9_controller.dispenser import LiquidDispenser
from n9_controller.pump_controller import PumpController
from n9_controller.state_machine import (
    ExperimentState,
    PCBSensorState,
    HolderSlotState,
    LegacyRackSlotState,
    SampleRecord,
    PCBSensorRecord,
    HolderSlotRecord,
    LegacyRackSlotRecord,
)
from n9_controller.experiment_config import ExperimentConfig, load_experiment
from n9_controller.experiment_runner import ExperimentRunner

__all__ = [
    "CoordinateMap",
    "LegacySampleRackLayout",
    "N9RobotController",
    "PumpController",
    "LiquidDispenser",
    "ExperimentState",
    "PCBSensorState",
    "HolderSlotState",
    "LegacyRackSlotState",
    "SampleRecord",
    "PCBSensorRecord",
    "HolderSlotRecord",
    "LegacyRackSlotRecord",
    "ExperimentConfig",
    "load_experiment",
    "ExperimentRunner",
]
