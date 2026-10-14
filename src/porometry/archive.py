"""Archive runs: move a .CFT file into an `Archive/` folder next to it, with a logged reason.

Archived files stay on disk (nothing is deleted) and can be restored. Loading a folder skips
anything inside a folder named `Archive`, so archived runs drop out of plots, tables and averages.

    Data/2026-10-11/CFP-0_25MM_MIN_T1.CFT
    Data/2026-10-11/Archive/CFP-0_25MM_MIN_T1.CFT      <- after archive_file()
    Data/2026-10-11/Archive/archive_log.csv            <- when, what, why
"""

from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ARCHIVE_DIR = "Archive"
LOG_NAME = "archive_log.csv"
_LOG_FIELDS = ["timestamp", "action", "file", "folder", "reason", "qc"]


class ArchiveError(OSError):
    """The file could not be archived or restored (nothing was moved)."""


def is_archived(path: str | Path) -> bool:
    """True if the file sits inside a folder named Archive (any letter case)."""
    return any(part.lower() == ARCHIVE_DIR.lower() for part in Path(path).parent.parts)


def _log(archive_dir: Path, action: str, file: Path, reason: str, qc: str) -> None:
    log = archive_dir / LOG_NAME
    new = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"timestamp": datetime.now().isoformat(timespec="seconds"), "action": action,
                    "file": file.name, "folder": str(archive_dir.parent), "reason": reason, "qc": qc})


def archive_file(path: str | Path, reason: str = "", qc: str = "") -> Path:
    """Move `path` into `<its folder>/Archive/`. Returns the new path. Never overwrites a file."""
    src = Path(path)
    if not src.is_file():
        raise ArchiveError(f"{src} does not exist")
    if is_archived(src):
        raise ArchiveError(f"{src.name} is already archived")
    archive_dir = src.parent / ARCHIVE_DIR
    archive_dir.mkdir(exist_ok=True)
    dest = archive_dir / src.name
    n = 2
    while dest.exists():  # keep both if a run with the same name was archived before
        dest = archive_dir / f"{src.stem} ({n}){src.suffix}"
        n += 1
    try:
        shutil.move(str(src), str(dest))
    except OSError as exc:
        raise ArchiveError(f"could not move {src.name}: {exc}") from exc
    _log(archive_dir, "archived", dest, reason, qc)
    return dest


def restore_file(path: str | Path) -> Path:
    """Move an archived file back to the folder above `Archive/`. Returns the restored path."""
    src = Path(path)
    if not is_archived(src):
        raise ArchiveError(f"{src.name} is not in an Archive folder")
    archive_dir = src.parent
    dest = archive_dir.parent / src.name
    if dest.exists():
        raise ArchiveError(f"{dest.name} already exists in {dest.parent}; rename one of them first")
    try:
        shutil.move(str(src), str(dest))
    except OSError as exc:
        raise ArchiveError(f"could not move {src.name}: {exc}") from exc
    _log(archive_dir, "restored", src, "", "")
    return dest


@dataclass
class ArchivedRun:
    path: Path
    archived_at: str = ""
    reason: str = ""
    qc: str = ""


def list_archived(folders) -> list[ArchivedRun]:
    """Archived .CFT files in (or below) the given folders, with the latest logged reason."""
    seen: dict[Path, ArchivedRun] = {}
    for folder in {Path(f) for f in folders}:
        if not folder.is_dir():
            continue
        dirs = [folder] if folder.name.lower() == ARCHIVE_DIR.lower() else []
        dirs += [d for d in folder.rglob("*") if d.is_dir() and d.name.lower() == ARCHIVE_DIR.lower()]
        for d in dirs:
            reasons: dict[str, dict] = {}
            log = d / LOG_NAME
            if log.exists():
                with log.open(newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        if row.get("action") == "archived":
                            reasons[row.get("file", "")] = row
            for p in sorted(d.glob("*")):
                if p.is_file() and p.suffix.lower() == ".cft":
                    row = reasons.get(p.name, {})
                    seen[p.resolve()] = ArchivedRun(p, row.get("timestamp", ""), row.get("reason", ""),
                                                    row.get("qc", ""))
    return sorted(seen.values(), key=lambda r: (str(r.path.parent), r.path.name))
