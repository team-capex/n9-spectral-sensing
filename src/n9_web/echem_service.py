"""
echem_service.py
================
Runs Gamry potentiostat techniques (CV, EIS, CP, CA, OCP) in a dedicated
worker thread for the web GUI.

COM threading: comtypes objects must be created and used in one thread that
has called CoInitialize(). Each run gets a fresh worker thread; the recipe
object never crosses threads. Abort sets recipe.terminate = True, which the
recipe's measure() loop checks every 100 ms.

Results are saved to data/echem/{ts}_{technique}_{run_id}.csv with a sidecar
.json holding the parameters, and kept in memory for immediate plotting.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # must precede any gamry import (it imports matplotlib)

from n9_web.hardware import DeviceBusy, ExperimentActive, HardwareManager

logger = logging.getLogger(__name__)

# Gamry internal range steps, offered as dropdowns in the UI. Values are
# numeric (max expected current in A / full-scale voltage in V); the driver
# maps the current to the instrument's internal range via TestIERange
# (0 = autorange), and the instrument picks its closest supported Vch range.
IE_RANGE_OPTIONS = [
    {"value": 0,    "label": "auto"},
    {"value": 1e-8, "label": "10 nA"},
    {"value": 1e-7, "label": "100 nA"},
    {"value": 1e-6, "label": "1 µA"},
    {"value": 1e-5, "label": "10 µA"},
    {"value": 1e-4, "label": "100 µA"},
    {"value": 1e-3, "label": "1 mA"},
    {"value": 1e-2, "label": "10 mA"},
    {"value": 1e-1, "label": "100 mA"},
    {"value": 1.0,  "label": "1 A"},
]
# Reference 600 Vch range steps, verified on the instrument 2026-07-14
# (TestVchRange boundaries at 0.03 / 0.3 / 3 / 12 V). Values are volts; the
# driver maps them to the internal range index via TestVchRange. 0 = autorange.
VCH_RANGE_OPTIONS = [
    {"value": 0,    "label": "auto"},
    {"value": 0.03, "label": "30 mV"},
    {"value": 0.3,  "label": "300 mV"},
    {"value": 3.0,  "label": "3 V"},
    {"value": 12.0, "label": "12 V"},
]
VCH_RANGE_OPTIONS_EIS = VCH_RANGE_OPTIONS

# Parameter specs drive both validation and the auto-generated UI form.
# Kwargs match src/gamry/recipe.py constructor signatures exactly.
TECHNIQUES: dict = {
    "CV": {
        "label": "Cyclic voltammetry",
        "params": [
            {"name": "init_voltage", "label": "Initial voltage (V)", "default": 0.0},
            {"name": "final_voltage", "label": "Final voltage (V)", "default": 0.0},
            {"name": "apex1", "label": "Apex 1 (V)", "default": 0.5},
            {"name": "apex2", "label": "Apex 2 (V)", "default": -0.5},
            {"name": "scanrate1", "label": "Scan rate (V/s)", "default": 0.1},
            {"name": "stepsize", "label": "Step size (V)", "default": 0.01},
            {"name": "cycles", "label": "Cycles", "default": 2, "type": "int"},
            {"name": "VchRange", "label": "Voltage range", "type": "select",
             "options": VCH_RANGE_OPTIONS, "default": 0},
            {"name": "ie_range_a", "label": "Current range", "type": "select",
             "options": IE_RANGE_OPTIONS, "default": 0},
        ],
        "plot": {"x": "Vf (V vs Ref)", "y": "Im (A)", "kind": "line"},
    },
    "EIS": {
        "label": "Impedance spectroscopy",
        "params": [
            {"name": "init_freq", "label": "Initial frequency (Hz)", "default": 100000.0},
            {"name": "final_freq", "label": "Final frequency (Hz)", "default": 1.0},
            {"name": "pts_per_dec", "label": "Points per decade", "default": 10, "type": "int"},
            {"name": "dc", "label": "DC voltage (V)", "default": 0.0},
            {"name": "ac", "label": "AC amplitude (V)", "default": 0.01},
            {"name": "VchRange", "label": "Voltage range", "type": "select",
             "options": VCH_RANGE_OPTIONS_EIS, "default": 0},
            {"name": "ie_range_a", "label": "Current range", "type": "select",
             "options": IE_RANGE_OPTIONS, "default": 0},
        ],
        "plot": {"kind": "eis"},
    },
    "CP": {
        "label": "Chronopotentiometry",
        "params": [
            {"name": "init_voltage", "label": "Initial current (A)", "default": 0.001},
            {"name": "tinit", "label": "Initial time (s)", "default": 10.0},
            {"name": "vstep1", "label": "Current step 1 (A)", "default": 0.05},
            {"name": "tstep1", "label": "Step 1 time (s)", "default": 20.0},
            {"name": "vstep2", "label": "Current step 2 (A)", "default": 0.1},
            {"name": "tstep2", "label": "Step 2 time (s)", "default": 20.0},
            {"name": "sample", "label": "Sample period (s)", "default": 0.01},
            {"name": "VchRange", "label": "Voltage range", "type": "select",
             "options": VCH_RANGE_OPTIONS, "default": 0},
            {"name": "ie_range_a", "label": "Current range", "type": "select",
             "options": IE_RANGE_OPTIONS, "default": 0},
        ],
        "plot": {"x": "Time (s)", "y": "Vf (V vs Ref)", "kind": "line"},
    },
    "CA": {
        "label": "Chronoamperometry",
        "params": [
            {"name": "init_voltage", "label": "Initial voltage (V)", "default": 0.5},
            {"name": "tinit", "label": "Initial time (s)", "default": 10.0},
            {"name": "vstep1", "label": "Voltage step 1 (V)", "default": 0.5},
            {"name": "tstep1", "label": "Step 1 time (s)", "default": 20.0},
            {"name": "vstep2", "label": "Voltage step 2 (V)", "default": 0.5},
            {"name": "tstep2", "label": "Step 2 time (s)", "default": 20.0},
            {"name": "sample", "label": "Sample period (s)", "default": 0.01},
            {"name": "VchRange", "label": "Voltage range", "type": "select",
             "options": VCH_RANGE_OPTIONS, "default": 0},
            {"name": "ie_range_a", "label": "Current range", "type": "select",
             "options": IE_RANGE_OPTIONS, "default": 0},
        ],
        "plot": {"x": "Time (s)", "y": "Im (A)", "kind": "line"},
    },
    "OCP": {
        "label": "Open-circuit potential",
        "params": [
            {"name": "tinit", "label": "Duration (s)", "default": 30.0},
            {"name": "samplerate", "label": "Sample period (s)", "default": 0.1},
        ],
        "plot": {"x": "Time (s)", "y": "Vf (V vs Ref)", "kind": "line"},
    },
}

_MAX_PLOT_POINTS = 2000

# The gamry package's dtaq event handlers return DataFrames with numeric
# column labels (its own rename step misses because the labels are ints, not
# the strings it maps). Rename here so plots/CSVs are self-describing.
# Cook maps follow the Gamry dtaq cook() column orders.
COLUMN_MAPS = {
    "CV": {"0": "Time (s)", "1": "Vf (V vs Ref)", "2": "Vu (V)", "3": "Im (A)",
           "4": "Vsig", "5": "Ach (V)", "6": "IERange", "7": "Overload",
           "8": "Stop Test", "9": "Cycle", "10": "Temperature (C)"},
    "CP": {"0": "Time (s)", "1": "Vf (V vs Ref)", "2": "Vu (V)", "3": "Im (A)",
           "4": "Charge Q", "5": "Vsig", "6": "Ach (V)", "7": "IERange",
           "8": "Overload", "9": "Stop Test"},
    "CA": {"0": "Time (s)", "1": "Vf (V vs Ref)", "2": "Vu (V)", "3": "Im (A)",
           "4": "Charge Q", "5": "Vsig", "6": "Ach (V)", "7": "IERange",
           "8": "Overload", "9": "Stop Test"},
    "OCP": {"0": "Time (s)", "1": "Vf (V vs Ref)", "2": "Vm (V)", "3": "Vsig",
            "4": "Ach (V)", "5": "Overload", "6": "Stop Test",
            "7": "Temperature (C)"},
    "EIS": {"0": "Time (s)", "1": "Freq (Hz)", "2": "Zreal (Ohm)",
            "3": "Zimag (Ohm)", "4": "Zsig", "5": "Zmod (Ohm)",
            "6": "Zphz (deg)", "7": "Idc (A)", "8": "Vdc (V)", "9": "IERange"},
}


def _rename_columns(technique: str, df):
    """Stringify column labels and apply the technique's name map.
    Already-named columns pass through unchanged."""
    df = df.copy()
    df.columns = [str(c) for c in df.columns]
    return df.rename(columns=COLUMN_MAPS.get(technique, {}))


def _final_potential(df) -> "float | None":
    """Last measured potential of a run: Vf (CV/CP/CA/OCP) or Vdc (EIS).
    Used to chain technique voltages to the previous block's endpoint."""
    import pandas as pd

    for prefix in ("vf", "vdc"):
        for c in df.columns:
            if str(c).lower().startswith(prefix):
                vals = pd.to_numeric(df[c], errors="coerce").dropna()
                if len(vals):
                    return float(vals.iloc[-1])
    return None


class EchemService:
    """One technique run at a time on the Gamry, in a CoInitialize'd thread."""

    def __init__(self, hw: HardwareManager) -> None:
        self.hw = hw
        self.echem_dir = os.path.join(hw.raw_cfg.get("data_dir", "data"), "echem")
        os.makedirs(self.echem_dir, exist_ok=True)

        self._thread: Optional[threading.Thread] = None
        self._recipe = None            # only touched for .terminate (bool set)
        self._status_lock = threading.Lock()
        self._status: dict = {
            "state": "idle",           # idle | running | done | error | aborted
            "run_id": None,
            "technique": None,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "csv_path": None,
        }
        self._results: dict = {}       # run_id → {"columns", "series", "csv_path"}
        # Final measured potential (V) of the most recent measurement —
        # consumed by sequences chaining voltages to the previous endpoint.
        self.last_final_potential: Optional[float] = None

    def techniques(self) -> dict:
        return TECHNIQUES

    # ── Control ───────────────────────────────────────────────────────────────

    def run(self, technique: str, params: dict, sample_id: str = "") -> str:
        if technique not in TECHNIQUES:
            raise ValueError(f"Unknown technique '{technique}'.")
        if self._thread is not None and self._thread.is_alive():
            raise DeviceBusy("An electrochemical measurement is already running.")
        if self.hw.mode == "EXPERIMENT_RUNNING":
            raise ExperimentActive(
                "Electrochemistry is disabled while an experiment is running."
            )
        if not self.hw.gamry_lock.acquire(timeout=0.5):
            raise DeviceBusy("Gamry is busy.")

        try:
            clean = self.validate_params(technique, params)
        except ValueError:
            self.hw.gamry_lock.release()
            raise

        run_id = time.strftime("%Y%m%d_%H%M%S")
        with self._status_lock:
            self._status.update(
                state="running", run_id=run_id, technique=technique,
                started_at=time.time(), finished_at=None, error=None, csv_path=None,
            )
        self._thread = threading.Thread(
            target=self._worker, args=(technique, clean, run_id, sample_id),
            daemon=True, name=f"echem-{run_id}",
        )
        self._thread.start()
        return run_id

    def abort(self) -> None:
        with self._status_lock:
            running = self._status["state"] == "running"
        if not running or self._recipe is None:
            raise RuntimeError("No electrochemical measurement is running.")
        # Recipe.measure() polls this flag every 100 ms — thread-safe bool set.
        self._recipe.terminate = True
        logger.info("Echem abort requested (recipe.terminate set).")

    # ── Execution ─────────────────────────────────────────────────────────────

    @staticmethod
    def validate_params(technique: str, params: dict) -> dict:
        """Validate/coerce params against the technique spec; unknown keys
        rejected, missing keys take defaults."""
        if technique not in TECHNIQUES:
            raise ValueError(f"Unknown technique '{technique}'.")
        spec = {p["name"]: p for p in TECHNIQUES[technique]["params"]}
        unknown = set(params) - set(spec)
        if unknown:
            raise ValueError(f"Unknown parameters for {technique}: {sorted(unknown)}")
        clean: dict = {}
        for name, p in spec.items():
            val = params.get(name, p["default"])
            clean[name] = int(val) if p.get("type") == "int" else float(val)
        return clean

    def execute_sync(
        self,
        technique: str,
        params: dict,
        run_id: str,
        out_dir: "str | None" = None,
        abort_event: "threading.Event | None" = None,
        extra_meta: "dict | None" = None,
    ) -> "tuple[str, str | None]":
        """Run one technique synchronously in the CALLING thread (which gets
        CoInitialize'd). Caller must hold the gamry lock and pass pre-validated
        params. Returns (state, csv_path). Used by _worker and by sequences.

        A COM error raised before ANY data was collected (e.g. transient
        device-open failures like 0xE0000027 when the instrument is reopened
        in quick succession) is retried once after a pause — a failure with
        partial data is never retried (would silently redo the measurement)."""
        import comtypes

        out_dir = out_dir or self.echem_dir
        os.makedirs(out_dir, exist_ok=True)
        state, csv_path = "done", None
        comtypes.CoInitialize()
        watcher = None
        try:
            from gamry import recipe as gamry_recipe

            recipe_cls = getattr(gamry_recipe, technique)
            recipe = recipe_cls(**params)
            self._recipe = recipe
            if abort_event is not None:
                # Bridge an external abort event to the terminate flag of the
                # CURRENT recipe (self._recipe — survives the retry swap below)
                def _watch() -> None:
                    abort_event.wait()
                    r = self._recipe
                    if r is not None:
                        r.terminate = True
                watcher = threading.Thread(target=_watch, daemon=True)
                watcher.start()
            logger.info("Echem %s starting: %s %s", run_id, technique, params)
            try:
                recipe.run()   # blocking; returns early if terminate was set
            except Exception as exc:
                points = 0
                try:
                    points = recipe.event_handler.get_num_datapoints()
                except Exception:
                    pass
                if points or (abort_event is not None and abort_event.is_set()):
                    raise
                logger.warning(
                    "Echem %s: %s failed before collecting data (%s) — "
                    "retrying once in 5 s.", run_id, technique, exc,
                )
                time.sleep(5.0)
                recipe = recipe_cls(**params)
                self._recipe = recipe
                recipe.run()
            df = _rename_columns(technique, recipe.get_data())
            self.last_final_potential = _final_potential(df)

            if recipe.terminate:
                state = "aborted"

            ts = time.strftime("%Y%m%d_%H%M%S")
            base = os.path.join(out_dir, f"{ts}_{technique}_{run_id}")
            csv_path = base + ".csv"
            df.to_csv(csv_path, index=False)
            meta = {"run_id": run_id, "technique": technique, "params": params,
                    "aborted": state == "aborted"}
            meta.update(extra_meta or {})
            with open(base + ".json", "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            self._results[run_id] = self._to_series(df, csv_path)
            logger.info("Echem %s finished (%d points) → %s",
                        run_id, len(df), csv_path)
        finally:
            self._recipe = None
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass
        return state, csv_path

    def measure_ocv(self, duration_s: float = 5.0,
                    abort_event: "threading.Event | None" = None) -> float:
        """Short open-circuit read (cell off): mean Vf over the final third of
        samples. Runs in the CALLING thread (CoInitialize'd here); caller must
        hold the gamry lock. Not saved to CSV — used to reference technique
        voltages to OCV."""
        import comtypes

        import pandas as pd

        comtypes.CoInitialize()
        try:
            from gamry import recipe as gamry_recipe

            recipe = gamry_recipe.OCP(tinit=float(duration_s), samplerate=0.1)
            self._recipe = recipe
            if abort_event is not None:
                def _watch() -> None:
                    abort_event.wait()
                    recipe.terminate = True
                threading.Thread(target=_watch, daemon=True).start()
            recipe.run()
            df = _rename_columns("OCP", recipe.get_data())
            col = next(
                (c for c in df.columns if str(c).lower().startswith("vf")), None
            )
            if col is None:
                raise RuntimeError("OCV reference read returned no Vf column.")
            vals = pd.to_numeric(df[col], errors="coerce").dropna()
            if not len(vals):
                raise RuntimeError("OCV reference read returned no data.")
            return float(vals.tail(max(1, len(vals) // 3)).mean())
        finally:
            self._recipe = None
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass

    def _worker(self, technique: str, params: dict, run_id: str,
                sample_id: str = "") -> None:
        from n9_web.trace import log_event

        state, error, csv_path = "done", None, None
        try:
            state, csv_path = self.execute_sync(
                technique, params, run_id,
                extra_meta={"sample_id": sample_id} if sample_id else None,
            )
            log_event(
                self.hw.raw_cfg.get("data_dir", "data"), technique,
                sample_id=sample_id, src="test_cell",
                data_ref=csv_path or "", run_id=run_id, context="manual",
            )
        except Exception as exc:
            state, error = "error", f"{exc}\n{traceback.format_exc()}"
            logger.error("Echem %s failed: %s", run_id, exc, exc_info=True)
        finally:
            self.hw.gamry_lock.release()
            with self._status_lock:
                self._status.update(
                    state=state, finished_at=time.time(),
                    error=error, csv_path=csv_path,
                )

    @staticmethod
    def _to_series(df, csv_path: str) -> dict:
        """Downsample a result DataFrame to JSON-safe plot series."""
        stride = max(1, len(df) // _MAX_PLOT_POINTS)
        sub = df.iloc[::stride]
        series = {}
        for col in sub.columns:
            try:
                vals = [
                    None if (isinstance(v, float) and v != v) else float(v)
                    for v in sub[col].tolist()
                ]
            except (TypeError, ValueError):
                continue
            series[str(col)] = vals
        return {
            "columns": list(series.keys()),
            "series": series,
            "n_points": len(df),
            "csv_path": csv_path.replace("\\", "/"),
        }

    # ── Read model ────────────────────────────────────────────────────────────

    def status(self) -> dict:
        with self._status_lock:
            return dict(self._status)

    def result(self, run_id: str) -> dict:
        res = self._results.get(run_id)
        if res is not None:
            return res
        # Fall back to reading the CSV from disk (past runs, app restarts)
        import glob

        import pandas as pd

        matches = glob.glob(
            os.path.join(self.echem_dir, "**", f"*_{run_id}.csv"), recursive=True
        ) + glob.glob(os.path.join(self.echem_dir, f"*_{run_id}.csv"))
        if not matches:
            raise KeyError(f"No result for run '{run_id}'.")
        df = pd.read_csv(matches[0])
        # Old runs were saved with numeric columns — rename using the
        # technique parsed from the filename ({ts}_{technique}_{run_id}.csv).
        parts = os.path.basename(matches[0]).split("_")
        technique = parts[2] if len(parts) >= 3 else ""
        df = _rename_columns(technique, df)
        res = self._to_series(df, matches[0])
        self._results[run_id] = res
        return res

    def list_runs(self) -> list:
        import glob

        runs = []
        paths = set(glob.glob(os.path.join(self.echem_dir, "*.json")))
        paths |= set(glob.glob(os.path.join(self.echem_dir, "**", "*.json"),
                               recursive=True))
        for path in sorted(paths, reverse=True):
            try:
                with open(path, encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                continue
            # Skip non-measurement JSONs (e.g. analysis reports in reports/)
            if not isinstance(meta, dict) or "technique" not in meta:
                continue
            meta["csv_path"] = path[:-5].replace("\\", "/") + ".csv"
            runs.append(meta)
        return runs
