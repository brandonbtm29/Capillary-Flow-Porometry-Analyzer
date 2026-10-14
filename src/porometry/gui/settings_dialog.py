"""Settings dialog: analysis options, QC thresholds, grouping."""

from __future__ import annotations

from dataclasses import replace

import html

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from .. import shortcuts
from ..analysis import Settings
from ..qc import QCSettings


def _dspin(value, lo, hi, step, decimals=3, suffix=""):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setDecimals(decimals)
    w.setValue(value)
    if suffix:
        w.setSuffix(suffix)
    return w


def _ispin(value, lo, hi):
    w = QSpinBox()
    w.setRange(lo, hi)
    w.setValue(value)
    return w


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, qc: QCSettings, group_mode: str, group_include_warn: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)

        # --- analysis
        box = QGroupBox("Analysis")
        f = QFormLayout(box)
        self.shape = _dspin(settings.shape_factor, 0.1, 1.5, 0.005)
        self.shape.setToolTip("0.715 reproduces CapRep/CapWin (D = 0.415·γ/ΔP). 1.0 = plain 4γ/ΔP.")
        f.addRow("Shape (tortuosity) factor", self.shape)
        self.bp = _dspin(settings.bubble_flow_threshold, 0, 1000, 0.5, 2, " cc/min")
        self.bp.setToolTip("Bubble point = first wet point with flow above this. 0 matches CapWin's log.")
        f.addRow("Bubble point flow threshold", self.bp)
        self.mindp = _dspin(settings.min_dp_kpa, 0, 20, 0.1, 2, " kPa")
        self.mindp.setToolTip("A wet point below this pressure is ignored when its flow is above the dry flow there "
                              "(a start-up blip). 0 matches CapRep exactly.")
        f.addRow("Ignore start-up blips below", self.mindp)
        self.small = _dspin(settings.smallest_pore_cff, 50, 100, 0.5, 1, " %")
        self.small.setToolTip("Smallest pore = first measured point where CFF reaches this. 98 % matches CapRep.")
        f.addRow("Smallest pore at CFF", self.small)
        self.clip = QCheckBox("Clip CFF to 0–100 % for the distribution")
        self.clip.setChecked(settings.clip_cff)
        f.addRow(self.clip)
        self.dry = QComboBox()
        self.dry.addItem("Linear interpolation (CapRep)", "interp")
        self.dry.addItem("Smooth quadratic fit through zero", "poly2")
        self.dry.setCurrentIndex(0 if settings.dry_model == "interp" else 1)
        f.addRow("Dry curve", self.dry)
        lay.addWidget(box)

        # --- QC
        box = QGroupBox("Data quality checks")
        f = QFormLayout(box)
        self.min_dry = _ispin(qc.min_dry_points, 1, 100)
        f.addRow("Minimum dry-curve points", self.min_dry)
        self.leak_win = _dspin(qc.leak_window_frac * 100, 0, 50, 1, 1, " % of range")
        f.addRow("Leak check window", self.leak_win)
        self.leak_cff = _dspin(qc.leak_cff, 1, 100, 1, 1, " %")
        f.addRow("Leak if CFF in window above", self.leak_cff)
        self.over = _dspin(qc.wet_above_dry_cff, 100, 200, 1, 1, " %")
        f.addRow("Wet-above-dry warning at CFF", self.over)
        self.closed = _dspin(qc.wet_meets_dry_cff, 50, 100, 1, 1, " %")
        f.addRow("Wet-meets-dry required CFF", self.closed)
        lay.addWidget(box)

        # --- grouping
        box = QGroupBox("Duplicates")
        f = QFormLayout(box)
        self.group = QComboBox()
        self.group.addItem("By file name (strip _TEST#, _S#)", "name")
        self.group.addItem("By folder", "folder")
        self.group.setCurrentIndex(0 if group_mode == "name" else 1)
        f.addRow("Group runs", self.group)
        self.inc_warn = QCheckBox("Include runs with warnings in group averages")
        self.inc_warn.setChecked(group_include_warn)
        f.addRow(self.inc_warn)
        f.addRow(QLabel("Runs that fail QC are never averaged."))
        lay.addWidget(box)

        # --- this computer
        box = QGroupBox("This computer")
        row = QHBoxLayout(box)
        info = QLabel(f"App icon {shortcuts.where()}.")
        info.setWordWrap(True)
        row.addWidget(info, 1)
        self.icon_btn = QPushButton("Create app icon")
        self.icon_btn.setToolTip("Makes (or remakes) the icon that starts this app. Use it again if the app folder moves.")
        self.icon_btn.clicked.connect(self._make_icon)
        row.addWidget(self.icon_btn)
        lay.addWidget(box)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        reset = QPushButton("Reset to defaults")
        btns.addButton(reset, QDialogButtonBox.ButtonRole.ResetRole)
        reset.clicked.connect(self._reset)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self._base_qc = qc

    def _make_icon(self):
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            made = shortcuts.create()
        except Exception as exc:
            QMessageBox.warning(self, "App icon", f"Could not create the app icon:\n{exc}")
            return
        finally:
            self.unsetCursor()
        paths = "".join(f"<li>{html.escape(str(p))}</li>" for p in made)
        QMessageBox.information(self, "App icon", f"Created the app icon {html.escape(shortcuts.where())}:<ul>{paths}</ul>")

    def _reset(self):
        s, q = Settings(), QCSettings()
        self.shape.setValue(s.shape_factor)
        self.bp.setValue(s.bubble_flow_threshold)
        self.mindp.setValue(s.min_dp_kpa)
        self.small.setValue(s.smallest_pore_cff)
        self.clip.setChecked(s.clip_cff)
        self.dry.setCurrentIndex(0)
        self.min_dry.setValue(q.min_dry_points)
        self.leak_win.setValue(q.leak_window_frac * 100)
        self.leak_cff.setValue(q.leak_cff)
        self.over.setValue(q.wet_above_dry_cff)
        self.closed.setValue(q.wet_meets_dry_cff)
        self.group.setCurrentIndex(0)
        self.inc_warn.setChecked(True)

    def values(self) -> tuple[Settings, QCSettings, str, bool]:
        s = Settings(
            shape_factor=self.shape.value(),
            bubble_flow_threshold=self.bp.value(),
            min_dp_kpa=self.mindp.value(),
            smallest_pore_cff=self.small.value(),
            clip_cff=self.clip.isChecked(),
            dry_model=self.dry.currentData(),
        )
        q = replace(
            self._base_qc,
            min_dry_points=self.min_dry.value(),
            leak_window_frac=self.leak_win.value() / 100,
            leak_cff=self.leak_cff.value(),
            wet_above_dry_cff=self.over.value(),
            wet_meets_dry_cff=self.closed.value(),
        )
        return s, q, self.group.currentData(), self.inc_warn.isChecked()
