"""Run style (colour, marker, line, legend label) and per-group colours."""

from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..figures import LINESTYLES, MARKER_NAMES
from .models import color_icon

AUTO = "Automatic"


class ColorButton(QPushButton):
    """A button showing a colour swatch; click to pick. `color` is a hex string or None (automatic)."""

    def __init__(self, color: str | None, auto_color: str = "#888888", parent=None):
        super().__init__(parent)
        self.auto_color = auto_color
        self.color = color
        self.clicked.connect(self._pick)
        self._show()

    def _show(self):
        c = self.color or self.auto_color
        self.setIcon(color_icon(c, 16))
        self.setText(f"  {c}" + ("" if self.color else "  (automatic)"))

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.color or self.auto_color), self, "Pick a colour")
        if c.isValid():
            self.color = c.name()
            self._show()

    def reset(self):
        self.color = None
        self._show()


class StyleDialog(QDialog):
    """Style overrides for one or more runs. `values()` gives keyword arguments for Workspace.set_style
    (None = automatic)."""

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Run style")
        self.setMinimumWidth(420)
        self.entries = entries
        first = entries[0]
        common = {k: first.style.get(k) for k in ("color", "marker", "linestyle", "linewidth")
                  if all(e.style.get(k) == first.style.get(k) for e in entries)}
        lay = QVBoxLayout(self)
        names = ", ".join(e.name for e in entries[:4]) + (f" and {len(entries) - 4} more" if len(entries) > 4 else "")
        head = QLabel(f"<b>{len(entries)} run(s):</b> {names}")
        head.setWordWrap(True)
        lay.addWidget(head)
        f = QFormLayout()
        row = QHBoxLayout()
        self.color = ColorButton(common.get("color"), first.color)
        row.addWidget(self.color, 1)
        auto = QPushButton(AUTO)
        auto.clicked.connect(self.color.reset)
        row.addWidget(auto)
        w = QWidget()
        w.setLayout(row)
        f.addRow("Colour", w)
        self.marker = QComboBox()
        self.marker.addItem(AUTO, None)
        for k, v in MARKER_NAMES.items():
            self.marker.addItem(v, k)
        self.marker.setCurrentIndex(max(self.marker.findData(common.get("marker")), 0))
        f.addRow("Marker", self.marker)
        self.linestyle = QComboBox()
        self.linestyle.addItem(AUTO + " (dashed if QC fails)", None)
        for k, v in LINESTYLES.items():
            self.linestyle.addItem(v, k)
        self.linestyle.setCurrentIndex(max(self.linestyle.findData(common.get("linestyle")), 0))
        f.addRow("Line", self.linestyle)
        self.linewidth = QDoubleSpinBox()
        self.linewidth.setRange(0.0, 6.0)
        self.linewidth.setSingleStep(0.2)
        self.linewidth.setDecimals(1)
        self.linewidth.setSpecialValueText(AUTO)
        self.linewidth.setValue(common.get("linewidth") or 0.0)
        f.addRow("Line width", self.linewidth)
        self.label = QLineEdit(first.style.get("label", "") if len(entries) == 1 else "")
        self.label.setPlaceholderText(first.name if len(entries) == 1 else "(one run at a time)")
        self.label.setEnabled(len(entries) == 1)
        f.addRow("Legend label", self.label)
        lay.addLayout(f)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        reset = QPushButton("All automatic")
        reset.clicked.connect(self._all_auto)
        btns.addButton(reset, QDialogButtonBox.ButtonRole.ResetRole)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _all_auto(self):
        self.color.reset()
        self.marker.setCurrentIndex(0)
        self.linestyle.setCurrentIndex(0)
        self.linewidth.setValue(0)
        self.label.clear()

    def values(self) -> dict:
        out = {"color": self.color.color, "marker": self.marker.currentData(),
               "linestyle": self.linestyle.currentData(), "linewidth": self.linewidth.value() or None}
        if len(self.entries) == 1:
            out["label"] = self.label.text().strip() or None
        return out


class GroupColorsDialog(QDialog):
    """One colour per value of a field. `values()` -> {value: hex or None (automatic)}."""

    def __init__(self, field: str, values: list[str], current: dict[str, str], automatic: dict[str, str],
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Colours for {field}")
        self.resize(460, 380)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Colour for each <b>{field}</b>. Runs with that value share it."))
        self.table = QTableWidget(len(values), 2)
        self.table.setHorizontalHeaderLabels([field, "Colour"])
        self.table.verticalHeader().setVisible(False)
        self.buttons: dict[str, ColorButton] = {}
        for i, v in enumerate(values):
            self.table.setItem(i, 0, QTableWidgetItem(v or "(blank)"))
            b = ColorButton(current.get(v), automatic.get(v, "#888888"))
            self.buttons[v] = b
            self.table.setCellWidget(i, 1, b)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.resizeColumnToContents(0)
        lay.addWidget(self.table)
        self.auto = QCheckBox("Reset all to the palette's colours")
        lay.addWidget(self.auto)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def values(self) -> dict[str, str | None]:
        if self.auto.isChecked():
            return {v: None for v in self.buttons}
        return {v: b.color for v, b in self.buttons.items()}
