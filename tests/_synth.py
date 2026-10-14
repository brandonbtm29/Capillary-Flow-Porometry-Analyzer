"""Made-up .CFT runs with a chosen pore size, for tests that don't need lab data."""

from pathlib import Path

import numpy as np

P0 = 14.7


def write_run(path: Path, shift: float = 1.0, noise: float = 0.0, seed: int = 0) -> Path:
    """Like test_synthetic.write_cft, with the pore size set by `shift` (bigger = smaller pores)."""
    rng = np.random.default_rng(seed)
    wet_dp = np.arange(0.0, 9.01, 0.25)
    wet = [(max(0.0, 1000 * d * np.clip((d - shift) / 3, 0, 1) * (1 + rng.normal(0, noise))), P0 + d)
           for d in wet_dp]
    dry = [(1000 * d, P0 + d) for d in np.arange(0.5, 7.01, 0.5)]
    lines = ["EXTENDED", " 8 ", "Operator=Test", "Lot Number=", "Hardware Serial Number=0",
             "Type of test= Wet Up/Dry Up", "Wet Parameter=x.tpf", "Dry Parameter=x.tpf", "Lohm Table=lohmtable.cal",
             "Tortuosity Factor= .715", "01-01-2026", "", "", "Galwick", "-15.9", " .635", " .05", "1"]
    lines += [f" {q:.6g}, {p:.6g}" for q, p in wet] + ["0,0"]
    lines += [f" {q:.6g}, {p:.6g}" for q, p in dry] + ["0,0", "", "B, 15, 250, 0, 1, 2", "0,0"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\r\n".join(lines) + "\r\n", encoding="latin-1")
    return path


def make_speeds(tmp_path: Path) -> Path:
    """3 speeds x 3 replicates in Data/2026-10-11, with a clear pore-size trend."""
    d = tmp_path / "Data" / "2026-10-11"
    i = 0
    for cond, shift in (("0_25MM_MIN", 0.8), ("2_00MM_MIN", 1.3), ("10_00MM_MIN", 2.0)):
        for t in (1, 2, 3):
            write_run(d / f"CFP-{cond}_S1_TEST{t}.CFT", shift * (1 + 0.05 * (t - 2)), 0.01, i)
            i += 1
    return d
