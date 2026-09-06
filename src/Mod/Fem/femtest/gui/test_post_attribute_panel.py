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

"""Task panel of the post-processing attribution filter."""

__title__ = "FEM attribution filter panel tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import FreeCADGui
import Fem
import Part

from PySide import QtCore

import ObjectsFem

from femtaskpanels import task_post_attributefilter
from femtools import membertools

from femtest.app.support_utils import fcc_print
from femtest.app.test_attribution import _two_solid_mesh


class TestPostAttributePanelGui(unittest.TestCase):
    """
    The panel is a view onto what the result stored, and nothing else.

    So the tests build a result whose attribution is known, put the panel on it,
    and check that what it offers and what it writes back are the same thing the
    filter reads.
    """

    fcc_print("import TestPostAttributePanelGui")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

        self.analysis = ObjectsFem.makeAnalysis(self.document)
        geometry = ObjectsFem.makeGeometryGroup(self.document)
        self.analysis.addObject(geometry)
        source = self.document.addObject("Part::Feature", "Source")
        source.Shape = Part.makeCompound(
            [Part.makeBox(1, 1, 1), Part.makeBox(1, 1, 1, FreeCAD.Vector(4, 0, 0))]
        )
        imported = ObjectsFem.makeGeometryImport(self.document)
        imported.Import = [source]
        geometry.Group = [imported]

        group = ObjectsFem.makeMeshShapeGroup(
            self.document, geometry=geometry, analysis=self.analysis
        )
        holder = self.document.addObject("Fem::FemMeshObject", "Mesh")
        holder.FemMesh = _two_solid_mesh()
        group.addObject(holder)

        material = ObjectsFem.makeMaterialSolid(self.document, "Steel")
        card = material.Material
        card["Name"] = "CalculiX-Steel"
        material.Material = card
        material.References = [(geometry, ["Solid1"])]
        self.analysis.addObject(material)
        self.document.recompute()

        solve_mesh = membertools.get_mesh_to_solve(self.analysis)
        result = ObjectsFem.makeResultMechanical(self.document, "Result")
        result.Mesh = holder
        nodes = holder.FemMesh.Nodes
        result.NodeNumbers = list(nodes.keys())
        result.DisplacementVectors = [FreeCAD.Vector(0, 0, 0)] * len(nodes)
        self.analysis.addObject(result)
        self.document.recompute()

        self.pipeline = self.document.addObject("Fem::FemPostPipeline", "Pipeline")
        self.pipeline.load(result)
        self.analysis.addObject(self.pipeline)
        self.document.recompute()
        self.pipeline.attribute(solve_mesh, self.analysis)
        self.document.recompute()

        self.filter = ObjectsFem.makePostFilterAttribute(self.document, self.pipeline)
        self.document.recompute()

    def tearDown(self):
        FreeCADGui.Control.closeDialog()
        FreeCAD.closeDocument(self.document.Name)

    def _panel(self):
        return task_post_attributefilter._TaskPanel(self.filter.ViewObject)

    @staticmethod
    def _rows(panel):
        """Top level rows of the tree, by label."""
        tree = panel.widget.ElementTree
        return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestPostAttributePanelGui tests {2}\n{0}".format(
                100 * "*", 10 * "*", 38 * "*"
            )
        )

    def test_the_combobox_offers_what_the_result_carries(self):
        panel = self._panel()
        offered = [
            panel.widget.AttributeComboBox.itemText(i)
            for i in range(panel.widget.AttributeComboBox.count())
        ]
        self.assertEqual(offered, self.filter.getEnumerationsOfProperty("Attribute"))
        self.assertIn("Material", offered)

    def test_subelement_lists_the_entities_flat(self):
        self.filter.Attribute = "Subelement"
        panel = self._panel()
        self.assertEqual(self._rows(panel), ["Solid1", "Solid2"])

    def test_component_groups_the_entities_under_their_component(self):
        self.filter.Attribute = "Component"
        panel = self._panel()
        self.assertEqual(self._rows(panel), ["Component1", "Component2"])

        tree = panel.widget.ElementTree
        children = [
            tree.topLevelItem(0).child(i).text(0) for i in range(tree.topLevelItem(0).childCount())
        ]
        self.assertEqual(children, ["Solid1"])

    def test_checking_a_row_writes_the_entity_back(self):
        self.filter.Attribute = "Subelement"
        panel = self._panel()
        tree = panel.widget.ElementTree
        tree.topLevelItem(0).setCheckState(0, QtCore.Qt.Checked)

        self.assertEqual(list(self.filter.Elements), ["Solid1"])
        self.document.recompute()
        cells = self.filter.getOutputAlgorithm().GetOutputDataObject(0).GetNumberOfCells()
        self.assertEqual(cells, 1)

    def test_a_parent_hands_its_state_to_its_children(self):
        self.filter.Attribute = "Material"
        panel = self._panel()
        tree = panel.widget.ElementTree
        parent = tree.topLevelItem(0)
        parent.setCheckState(0, QtCore.Qt.Checked)

        for i in range(parent.childCount()):
            self.assertEqual(parent.child(i).checkState(0), QtCore.Qt.Checked)
        self.assertEqual(
            sorted(self.filter.Elements),
            sorted(parent.child(i).text(0) for i in range(parent.childCount())),
        )

    def test_the_choice_survives_a_change_of_attribute(self):
        self.filter.Attribute = "Subelement"
        self.filter.Elements = ["Solid2"]
        panel = self._panel()
        panel.widget.AttributeComboBox.setCurrentText("Component")

        self.assertEqual(self.filter.Attribute, "Component")
        self.assertEqual(list(self.filter.Elements), ["Solid2"])
