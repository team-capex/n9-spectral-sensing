"""
trace.py
========
Append-only sample audit trail: data/sample_trace.csv

Every sample-relevant event (transfer, test-cell insert/retrieve, scan,
electrochemical measurement) is logged with timestamp, sample identity,
locations, and a reference to the data it produced, so any dataset can be
traced back to the physical sample and vice versa.
"""

from __future__ import annotations

import csv
import logging
import os
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

TRACE_NAME = "sample_trace.csv"
_HEADERS = [
    "timestamp", "event", "sample_id", "sample_type",
    "from", "to", "data_ref", "run_id", "context",
]
_lock = threading.Lock()


def trace_path(data_dir: str) -> str:
    return os.path.join(data_dir, TRACE_NAME)


def log_event(
    data_dir: str,
    event: str,
    sample_id: str = "",
    sample_type: str = "",
    src: str = "",
    dst: str = "",
    data_ref: str = "",
    run_id: str = "",
    context: str = "",
) -> None:
    """Append one event row (creates the file with headers if needed).
    Never raises — tracing must not break hardware operations."""
    try:
        path = trace_path(data_dir)
        os.makedirs(data_dir, exist_ok=True)
        with _lock:
            new = not os.path.exists(path)
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(_HEADERS)
                w.writerow([
                    datetime.now(timezone.utc).isoformat(),
                    event, sample_id, sample_type, src, dst,
                    data_ref.replace("\\", "/"), run_id, context,
                ])
    except Exception:
        logger.warning("Sample trace write failed", exc_info=True)


def tail(data_dir: str, n: int = 100) -> list:
    """Last n trace rows as dicts, newest last."""
    path = trace_path(data_dir)
    if not os.path.exists(path):
        return []
    with _lock:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    return rows[-n:]


def loc_str(loc: dict) -> str:
    """Human/machine-readable location key, e.g. holder-1:c0:r5, test_cell."""
    if not loc:
        return ""
    if loc.get("type") == "test_cell":
        return "test_cell"
    return f"{loc.get('id')}:c{loc.get('col', 0)}:r{loc.get('row', 0)}"
