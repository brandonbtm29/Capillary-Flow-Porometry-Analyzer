"""Qt table model over a pandas DataFrame, with QC status icons."""

from __future__ import annotations

import math

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap

from ..figures import STATUS_COLORS

_ICONS: dict[str, QIcon] = {}


def status_icon(status: str) -> QIcon:
    """A small filled dot in the QC status colour (always shown next to the word)."""
    if status not in _ICONS:
        pm = QPixmap(12, 12)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(STATUS_COLORS.get(status, "#888888"))))
        p.setPen(QColor(0, 0, 0, 0))
        p.drawEllipse(1, 1, 10, 10)
        p.end()
        _ICONS[status] = QIcon(pm)
    return _ICONS[status]


def color_icon(color: str, size: int = 12) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(QColor(0, 0, 0, 0))
    p.drawRoundedRect(1, 3, size - 2, size - 6, 2, 2)
    p.end()
    return QIcon(pm)


class DataFrameModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()
        self.run_colors: dict[str, str] = {}

    def set_frame(self, df: pd.DataFrame, run_colors: dict[str, str] | None = None) -> None:
        self.beginResetModel()
        self._df = df.reset_index(drop=True)
        if run_colors is not None:
            self.run_colors = run_colors
        self.endResetModel()

    @property
    def frame(self) -> pd.DataFrame:
        return self._df

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        col = self._df.columns[index.column()]
        val = self._df.iat[index.row(), index.column()]
        missing = val is None or (isinstance(val, float) and math.isnan(val))
        if role == Qt.ItemDataRole.DisplayRole:
            if missing:
                return "—"
            if isinstance(val, float):
                return f"{val:.4g}" if abs(val) < 1e4 else f"{val:.0f}"
            return str(val)
        if role == Qt.ItemDataRole.UserRole:  # raw value for sorting
            return None if missing else val
        if role == Qt.ItemDataRole.DecorationRole:
            if col == "QC" and not missing:
                return status_icon(str(val))
            if col == "Run" and str(val) in self.run_colors:
                return color_icon(self.run_colors[str(val)])
        if role == Qt.ItemDataRole.ToolTipRole:
            if col in ("QC issues", "File", "Excluded (QC)") and not missing:
                return str(val)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)
