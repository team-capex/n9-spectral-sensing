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


# ── Valid experiment step names ──────────────────────────────────────────────

VALID_STEPS: frozenset[str] = frozenset({
    "home_robot",
    "load_samples_to_pcb",
    "load_from_sample_holders_to_pcb",
    "create_mixture",
    "prime_mixture",
    "add_mixture_to_pcb",
    "deprime_mixture",
    "start_colour_scanning",
    "run_test_cell_loop",
    "wait_for_colour_scanning",
    "wait_for_pcb_temperature",
    "return_all_to_holder",
    "report_cleaning_needed",
})


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SampleSpec:
    """One group of samples to be used in the experiment."""
    sample_type: str            # e.g. "PC" or "Ni"
    count: int                  # how many of this type to use
    source: str = "holder"      # currently only "holder" is supported
    destination: str = "pcb"    # "pcb" | "test_cell"
    # dye to dispense (empty if pre-filled or test cell)
    dye_type: str = ""


@dataclass(frozen=True)
class ScanningConfig:
    """Colour scanning schedule."""
    # time between successive full board scans (0 = continuous)
    interval_minutes: float
    # total colour experiment duration (0 = until stopped)
    total_duration_hours: float
    # True = wait for boards to reach target temp before scanning
    temperature_control: bool = False


@dataclass(frozen=True)
class TestCellLoopConfig:
    """Settings for the test cell sample loop (run_test_cell_loop step).

    Hardware position is read from config.yaml test_cell section.
    These parameters control the fill/drain cycle for each sample.
    """
    fill_pump: str           # peristaltic pump name (e.g. "H2O_VIAL")
    fill_volume_ml: float    # volume to fill the cell (mL)
    drain_volume_ml: float   # volume to empty the cell (mL)
    wait_time_s: float       # seconds to hold sample in filled cell
    drain_pump: str = "Drain"  # peristaltic pump name to drain


@dataclass(frozen=True)
class MixtureConfig:
    """Dye mixture preparation parameters (from experiment.yaml mixture:)."""
    water_ml: float
    dye1_ml: float
    dye2_ml: float
    dose_volume_ml: float = 0.2     # fixed per-well dispense volume (ml)


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
        load_from_sample_holders_to_pcb
        create_mixture
        prime_mixture
        add_mixture_to_pcb
        deprime_mixture
        start_colour_scanning
        run_test_cell_loop
        wait_for_colour_scanning
        wait_for_pcb_temperature
        return_all_to_holder
        report_cleaning_needed
    """
    experiment_id: str
    description: str
    sensing_stations: list[str]         # sensing station ids from config.yaml
    sample_holders: list[str]           # holder_ids from config.yaml
    samples: list[SampleSpec]
    scanning: ScanningConfig
    test_cell_config: Optional[TestCellLoopConfig]
    steps: list[str]
    output: OutputConfig
    holder_state_path: str              # path to holder_state.json
    # dye mixture config; required for mixture steps
    mixture: Optional[MixtureConfig] = None


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

    sensing_stations = [str(x) for x in raw.get("sensing_stations", [])]
    if not sensing_stations:
        raise ValueError(
            "experiment.yaml must specify at least one "
            "entry in 'sensing_stations'."
        )

    sample_holders = [str(x) for x in raw.get("sample_holders", [])]

    # Samples
    raw_samples = raw.get("samples", [])
    if not raw_samples:
        raise ValueError(
            "experiment.yaml must define at least one entry in 'samples'."
        )
    samples = [
        SampleSpec(
            sample_type=str(s["sample_type"]),
            count=int(s["count"]),
            source=str(s.get("source", "holder")),
            destination=str(s.get("destination", "pcb")),
            dye_type=str(s.get("dye_type", "")),
        )
        for s in raw_samples
    ]

    # Scanning
    sc = raw.get("scanning", {})
    scanning = ScanningConfig(
        interval_minutes=float(sc.get("interval_minutes", 30.0)),
        total_duration_hours=float(sc.get("total_duration_hours", 24.0)),
        temperature_control=bool(sc.get("temperature_control", False)),
    )

    # Steps
    raw_steps = raw.get("steps", [])
    steps = [
        str(s["action"]) if isinstance(s, dict) else str(s)
        for s in raw_steps
    ]
    bad_steps = [s for s in steps if s not in VALID_STEPS]
    if bad_steps:
        raise ValueError(
            f"Unknown experiment step(s): {bad_steps}. "
            f"Valid steps: {sorted(VALID_STEPS)}"
        )

    # Output
    oc = raw.get("output", {})
    output = OutputConfig(
        cleaning_report_path=str(
            oc.get("cleaning_report_path", "data/cleaning_report.txt")
        ),
    )

    # Test cell loop config
    tcc = raw.get("test_cell_config")
    test_cell_config: Optional[TestCellLoopConfig] = None
    if tcc:
        test_cell_config = TestCellLoopConfig(
            fill_pump=str(tcc.get("fill_pump", "H2O_VIAL")),
            fill_volume_ml=float(tcc.get("fill_volume_ml", 5.0)),
            drain_volume_ml=float(tcc.get("drain_volume_ml", 5.0)),
            wait_time_s=float(tcc.get("wait_time_s", 60.0)),
            drain_pump=str(tcc.get("drain_pump", "Drain")),
        )

    # State init file path
    holder_state_path = str(raw.get("holder_state_path", "holder_state.json"))

    # Dye mixture config
    mx = raw.get("mixture")
    mixture: Optional[MixtureConfig] = None
    if mx:
        mixture = MixtureConfig(
            water_ml=float(mx["water_ml"]),
            dye1_ml=float(mx["dye1_ml"]),
            dye2_ml=float(mx["dye2_ml"]),
            dose_volume_ml=float(mx.get("dose_volume_ml", 0.2)),
        )

    return ExperimentConfig(
        experiment_id=experiment_id,
        description=description,
        sensing_stations=sensing_stations,
        sample_holders=sample_holders,
        samples=samples,
        scanning=scanning,
        test_cell_config=test_cell_config,
        steps=steps,
        output=output,
        holder_state_path=holder_state_path,
        mixture=mixture,
    )
