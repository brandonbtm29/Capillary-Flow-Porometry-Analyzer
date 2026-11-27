"""Update check and self-update (no network: GitHub is faked, the 'remote' is a local git repo)."""

import json
import os
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


def test_git_runs_without_the_callers_git_variables(monkeypatch):
    """GIT_CONFIG_* can make git run commands and GIT_DIR points it at another repo: none come along."""
    for name, value in {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "evil",
        "git_dir": "/elsewhere",
        "GIT_SSH_COMMAND": "evil",
    }.items():
        monkeypatch.setenv(name, value)
    env = updater._popen_kwargs()["env"]
    assert not [k for k in env if k.upper().startswith("GIT_") and k != "GIT_TERMINAL_PROMPT"]
    assert env["GIT_TERMINAL_PROMPT"] == "0" and "PATH" in env


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


REAL_RELEASE_SIGNED = updater.release_signed


@pytest.fixture
def clone(tmp_path, monkeypatch):
    """origin (like GitHub) and a clone of it. The throwaway releases aren't signed, so the signature
    check passes them here; the signing tests below use the real one."""
    monkeypatch.setattr(updater, "release_signed", lambda repo, ref: "")
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


# ------------------------------------------------------------------ signed releases
def _signers_file(repo, text='me@example.com namespaces="git" ssh-ed25519 AAAA\n'):
    (repo / ".github").mkdir(parents=True, exist_ok=True)
    (repo / ".github" / "allowed_signers").write_text(text)


@pytest.mark.parametrize(
    ("letter", "code", "words"),
    [
        ("N", 0, "isn't signed"),
        ("U", 0, "key that isn't on the trusted list"),
        ("B", 0, "bad signature"),
        ("E", 0, "couldn't be checked"),
        ("R", 0, "revoked key"),
        ("", 0, "couldn't be checked"),  # git printed nothing
        ("G", 128, "couldn't be checked"),  # git failed
    ],
)
def test_only_good_signatures_pass(tmp_path, monkeypatch, letter, code, words):
    _signers_file(tmp_path)
    monkeypatch.setattr(updater, "_ssh_keygen", lambda: "/usr/bin/ssh-keygen")
    calls = []

    def run(cmd, cwd, timeout):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, code, stdout=letter + "\n", stderr="")

    monkeypatch.setattr(updater, "_run", run)
    why = updater.release_signed(tmp_path, "abc123")
    assert words in why and "allowed_signers" in why and "wasn't installed" in why
    cmd = calls[0]
    assert cmd[:2] == ["git", "-c"] and cmd[-1] == "abc123" and "--format=%G?" in cmd
    assert f"gpg.ssh.allowedSignersFile={tmp_path / '.github' / 'allowed_signers'}" in cmd  # this copy's own
    assert "gpg.ssh.program=/usr/bin/ssh-keygen" in cmd

    monkeypatch.setattr(
        updater, "_run", lambda cmd, cwd, timeout: subprocess.CompletedProcess(cmd, 0, "G\n", "")
    )
    assert updater.release_signed(tmp_path, "abc123") == ""


def test_windows_uses_gits_ssh_keygen_first(tmp_path, monkeypatch):
    """System32's ssh-keygen can hang on -Y verify in an SSH session (BMAX), so Git's own copy comes first."""
    git = tmp_path / "Git" / "cmd" / "git.exe"
    gits = tmp_path / "Git" / "usr" / "bin" / "ssh-keygen.exe"
    on_path = str(tmp_path / "System32" / "OpenSSH" / "ssh-keygen.exe")
    for f in (git, gits):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("")
    monkeypatch.setattr(updater.shutil, "which", lambda name: str(git) if name == "git" else on_path)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "elsewhere"))
    assert updater._ssh_keygen(windows=True) == str(gits.resolve())
    gits.unlink()  # no Git copy: the one on PATH
    assert updater._ssh_keygen(windows=True) == on_path
    assert updater._ssh_keygen(windows=False) == on_path  # elsewhere: PATH only


def test_no_list_or_no_ssh_keygen_means_no_update(tmp_path, monkeypatch):
    def run(cmd, cwd, timeout):
        raise AssertionError("git shouldn't run")

    monkeypatch.setattr(updater, "_run", run)
    assert "has no .github/allowed_signers" in updater.release_signed(tmp_path, "abc123")
    _signers_file(tmp_path)
    monkeypatch.setattr(updater, "_ssh_keygen", lambda: None)
    assert "ssh-keygen isn't installed" in updater.release_signed(tmp_path, "abc123")


@needs_git
def test_update_refuses_a_release_that_is_not_signed(clone, monkeypatch):
    origin, local = clone
    release(origin, "0.3.0")
    before = git(local, "rev-parse", "HEAD")
    monkeypatch.setattr(updater, "release_signed", REAL_RELEASE_SIGNED)  # this clone has no allowed_signers
    with pytest.raises(updater.UpdateError, match="has no .github/allowed_signers"):
        updater.apply_update(local, "v0.3.0", command=NO_PIP)
    monkeypatch.setattr(
        updater, "release_signed", lambda repo, ref: "The release isn't signed, so it wasn't installed."
    )
    with pytest.raises(updater.UpdateError, match="Release v0.3.0 isn't signed"):
        updater.apply_update(local, "v0.3.0", command=NO_PIP)
    assert git(local, "rev-parse", "HEAD") == before and updater.local_version(local) == "0.2.0"


def _key(tmp_path, name):
    key = tmp_path / name
    subprocess.run(
        [updater._ssh_keygen(), "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)],
        check=True,
        capture_output=True,
    )
    return key


def _signed_release(origin, v, key, signers_text=None):
    """Like release(), but the commit is signed with `key` (and may change allowed_signers)."""
    write_version(origin, v)
    if signers_text is not None:
        _signers_file(origin, signers_text)
    git(origin, "add", "-A")
    sign = [
        "-c",
        "gpg.format=ssh",
        "-c",
        f"user.signingkey={key}",
        "-c",
        f"gpg.ssh.program={updater._ssh_keygen()}",
    ]
    r = subprocess.run(
        [*GIT, *sign, "commit", "-S", "-qm", f"v{v}"], cwd=origin, capture_output=True, text=True
    )
    if r.returncode and os.name == "nt":
        pytest.skip(f"can't sign a test commit here: {r.stderr.strip()[:200]}")
    assert r.returncode == 0, r.stderr
    git(origin, "tag", f"v{v}")


@needs_git
@pytest.mark.skipif(updater._ssh_keygen() is None, reason="OpenSSH's ssh-keygen not installed")
def test_real_signatures(tmp_path, monkeypatch):
    """Signed with a listed key: installs. Unsigned, signed by an unlisted key, or a release that lists its
    own new key: refused, because the check uses this copy's list, not the downloaded one."""
    monkeypatch.setattr(updater, "release_signed", REAL_RELEASE_SIGNED)
    trusted, stranger = _key(tmp_path, "trusted"), _key(tmp_path, "stranger")
    line = 'me@example.com namespaces="git" {}'.format
    trusted_line = line((tmp_path / "trusted.pub").read_text().strip())
    stranger_line = line((tmp_path / "stranger.pub").read_text().strip())
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    _signed_release(origin, "0.2.0", trusted, signers_text=trusted_line + "\n")
    git(tmp_path, "clone", "-q", str(origin), "clone")
    local = tmp_path / "clone"

    _signed_release(origin, "0.3.0", trusted)
    assert updater.apply_update(local, "v0.3.0", command=NO_PIP) == "0.3.0"

    release(origin, "0.4.0")  # not signed
    with pytest.raises(updater.UpdateError, match="Release v0.4.0 isn't signed"):
        updater.apply_update(local, "v0.4.0", command=NO_PIP)

    _signed_release(origin, "0.5.0", stranger)
    with pytest.raises(updater.UpdateError, match="isn't on the trusted list"):
        updater.apply_update(local, "v0.5.0", command=NO_PIP)

    # A release that adds its own key to the list is still checked against this copy's list
    _signed_release(origin, "0.6.0", stranger, signers_text=trusted_line + "\n" + stranger_line + "\n")
    with pytest.raises(updater.UpdateError, match="isn't on the trusted list"):
        updater.apply_update(local, "v0.6.0", command=NO_PIP)
    assert updater.local_version(local) == "0.3.0"
