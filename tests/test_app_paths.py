"""Settings files: app folder by default, a chosen settings folder, and the one-time copy from Qt's old store."""

import json
from pathlib import Path

import pytest
from PyQt6.QtCore import QByteArray, QSettings

from porometry import app_paths

_APP = None  # keep the QApplication alive for the dialog test


@pytest.fixture
def folders(tmp_path, monkeypatch):
    app, data = tmp_path / "app", tmp_path / "data"
    app.mkdir()
    monkeypatch.delenv(app_paths.SETTINGS_ENV, raising=False)
    monkeypatch.delenv("UAKRON_SETTINGS_DIR", raising=False)
    monkeypatch.setattr(app_paths, "app_dir", lambda: str(app))
    monkeypatch.setattr(app_paths, "data_dir", lambda: str(data))
    old_file = str(tmp_path / "old_store.ini")  # stands in for the plist / registry
    old = QSettings(old_file, QSettings.Format.IniFormat)
    monkeypatch.setattr(app_paths, "_native_store", lambda: QSettings(old_file, QSettings.Format.IniFormat))
    return app, data, old


def test_default_is_the_app_folder(folders):
    app, _, _ = folders
    shared, local = app_paths.open_settings()
    shared.setValue("qc", "{}")
    local.setValue("last_dir", "/x")
    shared.sync(); local.sync()
    assert (app / app_paths.SETTINGS_FILE).exists()
    assert (app / app_paths.LOCAL_FILE).exists()


def test_old_store_is_split_into_shared_and_local(folders):
    app, _, old = folders
    old.setValue("analysis_v2", '{"shape_factor": 0.8}')
    old.setValue("recent_folders", '["C:/data"]')
    old.setValue("geometry", QByteArray(b"\x01\x02"))
    old.sync()
    shared, local = app_paths.open_settings()
    assert shared.value("analysis_v2") == '{"shape_factor": 0.8}'
    assert shared.value("recent_folders") is None
    assert local.value("recent_folders") == '["C:/data"]'
    assert local.value("geometry") == QByteArray(b"\x01\x02")
    assert local.value("analysis_v2") is None
    assert old.value("analysis_v2") == '{"shape_factor": 0.8}'  # the old store is left as it was


def test_settings_folder_pointer(folders):
    app, data, old = folders
    (app / "settings_location.json").write_text(json.dumps({"settings_dir": "Settings"}))
    old.setValue("qc", "{}")
    old.sync()
    shared, local = app_paths.open_settings()
    assert app_paths.settings_dir() == str(data / "Settings")
    assert shared.fileName().endswith(app_paths.SETTINGS_FILE)
    assert (data / "Settings" / app_paths.SETTINGS_FILE).exists()
    assert Path(local.fileName()) == app / app_paths.LOCAL_FILE  # per-computer state stays put (Qt uses / on Windows)


def test_synced_settings_are_not_overwritten(folders):
    app, data, old = folders
    (app / "settings_location.json").write_text(json.dumps({"settings_dir": "Settings"}))
    (data / "Settings").mkdir(parents=True)
    synced = QSettings(str(data / "Settings" / app_paths.SETTINGS_FILE), QSettings.Format.IniFormat)
    synced.setValue("qc", "from the other computer")
    synced.sync()
    old.setValue("qc", "from this computer's old store")
    old.sync()
    shared, _ = app_paths.open_settings()
    assert shared.value("qc") == "from the other computer"


def test_env_file_holds_everything(tmp_path, monkeypatch):
    monkeypatch.setenv(app_paths.SETTINGS_ENV, str(tmp_path / "one.ini"))
    shared, local = app_paths.open_settings()
    assert shared is local


def test_settings_dialog_folder_box_moves_settings(folders, monkeypatch):
    """Settings > Settings Folder: copies the settings file to the new folder and asks to restart."""
    from PyQt6.QtWidgets import QApplication, QFileDialog, QGroupBox, QMessageBox, QPushButton

    from porometry.analysis import Settings
    from porometry.gui import settings_dialog
    from porometry.qc import QCSettings

    global _APP
    _APP = QApplication.instance() or QApplication([])
    app, data, _ = folders
    shared, _ = app_paths.open_settings()
    shared.setValue("qc", "mine")
    target = data / "Settings"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(target))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    d = settings_dialog.SettingsDialog(Settings(), QCSettings(), True, save_prefs=shared.sync)
    box = next(b for b in d.findChildren(QGroupBox) if b.title() == "Settings Folder")
    next(b for b in box.findChildren(QPushButton) if b.text() == "Change...").click()
    assert (target / app_paths.SETTINGS_FILE).exists()
    assert json.loads((app / "settings_location.json").read_text()) == {"settings_dir": "Settings"}
    assert app_paths.settings_dir() == str(target)
    assert d.restart_requested
