"""
n9_controller
=============
Robot automation layer for the N9 North Robotics platform, integrating with
the spectral_board_manager package to run autonomous multi-day experiments.

Key classes:
    N9RobotController  - wraps the 'north' API (robot.py)
    PumpController     - peristaltic pump and digital output control (pump_controller.py)
    CoordinateMap      - converts grid positions to robot XYZ (coordinate_map.py)
    ExperimentState    - state machines for PCB/holder tracking (state_machine.py)
    ExperimentConfig   - loads experiment.yaml (experiment_config.py)
    ExperimentRunner   - orchestrates the full workflow (experiment_runner.py)
"""

from n9_controller.coordinate_map import CoordinateMap
from n9_controller.robot import N9RobotController
from n9_controller.pump_controller import PumpController
from n9_controller.state_machine import (
    ExperimentState,
    PCBSensorState,
    HolderSlotState,
    SampleRecord,
    PCBSensorRecord,
    HolderSlotRecord,
)
from n9_controller.experiment_config import ExperimentConfig, load_experiment
from n9_controller.experiment_runner import ExperimentRunner

__all__ = [
    "CoordinateMap",
    "N9RobotController",
    "PumpController",
    "ExperimentState",
    "PCBSensorState",
    "HolderSlotState",
    "SampleRecord",
    "PCBSensorRecord",
    "HolderSlotRecord",
    "ExperimentConfig",
    "load_experiment",
    "ExperimentRunner",
]
