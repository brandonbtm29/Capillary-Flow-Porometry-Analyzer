"""App icon / shortcut creation. Nothing here touches the real Desktop, Start menu or Applications."""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from porometry import shortcuts


def test_mac_bundle(tmp_path):
    py = Path("/Users/me/.venvs/porometry-analyzer/bin/python")
    wd = Path("/Users/me/GitHub Projects/UAkron/Capillary-Flow-Porometry-Analyzer")
    app = shortcuts.mac_bundle(tmp_path, python=py, workdir=wd)
    assert app.name == "Capillary Flow Porometry Analyzer.app"
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == shortcuts.BUNDLE_ID and info["CFBundleExecutable"] == "launcher"
    launcher = app / "Contents" / "MacOS" / "launcher"
    text = launcher.read_text()
    assert text.startswith("#!/bin/bash") and f'exec "{py}" -m porometry' in text and f'cd "{wd}"' in text
    if os.name != "nt":
        assert os.access(launcher, os.X_OK)
    from PIL import Image
    with Image.open(app / "Contents" / "Resources" / "porometry.icns") as im:
        assert im.format == "ICNS" and im.size == (1024, 1024)
    shortcuts.mac_bundle(tmp_path, python=py)  # remaking our own bundle is fine


def test_mac_bundle_never_replaces_someone_elses_app(tmp_path):
    app = tmp_path / f"{shortcuts.APP_NAME}.app" / "Contents"
    app.mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.example.other"}))
    with pytest.raises(shortcuts.ShortcutError):
        shortcuts.mac_bundle(tmp_path)
    assert (app / "Info.plist").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux .desktop entry")
def test_create_on_linux(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(sys, "prefix", str(tmp_path))  # marker goes here, not into the real venv
    made = shortcuts.create()
    assert made[0].name == "capillary-flow-porometry-analyzer.desktop"
    assert "-m porometry" in made[0].read_text()
    assert (tmp_path / shortcuts.MARKER).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows .lnk")
def test_windows_shortcut_has_icon_and_taskbar_id(tmp_path):
    (tmp_path / "Porometry Analyzer.lnk").write_bytes(b"")  # pre-rename shortcut gets removed
    made = shortcuts._windows([tmp_path])
    lnk = tmp_path / f"{shortcuts.APP_NAME}.lnk"
    assert made == [lnk] and lnk.exists() and not (tmp_path / "Porometry Analyzer.lnk").exists()
    ps = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}'); "
          "$s.TargetPath; $s.Arguments; $s.IconLocation; "
          f"(New-Object -ComObject Shell.Application).NameSpace('{tmp_path}').ParseName('{lnk.name}')"
          ".ExtendedProperty('System.AppUserModel.ID')")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
    target, args, icon, app_id = out.strip().splitlines()[:4]
    assert target.lower().endswith("pythonw.exe") and args == "-m porometry"
    assert icon.lower().endswith("porometry.ico,0") and app_id == shortcuts.APP_ID


def test_where_mentions_a_place():
    assert shortcuts.where()
