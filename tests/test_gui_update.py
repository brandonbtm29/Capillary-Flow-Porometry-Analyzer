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
    assert "Can't update automatically" in d.status.text() and "release page" in d.status.text()
    assert d.page_btn.isVisibleTo(d) and not d.cancel_btn.isVisibleTo(d)
    assert d.auto.isChecked()


def _wait(app, worker, until):
    worker.wait(10000)
    for _ in range(100):  # deliver the queued signal
        app.processEvents()
        if until():
            return


@pytest.mark.parametrize("error, hint", [("No releases have been published on GitHub yet.", False),
                                         ("Could not reach GitHub. OSError: offline", True)])
def test_dialog_explains_check_problems(app, error, hint):
    from porometry.gui.update_dialog import UpdateDialog
    d = UpdateDialog(None, True, check=lambda: UpdateInfo("0.2.0", error=error))
    _wait(app, d._worker, lambda: d.info is not None)
    text = d.notes.toPlainText()
    assert text.startswith(error) and ("internet connection" in text) == hint
    assert not d.update_btn.isVisibleTo(d)


def test_dialog_updates_to_the_release_tag(app, monkeypatch, tmp_path):
    from porometry.gui.update_dialog import UpdateDialog
    calls = []

    def fake_update(repo, tag, log, cancel):
        calls.append((repo, tag))
        log("Downloading from GitHub…")
        return "0.3.0"
    monkeypatch.setattr(updater, "apply_update", fake_update)
    d = UpdateDialog(NEWER, True, repo=tmp_path)
    d.run_update()
    assert d.cancel_btn.isVisibleTo(d) and not d.update_btn.isEnabled()
    _wait(app, d._worker, lambda: d.restart)
    assert calls == [(tmp_path, "v0.3.0")]
    assert d.restart and d.updated_to == "0.3.0" and not d.cancel_btn.isVisibleTo(d)


def test_dialog_cancel_stops_the_update(app, monkeypatch, tmp_path):
    from porometry.gui.update_dialog import UpdateDialog

    def slow_update(repo, tag, log, cancel):
        assert cancel.wait(10)
        raise updater.UpdateCancelled("The update was cancelled, so the app was left on the old version.")
    monkeypatch.setattr(updater, "apply_update", slow_update)
    d = UpdateDialog(NEWER, True, repo=tmp_path)
    d.run_update()
    d.cancel_btn.click()
    assert "Cancelling" in d.cancel_btn.text() and not d.cancel_btn.isEnabled()
    _wait(app, d._worker, lambda: not d.cancel_btn.isVisibleTo(d))
    assert "left on the old version" in d.status.text() and "failed" not in d.status.text()
    assert not d.restart and not d.cancel_btn.isVisibleTo(d)


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


def test_restart_releases_the_lock_first(app, monkeypatch):
    from porometry.gui import main_window
    w = main_window.MainWindow()
    events = []

    class FakeProcess:
        ok = True

        @staticmethod
        def startDetached(exe, args):
            events.append(("start", args[:2]))
            return FakeProcess.ok, 0
    monkeypatch.setattr(main_window, "QProcess", FakeProcess)
    monkeypatch.setattr(main_window.single_instance, "release", lambda: events.append("release"))
    monkeypatch.setattr(main_window.single_instance, "acquire", lambda name: events.append(("acquire", name)))
    shown = []
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda *a: shown.append(a[2]))
    try:
        w.restart_app()
        assert events == ["release", ("start", ["-m", "porometry"])]
        events.clear()
        FakeProcess.ok = False  # couldn't start: keep running, take the lock back, say what to do
        w.restart_app()
        assert events == ["release", ("start", ["-m", "porometry"]), ("acquire", "Capillary Flow Porometry Analyzer")]
        assert shown == ["Couldn't restart automatically. Close the app and start it again."]
    finally:
        w.qs.clear()
        w.qs.sync()
        w.close()


def test_settings_app_buttons_reach_the_main_window(app, monkeypatch):
    from porometry.gui import main_window

    class FakeSettings:
        def __init__(self, *a, loaded_runs=None, **kw):
            assert loaded_runs == 0
            self.restart_requested, self.restart_app_requested, self.updates_requested = False, *flags

        def exec(self):
            return 0
    w = main_window.MainWindow()
    calls = []
    monkeypatch.setattr(main_window, "SettingsDialog", FakeSettings)
    monkeypatch.setattr(w, "_restart", lambda *a, **kw: calls.append(("restart", a, kw)))
    monkeypatch.setattr(w, "show_updates", lambda: calls.append("updates"))
    try:
        flags = (True, False)
        w.open_settings()
        flags = (False, True)
        w.open_settings()
        assert calls == [("restart", (None,), {"note": ""}), "updates"]
    finally:
        w.qs.clear()
        w.qs.sync()
        w.close()


def _settings_dialog(**kw):
    from porometry.analysis import Settings
    from porometry.gui import settings_dialog
    from porometry.qc import QCSettings
    return settings_dialog.SettingsDialog(Settings(), QCSettings(), True, **kw)


def test_settings_app_box_restart_and_updates(app):
    d = _settings_dialog()
    d.restart_btn.click()
    assert d.restart_app_requested and d.result() == 1 and not d.restart_requested  # keeps the fields
    d = _settings_dialog()
    d.updates_btn.click()
    assert d.updates_requested and d.result() == 1


def test_settings_copy_diagnostics(app):
    d = _settings_dialog(loaded_runs=3)
    assert d.log_btn.text() == "Open Log Folder" and d.diag_btn.text() == "Copy Diagnostics"
    QtWidgets.QApplication.clipboard().clear()
    d.diag_btn.click()
    text = QtWidgets.QApplication.clipboard().text()
    assert text.startswith(f"Capillary Flow Porometry Analyzer {__version__}")
    assert "Loaded runs: 3" in text and "Settings folder:" in text and "Log file:" in text
    assert d.app_status.text().startswith("Diagnostics copied.")


def test_settings_open_log_folder(app, monkeypatch, tmp_path):
    from porometry import crash_log, diagnostics
    from porometry.gui import settings_dialog
    opened, warned = [], []
    monkeypatch.setattr(crash_log, "log_path", lambda: str(tmp_path / "logs" / "porometry.log"))
    monkeypatch.setattr(diagnostics, "open_folder", opened.append)
    monkeypatch.setattr(settings_dialog.QMessageBox, "warning", lambda *a: warned.append(a[2]))
    d = _settings_dialog()
    d.log_btn.click()
    assert opened == [str(tmp_path / "logs")] and not warned

    def broken(path):
        raise OSError("no file manager")
    monkeypatch.setattr(diagnostics, "open_folder", broken)
    d.log_btn.click()
    assert warned and "no file manager" in warned[0]


def test_second_copy_quits_without_a_window(app, monkeypatch):
    """main(): when another copy holds the lock, it was asked to come forward and this one ends."""
    from porometry import crash_log, single_instance
    from porometry.gui import app as app_module
    from porometry.gui import main_window
    monkeypatch.setattr(crash_log, "setup", lambda *a, **kw: None)  # don't write the real log file
    monkeypatch.setattr(QtWidgets, "QApplication", lambda argv: app)
    monkeypatch.setattr(single_instance, "acquire", lambda name: None)
    monkeypatch.setattr(main_window, "MainWindow", lambda **kw: pytest.fail("no window when another copy runs"))
    name, org = app.applicationName(), app.organizationName()
    try:
        assert app_module.main(["porometry", "some-folder"]) == 0
    finally:
        app.setApplicationName(name)
        app.setOrganizationName(org)


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
