"""Keep the test suite away from your real data and app settings.

- App settings go to a temporary file (not the registry / ~/.config / the macOS plist).
- Run tags stay in memory, so tests never write run_tags.csv into the lab data folders.
  Tests that check the run_tags.csv file itself pass SidecarTags() explicitly, in a temporary folder.
"""

import os

import pytest

os.environ["POROMETRY_TAGS"] = "memory"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("POROMETRY_SETTINGS_FILE", str(tmp_path / "app_settings.ini"))
    monkeypatch.setenv("POROMETRY_TAGS", "memory")



@pytest.fixture
def speeds(tmp_path):
    """3 speeds x 3 replicates of made-up runs in Data/2026-10-11 (see _synth.py)."""
    from _synth import make_speeds
    return make_speeds(tmp_path)
