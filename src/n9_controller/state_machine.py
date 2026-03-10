"""
state_machine.py
================
State tracking for all physical locations in the experiment workspace.

Two state machines run in parallel:

1. PCB sensor slots (16 per board)
   States: EMPTY_CLEAN → DYE_FILLED → EXPERIMENT_RUNNING → EXPERIMENT_COMPLETE
           → SAMPLE_REMOVED → EMPTY_DIRTY

2. Sample holder slots (90 per holder, 5×18 grid)
   States: FRESH | EMPTY | USED | CLEAN

Sample records track individual samples through their full lifecycle (from
holder pick through PCB/test-cell experiments back to holder return).

All state is persisted as JSON in data/state/ so experiments survive
multi-day process restarts. Writes are atomic (temp file + rename).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

_STATE_FILE = "experiment_state.json"
_BAK_FILE = "experiment_state.json.bak"


# ── Enums ─────────────────────────────────────────────────────────────────────

class PCBSensorState(str, Enum):
    """Lifecycle states for a single sensor well on a PCB board."""
    EMPTY_CLEAN         = "EMPTY_CLEAN"         # Clean, ready to receive a sample
    DYE_FILLED          = "DYE_FILLED"           # Sample loaded and dye dispensed; scan not yet started
    EXPERIMENT_RUNNING  = "EXPERIMENT_RUNNING"   # Actively being colour-scanned
    EXPERIMENT_COMPLETE = "EXPERIMENT_COMPLETE"  # Scan duration elapsed; sample+dye still present
    SAMPLE_REMOVED      = "SAMPLE_REMOVED"       # Sample returned to holder; dye residue remains
    EMPTY_DIRTY         = "EMPTY_DIRTY"          # All material removed; needs cleaning before reuse


class HolderSlotState(str, Enum):
    """Lifecycle states for a single slot in a sample holder."""
    FRESH   = "FRESH"   # Contains a new, unused sample
    EMPTY   = "EMPTY"   # No sample present (removed for experiment or never filled)
    USED    = "USED"    # Sample returned after experiment; may have dye contamination
    CLEAN   = "CLEAN"   # Cleaned and ready for reuse or re-loading


# ── Records ───────────────────────────────────────────────────────────────────

@dataclass
class SampleRecord:
    """
    Tracks one physical sample through its entire lifecycle.

    sample_id is derived from its original holder location:
        e.g. "holder-1_c02_r05"
    """
    sample_id: str
    sample_type: str                            # e.g. "nickel_100ppm"
    dye_type: str                               # e.g. "congo_red"
    holder_id: str
    holder_col: int
    holder_row: int
    pcb_id: Optional[str]           = None
    pcb_col: Optional[int]          = None
    pcb_row: Optional[int]          = None
    placed_at: Optional[str]        = None      # ISO timestamp: when placed on PCB
    dye_dispensed_at: Optional[str] = None      # ISO timestamp: when dye was dispensed
    scan_started_at: Optional[str]  = None      # ISO timestamp: when scanning began
    scan_completed_at: Optional[str] = None     # ISO timestamp: when scanning completed
    returned_at: Optional[str]      = None      # ISO timestamp: when returned to holder
    in_test_cell: bool              = False     # True while sample is in the test cell

    def csv_labels(self) -> dict:
        """Return the label dict passed to SpectralAnalysis.parse_new_data()."""
        return {
            "sample_id":   self.sample_id,
            "sample_type": self.sample_type,
            "dye_type":    self.dye_type,
        }


@dataclass
class PCBSensorRecord:
    """State of one physical sensor well on a PCB."""
    pcb_id: str
    col: int
    row: int
    state: PCBSensorState           = PCBSensorState.EMPTY_CLEAN
    current_sample_id: Optional[str] = None
    last_updated: Optional[str]     = None     # ISO timestamp

    @property
    def location_key(self) -> str:
        return f"{self.pcb_id}_c{self.col}_r{self.row}"

    @property
    def sensor_no(self) -> int:
        """Convert (col, row) back to 1-indexed sensor number."""
        return self.row * 2 + self.col + 1


@dataclass
class HolderSlotRecord:
    """State of one slot in a sample holder."""
    holder_id: str
    col: int
    row: int
    state: HolderSlotState          = HolderSlotState.EMPTY
    sample_id: Optional[str]        = None
    sample_type: Optional[str]      = None
    last_updated: Optional[str]     = None

    @property
    def location_key(self) -> str:
        return f"{self.holder_id}_c{self.col}_r{self.row}"

    @property
    def slot_no(self) -> int:
        """Convert (col, row) back to 1-indexed slot number (5 cols)."""
        return self.row * 5 + self.col + 1


# ── Main state container ──────────────────────────────────────────────────────

@dataclass
class ExperimentState:
    """
    Complete state for one running experiment.

    Persists to/from JSON so that process restarts mid-experiment are safe.

    Keys for the three dicts:
        pcb_sensors  : "{pcb_id}_c{col}_r{row}"   e.g. "pcb-1_c0_r3"
        holder_slots : "{holder_id}_c{col}_r{row}" e.g. "holder-1_c2_r7"
        samples      : sample_id string            e.g. "holder-1_c02_r05"
    """

    experiment_id: str
    created_at: str
    pcb_sensors: dict[str, PCBSensorRecord]  = field(default_factory=dict)
    holder_slots: dict[str, HolderSlotRecord] = field(default_factory=dict)
    samples: dict[str, SampleRecord]          = field(default_factory=dict)
    scan_count: int                            = 0
    completed: bool                            = False

    def __post_init__(self) -> None:
        # Runtime reverse index: sample_id → holder slot key (not persisted).
        # Populated by _load_holder_init() and _state_from_dict(); updated on transitions.
        self._sample_to_holder: dict[str, str] = {}

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    def new(
        cls,
        experiment_id: str,
        pcb_layouts: "list[PCBBoardLayout]",
        holder_layouts: "list[SampleHolderLayout]",
        holder_state_path: Optional[str] = None,
    ) -> "ExperimentState":
        """
        Create a fresh ExperimentState.

        All PCB sensor slots start as EMPTY_CLEAN.
        Holder slots are seeded from holder_state_path (JSON) if provided;
        otherwise all slots default to EMPTY.

        holder_state_path JSON format:
        {
          "holder-1": [
            {"col": 0, "row": 0, "state": "FRESH",
             "sample_type": "nickel_100ppm",
             "sample_id": "holder-1_c0_r0"},
            ...
          ]
        }
        """
        state = cls(
            experiment_id=experiment_id,
            created_at=_now(),
        )

        # Initialise all PCB sensor slots
        for layout in pcb_layouts:
            for row in range(8):
                for col in range(2):
                    rec = PCBSensorRecord(pcb_id=layout.pcb_id, col=col, row=row)
                    state.pcb_sensors[rec.location_key] = rec

        # Initialise all holder slots (default EMPTY)
        for layout in holder_layouts:
            for row in range(layout.n_rows):
                for col in range(layout.n_cols):
                    rec = HolderSlotRecord(holder_id=layout.holder_id, col=col, row=row)
                    state.holder_slots[rec.location_key] = rec

        # Seed holder slots from JSON init file
        if holder_state_path:
            state._load_holder_init(holder_state_path)

        return state

    def _load_holder_init(self, path: str) -> None:
        """Seed holder slot states from the user-provided holder_state.json."""
        with open(path, encoding="utf-8") as f:
            data: dict[str, list[dict]] = json.load(f)

        for holder_id, slots in data.items():
            if not isinstance(slots, list):
                continue
            for s in slots:
                if not isinstance(s, dict) or "col" not in s or "row" not in s:
                    logger.warning("holder_state.json: skipping invalid slot entry: %s", s)
                    continue
                col = int(s["col"])
                row = int(s["row"])
                key = f"{holder_id}_c{col}_r{row}"
                if key not in self.holder_slots:
                    logger.warning("holder_state.json references unknown slot %s — skipping", key)
                    continue
                rec = self.holder_slots[key]
                rec.state = HolderSlotState(s.get("state", "FRESH"))
                rec.sample_type = s.get("sample_type")
                rec.sample_id = s.get("sample_id")
                rec.last_updated = _now()

                # Update reverse index
                if rec.sample_id:
                    self._sample_to_holder[rec.sample_id] = key

                # Register a SampleRecord for FRESH slots
                if rec.state == HolderSlotState.FRESH and rec.sample_id:
                    sample_type = rec.sample_type or "unknown"
                    if rec.sample_id not in self.samples:
                        self.samples[rec.sample_id] = SampleRecord(
                            sample_id=rec.sample_id,
                            sample_type=sample_type,
                            dye_type="",            # assigned later at dispense step
                            holder_id=holder_id,
                            holder_col=col,
                            holder_row=row,
                        )

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_free_pcb_locations(
        self, pcb_id: Optional[str] = None
    ) -> list[PCBSensorRecord]:
        """Return all EMPTY_CLEAN PCB sensor slots (optionally filtered by pcb_id)."""
        return [
            r for r in self.pcb_sensors.values()
            if r.state == PCBSensorState.EMPTY_CLEAN
            and (pcb_id is None or r.pcb_id == pcb_id)
        ]

    def get_fresh_samples(
        self, sample_type: str, n: int
    ) -> list[HolderSlotRecord]:
        """
        Return up to n FRESH holder slots of the requested sample_type.
        Raises ValueError if fewer than n are available.
        """
        matches = [
            r for r in self.holder_slots.values()
            if r.state == HolderSlotState.FRESH and r.sample_type == sample_type
        ]
        if len(matches) < n:
            raise ValueError(
                f"Not enough fresh '{sample_type}' samples: "
                f"requested {n}, available {len(matches)}."
            )
        return matches[:n]

    def get_dirty_pcb_locations(self) -> list[PCBSensorRecord]:
        """Return all PCB slots that need cleaning (EMPTY_DIRTY or SAMPLE_REMOVED)."""
        return [
            r for r in self.pcb_sensors.values()
            if r.state in (PCBSensorState.EMPTY_DIRTY, PCBSensorState.SAMPLE_REMOVED)
        ]

    def get_dirty_holder_slots(self) -> list[HolderSlotRecord]:
        """Return all USED holder slots (need cleaning before reuse)."""
        return [
            r for r in self.holder_slots.values()
            if r.state == HolderSlotState.USED
        ]

    def get_running_experiments(self) -> list[PCBSensorRecord]:
        """Return all PCB slots currently in EXPERIMENT_RUNNING state."""
        return [
            r for r in self.pcb_sensors.values()
            if r.state == PCBSensorState.EXPERIMENT_RUNNING
        ]

    def get_complete_experiments(self) -> list[PCBSensorRecord]:
        """Return all PCB slots in EXPERIMENT_COMPLETE state."""
        return [
            r for r in self.pcb_sensors.values()
            if r.state == PCBSensorState.EXPERIMENT_COMPLETE
        ]

    def get_labels_for_scan(self, pcb_id: str) -> dict[int, dict]:
        """
        Return per-sensor label dicts for CSV tagging during a scan.

        Returns:
            {sensor_no: {"sample_id": ..., "sample_type": ..., "dye_type": ...}}
            Only sensors with an active sample are included.
        """
        labels: dict[int, dict] = {}
        for rec in self.pcb_sensors.values():
            if rec.pcb_id != pcb_id:
                continue
            if rec.current_sample_id is None:
                continue
            sample = self.samples.get(rec.current_sample_id)
            if sample is None:
                continue
            labels[rec.sensor_no] = sample.csv_labels()
        return labels

    # ── State transitions ─────────────────────────────────────────────────────

    def load_sample_to_pcb(
        self,
        sample_id: str,
        pcb_id: str,
        col: int,
        row: int,
        dye_type: str,
    ) -> None:
        """
        Record that a sample has been placed on a PCB sensor slot and dye will
        be (or has been) dispensed. Transitions EMPTY_CLEAN → DYE_FILLED.
        """
        pcb_key = f"{pcb_id}_c{col}_r{row}"
        pcb_rec = self._get_pcb(pcb_key)
        holder_rec = self._find_holder_slot_for_sample(sample_id)

        if pcb_rec.state != PCBSensorState.EMPTY_CLEAN:
            raise ValueError(
                f"Cannot load sample: PCB slot {pcb_key} is in state "
                f"'{pcb_rec.state.value}' (expected EMPTY_CLEAN)."
            )

        # Update holder slot
        holder_rec.state = HolderSlotState.EMPTY
        holder_rec.sample_id = None
        holder_rec.last_updated = _now()
        self._sample_to_holder.pop(sample_id, None)

        # Update PCB slot
        pcb_rec.state = PCBSensorState.DYE_FILLED
        pcb_rec.current_sample_id = sample_id
        pcb_rec.last_updated = _now()

        # Update sample record
        sample = self.samples[sample_id]
        sample.dye_type = dye_type
        sample.pcb_id = pcb_id
        sample.pcb_col = col
        sample.pcb_row = row
        sample.placed_at = _now()
        sample.dye_dispensed_at = _now()

    def start_experiment(self, pcb_id: str, col: int, row: int) -> None:
        """
        Mark a PCB slot as actively scanning. Transitions DYE_FILLED → EXPERIMENT_RUNNING.
        """
        key = f"{pcb_id}_c{col}_r{row}"
        rec = self._get_pcb(key)
        if rec.state != PCBSensorState.DYE_FILLED:
            raise ValueError(
                f"Cannot start experiment: {key} is in state '{rec.state.value}' "
                f"(expected DYE_FILLED)."
            )
        rec.state = PCBSensorState.EXPERIMENT_RUNNING
        rec.last_updated = _now()
        if rec.current_sample_id:
            self.samples[rec.current_sample_id].scan_started_at = _now()

    def start_all_loaded_experiments(self, pcb_id: Optional[str] = None) -> None:
        """Convenience: start all DYE_FILLED slots (optionally filtered by pcb_id)."""
        for rec in self.pcb_sensors.values():
            if rec.state == PCBSensorState.DYE_FILLED:
                if pcb_id is None or rec.pcb_id == pcb_id:
                    self.start_experiment(rec.pcb_id, rec.col, rec.row)

    def record_scan(self) -> None:
        """Increment the global scan counter (called once per BoardManager.run())."""
        self.scan_count += 1

    def complete_experiment(self, pcb_id: str, col: int, row: int) -> None:
        """
        Mark scanning as complete for a slot.
        Transitions EXPERIMENT_RUNNING → EXPERIMENT_COMPLETE.
        """
        key = f"{pcb_id}_c{col}_r{row}"
        rec = self._get_pcb(key)
        if rec.state != PCBSensorState.EXPERIMENT_RUNNING:
            raise ValueError(
                f"Cannot complete: {key} is in state '{rec.state.value}' "
                f"(expected EXPERIMENT_RUNNING)."
            )
        rec.state = PCBSensorState.EXPERIMENT_COMPLETE
        rec.last_updated = _now()
        if rec.current_sample_id:
            self.samples[rec.current_sample_id].scan_completed_at = _now()

    def complete_all_running_experiments(self, pcb_id: Optional[str] = None) -> None:
        """Convenience: complete all EXPERIMENT_RUNNING slots."""
        for rec in list(self.pcb_sensors.values()):
            if rec.state == PCBSensorState.EXPERIMENT_RUNNING:
                if pcb_id is None or rec.pcb_id == pcb_id:
                    self.complete_experiment(rec.pcb_id, rec.col, rec.row)

    def remove_sample_from_pcb(self, pcb_id: str, col: int, row: int) -> str:
        """
        Record that a sample has been removed from a PCB slot back to the holder.
        Transitions EXPERIMENT_COMPLETE → SAMPLE_REMOVED.
        Returns the sample_id that was removed.
        """
        key = f"{pcb_id}_c{col}_r{row}"
        rec = self._get_pcb(key)
        if rec.state not in (
            PCBSensorState.EXPERIMENT_COMPLETE,
            PCBSensorState.EXPERIMENT_RUNNING,
        ):
            raise ValueError(
                f"Cannot remove sample: {key} is in state '{rec.state.value}'."
            )
        sample_id = rec.current_sample_id
        rec.state = PCBSensorState.SAMPLE_REMOVED
        rec.current_sample_id = None
        rec.last_updated = _now()
        return sample_id or ""

    def mark_pcb_dirty(self, pcb_id: str, col: int, row: int) -> None:
        """
        Mark a PCB slot as EMPTY_DIRTY (needs cleaning). Can be called from any state.
        """
        key = f"{pcb_id}_c{col}_r{row}"
        rec = self._get_pcb(key)
        rec.state = PCBSensorState.EMPTY_DIRTY
        rec.current_sample_id = None
        rec.last_updated = _now()

    def return_sample_to_holder(
        self,
        sample_id: str,
        holder_id: str,
        col: int,
        row: int,
    ) -> None:
        """
        Record that a sample has been returned to its holder slot.
        Transitions holder slot → USED.
        """
        holder_key = f"{holder_id}_c{col}_r{row}"
        holder_rec = self.holder_slots.get(holder_key)
        if holder_rec is None:
            raise KeyError(f"Holder slot {holder_key} not found in state.")
        if holder_rec.state != HolderSlotState.EMPTY:
            raise ValueError(
                f"Cannot return sample to {holder_key}: slot is in state "
                f"'{holder_rec.state.value}' (expected EMPTY)."
            )

        sample = self.samples.get(sample_id)

        holder_rec.state = HolderSlotState.USED
        holder_rec.sample_id = sample_id
        holder_rec.sample_type = sample.sample_type if sample else None
        holder_rec.last_updated = _now()
        self._sample_to_holder[sample_id] = holder_key

        if sample:
            sample.returned_at = _now()
            sample.holder_col = col
            sample.holder_row = row

    def set_sample_in_test_cell(self, sample_id: str, in_test_cell: bool) -> None:
        """Update test-cell residency flag for a sample."""
        sample = self.samples.get(sample_id)
        if sample is None:
            raise KeyError(f"Sample '{sample_id}' not found.")
        sample.in_test_cell = in_test_cell

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, state_dir: str) -> None:
        """
        Atomically save state to JSON.

        Writes to a .tmp file first, then renames to the target.
        A .bak copy of the previous state is kept for crash recovery.
        """
        os.makedirs(state_dir, exist_ok=True)
        target = os.path.join(state_dir, _STATE_FILE)
        bak    = os.path.join(state_dir, _BAK_FILE)

        payload = _state_to_dict(self)

        # Write to temp file in same directory (ensures atomic rename on same fs)
        fd, tmp_path = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

            # Rotate backup
            if os.path.exists(target):
                shutil.copy2(target, bak)

            os.replace(tmp_path, target)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        logger.debug("ExperimentState saved to %s (scan_count=%d)", target, self.scan_count)

    @classmethod
    def load(cls, state_dir: str) -> "ExperimentState":
        """
        Load persisted state from JSON.

        Falls back to .bak if the primary file is corrupt.
        """
        primary = os.path.join(state_dir, _STATE_FILE)
        bak     = os.path.join(state_dir, _BAK_FILE)

        for path in (primary, bak):
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                return _state_from_dict(data)
            except Exception as exc:
                logger.warning("Failed to load state from %s: %s", path, exc)

        raise FileNotFoundError(
            f"No valid experiment state found in '{state_dir}'. "
            f"Run ExperimentState.new() to create a fresh state."
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_pcb(self, key: str) -> PCBSensorRecord:
        rec = self.pcb_sensors.get(key)
        if rec is None:
            raise KeyError(f"PCB sensor slot '{key}' not found in state.")
        return rec

    def _find_holder_slot_for_sample(self, sample_id: str) -> HolderSlotRecord:
        key = self._sample_to_holder.get(sample_id)
        if key is None:
            raise KeyError(
                f"No holder slot found for sample '{sample_id}'. "
                f"Has it already been removed?"
            )
        return self.holder_slots[key]


# ── Serialisation helpers (private) ──────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_to_dict(state: ExperimentState) -> dict:
    return {
        "experiment_id": state.experiment_id,
        "created_at": state.created_at,
        "scan_count": state.scan_count,
        "completed": state.completed,
        "pcb_sensors": {
            k: {**asdict(v), "state": v.state.value}
            for k, v in state.pcb_sensors.items()
        },
        "holder_slots": {
            k: {**asdict(v), "state": v.state.value}
            for k, v in state.holder_slots.items()
        },
        "samples": {k: asdict(v) for k, v in state.samples.items()},
    }


def _state_from_dict(data: dict) -> ExperimentState:
    pcb_sensors = {
        k: PCBSensorRecord(
            pcb_id=v["pcb_id"],
            col=v["col"],
            row=v["row"],
            state=PCBSensorState(v["state"]),
            current_sample_id=v.get("current_sample_id"),
            last_updated=v.get("last_updated"),
        )
        for k, v in data.get("pcb_sensors", {}).items()
    }

    holder_slots = {
        k: HolderSlotRecord(
            holder_id=v["holder_id"],
            col=v["col"],
            row=v["row"],
            state=HolderSlotState(v["state"]),
            sample_id=v.get("sample_id"),
            sample_type=v.get("sample_type"),
            last_updated=v.get("last_updated"),
        )
        for k, v in data.get("holder_slots", {}).items()
    }

    samples = {
        k: SampleRecord(**v)
        for k, v in data.get("samples", {}).items()
    }

    state = ExperimentState(
        experiment_id=data["experiment_id"],
        created_at=data["created_at"],
        pcb_sensors=pcb_sensors,
        holder_slots=holder_slots,
        samples=samples,
        scan_count=data.get("scan_count", 0),
        completed=data.get("completed", False),
    )
    # Rebuild the runtime reverse index from persisted holder_slots
    state._sample_to_holder = {
        rec.sample_id: key
        for key, rec in state.holder_slots.items()
        if rec.sample_id is not None
    }
    return state
