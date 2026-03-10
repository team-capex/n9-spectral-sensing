"""
experiment_runner.py
====================
Orchestrates the full experiment workflow, coordinating:
  - N9 robot pick/place moves
  - Liquid dispenser
  - Periodic colour scanning (background thread)
  - Test-cell experiments (placeholder)
  - State machine updates + JSON persistence
  - Post-experiment reporting

Usage:
    runner = ExperimentRunner("config.yaml", "experiment.yaml")
    runner.run()

CLI entry point (registered in pyproject.toml):
    experiment-run --config config.yaml --experiment experiment.yaml [--resume]
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from typing import Optional

import yaml

from n9_controller.coordinate_map import CoordinateMap
from n9_controller.dispenser import LiquidDispenser
from n9_controller.experiment_config import ExperimentConfig, load_experiment
from n9_controller.robot import N9RobotController
from n9_controller.state_machine import (
    ExperimentState,
    HolderSlotState,
    PCBSensorState,
)
from spectral_board_manager.board_manager import BoardManager

logger = logging.getLogger(__name__)

_STATE_SUBDIR = "state"


class ExperimentRunner:
    """
    Executes an experiment defined in experiment.yaml.

    The runner reads config.yaml for hardware locations and robot settings,
    and experiment.yaml for which samples/dyes/steps to run.

    The step sequence in experiment.yaml controls which methods are called and
    in what order. Each named step maps to a method on this class.

    Args:
        config_path:     Path to config.yaml
        experiment_path: Path to experiment.yaml
        resume:          If True, load existing state from data/state/ instead
                         of initialising fresh state.
    """

    STEP_MAP: dict = {}   # populated after class definition

    def __init__(
        self,
        config_path: str,
        experiment_path: str,
        resume: bool = False,
    ) -> None:
        self.config_path = config_path
        self.experiment_path = experiment_path

        # Load raw config
        with open(config_path, encoding="utf-8") as f:
            self._raw_cfg: dict = yaml.safe_load(f)

        # Load experiment spec
        self.exp_cfg: ExperimentConfig = load_experiment(experiment_path)

        # State directory
        self._state_dir = os.path.join(
            self._raw_cfg.get("data_dir", "data"), _STATE_SUBDIR
        )

        # Build hardware abstraction layers
        robot_cfg = self._raw_cfg.get("robot", {})
        self.robot = N9RobotController(
            simulate=bool(robot_cfg.get("simulate", True)),
            safe_travel_z_mm=float(robot_cfg.get("safe_travel_z_mm", 80.0)),
        )

        dispenser_cfg = self._raw_cfg.get("dispenser", {})
        self.dispenser = LiquidDispenser(
            simulate=bool(dispenser_cfg.get("simulate", True)),
            config=dispenser_cfg,
        )

        self.coord_map = CoordinateMap.from_config(self._raw_cfg)

        # Spectral board manager (uses the same config.yaml)
        self.board_manager = BoardManager(config_path)
        self.board_manager.experiment_id = self.exp_cfg.experiment_id

        # Resolve board_id → pcb_id mapping
        self._board_to_pcb: dict[str, str] = {
            p["board_id"]: p["pcb_id"]
            for p in self._raw_cfg.get("pcb_boards", [])
        }

        # Initialise or resume experiment state
        holder_state_path = (
            self.exp_cfg.holder_state_path
            if os.path.exists(self.exp_cfg.holder_state_path)
            else None
        )

        if resume:
            logger.info("Resuming experiment state from %s", self._state_dir)
            self.state = ExperimentState.load(self._state_dir)
        else:
            logger.info("Initialising fresh experiment state for '%s'", self.exp_cfg.experiment_id)
            self.state = ExperimentState.new(
                experiment_id=self.exp_cfg.experiment_id,
                pcb_layouts=[
                    self.coord_map.pcb_layout(pid)
                    for pid in self.exp_cfg.pcb_boards
                ],
                holder_layouts=[
                    self.coord_map.holder_layout(hid)
                    for hid in self.exp_cfg.sample_holders
                ],
                holder_state_path=holder_state_path,
            )
            self.state.save(self._state_dir)

        # Scanning control
        self._scan_stop_event: Optional[threading.Event] = None
        self._scan_thread: Optional[threading.Thread] = None

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self) -> None:
        """Execute all steps defined in experiment.yaml in order."""
        logger.info(
            "Starting experiment '%s': %d steps",
            self.exp_cfg.experiment_id,
            len(self.exp_cfg.steps),
        )

        for step_name in self.exp_cfg.steps:
            method = self.STEP_MAP.get(step_name)
            if method is None:
                raise ValueError(f"No handler for experiment step '{step_name}'.")
            logger.info("── Step: %s ──", step_name)
            method(self)
            self.state.save(self._state_dir)

        self.state.completed = True
        self.state.save(self._state_dir)
        logger.info("Experiment '%s' complete.", self.exp_cfg.experiment_id)

    # ── Step implementations ──────────────────────────────────────────────────

    def home_robot(self) -> None:
        """Home the robot and dispenser."""
        self.robot.home()
        self.dispenser.home_dispenser()

    def load_samples_to_pcb(self) -> None:
        """
        For each sample spec in experiment.yaml:
          - Find N fresh holder slots of the requested type
          - Pick each sample and place it on a free PCB sensor slot
          - Update state machine
        """
        for spec in self.exp_cfg.samples:
            logger.info(
                "Loading %d × '%s' (dye: %s) to PCB",
                spec.count, spec.sample_type, spec.dye_type,
            )
            fresh_slots = self.state.get_fresh_samples(spec.sample_type, spec.count)
            free_pcb_slots = self.state.get_free_pcb_locations()

            if len(free_pcb_slots) < spec.count:
                raise RuntimeError(
                    f"Not enough free PCB slots: need {spec.count}, "
                    f"only {len(free_pcb_slots)} available."
                )

            for holder_slot, pcb_slot in zip(fresh_slots, free_pcb_slots[:spec.count]):
                sample_id = holder_slot.sample_id
                if sample_id is None:
                    raise RuntimeError(
                        f"Holder slot {holder_slot.location_key} has no sample_id. "
                        f"Check holder_state.json."
                    )

                from_xyz = self.coord_map.holder_slot_xyz(
                    holder_slot.holder_id, holder_slot.col, holder_slot.row
                )
                to_xyz = self.coord_map.pcb_sensor_xyz(
                    pcb_slot.pcb_id, pcb_slot.col, pcb_slot.row
                )

                logger.info(
                    "  %s: holder %s → PCB %s",
                    sample_id, holder_slot.location_key, pcb_slot.location_key,
                )
                self.robot.transfer(from_xyz, to_xyz)

                # Update state (also registers dye_type on the sample)
                self.state.load_sample_to_pcb(
                    sample_id=sample_id,
                    pcb_id=pcb_slot.pcb_id,
                    col=pcb_slot.col,
                    row=pcb_slot.row,
                    dye_type=spec.dye_type,
                )
                self.state.save(self._state_dir)

    def dispense_dye_to_pcb(self) -> None:
        """
        Dispense dye to all PCB slots in DYE_FILLED state.
        After dispensing, transitions the slot to EXPERIMENT_RUNNING.
        """
        self.dispenser.prime(self.exp_cfg.samples[0].dye_type if self.exp_cfg.samples else "")

        for rec in list(self.state.pcb_sensors.values()):
            if rec.state != PCBSensorState.DYE_FILLED:
                continue

            xyz = self.coord_map.pcb_dispense_xyz(rec.pcb_id, rec.col, rec.row)
            sample = self.state.samples.get(rec.current_sample_id or "")
            dye = sample.dye_type if sample else ""

            logger.info("  Dispensing '%s' to PCB slot %s", dye, rec.location_key)
            self.dispenser.dispense(
                volume_ul=self.exp_cfg.dispense.volume_ul,
                dye_type=dye,
                x=xyz[0], y=xyz[1], z=xyz[2],
            )
            self.state.save(self._state_dir)

        self.dispenser.flush()

        # Transition all loaded slots to EXPERIMENT_RUNNING
        self.state.start_all_loaded_experiments()

    def start_colour_scanning(self) -> None:
        """
        Launch a background thread that periodically runs BoardManager.run()
        with sample labels from the state machine.

        The thread runs until wait_for_colour_scanning() is called.
        """
        if self._scan_thread and self._scan_thread.is_alive():
            logger.warning("Colour scanning thread already running — not starting a second one.")
            return

        # Block until all boards have reached their target temperature (no-op if null)
        self.board_manager.wait_for_temperature()

        self._scan_stop_event = threading.Event()
        self._scan_thread = threading.Thread(
            target=self._scan_loop,
            args=(self._scan_stop_event,),
            name="colour-scan",
            daemon=True,
        )
        self._scan_thread.start()
        logger.info(
            "Colour scanning started (interval=%.1f min, duration=%.1f h)",
            self.exp_cfg.scanning.interval_minutes,
            self.exp_cfg.scanning.total_duration_hours,
        )

    def wait_for_colour_scanning(self) -> None:
        """
        Block until the colour scanning duration has elapsed, then stop the
        background thread and mark all running experiments as complete.
        """
        if self._scan_thread is None:
            logger.warning("wait_for_colour_scanning called but no scan thread is running.")
            return

        duration_s = self.exp_cfg.scanning.total_duration_hours * 3600.0
        logger.info(
            "Waiting %.1f hours for colour experiments to complete ...",
            self.exp_cfg.scanning.total_duration_hours,
        )
        self._scan_thread.join(timeout=duration_s)

        # Stop the background thread
        if self._scan_stop_event:
            self._scan_stop_event.set()
        if self._scan_thread.is_alive():
            self._scan_thread.join(timeout=30.0)

        self.state.complete_all_running_experiments()
        logger.info("Colour scanning complete. Total scans: %d", self.state.scan_count)

    def run_test_cell_experiments(self) -> None:
        """
        Run each requested sample type through the test cell one at a time.

        For each sample:
          1. Pick from PCB (or holder) → transfer to test cell
          2. Run test-cell protocol (placeholder)
          3. Return sample to its holder slot
        """
        tc_cfg = self.exp_cfg.test_cell_experiment
        if not tc_cfg.enabled:
            logger.info("Test-cell experiments disabled — skipping.")
            return

        test_xyz = self.coord_map.test_cell_xyz()

        for spec in tc_cfg.samples:
            logger.info(
                "Test cell: running %d × '%s' (protocol: %s)",
                spec.count, spec.sample_type, tc_cfg.protocol,
            )
            # Find FRESH samples still in holder (not yet moved to PCB)
            try:
                candidates = self.state.get_fresh_samples(spec.sample_type, spec.count)
            except ValueError:
                logger.warning(
                    "Not enough fresh '%s' samples for test cell — using whatever is available.",
                    spec.sample_type,
                )
                candidates = [
                    r for r in self.state.holder_slots.values()
                    if r.state == HolderSlotState.FRESH
                    and r.sample_type == spec.sample_type
                ][:spec.count]

            for holder_slot in candidates:
                sample_id = holder_slot.sample_id
                if sample_id is None:
                    continue

                from_xyz = self.coord_map.holder_slot_xyz(
                    holder_slot.holder_id, holder_slot.col, holder_slot.row
                )
                logger.info("  %s → test cell", sample_id)

                # Pick from holder, place in test cell
                self.robot.transfer(from_xyz, test_xyz)
                self.state.set_sample_in_test_cell(sample_id, True)
                self.state.save(self._state_dir)

                # Run protocol (placeholder)
                self._run_test_cell_protocol(sample_id, tc_cfg.protocol)

                # Return to holder
                logger.info("  %s → holder %s", sample_id, holder_slot.location_key)
                self.robot.transfer(test_xyz, from_xyz)
                self.state.set_sample_in_test_cell(sample_id, False)
                self.state.return_sample_to_holder(
                    sample_id,
                    holder_slot.holder_id,
                    holder_slot.col,
                    holder_slot.row,
                )
                self.state.save(self._state_dir)

    def post_colour_test_cell(self) -> None:
        """
        After colour experiments are complete, move each used PCB sample
        through the test cell for a quick electrochemical test before
        returning it to the holder.

        Placeholder: moves samples but the protocol is not yet defined.
        """
        tc_cfg = self.exp_cfg.test_cell_experiment
        if not tc_cfg.enabled:
            logger.info("Test-cell post-colour experiments disabled — skipping.")
            return

        test_xyz = self.coord_map.test_cell_xyz()
        complete_slots = self.state.get_complete_experiments()
        logger.info("Post-colour test cell: %d samples to process", len(complete_slots))

        for pcb_rec in complete_slots:
            sample_id = pcb_rec.current_sample_id
            if sample_id is None:
                continue
            sample = self.state.samples.get(sample_id)
            if sample is None:
                continue

            pcb_xyz = self.coord_map.pcb_sensor_xyz(pcb_rec.pcb_id, pcb_rec.col, pcb_rec.row)
            holder_xyz = self.coord_map.holder_slot_xyz(
                sample.holder_id, sample.holder_col, sample.holder_row
            )

            # PCB → test cell
            logger.info("  %s: PCB %s → test cell", sample_id, pcb_rec.location_key)
            self.robot.transfer(pcb_xyz, test_xyz)
            self.state.remove_sample_from_pcb(pcb_rec.pcb_id, pcb_rec.col, pcb_rec.row)
            self.state.set_sample_in_test_cell(sample_id, True)
            self.state.save(self._state_dir)

            # Run protocol
            self._run_test_cell_protocol(sample_id, tc_cfg.protocol)

            # Test cell → holder
            logger.info("  %s: test cell → holder %s", sample_id, sample.holder_id)
            self.robot.transfer(test_xyz, holder_xyz)
            self.state.set_sample_in_test_cell(sample_id, False)
            self.state.return_sample_to_holder(
                sample_id,
                sample.holder_id,
                sample.holder_col,
                sample.holder_row,
            )
            self.state.save(self._state_dir)

    def return_all_to_holder(self) -> None:
        """
        Return all remaining PCB samples (EXPERIMENT_COMPLETE or EXPERIMENT_RUNNING)
        directly to their holder slots, without passing through the test cell.
        """
        complete = (
            self.state.get_complete_experiments()
            + self.state.get_running_experiments()
        )
        logger.info("Returning %d samples to holder ...", len(complete))

        for pcb_rec in complete:
            sample_id = pcb_rec.current_sample_id
            if sample_id is None:
                continue
            sample = self.state.samples.get(sample_id)
            if sample is None:
                continue

            pcb_xyz = self.coord_map.pcb_sensor_xyz(pcb_rec.pcb_id, pcb_rec.col, pcb_rec.row)
            holder_xyz = self.coord_map.holder_slot_xyz(
                sample.holder_id, sample.holder_col, sample.holder_row
            )

            logger.info("  %s: PCB %s → holder", sample_id, pcb_rec.location_key)
            self.robot.transfer(pcb_xyz, holder_xyz)
            self.state.remove_sample_from_pcb(pcb_rec.pcb_id, pcb_rec.col, pcb_rec.row)
            self.state.return_sample_to_holder(
                sample_id,
                sample.holder_id,
                sample.holder_col,
                sample.holder_row,
            )
            self.state.save(self._state_dir)

    def report_cleaning_needed(self) -> None:
        """
        Write a cleaning report listing all locations that need cleaning and
        print a summary to stdout.

        Dirty PCB slots:   EMPTY_DIRTY or SAMPLE_REMOVED  → need dye wash
        Dirty holder slots: USED                           → need sample clean
        """
        dirty_pcb = self.state.get_dirty_pcb_locations()
        dirty_holders = self.state.get_dirty_holder_slots()

        lines: list[str] = [
            f"=== Cleaning Report — Experiment: {self.state.experiment_id} ===",
            "",
            f"PCB slots needing cleaning ({len(dirty_pcb)} locations):",
        ]
        if dirty_pcb:
            for rec in sorted(dirty_pcb, key=lambda r: r.location_key):
                lines.append(f"  {rec.location_key}  [state: {rec.state.value}]")
        else:
            lines.append("  (none)")

        lines += [
            "",
            f"Sample holder slots needing cleaning ({len(dirty_holders)} locations):",
        ]
        if dirty_holders:
            for rec in sorted(dirty_holders, key=lambda r: r.location_key):
                lines.append(
                    f"  {rec.location_key}  sample: {rec.sample_id or 'unknown'}  "
                    f"type: {rec.sample_type or 'unknown'}"
                )
        else:
            lines.append("  (none)")

        report = "\n".join(lines)

        # Write to file
        report_path = self.exp_cfg.output.cleaning_report_path
        os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report + "\n")

        # Always print to console
        print(report)
        logger.info("Cleaning report written to %s", report_path)

    # ── Background scanning loop ───────────────────────────────────────────────

    def _scan_loop(self, stop_event: threading.Event) -> None:
        """
        Background thread: periodically runs BoardManager.run() with labels.

        Runs until stop_event is set or the configured duration elapses.
        """
        interval_s = self.exp_cfg.scanning.interval_minutes * 60.0
        duration_s = self.exp_cfg.scanning.total_duration_hours * 3600.0
        started_at = time.monotonic()

        while not stop_event.is_set():
            elapsed = time.monotonic() - started_at
            if elapsed >= duration_s:
                logger.info("Colour scan duration reached (%.1f h). Stopping scan loop.", elapsed / 3600)
                break

            scan_start = time.monotonic()
            try:
                # Build label map: {board_id: {sensor_no: {sample_id, sample_type, dye_type}}}
                sensor_labels: dict[str, dict[int, dict]] = {}
                for board_id, pcb_id in self._board_to_pcb.items():
                    if pcb_id in self.exp_cfg.pcb_boards:
                        sensor_labels[board_id] = self.state.get_labels_for_scan(pcb_id)

                self.board_manager.run(sensor_labels=sensor_labels)
                self.state.record_scan()
                self.state.save(self._state_dir)

                logger.info(
                    "Scan #%d complete. Elapsed: %.1f / %.1f h",
                    self.state.scan_count,
                    elapsed / 3600,
                    self.exp_cfg.scanning.total_duration_hours,
                )
            except Exception as exc:
                logger.error("Scan #%d failed: %s", self.state.scan_count + 1, exc)

            # Wait for next scan interval minus time already spent scanning (drift fix)
            scan_duration = time.monotonic() - scan_start
            stop_event.wait(timeout=max(0.0, interval_s - scan_duration))

    # ── Test cell protocol placeholder ─────────────────────────────────────────

    def _run_test_cell_protocol(self, sample_id: str, protocol: str) -> None:
        """
        Placeholder for test-cell electrochemical experimentation.

        Args:
            sample_id: ID of the sample currently in the test cell.
            protocol:  Protocol identifier string from experiment.yaml.

        Raises:
            NotImplementedError: Always raised with guidance on implementation.
        """
        raise NotImplementedError(
            f"Test-cell protocol '{protocol}' is not yet implemented. "
            f"Sample: '{sample_id}'. "
            f"To implement:\n"
            f"  1. Add hardware driver calls in this method.\n"
            f"  2. Replace or extend the protocol field in experiment.yaml.\n"
            f"  3. Remove this NotImplementedError once hardware is integrated.\n"
            f"To skip test-cell steps, set 'test_cell_experiment.enabled: false' "
            f"in experiment.yaml."
        )


# ── Step dispatch table ───────────────────────────────────────────────────────

ExperimentRunner.STEP_MAP = {
    "home_robot":               ExperimentRunner.home_robot,
    "load_samples_to_pcb":      ExperimentRunner.load_samples_to_pcb,
    "dispense_dye_to_pcb":      ExperimentRunner.dispense_dye_to_pcb,
    "start_colour_scanning":    ExperimentRunner.start_colour_scanning,
    "run_test_cell_experiments": ExperimentRunner.run_test_cell_experiments,
    "wait_for_colour_scanning": ExperimentRunner.wait_for_colour_scanning,
    "post_colour_test_cell":    ExperimentRunner.post_colour_test_cell,
    "return_all_to_holder":     ExperimentRunner.return_all_to_holder,
    "report_cleaning_needed":   ExperimentRunner.report_cleaning_needed,
}


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    """CLI: experiment-run"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Run an N9 robot experiment from experiment.yaml."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    parser.add_argument(
        "--experiment",
        default="experiment.yaml",
        help="Path to experiment.yaml (default: experiment.yaml)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a previously interrupted experiment (load existing state).",
    )
    args = parser.parse_args()

    runner = ExperimentRunner(
        config_path=args.config,
        experiment_path=args.experiment,
        resume=args.resume,
    )
    runner.run()


if __name__ == "__main__":
    main()
