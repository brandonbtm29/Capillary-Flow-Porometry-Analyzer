"""Capillary flow porometry calculations, following PMI CapRep's formulas.

All pressures here are differential pressures in psi; diameters are in micrometres.
Convert for display with :data:`porometry.cft.PSI_TO_KPA`.

CapRep (Calculations help page):
    Diameter  D  = C * gamma / dP          C = 0.415 with dP in psi, gamma in dyn/cm
    CFF (%)      = Q_wet / Q_dry * 100     cumulative filter flow
    FF  (%)      = CFF_i - CFF_(i-1)       filter flow through each step
    PSD          = FF / (D_(i-1) - D_i)    plotted at the average diameter
    Mean flow pore = diameter where Q_wet = Q_dry / 2

C = 0.415 equals 4 * cos(theta) * 0.715 / 6.894757 (psi -> kPa) with cos(theta) = 1;
0.715 is the "Tortuosity Factor" CapWin writes into each file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .cft import PSI_TO_KPA, Run

CAPREP_CONSTANT = 0.415  # um * psi / (dyn/cm), includes the 0.715 shape factor
CAPREP_SHAPE_FACTOR = 0.715


@dataclass
class Settings:
    """Analysis options. Defaults reproduce CapRep."""

    shape_factor: float = CAPREP_SHAPE_FACTOR  # 1.0 = plain Young-Laplace (4*gamma/dP)
    bubble_flow_threshold: float = 0.0  # cc/min; bubble point = first wet point above this
    min_dp_kpa: float = 0.5  # wet points below this differential pressure are ignored (start-up blips)
    smallest_pore_cff: float = 98.0  # %; CapRep: first measured point where CFF reaches 98 % (else the CFF peak)
    clip_cff: bool = True  # clip CFF to 0-100 % before computing the distribution
    dry_model: str = "interp"  # "interp" (CapRep) or "poly2" (smooth quadratic fit through 0)
    # CapRep conventions, checked against 311 CapRep reports (scratch/validate_vs_caprep.py):
    cff_mode: str = "caprep"  # "caprep": CFF never decreases and is capped at 100 %; "raw": wet/dry x 100
    extrapolate_dry: bool = True  # extend the dry curve past its last point along its last segment
    mfp_method: str = "half_dry"  # "half_dry": wet curve meets half the dry curve; "cff": CFF = 50 % crossing

    @property
    def diameter_constant(self) -> float:
        return CAPREP_CONSTANT * self.shape_factor / CAPREP_SHAPE_FACTOR


@dataclass
class Analysis:
    run: Run
    settings: Settings
    # dry curve (differential)
    dry_dp: np.ndarray
    dry_flow: np.ndarray
    # wet curve (differential), all points
    wet_dp: np.ndarray
    wet_flow: np.ndarray
    # wet points with dP > 0 and a dry value available
    dp: np.ndarray
    diameter: np.ndarray
    dry_at_wet: np.ndarray
    cff: np.ndarray  # %, as reported (CapRep convention unless Settings.cff_mode == "raw")
    wet_q: np.ndarray  # wet flow (cc/min) at those points
    cff_raw: np.ndarray = field(default_factory=lambda: np.array([]))  # %, plain wet/dry x 100 (used by QC)
    # results (None when not defined)
    bubble_dp: float | None = None
    bubble_d: float | None = None
    mean_flow_dp: float | None = None
    mean_flow_d: float | None = None
    smallest_dp: float | None = None
    smallest_d: float | None = None
    notes: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ helpers
    def to_d(self, dp_psi: float | np.ndarray) -> float | np.ndarray:
        return self.settings.diameter_constant * self.run.surface_tension / np.asarray(dp_psi)

    @property
    def max_dp(self) -> float:
        vals = [a.max() for a in (self.wet_dp, self.dry_dp) if a.size]
        return float(max(vals)) if vals else 0.0

    def cff_for_distribution(self) -> np.ndarray:
        c = self.cff.copy()
        if self.settings.clip_cff:
            c = np.clip(c, 0.0, 100.0)
        return c

    def distribution(self, weighting: str = "D") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Point-by-point pore size distribution, as CapRep computes it.

        Returns (average diameter um, distribution, flow % in the step).
        weighting "D": %/um = dCFF / dD (the manual, and the lab's current CapRep export).
        "D2": %/um^2 = dCFF / d(D^2).   "dD2": dCFF / (dD)^2, which some older CapRep exports use.
        """
        if self.dp.size < 2:
            e = np.array([])
            return e, e, e
        c = self.cff_for_distribution()
        d = self.diameter
        dcff = np.diff(c)
        if weighting == "D2":
            width = d[:-1] ** 2 - d[1:] ** 2
        elif weighting == "dD2":
            width = (d[:-1] - d[1:]) ** 2
        else:
            width = d[:-1] - d[1:]
        with np.errstate(divide="ignore", invalid="ignore"):
            psd = np.where(width > 0, dcff / width, np.nan)
        avg = (d[:-1] + d[1:]) / 2
        return avg, psd, dcff

    def binned_distribution(self, n_bins: int = 20, log: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Histogram of flow through pores, binned by diameter.

        Returns (bin edges um, flow % per bin, %/um per bin, bin centres um).
        CFF is interpolated (in log D) between measured points.
        """
        c = self.cff_for_distribution()
        d = self.diameter
        if d.size < 2:
            e = np.array([])
            return e, e, e, e
        lo, hi = float(d.min()), float(d.max())
        edges = np.geomspace(lo, hi, n_bins + 1) if log else np.linspace(lo, hi, n_bins + 1)
        # d decreases along the curve; np.interp needs increasing x
        x = np.log(d[::-1]) if log else d[::-1]
        y = c[::-1]
        xe = np.log(edges) if log else edges
        cff_at_edges = np.interp(xe, x, y)
        flow_pct = cff_at_edges[:-1] - cff_at_edges[1:]  # small-D edge minus large-D edge
        density = flow_pct / np.diff(edges)
        centres = np.sqrt(edges[:-1] * edges[1:]) if log else (edges[:-1] + edges[1:]) / 2
        return edges, flow_pct, density, centres

    @property
    def closed(self) -> bool:
        """True when CFF reached the smallest-pore level (wet met dry), so the smallest pore was measured."""
        return bool(self.cff.size and np.nanmax(self.cff) >= self.settings.smallest_pore_cff)

    def d_at_cff(self, level: float) -> float | None:
        """Diameter at which CFF first reaches `level` % (e.g. 50 = mean flow pore)."""
        dp = _crossing(self.dp, self.cff, level)
        return None if dp is None else float(self.to_d(dp))


def _crossing(x: np.ndarray, y: np.ndarray, level: float) -> float | None:
    """x where y first rises through `level` (linear interpolation). None if y starts above it or never gets there."""
    if y.size == 0 or y[0] >= level:
        return None
    idx = np.nonzero(y >= level)[0]
    if idx.size == 0:
        return None
    i = int(idx[0])
    x0, x1, y0, y1 = x[i - 1], x[i], y[i - 1], y[i]
    if y1 == y0:
        return float(x1)
    return float(x0 + (level - y0) * (x1 - x0) / (y1 - y0))


def _dry_function(dp: np.ndarray, flow: np.ndarray, model: str, extrapolate: bool = True):
    """Return f(dP) giving dry flow.

    Above the last dry point CapRep extends the dry curve along a straight line fitted to its last 3
    points (checked on reports whose wet run went higher than the dry run). With extrapolate=False it
    returns NaN there.
    """
    if dp.size == 0:
        return lambda q: np.full_like(np.asarray(q, dtype=float), np.nan)
    # anchor: no flow at zero differential pressure
    if dp.min() > 0:
        dp = np.concatenate([[0.0], dp])
        flow = np.concatenate([[0.0], flow])
    top = dp.max()
    if model == "poly2" and dp.size >= 4:
        # least squares a*dP + b*dP^2 (passes through the origin)
        A = np.column_stack([dp, dp**2])
        coef, *_ = np.linalg.lstsq(A, flow, rcond=None)

        def f(q):
            q = np.asarray(q, dtype=float)
            out = coef[0] * q + coef[1] * q**2
            return out if extrapolate else np.where(q <= top * 1.0001, out, np.nan)

        return f

    # CapRep extends the dry curve with the least-squares line through its last 3 points
    # (median error 0.003 % on 125 reports with extrapolated rows; scratch/test_extrapolation.py).
    k = min(3, dp.size)
    if k >= 2 and np.ptp(dp[-k:]) > 0:
        slope, intercept = np.polyfit(dp[-k:], flow[-k:], 1)
    else:
        slope, intercept = 0.0, float(flow[-1])

    def f(q):
        q = np.asarray(q, dtype=float)
        out = np.interp(q, dp, flow)
        if not extrapolate:
            return np.where(q <= top * 1.0001, out, np.nan)
        return np.where(q > top, intercept + slope * q, out)

    return f


def _caprep_cff(raw: np.ndarray) -> np.ndarray:
    """CapRep's reported CFF: never decreases from one point to the next and is capped at 100 %."""
    out = np.minimum(np.fmax.accumulate(np.nan_to_num(raw, nan=0.0)), 100.0)
    return np.where(np.isfinite(raw), out, np.nan)


def _half_dry_crossing(dp: np.ndarray, wet_q: np.ndarray, dry_f, lo: float) -> float | None:
    """dP where the wet curve first rises through half the dry curve (CapRep's mean flow pressure).

    Both curves are straight lines between their own measured points, so the crossing is found on the
    union of wet and dry breakpoints. Only pressures from `lo` (the first usable wet point) up are used.
    """
    if dp.size < 2:
        return None
    knots = np.unique(np.concatenate([dp, dry_f.knots[(dry_f.knots > dp[0]) & (dry_f.knots < dp[-1])]]))
    knots = knots[knots >= lo]
    w = np.interp(knots, dp, wet_q)
    g = w - dry_f(knots) / 2.0
    if g.size == 0 or not np.isfinite(g[0]) or g[0] >= 0:
        return None
    idx = np.nonzero(g >= 0)[0]
    if idx.size == 0:
        return None
    i = int(idx[0])
    x0, x1, g0, g1 = knots[i - 1], knots[i], g[i - 1], g[i]
    return float(x1) if g1 == g0 else float(x0 - g0 * (x1 - x0) / (g1 - g0))


def analyze(run: Run, settings: Settings | None = None) -> Analysis:
    s = settings or Settings()
    p0 = run.p_atm
    wet_dp = run.wet.pressure - p0
    dry_dp = run.dry.pressure - p0
    wet_flow = run.wet.flow
    dry_flow = run.dry.flow

    dry_f = None
    if run.dry.n >= 2:
        ok = dry_dp >= 0
        dry_f = _dry_function(dry_dp[ok], dry_flow[ok], s.dry_model, s.extrapolate_dry)
        dry_f.knots = np.unique(dry_dp[ok])

    # Start-up blips: CapWin sometimes logs a wet point with flow at almost zero pressure (e.g. 15 cc/min
    # at 0.008 kPa). CapRep has no cut-off: its bubble point is always the first wet point with flow, even
    # far below 0.5 kPa for very open media. So a point below min_dp_kpa is dropped only when its wet flow
    # exceeds the dry flow there, which a real bubble point cannot do.
    min_dp = s.min_dp_kpa / PSI_TO_KPA
    blip = (wet_dp > 0) & (wet_dp < min_dp)
    if dry_f is not None:
        with np.errstate(invalid="ignore"):
            blip &= wet_flow > dry_f(wet_dp)
    mask = (wet_dp > 0) & ~blip
    if blip.any():
        notes_blip = (f"Ignored {int(blip.sum())} start-up point(s) below {s.min_dp_kpa:g} kPa "
                      "where wet flow exceeded dry flow.")
    else:
        notes_blip = None
    dp = wet_dp[mask]
    q = wet_flow[mask]
    if dry_f is not None:
        dry_at = dry_f(dp)
        with np.errstate(divide="ignore", invalid="ignore"):
            cff = np.where(dry_at > 0, q / dry_at * 100.0, np.nan)
        keep = np.isfinite(cff)
    else:
        dry_at = np.full_like(dp, np.nan)
        cff = np.full_like(dp, np.nan)
        keep = np.zeros_like(dp, dtype=bool)

    raw = cff[keep]
    a = Analysis(
        run=run,
        settings=s,
        dry_dp=dry_dp,
        dry_flow=dry_flow,
        wet_dp=wet_dp,
        wet_flow=wet_flow,
        dp=dp[keep],
        diameter=s.diameter_constant * run.surface_tension / dp[keep] if keep.any() else np.array([]),
        dry_at_wet=dry_at[keep],
        cff=_caprep_cff(raw) if s.cff_mode == "caprep" else raw.copy(),
        wet_q=q[keep],
        cff_raw=raw,
    )

    # bubble point: first wet point with flow above the threshold (needs no dry curve)
    if notes_blip:
        a.notes.append(notes_blip)
    above = np.nonzero(mask & (wet_flow > s.bubble_flow_threshold))[0]
    if above.size:
        a.bubble_dp = float(wet_dp[above[0]])
        a.bubble_d = float(a.to_d(a.bubble_dp))

    if a.dp.size:
        if s.mfp_method == "half_dry":
            a.mean_flow_dp = _half_dry_crossing(a.dp, a.wet_q, dry_f, float(a.dp[0]))
        else:
            a.mean_flow_dp = _crossing(a.dp, a.cff, 50.0)
        if a.mean_flow_dp is not None:
            a.mean_flow_d = float(a.to_d(a.mean_flow_dp))
        # smallest detected pore: CapRep takes the first measured point whose CFF reaches 98 % (no
        # interpolation; matched 173 of 174 CapRep reports). If CFF never gets there, the CFF peak.
        if np.isfinite(a.cff).any():
            hit = np.nonzero(a.cff >= s.smallest_pore_cff)[0]
            i = int(hit[0]) if hit.size else int(np.nanargmax(a.cff))
            if not hit.size:
                a.notes.append(f"CFF peaks at {a.cff[i]:.1f}%, so the smallest pore is taken at that point.")
            a.smallest_dp = float(a.dp[i])
            a.smallest_d = float(a.to_d(a.smallest_dp))
    else:
        a.notes.append("No usable wet/dry overlap: the dry curve is missing or too short.")
    return a
