"""Run tags: Condition, Sample, Replicate, Folder (and any fields you add).

Automatic values come from the file name and folder; your edits are saved in ``run_tags.csv`` next to the
``.CFT`` files (one row per edited run, one column per field). It travels with the data (SyncThing) and
opens in Excel. Only the fields you changed are stored; a blank cell means "use the automatic value".

    CFP-0_25MM_MIN_S1_TEST2.CFT  ->  Condition "0.25 mm/min", Sample "S1", Replicate "2", Folder "2026-10-11"
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

SIDECAR = "run_tags.csv"
DEFAULT_FIELDS = ["Condition", "Sample", "Replicate", "Folder"]

_REPLICATE = re.compile(r"[_\- ](?:TEST|RUN|T)(\d+)$", re.IGNORECASE)
_SPECIMEN = re.compile(r"[_\- ](S|SAMPLE)(\d+)$", re.IGNORECASE)
_PREFIX = re.compile(r"^CFP[_\- ]+", re.IGNORECASE)
_DECIMAL = re.compile(r"(?<![\d.])(\d+)_(\d+)(?=[A-Za-z])")  # 0_25MM -> 0.25MM (not dates like 2_2026)
_MM_MIN = re.compile(r"\s*MM[_\- ]?(?:PER[_\- ]?)?MIN\b", re.IGNORECASE)
_NUMBER = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)")


def auto_tags(path: str | Path) -> dict[str, str]:
    """Tags read from the file name and folder."""
    p = Path(path)
    stem = p.stem
    rep = ""
    m = _REPLICATE.search(stem)
    if m:
        rep, stem = str(int(m.group(1))), stem[:m.start()]
    sample = ""
    m = _SPECIMEN.search(stem)
    if m:
        sample, stem = f"S{int(m.group(2))}", stem[:m.start()]
    cond = _PREFIX.sub("", stem) or stem
    cond = _DECIMAL.sub(r"\1.\2", cond)
    cond = _MM_MIN.sub(" mm/min", cond)
    cond = re.sub(r"[_]+", " ", cond).strip(" -")
    return {"Condition": cond or p.stem, "Sample": sample, "Replicate": rep, "Folder": p.parent.name}


def sort_key(value: str):
    """Numbers first, in numeric order ("0.25 mm/min" < "2 mm/min" < "10 mm/min"), then text."""
    m = _NUMBER.match(value or "")
    return (0, float(m.group(1)), value) if m else (1, 0.0, (value or "").lower())


class TagStore:
    """Where your tag edits live. `get` returns only the edited fields for a file."""

    def get(self, path: Path) -> dict[str, str]:
        raise NotImplementedError

    def set(self, path: Path, field: str, value: str | None) -> None:
        raise NotImplementedError

    def fields_seen(self) -> list[str]:
        return []


class MemoryTags(TagStore):
    """Keeps edits in memory only (tests, read-only folders)."""

    def __init__(self):
        self._data: dict[str, dict[str, str]] = {}

    def get(self, path):
        return dict(self._data.get(str(Path(path).resolve()), {}))

    def set(self, path, field, value):
        row = self._data.setdefault(str(Path(path).resolve()), {})
        if value is None:
            row.pop(field, None)
        else:
            row[field] = value

    def fields_seen(self):
        return list(dict.fromkeys(f for row in self._data.values() for f in row))


class SidecarTags(TagStore):
    """`run_tags.csv` in each data folder. Falls back to memory if a folder can't be written."""

    def __init__(self):
        self._cache: dict[Path, dict[str, dict[str, str]]] = {}
        self.write_errors: list[str] = []
        self._memory = MemoryTags()

    def _folder(self, folder: Path) -> dict[str, dict[str, str]]:
        folder = folder.resolve()
        if folder not in self._cache:
            rows: dict[str, dict[str, str]] = {}
            f = folder / SIDECAR
            if f.exists():
                try:
                    with f.open(newline="", encoding="utf-8-sig") as fh:
                        for r in csv.DictReader(fh):
                            name = (r.pop("File", "") or "").strip()
                            if name:
                                rows[name.lower()] = {"__name__": name,
                                                      **{k: v for k, v in r.items() if k and v not in (None, "")}}
                except (OSError, csv.Error, UnicodeDecodeError):
                    pass
            self._cache[folder] = rows
        return self._cache[folder]

    def get(self, path):
        p = Path(path)
        out = {k: v for k, v in self._folder(p.parent).get(p.name.lower(), {}).items() if k != "__name__"}
        out.update(self._memory.get(p))
        return out

    def set(self, path, field, value):
        p = Path(path)
        rows = self._folder(p.parent)
        row = rows.setdefault(p.name.lower(), {"__name__": p.name})
        if value is None:
            row.pop(field, None)
        else:
            row[field] = value
        try:
            self._write(p.parent.resolve(), rows)
        except OSError as exc:
            self.write_errors.append(f"{p.parent / SIDECAR}: {exc}")
            self._memory.set(p, field, value)

    def _write(self, folder: Path, rows: dict[str, dict[str, str]]) -> None:
        fields = list(dict.fromkeys(k for r in rows.values() for k in r if k != "__name__"))
        ordered = [f for f in DEFAULT_FIELDS if f in fields] + [f for f in fields if f not in DEFAULT_FIELDS]
        tmp = folder / (SIDECAR + ".tmp")
        with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["File", *ordered])
            for key, r in sorted(rows.items()):
                values = [r.get(f, "") for f in ordered]
                if any(values):
                    w.writerow([r.get("__name__", key), *values])
        tmp.replace(folder / SIDECAR)

    def fields_seen(self):
        seen = [k for rows in self._cache.values() for r in rows.values() for k in r if k != "__name__"]
        return list(dict.fromkeys(seen + self._memory.fields_seen()))
