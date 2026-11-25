"""tools/caprep_check.py on a made-up CapRep report (no real exports: they hold lab results).

The script reads CapRep's .xls files with xlrd; here the workbook is a stand-in, so neither xlrd nor an .xls
file is needed.
"""

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from _synth import write_run

from porometry import Settings, analyze, read_cft

TOOL = Path(__file__).resolve().parents[1] / "tools" / "caprep_check.py"
KPA = 6.894757293168361


@pytest.fixture
def cc(monkeypatch):
    """The tool as a module. A placeholder xlrd stands in if xlrd isn't installed (it's an optional extra)."""
    if importlib.util.find_spec("xlrd") is None:
        monkeypatch.setitem(sys.modules, "xlrd", types.ModuleType("xlrd"))
    spec = importlib.util.spec_from_file_location("caprep_check_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Sheet:
    def __init__(self, name, rows):
        self.name, self._rows, self.nrows = name, rows, len(rows)

    def row_values(self, r):
        return self._rows[r]


class Book:
    def __init__(self, *sheets):
        self._sheets = sheets

    def sheets(self):
        return list(self._sheets)


def use_book(monkeypatch, cc, book):
    def open_workbook(path, on_demand=False):
        if book is None:
            raise OSError("not an Excel file")
        return book
    monkeypatch.setattr(cc.xlrd, "open_workbook", open_workbook, raising=False)


def block_rows(file, a, bp_unit="KPA"):
    """One CapRep report block whose numbers are our own analysis `a`, so a perfect match is expected."""
    f = KPA if bp_unit == "KPA" else 1.0
    rows = [
        ["CAPILLARY FLOW ANALYSIS", "", ""],
        ["Sample ID", "made up", ""],
        ["FILE =", file, ""],
        ["FILE =", "ignored-second-file.CFT", ""],  # the first FILE = line wins
        ["Pore distribution = dF/dD", "", ""],
        ["BUBBLE POINT PRESSURE", f"{a.bubble_dp * f:.6f} {bp_unit.lower()}", bp_unit],  # text with a unit is ok
        ["BUBBLE POINT PORE DIAMETER", a.bubble_d, "MICRONS"],
        ["MEAN FLOW PORE PRESSURE", a.mean_flow_dp, "PSI"],
        ["MEAN FLOW PORE DIAMETER", a.mean_flow_d, "MICRONS"],
        ["SMALLEST DETECTED PORE DIAMETER (98%)", a.smallest_d, "MICRONS"],
        ["PRESSURE AT SMALLEST PORE", a.smallest_dp, "PSI"],
        [f"25% Cumulative Filter Flow occurs at {a.d_at_cff(25.0):.4f} microns", "", ""],
        [f"75% Cumulative Filter Flow occurs at {a.d_at_cff(75.0):.4f} microns", "", ""],
        ["PSI", "MICRONS", "WET FLOW", "DRY FLOW", "% FLOW", "FILTER FLOW", "PORE DIST", ""],
    ]
    ok = a.dp > 0
    prev = None
    for dp, d, wet, dry, cff in zip(a.dp[ok], a.diameter[ok], a.wet_q[ok], a.dry_at_wet[ok], a.cff[ok], strict=True):
        inc = 0.0 if prev is None else float(cff - prev[1])
        psd = 0.0 if prev is None or prev[0] <= d else inc / (prev[0] - d)
        rows.append([float(dp), float(d), float(wet), float(dry), inc, float(cff), psd, ""])
        prev = (d, cff)
    rows.append(["---- end of table ----", "", "", "", "", "", "", ""])
    rows.append([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, ""])  # after the table: not a row
    return rows


@pytest.fixture
def run(tmp_path):
    path = write_run(tmp_path / "Reports" / "CFP-2_00MM_MIN_S1T1.CFT", 1.3)
    return path, analyze(read_cft(path), Settings(min_dp_kpa=0.5))


def test_num(cc):
    assert cc.num(3) == 3.0 and cc.num(2.5) == 2.5
    assert cc.num("12.75 psi") == 12.75 and cc.num("-0.5") == -0.5
    assert cc.num("n/a") is None


def test_parse_blocks(cc, monkeypatch, run):
    path, a = run
    rows = [["Report printed by CapRep", "", ""]] + block_rows(path.name, a) + block_rows("OTHER.CFT", a, "PSI")
    use_book(monkeypatch, cc, Book(Sheet("Sheet1", rows), Sheet("Empty", [["no reports here"]])))
    blocks = list(cc.parse_blocks(path.parent / "report.xls"))
    assert [b["file"] for b in blocks] == [path.name, "OTHER.CFT"]
    b = blocks[0]
    assert b["sheet"] == "Sheet1" and b["psd_formula"] == "Pore distribution = dF/dD"
    assert b["bp_unit"] == "KPA" and b["bp_p"] == pytest.approx(a.bubble_dp * KPA, rel=1e-5)
    assert b["mfp_p"] == pytest.approx(a.mean_flow_dp) and b["mfp_unit"] == "PSI"
    assert b["small_d"] == pytest.approx(a.smallest_d) and b["small_label"].startswith("SMALLEST")
    assert b["cff25_d"] == pytest.approx(a.d_at_cff(25.0), abs=1e-4) and "cff75_d" in b
    assert b["table_unit"] == "PSI" and len(b["table"]) == int((a.dp > 0).sum())
    assert all(len(r) == 8 and np.isnan(r[7]) for r in b["table"])  # text cells become NaN
    assert b["table"][0][0] == pytest.approx(a.dp[a.dp > 0][0])
    assert blocks[1]["bp_unit"] == "PSI"


def test_parse_blocks_unreadable_file(cc, monkeypatch, tmp_path):
    use_book(monkeypatch, cc, None)
    assert list(cc.parse_blocks(tmp_path / "broken.xls")) == []


def test_compare_matches_our_own_numbers(cc, monkeypatch, run):
    path, a = run
    use_book(monkeypatch, cc, Book(Sheet("Sheet1", block_rows(path.name, a))))
    (block,) = cc.parse_blocks(path.parent / "report.xls")
    out = cc.compare(block, path)
    assert out["bp_p_caprep"] == pytest.approx(out["bp_p_ours"], abs=1e-5)  # kPa converted back to psi
    assert out["mfp_p_caprep"] == pytest.approx(out["mfp_p_ours"])
    assert out["mfp_d_caprep"] == pytest.approx(out["mfp_d_ours"])
    assert out["cff25_d_caprep"] == pytest.approx(out["cff25_d_ours"], abs=1e-4)
    assert out["n_rows_caprep"] == len(block["table"])
    assert out["row_dp_maxerr"] == pytest.approx(0, abs=1e-9)
    assert out["row_d_maxrel"] == pytest.approx(0, abs=1e-9)
    assert out["ff_maxabs"] == pytest.approx(0, abs=1e-9)
    assert out["dry_ratio_med"] == pytest.approx(1.0)
    assert np.isfinite(out["psd_err_dD"])


def test_main_writes_the_comparison(cc, monkeypatch, run, tmp_path, capsys):
    path, a = run
    (path.parent / "report.xls").write_bytes(b"stand-in")  # collect() looks for .xls files
    (path.parent / "notes.txt").write_text("not a report")
    use_book(monkeypatch, cc, Book(Sheet("Sheet1", block_rows(path.name, a) + block_rows("MISSING.CFT", a))))
    out = tmp_path / "private" / "comparison.csv"
    cc.main([str(path.parent), "--out", str(out)])
    text = capsys.readouterr().out
    assert "1 CapRep report blocks matched to .CFT files" in text  # MISSING.CFT has no file next to it
    assert "mean flow diameter" in text and "n=   1" in text
    assert out.is_file()
    import pandas as pd
    df = pd.read_csv(out)
    assert len(df) == 1 and df.loc[0, "cft"] == str(path)


def test_default_out(cc, monkeypatch, tmp_path):
    monkeypatch.setenv("UAKRON_DATA_DIR", str(tmp_path))
    assert cc.default_out() == tmp_path / "Capillary Flow Porometer" / "Validation" / "caprep_comparison.csv"
