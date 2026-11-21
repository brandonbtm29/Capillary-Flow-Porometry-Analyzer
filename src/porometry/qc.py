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
    dry_check_pass_pct: float = 5.0  # dry check: the two passes may differ by this much (median) ...
    dry_check_previous_pct: float = 15.0  # ... and its second pass from the previous test's dry curve by this much


@dataclass
class Finding:
    code: str
    level: Level
    title: str
    detail: str


@dataclass
class QCReport:
    findings: list[Finding] = field(default_factory=list)
    dry_check: bool = False  # checked as a dry check (the dry specimen run twice), not as a pore-size test

    @property
    def level(self) -> Level:
        return max((f.level for f in self.findings), default=Level.PASS)

    @property
    def status(self) -> str:
        if self.dry_check and self.level <= Level.INFO:
            return "dry check"
        return self.level.label

    def summary(self) -> str:
        bad = [f.title for f in self.findings if f.level >= Level.WARN]
        return "; ".join(bad) if bad else ("Dry check" if self.dry_check else "OK")

    def add(self, *args) -> None:
        self.findings.append(Finding(*args))


def check(a: Analysis, s: QCSettings | None = None, dry_check: bool = False,
          previous: Analysis | None = None) -> QCReport:
    """QC findings for one run. A dry check (marked by you: the dry specimen run again after its test) skips
    the pore-size checks; instead its two passes are compared with each other and with `previous`, the dry
    curve of the test before it on the same specimen, when that run is loaded."""
    s = s or QCSettings()
    r = QCReport(dry_check=dry_check)
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

    if dry_check:
        _dry_check(r, a, s, previous)
    else:
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
                same = pass_difference(a)
                if same is not None and same <= s.dry_check_pass_pct:
                    r.add("looks_dry_check", Level.INFO, "Looks like a dry check",
                          f"Wet and dry flow agree within a median {same:.1f}% from the first point, as when a dry "
                          "specimen is run twice. If this run was a dry check, mark it with Runs > Mark as dry "
                          "check: it is then checked as one and stops failing QC.")

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


def pass_difference(a: Analysis) -> float | None:
    """Median difference (%) between a run's wet and dry flow where there is real flow. For a dry check these
    are its two passes."""
    if not a.dp.size or not a.dry_at_wet.size:
        return None
    ok = np.isfinite(a.cff_raw) & (a.dry_at_wet > 0.05 * np.nanmax(a.dry_at_wet))
    if ok.sum() < 3:
        return None
    return float(np.median(np.abs(a.cff_raw[ok] - 100.0)))


def dry_curve_difference(a: Analysis, ref: Analysis) -> float | None:
    """Signed median difference (%) of `a`'s dry curve from `ref`'s, over the pressures both cover, where there
    is real flow. Negative = `a` passes less gas."""
    x, y = a.dry_dp, a.dry_flow
    order = np.argsort(ref.dry_dp)
    rx, ry = ref.dry_dp[order], ref.dry_flow[order]
    if x.size < 3 or rx.size < 3:
        return None
    m = (x >= rx[0]) & (x <= rx[-1]) & (y > 0.05 * np.nanmax(y))
    ref_at = np.interp(x[m], rx, ry)
    ok = ref_at > 0
    if ok.sum() < 3:
        return None
    return float(np.median(y[m][ok] / ref_at[ok] - 1.0) * 100.0)


def _dry_check(r: QCReport, a: Analysis, s: QCSettings, previous: Analysis | None) -> None:
    d = pass_difference(a)
    if d is None:
        r.add("dry_check", Level.INFO, "Dry check",
              "Marked as a dry check: no pore sizes are reported and it is never averaged. "
              "Too few points with flow to compare its two passes.")
    elif d <= s.dry_check_pass_pct:
        r.add("dry_check", Level.INFO, "Dry check",
              f"Marked as a dry check: no pore sizes are reported and it is never averaged. Its two passes "
              f"agree within a median {d:.1f}% (limit {s.dry_check_pass_pct:g}%).")
    else:
        r.add("dry_check", Level.WARN, "Dry check: passes differ",
              f"The two passes of this dry check differ by a median {d:.1f}% (limit {s.dry_check_pass_pct:g}%), "
              "so the flow readings didn't repeat. Check the gas supply and the seal, and whether liquid was "
              "left in the specimen.")
    if previous is None:
        return
    p = dry_curve_difference(a, previous)
    if p is None:
        return
    how = f"{abs(p):.0f}% {'below' if p < 0 else 'above'}"
    name = previous.run.name
    if abs(p) <= s.dry_check_previous_pct:
        r.add("dry_check_previous", Level.INFO, "Dry check matches the test before",
              f"Its second pass runs a median {how} the dry curve of {name} (limit {s.dry_check_previous_pct:g}%).")
    else:
        r.add("dry_check_previous", Level.WARN, "Dry check differs from the test before",
              f"Its second pass runs a median {how} the dry curve of {name} (limit "
              f"{s.dry_check_previous_pct:g}%). Possible causes: liquid left in the specimen, a specimen that "
              "was reloaded or changed, or a change in the gas flow.")


def _longest_run(mask: np.ndarray) -> int:
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best
