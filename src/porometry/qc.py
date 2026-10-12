"""Data-quality checks: decide whether a run's numbers can be trusted."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np

from .analysis import Analysis
from .cft import PSI_TO_KPA


class Level(IntEnum):
    PASS = 0
    INFO = 1
    WARN = 2
    FAIL = 3

    @property
    def label(self) -> str:
        return {0: "pass", 1: "info", 2: "warn", 3: "fail"}[int(self)]


@dataclass
class QCSettings:
    min_dry_points: int = 5
    min_wet_points: int = 5
    below_ambient_kpa: float = -0.5  # any point below this differential pressure fails
    leak_window_frac: float = 0.05  # first 5 % of the pressure range ...
    leak_cff: float = 20.0  # ... wet flow above 20 % of dry there = leak / bypass
    wet_above_dry_cff: float = 105.0
    wet_above_dry_points: int = 3  # consecutive points above that
    wet_meets_dry_cff: float = 95.0  # max CFF below this = distribution cut off
    min_points_bp_to_mfp: int = 5
    check_parameter_paths: bool = True


@dataclass
class Finding:
    code: str
    level: Level
    title: str
    detail: str


@dataclass
class QCReport:
    findings: list[Finding] = field(default_factory=list)

    @property
    def level(self) -> Level:
        return max((f.level for f in self.findings), default=Level.PASS)

    @property
    def status(self) -> str:
        return self.level.label

    def summary(self) -> str:
        bad = [f.title for f in self.findings if f.level >= Level.WARN]
        return "; ".join(bad) if bad else "OK"

    def add(self, *args) -> None:
        self.findings.append(Finding(*args))


def check(a: Analysis, s: QCSettings | None = None) -> QCReport:
    s = s or QCSettings()
    r = QCReport()
    run = a.run
    kpa = PSI_TO_KPA

    # --- curve completeness -------------------------------------------------
    if run.wet.n < s.min_wet_points:
        r.add("wet_short", Level.FAIL, "Wet curve too short",
              f"The wet curve has {run.wet.n} points (need at least {s.min_wet_points}).")
    if run.dry.n < s.min_dry_points:
        r.add("dry_missing", Level.FAIL, "Dry curve missing or incomplete",
              f"The dry curve has {run.dry.n} point(s) (need at least {s.min_dry_points}). "
              "The dry run was probably stopped early. CapRep reports 'The data file cannot be processed' for files like this.")

    # --- pressure sanity ----------------------------------------------------
    lowest = min([x.min() for x in (a.wet_dp, a.dry_dp) if x.size], default=0.0) * kpa
    if lowest < s.below_ambient_kpa:
        r.add("below_ambient", Level.FAIL, "Pressure below ambient",
              f"A point was recorded at {lowest:.1f} kPa differential (below atmospheric). "
              "This usually means the run was aborted or the pressure transducer zero drifted.")

    # --- leak / bypass ------------------------------------------------------
    if a.dp.size and run.dry.n >= s.min_dry_points:
        # the first 5 % of the range, and always the first measured point
        window = max(a.max_dp * s.leak_window_frac, float(a.dp[0]))
        early = a.cff_raw[a.dp <= window]
        if early.size and np.nanmax(early) > s.leak_cff:
            d_window = a.to_d(window)
            r.add("leak", Level.FAIL, "Flow at near-zero pressure (leak or bypass)",
                  f"Wet flow is already {np.nanmax(early):.0f}% of dry flow below {window * kpa:.1f} kPa. "
                  "A wetted sample should pass almost no air before its bubble point. Likely causes: air "
                  "leaking around the sample (seal, O-ring, support mesh under the seal), a pinhole or tear, "
                  f"or incomplete wetting. (Real pores would have to be larger than about {d_window:.0f} um.)")

    # --- mean flow pore -----------------------------------------------------
    if a.dp.size and a.mean_flow_d is None:
        if a.cff_raw[0] >= 50:
            why = f"CFF is already {a.cff_raw[0]:.0f}% at the first point, so wet flow never crosses half of dry flow."
        else:
            why = f"CFF only reaches {np.nanmax(a.cff_raw):.0f}% by the end of the test."
        r.add("no_mfp", Level.FAIL, "No mean flow pore", why)

    # --- wet above dry ------------------------------------------------------
    if a.cff_raw.size:
        over = a.cff_raw > s.wet_above_dry_cff
        run_len = _longest_run(over)
        if run_len >= s.wet_above_dry_points:
            first = a.dp[np.argmax(over)] * kpa
            r.add("wet_above_dry", Level.WARN, "Wet flow above dry flow",
                  f"Wet flow exceeds dry flow by more than {s.wet_above_dry_cff - 100:.0f}% for {run_len} points, "
                  f"starting near {first:.0f} kPa. The sample may be stretching or tearing at high pressure, "
                  "or it changed between the wet and dry runs. Consider a lower maximum pressure.")
        mx = float(np.nanmax(a.cff_raw))
        if mx < s.wet_meets_dry_cff:
            r.add("not_closed", Level.WARN, "Wet curve never meets dry curve",
                  f"CFF peaks at {mx:.0f}%, so the smallest pores never opened and the distribution is cut off. "
                  "Raise the maximum pressure.")

    # --- resolution near the bubble point ------------------------------------
    if a.bubble_dp is not None and a.mean_flow_dp is not None:
        n = int(np.sum((a.dp >= a.bubble_dp) & (a.dp <= a.mean_flow_dp)))
        if n < s.min_points_bp_to_mfp:
            r.add("coarse", Level.WARN, "Few points between bubble point and mean flow pore",
                  f"Only {n} points between {a.bubble_dp * kpa:.0f} and {a.mean_flow_dp * kpa:.0f} kPa. "
                  "Use smaller pressure steps for a smoother distribution.")

    # --- parameter files ------------------------------------------------------
    if s.check_parameter_paths and os.name == "nt":
        for key in ("Wet Parameter", "Dry Parameter"):
            p = run.header.get(key, "")
            if p and not os.path.exists(p):
                r.add("param_path", Level.INFO, "Parameter file not found",
                      f"{key} '{p}' does not exist on this computer. The test settings are still stored in the file.")
                break

    for note in a.notes:
        r.add("note", Level.INFO, "Note", note)
    return r


def _longest_run(mask: np.ndarray) -> int:
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best
