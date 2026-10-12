"""Builds examples/compare_conditions.ipynb (run once; edit the notebook itself afterwards)."""

import nbformat as nbf

nb = nbf.v4.new_notebook()
md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = []

cells.append(md("""# Capillary flow porometry: compare runs by rate (mm/min)

Loads every `.CFT` file that matches `PATTERN` in `DATA_DIR`, calculates CapRep's numbers (bubble point,
mean flow pore, smallest pore, pore size distribution), and plots the runs side by side.

**How to use:**
- Change the settings in the next cell, then choose **Run All**.
- Each plot cell is plain matplotlib, so you can change colors, axis limits, labels or figure sizes right in that cell.
- Set `SAVE = True` to write the figures (PNG at 300 dpi, plus SVG) and the tables into `OUT_DIR`.

Calculations come from the `porometry` package in this repo (`src/porometry/analysis.py`), following CapRep's formulas."""))

cells.append(code("""# ---- settings: change these ----
import os
from pathlib import Path

def find_repo():
    \"\"\"The porometry-analyzer folder (works whether the notebook runs from examples/ or the repo root).\"\"\"
    for d in [Path.cwd(), *Path.cwd().parents]:
        if (d / "pyproject.toml").exists() and (d / "src" / "porometry").exists():
            return d
    return Path.cwd()

REPO = find_repo()

# First folder that exists is used. Works on Windows and macOS (Path.home() = C:\\Users\\Brand or /Users/<you>).
# If your SyncThing folder lives somewhere else on this computer, add it to SYNC_ROOTS,
# or set the CFP_DATA_DIR environment variable to the data folder itself.
DATE = "2026-10-11"                 # sub-folder of Data/ to load
SYNC_ROOTS = [Path.home() / "SyncThing", Path.home() / "Sync", Path.home() / "Documents" / "SyncThing"]
DATA_CANDIDATES = (
    [os.environ.get("CFP_DATA_DIR")]
    + [root / "UAkron Playground" / "Capillary Flow Porometer" / "Data" / DATE for root in SYNC_ROOTS]
    + [root / "UAkron Playground" / "Capillary Flow Porometer" / "Test Data" for root in SYNC_ROOTS]
)
DATA_DIR = next((Path(p) for p in DATA_CANDIDATES if p and Path(p).exists()), None)
if DATA_DIR is None:
    raise SystemExit("No data folder found: set CFP_DATA_DIR, or add your SyncThing folder to SYNC_ROOTS.")
PATTERN  = "CFP-*_T*.CFT"          # which files to load (e.g. "*_T1.CFT", "*.CFT")
if DATA_DIR.name == "Test Data":
    PATTERN = "*.CFT"
    print(f"{DATE} data folder not found; showing the lab test files in {DATA_DIR} instead.")
OUT_DIR  = DATA_DIR / "Report"
SAVE     = False                    # True = write figures and tables to OUT_DIR
UNITS    = "kPa"                    # "kPa" or "psi"
LOG_DIAMETER = True                 # log scale for the diameter axes
HIST_BINS = 25                      # bins for the pore size histogram

# analysis options (defaults reproduce CapRep)
SHAPE_FACTOR = 0.715                # 1.0 = plain 4*gamma/dP (diameters x1.4)
MIN_DP_KPA   = 0.5                  # ignore start-up blips (wet flow above dry flow) below this pressure
print("Data folder:", DATA_DIR)"""))

cells.append(code("""import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from porometry import PSI_TO_KPA, Settings, Workspace

P = PSI_TO_KPA if UNITS == "kPa" else 1.0          # psi -> display units
RATE = re.compile(r"(\\d+)_(\\d+)MM_MIN", re.IGNORECASE)

def rate_of(name):
    m = RATE.search(name)
    return float(f"{m.group(1)}.{m.group(2)}") if m else np.nan

ws = Workspace(settings=Settings(shape_factor=SHAPE_FACTOR, min_dp_kpa=MIN_DP_KPA))
files = sorted(DATA_DIR.glob(PATTERN), key=lambda p: rate_of(p.stem))
ws.add_files(files)
runs = sorted(ws.entries, key=lambda e: (rate_of(e.name), e.name))
print(f"{len(runs)} runs loaded from {DATA_DIR}")
for e in runs:
    print(f"  {e.name:28s} rate {rate_of(e.name):>6g} mm/min   QC: {e.qc.status:5s} {e.qc.summary()}")
for p, err in ws.errors:
    print("  could not read", p.name, ":", err)"""))

cells.append(md("""## Plot style
One color per rate, in this order. Change `COLORS` or `LABEL` to restyle every plot below."""))

cells.append(code("""COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
COLOR = {e.name: COLORS[i % len(COLORS)] for i, e in enumerate(runs)}
LABEL = {e.name: f"{rate_of(e.name):g} mm/min" + ("" if e.name.upper().endswith("T1") else f" ({e.name.split('_')[-1]})")
         for e in runs}

plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 300, "savefig.bbox": "tight",
    "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.6,
    "legend.frameon": False, "lines.linewidth": 1.6, "lines.markersize": 3.5,
})

def plain_log_x(ax):
    \"\"\"Log diameter axis labelled 0.2, 0.5, 1, 2 ... instead of 2x10^-1.\"\"\"
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.xaxis.set_minor_formatter(FuncFormatter(lambda v, _: f"{v:g}" if f"{v:.0e}"[0] in "25" else ""))

def save(fig, name):
    if SAVE:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        for ext in ("png", "svg"):
            fig.savefig(OUT_DIR / f"{name}.{ext}")
        print("saved", OUT_DIR / f"{name}.png")"""))

cells.append(md("""## Comparison table
*Wet/dry at max* shows how far the run got. Below 98%, the run ended before every pore opened, so
the smallest pore isn't fully measured and the small-pore end of the distribution is missing."""))

cells.append(code("""rows = []
for e in runs:
    a = e.analysis
    dry50 = (np.interp(50 / PSI_TO_KPA, a.dry_dp, a.dry_flow) / 1000
             if a.dry_dp.size and a.dry_dp.max() * PSI_TO_KPA >= 50 else np.nan)
    rows.append({
        "Rate (mm/min)": rate_of(e.name),
        "Run": e.name,
        "QC": e.qc.status,
        "Thickness (mm)": e.run.thickness_cm * 10,
        f"Bubble point ({UNITS})": a.bubble_dp * P if a.bubble_dp else np.nan,
        "Largest pore (µm)": a.bubble_d,
        f"Mean flow pressure ({UNITS})": a.mean_flow_dp * P if a.mean_flow_dp else np.nan,
        "Mean flow pore (µm)": a.mean_flow_d,
        "Smallest pore (µm)": a.smallest_d if a.closed else np.nan,
        f"Max pressure ({UNITS})": a.max_dp * P,
        "Wet/dry at max (%)": a.cff_raw[-1] if a.cff_raw.size else np.nan,
        "Dry flow at 50 kPa (L/min)": dry50,
    })
table = pd.DataFrame(rows)
display(table.style.format(precision=3, na_rep="—").hide(axis="index"))
if SAVE:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT_DIR / "comparison.csv", index=False, encoding="utf-8-sig")"""))

cells.append(md("""## 1. Flow vs pressure
Solid line = wet curve, dotted = dry curve. A good run has wet flow near zero until the bubble point,
then rises to meet the dry curve."""))

cells.append(code("""fig, ax = plt.subplots(figsize=(8, 4.8))
for e in runs:
    a, c = e.analysis, COLOR[e.name]
    ax.plot(a.wet_dp * P, a.wet_flow / 1000, "o-", color=c, label=LABEL[e.name])
    ax.plot(a.dry_dp * P, a.dry_flow / 1000, ":", color=c, lw=1.3)
ax.set_xlabel(f"Differential pressure ({UNITS})")
ax.set_ylabel("Air flow (L/min)")
ax.set_xlim(left=0); ax.set_ylim(bottom=0)
ax.set_title("Flow vs pressure (solid = wet, dotted = dry)", loc="left", fontweight="bold")
ax.legend(loc="upper left")
save(fig, "flow_vs_pressure")
plt.show()"""))

cells.append(md("""## 2. Cumulative filter flow vs pore diameter
CFF = wet flow / dry flow x 100, i.e. % of flow passing through pores at least this large.
The open circle marks the mean flow pore (CFF = 50%)."""))

cells.append(code("""fig, ax = plt.subplots(figsize=(8, 4.8))
for e in runs:
    a, c = e.analysis, COLOR[e.name]
    ax.plot(a.diameter, a.cff, "o-", color=c, label=LABEL[e.name])
    if a.mean_flow_d:
        ax.plot(a.mean_flow_d, 50, "o", ms=9, mfc="white", mec=c, mew=2)
ax.axhline(50, color="#52514e", lw=0.8, ls=":")
ax.axhline(100, color="#52514e", lw=0.6)
if LOG_DIAMETER:
    plain_log_x(ax)
ax.set_ylim(0, 110)
ax.set_xlabel("Pore diameter (µm)")
ax.set_ylabel("Cumulative filter flow (%)")
ax.set_title("Cumulative filter flow (open circle = mean flow pore)", loc="left", fontweight="bold")
ax.legend(loc="lower left")
save(fig, "cumulative_filter_flow")
plt.show()"""))

cells.append(md("""## 3. Pore size distribution (histogram)
Share of the total air flow that passes through pores in each diameter bin. This view is smoother
than CapRep's point-by-point distribution, which is in the next cell. Change `HIST_BINS` in the settings cell."""))

cells.append(code("""fig, ax = plt.subplots(figsize=(8, 4.8))
for e in runs:
    a, c = e.analysis, COLOR[e.name]
    edges, flow_pct, density, centres = a.binned_distribution(HIST_BINS, log=LOG_DIAMETER)
    if edges.size:
        ax.step(edges, np.r_[flow_pct, flow_pct[-1]], where="post", color=c, label=LABEL[e.name])
ax.axhline(0, color="#b8b7b1", lw=0.8)
if LOG_DIAMETER:
    plain_log_x(ax)
ax.set_xlabel("Pore diameter (µm)")
ax.set_ylabel("Flow through pores in bin (%)")
ax.set_title(f"Pore size distribution ({HIST_BINS} bins)", loc="left", fontweight="bold")
ax.legend(loc="upper right")
save(fig, "pore_size_distribution_hist")
plt.show()"""))

cells.append(code("""# CapRep-style point-by-point distribution: dCFF / dD at the average diameter of each step
fig, ax = plt.subplots(figsize=(8, 4.8))
for e in runs:
    a, c = e.analysis, COLOR[e.name]
    d, psd, _ = a.distribution("D")          # "D2" = CapRep's 'distribution as f(D^2)' style
    ok = np.isfinite(psd)
    ax.plot(d[ok], psd[ok], "o-", color=c, label=LABEL[e.name])
ax.axhline(0, color="#b8b7b1", lw=0.8)
if LOG_DIAMETER:
    plain_log_x(ax)
ax.set_xlabel("Pore diameter (µm)")
ax.set_ylabel("Pore size distribution (%/µm)")
ax.set_title("Pore size distribution, point by point (CapRep method)", loc="left", fontweight="bold")
ax.legend(loc="upper right")
save(fig, "pore_size_distribution_points")
plt.show()"""))

cells.append(md("""## 4. Pore size vs rate
Filled marker = the run reached wet = dry (CFF reached 98%). Open marker = the run stopped early; its mean flow pore is
still valid, but its small-pore end is missing."""))

cells.append(code("""fig, ax = plt.subplots(figsize=(6.5, 4.2))
x = table["Rate (mm/min)"].to_numpy(float)
complete = np.array([e.analysis.closed for e in runs])
for col, c, lab in (("Largest pore (µm)", "#eb6834", "Largest pore (bubble point)"),
                    ("Mean flow pore (µm)", "#2a78d6", "Mean flow pore")):
    y = table[col].to_numpy(float)
    ax.plot(x, y, "-", color=c, label=lab)
    ax.plot(x[complete], y[complete], "o", color=c, ms=7)
    ax.plot(x[~complete], y[~complete], "o", mfc="white", mec=c, mew=1.8, ms=7)
ax.set_xscale("log")
ax.set_xticks(np.unique(x), [f"{v:g}" for v in np.unique(x)])
ax.minorticks_off()
ax.set_ylim(bottom=0)
ax.set_xlabel("Rate in file name (mm/min)")
ax.set_ylabel("Pore diameter (µm)")
ax.set_title("Pore size vs rate", loc="left", fontweight="bold")
ax.legend(loc="upper left")
save(fig, "pore_size_vs_rate")
plt.show()"""))

cells.append(md("""## 5. One run in detail
Set `RUN` to any run name from the table."""))

cells.append(code("""RUN = runs[0].name
e = next(r for r in runs if r.name == RUN)
a, c = e.analysis, COLOR[e.name]
fig, axs = plt.subplots(1, 3, figsize=(14, 4), layout="constrained")
axs[0].plot(a.wet_dp * P, a.wet_flow / 1000, "o-", color=c, label="wet")
axs[0].plot(a.dry_dp * P, a.dry_flow / 1000, ":", color=c, label="dry")
axs[0].plot(a.dry_dp * P, a.dry_flow / 2000, "-", color="#52514e", lw=0.9, label="half dry")
for dp, lab in ((a.bubble_dp, "bubble point"), (a.mean_flow_dp, "mean flow")):
    if dp:
        axs[0].axvline(dp * P, color="#52514e", lw=0.8, ls=":")
axs[0].set(xlabel=f"Differential pressure ({UNITS})", ylabel="Air flow (L/min)", xlim=(0, None), ylim=(0, None))
axs[0].legend(loc="upper left")
axs[1].plot(a.diameter, a.cff, "o-", color=c)
axs[1].axhline(50, color="#52514e", lw=0.8, ls=":")
axs[1].set(xlabel="Pore diameter (µm)", ylabel="Cumulative filter flow (%)", ylim=(0, 110))
edges, flow_pct, _, _ = a.binned_distribution(HIST_BINS, log=LOG_DIAMETER)
axs[2].bar(edges[:-1], flow_pct, width=np.diff(edges), align="edge", color=c, alpha=0.85, edgecolor="white")
axs[2].set(xlabel="Pore diameter (µm)", ylabel="Flow through pores in bin (%)")
if LOG_DIAMETER:
    plain_log_x(axs[1]); plain_log_x(axs[2])
fig.suptitle(f"{RUN}  —  mean flow pore {a.mean_flow_d:.3g} µm" if a.mean_flow_d else RUN, x=0.01, ha="left", fontweight="bold")
save(fig, f"{RUN}_detail")
plt.show()"""))

cells.append(md("""## 6. Export
Writes `summary.xlsx` to `OUT_DIR`, with Summary, Groups (mean ± SD of duplicates), QC and one sheet per run, plus this comparison table."""))

cells.append(code("""from porometry.export import write_summary
if SAVE:
    xlsx = write_summary(ws, OUT_DIR / "summary.xlsx", UNITS)
    with pd.ExcelWriter(xlsx, engine="openpyxl", mode="a") as xw:
        table.to_excel(xw, sheet_name="Comparison", index=False)
    print("wrote", xlsx)
else:
    print("SAVE is False: nothing written")"""))

nb.cells = cells
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nbf.write(nb, "examples/compare_conditions.ipynb")
print("ok", len(cells), "cells")
