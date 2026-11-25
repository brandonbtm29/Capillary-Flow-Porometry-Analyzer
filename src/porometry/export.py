"""Write results to CSV / Excel and figures to PNG / SVG / PDF."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import Analysis
from .cft import PSI_TO_KPA
from .figures import PlotOptions, make_figure
from .qc import Level
from .workspace import Workspace


def run_table(a: Analysis, units: str = "kPa") -> pd.DataFrame:
    """Point-by-point table for one run: pressure, flows, CFF, diameter, distribution."""
    f = PSI_TO_KPA if units == "kPa" else 1.0
    df = pd.DataFrame({
        f"dP ({units})": a.dp * f,
        "Wet flow (cc/min)": a.wet_q,
        "Dry flow (cc/min)": a.dry_at_wet,
        "CFF (%)": a.cff,
        "Diameter (µm)": a.diameter,
    })
    d, psd, dcff = a.distribution("D")
    df["Avg diameter of step (µm)"] = np.r_[np.nan, d] if d.size else np.nan
    df["Flow in step (%)"] = np.r_[np.nan, dcff] if d.size else np.nan
    df["PSD (%/µm)"] = np.r_[np.nan, psd] if d.size else np.nan
    return df



def raw_curves(a: Analysis, units: str = "kPa") -> pd.DataFrame:
    f = PSI_TO_KPA if units == "kPa" else 1.0
    n = max(a.wet_dp.size, a.dry_dp.size)
    pad = lambda x: np.r_[x, np.full(n - x.size, np.nan)]  # noqa: E731
    return pd.DataFrame({
        f"Wet dP ({units})": pad(a.wet_dp * f), "Wet flow (cc/min)": pad(a.wet_flow),
        f"Dry dP ({units})": pad(a.dry_dp * f), "Dry flow (cc/min)": pad(a.dry_flow),
    })


# Excel reads a CSV cell starting with one of these as a formula, and openpyxl stores a string starting with
# "=" as one, so text people typed (tags, field names, run names) could run as a formula when the file is
# opened. Such cells get a leading ' (the same as typing it in Excel); numbers are left alone.
CSV_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
XLSX_FORMULA_START = ("=",)


def plain_text(df: pd.DataFrame, starts: tuple[str, ...] = CSV_FORMULA_START) -> pd.DataFrame:
    """A copy of `df` in which text cells (and column names) that would be read as a formula start with '."""
    def fix(v):
        return "'" + v if isinstance(v, str) and v.startswith(starts) else v

    out = df.copy()
    if not isinstance(out.columns, pd.MultiIndex):
        out.columns = [fix(c) for c in out.columns]
    for c in out.columns:
        if pd.api.types.is_object_dtype(out[c]) or pd.api.types.is_string_dtype(out[c]):
            out[c] = out[c].map(fix)
    return out


def _sheet_name(name: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]\*\?/\\:]", "_", name)[:28]
    s, i = base, 2
    while s in used:
        s = f"{base[:25]}~{i}"
        i += 1
    used.add(s)
    return s


def write_summary(ws: Workspace, path: str | Path, units: str = "kPa", per_run_sheets: bool = True,
                  group_max_level: Level = Level.WARN) -> Path:
    """CSV (summary only) or Excel (Summary, Groups, Statistics, QC and one sheet per run)."""
    path = Path(path)
    summary = ws.summary_frame(units)
    if path.suffix.lower() == ".csv":
        plain_text(summary).to_csv(path, index=False, encoding="utf-8-sig")
        return path
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    qc_rows = [{"Run": e.name, "Level": f.level.label, "Check": f.title, "Detail": f.detail}
               for e in ws.entries for f in e.qc.findings]
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        tables = {
            "Summary": summary,
            "Groups": ws.group_frame(group_max_level),
            "Statistics": ws.stats_frame(units=units, max_level=group_max_level),
            "QC": pd.DataFrame(qc_rows, columns=["Run", "Level", "Check", "Detail"]),
        }
        for sheet, table in tables.items():
            plain_text(table, XLSX_FORMULA_START).to_excel(xw, sheet_name=sheet, index=False)
        if per_run_sheets:
            used = {"Summary", "Groups", "Statistics", "QC"}
            for e in ws.entries:
                name = _sheet_name(e.name, used)
                t = run_table(e.analysis, units)
                t.to_excel(xw, sheet_name=name, index=False)
                raw = raw_curves(e.analysis, units)
                raw.to_excel(xw, sheet_name=name, index=False, startcol=len(t.columns) + 1)
        for sheet in xw.book.worksheets:
            for col in sheet.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:50])
                sheet.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
            sheet.freeze_panes = "A2"
    return path


def figure_for(ws: Workspace, kind: str, options: PlotOptions | None = None, highlight: str | None = None,
               size: tuple[float, float] = (6.5, 4.2), font_pt: float | None = None,
               group_max_level: Level = Level.WARN):
    """The figure the app shows for `kind`, at an export size (inches) and font size."""
    o = options or PlotOptions()
    groups = ws.group_data(group_max_level) if (o.display != "runs" or kind == "compare") else None
    return make_figure(kind, ws.series(highlight=highlight), o, size=size, groups=groups, font_pt=font_pt)


def save_figure(ws: Workspace, kind: str, path: str | Path, options: PlotOptions | None = None,
                highlight: str | None = None, size: tuple[float, float] = (6.5, 4.2), font_pt: float | None = None,
                dpi: int = 300, transparent: bool = False, group_max_level: Level = Level.WARN) -> Path:
    path = Path(path)
    fig = figure_for(ws, kind, options, highlight, size, font_pt, group_max_level)
    fig.savefig(path, dpi=dpi, transparent=transparent)
    return path
