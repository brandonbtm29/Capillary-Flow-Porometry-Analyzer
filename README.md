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

The window has the run list on the left, plots and tables in the middle, and **Plot options** on the right
(close it from its corner; bring it back with *Plot > Plot options panel*). Everything is in the menus
(File, Runs, Plot, Tools, Help); the toolbar keeps the common actions.

1. **Open folder…** (or drag a folder or `.CFT` files onto the window). Subfolders are included.
2. Tick runs to plot them. Click a run to highlight it and read its header, tags and QC findings under
   **Run details**.
3. Tabs: **Flow vs pressure**, **Cumulative filter flow**, **Pore size distribution** and **Compare**.

### Groups, Average by and tags

There are two ideas (also in the app under *Help > How grouping works*):

**Groups pick which runs you're looking at.** They work like playlists: *All runs*, then your own groups
in the list above the runs.

- Select runs (Ctrl/Shift-click) → **New group from selection…**. Add more with **Add to group**,
  right-click > *Add to group*, or by dragging runs onto a group.
- **A run can be in many groups** (e.g. in "Speed series" and in "S1 replicates").
- Click a group: plots, tables, statistics, the Compare tab and exports show only its runs.
- Each group remembers how it's plotted (Average by, Colour by, palette, Show).
- Right-click a group to rename or delete it (deleting never touches the runs or files).

**Average by decides which of those runs are replicates of each other** (Plot options): Condition by
default, or Sample, Folder, a field you added, or **Run (no averaging)** to compare replicates one by one.

| You want to | Group | Average by | Colour by | Show |
|---|---|---|---|---|
| Compare speeds, replicates averaged | "Speed series" | Condition | Condition | Group means ± SD |
| See how the replicates of one sample agree | "S1 replicates" | Run | Replicate | Individual runs |
| Compare samples at one speed | "0.25 mm/min samples" | Sample | Sample | Runs + group means |

**Tags** describe each run: **Condition**, **Sample**, **Replicate** and **Folder**, read from the file name
(`CFP-0_25MM_MIN_S1_TEST2` → Condition *0.25 mm/min*, Sample *S1*, Replicate *2*) and the folder.
Double-click a cell to change one run, or select several and use **Set Condition…** (*Runs > Set field*).
A blank value goes back to the automatic one; values you set show in italics. Add your own fields with
*Runs > Add field…* (e.g. Membrane, Batch).

Tags you change and group membership are saved in **`run_tags.csv` next to the `.CFT` files** (group names
in its *Groups* column), so they travel with the data through SyncThing and open in Excel. Runs that fail QC
are never averaged; runs with warnings are, unless you turn that off in Settings.

### Recent folders

*File > Recent folders*, or the arrow on the **Open folder** button, lists the last 10 folders you opened
on this computer. Each computer keeps its own list, because the paths differ between the Mac and the PC.

### Colours, markers and plot options

- **Colour by** *Run* gives every run its own colour. Colour by a field (e.g. Condition) gives runs with the
  same value one colour and different markers.
- **Palette:** colour-blind safe (default), *Viridis* or *Cividis* for ordered series such as speeds,
  Tableau 10, or greys for print. **Group colours…** sets a colour per value.
- **Style…** (or right-click a run) sets a run's colour, marker, line style, line width and legend label.
- **Show:** individual runs, **group means ± SD** (a shaded band), or both. Means are averaged where every
  run in the group has data.
- **Axis limits** apply to the plot you're looking at (blank = automatic). Also: pressure units,
  log/linear diameter axis, distribution style (point-by-point like CapRep, D²-weighted, or a histogram),
  markers, line width, legend position (including outside the plot) and titles.

### Compare groups and statistics

The **Compare** tab plots one number per *Average by* group (mean flow pore, largest pore, smallest pore, bubble
point or mean flow pressure; pick it under *Compare*): every run as a point and the group mean ± SD. Runs
left out by QC show as grey crosses. The **Statistics** table and the plot title give Welch's t-test for
two groups, or one-way ANOVA with Tukey's pairwise comparisons for three or more. Groups with a single
run are left out of the tests.

### Sessions

**File > Save session** (Ctrl+S) stores the loaded runs, which are shown, styles, colours, grouping and
plot settings in a `.cfpa` file. Reopen it with *Open session*, *Recent sessions*, or by dragging it onto
the window. Save sessions next to your data in SyncThing: paths are stored relative to the session file,
so the same session opens on the Mac and the PC.

### Exporting

- **Export summary…** writes an Excel workbook: Summary (with tags), Groups, Statistics, QC, and one sheet
  per run with the point-by-point table and raw curves.
- **Export figure…** saves any plot (or the three curves stacked) at a journal size: single column
  (8.5 cm), 1.5 columns, double column (17.8 cm), a 16:9 slide, or your own size. It sets the font size and
  resolution (300 to 1200 dpi), shows a preview, and saves PNG, TIFF, SVG or PDF at exactly that size.
  Titles are off by default because journals put them in the caption.
- **Copy figure** (Ctrl+Shift+C) puts the current plot on the clipboard at the last export size, ready to
  paste into Word or PowerPoint.

### Where settings are saved

Settings are saved as files in the app's own folder (the folder you cloned), not in the registry or a
macOS plist:

- `porometry_settings.ini`: analysis and QC settings, plot options, views, colours, export choices.
- `porometry_local.ini`: window size and layout, last folder, recent folders and sessions. This one always
  stays in the app folder, because those paths differ between computers.

To share the first file between the Mac and the PC, open **Settings > Settings Folder > Change...** and pick a
folder in SyncThing, e.g. `UAkron Playground/Capillary Flow Porometer/Settings`. The app copies your
current settings there and asks to restart. On the second computer, choose the same folder: it uses the
settings already there instead of overwriting them. **Use Default** goes back to the app folder. The
`UAKRON_SETTINGS_DIR` environment variable overrides the choice. Both files are ignored by git.

Settings from versions before 0.6 (kept in the registry / plist) are copied over the first time the new
version starts. The old copy is left untouched.

### Other

- **Error log**: errors, with tracebacks (also from background threads), go to `%LOCALAPPDATA%\PorometryAnalyzer\logs\porometry.log` on Windows (`~/Library/Logs/PorometryAnalyzer/porometry.log` on macOS). An unexpected error is shown in a dialog and the app keeps running instead of closing. A hard crash (e.g. in a driver) leaves a `.fatal.log` next to it.
- **Archive…** moves bad or practice runs into an `Archive` folder next to them, with a reason logged in
  `Archive/archive_log.csv`. They stop loading with the folder; **Archived runs…** brings them back.
  **Remove from list** only hides a run for this session.
- **Tools > Create app icon** remakes the Desktop / Start menu icon (Windows) or the app in
  `~/Applications` (macOS). Use it if the icon goes missing or the app folder moves.
- A run that fails QC is still plotted, drawn dashed and labelled `[QC fail]`, so you can see what went
  wrong.

### Updating

The version you have is in the bottom-right corner. The app checks GitHub when it starts; when a newer
version exists, that corner turns into a link (*v0.4.0 → v0.5.0 available*). Click it, the **Update**
button on the toolbar, or *Help > Check for updates*, to see what's new and **Update and restart**. The update pulls the new version into this
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
  tags.py       run tags from file names + run_tags.csv next to the data
  app_paths.py  where the settings files are (app folder or the chosen settings folder)
  settings_location.py  Settings Folder option, same copy as in the other UAkron apps
  groups.py     group mean curves, compare metrics, t-test / ANOVA / Tukey
  session.py    save / open .cfpa sessions
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
