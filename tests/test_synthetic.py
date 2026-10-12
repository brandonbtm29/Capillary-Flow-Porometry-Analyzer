"""Tests on made-up .CFT files, so they run anywhere (no lab data needed).

The synthetic run: ambient 14.7 psia, dry flow = 1000 cc/min per psi measured up to 5 psi, wet flow =
dry x F with F rising linearly from 0 at 1 psi to 1 at 4 psi, wet measured every 0.5 psi up to 7 psi.
By hand: bubble point 1.5 psi; wet meets half dry at 2.5 psi; CFF first reaches 98 % at 4.0 psi.
"""

from pathlib import Path

import numpy as np
import pytest

from porometry.analysis import CAPREP_CONSTANT, Settings, _caprep_cff, _dry_function, analyze
from porometry.cft import CFTError, read_cft
from porometry.workspace import group_key

P0 = 14.7
GAMMA = 15.9


def _fraction(dp):
    return np.clip((dp - 1.0) / 3.0, 0.0, 1.0)


def write_cft(path: Path, test_type="Wet Up/Dry Up", blip=None) -> Path:
    wet_dp = np.arange(0.0, 7.01, 0.5)
    wet = [(1000 * d * _fraction(d), P0 + d) for d in wet_dp]
    if blip is not None:  # (dP psi, flow cc/min) logged right after the zero point
        wet.insert(1, (blip[1], P0 + blip[0]))
    dry = [(1000 * d, P0 + d) for d in np.arange(0.5, 5.01, 0.5)]
    lines = ["EXTENDED", " 8 ", "Operator=Test", "Lot Number=", "Hardware Serial Number=0",
             f"Type of test= {test_type}", "Wet Parameter=x.tpf", "Dry Parameter=x.tpf",
             "Lohm Table=lohmtable.cal", "Tortuosity Factor= .715", "01-01-2026", "", "",
             "Galwick", f"-{GAMMA}", " .635", " .05", "1"]
    lines += [f" {q:.6g}, {p:.6g}" for q, p in wet] + ["0,0"]
    lines += [f" {q:.6g}, {p:.6g}" for q, p in dry] + ["0,0", "", "B, 15, 250, 0, 1, 2", "0,0"]
    path.write_text("\r\n".join(lines) + "\r\n", encoding="latin-1")
    return path


def d_of(dp):
    return CAPREP_CONSTANT * GAMMA / dp


def test_parser_reads_header_and_curves(tmp_path):
    r = read_cft(write_cft(tmp_path / "a.CFT"))
    assert r.fluid == "Galwick" and r.surface_tension == pytest.approx(GAMMA)
    assert r.wet.n == 15 and r.dry.n == 10 and r.p_atm == pytest.approx(P0)
    assert r.tortuosity == pytest.approx(0.715)


def test_not_a_cft(tmp_path):
    p = tmp_path / "x.cft"
    p.write_text("hello\nworld\n")
    with pytest.raises(CFTError):
        read_cft(p)


def test_hand_calculated_results(tmp_path):
    a = analyze(read_cft(write_cft(tmp_path / "a.CFT")))
    assert a.bubble_dp == pytest.approx(1.5)
    assert a.bubble_d == pytest.approx(d_of(1.5))
    assert a.mean_flow_dp == pytest.approx(2.5)
    assert a.smallest_dp == pytest.approx(4.0)
    assert a.smallest_d == pytest.approx(d_of(4.0))


def test_dry_up_wet_up_still_has_wet_curve_first(tmp_path):
    """CapWin stores the wet curve first even for Dry Up/Wet Up runs."""
    a = analyze(read_cft(write_cft(tmp_path / "a.CFT", "Dry Up/Wet Up")))
    assert a.bubble_dp == pytest.approx(1.5) and a.mean_flow_dp == pytest.approx(2.5)


def test_dry_curve_is_extended_past_its_last_point(tmp_path):
    """Wet points above the last dry point (5 psi) are kept, as in CapRep."""
    a = analyze(read_cft(write_cft(tmp_path / "a.CFT")))
    assert a.dp.max() == pytest.approx(7.0)
    assert a.dry_at_wet[-1] == pytest.approx(7000)
    off = analyze(read_cft(write_cft(tmp_path / "b.CFT")), Settings(extrapolate_dry=False))
    assert off.dp.max() == pytest.approx(5.0)


def test_extension_uses_line_through_last_three_dry_points():
    f = _dry_function(np.array([3.0, 4.0, 4.5, 5.0]), np.array([3000, 4000, 4600, 5100.0]), "interp")
    # least squares through (4, 4000), (4.5, 4600), (5, 5100): slope 1100, intercept -383.33
    assert f(6.0) == pytest.approx(-383.333 + 1100 * 6, rel=1e-6)
    assert f(4.25) == pytest.approx(4300)  # inside the range: plain interpolation


def test_caprep_cff_never_decreases_and_caps_at_100():
    raw = np.array([10.0, 40.0, 35.0, 90.0, 104.0, 99.0])
    assert _caprep_cff(raw).tolist() == [10, 40, 40, 90, 100, 100]


def test_startup_blip_above_dry_flow_is_ignored(tmp_path):
    """15 cc/min at 0.001 psi is more than the dry flow there (1 cc/min): not a real bubble point."""
    a = analyze(read_cft(write_cft(tmp_path / "a.CFT", blip=(0.001, 15.0))))
    assert a.bubble_dp == pytest.approx(1.5)
    assert any("start-up" in n for n in a.notes)
    exact = analyze(read_cft(write_cft(tmp_path / "b.CFT", blip=(0.001, 15.0))), Settings(min_dp_kpa=0))
    assert exact.bubble_dp == pytest.approx(0.001)  # what CapRep itself reports


def test_low_pressure_flow_below_dry_flow_is_kept(tmp_path):
    """Very open media really do bubble below 0.5 kPa; CapRep reports those, so must we."""
    a = analyze(read_cft(write_cft(tmp_path / "a.CFT", blip=(0.001, 0.5))))
    assert a.bubble_dp == pytest.approx(0.001)


def test_group_key():
    assert group_key(Path("CFP-0_25MM_MIN_TEST3.CFT")) == "CFP-0_25MM_MIN"
    assert group_key(Path("CFP-10_00MM_MIN_S1_TEST1.CFT")) == "CFP-10_00MM_MIN"
    assert group_key(Path("x/CFP-0_70MM_MIN/a.CFT"), "folder") == "CFP-0_70MM_MIN"


def test_template_notebook_has_no_outputs():
    """The repo is public: the notebook template must never carry results (plots, tables) from lab data."""
    import json

    nb = json.loads((Path(__file__).parents[1] / "examples" / "compare_conditions.ipynb").read_text(encoding="utf-8"))
    assert all(not c.get("outputs") for c in nb["cells"])
