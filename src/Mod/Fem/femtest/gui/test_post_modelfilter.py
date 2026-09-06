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

from PySide import QtCore, QtGui

import ObjectsFem

from femtaskpanels import task_post_modelfilter
from femtools import membertools

from femtest.app.support_utils import fcc_print
from femtest.app.test_attribution import _two_solid_mesh


class TestPostModelFilterGui(unittest.TestCase):
    """
    The panel is a view onto what the result stored, and nothing else.

    So the tests build a result whose attribution is known, put the panel on it,
    and check that what it offers and what it writes back are the same thing the
    filter reads.
    """

    fcc_print("import TestPostModelFilterGui")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

        self.analysis = ObjectsFem.makeAnalysis(self.document)
        geometry = ObjectsFem.makeGeometryGroup(self.document)
        self.geometry = geometry
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

        # The same result loaded a second time and deliberately left alone, so
        # the panel can be asked what it does with a result nobody attributed.
        self.bare_pipeline = self.document.addObject("Fem::FemPostPipeline", "Bare")
        self.bare_pipeline.load(result)
        self.analysis.addObject(self.bare_pipeline)
        self.document.recompute()

        self.filter = ObjectsFem.makePostFilterModel(self.document, self.pipeline)
        self.document.recompute()

    def tearDown(self):
        FreeCADGui.Control.closeDialog()
        FreeCAD.closeDocument(self.document.Name)

    def _panel(self):
        return task_post_modelfilter._TaskPanel(self.filter.ViewObject)

    @staticmethod
    def _rows(panel):
        """Top level rows of the tree, by label."""
        tree = panel.widget.ElementTree
        return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestPostModelFilterGui tests {2}\n{0}".format(
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
        # Component and material, and nothing that lists the entities flat: the
        # component rows already carry every entity, grouped.
        self.assertEqual(offered, ["Component", "Material"])

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
        self.filter.Attribute = "Component"
        panel = self._panel()
        tree = panel.widget.ElementTree
        # The entity under the first component, not the component row itself:
        # what is stored is always the entity a row stands for.
        tree.topLevelItem(0).child(0).setCheckState(0, QtCore.Qt.Checked)

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
        self.filter.Attribute = "Component"
        self.filter.Elements = ["Solid2"]
        panel = self._panel()
        panel.widget.AttributeComboBox.setCurrentText("Material")

        self.assertEqual(self.filter.Attribute, "Material")
        # The checked entities are the same entities under either grouping.
        self.assertEqual(list(self.filter.Elements), ["Solid2"])

    def test_the_name_column_takes_what_the_counts_do_not_need(self):
        """A dotted path is as long as the model makes it; a count is not."""
        panel = self._panel()
        tree = panel.widget.ElementTree
        header = tree.header()

        if hasattr(header, "sectionResizeMode"):
            mode = header.sectionResizeMode
            stretch = QtGui.QHeaderView.ResizeMode.Stretch
            to_contents = QtGui.QHeaderView.ResizeMode.ResizeToContents
        else:
            mode = header.resizeMode
            stretch = QtGui.QHeaderView.Stretch
            to_contents = QtGui.QHeaderView.ResizeToContents

        # The names take whatever the counts leave over, at any panel width,
        # rather than the even split that cut them off halfway across an
        # otherwise empty panel.
        self.assertEqual(mode(0), stretch)
        self.assertEqual(mode(1), to_contents)
        self.assertFalse(header.stretchLastSection())
        self.assertEqual(tree.columnWidth(0) + tree.columnWidth(1), tree.viewport().width())

    def test_a_result_without_attribution_says_so(self):
        """An empty tree reads as breakage, so the reason replaces it."""
        bare = ObjectsFem.makePostFilterModel(self.document, self.bare_pipeline)
        self.document.recompute()
        panel = task_post_modelfilter._TaskPanel(bare.ViewObject)

        self.assertFalse(panel.widget.ElementTree.isVisibleTo(panel.widget))
        self.assertTrue(panel.widget.MessageLabel.isVisibleTo(panel.widget))
        self.assertNotEqual(panel.widget.MessageLabel.text(), "")
        # Nothing to group by, so nothing to choose either.
        self.assertFalse(panel.widget.AttributeComboBox.isEnabled())

    def test_an_attributed_result_shows_the_tree_and_not_the_message(self):
        panel = self._panel()
        self.assertTrue(panel.widget.ElementTree.isVisibleTo(panel.widget))
        self.assertFalse(panel.widget.MessageLabel.isVisibleTo(panel.widget))
        self.assertTrue(panel.widget.AttributeComboBox.isEnabled())

    def test_narrowing_writes_the_colours_once(self):
        """A filter re-running must not make the pipeline recolour everything.

        Switching the filter between its own VTK pipelines used to be announced
        as a change of the pipeline's Group, which reads as "the membership
        moved" and had the view rewrite the colours of every visible child -
        over every point of them - on top of the rewrite the filter had just
        done itself.

        Counted rather than timed: the cost is one whole pass per extra call,
        and the count is what says whether there are extra calls at all.
        """
        import FemGui

        self.pipeline.ViewObject.Visibility = False
        self.filter.ViewObject.Visibility = True
        self.filter.ViewObject.DisplayMode = "Surface"
        for name in self.filter.ViewObject.getEnumerationsOfProperty("Field"):
            if name != "None":
                self.filter.ViewObject.Field = name
                break
        self.document.recompute()

        # Warm up, so first-time work is not counted with the operation.
        self.filter.Elements = ["Solid1"]
        self.document.recompute()
        self.filter.Elements = []
        self.document.recompute()

        FemGui.perfReset()
        FemGui.perfEnable(True)
        try:
            self.filter.Elements = ["Solid1"]
            self.document.recompute()
        finally:
            FemGui.perfEnable(False)

        written = {name: count for name, count, _total, _self in FemGui.perfReport()}
        self.assertEqual(written.get("post.toCoin.colors", 0), 1)

    def test_ticking_a_group_recomputes_once(self):
        """One tick is one recompute, however many rows it moves.

        Qt will happily propagate a parent's tick to its children itself, one at
        a time, reporting each as a change of its own. Every one of those is a
        filter to rebuild and a document to recompute, so ticking a component of
        eight faces recomputed eight times - seconds, on a real result.
        """
        # A group of one would tick the same either way and prove nothing, so the
        # material is widened to hold both solids and the result attributed
        # again, which is what puts two entities under one row.
        material = self.document.getObject("Steel")
        material.References = [(self.geometry, ["Solid1", "Solid2"])]
        self.document.recompute()
        self.pipeline.attribute(membertools.get_mesh_to_solve(self.analysis), self.analysis)
        self.document.recompute()

        self.filter.Attribute = "Material"
        panel = self._panel()
        tree = panel.widget.ElementTree

        parent = max(
            (tree.topLevelItem(i) for i in range(tree.topLevelItemCount())),
            key=lambda item: item.childCount(),
        )
        self.assertGreater(parent.childCount(), 1, "need a group of several to tick")

        recomputes = []
        original = panel._recompute
        panel._recompute = lambda: (recomputes.append(1), original())[1]

        parent.setCheckState(0, QtCore.Qt.Checked)

        self.assertEqual(len(recomputes), 1)
        # and it still wrote down every entity the group holds
        self.assertEqual(
            sorted(self.filter.Elements),
            sorted(parent.child(i).text(0) for i in range(parent.childCount())),
        )
