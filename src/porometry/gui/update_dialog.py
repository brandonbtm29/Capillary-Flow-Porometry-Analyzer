"""Check for updates / update and restart."""

from __future__ import annotations

import html
from typing import Callable

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QPushButton, QTextBrowser, QVBoxLayout,
)

from .. import updater
from ..updater import UpdateInfo


class Worker(QThread):
    """Run `fn` off the GUI thread; `done` carries its result or the exception it raised."""
    done = pyqtSignal(object)
    progress = pyqtSignal(str)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            result = self.fn(self.progress.emit)
        except Exception as exc:  # handed to the GUI thread, shown to the user
            result = exc
        self.done.emit(result)


class UpdateDialog(QDialog):
    """Shows the current and latest version, what's new, and an Update button.

    After a successful update `updated_to` holds the new version and `restart` is True when the user
    chose to restart now.
    """

    def __init__(self, info: UpdateInfo | None, auto_check: bool, parent=None,
                 check: Callable[[], UpdateInfo] = updater.check, repo=None):
        super().__init__(parent)
        self.setWindowTitle("Updates")
        self.resize(620, 460)
        self.repo = updater.repo_root() if repo is None else repo
        self._check = check
        self.info = info
        self.updated_to: str | None = None
        self.restart = False
        self._worker: Worker | None = None

        lay = QVBoxLayout(self)
        self.headline = QLabel()
        self.headline.setWordWrap(True)
        lay.addWidget(self.headline)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        lay.addWidget(self.notes, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#52514e")
        lay.addWidget(self.status)
        self.auto = QCheckBox("Check for updates when the app starts")
        self.auto.setChecked(auto_check)
        lay.addWidget(self.auto)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.check_btn = QPushButton("Check again")
        self.update_btn = QPushButton("Update and restart")
        self.update_btn.setDefault(True)
        self.buttons.addButton(self.check_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.addButton(self.update_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.check_btn.clicked.connect(self.run_check)
        self.update_btn.clicked.connect(self.run_update)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        if info is None or info.error:
            self.run_check()
        else:
            self._show(info)

    # ------------------------------------------------------------------ check
    def run_check(self):
        self.headline.setText("Checking GitHub for a newer version…")
        self.notes.clear()
        self.status.clear()
        self._busy(True)
        self._start(lambda _progress: self._check(), self._checked)

    def _checked(self, result):
        self._busy(False)
        if isinstance(result, Exception):
            result = UpdateInfo(updater.__version__, error=str(result))
        self.info = result
        self._show(result)

    def _show(self, info: UpdateInfo):
        if info.error:
            self.headline.setText(f"<b>You have version {info.current}.</b> {html.escape(info.error)}")
            self.notes.setPlainText("Check your internet connection and try again.")
            self.update_btn.setVisible(False)
            return
        if not info.available:
            self.headline.setText(f"<b>You're up to date</b> (version {info.current}).")
            self.notes.setPlainText("")
            self.update_btn.setVisible(False)
            return
        self.headline.setText(f"<b>Version {info.latest} is available.</b> You have {info.current}.")
        self.notes.setMarkdown(info.notes or "See CHANGELOG.md on GitHub for what changed.")
        reason = updater.why_not(self.repo)
        self.update_btn.setVisible(True)
        self.update_btn.setEnabled(not reason)
        if reason:
            self.status.setText(f"Can't update automatically: {reason}")
        else:
            self.status.setText("Updating downloads the new version from GitHub and restarts the app with the "
                                "same runs loaded. Your data files and settings are not touched.")

    # ------------------------------------------------------------------ update
    def run_update(self):
        self._busy(True)
        self.status.setText("Updating…")
        self._start(lambda progress: updater.apply_update(self.repo, log=progress), self._updated)

    def _updated(self, result):
        self._busy(False)
        if isinstance(result, Exception):
            self.status.setText(f"<span style='color:#b3261e'>Update failed:</span> "
                                f"{html.escape(str(result)).replace(chr(10), '<br>')}")
            return
        self.updated_to = result
        self.restart = True
        self.accept()

    # ------------------------------------------------------------------ helpers
    def _start(self, fn, on_done):
        self._worker = Worker(fn, self)
        self._worker.progress.connect(self.status.setText)
        self._worker.done.connect(on_done)
        self._worker.start()

    def _busy(self, busy: bool):
        self.check_btn.setEnabled(not busy)
        self.update_btn.setEnabled(not busy)
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setEnabled(not busy)

    def reject(self):
        if self._worker is not None and self._worker.isRunning():
            return  # don't close mid-update
        super().reject()

    def closeEvent(self, ev):
        if self._worker is not None and self._worker.isRunning():
            ev.ignore()
            return
        super().closeEvent(ev)
