"""
sequence_service.py
===================
Executes user-built sequences (from the drag/drop builders) in a background
thread. One engine serves both the electrochemistry sequence builder and the
experiment procedure builder — the tabs just use different action palettes.

Sequence document:
    {
      "name": str,
      "data_dir": str | null,      # echem results subfolder under data/echem/
      "steps": [
        {"action": "<name>", "params": {...}},
        {"action": "loop", "count": N, "steps": [ ...non-loop steps... ]},
        ...
      ]
    }

Execution takes the global EXPERIMENT_RUNNING mode (manual control and
experiment starts are blocked), acquires per-device locks per step, and
checks the abort event between steps. Loops may not be nested.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
import traceback
from contextlib import contextmanager
from typing import Iterator, Optional

from n9_web.echem_service import TECHNIQUES, EchemService
from n9_web.hardware import HardwareManager
from n9_web.trace import log_event, loc_str

logger = logging.getLogger(__name__)


class SampleTracker:
    """Tracks which sample sits where during a sequence run.

    Seeded from holder_state.json (declared holder contents). Updated on every
    transfer / test-cell move so scans and echem measurements can be labelled
    with the sample they actually measured. Unknown samples never fail a run —
    they are recorded as 'unknown@<location>'.
    """

    def __init__(self, holder_state: dict) -> None:
        self._where: dict = {}
        for holder_id, slots in (holder_state or {}).items():
            if holder_id.startswith("_"):
                continue
            for s in slots:
                if s.get("state") in ("FRESH", "USED", "CLEAN") and s.get("sample_id"):
                    key = f"{holder_id}:c{s['col']}:r{s['row']}"
                    self._where[key] = {
                        "sample_id": s["sample_id"],
                        "sample_type": s.get("sample_type", ""),
                    }

    def pop(self, loc: dict) -> dict:
        key = loc_str(loc)
        return self._where.pop(key, None) or {
            "sample_id": f"unknown@{key}", "sample_type": "",
        }

    def put(self, loc: dict, sample: dict) -> None:
        self._where[loc_str(loc)] = sample

    def at(self, loc: dict) -> "dict | None":
        return self._where.get(loc_str(loc))

    def pcb_labels(self, station_id: str) -> dict:
        """{sensor_no: {sample_id, sample_type, dye_type}} for one station."""
        labels = {}
        prefix = f"{station_id}:c"
        for key, sample in self._where.items():
            if not key.startswith(prefix):
                continue
            try:
                c, r = key.split(":c")[1].split(":r")
                sensor_no = int(r) * 2 + int(c) + 1
            except (ValueError, IndexError):
                continue
            labels[sensor_no] = {
                "sample_id": sample["sample_id"],
                "sample_type": sample["sample_type"],
                "dye_type": "",
            }
        return labels

MAX_LOOP_COUNT = 500
MAX_TOTAL_STEPS = 5000   # flattened
SEQUENCE_DIR = "sequences"

# Voltage-setpoint params per technique — offset when a block's "vs" reference
# is OCV or the previous block's endpoint. CP is galvanostatic (its setpoints
# are currents) and OCP applies no signal, so neither is referenced.
VOLTAGE_PARAMS = {
    "CV": ("init_voltage", "final_voltage", "apex1", "apex2"),
    "CA": ("init_voltage", "vstep1", "vstep2"),
    "EIS": ("dc",),
}
VS_OPTIONS = ("Ref", "OCV", "previous endpoint")


def _estimate_echem_s(technique: str, p: dict) -> float:
    """Rough duration of one technique from its params (missing params take
    the TECHNIQUES defaults). Includes COM/cell-settle overhead and, when any
    setpoint references OCV, the settle read."""
    spec = {q["name"]: q for q in TECHNIQUES.get(technique, {}).get("params", [])}

    def val(name: str, fallback: float = 0.0) -> float:
        raw = p.get(name, spec.get(name, {}).get("default", fallback))
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(spec.get(name, {}).get("default", fallback) or fallback)

    t = 8.0   # COM init + cell settle overhead
    if technique == "CV":
        legs = (abs(val("apex1") - val("init_voltage"))
                + abs(val("apex2") - val("apex1"))
                + abs(val("final_voltage") - val("apex2")))
        t += max(1.0, val("cycles", 2)) * legs / max(val("scanrate1", 0.1), 1e-6)
    elif technique in ("CP", "CA"):
        t += val("tinit") + val("tstep1") + val("tstep2")
    elif technique == "OCP":
        t += val("tinit")
    elif technique == "EIS":
        f0 = max(val("init_freq", 1e5), 1e-3)
        f1 = max(val("final_freq", 1.0), 1e-3)
        n = max(1, round(0.5 + abs(math.log10(f1) - math.log10(f0))
                         * max(val("pts_per_dec", 10), 1.0)))
        for i in range(int(n)):
            f = 10 ** (math.log10(f0)
                       + (math.log10(f1) - math.log10(f0)) * i / max(n - 1, 1))
            t += 2.0 + 3.0 / f   # per-point overhead + a few periods
    block = str(p.get("vs") or "Ref")
    modes = {str(p.get(f"vs_{name}") or "") or block
             for name in VOLTAGE_PARAMS.get(technique, ())}
    if "OCV" in modes:
        try:
            t += float(p.get("ocv_s") or 5.0) + 4.0
        except (TypeError, ValueError):
            t += 9.0
    return t


def _is_control_param(name: str) -> bool:
    """Block-control params consumed by the sequence engine, not the
    technique: block-level reference ('vs'), OCV settle time, per-setpoint
    reference overrides ('vs_<param>'), and the retired 'background' toggle
    (still present in older saved sequences — echem now always runs in the
    background)."""
    return name in ("vs", "ocv_s", "background") or name.startswith("vs_")


def build_action_registry(hw: HardwareManager) -> dict:
    """Action specs for validation + UI form generation.

    groups: echem | flow | robot | testcell | pumps | spectral
    The echem builder shows groups {echem, flow}; the procedure builder all.
    Param types: number | int | text | select | location.
    """
    pumps = list(hw.raw_cfg.get("peristaltic_pumps", {}).keys())
    board_ids = [
        b["board_id"] for b in hw.raw_cfg.get("PCBs", [])
    ]
    actions: dict = {}

    # Echem blocks always run in the background: they only need the
    # potentiostat, so robot/spectral/pump steps continue in parallel. The
    # next echem or test-cell/peristaltic step — or a wait_echem block —
    # joins the running measurement.
    for t, spec in TECHNIQUES.items():
        params = [dict(pp) for pp in spec["params"]]   # copy — annotated below
        extra = []
        if t in VOLTAGE_PARAMS:
            # Voltage setpoints get a per-param reference selector in the UI
            # (stored as vs_<name>); the block-level 'vs' is the default.
            for pp in params:
                if pp["name"] in VOLTAGE_PARAMS[t]:
                    pp["ref_select"] = True
            extra = [
                {"name": "vs", "label": "Voltages vs (default)", "type": "select",
                 "options": list(VS_OPTIONS), "default": "Ref"},
                {"name": "ocv_s", "label": "OCV settle time (s)", "default": 5.0},
            ]
        actions[f"echem:{t}"] = {
            "label": f"{t} — {spec['label']}",
            "group": "echem",
            "params": extra + params,
        }

    actions["wait"] = {
        "label": "Wait",
        "group": "flow",
        "params": [{"name": "seconds", "label": "Seconds", "default": 10.0}],
    }
    actions["wait_echem"] = {
        "label": "Wait for echem to finish",
        "group": "flow",
        "params": [],
    }

    actions["robot_home"] = {"label": "Home robot", "group": "robot", "params": []}
    actions["robot_transfer"] = {
        "label": "Transfer sample",
        "group": "robot",
        "params": [
            {"name": "from", "label": "From", "type": "location"},
            {"name": "to", "label": "To", "type": "location"},
        ],
    }
    actions["testcell_insert"] = {
        "label": "Insert into test cell",
        "group": "testcell",
        "params": [{"name": "from", "label": "Pick from", "type": "location"}],
    }
    actions["testcell_retrieve"] = {
        "label": "Retrieve from test cell",
        "group": "testcell",
        "params": [{"name": "to", "label": "Return to", "type": "location"}],
    }
    actions["testcell_fill"] = {
        "label": "Fill test cell",
        "group": "testcell",
        "params": [
            {"name": "pump", "label": "Pump", "type": "select", "options": pumps,
             "default": hw.raw_cfg.get("test_cell", {}).get("fill_pump", pumps[0] if pumps else "")},
            {"name": "volume_ml", "label": "Volume (mL)", "default": 5.0},
        ],
    }
    actions["testcell_drain"] = {
        "label": "Drain test cell",
        "group": "testcell",
        "params": [{"name": "volume_ml", "label": "Volume (mL)", "default": 5.0}],
    }
    actions["pump_peristaltic"] = {
        "label": "Peristaltic pump",
        "group": "pumps",
        "params": [
            {"name": "pump", "label": "Pump", "type": "select", "options": pumps,
             "default": pumps[0] if pumps else ""},
            {"name": "volume_ml", "label": "Volume (mL)", "default": 1.0},
        ],
    }
    actions["pump_stepper"] = {
        "label": "Stepper pump",
        "group": "pumps",
        "params": [
            {"name": "no", "label": "Pump # (1-4)", "type": "int", "default": 1},
            {"name": "ml", "label": "Volume (mL, − = reverse)", "default": 0.5},
            {"name": "flow_rate", "label": "Flow (mL/s)", "default": 0.02},
        ],
    }
    actions["scan"] = {
        "label": "Spectral scan",
        "group": "spectral",
        "params": [
            {"name": "board_id", "label": "Board", "type": "select",
             "options": ["all"] + board_ids, "default": "all"},
        ],
    }
    actions["set_temperature"] = {
        "label": "Set temperature target",
        "group": "spectral",
        "params": [
            {"name": "board_id", "label": "Board", "type": "select",
             "options": board_ids, "default": board_ids[0] if board_ids else ""},
            {"name": "target_c", "label": "Target (°C)", "default": 40.0},
            {"name": "max_power_pct", "label": "Max power (%)", "default": 20.0},
        ],
    }
    actions["wait_for_temperature"] = {
        "label": "Wait for temperature",
        "group": "spectral",
        "params": [
            {"name": "tolerance_c", "label": "Tolerance (°C)", "default": 1.0},
            {"name": "timeout_s", "label": "Timeout (s)", "default": 1000.0},
        ],
    }
    actions["heaters_off"] = {
        "label": "All heaters off", "group": "spectral", "params": [],
    }
    actions["led_panel"] = {
        "label": "LED panel",
        "group": "spectral",
        "params": [{"name": "on", "label": "On (1) / Off (0)", "type": "int", "default": 1}],
    }
    return actions


class SequenceAborted(Exception):
    pass


class SequenceService:
    """Validates, stores, and runs builder sequences."""

    def __init__(self, hw: HardwareManager, echem: EchemService) -> None:
        self.hw = hw
        self.echem = echem
        self.actions = build_action_registry(hw)
        os.makedirs(os.path.join(SEQUENCE_DIR, "echem"), exist_ok=True)
        os.makedirs(os.path.join(SEQUENCE_DIR, "procedure"), exist_ok=True)

        self._thread: Optional[threading.Thread] = None
        self._abort = threading.Event()
        # Targets set by set_temperature steps in the current run
        # (board_id → target_c); consumed by wait_for_temperature.
        self._targets_set: dict = {}
        # Per-run context (set in _worker)
        self._run_id = ""
        self._seq_name = ""
        self._data_dir = hw.raw_cfg.get("data_dir", "data")
        self._tracker = SampleTracker({})
        # Echem measurements executed in the current run, in order —
        # consumed by the automatic analysis report at the end of the run.
        self._echem_measurements: list = []
        # In-flight background echem measurement (holder dict), or None
        self._bg_echem: "dict | None" = None
        self._status_lock = threading.Lock()
        self._status: dict = {
            "running": False, "run_id": None, "name": None, "kind": None,
            "step": None, "step_index": None, "n_steps": None,
            "started_at": None, "finished_at": None, "outcome": None,
            "error": None, "report": None, "est_total_s": None,
        }

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self, seq: dict, kind: str) -> int:
        """Validate structure + params. Returns flattened step count."""
        steps = seq.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("Sequence has no steps.")
        allowed_groups = (
            {"echem", "flow"} if kind == "echem" else
            {"echem", "flow", "robot", "testcell", "pumps", "spectral"}
        )
        total = 0

        def _check(step: dict, in_loop: bool) -> int:
            action = step.get("action")
            if action == "loop":
                if in_loop:
                    raise ValueError("Nested loops are not supported.")
                count = int(step.get("count", 0))
                if not (1 <= count <= MAX_LOOP_COUNT):
                    raise ValueError(f"Loop count must be 1..{MAX_LOOP_COUNT}.")
                inner = step.get("steps") or []
                if not inner:
                    raise ValueError("Loop has no steps.")
                return count * sum(_check(s, True) for s in inner)
            spec = self.actions.get(action)
            if spec is None:
                raise ValueError(f"Unknown action '{action}'.")
            if spec["group"] not in allowed_groups:
                raise ValueError(f"Action '{action}' not allowed in a {kind} sequence.")
            params = step.get("params") or {}
            if action.startswith("echem:"):
                vs = params.get("vs", "Ref")
                if vs not in VS_OPTIONS:
                    raise ValueError(f"{action}: unknown voltage reference '{vs}'.")
                for k, v in params.items():
                    if k.startswith("vs_") and v not in ("",) + VS_OPTIONS:
                        raise ValueError(
                            f"{action}: unknown voltage reference '{v}' for {k[3:]}."
                        )
                float(params.get("ocv_s") or 5.0)
                tech_params = {k: v for k, v in params.items()
                               if not _is_control_param(k)}
                self.echem.validate_params(action.split(":", 1)[1], tech_params)
            else:
                known = {p["name"] for p in spec["params"]}
                unknown = set(params) - known
                if unknown:
                    raise ValueError(f"{action}: unknown params {sorted(unknown)}")
                for p in spec["params"]:
                    if p.get("type") == "location":
                        self._resolve_location(params.get(p["name"]) or {})
            return 1

        for s in steps:
            total += _check(s, False)
        if total > MAX_TOTAL_STEPS:
            raise ValueError(f"Sequence expands to {total} steps (max {MAX_TOTAL_STEPS}).")

        data_dir = seq.get("data_dir")
        if data_dir:
            if os.path.isabs(data_dir) or ".." in data_dir.replace("\\", "/").split("/"):
                raise ValueError("data_dir must be a simple subfolder name.")
        return total

    def _resolve_location(self, loc: dict) -> "tuple[float, float, float]":
        cm = self.hw.coord_map
        t = loc.get("type")
        if t == "test_cell":
            return cm.test_cell_xyz()
        if t == "holder":
            layout = cm.holder_layout(loc["id"])   # KeyError if unknown
            col, row = int(loc.get("col", 0)), int(loc.get("row", 0))
            if not (0 <= col < layout.n_cols and 0 <= row < layout.n_rows):
                raise ValueError(
                    f"Slot (col={col}, row={row}) outside {loc['id']} grid."
                )
            return cm.holder_slot_xyz(loc["id"], col, row)
        if t == "pcb":
            col, row = int(loc.get("col", 0)), int(loc.get("row", 0))
            if not (0 <= col <= 1 and 0 <= row <= 7):
                raise ValueError(f"PCB position (col={col}, row={row}) outside 2×8 grid.")
            return cm.pcb_sensor_xyz(loc["id"], col, row)
        raise ValueError(f"Bad location: {loc!r}")

    # ── Library ───────────────────────────────────────────────────────────────

    @staticmethod
    def _safe_name(name: str) -> str:
        name = re.sub(r"[^A-Za-z0-9_\- ]", "", name).strip().replace(" ", "-")
        if not name:
            raise ValueError("Sequence name is empty or invalid.")
        return name

    def save_sequence(self, kind: str, name: str, seq: dict) -> str:
        self.validate(seq, kind)
        name = self._safe_name(name)
        path = os.path.join(SEQUENCE_DIR, kind, name + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(seq, f, indent=2)
        logger.info("Sequence saved: %s", path)
        return name

    def list_sequences(self, kind: str) -> list:
        folder = os.path.join(SEQUENCE_DIR, kind)
        if not os.path.isdir(folder):
            return []
        return sorted(
            os.path.splitext(f)[0] for f in os.listdir(folder) if f.endswith(".json")
        )

    def load_sequence(self, kind: str, name: str) -> dict:
        path = os.path.join(SEQUENCE_DIR, kind, self._safe_name(name) + ".json")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def delete_sequence(self, kind: str, name: str) -> None:
        path = os.path.join(SEQUENCE_DIR, kind, self._safe_name(name) + ".json")
        os.remove(path)

    # ── Duration estimation ───────────────────────────────────────────────────

    # Rough fixed durations (s) for robot/board actions
    _ACTION_EST = {
        "robot_home": 15.0, "robot_transfer": 30.0,
        "testcell_insert": 40.0, "testcell_retrieve": 40.0,
        "set_temperature": 2.0, "heaters_off": 2.0, "led_panel": 1.0,
        "wait_echem": 0.0,
    }
    # Actions that wait for a running background measurement first
    _JOIN_ACTIONS = ("wait_echem", "testcell_insert", "testcell_retrieve",
                     "testcell_fill", "testcell_drain", "pump_peristaltic")

    def estimate(self, seq: dict) -> dict:
        """Rough total duration honouring background echem: the sequence
        cursor advances through other steps while a measurement runs, and
        join actions wait for it. Returns {"total_s": float | None}."""
        t = 0.0          # sequence-thread cursor
        echem_end = 0.0  # completion time of the in-flight measurement
        try:
            for step, _label in self._iter_steps(seq.get("steps") or []):
                action = str(step.get("action") or "")
                p = step.get("params") or {}
                if action.startswith("echem:"):
                    start = max(t, echem_end)          # joins the previous one
                    echem_end = start + _estimate_echem_s(
                        action.split(":", 1)[1], p
                    )
                    t = start                           # dispatch is instant
                    continue
                if action in self._JOIN_ACTIONS:
                    t = max(t, echem_end)
                t += self._estimate_action_s(action, p)
            return {"total_s": round(max(t, echem_end), 1)}
        except Exception:
            logger.debug("Sequence estimate failed.", exc_info=True)
            return {"total_s": None}

    def _estimate_action_s(self, action: str, p: dict) -> float:
        if action == "wait":
            return float(p.get("seconds") or 0.0)
        if action in self._ACTION_EST:
            return self._ACTION_EST[action]
        if action in ("testcell_fill", "pump_peristaltic"):
            pumps = self.hw.raw_cfg.get("peristaltic_pumps", {}) or {}
            rate = float((pumps.get(str(p.get("pump")), {}) or {})
                         .get("flow_rate_ml_per_s") or 0.5)
            return abs(float(p.get("volume_ml") or 0.0)) / max(rate, 1e-3) + 3.0
        if action == "testcell_drain":
            return abs(float(p.get("volume_ml") or 0.0)) / 0.5 + 5.0
        if action == "pump_stepper":
            return (abs(float(p.get("ml") or 0.0))
                    / max(float(p.get("flow_rate") or 0.02), 1e-4) + 2.0)
        if action == "scan":
            boards = (self.hw.raw_cfg.get("PCBs")
                      or self.hw.raw_cfg.get("boards") or [])
            n = 1 if p.get("board_id") not in ("all", "", None) else max(len(boards), 1)
            return 25.0 * n
        if action == "wait_for_temperature":
            return min(float(p.get("timeout_s") or 1000.0), 300.0)
        return 5.0

    # ── Run control ───────────────────────────────────────────────────────────

    def start(self, seq: dict, kind: str) -> str:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("A sequence is already running.")
        n_steps = self.validate(seq, kind)
        est_total_s = self.estimate(seq).get("total_s")
        self.hw.start_experiment_mode()   # raises if not IDLE

        run_id = time.strftime("%Y%m%d_%H%M%S")
        self._abort = threading.Event()
        with self._status_lock:
            self._status.update(
                running=True, run_id=run_id, name=seq.get("name") or "unnamed",
                kind=kind, step=None, step_index=0, n_steps=n_steps,
                started_at=time.time(), finished_at=None, outcome=None,
                error=None, report=None, est_total_s=est_total_s,
            )
        self._thread = threading.Thread(
            target=self._worker, args=(seq, run_id), daemon=True,
            name=f"sequence-{run_id}",
        )
        self._thread.start()
        return run_id

    def abort(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            raise RuntimeError("No sequence is running.")
        self._abort.set()
        logger.info("Sequence abort requested.")

    def status(self) -> dict:
        with self._status_lock:
            return dict(self._status)

    # ── Worker ────────────────────────────────────────────────────────────────

    def _iter_steps(self, steps: list) -> Iterator["tuple[dict, str]"]:
        for i, step in enumerate(steps):
            if step.get("action") == "loop":
                count = int(step["count"])
                for k in range(count):
                    for j, inner in enumerate(step.get("steps") or []):
                        yield inner, f"step {i + 1} (loop {k + 1}/{count}) → {inner['action']}"
            else:
                yield step, f"step {i + 1}: {step['action']}"

    def _worker(self, seq: dict, run_id: str) -> None:
        outcome, error = "completed", None
        data_dir = seq.get("data_dir")
        echem_out = (
            os.path.join(self.echem.echem_dir, data_dir) if data_dir else None
        )
        logger.info("Sequence '%s' started (%s).", seq.get("name"), run_id)
        self._targets_set = {}
        self._run_id = run_id
        self._seq_name = seq.get("name") or "unnamed"
        self._data_dir = self.hw.raw_cfg.get("data_dir", "data")
        # Sample tracking, seeded from the declared holder contents
        try:
            with open("holder_state.json", encoding="utf-8") as f:
                holder_state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            holder_state = {}
        self._tracker = SampleTracker(holder_state)
        self._echem_measurements = []
        self._bg_echem = None
        # 'previous endpoint' voltage references are scoped to this run
        self.echem.last_final_potential = None
        try:
            done = 0
            for step, label in self._iter_steps(seq["steps"]):
                if self._abort.is_set():
                    raise SequenceAborted("Abort requested.")
                with self._status_lock:
                    self._status["step"] = label
                    self._status["step_index"] = done
                logger.info("── %s ──", label)
                self._exec_step(step, echem_out, run_id)
                done += 1
            # All steps dispatched — wait for a background measurement
            # that may still be running before declaring the outcome.
            self._join_bg_echem()
        except SequenceAborted as exc:
            outcome, error = "aborted", str(exc)
            logger.info("Sequence aborted.")
        except Exception as exc:
            outcome, error = "error", f"{exc}\n{traceback.format_exc()}"
            logger.error("Sequence failed: %s", exc, exc_info=True)
        finally:
            if self._bg_echem is not None:
                # Abnormal exit with a measurement still running in the
                # background — stop it and fold in whatever data it produced.
                self._abort.set()
                try:
                    self._join_bg_echem()
                except Exception:
                    logger.error("Background echem cleanup failed.", exc_info=True)
            self.hw.end_experiment_mode()
            report_id = self._generate_report(run_id)
            with self._status_lock:
                self._status.update(
                    running=False, finished_at=time.time(),
                    outcome=outcome, error=error, report=report_id,
                )
            logger.info("Sequence finished: %s", outcome)

    def _generate_report(self, run_id: str) -> "str | None":
        """Build the automatic analysis report for the echem measurements of
        this run (aborted/failed runs too — partial data is still analysed).
        Never raises: analysis must not turn a completed run into a failure."""
        if not self._echem_measurements:
            return None
        try:
            from n9_web import echem_analysis

            report = echem_analysis.build_report(
                self._echem_measurements, run_id, self._seq_name
            )
            echem_analysis.save_report(self.echem.echem_dir, report)
            logger.info("Echem analysis report ready (%d measurements).",
                        report["n_measurements"])
            return run_id
        except Exception:
            logger.error("Echem analysis report failed.", exc_info=True)
            return None

    @contextmanager
    def _locks(self, *names: str):
        acquired = []
        try:
            for n in names:
                lock = self.hw._locks[n]
                if not lock.acquire(timeout=30.0):
                    raise RuntimeError(f"Device '{n}' busy — cannot run step.")
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()

    def _exec_step(self, step: dict, echem_out: "str | None", run_id: str) -> None:
        action = step["action"]
        p = step.get("params") or {}
        hw = self.hw

        if action == "wait":
            deadline = time.monotonic() + float(p.get("seconds", 10.0))
            while time.monotonic() < deadline:
                if self._abort.is_set():
                    raise SequenceAborted("Abort during wait.")
                time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
            return

        if action == "wait_echem":
            self._join_bg_echem()
            return

        if action.startswith("echem:"):
            technique = action.split(":", 1)[1]
            clean = self.echem.validate_params(
                technique,
                {k: v for k, v in p.items() if not _is_control_param(k)},
            )
            modes = self._param_modes(technique, p)
            ocv_s = float(p.get("ocv_s") or 5.0)
            # One measurement at a time: wait for the previous one first
            self._join_bg_echem()
            # Label the measurement with the sample currently in the test cell
            sample = self._tracker.at({"type": "test_cell"}) or {}
            # Echem always runs in the background — it only needs the
            # potentiostat, so the sequence continues with other equipment.
            self._start_bg_echem(technique, clean, modes, ocv_s,
                                 echem_out, sample)
            return

        if action == "robot_home":
            with self._locks("robot"):
                hw.get_robot().home()
        elif action == "robot_transfer":
            # Test-cell endpoints need the rotated gripper approach + piston —
            # reroute to the dedicated test-cell flows (which also wait for a
            # running background measurement).
            if (p.get("to") or {}).get("type") == "test_cell":
                self._exec_step({"action": "testcell_insert",
                                 "params": {"from": p["from"]}},
                                echem_out, run_id)
                return
            if (p.get("from") or {}).get("type") == "test_cell":
                self._exec_step({"action": "testcell_retrieve",
                                 "params": {"to": p["to"]}},
                                echem_out, run_id)
                return
            from_xyz = self._resolve_location(p["from"])
            to_xyz = self._resolve_location(p["to"])
            with self._locks("robot"):
                robot = hw.get_robot()
                robot.transfer(from_xyz, to_xyz)
                robot.force_home()
            sample = self._tracker.pop(p["from"])
            self._tracker.put(p["to"], sample)
            self._trace("transfer", sample,
                        src=loc_str(p["from"]), dst=loc_str(p["to"]))
        elif action == "testcell_insert":
            self._join_bg_echem()   # never disturb a running measurement
            from_xyz = self._resolve_location(p["from"])
            tc_xyz = hw.coord_map.test_cell_xyz()
            import math
            angle = math.radians(hw.coord_map.test_cell.gripper_angle_deg)
            with self._locks("robot"):
                robot = hw.get_robot()
                pumps = hw.get_peristaltic()
                robot.pick_from(*from_xyz)
                robot.move_to_test_cell(tc_xyz, gripper_angle_offset_rad=angle)
                pumps.engage_piston()
                robot.release_at_test_cell()
            sample = self._tracker.pop(p["from"])
            self._tracker.put({"type": "test_cell"}, sample)
            self._trace("testcell_insert", sample,
                        src=loc_str(p["from"]), dst="test_cell")
        elif action == "testcell_retrieve":
            self._join_bg_echem()   # never disturb a running measurement
            to_xyz = self._resolve_location(p["to"])
            tc_xyz = hw.coord_map.test_cell_xyz()
            import math
            angle = math.radians(hw.coord_map.test_cell.gripper_angle_deg)
            with self._locks("robot"):
                robot = hw.get_robot()
                pumps = hw.get_peristaltic()
                pumps.release_piston()
                robot.retrieve_from_test_cell(tc_xyz, gripper_angle_offset_rad=angle)
                robot.place_at(*to_xyz)
                robot.force_home()
            sample = self._tracker.pop({"type": "test_cell"})
            self._tracker.put(p["to"], sample)
            self._trace("testcell_retrieve", sample,
                        src="test_cell", dst=loc_str(p["to"]))
        elif action == "testcell_fill":
            self._join_bg_echem()   # never disturb a running measurement
            with self._locks("robot"):
                hw.get_peristaltic().fill_peristaltic(
                    str(p["pump"]), float(p["volume_ml"])
                )
        elif action == "testcell_drain":
            self._join_bg_echem()   # never disturb a running measurement
            with self._locks("robot"):
                pumps = hw.get_peristaltic()
                pumps.open_drain()
                try:
                    pumps.drain(float(p["volume_ml"]))
                finally:
                    pumps.close_drain()
        elif action == "pump_peristaltic":
            # Peristaltic lines are plumbed to the test cell — same guard
            self._join_bg_echem()
            with self._locks("robot"):
                hw.get_peristaltic().fill_peristaltic(
                    str(p["pump"]), float(p["volume_ml"])
                )
        elif action == "pump_stepper":
            with self._locks("fluidic"):
                hw.get_fluidic().stepper_pump(
                    int(p["no"]), float(p["ml"]), float(p.get("flow_rate", 0.02))
                )
        elif action == "scan":
            board = p.get("board_id", "all")
            # Map board_id → sensing-station id so scan rows carry sample labels
            board_to_station = {
                s["board_id"]: s["id"]
                for s in hw.raw_cfg.get("sensing_stations", [])
            }
            with self._locks("boards"):
                mgr = hw.get_boards()
                for rt in mgr._boards:
                    if board in ("all", "", None) or rt.cfg.board_id == board:
                        station = board_to_station.get(rt.cfg.board_id)
                        labels = (
                            self._tracker.pcb_labels(station) if station else None
                        )
                        rt.run_once(self._run_id, labels)
                        for lab in (labels or {}).values():
                            self._trace(
                                "scan", lab, src=station or rt.cfg.board_id,
                                data_ref=os.path.join(self._data_dir, "spectral_log.csv"),
                            )
        elif action == "set_temperature":
            with self._locks("boards"):
                mgr = hw.get_boards()
                for rt in mgr._boards:
                    if rt.cfg.board_id == p["board_id"]:
                        rt.sensor.set_temperature_target(
                            float(p["target_c"]),
                            float(p.get("max_power_pct", rt.cfg.max_power_pct)),
                            rt.cfg.sensor_pin,
                        )
                        self._targets_set[rt.cfg.board_id] = float(p["target_c"])
                        break
                else:
                    raise ValueError(f"Board '{p['board_id']}' not connected.")
        elif action == "wait_for_temperature":
            # Poll temperatures against the targets set by set_temperature steps
            deadline = time.monotonic() + float(p.get("timeout_s", 1000.0))
            tol = float(p.get("tolerance_c", 1.0))
            targets = self._collect_targets()
            if not targets:
                logger.info("wait_for_temperature: no targets set — skipping.")
                return
            while True:
                if self._abort.is_set():
                    raise SequenceAborted("Abort during temperature wait.")
                with self._locks("boards"):
                    mgr = hw.get_boards()
                    remaining = {
                        rt.cfg.board_id: rt.sensor.get_temperature(rt.cfg.sensor_pin)
                        for rt in mgr._boards if rt.cfg.board_id in targets
                    }
                pending = {
                    b: t for b, t in remaining.items()
                    if abs(t - targets[b]) > tol
                }
                if not pending:
                    return
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Temperature not reached: {pending}")
                logger.info("Waiting for temperature: %s", pending)
                time.sleep(5.0)
        elif action == "heaters_off":
            with self._locks("boards"):
                for rt in hw.get_boards()._boards:
                    rt.sensor.clear_temperature_target()
            self._targets_set.clear()
        elif action == "led_panel":
            on = bool(int(p.get("on", 1)))
            with self._locks("boards"):
                for rt in hw.get_boards()._boards:
                    rt._safe_set_voltage(rt.cfg.control_voltage if on else 0.0)
        else:
            raise ValueError(f"Unknown action '{action}'.")

    # ── Echem execution (always in the background) ────────────────────────────

    def _param_modes(self, technique: str, p: dict) -> dict:
        """Effective voltage reference per setpoint: per-param override
        (vs_<name>) when set, else the block-level 'vs'."""
        block = str(p.get("vs") or "Ref")
        return {
            name: str(p.get(f"vs_{name}") or "") or block
            for name in VOLTAGE_PARAMS.get(technique, ())
        }

    def _resolve_references(self, modes: dict, ocv_s: float) -> dict:
        """Measure/collect the reference potentials the block needs. Caller
        must hold the gamry lock; the OCV mode runs a short open-circuit
        read (once, even if several setpoints use it)."""
        needed = set(modes.values())
        offsets = {"Ref": 0.0}
        if "previous endpoint" in needed:
            v = self.echem.last_final_potential
            if v is None:
                raise ValueError(
                    "'previous endpoint' voltage reference: no earlier echem "
                    "measurement in this sequence provides an endpoint."
                )
            offsets["previous endpoint"] = float(v)
            logger.info("Previous-endpoint reference: %.4f V.", v)
        if "OCV" in needed:
            offsets["OCV"] = self.echem.measure_ocv(
                ocv_s, abort_event=self._abort
            )
            logger.info("OCV reference: %.4f V.", offsets["OCV"])
        unknown = needed - set(offsets)
        if unknown:
            raise ValueError(f"Unknown voltage reference {sorted(unknown)}.")
        return offsets

    def _run_echem(self, technique: str, clean: dict, modes: dict,
                   ocv_s: float, echem_out: "str | None",
                   sample: dict) -> "tuple[dict | None, str]":
        """Run one technique on the Gamry in the calling thread. Resolves the
        voltage references, executes, and returns (measurement record, state)."""
        with self._locks("gamry"):
            offsets = self._resolve_references(modes, ocv_s)
            applied = dict(clean)
            for name, mode in modes.items():
                applied[name] = applied[name] + offsets[mode]
            used = sorted({m for m in modes.values() if m != "Ref"})
            vs_summary = used[0] if len(used) == 1 else ("mixed" if used else "Ref")
            reference_v = round(offsets[used[0]], 6) if len(used) == 1 else None
            ref_meta = {
                "vs": vs_summary,
                "reference_v": reference_v,
                "setpoint_offsets": {
                    name: round(offsets[mode], 6)
                    for name, mode in modes.items() if mode != "Ref"
                },
            }
            step_run_id = time.strftime("%Y%m%d_%H%M%S")
            state, csv_path = self.echem.execute_sync(
                technique, applied, step_run_id,
                out_dir=echem_out, abort_event=self._abort,
                extra_meta={
                    "sample_id": sample.get("sample_id", ""),
                    "sample_type": sample.get("sample_type", ""),
                    "sequence": self._seq_name,
                    "sequence_run_id": self._run_id,
                    **ref_meta,
                },
            )
        record = None
        if csv_path:
            record = {
                "run_id": step_run_id, "technique": technique,
                "csv_path": csv_path, "params": applied,
                "sample_id": sample.get("sample_id", ""),
                "sample_type": sample.get("sample_type", ""),
                "aborted": state == "aborted",
                **ref_meta,
            }
        return record, state

    def _finish_echem(self, record: "dict | None", state: str) -> None:
        """Record + trace a finished measurement; propagate an abort."""
        if record:
            self._echem_measurements.append(record)
            self._trace(record["technique"],
                        {"sample_id": record["sample_id"],
                         "sample_type": record.get("sample_type", "")},
                        src="test_cell", data_ref=record["csv_path"] or "")
        if state == "aborted":
            raise SequenceAborted(
                f"{(record or {}).get('technique', 'echem')} measurement aborted."
            )

    def _start_bg_echem(self, technique: str, clean: dict, modes: dict,
                        ocv_s: float, echem_out: "str | None",
                        sample: dict) -> None:
        """Start a technique in a background thread and return immediately, so
        subsequent robot/spectral/pump steps run in parallel. The result is
        folded into the run at the next _join_bg_echem() point."""
        holder: dict = {"technique": technique, "record": None,
                        "state": None, "error": None}

        def _bg() -> None:
            try:
                holder["record"], holder["state"] = self._run_echem(
                    technique, clean, modes, ocv_s, echem_out, sample
                )
            except Exception as exc:   # surfaced at the join point
                holder["error"] = exc

        thread = threading.Thread(target=_bg, daemon=True,
                                  name=f"sequence-echem-bg-{technique}")
        holder["thread"] = thread
        self._bg_echem = holder
        thread.start()
        logger.info("%s started in background — sequence continues.", technique)

    def _join_bg_echem(self) -> None:
        """Wait for the background measurement (if any) and fold its result
        into the run. Called by the next echem block, wait_echem, test-cell /
        peristaltic steps (which would disturb the cell), and at run end."""
        bg = self._bg_echem
        if bg is None:
            return
        self._bg_echem = None
        if bg["thread"].is_alive():
            logger.info("Waiting for background %s to finish…", bg["technique"])
            with self._status_lock:
                self._status["step"] = f"waiting for background {bg['technique']}"
        bg["thread"].join()
        if bg["error"] is not None:
            raise RuntimeError(
                f"Background {bg['technique']} failed: {bg['error']}"
            ) from bg["error"]
        self._finish_echem(bg["record"], bg["state"] or "done")

    def _collect_targets(self) -> dict:
        return dict(self._targets_set)

    def _trace(self, event: str, sample: dict, src: str = "", dst: str = "",
               data_ref: str = "") -> None:
        log_event(
            self._data_dir, event,
            sample_id=(sample or {}).get("sample_id", ""),
            sample_type=(sample or {}).get("sample_type", ""),
            src=src, dst=dst, data_ref=data_ref,
            run_id=self._run_id, context=f"sequence:{self._seq_name}",
        )
