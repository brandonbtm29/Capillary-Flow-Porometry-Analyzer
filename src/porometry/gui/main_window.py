"""Main window: run list on the left, plots and summary tables on the right."""

from __future__ import annotations

import html
import json
import sys
from dataclasses import asdict
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PyQt6.QtCore import QByteArray, QProcess, QSettings, QSortFilterProxyModel, Qt, QTimer
from PyQt6.QtGui import QAction, QFont, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMainWindow,
    QMenu, QMessageBox, QPushButton, QSpinBox, QSplitter, QTableView, QTabWidget, QTextBrowser, QToolBar,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import __version__, updater
from ..analysis import Settings
from ..archive import ArchiveError, list_archived
from ..cft import PSI_TO_KPA
from ..export import save_figure, write_summary
from ..figures import STATUS_COLORS, PlotOptions, apply_style, draw_cff, draw_flow, draw_psd
from ..qc import Level, QCSettings
from ..workspace import Entry, Workspace
from .archive_dialog import ArchiveDialog, ArchivedRunsDialog
from .models import DataFrameModel, color_icon, status_icon
from .settings_dialog import SettingsDialog
from .update_dialog import UpdateDialog, Worker

NAME_ROLE = Qt.ItemDataRole.UserRole + 1
PLOTS = [("flow", "Flow vs pressure", draw_flow), ("cff", "Cumulative filter flow", draw_cff),
         ("psd", "Pore size distribution", draw_psd)]


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


class MainWindow(QMainWindow):
    def __init__(self, check_updates: bool = False):
        super().__init__()
        apply_style()
        self.setWindowTitle(f"Capillary Flow Porometry Analyzer {__version__}")
        self.resize(1400, 900)
        self.setAcceptDrops(True)
        self.qs = QSettings("PorometryAnalyzer", "PorometryAnalyzer")
        self.ws = Workspace()
        self.group_include_warn = True
        self.highlight: str | None = None
        self._folders: set[Path] = set()  # folders opened this session (where to look for archived runs)
        self._building = False
        self._update_info: updater.UpdateInfo | None = None
        self._update_worker: Worker | None = None
        self._load_prefs()
        self._build_ui()
        self._refresh_all()
        if check_updates and self._auto_update_check():
            QTimer.singleShot(2000, self._background_update_check)

    # ================================================================== UI
    def _build_ui(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        def act(text, slot, shortcut=None, tip=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip:
                a.setToolTip(tip)
            tb.addAction(a)
            return a

        act("Open folder…", self.open_folder, "Ctrl+O", "Load every .CFT file in a folder and its subfolders")
        act("Add files…", self.add_files, "Ctrl+Shift+O")
        act("Remove from list", self.remove_selected, "Delete",
            "Drop the selected runs from this session's list. The files are not touched and load again next time.")
        act("Archive…", self.archive_selected, "Ctrl+Shift+A",
            "Move the selected runs' .CFT files into an Archive folder next to them, with a reason. "
            "They stop loading with the folder; restore them from Archived runs…")
        act("Archived runs…", self.show_archived, None, "List archived runs in the opened folders and restore them")
        act("Clear", self.clear_all)
        tb.addSeparator()
        act("Export summary…", self.export_summary, "Ctrl+E", "Excel: summary, group averages, QC, one sheet per run")
        fig_btn = QToolButton()
        fig_btn.setText("Export figure")
        fig_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(fig_btn)
        m.addAction("Current plot…", lambda: self.export_figure(False))
        m.addAction("All three plots (one figure)…", lambda: self.export_figure(True))
        fig_btn.setMenu(m)
        tb.addWidget(fig_btn)
        tb.addSeparator()
        act("Settings…", self.open_settings, "Ctrl+,")
        act("Update…", self.show_updates, None, "Check GitHub for a newer version of the app and install it")
        tb.addSeparator()

        tb.addWidget(QLabel(" Units "))
        self.units = QComboBox()
        self.units.addItems(["kPa", "psi"])
        self.units.setCurrentText(self.plot_opts.units)
        self.units.currentTextChanged.connect(self._opts_changed)
        tb.addWidget(self.units)
        self.logx = QCheckBox("Log diameter")
        self.logx.setChecked(self.plot_opts.log_diameter)
        self.logx.toggled.connect(self._opts_changed)
        tb.addWidget(self.logx)
        tb.addWidget(QLabel("  Distribution "))
        self.psd_mode = QComboBox()
        self.psd_mode.addItem("Point-by-point (CapRep), %/µm", ("points", "D"))
        self.psd_mode.addItem("Point-by-point, %/µm² (D² weighting)", ("points", "D2"))
        self.psd_mode.addItem("Histogram, % flow per bin", ("binned", "D"))
        self.psd_mode.addItem("Point-by-point, ΔFF/ΔD² (older CapRep exports)", ("points", "dD2"))
        for i in range(self.psd_mode.count()):
            if self.psd_mode.itemData(i) == (self.plot_opts.psd_mode, self.plot_opts.psd_weighting):
                self.psd_mode.setCurrentIndex(i)
        self.psd_mode.currentIndexChanged.connect(self._opts_changed)
        tb.addWidget(self.psd_mode)
        self.bins = QSpinBox()
        self.bins.setRange(4, 100)
        self.bins.setValue(self.plot_opts.psd_bins)
        self.bins.setPrefix("bins ")
        self.bins.valueChanged.connect(self._opts_changed)
        tb.addWidget(self.bins)

        # ---- left: runs + details
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 6, 0, 6)
        head = QLabel("<b>Runs</b> — tick to plot, click to highlight")
        ll.addWidget(head)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Run", "QC"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setStretchLastSection(False)
        self.tree.itemChanged.connect(self._tree_checked)
        self.tree.currentItemChanged.connect(self._tree_selected)
        ll.addWidget(self.tree, 3)
        row = QHBoxLayout()
        for text, slot in (("Show all", lambda: self._set_visible(lambda e: True)),
                           ("Hide all", lambda: self._set_visible(lambda e: False)),
                           ("Hide QC fails", lambda: self._set_visible(lambda e: e.qc.level < Level.FAIL))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        ll.addLayout(row)
        row2 = QHBoxLayout()
        dup = QPushButton("Mark selected as duplicates…")
        dup.setToolTip("Put the selected runs in one group; the Groups table averages them (mean ± SD). "
                       "Ctrl/Shift-click to select several. Right-click for more options.")
        dup.clicked.connect(self.mark_duplicates)
        row2.addWidget(dup)
        ll.addLayout(row2)
        ll.addWidget(QLabel("<b>Run details</b>"))
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(False)
        ll.addWidget(self.details, 2)

        # ---- right: plots over tables
        self.plot_tabs = QTabWidget()
        self.panels: dict[str, PlotPanel] = {}
        for key, title, _ in PLOTS:
            p = PlotPanel()
            self.panels[key] = p
            self.plot_tabs.addTab(p, title)

        self.table_tabs = QTabWidget()
        self.run_model = DataFrameModel()
        self.group_model = DataFrameModel()
        self.run_view = self._make_table(self.run_model)
        self.run_view.selectionModel().currentRowChanged.connect(self._table_selected)
        self.group_view = self._make_table(self.group_model)
        self.table_tabs.addTab(self.run_view, "Runs")
        self.table_tabs.addTab(self.group_view, "Groups (mean ± SD)")

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
        split.setSizes([360, 1040])
        self.setCentralWidget(split)
        self.statusBar().showMessage("Open a folder of .CFT files, or drag files or folders onto this window.")
        self.version_label = QLabel(f"v{__version__}  ")
        self.version_label.setToolTip("Click to check for updates")
        self.version_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.version_label.mousePressEvent = lambda _ev: self.show_updates()
        self.statusBar().addPermanentWidget(self.version_label)

        geo = self.qs.value("geometry")
        if isinstance(geo, QByteArray):
            self.restoreGeometry(geo)

    def _make_table(self, model) -> QTableView:
        proxy = SortProxy(self)
        proxy.setSourceModel(model)
        v = QTableView()
        v.setModel(proxy)
        v.setSortingEnabled(True)
        v.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        v.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        v.setAlternatingRowColors(True)
        v.verticalHeader().setVisible(False)
        v.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        v.setWordWrap(False)
        v.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        return v

    # ================================================================== prefs
    def _load_prefs(self):
        self.plot_opts = PlotOptions()
        try:
            o = json.loads(self.qs.value("plot_options", "{}") or "{}")
            self.plot_opts = PlotOptions(**{k: v for k, v in o.items() if k in asdict(PlotOptions())})
            s = json.loads(self.qs.value("analysis_v2", "{}") or "{}")
            self.ws.settings = Settings(**{k: v for k, v in s.items() if k in asdict(Settings())})
            q = json.loads(self.qs.value("qc", "{}") or "{}")
            self.ws.qc_settings = QCSettings(**{k: v for k, v in q.items() if k in asdict(QCSettings())})
            self.ws.group_mode = self.qs.value("group_mode", "name")
            self.group_include_warn = self.qs.value("group_include_warn", "true") in ("true", True)
            self.ws.group_overrides = dict(json.loads(self.qs.value("group_overrides", "{}") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    def _save_prefs(self):
        self.qs.setValue("plot_options", json.dumps(asdict(self.plot_opts)))
        self.qs.setValue("analysis_v2", json.dumps(asdict(self.ws.settings)))
        self.qs.setValue("qc", json.dumps(asdict(self.ws.qc_settings)))
        self.qs.setValue("group_mode", self.ws.group_mode)
        self.qs.setValue("group_include_warn", "true" if self.group_include_warn else "false")
        self.qs.setValue("group_overrides", json.dumps(self.ws.group_overrides))
        self.qs.setValue("geometry", self.saveGeometry())

    def closeEvent(self, ev):
        self._save_prefs()
        super().closeEvent(ev)

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
        self._refresh_all()
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

    def remove_selected(self):
        sel = self._selected_entries() or [e for e in [self._entry(self.highlight)] if e]
        for e in sel:
            self.ws.remove(e)
        if sel:
            self.highlight = None
            self._refresh_all()

    # ================================================================== archive
    def archive_selected(self):
        sel = self._selected_entries() or [e for e in [self._entry(self.highlight)] if e]
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

    # ================================================================== duplicates
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

    def mark_duplicates(self):
        sel = self._selected_entries()
        if len(sel) < 1:
            QMessageBox.information(self, "Mark duplicates", "Select the runs first (Ctrl- or Shift-click).")
            return
        groups = sorted({e.group for e in self.ws.entries})
        default = sel[0].group
        name, ok = QInputDialog.getItem(self, "Mark as duplicates",
                                        f"Group name for {len(sel)} run(s) (pick an existing group or type a new one):",
                                        groups, groups.index(default) if default in groups else 0, True)
        if ok and name.strip():
            self.ws.set_group(sel, name.strip())
            self._save_prefs()
            self._refresh_all()

    def _tree_menu(self, pos):
        sel = self._selected_entries()
        if not sel:
            return
        m = QMenu(self)
        m.addAction(f"Mark {len(sel)} run(s) as duplicates…", self.mark_duplicates)
        m.addAction("Not duplicates (each its own group)", lambda: self._group_op(self.ws.separate, sel))
        m.addAction("Reset to automatic grouping", lambda: self._group_op(self.ws.reset_group, sel))
        m.addSeparator()
        m.addAction("Show only these", lambda: self._set_visible(lambda e: e in sel))
        m.addAction("Remove from list", self.remove_selected)
        m.addAction(f"Archive {len(sel)} run(s)…", self.archive_selected)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _group_op(self, fn, sel):
        fn(sel)
        self._save_prefs()
        self._refresh_all()

    def clear_all(self):
        self.ws.clear()
        self.highlight = None
        self._refresh_all()

    # ================================================================== settings
    def open_settings(self):
        dlg = SettingsDialog(self.ws.settings, self.ws.qc_settings, self.ws.group_mode, self.group_include_warn, self)
        if dlg.exec():
            self.ws.settings, self.ws.qc_settings, self.ws.group_mode, self.group_include_warn = dlg.values()
            self.ws.reanalyze()
            self._save_prefs()
            self._refresh_all()

    def _opts_changed(self, *_):
        mode, weighting = self.psd_mode.currentData()
        self.plot_opts.units = self.units.currentText()
        self.plot_opts.log_diameter = self.logx.isChecked()
        self.plot_opts.psd_mode = mode
        self.plot_opts.psd_weighting = weighting
        self.plot_opts.psd_bins = self.bins.value()
        self.bins.setEnabled(mode == "binned")
        self._refresh_tables()
        self._redraw()
        self._show_details()

    # ================================================================== refresh
    def _entry(self, name: str | None) -> Entry | None:
        return next((e for e in self.ws.entries if e.name == name), None)

    def _refresh_all(self):
        self._rebuild_tree()
        self._refresh_tables()
        self._redraw()
        self._show_details()
        self.bins.setEnabled(self.plot_opts.psd_mode == "binned")
        n = len(self.ws.entries)
        if n:
            counts = {lv: sum(e.qc.level == lv for e in self.ws.entries) for lv in Level}
            self.statusBar().showMessage(
                f"{n} runs · {counts[Level.PASS] + counts[Level.INFO]} pass · {counts[Level.WARN]} warn · "
                f"{counts[Level.FAIL]} fail")

    def _rebuild_tree(self):
        self._building = True
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        bold = QFont()
        bold.setBold(True)
        for e in self.ws.entries:
            g = groups.get(e.group)
            if g is None:
                g = QTreeWidgetItem(self.tree, [e.group, ""])
                g.setFont(0, bold)
                g.setFlags(g.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                g.setExpanded(True)
                groups[e.group] = g
            it = QTreeWidgetItem(g, [e.name, e.qc.status])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked if e.visible else Qt.CheckState.Unchecked)
            it.setIcon(0, color_icon(e.color))
            it.setIcon(1, status_icon(e.qc.status))
            it.setData(0, NAME_ROLE, e.name)
            it.setToolTip(0, str(e.path))
            it.setToolTip(1, e.qc.summary())
            if e.name == self.highlight:
                self.tree.setCurrentItem(it)
        self._building = False

    def _refresh_tables(self):
        colors = {e.name: e.color for e in self.ws.entries}
        df = self.ws.summary_frame(self.plot_opts.units)
        self.run_model.set_frame(df, colors)
        max_level = Level.WARN if self.group_include_warn else Level.INFO
        self.group_model.set_frame(self.ws.group_frame(max_level))
        for v in (self.run_view, self.group_view):
            v.resizeColumnsToContents()
            for c in range(v.model().columnCount()):
                v.setColumnWidth(c, min(v.columnWidth(c), 260))

    def _redraw(self):
        series = self.ws.series(highlight=self.highlight)
        for key, _title, drawer in PLOTS:
            p = self.panels[key]
            p.figure.clear()
            ax = p.figure.add_subplot()
            if series:
                drawer(ax, series, self.plot_opts)
            else:
                ax.set_axis_off()
                ax.text(0.5, 0.5, "No runs to show.\nOpen a folder, or tick runs on the left.", ha="center",
                        va="center", color="#52514e", transform=ax.transAxes)
            p.canvas.draw_idle()

    def _show_details(self):
        e = self._entry(self.highlight)
        if e is None:
            self.details.setHtml("<p style='color:#52514e'>Select a run to see its header and QC findings.</p>")
            return
        u = self.plot_opts.units
        f = PSI_TO_KPA if u == "kPa" else 1.0
        a = e.analysis

        def pr(dp, d):
            if dp is None:
                return "—"
            return f"{dp * f:.2f} {u} &nbsp;→&nbsp; <b>{d:.3g} µm</b>"

        rows = [("File", html.escape(str(e.path))), ("Date", e.run.date), ("Operator", html.escape(e.run.operator)),
                ("Test", html.escape(e.run.test_type)),
                ("Fluid", f"{html.escape(e.run.fluid)} ({e.run.surface_tension:g} dyn/cm)"),
                ("Thickness", f"{e.run.thickness_cm * 10:.2f} mm"),
                ("Points", f"wet {e.run.wet.n}, dry {e.run.dry.n}"),
                ("Max pressure", f"{a.max_dp * f:.1f} {u}"),
                ("Bubble point", pr(a.bubble_dp, a.bubble_d)),
                ("Mean flow pore", pr(a.mean_flow_dp, a.mean_flow_d)),
                ("Smallest pore", pr(a.smallest_dp, a.smallest_d))]
        h = [f"<h3 style='margin:2px 0'>{html.escape(e.name)}</h3><table cellspacing='0' cellpadding='2'>"]
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
    def _tree_checked(self, item: QTreeWidgetItem, col: int):
        if self._building or col != 0:
            return
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
        self._redraw()

    def _tree_selected(self, cur, _prev):
        if self._building or cur is None:
            return
        name = cur.data(0, NAME_ROLE)
        self._select(name)

    def _table_selected(self, cur, _prev):
        if not cur.isValid():
            return
        proxy = self.run_view.model()
        src = proxy.mapToSource(cur)
        name = self.run_model.frame.iloc[src.row()]["Run"]
        self._select(name)

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
        self._redraw()

    # ================================================================== export
    def export_summary(self):
        if not self.ws.entries:
            QMessageBox.information(self, "Nothing to export", "Load some runs first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export summary", str(Path(self._last_dir()) / "porometry_summary.xlsx"),
                                              "Excel workbook (*.xlsx);;CSV, summary only (*.csv)")
        if not path:
            return
        max_level = Level.WARN if self.group_include_warn else Level.INFO
        try:
            out = write_summary(self.ws, path, self.plot_opts.units, group_max_level=max_level)
        except PermissionError:
            QMessageBox.warning(self, "Could not save", f"{path} is open in another program. Close it and try again.")
            return
        self.statusBar().showMessage(f"Saved {out}", 8000)

    def export_figure(self, all_three: bool):
        if not self.ws.entries:
            QMessageBox.information(self, "Nothing to export", "Load some runs first.")
            return
        kind = "all" if all_three else PLOTS[self.plot_tabs.currentIndex()][0]
        path, _ = QFileDialog.getSaveFileName(self, "Export figure", str(Path(self._last_dir()) / f"porometry_{kind}.png"),
                                              "PNG image, 300 dpi (*.png);;SVG vector (*.svg);;PDF vector (*.pdf)")
        if not path:
            return
        if Path(path).suffix.lower() not in (".png", ".svg", ".pdf"):
            path += ".png"
        save_figure(self.ws, kind, path, self.plot_opts, highlight=self.highlight)
        self.statusBar().showMessage(f"Saved {path}", 8000)

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
                                         "corner or use Update… in the toolbar.", 15000)

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
        """Folders opened this session plus loose files outside them, to reload after a restart."""
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
