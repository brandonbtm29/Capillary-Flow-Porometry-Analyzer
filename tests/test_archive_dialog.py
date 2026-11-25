"""The Archive and Archived runs dialogs on their own (test_gui_archive.py drives them through the window)."""

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from _synth import write_run  # noqa: E402

from porometry.archive import archive_file, list_archived  # noqa: E402

_APP = None


@pytest.fixture(autouse=True)
def app():
    global _APP
    _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # keep it alive
    return _APP


def _entry(name, status="pass", summary=""):
    return SimpleNamespace(name=name, qc=SimpleNamespace(status=status, summary=lambda: summary))


def _button(dlg, text):
    return next(b for b in dlg.findChildren(QtWidgets.QPushButton) if b.text() == text)


def _labels(dlg):
    return " ".join(lb.text() for lb in dlg.findChildren(QtWidgets.QLabel))


def test_archive_dialog_fills_in_the_qc_fail(app):
    from porometry.gui.archive_dialog import ArchiveDialog
    dlg = ArchiveDialog([_entry("CFP-<b>1</b>", "fail", "Leak: wet flow above dry flow")])
    assert dlg.reason.text() == "QC fail: Leak: wet flow above dry flow"
    assert "CFP-&lt;b&gt;1&lt;/b&gt;" in _labels(dlg)  # names are shown as text, not markup
    assert "Move 1 run file(s)" in _labels(dlg)
    dlg.reason.setText("  torn sample  ")
    assert dlg.value() == "torn sample"
    _button(dlg, "Archive").click()
    assert dlg.result() == QtWidgets.QDialog.DialogCode.Accepted


def test_archive_dialog_several_runs_starts_blank(app):
    from porometry.gui.archive_dialog import ArchiveDialog
    dlg = ArchiveDialog([_entry("A", "fail", "Leak"), _entry("B")])
    assert dlg.value() == ""
    assert "Move 2 run file(s)" in _labels(dlg)
    dlg.reject()
    assert dlg.result() == QtWidgets.QDialog.DialogCode.Rejected


def test_archive_dialog_with_real_runs(app, speeds):
    from porometry import Workspace
    from porometry.gui.archive_dialog import ArchiveDialog
    ws = Workspace()
    ws.add_files(sorted(speeds.glob("*.CFT"))[:2])
    dlg = ArchiveDialog(ws.entries)
    for e in ws.entries:
        assert e.name in _labels(dlg) and f"QC: {e.qc.status}" in _labels(dlg)


def test_archived_runs_dialog_lists_and_restores(app, tmp_path):
    from porometry.gui.archive_dialog import ArchivedRunsDialog
    day = tmp_path / "Data"
    keep = write_run(day / "CFP-0_25MM_MIN_S1T1.CFT")
    gone = archive_file(write_run(day / "CFP-0_70MM_MIN_S1T1.CFT"), reason="torn sample", qc="fail")
    runs = list_archived([day])
    assert [r.path for r in runs] == [gone]

    dlg = ArchivedRunsDialog(runs, [day])
    t = dlg.table
    assert t.rowCount() == 1
    assert t.item(0, 0).text() == "CFP-0_70MM_MIN_S1T1" and t.item(0, 0).toolTip() == str(gone)
    assert "T" not in t.item(0, 1).text() and t.item(0, 1).text()[:4].isdigit()  # "2026-11-25 10:00:00"
    assert (t.item(0, 2).text(), t.item(0, 3).text()) == ("fail", "torn sample")
    assert str(day) in _labels(dlg)
    assert dlg.restore_btn.isEnabled()

    dlg.restore_btn.click()  # nothing selected: stays open, restores nothing
    assert dlg.restore_paths == [] and dlg.result() != QtWidgets.QDialog.DialogCode.Accepted
    t.selectRow(0)
    dlg.restore_btn.click()
    assert dlg.restore_paths == [gone]
    assert dlg.result() == QtWidgets.QDialog.DialogCode.Accepted
    assert keep.exists()  # the dialog only picks runs; the window does the restoring


def test_archived_runs_dialog_when_there_are_none(app):
    from porometry.gui.archive_dialog import ArchivedRunsDialog
    dlg = ArchivedRunsDialog([], [])
    assert dlg.table.rowCount() == 0
    assert not dlg.restore_btn.isEnabled()
    text = _labels(dlg)
    assert "No archived runs here." in text and "no folders opened yet" in text
