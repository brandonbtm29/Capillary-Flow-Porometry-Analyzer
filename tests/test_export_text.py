"""Text people type (tags, field names) must not turn into formulas in exported CSV and Excel files."""

import csv

import openpyxl
import pandas as pd
from _synth import write_run

from porometry.export import plain_text, write_summary
from porometry.workspace import Workspace


def _workspace(tmp_path):
    ws = Workspace()
    ws.add_files([write_run(tmp_path / "CFP-2_00MM_MIN_S1T1.CFT"), write_run(tmp_path / "CFP-2_00MM_MIN_S2T1.CFT")])
    a, b = ws.entries
    ws.set_tag([a], "Condition", "=HYPERLINK(\"http://example.invalid\")")
    ws.set_tag([b], "Condition", "-20 C")
    return ws


def test_plain_text_marks_formula_starts_only_in_text():
    df = pd.DataFrame({"=x": ["=1+2", "+3", "-20 C", "@SUM(A1)", "\tx", "plain", None], "n": [-1.5] * 7})
    out = plain_text(df)
    assert list(out.columns) == ["'=x", "n"]
    assert out["'=x"].tolist()[:6] == ["'=1+2", "'+3", "'-20 C", "'@SUM(A1)", "'\tx", "plain"]
    assert pd.isna(out["'=x"].iloc[6]) and (out["n"] == -1.5).all()  # numbers and blanks untouched
    assert df["=x"].iloc[0] == "=1+2"  # the original frame is not changed


def test_csv_summary_has_no_formulas(tmp_path):
    path = write_summary(_workspace(tmp_path), tmp_path / "out.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        cells = [c for row in csv.reader(f) for c in row]
    assert "'=HYPERLINK(\"http://example.invalid\")" in cells and "'-20 C" in cells
    assert not any(c.startswith(("=", "+", "-", "@")) for c in cells if c)


def test_xlsx_summary_stores_text_as_text(tmp_path):
    path = write_summary(_workspace(tmp_path), tmp_path / "out.xlsx")
    book = openpyxl.load_workbook(path)
    cells = [c for sheet in book.worksheets for row in sheet.iter_rows() for c in row if c.value is not None]
    assert not [c.coordinate for c in cells if c.data_type == "f"]
    values = {c.value for c in cells}
    assert "'=HYPERLINK(\"http://example.invalid\")" in values
    assert "-20 C" in values  # Excel only treats "=" as a formula in a stored string, so this stays as typed
