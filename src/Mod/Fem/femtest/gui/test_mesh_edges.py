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

"""Gui unit tests for the element edges drawn over a mesh.

Only the edges lying on the surface are drawn, taken from the element faces
the surface is made of. A mesh of quadratic elements is the case that tells a
sound answer from an unsound one, its outside being gathered by a route that
straight elements do not take.
"""

__title__ = "FEM mesh edge Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import FreeCADGui
import FemGui
import Fem
import ObjectsFem
import Part

from pivy import coin

from femtools import importtools
from femtest.app.support_utils import fcc_print

BOX_SIZE = 10.0

# Cells along each side of the block. Five, so that there are cells buried in
# the middle of it, and edges that only they and their neighbours own. Drawing
# any of those would mean the surface is not what the edges were taken from.
CELLS_PER_AXIS = 5

# Shell elements along each side of the plane, and beam elements along the line.
SHELL_PER_AXIS = 3
BEAM_COUNT = 4


def _edges_of_surface_faces():
    """
    How many element edges the block ought to draw, counted from its lattice.

    The sides of the element faces that lie on the outside of the block, each
    side once however many faces share it. Edges that run into the block are
    left out: they are behind the surface and nobody can see them.
    """
    n = CELLS_PER_AXIS
    edges = set()
    for i in range(n):
        for j in range(n):
            for k in range(n):
                cell = (i, j, k)
                corners = [(i + a, j + b, k + c) for a in (0, 1) for b in (0, 1) for c in (0, 1)]
                for axis in range(3):
                    for side in (0, 1):
                        outside = cell[axis] == (0 if side == 0 else n - 1)
                        if not outside:
                            continue
                        plane = cell[axis] + side
                        quad = [c for c in corners if c[axis] == plane]
                        for first in quad:
                            for second in quad:
                                if sum(1 for x, y in zip(first, second) if x != y) == 1:
                                    edges.add(frozenset((first, second)))
    return len(edges)


def _node_ids(mesh, quadratic):
    """
    Number the nodes of the block and put them in the mesh.

    Counted in half steps, so that a quadratic mesh can name the midpoints of
    its edges and a linear one takes every second node. Both then stand on the
    same corners and differ only in what they carry between them.
    """
    span = 2 * CELLS_PER_AXIS
    step = BOX_SIZE / span
    ident = {}

    def wanted(i, j, k):
        if not quadratic:
            return i % 2 == 0 and j % 2 == 0 and k % 2 == 0
        # A 20 node hexahedron has its corners and the midpoint of each edge,
        # and nothing in the middle of a face or of the cell itself.
        return (i % 2) + (j % 2) + (k % 2) <= 1

    for i in range(span + 1):
        for j in range(span + 1):
            for k in range(span + 1):
                if wanted(i, j, k):
                    ident[(i, j, k)] = len(ident) + 1
                    mesh.addNode(i * step, j * step, k * step, ident[(i, j, k)])
    return ident


def _block_mesh(quadratic):
    """A block of hexahedra, linear or quadratic, as one volume group."""
    mesh = Fem.FemMesh()
    ident = _node_ids(mesh, quadratic)

    corners = [
        (0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0),
        (0, 0, 2), (2, 0, 2), (2, 2, 2), (0, 2, 2),
    ]  # fmt: skip
    midpoints = [
        (1, 0, 0), (2, 1, 0), (1, 2, 0), (0, 1, 0),
        (1, 0, 2), (2, 1, 2), (1, 2, 2), (0, 1, 2),
        (0, 0, 1), (2, 0, 1), (2, 2, 1), (0, 2, 1),
    ]  # fmt: skip
    offsets = corners + midpoints if quadratic else corners

    volumes = []
    for i in range(CELLS_PER_AXIS):
        for j in range(CELLS_PER_AXIS):
            for k in range(CELLS_PER_AXIS):
                base = (2 * i, 2 * j, 2 * k)
                volumes.append(
                    mesh.addVolume(
                        [ident[tuple(b + d for b, d in zip(base, off))] for off in offsets]
                    )
                )
    mesh.addGroupElements(mesh.addGroup("Solid1", "Volume"), volumes)
    return mesh


def _shell_mesh(size):
    """A grid of quad shells on the xy plane, as one face group."""
    mesh = Fem.FemMesh()
    step = BOX_SIZE / size
    ident = {}
    for i in range(size + 1):
        for j in range(size + 1):
            ident[(i, j)] = len(ident) + 1
            mesh.addNode(i * step, j * step, 0, ident[(i, j)])
    faces = [
        mesh.addFace([ident[(i, j)], ident[(i + 1, j)], ident[(i + 1, j + 1)], ident[(i, j + 1)]])
        for i in range(size)
        for j in range(size)
    ]
    mesh.addGroupElements(mesh.addGroup("Face1", "Face"), faces)
    return mesh


def _beam_mesh(count):
    """A row of beam elements along x, as one edge group."""
    mesh = Fem.FemMesh()
    step = BOX_SIZE / count
    for i in range(count + 1):
        mesh.addNode(i * step, 0, 0, i + 1)
    edges = [mesh.addEdge([i + 1, i + 2]) for i in range(count)]
    mesh.addGroupElements(mesh.addGroup("Edge1", "Edge"), edges)
    return mesh


def _drawn_lines(vobj):
    """
    Line segments a traversal from this view provider draws.

    A traversal and not a search of the graph: the modes not on show hang in
    the same graph as the one that is, and only a traversal takes the switches
    into account. A curved edge is one line of three points and so two
    segments, which is what makes a quadratic mesh count double.
    """
    action = coin.SoGetPrimitiveCountAction()
    action.apply(vobj.RootNode)
    return action.getLineCount()


class TestMeshEdgesGui(unittest.TestCase):
    fcc_print("import TestMeshEdgesGui")

    def setUp(self):
        self.document = FreeCAD.newDocument("MeshEdges")

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def _placed(self, name, shape, mesh):
        """
        A meshed shape placed in an assembly, with the mesh on show.

        Placed rather than looked at on its own: an import is what draws a mesh
        through the view the element edges are built for.
        """
        analysis = ObjectsFem.makeAnalysis(self.document, name)
        geometry = ObjectsFem.makeGeometryGroup(self.document, name + "Geometry")
        analysis.addObject(geometry)

        source = self.document.addObject("Part::Feature", name + "Part")
        source.Shape = shape
        step = ObjectsFem.makeGeometryImport(self.document)
        step.Import = [source]
        geometry.Group = [step]

        group = ObjectsFem.makeMeshShapeGroup(self.document, geometry=geometry, analysis=analysis)
        mesh_obj = self.document.addObject("Fem::FemMeshObject", name + "Mesh")
        mesh_obj.FemMesh = mesh
        group.addObject(mesh_obj)
        self.document.recompute()

        assembly = ObjectsFem.makeAnalysis(self.document, name + "Assembly")
        placed = ObjectsFem.makeAnalysisImport(self.document, name + "Placed")
        placed.Analysis = analysis
        importtools.wire_import(assembly, placed)
        self.document.recompute()

        FemGui.setActiveAnalysis(assembly)
        FemGui.getAnalysisViewState(assembly).setActiveStage("Mesh")
        self.document.recompute()
        return placed

    def _placed_block(self, quadratic):
        return self._placed(
            "Quadratic" if quadratic else "Linear",
            Part.makeBox(BOX_SIZE, BOX_SIZE, BOX_SIZE),
            _block_mesh(quadratic),
        )

    def test_only_the_edges_on_the_surface_are_drawn(self):
        """The sides of the outside faces, and nothing that runs inwards."""
        placed = self._placed_block(quadratic=False)
        self.assertEqual(_drawn_lines(placed.ViewObject), _edges_of_surface_faces())

    def test_a_shell_mesh_draws_the_sides_of_its_elements(self):
        """
        A shell is its own surface, so all of it is drawn: every side of every
        quad, each shared side once. Nothing is gathered as an outside face
        here, and the walk has to take the elements as they come.
        """
        placed = self._placed(
            "Shell", Part.makePlane(BOX_SIZE, BOX_SIZE), _shell_mesh(SHELL_PER_AXIS)
        )
        n = SHELL_PER_AXIS
        self.assertEqual(_drawn_lines(placed.ViewObject), 2 * n * (n + 1))

    def test_a_beam_mesh_draws_its_elements(self):
        """
        A beam has no face and no edge of its own to report, so what is drawn
        is the element itself.

        Twice over: the surface carries a beam as a line of its own, and the
        walk draws it again. Which is worth the one line it costs, because a
        curved beam comes off the surface as two segments meeting at a
        midpoint, where the drawn one is a single line that runs through it.
        """
        line = Part.makeLine(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(BOX_SIZE, 0, 0))
        placed = self._placed("Beam", line, _beam_mesh(BEAM_COUNT))
        self.assertEqual(_drawn_lines(placed.ViewObject), 2 * BEAM_COUNT)

    def test_a_quadratic_block_draws_the_same_edges_curved(self):
        """
        The quadratic block is the same cells on the same corners, so the same
        edges lie on its surface; each of them merely runs through a midpoint
        and counts as two segments rather than one.

        The surface filter is no use for saying where those edges are, since it
        triangulates a quadratic face and the sides are then the triangulation
        rather than the elements. A curved mesh has its outside gathered as
        faces first, and this asks whether that happened.
        """
        placed = self._placed_block(quadratic=True)
        self.assertEqual(_drawn_lines(placed.ViewObject), 2 * _edges_of_surface_faces())
