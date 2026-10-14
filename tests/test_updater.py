"""Update check and self-update (no network: GitHub is faked, the 'remote' is a local git repo)."""

import json
import shutil
import subprocess

import pytest

from porometry import updater

CHANGELOG = """# Changelog

Intro text.

## 0.4.0 - 2026-11-01

### Added
- Something new.

## 0.3.0 - 2026-10-20

### Fixed
- A bug.

## 0.2.0 - 2026-10-13

- Old stuff.
"""


def test_versions():
    assert updater.parse_version("v0.3.0") == (0, 3, 0)
    assert updater.parse_version("0.10.2") == (0, 10, 2)
    assert updater.parse_version("latest") is None
    assert updater.is_newer("v0.10.0", "0.9.9")
    assert not updater.is_newer("0.2.0", "0.2.0")
    assert not updater.is_newer("junk", "0.2.0")


def test_notes_since_keeps_only_newer_sections():
    n = updater.notes_since(CHANGELOG, "0.2.0")
    assert n.startswith("## 0.4.0") and "## 0.3.0" in n and "Old stuff" not in n and "Intro" not in n
    assert updater.notes_since(CHANGELOG, "0.4.0") == ""


def fake_fetch(tags):
    def fetch(url, timeout):
        if url == updater.TAGS_URL:
            return json.dumps([{"name": t} for t in tags])
        assert url == updater.CHANGELOG_URL.format(ref="v0.4.0")
        return CHANGELOG
    return fetch


def test_check_finds_newest_tag_and_notes():
    info = updater.check("0.2.0", fetch=fake_fetch(["v0.2.0", "v0.4.0", "v0.3.0", "not-a-version"]), repo=None)
    assert info.available and info.latest == "0.4.0" and not info.error
    assert "Something new" in info.notes and "Old stuff" not in info.notes


def test_check_up_to_date_and_offline():
    info = updater.check("0.4.0", fetch=fake_fetch(["v0.4.0", "v0.3.0"]), repo=None)
    assert not info.available and info.latest == "0.4.0"

    def offline(url, timeout):
        raise OSError("no route to host")
    info = updater.check("0.2.0", fetch=offline, repo=None)
    assert not info.available and "no route to host" in info.error


def test_certificate_error_gets_a_plain_explanation():
    def bad_cert(url, timeout):
        raise OSError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    info = updater.check("0.2.0", fetch=bad_cert, repo=None)
    assert "Install Certificates.command" in info.error


# ------------------------------------------------------------------ git
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
       "-c", "tag.gpgsign=false"]  # throwaway repos: no signing, no editor prompts


def git(cwd, *args):
    subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True)


def write_version(repo, v, extra_dep=False):
    pkg = repo / "src" / "porometry"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(f'__version__ = "{v}"\n')
    deps = '["numpy", "requests"]' if extra_dep else '["numpy"]'
    (repo / "pyproject.toml").write_text(f'[project]\nname = "x"\ndependencies = {deps}\n')


@pytest.fixture
def clone(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    write_version(origin, "0.2.0")
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", "v0.2.0")
    git(tmp_path, "clone", "-q", str(origin), "clone")
    return origin, tmp_path / "clone"


@needs_git
def test_apply_update_fast_forwards(clone, monkeypatch):
    origin, local = clone
    calls = []
    monkeypatch.setattr(updater, "_pip_install", calls.append)
    assert updater.repo_root(local / "src" / "porometry" / "__init__.py") == local
    write_version(origin, "0.3.0")
    git(origin, "commit", "-qam", "v0.3.0")
    assert updater.why_not(local) == ""
    steps = []
    assert updater.apply_update(local, log=steps.append) == "0.3.0"
    assert steps and calls == []  # pyproject unchanged: no reinstall
    write_version(origin, "0.4.0", extra_dep=True)
    git(origin, "commit", "-qam", "v0.4.0")
    assert updater.apply_update(local) == "0.4.0"
    assert calls == [local]  # new dependency: reinstall


@needs_git
def test_update_refuses_local_changes_and_other_branches(clone):
    origin, local = clone
    (local / "src" / "porometry" / "__init__.py").write_text('__version__ = "9.9.9"\n')
    reason = updater.why_not(local)
    assert "local changes" in reason and "src/porometry/__init__.py" in reason
    with pytest.raises(updater.UpdateError):
        updater.apply_update(local)
    git(local, "checkout", "-q", "--", ".")
    git(local, "checkout", "-q", "-b", "experiment")
    assert "experiment" in updater.why_not(local)
    assert "git clone" in updater.why_not(None)


@needs_git
def test_update_refuses_diverged_history(clone):
    origin, local = clone
    write_version(origin, "0.3.0")
    git(origin, "commit", "-qam", "v0.3.0")
    (local / "notes.txt").write_text("local work")
    git(local, "add", "notes.txt")
    git(local, "commit", "-qm", "local commit")
    with pytest.raises(updater.UpdateError, match="aren't on GitHub"):
        updater.apply_update(local)


@needs_git
def test_check_uses_git_first(clone):
    origin, local = clone
    git(origin, "tag", "v0.2.0")
    write_version(origin, "0.3.0")
    (origin / "CHANGELOG.md").write_text(CHANGELOG.replace("0.4.0", "0.9.9").replace("0.3.0", "0.3.0"))
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "v0.3.0")
    git(origin, "tag", "v0.3.0")
    git(origin, "tag", "not-a-version")

    def no_https(url, timeout):
        raise AssertionError("should not need the web API")
    info = updater.check("0.2.0", fetch=no_https, repo=local)
    assert info.available and info.latest == "0.3.0" and not info.error
    assert "A bug." in info.notes and "Old stuff" not in info.notes
    assert updater.local_version(local) == "0.2.0"  # checking never changes the files
    assert updater.apply_update(local, install=False) == "0.3.0"


def test_check_falls_back_to_https_when_git_fails(tmp_path):
    info = updater.check("0.2.0", fetch=fake_fetch(["v0.4.0"]), repo=tmp_path)  # not a git repo
    assert info.latest == "0.4.0" and not info.error
