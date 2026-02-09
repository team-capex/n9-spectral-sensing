from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, List

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

layout = (
    [2, 4, 6, 8, 10, 12, 14, 16] +   # top row (axes[0..7])
    [1, 3, 5, 7, 9, 11, 13, 15]      # bottom row (axes[8..15])
)

# ---------------------------- Data loading / filtering ----------------------------

def load_experiment_dataframe(
    csv_path: str,
    experiment_id: Optional[str] = None,
    board_ids: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Load the CSV into a dataframe and filter by experiment_id and optional board_ids.

    If experiment_id is None, selects the latest experiment by timestamp.
    """
    df = pd.read_csv(csv_path)

    required = {"experiment_id", "timestamp", "board_id", "sensor", "hex_color"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    # Parse timestamps (ISO expected)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    if df["timestamp"].isna().any():
        bad = int(df["timestamp"].isna().sum())
        raise ValueError(f"Found {bad} rows with unparseable timestamp values")

    # Pick latest experiment if none specified (based on max timestamp)
    if experiment_id is None:
        # If multiple experiments exist, pick the one with the latest timestamp
        idx = df["timestamp"].idxmax()
        experiment_id = str(df.loc[idx, "experiment_id"])

    df = df[df["experiment_id"] == experiment_id].copy()

    if board_ids:
        df = df[df["board_id"].isin(board_ids)].copy()

    if df.empty:
        raise ValueError("No rows after applying filters. Check experiment-id / board-id.")

    return df


def get_spectral_columns(df: pd.DataFrame) -> List[str]:
    """
    Return the known spectral columns in a fixed order, filtered to those present in df.
    Update this list if your CSV schema changes.
    """
    ordered = [
        "Violet_%",
        "Blue_%",
        "Cyan_%",
        "Green_%",
        "Yellow_%",
        "Orange_%",
        "Red_%",
    ]
    cols = [c for c in ordered if c in df.columns]
    if not cols:
        raise ValueError("No spectral columns found (expected e.g. 'Violet_%', 'Blue_%', ...).")
    return cols


# ---------------------------- Normalization ----------------------------

def normalize_spectrum(values: np.ndarray, mode: str = "rowmax") -> np.ndarray:
    """
    Normalize one spectrum row.
      - rowmax: divide by max (default, best for shape comparisons)
      - rowsum: divide by sum (useful if you treat it like a distribution)
      - none: no normalization
    """
    values = values.astype(float)

    if mode == "rowmax":
        m = float(np.max(values)) if values.size else 0.0
        return values / m if m > 0 else values

    if mode == "rowsum":
        s = float(np.sum(values)) if values.size else 0.0
        return values / s if s > 0 else values

    if mode == "none":
        return values

    raise ValueError(f"Unknown normalization mode: {mode}")


# ---------------------------- Plotting helpers ----------------------------

def _hex_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    """
    Convert '#RRGGBB' to (r,g,b) floats in 0..1 for matplotlib image strips.
    Falls back to gray on invalid input.
    """
    if not isinstance(hex_color, str):
        return (0.5, 0.5, 0.5)
    s = hex_color.strip()
    if not s.startswith("#") or len(s) != 7:
        return (0.5, 0.5, 0.5)
    try:
        r = int(s[1:3], 16) / 255.0
        g = int(s[3:5], 16) / 255.0
        b = int(s[5:7], 16) / 255.0
        return (r, g, b)
    except Exception:
        return (0.5, 0.5, 0.5)


def add_color_strip(ax: plt.Axes, hex_colors: List[str]) -> None:
    """
    Add a thin time-ordered color strip at the bottom of the subplot showing
    how measured hex_color changes over time.
    """
    if not hex_colors:
        return

    rgb = np.array([_hex_to_rgb01(h) for h in hex_colors], dtype=float)  # (N,3)
    strip = rgb[np.newaxis, :, :]  # (1,N,3)

    # Put strip at the bottom, occupying a small fraction of y-range
    ax.imshow(
        strip,
        aspect="auto",
        extent=(-0.5, len(hex_colors) - 0.5, -0.12, -0.02),
        origin="lower",
        interpolation="nearest",
        clip_on=False,
    )


def plot_sensor_spectra(
    ax: plt.Axes,
    df_sensor: pd.DataFrame,
    spectral_cols: List[str],
    normalization: str,
    max_lines: Optional[int] = None,
) -> None:
    """
    Plot time-evolving spectra for a single sensor as multiple lines.
    Line color = measured hex_color for that timestamp.
    Also adds a thin color strip showing hex_color drift over time.
    """
    if df_sensor.empty:
        ax.axis("off")
        ax.set_title("Unused")
        return

    df_sensor = df_sensor.sort_values("timestamp")

    if max_lines is not None and max_lines > 0 and len(df_sensor) > max_lines:
        df_sensor = df_sensor.iloc[-max_lines:]

    x = np.arange(len(spectral_cols))

    # Plot each timestamp row as one line
    hex_colors = []
    for _, row in df_sensor.iterrows():
        y = row[spectral_cols].to_numpy(dtype=float)
        y = normalize_spectrum(y, normalization)

        hex_c = str(row.get("hex_color", "#808080"))
        hex_colors.append(hex_c)

        ax.plot(
            x,
            y,
            color=hex_c,
            linewidth=1.5,
            alpha=0.85,
        )

    # Color strip: time drift of hex values
    add_color_strip(ax, hex_colors)

    # Axes styling
    ax.set_xticks(x)
    ax.set_xticklabels([c.replace("_%", "") for c in spectral_cols], rotation=45, ha="right")
    if normalization in ("rowmax", "rowsum"):
        ax.set_ylim(-0.15, 1.05)
    else:
        ax.set_ylim(-0.15, float(np.nanmax(df_sensor[spectral_cols].to_numpy())) * 1.05 if len(df_sensor) else 1.0)

    ax.grid(alpha=0.2)


def plot_board_experiment(
    df: pd.DataFrame,
    board_id: str,
    experiment_id: str,
    outdir: Path,
    normalization: str = "rowmax",
    max_lines_per_sensor: Optional[int] = None,
    dpi: int = 150,
) -> Path:
    """
    Create a 2x8 (16 slots) figure for a single board, one subplot per sensor index.
    Missing sensors are shown as blank "Unused".
    Saves one PNG and returns its path.
    """
    spectral_cols = get_spectral_columns(df)

    fig, axes = plt.subplots(2, 8, figsize=(24, 6), sharey=True)
    axes = axes.flatten()

    # Ensure sensor column is int-like
    df_board = df[df["board_id"] == board_id].copy()
    try:
        df_board["sensor"] = df_board["sensor"].astype(int)
    except Exception:
        # leave as-is; filtering below will still work if it's numeric strings
        pass

    for ax, sensor_num in zip(axes, layout):
        df_sensor = df_board[df_board["sensor"].astype(int) == sensor_num]

        plot_sensor_spectra(
            ax=ax,
            df_sensor=df_sensor,
            spectral_cols=spectral_cols,
            normalization=normalization,
            max_lines=max_lines_per_sensor,
        )

        if not df_sensor.empty:
            n = len(df_sensor)
            t0 = df_sensor["timestamp"].min()
            t1 = df_sensor["timestamp"].max()
            ax.set_title(
                f"Sensor {sensor_num} (n={n})\n{t0:%H:%M:%S} → {t1:%H:%M:%S}"
            )
        else:
            ax.set_title(f"Sensor {sensor_num} (unused)")

    fig.suptitle(f"Experiment: {experiment_id} | Board: {board_id}", fontsize=16)

    outdir.mkdir(parents=True, exist_ok=True)
    outfile = outdir / f"{experiment_id}_{board_id}.png"

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    plt.savefig(outfile, dpi=dpi)
    plt.close(fig)

    return outfile


# ---------------------------- CLI ----------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Plot spectral experiment data from CSV log.")
    p.add_argument("--csv", required=True, help="Path to spectral_log.csv")
    p.add_argument("--experiment-id", help="Experiment ID to plot (defaults to latest in file)")
    p.add_argument("--board-id", action="append", help="Board ID filter (repeatable), e.g. --board-id board-1")
    p.add_argument("--outdir", default="plots", help="Output directory for PNG(s)")
    p.add_argument(
        "--normalization",
        choices=["rowmax", "rowsum", "none"],
        default="rowmax",
        help="Spectrum normalization mode",
    )
    p.add_argument(
        "--max-lines-per-sensor",
        type=int,
        default=None,
        help="Limit number of time lines drawn per sensor (keeps latest N)",
    )
    p.add_argument("--dpi", type=int, default=150, help="PNG DPI")
    return p


def main() -> None:
    """
    Entry point for:
        spectral-plotter = "spectral_board_manager.plotter:main"
    """
    # seaborn just for nicer defaults; plotting is still matplotlib
    sns.set_context("notebook")

    args = build_parser().parse_args()

    df = load_experiment_dataframe(
        csv_path=args.csv,
        experiment_id=args.experiment_id,
        board_ids=args.board_id,
    )

    experiment_id = str(df["experiment_id"].iloc[0])
    outdir = Path(args.outdir)

    board_ids = sorted(df["board_id"].unique())
    for board_id in board_ids:
        out = plot_board_experiment(
            df=df,
            board_id=str(board_id),
            experiment_id=experiment_id,
            outdir=outdir,
            normalization=args.normalization,
            max_lines_per_sensor=args.max_lines_per_sensor,
            dpi=args.dpi,
        )
        print(f"[saved] {out}")


if __name__ == "__main__":
    main()
