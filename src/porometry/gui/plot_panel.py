"""The 'Plot options' panel beside the plots: grouping, colours, axes and look."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ..figures import KIND_TITLES, LEGEND_POSITIONS, PALETTES, PlotOptions
from ..groups import METRICS
from ..workspace import RUN, Workspace

DISPLAY = {"runs": "Individual runs", "means": "Group means ± SD", "both": "Runs + group means"}
PSD_MODES = [("Point-by-point (CapRep), %/µm", ("points", "D")),
             ("Point-by-point, %/µm² (D² weighting)", ("points", "D2")),
             ("Histogram, % flow per bin", ("binned", "D")),
             ("Point-by-point, ΔFF/ΔD² (older CapRep)", ("points", "dD2"))]


def _combo(items: dict | list, current=None) -> QComboBox:
    c = QComboBox()
    pairs = items.items() if isinstance(items, dict) else items
    for key, text in pairs:
        c.addItem(text, key)
    if current is not None:
        i = c.findData(current)
        c.setCurrentIndex(max(i, 0))
    return c


class PlotOptionsPanel(QWidget):
    """Edits the workspace's grouping/colour settings and the PlotOptions in place.

    `changed(regroup)` fires after every edit; regroup is True when the run list must be rebuilt
    (the 'average by' field changed).
    """
    changed = pyqtSignal(bool)
    edit_colors = pyqtSignal()

    def __init__(self, ws: Workspace, opts: PlotOptions, parent=None):
        super().__init__(parent)
        self.ws, self.opts = ws, opts
        self.kind = "flow"
        self._quiet = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(6, 6, 6, 6)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        # ---- groups and colours
        box = QGroupBox("Groups and colours")
        f = QFormLayout(box)
        self.average_by = QComboBox()
        self.average_by.setToolTip("Runs with the same value of this field are averaged (Averages table, group "
                                   "means, Compare tab). 'Run' keeps every run separate, to compare replicates.")
        f.addRow("Average by", self.average_by)
        self.color_by = QComboBox()
        self.color_by.setToolTip("Run: every run its own colour. A field: runs with the same value share a colour "
                                 "and get different markers.")
        f.addRow("Colour by", self.color_by)
        self.palette = _combo(PALETTES)
        f.addRow("Palette", self.palette)
        self.colors_btn = QPushButton("Group colours…")
        self.colors_btn.setToolTip("Pick the colour for each value of the 'colour by' field")
        self.colors_btn.clicked.connect(self.edit_colors.emit)
        f.addRow("", self.colors_btn)
        self.display = _combo(DISPLAY)
        f.addRow("Show", self.display)
        self.sd_band = QCheckBox("± SD band around group means")
        f.addRow(self.sd_band)
        lay.addWidget(box)

        # ---- axes
        box = QGroupBox("Axes")
        f = QFormLayout(box)
        self.units = _combo([("kPa", "kPa"), ("psi", "psi")])
        f.addRow("Pressure units", self.units)
        self.logx = QCheckBox("Log diameter axis")
        f.addRow(self.logx)
        self.psd_mode = QComboBox()
        for text, data in PSD_MODES:
            self.psd_mode.addItem(text, data)
        f.addRow("Distribution", self.psd_mode)
        self.bins = QSpinBox()
        self.bins.setRange(4, 100)
        f.addRow("Histogram bins", self.bins)
        self.metric = _combo({k: v[0] for k, v in METRICS.items()})
        self.metric.setToolTip("What the Compare groups tab and the Statistics table show")
        f.addRow("Compare", self.metric)
        lay.addWidget(box)

        # ---- axis limits for the current plot
        self.lim_box = QGroupBox("Axis limits")
        g = QVBoxLayout(self.lim_box)
        self.lim_label = QLabel()
        self.lim_label.setStyleSheet("color:#52514e")
        g.addWidget(self.lim_label)
        self.lims: list[QLineEdit] = []
        for axis in ("x", "y"):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{axis} from"))
            for i in range(2):
                e = QLineEdit()
                e.setPlaceholderText("auto")
                e.setValidator(QDoubleValidator())
                e.setMaximumWidth(80)
                e.editingFinished.connect(self._limits_edited)
                self.lims.append(e)
                row.addWidget(e)
                if i == 0:
                    row.addWidget(QLabel("to"))
            g.addLayout(row)
        reset = QPushButton("Automatic")
        reset.setToolTip("Clear the limits of this plot")
        reset.clicked.connect(self._limits_reset)
        g.addWidget(reset, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.lim_box)

        # ---- look
        box = QGroupBox("Look")
        f = QFormLayout(box)
        self.markers = QCheckBox("Markers on curves")
        f.addRow(self.markers)
        self.line_width = QDoubleSpinBox()
        self.line_width.setRange(0.5, 6)
        self.line_width.setSingleStep(0.2)
        self.line_width.setDecimals(1)
        f.addRow("Line width", self.line_width)
        self.legend = _combo(LEGEND_POSITIONS)
        f.addRow("Legend", self.legend)
        self.titles = QCheckBox("Plot titles")
        f.addRow(self.titles)
        lay.addWidget(box)
        lay.addStretch(1)

        self.sync()
        for w in (self.average_by, self.color_by, self.palette, self.display, self.units, self.psd_mode, self.metric,
                  self.legend):
            w.currentIndexChanged.connect(self._edited)
        for w in (self.sd_band, self.logx, self.markers, self.titles):
            w.toggled.connect(self._edited)
        self.bins.valueChanged.connect(self._edited)
        self.line_width.valueChanged.connect(self._edited)

    # ------------------------------------------------------------------ model -> widgets
    def sync(self) -> None:
        """Show the current workspace / options (after loading a session, adding a field, ...)."""
        self._quiet = True
        try:
            ws, o = self.ws, self.opts
            for combo, items, cur in ((self.average_by, [*ws.fields, RUN], ws.average_by),
                                      (self.color_by, [RUN, *ws.fields], ws.color_by)):
                combo.clear()
                for it in items:
                    text = "Run (no averaging)" if (it == RUN and combo is self.average_by) else it
                    combo.addItem(text, it)
                combo.setCurrentIndex(max(combo.findData(cur), 0))
            for combo, cur in ((self.palette, ws.palette), (self.display, o.display), (self.units, o.units),
                               (self.metric, o.compare_metric), (self.legend, o.legend)):
                combo.setCurrentIndex(max(combo.findData(cur), 0))
            for i in range(self.psd_mode.count()):
                if self.psd_mode.itemData(i) == (o.psd_mode, o.psd_weighting):
                    self.psd_mode.setCurrentIndex(i)
            self.sd_band.setChecked(o.sd_band)
            self.logx.setChecked(o.log_diameter)
            self.bins.setValue(o.psd_bins)
            self.markers.setChecked(o.show_markers)
            self.titles.setChecked(o.title)
            self.line_width.setValue(o.line_width)
            self._update_enabled()
            self._show_limits()
        finally:
            self._quiet = False

    def set_kind(self, kind: str) -> None:
        """Which plot tab is showing (axis limits apply to that plot)."""
        self.kind = kind
        self._show_limits()

    def _show_limits(self) -> None:
        self.lim_box.setTitle(f"Axis limits: {KIND_TITLES.get(self.kind, self.kind)}")
        self.lim_label.setText("Blank = automatic. Values in the plot's units.")
        lim = (self.opts.limits or {}).get(self.kind) or [None] * 4
        for e, v in zip(self.lims, lim):
            e.blockSignals(True)
            e.setText("" if v is None else f"{v:g}")
            e.blockSignals(False)
        for i, e in enumerate(self.lims):
            e.setEnabled(not (self.kind == "compare" and i < 2))  # x of the compare chart is the groups

    def _update_enabled(self) -> None:
        self.colors_btn.setEnabled(self.ws.color_by != RUN)
        self.bins.setEnabled(self.opts.psd_mode == "binned")
        self.sd_band.setEnabled(self.opts.display != "runs")

    # ------------------------------------------------------------------ widgets -> model
    def _edited(self, *_):
        if self._quiet:
            return
        ws, o = self.ws, self.opts
        old_avg = ws.average_by
        ws.average_by = self.average_by.currentData() or ws.average_by
        ws.color_by = self.color_by.currentData() or RUN
        ws.palette = self.palette.currentData()
        o.display = self.display.currentData()
        o.sd_band = self.sd_band.isChecked()
        o.units = self.units.currentData()
        o.log_diameter = self.logx.isChecked()
        o.psd_mode, o.psd_weighting = self.psd_mode.currentData()
        o.psd_bins = self.bins.value()
        o.compare_metric = self.metric.currentData()
        o.show_markers = self.markers.isChecked()
        o.title = self.titles.isChecked()
        o.line_width = self.line_width.value()
        o.legend = self.legend.currentData()
        regroup = ws.average_by != old_avg
        if regroup:
            ws.regroup()
        else:
            ws.restyle()
        self._update_enabled()
        self.changed.emit(regroup)

    def _limits_edited(self):
        vals = []
        for e in self.lims:
            t = e.text().strip().replace(",", ".")
            try:
                vals.append(float(t) if t else None)
            except ValueError:
                vals.append(None)
        lim = dict(self.opts.limits or {})
        if any(v is not None for v in vals):
            lim[self.kind] = vals
        else:
            lim.pop(self.kind, None)
        if lim != self.opts.limits:
            self.opts.limits = lim
            self.changed.emit(False)

    def _limits_reset(self):
        for e in self.lims:
            e.clear()
        self._limits_edited()
