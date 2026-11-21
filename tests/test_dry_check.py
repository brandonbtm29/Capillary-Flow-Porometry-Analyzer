"""Dry checks: runs you mark as the dry specimen run again (made-up runs, no lab data)."""

import pandas as pd
import pytest
from _synth import write_dry_check, write_run  # noqa: E402

from porometry.figures import PlotOptions, make_figure
from porometry.qc import Level
from porometry.tags import SIDECAR, MemoryTags, SidecarTags
from porometry.workspace import DRY_CHECK, Workspace


def load(folder, store=None) -> Workspace:
    ws = Workspace(tag_store=store or MemoryTags())
    ws.add_folder(folder)
    return ws


def by_name(ws, name):
    return next(e for e in ws.entries if e.name == name)


def codes(e) -> set[str]:
    return {f.code for f in e.qc.findings}


def test_unmarked_dry_check_fails_as_a_leak_and_looks_like_a_dry_check(tmp_path):
    write_dry_check(tmp_path / "CFP-0_25MM_MIN_S2T2.CFT")
    e = load(tmp_path).entries[0]
    assert not e.dry_check
    assert e.qc.level == Level.FAIL and {"leak", "looks_dry_check"} <= codes(e)


def test_normal_runs_never_look_like_dry_checks(speeds):
    for e in load(speeds).entries:
        assert "looks_dry_check" not in codes(e) and not e.dry_check


def test_mark_is_checked_as_a_dry_check_saved_and_kept(tmp_path):
    write_dry_check(tmp_path / "CFP-0_25MM_MIN_S2T2.CFT")
    ws = load(tmp_path, SidecarTags())
    e = ws.entries[0]
    ws.set_dry_check([e], True)
    assert e.dry_check and e.qc.dry_check
    assert e.qc.level <= Level.INFO and e.qc.status == "dry check" and e.qc.summary() == "Dry check"
    assert "dry_check" in codes(e) and not codes(e) & {"leak", "no_mfp", "not_closed", "looks_dry_check"}
    assert DRY_CHECK in (tmp_path / SIDECAR).read_text(encoding="utf-8-sig")

    ws2 = load(tmp_path, SidecarTags())  # opened again: still a dry check, and not a column of its own
    e2 = ws2.entries[0]
    assert e2.dry_check and DRY_CHECK not in ws2.fields
    ws2.set_tag([e2], "Condition", "baseline")
    ws2.reset_tags([e2])  # back to automatic tags: the mark stays
    assert e2.dry_check and e2.tags["Condition"] == "0.25 mm/min"
    ws2.set_dry_check([e2], False)
    assert not e2.dry_check and e2.qc.level == Level.FAIL


@pytest.mark.parametrize("value", ["yes", "Yes", "x", "TRUE", "1"])
def test_mark_typed_in_excel(tmp_path, value):
    write_dry_check(tmp_path / "CFP-0_25MM_MIN_S2T2.CFT")
    (tmp_path / SIDECAR).write_text(f"File,{DRY_CHECK}\nCFP-0_25MM_MIN_S2T2.CFT,{value}\n", encoding="utf-8")
    assert load(tmp_path, SidecarTags()).entries[0].dry_check


def test_passes_that_differ_warn(tmp_path):
    write_dry_check(tmp_path / "CFP-X_S1T2.CFT", first=1.0, second=1.25)
    ws = load(tmp_path)
    ws.set_dry_check(ws.entries, True)
    e = ws.entries[0]
    assert e.qc.level == Level.WARN and e.qc.status == "warn"
    assert next(f for f in e.qc.findings if f.code == "dry_check").title == "Dry check: passes differ"


def test_dry_check_is_compared_with_the_test_before(tmp_path):
    write_run(tmp_path / "CFP-0_25MM_MIN_S2T1.CFT")
    write_dry_check(tmp_path / "CFP-0_25MM_MIN_S2T2.CFT")  # same flow as S2T1's dry curve
    write_run(tmp_path / "CFP-0_25MM_MIN_S3T1.CFT")
    write_dry_check(tmp_path / "CFP-0_25MM_MIN_S3T2.CFT", 0.6, 0.6)  # 40 % less gas than S3T1's dry curve
    ws = load(tmp_path)
    good, low = by_name(ws, "CFP-0_25MM_MIN_S2T2"), by_name(ws, "CFP-0_25MM_MIN_S3T2")
    ws.set_dry_check([good, low], True)
    f = {x.code: x for x in good.qc.findings}
    assert f["dry_check_previous"].level == Level.INFO and "S2T1" in f["dry_check_previous"].detail
    assert good.qc.status == "dry check"
    f = {x.code: x for x in low.qc.findings}
    assert f["dry_check_previous"].level == Level.WARN and "40% below" in f["dry_check_previous"].detail
    # the test before isn't loaded: no comparison
    ws.remove(by_name(ws, "CFP-0_25MM_MIN_S2T1"))
    ws.recheck()
    assert "dry_check_previous" not in codes(good)


def test_dry_checks_are_never_averaged_and_have_no_pore_sizes(speeds):
    write_dry_check(speeds / "CFP-0_25MM_MIN_S1_TEST4.CFT")
    ws = load(speeds)
    dry = by_name(ws, "CFP-0_25MM_MIN_S1_TEST4")
    ws.set_dry_check([dry], True)
    g = next(g for g in ws.group_data() if g.name == "0.25 mm/min")
    assert len(g.analyses) == 3 and dry.analysis not in g.analyses and dry.analysis not in g.excluded
    assert ws.group_frame().set_index("Group").loc["0.25 mm/min", "Runs"] == 3
    row = ws.summary_frame().set_index("Run").loc[dry.name]
    assert row[DRY_CHECK] == "yes" and pd.isna(row["Mean flow pore (µm)"]) and pd.isna(row["Largest pore (µm)"])
    assert ws.summary_frame().set_index("Run").loc["CFP-0_25MM_MIN_S1_TEST3", DRY_CHECK] == ""


@pytest.mark.parametrize("kind", ["flow", "cff", "psd", "compare", "all"])
def test_plots_with_a_dry_check(speeds, kind):
    write_dry_check(speeds / "CFP-0_25MM_MIN_S1_TEST4.CFT")
    ws = load(speeds)
    ws.set_dry_check([by_name(ws, "CFP-0_25MM_MIN_S1_TEST4")], True)
    fig = make_figure(kind, ws.series(), PlotOptions(display="runs"), groups=ws.group_data())
    labels = [t for ax in fig.axes for t in ax.get_legend_handles_labels()[1]]
    assert any("[dry check]" in t for t in labels) == (kind in ("flow", "all"))
