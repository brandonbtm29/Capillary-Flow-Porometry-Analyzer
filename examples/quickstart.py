"""Analyze a folder of .CFT files from a script and make a comparison figure.

Run:  python examples/quickstart.py C:\\CFP-1500AEX\\StudentData\\BrandonM
"""

import sys
from pathlib import Path

from porometry import Workspace
from porometry.export import save_figure, write_summary
from porometry.figures import PlotOptions

folder = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parents[1] / "tests" / "data")

ws = Workspace()
ws.add_folder(folder)

# keep only runs that pass QC (or only warn) in the plots
for e in ws.entries:
    e.visible = e.qc.status in ("pass", "info", "warn")

print(ws.summary_frame()[["Run", "QC", "Largest pore (µm)", "Mean flow pore (µm)", "Smallest pore (µm)"]])
print(ws.group_frame())

write_summary(ws, "porometry_summary.xlsx")
save_figure(ws, "all", "porometry_overview.png", PlotOptions(psd_mode="binned", psd_bins=25))
print("wrote porometry_summary.xlsx and porometry_overview.png")
