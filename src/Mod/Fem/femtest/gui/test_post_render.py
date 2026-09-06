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

"""What the post-processing view puts into the scene graph."""

__title__ = "FEM post-processing render tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import FreeCADGui
import Fem
import ObjectsFem

# SoIndexedLineSet and friends come from the Coin bindings
from pivy import coin

from femtest.app.support_utils import fcc_print


def _quadratic_tetra_mesh():
    """One ten-node tetrahedron, its midpoints lifted off the straight edges.

    Lifted on purpose: a midpoint that sits exactly halfway makes a curved edge
    and a straight one land on the same points, and the whole question here is
    which of the two got drawn.
    """
    mesh = Fem.FemMesh()
    corners = [(0, 0, 0), (4, 0, 0), (0, 4, 0), (0, 0, 4)]
    for index, (x, y, z) in enumerate(corners, start=1):
        mesh.addNode(x, y, z, index)

    # SMESH orders the midside nodes 12, 23, 31, 14, 24, 34
    pairs = [(1, 2), (2, 3), (3, 1), (1, 4), (2, 4), (3, 4)]
    for offset, (a, b) in enumerate(pairs, start=5):
        first = corners[a - 1]
        second = corners[b - 1]
        mesh.addNode(
            (first[0] + second[0]) / 2.0,
            (first[1] + second[1]) / 2.0,
            (first[2] + second[2]) / 2.0 + 1.0,
            offset,
        )

    mesh.addVolume([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    return mesh


def _linear_tetra_mesh():
    """One four-node tetrahedron, for the case that has no curvature to keep."""
    mesh = Fem.FemMesh()
    for index, (x, y, z) in enumerate([(0, 0, 0), (4, 0, 0), (0, 4, 0), (0, 0, 4)], start=1):
        mesh.addNode(x, y, z, index)
    mesh.addVolume([1, 2, 3, 4])
    return mesh


def _line_index_count(vobj):
    """Length of the coordIndex of the line set the view provider draws with.

    Found with Coin's own search rather than by walking the children: a scene
    graph holds nodes that are not groups and kinds that a hand-written walk has
    to know about, and the action already knows about all of them.
    """
    search = coin.SoSearchAction()
    search.setType(coin.SoIndexedLineSet.getClassTypeId())
    search.setInterest(coin.SoSearchAction.ALL)
    search.setSearchingAll(True)
    search.apply(vobj.RootNode)

    paths = search.getPaths()
    biggest = 0
    for i in range(paths.getLength()):
        node = paths[i].getTail()
        biggest = max(biggest, node.coordIndex.getNum())
    return biggest


class TestPostRenderGui(unittest.TestCase):
    """
    The edges drawn over a result of curved elements.

    A quadratic face is triangulated over its midpoints before it is drawn, and
    the sides of those little triangles are not the edges of the element: they
    cut across its face. Asking the triangulation for the edges therefore draws
    a mesh that is not there, and several times more of it.
    """

    fcc_print("import TestPostRenderGui")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def _pipeline(self, mesh):
        """A pipeline drawing a result of *mesh*, with its edges on show.

        Built per test rather than shared: a result object names the nodes it
        holds values for, so swapping the mesh underneath one leaves it
        describing a mesh that is no longer there.
        """
        analysis = ObjectsFem.makeAnalysis(self.document)
        holder = self.document.addObject("Fem::FemMeshObject", "Mesh")
        holder.FemMesh = mesh
        analysis.addObject(holder)
        self.document.recompute()

        result = ObjectsFem.makeResultMechanical(self.document, "Result")
        result.Mesh = holder
        nodes = holder.FemMesh.Nodes
        result.NodeNumbers = list(nodes.keys())
        result.DisplacementVectors = [FreeCAD.Vector(0, 0, 0)] * len(nodes)
        analysis.addObject(result)
        self.document.recompute()

        pipeline = self.document.addObject("Fem::FemPostPipeline", "Pipeline")
        pipeline.load(result)
        analysis.addObject(pipeline)
        self.document.recompute()

        pipeline.ViewObject.DisplayMode = "Wireframe (surface only)"
        self.document.recompute()
        return pipeline

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestPostRenderGui tests {2}\n{0}".format(
                100 * "*", 10 * "*", 44 * "*"
            )
        )

    def test_surface_edges_of_a_curved_element_are_its_own(self):
        """One quadratic tetrahedron has six edges, not the sides of a mesh.

        Taken from the triangulation instead, this was twenty-four straight
        segments cutting across the faces.
        """
        pipeline = self._pipeline(_quadratic_tetra_mesh())

        # Six edges, each drawn through its midpoint as two segments, and each
        # Coin index list closed by a -1: 6 * 2 * (2 + 1).
        self.assertEqual(_line_index_count(pipeline.ViewObject), 36)

    def test_a_result_of_straight_elements_is_unchanged(self):
        """Nothing is routed differently where there is no curvature to keep."""
        pipeline = self._pipeline(_linear_tetra_mesh())

        # Four corners, six straight edges, each closed by a -1.
        self.assertEqual(_line_index_count(pipeline.ViewObject), 18)
