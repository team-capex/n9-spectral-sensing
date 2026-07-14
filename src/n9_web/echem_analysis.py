"""
echem_analysis.py
=================
Automatic post-run analysis for electrochemistry sequences.

When a sequence containing echem steps finishes, SequenceService calls
build_report() with the measurements it executed. The report bundles, per
technique, overlay plot series (all CVs in one voltammogram, Nyquist/Bode
overlays for EIS, time traces for CA/CP/OCP) and per-measurement metrics
(peak currents and positions, Rs/Rp, steady-state values, OCP drift, charge).
Reports are saved to data/echem/reports/<sequence_run_id>.json and rendered
in the web UI by the sequence builder's Analysis panel (plot.js).

Reports for sequence runs that predate this feature (or whose report file
was deleted) are rebuilt on demand by scanning the measurement sidecar
.json files for a matching sequence_run_id.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import time
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_MAX_PLOT_POINTS = 800     # per series, per plot (overlays multiply this)
_REPORTS_SUBDIR = "reports"

# np.trapz was renamed to trapezoid in numpy 2
_trapz = getattr(np, "trapezoid", None) or np.trapz


# ── Column helpers ────────────────────────────────────────────────────────────

def _find_col(df: pd.DataFrame, *patterns: str) -> Optional[str]:
    for pat in patterns:
        for c in df.columns:
            if re.search(pat, str(c), re.IGNORECASE):
                return str(c)
    return None


def _numeric(df: pd.DataFrame, col: str) -> np.ndarray:
    return pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)


def _pair(df: pd.DataFrame, xcol: str, ycol: str) -> "tuple[np.ndarray, np.ndarray]":
    x, y = _numeric(df, xcol), _numeric(df, ycol)
    mask = np.isfinite(x) & np.isfinite(y)
    return x[mask], y[mask]


def _sig(v: float) -> "float | None":
    """Round to 6 significant digits for compact, readable JSON."""
    if v is None or not np.isfinite(v):
        return None
    return float(f"{float(v):.6g}")


# ── Plot extraction ───────────────────────────────────────────────────────────

def _extract_plots(technique: str, df: pd.DataFrame,
                   rs: "float | None" = None) -> list:
    """Downsampled (x, y) arrays for each plot this technique produces.
    When an EIS-derived series resistance `rs` is available, CV and CP also
    get iR-corrected variants (pointwise V − I·Rs)."""
    plots: list = []

    def add(title: str, xpats: tuple, ypats: tuple, negate_y: bool = False,
            xlabel: "str | None" = None, ylabel: "str | None" = None,
            logx: bool = False, logy: bool = False,
            equal: bool = False) -> None:
        xc, yc = _find_col(df, *xpats), _find_col(df, *ypats)
        if not (xc and yc):
            return
        x, y = _pair(df, xc, yc)
        if negate_y:
            y = -y
        if not len(x):
            return
        stride = max(1, len(x) // _MAX_PLOT_POINTS)
        plots.append({
            "title": title, "xlabel": xlabel or xc, "ylabel": ylabel or yc,
            "logx": logx, "logy": logy, "equal": equal,
            "x": x[::stride].tolist(), "y": y[::stride].tolist(),
        })

    def _vi() -> "tuple[np.ndarray, np.ndarray, np.ndarray] | None":
        """(time, Vf, Im) with a common finite mask, or None."""
        tc = _find_col(df, r"^time")
        vc = _find_col(df, r"^vf")
        ic = _find_col(df, r"^im")
        if not (tc and vc and ic):
            return None
        t = _numeric(df, tc)
        v = _numeric(df, vc)
        i = _numeric(df, ic)
        mask = np.isfinite(t) & np.isfinite(v) & np.isfinite(i)
        if not mask.any():
            return None
        return t[mask], v[mask], i[mask]

    if technique == "CV":
        add("Cyclic voltammogram", (r"^vf",), (r"^im",))
        if rs:
            tvi = _vi()
            if tvi is not None:
                _t, v, i = tvi
                stride = max(1, len(v) // _MAX_PLOT_POINTS)
                plots.append({
                    "title": "Cyclic voltammogram (iR-corrected)",
                    "xlabel": f"Vf - Im*Rs (V, Rs={rs:g} Ohm)",
                    "ylabel": "Im (A)", "logx": False, "logy": False,
                    "x": (v - i * rs)[::stride].tolist(),
                    "y": i[::stride].tolist(),
                })
    elif technique == "EIS":
        add("Nyquist", (r"^zreal",), (r"^zimag",), negate_y=True,
            ylabel="-Zimag (Ohm)", equal=True)
        add("Bode |Z|", (r"^freq",), (r"^zmod",), logx=True, logy=True)
        add("Bode phase", (r"^freq",), (r"^zphz",), logx=True,
            ylabel="Phase (deg)")
    elif technique == "CA":
        add("Current vs time", (r"^time",), (r"^im",))
    elif technique == "CP":
        add("Potential vs time", (r"^time",), (r"^vf",))
        if rs:
            tvi = _vi()
            if tvi is not None:
                t, v, i = tvi
                stride = max(1, len(t) // _MAX_PLOT_POINTS)
                plots.append({
                    "title": "Potential vs time (iR-corrected)",
                    "xlabel": "Time (s)",
                    "ylabel": f"Vf - Im*Rs (V, Rs={rs:g} Ohm)",
                    "logx": False, "logy": False,
                    "x": t[::stride].tolist(),
                    "y": (v - i * rs)[::stride].tolist(),
                })
    elif technique == "OCP":
        add("Open-circuit potential", (r"^time",), (r"^vf",))
    return plots


# ── Metrics ───────────────────────────────────────────────────────────────────

def _metrics_cv(df: pd.DataFrame) -> dict:
    vc, ic = _find_col(df, r"^vf"), _find_col(df, r"^im")
    if not (vc and ic):
        return {}
    out: dict = {}
    sub = df
    cyc = _find_col(df, r"^cycle")
    if cyc is not None:
        cnum = pd.to_numeric(df[cyc], errors="coerce")
        last = cnum.max()
        if pd.notna(last):
            out["cycles"] = int(last - cnum.min() + 1)
            # Analyse the last complete cycle (most representative)
            s2 = df[cnum == last]
            if len(s2) >= 10:
                sub = s2
    v, i = _pair(sub, vc, ic)
    if not len(v):
        return out
    ka, kc = int(np.argmax(i)), int(np.argmin(i))
    out["E_pa (V)"] = _sig(v[ka])
    out["I_pa (A)"] = _sig(i[ka])
    out["E_pc (V)"] = _sig(v[kc])
    out["I_pc (A)"] = _sig(i[kc])
    out["dEp (V)"] = _sig(v[ka] - v[kc])
    if i[kc]:
        out["|I_pa/I_pc|"] = _sig(abs(i[ka] / i[kc]))
    return out


def _metrics_eis(df: pd.DataFrame) -> dict:
    fc, zrc = _find_col(df, r"^freq"), _find_col(df, r"^zreal")
    if not (fc and zrc):
        return {}
    f, zr = _pair(df, fc, zrc)
    if not len(f):
        return {}
    hi, lo = int(np.argmax(f)), int(np.argmin(f))
    rs = zr[hi]
    out = {
        "Rs (Ohm)": _sig(rs),                 # high-frequency intercept
        "Rp (Ohm)": _sig(zr[lo] - rs),        # polarisation resistance estimate
    }
    zic = _find_col(df, r"^zimag")
    if zic:
        f2, zi = _pair(df, fc, zic)
        if len(f2):
            k = int(np.argmax(-zi))
            out["f_peak (Hz)"] = _sig(f2[k])  # frequency at max -Zimag
    zmc = _find_col(df, r"^zmod")
    if zmc:
        f3, zm = _pair(df, fc, zmc)
        if len(f3):
            out["|Z| @ fmin (Ohm)"] = _sig(zm[int(np.argmin(f3))])
    return out


def _tail_mean(y: np.ndarray, frac: float = 0.1) -> float:
    n = max(1, int(len(y) * frac))
    return float(np.mean(y[-n:]))


def _metrics_ca(df: pd.DataFrame) -> dict:
    tc, ic = _find_col(df, r"^time"), _find_col(df, r"^im")
    if not (tc and ic):
        return {}
    t, i = _pair(df, tc, ic)
    if len(t) < 2:
        return {}
    return {
        "I_final (A)": _sig(_tail_mean(i)),
        "Q (C)": _sig(float(_trapz(i, t))),
        "duration (s)": _sig(t[-1] - t[0]),
    }


def _metrics_cp(df: pd.DataFrame) -> dict:
    tc, vc = _find_col(df, r"^time"), _find_col(df, r"^vf")
    if not (tc and vc):
        return {}
    t, v = _pair(df, tc, vc)
    if len(t) < 2:
        return {}
    return {
        "V_final (V)": _sig(_tail_mean(v)),
        "V_min (V)": _sig(float(np.min(v))),
        "V_max (V)": _sig(float(np.max(v))),
        "duration (s)": _sig(t[-1] - t[0]),
    }


def _metrics_ocp(df: pd.DataFrame) -> dict:
    tc, vc = _find_col(df, r"^time"), _find_col(df, r"^vf")
    if not (tc and vc):
        return {}
    t, v = _pair(df, tc, vc)
    if len(t) < 2:
        return {}
    slope = float(np.polyfit(t, v, 1)[0])     # V/s
    return {
        "V_start (V)": _sig(float(v[0])),
        "V_final (V)": _sig(_tail_mean(v)),
        "drift (mV/min)": _sig(slope * 1000.0 * 60.0),
        "duration (s)": _sig(t[-1] - t[0]),
    }


def _cp_overpotential(df: pd.DataFrame, eoc: "float | None",
                      rs: "float | None") -> dict:
    """Overpotential of a constant-current (CP) step: steady-state potential
    minus the open-circuit potential (from an OCP block earlier in the run,
    or the block's OCV reference), optionally corrected for the ohmic drop
    I·Rs using the run's EIS series resistance."""
    tc, vc = _find_col(df, r"^time"), _find_col(df, r"^vf")
    if not (tc and vc):
        return {}
    t, v = _pair(df, tc, vc)
    if len(t) < 2:
        return {}
    out: dict = {}
    v_fin = _tail_mean(v)
    i_app = None
    ic = _find_col(df, r"^im")
    if ic:
        _t2, i2 = _pair(df, tc, ic)
        if len(i2):
            i_app = _tail_mean(i2)
    if rs:
        out["Rs used (Ohm)"] = _sig(rs)
        if i_app is not None:
            out["iR drop (V)"] = _sig(i_app * rs)
    if eoc is not None:
        out["E_oc used (V)"] = _sig(eoc)
        out["eta (V)"] = _sig(v_fin - eoc)
        if rs and i_app is not None:
            out["eta iR-free (V)"] = _sig(v_fin - i_app * rs - eoc)
    return out


_METRIC_FNS = {
    "CV": _metrics_cv, "EIS": _metrics_eis, "CA": _metrics_ca,
    "CP": _metrics_cp, "OCP": _metrics_ocp,
}


def _metrics(technique: str, df: pd.DataFrame) -> dict:
    fn = _METRIC_FNS.get(technique)
    if fn is None:
        return {}
    try:
        out = fn(df)
    except Exception:
        logger.warning("Metric extraction failed for %s.", technique,
                       exc_info=True)
        return {}
    out["points"] = int(len(df))
    return out


# ── Report building ───────────────────────────────────────────────────────────

def build_report(measurements: list, sequence_run_id: str,
                 sequence_name: str) -> dict:
    """Assemble the analysis report from executed measurements.

    measurements: [{run_id, technique, csv_path, params, sample_id, aborted}]
    in execution order. Missing/unreadable CSVs are skipped, never fatal.
    """
    # Pass 1: load data + collect run-level context (EIS Rs, OCP potentials)
    loaded: list = []
    for k, m in enumerate(measurements, 1):
        csv_path = m.get("csv_path")
        if not csv_path or not os.path.isfile(csv_path):
            logger.warning("Report: missing CSV for measurement %s.", m.get("run_id"))
            continue
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            logger.warning("Report: unreadable CSV %s.", csv_path, exc_info=True)
            continue
        loaded.append((k, m, df))

    eis_rs: dict = {}   # position → series resistance
    ocp_v: dict = {}    # position → final open-circuit potential
    for pos, (_k, m, df) in enumerate(loaded):
        tech = str(m.get("technique", ""))
        if tech == "EIS":
            r = _metrics_eis(df).get("Rs (Ohm)")
            if r is not None:
                eis_rs[pos] = float(r)
        elif tech == "OCP":
            v = _metrics_ocp(df).get("V_final (V)")
            if v is not None:
                ocp_v[pos] = float(v)

    def _nearest_before(d: dict, pos: int) -> "float | None":
        """Latest value earlier in the run; falls back to the first later one."""
        best = None
        for j, v in d.items():          # insertion-ordered, ascending
            if j < pos:
                best = v
        if best is None and d:
            best = next(iter(d.values()))
        return best

    # Pass 2: build groups with overlay plots + metrics
    groups: dict = {}
    order: list = []
    n_ok = 0
    for pos, (k, m, df) in enumerate(loaded):
        tech = str(m.get("technique", ""))
        rs = _nearest_before(eis_rs, pos) if tech in ("CV", "CP") else None
        label = f"{k}. " + (m.get("sample_id") or m.get("run_id") or tech)
        if m.get("aborted"):
            label += " (aborted)"
        if tech not in groups:
            groups[tech] = {"technique": tech, "plots": {}, "measurements": []}
            order.append(tech)
        g = groups[tech]
        for p in _extract_plots(tech, df, rs):
            merged = g["plots"].setdefault(p["title"], {
                "title": p["title"], "xlabel": p["xlabel"], "ylabel": p["ylabel"],
                "logx": p["logx"], "logy": p["logy"],
                "equal": p.get("equal", False), "series": [],
            })
            merged["series"].append({"label": label, "x": p["x"], "y": p["y"]})
        metrics = _metrics(tech, df)
        if tech == "CP":
            eoc = _nearest_before(ocp_v, pos)
            if eoc is None and m.get("reference_v") is not None \
                    and m.get("vs") == "OCV":
                eoc = float(m["reference_v"])
            metrics.update(_cp_overpotential(df, eoc, rs))
        g["measurements"].append({
            "run_id": m.get("run_id"),
            "label": label,
            "sample_id": m.get("sample_id", ""),
            "aborted": bool(m.get("aborted")),
            "params": m.get("params", {}),
            "vs": m.get("vs", "Ref"),
            "reference_v": m.get("reference_v"),
            "csv_path": str(m.get("csv_path")).replace("\\", "/"),
            "metrics": metrics,
        })
        n_ok += 1
    return {
        "sequence_run_id": sequence_run_id,
        "sequence": sequence_name,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_measurements": n_ok,
        "groups": [
            {**groups[t], "plots": list(groups[t]["plots"].values())}
            for t in order
        ],
    }


# ── Persistence ───────────────────────────────────────────────────────────────

def _safe_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", str(run_id)):
        raise ValueError(f"Bad run id '{run_id}'.")
    return str(run_id)


def save_report(echem_dir: str, report: dict) -> str:
    folder = os.path.join(echem_dir, _REPORTS_SUBDIR)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, _safe_id(report["sequence_run_id"]) + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f)
    logger.info("Analysis report saved: %s", path)
    return path


def list_reports(echem_dir: str) -> list:
    folder = os.path.join(echem_dir, _REPORTS_SUBDIR)
    if not os.path.isdir(folder):
        return []
    out = []
    for path in sorted(glob.glob(os.path.join(folder, "*.json")), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                rep = json.load(f)
        except Exception:
            continue
        out.append({
            "run_id": rep.get("sequence_run_id"),
            "sequence": rep.get("sequence"),
            "generated_at": rep.get("generated_at"),
            "n_measurements": rep.get("n_measurements", 0),
        })
    return out


def load_or_rebuild(echem_dir: str, run_id: str) -> dict:
    """Load a saved report; if absent, rebuild it from measurement sidecar
    files carrying this sequence_run_id (pre-feature runs, deleted reports)."""
    run_id = _safe_id(run_id)
    path = os.path.join(echem_dir, _REPORTS_SUBDIR, run_id + ".json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    measurements = []
    for jp in glob.glob(os.path.join(echem_dir, "**", "*.json"), recursive=True):
        if os.path.basename(os.path.dirname(jp)) == _REPORTS_SUBDIR:
            continue
        try:
            with open(jp, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue
        if (not isinstance(meta, dict) or "technique" not in meta
                or meta.get("sequence_run_id") != run_id):
            continue
        measurements.append({**meta, "csv_path": jp[:-5] + ".csv"})
    if not measurements:
        raise KeyError(f"No report or measurements for sequence run '{run_id}'.")
    measurements.sort(key=lambda m: str(m.get("run_id") or ""))
    report = build_report(measurements, run_id,
                          str(measurements[0].get("sequence", "")))
    save_report(echem_dir, report)
    return report
