"""Save and reopen everything you set up: loaded runs, what's shown, styles, grouping and plot settings.

A session is a small JSON file (``.cfpa``). Run paths are stored both absolute and relative to the session
file, so a session saved next to the data in SyncThing opens on the Mac and the PC alike. Run tags are not
in the session: they live with the data in ``run_tags.csv``.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import __version__
from .analysis import Settings
from .figures import PlotOptions
from .qc import QCSettings
from .workspace import Workspace

SUFFIX = ".cfpa"
FORMAT = 1


class SessionError(ValueError):
    pass


def _rel(path: Path, base: Path) -> str | None:
    try:
        return Path(os.path.relpath(path, base)).as_posix()
    except ValueError:  # another drive on Windows
        return None


def _resolve(item: dict, base: Path) -> Path | None:
    for cand in ((base / item["relpath"]) if item.get("relpath") else None, Path(item.get("path", ""))):
        if cand is not None and str(cand) and cand.exists():
            return cand.resolve()
    return None


def save(path: str | Path, ws: Workspace, plot_options: PlotOptions, *, folders=(), highlight: str | None = None,
         tab: int = 0, group_include_warn: bool = True) -> Path:
    path = Path(path)
    if path.suffix.lower() != SUFFIX:
        path = path.with_suffix(SUFFIX)
    base = path.parent.resolve()
    data = {
        "app": "Capillary Flow Porometry Analyzer",
        "version": __version__,
        "format": FORMAT,
        "runs": [{"path": str(e.path.resolve()), "relpath": _rel(e.path.resolve(), base), "visible": e.visible,
                  "style": e.style} for e in ws.entries],
        "folders": [{"path": str(Path(f).resolve()), "relpath": _rel(Path(f).resolve(), base)} for f in folders],
        "view": {"fields": ws.fields, "average_by": ws.average_by, "color_by": ws.color_by, "palette": ws.palette,
                 "value_colors": ws.value_colors},
        "plot_options": asdict(plot_options),
        "analysis": asdict(ws.settings),
        "qc": asdict(ws.qc_settings),
        "group_include_warn": group_include_warn,
        "highlight": highlight,
        "tab": tab,
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


@dataclass
class Loaded:
    """A session read back: what to load and the settings to apply."""
    path: Path
    runs: list[tuple[Path, bool, dict]] = field(default_factory=list)  # (file, visible, style)
    missing: list[str] = field(default_factory=list)
    folders: list[Path] = field(default_factory=list)
    plot_options: PlotOptions = field(default_factory=PlotOptions)
    settings: Settings = field(default_factory=Settings)
    qc: QCSettings = field(default_factory=QCSettings)
    view: dict = field(default_factory=dict)
    group_include_warn: bool = True
    highlight: str | None = None
    tab: int = 0
    version: str = ""


def _known(cls, d: dict):
    names = set(asdict(cls()))
    return cls(**{k: v for k, v in (d or {}).items() if k in names})


def load(path: str | Path) -> Loaded:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SessionError(f"{path.name} is not a session file ({exc})") from exc
    if not isinstance(data, dict) or "runs" not in data:
        raise SessionError(f"{path.name} is not a session file")
    if data.get("format", 1) > FORMAT:
        raise SessionError(f"{path.name} was saved by a newer version ({data.get('version')}); update the app first")
    base = path.parent.resolve()
    out = Loaded(path, version=data.get("version", ""))
    for item in data.get("runs", []):
        p = _resolve(item, base)
        if p is None:
            out.missing.append(item.get("relpath") or item.get("path", "?"))
        else:
            out.runs.append((p, bool(item.get("visible", True)), dict(item.get("style") or {})))
    out.folders = [p for p in (_resolve(f, base) for f in data.get("folders", [])) if p is not None]
    out.plot_options = _known(PlotOptions, data.get("plot_options"))
    out.settings = _known(Settings, data.get("analysis"))
    out.qc = _known(QCSettings, data.get("qc"))
    out.view = dict(data.get("view") or {})
    out.group_include_warn = bool(data.get("group_include_warn", True))
    out.highlight = data.get("highlight")
    out.tab = int(data.get("tab", 0) or 0)
    return out


def apply(loaded: Loaded, ws: Workspace) -> None:
    """Replace the workspace contents with the session's runs and settings."""
    ws.clear()
    ws.settings, ws.qc_settings = loaded.settings, loaded.qc
    v = loaded.view
    if v.get("fields"):
        ws.fields = list(dict.fromkeys(list(v["fields"])))
    ws.average_by = v.get("average_by", ws.average_by)
    ws.color_by = v.get("color_by", ws.color_by)
    ws.palette = v.get("palette", ws.palette)
    ws.value_colors = {k: dict(d) for k, d in (v.get("value_colors") or {}).items()}
    for p, _vis, style in loaded.runs:
        key = str(p.resolve())
        if style:
            ws.run_styles[key] = dict(style)
        else:
            ws.run_styles.pop(key, None)
    ws.add_files([p for p, _v, _s in loaded.runs])
    vis = {str(p.resolve()): v for p, v, _s in loaded.runs}
    for e in ws.entries:
        e.visible = vis.get(str(e.path.resolve()), True)
    ws.restyle()
