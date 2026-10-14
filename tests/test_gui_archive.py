"""Archive / restore through the main window, on made-up .CFT files (no lab data needed)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from test_synthetic import write_cft  # noqa: E402

_APP = None


@pytest.fixture
def win(tmp_path, monkeypatch):
    from PyQt6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    global _APP
    _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # keep it alive
    from porometry.gui import main_window
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *a, **k: None)
    w = main_window.MainWindow()
    w.qs.clear()
    yield w, main_window
    w.close()
    w.qs.clear()
    w.qs.sync()


def test_archive_and_restore_from_the_window(win, tmp_path, monkeypatch):
    w, mw = win
    day = tmp_path / "Data" / "2026-10-11"
    day.mkdir(parents=True)
    write_cft(day / "CFP-0_25MM_MIN_T1.CFT")
    write_cft(day / "CFP-0_70MM_MIN_T1.CFT")
    w.load_paths([str(tmp_path / "Data")])
    assert len(w.ws.entries) == 2
    assert "Capillary Flow Porometry Analyzer" in w.windowTitle()

    class FakeArchiveDialog:
        def __init__(self, entries, parent=None):
            self.entries = entries

        def exec(self):
            return True

        def value(self):
            return "torn sample"

    monkeypatch.setattr(mw, "ArchiveDialog", FakeArchiveDialog)
    w._select("CFP-0_25MM_MIN_T1")
    w.archive_selected()
    assert [e.name for e in w.ws.entries] == ["CFP-0_70MM_MIN_T1"]
    assert (day / "Archive" / "CFP-0_25MM_MIN_T1.CFT").exists()

    class FakeArchivedRuns:
        def __init__(self, runs, folders, parent=None):
            assert [r.reason for r in runs] == ["torn sample"]
            self.restore_paths = [r.path for r in runs]

        def exec(self):
            return True

    monkeypatch.setattr(mw, "ArchivedRunsDialog", FakeArchivedRuns)
    w.show_archived()
    assert sorted(e.name for e in w.ws.entries) == ["CFP-0_25MM_MIN_T1", "CFP-0_70MM_MIN_T1"]
    assert (day / "CFP-0_25MM_MIN_T1.CFT").exists()
