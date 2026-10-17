"""Reader for PMI CapWin capillary-flow data files (.CFT).

A .CFT file is plain text:

    EXTENDED
     8
    Operator=...            <- "key=value" header lines
    Type of test= Wet Up/Dry Down
    ...
    10-09-2026              <- test date
    <blank>
    <blank>
    Galwick                 <- wetting fluid
    -15.9                   <- surface tension, dyn/cm (sign is ignored)
     .635                   <- sample diameter, cm
     .092                   <- sample thickness, cm
    1                       <- flag (kept as-is)
     0, 14.71167            <- first curve: flow (cc/min), pressure (psia)
    ...
    0,0                     <- end of first curve
     30136.14, 29.42833     <- second curve
    ...
    0,0                     <- end of second curve
    <blank>
    B, 15, 250, 0, 1, 2     <- test parameters (kept as raw text)
    W, ...
    D, ...
    0,0
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

PSI_TO_KPA = 6.894757293168361

_PAIR = re.compile(r"^\s*(-?[\d.]+(?:[eE][-+]?\d+)?)\s*,\s*(-?[\d.]+(?:[eE][-+]?\d+)?)\s*$")
_DATE = re.compile(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$")


class CFTError(ValueError):
    """The file could not be read as a CapWin .CFT file."""


@dataclass
class Curve:
    """One flow curve. Arrays are sorted by increasing pressure."""

    flow: np.ndarray  # cc/min
    pressure: np.ndarray  # psia (absolute, as recorded)

    @property
    def n(self) -> int:
        return len(self.flow)

    @classmethod
    def from_pairs(cls, pairs: list[tuple[float, float]]) -> Curve:
        if not pairs:
            return cls(np.array([]), np.array([]))
        arr = np.array(pairs, dtype=float)
        order = np.argsort(arr[:, 1], kind="stable")
        return cls(flow=arr[order, 0], pressure=arr[order, 1])


@dataclass
class Run:
    """Everything read from one .CFT file."""

    path: Path
    header: dict[str, str]
    date: str
    fluid: str
    surface_tension: float  # dyn/cm
    diameter_cm: float
    thickness_cm: float
    wet: Curve
    dry: Curve
    test_type: str = ""
    tortuosity: float | None = None
    parameters: list[str] = field(default_factory=list)
    raw_order: str = "wet-dry"  # which curve came first in the file

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def operator(self) -> str:
        return self.header.get("Operator", "")

    @property
    def p_atm(self) -> float:
        """Ambient pressure (psia): the first recorded wet point."""
        if self.wet.n:
            # the file's first wet point is the lowest pressure, taken before flow starts
            return float(self.wet.pressure[0])
        if self.dry.n:
            return float(self.dry.pressure.min())
        return 14.696


def _num(text: str) -> float:
    try:
        return float(text.strip())
    except ValueError as exc:
        raise CFTError(f"expected a number, got {text!r}") from exc


def read_cft(path: str | Path) -> Run:
    """Parse a .CFT file. Raises CFTError if the layout is not recognised."""
    path = Path(path)
    text = path.read_text(encoding="latin-1", errors="replace")
    lines = [ln.rstrip("\r") for ln in text.split("\n")]

    # first "flow, pressure" pair = start of the curve block
    first_pair = next((i for i, ln in enumerate(lines) if _PAIR.match(ln)), None)
    if first_pair is None:
        raise CFTError(f"{path.name}: no flow/pressure data found")

    # the five non-blank lines before it: fluid, surface tension, diameter, thickness, flag
    pre = [i for i in range(first_pair) if lines[i].strip()]
    if len(pre) < 5:
        raise CFTError(f"{path.name}: sample block (fluid, surface tension, ...) not found")
    i_fluid, i_gamma, i_diam, i_thick, _i_flag = pre[-5:]
    fluid = lines[i_fluid].strip()
    gamma = abs(_num(lines[i_gamma]))
    diameter = _num(lines[i_diam])
    thickness = _num(lines[i_thick])

    header: dict[str, str] = {}
    date = ""
    for ln in lines[:i_fluid]:
        s = ln.strip()
        if "=" in s:
            k, v = s.split("=", 1)
            header[k.strip()] = v.strip()
        elif _DATE.match(s):
            date = s

    # read curves: each ends with a "0,0" line
    curves: list[list[tuple[float, float]]] = [[]]
    k = first_pair
    while k < len(lines) and len(curves) <= 2:
        s = lines[k].strip()
        m = _PAIR.match(s)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            if a == 0 and b == 0:
                curves.append([])
                if len(curves) == 3:
                    k += 1
                    break
            else:
                curves[-1].append((a, b))
        elif s:
            break  # something else: stop reading curves
        k += 1
    first = curves[0]
    second = curves[1] if len(curves) > 1 else []

    params = [ln.strip() for ln in lines[k:] if ln.strip() and not _PAIR.match(ln)]

    test_type = header.get("Type of test", "").strip()
    # The wet curve is always stored first, whatever the run order ("Dry Up/Wet Up" included):
    # checked against CapRep's own WET FLOW column for all 14 Dry Up/Wet Up files in the lab's archive.
    dry_first = False
    wet_pairs, dry_pairs = first, second

    tort = header.get("Tortuosity Factor")
    try:
        tortuosity = float(tort) if tort else None
    except ValueError:
        tortuosity = None

    return Run(
        path=path,
        header=header,
        date=date,
        fluid=fluid,
        surface_tension=gamma,
        diameter_cm=diameter,
        thickness_cm=thickness,
        wet=Curve.from_pairs(wet_pairs),
        dry=Curve.from_pairs(dry_pairs),
        test_type=test_type,
        tortuosity=tortuosity,
        parameters=params,
        raw_order="dry-wet" if dry_first else "wet-dry",
    )
