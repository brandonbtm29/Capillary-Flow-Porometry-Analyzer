"""Entry point: `porometry` (or `python -m porometry`)."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from PyQt6.QtWidgets import QApplication

    from .main_window import MainWindow

    from pathlib import Path

    from PyQt6.QtGui import QIcon

    if sys.platform == "win32":
        # own taskbar entry and icon instead of Python's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PorometryAnalyzer.App")
        except (AttributeError, OSError):
            pass

    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("Porometry Analyzer")
    app.setOrganizationName("PorometryAnalyzer")
    res = Path(__file__).parent / "resources"
    icon = QIcon(str(res / "porometry.ico")) if (res / "porometry.ico").exists() else QIcon(str(res / "porometry_256.png"))
    app.setWindowIcon(icon)
    win = MainWindow()
    if len(argv) > 1:  # files or folders given on the command line / dropped on the shortcut
        win.load_paths(argv[1:])
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
