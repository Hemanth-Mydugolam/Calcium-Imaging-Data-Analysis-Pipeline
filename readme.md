# Calcium Imaging Data Analysis Pipeline

Python pipeline for batch processing fluorescence calcium imaging data from coverslip-based neuronal preparations. The pipeline performs background subtraction, F/F₀ normalization, spike detection, peak analysis, latency-to-threshold calculations, AUC computation, and plots response trances.

---

## Compatible Imaging Software

This pipeline is designed for data exported from **fluorescence calcium imaging systems** where regions of interest (ROIs) are drawn around individual neurons and mean fluorescence values are exported to Excel.

It has been developed and validated with data from experiments using fluorescence microscopy rigs where acquisition/analysis software exports ROI measurements in the column format:

```
Time (sec) | R1 W4 Avg | R2 W4 Avg | R3 W4 Avg | ...
```

Where `R#` = ROI number and `W4` = wavelength/channel identifier. This naming convention is produced by systems such as:

- **Metamorph / MetaFluor** (Molecular Devices)

> **Check compatibility:** Open one of your coverslip `.xlsx` files. If the columns follow the `R# W# Avg` pattern with a `Time (sec)` as first column, this pipeline will work for your data.

---

## Quick Start

### 1. Get the repository

**Option A — Git clone (recommended if you have Git installed):**

```bash
git clone https://github.com/Hemanth-Mydugolam/Calcium-Imaging-Data-Analysis-Pipeline.git
cd Calcium-Imaging-Data-Analysis-Pipeline
```

**Option B — Download as ZIP (no Git required):**

1. Go to the repository page on GitHub: [https://github.com/Hemanth-Mydugolam/Calcium-Imaging-Data-Analysis-Pipeline](https://github.com/Hemanth-Mydugolam/Calcium-Imaging-Data-Analysis-Pipeline)
2. Click the green **`< > Code`** button near the top right.
3. Select **Download ZIP** from the dropdown.
4. Once downloaded, **extract (unzip)** the folder to a location of your choice (e.g., your Desktop or Documents folder).
5. Open a terminal/command prompt and navigate into the extracted folder:

```bash
# Replace the path below with wherever you extracted the folder
cd ~/Desktop/Calcium-Imaging-Data-Analysis-Pipeline-main
```

> **Note:** The extracted folder will be named `Calcium-Imaging-Data-Analysis-Pipeline-main` by default (GitHub appends `-main` to ZIP downloads). You can rename it if you prefer.

### 2. Install dependencies

Python 3.10 or later is required.

```bash
pip install -r requirements.txt
```

### 3. Prepare your input data

See [Input Format](#input-format) below.

### 4. Edit `config.yaml`

Open `config.yaml` and adjust the frame boundaries, thresholds, and plot labels to match your experiment. See [Configuration](#configuration) for details.

### 5. Run the pipeline

```bash
python pipeline.py
```

Outputs are written to `Output/<run_name>/`. To use a different config file:

```bash
python pipeline.py --config my_experiment.yaml
```

---

## Repository Structure

```
calcium-imaging-pipeline/
├── pipeline.py                          # Main pipeline script
├── config.yaml                          # User configuration (edit this)
├── requirements.txt                     # Python dependencies
│
├── Input/
│   ├── cv1.xlsx                         # One file per coverslip
│   ├── cv2.xlsx
│   ├── ...
│   ├── Background_Columns_Data/
│   │   └── Background_Columns.xlsx      # Background ROI mapping (required)
│   └── X_axis_time.xlsx                 # Optional: time values for x-axis
│
└── Output/
    └── Run1/                            # Created automatically per run_name
        ├── cv1/
        │   ├── normalized_data.csv
        │   ├── Peak value of each column.csv
        │   ├── R1 W4 Avg_plot.jpg
        │   ├── ...
        │   ├── cv1- All flourecence Traces.jpg
        │   └── Existance_Yes_No_plot.png
        └── cv2/
            └── ...
```

---

## Input Format

### Coverslip files (`Input/*.xlsx`)

Each coverslip is a single Excel file. The pipeline processes **all `.xlsx` files** found in the `Input/` directory (subdirectories are ignored).

| Column | Format | Description |
|--------|--------|-------------|
| `Time (sec)` | Float | Acquisition time in seconds |
| `R1 W4 Avg` | Float | Mean fluorescence for ROI 1 |
| `R2 W4 Avg` | Float | Mean fluorescence for ROI 2 |
| `R1 W4 Area` | — | **Automatically excluded** (any column containing "Area") |
| … | … | Additional ROIs follow the same pattern |

- Each file must contain **exactly one sheet** with only the time points, ROI columns, and background columns — no additional sheets, metadata rows, or summary tables.
- The first row must be column headers (no metadata rows above).
- File names become the folder names in the output (e.g., `cv1.xlsx` → `Output/Run1/cv1/`).

**Example layout:**

```
Time (sec)  | R1 W4 Avg | R1 W4 Area | R2 W4 Avg | R2 W4 Area | ...
0.00        | 1523.4    | 45.2       | 1487.2    | 38.6       | ...
1.50        | 1531.7    | 45.2       | 1492.5    | 38.6       | ...
...
```

---

### Background columns file (`Input/Background_Columns_Data/Background_Columns.xlsx`)

This file maps each coverslip to its designated background ROI column(s). Background ROIs are drawn over cell-free areas of the coverslip to correct for non-specific fluorescence.

**Required columns:**

| `File_Name` | `Background_Columns` |
|-------------|----------------------|
| cv1         | R15 W4 Avg           |
| cv2         | R11 W4 Avg           |
| cv3         | R21 W4 Avg, R22 W4 Avg |

- `File_Name` must exactly match the coverslip filename **without the `.xlsx` extension**.
- `Background_Columns` is a comma-separated list of one or more column names from the corresponding coverslip file.
- Coverslip files with **no entry** in this file are **skipped** with a warning.

---

### Time axis file (`Input/X_axis_time.xlsx`) —

An Excel file with a single column containing the time values (in seconds) corresponding to each frame. Used to label the x-axis of all plots.

- The **first column** of the first sheet is used.

---

## Configuration

To customize the pipeline for your experiment, open config.yaml in any text editor (e.g., Notepad++) and update the settings.

### Key parameters

```yaml
run_name: "Run1"          # Output subfolder — change per experiment to avoid overwriting
```

#### Frame boundaries
Define the temporal structure of your experiment. All values are 0-based frame indices.

```
|<------ baseline ----->|<-- Stim1 -->|<------ Wash ------>|<-- Stim2 -->|
0                      250           350                  500           600
```

```yaml
frame_boundaries:
  baseline_end:   250    # End of baseline (= start of Stim1)
  stimulus1_end:  350    # End of Stim1
  wash_end:       500    # End of wash (= start of Stim2)
  stimulus2_end:  600    # End of Stim2 (= end of analysis)
```

#### Normalization
```yaml
normalization:
  avg_baseline_frames: 250   # F0 = mean of last N frames of baseline
```

#### Latency calculations
```yaml
baseline_reference_frames:
  stimulus1: 250    # Frame used as "time zero" for Stim1 latency
  stimulus2: 500    # Frame used as "time zero" for Stim2 latency

thresholds:
  stimulus1_percent: 20   # % above baseline to register a Stim1 latency
  stimulus2_percent: 30   # % above wash-end to register a Stim2 latency
```

#### Response detection (Yes / No)
```yaml
spike_detection_percent: 10   # Any frame exceeding baseline × 1.10 → "Yes"
```

#### Plot annotations
```yaml
plot:
  vertical_lines:
    - position: 307        # x-axis value (time in sec) for the dashed line
      label: "Capsaicin"
    - position: 430
      label: "Wash"
    - position: 615
      label: "High K⁺"
```

---

## Output Files

All outputs are written to `Output/<run_name>/<coverslip_name>/`.

### `normalized_data.csv`

Full-length normalized (F/F₀) traces for all ROIs, with appended metadata rows at the bottom:

| Row label | Description |
|-----------|-------------|
| `Stimulus_1` | Per-ROI Yes/No spike detection for the Stimulus 1 window |
| `Stimulus_2` | Per-ROI Yes/No spike detection for the Stimulus 2 window |
| `Stimulus1_2_Wash_AUC` | Trapezoidal AUC over the Stim1+Wash window (frame interval = 1.5 s) |
| `Stimulus_2_AUC` | Trapezoidal AUC over the Stim2 window |

### `Peak value of each column.csv`

One row per ROI with the following metrics:

| Column | Description |
|--------|-------------|
| `Column Names` | ROI label (e.g., `R1 W4 Avg`) |
| `Peak Value` | Maximum F/F₀ in the Stim1 window |
| `No of Frames to Peak` | Frames from `baseline_end` to peak (Stim1) |
| `Stim2 - Peak Value` | Maximum F/F₀ in the Stim2 window |
| `No of Frames to Peak in Stim2` | Frames from `wash_end` to peak (Stim2) |
| `Base Value {pct}%` | F/F₀ value at the baseline reference frame used for latency |
| `No of Frames to {pct}%` | Frames from reference to first threshold crossing (`-` if never reached) |
| `{pct}% Rise Exists` | `Yes` / `No` |

### `<ROI>_plot.jpg`

Individual fluorescence trace (F/F₀ vs. time) for each ROI, with annotated vertical lines marking stimulus transitions.

### `<coverslip>- All flourecence Traces.jpg`

Overlay of all ROI traces for at-a-glance inspection of the population response.

### `Existance_Yes_No_plot.png`

Stacked bar chart showing the number of ROIs classified as responding (`Yes`) or non-responding (`No`) for Stimulus 1 and Stimulus 2.

---

## Citation

If you use this pipeline in your research, please cite:

> Franco-Enzástiga Ú, Natarajan K, Espinosa F, Granja-Vazquez R, Mydugolam H, Price TJ.
> **Type I IFNs enhance human dorsal root ganglion nociceptor excitability and induce TRPV1 sensitization.**
> *JCI Insight.* 2025;10(19):e194987.
> https://doi.org/10.1172/jci.insight.194987

---

## Credits and Acknowledgments

This Calcium Imaging Data Analysis Pipeline was developed with contributions from the following team members:

**Authors:**
- Keerthana Natarajan
- Urzula, Enzastiga
- Hemanth Mydugolam 

For questions, bug reports, or feature requests, please [open an issue on GitHub](https://github.com/Hemanth-Mydugolam/Calcium-Imaging-Data-Analysis-Pipeline/issues) or reach out to **Hemanth Mydugolam** directly:
- hemanth.mydugolam@gmail.com
- hemanth.mydugolam@utdallas.edu

---

## License

This project is released under the [MIT License](LICENSE).