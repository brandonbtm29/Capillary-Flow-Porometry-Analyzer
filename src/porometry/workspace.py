"""A set of loaded runs with their analysis, QC and plot identity. Used by the GUI and CLI."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import Analysis, Settings, analyze
from .archive import archive_file, is_archived, restore_file
from .cft import PSI_TO_KPA, CFTError, Run, read_cft
from .figures import Series, style_for
from .qc import Level, QCReport, QCSettings, check

_SUFFIX = re.compile(r"(?:[_\- ](?:TEST|RUN|T)\d+)$", re.IGNORECASE)
_SPECIMEN = re.compile(r"(?:[_\- ](?:S|SAMPLE)\d+)$", re.IGNORECASE)


def group_key(path: Path, mode: str = "name") -> str:
    """Which sample/condition a run belongs to, for averaging duplicates.

    mode "name":   file name with trailing _TEST#, then _S# removed
                   (CFP-10_00MM_MIN_S1_TEST1 -> CFP-10_00MM_MIN)
    mode "folder": the containing folder's name
    """
    if mode == "folder":
        return path.parent.name
    stem = path.stem
    stem = _SUFFIX.sub("", stem)
    stem = _SPECIMEN.sub("", stem)
    return stem


@dataclass(eq=False)  # identity comparison: entries hold numpy arrays
class Entry:
    run: Run
    analysis: Analysis
    qc: QCReport
    color: str
    marker: str
    group: str
    visible: bool = True

    @property
    def name(self) -> str:
        return self.run.name

    @property
    def path(self) -> Path:
        return self.run.path


@dataclass
class Workspace:
    settings: Settings = field(default_factory=Settings)
    qc_settings: QCSettings = field(default_factory=QCSettings)
    group_mode: str = "name"
    group_overrides: dict[str, str] = field(default_factory=dict)  # resolved path -> group name
    entries: list[Entry] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)
    _loaded: int = 0  # how many runs have ever been loaded: keeps colours stable

    # ---------------------------------------------------------------- loading
    def add_files(self, paths) -> list[Entry]:
        added = []
        known = {e.path.resolve() for e in self.entries}
        for p in paths:
            p = Path(p)
            if p.resolve() in known:
                continue
            try:
                run = read_cft(p)
            except (CFTError, OSError, ValueError) as exc:
                self.errors.append((p, str(exc)))
                continue
            a = analyze(run, self.settings)
            color, marker = style_for(self._loaded)
            self._loaded += 1
            e = Entry(run, a, check(a, self.qc_settings), color, marker, self._group_for(p))
            self.entries.append(e)
            known.add(p.resolve())
            added.append(e)
        return added

    def add_folder(self, folder, recursive: bool = True, include_archived: bool = False) -> list[Entry]:
        """Load every .CFT in `folder` (and subfolders). Files inside an `Archive/` folder are skipped."""
        folder = Path(folder)
        it = folder.rglob("*") if recursive else folder.glob("*")
        files = sorted(p for p in it if p.is_file() and p.suffix.lower() == ".cft"
                       and (include_archived or not is_archived(p.relative_to(folder))))
        return self.add_files(files)

    def remove(self, entry: Entry) -> None:
        """Drop a run from the list (the file is not touched)."""
        self.entries.remove(entry)

    # ---------------------------------------------------------------- archive
    def archive(self, entries: list[Entry], reason: str = "") -> list[Path]:
        """Move the runs' files into `Archive/` next to them and drop them from the list.

        Raises ArchiveError on the first file that can't be moved; runs archived before it stay archived.
        """
        moved = []
        for e in list(entries):
            old = str(e.path.resolve())
            new = archive_file(e.path, reason, e.qc.status)
            if old in self.group_overrides:  # keep a manual duplicate grouping with the file
                self.group_overrides[str(new.resolve())] = self.group_overrides.pop(old)
            self.entries.remove(e)
            moved.append(new)
        return moved

    def restore(self, paths) -> list[Path]:
        """Move archived files back out of `Archive/`. Returns the restored paths (not loaded)."""
        restored = []
        for p in paths:
            old = str(Path(p).resolve())
            new = restore_file(p)
            if old in self.group_overrides:
                self.group_overrides[str(new.resolve())] = self.group_overrides.pop(old)
            restored.append(new)
        return restored

    def clear(self) -> None:
        self.entries.clear()
        self.errors.clear()
        self._loaded = 0

    def reanalyze(self) -> None:
        for e in self.entries:
            e.analysis = analyze(e.run, self.settings)
            e.qc = check(e.analysis, self.qc_settings)
            e.group = self._group_for(e.path)

    # ---------------------------------------------------------------- duplicates
    def _group_for(self, path: Path) -> str:
        return self.group_overrides.get(str(Path(path).resolve()), group_key(Path(path), self.group_mode))

    def set_group(self, entries: list[Entry], name: str) -> None:
        """Mark runs as duplicates of each other (same group), overriding the automatic grouping."""
        for e in entries:
            self.group_overrides[str(e.path.resolve())] = name
            e.group = name

    def separate(self, entries: list[Entry]) -> None:
        """Mark runs as not duplicates: each gets its own group."""
        for e in entries:
            self.set_group([e], e.name)

    def reset_group(self, entries: list[Entry]) -> None:
        """Back to automatic grouping."""
        for e in entries:
            self.group_overrides.pop(str(e.path.resolve()), None)
            e.group = self._group_for(e.path)

    # ---------------------------------------------------------------- views
    def series(self, entries: list[Entry] | None = None, highlight: str | None = None) -> list[Series]:
        entries = [e for e in self.entries if e.visible] if entries is None else entries
        return [Series(e.analysis, e.color, e.marker, e.qc.level, e.name, highlighted=(e.name == highlight))
                for e in entries]

    def summary_frame(self, units: str = "kPa") -> pd.DataFrame:
        f = PSI_TO_KPA if units == "kPa" else 1.0
        rows = []
        for e in self.entries:
            a = e.analysis

            def p(x):
                return None if x is None else round(x * f, 3)

            def d(x):
                return None if x is None else round(x, 4)

            rows.append({
                "Run": e.name,
                "Group": e.group,
                "QC": e.qc.status,
                "QC issues": e.qc.summary(),
                "Date": e.run.date,
                "Fluid": e.run.fluid,
                "Surface tension (dyn/cm)": e.run.surface_tension,
                "Thickness (mm)": round(e.run.thickness_cm * 10, 3),
                f"Bubble point ({units})": p(a.bubble_dp),
                "Largest pore (µm)": d(a.bubble_d),
                f"Mean flow pressure ({units})": p(a.mean_flow_dp),
                "Mean flow pore (µm)": d(a.mean_flow_d),
                f"Smallest pore pressure ({units})": p(a.smallest_dp),
                "Smallest pore (µm)": d(a.smallest_d),
                f"Max pressure ({units})": round(a.max_dp * f, 2),
                "Wet points": e.run.wet.n,
                "Dry points": e.run.dry.n,
                "File": str(e.path),
            })
        return pd.DataFrame(rows)

    def group_frame(self, max_level: Level = Level.WARN) -> pd.DataFrame:
        """Mean ± SD per group, using runs whose QC is no worse than `max_level`."""
        rows = []
        groups: dict[str, list[Entry]] = {}
        for e in self.entries:
            groups.setdefault(e.group, []).append(e)
        for g, es in groups.items():
            use = [e for e in es if e.qc.level <= max_level]
            row = {"Group": g, "Runs": len(es), "Used": len(use),
                   "Excluded (QC)": ", ".join(e.name for e in es if e not in use)}
            for label, attr in (("Largest pore", "bubble_d"), ("Mean flow pore", "mean_flow_d"),
                                ("Smallest pore", "smallest_d")):
                vals = np.array([getattr(e.analysis, attr) for e in use if getattr(e.analysis, attr) is not None])
                row[f"{label} mean (µm)"] = round(float(vals.mean()), 4) if vals.size else None
                row[f"{label} SD (µm)"] = round(float(vals.std(ddof=1)), 4) if vals.size > 1 else None
            rows.append(row)
        return pd.DataFrame(rows)
