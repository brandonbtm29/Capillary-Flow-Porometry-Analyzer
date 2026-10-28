"""Update check and self-update (no network: GitHub is faked, the 'remote' is a local git repo)."""

import json
import shutil
import subprocess
import sys
import threading
import urllib.error

import pytest

from porometry import updater

CHANGELOG = """# Changelog

Intro text.

## [Unreleased]

- Not released yet.

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
    assert updater.parse_version("v1.0.0-rc1") is None
    assert updater.is_newer("v0.10.0", "0.9.9")
    assert not updater.is_newer("0.2.0", "0.2.0")
    assert not updater.is_newer("junk", "0.2.0")


def test_notes_since_keeps_only_newer_sections():
    n = updater.notes_since(CHANGELOG, "0.2.0")
    assert n.startswith("## 0.4.0") and "## 0.3.0" in n
    assert "Old stuff" not in n and "Intro" not in n and "Not released" not in n
    assert updater.notes_since(CHANGELOG, "0.4.0") == ""


# ------------------------------------------------------------------ checking (GitHub's API faked)
def http_error(code):
    return urllib.error.HTTPError(updater.API_URL, code, "error", {}, None)


def fake_api(tag="v0.4.0", body="", changelog=CHANGELOG):
    seen = []

    def fetch(url, timeout):
        seen.append(url)
        if url == updater.API_URL:
            return json.dumps(
                {
                    "tag_name": tag,
                    "name": f"Version {tag}",
                    "body": body,
                    "html_url": f"https://github.com/{updater.REPO}/releases/tag/{tag}",
                }
            )
        assert url == updater.CHANGELOG_URL.format(ref=tag)
        return changelog

    fetch.seen = seen
    return fetch


def test_check_uses_the_latest_release_and_its_notes():
    fetch = fake_api(body="## What's new\n\n- **Release notes** from GitHub")
    info = updater.check("0.2.0", fetch=fetch, repo=None)
    assert info.available and info.latest == "0.4.0" and info.tag == "v0.4.0" and not info.error
    assert "Release notes" in info.notes
    assert info.url.endswith("/releases/tag/v0.4.0")
    assert fetch.seen == [updater.API_URL]  # notes were in the release: no CHANGELOG download


def test_check_falls_back_to_changelog_at_the_tag():
    fetch = fake_api(body="  ")
    info = updater.check("0.2.0", fetch=fetch, repo=None)
    assert info.available and "Something new" in info.notes and "A bug." in info.notes
    assert "Old stuff" not in info.notes
    assert fetch.seen[-1] == updater.CHANGELOG_URL.format(ref="v0.4.0")


def test_check_up_to_date_and_offline():
    info = updater.check("0.4.0", fetch=fake_api(), repo=None)
    assert not info.available and info.latest == "0.4.0" and not info.error

    def offline(url, timeout):
        raise OSError("no route to host")

    info = updater.check("0.2.0", fetch=offline, repo=None)
    assert not info.available and "Could not reach GitHub" in info.error and "no route to host" in info.error


def test_check_explains_github_answers(tmp_path):
    def answer(code):
        def fetch(url, timeout):
            raise http_error(code)

        return fetch

    # no releases yet: said plainly, and a bare tag is never offered instead (repo is ignored)
    info = updater.check("0.2.0", fetch=answer(404), repo=tmp_path)
    assert info.error == "No releases have been published on GitHub yet." and not info.available
    assert "Try again in an hour" in updater.check("0.2.0", fetch=answer(403), repo=None).error
    assert "Try again in an hour" in updater.check("0.2.0", fetch=answer(429), repo=None).error
    assert "(500)" in updater.check("0.2.0", fetch=answer(500), repo=None).error


def test_check_rejects_a_release_that_is_not_a_version():
    info = updater.check("0.2.0", fetch=fake_api(tag="nightly"), repo=None)
    assert not info.available and "isn't a version number" in info.error


def test_certificate_error_gets_a_plain_explanation():
    def bad_cert(url, timeout):
        raise OSError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    info = updater.check("0.2.0", fetch=bad_cert, repo=None)
    assert "Install Certificates.command" in info.error


def test_check_names_both_problems_when_git_fails_too(tmp_path):
    def offline(url, timeout):
        raise OSError("no route to host")

    info = updater.check("0.2.0", fetch=offline, repo=tmp_path)  # not a git repo
    assert "no route to host" in info.error and "git:" in info.error


def test_update_info_defaults_the_tag():
    assert updater.UpdateInfo("0.2.0", "0.3.0", "notes").tag == "v0.3.0"
    assert updater.UpdateInfo("0.2.0", error="offline").tag == ""


def test_never_waits_for_input_or_opens_a_console():
    kw = updater._popen_kwargs()
    env = kw["env"]
    assert (
        env["GIT_TERMINAL_PROMPT"] == "0" and env["GCM_INTERACTIVE"] == "never" and env["PIP_NO_INPUT"] == "1"
    )
    assert kw["stdin"] is subprocess.DEVNULL
    assert kw["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_pip_runs_with_the_console_python(tmp_path):
    (tmp_path / "pythonw.exe").write_text("")
    (tmp_path / "python.exe").write_text("")
    assert updater.console_python(str(tmp_path / "pythonw.exe")) == str(tmp_path / "python.exe")
    assert updater.console_python(str(tmp_path / "python.exe")) == str(tmp_path / "python.exe")
    cmd = updater.install_command()
    assert cmd[1:4] == ["-m", "pip", "install"] and cmd[-2:] == ["-e", "."]


def test_copies_that_cannot_update_are_sent_to_the_release_page(tmp_path, monkeypatch):
    assert "release page" in updater.why_not(None)
    assert "ZIP" in updater.why_not(tmp_path)  # a folder without .git
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(updater.shutil, "which", lambda name: None)
    assert "Git isn't installed" in updater.why_not(tmp_path)
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    assert "standalone build" in updater.why_not(tmp_path)


# ------------------------------------------------------------------ git
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
GIT = [
    "git",
    "-c",
    "user.name=test",
    "-c",
    "user.email=test@example.com",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "tag.gpgsign=false",
]  # throwaway repos: no signing, no editor prompts


def git(cwd, *args):
    return subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def write_version(repo, v, extra_dep=False):
    pkg = repo / "src" / "porometry"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(f'__version__ = "{v}"\n')
    deps = '["numpy", "requests"]' if extra_dep else '["numpy"]'
    (repo / "pyproject.toml").write_text(f'[project]\nname = "x"\ndependencies = {deps}\n')


def release(origin, v, extra_dep=False, changelog=None):
    """Commit version `v` on origin's main and tag it vX.Y.Z, like a GitHub release."""
    write_version(origin, v, extra_dep)
    if changelog is not None:
        (origin / "CHANGELOG.md").write_text(changelog)
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", f"v{v}")
    git(origin, "tag", f"v{v}")


def unreleased_commit(origin):
    (origin / "work.txt").write_text("unfinished")
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "work in progress")


@pytest.fixture
def clone(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    release(origin, "0.2.0")
    git(tmp_path, "clone", "-q", str(origin), "clone")
    return origin, tmp_path / "clone"


NO_PIP = [sys.executable, "-c", "raise SystemExit('pip should not run')"]


@needs_git
def test_update_moves_to_the_release_tag_not_main(clone):
    origin, local = clone
    assert updater.repo_root(local / "src" / "porometry" / "__init__.py") == local
    release(origin, "0.3.0")
    unreleased_commit(origin)  # on main, after the release: must not reach the user
    assert updater.why_not(local) == ""
    steps = []
    assert updater.apply_update(local, "v0.3.0", log=steps.append, command=NO_PIP) == "0.3.0"
    assert steps[0].startswith("Downloading") and any("v0.3.0" in s for s in steps)
    assert git(local, "rev-parse", "HEAD") == git(origin, "rev-parse", "v0.3.0^{commit}")
    assert not (local / "work.txt").exists()
    assert git(local, "rev-parse", "--abbrev-ref", "HEAD") == "main"  # still on main, just moved forward


@needs_git
def test_reinstalls_only_when_pyproject_changed(clone):
    origin, local = clone
    release(origin, "0.3.0")
    assert updater.apply_update(local, "v0.3.0", command=NO_PIP) == "0.3.0"  # pyproject unchanged: no pip
    release(origin, "0.4.0", extra_dep=True)
    marker = local / "installed.txt"
    install = [sys.executable, "-c", "open('installed.txt', 'w').write('yes')"]  # runs in the app folder
    assert updater.apply_update(local, "v0.4.0", command=install) == "0.4.0"
    assert marker.read_text() == "yes"


@needs_git
@pytest.mark.parametrize("how", ["fails", "timeout", "cancelled"])
def test_failed_install_goes_back_to_the_old_version(clone, monkeypatch, how):
    origin, local = clone
    old = git(local, "rev-parse", "HEAD")
    release(origin, "0.3.0", extra_dep=True)
    cancel = threading.Event()
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    if how == "fails":
        command = [sys.executable, "-c", "print('ERROR: no matching distribution'); raise SystemExit(1)"]
    elif how == "timeout":
        monkeypatch.setattr(updater, "INSTALL_TIMEOUT", 1)

    def log(msg):
        if how == "cancelled" and msg.startswith("Installing"):
            cancel.set()  # the user presses Cancel while pip runs

    expected = updater.UpdateCancelled if how == "cancelled" else updater.UpdateError
    with pytest.raises(expected, match="left on the old version") as err:
        updater.apply_update(local, "v0.3.0", log=log, cancel=cancel, command=command)
    if how == "fails":
        assert "no matching distribution" in str(err.value)
    assert git(local, "rev-parse", "HEAD") == old
    assert updater.local_version(local) == "0.2.0"
    assert git(local, "status", "--porcelain", "--untracked-files=no") == ""


@needs_git
def test_cancel_before_download_changes_nothing(clone):
    origin, local = clone
    old = git(local, "rev-parse", "HEAD")
    release(origin, "0.3.0")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(updater.UpdateCancelled, match="Nothing was changed"):
        updater.apply_update(local, "v0.3.0", cancel=cancel, command=NO_PIP)
    assert git(local, "rev-parse", "HEAD") == old


@needs_git
def test_update_refuses_local_changes_and_other_branches(clone):
    origin, local = clone
    release(origin, "0.3.0")
    (local / "src" / "porometry" / "__init__.py").write_text('__version__ = "9.9.9"\n')
    reason = updater.why_not(local)
    assert "local changes" in reason and "src/porometry/__init__.py" in reason
    with pytest.raises(updater.UpdateError, match="local changes"):
        updater.apply_update(local, "v0.3.0", command=NO_PIP)
    git(local, "checkout", "-q", "--", ".")
    git(local, "checkout", "-q", "-b", "experiment")
    assert "experiment" in updater.why_not(local)
    git(local, "checkout", "-q", "--detach", "main")  # not on any branch, e.g. a release checked out
    assert updater.why_not(local) == ""


@needs_git
def test_update_refuses_diverged_history_and_missing_tags(clone):
    origin, local = clone
    release(origin, "0.3.0")
    with pytest.raises(updater.UpdateError, match="wasn't found"):
        updater.apply_update(local, "v9.9.9", command=NO_PIP)
    (local / "notes.txt").write_text("local work")
    git(local, "add", "notes.txt")
    git(local, "commit", "-qm", "local commit")
    with pytest.raises(updater.UpdateError, match="aren't on GitHub"):
        updater.apply_update(local, "v0.3.0", command=NO_PIP)


@needs_git
@pytest.mark.parametrize("api", ["offline", "rate-limited"])
def test_check_asks_git_when_the_api_cannot_help(clone, api):
    origin, local = clone
    release(origin, "0.3.0", changelog=CHANGELOG.replace("0.4.0", "0.9.9"))
    git(origin, "tag", "not-a-version")
    unreleased_commit(origin)

    def fetch(url, timeout):
        if api == "offline":
            raise OSError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
        raise http_error(403)

    info = updater.check("0.2.0", fetch=fetch, repo=local)
    assert info.available and info.latest == "0.3.0" and info.tag == "v0.3.0" and not info.error
    assert "A bug." in info.notes and "Old stuff" not in info.notes
    assert updater.local_version(local) == "0.2.0"  # checking never changes the files
    assert updater.apply_update(local, info.tag, command=NO_PIP) == "0.3.0"
