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

from femguiutils.selection_rules import ReferenceRule
from femguiutils.selection_slots import ReferenceSelection
from femmesh import meshcomponents


class ComponentSelection(QtGui.QGroupBox):
    """
    Picker for the geometry components a mesh object meshes.

    Components are the unit the analysis view panel names things by, so they
    are the unit here too. 3D picks go through the shared reference slot with
    1-based ComponentN names; "All components" keeps following the geometry.
    """

    selectionChanged = QtCore.Signal()

    def __init__(self, obj, parent=None):
        super().__init__(parent)
        self.obj = obj
        self.geometry = meshcomponents.geometry_of(obj)
        self._updating = False

        self.setTitle(FreeCAD.Qt.translate("FEM", "Components to mesh"))
        self._setup_ui()
        self.rebuild()
        self.selection.consume_handoff()

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

        self.selection = ReferenceSelection(self.obj, geometry=self.geometry)
        self.slot = self.selection.add_slot(
            "Components",
            FreeCAD.Qt.translate("FEM", "Components"),
            ReferenceRule(component=True),
            marks=False,
        )
        self.selection.arm("Components")
        self.slot.picksChanged.connect(self._slot_changed)

        self.summary = QtGui.QLabel()
        self.summary.setWordWrap(True)

        layout = QtGui.QVBoxLayout()
        layout.addWidget(self.all_check)
        layout.addWidget(self.selection)
        layout.addWidget(self.summary)
        self.setLayout(layout)

        self.all_check.toggled.connect(self._all_toggled)

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

        self._updating = True
        self.all_check.blockSignals(True)
        self.all_check.setChecked(meshcomponents.meshes_all(self.obj))
        self.all_check.setEnabled(not foreign)
        self.all_check.blockSignals(False)

        picks = [
            (self.geometry, meshcomponents.component_name(index)) for index in sorted(self.mine)
        ]
        self.slot.picks = picks
        self.slot._rebuild()
        self.selection.setEnabled(not self.all_check.isChecked())
        self._updating = False

        self._update_summary(count)

    def finish_selection(self):
        self.selection.finish_selection()

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

    def _all_toggled(self, checked):
        if self._updating:
            return
        if checked:
            meshcomponents.assign_all(self.obj, self.geometry)
        else:
            meshcomponents.assign_components(self.obj, self.geometry, self.mine)
        self._committed()

    def _slot_changed(self, _slot):
        if self._updating or self.geometry is None:
            return
        indices = set()
        for obj, sub in self.slot.picks:
            if obj != self.geometry:
                continue
            index = meshcomponents.component_index(sub)
            if index is not None:
                indices.add(index)
        meshcomponents.assign_components(self.obj, self.geometry, indices)
        self._committed()

    def _committed(self):
        self.rebuild()
        self.selectionChanged.emit()
