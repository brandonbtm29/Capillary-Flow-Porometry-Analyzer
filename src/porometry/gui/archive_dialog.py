"""Dialogs for archiving runs and restoring archived ones."""

from __future__ import annotations

import html
from pathlib import Path

from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ..archive import ARCHIVE_DIR, ArchivedRun


class ArchiveDialog(QDialog):
    """Confirm archiving the selected runs and ask for a reason."""

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Archive runs")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        names = "".join(f"<li>{html.escape(e.name)} <span style='color:#52514e'>(QC: {e.qc.status})</span></li>"
                        for e in entries)
        intro = QLabel(
            f"<p>Move {len(entries)} run file(s) into an <b>{ARCHIVE_DIR}</b> folder next to them?</p>"
            f"<ul style='margin-top:0'>{names}</ul>"
            "<p style='color:#52514e'>Nothing is deleted. Archived runs are skipped when you open the folder, "
            "so they drop out of plots, tables and group averages. Bring them back any time from "
            "<b>Archived runs…</b>.</p>")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addWidget(QLabel("Reason (saved in Archive/archive_log.csv):"))
        self.reason = QLineEdit()
        fails = [e.qc.summary() for e in entries if e.qc.status == "fail"]
        self.reason.setPlaceholderText("e.g. torn sample, leak at seal, practice run")
        if len(entries) == 1 and fails:
            self.reason.setText(f"QC fail: {fails[0]}")
        lay.addWidget(self.reason)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        ok = QPushButton("Archive")
        btns.addButton(ok, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def value(self) -> str:
        return self.reason.text().strip()


class ArchivedRunsDialog(QDialog):
    """List archived runs under the given folders; restore the selected ones."""

    def __init__(self, runs: list[ArchivedRun], folders: list[Path], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Archived runs")
        self.resize(900, 420)
        self.runs = runs
        self.restore_paths: list[Path] = []
        lay = QVBoxLayout(self)
        where = ", ".join(str(f) for f in folders) or "no folders opened yet"
        lay.addWidget(QLabel(f"Archived runs found under: <span style='color:#52514e'>{html.escape(where)}</span>"))
        self.table = QTableWidget(len(runs), 4)
        self.table.setHorizontalHeaderLabels(["Run", "Archived", "QC", "Reason"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        for i, r in enumerate(runs):
            item = QTableWidgetItem(r.path.stem)
            item.setToolTip(str(r.path))
            self.table.setItem(i, 0, item)
            self.table.setItem(i, 1, QTableWidgetItem(r.archived_at.replace("T", " ")))
            self.table.setItem(i, 2, QTableWidgetItem(r.qc))
            self.table.setItem(i, 3, QTableWidgetItem(r.reason))
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.resizeColumnsToContents()
        lay.addWidget(self.table)
        if not runs:
            lay.addWidget(QLabel("No archived runs here."))
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.restore_btn = QPushButton("Restore selected")
        self.restore_btn.setEnabled(bool(runs))
        btns.addButton(self.restore_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        self.restore_btn.clicked.connect(self._restore)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _restore(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        self.restore_paths = [self.runs[r].path for r in rows]
        self.accept()
