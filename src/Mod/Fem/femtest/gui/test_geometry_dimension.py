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
Gui unit tests for what the dimension mode picks out of a geometry.

A dimension names the elements whose declared analysis dimension it is, and
nothing else. So a solid answers for 3D alone: the faces bounding it are where
a volume element ends rather than elements of their own, and only a free face
is 2D, only a free edge 1D. That is the reading the mesh stage has always had,
where the construction elements are what opens up the dimensions below the one
the analysis solves on, and these tests hold the geometry to the same one.
"""

__title__ = "FEM geometry dimension Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import FreeCADGui
import FemGui
import Part

from pivy import coin

import ObjectsFem

from femtools import importtools

from femtest.app.support_utils import fcc_print

# Where each element of the fixture below sits along x. Set apart so that the
# span of what is drawn says which of them are on screen.
SOLID = (0.0, 10.0)
FACE = (20.0, 30.0)
EDGE = (40.0, 50.0)
VERTEX = (60.0, 60.0)
EVERYTHING = (SOLID[0], VERTEX[1])


def _drawn_span(vobj):
    """
    Reach along x of everything a traversal from this view provider draws, or
    None when nothing is drawn.

    A traversal rather than a look at the index fields: the elements are drawn
    by several shapes between them, and an instance hangs under the mode switch
    of the analysis that placed it.
    """
    action = coin.SoGetBoundingBoxAction(coin.SbViewportRegion(400, 400))
    action.apply(vobj.RootNode)
    box = action.getBoundingBox()
    if box.isEmpty():
        return None
    return (round(box.getMin().getValue()[0], 3), round(box.getMax().getValue()[0], 3))


class TestGeometryDimensionGui(unittest.TestCase):
    fcc_print("import TestGeometryDimensionGui")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

        source = self.document.addObject("Part::Feature", "Source")
        # One element of every dimension, and the solid brings faces, edges and
        # vertices of its own along for the mode to leave where they belong.
        source.Shape = Part.makeCompound(
            [
                Part.makeBox(10, 10, 10),
                Part.makePlane(10, 10, FreeCAD.Vector(FACE[0], 0, 0)),
                Part.makeLine(FreeCAD.Vector(EDGE[0], 0, 0), FreeCAD.Vector(EDGE[1], 0, 0)),
                Part.Vertex(VERTEX[0], 0, 0),
            ]
        )

        self.analysis = ObjectsFem.makeAnalysis(self.document)
        self.geometry = ObjectsFem.makeGeometryGroup(self.document)
        self.analysis.addObject(self.geometry)
        step = ObjectsFem.makeGeometryImport(self.document)
        step.Import = [source]
        self.geometry.Group = [step]
        self.document.recompute()
        FemGui.setActiveAnalysis(self.analysis)

        self.state = FemGui.getAnalysisViewState(self.analysis)
        # The ghost draws the whole shape however much the mode leaves out,
        # which is the one thing these tests must not read.
        self.state.setOverlay(False)

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        FreeCAD.closeDocument(self.document.Name)

    def _span(self):
        return _drawn_span(self.geometry.ViewObject)

    # -- what a dimension picks out ------------------------------------------

    def test_everything_is_drawn_when_every_dimension_is_asked_for(self):
        self.assertEqual(self.state.getDimensionMode(), "All")
        self.assertEqual(self._span(), EVERYTHING)

    def test_asking_for_solids_leaves_the_rest_behind(self):
        self.state.setDimensionMode("3D")
        self.assertEqual(self._span(), SOLID)

    def test_a_solid_is_not_a_set_of_faces(self):
        """
        The heart of it. A solid met while 2D is wanted is not what was asked
        for, so it goes whole: drawing the faces bounding it would answer a
        question about the analysis with a fact about the topology.
        """
        self.state.setDimensionMode("2D")
        self.assertEqual(self._span(), FACE)

    def test_the_edges_bounding_a_solid_are_not_1d_elements(self):
        """
        Same again one dimension down, and the case that is easiest to get
        wrong: every solid and every face is bounded by edges, and none of
        them is an element the analysis would solve on.
        """
        self.state.setDimensionMode("1D")
        self.assertEqual(self._span(), EDGE)

    def test_a_free_vertex_is_what_0d_asks_for(self):
        self.state.setDimensionMode("0D")
        self.assertEqual(self._span(), VERTEX)

    def test_the_mode_is_a_filter_and_not_a_style(self):
        """
        1D used to draw everything with the faces switched off, which is the
        wireframe under another name. The two are separate settings and have
        to stay separate: a wireframe of the 1D elements is a thing to ask for.
        """
        self.state.setDimensionMode("1D")
        self.state.setWireframe(True)
        try:
            self.assertEqual(self._span(), EDGE)
        finally:
            self.state.setWireframe(False)

    def test_the_ghost_says_where_the_other_dimensions_went(self):
        """
        Leaving elements out is what the ghost is for, and the mode leaves them
        out the way hiding them does.
        """
        self.state.setDimensionMode("2D")
        self.state.setOverlay(True)
        try:
            span = self._span()
        finally:
            self.state.setOverlay(False)
        self.assertEqual(
            span[0],
            SOLID[0],
            "the solid that 2D left out has to still show as a ghost",
        )

    # -- and the same for a placed instance ----------------------------------

    def test_an_instance_answers_the_mode_the_same_way(self):
        """
        An instance draws the geometry of the analysis it places, through a
        renderer of its own. A mode that reached only one of the two would
        leave an assembly showing the solids of some parts and not others.
        """
        assembly = ObjectsFem.makeAnalysis(self.document, "Assembly")
        placed = ObjectsFem.makeAnalysisImport(self.document, "Placed")
        placed.Analysis = self.analysis
        importtools.wire_import(assembly, placed)
        self.document.recompute()

        state = FemGui.getAnalysisViewState(assembly)
        state.setOverlay(False)
        whole = _drawn_span(placed.ViewObject)
        self.assertEqual(whole[0], SOLID[0], "the instance draws the solid to begin with")
        state.setDimensionMode("2D")
        self.assertEqual(_drawn_span(placed.ViewObject), FACE)
        state.setDimensionMode("1D")
        self.assertEqual(_drawn_span(placed.ViewObject), EDGE)
        state.setDimensionMode("0D")
        self.assertEqual(_drawn_span(placed.ViewObject), VERTEX)
