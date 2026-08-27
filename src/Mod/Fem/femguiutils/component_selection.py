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

from femmesh import meshcomponents


class ComponentSelection(QtGui.QGroupBox):
    """
    Picker for the geometry components a mesh object meshes.

    Components are the unit the analysis view panel names things by, so they
    are the unit here too, with their toplevel elements as read-only detail.
    A component another mesh object meshes is shown but locked; it has to be
    taken over from the context menu, which is what keeps the mesh group free
    of overlapping claims.
    """

    selectionChanged = QtCore.Signal()

    # Components can hold a lot of solids, so the row only names a few of them
    max_shown_elements = 3

    def __init__(self, obj, parent=None):
        super().__init__(parent)
        self.obj = obj
        self.geometry = meshcomponents.geometry_of(obj)

        self.setTitle(FreeCAD.Qt.translate("FEM", "Components to mesh"))
        self._setup_ui()
        self.rebuild()

    def _setup_ui(self):
        self.all_check = QtGui.QCheckBox(FreeCAD.Qt.translate("FEM", "All components"))
        self.all_check.setToolTip(
            FreeCAD.Qt.translate(
                "FEM",
                "Mesh the whole geometry, components added later included.\n"
                "Unchecking spells the components out so single ones can be dropped.\n"
                "Only available while no other mesh object meshes a component.",
            )
        )

        self.list = QtGui.QListWidget()
        self.list.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        self.list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

        self.summary = QtGui.QLabel()
        self.summary.setWordWrap(True)

        layout = QtGui.QVBoxLayout()
        layout.addWidget(self.all_check)
        layout.addWidget(self.list)
        layout.addWidget(self.summary)
        self.setLayout(layout)

        self.all_check.toggled.connect(self._all_toggled)
        self.list.itemChanged.connect(self._item_changed)
        self.list.itemSelectionChanged.connect(self._select_in_view)
        self.list.customContextMenuRequested.connect(self._context_menu)

    # data -------------------------------------------------------------------

    def has_components(self):
        """True if the mesh object meshes at least one component."""
        return bool(meshcomponents.selected_components(self.obj))

    def hint(self):
        """What is missing before the mesh object can run, empty if nothing."""
        if self.has_components():
            return ""
        return FreeCAD.Qt.translate("FEM", "Select at least one component to mesh")

    def rebuild(self):
        """Refill the rows from the document."""
        if self.geometry is None:
            self.setVisible(False)
            return

        self.owners = meshcomponents.component_owners(self.obj)
        self.mine = set(meshcomponents.selected_components(self.obj))
        count = meshcomponents.component_count(self.geometry)
        foreign = any(owner != self.obj for owner in self.owners.values())

        # Rebuilding sets check states, which must not be taken for user input
        self.list.blockSignals(True)
        self.all_check.blockSignals(True)

        self.list.clear()
        for index in range(1, count + 1):
            self.list.addItem(self._build_item(index))

        self.all_check.setChecked(meshcomponents.meshes_all(self.obj))
        # "All" keeps following the geometry, which only works while nobody
        # else meshes a part of it
        self.all_check.setEnabled(not foreign)

        self.list.blockSignals(False)
        self.all_check.blockSignals(False)

        self._update_summary(count)

    def _build_item(self, index):
        owner = self.owners.get(index)
        foreign = owner is not None and owner != self.obj

        item = QtGui.QListWidgetItem(self._item_text(index, owner))
        item.setData(QtCore.Qt.UserRole, index)
        item.setToolTip(self._item_tooltip(index, owner))
        item.setCheckState(QtCore.Qt.Checked if index in self.mine else QtCore.Qt.Unchecked)
        if foreign:
            # Locked rather than hidden: the context menu can take it over
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsUserCheckable)
            item.setForeground(QtGui.QPalette().color(QtGui.QPalette.Disabled, QtGui.QPalette.Text))
        return item

    def _item_text(self, index, owner):
        name = meshcomponents.component_name(index)
        if owner is not None and owner != self.obj:
            return FreeCAD.Qt.translate("FEM", "{} — meshed by {}").format(name, owner.Label)

        elements = self._element_names(index)
        if not elements:
            return name

        shown = elements[: self.max_shown_elements]
        text = ", ".join(shown)
        if len(elements) > len(shown):
            text += FreeCAD.Qt.translate("FEM", ", +{} more").format(len(elements) - len(shown))
        return f"{name} ({text})"

    def _item_tooltip(self, index, owner):
        elements = self._element_names(index)
        lines = [
            FreeCAD.Qt.translate("FEM", "{} elements: {}").format(
                len(elements), ", ".join(elements)
            )
        ]
        if owner is not None and owner != self.obj:
            lines.append(
                FreeCAD.Qt.translate("FEM", "Meshed by {}, right click to take it over").format(
                    owner.Label
                )
            )
        return "\n".join(lines)

    def _element_names(self, index):
        # Component indices are 1-based, FemGeometry is 0-based
        return list(self.geometry.getToplevelElements(index - 1))

    def _update_summary(self, count):
        if not self.mine:
            text = FreeCAD.Qt.translate("FEM", "No component selected, nothing to mesh.")
        else:
            missing = [i for i in range(1, count + 1) if i not in self.owners]
            if missing:
                names = ", ".join(meshcomponents.component_name(i) for i in missing)
                text = FreeCAD.Qt.translate("FEM", "Not meshed by any mesh object: {}").format(
                    names
                )
            else:
                text = FreeCAD.Qt.translate("FEM", "All components of the geometry are meshed.")
        self.summary.setText(text)

    # user input -------------------------------------------------------------

    def _all_toggled(self, checked):
        if checked:
            meshcomponents.assign_all(self.obj, self.geometry)
        else:
            # Leaving "all" keeps the components, just spelled out, so that
            # single ones can be unchecked from here on
            meshcomponents.assign_components(self.obj, self.geometry, self.mine)
        self._committed()

    def _item_changed(self, item):
        index = item.data(QtCore.Qt.UserRole)
        selection = set(self.mine)
        if item.checkState() == QtCore.Qt.Checked:
            selection.add(index)
        else:
            selection.discard(index)

        meshcomponents.assign_components(self.obj, self.geometry, selection)
        self._committed()

    def _context_menu(self, point):
        item = self.list.itemAt(point)
        if item is None:
            return

        index = item.data(QtCore.Qt.UserRole)
        owner = self.owners.get(index)
        if owner is None or owner == self.obj:
            return

        menu = QtGui.QMenu(self.list)
        action = menu.addAction(
            FreeCAD.Qt.translate("FEM", "Take over from {}").format(owner.Label)
        )
        if menu.exec_(self.list.mapToGlobal(point)) != action:
            return

        indices = {index}
        meshcomponents.take_over(self.obj, indices, self.owners)
        meshcomponents.assign_components(self.obj, self.geometry, self.mine | indices)
        self._committed()

    def _select_in_view(self):
        FreeCADGui.Selection.clearSelection()
        document = self.geometry.Document.Name
        for item in self.list.selectedItems():
            for element in self._element_names(item.data(QtCore.Qt.UserRole)):
                FreeCADGui.Selection.addSelection(document, self.geometry.Name, element)

    def _committed(self):
        # No recompute here: that would start meshing right from the panel
        self.rebuild()
        self.selectionChanged.emit()
