"""Group averages: mean ± SD curves across replicate runs, and statistics between groups.

Curves are averaged where every run in the group has data (the overlapping diameter or pressure range),
on a common grid. Cumulative filter flow is interpolated in log(diameter), as for the binned distribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .analysis import Analysis
from .cft import PSI_TO_KPA

# metric key -> (label, unit kind)  ("um" or "pressure")
METRICS = {
    "mean_flow_d": ("Mean flow pore", "um"),
    "bubble_d": ("Largest pore (bubble point)", "um"),
    "smallest_d": ("Smallest pore", "um"),
    "bubble_dp": ("Bubble point pressure", "pressure"),
    "mean_flow_dp": ("Mean flow pressure", "pressure"),
}


@dataclass
class GroupData:
    """Runs of one group, as plotted. `analyses` passed QC; `excluded` did not (shown but not averaged)."""
    name: str
    color: str
    analyses: list[Analysis]
    labels: list[str] = field(default_factory=list)
    excluded: list[Analysis] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.analyses)


@dataclass
class MeanCurve:
    x: np.ndarray
    mean: np.ndarray
    sd: np.ndarray  # NaN where only one run
    n: int


def _mean_sd(stack: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = stack.mean(axis=0)
    sd = stack.std(axis=0, ddof=1) if stack.shape[0] > 1 else np.full(stack.shape[1], np.nan)
    return mean, sd


def _d_range(analyses: list[Analysis]) -> tuple[float, float] | None:
    lo, hi = [], []
    for a in analyses:
        d = a.diameter[np.isfinite(a.diameter) & (a.diameter > 0)]
        if d.size < 2:
            return None
        lo.append(d.min())
        hi.append(d.max())
    if not lo:
        return None
    a, b = max(lo), min(hi)
    return (a, b) if b > a * 1.0001 else None


def _cff_at(a: Analysis, d_grid: np.ndarray) -> np.ndarray:
    """CFF (clipped like the distribution) at diameters `d_grid`, interpolated in log D."""
    ok = np.isfinite(a.diameter) & (a.diameter > 0)
    d, c = a.diameter[ok], a.cff_for_distribution()[ok]
    order = np.argsort(d)
    return np.interp(np.log(d_grid), np.log(d[order]), c[order])


def cff_mean(analyses: list[Analysis], n: int = 200) -> MeanCurve | None:
    rng = _d_range(analyses)
    if rng is None:
        return None
    grid = np.geomspace(rng[0], rng[1], n)
    mean, sd = _mean_sd(np.array([_cff_at(a, grid) for a in analyses]))
    return MeanCurve(grid, mean, sd, len(analyses))


def psd_mean(analyses: list[Analysis], weighting: str = "D", binned: bool = False, n_bins: int = 20,
             log: bool = True, n_points: int = 40) -> MeanCurve | None:
    """Mean distribution. Point mode: dCFF/dD on a common grid. Binned: % flow per common bin.

    For binned, `x` holds the bin edges (len n_bins + 1) and mean/sd one value per bin.
    """
    rng = _d_range(analyses)
    if rng is None:
        return None
    if binned:
        edges = np.geomspace(rng[0], rng[1], n_bins + 1) if log else np.linspace(rng[0], rng[1], n_bins + 1)
        flows = np.array([(lambda c: c[:-1] - c[1:])(_cff_at(a, edges)) for a in analyses])
        mean, sd = _mean_sd(flows)
        return MeanCurve(edges, mean, sd, len(analyses))
    grid = np.geomspace(rng[0], rng[1], n_points)
    if weighting == "D2":
        width = grid[1:] ** 2 - grid[:-1] ** 2
    elif weighting == "dD2":
        width = (grid[1:] - grid[:-1]) ** 2
    else:
        width = grid[1:] - grid[:-1]
    psd = np.array([(lambda c: (c[:-1] - c[1:]) / width)(_cff_at(a, grid)) for a in analyses])
    mean, sd = _mean_sd(psd)
    return MeanCurve(np.sqrt(grid[:-1] * grid[1:]), mean, sd, len(analyses))


def flow_mean(analyses: list[Analysis], n: int = 150) -> tuple[MeanCurve | None, MeanCurve | None]:
    """Mean wet and dry flow (cc/min) against differential pressure (psi)."""
    out = []
    for kind in ("wet", "dry"):
        curves = [(getattr(a, f"{kind}_dp"), getattr(a, f"{kind}_flow")) for a in analyses]
        if not curves or any(dp.size < 2 for dp, _ in curves):
            out.append(None)
            continue
        hi = min(float(dp.max()) for dp, _ in curves)
        lo = max(float(dp.min()) for dp, _ in curves)
        if hi <= lo:
            out.append(None)
            continue
        grid = np.linspace(lo, hi, n)
        stack = np.array([np.interp(grid, dp, q) for dp, q in curves])
        mean, sd = _mean_sd(stack)
        out.append(MeanCurve(grid, mean, sd, len(analyses)))
    return out[0], out[1]


# ---------------------------------------------------------------- metrics and statistics
def metric_value(a: Analysis, metric: str, units: str = "kPa") -> float | None:
    v = getattr(a, metric)
    if v is None:
        return None
    if METRICS[metric][1] == "pressure":
        v = v * (PSI_TO_KPA if units == "kPa" else 1.0)
    return float(v)


def metric_label(metric: str, units: str = "kPa") -> str:
    label, kind = METRICS[metric]
    return f"{label} ({'µm' if kind == 'um' else units})"


@dataclass
class Stats:
    test: str = ""
    p: float | None = None
    statistic: float | None = None
    pairs: list[tuple[str, str, float, float]] = field(default_factory=list)  # (a, b, mean b - a, p)
    note: str = ""

    def summary(self) -> str:
        if self.p is None:
            return self.note
        fp = format_p(self.p)
        return f"{self.test}: p {fp}" if fp.startswith("<") else f"{self.test}: p = {fp}"


def format_p(p: float | None) -> str:
    if p is None or not np.isfinite(p):
        return "n/a"
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def compare_stats(values: dict[str, list[float]]) -> Stats:
    """Welch's t-test for two groups, one-way ANOVA + Tukey HSD for three or more.

    Groups with fewer than 2 values are left out of the tests (noted).
    """
    usable = {g: [v for v in vs if v is not None and np.isfinite(v)] for g, vs in values.items()}
    small = [g for g, vs in usable.items() if len(vs) < 2]
    usable = {g: vs for g, vs in usable.items() if len(vs) >= 2}
    note = f"Left out (fewer than 2 runs): {', '.join(small)}." if small else ""
    if len(usable) < 2:
        return Stats(note=("Need at least two groups with 2 or more runs each for a test. " + note).strip())
    if all(np.ptp(vs) == 0 for vs in usable.values()) and len({vs[0] for vs in usable.values()}) == 1:
        return Stats(note=("All values are identical; nothing to test. " + note).strip())
    import warnings

    from scipy import stats as st
    names = list(usable)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # near-identical values: scipy warns, p is still defined
        return _tests(st, names, usable, note)


def _tests(st, names, usable, note) -> Stats:
    if len(names) == 2:
        a, b = (np.asarray(usable[n]) for n in names)
        r = st.ttest_ind(a, b, equal_var=False)
        return Stats("Welch t-test", _f(r.pvalue), _f(r.statistic),
                     [(names[0], names[1], float(b.mean() - a.mean()), float(r.pvalue))], note)
    arrays = [np.asarray(usable[n]) for n in names]
    r = st.f_oneway(*arrays)
    pairs = []
    try:
        t = st.tukey_hsd(*arrays)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                pairs.append((names[i], names[j], float(arrays[j].mean() - arrays[i].mean()), float(t.pvalue[i, j])))
    except (AttributeError, ValueError):  # very old scipy
        pass
    return Stats("One-way ANOVA", _f(r.pvalue), _f(r.statistic), pairs, note)


def _f(x) -> float | None:
    x = float(x)
    return x if np.isfinite(x) else None
