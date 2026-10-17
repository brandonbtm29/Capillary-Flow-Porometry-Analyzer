"""Matplotlib figures shared by the GUI and the exporters."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import matplotlib
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from . import groups as G
from .analysis import Analysis
from .cft import PSI_TO_KPA
from .qc import Level

# Categorical order (colour-blind checked as an ordered set). Never cycled past 8:
# runs 9+ reuse the hues with a different marker so identity never rests on colour alone.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]
STATUS_COLORS = {"pass": "#0ca30c", "info": "#2a78d6", "warn": "#fab219", "fail": "#d03b3b"}
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3df"

STYLE = {
    "font.size": 12,
    "axes.titlesize": 14,
    "axes.titleweight": "bold",
    "axes.labelsize": 14,
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
    "axes.edgecolor": "#b8b7b1",
    "axes.labelcolor": INK,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "xtick.color": INK2,
    "ytick.color": INK2,
    "text.color": INK,
    "legend.frameon": False,
    "legend.fontsize": 11,
    "lines.linewidth": 1.6,
    "lines.markersize": 4,
    "figure.dpi": 100,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
}


PALETTES = {  # key -> name shown in the app
    "default": "Colour-blind safe (default)",
    "viridis": "Viridis (ordered, e.g. speeds)",
    "cividis": "Cividis (ordered, colour-blind safe)",
    "tab10": "Tableau 10",
    "greys": "Greys (print)",
}
LINESTYLES = {"-": "Solid", "--": "Dashed", ":": "Dotted", "-.": "Dash-dot"}
MARKER_NAMES = {"o": "Circle", "s": "Square", "^": "Triangle", "D": "Diamond", "v": "Triangle down", "P": "Plus",
                "X": "Cross", "*": "Star", "none": "No marker"}
LEGEND_POSITIONS = {"best": "Best", "upper right": "Upper right", "upper left": "Upper left",
                    "lower right": "Lower right", "outside": "Outside, right", "none": "No legend"}


def palette_colors(name: str, n: int) -> list[str]:
    """n colours from a palette. Ordered palettes spread evenly; categorical ones repeat after their length."""
    n = max(n, 1)
    if name in ("viridis", "cividis", "greys"):
        cmap = matplotlib.colormaps["Greys" if name == "greys" else name]
        lo, hi = (0.35, 0.95) if name == "greys" else (0.0, 0.80)  # skip the palest end
        pos = [0.5 * (lo + hi)] if n == 1 else list(np.linspace(lo, hi, n))
        if name == "greys":
            pos = pos[::-1]
        return [matplotlib.colors.to_hex(cmap(x)) for x in pos]
    base = list(matplotlib.colormaps["tab10"].colors) if name == "tab10" else PALETTE
    base = [matplotlib.colors.to_hex(c) for c in base]
    return [base[i % len(base)] for i in range(n)]


@dataclass
class PlotOptions:
    units: str = "kPa"  # or "psi"
    log_diameter: bool = True
    psd_mode: str = "points"  # "points" (CapRep) or "binned"
    psd_bins: int = 20
    psd_weighting: str = "D"  # "D", "D2" or "dD2" (see Analysis.distribution)
    show_markers: bool = True
    show_half_dry: bool = True  # only drawn when one run is shown
    title: bool = True
    line_width: float = 1.6
    legend: str = "best"  # see LEGEND_POSITIONS
    display: str = "runs"  # "runs", "means" (group mean ± SD) or "both"
    sd_band: bool = True
    compare_metric: str = "mean_flow_d"  # see groups.METRICS
    limits: dict = field(default_factory=dict)  # plot kind -> [xmin, xmax, ymin, ymax]; None = automatic


@dataclass
class Series:
    """A run to draw, with its identity colour/marker and QC level."""

    analysis: Analysis
    color: str
    marker: str = "o"
    level: Level = Level.PASS
    label: str = ""
    highlighted: bool = False
    extra: dict = field(default_factory=dict)
    linestyle: str | None = None  # None: solid, dashed if the run fails QC
    linewidth: float | None = None  # None: PlotOptions.line_width

    @property
    def name(self) -> str:
        return self.label or self.analysis.run.name


def style_for(index: int) -> tuple[str, str]:
    """Stable colour + marker for the n-th run loaded."""
    return PALETTE[index % len(PALETTE)], MARKERS[(index // len(PALETTE)) % len(MARKERS)]


def style_rc(font_pt: float | None = None) -> dict:
    """STYLE, with every text size set from one font size (for export at journal sizes)."""
    rc = dict(STYLE)
    if font_pt:
        f = float(font_pt)
        rc.update({"font.size": f, "axes.titlesize": f, "axes.labelsize": f, "xtick.labelsize": f - 1,
                   "ytick.labelsize": f - 1, "legend.fontsize": f - 1, "lines.markersize": max(2.5, f / 3)})
    return rc


def _p(dp_psi, units: str):
    return np.asarray(dp_psi) * (PSI_TO_KPA if units == "kPa" else 1.0)


def _ls(s: Series) -> str:
    if s.linestyle:
        return s.linestyle
    return "--" if s.level >= Level.FAIL else "-"


def _lw(s: Series, any_highlight: bool, o: PlotOptions) -> float:
    base = s.linewidth or o.line_width
    if s.highlighted:
        return base + 1.0
    return base * 0.65 if any_highlight else base


def _alpha(s: Series, any_highlight: bool) -> float:
    if any_highlight and not s.highlighted:
        return 0.35
    return 1.0


def _marker(s: Series, o: PlotOptions):
    return None if (not o.show_markers or s.marker == "none") else s.marker


def _log_diameter_axis(ax: Axes) -> None:
    """Log x axis with plain numbers (0.2, 0.5, 1, 2) instead of 2x10^-1."""
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.xaxis.set_minor_formatter(FuncFormatter(lambda v, _: f"{v:g}" if f"{v:.0e}"[0] in "25" else ""))


def _label(s: Series) -> str:
    return s.name + ("  [QC fail]" if s.level >= Level.FAIL else "")


def _legend(ax: Axes, o: PlotOptions, default: str = "best") -> None:
    handles, _labels = ax.get_legend_handles_labels()
    if not handles or o.legend == "none":
        return
    n = len(handles)
    if o.legend == "outside":
        ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0, ncols=1 if n < 16 else 2)
    else:
        ax.legend(loc=default if o.legend == "best" else o.legend, ncols=1 if n < 8 else 2)


def _limits(ax: Axes, kind: str, o: PlotOptions) -> None:
    lim = o.limits.get(kind) if o.limits else None
    if not lim:
        return
    x0, x1, y0, y1 = (list(lim) + [None] * 4)[:4]
    if ax.get_xscale() == "log":
        x0 = x0 if (x0 is None or x0 > 0) else None
        x1 = x1 if (x1 is None or x1 > 0) else None
    if x0 is not None or x1 is not None:
        ax.set_xlim(left=x0, right=x1)
    if y0 is not None or y1 is not None:
        ax.set_ylim(bottom=y0, top=y1)


def _runs(series: list[Series], o: PlotOptions, groups) -> tuple[list[Series], bool]:
    """Which runs to draw, and whether they are the faded background behind group means."""
    if groups and o.display == "means":
        return [], False
    return series, bool(groups) and o.display == "both"


def _band(ax, x, m: G.MeanCurve, color, o: PlotOptions, scale: float = 1.0):
    if o.sd_band and m.n > 1:
        ok = np.isfinite(m.sd)
        ax.fill_between(np.asarray(x)[ok], (m.mean - m.sd)[ok] * scale, (m.mean + m.sd)[ok] * scale,
                        color=color, alpha=0.18, lw=0)


def _group_label(g: G.GroupData) -> str:
    return f"{g.name} (n={g.n})"


def draw_flow(ax: Axes, series: list[Series], o: PlotOptions, groups: list[G.GroupData] | None = None) -> None:
    runs, faded = _runs(series, o, groups)
    hl = any(s.highlighted for s in runs)
    single = len(runs) == 1 and not groups
    for s in runs:
        a = s.analysis
        al, lw = (0.3, 1.0) if faded else (_alpha(s, hl), _lw(s, hl, o))
        if a.wet_dp.size:
            ax.plot(_p(a.wet_dp, o.units), a.wet_flow / 1000, _ls(s), color=s.color, lw=lw, alpha=al,
                    marker=None if faded else _marker(s, o), markevery=max(1, a.wet_dp.size // 25),
                    label=None if faded else (f"{_label(s)} wet" if single else _label(s)))
        if a.dry_dp.size:
            ax.plot(_p(a.dry_dp, o.units), a.dry_flow / 1000, ":", color=s.color, lw=max(1.0, lw - 0.4), alpha=al,
                    label=f"{s.name} dry" if single else None)
        if single and o.show_half_dry and a.dry_dp.size:
            ax.plot(_p(a.dry_dp, o.units), a.dry_flow / 2000, "-", color=INK2, lw=0.9, alpha=0.8, label="half dry")
        for dp, txt in ((a.bubble_dp, "bubble point"), (a.mean_flow_dp, "mean flow pore")):
            if dp is None or not single:
                continue
            x = float(_p(dp, o.units))
            ax.axvline(x, color=INK2, lw=0.8, ls=(0, (2, 3)))
            d = a.to_d(dp)
            ax.annotate(f"{txt}\n{x:.1f} {o.units} · {d:.3g} µm", (x, 1), xycoords=("data", "axes fraction"),
                        xytext=(4, -4), textcoords="offset points", va="top", fontsize=8, color=INK2)
    for g in (groups or []) if o.display in ("means", "both") else []:
        wet, dry = G.flow_mean(g.analyses)
        if wet is not None:
            x = _p(wet.x, o.units)
            _band(ax, x, wet, g.color, o, 1 / 1000)
            ax.plot(x, wet.mean / 1000, "-", color=g.color, lw=o.line_width + 0.8, label=_group_label(g))
        if dry is not None:
            ax.plot(_p(dry.x, o.units), dry.mean / 1000, ":", color=g.color, lw=o.line_width)
    ax.set_xlabel(f"Differential pressure ({o.units})")
    ax.set_ylabel("Air flow (L/min)")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    if o.title:
        if single:
            sub = ""
        elif groups and o.display != "runs":
            sub = "  (means ± SD; wet solid, dry dotted)"
        else:
            sub = "  (solid = wet, dotted = dry)"
        ax.set_title("Flow vs pressure" + sub, loc="left", wrap=True)
    _limits(ax, "flow", o)
    _legend(ax, o, "lower right" if single else "best")


def draw_cff(ax: Axes, series: list[Series], o: PlotOptions, groups: list[G.GroupData] | None = None) -> None:
    runs, faded = _runs(series, o, groups)
    hl = any(s.highlighted for s in runs)
    for s in runs:
        a = s.analysis
        if not a.dp.size:
            continue
        al, lw = (0.3, 1.0) if faded else (_alpha(s, hl), _lw(s, hl, o))
        ax.plot(a.diameter, a.cff, _ls(s), color=s.color, lw=lw, alpha=al,
                marker=None if faded else _marker(s, o), markevery=max(1, a.dp.size // 25),
                label=None if faded else _label(s))
        if a.mean_flow_d is not None and not faded:
            ax.plot([a.mean_flow_d], [50], marker="o", ms=8, mfc="white", mec=s.color, mew=2, alpha=al, ls="none")
    for g in (groups or []) if o.display in ("means", "both") else []:
        m = G.cff_mean(g.analyses)
        if m is None:
            continue
        _band(ax, m.x, m, g.color, o)
        ax.plot(m.x, m.mean, "-", color=g.color, lw=o.line_width + 0.8, label=_group_label(g))
    ax.axhline(50, color=INK2, lw=0.8, ls=(0, (2, 3)))
    ax.axhline(100, color=INK2, lw=0.6)
    if o.log_diameter:
        _log_diameter_axis(ax)
    ax.set_xlabel("Pore diameter (µm)")
    ax.set_ylabel("Cumulative filter flow (%)")
    ax.set_ylim(0, 110)
    if o.title:
        means = groups and o.display != "runs"
        ax.set_title("Cumulative filter flow" + ("  (group means ± SD)" if means else "  (open circle = mean flow pore)"),
                     loc="left", wrap=True)
    _limits(ax, "cff", o)
    _legend(ax, o)


def draw_psd(ax: Axes, series: list[Series], o: PlotOptions, groups: list[G.GroupData] | None = None) -> None:
    runs, faded = _runs(series, o, groups)
    hl = any(s.highlighted for s in runs)
    ylab = "Pore size distribution (%/µm²)" if o.psd_weighting in ("D2", "dD2") else "Pore size distribution (%/µm)"
    binned = o.psd_mode == "binned"
    for s in runs:
        a = s.analysis
        if a.dp.size < 2:
            continue
        al, lw = (0.3, 1.0) if faded else (_alpha(s, hl), _lw(s, hl, o))
        lab = None if faded else _label(s)
        if binned:
            edges, flow_pct, _dens, centres = a.binned_distribution(o.psd_bins, log=o.log_diameter)
            if len(runs) == 1 and not groups:
                ax.bar(edges[:-1], flow_pct, width=np.diff(edges), align="edge", color=s.color, alpha=0.85 * al,
                       edgecolor="white", linewidth=1, label=lab)
            else:
                ax.step(edges, np.r_[flow_pct, flow_pct[-1]], where="post", color=s.color, lw=lw, alpha=al,
                        ls=_ls(s), label=lab)
        else:
            d, psd, _ = a.distribution(o.psd_weighting)
            ok = np.isfinite(psd)
            ax.plot(d[ok], psd[ok], _ls(s), color=s.color, lw=lw, alpha=al,
                    marker=None if faded else _marker(s, o), markevery=max(1, ok.sum() // 25), label=lab)
    for g in (groups or []) if o.display in ("means", "both") else []:
        m = G.psd_mean(g.analyses, o.psd_weighting, binned, o.psd_bins, o.log_diameter)
        if m is None:
            continue
        if binned:
            edges = m.x
            centres = np.sqrt(edges[:-1] * edges[1:]) if o.log_diameter else (edges[:-1] + edges[1:]) / 2
            ax.step(edges, np.r_[m.mean, m.mean[-1]], where="post", color=g.color, lw=o.line_width + 0.8,
                    label=_group_label(g))
            if o.sd_band and m.n > 1:
                ax.errorbar(centres, m.mean, yerr=m.sd, fmt="none", ecolor=g.color, elinewidth=1, capsize=2)
        else:
            _band(ax, m.x, m, g.color, o)
            ax.plot(m.x, m.mean, "-", color=g.color, lw=o.line_width + 0.8, label=_group_label(g))
    if o.log_diameter:
        _log_diameter_axis(ax)
    ax.axhline(0, color="#b8b7b1", lw=0.8)
    ax.set_xlabel("Pore diameter (µm)")
    ax.set_ylabel("Flow through pores in bin (%)" if binned else ylab)
    if o.title:
        means = groups and o.display != "runs"
        ax.set_title("Pore size distribution" + (f"  ({o.psd_bins} bins)" if binned else "")
                     + ("  (group means ± SD)" if means else ""), loc="left", wrap=True)
    _limits(ax, "psd", o)
    _legend(ax, o)


def draw_compare(ax: Axes, series: list[Series], o: PlotOptions, groups: list[G.GroupData] | None = None) -> None:
    """One metric per group: every run as a point, the group mean as a bar with ± SD."""
    groups = groups or []
    metric = o.compare_metric if o.compare_metric in G.METRICS else "mean_flow_d"
    values: dict[str, list[float]] = {}
    shown_excluded = False
    for i, g in enumerate(groups):
        vals = [G.metric_value(a, metric, o.units) for a in g.analyses]
        vals = [v for v in vals if v is not None]
        values[g.name] = vals
        if vals:
            jit = np.linspace(-0.12, 0.12, len(vals)) if len(vals) > 1 else np.zeros(1)
            ax.plot(i + jit, vals, "o", ls="none", ms=6, mfc="white", mec=g.color, mew=1.6, zorder=3)
            m = float(np.mean(vals))
            ax.plot([i - 0.28, i + 0.28], [m, m], "-", color=g.color, lw=3, solid_capstyle="butt", zorder=4)
            if len(vals) > 1:
                ax.errorbar([i], [m], yerr=[np.std(vals, ddof=1)], fmt="none", ecolor=INK, elinewidth=1.2,
                            capsize=7, zorder=5)
        ex = [G.metric_value(a, metric, o.units) for a in g.excluded]
        ex = [v for v in ex if v is not None]
        if ex:
            ax.plot(np.full(len(ex), i + 0.2), ex, "x", ls="none", color="#9a9893", ms=6, zorder=2,
                    label=None if shown_excluded else "left out (QC)")
            shown_excluded = True
    ax.set_xticks(range(len(groups)))
    show_n = any(len(v) != 1 for v in values.values())
    names = [f"{g.name}\nn={len(values.get(g.name, []))}" if show_n else g.name for g in groups]
    tilt = len(groups) > 5 or max((len(g.name) for g in groups), default=0) * len(groups) > 60
    ax.set_xticklabels(names, rotation=30 if tilt else 0, ha="right" if tilt else "center",
                       rotation_mode="anchor" if tilt else "default")
    ax.set_xlim(-0.6, max(len(groups) - 0.4, 0.6))
    ax.set_ylabel(G.metric_label(metric, o.units))
    every = [v for vs in values.values() for v in vs]
    every += [G.metric_value(a, metric, o.units) or 0 for g in groups for a in g.excluded]
    ax.set_ylim(0, max(every) * 1.12 if every and max(every) > 0 else None)
    ax.grid(axis="x", visible=False)
    stats = G.compare_stats(values) if len(groups) > 1 else None
    if o.title:
        label = G.METRICS[metric][0]
        sub = f"  ({stats.summary()})" if stats and stats.p is not None else ""
        by = (groups[0].field or "group").lower() if groups else "group"
        ax.set_title(f"{label} by {by}{sub}", loc="left", wrap=True)
    if not groups:
        ax.text(0.5, 0.5, "No groups to compare.", ha="center", va="center", color=INK2, transform=ax.transAxes)
    _limits(ax, "compare", o)
    if shown_excluded:
        _legend(ax, o)


DRAWERS = {"flow": draw_flow, "cff": draw_cff, "psd": draw_psd, "compare": draw_compare}
KIND_TITLES = {"flow": "Flow vs pressure", "cff": "Cumulative filter flow", "psd": "Pore size distribution",
               "compare": "Compare", "all": "All three curves (stacked)"}


def make_figure(kind: str, series: list[Series], options: PlotOptions | None = None,
                size: tuple[float, float] = (6.5, 4.2), groups: list[G.GroupData] | None = None,
                font_pt: float | None = None) -> Figure:
    """A standalone figure (for export). kind: 'flow', 'cff', 'psd', 'compare' or 'all' (three panels).

    `size` is in inches (per panel for 'all'); `font_pt` sets every text size (None: the app's sizes).
    """
    o = options or PlotOptions()
    with matplotlib.rc_context(style_rc(font_pt)):
        if kind == "all":
            fig = Figure(figsize=(size[0], size[1] * 3), layout="constrained")
            axes = fig.subplots(3, 1)
            for ax, k in zip(axes, ("flow", "cff", "psd")):
                DRAWERS[k](ax, series, o, groups)
        else:
            fig = Figure(figsize=size, layout="constrained")
            DRAWERS[kind](fig.add_subplot(), series, o, groups)
    return fig


def save_exact(fig: Figure, target, **kw) -> None:
    """Save at exactly the figure's size (no "tight" cropping or growing): what journals check."""
    with matplotlib.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(target, **kw)


def apply_style() -> None:
    matplotlib.rcParams.update(STYLE)


def series_from(analyses: Iterable[Analysis], levels: Iterable[Level] | None = None) -> list[Series]:
    out = []
    levels = list(levels) if levels is not None else None
    for i, a in enumerate(analyses):
        c, m = style_for(i)
        out.append(Series(a, c, m, levels[i] if levels else Level.PASS))
    return out
