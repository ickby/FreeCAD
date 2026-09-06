# ***************************************************************************
# *   Copyright (c) 2026 Stefan Tröger <stefantroeger@gmx.net>              *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

__title__ = "FreeCAD FEM shell builder task panel"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

from PySide import QtCore, QtGui

import FreeCAD
import Part

from femguiutils.selection_rules import ReferenceRule
from femguiutils.selection_slots import ReferenceSelection

from femobjects import geometry_shellbuilder
from femviewprovider import view_geometry_base

from . import base_femtaskpanel

# The solids this step will reduce, and the faces of a wall being paired by
# hand, are marked in their own colours, clear of the green of a selection and
# the orange of a hover.
MARK_TARGETS = "GeometryShellBuilder.Targets"
MARK_PAIR = "GeometryShellBuilder.Pair"

MARK_WALL_OUTER = "GeometryShellBuilder.WallOuter"
MARK_WALL_INNER = "GeometryShellBuilder.WallInner"

# Four things are shown at once on the same geometry, and each has to be
# telling at a glance against the others. The solids picked to reduce keep the
# blue they have always had; a wall's two faces are magenta and green, which
# read against blue and against each other; and the sheets are drawn in orange,
# the furthest thing from all three.
MARK_COLORS = {
    MARK_TARGETS: (0.1, 0.6, 0.85),
    MARK_PAIR: (0.9, 0.2, 0.85),
    MARK_WALL_OUTER: (0.9, 0.2, 0.85),
    MARK_WALL_INNER: (0.1, 0.8, 0.35),
}

PREVIEW_COLOR = (1.0, 0.55, 0.1)

# Faint enough to see the body through, solid enough to be seen against it. The
# partition tool sits at 0.85, which is right for a plane crossing the whole
# view and too little for a surface lying on a face of the same colour family.
PREVIEW_TRANSPARENCY = 0.55

# Building the sheets of a mid-surface costs about as much as the search does,
# so a change asks for the preview rather than making it, and a burst of them
# waits this long and then draws once.
PREVIEW_DELAY = 60

# A wall the search found and a wall the user paired are both walls: they sit in
# one list and differ only in where they came from and whether they can be taken
# out of it again.
ROW_FOUND = "found"
ROW_ADDED = "added"
ROW_NOTE = "note"

ADDED_COLOR = QtGui.QColor(90, 150, 220)
NOTE_COLOR = QtGui.QColor(150, 110, 40)
QUIET_COLOR = QtGui.QColor(120, 120, 130)

COLUMN_WALL = 0
COLUMN_FACES = 1
COLUMN_THICKNESS = 2
COLUMN_VARIATION = 3


def _references_to_links(references):
    grouped = {}
    for obj, sub in references:
        grouped.setdefault(obj, []).append(sub)
    return [(obj, subs) for obj, subs in grouped.items()]


def _links_to_references(links):
    references = []
    for link in links or []:
        obj = link[0]
        subs = link[1] if isinstance(link[1], (list, tuple)) else (link[1],)
        for sub in subs:
            if sub:
                references.append((obj, sub))
    return references


def _stored_pairs(obj):
    """The hand-picked pairs already on the object, as (source, partner) picks."""
    sources = _links_to_references(obj.PairSources)
    partners = _links_to_references(obj.PairPartners)
    return list(zip(sources, partners))


def _solid_rule():
    """Solids of the step input; a wall is a property of a body, not of a face."""
    return ReferenceRule(types=("Solid",), max_count=None, homogeneous=True, scope="input")


def _wall_rule():
    """
    The two faces of one wall, in a single box.

    Two boxes would say the two faces differ in kind, and they do not: a wall is
    bounded by two faces and which of them is picked first means nothing.
    """
    return ReferenceRule(types=("Face",), max_count=2, homogeneous=True, scope="input")


class _Settings:
    """
    The panel's picks in the shape the object lookups expect.

    Scanning has to answer for what the panel is holding, which has not been
    written to the step yet, so the lookups are handed this instead of the
    object and see the same field names.
    """

    def __init__(self, elements, pairs=()):
        self.Elements = elements
        self.PairSources = _references_to_links([first for first, _ in pairs])
        self.PairPartners = _references_to_links([second for _, second in pairs])


class _Row:
    """One line of the wall list, and what it stands for."""

    def __init__(self, kind, columns, name=None, pair=None, faces=()):
        self.kind = kind
        self.columns = columns
        self.name = name
        self.pair = pair
        self.faces = faces


class _Body:
    """
    What one solid offered at the last scan.

    Keeping it means a tick in the list costs a redraw rather than another
    search: the walls do not change when the user decides which of them to use.
    """

    def __init__(self, number, solid, found, near_misses):
        self.number = number
        self.solid = solid
        self.found = found
        self.added = []
        self.near_misses = near_misses


class _LeaveWatcher(QtCore.QObject):
    """
    Tells the panel when the mouse has left the list.

    itemEntered says which row the mouse is on and never says that it is on
    none of them, so without this the last row hovered would stay lit after the
    mouse had gone.
    """

    def __init__(self, on_leave):
        super().__init__()
        self._on_leave = on_leave

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Leave:
            self._on_leave()
        return False


class _ShellBuilderTaskPanel(base_femtaskpanel._BaseTaskPanel):
    """Task panel for reducing thin solids to faces with a thickness."""

    def __init__(self, obj):
        super().__init__(obj)
        # Restoring a widget fires its change signal, and writing back before
        # every widget holds its stored value would clear the ones not restored.
        self._loading = True
        self.base_obj = obj.Base

        # Held by the panel rather than written to the object, so that
        # cancelling leaves the step exactly as it was.
        self._pairs = _stored_pairs(obj)
        self._excluded = {sub for _, sub in _links_to_references(obj.ExcludedWalls) if sub}
        self._bodies = []
        self._rows = []
        self._names = {}
        self._stale = True
        self._hovered = None
        self._enabled_walls = []
        self._preview_timer = QtCore.QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._draw_preview)

        self.form = QtGui.QWidget()
        layout = QtGui.QVBoxLayout()

        self.picker = ReferenceSelection(
            obj, parent=self.form, geometry=self.base_obj, auto_install=False
        )
        self.picker.hide()

        self.method_combo = QtGui.QComboBox()
        for method in geometry_shellbuilder.SHELL_METHODS:
            self.method_combo.addItem(method)
        index = self.method_combo.findText(obj.Method)
        if index >= 0:
            self.method_combo.setCurrentIndex(index)
        self.method_combo.currentIndexChanged.connect(self._method_changed)

        self.targets = self.picker.add_slot(
            "Targets",
            FreeCAD.Qt.translate("FEM", "Solids to reduce"),
            _solid_rule(),
            marks=False,
            color=MARK_COLORS[MARK_TARGETS],
        )
        self.targets.set_picks(_links_to_references(obj.Elements))
        # Solids are picked a few at a time, and the box only has to show that
        # much. What it does not take, the wall list gets.
        self.targets.set_visible_rows(3)

        self.max_spin = QtGui.QDoubleSpinBox()
        self.max_spin.setRange(0.001, 1000.0)
        self.max_spin.setDecimals(3)
        self.max_spin.setSuffix(" mm")
        self.max_spin.setValue(float(obj.MaxThickness))
        self.max_spin.valueChanged.connect(self._settings_changed)

        self.tol_spin = QtGui.QDoubleSpinBox()
        self.tol_spin.setRange(0.0, 100.0)
        self.tol_spin.setDecimals(1)
        self.tol_spin.setSuffix(" %")
        self.tol_spin.setValue(obj.Tolerance * 100.0)
        self.tol_spin.valueChanged.connect(self._settings_changed)

        self.side_combo = QtGui.QComboBox()
        for side in geometry_shellbuilder.SHELL_SIDES:
            self.side_combo.addItem(side)
        index = self.side_combo.findText(obj.Side)
        if index >= 0:
            self.side_combo.setCurrentIndex(index)

        self.ratio_spin = QtGui.QDoubleSpinBox()
        self.ratio_spin.setRange(0.0, 1.0)
        self.ratio_spin.setSingleStep(0.05)
        self.ratio_spin.setValue(obj.Ratio)

        self.close_check = QtGui.QCheckBox(
            FreeCAD.Qt.translate("FEM", "Close junctions")
        )
        self.close_check.setChecked(bool(obj.CloseJunctions))
        self.close_check.setToolTip(
            FreeCAD.Qt.translate(
                "FEM",
                "Grow the sheets of walls that meet until they close on one another. "
                "Switched off, each sheet ends at its own wall, half a thickness short "
                "of its neighbours.",
            )
        )
        self.close_check.toggled.connect(self._junctions_toggled)

        self.reach_spin = QtGui.QDoubleSpinBox()
        self.reach_spin.setRange(0.0, 1000.0)
        self.reach_spin.setDecimals(2)
        self.reach_spin.setSuffix(" mm")
        # Nought is not a reach of nothing, it is the reach taken from the
        # walls, and the box says so rather than showing a number that would
        # mean the joints stay open.
        self.reach_spin.setSpecialValueText(FreeCAD.Qt.translate("FEM", "Automatic"))
        self.reach_spin.setValue(float(obj.JunctionReach))
        self.reach_spin.setToolTip(
            FreeCAD.Qt.translate(
                "FEM",
                "How far a sheet may reach past its own wall to find the joint. It has "
                "to clear the neighbour's half thickness and any fillet in the root of "
                "the joint. Automatic uses twice the thickest wall.",
            )
        )
        self.reach_spin.valueChanged.connect(self._settings_changed)
        self.reach_row = self._labelled_row(
            FreeCAD.Qt.translate("FEM", "Reach"), self.reach_spin
        )
        self.junction_page = QtGui.QWidget()
        junctions = QtGui.QVBoxLayout()
        junctions.setContentsMargins(0, 0, 0, 0)
        junctions.addWidget(self.close_check)
        junctions.addWidget(self.reach_row)
        self.junction_page.setLayout(junctions)

        # What a method asks for is shown and the other hidden, rather than
        # stacked, so the panel does not hold the height of both open at once.
        self.side_page = self._labelled_row(
            FreeCAD.Qt.translate("FEM", "Keep face"), self.side_combo
        )
        self.ratio_page = self._labelled_row(FreeCAD.Qt.translate("FEM", "Ratio"), self.ratio_spin)

        self.scan_button = QtGui.QPushButton(FreeCAD.Qt.translate("FEM", "Scan"))
        self.scan_button.clicked.connect(self.scan)

        self.wall_list = QtGui.QTreeWidget()
        self.wall_list.setColumnCount(4)
        self.wall_list.setHeaderLabels(
            [
                FreeCAD.Qt.translate("FEM", "Wall"),
                FreeCAD.Qt.translate("FEM", "Faces"),
                FreeCAD.Qt.translate("FEM", "Thickness"),
                FreeCAD.Qt.translate("FEM", "Variation"),
            ]
        )
        self.wall_list.setRootIsDecorated(False)
        self.wall_list.setAlternatingRowColors(True)
        self.wall_list.setUniformRowHeights(True)
        self.wall_list.setSizePolicy(
            QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Expanding
        )
        self.wall_list.setMinimumHeight(160)
        # The face names are the one column with no natural width, so they take
        # what is left over. Sizing every column to its contents instead pushes
        # the last one off the edge and leaves the panel scrolling sideways for
        # a number that would have fitted.
        header = self.wall_list.header()
        header.setStretchLastSection(False)
        try:
            header.setSectionResizeMode(COLUMN_FACES, QtGui.QHeaderView.Stretch)
            for column in (COLUMN_WALL, COLUMN_THICKNESS, COLUMN_VARIATION):
                header.setSectionResizeMode(column, QtGui.QHeaderView.ResizeToContents)
        except AttributeError:
            header.setStretchLastSection(True)
        self.wall_list.itemChanged.connect(self._row_toggled)
        self.wall_list.currentItemChanged.connect(lambda *_: self._focus_changed())
        # Hovering a row is how a wall in the list is matched to a wall in the
        # view, so the list has to say where the mouse is - and say when it has
        # left, or the last row hovered stays lit for good.
        self.wall_list.setMouseTracking(True)
        self.wall_list.viewport().setMouseTracking(True)
        self.wall_list.itemEntered.connect(lambda item, _column: self._hover(item))
        self._leave_filter = _LeaveWatcher(self._hover_ended)
        self.wall_list.viewport().installEventFilter(self._leave_filter)

        self.pair_slot = self.picker.add_slot(
            "Pair",
            FreeCAD.Qt.translate("FEM", "Two faces of one wall"),
            _wall_rule(),
            marks=False,
            color=MARK_COLORS[MARK_PAIR],
        )
        # This one holds two faces and can never hold three.
        self.pair_slot.set_visible_rows(2)
        self.pair_slot.picksChanged.connect(lambda *_: self._update_buttons())

        self.add_button = QtGui.QPushButton(FreeCAD.Qt.translate("FEM", "Add wall"))
        self.add_button.clicked.connect(self.add_pair)
        self.remove_button = QtGui.QPushButton(FreeCAD.Qt.translate("FEM", "Remove"))
        self.remove_button.clicked.connect(self.remove_pair)

        self.summary = QtGui.QLabel()
        self.summary.setWordWrap(True)

        layout.addWidget(QtGui.QLabel(FreeCAD.Qt.translate("FEM", "Method")))
        layout.addWidget(self.method_combo)
        layout.addWidget(self.targets)
        layout.addLayout(self._row(FreeCAD.Qt.translate("FEM", "Max thickness"), self.max_spin))
        layout.addLayout(self._row(FreeCAD.Qt.translate("FEM", "Tolerance"), self.tol_spin))
        layout.addWidget(self.side_page)
        layout.addWidget(self.ratio_page)
        layout.addWidget(self.junction_page)
        layout.addWidget(self.scan_button)
        layout.addWidget(self.wall_list, 1)
        layout.addWidget(self.pair_slot)
        buttons = QtGui.QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        layout.addLayout(buttons)
        layout.addWidget(self.summary)
        self.form.setLayout(layout)

        self.targets.picksChanged.connect(lambda *_: self._targets_changed())
        self._loading = False

        self._update_method_page()
        self.picker.begin_selection()
        self.picker.arm("Targets")
        self.picker.consume_handoff()
        self._update_marks()
        self.scan()

    # ----------------------------------------------------------------- layout

    @staticmethod
    def _row(label, widget):
        row = QtGui.QHBoxLayout()
        row.addWidget(QtGui.QLabel(label))
        row.addWidget(widget)
        return row

    def _labelled_row(self, label, widget):
        """
        A labelled row that can be shown and hidden on its own.

        Wrapping the row in a widget is what lets it be hidden, and it also
        puts the row one layout deeper than the rows that are added straight
        to the panel. The margins of that extra layer are taken out, or the
        label steps to the right of every other label beside it.
        """
        page = QtGui.QWidget()
        row = self._row(label, widget)
        row.setContentsMargins(0, 0, 0, 0)
        page.setLayout(row)
        return page

    # ---------------------------------------------------------------- changes

    def _element_links(self):
        return _references_to_links(self.targets.picks)

    def _method_changed(self):
        self._update_method_page()
        self._settings_changed()

    def _junctions_toggled(self):
        self.reach_row.setEnabled(self.close_check.isChecked())
        self._settings_changed()

    def _settings_changed(self):
        """
        Say the list no longer answers for the settings, and stop there.

        Searching a part for walls costs real time, and it was being spent on
        every change of mind - a tick in the list, a solid picked, a number
        nudged. What the search costs is the user's to spend, so it is spent
        when the button is pressed and not before.
        """
        if self._loading:
            return
        self._stale = True
        self._update_summary()
        # The walls are still the walls, so what a sheet would look like can be
        # redrawn without searching for them again.
        self._ask_for_preview()

    def _update_method_page(self):
        skin = self.method_combo.currentText() == geometry_shellbuilder.METHOD_SKIN
        self.side_page.setVisible(skin)
        self.ratio_page.setVisible(not skin)
        # Two skins kept on the outside of a corner never meet however far
        # either runs, so there is no joint to close and nothing to ask about.
        self.junction_page.setVisible(not skin)
        self.reach_row.setEnabled(self.close_check.isChecked())

    def _targets_changed(self):
        self._update_marks()
        self._settings_changed()

    def _update_marks(self):
        if not self.base_obj:
            return
        elements = [sub for obj, sub in self.targets.picks if obj == self.base_obj and sub]
        view_geometry_base.set_input_marks(
            self.obj, MARK_TARGETS, elements, MARK_COLORS[MARK_TARGETS]
        )

    def _update_buttons(self):
        # The list keeps emitting while it is torn down, and by then the pick
        # boxes may be gone on the C++ side, so what they say is asked for
        # defensively rather than assumed to still be there.
        try:
            self.add_button.setEnabled(len(self.pair_slot.picks) == 2)
            row = self._current_row()
            self.remove_button.setEnabled(row is not None and row.kind == ROW_ADDED)
        except RuntimeError:
            return

    def _current_row(self):
        item = self.wall_list.currentItem()
        if item is None:
            return None
        index = item.data(COLUMN_WALL, QtCore.Qt.UserRole)
        if index is None or index >= len(self._rows):
            return None
        return self._rows[index]

    def _hover(self, item):
        """Light the two faces of the wall the mouse is over."""
        index = item.data(COLUMN_WALL, QtCore.Qt.UserRole) if item is not None else None
        row = self._rows[index] if index is not None and index < len(self._rows) else None
        self._hovered = row
        self._mark_wall(row)

    def _hover_ended(self):
        self._hovered = None
        self._mark_wall(self._current_row())

    def _focus_changed(self):
        """A row stays lit once it is clicked, so the mouse can go elsewhere."""
        self._update_buttons()
        if self._hovered is None:
            self._mark_wall(self._current_row())

    def _mark_wall(self, row):
        """
        Show which wall a row is, on the geometry.

        Its two faces in two colours, because which of them is the outer one is
        what the Keep face setting turns on, and a wall is far easier to find in
        the view than in a list of face names.
        """
        if not self.base_obj:
            return
        outer, inner = ("", "")
        if row is not None and row.kind in (ROW_FOUND, ROW_ADDED):
            outer, inner = (row.faces + ("", ""))[:2]
        view_geometry_base.set_input_marks(
            self.obj, MARK_WALL_OUTER, [outer] if outer else [], MARK_COLORS[MARK_WALL_OUTER]
        )
        view_geometry_base.set_input_marks(
            self.obj, MARK_WALL_INNER, [inner] if inner else [], MARK_COLORS[MARK_WALL_INNER]
        )

    def _ask_for_preview(self):
        """
        Queue the overlay rather than build it.

        The sheets of a mid-surface take about as long to build as the search
        takes to find the walls, so building them inside a click would be felt.
        Asked for and drawn a moment later, a burst of changes costs one draw.
        """
        self._preview_timer.start(PREVIEW_DELAY)

    def _draw_preview(self):
        """Show the faces the step would make from the walls now in use."""
        if not self.base_obj:
            return
        try:
            if not self._enabled_walls:
                view_geometry_base.clear_tool_preview(self.obj)
                return
            # The whole of what the step does to a body, asked for with the
            # settings still being edited. Building the sheets directly here
            # instead drew what a body that is wholly replaced would give, and
            # a body that has to be cut got something else entirely when OK
            # was pressed - a closed shell promised and an open one built.
            settings = geometry_shellbuilder.ShellSettings(
                method=self.method_combo.currentText(),
                ratio=self.ratio_spin.value(),
                side=self.side_combo.currentText(),
                min_coverage=self.obj.MinCoverage,
                close_junctions=self.close_check.isChecked(),
                reach=self.reach_spin.value(),
                # What is ticked off in the list here, not what the object was
                # last saved with, or the drawing would answer for settings the
                # user has already moved on from.
                curated=bool(self._excluded) or bool(self._pairs),
            )
            # Which bodies close on which, asked of the same code the step
            # asks. Left out, the drawing showed every body reduced on its own
            # and a junction between two of them was missing from it although
            # the result had one.
            joined = geometry_shellbuilder.joined_neighbours(self._enabled_walls)
            sheets = []
            for index, (solid, walls) in enumerate(self._enabled_walls):
                produced, _, _, _ = geometry_shellbuilder.shell_of_solid(
                    solid, walls, settings, neighbours=joined[index]
                )
                sheets.extend(produced)
            if not sheets:
                view_geometry_base.clear_tool_preview(self.obj)
                return
            shape = Part.makeCompound([sheet.face for sheet in sheets])
            view_geometry_base.set_shape_preview(
                self.obj, shape, PREVIEW_COLOR, PREVIEW_TRANSPARENCY
            )
        except Exception:
            # A preview is a convenience. It must never be the reason a panel
            # falls over, so a shape that will not build simply is not shown.
            view_geometry_base.clear_tool_preview(self.obj)

    def _row_toggled(self, item, column=COLUMN_WALL):
        """A wall switched off here is left out of the result."""
        if self._loading:
            return
        index = item.data(COLUMN_WALL, QtCore.Qt.UserRole)
        if index is None or index >= len(self._rows):
            return
        row = self._rows[index]
        if row.name is None:
            return
        if item.checkState(COLUMN_WALL) == QtCore.Qt.Checked:
            self._excluded.discard(row.name)
        else:
            self._excluded.add(row.name)

        # The walls are the same walls whatever is done with them, so the list
        # is redrawn from what the last search found rather than searched again
        # - but not from in here. This runs while the view is still working on
        # the click, and clearing the list would delete the very item it is
        # holding. Queued for the moment that is over, it is safe.
        QtCore.QTimer.singleShot(0, self._refresh_list)

    # -------------------------------------------------------------- the walls

    def _name_of(self, face):
        return geometry_shellbuilder.face_name(self._names, face)

    def _add_row(self, row, checkable=False, color=None, span=False):
        item = QtGui.QTreeWidgetItem(row.columns)
        # A note is a sentence in a column sized for face names, so it is elided
        # when the panel is narrow. Spanning the row would be the fix and the
        # call for it takes this build of PySide down, so the whole of it is
        # kept where hovering will show it.
        full = " ".join(text for text in row.columns if text).strip()
        for column in range(len(row.columns)):
            item.setToolTip(column, full)
        item.setData(COLUMN_WALL, QtCore.Qt.UserRole, len(self._rows))
        if checkable:
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(
                COLUMN_WALL,
                QtCore.Qt.Unchecked if row.name in self._excluded else QtCore.Qt.Checked,
            )
        else:
            item.setFlags(QtCore.Qt.ItemIsEnabled)
        if color is not None:
            for column in range(self.wall_list.columnCount()):
                item.setForeground(column, QtGui.QBrush(color))
        self._rows.append(row)
        self.wall_list.addTopLevelItem(item)
        if span and hasattr(item, "setFirstColumnSpanned"):
            # A note is a sentence, not a row of values, and a column sized for
            # face names cuts it off. Spanning has to come after the item is in
            # the tree, and the tree must not be being rebuilt from inside one
            # of its own signals when it does.
            item.setFirstColumnSpanned(True)

    def _wall_row(self, kind, number, wall, pair=None):
        label = FreeCAD.Qt.translate("FEM", "Solid {n}").format(n=number)
        if kind == ROW_ADDED:
            label = FreeCAD.Qt.translate("FEM", "Solid {n}, added").format(n=number)
        return _Row(
            kind,
            [
                label,
                f"{self._name_of(wall.outer) or '?'} + {self._name_of(wall.inner) or '?'}",
                f"{wall.thickness:.2f} mm",
                f"{wall.spread * 100:.1f} %",
            ],
            name=self._name_of(wall.outer),
            pair=pair,
            faces=(self._name_of(wall.outer), self._name_of(wall.inner)),
        )

    def scan(self):
        """
        Search the input for walls, and hold on to what is found.

        This is the only thing here that looks at the geometry, and it runs when
        the button is pressed. Everything after it - a wall switched off, one
        added by hand, a row redrawn - works from what this left behind.
        """
        if not self.base_obj or self.base_obj.Shape.isNull():
            self._bodies = []
            self._stale = False
            self._refresh_list()
            return

        shape = self.base_obj.Shape
        self._names = geometry_shellbuilder.face_names(shape)
        settings = _Settings(self._element_links(), self._pairs)
        # Each pair is resolved on its own so that one which no longer names a
        # face costs its own row and not the alignment of every row after it.
        picked = []
        for pair in self._pairs:
            for owner, wall in geometry_shellbuilder.manual_walls(
                _Settings([], [pair]), shape
            ):
                picked.append((pair, owner, wall))

        max_thickness = self.max_spin.value()
        tolerance = self.tol_spin.value() / 100.0

        self._bodies = []
        for number, solid in enumerate(
            geometry_shellbuilder._target_solids(settings, shape), start=1
        ):
            near_misses = []
            found = geometry_shellbuilder.walls_of_solid(
                solid, max_thickness, tolerance, rejected=near_misses
            )
            body = _Body(number, solid, found, near_misses)
            body.added = [
                (pair, wall) for pair, owner, wall in picked if owner.isSame(solid)
            ]
            self._bodies.append(body)

        self._stale = False
        self._refresh_list()

    def _refresh_list(self):
        """Redraw the list from the last search, with nothing measured again."""
        was_loading = self._loading
        self._loading = True
        self.wall_list.blockSignals(True)
        self.wall_list.clear()
        self._rows = []

        used = 0
        enabled = []
        for body in self._bodies:
            for wall in body.found:
                self._add_row(self._wall_row(ROW_FOUND, body.number, wall), checkable=True)
            for pair, wall in body.added:
                self._add_row(
                    self._wall_row(ROW_ADDED, body.number, wall, pair),
                    checkable=True,
                    color=ADDED_COLOR,
                )

            walls = [
                wall
                for wall in body.found + [wall for _, wall in body.added]
                if self._name_of(wall.outer) not in self._excluded
            ]
            used += len(walls)
            if walls:
                # Kept with the body they came from: a mid-surface is grown
                # into the joints beside it by asking the body where its
                # material carries on, so the preview needs to know which
                # body each set of walls belongs to.
                enabled.append((body.solid, walls))
            self._add_note(body, walls)

            for line in geometry_shellbuilder.near_miss_report(
                body.near_misses, self.max_spin.value(), self.tol_spin.value() / 100.0
            ):
                self._add_row(
                    _Row(ROW_NOTE, ["    " + line, "", "", ""]),
                    color=QUIET_COLOR,
                    span=True,
                )

        self.wall_list.blockSignals(False)
        self._loading = was_loading
        self._enabled_walls = enabled
        self._update_summary(used)
        self._update_buttons()
        self._ask_for_preview()

    def _add_note(self, body, walls):
        """
        What is going to become of a body, as far as it can be said cheaply.

        The share its walls cover is arithmetic on areas. Whether a body short
        of that can be cut free is not - it needs the cuts made to find out - so
        that is left to the search rather than worked out on every tick.
        """
        if not walls:
            text = FreeCAD.Qt.translate("FEM", "stays solid, no wall in use")
        else:
            share = geometry_shellbuilder.wall_coverage(walls, body.solid)
            if share >= self.obj.MinCoverage:
                text = FreeCAD.Qt.translate("FEM", "reduces, walls cover {c:.0f}%").format(
                    c=share * 100.0
                )
            else:
                text = FreeCAD.Qt.translate(
                    "FEM", "walls cover {c:.0f}%, the rest is cut free or kept"
                ).format(c=share * 100.0)
        self._add_row(
            _Row(ROW_NOTE, ["    " + text, "", "", ""]), color=NOTE_COLOR, span=True
        )

    def _update_summary(self, used=None):
        if self._stale:
            self.summary.setText(
                FreeCAD.Qt.translate("FEM", "Settings changed — press Scan to search again.")
            )
            return
        if used is None:
            used = sum(
                1
                for row in self._rows
                if row.kind in (ROW_FOUND, ROW_ADDED) and row.name not in self._excluded
            )
        walls = (
            FreeCAD.Qt.translate("FEM", "1 wall")
            if used == 1
            else FreeCAD.Qt.translate("FEM", "{w} walls").format(w=used)
        )
        solids = (
            FreeCAD.Qt.translate("FEM", "1 solid")
            if len(self._bodies) == 1
            else FreeCAD.Qt.translate("FEM", "{n} solids").format(n=len(self._bodies))
        )
        self.summary.setText(
            FreeCAD.Qt.translate("FEM", "{w} in use, {s} scanned.").format(
                w=walls, s=solids
            )
        )

    # --------------------------------------------------------------- the pair

    def add_pair(self):
        """
        Take the two picked faces as a wall of their own.

        The one wall it makes is worked out here rather than by searching the
        part again: the pair is known, and what it bounds is a question about
        those two faces.
        """
        if len(self.pair_slot.picks) != 2:
            return
        pair = (self.pair_slot.picks[0], self.pair_slot.picks[1])
        self._pairs.append(pair)
        self.pair_slot.set_picks([])
        self.picker.arm("Pair")

        if self.base_obj and not self.base_obj.Shape.isNull():
            settings = _Settings([], [pair])
            for owner, wall in geometry_shellbuilder.manual_walls(
                settings, self.base_obj.Shape
            ):
                for body in self._bodies:
                    if body.solid.isSame(owner):
                        body.added.append((pair, wall))
                        break
        self._refresh_list()

    def remove_pair(self):
        """
        Take a hand-added wall out again.

        Only those: a wall the search found comes back on the next scan however
        often it is deleted, so switching it off is the only thing that means
        anything, and offering to remove it would be a lie.
        """
        row = self._current_row()
        if row is None or row.kind != ROW_ADDED or row.pair is None:
            return
        self._pairs = [pair for pair in self._pairs if pair is not row.pair]
        for body in self._bodies:
            body.added = [entry for entry in body.added if entry[0] is not row.pair]
        self._refresh_list()

    # ---------------------------------------------------------------- closing

    def commit_properties(self):
        self.obj.Method = self.method_combo.currentText()
        self.obj.Elements = self._element_links()
        self.obj.MaxThickness = self.max_spin.value()
        self.obj.Tolerance = self.tol_spin.value() / 100.0
        self.obj.Side = self.side_combo.currentText()
        self.obj.Ratio = self.ratio_spin.value()
        self.obj.CloseJunctions = self.close_check.isChecked()
        self.obj.JunctionReach = self.reach_spin.value()
        self.obj.PairSources = _references_to_links([first for first, _ in self._pairs])
        self.obj.PairPartners = _references_to_links([second for _, second in self._pairs])
        self.obj.ExcludedWalls = (
            [(self.base_obj, sorted(self._excluded))]
            if self._excluded and self.base_obj
            else []
        )

    def deactivate(self):
        # Cut the list loose before the pick boxes go, or its parting signals
        # arrive at handlers that ask deleted widgets what they hold.
        try:
            self.wall_list.itemChanged.disconnect()
            self.wall_list.currentItemChanged.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._preview_timer.stop()
        self.picker.finish_selection()
        if self.base_obj:
            view_geometry_base.clear_input_marks(
                self.obj, MARK_TARGETS, MARK_PAIR, MARK_WALL_OUTER, MARK_WALL_INNER
            )
            view_geometry_base.clear_tool_preview(self.obj)

    def accept(self):
        self.commit_properties()
        self.deactivate()
        return super().accept()

    def reject(self):
        self.deactivate()
        return super().reject()
