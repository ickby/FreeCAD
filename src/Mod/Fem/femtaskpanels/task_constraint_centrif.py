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

__title__ = "FreeCAD FEM constraint centrif task panel for the document object"
__author__ = "Bernd Hahnebach"
__url__ = "https://www.freecad.org"

## @package task_constraint_centrif
#  \ingroup FEM
#  \brief task panel for constraint centrif object

from PySide import QtCore
from PySide import QtGui

import FreeCAD
import FreeCADGui

from femguiutils import selection_slots
from . import base_femtaskpanel


class _TaskPanel(base_femtaskpanel._BaseTaskPanel):
    """
    The TaskPanel for editing References property of FemConstraintCentrif objects
    """

    def __init__(self, obj):
        super().__init__(obj)

        # parameter widget
        self.parameter_widget = FreeCADGui.PySideUic.loadUi(
            FreeCAD.getHomePath() + "Mod/Fem/Resources/ui/ConstraintCentrif.ui"
        )
        QtCore.QObject.connect(
            self.parameter_widget.qsb_rotation_frequency,
            QtCore.SIGNAL("valueChanged(Base::Quantity)"),
            self.rotation_frequency_changed,
        )
        self.init_parameter_widget()

        self.selection_widget = selection_slots.from_slot_specs(
            obj,
            [
                {
                    "id": "References",
                    "property": "References",
                    "title": FreeCAD.Qt.translate("FEM", "Body"),
                    "types": ["Solid", "Face"],
                    "armed": True,
                },
                {
                    "id": "RotationAxis",
                    "property": "RotationAxis",
                    "title": FreeCAD.Qt.translate("FEM", "Axis"),
                    "types": ["Edge"],
                    "max_count": 1,
                },
            ],
        )

        self.form = [self.parameter_widget, self.selection_widget]

    def accept(self):
        items = len(self.selection_widget.slot("RotationAxis").picks)
        FreeCAD.Console.PrintMessage(
            "Task panel: found axis references: {}\n{}\n".format(
                items, self.selection_widget.slot("RotationAxis").picks
            )
        )

        if items != 1:
            msgBox = QtGui.QMessageBox()
            msgBox.setIcon(QtGui.QMessageBox.Question)
            msgBox.setText(
                f"Constraint Centrif requires exactly one line\n\nfound references: {items}"
            )
            msgBox.setWindowTitle("FreeCAD FEM Constraint Centrif - Axis Selection")
            retryButton = msgBox.addButton(QtGui.QMessageBox.Retry)
            ignoreButton = msgBox.addButton(QtGui.QMessageBox.Ignore)
            msgBox.exec_()

            if msgBox.clickedButton() == retryButton:
                return False
            elif msgBox.clickedButton() == ignoreButton:
                pass

        items = len(self.selection_widget.slot("References").picks)
        FreeCAD.Console.PrintMessage(
            "Task panel: found body references: {}\n{}\n".format(
                items, self.selection_widget.slot("References").picks
            )
        )

        if self.rotation_frequency == 0:
            msgBox = QtGui.QMessageBox()
            msgBox.setIcon(QtGui.QMessageBox.Question)
            msgBox.setText("Rotational speed is zero")
            msgBox.setWindowTitle("FEM Constraint Centrifuge - Rotational Speed Setting")
            retryButton = msgBox.addButton(QtGui.QMessageBox.Retry)
            ignoreButton = msgBox.addButton(QtGui.QMessageBox.Ignore)
            msgBox.exec_()

            if msgBox.clickedButton() == retryButton:
                return False
            elif msgBox.clickedButton() == ignoreButton:
                pass

        self.obj.RotationFrequency = self.rotation_frequency
        self.selection_widget.finish_selection()
        return super().accept()

    def reject(self):
        self.selection_widget.finish_selection()
        return super().reject()

    def init_parameter_widget(self):
        self.rotation_frequency = self.obj.RotationFrequency
        FreeCADGui.ExpressionBinding(self.parameter_widget.qsb_rotation_frequency).bind(
            self.obj, "RotationFrequency"
        )
        self.parameter_widget.qsb_rotation_frequency.setProperty("value", self.rotation_frequency)

    def rotation_frequency_changed(self, base_quantity_value):
        self.rotation_frequency = base_quantity_value
