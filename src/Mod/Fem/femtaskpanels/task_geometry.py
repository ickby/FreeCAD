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

__title__ = "FreeCAD FEM geometry task panels"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

## @package task_geometry
#  \ingroup FEM
#  \brief Task panels for analysis geometry tools

from PySide import QtGui

from femguiutils.selection_slots import from_slot_specs

from . import base_femtaskpanel


class _ImportTaskPanel(base_femtaskpanel._BaseTaskPanel):
    """Task panel for GeometryImport Embed mode and Import links."""

    def __init__(self, obj):
        super().__init__(obj)

        self.data_widget = QtGui.QWidget()
        vertical_layout = QtGui.QVBoxLayout()

        self.Keep = QtGui.QRadioButton("Keep separated")
        self.Embed = QtGui.QRadioButton("Embed imports")
        self.EmbedAll = QtGui.QRadioButton("Embed into existing geometry")
        self.Select = from_slot_specs(
            self.obj,
            [
                {
                    "property": "Import",
                    "title": "Import",
                    "types": (),
                    "allow_empty_sub": True,
                    "scope": "any",
                    "armed": True,
                    "marks": False,
                }
            ],
        )

        vertical_layout.addWidget(self.Keep)
        vertical_layout.addWidget(self.Embed)
        vertical_layout.addWidget(self.EmbedAll)
        vertical_layout.addWidget(self.Select)

        self.data_widget.setLayout(vertical_layout)
        self.data_widget.setWindowTitle("Import settings")

        self.__init_widgets()
        self.form = [self.data_widget]

    def __init_widgets(self):
        if self.obj.Embed == "Seperated":
            self.Keep.setChecked(True)
        elif self.obj.Embed == "Embed import":
            self.Embed.setChecked(True)
        elif self.obj.Embed == "Embed all":
            self.EmbedAll.setChecked(True)

        self.Keep.clicked.connect(self.embed_changed)
        self.Embed.clicked.connect(self.embed_changed)
        self.EmbedAll.clicked.connect(self.embed_changed)

    def embed_changed(self):
        if self.Keep.isChecked():
            self.obj.Embed = "Seperated"
        elif self.Embed.isChecked():
            self.obj.Embed = "Embed import"
        elif self.EmbedAll.isChecked():
            self.obj.Embed = "Embed all"

    def accept(self):
        self.Select.finish_selection()
        return super().accept()

    def reject(self):
        self.Select.finish_selection()
        return super().reject()

