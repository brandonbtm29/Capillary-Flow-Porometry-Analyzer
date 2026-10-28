"""Entry point: `porometry` (or `python -m porometry`)."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from .. import __version__, crash_log, single_instance

    # Errors go to a per-user log folder (the app has no data folder of its own):
    # %LOCALAPPDATA%\PorometryAnalyzer\logs on Windows, ~/Library/Logs/PorometryAnalyzer on macOS.
    crash_log.setup("porometry", crash_log.user_log_dir("PorometryAnalyzer"), __version__)

    from pathlib import Path

    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    from ..shortcuts import APP_NAME
    from .main_window import MainWindow

    if sys.platform == "win32":
        # own taskbar entry and icon instead of Python's
        try:
            import ctypes

            from ..shortcuts import (
                APP_ID,  # the shortcuts carry the same ID, so a pinned icon and the window are one button
            )
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass

    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("PorometryAnalyzer")
    # One copy at a time. If one is already running, it comes to the front and this one quits; files or
    # folders given to this copy are not passed on to it (open them there instead).
    guard = single_instance.acquire(APP_NAME)
    if guard is None:
        return 0
    res = Path(__file__).parent / "resources"
    icon = QIcon(str(res / "porometry.ico")) if (res / "porometry.ico").exists() else QIcon(str(res / "porometry_256.png"))
    app.setWindowIcon(icon)
    win = MainWindow(check_updates=True)
    guard.set_window(win)  # the window to bring forward when the app is opened again
    if len(argv) > 1:  # files or folders given on the command line / dropped on the shortcut
        win.load_paths(argv[1:])
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
