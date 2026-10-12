"""Compare runs made at different processing rates (the "mm/min" in the file name).

    python examples/compare_conditions.py <folder with .CFT files> [<output folder>] [--pattern "*_T1.CFT"]

Writes into the output folder (default: <folder>/Report):
  comparison.csv / summary.xlsx      one row per run, plus the usual Summary/Groups/QC/per-run sheets
  overlay_flow/cff/psd.png           all runs on one plot each
  trend_vs_rate.png                  pore sizes vs mm/min
  Porometry <folder> (script).pptx   PowerPoint of the tables and figures
  <run>_report.png                   flow, CFF and distribution for each run
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from porometry import PSI_TO_KPA, Workspace  # noqa: E402
from porometry.export import write_summary  # noqa: E402
from porometry.figures import STYLE, PlotOptions, make_figure  # noqa: E402

RATE = re.compile(r"(\d+)_(\d+)MM_MIN", re.IGNORECASE)


def rate_of(name: str) -> float | None:
    m = RATE.search(name)
    return float(f"{m.group(1)}.{m.group(2)}") if m else None


def comparison(ws: Workspace) -> pd.DataFrame:
    rows = []
    for e in ws.entries:
        a = e.analysis
        k = PSI_TO_KPA
        cff_end = float(a.cff_raw[-1]) if a.cff_raw.size else np.nan
        d_end = float(a.diameter[-1]) if a.diameter.size else np.nan
        dry50 = np.interp(50 / k, a.dry_dp, a.dry_flow) / 1000 if a.dry_dp.size and a.dry_dp.max() * k >= 50 else np.nan
        rows.append({
            "Rate (mm/min)": rate_of(e.name),
            "Run": e.name,
            "QC": e.qc.status,
            "QC issues": e.qc.summary(),
            "Thickness (mm)": round(e.run.thickness_cm * 10, 3),
            "Bubble point (kPa)": None if a.bubble_dp is None else round(a.bubble_dp * k, 1),
            "Largest pore (µm)": None if a.bubble_d is None else round(a.bubble_d, 3),
            "Mean flow pressure (kPa)": None if a.mean_flow_dp is None else round(a.mean_flow_dp * k, 1),
            "Mean flow pore (µm)": None if a.mean_flow_d is None else round(a.mean_flow_d, 3),
            "Smallest pore (µm)": round(a.smallest_d, 3) if a.closed else None,
            "Max pressure reached (kPa)": round(a.max_dp * k, 1),
            "Wet/dry flow at max (%)": round(cff_end, 1),
            "Pore size at max pressure (µm)": round(d_end, 3),
            "Dry flow at 50 kPa (L/min)": None if np.isnan(dry50) else round(float(dry50), 2),
            "Complete (wet met dry)": a.closed,
        })
    return pd.DataFrame(rows).sort_values("Rate (mm/min)").reset_index(drop=True)


def trend_plot(df: pd.DataFrame, path: Path) -> None:
    with matplotlib.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(6.5, 4.2), layout="constrained")
        x = df["Rate (mm/min)"].to_numpy(float)
        for col, color, label in (("Largest pore (µm)", "#eb6834", "Largest pore (bubble point)"),
                                  ("Mean flow pore (µm)", "#2a78d6", "Mean flow pore")):
            y = pd.to_numeric(df[col], errors="coerce").to_numpy(float)
            ax.plot(x, y, "-", color=color, lw=1.4, label=label)
            done = df["Complete (wet met dry)"].to_numpy(bool)
            ax.plot(x[done], y[done], "o", color=color, ms=7)
            ax.plot(x[~done], y[~done], "o", mfc="white", mec=color, mew=1.8, ms=7)
        ax.set_xscale("log")
        ax.set_xticks(x, [f"{v:g}" for v in x])
        ax.minorticks_off()
        ax.set_xlabel("Rate in file name (mm/min)")
        ax.set_ylabel("Pore diameter (µm)")
        ax.set_ylim(bottom=0)
        ax.set_title("Pore size vs rate  (open marker = run did not reach wet = dry)", loc="left")
        ax.legend(loc="best")
        fig.savefig(path)
        plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--pattern", default="*.CFT")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    out = Path(a.out) if a.out else folder / "Report"
    out.mkdir(parents=True, exist_ok=True)

    files = sorted(folder.glob(a.pattern), key=lambda p: rate_of(p.stem) or 0)
    ws = Workspace()
    ws.add_files(files)
    df = comparison(ws)
    df.to_csv(out / "comparison.csv", index=False, encoding="utf-8-sig")
    xlsx = write_summary(ws, out / "summary.xlsx")
    with pd.ExcelWriter(xlsx, engine="openpyxl", mode="a") as xw:
        df.to_excel(xw, sheet_name="Comparison", index=False)

    opts = PlotOptions(units="kPa", show_markers=True)
    for kind in ("flow", "cff", "psd"):
        make_figure(kind, ws.series(), opts, size=(7.5, 4.6)).savefig(out / f"overlay_{kind}.png")
    binned = PlotOptions(psd_mode="binned", psd_bins=25)
    make_figure("psd", ws.series(), binned, size=(7.5, 4.6)).savefig(out / "overlay_psd_histogram.png")
    for e in ws.entries:
        make_figure("all", ws.series([e]), opts, size=(6.5, 3.6)).savefig(out / f"{e.name}_report.png")
    trend_plot(df, out / "trend_vs_rate.png")
    from porometry.slides import write_deck

    pick = lambda *names: df[[c for c in df.columns if any(c.startswith(n) for n in names)]]  # noqa: E731
    figs = [("Flow vs pressure", out / "overlay_flow.png"),
            ("Cumulative filter flow", out / "overlay_cff.png"),
            ("Pore size distribution", out / "overlay_psd.png"),
            ("Pore size distribution (histogram)", out / "overlay_psd_histogram.png"),
            ("Pore size vs rate", out / "trend_vs_rate.png")]
    figs += [(e.name, out / f"{e.name}_report.png") for e in ws.entries]
    write_deck(out / f"Porometry {folder.name} (script).pptx", "Capillary flow porometry", f"{len(ws.entries)} runs, {folder.name}",
               tables=[("Pore sizes", pick("Run", "Rate", "QC", "Largest pore", "Mean flow pore", "Smallest pore",
                                           "Wet/dry flow at max")),
                       ("Pressures (kPa) and flows", pick("Run", "Thickness", "Bubble point", "Mean flow pressure",
                                                          "Max pressure", "Dry flow at 50"))],
               figures=figs, footer="CFP-1500AEX, analyzed with Porometry Analyzer (CapRep calculations)")
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(df.drop(columns=["QC issues"]).to_string(index=False))
        print(df[["Run", "QC issues"]].to_string(index=False))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
