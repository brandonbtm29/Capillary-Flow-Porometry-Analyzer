"""A set of loaded runs with their analysis, QC, tags and plot style. Used by the GUI and CLI."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import Analysis, Settings, analyze
from .archive import archive_file, is_archived, restore_file
from .cft import PSI_TO_KPA, CFTError, Run, read_cft
from .figures import MARKERS, Series, palette_colors, style_for
from .groups import METRICS, GroupData, compare_stats, format_p, metric_label, metric_value
from .qc import Level, QCReport, QCSettings, check
from .tags import DEFAULT_FIELDS, MemoryTags, SidecarTags, TagStore, auto_tags, sort_key

_SUFFIX = re.compile(r"(?:[_\- ](?:TEST|RUN|T)\d+)$", re.IGNORECASE)
_SPECIMEN = re.compile(r"(?:[_\- ](?:S|SAMPLE)\d+)$", re.IGNORECASE)
RUN = "Run"  # "colour by" choice: every run its own colour
STYLE_KEYS = ("color", "marker", "linestyle", "linewidth", "label")


def default_tag_store() -> TagStore:
    """run_tags.csv next to the data; in memory only when POROMETRY_TAGS=memory (the test suite sets it)."""
    return MemoryTags() if os.environ.get("POROMETRY_TAGS") == "memory" else SidecarTags()


def group_key(path: Path, mode: str = "name") -> str:
    """Raw file-name group (kept for scripts): file name with trailing _TEST#, then _S# removed
    (CFP-10_00MM_MIN_S1_TEST1 -> CFP-10_00MM_MIN), or the folder name for mode "folder"."""
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
    color: str            # colour and marker as drawn (after colour-by, palette and your overrides)
    marker: str
    group: str            # value of the "average by" field
    visible: bool = True
    load_index: int = 0   # order loaded: keeps per-run colours stable
    auto: dict[str, str] = field(default_factory=dict)   # tags from the file name
    tags: dict[str, str] = field(default_factory=dict)   # auto + your edits
    style: dict = field(default_factory=dict)            # your style overrides (color, marker, linestyle, ...)

    @property
    def name(self) -> str:
        return self.run.name

    @property
    def path(self) -> Path:
        return self.run.path

    @property
    def label(self) -> str:
        return self.style.get("label") or self.name


@dataclass
class Workspace:
    settings: Settings = field(default_factory=Settings)
    qc_settings: QCSettings = field(default_factory=QCSettings)
    group_mode: str = "name"  # CLI compatibility: "folder" averages by the Folder field
    fields: list[str] = field(default_factory=lambda: list(DEFAULT_FIELDS))
    average_by: str = "Condition"
    color_by: str = RUN
    palette: str = "default"
    value_colors: dict[str, dict[str, str]] = field(default_factory=dict)  # field -> value -> colour
    run_styles: dict[str, dict] = field(default_factory=dict)              # resolved path -> style overrides
    legacy_groups: dict[str, str] = field(default_factory=dict)  # pre-0.4 "mark as duplicates" (path -> name)
    tag_store: TagStore = field(default_factory=default_tag_store)
    entries: list[Entry] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)
    _loaded: int = 0  # how many runs have ever been loaded: keeps colours stable

    def __post_init__(self):
        if self.group_mode == "folder":
            self.average_by = "Folder"

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
            e = Entry(run, a, check(a, self.qc_settings), color, marker, "", load_index=self._loaded)
            self._loaded += 1
            self._migrate_legacy(e)
            self._retag(e)
            e.style = dict(self.run_styles.get(str(p.resolve()), {}))
            self.entries.append(e)
            known.add(p.resolve())
            added.append(e)
        for f in self.tag_store.fields_seen():
            if f not in self.fields:
                self.fields.append(f)
        self.restyle()
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
        self.restyle()

    # ---------------------------------------------------------------- archive
    def archive(self, entries: list[Entry], reason: str = "") -> list[Path]:
        """Move the runs' files into `Archive/` next to them and drop them from the list.

        Raises ArchiveError on the first file that can't be moved; runs archived before it stay archived.
        """
        moved = []
        for e in list(entries):
            old = str(e.path.resolve())
            new = archive_file(e.path, reason, e.qc.status)
            self._move_keys(old, str(new.resolve()))
            self.entries.remove(e)
            moved.append(new)
        self.restyle()
        return moved

    def restore(self, paths) -> list[Path]:
        """Move archived files back out of `Archive/`. Returns the restored paths (not loaded)."""
        restored = []
        for p in paths:
            old = str(Path(p).resolve())
            new = restore_file(p)
            self._move_keys(old, str(new.resolve()))
            restored.append(new)
        return restored

    def _move_keys(self, old: str, new: str) -> None:
        for d in (self.run_styles, self.legacy_groups):
            if old in d:
                d[new] = d.pop(old)

    def clear(self) -> None:
        self.entries.clear()
        self.errors.clear()
        self._loaded = 0

    def reanalyze(self) -> None:
        for e in self.entries:
            e.analysis = analyze(e.run, self.settings)
            e.qc = check(e.analysis, self.qc_settings)
        self.regroup()

    # ---------------------------------------------------------------- tags
    def _migrate_legacy(self, e: Entry) -> None:
        """A pre-0.4 'Mark as duplicates' group becomes the run's Condition (saved in run_tags.csv)."""
        key = str(e.path.resolve())
        name = self.legacy_groups.pop(key, None)
        if name and "Condition" not in self.tag_store.get(e.path):
            self.tag_store.set(e.path, "Condition", name)

    def _retag(self, e: Entry) -> None:
        e.auto = auto_tags(e.path)
        user = self.tag_store.get(e.path)
        e.tags = {**e.auto, **user}
        e.group = self.group_of(e)

    def group_of(self, e: Entry) -> str:
        return e.tags.get(self.average_by, "") or e.name

    def is_edited(self, e: Entry, fld: str) -> bool:
        return fld in self.tag_store.get(e.path)

    def set_tag(self, entries: list[Entry], fld: str, value: str) -> None:
        """Set a field for these runs (saved next to the data). Blank = back to automatic."""
        value = (value or "").strip()
        if fld not in self.fields:
            self.fields.append(fld)
        for e in entries:
            self.tag_store.set(e.path, fld, value if value and value != e.auto.get(fld, "") else None)
            self._retag(e)
        self.restyle()

    def reset_tags(self, entries: list[Entry], fields: list[str] | None = None) -> None:
        for e in entries:
            for f in fields or list(self.tag_store.get(e.path)):
                self.tag_store.set(e.path, f, None)
            self._retag(e)
        self.restyle()

    def add_field(self, name: str) -> None:
        name = name.strip()
        if name and name not in self.fields and name != RUN:
            self.fields.append(name)

    def values(self, fld: str) -> list[str]:
        """Distinct values of a field over the loaded runs, in natural order."""
        vals = {e.tags.get(fld, "") or (e.name if fld == self.average_by else "") for e in self.entries}
        return sorted(vals, key=sort_key)

    def regroup(self) -> None:
        for e in self.entries:
            self._retag(e)
        self.restyle()

    # pre-0.4 API (kept for scripts and the notebook)
    def set_group(self, entries: list[Entry], name: str) -> None:
        """Put runs in one averaging group: sets the 'average by' field."""
        self.set_tag(entries, self.average_by, name)

    def separate(self, entries: list[Entry]) -> None:
        for e in entries:
            self.set_tag([e], self.average_by, e.name)

    def reset_group(self, entries: list[Entry]) -> None:
        self.reset_tags(entries, [self.average_by])

    # ---------------------------------------------------------------- styles
    def restyle(self) -> None:
        """Work out every run's colour and marker from colour-by, palette and your overrides."""
        if self.color_by == RUN:
            order = sorted(self.entries, key=lambda e: e.load_index)
            if self.palette == "default":
                for e in order:
                    e.color, e.marker = style_for(e.load_index)
            else:
                cols = palette_colors(self.palette, len(order))
                for i, e in enumerate(order):
                    e.color, e.marker = cols[i], MARKERS[(i // 8) % len(MARKERS)]
        else:
            vals = self.values(self.color_by)
            cols = palette_colors(self.palette, len(vals))
            cmap = {v: cols[i] for i, v in enumerate(vals)}
            cmap.update({k: c for k, c in self.value_colors.get(self.color_by, {}).items() if k in cmap})
            seen: dict[str, int] = {}
            for e in sorted(self.entries, key=lambda e: e.load_index):
                v = e.tags.get(self.color_by, "") or (e.name if self.color_by == self.average_by else "")
                e.color = cmap.get(v, "#888888")
                e.marker = MARKERS[seen.get(v, 0) % len(MARKERS)]
                seen[v] = seen.get(v, 0) + 1
        for e in self.entries:
            if e.style.get("color"):
                e.color = e.style["color"]
            if e.style.get("marker"):
                e.marker = e.style["marker"]

    def set_style(self, entries: list[Entry], **style) -> None:
        """Style overrides for these runs. A value of None removes that override."""
        for e in entries:
            for k, v in style.items():
                if k not in STYLE_KEYS:
                    raise KeyError(k)
                if v in (None, ""):
                    e.style.pop(k, None)
                else:
                    e.style[k] = v
            key = str(e.path.resolve())
            if e.style:
                self.run_styles[key] = dict(e.style)
            else:
                self.run_styles.pop(key, None)
        self.restyle()

    def reset_style(self, entries: list[Entry]) -> None:
        self.set_style(entries, **{k: None for k in STYLE_KEYS})

    def set_value_color(self, fld: str, value: str, color: str | None) -> None:
        d = self.value_colors.setdefault(fld, {})
        if color:
            d[value] = color
        else:
            d.pop(value, None)
        self.restyle()

    def group_colors(self) -> dict[str, str]:
        """Colour of each 'average by' group: the colour-by colour when both use the same field."""
        vals = self.values(self.average_by)
        if self.color_by == self.average_by:
            first = {}
            for e in sorted(self.entries, key=lambda e: e.load_index):
                first.setdefault(e.group, e.color)
            return {v: first.get(v, "#888888") for v in vals}
        cols = palette_colors(self.palette, len(vals))
        out = {v: cols[i] for i, v in enumerate(vals)}
        out.update({k: c for k, c in self.value_colors.get(self.average_by, {}).items() if k in out})
        return out

    # ---------------------------------------------------------------- views
    def series(self, entries: list[Entry] | None = None, highlight: str | None = None) -> list[Series]:
        entries = [e for e in self.entries if e.visible] if entries is None else entries
        return [Series(e.analysis, e.color, e.marker, e.qc.level, e.label, highlighted=(e.name == highlight),
                       linestyle=e.style.get("linestyle"), linewidth=e.style.get("linewidth"))
                for e in entries]

    def group_data(self, max_level: Level = Level.WARN, visible_only: bool = True) -> list[GroupData]:
        """Groups of the 'average by' field, in natural order, for mean curves and the compare chart.
        Runs whose QC is worse than `max_level` are kept apart (shown, not averaged)."""
        colors = self.group_colors()
        by: dict[str, list[Entry]] = {}
        for e in self.entries:
            if e.visible or not visible_only:
                by.setdefault(e.group, []).append(e)
        out = []
        for g in sorted(by, key=sort_key):
            use = [e for e in by[g] if e.qc.level <= max_level]
            out.append(GroupData(g, colors.get(g, "#888888"), [e.analysis for e in use], [e.label for e in use],
                                 [e.analysis for e in by[g] if e not in use]))
        return out

    def summary_frame(self, units: str = "kPa") -> pd.DataFrame:
        f = PSI_TO_KPA if units == "kPa" else 1.0
        rows = []
        for e in self.entries:
            a = e.analysis

            def p(x):
                return None if x is None else round(x * f, 3)

            def d(x):
                return None if x is None else round(x, 4)

            row = {"Run": e.name, "Group": e.group}
            row.update({k: e.tags.get(k, "") for k in self.fields if k not in row})
            row.update({
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
            rows.append(row)
        return pd.DataFrame(rows)

    def group_frame(self, max_level: Level = Level.WARN) -> pd.DataFrame:
        """Mean ± SD per group, using runs whose QC is no worse than `max_level`."""
        rows = []
        groups: dict[str, list[Entry]] = {}
        for e in self.entries:
            groups.setdefault(e.group, []).append(e)
        for g in sorted(groups, key=sort_key):
            es = groups[g]
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

    def stats_frame(self, metrics: list[str] | None = None, units: str = "kPa", max_level: Level = Level.WARN,
                    visible_only: bool = False) -> pd.DataFrame:
        """Tests between the 'average by' groups: Welch t-test (2 groups) or ANOVA + Tukey HSD (3+)."""
        groups = self.group_data(max_level, visible_only)
        rows = []
        for m in metrics or list(METRICS):
            vals = {g.name: [metric_value(a, m, units) for a in g.analyses] for g in groups}
            st = compare_stats(vals)
            rows.append({"Metric": metric_label(m, units), "Test": st.test or "none",
                         "p": None if st.p is None else format_p(st.p), "Comparison": "all groups",
                         "Difference": None, "Note": st.note})
            pair_test = "Tukey HSD" if st.test == "One-way ANOVA" else st.test
            for a, b, diff, p in st.pairs:
                rows.append({"Metric": metric_label(m, units), "Test": pair_test, "p": format_p(p),
                             "Comparison": f"{b} vs {a}", "Difference": round(diff, 4), "Note": ""})
        return pd.DataFrame(rows, columns=["Metric", "Test", "p", "Comparison", "Difference", "Note"])


def analyses(entries: list[Entry]) -> list[Analysis]:
    return [e.analysis for e in entries]
