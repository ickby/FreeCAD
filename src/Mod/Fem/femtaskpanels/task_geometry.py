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

import FreeCADGui

from . import base_femtaskpanel


class _ObjectSelectionWidget(QtGui.QWidget):
    """List of linked document objects with Add / Clear for a property."""

    def __init__(self, obj, propname, parent=None):
        super().__init__(parent)

        self.obj = obj
        self.prop = propname
        self.selected = []

        self.Add = QtGui.QPushButton()
        self.Add.setText("Add")
        self.Add.clicked.connect(self.add_selection)
        self.Remove = QtGui.QPushButton()
        self.Remove.setText("Clear")
        self.Remove.clicked.connect(self.clear_all)
        self.List = QtGui.QListWidget()

        hor = QtGui.QHBoxLayout()
        hor.addWidget(self.Add)
        hor.addWidget(self.Remove)

        ver = QtGui.QVBoxLayout()
        ver.addWidget(self.List)
        ver.addLayout(hor)
        self.setLayout(ver)

        used = getattr(obj, propname)
        if isinstance(used, list):
            self.selected = list(used)
            for linked in used:
                self.List.addItem(linked.Label)
        elif used:
            self.selected = [used]
            self.List.addItem(used.Label)

    def _write_property(self):
        if "List" in self.obj.getTypeIdOfProperty(self.prop):
            setattr(self.obj, self.prop, self.selected)
        else:
            setattr(self.obj, self.prop, self.selected[0] if self.selected else None)

    def add_selection(self):
        for new_obj in FreeCADGui.Selection.getSelection():
            if new_obj not in self.selected:
                self.selected.append(new_obj)
                self.List.addItem(new_obj.Label)
        self._write_property()

    def clear_all(self):
        self.selected = []
        self.List.clear()
        self._write_property()


class _ImportTaskPanel(base_femtaskpanel._BaseTaskPanel):
    """Task panel for GeometryImport Embed mode and Import links."""

    def __init__(self, obj):
        super().__init__(obj)

        self.data_widget = QtGui.QWidget()
        vertical_layout = QtGui.QVBoxLayout()

        self.Keep = QtGui.QRadioButton("Keep separated")
        self.Embed = QtGui.QRadioButton("Embed imports")
        self.EmbedAll = QtGui.QRadioButton("Embed into existing geometry")
        self.Select = _ObjectSelectionWidget(self.obj, "Import")

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
