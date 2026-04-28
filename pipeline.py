"""
Calcium Imaging Analysis Pipeline
==================================
Processes fluorescence calcium imaging data exported from widefield/confocal
imaging software for multiple coverslip preparations.

Usage:
    python pipeline.py                    # uses config.yaml in current directory
    python pipeline.py --config my.yaml   # uses a custom config file

Outputs per coverslip (inside Output/<run_name>/<coverslip_name>/):
    normalized_data.csv              — full normalized traces + spike detection rows + AUC rows
    Peak value of each column.csv    — peak, frames-to-peak, latency, AUC per neuron
    <ROI>_plot.jpg                   — individual fluorescence trace per ROI
    <coverslip>- All flourecence Traces.jpg — overlay of all traces
    Existance_Yes_No_plot.png        — stacked bar chart of Yes/No response counts
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # non-interactive backend — must be set before pyplot import
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config(config_path: str = "config.yaml") -> dict:
    """Load and return the YAML configuration file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {path}\n"
            "Make sure config.yaml is in the same directory as pipeline.py."
        )
    with open(path, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    log.info("Loaded config from %s", path)
    return config


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def load_time_axis(config: dict) -> list | None:
    """
    Load optional time-axis values (seconds) from an Excel file.
    Returns a list of floats, or None if the file does not exist.
    """
    path = Path(config["paths"]["time_axis_file"])
    if path.exists():
        df = pd.read_excel(path, sheet_name=0)
        log.info("Loaded time axis from %s (%d points)", path, len(df))
        return df.iloc[:, 0].tolist()
    log.warning(
        "Time axis file not found: %s — using frame indices for x-axis.", path
    )
    return None


def load_background_columns(config: dict) -> dict[str, str]:
    """
    Load the background-column mapping from the Background_Columns Excel file.

    Expected sheet layout:
        File_Name          | Background_Columns
        cv1                | R15 W4 Avg
        cv2                | R11 W4 Avg, R12 W4 Avg
        ...

    Returns a dict  {coverslip_stem: "col1, col2, ..."}
    """
    path = Path(config["paths"]["background_columns_file"])
    if not path.exists():
        raise FileNotFoundError(f"Background columns file not found: {path}")
    df = pd.read_excel(path, sheet_name=0)
    mapping: dict[str, str] = df.set_index("File_Name")["Background_Columns"].to_dict()
    log.info("Loaded background columns for %d coverslip(s).", len(mapping))
    return mapping


def get_coverslip_files(config: dict) -> list[Path]:
    """Return sorted list of .xlsx files in the input directory."""
    input_dir = Path(config["paths"]["input_dir"])
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    files = sorted(input_dir.glob("*.xlsx"))
    log.info("Found %d coverslip file(s) in %s.", len(files), input_dir)
    return files


# ---------------------------------------------------------------------------
# Pre-processing
# ---------------------------------------------------------------------------

def preprocess(df: pd.DataFrame, background_columns_str: str) -> pd.DataFrame:
    """
    1. Drop all columns whose name contains the word 'Area'.
    2. Subtract the row-wise mean of the designated background columns.
    3. Drop the background columns from the result.

    Parameters
    ----------
    df : raw coverslip DataFrame (includes a 'Time (sec)' column)
    background_columns_str : comma-separated ROI column names to use as background

    Returns
    -------
    DataFrame with background-subtracted fluorescence values and 'Time (sec)' column.
    """
    # Remove 'Area' columns
    filtered = df.filter(regex=r"^(?!.*Area).*$", axis=1)

    # Parse background column list
    bg_cols = [c.strip() for c in re.split(r",\s*", background_columns_str) if c.strip()]
    missing = [c for c in bg_cols if c not in filtered.columns]
    if missing:
        raise KeyError(
            f"Background column(s) not found in data: {missing}\n"
            f"Available columns: {filtered.columns.tolist()}"
        )

    time_col = filtered["Time (sec)"].copy()
    bg_mean = filtered[bg_cols].mean(axis=1)

    subtracted = filtered.drop(columns=["Time (sec)"]).sub(bg_mean, axis=0)
    result = pd.concat([time_col, subtracted], axis=1)
    result = result.drop(columns=bg_cols)
    return result


def normalize(df: pd.DataFrame, baseline_end: int, avg_frames: int) -> pd.DataFrame:
    """
    Normalize each fluorescence column to F/F0, where F0 is the mean of the
    last `avg_frames` frames of the baseline period.

    The 'Time (sec)' column is preserved unchanged.
    """
    start = max(0, baseline_end - avg_frames)
    f0 = df.iloc[start:baseline_end].mean()

    normalized = df.div(f0)
    normalized.iloc[:, 0] = df.iloc[:, 0]   # restore Time column (divided itself → 1s)
    return normalized


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def detect_spike_presence(
    norm_df: pd.DataFrame, config: dict
) -> pd.DataFrame:
    """
    Classify each ROI as 'Yes' or 'No' for Stimulus 1 and Stimulus 2.

    Stimulus 1 window : [baseline_end, wash_end)
    Stimulus 2 window : [wash_end, stimulus2_end)

    A neuron is classified 'Yes' if any value in the window exceeds:
        last-baseline-frame value × (1 + spike_detection_percent / 100)
    for Stim1, and
        last-wash-frame value × (1 + stimulus2_percent / 100)
    for Stim2.
    """
    b = config["frame_boundaries"]
    baseline_end   = b["baseline_end"]
    wash_end        = b["wash_end"]
    stimulus2_end   = b["stimulus2_end"]
    spike_pct       = config["spike_detection_percent"]
    stim2_pct       = config["thresholds"]["stimulus2_percent"]

    result = pd.DataFrame(columns=norm_df.columns)
    result.loc[0, "Time (sec)"] = "Stimulus_1"
    result.loc[1, "Time (sec)"] = "Stimulus_2"

    base_ref_s1  = norm_df.iloc[baseline_end - 1]
    base_ref_s2  = norm_df.iloc[wash_end - 1]
    thresh_s1    = base_ref_s1 * (1 + spike_pct / 100)
    thresh_s2    = base_ref_s2 * (1 + stim2_pct / 100)

    for col in norm_df.columns[1:]:
        window_s1 = norm_df[col].iloc[baseline_end : wash_end - 1]
        result.loc[0, col] = "Yes" if (window_s1 > thresh_s1[col]).any() else "No"

        window_s2 = norm_df[col].iloc[wash_end : stimulus2_end]
        result.loc[1, col] = "Yes" if (window_s2 > thresh_s2[col]).any() else "No"

    return result


def calculate_peak_metrics(norm_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    For each ROI compute:
      Stimulus 1  →  Peak Value,            No of Frames to Peak
      Stimulus 2  →  Stim2 - Peak Value,    No of Frames to Peak in Stim2

    Returns a DataFrame with one row per ROI (Time column excluded).
    """
    b = config["frame_boundaries"]
    baseline_end  = b["baseline_end"]
    wash_end      = b["wash_end"]
    stimulus2_end = b["stimulus2_end"]

    def _peak_df(window: pd.DataFrame, offset: int, value_col: str, frames_col: str) -> pd.DataFrame:
        max_vals = window.max()
        max_idx  = window.idxmax()
        d = pd.DataFrame(
            {
                "Column Names": max_vals.index,
                value_col:      max_vals.values,
                "_idx":         max_idx.values,
            }
        ).iloc[1:]   # skip Time (sec)
        d[frames_col] = d["_idx"].apply(lambda x: x - offset)
        return d.drop(columns=["_idx"])

    s1 = _peak_df(
        norm_df.iloc[baseline_end:wash_end],
        baseline_end,
        "Peak Value",
        "No of Frames to Peak",
    )
    s2 = _peak_df(
        norm_df.iloc[wash_end:stimulus2_end],
        wash_end,
        "Stim2 - Peak Value",
        "No of Frames to Peak in Stim2",
    )
    return s1.merge(s2, on="Column Names", how="left")


def calculate_latency(
    norm_df: pd.DataFrame, peak_df: pd.DataFrame, config: dict
) -> pd.DataFrame:
    """
    For each configured threshold percentage and its corresponding stimulus window,
    calculate the number of frames it takes each ROI to exceed
        baseline_value × (1 + pct / 100)

    Adds columns to peak_df:
        Base Value {pct}%
        No of Frames to {pct}%
        {pct}% Rise Exists
    """
    b = config["frame_boundaries"]
    baseline_end  = b["baseline_end"]
    wash_end      = b["wash_end"]
    stimulus2_end = b["stimulus2_end"]

    pct_s1 = config["thresholds"]["stimulus1_percent"]
    pct_s2 = config["thresholds"]["stimulus2_percent"]
    ref_s1 = config["baseline_reference_frames"]["stimulus1"]
    ref_s2 = config["baseline_reference_frames"]["stimulus2"]

    specs = [
        {
            "pct":     pct_s1,
            "window":  norm_df.iloc[baseline_end:wash_end],
            "base":    norm_df.iloc[baseline_end - 1],
            "ref":     ref_s1,
        },
        {
            "pct":     pct_s2,
            "window":  norm_df.iloc[wash_end:stimulus2_end],
            "base":    norm_df.iloc[wash_end - 1],
            "ref":     ref_s2,
        },
    ]

    result = peak_df.copy()

    for spec in specs:
        pct      = spec["pct"]
        window   = spec["window"]
        base     = spec["base"]
        ref      = spec["ref"]
        mult     = 1 + pct / 100
        threshold = base * mult

        first_idx: dict[str, int] = {}
        for col in window.columns[1:]:
            over = window[col] > threshold[col]
            first_idx[col] = int(over.idxmax()) if over.any() else 0

        series = pd.Series(first_idx)

        base_col   = f"Base Value {pct}%"
        frames_col = f"No of Frames to {pct}%"
        exists_col = f"{pct}% Rise Exists"

        result[base_col]   = base.values[1:]
        result[frames_col] = series.values
        result[frames_col] = result[frames_col].apply(lambda x: x - ref)
        result[frames_col] = result[frames_col].apply(lambda x: "-" if x < 0 else x)
        result[exists_col] = result[frames_col].apply(lambda x: "Yes" if x != "-" else "No")

    return result


def calculate_auc(norm_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Compute trapezoidal AUC (frame interval = 1.5 s) for two windows:
        Stimulus1_2_Wash_AUC : [baseline_end, wash_end)
        Stimulus_2_AUC       : [wash_end, stimulus2_end]

    Returns a two-row DataFrame appended to norm_df layout.
    """
    b = config["frame_boundaries"]
    baseline_end  = b["baseline_end"]
    wash_end      = b["wash_end"]
    stimulus2_end = b["stimulus2_end"]

    def _auc(values: np.ndarray, dt: float = 1.5) -> float:
        return float(np.sum(((values[:-1] + values[1:]) / 2.0) * dt))

    result = pd.DataFrame(columns=norm_df.columns)
    result.loc[0, "Time (sec)"] = "Stimulus1_2_Wash_AUC"
    result.loc[1, "Time (sec)"] = "Stimulus_2_AUC"

    w1 = norm_df.iloc[baseline_end:wash_end]
    w2 = norm_df.iloc[wash_end : stimulus2_end + 1]

    for col in norm_df.columns:
        result.loc[0, col] = _auc(w1[col].to_numpy())
        result.loc[1, col] = _auc(w2[col].to_numpy())

    result.loc[0, "Time (sec)"] = "Stimulus1_2_Wash_AUC"
    result.loc[1, "Time (sec)"] = "Stimulus_2_AUC"
    return result


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def _x_axis(time_axis: list | None, n_frames: int) -> list:
    """Return x-axis values trimmed/padded to n_frames."""
    if time_axis is not None:
        return time_axis[:n_frames]
    return list(range(n_frames))


def plot_individual_traces(
    norm_df: pd.DataFrame,
    time_axis: list | None,
    config: dict,
    output_dir: Path,
) -> None:
    """Save one .jpg trace plot per ROI column."""
    n = config["frame_boundaries"]["stimulus2_end"]
    x = _x_axis(time_axis, n)
    vlines = config["plot"].get("vertical_lines", [])

    for col in norm_df.columns[1:]:
        y = norm_df[col].tolist()[:n]
        y_max = max(y) if y else 1.0
        y_ticks = np.arange(0, y_max + 0.2, 0.2)

        fig, ax = plt.subplots(figsize=(18, 6), dpi=100)
        ax.set_xlabel("Time (sec)")
        ax.set_ylabel("Normalized F/F\u2080")
        ax.set_title(col)
        ax.plot(x, y, color="purple")
        ax.set_yticks(y_ticks)

        for vl in vlines:
            ax.axvline(x=vl["position"], color="green", linestyle="--", linewidth=1)
            ax.text(
                vl["position"] + 1,
                y_max,
                vl["label"],
                verticalalignment="bottom",
                color="black",
            )

        fig.savefig(output_dir / f"{col}_plot.jpg", bbox_inches="tight")
        plt.close(fig)


def plot_all_traces(
    norm_df: pd.DataFrame,
    time_axis: list | None,
    config: dict,
    output_dir: Path,
    coverslip_name: str,
) -> None:
    """Save an overlay plot of all ROI traces."""
    n = config["frame_boundaries"]["stimulus2_end"]
    x = _x_axis(time_axis, n)

    fig, ax = plt.subplots(figsize=(18, 6), dpi=100)
    for col in norm_df.columns[1:]:
        ax.plot(x, norm_df[col].tolist()[:n])

    ax.set_title(f"{coverslip_name} - All Fluorescence Traces")
    ax.set_xlabel("Time (sec)")
    ax.set_ylabel("Normalized F/F\u2080")
    fig.savefig(
        output_dir / f"{coverslip_name}- All flourecence Traces.jpg",
        bbox_inches="tight",
    )
    plt.close(fig)


def plot_spike_detection_bar(
    neuron_df: pd.DataFrame, output_dir: Path
) -> None:
    """Save a stacked bar chart showing Yes / No response counts per stimulus."""
    df = neuron_df.set_index("Time (sec)")
    count_yes = (df == "Yes").sum(axis=1)
    count_no  = (df == "No").sum(axis=1)

    fig, ax = plt.subplots()
    idx = range(len(count_yes))
    bar_w = 0.35

    bars_yes = ax.bar(idx, count_yes, bar_w, alpha=0.8, color="steelblue", label="Yes")
    bars_no  = ax.bar(idx, count_no,  bar_w, alpha=0.8, color="tomato",    label="No",
                      bottom=count_yes)

    ax.set_xlabel("Stimulus")
    ax.set_ylabel("Count")
    ax.set_title("Neuron Response Detection")
    ax.set_xticks(list(idx))
    ax.set_xticklabels(df.index)
    ax.legend()

    for r_yes, r_no in zip(bars_yes, bars_no):
        h_yes = r_yes.get_height()
        h_no  = r_no.get_height()
        if h_yes > 0:
            ax.text(r_yes.get_x() + r_yes.get_width() / 2, h_yes / 2,
                    f"{int(h_yes)}", ha="center", va="center", color="white", fontweight="bold")
        if h_no > 0:
            ax.text(r_no.get_x() + r_no.get_width() / 2, h_yes + h_no / 2,
                    f"{int(h_no)}", ha="center", va="center", color="white", fontweight="bold")

    fig.savefig(output_dir / "Existance_Yes_No_plot.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Per-coverslip orchestration
# ---------------------------------------------------------------------------

def process_coverslip(
    file_path: Path,
    background_columns_map: dict[str, str],
    time_axis: list | None,
    config: dict,
    output_base: Path,
) -> None:
    """Run the full pipeline for a single coverslip file."""
    name = file_path.stem
    log.info("Processing coverslip: %s", name)

    if name not in background_columns_map:
        log.warning(
            "  No entry for '%s' in Background_Columns.xlsx — skipping.", name
        )
        return

    # --- Load raw data ---
    raw_df = pd.read_excel(file_path)

    # --- Pre-process ---
    bg_str = background_columns_map[name]
    preprocessed = preprocess(raw_df, bg_str)

    # --- Normalize ---
    b = config["frame_boundaries"]
    norm_df = normalize(
        preprocessed,
        b["baseline_end"],
        config["normalization"]["avg_baseline_frames"],
    )

    # --- Analysis ---
    neuron_presence = detect_spike_presence(norm_df, config)
    peak_df         = calculate_peak_metrics(norm_df, config)
    peak_latency_df = calculate_latency(norm_df, peak_df, config)
    auc_df          = calculate_auc(norm_df, config)

    # --- Output directory ---
    out_dir = output_base / name
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Save CSVs ---
    peak_latency_df.to_csv(out_dir / "Peak value of each column.csv", index=False)

    combined = pd.concat([norm_df, neuron_presence, auc_df], ignore_index=True)
    combined.to_csv(out_dir / "normalized_data.csv", index=False)

    # --- Save plots ---
    plot_individual_traces(norm_df, time_axis, config, out_dir)
    plot_all_traces(norm_df, time_axis, config, out_dir, name)
    plot_spike_detection_bar(neuron_presence, out_dir)

    log.info("  Outputs written to: %s", out_dir)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calcium imaging analysis pipeline"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="PATH",
        help="Path to the YAML configuration file (default: config.yaml)",
    )
    args = parser.parse_args()

    t0 = time.perf_counter()

    config      = load_config(args.config)
    time_axis   = load_time_axis(config)
    bg_map      = load_background_columns(config)
    cv_files    = get_coverslip_files(config)

    output_base = Path(config["paths"]["output_dir"]) / config["run_name"]
    output_base.mkdir(parents=True, exist_ok=True)

    for fp in cv_files:
        process_coverslip(fp, bg_map, time_axis, config, output_base)

    elapsed = time.perf_counter() - t0
    log.info("Pipeline complete. Total time: %.2f s", elapsed)


if __name__ == "__main__":
    main()
