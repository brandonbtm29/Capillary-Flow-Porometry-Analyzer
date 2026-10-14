# Changelog

Versions follow [semantic versioning](https://semver.org): **MAJOR.MINOR.PATCH**.

- **MINOR** (0.3 → 0.4): new features, or behaviour you'd notice.
- **PATCH** (0.3.1 → 0.3.2): bug fixes only.
- **MAJOR**: 1.0.0 once the app is complete and trusted enough for the rest of the lab to use without help.
  After that, MAJOR goes up only for changes that break existing files, settings or workflows.

Each release is tagged `vX.Y.Z` on GitHub. The version shows in the window title and the bottom-right corner
of the app.

## 0.4.0 - 2026-10-14

### Added
- **Tags for every run:** Condition, Sample, Replicate and Folder, read from the file name
  (`CFP-0_25MM_MIN_S1_TEST2` → *0.25 mm/min*, *S1*, *2*) and the folder. Edit them in the run list
  (double-click a cell) or for several runs at once (*Set Condition…*), and add your own fields
  (*Runs > Add field…*). Your changes are saved in `run_tags.csv` next to the data, so they sync between
  computers and open in Excel.
- **Average by / Colour by:** group runs by any field. Runs that share a value can share a colour, with a
  different marker each.
- **Group means ± SD:** plot the average curve of each group with a shaded band, alone or over the
  individual runs.
- **Compare groups tab and Statistics table:** one number per group (mean flow pore, largest or smallest
  pore, bubble point or mean flow pressure) with every run shown, mean ± SD, and Welch's t-test or ANOVA +
  Tukey's pairwise comparisons. The Excel export gets a Statistics sheet.
- **Styling:** per-run colour, marker, line style, line width and legend label (*Style…*); a colour per
  group (*Group colours…*); palettes, including Viridis/Cividis for ordered series like speeds; legend
  position (including outside the plot); axis limits per plot; line width; titles on/off.
- **Sessions:** *File > Save session* keeps the loaded runs, what's shown, styles and plot settings in a
  `.cfpa` file that opens on both the Mac and the PC (paths relative to the session file). There are recent
  sessions, and you can drag a session onto the window.
- **Publication export:** *Export figure…* saves at journal sizes (single column 8.5 cm, 1.5 columns,
  double column 17.8 cm, a slide, or custom), with font size, 300 to 1200 dpi, a preview, and PNG/TIFF/SVG/PDF
  at exactly that size. *Copy figure* (Ctrl+Shift+C) puts the plot on the clipboard.

### Changed
- **Menus and a shorter toolbar.** File, Runs, Plot, Tools and Help menus; units, axes, distribution and
  colours moved to the **Plot options** panel on the right. On a Mac the menus sit at the top of the screen.
- "Mark as duplicates" is now **Set Condition…** (or any field). Duplicate groups you made before carry
  over as the Condition of those runs.
- Group names read better: *0.25 mm/min* instead of *CFP-0_25MM_MIN*.
- The *Group runs by file name / folder* setting is replaced by **Average by** in the Plot options panel.
- Needs scipy (for the statistics). The Update button installs it.

### Fixed
- Running the tests on this computer no longer resets the app's saved settings (window size, last folder,
  plot options).

## 0.3.2 - 2026-10-13

### Fixed
- **Update check on the Mac.** Checking for updates failed with `CERTIFICATE_VERIFY_FAILED`, because Python
  from python.org on macOS doesn't trust any certificates until its *Install Certificates* step is run. The
  app now asks git for the latest version, the same way the update itself downloads it, and uses the web API
  only as a fallback. If both fail, the window says why in plain words.

## 0.3.1 - 2026-10-13

### Added
- **App icon on both computers.** On a Mac, the first launch puts *Capillary Flow Porometry Analyzer.app*,
  with the app icon, in Applications in your home folder, so it shows in Launchpad and Spotlight and can be
  dragged to the Dock. On Windows, the first launch makes the Desktop and Start menu icons, which
  `make_shortcut.ps1` used to do. Pin the Start menu entry to the taskbar and it shares one button with the
  open window.
- *Settings… > Create app icon* remakes the icon, for example after moving the app folder.

## 0.3.0 - 2026-10-13

### Added
- **Update button.** *Update…* in the toolbar (or a click on the version number in the bottom-right
  corner) checks GitHub for a newer version, shows what's new, and with **Update and restart** downloads it
  and reopens the runs you had loaded. The app also checks quietly when it starts and turns the version
  number into a link when an update is available; switch that off in the same window. It never updates
  without asking, and refuses if files in the app folder have local changes.

## 0.2.0 - 2026-10-13

### Added
- **Archive runs.** *Archive…* (toolbar, right-click menu, Ctrl+Shift+A) moves the selected runs' `.CFT`
  files into an `Archive/` folder next to them and logs the date, QC status and your reason in
  `Archive/archive_log.csv`. Archived runs are skipped when a folder is opened, so they drop out of plots,
  tables and group averages. *Archived runs…* lists them and restores the ones you pick. Nothing is deleted.
- Version number in the status bar; this changelog.

### Changed
- Renamed to **Capillary Flow Porometry Analyzer** (repo `Capillary-Flow-Porometry-Analyzer`, package
  `capillary-flow-porometry-analyzer`) to avoid confusion with other porometry techniques. The Python
  import name (`porometry`) and the `porometry` / `porometry-cli` commands are unchanged.
- Launchers renamed to `Capillary Flow Porometry Analyzer.bat` / `.command`; `make_shortcut.ps1`
  replaces the old desktop and Start menu shortcuts.
- "Remove" is now "Remove from list", to make clear it only affects the current session.

## 0.1.0 - 2026-10-12

First public version.

- Reads CapWin `.CFT` files and reproduces CapRep's bubble point, mean flow pore, smallest detected pore,
  cumulative filter flow and pore size distribution (checked against 311 CapRep reports).
- Data-quality checks (leak/bypass, incomplete dry curve, wet above dry, distribution cut off, ...).
- PyQt6 app: run overlays, summary and group (mean ± SD) tables, manual duplicate grouping, Excel/CSV,
  PNG/SVG/PDF and PowerPoint export; kPa/psi.
- Comparison notebook, `porometry-cli`, Windows and macOS launchers.
