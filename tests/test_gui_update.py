"""Update dialog and the main window's update hooks (headless, no network)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from porometry import __version__, updater  # noqa: E402
from porometry.updater import UpdateInfo  # noqa: E402

_APP = None


@pytest.fixture
def app(tmp_path):
    global _APP
    from PyQt6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return _APP


NEWER = UpdateInfo("0.2.0", "0.3.0", "## 0.3.0 - 2026-10-20\n\n### Added\n- **Update button**")


def test_dialog_shows_notes_and_update_button(app, tmp_path):
    from porometry.gui.update_dialog import UpdateDialog
    d = UpdateDialog(NEWER, True, repo=tmp_path)  # tmp_path is no git clone -> can't update
    assert "0.3.0 is available" in d.headline.text()
    assert "Update button" in d.notes.toPlainText()
    assert d.update_btn.isVisibleTo(d) and not d.update_btn.isEnabled()
    assert "Can't update automatically" in d.status.text()
    assert d.auto.isChecked()


def test_dialog_up_to_date(app):
    from porometry.gui.update_dialog import UpdateDialog
    d = UpdateDialog(UpdateInfo("0.3.0", "0.3.0"), False)
    assert "up to date" in d.headline.text() and not d.update_btn.isVisibleTo(d)


def test_dialog_checks_in_background(app):
    from porometry.gui.update_dialog import UpdateDialog
    d = UpdateDialog(None, True, check=lambda: NEWER)
    assert "Checking" in d.headline.text()
    d._worker.wait(5000)
    for _ in range(50):  # deliver the queued signal
        app.processEvents()
        if d.info is not None:
            break
    assert d.info is NEWER and "available" in d.headline.text()


def test_main_window_update_hooks(app, monkeypatch):
    from porometry.gui import main_window
    w = main_window.MainWindow()  # check_updates=False: no network in tests
    try:
        w._background_checked(UpdateInfo(__version__, "99.0.0", "notes"))
        assert "99.0.0 available" in w.version_label.text()
        w._background_checked(UpdateInfo(__version__, error="offline"))  # ignored
        assert "99.0.0" in w.version_label.text()

        class FakeDialog:
            def __init__(self, info, auto, parent):
                assert info.latest == "99.0.0"
                self.auto = QtWidgets.QCheckBox()
                self.auto.setChecked(False)
                self.info, self.restart, self.updated_to = info, True, "99.0.0"

            def exec(self):
                return 1
        restarted = []
        monkeypatch.setattr(main_window, "UpdateDialog", FakeDialog)
        monkeypatch.setattr(w, "_restart", restarted.append)
        w.show_updates()
        assert restarted == ["99.0.0"] and not w._auto_update_check()
        assert w._restart_args() == []
    finally:
        w.qs.clear()
        w.qs.sync()
        w.close()


def test_repo_root_of_this_checkout():
    root = updater.repo_root()
    assert root is None or (root / "pyproject.toml").exists()


def test_settings_create_app_icon_button(app, monkeypatch, tmp_path):
    from porometry import shortcuts
    from porometry.analysis import Settings
    from porometry.gui import settings_dialog
    from porometry.qc import QCSettings
    made, shown = [tmp_path / "icon.lnk"], []
    monkeypatch.setattr(shortcuts, "create", lambda: made)
    monkeypatch.setattr(settings_dialog.QMessageBox, "information", lambda *a: shown.append(a[2]))
    d = settings_dialog.SettingsDialog(Settings(), QCSettings(), True)
    d.icon_btn.click()
    assert shown and "icon.lnk" in shown[0]
