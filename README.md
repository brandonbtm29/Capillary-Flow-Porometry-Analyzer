# Capillary Flow Porometry Analyzer

A desktop app for capillary flow porometry data from the PMI **CFP-1500AEX** (CapWin `.CFT` files).
It reproduces CapRep's results (bubble point, mean flow pore, cumulative filter flow, pore size
distribution) and adds:

- **Overlays:** any number of runs on one plot, each with a fixed colour.
- **Batch summary:** one row per run, plus mean ± SD per sample. Export to Excel or CSV.
- **Data quality checks:** flags leaks and bypass, missing or short dry curves, wet flow above dry flow,
  runs with no mean flow pore, distributions cut off before the smallest pores, and more.
- **Publication figures:** PNG (300 dpi), SVG or PDF.
- **Duplicates:** runs are grouped automatically by file name, or you mark them by hand.

Pressures are in **kPa** by default; switch to psi from the toolbar. Diameters are in µm.

## Install

The app and notebook run on **Windows and macOS** (Linux too). Each computer gets its own Python
environment: `.venv` inside the repo on Windows, `~/.venvs/porometry-analyzer` on macOS (outside the repo,
so a synced copy never carries it).

### macOS

Double-click **`Capillary Flow Porometry Analyzer.command`** for the app, or **`Open Notebook.command`** for the
comparison notebook. The first launch sets everything up in `~/.venvs/porometry-analyzer`. If the files
won't run (a copy synced from Windows loses the "executable" flag), run `chmod +x *.command` once in
Terminal in this folder. If macOS blocks them, right-click and choose Open. You need Python 3.10+ (`brew install python`, or python.org).

The first launch also puts **Capillary Flow Porometry Analyzer.app**, with the app icon, in the
Applications folder in your home folder (`~/Applications`), so it shows in Launchpad and Spotlight. Drag
it to the Dock to keep it there. After that you don't need the `.command` file.

### Windows

You need Python 3.10 or newer ([python.org](https://www.python.org/downloads/); tick
"Add python.exe to PATH" during install).

**Easiest:** double-click `Capillary Flow Porometry Analyzer.bat`. The first launch creates a private Python
environment in `.venv` and installs the dependencies (about a minute). Later launches open straight away.

The first launch also puts a **Capillary Flow Porometry Analyzer** icon on the Desktop and in the Start
menu. To keep it on the taskbar, right-click the Start menu entry and choose *Pin to taskbar*. The pinned
icon and the open window share one taskbar button.

**By hand**, in PowerShell in this folder:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
porometry            # the app
porometry-cli C:\CFP-1500AEX\StudentData\BrandonM --excel summary.xlsx   # no GUI
pytest               # tests
```

## Using the app

1. **Open folder…** (or drag a folder or `.CFT` files onto the window). Subfolders are included.
2. Tick runs in the left panel to plot them. Click a run to highlight it and read its header and QC
   findings under **Run details**.
3. Switch between **Flow vs pressure**, **Cumulative filter flow** and **Pore size distribution** tabs.
   The toolbar sets units, log/linear diameter axis, and distribution style: point-by-point like CapRep,
   D²-weighted, or a histogram with N bins.
4. **Duplicates:** select runs (Ctrl/Shift-click), then click **Mark selected as duplicates…** or
   right-click for *Not duplicates* / *Reset to automatic grouping*. The **Groups (mean ± SD)** table
   averages each group. Runs that fail QC are never averaged; runs with warnings are averaged by default,
   which you can turn off in Settings. Your choices are remembered between sessions.
5. **Export summary…** writes an Excel workbook with these sheets:
   - Summary
   - Groups
   - QC
   - one sheet per run, with the point-by-point table and raw curves

   **Export figure** saves the current plot, or all three plots stacked in one figure.

6. **Settings… > Create app icon** remakes the Desktop / Start menu icon (Windows) or the app in
   `~/Applications` (macOS). Use it if the icon goes missing or the app folder moves.
7. **Archive…** moves bad or practice runs into an `Archive` folder next to them, with a reason logged in
   `Archive/archive_log.csv`. They stop loading with the folder; **Archived runs…** brings them back.
   **Remove from list** only hides a run for this session.

A run that fails QC is still plotted, drawn dashed and labelled `[QC fail]`, so you can see what went
wrong.

### Updating

The version you have is in the bottom-right corner. The app checks GitHub when it starts; when a newer
version exists, that corner turns into a link (*v0.3.0 → v0.4.0 available*). Click it, or **Update…** in
the toolbar, to see what's new and **Update and restart**. The update pulls the new version into this
folder (`git pull`), reinstalls dependencies if they changed, and reopens the runs you had loaded. Your data
and settings are not touched. It needs git, and it won't run if files in the app folder have local changes.
Turn off the start-up check in the same window. What changed in each version is in `CHANGELOG.md`.

## Comparing runs in a notebook

`examples/compare_conditions.ipynb` loads a folder of runs, shows the comparison table and plots each
figure with plain matplotlib, so you can change colors, limits and labels cell by cell.

The copy in this repo is a template with no results in it. You work in your own copy, which lives
with the data in SyncThing: `~/SyncThing/UAkron Playground/Capillary Flow Porometer/Notebooks/`.
`Open Notebook.bat` (Windows) or `Open Notebook.command` (macOS) makes that copy the first time and
opens it in JupyterLab. In VS Code, open the same file and pick the app's Python environment as the
kernel (`.venv` in this folder on Windows, `~/.venvs/porometry-analyzer` on macOS); plots show up
under each cell. The settings cell looks for `Data/<date>` next to it (set `DATE`, or add your
SyncThing location to `SYNC_ROOTS`) and falls back to `Test Data`. With `SAVE = True` it writes
figures and tables to that data folder's `Report/`, and with `SLIDES = True` (the default) the last
cell writes a PowerPoint there: title slide, the comparison table, then one slide per figure.
`TEXT_SIZE` and `LABEL_SIZE` in the settings cell set the tick-label and axis-title sizes.

`examples/compare_conditions.py` makes the same report, PowerPoint included, from the command line.

## How the numbers are calculated

From CapRep's *Calculations* appendix (manual section 5.1). Where the manual is silent, the rule was
worked out from CapRep's own reports (see *Checked against CapRep* below).

| Quantity | How |
|---|---|
| Differential pressure | ΔP = P − P_atm, with P_atm = the first wet point (psi) |
| Diameter | D (µm) = 0.415 · γ / ΔP (γ in dyn/cm, ΔP in psi) |
| Dry flow at each wet point | straight lines between dry points; past the last one, the least-squares line through the last 3 |
| Cumulative filter flow | CFF = Q_wet / Q_dry × 100, never allowed to decrease and capped at 100 % (the data checks use the raw ratio) |
| Bubble point (largest pore) | first wet point with flow > 0 |
| Mean flow pore | ΔP where the wet curve crosses half the dry curve, both drawn as straight lines between measured points |
| Smallest detected pore | first measured point where CFF reaches 98 % (the CFF peak if it never does) |
| Pore size distribution | (CFF_i − CFF_(i−1)) / (D_(i−1) − D_i), at the average diameter of the step |

Some older CapRep exports divide the distribution by (D_(i−1) − D_i)² instead; that style is in the
*Distribution* menu.

**Start-up blips.** CapWin sometimes logs a wet point with flow at almost zero pressure (for example
15 cc/min at 0.008 kPa). A wet point below 0.5 kPa whose flow is higher than the dry flow there is
ignored. CapRep has no such rule and takes the blip as the bubble point; set *Ignore start-up blips
below* to 0 in Settings to do the same.

0.415 = 4 × 0.715 / 6.894757. The 0.715 is the shape ("tortuosity") factor CapWin writes into every
file. Settings lets you use 1.0 (plain 4γ/ΔP) instead, which makes every diameter 1.4× larger. Say which
convention you used when comparing with the literature.

### Checked against CapRep

`tools/caprep_check.py` finds CapRep's own Excel reports (`.xls`) next to the `.CFT` files they came
from, analyzes each file and compares the numbers. On 311 reports from the lab's instrument
(2015 to 2026, Wet Up/Dry Up, Wet Up/Dry Down, Dry Up/Wet Up and Wet Up/Calc. Dry runs):

| Result | Agreement with CapRep |
|---|---|
| Bubble point | 309 of 311 to the printed digits; the other 2 are start-up blips (see above) |
| Mean flow pore | 99 % of 295 reports within 0.1 % |
| Smallest detected pore | 98 % of 174 reports within 0.1 % |
| CFF at every table point | 89 % of reports exact to 0.01, 97 % within 0.5 percentage points |

Known difference: in 13 reports the wet flow is already more than half the dry flow at the first
point, usually a leak or a very open sample. CapRep still prints a mean flow pore for these. The app
leaves it blank and the data checks report *No mean flow pore*.

Bubble points of the lab's test runs also match CapWin's own `log.txt` exactly.

## Data quality checks

| Check | Fails / warns when |
|---|---|
| Dry curve missing or incomplete | fewer than 5 dry points. CapRep says "The data file cannot be processed" |
| Pressure below ambient | any point below −0.5 kPa differential |
| Flow at near-zero pressure (leak or bypass) | wet flow > 20 % of dry flow at the first point or in the first 5 % of the range |
| No mean flow pore | CFF never crosses 50 % |
| Wet flow above dry flow (warn) | CFF > 105 % for 3+ points in a row. Sample stretching or tearing? |
| Wet curve never meets dry curve (warn) | CFF < 95 % at maximum pressure. Raise the maximum pressure |
| Few points between bubble point and mean flow pore (warn) | fewer than 5 |

All thresholds are in **Settings**.

## Project layout

```
src/porometry/
  cft.py        .CFT reader
  analysis.py   CapRep calculations
  qc.py         data quality checks
  workspace.py  loaded runs, grouping, summary tables
  archive.py    move runs to Archive/ and back
  updater.py    check GitHub for a newer version, update the git clone
  shortcuts.py  app icon: Windows shortcuts, macOS .app bundle, Linux .desktop entry
  export.py     Excel / CSV / figure export
  figures.py    matplotlib plots (shared by app and exports)
  slides.py     PowerPoint export (write_deck)
  cli.py        porometry-cli
  gui/          PyQt6 app
tests/          pytest. test_synthetic.py runs anywhere; the rest use lab files from SyncThing (tests/_data.py)
tools/          caprep_check.py: compare with CapRep's own Excel reports
examples/       using the library from a script or Jupyter
```

## Where the data lives

This repo holds code only. Measurement data stays in SyncThing, like the other UAkron lab apps:
`~/SyncThing/UAkron Playground/Capillary Flow Porometer/` (set `UAKRON_DATA_DIR` to use another root).

| Folder | Contents |
|---|---|
| `Data/<date>/` | runs, plus any `Report/` the notebook writes |
| `Test Data/` | the `.CFT` files the tests use |
| `Validation/` | `tools/caprep_check.py` results |

Tests that need the lab files are skipped when that folder isn't on the computer.

## Using it from Python

```python
from porometry import read_cft, analyze, check, PSI_TO_KPA

a = analyze(read_cft(r"C:\CFP-1500AEX\StudentData\BrandonM\CFP-0_25MM_MIN_TEST1.CFT"))
print(a.bubble_d, a.mean_flow_d, a.smallest_d)        # µm
print(check(a).status, check(a).summary())
diam, psd, step_flow = a.distribution()                # CapRep point-by-point PSD
edges, flow_pct, density, centres = a.binned_distribution(20)
```

## Not yet supported

- Gas or liquid permeability reports (Darcy, Frazier, Gurley).
- Integrity, pressure-hold and other test types.
- CapRep's mean flow pore for runs whose wet flow starts above half the dry flow (see above).

## License

MIT. See [LICENSE](LICENSE).
