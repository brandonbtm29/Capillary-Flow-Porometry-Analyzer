"""Main window: runs (with tags) on the left, plots and tables in the middle, plot options on the right."""

from __future__ import annotations

import html
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PyQt6.QtCore import QByteArray, QProcess, QSettings, QSortFilterProxyModel, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QActionGroup, QDesktopServices, QFont, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDockWidget, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter, QStyle, QStyledItemDelegate, QTableView, QTabWidget,
    QTextBrowser, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import __version__, session, shortcuts, updater
from ..analysis import Settings
from ..archive import ArchiveError, list_archived
from ..cft import PSI_TO_KPA
from ..export import figure_for, write_summary
from ..figures import DRAWERS, KIND_TITLES, STATUS_COLORS, PlotOptions, apply_style, palette_colors
from ..qc import Level, QCSettings
from ..tags import sort_key
from ..workspace import RUN, Entry, Workspace
from .archive_dialog import ArchiveDialog, ArchivedRunsDialog
from .export_dialog import ExportDialog, copy_figure
from .models import DataFrameModel, color_icon, status_icon
from .plot_panel import DISPLAY, PlotOptionsPanel
from .settings_dialog import SettingsDialog
from .style_dialog import GroupColorsDialog, StyleDialog
from .update_dialog import UpdateDialog, Worker

NAME_ROLE = Qt.ItemDataRole.UserRole + 1
PLOTS = [("flow", "Flow vs pressure"), ("cff", "Cumulative filter flow"), ("psd", "Pore size distribution"),
         ("compare", "Compare groups")]
REPO_URL = "https://github.com/" + updater.REPO
MAX_RECENT = 8
SETTINGS_ENV = "POROMETRY_SETTINGS_FILE"  # tests point this at a temporary file


def app_settings() -> QSettings:
    """The app's saved settings (registry on Windows, a plist on macOS), or a test file."""
    path = os.environ.get(SETTINGS_ENV)
    if path:
        return QSettings(path, QSettings.Format.IniFormat)
    return QSettings("PorometryAnalyzer", "PorometryAnalyzer")


class SortProxy(QSortFilterProxyModel):
    """Sorts numbers as numbers and puts empty cells last."""

    def lessThan(self, left, right):
        a = self.sourceModel().data(left, Qt.ItemDataRole.UserRole)
        b = self.sourceModel().data(right, Qt.ItemDataRole.UserRole)
        if a is None:
            return False
        if b is None:
            return True
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class PlotPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(NavigationToolbar2QT(self.canvas, self))
        lay.addWidget(self.canvas)


class TagDelegate(QStyledItemDelegate):
    """Only tag cells of run rows can be edited (not the run name, the QC column or group rows)."""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window = window

    def createEditor(self, parent, option, index):
        item = self.window.tree.itemFromIndex(index)
        if item is None or item.data(0, NAME_ROLE) is None or not self.window._is_tag_column(index.column()):
            return None
        return super().createEditor(parent, option, index)


class MainWindow(QMainWindow):
    def __init__(self, check_updates: bool = False):
        super().__init__()
        apply_style()
        self.resize(1500, 920)
        self.setAcceptDrops(True)
        self.qs = app_settings()
        self.ws = Workspace()
        self.group_include_warn = True
        self.highlight: str | None = None
        self.session_path: Path | None = None
        self._folders: set[Path] = set()  # folders opened this session (where to look for archived runs)
        self._building = False
        self._update_info: updater.UpdateInfo | None = None
        self._update_worker: Worker | None = None
        self.actions: dict[str, QAction] = {}
        self._load_prefs()
        self._build_ui()
        self._update_title()
        self._refresh_all()
        if check_updates and self._auto_update_check():
            QTimer.singleShot(2000, self._background_update_check)

    # ================================================================== UI
    def _act(self, key: str, text: str, slot, shortcut=None, tip: str | None = None, icon=None,
             checkable: bool = False) -> QAction:
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        if icon is not None:
            a.setIcon(self.style().standardIcon(icon))
        a.setCheckable(checkable)
        self.actions[key] = a
        return a

    def _build_ui(self):
        SP = QStyle.StandardPixmap
        A = self._act
        A("open_folder", "Open folder…", self.open_folder, "Ctrl+O", "Load every .CFT file in a folder and its subfolders",
          SP.SP_DirOpenIcon)
        A("add_files", "Add files…", self.add_files, "Ctrl+Shift+O", "Add individual .CFT files", SP.SP_FileIcon)
        A("open_session", "Open session…", lambda: self.open_session(), None,
          "Reopen saved runs, groups, colours and plot settings")
        A("save_session", "Save session", self.save_session, "Ctrl+S",
          "Save the loaded runs, what's shown, colours and plot settings to a .cfpa file", SP.SP_DialogSaveButton)
        A("save_session_as", "Save session as…", self.save_session_as, "Ctrl+Shift+S")
        A("export_summary", "Export summary…", self.export_summary, "Ctrl+E",
          "Excel: summary, group averages, statistics, QC and one sheet per run")
        A("export_figure", "Export figure…", self.export_figure, "Ctrl+Shift+E",
          "Save a plot at a journal size (with preview)")
        A("copy_figure", "Copy figure", self.copy_figure, "Ctrl+Shift+C",
          "Copy the current plot to the clipboard at the last export size")
        A("quit", "Quit", self.close, "Ctrl+Q").setMenuRole(QAction.MenuRole.QuitRole)
        A("set_field", "Set field for selected…", lambda: self.set_field_dialog(None), "Ctrl+G",
          "Give the selected runs the same value of a field (e.g. Condition)")
        A("add_field", "Add field…", self.add_field)
        A("reset_tags", "Reset tags to automatic", self.reset_tags)
        A("style", "Style…", self.style_selected, "Ctrl+L", "Colour, marker, line and legend label of the selected runs")
        A("reset_style", "Reset style", self.reset_style)
        A("group_colors", "Group colours…", self.edit_group_colors)
        A("show_all", "Show all", lambda: self._set_visible(lambda e: True))
        A("hide_all", "Hide all", lambda: self._set_visible(lambda e: False))
        A("hide_fails", "Hide QC fails", lambda: self._set_visible(lambda e: e.qc.level < Level.FAIL))
        A("show_only", "Show only selected", self.show_only_selected)
        A("remove", "Remove from list", self.remove_selected, "Delete",
          "Drop the selected runs from this session's list. The files are not touched and load again next time.")
        A("archive", "Archive…", self.archive_selected, "Ctrl+Shift+A",
          "Move the selected runs' .CFT files into an Archive folder next to them, with a reason", SP.SP_TrashIcon)
        A("archived", "Archived runs…", self.show_archived, None, "List archived runs in the opened folders and restore them")
        A("clear", "Clear list", self.clear_all)
        A("settings", "Settings…", self.open_settings, "Ctrl+,", "Analysis options and data quality checks",
          SP.SP_FileDialogDetailedView).setMenuRole(QAction.MenuRole.PreferencesRole)
        A("app_icon", "Create app icon", self.make_app_icon, None, f"Put the app icon {shortcuts.where()}")
        A("updates", "Check for updates…", self.show_updates, None,
          "Check GitHub for a newer version of the app and install it")
        A("whats_new", "What's new", self.show_changelog)
        A("guide", "User guide (online)", lambda: QDesktopServices.openUrl(QUrl(REPO_URL + "#readme")))
        A("report", "Report a problem…", lambda: QDesktopServices.openUrl(QUrl(REPO_URL + "/issues/new")))
        A("about", "About", self.show_about).setMenuRole(QAction.MenuRole.AboutRole)
        for key, text in (("logx", "Log diameter axis"), ("markers", "Markers on curves"), ("titles", "Plot titles")):
            A(key, text, lambda checked, k=key: self._menu_toggle(k, checked), checkable=True)

        # ---- menu bar
        mb = self.menuBar()
        m = mb.addMenu("&File")
        for k in ("open_folder", "add_files"):
            m.addAction(self.actions[k])
        m.addSeparator()
        m.addAction(self.actions["open_session"])
        self.recent_menu = m.addMenu("Recent sessions")
        m.addAction(self.actions["save_session"])
        m.addAction(self.actions["save_session_as"])
        m.addSeparator()
        for k in ("export_summary", "export_figure", "copy_figure"):
            m.addAction(self.actions[k])
        m.addSeparator()
        m.addAction(self.actions["quit"])

        m = mb.addMenu("&Runs")
        self.field_menu = m.addMenu("Set field for selected")
        m.addAction(self.actions["add_field"])
        m.addAction(self.actions["reset_tags"])
        m.addSeparator()
        for k in ("style", "reset_style", "group_colors"):
            m.addAction(self.actions[k])
        m.addSeparator()
        for k in ("show_all", "hide_all", "hide_fails", "show_only"):
            m.addAction(self.actions[k])
        m.addSeparator()
        for k in ("remove", "archive", "archived", "clear"):
            m.addAction(self.actions[k])

        self.plot_menu = m = mb.addMenu("&Plot")
        show = m.addMenu("Show")
        self.display_group = QActionGroup(self)
        for key, text in DISPLAY.items():
            a = QAction(text, self, checkable=True)
            a.setData(key)
            a.triggered.connect(lambda _c, k=key: self._menu_display(k))
            self.display_group.addAction(a)
            show.addAction(a)
        units = m.addMenu("Pressure units")
        self.units_group = QActionGroup(self)
        for u in ("kPa", "psi"):
            a = QAction(u, self, checkable=True)
            a.setData(u)
            a.triggered.connect(lambda _c, u=u: self._menu_units(u))
            self.units_group.addAction(a)
            units.addAction(a)
        for k in ("logx", "markers", "titles"):
            m.addAction(self.actions[k])
        m.addSeparator()

        m = mb.addMenu("&Tools")
        m.addAction(self.actions["settings"])
        m.addAction(self.actions["app_icon"])

        m = mb.addMenu("&Help")
        for k in ("updates", "whats_new", "guide", "report"):
            m.addAction(self.actions[k])
        m.addSeparator()
        m.addAction(self.actions["about"])

        # ---- slim toolbar
        tb = QToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for k in ("open_folder", "add_files", "save_session", None, "export_summary", "export_figure", "copy_figure",
                  None, "archive", None, "settings"):
            if k is None:
                tb.addSeparator()
            else:
                tb.addAction(self.actions[k])
        self.addToolBar(tb)

        # ---- left: runs + details
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 6, 0, 6)
        self.list_head = QLabel()
        self.list_head.setWordWrap(True)
        ll.addWidget(self.list_head)
        self.tree = QTreeWidget()
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                  | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.tree.setItemDelegate(TagDelegate(self))
        self.tree.itemChanged.connect(self._tree_changed)
        self.tree.currentItemChanged.connect(self._tree_selected)
        ll.addWidget(self.tree, 3)
        row = QHBoxLayout()
        for text, key in (("Show all", "show_all"), ("Hide all", "hide_all"), ("Hide QC fails", "hide_fails")):
            b = QPushButton(text)
            b.clicked.connect(self.actions[key].trigger)
            row.addWidget(b)
        ll.addLayout(row)
        row2 = QHBoxLayout()
        self.set_field_btn = QPushButton()
        self.set_field_btn.setToolTip("Give the selected runs the same value (Ctrl/Shift-click to select several). "
                                      "Double-click a cell to edit one run. Right-click for more.")
        self.set_field_btn.clicked.connect(lambda: self.set_field_dialog(self.ws.average_by))
        row2.addWidget(self.set_field_btn)
        style_btn = QPushButton("Style…")
        style_btn.setToolTip("Colour, marker, line and legend label of the selected runs")
        style_btn.clicked.connect(self.style_selected)
        row2.addWidget(style_btn)
        ll.addLayout(row2)
        ll.addWidget(QLabel("<b>Run details</b>"))
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(False)
        ll.addWidget(self.details, 2)

        # ---- middle: plots over tables
        self.plot_tabs = QTabWidget()
        self.panels: dict[str, PlotPanel] = {}
        for key, title in PLOTS:
            p = PlotPanel()
            self.panels[key] = p
            self.plot_tabs.addTab(p, title)

        self.table_tabs = QTabWidget()
        self.run_model = DataFrameModel()
        self.group_model = DataFrameModel()
        self.stats_model = DataFrameModel()
        self.run_view = self._make_table(self.run_model)
        self.run_view.selectionModel().currentRowChanged.connect(self._table_selected)
        self.group_view = self._make_table(self.group_model)
        self.stats_view = self._make_table(self.stats_model, sortable=False)
        self.table_tabs.addTab(self.run_view, "Runs")
        self.table_tabs.addTab(self.group_view, "Groups (mean ± SD)")
        self.table_tabs.addTab(self.stats_view, "Statistics")

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.plot_tabs)
        right.addWidget(self.table_tabs)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([430, 800])
        self.setCentralWidget(split)

        # ---- right: plot options dock
        self.options = PlotOptionsPanel(self.ws, self.plot_opts)
        self.options.changed.connect(self._options_changed)
        self.options.edit_colors.connect(self.edit_group_colors)
        self.dock = QDockWidget("Plot options", self)
        self.dock.setObjectName("plot_options_dock")
        self.dock.setWidget(self.options)
        self.dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                              | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.setMinimumWidth(280)
        toggle = self.dock.toggleViewAction()
        toggle.setText("Plot options panel")
        self.plot_menu.addAction(toggle)
        self.actions["plot_panel"] = toggle
        self.plot_tabs.currentChanged.connect(self._tab_changed)

        self.statusBar().showMessage("Open a folder of .CFT files, or drag files or folders onto this window.")
        self.version_label = QLabel(f"v{__version__}  ")
        self.version_label.setToolTip("Click to check for updates")
        self.version_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.version_label.mousePressEvent = lambda _ev: self.show_updates()
        self.statusBar().addPermanentWidget(self.version_label)

        geo = self.qs.value("geometry")
        if isinstance(geo, QByteArray):
            self.restoreGeometry(geo)
        state = self.qs.value("window_state_v2")
        if isinstance(state, QByteArray):
            self.restoreState(state)
        self._rebuild_recent()
        self._sync_menus()

    def _make_table(self, model, sortable: bool = True) -> QTableView:
        proxy = SortProxy(self)
        proxy.setSourceModel(model)
        v = QTableView()
        v.setModel(proxy)
        v.setSortingEnabled(sortable)
        v.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        v.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        v.setAlternatingRowColors(True)
        v.verticalHeader().setVisible(False)
        v.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        v.setWordWrap(False)
        if sortable:
            v.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        return v

    # ================================================================== prefs
    def _load_prefs(self):
        self.plot_opts = PlotOptions()
        self.export_prefs: dict = {}
        try:
            o = json.loads(self.qs.value("plot_options", "{}") or "{}")
            self.plot_opts = PlotOptions(**{k: v for k, v in o.items() if k in asdict(PlotOptions())})
            s = json.loads(self.qs.value("analysis_v2", "{}") or "{}")
            self.ws.settings = Settings(**{k: v for k, v in s.items() if k in asdict(Settings())})
            q = json.loads(self.qs.value("qc", "{}") or "{}")
            self.ws.qc_settings = QCSettings(**{k: v for k, v in q.items() if k in asdict(QCSettings())})
            self.group_include_warn = self.qs.value("group_include_warn", "true") in ("true", True)
            v = json.loads(self.qs.value("view_v1", "{}") or "{}")
            if v.get("fields"):
                self.ws.fields = list(dict.fromkeys(v["fields"]))
            self.ws.average_by = v.get("average_by", self.ws.average_by)
            self.ws.color_by = v.get("color_by", self.ws.color_by)
            self.ws.palette = v.get("palette", self.ws.palette)
            self.ws.value_colors = dict(v.get("value_colors") or {})
            self.ws.run_styles = dict(v.get("run_styles") or {})
            # pre-0.4 'mark as duplicates' groups: applied as Condition tags when those runs load
            self.ws.legacy_groups = dict(json.loads(self.qs.value("group_overrides", "{}") or "{}"))
            self.export_prefs = dict(json.loads(self.qs.value("export_v1", "{}") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        if self.ws.average_by not in self.ws.fields:
            self.ws.average_by = "Condition"
        if self.ws.color_by != RUN and self.ws.color_by not in self.ws.fields:
            self.ws.color_by = RUN

    def _save_prefs(self):
        self.qs.setValue("plot_options", json.dumps(asdict(self.plot_opts)))
        self.qs.setValue("analysis_v2", json.dumps(asdict(self.ws.settings)))
        self.qs.setValue("qc", json.dumps(asdict(self.ws.qc_settings)))
        self.qs.setValue("group_include_warn", "true" if self.group_include_warn else "false")
        self.qs.setValue("view_v1", json.dumps({
            "fields": self.ws.fields, "average_by": self.ws.average_by, "color_by": self.ws.color_by,
            "palette": self.ws.palette, "value_colors": self.ws.value_colors, "run_styles": self.ws.run_styles}))
        self.qs.setValue("group_overrides", json.dumps(self.ws.legacy_groups))
        self.qs.setValue("export_v1", json.dumps(self.export_prefs))
        self.qs.setValue("geometry", self.saveGeometry())
        self.qs.setValue("window_state_v2", self.saveState())

    def closeEvent(self, ev):
        self._save_prefs()
        super().closeEvent(ev)

    @property
    def max_level(self) -> Level:
        return Level.WARN if self.group_include_warn else Level.INFO

    # ================================================================== loading
    def _last_dir(self) -> str:
        return self.qs.value("last_dir", "C:/CFP-1500AEX/StudentData" if Path("C:/CFP-1500AEX").exists() else str(Path.home()))

    def open_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Open folder of .CFT files", self._last_dir())
        if d:
            self.qs.setValue("last_dir", d)
            self._folders.add(Path(d))
            self._load(lambda: self.ws.add_folder(d))

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add .CFT files", self._last_dir(),
                                                "CapWin data (*.cft *.CFT);;All files (*)")
        if files:
            self.qs.setValue("last_dir", str(Path(files[0]).parent))
            self._load(lambda: self.ws.add_files(files))

    def load_paths(self, paths):
        sessions = [p for p in map(Path, paths) if p.suffix.lower() == session.SUFFIX]
        if sessions:
            self.open_session(sessions[0])
            return

        def go():
            added = []
            for p in map(Path, paths):
                if p.is_dir():
                    self._folders.add(p)
                    added += self.ws.add_folder(p)
                elif p.suffix.lower() == ".cft":
                    added += self.ws.add_files([p])
            return added
        self._load(go)

    def _load(self, fn):
        n_err = len(self.ws.errors)
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            added = fn()
        finally:
            self.unsetCursor()
        self.options.sync()
        self._refresh_all()
        self._warn_tag_writes()
        new_err = self.ws.errors[n_err:]
        if new_err:
            msg = "\n".join(f"{p.name}: {e}" for p, e in new_err[:15])
            QMessageBox.warning(self, "Some files could not be read", msg)
        if not added and not new_err:
            self.statusBar().showMessage("No new .CFT files found.", 5000)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        self.load_paths([u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()])

    def _warn_tag_writes(self):
        errs = getattr(self.ws.tag_store, "write_errors", [])
        if errs:
            QMessageBox.warning(self, "Tags not saved to the folder",
                                "These folders can't be written, so tag changes there last only until you close "
                                "the app:\n\n" + "\n".join(errs[:5]))
            errs.clear()

    # ================================================================== sessions
    def _update_title(self):
        name = f" — {self.session_path.name}" if self.session_path else ""
        self.setWindowTitle(f"Capillary Flow Porometry Analyzer {__version__}{name}")

    def save_session(self):
        if self.session_path is None:
            return self.save_session_as()
        return self._write_session(self.session_path)

    def save_session_as(self):
        start = str(self.session_path or Path(self._last_dir()) / f"porometry_session{session.SUFFIX}")
        path, _ = QFileDialog.getSaveFileName(self, "Save session", start,
                                              f"Porometry session (*{session.SUFFIX})")
        if not path:
            return None
        return self._write_session(Path(path))

    def _write_session(self, path: Path) -> Path | None:
        try:
            out = session.save(path, self.ws, self.plot_opts, folders=sorted(self._folders), highlight=self.highlight,
                               tab=self.plot_tabs.currentIndex(), group_include_warn=self.group_include_warn)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save the session", str(exc))
            return None
        self.session_path = out
        self._remember_recent(out)
        self._update_title()
        self.statusBar().showMessage(f"Saved session {out}", 8000)
        return out

    def open_session(self, path: str | Path | None = None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open session", self._last_dir(),
                                                  f"Porometry session (*{session.SUFFIX});;All files (*)")
            if not path:
                return
        try:
            loaded = session.load(path)
        except session.SessionError as exc:
            QMessageBox.warning(self, "Open session", str(exc))
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            session.apply(loaded, self.ws)
        finally:
            self.unsetCursor()
        self.plot_opts = loaded.plot_options
        self.options.opts = self.plot_opts
        self.group_include_warn = loaded.group_include_warn
        self._folders = set(loaded.folders)
        self.highlight = loaded.highlight if any(e.name == loaded.highlight for e in self.ws.entries) else None
        self.session_path = loaded.path
        self._remember_recent(loaded.path)
        self.options.sync()
        self.plot_tabs.setCurrentIndex(min(loaded.tab, self.plot_tabs.count() - 1))
        self._update_title()
        self._refresh_all()
        if loaded.missing:
            QMessageBox.warning(self, "Some runs were not found",
                                "These files from the session are no longer there (moved, renamed or archived):\n\n"
                                + "\n".join(loaded.missing[:15]))

    def _remember_recent(self, path: Path):
        try:
            recent = json.loads(self.qs.value("recent_sessions", "[]") or "[]")
        except (TypeError, json.JSONDecodeError):
            recent = []
        recent = [p for p in recent if p != str(path)]
        recent.insert(0, str(path))
        self.qs.setValue("recent_sessions", json.dumps(recent[:MAX_RECENT]))
        self._rebuild_recent()

    def _rebuild_recent(self):
        self.recent_menu.clear()
        try:
            recent = json.loads(self.qs.value("recent_sessions", "[]") or "[]")
        except (TypeError, json.JSONDecodeError):
            recent = []
        for p in recent:
            a = self.recent_menu.addAction(Path(p).name, lambda p=p: self.open_session(p))
            a.setToolTip(p)
            a.setEnabled(Path(p).exists())
        self.recent_menu.setEnabled(bool(recent))

    # ================================================================== remove / archive
    def remove_selected(self):
        sel = self._selected_or_current()
        for e in sel:
            self.ws.remove(e)
        if sel:
            self.highlight = None
            self._refresh_all()

    def archive_selected(self):
        sel = self._selected_or_current()
        if not sel:
            QMessageBox.information(self, "Archive", "Select the runs to archive first (Ctrl- or Shift-click).")
            return
        dlg = ArchiveDialog(sel, self)
        if not dlg.exec():
            return
        self._folders.update(e.path.parent for e in sel)
        try:
            moved = self.ws.archive(sel, dlg.value())
        except ArchiveError as exc:
            QMessageBox.warning(self, "Archive", f"Could not archive every run:\n{exc}")
            moved = None
        self.highlight = None
        self._save_prefs()
        self._refresh_all()
        if moved:
            self.statusBar().showMessage(f"Archived {len(moved)} run(s) to {moved[0].parent}", 8000)

    def _archive_search_folders(self) -> list[Path]:
        folders = set(self._folders) | {e.path.parent for e in self.ws.entries}
        last = Path(self._last_dir())
        if last.is_dir():
            folders.add(last)
        # drop folders already covered by a parent in the set
        return sorted(f for f in folders if not any(p != f and p in f.parents for p in folders))

    def show_archived(self):
        folders = self._archive_search_folders()
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            runs = list_archived(folders)
        finally:
            self.unsetCursor()
        dlg = ArchivedRunsDialog(runs, folders, self)
        if not dlg.exec() or not dlg.restore_paths:
            return
        try:
            restored = self.ws.restore(dlg.restore_paths)
        except ArchiveError as exc:
            QMessageBox.warning(self, "Restore", str(exc))
            return
        self._save_prefs()
        self._load(lambda: self.ws.add_files(restored))
        self.statusBar().showMessage(f"Restored and loaded {len(restored)} run(s)", 8000)

    # ================================================================== tags
    def _selected_entries(self) -> list[Entry]:
        out = []
        for it in self.tree.selectedItems():
            name = it.data(0, NAME_ROLE)
            if name is None:  # a group row selects its runs
                out += [self._entry(it.child(i).data(0, NAME_ROLE)) for i in range(it.childCount())]
            else:
                out.append(self._entry(name))
        seen, uniq = set(), []
        for e in out:
            if e is not None and e.name not in seen:
                seen.add(e.name)
                uniq.append(e)
        return uniq

    def _selected_or_current(self) -> list[Entry]:
        return self._selected_entries() or [e for e in [self._entry(self.highlight)] if e]

    def set_field_dialog(self, fld: str | None = None, entries: list[Entry] | None = None):
        sel = entries if entries is not None else self._selected_or_current()
        if not sel:
            QMessageBox.information(self, "Set field", "Select the runs first (Ctrl- or Shift-click).")
            return
        if fld is None:
            fields = self.ws.fields
            start = fields.index(self.ws.average_by) if self.ws.average_by in fields else 0
            fld, ok = QInputDialog.getItem(self, "Set field", "Field:", fields, start, False)
            if not ok:
                return
        values = [v for v in self.ws.values(fld) if v]
        current = sel[0].tags.get(fld, "")
        name, ok = QInputDialog.getItem(
            self, f"Set {fld}", f"{fld} for {len(sel)} run(s): pick a value or type a new one.\n"
            "Leave blank to go back to the automatic value.", values or [current],
            values.index(current) if current in values else 0, True)
        if ok:
            self.ws.set_tag(sel, fld, name)
            self._after_tags()

    def add_field(self):
        name, ok = QInputDialog.getText(self, "Add field", "New field name (e.g. Membrane, Batch, Treatment):")
        if ok and name.strip():
            self.ws.add_field(name.strip())
            self._save_prefs()
            self.options.sync()
            self._refresh_all()

    def reset_tags(self, entries: list[Entry] | None = None):
        sel = entries or self._selected_or_current()
        if sel:
            self.ws.reset_tags(sel)
            self._after_tags()

    def _after_tags(self):
        self._save_prefs()
        self._warn_tag_writes()
        self.options.sync()
        self._refresh_all()

    def _is_tag_column(self, col: int) -> bool:
        return 1 <= col <= len(self.ws.fields)

    def _tree_changed(self, item: QTreeWidgetItem, col: int):
        if self._building:
            return
        if col == 0:
            self._tree_checked(item)
            return
        name = item.data(0, NAME_ROLE)
        if name is None or not self._is_tag_column(col):
            return
        e = self._entry(name)
        if e is None:
            return
        fld = self.ws.fields[col - 1]
        if item.text(col) != e.tags.get(fld, ""):
            self.ws.set_tag([e], fld, item.text(col))
            QTimer.singleShot(0, self._after_tags)  # don't rebuild the tree inside its own signal

    # ================================================================== styles
    def style_selected(self):
        sel = self._selected_or_current()
        if not sel:
            QMessageBox.information(self, "Style", "Select the runs first (Ctrl- or Shift-click).")
            return
        dlg = StyleDialog(sel, self)
        if dlg.exec():
            self.ws.set_style(sel, **dlg.values())
            self._save_prefs()
            self._refresh_all()

    def reset_style(self):
        sel = self._selected_or_current()
        if sel:
            self.ws.reset_style(sel)
            self._save_prefs()
            self._refresh_all()

    def edit_group_colors(self):
        fld = self.ws.color_by if self.ws.color_by != RUN else self.ws.average_by
        values = self.ws.values(fld)
        if not values:
            QMessageBox.information(self, "Group colours", "Load some runs first.")
            return
        current = dict(self.ws.value_colors.get(fld, {}))
        auto = dict(zip(values, palette_colors(self.ws.palette, len(values))))
        dlg = GroupColorsDialog(fld, values, current, auto, self)
        if dlg.exec():
            for v, c in dlg.values().items():
                self.ws.set_value_color(fld, v, c)
            if self.ws.color_by == RUN:
                self.statusBar().showMessage(f"These colours are used for the group means. Set 'Colour by' to {fld} "
                                             "to colour the runs too.", 10000)
            self._save_prefs()
            self._refresh_all()

    # ================================================================== menus <-> panel
    def _sync_menus(self):
        o = self.plot_opts
        for grp, cur in ((self.display_group, o.display), (self.units_group, o.units)):
            for a in grp.actions():
                a.blockSignals(True)
                a.setChecked(a.data() == cur)
                a.blockSignals(False)
        for k, v in (("markers", o.show_markers), ("titles", o.title), ("logx", o.log_diameter)):
            self.actions[k].blockSignals(True)
            self.actions[k].setChecked(v)
            self.actions[k].blockSignals(False)
        self.set_field_btn.setText(f"Set {self.ws.average_by}…")
        self.field_menu.clear()
        for f in self.ws.fields:
            self.field_menu.addAction(f"{f}…", lambda f=f: self.set_field_dialog(f))
        self.field_menu.addSeparator()
        self.field_menu.addAction("New field…", self.add_field)

    def _menu_toggle(self, key: str, checked: bool):
        w = {"markers": self.options.markers, "titles": self.options.titles, "logx": self.options.logx}[key]
        w.setChecked(checked)

    def _menu_display(self, key: str):
        self.options.display.setCurrentIndex(self.options.display.findData(key))

    def _menu_units(self, u: str):
        self.options.units.setCurrentIndex(self.options.units.findData(u))

    def _options_changed(self, regroup: bool):
        self._save_prefs()
        if regroup:
            self._refresh_all()
        else:
            self._sync_menus()
            self._refresh_soft()

    def _tab_changed(self, i: int):
        self.options.set_kind(PLOTS[i][0])

    # ================================================================== settings, icon, help
    def open_settings(self):
        dlg = SettingsDialog(self.ws.settings, self.ws.qc_settings, self.group_include_warn, self)
        if dlg.exec():
            self.ws.settings, self.ws.qc_settings, self.group_include_warn = dlg.values()
            self.ws.reanalyze()
            self._save_prefs()
            self._refresh_all()

    def make_app_icon(self):
        try:
            made = shortcuts.create()
        except Exception as exc:
            QMessageBox.warning(self, "App icon", f"Could not create the app icon:\n{exc}")
            return
        QMessageBox.information(self, "App icon", f"Created the app icon {shortcuts.where()}:\n\n"
                                + "\n".join(str(p) for p in made))

    def show_changelog(self):
        root = updater.repo_root()
        f = (root / "CHANGELOG.md") if root else None
        text = f.read_text(encoding="utf-8") if f and f.exists() else f"See {REPO_URL}/blob/main/CHANGELOG.md"
        dlg = QDialog(self)
        dlg.setWindowTitle("What's new")
        dlg.resize(680, 620)
        lay = QVBoxLayout(dlg)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setMarkdown(text)
        lay.addWidget(tb)
        dlg.exec()

    def show_about(self):
        QMessageBox.about(self, "About", f"<h3>Capillary Flow Porometry Analyzer {__version__}</h3>"
                          "<p>Analysis of PMI CapWin capillary flow porometry (.CFT) files: bubble point, mean flow "
                          "pore, pore size distribution, quality checks and group comparisons.</p>"
                          "<p>Brandon T. McReynolds, University of Akron. MIT license.<br>"
                          f"<a href='{REPO_URL}'>{REPO_URL}</a></p>")

    # ================================================================== refresh
    def _entry(self, name: str | None) -> Entry | None:
        return next((e for e in self.ws.entries if e.name == name), None)

    def _refresh_all(self):
        self._sync_menus()
        self._rebuild_tree()
        self._refresh_soft()

    def _refresh_soft(self):
        """Everything except rebuilding the run list (keeps its scroll position and selection)."""
        self._recolor_tree()
        self._refresh_tables()
        self._redraw()
        self._show_details()
        n = len(self.ws.entries)
        if n:
            counts = {lv: sum(e.qc.level == lv for e in self.ws.entries) for lv in Level}
            self.statusBar().showMessage(
                f"{n} runs · {counts[Level.PASS] + counts[Level.INFO]} pass · {counts[Level.WARN]} warn · "
                f"{counts[Level.FAIL]} fail")

    def _rebuild_tree(self):
        self._building = True
        self.tree.clear()
        fields = self.ws.fields
        self.tree.setColumnCount(len(fields) + 2)
        self.tree.setHeaderLabels(["Run", *fields, "QC"])
        hdr = self.tree.header()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        self.list_head.setText(f"<b>Runs</b> grouped by <b>{html.escape(self.ws.average_by)}</b>. Tick to plot, "
                               "click to highlight, double-click a cell to edit.")
        groups: dict[str, QTreeWidgetItem] = {}
        bold = QFont()
        bold.setBold(True)
        italic = QFont()
        italic.setItalic(True)
        for e in sorted(self.ws.entries, key=lambda e: (sort_key(e.group), e.load_index)):
            g = groups.get(e.group)
            if g is None:
                g = QTreeWidgetItem(self.tree, [e.group])
                g.setFont(0, bold)
                g.setFlags((g.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                           & ~Qt.ItemFlag.ItemIsEditable)
                g.setFirstColumnSpanned(False)
                g.setExpanded(True)
                groups[e.group] = g
            it = QTreeWidgetItem(g, [e.name, *[e.tags.get(f, "") for f in fields], e.qc.status])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            it.setCheckState(0, Qt.CheckState.Checked if e.visible else Qt.CheckState.Unchecked)
            it.setData(0, NAME_ROLE, e.name)
            it.setToolTip(0, str(e.path))
            for i, f in enumerate(fields, start=1):
                if self.ws.is_edited(e, f):
                    it.setFont(i, italic)
                    it.setToolTip(i, f"Set by you (automatic: {e.auto.get(f, '') or 'blank'})")
                else:
                    it.setToolTip(i, "Automatic, from the file name. Double-click to change.")
            it.setIcon(len(fields) + 1, status_icon(e.qc.status))
            it.setToolTip(len(fields) + 1, e.qc.summary())
            if e.name == self.highlight:
                self.tree.setCurrentItem(it)
        self._recolor_tree()
        for c in range(len(fields) + 2):
            self.tree.resizeColumnToContents(c)
        self.tree.setColumnWidth(0, min(max(self.tree.columnWidth(0), 160), 280))
        self._building = False

    def _recolor_tree(self):
        was = self._building
        self._building = True
        gcol = self.ws.group_colors()
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            g.setIcon(0, color_icon(gcol.get(g.text(0), "#888888")))
            for j in range(g.childCount()):
                it = g.child(j)
                e = self._entry(it.data(0, NAME_ROLE))
                if e:
                    it.setIcon(0, color_icon(e.color))
        self._building = was

    def _refresh_tables(self):
        colors = {e.name: e.color for e in self.ws.entries}
        o = self.plot_opts
        self.run_model.set_frame(self.ws.summary_frame(o.units), colors)
        self.group_model.set_frame(self.ws.group_frame(self.max_level))
        self.stats_model.set_frame(self.ws.stats_frame([o.compare_metric], o.units, self.max_level, visible_only=True))
        for v in (self.run_view, self.group_view, self.stats_view):
            v.resizeColumnsToContents()
            for c in range(v.model().columnCount()):
                v.setColumnWidth(c, min(v.columnWidth(c), 300))

    def _redraw(self):
        series = self.ws.series(highlight=self.highlight)
        need_groups = self.plot_opts.display != "runs"
        groups_all = self.ws.group_data(self.max_level)
        for key, _title in PLOTS:
            p = self.panels[key]
            p.figure.clear()
            ax = p.figure.add_subplot()
            groups = groups_all if (need_groups or key == "compare") else None
            if series:
                DRAWERS[key](ax, series, self.plot_opts, groups)
            else:
                ax.set_axis_off()
                ax.text(0.5, 0.5, "No runs to show.\nOpen a folder, or tick runs on the left.", ha="center",
                        va="center", color="#52514e", transform=ax.transAxes)
            p.canvas.draw_idle()

    def _show_details(self):
        e = self._entry(self.highlight)
        if e is None:
            self.details.setHtml("<p style='color:#52514e'>Select a run to see its header, tags and QC findings.</p>")
            return
        u = self.plot_opts.units
        f = PSI_TO_KPA if u == "kPa" else 1.0
        a = e.analysis

        def pr(dp, d):
            if dp is None:
                return "—"
            return f"{dp * f:.2f} {u} &nbsp;→&nbsp; <b>{d:.3g} µm</b>"

        rows = [("File", html.escape(str(e.path))), ("Date", e.run.date), ("Operator", html.escape(e.run.operator)),
                ("Test", html.escape(e.run.test_type))]
        rows += [(html.escape(k), html.escape(e.tags.get(k, "")) or "—") for k in self.ws.fields]
        rows += [("Fluid", f"{html.escape(e.run.fluid)} ({e.run.surface_tension:g} dyn/cm)"),
                 ("Thickness", f"{e.run.thickness_cm * 10:.2f} mm"),
                 ("Points", f"wet {e.run.wet.n}, dry {e.run.dry.n}"),
                 ("Max pressure", f"{a.max_dp * f:.1f} {u}"),
                 ("Bubble point", pr(a.bubble_dp, a.bubble_d)),
                 ("Mean flow pore", pr(a.mean_flow_dp, a.mean_flow_d)),
                 ("Smallest pore", pr(a.smallest_dp, a.smallest_d))]
        h = [f"<h3 style='margin:2px 0'>{html.escape(e.label)}</h3><table cellspacing='0' cellpadding='2'>"]
        h += [f"<tr><td style='color:#52514e;padding-right:10px'>{k}</td><td>{v}</td></tr>" for k, v in rows]
        h.append("</table><h4 style='margin:8px 0 2px'>Quality checks</h4>")
        if not e.qc.findings:
            h.append(f"<p><span style='color:{STATUS_COLORS['pass']}'>●</span> pass: no problems found</p>")
        for fd in sorted(e.qc.findings, key=lambda x: -x.level):
            c = STATUS_COLORS[fd.level.label]
            h.append(f"<p style='margin:4px 0'><span style='color:{c}'>●</span> <b>{fd.level.label}: "
                     f"{html.escape(fd.title)}</b><br>{html.escape(fd.detail)}</p>")
        self.details.setHtml("".join(h))

    # ================================================================== interaction
    def _tree_checked(self, item: QTreeWidgetItem):
        name = item.data(0, NAME_ROLE)
        if name is None:
            # group item: children follow via auto-tristate; sync all
            for i in range(item.childCount()):
                ch = item.child(i)
                e = self._entry(ch.data(0, NAME_ROLE))
                if e:
                    e.visible = ch.checkState(0) == Qt.CheckState.Checked
        else:
            e = self._entry(name)
            if e:
                e.visible = item.checkState(0) == Qt.CheckState.Checked
        self._refresh_tables()
        self._redraw()

    def _tree_selected(self, cur, _prev):
        if self._building or cur is None:
            return
        self._select(cur.data(0, NAME_ROLE))

    def _table_selected(self, cur, _prev):
        if not cur.isValid():
            return
        proxy = self.run_view.model()
        src = proxy.mapToSource(cur)
        self._select(self.run_model.frame.iloc[src.row()]["Run"])

    def _select(self, name: str | None):
        if name == self.highlight:
            return
        self.highlight = name
        self._redraw()
        self._show_details()

    def _set_visible(self, pred):
        for e in self.ws.entries:
            e.visible = bool(pred(e))
        self._rebuild_tree()
        self._refresh_soft()

    def show_only_selected(self):
        sel = self._selected_entries()
        if sel:
            self._set_visible(lambda e: e in sel)

    def _tree_menu(self, pos):
        sel = self._selected_entries()
        if not sel:
            return
        n = len(sel)
        m = QMenu(self)
        sub = m.addMenu(f"Set field for {n} run(s)")
        for f in self.ws.fields:
            sub.addAction(f"{f}…", lambda f=f: self.set_field_dialog(f, sel))
        sub.addSeparator()
        sub.addAction("New field…", self.add_field)
        m.addAction("Reset tags to automatic", lambda: self.reset_tags(sel))
        m.addSeparator()
        m.addAction(f"Style {n} run(s)…", self.style_selected)
        m.addAction("Reset style", self.reset_style)
        m.addSeparator()
        m.addAction("Show only these", lambda: self._set_visible(lambda e: e in sel))
        m.addAction("Hide these", lambda: self._set_visible(lambda e: e.visible and e not in sel))
        m.addSeparator()
        m.addAction("Remove from list", self.remove_selected)
        m.addAction(f"Archive {n} run(s)…", self.archive_selected)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def clear_all(self):
        self.ws.clear()
        self.highlight = None
        self.session_path = None
        self._update_title()
        self._refresh_all()

    # ================================================================== export
    def export_summary(self):
        if not self.ws.entries:
            QMessageBox.information(self, "Nothing to export", "Load some runs first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export summary", str(Path(self._last_dir()) / "porometry_summary.xlsx"),
                                              "Excel workbook (*.xlsx);;CSV, summary only (*.csv)")
        if not path:
            return
        try:
            out = write_summary(self.ws, path, self.plot_opts.units, group_max_level=self.max_level)
        except PermissionError:
            QMessageBox.warning(self, "Could not save", f"{path} is open in another program. Close it and try again.")
            return
        self.statusBar().showMessage(f"Saved {out}", 8000)

    def current_kind(self) -> str:
        return PLOTS[self.plot_tabs.currentIndex()][0]

    def render_figure(self, kind: str, size_in: tuple[float, float], font_pt: float | None,
                      titles: bool | None = None):
        o = self.plot_opts if titles is None else replace(self.plot_opts, title=titles)
        return figure_for(self.ws, kind, o, self.highlight, size_in, font_pt, self.max_level)

    def export_figure(self):
        if not self.ws.entries:
            QMessageBox.information(self, "Nothing to export", "Load some runs first.")
            return
        dlg = ExportDialog(self.render_figure, self.current_kind(), self.export_prefs, self._last_dir(), self)
        dlg.exec()
        if dlg.saved:
            self.statusBar().showMessage(f"Saved {dlg.saved}", 8000)
        self._save_prefs()

    def copy_figure(self):
        if not self.ws.entries:
            return
        p = self.export_prefs
        w, h, font = p.get("w", 16.5), p.get("h", 10.7), p.get("font", 12)
        fig = self.render_figure(self.current_kind(), (w / 2.54, h / 2.54), font, p.get("titles", False))
        copy_figure(fig, min(p.get("dpi", 300), 600))
        self.statusBar().showMessage(f"Copied {KIND_TITLES[self.current_kind()]} ({w:g} × {h:g} cm) to the clipboard",
                                     6000)

    # ================================================================== updates
    def _auto_update_check(self) -> bool:
        return self.qs.value("check_updates", "true") in ("true", True)

    def _background_update_check(self):
        self._update_worker = Worker(lambda _progress: updater.check(), self)
        self._update_worker.done.connect(self._background_checked)
        self._update_worker.start()

    def _background_checked(self, info):
        if isinstance(info, updater.UpdateInfo) and info.available:
            self._update_info = info
            self.version_label.setText(f"<a href='update'>v{info.current} → v{info.latest} available</a>  ")
            self.statusBar().showMessage(f"Version {info.latest} is available: click it in the bottom-right "
                                         "corner or use Help > Check for updates.", 15000)

    def show_updates(self):
        dlg = UpdateDialog(self._update_info, self._auto_update_check(), self)
        dlg.exec()
        self.qs.setValue("check_updates", "true" if dlg.auto.isChecked() else "false")
        if dlg.info is not None and not dlg.info.error:
            self._update_info = dlg.info
            if not dlg.info.available:
                self.version_label.setText(f"v{__version__}  ")
        if dlg.restart:
            self._restart(dlg.updated_to)

    def _restart_args(self) -> list[str]:
        """The open session, or folders opened this session plus loose files outside them, to reload."""
        if self.session_path is not None and self._write_session(self.session_path):
            return [str(self.session_path)]
        folders = sorted({f.resolve() for f in self._folders if f.is_dir()})
        files = [e.path for e in self.ws.entries
                 if Path(e.path).exists() and not any(Path(e.path).resolve().is_relative_to(f) for f in folders)]
        return [str(p) for p in [*folders, *files]]

    def _restart(self, version: str | None):
        self._save_prefs()
        ok = QProcess.startDetached(sys.executable, ["-m", "porometry", *self._restart_args()])[0]
        if ok:
            self.close()
        else:
            QMessageBox.information(self, "Updated", f"Updated to version {version}. Close the app and start it "
                                    "again to use the new version.")
