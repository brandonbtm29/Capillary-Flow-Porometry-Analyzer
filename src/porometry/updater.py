"""Check GitHub for a newer release and update this copy of the app to it.

Checking asks GitHub's public API for the latest *release* (no account needed), so unreleased work on
``main`` never reaches anyone. "What's new" is that release's notes on GitHub, or the CHANGELOG.md
sections at its tag when the notes are empty. If the API can't be reached (python.org's macOS Python
has no certificates until its "Install Certificates.command" is run; a proxy; GitHub limiting requests)
and the app runs from a git clone, git is asked for the newest ``vX.Y.Z`` tag instead: git has its own
network and certificate setup, the same one the update itself uses.

Updating works for a git clone (``pip install -e .``): ``git fetch --tags --force origin``, then
``git merge --ff-only <tag>``, so local work is never overwritten and no merge commits are made.
``pip install -e .`` runs only when ``pyproject.toml`` changed between the old commit and the tag; if
that fails, takes too long or is cancelled, ``git reset --keep <old commit>`` puts the folder back.
It refuses when the app's own tracked files were edited (and says which) or the clone is on a branch
other than ``main``. ZIP copies, standalone builds and computers without git are sent to the release
page instead.

Nothing here waits for input (no git password prompts, no pip questions) or opens a console window on
Windows. No Qt here, so it can be tested on its own.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__

logger = logging.getLogger(__name__)

REPO = "brandonbtm29/Capillary-Flow-Porometry-Analyzer"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
CHANGELOG_URL = f"https://raw.githubusercontent.com/{REPO}/{{ref}}/CHANGELOG.md"
BRANCH = "main"
FETCH_TIMEOUT = 120  # seconds for git fetch
INSTALL_TIMEOUT = 600  # seconds for pip install
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


class UpdateError(RuntimeError):
    """The update could not be applied (nothing was changed unless the message says so)."""


class UpdateCancelled(UpdateError):
    """The user cancelled the update; the app folder is as it was."""


# ------------------------------------------------------------------ versions
def parse_version(text: str) -> tuple[int, int, int] | None:
    m = _VERSION_RE.match((text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


def notes_since(changelog: str, current: str) -> str:
    """The CHANGELOG.md sections (``## X.Y.Z - date``) newer than `current`, newest first."""
    out, keep = [], False
    for line in changelog.splitlines():
        if line.startswith("## "):
            v = line[3:].split()[0] if line[3:].split() else ""
            keep = is_newer(v, current)
        if keep:
            out.append(line)
    return "\n".join(out).strip()


@dataclass
class UpdateInfo:
    current: str
    latest: str | None = None
    notes: str = ""
    error: str = ""
    tag: str = ""  # the release's git tag, e.g. "v0.7.0" (default: "v" + latest)
    url: str = RELEASES_PAGE  # the release's page on GitHub

    def __post_init__(self):
        if self.latest and not self.tag:
            self.tag = "v" + self.latest

    @property
    def available(self) -> bool:
        return bool(self.latest) and is_newer(self.latest, self.current)


# ------------------------------------------------------------------ checking
def _ssl_context() -> ssl.SSLContext:
    """certifi's certificates when available: python.org's macOS Python has none until its
    "Install Certificates.command" is run (CERTIFICATE_VERIFY_FAILED)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _fetch(url: str, timeout: float) -> str:
    """GET `url`. Raises urllib.error.HTTPError when GitHub answers with an error status."""
    req = urllib.request.Request(  # noqa: S310 (fixed https URLs)
        url,
        headers={
            "User-Agent": f"capillary-flow-porometry-analyzer/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:  # noqa: S310
        return r.read().decode("utf-8")


def _newest(tags: list[str]) -> str | None:
    versions = [t for t in tags if parse_version(t)]
    return max(versions, key=parse_version) if versions else None


def _explain(exc: Exception) -> str:
    text = f"{exc.__class__.__name__}: {exc}"
    if "CERTIFICATE_VERIFY_FAILED" in text:
        hint = (
            "Python on this computer can't verify GitHub's security certificate. On a Mac with Python from "
            "python.org, run 'Install Certificates.command' in Applications > Python 3.x"
        )
        return f"{hint} ({text})"
    return text


def _http_problem(exc: urllib.error.HTTPError) -> str:
    if exc.code == 404:
        return "No releases have been published on GitHub yet."
    if exc.code in (403, 429):
        return "GitHub is limiting requests right now. Try again in an hour."
    return f"GitHub answered with an error ({exc.code})."


def _check_api(current: str, timeout: float, fetch: Callable[[str, float], str]) -> UpdateInfo:
    """The latest release from GitHub's API; its notes, or CHANGELOG.md at its tag if it has none."""
    data = json.loads(fetch(API_URL, timeout))
    tag = str(data.get("tag_name") or "")
    version = parse_version(tag)
    if version is None:
        return UpdateInfo(current, error=f"The latest release's tag {tag!r} isn't a version number (vX.Y.Z).")
    info = UpdateInfo(
        current,
        ".".join(map(str, version)),
        str(data.get("body") or "").strip(),
        tag=tag,
        url=str(data.get("html_url") or RELEASES_PAGE),
    )
    if info.available and not info.notes:
        try:
            info.notes = notes_since(fetch(CHANGELOG_URL.format(ref=tag), timeout), current)
        except Exception:  # notes are nice to have
            info.notes = ""
    return info


def _check_git(repo: Path, current: str, timeout: float) -> UpdateInfo:
    """Newest vX.Y.Z tag via `git ls-remote`; notes from CHANGELOG.md at that tag."""
    out = _git(repo, "ls-remote", "--tags", "--refs", "origin", timeout=timeout + 22)
    tag = _newest([ln.split("refs/tags/", 1)[1] for ln in out.splitlines() if "refs/tags/" in ln])
    if tag is None:
        return UpdateInfo(current, error="No released versions found on GitHub.")
    info = UpdateInfo(current, ".".join(map(str, parse_version(tag))), tag=tag)
    if info.available:
        try:  # downloads the release's commits (doesn't change any files) to read its CHANGELOG.md
            _git(
                repo, "fetch", "--quiet", "origin", f"+refs/tags/{tag}:refs/tags/{tag}", timeout=FETCH_TIMEOUT
            )
            info.notes = notes_since(_git(repo, "show", f"{tag}:CHANGELOG.md", strip=False), current)
        except UpdateError:
            info.notes = ""
    return info


def check(
    current: str = __version__,
    timeout: float = 8.0,
    fetch: Callable[[str, float], str] = _fetch,
    repo: Path | None | str = "auto",
) -> UpdateInfo:
    """Find the latest release on GitHub. Never raises: problems end up in `.error`.

    Asks GitHub's releases API first. If that can't be reached, or GitHub is limiting requests, a git
    clone (`repo="auto"` finds this one) asks git for the newest release tag instead.
    """
    if repo == "auto":
        repo = repo_root()
    try:
        return _check_api(current, timeout, fetch)
    except urllib.error.HTTPError as exc:
        problem = _http_problem(exc)
        if exc.code == 404:  # GitHub answered: there is no release (a bare tag is not one)
            return UpdateInfo(current, error=problem)
    except Exception as exc:  # offline, proxy, certificates, an answer that isn't JSON, ...
        problem = f"Could not reach GitHub. {_explain(exc)}"
    if repo is not None:
        try:
            return _check_git(Path(repo), current, timeout)
        except Exception as exc:
            problem += f" / git: {_explain(exc)}"
    return UpdateInfo(current, error=problem)


# ------------------------------------------------------------------ running git and pip
# Never wait for someone to type something: no git password prompts, no pip questions.
_QUIET_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
    "PIP_NO_INPUT": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PYTHONUNBUFFERED": "1",
}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flashes up under pythonw on Windows


def _popen_kwargs() -> dict:
    return {"env": {**os.environ, **_QUIET_ENV}, "stdin": subprocess.DEVNULL, "creationflags": _NO_WINDOW}


def _run(cmd: list[str], cwd: Path | None, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **_popen_kwargs(),
    )


def _git(repo: Path, *args: str, timeout: float = 120, strip: bool = True) -> str:
    try:
        r = _run(["git", *args], repo, timeout)
    except FileNotFoundError as exc:
        raise UpdateError("git is not installed or not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(f"git {args[0]} took too long (no network?).") from exc
    if r.returncode != 0:
        raise UpdateError(f"git {' '.join(args)} failed:\n{(r.stderr or r.stdout).strip()}")
    return r.stdout.strip() if strip else r.stdout


def _kill_tree(proc: subprocess.Popen) -> None:
    """Stop a command and anything it started (pip starts helper processes)."""
    if os.name == "nt":
        try:
            _run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], None, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    proc.kill()
    proc.wait()


@dataclass
class StreamResult:
    returncode: int
    output: str  # the last lines the command printed
    stopped: str = ""  # "", "cancelled" or "timeout"


def _stream(
    cmd: list[str],
    cwd: Path,
    timeout: float,
    on_line: Callable[[str], None] | None = None,
    cancel: threading.Event | None = None,
) -> StreamResult:
    """Run a command, passing each line it prints to `on_line` as it comes.

    Stops it (and what it started) if `cancel` is set or `timeout` seconds pass.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_popen_kwargs(),
        )
    except OSError as exc:
        return StreamResult(-1, str(exc))
    lines: queue.Queue[str] = queue.Queue()

    def pump():
        for line in proc.stdout:
            lines.put(line.rstrip())
        proc.stdout.close()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    tail: list[str] = []
    stopped = ""
    deadline = time.monotonic() + timeout
    while True:
        try:
            line = lines.get(timeout=0.2)
        except queue.Empty:
            line = None
        if line:
            tail = [*tail, line][-40:]
            if on_line:
                on_line(line)
        if line is None and proc.poll() is not None and not reader.is_alive() and lines.empty():
            break
        if cancel is not None and cancel.is_set():
            stopped = "cancelled"
        elif time.monotonic() > deadline:
            stopped = "timeout"
        if stopped:
            _kill_tree(proc)
            break
    return StreamResult(proc.returncode if proc.returncode is not None else -1, "\n".join(tail), stopped)


def console_python(executable: str | None = None) -> str:
    """The python.exe next to pythonw.exe: the app runs windowless under pythonw.exe on Windows,
    but pip should run under the console one."""
    exe = Path(executable or sys.executable)
    if exe.stem.lower() == "pythonw":
        console = exe.with_name("python" + exe.suffix)
        if console.exists():
            return str(console)
    return str(exe)


def install_command() -> list[str]:
    """``pip install -e .`` (run in the app folder), with no questions and no progress bars."""
    return [
        console_python(),
        "-m",
        "pip",
        "install",
        "--no-input",
        "--disable-pip-version-check",
        "--progress-bar",
        "off",
        "-e",
        ".",
    ]


# ------------------------------------------------------------------ local clone
def repo_root(start: Path | None = None) -> Path | None:
    """The git clone this copy of the package runs from, or None (e.g. a plain pip install)."""
    here = Path(start or __file__).resolve()
    for d in [here, *here.parents]:
        if (d / ".git").exists() and (d / "pyproject.toml").exists():
            return d
    return None


def why_not(repo: Path | None) -> str:
    """Empty string if `repo` can update itself, otherwise the reason in plain words."""
    page = "Download the new version from the release page instead."
    if getattr(sys, "frozen", False):
        return f"This is a standalone build, so it can't update itself. {page}"
    if repo is None or not (Path(repo) / ".git").exists():
        return f"This copy wasn't installed with git (for example it came from a ZIP file), so it can't update itself. {page}"
    if shutil.which("git") is None:
        return f"Git isn't installed on this computer, so the app can't update itself. {page}"
    try:
        branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        changed = [
            ln
            for ln in _git(repo, "status", "--porcelain", "--untracked-files=no", strip=False).splitlines()
            if ln.strip()
        ]  # keep the 2-letter status column: "XY path"
    except UpdateError as exc:
        return f"This folder's git information looks broken: {exc}"
    if branch not in (BRANCH, "HEAD"):  # "HEAD": not on any branch, e.g. a release tag checked out
        return f"The folder is on branch '{branch}', not '{BRANCH}'. Switch back to '{BRANCH}' or update it with git yourself."
    if changed:
        files = ", ".join(line[3:] for line in changed[:6]) + (", …" if len(changed) > 6 else "")
        return (
            f"Files in the app folder have local changes ({files}), so updating could overwrite them. "
            "Commit or undo them first."
        )
    return ""


def local_version(repo: Path) -> str:
    text = (repo / "src" / "porometry" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else "?"


def apply_update(
    repo: Path,
    tag: str,
    install: bool = True,
    log: Callable[[str], None] = lambda s: None,
    cancel: threading.Event | None = None,
    command: list[str] | None = None,
) -> str:
    """Move `repo` to release `tag` (fast-forward only); reinstall if dependencies changed.

    Returns the new version. Raises UpdateError (UpdateCancelled if `cancel` was set) with a plain
    message; the folder is then on the old commit. `log` gets short progress messages; `command`
    replaces ``pip install -e .`` (tests).
    """
    reason = why_not(repo)
    if reason:
        raise UpdateError(reason)
    old = _git(repo, "rev-parse", "HEAD")

    log("Downloading from GitHub…")
    fetch = _stream(["git", "fetch", "--tags", "--force", "origin"], repo, FETCH_TIMEOUT, cancel=cancel)
    if fetch.stopped == "cancelled":
        raise UpdateCancelled("The update was cancelled. Nothing was changed.")
    if fetch.stopped == "timeout":
        raise UpdateError(
            "Downloading the update took too long. Check the internet connection and try again."
        )
    if fetch.returncode != 0:
        raise UpdateError("Couldn't download the update:\n" + fetch.output.strip()[-500:])
    try:
        _git(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
    except UpdateError as exc:
        raise UpdateError(f"The release tag {tag} wasn't found on GitHub.") from exc
    if cancel is not None and cancel.is_set():
        raise UpdateCancelled("The update was cancelled. Nothing was changed.")

    log(f"Switching to {tag}…")
    try:
        _git(repo, "merge", "--ff-only", "--quiet", tag)
    except UpdateError as exc:
        raise UpdateError(
            f"Your copy has commits that aren't on GitHub (not in release {tag}), so it can't simply move "
            f"forward to it. Update it with git yourself.\n{exc}"
        ) from exc

    deps_changed = (
        _run(["git", "diff", "--quiet", old, "HEAD", "--", "pyproject.toml"], repo, 60).returncode != 0
    )
    if install and deps_changed:
        log("Installing the new dependencies… (this can take a minute)")

        def show(line: str):
            log("Installing the new dependencies…\n" + (line[:90] + "…" if len(line) > 90 else line))

        result = _stream(command or install_command(), repo, INSTALL_TIMEOUT, on_line=show, cancel=cancel)
        if result.stopped or result.returncode != 0:
            why = {
                "cancelled": "The update was cancelled",
                "timeout": f"Installing the new dependencies took over {INSTALL_TIMEOUT // 60} minutes",
            }.get(result.stopped, "Installing the new dependencies failed")
            logger.error("%s; going back to %s:\n%s", why, old[:10], result.output[-800:])
            try:
                _git(repo, "reset", "--keep", old)
                note = ""
            except UpdateError as exc:
                note = f"\n\nGoing back also failed: {exc}"
            detail = "" if result.stopped == "cancelled" else "\n\n" + result.output.strip()[-800:]
            error = UpdateCancelled if result.stopped == "cancelled" else UpdateError
            raise error(f"{why}, so the app was left on the old version.{note}{detail}")

    logger.info("Updated from %s to %s", old[:10], tag)
    return local_version(repo)
