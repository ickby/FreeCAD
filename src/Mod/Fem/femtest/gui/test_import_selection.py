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

"""
Gui unit tests for what a pick on a placed analysis lights up.

A pick is recorded against the top of the tree, so what an instance is handed
names the analysis and carries the way down to the element in the subname. A
face lights from the picked detail alone, but a solid has no part of its own -
and a clip plane makes the cut face report the solid it cuts - so lighting one
means lighting every face of it, which only happens if the instance recognises
its own element in what arrived.
"""

__title__ = "FEM placed analysis selection Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import FreeCADGui
import Part

import ObjectsFem

from femtools import importtools

from femtest.app.support_utils import fcc_print


def _lit(vobj):
    """
    What every face set below a view provider reports as lit.

    The helpers do not recolour to show a selection: they name the parts to
    light in the fields of the face set, which is what the render reads.
    """
    marked = []

    def walk(node):
        if hasattr(node, "selectionPartIndex") and hasattr(node, "highlightPartIndex"):
            selected = [node.selectionPartIndex[i] for i in range(node.selectionPartIndex.getNum())]
            highlighted = [
                node.highlightPartIndex[i] for i in range(node.highlightPartIndex.getNum())
            ]
            if selected or highlighted:
                marked.append((selected, highlighted))
        children = node.getChildren() if hasattr(node, "getChildren") else None
        if children:
            for i in range(children.getLength()):
                walk(children[i])

    walk(vobj.RootNode)
    return marked


def _polylines(vobj):
    """How many polylines every line set below a view provider draws."""
    counts = []

    def walk(node):
        if str(node.getTypeId().getName()) == "SoBrepEdgeSet":
            index = node.coordIndex
            counts.append(sum(1 for i in range(index.getNum()) if index[i] < 0))
        children = node.getChildren() if hasattr(node, "getChildren") else None
        if children:
            for i in range(children.getLength()):
                walk(children[i])

    walk(vobj.RootNode)
    return counts


class TestImportSelectionGui(unittest.TestCase):
    fcc_print("import TestImportSelectionGui")

    def setUp(self):
        self.document = FreeCAD.newDocument("ImportSelection")

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.clearPreselection()
        FreeCAD.closeDocument(self.document.Name)

    def _analysis(self, name):
        """An analysis with one box in its geometry, so Solid1 has six faces."""
        analysis = ObjectsFem.makeAnalysis(self.document, name)
        geometry = ObjectsFem.makeGeometryGroup(self.document, name + "Geometry")
        analysis.addObject(geometry)

        source = self.document.addObject("Part::Feature", name + "Part")
        source.Shape = Part.makeBox(10, 10, 10)
        step = ObjectsFem.makeGeometryImport(self.document)
        step.Import = [source]
        geometry.Group = [step]
        self.document.recompute()
        return analysis

    def _place(self, analysis, source, name):
        """Place *source* in *analysis*, and say where the container ended up."""
        placed = ObjectsFem.makeAnalysisImport(self.document, name)
        placed.Analysis = source
        container = importtools.wire_import(analysis, placed)
        self.document.recompute()
        return placed, container

    def _assembly(self):
        source = self._analysis("Leg")
        assembly = ObjectsFem.makeAnalysis(self.document, "Table")
        placed, container = self._place(assembly, source, "Placed")
        return assembly, container, placed

    # -- a pick that comes down through the analysis -------------------------

    def test_a_solid_selected_as_the_analysis_reports_it_lights_its_faces(self):
        """
        The element of an instance arrives behind the way down to it. Compared
        against the name in front of the subname instead, no pick from the 3D
        view is ever recognised: the element lands in the selection view and
        nothing on screen answers for it.
        """
        assembly, container, placed = self._assembly()

        FreeCADGui.Selection.addSelection(
            self.document.Name,
            assembly.Name,
            f"{container.Name}.{placed.Name}.Solid1",
        )
        self.assertEqual(_lit(placed.ViewObject), [([0, 1, 2, 3, 4, 5], [])])

    def test_a_solid_hovered_as_the_analysis_reports_it_lights_its_faces(self):
        """
        What a clip plane exposes reports the solid it cut, and a solid has no
        part of its own to light - so all of them have to be named here.
        """
        assembly, container, placed = self._assembly()

        FreeCADGui.Selection.setPreselection(
            assembly,
            f"{container.Name}.{placed.Name}.Solid1",
            0.0,
            0.0,
            0.0,
        )
        self.assertEqual(_lit(placed.ViewObject), [([], [0, 1, 2, 3, 4, 5])])

    def test_a_solid_of_a_nested_instance_lights_in_the_one_that_drew_it(self):
        """
        An instance draws its own copy of everything the nested ones hold, so a
        pick inside a nested instance belongs to the outer one, which knows it
        by the nested instances still in front of the element.
        """
        leg = self._analysis("Leg")
        side = ObjectsFem.makeAnalysis(self.document, "Side")
        inner, _ = self._place(side, leg, "InnerPlaced")
        table = ObjectsFem.makeAnalysis(self.document, "Table")
        outer, container = self._place(table, side, "OuterPlaced")

        FreeCADGui.Selection.addSelection(
            self.document.Name,
            table.Name,
            f"{container.Name}.{outer.Name}.{inner.Name}.Solid1",
        )
        self.assertEqual(_lit(outer.ViewObject), [([0, 1, 2, 3, 4, 5], [])])
        self.assertEqual(
            _lit(inner.ViewObject),
            [],
            "the nested instance draws the copy inside Side, not the one picked",
        )

    def test_the_element_named_on_the_instance_itself_still_lights(self):
        """A panel selecting on the instance names it and nothing above it."""
        _, _, placed = self._assembly()

        FreeCADGui.Selection.addSelection(self.document.Name, placed.Name, "Solid1")
        self.assertEqual(_lit(placed.ViewObject), [([0, 1, 2, 3, 4, 5], [])])

    def test_a_pick_in_the_source_analysis_leaves_the_instance_dark(self):
        """
        The source draws its own geometry where it stands; what the instance
        draws is a copy somewhere else, and was not what was picked.
        """
        assembly, _, placed = self._assembly()
        source = placed.Analysis
        geometry = source.Group[0]

        FreeCADGui.Selection.addSelection(
            self.document.Name,
            source.Name,
            f"{geometry.Name}.Solid1",
        )
        self.assertEqual(_lit(placed.ViewObject), [])

    def test_a_pick_on_another_instance_leaves_this_one_dark(self):
        assembly, container, first = self._assembly()
        second, _ = self._place(assembly, first.Analysis, "Placed2")

        FreeCADGui.Selection.addSelection(
            self.document.Name,
            assembly.Name,
            f"{container.Name}.{second.Name}.Solid1",
        )
        self.assertEqual(_lit(second.ViewObject), [([0, 1, 2, 3, 4, 5], [])])
        self.assertEqual(_lit(first.ViewObject), [])

    def test_an_instance_draws_every_edge_of_its_shape_once(self):
        """
        A face hands its own edges to the mesher a second time, tagged with the
        id of the face rather than the one of the edge. Drawn, such a copy
        answers a pick on the edge with the name of the face, so only the edges
        the shape really has may reach the line set.
        """
        _, _, placed = self._assembly()

        drawn = [count for count in _polylines(placed.ViewObject) if count]
        self.assertTrue(drawn, "the instance draws no edges at all")
        for count in drawn:
            self.assertEqual(count, 12, "a box has twelve edges to draw")

    def test_clearing_the_selection_puts_the_instance_out(self):
        assembly, container, placed = self._assembly()
        FreeCADGui.Selection.addSelection(
            self.document.Name,
            assembly.Name,
            f"{container.Name}.{placed.Name}.Solid1",
        )
        FreeCADGui.Selection.clearSelection()
        self.assertEqual(_lit(placed.ViewObject), [])
