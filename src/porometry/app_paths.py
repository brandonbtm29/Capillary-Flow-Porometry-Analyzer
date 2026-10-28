"""Where the app keeps its settings files.

* ``porometry_settings.ini``: analysis and QC settings, plot options, views, colours, export choices,
  update checks. Lives in the **settings folder**: the app folder by default, or a folder chosen in
  *Settings > Settings Folder* (e.g. inside SyncThing, so the PC and the Mac share them). That choice is
  stored in ``settings_location.json`` in the app folder; ``UAKRON_SETTINGS_DIR`` overrides it
  (see ``settings_location.py``, the same copy as in the other UAkron apps).
* ``porometry_local.ini``: things that only make sense on this computer (window size and layout, last
  folder, recent folders and sessions). Always in the app folder.

Both files are gitignored. Before 0.6.0 everything lived in Qt's own store (the registry on Windows, a
plist on macOS); :func:`open_settings` copies it over once and leaves the old store as it was.
``POROMETRY_SETTINGS_FILE`` puts everything in that one file instead (the tests use it).
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QSettings

from . import settings_location, updater

SETTINGS_FILE = "porometry_settings.ini"
LOCAL_FILE = "porometry_local.ini"
SETTINGS_ENV = "POROMETRY_SETTINGS_FILE"
DATA_FOLDER = "Capillary Flow Porometer"  # this app's folder in the UAkron data root (SyncThing)
LOCAL_KEYS = frozenset({"geometry", "window_state_v2", "last_dir", "recent_folders", "recent_sessions"})
NATIVE = ("PorometryAnalyzer", "PorometryAnalyzer")  # organisation, application of the pre-0.6 store


def app_dir() -> str:
    """The app's own folder: the git clone it runs from (or the .exe's folder in a frozen build)."""
    root = updater.repo_root()
    if root is None:  # a plain pip install: keep the files out of site-packages
        root = Path.home() / ".porometry-analyzer"
        root.mkdir(exist_ok=True)
    return settings_location.app_folder(str(root))


def data_dir() -> str:
    """This app's data folder; a relative settings folder (e.g. "Settings") is placed inside it."""
    base = os.environ.get("UAKRON_DATA_DIR") or os.path.join(os.path.expanduser("~"), "SyncThing", "UAkron Playground")
    return os.path.join(base, DATA_FOLDER)


def settings_dir() -> str:
    """Folder holding ``porometry_settings.ini`` (created if missing)."""
    return settings_location.resolve(app_dir(), data_dir())


def current_settings_dir() -> str:
    """Where the shared settings are right now (the folder of ``POROMETRY_SETTINGS_FILE`` when it is set)."""
    test_file = os.environ.get(SETTINGS_ENV)
    return os.path.dirname(os.path.abspath(test_file)) if test_file else settings_dir()


def _native_store() -> QSettings:
    s = QSettings(*NATIVE)
    s.setFallbacksEnabled(False)  # macOS would otherwise add system-wide keys (trackpad, locale, ...)
    return s


def _copy_native(path: str, local: bool) -> None:
    """Fill a new settings file with the matching keys from the pre-0.6 store, if it has any."""
    native = _native_store()
    keys = [k for k in native.allKeys() if (k in LOCAL_KEYS) == local]
    if not keys:
        return
    out = QSettings(path, QSettings.Format.IniFormat)
    for k in keys:
        out.setValue(k, native.value(k))
    out.sync()


def open_settings() -> tuple[QSettings, QSettings]:
    """(shared, local) settings. Missing files start from the pre-0.6 store, if there is one."""
    test_file = os.environ.get(SETTINGS_ENV)
    if test_file:
        qs = QSettings(test_file, QSettings.Format.IniFormat)
        return qs, qs
    shared = os.path.join(settings_dir(), SETTINGS_FILE)
    local = os.path.join(app_dir(), LOCAL_FILE)
    # A shared file that already exists (e.g. synced from another computer) is never overwritten.
    if not os.path.exists(shared):
        _copy_native(shared, local=False)
    if not os.path.exists(local):
        _copy_native(local, local=True)
    return QSettings(shared, QSettings.Format.IniFormat), QSettings(local, QSettings.Format.IniFormat)


def folder_box(save_cb=None, restart_cb=None, parent=None):
    """The shared "Settings Folder" box, or a note when ``POROMETRY_SETTINGS_FILE`` is in charge."""
    test_file = os.environ.get(SETTINGS_ENV)
    if test_file:
        from PyQt6.QtWidgets import QGroupBox, QLabel, QVBoxLayout

        box = QGroupBox("Settings Folder", parent)
        label = QLabel(f"All settings are in {test_file} (set by {SETTINGS_ENV}).")
        label.setWordWrap(True)
        QVBoxLayout(box).addWidget(label)
        return box
    return settings_location.settings_folder_box(app_dir(), data_dir(), [SETTINGS_FILE], save_cb, restart_cb, parent)
