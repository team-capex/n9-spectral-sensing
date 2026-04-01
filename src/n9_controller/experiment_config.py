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
    "load_from_legacy_rack_to_pcb",
    "load_from_sample_holders_to_pcb",
    "create_mixture",
    "prime_mixture",
    "add_mixture_to_pcb",
    "deprime_mixture",
    "start_colour_scanning",
    "run_test_cell_experiments",
    "run_ni_test_cell_loop",
    "wait_for_colour_scanning",
    "post_colour_test_cell",
    "return_all_to_holder",
    "report_cleaning_needed",
})


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SampleSpec:
    """One group of samples to be used in the experiment."""
    sample_type: str            # e.g. "PC" or "Ni"
    count: int                  # how many of this type to use
    source: str = "holder"      # "holder" | legacy rack id (e.g. "legacy-rack-1")
    destination: str = "pcb"    # "pcb" | "test_cell"
    dye_type: str = ""          # dye to dispense (empty if pre-filled or test cell)


@dataclass(frozen=True)
class ScanningConfig:
    """Colour scanning schedule."""
    interval_minutes: float     # time between successive full board scans (0 = continuous)
    total_duration_hours: float # total colour experiment duration (0 = until stopped)
    temperature_control: bool = False  # True = wait for boards to reach target temp


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
class TestCellDemoConfig:
    """Settings for the demo Ni-strip test cell loop."""
    fill_pump: str          # peristaltic pump name to fill the cell (e.g. "H2O_ECELL")
    fill_volume_ml: float   # volume to fill the cell (mL)
    drain_volume_ml: float  # volume to empty the cell (mL)
    wait_time_s: float      # how long to hold the sample in the filled cell (seconds)
    drain_pump: str = "Drain"  # peristaltic pump name to drain the cell


@dataclass(frozen=True)
class MixtureConfig:
    """Dye mixture preparation parameters (from experiment.yaml mixture: section)."""
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
        load_from_legacy_rack_to_pcb
        load_from_sample_holders_to_pcb
        create_mixture
        prime_mixture
        add_mixture_to_pcb
        deprime_mixture
        start_colour_scanning
        run_test_cell_experiments
        run_ni_test_cell_loop
        wait_for_colour_scanning
        post_colour_test_cell
        return_all_to_holder
        report_cleaning_needed
    """
    experiment_id: str
    description: str
    sensing_stations: list[str]         # sensing station ids from config.yaml
    sample_holders: list[str]           # holder_ids from config.yaml
    legacy_racks: list[str]             # legacy rack ids from config.yaml
    samples: list[SampleSpec]
    scanning: ScanningConfig
    test_cell_experiment: TestCellConfig
    test_cell_demo: Optional[TestCellDemoConfig]
    steps: list[str]
    output: OutputConfig
    holder_state_path: str              # path to holder_state.json
    legacy_rack_state_path: str         # path to legacy_rack_state.json
    mixture: Optional[MixtureConfig] = None  # dye mixture config; required for mixture steps


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
        raise ValueError("experiment.yaml must specify at least one entry in 'sensing_stations'.")

    sample_holders = [str(x) for x in raw.get("sample_holders", [])]
    # sample_holders may be empty (e.g. demo uses legacy rack only)

    legacy_racks = [str(x) for x in raw.get("legacy_racks", [])]

    # Samples
    raw_samples = raw.get("samples", [])
    if not raw_samples:
        raise ValueError("experiment.yaml must define at least one entry in 'samples'.")
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

    # Test cell demo (Ni strip loop)
    tcd = raw.get("test_cell_demo")
    test_cell_demo: Optional[TestCellDemoConfig] = None
    if tcd:
        test_cell_demo = TestCellDemoConfig(
            fill_pump=str(tcd.get("fill_pump", "H2O_ECELL")),
            fill_volume_ml=float(tcd.get("fill_volume_ml", 5.0)),
            drain_volume_ml=float(tcd.get("drain_volume_ml", 5.0)),
            wait_time_s=float(tcd.get("wait_time_s", 60.0)),
            drain_pump=str(tcd.get("drain_pump", "Drain")),
        )

    # State init file paths
    holder_state_path = str(raw.get("holder_state_path", "holder_state.json"))
    legacy_rack_state_path = str(raw.get("legacy_rack_state_path", "legacy_rack_state.json"))

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
        legacy_racks=legacy_racks,
        samples=samples,
        scanning=scanning,
        test_cell_experiment=test_cell,
        test_cell_demo=test_cell_demo,
        steps=steps,
        output=output,
        holder_state_path=holder_state_path,
        legacy_rack_state_path=legacy_rack_state_path,
        mixture=mixture,
    )
