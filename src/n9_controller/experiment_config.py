"""
experiment_config.py
====================
Loads and validates the experiment.yaml specification file.

experiment.yaml defines what samples to use, which dyes, scanning schedules,
test-cell protocols, and the ordered list of high-level experiment steps.

Example usage:
    config = load_experiment("experiment.yaml")
    print(config.experiment_id)
    for step in config.steps:
        print(step)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import yaml


# ── Valid experiment step names ───────────────────────────────────────────────

VALID_STEPS: frozenset[str] = frozenset({
    "home_robot",
    "load_samples_to_pcb",
    "dispense_dye_to_pcb",
    "start_colour_scanning",
    "run_test_cell_experiments",
    "wait_for_colour_scanning",
    "post_colour_test_cell",
    "return_all_to_holder",
    "report_cleaning_needed",
})


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SampleSpec:
    """One group of samples to be used in the experiment."""
    sample_type: str    # e.g. "nickel_100ppm"
    dye_type: str       # e.g. "congo_red"
    count: int          # how many of this type to pull from the holder


@dataclass(frozen=True)
class ScanningConfig:
    """Colour scanning schedule."""
    interval_minutes: float     # time between successive full board scans
    total_duration_hours: float # total colour experiment duration


@dataclass(frozen=True)
class DispenseConfig:
    """Dye dispense settings."""
    volume_ul: float            # volume per well in microlitres


@dataclass(frozen=True)
class TestCellSampleSpec:
    """Sample selection for test-cell experiments."""
    sample_type: str
    count: int


@dataclass(frozen=True)
class TestCellConfig:
    """Test-cell experiment settings."""
    enabled: bool
    protocol: str                           # placeholder protocol identifier
    samples: list[TestCellSampleSpec]       # which sample types to run through test cell


@dataclass(frozen=True)
class OutputConfig:
    """Output paths and flags."""
    cleaning_report_path: str = "data/cleaning_report.txt"


@dataclass(frozen=True)
class ExperimentConfig:
    """
    Full specification for one experiment run, loaded from experiment.yaml.

    Steps define the ordered sequence of actions that ExperimentRunner will
    execute. Valid step names:
        home_robot
        load_samples_to_pcb
        dispense_dye_to_pcb
        start_colour_scanning
        run_test_cell_experiments
        wait_for_colour_scanning
        post_colour_test_cell
        return_all_to_holder
        report_cleaning_needed
    """
    experiment_id: str
    description: str
    pcb_boards: list[str]           # pcb_ids from config.yaml
    sample_holders: list[str]       # holder_ids from config.yaml
    samples: list[SampleSpec]
    scanning: ScanningConfig
    dispense: DispenseConfig
    test_cell_experiment: TestCellConfig
    steps: list[str]
    output: OutputConfig
    holder_state_path: str          # path to holder_state.json


def load_experiment(path: str) -> ExperimentConfig:
    """
    Parse and validate an experiment.yaml file.

    Args:
        path: Path to the experiment.yaml file.

    Returns:
        Validated ExperimentConfig instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If required fields are missing or invalid.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"experiment.yaml not found at '{path}'.")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    # experiment_id defaults to current UTC timestamp
    experiment_id = str(raw.get(
        "experiment_id",
        datetime.now(timezone.utc).strftime("exp-%Y%m%d-%H%M%S")
    ))

    description = str(raw.get("description", ""))

    pcb_boards = [str(x) for x in raw.get("pcb_boards", [])]
    if not pcb_boards:
        raise ValueError("experiment.yaml must specify at least one entry in 'pcb_boards'.")

    sample_holders = [str(x) for x in raw.get("sample_holders", [])]
    if not sample_holders:
        raise ValueError("experiment.yaml must specify at least one entry in 'sample_holders'.")

    # Samples
    raw_samples = raw.get("samples", [])
    if not raw_samples:
        raise ValueError("experiment.yaml must define at least one entry in 'samples'.")
    samples = [
        SampleSpec(
            sample_type=str(s["sample_type"]),
            dye_type=str(s["dye_type"]),
            count=int(s["count"]),
        )
        for s in raw_samples
    ]

    # Scanning
    sc = raw.get("scanning", {})
    scanning = ScanningConfig(
        interval_minutes=float(sc.get("interval_minutes", 30.0)),
        total_duration_hours=float(sc.get("total_duration_hours", 24.0)),
    )

    # Dispense
    dc = raw.get("dispense", {})
    dispense = DispenseConfig(
        volume_ul=float(dc.get("volume_ul", 50.0)),
    )

    # Test cell
    tc = raw.get("test_cell_experiment", {})
    tc_samples = [
        TestCellSampleSpec(
            sample_type=str(s["sample_type"]),
            count=int(s["count"]),
        )
        for s in tc.get("samples", [])
    ]
    test_cell = TestCellConfig(
        enabled=bool(tc.get("enabled", False)),
        protocol=str(tc.get("protocol", "placeholder")),
        samples=tc_samples,
    )

    # Steps
    raw_steps = raw.get("steps", [])
    steps = [str(s["action"]) if isinstance(s, dict) else str(s) for s in raw_steps]
    bad_steps = [s for s in steps if s not in VALID_STEPS]
    if bad_steps:
        raise ValueError(
            f"Unknown experiment step(s): {bad_steps}. "
            f"Valid steps: {sorted(VALID_STEPS)}"
        )

    # Output
    oc = raw.get("output", {})
    output = OutputConfig(
        cleaning_report_path=str(oc.get("cleaning_report_path", "data/cleaning_report.txt")),
    )

    # Holder state init file
    holder_state_path = str(raw.get("holder_state_path", "holder_state.json"))

    return ExperimentConfig(
        experiment_id=experiment_id,
        description=description,
        pcb_boards=pcb_boards,
        sample_holders=sample_holders,
        samples=samples,
        scanning=scanning,
        dispense=dispense,
        test_cell_experiment=test_cell,
        steps=steps,
        output=output,
        holder_state_path=holder_state_path,
    )
