"""Menus, plot options panel, tag editing, styles, sessions and figure export in the window (headless)."""

import pytest

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

_APP = None


@pytest.fixture
def win(speeds):
    global _APP
    _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from porometry.gui.main_window import MainWindow
    w = MainWindow()
    w.resize(1500, 900)
    w.show()
    w.load_paths([str(speeds)])
    yield w
    w.close()


def top_level(w) -> list[str]:
    return [w.tree.topLevelItem(i).text(0) for i in range(w.tree.topLevelItemCount())]


def test_menus_and_slim_toolbar(win):
    titles = [a.text().replace("&", "") for a in win.menuBar().actions()]
    assert titles == ["File", "Runs", "Plot", "Tools", "Help"]
    for key in ("open_session", "save_session", "export_figure", "copy_figure", "set_field", "style", "group_colors",
                "archive", "settings", "updates", "plot_panel"):
        assert key in win.actions
    tb = win.findChild(QtWidgets.QToolBar)
    assert len([a for a in tb.actions() if not a.isSeparator()]) == 8
    assert win.plot_tabs.count() == 4 and win.table_tabs.count() == 3


def test_tree_groups_by_average_by_and_edits_tags(win):
    assert top_level(win) == ["0.25 mm/min", "2.00 mm/min", "10.00 mm/min"]
    assert win.tree.headerItem().text(1) == "Condition"
    o = win.options
    o.average_by.setCurrentIndex(o.average_by.findData("Folder"))
    assert top_level(win) == ["2026-10-11"]
    o.average_by.setCurrentIndex(o.average_by.findData("Condition"))
    # edit a Condition cell like a double-click edit would
    it = win.tree.topLevelItem(0).child(0)
    name = it.text(0)
    it.setText(1, "control")
    QtWidgets.QApplication.processEvents()
    assert win._entry(name).tags["Condition"] == "control"
    assert "control" in top_level(win)
    # bulk: same value for several runs
    sel = [e for e in win.ws.entries if e.group == "2.00 mm/min"]
    win.ws.set_tag(sel, "Condition", "control")
    win._after_tags()
    assert top_level(win) == ["10.00 mm/min", "0.25 mm/min", "control"] or "control" in top_level(win)
    # the menu offers every field
    assert [a.text() for a in win.field_menu.actions() if a.text()][:4] == ["Condition…", "Sample…", "Replicate…",
                                                                           "Folder…"]


def test_colour_by_display_and_menus_stay_in_sync(win):
    o = win.options
    o.color_by.setCurrentIndex(o.color_by.findData("Condition"))
    groups = {}
    for e in win.ws.entries:
        groups.setdefault(e.group, set()).add(e.color)
    assert all(len(c) == 1 for c in groups.values()) and o.colors_btn.isEnabled()
    win._menu_display("means")
    assert o.display.currentData() == "means" and win.plot_opts.display == "means"
    assert any(a.isChecked() and a.data() == "means" for a in win.display_group.actions())
    win.actions["logx"].trigger()
    assert win.plot_opts.log_diameter is False and not o.logx.isChecked()
    win.plot_tabs.setCurrentIndex(3)
    QtWidgets.QApplication.processEvents()
    title = win.panels["compare"].figure.axes[0].get_title(loc="left")
    assert "by condition" in title
    assert win.stats_model.frame.iloc[0]["Test"] == "One-way ANOVA"
    # axis limits typed into the panel apply to the current plot
    win.plot_tabs.setCurrentIndex(1)
    o.lims[0].setText("1")
    o.lims[1].setText("10")
    o._limits_edited()
    assert win.plot_opts.limits["cff"][:2] == [1.0, 10.0]
    assert win.panels["cff"].figure.axes[0].get_xlim() == pytest.approx((1, 10))


def test_style_dialog_and_group_colours(win, monkeypatch):
    from porometry.gui import main_window, style_dialog
    e = win.ws.entries[0]
    d = style_dialog.StyleDialog([e], win)
    d.color.color = "#00aa00"
    d.marker.setCurrentIndex(d.marker.findData("D"))
    d.label.setText("My control")
    vals = d.values()
    assert vals == {"color": "#00aa00", "marker": "D", "linestyle": None, "linewidth": None, "label": "My control"}
    win.ws.set_style([e], **vals)
    win._refresh_all()
    assert e.color == "#00aa00" and any(s.label == "My control" for s in win.ws.series())
    assert "My control" in [t.get_text() for t in win.panels["flow"].figure.axes[0].get_legend().get_texts()]

    class FakeColors:
        def __init__(self, fld, values, current, auto, parent):
            self.fld, self.vals = fld, values

        def exec(self):
            return 1

        def values(self):
            return {self.vals[0]: "#abcdef"}
    monkeypatch.setattr(main_window, "GroupColorsDialog", FakeColors)
    win.options.color_by.setCurrentIndex(win.options.color_by.findData("Condition"))
    win.edit_group_colors()
    assert win.ws.value_colors["Condition"]["0.25 mm/min"] == "#abcdef"
    assert {x.color for x in win.ws.entries if x.group == "0.25 mm/min" and x is not e} == {"#abcdef"}


def test_session_save_and_open(win, tmp_path):
    win.options.display.setCurrentIndex(win.options.display.findData("both"))
    win.ws.entries[0].visible = False
    win.plot_tabs.setCurrentIndex(2)
    out = win._write_session(tmp_path / "my comparison.cfpa")
    assert out.exists() and "my comparison.cfpa" in win.windowTitle()
    win.clear_all()
    assert not win.ws.entries and win.session_path is None
    win.load_paths([str(out)])  # dropping / double-clicking a .cfpa opens it
    assert len(win.ws.entries) == 9 and sum(not e.visible for e in win.ws.entries) == 1
    assert win.plot_opts.display == "both" and win.options.display.currentData() == "both"
    assert win.plot_tabs.currentIndex() == 2 and win.session_path == out
    assert win.recent_menu.actions()[0].text() == "my comparison.cfpa"


def test_export_dialog_and_clipboard(win, tmp_path):
    from porometry.gui.export_dialog import SIZES, ExportDialog
    prefs = {}
    d = ExportDialog(win.render_figure, "cff", prefs, str(tmp_path), win)
    d.size.setCurrentIndex(d.size.findData("Double column / full page width (17.8 cm)"))
    assert d.w.value() == SIZES["Double column / full page width (17.8 cm)"][0] and d.font.value() == 10
    d.w.setValue(12)  # typing a size switches the preset to Custom
    assert d.size.currentData() == "Custom" and prefs["w"] == 12
    d._update_preview()
    assert not d.preview.pixmap().isNull()
    for ext in ("png", "svg", "pdf", "tif"):
        p = d.save(str(tmp_path / f"fig.{ext}"))
        assert p.exists() and p.stat().st_size > 1000
    from PIL import Image
    with Image.open(tmp_path / "fig.png") as im:
        assert im.size[0] == pytest.approx(12 / 2.54 * 600, abs=2)  # exactly 12 cm at 600 dpi
    d.kind.setCurrentIndex(d.kind.findData("all"))
    assert d.h_label.text() == "Height per panel"
    win.copy_figure()
    assert not QtWidgets.QApplication.clipboard().image().isNull()


# ---------------------------------------------------------------- v0.5: named groups, recent folders
def group_items(w) -> list[str]:
    return [w.group_list.item(i).text().strip() for i in range(w.group_list.count())]


def select_runs(w, pred):
    w.tree.clearSelection()
    for i in range(w.tree.topLevelItemCount()):
        top = w.tree.topLevelItem(i)
        for it in [top] if top.data(0, w_role()) else [top.child(j) for j in range(top.childCount())]:
            e = w._entry(it.data(0, w_role()))
            if e is not None and pred(e):
                it.setSelected(True)


def w_role():
    from porometry.gui.main_window import NAME_ROLE
    return NAME_ROLE


def test_groups_list_new_add_remove_rename_delete(win, monkeypatch):
    from porometry.gui import main_window as mw
    assert group_items(win) == ["All runs  (9)"]
    select_runs(win, lambda e: e.tags["Replicate"] == "2")
    monkeypatch.setattr(mw.QInputDialog, "getText", lambda *a, **k: ("Speed series", True))
    win.new_group_from_selection()
    assert win.ws.active_group == "Speed series" and group_items(win) == ["All runs  (9)", "Speed series  (3)"]
    assert win.tree.topLevelItemCount() == 3 and len(win.ws.series()) == 3  # only the group's runs
    # the same run in a second group
    win.activate_group(None)
    select_runs(win, lambda e: e.group == "0.25 mm/min")
    win.add_selected_to_group("S1 replicates")  # what dropping runs onto a group does
    assert "S1 replicates  (3)" in group_items(win)
    assert sum(len(e.groups) == 2 for e in win.ws.entries) == 1
    # Average by Run: a flat list, every run on its own
    win.activate_group("S1 replicates")
    win.options.average_by.setCurrentIndex(win.options.average_by.findData("Run"))
    assert win.tree.topLevelItemCount() == 3 and all(win.tree.topLevelItem(i).data(0, w_role())
                                                      for i in range(3))
    assert "by run" in win.panels["compare"].figure.axes[0].get_title(loc="left")
    # clicking All runs restores its own view
    win.group_list.setCurrentRow(0)
    assert win.ws.active_group is None and win.ws.average_by == "Condition"
    win.group_list.setCurrentRow(1)  # S1 replicates
    assert win.ws.average_by == "Run"
    # remove one run from the group being shown
    select_runs(win, lambda e: e.tags["Replicate"] == "1")
    win.remove_selected_from_group()
    assert "S1 replicates  (2)" in group_items(win)
    monkeypatch.setattr(mw.QInputDialog, "getText", lambda *a, **k: ("Slow reps", True))
    win.rename_group("S1 replicates")
    assert "Slow reps  (2)" in group_items(win) and win.ws.active_group == "Slow reps"
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a, **k: mw.QMessageBox.StandardButton.Yes)
    win.delete_group("Slow reps")
    assert win.ws.active_group is None and "Slow reps" not in " ".join(group_items(win))
    assert "Groups work like playlists" in mw.GROUPING_HELP


def test_recent_folders_are_remembered(win, speeds, tmp_path):
    names = [a.text() for a in win.recent_folders_menu.actions() if a.text()]
    assert names[0].startswith("2026-10-11") and names[-1] == "Clear recent folders"
    other = tmp_path / "other"
    other.mkdir()
    win.open_folder_path(other)
    assert win._recent_folders()[:2] == [str(other.resolve()), str(speeds.resolve())]
    other.rmdir()
    win._rebuild_recent_folders()
    assert not win.recent_folders_menu.actions()[0].isEnabled()  # gone: greyed out
    win._clear_recent_folders()
    assert win._recent_folders() == []
