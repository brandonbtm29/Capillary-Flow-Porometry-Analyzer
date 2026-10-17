"""Check GitHub for a newer version and update this copy of the app in place.

The app runs from a git clone (``pip install -e .``), so updating means a fast-forward ``git pull`` of
``main`` and, only when ``pyproject.toml`` changed, ``pip install -e .`` to pick up new dependencies.
Released versions are the ``vX.Y.Z`` tags on GitHub; "what's new" comes from CHANGELOG.md at that tag.

Nothing here touches local work: the update refuses to run when tracked files have local changes or
the clone is not on ``main``, and ``--ff-only`` never creates merge commits.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__

REPO = "brandonbtm29/Capillary-Flow-Porometry-Analyzer"
TAGS_URL = f"https://api.github.com/repos/{REPO}/tags?per_page=100"
CHANGELOG_URL = f"https://raw.githubusercontent.com/{REPO}/{{ref}}/CHANGELOG.md"
BRANCH = "main"
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


class UpdateError(RuntimeError):
    """The update could not be applied (nothing was changed unless the message says so)."""


# ------------------------------------------------------------------ versions
def parse_version(text: str) -> tuple[int, int, int] | None:
    m = _VERSION_RE.match(text.strip())
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

    @property
    def available(self) -> bool:
        return bool(self.latest) and is_newer(self.latest, self.current)


def _ssl_context() -> ssl.SSLContext:
    """certifi's certificates when available: python.org's macOS Python has none until its
    "Install Certificates.command" is run (CERTIFICATE_VERIFY_FAILED)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _fetch(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": f"capillary-flow-porometry-analyzer/{__version__}",  # noqa: S310
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:  # noqa: S310 (fixed URLs)
        return r.read().decode("utf-8")


def _latest(tags: list[str]) -> str | None:
    versions = [t for t in tags if parse_version(t)]
    return max(versions, key=parse_version) if versions else None


def _check_git(repo: Path, current: str, timeout: float) -> UpdateInfo:
    """Tags via `git ls-remote`, notes from the fetched CHANGELOG.md. Uses git's own network and
    certificate setup, the same path the update itself takes."""
    info = UpdateInfo(current)
    out = _git(repo, "ls-remote", "--tags", "--refs", "origin", timeout=timeout + 22)
    latest = _latest([ln.split("refs/tags/", 1)[1] for ln in out.splitlines() if "refs/tags/" in ln])
    if latest is None:
        info.error = "No released versions found on GitHub."
        return info
    info.latest = latest.lstrip("v")
    if info.available:
        try:  # downloads the new commits (doesn't change any files) to read their CHANGELOG.md
            _git(repo, "fetch", "--quiet", "origin", BRANCH, timeout=120)
            info.notes = notes_since(_git(repo, "show", f"origin/{BRANCH}:CHANGELOG.md", strip=False), current)
        except UpdateError:
            info.notes = ""
    return info


def _check_https(current: str, timeout: float, fetch: Callable[[str, float], str]) -> UpdateInfo:
    info = UpdateInfo(current)
    latest = _latest([t.get("name", "") for t in json.loads(fetch(TAGS_URL, timeout))])
    if latest is None:
        info.error = "No released versions found on GitHub."
        return info
    info.latest = latest.lstrip("v")
    if info.available:
        try:
            info.notes = notes_since(fetch(CHANGELOG_URL.format(ref=latest), timeout), current)
        except Exception:  # notes are nice to have
            info.notes = ""
    return info


def _explain(exc: Exception) -> str:
    text = f"{exc.__class__.__name__}: {exc}"
    if "CERTIFICATE_VERIFY_FAILED" in text:
        hint = ("Python on this computer can't verify GitHub's security certificate. On a Mac with Python from "
                "python.org, run 'Install Certificates.command' in Applications > Python 3.x")
        return f"{hint} ({text})"
    return text


def check(current: str = __version__, timeout: float = 8.0,
          fetch: Callable[[str, float], str] = _fetch, repo: Path | None | str = "auto") -> UpdateInfo:
    """Find the newest vX.Y.Z tag on GitHub. Never raises: problems end up in `.error`.

    Asks git first when running from a clone (`repo="auto"`), then the GitHub web API.
    """
    if repo == "auto":
        repo = repo_root()
    problems = []
    if repo is not None:
        try:
            return _check_git(Path(repo), current, timeout)
        except Exception as exc:
            problems.append(f"git: {_explain(exc)}")
    try:
        return _check_https(current, timeout, fetch)
    except Exception as exc:  # offline, proxy, rate limit, certificates, ...
        problems.append(_explain(exc))
    return UpdateInfo(current, error="Could not reach GitHub. " + " / ".join(problems))


# ------------------------------------------------------------------ local clone
def repo_root(start: Path | None = None) -> Path | None:
    """The git clone this copy of the package runs from, or None (e.g. a plain pip install)."""
    here = Path(start or __file__).resolve()
    for d in [here, *here.parents]:
        if (d / ".git").exists() and (d / "pyproject.toml").exists():
            return d
    return None


def _git(repo: Path, *args: str, timeout: float = 120, strip: bool = True) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")  # fail instead of waiting for a password prompt
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flashes under pythonw on Windows
    try:
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout,
                           env=env, creationflags=flags)
    except FileNotFoundError as exc:
        raise UpdateError("git is not installed or not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(f"git {args[0]} took too long (no network?).") from exc
    if r.returncode != 0:
        raise UpdateError(f"git {' '.join(args)} failed:\n{(r.stderr or r.stdout).strip()}")
    return r.stdout.strip() if strip else r.stdout


def why_not(repo: Path | None) -> str:
    """Empty string if `repo` can be updated automatically, otherwise the reason in plain words."""
    if repo is None:
        return "This copy wasn't installed from a git clone, so it can't update itself."
    try:
        branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if branch != BRANCH:
            return f"The folder is on branch '{branch}', not '{BRANCH}'."
        changed = [ln for ln in _git(repo, "status", "--porcelain", "--untracked-files=no", strip=False).splitlines()
                   if ln.strip()]  # keep the 2-letter status column: "XY path"
    except UpdateError as exc:
        return str(exc)
    if changed:
        files = ", ".join(line[3:] for line in changed[:6])
        return f"Files in the app folder have local changes ({files}). Commit or undo them first."
    return ""


def local_version(repo: Path) -> str:
    text = (repo / "src" / "porometry" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else "?"


def _python_for_pip() -> str:
    exe = Path(sys.executable)
    if exe.stem.lower() == "pythonw":  # the GUI shortcut runs pythonw.exe; pip wants the console one
        console = exe.with_name("python" + exe.suffix)
        if console.exists():
            return str(console)
    return str(exe)


def apply_update(repo: Path, install: bool = True, log: Callable[[str], None] = lambda s: None) -> str:
    """Fast-forward `repo` to origin/main; reinstall if dependencies changed. Returns the new version."""
    reason = why_not(repo)
    if reason:
        raise UpdateError(reason)
    old = _git(repo, "rev-parse", "HEAD")
    log("Downloading from GitHub…")
    _git(repo, "fetch", "--quiet", "origin", BRANCH, timeout=300)
    log("Updating files…")
    try:
        _git(repo, "merge", "--ff-only", "--quiet", f"origin/{BRANCH}")
    except UpdateError as exc:
        raise UpdateError("Your copy has commits that aren't on GitHub, so it can't simply move forward.\n"
                          f"{exc}") from exc
    new = _git(repo, "rev-parse", "HEAD")
    if install and new != old and "pyproject.toml" in _git(repo, "diff", "--name-only", old, new).split():
        log("Installing new dependencies…")
        _pip_install(repo)
    return local_version(repo)


def _pip_install(repo: Path) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([_python_for_pip(), "-m", "pip", "install", "--quiet", "-e", str(repo)],
                       capture_output=True, text=True, timeout=900, creationflags=flags)
    if r.returncode != 0:
        raise UpdateError("The files were updated, but installing dependencies failed:\n"
                          f"{(r.stderr or r.stdout).strip()[-1500:]}")
