"""porometry-cli on made-up .CFT runs: the table it prints and the files it writes."""

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from _synth import write_run

from porometry import cli

SRC = Path(__file__).resolve().parents[1] / "src"


def test_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "porometry-cli" in out and "--excel" in out and "--figures" in out


def test_needs_a_path(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


def test_folder_prints_one_row_per_run(speeds, capsys):
    assert cli.main([str(speeds)]) == 0
    out = capsys.readouterr().out
    assert "Bubble point (kPa)" in out and "Mean flow pore (µm)" in out
    for name in ("CFP-0_25MM_MIN_S1_TEST1", "CFP-2_00MM_MIN_S1_TEST2", "CFP-10_00MM_MIN_S1_TEST3"):
        assert name in out
    assert "wrote" not in out  # nothing asked for, nothing written


def test_excel_figures_and_psi(tmp_path, capsys):
    run = write_run(tmp_path / "runs" / "CFP-2_00MM_MIN_S1T1.CFT", 1.3)
    xlsx, figs = tmp_path / "out" / "summary.xlsx", tmp_path / "out" / "figs"
    xlsx.parent.mkdir()
    assert cli.main([str(run), "--excel", str(xlsx), "--figures", str(figs), "--format", "svg", "--psi"]) == 0
    out = capsys.readouterr().out
    assert "Bubble point (psi)" in out and "CFP-2_00MM_MIN_S1T1" in out
    assert xlsx.is_file()
    summary = pd.read_excel(xlsx, sheet_name="Summary")
    assert list(summary["Run"]) == ["CFP-2_00MM_MIN_S1T1"]
    assert "Bubble point (psi)" in summary.columns
    for kind in ("flow", "cff", "psd"):
        f = figs / f"{kind}.svg"
        assert f.is_file() and f.stat().st_size > 1000
        assert f"wrote {f}" in out


def test_csv_summary(speeds, tmp_path):
    out = tmp_path / "summary.csv"
    assert cli.main([str(speeds), "--excel", str(out)]) == 0
    df = pd.read_csv(out, encoding="utf-8-sig")
    assert len(df) == 9
    mfp = df.set_index("Run")["Mean flow pore (µm)"]
    # bigger shift in _synth = smaller pores, so the pore size falls from 0.25 to 10.00 mm/min
    assert mfp["CFP-0_25MM_MIN_S1_TEST2"] > mfp["CFP-2_00MM_MIN_S1_TEST2"] > mfp["CFP-10_00MM_MIN_S1_TEST2"]


def test_group_by_folder(speeds, tmp_path):
    by_name, by_folder = tmp_path / "name.xlsx", tmp_path / "folder.xlsx"
    assert cli.main([str(speeds), "--excel", str(by_name)]) == 0
    assert cli.main([str(speeds), "--excel", str(by_folder), "--group-by", "folder"]) == 0
    assert {"0.25 mm/min", "10.00 mm/min"} <= set(pd.read_excel(by_name, "Groups")["Group"])
    assert set(pd.read_excel(by_folder, "Groups")["Group"]) == {speeds.name}


def test_unreadable_file_is_reported(tmp_path, capsys):
    good = write_run(tmp_path / "CFP-2_00MM_MIN_S1T1.CFT")
    bad = tmp_path / "CFP-BROKEN.CFT"
    bad.write_text("not a CapWin file\n")
    assert cli.main([str(good), str(bad)]) == 0
    out = capsys.readouterr().out
    assert "CFP-2_00MM_MIN_S1T1" in out
    assert f"! {bad}" in out


def test_runs_as_a_module():
    env = {**os.environ, "PYTHONPATH": str(SRC) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    r = subprocess.run([sys.executable, "-m", "porometry.cli", "--help"], capture_output=True, text=True,
                       env=env, timeout=120)
    assert r.returncode == 0 and "porometry-cli" in r.stdout
