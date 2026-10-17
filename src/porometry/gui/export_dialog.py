"""Export a figure at a journal size, with a preview; or copy it to the clipboard."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from ..figures import KIND_TITLES, save_exact

CM = 1 / 2.54
# name -> (width cm, height cm, font pt)
SIZES = {
    "Single journal column (8.5 cm)": (8.5, 6.4, 8),
    "1.5 columns (14 cm)": (14.0, 9.0, 9),
    "Double column / full page width (17.8 cm)": (17.8, 10.5, 10),
    "Slide, 16:9 (25 cm)": (25.0, 14.0, 16),
    "Same as the app (16.5 cm)": (16.5, 10.7, 12),
    "Custom": None,
}
FORMATS = "PNG image (*.png);;TIFF image (*.tif);;SVG vector (*.svg);;PDF vector (*.pdf)"


def figure_png(fig, dpi: int, transparent: bool = False) -> bytes:
    buf = io.BytesIO()
    save_exact(fig, buf, format="png", dpi=dpi, transparent=transparent)
    return buf.getvalue()


def copy_figure(fig, dpi: int = 300) -> None:
    """Put a figure on the clipboard as an image (paste into Word, PowerPoint, OneNote, ...)."""
    QApplication.clipboard().setImage(QImage.fromData(figure_png(fig, dpi)))


class ExportDialog(QDialog):
    """`render(kind, (w_in, h_in), font_pt, titles)` returns a matplotlib Figure. `prefs` is updated in place."""

    def __init__(self, render: Callable, kind: str, prefs: dict, start_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export figure")
        self.resize(900, 600)
        self.render, self.prefs, self.start_dir = render, prefs, start_dir
        self.saved: Path | None = None
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        f = QFormLayout()
        self.kind = QComboBox()
        for k, t in KIND_TITLES.items():
            self.kind.addItem(t, k)
        self.kind.setCurrentIndex(max(self.kind.findData(kind), 0))
        f.addRow("Plot", self.kind)
        self.size = QComboBox()
        for name in SIZES:
            self.size.addItem(name, name)
        self.size.setCurrentIndex(max(self.size.findData(prefs.get("size", "Single journal column (8.5 cm)")), 0))
        f.addRow("Size", self.size)
        self.w = self._spin(prefs.get("w", 8.5), 3, 60, " cm")
        self.h = self._spin(prefs.get("h", 6.4), 3, 60, " cm")
        f.addRow("Width", self.w)
        self.h_label = QLabel("Height")
        f.addRow(self.h_label, self.h)
        self.font = self._spin(prefs.get("font", 8), 5, 30, " pt", 1, 0.5)
        f.addRow("Font size", self.font)
        self.dpi = QComboBox()
        for d in (300, 600, 1200):
            self.dpi.addItem(f"{d} dpi", d)
        self.dpi.setCurrentIndex(max(self.dpi.findData(prefs.get("dpi", 600)), 0))
        self.dpi.setToolTip("For PNG/TIFF. Most journals ask for 300 (photos) to 600-1200 (line art) dpi.")
        f.addRow("Resolution", self.dpi)
        self.titles = QCheckBox("Include plot titles")
        self.titles.setToolTip("Journal figures usually leave the title to the caption")
        self.titles.setChecked(bool(prefs.get("titles", False)))
        f.addRow(self.titles)
        self.transparent = QCheckBox("Transparent background")
        self.transparent.setChecked(bool(prefs.get("transparent", False)))
        f.addRow(self.transparent)
        left.addLayout(f)
        tip = QLabel("SVG and PDF stay sharp at any size and keep text editable. Uses the current plot settings "
                     "(runs shown, colours, legend, axis limits).")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#52514e")
        left.addWidget(tip)
        left.addStretch(1)
        btns = QDialogButtonBox()
        self.save_btn = QPushButton("Save…")
        self.copy_btn = QPushButton("Copy to clipboard")
        btns.addButton(self.save_btn, QDialogButtonBox.ButtonRole.ActionRole)
        btns.addButton(self.copy_btn, QDialogButtonBox.ButtonRole.ActionRole)
        btns.addButton(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        self.save_btn.clicked.connect(self.save)
        self.copy_btn.clicked.connect(self.copy)
        left.addWidget(btns)
        lay.addLayout(left, 0)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 400)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setStyleSheet("background:#f4f3ef; border:1px solid #d6d5cf")
        lay.addWidget(self.preview, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_preview)
        self.size.currentIndexChanged.connect(self._preset)
        for w in (self.w, self.h, self.font):
            w.valueChanged.connect(self._custom)
        self.kind.currentIndexChanged.connect(self._changed)
        self.transparent.toggled.connect(self._changed)
        self.titles.toggled.connect(self._changed)
        self._quiet = False
        self._preset() if self.size.currentData() != "Custom" else self._changed()

    @staticmethod
    def _spin(value, lo, hi, suffix, decimals=1, step=0.5):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(decimals)
        s.setSingleStep(step)
        s.setSuffix(suffix)
        s.setValue(float(value))
        return s

    # ------------------------------------------------------------------ state
    def _preset(self):
        spec = SIZES.get(self.size.currentData())
        if spec:
            self._quiet = True
            self.w.setValue(spec[0])
            self.h.setValue(spec[1])
            self.font.setValue(spec[2])
            self._quiet = False
        self._changed()

    def _custom(self):
        if self._quiet:
            return
        spec = SIZES.get(self.size.currentData())
        if spec and (self.w.value(), self.h.value(), self.font.value()) != spec:
            self.size.blockSignals(True)
            self.size.setCurrentIndex(self.size.findData("Custom"))
            self.size.blockSignals(False)
        self._changed()

    def _changed(self):
        self.h_label.setText("Height per panel" if self.kind.currentData() == "all" else "Height")
        self.prefs.update(size=self.size.currentData(), w=self.w.value(), h=self.h.value(), font=self.font.value(),
                          dpi=self.dpi.currentData(), transparent=self.transparent.isChecked(),
                          titles=self.titles.isChecked())
        self._timer.start()

    def figure(self):
        return self.render(self.kind.currentData(), (self.w.value() * CM, self.h.value() * CM), self.font.value(),
                           self.titles.isChecked())

    def _update_preview(self):
        fig = self.figure()
        img = QImage.fromData(figure_png(fig, 110, self.transparent.isChecked()))
        pm = QPixmap.fromImage(img)
        area = self.preview.size()
        if pm.width() > area.width() - 10 or pm.height() > area.height() - 10:
            pm = pm.scaled(area.width() - 10, area.height() - 10, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pm)
        self.preview.setToolTip(f"Shown at about screen size. Saved at {self.w.value():g} × "
                                f"{self.h.value():g} cm, {self.font.value():g} pt text.")

    # ------------------------------------------------------------------ actions
    def save(self, path: str | None = None):
        self.prefs["dpi"] = self.dpi.currentData()
        if not path:
            name = f"porometry_{self.kind.currentData()}.{self.prefs.get('ext', 'png')}"
            path, _ = QFileDialog.getSaveFileName(self, "Save figure", str(Path(self.start_dir) / name), FORMATS)
            if not path:
                return None
        p = Path(path)
        if p.suffix.lower() not in (".png", ".tif", ".tiff", ".svg", ".pdf"):
            p = p.with_suffix(".png")
        try:
            save_exact(self.figure(), p, dpi=self.dpi.currentData(), transparent=self.transparent.isChecked())
        except PermissionError:
            QMessageBox.warning(self, "Could not save", f"{p} is open in another program. Close it and try again.")
            return None
        self.prefs["ext"] = p.suffix.lower().lstrip(".")
        self.saved = p
        return p

    def copy(self):
        copy_figure(self.figure(), min(self.dpi.currentData(), 600))
        self.copy_btn.setText("Copied ✓")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy to clipboard"))
