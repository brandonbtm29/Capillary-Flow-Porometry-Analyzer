"""Check Capillary Flow Porometry Analyzer against CapRep: compare with CapRep's own Excel reports.

CapRep's "export to Excel" (.xls) files sit next to the .CFT files they were made from. This script
finds every report block, analyzes the matching .CFT with porometry.analyze(), and compares bubble
point, mean flow pore, smallest detected pore, CFF diameters and the point-by-point table.

    python tools/caprep_check.py [folder] [--out results.csv] [--min-dp 0.5]

folder defaults to C:\\CFP-1500AEX\\StudentData. Needs xlrd (pip install xlrd).
The comparison table can name other people's files, so write it somewhere private (the default is
the Validation folder in SyncThing, see tests/_data.py for how that folder is found).
"""
import argparse
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xlrd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from porometry.analysis import Settings, analyze  # noqa: E402
from porometry.cft import read_cft  # noqa: E402

NUM = re.compile(r"[-+]?\d*\.?\d+")
MIN_DP = 0.5


def num(v):
    if isinstance(v, (int, float)):
        return float(v)
    m = NUM.search(str(v))
    return float(m.group()) if m else None


def parse_blocks(xls):
    """Yield dicts, one per CapRep report block (one data file each)."""
    try:
        book = xlrd.open_workbook(str(xls), on_demand=True)
    except Exception as e:  # noqa: BLE001
        return
    for sh in book.sheets():
        rows = [sh.row_values(r) for r in range(sh.nrows)]
        cur = None
        in_table = False
        for row in rows:
            a = str(row[0]).strip() if row else ""
            if a.startswith("CAPILLARY FLOW ANALYSIS"):
                if cur and cur.get("file"):
                    yield cur
                cur = {"table": [], "sheet": sh.name}
                in_table = False
                continue
            if cur is None:
                continue
            up = a.upper()
            if up.startswith("FILE ="):
                cur.setdefault("file", str(row[1]).strip())
            elif up.startswith("PORE DISTRIBUTION ="):
                cur["psd_formula"] = a
            elif up.startswith("MEAN FLOW PORE PRESSURE"):
                cur["mfp_p"] = num(row[1]); cur["mfp_unit"] = str(row[2]).strip()
            elif up.startswith("MEAN FLOW PORE DIAMETER"):
                cur["mfp_d"] = num(row[1])
            elif up.startswith("BUBBLE POINT PRESSURE"):
                cur["bp_p"] = num(row[1]); cur["bp_unit"] = str(row[2]).strip()
            elif up.startswith("BUBBLE POINT PORE DIAMETER"):
                cur["bp_d"] = num(row[1])
            elif up.startswith("SMALLEST DETECTED PORE DIAMETER"):
                cur["small_d"] = num(row[1]); cur["small_label"] = a
            elif up.startswith("PRESSURE AT SMALLEST PORE"):
                cur["small_p"] = num(row[1])
            elif "CUMULATIVE FILTER FLOW OCCURS AT" in up:
                m = re.match(r"(\d+)% .* at ([\d.]+)", a)
                if m:
                    cur[f"cff{m.group(1)}_d"] = float(m.group(2))
            elif up == "PSI" or (len(row) > 1 and str(row[1]).strip().upper() == "MICRONS" and up in ("PSI", "KPA", "PA", "CM HG")):
                in_table = True
                cur["table_unit"] = up
            elif in_table:
                if isinstance(row[0], float) and len(row) >= 6 and isinstance(row[1], float):
                    cur["table"].append([v if isinstance(v, float) else np.nan for v in row[:8]])
                elif a.startswith("---"):
                    in_table = False
        if cur and cur.get("file"):
            yield cur


TO_PSI = {"PSI": 1.0, "KPA": 1 / 6.894757293168361, "PA": 1 / 6894.757293168361, "CM HG": 0.19336774}


def compare(block, cft):
    a = analyze(read_cft(cft), Settings(min_dp_kpa=MIN_DP))
    out = {"cft": str(cft), "xls_sheet": block["sheet"], "psd_formula": block.get("psd_formula", "")}
    f = TO_PSI.get(str(block.get("bp_unit", "PSI")).upper(), np.nan)
    if block.get("bp_p") is not None and a.bubble_dp is not None:
        out["bp_p_caprep"] = block["bp_p"] * f; out["bp_p_ours"] = a.bubble_dp
        out["bp_d_caprep"] = block.get("bp_d"); out["bp_d_ours"] = a.bubble_d
    f = TO_PSI.get(str(block.get("mfp_unit", "PSI")).upper(), np.nan)
    if block.get("mfp_p") is not None:
        out["mfp_p_caprep"] = block["mfp_p"] * f; out["mfp_p_ours"] = a.mean_flow_dp
        out["mfp_d_caprep"] = block.get("mfp_d"); out["mfp_d_ours"] = a.mean_flow_d
    out["small_d_caprep"] = block.get("small_d")
    out["small_label"] = block.get("small_label", "")
    out["small_d_ours99"] = a.smallest_d
    out["small_d_ours100"] = a.d_at_cff(100.0)
    for k in (10, 25, 75, 90):
        if f"cff{k}_d" in block:
            out[f"cff{k}_d_caprep"] = block[f"cff{k}_d"]; out[f"cff{k}_d_ours"] = a.d_at_cff(float(k))
    t = np.array(block["table"], dtype=float) if block["table"] else np.empty((0, 8))
    out["n_rows_caprep"] = len(t); out["n_wet_ours"] = int(a.dp.size)
    if len(t) and a.dp.size:
        tf = TO_PSI.get(block.get("table_unit", "PSI"), 1.0)
        tp = t[:, 0] * tf
        idx = np.array([int(np.argmin(np.abs(a.dp - p))) for p in tp])
        out["row_dp_maxerr"] = float(np.max(np.abs(a.dp[idx] - tp)))
        out["row_d_maxrel"] = float(np.nanmax(np.abs(a.diameter[idx] / t[:, 1] - 1)))
        with np.errstate(divide="ignore", invalid="ignore"):
            out["wet_ratio_med"] = float(np.nanmedian(a.wet_q[idx] / t[:, 2]))
            out["dry_ratio_med"] = float(np.nanmedian(a.dry_at_wet[idx] / t[:, 3]))
            dr = a.dry_at_wet[idx] / t[:, 3]
            out["dry_ratio_spread"] = float(np.nanmax(dr) - np.nanmin(dr))
        out["ff_maxabs"] = float(np.nanmax(np.abs(a.cff[idx] - t[:, 5])))
        # which PSD formula reproduces CapRep's PORE DIST column (from CapRep's own columns)?
        dd = t[:-1, 1] - t[1:, 1]
        inc = t[1:, 4]
        psd = t[1:, 6]
        ok = np.isfinite(psd) & (dd > 0)
        if ok.any():
            out["psd_err_dD"] = float(np.nanmax(np.abs(inc[ok] / dd[ok] - psd[ok]) / np.maximum(psd[ok], 1e-3)))
            out["psd_err_dD2"] = float(np.nanmax(np.abs(inc[ok] / dd[ok] ** 2 - psd[ok]) / np.maximum(psd[ok], 1e-3)))
        out["first_row_wet_ours_index"] = int(idx[0])
        out["caprep_last_ff"] = float(t[-1, 5])
    return out


def collect(root: Path) -> pd.DataFrame:
    seen = set()
    results = []
    for xls in sorted(root.rglob("*")):
        if xls.suffix.lower() != ".xls":
            continue
        for b in parse_blocks(xls):
            cft = next((p for p in xls.parent.iterdir() if p.name.lower() == b["file"].lower()), None)
            if cft is None:
                continue
            key = (str(cft).lower(), b.get("mfp_p"), b.get("bp_p"))
            if key in seen:
                continue
            seen.add(key)
            try:
                r = compare(b, cft)
            except Exception as e:  # noqa: BLE001
                r = {"cft": str(cft), "error": f"{type(e).__name__}: {e}"}
            r["xls"] = str(xls)
            results.append(r)
    return pd.DataFrame(results)


def summarize(df: pd.DataFrame) -> None:
    def report(name, ours, theirs, kind="rel", tol=(0.001, 0.01, 0.05)):
        if ours not in df or theirs not in df:
            return
        m = df[ours].notna() & df[theirs].notna()
        if kind == "rel":
            e = (df.loc[m, ours] / df.loc[m, theirs] - 1).abs()
            fmt = lambda x: f"{100 * x:.2f}%"  # noqa: E731
        else:
            e = (df.loc[m, ours] - df.loc[m, theirs]).abs()
            fmt = lambda x: f"{x:.4f}"  # noqa: E731
        within = "  ".join(f"<={fmt(t)}: {(e <= t).mean() * 100:.0f}%" for t in tol)
        missing = int((df[theirs].notna() & df[ours].isna()).sum())
        print(f"{name:26s} n={m.sum():4d}  {within}" + (f"   (no value from us: {missing})" if missing else ""))

    print(f"{len(df)} CapRep report blocks matched to .CFT files")
    report("bubble point pressure, psi", "bp_p_ours", "bp_p_caprep", "abs", (0.0006, 0.002, 0.01))
    report("mean flow pressure, psi", "mfp_p_ours", "mfp_p_caprep", "abs", (0.0006, 0.002, 0.01))
    report("mean flow diameter", "mfp_d_ours", "mfp_d_caprep")
    report("smallest pore diameter", "small_d_ours99", "small_d_caprep")
    if "ff_maxabs" in df:
        x = df["ff_maxabs"].dropna()
        print(f"{'table CFF (max |diff|)':26s} n={len(x):4d}  <=0.01 pt: {(x <= 0.01).mean() * 100:.0f}%  "
              f"<=0.5 pt: {(x <= 0.5).mean() * 100:.0f}%")


def default_out() -> Path:
    base = os.environ.get("UAKRON_DATA_DIR") or Path.home() / "SyncThing" / "UAkron Playground"
    return Path(base) / "Capillary Flow Porometer" / "Validation" / "caprep_comparison.csv"


def main(argv=None):
    global MIN_DP
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder", nargs="?", default=r"C:\CFP-1500AEX\StudentData")
    ap.add_argument("--out", type=Path, default=default_out())
    ap.add_argument("--min-dp", type=float, default=0.5, help="Settings.min_dp_kpa (0 = exactly like CapRep)")
    args = ap.parse_args(argv)
    MIN_DP = args.min_dp
    df = collect(Path(args.folder))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    summarize(df)
    print(f"details: {args.out}")


if __name__ == "__main__":
    main()
