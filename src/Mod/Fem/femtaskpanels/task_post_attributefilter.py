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
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

__title__ = "FreeCAD FEM attribution filter task panel for the document object"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

## @package task_post_attributefilter
#  \ingroup FEM
#  \brief task panel for post attribution filter object

from PySide import QtCore, QtGui

import FreeCAD
import FreeCADGui

from femobjects import post_attributefilter

from . import base_fempostpanel

translate = FreeCAD.Qt.translate

#: Role the entity or category name is kept in, so the label may be anything.
_KEY_ROLE = QtCore.Qt.UserRole


class _TaskPanel(base_fempostpanel._BasePostTaskPanel):
    """
    The TaskPanel for editing properties of the attribution filter

    The tree is the same shape as the one in the analysis view panel -
    categories as parents, the entities they hold as children, and a tri-state
    parent that follows its children - but it is filled from the tables stored
    on the result rather than from the live analysis. That is the whole point of
    the filter: the mesh and the geometry may be long gone, and the result still
    knows what it was computed from.
    """

    def __init__(self, vobj):
        super().__init__(vobj.Object)

        self.widget = FreeCADGui.PySideUic.loadUi(
            FreeCAD.getHomePath() + "Mod/Fem/Resources/ui/TaskPostAttribute.ui"
        )
        self.widget.setWindowIcon(FreeCADGui.getIcon(":/icons/FEM_PostFilterAttribute.svg"))
        self.__init_widget()

        self.form = [self.widget, vobj.createDisplayTaskWidget()]

    # Setup functions
    # ###############

    def __init_widget(self):

        self._attribution = post_attributefilter.Attribution(self.obj.getInputData())

        self._enumPropertyToCombobox(self.obj, "Attribute", self.widget.AttributeComboBox)
        self.__build_tree()

        self.widget.AttributeComboBox.currentTextChanged.connect(self._attribute_changed)
        self.widget.ElementTree.itemChanged.connect(self._item_changed)

    def __build_tree(self):
        """Fill the tree for the attribute currently chosen."""

        tree = self.widget.ElementTree
        tree.blockSignals(True)
        tree.clear()

        attribute = self.obj.Attribute
        checked = set(self.obj.Elements)

        if attribute == "Subelement":
            # An entity is its own category there, so a parent per entity would
            # be a row that never says anything the child does not.
            for entity in self._attribution.entities:
                self.__add_row(tree, entity, entity, entity in checked)
        else:
            for (key, label), entities in sorted(self._attribution.grouped(attribute).items()):
                parent = self.__add_row(tree, label or key, None, False)
                for entity in entities:
                    self.__add_row(parent, entity, entity, entity in checked)
                self.__update_parent(parent)

            loose = self._attribution.uncategorised(attribute)
            if loose:
                parent = self.__add_row(
                    tree, translate("FEM", "No {}").format(attribute.lower()), None, False
                )
                for entity in loose:
                    self.__add_row(parent, entity, entity, entity in checked)
                self.__update_parent(parent)

        # The cells no entity claims at all. They are a row of their own so a
        # partial attribution can be seen and excluded rather than staying
        # invisible, and the count is what makes it worth looking at.
        if self._attribution.unattributed_cells:
            item = self.__add_row(
                tree,
                translate("FEM", "Unattributed"),
                post_attributefilter.UNATTRIBUTED,
                post_attributefilter.UNATTRIBUTED in checked,
            )
            item.setText(1, str(self._attribution.unattributed_cells))

        tree.expandAll()
        tree.blockSignals(False)

    @staticmethod
    def __add_row(parent, label, key, checked):
        item = QtGui.QTreeWidgetItem(parent)
        item.setText(0, label)
        if key is not None:
            item.setData(0, _KEY_ROLE, key)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(0, QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
        else:
            item.setFlags(
                item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsAutoTristate
            )
        return item

    @staticmethod
    def __update_parent(parent):
        states = {parent.child(i).checkState(0) for i in range(parent.childCount())}
        if states == {QtCore.Qt.Checked}:
            parent.setCheckState(0, QtCore.Qt.Checked)
        elif states == {QtCore.Qt.Unchecked}:
            parent.setCheckState(0, QtCore.Qt.Unchecked)
        else:
            parent.setCheckState(0, QtCore.Qt.PartiallyChecked)

    def __checked_keys(self):
        """Every checked row that names something, parents excluded."""
        keys = []
        iterator = QtGui.QTreeWidgetItemIterator(self.widget.ElementTree)
        while iterator.value():
            item = iterator.value()
            key = item.data(0, _KEY_ROLE)
            if key is not None and item.checkState(0) == QtCore.Qt.Checked:
                keys.append(key)
            iterator += 1
        return keys

    # callbacks and logic
    # ###################

    def _attribute_changed(self, value):
        self.obj.Attribute = value
        # The checked entities are the same entities under any attribute, so the
        # choice survives a regrouping and only the tree around it is rebuilt.
        self.__build_tree()
        self._recompute()

    def _item_changed(self, item, column):
        if column != 0:
            return

        tree = self.widget.ElementTree
        tree.blockSignals(True)
        # A parent hands its state down; a child hands its parent a new summary.
        if item.data(0, _KEY_ROLE) is None:
            state = item.checkState(0)
            if state != QtCore.Qt.PartiallyChecked:
                for i in range(item.childCount()):
                    item.child(i).setCheckState(0, state)
        elif item.parent() is not None:
            self.__update_parent(item.parent())
        tree.blockSignals(False)

        self.obj.Elements = self.__checked_keys()
        self._recompute()
