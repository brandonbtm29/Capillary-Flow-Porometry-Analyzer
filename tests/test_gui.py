"""Headless smoke test of the main window (runs with QT_QPA_PLATFORM=offscreen)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from _data import DATA, EXPECTED, needs_data  # noqa: E402

pytestmark = needs_data


@pytest.fixture(scope="module")
def app():
    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield a


@pytest.fixture
def win(app):
    from porometry.gui.main_window import MainWindow
    w = MainWindow()  # settings go to a temporary file and tags stay in memory (tests/conftest.py)
    w.show()
    yield w
    w.close()


def test_load_select_and_switch_options(win, tmp_path):
    win.load_paths([str(DATA)])
    assert len(win.ws.entries) == 10
    assert win.tree.topLevelItemCount() == 6  # 4 conditions + lastdata2 + practice run
    assert win.run_model.rowCount() == 10
    # select a run -> highlight + details
    win._select("CFP-0_25MM_MIN_TEST1")
    assert "Mean flow pore" in win.details.toPlainText()
    assert f"{EXPECTED['good_run']['mean_flow_um']:.3f}" in win.details.toPlainText()
    # unit toggle updates the table header
    o = win.options
    o.units.setCurrentIndex(o.units.findData("psi"))
    assert "Bubble point (psi)" in list(win.run_model.frame.columns)
    o.units.setCurrentIndex(o.units.findData("kPa"))
    # histogram mode enables bins
    o.psd_mode.setCurrentIndex(2)
    assert o.bins.isEnabled()
    # group means and the compare chart draw on real data
    o.display.setCurrentIndex(o.display.findData("both"))
    o.average_by.setCurrentIndex(o.average_by.findData("Condition"))
    assert "0.25 mm/min" in [win.tree.topLevelItem(i).text(0) for i in range(win.tree.topLevelItemCount())]
    # hide fails -> only the warn run is visible
    win._set_visible(lambda e: e.qc.level < 3)
    assert [e.name for e in win.ws.entries if e.visible] == ["CFP-0_25MM_MIN_TEST1"]


def test_mark_duplicates_and_exports(win, tmp_path):
    from porometry.export import save_figure, write_summary
    win.load_paths([str(DATA)])
    a = win._entry("CFP-0_25MM_MIN_TEST1")
    b = win._entry("lastdata2_2026-10-08")
    win.ws.set_group([a, b], "baseline")
    win._refresh_all()
    groups = win.group_model.frame
    assert "baseline" in set(groups["Group"])
    out = write_summary(win.ws, tmp_path / "s.xlsx", group_max_level=2)
    assert out.exists()
    for kind in ("flow", "cff", "psd"):
        win.plot_tabs.setCurrentIndex(["flow", "cff", "psd"].index(kind))
        p = save_figure(win.ws, kind, tmp_path / f"{kind}.svg", win.plot_opts)
        assert p.stat().st_size > 1000


def test_screenshot(win, tmp_path):
    """Not an assertion test: saves a screenshot for a visual check."""
    win.resize(1500, 950)
    win.load_paths([str(DATA)])
    win._set_visible(lambda e: e.name.startswith("CFP-0_25"))
    win._select("CFP-0_25MM_MIN_TEST1")
    QtWidgets.QApplication.processEvents()
    out = os.environ.get("POROMETRY_SCREENSHOT")
    if out:
        win.grab().save(out)
