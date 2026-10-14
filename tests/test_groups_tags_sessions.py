"""Tags, colours/styles, group means, statistics, figures and sessions, on made-up runs (no lab data)."""

import json
from pathlib import Path

import numpy as np
import pytest

from porometry import groups as G
from porometry.figures import PlotOptions, make_figure, palette_colors
from porometry.qc import Level
from porometry.tags import SIDECAR, MemoryTags, SidecarTags, auto_tags, sort_key
from porometry.workspace import RUN, Workspace

from _synth import write_run  # noqa: E402


def loaded(folder, **kw) -> Workspace:
    ws = Workspace(tag_store=kw.pop("tag_store", MemoryTags()), **kw)
    ws.add_folder(folder)
    return ws


# ---------------------------------------------------------------- tags
@pytest.mark.parametrize("name,cond,sample,rep", [
    ("CFP-0_25MM_MIN_S1_TEST2.CFT", "0.25 mm/min", "S1", "2"),
    ("CFP-10_00MM_MIN_T3.CFT", "10.00 mm/min", "", "3"),
    ("CFP-0_70MM_MIN_TEST4.CFT", "0.70 mm/min", "", "4"),
    ("CFP-PRACTICE-RUN2.CFT", "PRACTICE", "", "2"),
    ("lastdata2_2026-10-08.CFT", "lastdata2 2026-10-08", "", ""),  # dates are not turned into decimals
    ("membrane A_sample3.CFT", "membrane A", "S3", ""),
])
def test_auto_tags_from_file_name(name, cond, sample, rep):
    t = auto_tags(Path("Data/2026-10-11") / name)
    assert (t["Condition"], t["Sample"], t["Replicate"], t["Folder"]) == (cond, sample, rep, "2026-10-11")


def test_natural_order():
    vals = ["10 mm/min", "practice", "0.25 mm/min", "2 mm/min", "Alpha"]
    assert sorted(vals, key=sort_key) == ["0.25 mm/min", "2 mm/min", "10 mm/min", "Alpha", "practice"]


def test_sidecar_file_round_trip(speeds):
    ws = loaded(speeds, tag_store=SidecarTags())
    e = ws.entries[0]
    ws.set_tag([e], "Condition", "baseline")
    ws.set_tag([e], "Membrane", "PES 0.45")  # a new field
    assert "Membrane" in ws.fields and e.group == "baseline"
    text = (speeds / SIDECAR).read_text(encoding="utf-8-sig")
    assert text.splitlines()[0] == "File,Condition,Membrane" and e.path.name in text  # file name keeps its case
    again = loaded(speeds, tag_store=SidecarTags())
    e2 = next(x for x in again.entries if x.name == e.name)
    assert e2.tags["Condition"] == "baseline" and e2.tags["Membrane"] == "PES 0.45" and "Membrane" in again.fields
    again.set_tag([e2], "Condition", "")  # blank = back to automatic
    assert e2.tags["Condition"] == "0.25 mm/min"
    assert "baseline" not in (speeds / SIDECAR).read_text(encoding="utf-8-sig")
    again.set_tag([e2], "Sample", "S1")  # same as automatic: nothing stored
    assert "Sample" not in again.tag_store.get(e2.path)


def test_sidecar_unwritable_folder_keeps_tags_in_memory(speeds, monkeypatch):
    store = SidecarTags()
    ws = loaded(speeds, tag_store=store)

    def fail(*_a, **_k):
        raise PermissionError("read-only")
    monkeypatch.setattr(store, "_write", fail)
    ws.set_tag(ws.entries[:1], "Condition", "x")
    assert ws.entries[0].tags["Condition"] == "x" and store.write_errors


def test_average_by_and_legacy_groups(speeds):
    ws = loaded(speeds)
    assert [g for g, _ in [(g.name, 0) for g in ws.group_data()]] == ["0.25 mm/min", "2.00 mm/min", "10.00 mm/min"]
    ws.average_by = "Folder"
    ws.regroup()
    assert {e.group for e in ws.entries} == {"2026-10-11"}
    # pre-0.4 "mark as duplicates" choices become the Condition tag when the run loads
    first = sorted(speeds.glob("*.CFT"))[0]
    ws2 = Workspace(tag_store=MemoryTags(), legacy_groups={str(first.resolve()): "Oct-8 baseline"})
    ws2.add_folder(speeds)
    assert next(e for e in ws2.entries if e.path == first).tags["Condition"] == "Oct-8 baseline"
    assert ws2.legacy_groups == {}


# ---------------------------------------------------------------- colours and styles
def test_colour_by_field_shares_colours_and_varies_markers(speeds):
    ws = loaded(speeds)
    assert len({e.color for e in ws.entries}) == 8  # every run its own colour (8 colours, then markers change)
    ws.color_by = "Condition"
    ws.palette = "viridis"
    ws.restyle()
    by = {}
    for e in ws.entries:
        by.setdefault(e.group, []).append(e)
    assert all(len({e.color for e in es}) == 1 for es in by.values())
    assert all(len({e.marker for e in es}) == len(es) for es in by.values())
    order = [by[g][0].color for g in ("0.25 mm/min", "2.00 mm/min", "10.00 mm/min")]
    assert order == palette_colors("viridis", 3)  # ordered palette follows the natural order
    assert ws.group_colors()["2.00 mm/min"] == order[1]
    ws.set_value_color("Condition", "2.00 mm/min", "#ff0000")
    assert {e.color for e in by["2.00 mm/min"]} == {"#ff0000"}


def test_run_style_overrides(speeds):
    ws = loaded(speeds)
    e = ws.entries[0]
    ws.set_style([e], color="#123456", marker="D", linestyle=":", linewidth=3.0, label="Control")
    s = next(x for x in ws.series() if x.label == "Control")
    assert (s.color, s.marker, s.linestyle, s.linewidth) == ("#123456", "D", ":", 3.0)
    ws.color_by = "Condition"
    ws.restyle()
    assert e.color == "#123456"  # your colour beats colour-by
    assert ws.run_styles[str(e.path.resolve())]["label"] == "Control"
    ws.set_style([e], color=None)
    assert e.color != "#123456" and "color" not in e.style
    ws.reset_style([e])
    assert e.style == {} and str(e.path.resolve()) not in ws.run_styles
    with pytest.raises(KeyError):
        ws.set_style([e], colour="#000000")


def test_palettes():
    assert palette_colors("default", 10)[8] == palette_colors("default", 10)[0]  # categorical repeats
    v = palette_colors("viridis", 5)
    assert len(set(v)) == 5
    assert len(palette_colors("greys", 1)) == 1


# ---------------------------------------------------------------- group means and statistics
def test_cff_mean_of_identical_runs_is_that_run(tmp_path):
    a = [loaded_one(tmp_path / f"r{i}.CFT", 1.0) for i in range(3)]
    m = G.cff_mean(a)
    assert m.n == 3 and np.nanmax(m.sd) == pytest.approx(0, abs=1e-9)
    assert np.allclose(m.mean, G._cff_at(a[0], m.x))


def loaded_one(path, shift, noise=0.0, seed=0):
    from porometry.analysis import analyze
    from porometry.cft import read_cft
    return analyze(read_cft(write_run(path, shift, noise, seed)))


def test_mean_curves_follow_the_trend(speeds):
    ws = loaded(speeds)
    gd = ws.group_data()
    mfp = [np.interp(50, *(lambda m: (m.mean[::-1], m.x[::-1]))(G.cff_mean(g.analyses))) for g in gd]
    assert mfp[0] > mfp[1] > mfp[2]  # bigger shift -> smaller pores
    for g in gd:
        wet, dry = G.flow_mean(g.analyses)
        assert wet.n == 3 and dry.mean[-1] > 0
        hist = G.psd_mean(g.analyses, binned=True, n_bins=12)
        assert hist.x.size == 13 and hist.mean.sum() == pytest.approx(
            G._cff_at(g.analyses[0], hist.x[:1])[0] - G._cff_at(g.analyses[0], hist.x[-1:])[0], abs=8)
        pts = G.psd_mean(g.analyses, "D")
        assert np.all(np.isfinite(pts.mean))


def test_no_overlap_gives_no_mean(tmp_path):
    from porometry.analysis import analyze
    from porometry.cft import read_cft
    a = analyze(read_cft(write_run(tmp_path / "a.CFT", 1.0)))
    b = analyze(read_cft(write_run(tmp_path / "b.CFT", 1.0)))
    b.diameter = b.diameter * 1000  # no common diameter range
    assert G.cff_mean([a, b]) is None


def test_compare_stats():
    from scipy import stats as st
    two = G.compare_stats({"A": [1.0, 1.1, 0.9], "B": [2.0, 2.2, 1.9]})
    assert two.test == "Welch t-test"
    assert two.p == pytest.approx(st.ttest_ind([1.0, 1.1, 0.9], [2.0, 2.2, 1.9], equal_var=False).pvalue)
    three = G.compare_stats({"A": [1, 1.1, 0.9], "B": [2, 2.2, 1.9], "C": [3, 3.1, 2.8], "D": [5.0]})
    assert three.test == "One-way ANOVA" and len(three.pairs) == 3 and "D" in three.note
    assert "p < 0.001" in three.summary() or "p = " in three.summary()
    assert G.compare_stats({"A": [1.0, 1.0], "B": [1.0, 1.0]}).p is None
    assert "at least two groups" in G.compare_stats({"A": [1.0, 2.0], "B": [1.0]}).note
    assert G.format_p(0.0004) == "< 0.001" and G.format_p(float("nan")) == "n/a"


def test_stats_frame_and_qc_exclusion(speeds):
    ws = loaded(speeds)
    bad = ws.entries[0]
    bad.qc.findings.append(type("F", (), {"level": Level.FAIL, "code": "x", "title": "t", "detail": "d"})())
    assert bad.qc.level == Level.FAIL
    gd = {g.name: g for g in ws.group_data(Level.WARN)}
    assert gd["0.25 mm/min"].n == 2 and len(gd["0.25 mm/min"].excluded) == 1
    st = ws.stats_frame(["mean_flow_d"])
    assert st.iloc[0]["Test"] == "One-way ANOVA" and len(st) == 4  # overall + 3 pairs


# ---------------------------------------------------------------- figures
@pytest.mark.parametrize("kind", ["flow", "cff", "psd", "compare", "all"])
@pytest.mark.parametrize("display", ["runs", "means", "both"])
def test_every_plot_draws(speeds, kind, display):
    ws = loaded(speeds)
    o = PlotOptions(display=display, legend="outside", psd_mode="binned" if kind == "psd" else "points")
    fig = make_figure(kind, ws.series(), o, groups=ws.group_data(), font_pt=8, size=(3.3, 2.5))
    assert fig.axes and fig.get_size_inches()[0] == pytest.approx(3.3)


def test_limits_legend_and_fonts(speeds):
    ws = loaded(speeds)
    o = PlotOptions(limits={"cff": [0.5, 20, None, 105]}, legend="none", title=False)
    ax = make_figure("cff", ws.series(), o).axes[0]
    assert ax.get_xlim() == pytest.approx((0.5, 20)) and ax.get_ylim()[1] == pytest.approx(105)
    assert ax.get_legend() is None and ax.get_title(loc="left") == ""
    ax = make_figure("flow", ws.series(), PlotOptions(), font_pt=7).axes[0]
    assert ax.xaxis.label.get_fontsize() == pytest.approx(7)
    title = make_figure("compare", ws.series(), PlotOptions(), groups=ws.group_data()).axes[0].get_title(loc="left")
    assert title.startswith("Mean flow pore by condition") and "ANOVA" in title


def test_excel_has_statistics(speeds, tmp_path):
    import openpyxl
    from porometry.export import save_figure, write_summary
    ws = loaded(speeds)
    wb = openpyxl.load_workbook(write_summary(ws, tmp_path / "s.xlsx"))
    assert "Statistics" in wb.sheetnames
    header = [c.value for c in wb["Summary"][1]]
    assert {"Condition", "Sample", "Replicate", "Folder"} <= set(header)
    p = save_figure(ws, "compare", tmp_path / "c.svg", PlotOptions(), size=(3.3, 2.5), font_pt=8)
    assert p.stat().st_size > 1000


# ---------------------------------------------------------------- sessions
def test_session_round_trip_survives_moving_the_data(speeds, tmp_path):
    from porometry import session
    ws = loaded(speeds)
    ws.color_by, ws.palette, ws.average_by = "Condition", "cividis", "Condition"
    ws.set_value_color("Condition", "10.00 mm/min", "#000000")
    ws.set_style(ws.entries[:1], label="Control", linewidth=2.5)
    ws.entries[1].visible = False
    o = PlotOptions(display="both", units="psi", limits={"cff": [1, 10, None, None]})
    f = session.save(tmp_path / "Data" / "speed series", ws, o, folders=[speeds], highlight=ws.entries[2].name,
                     tab=3, group_include_warn=False)
    assert f.suffix == ".cfpa" and json.loads(f.read_text(encoding="utf-8"))["runs"][0]["relpath"].startswith("2026")

    # move the whole Data folder (another computer / another SyncThing path)
    moved = tmp_path / "elsewhere" / "Data"
    moved.parent.mkdir()
    (tmp_path / "Data").rename(moved)
    s = session.load(moved / "speed series.cfpa")
    assert len(s.runs) == 9 and not s.missing and s.tab == 3 and not s.group_include_warn
    assert s.plot_options.display == "both" and s.plot_options.units == "psi"
    assert s.plot_options.limits == {"cff": [1, 10, None, None]}
    ws2 = Workspace(tag_store=MemoryTags())
    session.apply(s, ws2)
    assert len(ws2.entries) == 9 and sum(not e.visible for e in ws2.entries) == 1
    assert ws2.color_by == "Condition" and ws2.palette == "cividis"
    assert {e.color for e in ws2.entries if e.group == "10.00 mm/min"} == {"#000000"}
    first = next(e for e in ws2.entries if e.style.get("label") == "Control")
    assert first.style["linewidth"] == 2.5

    next(moved.rglob("*TEST3.CFT")).unlink()
    assert len(session.load(moved / "speed series.cfpa").missing) == 1


def test_session_errors(tmp_path):
    from porometry import session
    bad = tmp_path / "x.cfpa"
    bad.write_text("not json")
    with pytest.raises(session.SessionError):
        session.load(bad)
    bad.write_text(json.dumps({"runs": [], "format": 99, "version": "9.0.0"}))
    with pytest.raises(session.SessionError, match="newer version"):
        session.load(bad)
    assert RUN == "Run"


# ---------------------------------------------------------------- named groups (v0.5)
def test_named_groups_many_to_many_and_scope(speeds):
    from porometry.workspace import GROUPS
    ws = loaded(speeds, tag_store=SidecarTags())
    slow = [e for e in ws.entries if e.group == "0.25 mm/min"]
    second = [e for e in ws.entries if e.tags["Replicate"] == "2"]
    ws.add_to_group(slow, "S1 replicates")
    ws.add_to_group(second, "Speed series")
    both = next(e for e in slow if e in second)
    assert both.groups == ["S1 replicates", "Speed series"]  # one run, two groups
    assert ws.group_names() == ["S1 replicates", "Speed series"]
    assert GROUPS not in ws.fields
    csv_text = (speeds / SIDECAR).read_text(encoding="utf-8-sig")
    assert "Groups" in csv_text.splitlines()[0] and "S1 replicates; Speed series" in csv_text

    ws.active_group = "Speed series"
    assert {e.name for e in ws.scope()} == {e.name for e in second}
    assert len(ws.series()) == 3 and len(ws.summary_frame()) == 3
    assert [g.name for g in ws.group_data()] == ["0.25 mm/min", "2.00 mm/min", "10.00 mm/min"]
    assert all(g.n == 1 for g in ws.group_data())

    # survives a reload from run_tags.csv
    again = loaded(speeds, tag_store=SidecarTags())
    assert again.group_names() == ["S1 replicates", "Speed series"] and GROUPS not in again.fields

    ws.rename_group("Speed series", "Speeds")
    assert ws.active_group == "Speeds" and both.groups == ["S1 replicates", "Speeds"]
    ws.remove_from_group(second, "Speeds")
    assert ws.active_group is None and "Speeds" not in ws.group_names()
    ws.delete_group("S1 replicates")
    assert ws.group_names() == [] and both.groups == []
    with pytest.raises(ValueError):
        ws.add_to_group(slow, "  ")


def test_average_by_run_and_group_views(speeds):
    from porometry.workspace import RUN
    ws = loaded(speeds)
    ws.add_to_group(ws.entries[:3], "Reps")
    ws.average_by, ws.color_by = "Condition", "Condition"
    v = ws.activate_group("Reps", {"display": "means"})  # first visit: nothing remembered yet
    assert v == {} and ws.group_views[""]["display"] == "means"
    ws.average_by, ws.color_by = RUN, "Replicate"
    ws.regroup()
    assert [e.group for e in ws.scope()] == [e.name for e in ws.entries[:3]]
    gc = ws.group_colors()
    assert all(gc[e.name] == e.color for e in ws.scope())  # compare chart colours = run colours
    assert ws.stats_frame(["mean_flow_d"]).iloc[0]["Test"] == "none"  # one run per 'group': no test
    ws.activate_group(None, {"display": "runs"})
    assert (ws.average_by, ws.color_by) == ("Condition", "Condition")  # all runs' view comes back
    back = ws.activate_group("Reps")
    assert (ws.average_by, ws.color_by, back["display"]) == (RUN, "Replicate", "runs")


def test_session_keeps_active_group(speeds, tmp_path):
    from porometry import session
    ws = loaded(speeds)
    ws.add_to_group(ws.entries[:2], "Pair")
    ws.activate_group("Pair", {"display": "both"})
    f = session.save(tmp_path / "s.cfpa", ws, PlotOptions())
    ws2 = Workspace(tag_store=ws.tag_store)  # same tags (memory store here; run_tags.csv in real use)
    session.apply(session.load(f), ws2)
    assert ws2.active_group == "Pair" and len(ws2.scope()) == 2 and "" in ws2.group_views
