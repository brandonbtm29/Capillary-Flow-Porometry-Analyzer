"""The left side of the main window: the run list's tag editor and the groups panel (with its help text)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidget, QStyledItemDelegate

if TYPE_CHECKING:
    from .main_window import MainWindow

NAME_ROLE = Qt.ItemDataRole.UserRole + 1


class TagDelegate(QStyledItemDelegate):
    """Only tag cells of run rows can be edited (not the run name, the QC column or group rows)."""

    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window = window

    def createEditor(self, parent, option, index):
        item = self.window.tree.itemFromIndex(index)
        if item is None or item.data(0, NAME_ROLE) is None or not self.window._is_tag_column(index.column()):
            return None
        return super().createEditor(parent, option, index)


GROUP_ROLE = Qt.ItemDataRole.UserRole + 2
ALL_RUNS = "All runs"
GROUPING_HELP = """\
## How grouping works

There are two separate ideas: **groups** (which runs you're looking at) and **Average by** (which of those
runs are averaged together).

### Groups: pick the runs to compare

Groups work like playlists. *All runs* is everything loaded; your own groups sit under it.

- **Make one:** select runs in the list (Ctrl- or Shift-click), then **New group from selection…**.
- **Add more:** select runs, then **Add to group** (or right-click > *Add to group*), or drag them onto a
  group in the list.
- **One run can be in many groups.** The same run can be in "Speed series" and in "S1 replicates".
- **Click a group** and the plots, tables, statistics, Compare tab and exports show only its runs.
- Each group remembers how it's plotted: its Average by, Colour by, palette and Show setting.
- Membership is saved in `run_tags.csv` next to the data (column *Groups*), so it syncs between computers.

### Average by: which runs are replicates of each other

Inside whatever you're looking at, **Average by** (Plot options) decides which runs count as replicates:

- **Condition** (the default): runs with the same condition are averaged, e.g. three 0.25 mm/min runs.
- **Sample**, **Folder** or a field you added: average along that instead.
- **Run (no averaging)**: every run stands alone. Use this to compare replicates with each other.

### Examples

| You want to | Group | Average by | Colour by | Show |
|---|---|---|---|---|
| Compare speeds, replicates averaged | "Speed series" | Condition | Condition | Group means ± SD |
| See how the replicates of one sample agree | "S1 replicates" | Run | Replicate | Individual runs |
| Compare samples at one speed | "0.25 mm/min samples" | Sample | Sample | Runs + group means |

### Tags

Condition, Sample, Replicate and Folder are read from the file name. Double-click a cell to change one run,
or select several and use *Runs > Set field*. Add your own fields (e.g. Membrane, Batch) with
*Runs > Add field…*.
"""


class GroupList(QListWidget):
    """The groups panel. Runs dragged here from the run list are added to the group they're dropped on."""

    def __init__(self, window: MainWindow):
        super().__init__()
        self.window = window
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, ev):
        if ev.source() is self.window.tree:
            ev.acceptProposedAction()
        else:
            super().dragEnterEvent(ev)

    def dragMoveEvent(self, ev):
        if ev.source() is self.window.tree:
            it = self.itemAt(ev.position().toPoint())
            if it is not None and it.data(GROUP_ROLE):
                ev.acceptProposedAction()
                return
            ev.ignore()
        else:
            super().dragMoveEvent(ev)

    def dropEvent(self, ev):
        it = self.itemAt(ev.position().toPoint())
        if ev.source() is self.window.tree and it is not None and it.data(GROUP_ROLE):
            self.window.add_selected_to_group(it.data(GROUP_ROLE))
            ev.acceptProposedAction()
        else:
            ev.ignore()
