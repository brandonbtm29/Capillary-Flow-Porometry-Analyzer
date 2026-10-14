# Changelog

Versions follow [semantic versioning](https://semver.org): **MAJOR.MINOR.PATCH**.

- **MINOR** (0.3 → 0.4): new features, or behaviour you'd notice.
- **PATCH** (0.3.1 → 0.3.2): bug fixes only.
- **MAJOR**: 1.0.0 once the app is complete and trusted enough for the rest of the lab to use without help.
  After that, MAJOR goes up only for changes that break existing files, settings or workflows.

Each release is tagged `vX.Y.Z` on GitHub. The version shows in the window title and the bottom-right corner
of the app.

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
