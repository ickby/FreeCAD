# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2026 Stefan Tröger <stefantroeger@gmx.net>              *
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

__title__ = "FreeCAD FEM component selection widget for mesh task panels"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

## @package component_selection
#  \ingroup FEM
#  \brief widget to select the geometry components a mesh object meshes

from PySide import QtCore
from PySide import QtGui

import FreeCAD
import FreeCADGui

from femguiutils.selection_rules import resolve_pick
from femguiutils.selection_slots import hairline_color, header_button_side, muted_color
from femmesh import meshcomponents


COMPONENT_ROLE = QtCore.Qt.UserRole
FOREIGN_ROLE = QtCore.Qt.UserRole + 1
ELEMENT_ROLE = QtCore.Qt.UserRole + 2


def _tr(text):
    return FreeCAD.Qt.translate("FEM", text)


class _ViewPicker:
    """
    Selection observer and gate turning a 3D click into a ticked row.

    A component is not a reference: the only thing a click can say here is
    which component it landed in. So the gate lets through what maps to one
    and refuses the rest — which is also the answer to clicking a part of the
    document that is no part of the analysis geometry at all.
    """

    def __init__(self, owner):
        self.owner = owner
        self.notAllowedReason = ""
        self.active = False

    def start(self):
        if self.active:
            return
        FreeCADGui.Selection.addObserver(self)
        FreeCADGui.Selection.addSelectionGate(self)
        self.active = True

    def stop(self):
        if not self.active:
            return
        self.active = False
        try:
            FreeCADGui.Selection.removeSelectionGate()
        except Exception:
            pass
        try:
            FreeCADGui.Selection.removeObserver(self)
        except Exception:
            pass

    def allow(self, doc, obj, sub):
        if self.owner.components_at(obj, sub or ""):
            self.notAllowedReason = ""
            return True
        self.notAllowedReason = _tr("Not part of the geometry this mesh works on.")
        return False

    def addSelection(self, doc_name, obj_name, sub, pos):
        # Highlighting a row puts its elements in the 3D selection, which
        # would come straight back here and undo the tick that caused it.
        if self.owner.echoing:
            return
        document = FreeCAD.getDocument(doc_name) if doc_name else None
        obj = document.getObject(obj_name) if document else None
        indices = self.owner.components_at(obj, sub or "")
        FreeCADGui.Selection.clearSelection()
        if indices:
            self.owner.toggle_components(indices)


class ComponentSelection(QtGui.QFrame):
    """
    Picker for the geometry components a mesh object meshes.

    A checklist rather than a collected list of picks, because the set is
    closed and small and what is left out matters as much as what is taken:
    a component no mesh object claims fails the group, and one a sibling
    claims can only be had by taking it over. Neither is something a list of
    what this object happens to hold could show.

    Clicking in the 3D view still works — it ticks the row the click landed
    in, which is how "that blob there" gets said without knowing its number.
    """

    selectionChanged = QtCore.Signal()

    def __init__(self, obj, parent=None):
        super().__init__(parent)
        self.obj = obj
        self.geometry = meshcomponents.geometry_of(obj)
        self.owners = {}
        self.mine = set()
        self.echoing = False
        self._updating = False
        self._syncing_palette = False
        self._lookup = None
        self.picker = _ViewPicker(self)

        self.setObjectName("FemComponentSelection")
        self.setFrameShape(QtGui.QFrame.StyledPanel)
        self._build()
        self.rebuild()
        self._sync_palette()

    # -- construction --------------------------------------------------------

    def _build(self):
        self.pick_btn = QtGui.QToolButton()
        self.pick_btn.setObjectName("FemComponentPick")
        self.pick_btn.setCheckable(True)
        self.pick_btn.setAutoRaise(True)
        self.pick_btn.setText("◎")
        self.pick_btn.setToolTip(
            _tr("Click a component in the 3D view to tick it, click it again to drop it")
        )
        self.pick_btn.toggled.connect(self._pick_toggled)

        self.title_label = QtGui.QLabel(_tr("Components to mesh"))
        self.count_label = QtGui.QLabel()

        self.all_check = QtGui.QCheckBox(_tr("All components"))
        self.all_check.setToolTip(
            _tr(
                "Mesh the whole geometry, components added later included.\n"
                "Unchecking spells the components out so single ones can be dropped.\n"
                "Only available while no other mesh object meshes a component."
            )
        )
        self.all_check.toggled.connect(self._all_toggled)

        self.tree = QtGui.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemSelectionChanged.connect(self._select_in_view)
        self.tree.customContextMenuRequested.connect(self._context_menu)

        self.summary = QtGui.QLabel()
        self.summary.setWordWrap(True)

        header = QtGui.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.pick_btn)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.count_label)

        layout = QtGui.QVBoxLayout()
        layout.addLayout(header)
        layout.addWidget(self.all_check)
        layout.addWidget(self.tree)
        layout.addWidget(self.summary)
        self.setLayout(layout)
        self._sync_metrics()

    def _sync_metrics(self):
        side = header_button_side(self)
        glyph = QtGui.QFont(self.font())
        if glyph.pointSizeF() > 0:
            glyph.setPointSizeF(glyph.pointSizeF() * 1.3)
        else:
            glyph.setPixelSize(round(glyph.pixelSize() * 1.3))
        self.pick_btn.setFont(glyph)
        self.pick_btn.setFixedSize(side, side)

        # A handful of rows, so that a short list leaves no empty box behind
        # and a long one scrolls rather than pushing the mesh settings away
        row = self.fontMetrics().height() + 8
        self.tree.setMinimumHeight(row * 3)
        self.tree.setMaximumHeight(row * 9)

    # -- theme ---------------------------------------------------------------

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.PaletteChange:
            self._sync_palette()
        elif event.type() == QtCore.QEvent.FontChange and hasattr(self, "pick_btn"):
            self._sync_metrics()

    def _sync_palette(self):
        # Setting a stylesheet re-resolves the palette, which lands back here.
        if self._syncing_palette or not hasattr(self, "count_label"):
            return
        self._syncing_palette = True
        try:
            palette = self.palette()
            self.count_label.setStyleSheet(f"color: {muted_color(palette).name()};")
            self.summary.setStyleSheet(f"color: {muted_color(palette).name()};")
            self._sync_frame()
            self._tint_rows()
        finally:
            self._syncing_palette = False

    def _sync_frame(self):
        """Picking is a 2 px accent bar on the leading edge, as on a slot."""
        palette = self.palette()
        color = (
            palette.color(QtGui.QPalette.Highlight).name()
            if self.pick_btn.isChecked()
            else hairline_color(palette).name()
        )
        self.setStyleSheet(
            f"QFrame#FemComponentSelection {{ border: 1px solid {color};"
            f" border-left: 2px solid {color}; }}"
        )

    def _tint_rows(self):
        """A row's colour is a brush on the item, out of reach of a restyle."""
        muted = QtGui.QBrush(muted_color(self.palette(), on_base=True))
        # A brush is a change of the item like any other, and the rows would
        # come back through itemChanged as if somebody had ticked them.
        self.tree.blockSignals(True)
        try:
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                if item.data(0, FOREIGN_ROLE):
                    item.setForeground(0, muted)
                for row in range(item.childCount()):
                    item.child(row).setForeground(0, muted)
        finally:
            self.tree.blockSignals(False)

    # -- state ---------------------------------------------------------------

    def has_components(self):
        """True if the mesh object meshes at least one component."""
        return bool(meshcomponents.selected_components(self.obj))

    def hint(self):
        """What is missing before the mesh object can run, empty if nothing."""
        if self.has_components():
            return ""
        return _tr("Select at least one component to mesh")

    def rebuild(self):
        """Refill the rows from the document."""
        if self.geometry is None:
            self.setVisible(False)
            return

        self.owners = meshcomponents.component_owners(self.obj)
        self.mine = set(meshcomponents.selected_components(self.obj))
        count = meshcomponents.component_count(self.geometry)
        foreign = any(owner != self.obj for owner in self.owners.values())
        takes_all = meshcomponents.meshes_all(self.obj)

        # Refilling sets check states, which must not be read back as input
        self._updating = True
        self.tree.blockSignals(True)
        self.all_check.blockSignals(True)

        self.tree.clear()
        for index in range(1, count + 1):
            self.tree.addTopLevelItem(self._build_item(index))

        self.all_check.setChecked(takes_all)
        # "All" keeps following the geometry, which only works while nobody
        # else meshes a part of it
        self.all_check.setEnabled(not foreign)
        # Under "all" every component is in already, so there is nothing left
        # for a row or a 3D click to say.
        self.tree.setEnabled(not takes_all)
        self.pick_btn.setEnabled(not takes_all)
        if takes_all:
            self.pick_btn.setChecked(False)
        self.count_label.setText(
            _tr("{taken} of {total}").format(taken=len(self.mine), total=count)
        )

        self.tree.blockSignals(False)
        self.all_check.blockSignals(False)
        self._updating = False

        self._tint_rows()
        self._update_summary(count)

    def _build_item(self, index):
        owner = self.owners.get(index)
        foreign = owner is not None and owner != self.obj
        name = meshcomponents.component_name(index)

        item = QtGui.QTreeWidgetItem([name])
        item.setData(0, COMPONENT_ROLE, index)
        item.setCheckState(0, QtCore.Qt.Checked if index in self.mine else QtCore.Qt.Unchecked)
        if foreign:
            item.setText(0, _tr("{name} — meshed by {owner}").format(name=name, owner=owner.Label))
            item.setToolTip(
                0, _tr("Meshed by {owner}, right click to take it over").format(owner=owner.Label)
            )
            # Locked rather than hidden: the context menu can take it over
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsUserCheckable)
            item.setData(0, FOREIGN_ROLE, True)

        for element in self._element_names(index):
            child = QtGui.QTreeWidgetItem([element])
            child.setData(0, ELEMENT_ROLE, element)
            child.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            item.addChild(child)
        return item

    def _element_names(self, index):
        # Component indices are 1-based, FemGeometry is 0-based
        return list(self.geometry.getToplevelElements(index - 1))

    def _update_summary(self, count):
        """
        What the group is still short of, which is the point of the checklist.

        A component no mesh object claims fails the whole group, and it is
        nothing the ticks of this one object could show on their own.
        """
        missing = [i for i in range(1, count + 1) if self.owners.get(i) is None]
        if missing:
            names = ", ".join(meshcomponents.component_name(i) for i in missing)
            text = _tr("Not meshed by any mesh object: {}").format(names)
        else:
            text = _tr("Every component of the geometry is meshed.")
        self.summary.setText(text)

    # -- picking in the 3D view ----------------------------------------------

    def components_at(self, obj, sub):
        """
        Components a 3D pick lands in, empty when it lands outside them.

        Only this geometry answers: an import the analysis was built from is
        a different object, and a solid of it is no component of anything.
        """
        if self.geometry is None or obj is None:
            return []
        obj, sub = resolve_pick(obj, sub or "")
        if obj != self.geometry or not sub:
            return []

        leaf = sub.rsplit(".", 1)[-1]
        index = meshcomponents.component_index(leaf)
        if index is not None:
            count = meshcomponents.component_count(self.geometry)
            return [index] if 1 <= index <= count else []

        if self._lookup is None:
            self._lookup = meshcomponents.component_lookup(self.geometry)
        found = self._lookup.get(leaf)
        return [found] if found else []

    def toggle_components(self, indices):
        """Tick the components a pick landed in, or untick them again."""
        selection = set(self.mine)
        touched = []
        for index in indices:
            if self.owners.get(index) not in (None, self.obj):
                continue
            if index in selection:
                selection.discard(index)
            else:
                selection.add(index)
            touched.append(index)
        if not touched:
            return
        meshcomponents.assign_components(self.obj, self.geometry, selection)
        self._committed()
        self._reveal(touched)

    def _reveal(self, indices):
        """Put the rows a pick changed on screen, so the change is visible."""
        wanted = set(indices)
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if item.data(0, COMPONENT_ROLE) in wanted:
                item.setSelected(True)
                self.tree.scrollToItem(item)
        self.tree.blockSignals(False)

    # -- user input ----------------------------------------------------------

    def _pick_toggled(self, on):
        if on:
            self.picker.start()
        else:
            self.picker.stop()
        self._sync_frame()

    def _all_toggled(self, checked):
        if self._updating:
            return
        if checked:
            meshcomponents.assign_all(self.obj, self.geometry)
        else:
            # Leaving "all" keeps the components, just spelled out, so that
            # single ones can be unchecked from here on
            meshcomponents.assign_components(self.obj, self.geometry, self.mine)
        self._committed()

    def _item_changed(self, item, _column):
        if self._updating:
            return
        index = item.data(0, COMPONENT_ROLE)
        if index is None:
            return
        # Anything at all about a row is an itemChanged, its colour included
        checked = item.checkState(0) == QtCore.Qt.Checked
        if checked == (index in self.mine):
            return
        selection = set(self.mine)
        if checked:
            selection.add(index)
        else:
            selection.discard(index)
        meshcomponents.assign_components(self.obj, self.geometry, selection)
        self._committed()

    def _context_menu(self, point):
        item = self.tree.itemAt(point)
        if item is None:
            return
        if item.parent() is not None:
            item = item.parent()

        index = item.data(0, COMPONENT_ROLE)
        owner = self.owners.get(index)
        if owner is None or owner == self.obj:
            return

        menu = QtGui.QMenu(self.tree)
        action = menu.addAction(_tr("Take over from {}").format(owner.Label))
        if menu.exec_(self.tree.viewport().mapToGlobal(point)) != action:
            return

        indices = {index}
        meshcomponents.take_over(self.obj, indices, self.owners)
        meshcomponents.assign_components(self.obj, self.geometry, self.mine | indices)
        self._committed()

    def _select_in_view(self):
        """Show what a row stands for. The elements are what the view knows."""
        if self._updating or self.geometry is None:
            return
        wanted = []
        for item in self.tree.selectedItems():
            element = item.data(0, ELEMENT_ROLE)
            if element:
                wanted.append(element)
                continue
            index = item.data(0, COMPONENT_ROLE)
            if index is not None:
                wanted.extend(self._element_names(index))

        # These go through the gate and back to the observer, where they
        # would read as picks of their own.
        self.echoing = True
        try:
            FreeCADGui.Selection.clearSelection()
            document = self.geometry.Document.Name
            for element in wanted:
                FreeCADGui.Selection.addSelection(document, self.geometry.Name, element)
        finally:
            self.echoing = False

    # -- lifetime ------------------------------------------------------------

    def finish_selection(self):
        self.pick_btn.setChecked(False)
        self.picker.stop()

    def hideEvent(self, event):
        # Nothing off screen may keep hold of the 3D view
        self.picker.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self.pick_btn.isChecked():
            self.picker.start()

    def _committed(self):
        # No recompute here: that would start meshing right from the panel
        self.rebuild()
        self.selectionChanged.emit()
