"""Command line: analyze a folder of .CFT files without opening the GUI.

    porometry-cli C:\\CFP-1500AEX\\StudentData\\BrandonM --excel summary.xlsx --figures figs
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .export import save_figure, write_summary
from .figures import PlotOptions
from .workspace import Workspace


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="porometry-cli", description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", help=".CFT files or folders (searched recursively)")
    ap.add_argument("--excel", help="write an Excel (or .csv) summary here")
    ap.add_argument("--figures", help="folder for flow / CFF / PSD figures")
    ap.add_argument("--format", default="png", choices=["png", "svg", "pdf"])
    ap.add_argument("--psi", action="store_true", help="report pressures in psi instead of kPa")
    ap.add_argument("--group-by", default="name", choices=["name", "folder"])
    a = ap.parse_args(argv)

    ws = Workspace(group_mode=a.group_by)
    for p in map(Path, a.paths):
        ws.add_folder(p) if p.is_dir() else ws.add_files([p])
    units = "psi" if a.psi else "kPa"
    df = ws.summary_frame(units)
    cols = ["Run", "QC", f"Bubble point ({units})", "Largest pore (µm)", "Mean flow pore (µm)", "Smallest pore (µm)",
            "QC issues"]
    if len(df):
        print(df[cols].to_string(index=False, max_colwidth=70))
    for p, err in ws.errors:
        print(f"! {p}: {err}")
    if a.excel:
        print("wrote", write_summary(ws, a.excel, units))
    if a.figures:
        out = Path(a.figures)
        out.mkdir(parents=True, exist_ok=True)
        for kind in ("flow", "cff", "psd"):
            print("wrote", save_figure(ws, kind, out / f"{kind}.{a.format}", PlotOptions(units=units)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
