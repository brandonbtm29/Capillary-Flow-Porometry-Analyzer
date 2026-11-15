"""The data folder: the app's own SyncThing folder, or the old shared one until that arrives."""

import pytest

from porometry import app_paths


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv("UAKRON_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


def test_uses_its_own_syncthing_folder(home):
    new = home / "SyncThing" / "Capillary Flow Porometer"
    new.mkdir(parents=True)
    (home / "SyncThing" / "UAkron Playground" / "Capillary Flow Porometer").mkdir(parents=True)
    assert app_paths.data_dir() == str(new)


def test_keeps_the_old_shared_folder_until_the_new_one_arrives(home):
    old = home / "SyncThing" / "UAkron Playground" / "Capillary Flow Porometer"
    old.mkdir(parents=True)
    assert app_paths.data_dir() == str(old)


def test_a_new_computer_gets_the_new_folder(home):
    assert app_paths.data_dir() == str(home / "SyncThing" / "Capillary Flow Porometer")
