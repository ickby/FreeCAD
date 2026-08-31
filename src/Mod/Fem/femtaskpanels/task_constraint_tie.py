# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2020 Bernd Hahnebach <bernd@bimstatik.org>              *
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

__title__ = "FreeCAD FEM constraint tie task panel for the document object"
__author__ = "Bernd Hahnebach"
__url__ = "https://www.freecad.org"

## @package task_constraint_tie
#  \ingroup FEM
#  \brief task panel for constraint tie object

from PySide import QtCore
from PySide import QtGui

import FreeCAD
import FreeCADGui

from femguiutils import selection_slots
from . import base_femtaskpanel


class _TaskPanel(base_femtaskpanel._BaseTaskPanel):
    """
    The TaskPanel for editing References property of FemConstraintTie objects
    """

    def __init__(self, obj):
        super().__init__(obj)

        # parameter widget
        self.parameter_widget = FreeCADGui.PySideUic.loadUi(
            FreeCAD.getHomePath() + "Mod/Fem/Resources/ui/ConstraintTie.ui"
        )
        QtCore.QObject.connect(
            self.parameter_widget.spb_tolerance,
            QtCore.SIGNAL("valueChanged(Base::Quantity)"),
            self.tolerance_changed,
        )
        QtCore.QObject.connect(
            self.parameter_widget.ckb_adjust, QtCore.SIGNAL("toggled(bool)"), self.adjust_changed
        )
        QtCore.QObject.connect(
            self.parameter_widget.ckb_rev_master,
            QtCore.SIGNAL("toggled(bool)"),
            self.reversed_master_changed,
        )
        QtCore.QObject.connect(
            self.parameter_widget.ckb_rev_slave,
            QtCore.SIGNAL("toggled(bool)"),
            self.reversed_slave_changed,
        )
        # Reading the object into the boxes trips their signals, which must not
        # be read back as the user having picked a side.
        self._loading = True
        self.init_parameter_widget()
        self._loading = False
        # Tie's master and slave slots have no obvious primary; the command
        # does not stash a prefill.
        self.selection_widget = selection_slots.from_slot_specs(
            obj,
            [
                {
                    "id": "slave",
                    "property": "References",
                    "role": "slave",
                    "title": FreeCAD.Qt.translate("FEM", "Slave"),
                    "types": ["Edge", "Face"],
                    "armed": True,
                },
                {
                    "id": "master",
                    "property": "References",
                    "role": "master",
                    "title": FreeCAD.Qt.translate("FEM", "Master"),
                    "types": ["Edge", "Face"],
                    "max_count": 1,
                },
            ],
        )

        # form made from param and selection widget
        self.form = [self.selection_widget, self.parameter_widget]

    def accept(self):
        master = self.selection_widget.slot("master").picks
        slave = self.selection_widget.slot("slave").picks
        items = len(master) + len(slave)
        FreeCAD.Console.PrintMessage(
            f"Task panel: found master references: {len(master)}\n{master}\n"
        )
        FreeCAD.Console.PrintMessage(
            f"Task panel: found slave references: {len(slave)}\n{slave}\n"
        )

        if items != 2:
            msgBox = QtGui.QMessageBox()
            msgBox.setIcon(QtGui.QMessageBox.Question)
            msgBox.setText(
                f"Constraint Tie requires exactly one master and one slave references\n\nfound references: {items}"
            )
            msgBox.setWindowTitle("FreeCAD FEM Constraint Tie")
            retryButton = msgBox.addButton(QtGui.QMessageBox.Retry)
            ignoreButton = msgBox.addButton(QtGui.QMessageBox.Ignore)
            msgBox.exec_()

            if msgBox.clickedButton() == retryButton:
                return False
            elif msgBox.clickedButton() == ignoreButton:
                pass
        self.obj.Tolerance = self.tolerance
        self.obj.Adjust = self.adjust
        self.write_sides()
        self.selection_widget.finish_selection()
        return super().accept()

    def reject(self):
        self.selection_widget.finish_selection()
        return super().reject()

    def init_parameter_widget(self):
        self.tolerance = self.obj.Tolerance
        self.adjust = self.obj.Adjust
        self.reversed_master = self.obj.ReversedMaster
        self.reversed_slave = self.obj.ReversedSlave
        FreeCADGui.ExpressionBinding(self.parameter_widget.spb_tolerance).bind(
            self.obj, "Tolerance"
        )
        self.parameter_widget.spb_tolerance.setProperty("value", self.tolerance)
        self.parameter_widget.ckb_adjust.setChecked(self.adjust)
        self.parameter_widget.ckb_rev_master.setChecked(
            False if not self.reversed_master else self.reversed_master[0]
        )
        self.parameter_widget.ckb_rev_slave.setChecked(
            False if not self.reversed_slave else self.reversed_slave[0]
        )

    def tolerance_changed(self, base_quantity_value):
        self.tolerance = base_quantity_value

    def adjust_changed(self, bool_value):
        self.adjust = bool_value

    def reversed_master_changed(self, bool_value):
        self.reversed_master = [bool_value]
        self.write_sides()

    def reversed_slave_changed(self, bool_value):
        self.reversed_slave = [bool_value]
        self.write_sides()

    def write_sides(self):
        """
        Put the picked sides on the object at once, rather than on OK.

        The 3D marker follows these properties, and a marker that only moved
        once the panel was gone could not help anybody choose. Cancel takes
        them back with everything else the panel wrote.

        The lists run as long as the references they line up with, because the
        solver writer walks the two in step and would otherwise reverse the
        first slave only.
        """
        if self._loading:
            return
        count = sum(len(subs) for _, subs in self.obj.References)
        master = bool(self.reversed_master) and bool(self.reversed_master[0])
        slave = bool(self.reversed_slave) and bool(self.reversed_slave[0])
        self.obj.ReversedMaster = [master] * min(count, 1)
        self.obj.ReversedSlave = [slave] * max(count - 1, 0)
