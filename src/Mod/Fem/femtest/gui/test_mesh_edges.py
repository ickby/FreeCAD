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

"""Gui unit tests for what a mesh draws of each dimension.

Only the edges lying on the surface are drawn, taken from the element faces
the surface is made of. A mesh of quadratic elements is the case that tells a
sound answer from an unsound one, its outside being gathered by a route that
straight elements do not take.

An element of a lower dimension than the mesh around it is drawn as the
element it is and not as a detail of its neighbours: coloured by its own
category rather than dark like an element edge, and in front of the elements
it skins rather than buried in them.
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
from femtest.gui.test_geometry_marks import field_values, node_colors

BOX_SIZE = 10.0

# What an element edge is drawn in, and so what a 1D element must not be
# drawn in, that being the whole difference between an element and a detail
# of one. FemMeshRenderer keeps this colour in the slot past the palette.
EDGE_GREY = (0.2, 0.2, 0.2)

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


def _beam_mesh(count, quadratic=False):
    """A row of beam elements along x, as one edge group."""
    mesh = Fem.FemMesh()
    step = BOX_SIZE / count
    if not quadratic:
        for i in range(count + 1):
            mesh.addNode(i * step, 0, 0, i + 1)
        edges = [mesh.addEdge([i + 1, i + 2]) for i in range(count)]
    else:
        # Counted in half steps, so that every beam can name the midpoint
        # between its ends.
        for i in range(2 * count + 1):
            mesh.addNode(i * step / 2, 0, 0, i + 1)
        edges = [mesh.addEdge([2 * i + 1, 2 * i + 3, 2 * i + 2]) for i in range(count)]
    mesh.addGroupElements(mesh.addGroup("Edge1", "Edge"), edges)
    return mesh


def _skinned_tet_mesh():
    """
    One tetrahedron, with a triangle on the face it rests on and its edges.

    The mesher builds a solid from its outside, so a mesh of one arrives with
    the lower dimensions still in it: those are the construction elements, and
    they lie exactly where the solid does. The triangle covers the face in the
    z = 0 plane and no other, which is what tells the two sets of faces apart
    afterwards.
    """
    mesh = Fem.FemMesh()
    for i, point in enumerate(
        [(0, 0, 0), (BOX_SIZE, 0, 0), (0, BOX_SIZE, 0), (0, 0, BOX_SIZE)], start=1
    ):
        mesh.addNode(*point, i)

    mesh.addGroupElements(mesh.addGroup("Solid1", "Volume"), [mesh.addVolume([1, 2, 3, 4])])
    mesh.addGroupElements(mesh.addGroup("Face1", "Face"), [mesh.addFace([1, 2, 3])])
    edges = [mesh.addEdge([1, 2]), mesh.addEdge([2, 3]), mesh.addEdge([1, 3])]
    for i, edge in enumerate(edges, start=1):
        mesh.addGroupElements(mesh.addGroup(f"Edge{i}", "Edge"), [edge])
    return mesh


def _shapes_in(vobj, wanted, type_name):
    """
    Every shape of exactly that type a traversal from here reaches, with the
    material, the binding and the depth bias in force at each of them.

    Read as Coin reads them: what governs a shape is the last of each that the
    separator holding it lists before it. A traversal and not a search of the
    whole graph, since the modes that are not on show hang in the same graph.
    """
    search = coin.SoSearchAction()
    search.setType(wanted.getClassTypeId())
    search.setInterest(coin.SoSearchAction.ALL)
    search.apply(vobj.RootNode)
    paths = search.getPaths()

    found = []
    for i in range(paths.getLength()):
        path = paths[i]
        node = path.getTail()
        # Exactly the type: SoBrepFaceSet and SoBrepEdgeSet are indexed sets
        # too, and are how the geometry rather than the mesh is drawn.
        if node.getTypeId().getName() != type_name:
            continue

        parent = path.getNodeFromTail(1)
        material = binding = offset = points = None
        for j in range(path.getIndex(path.getLength() - 1)):
            child = parent.getChild(j)
            if child.isOfType(coin.SoMaterial.getClassTypeId()):
                material = child
            elif child.isOfType(coin.SoMaterialBinding.getClassTypeId()):
                binding = child
            elif child.isOfType(coin.SoPolygonOffset.getClassTypeId()):
                offset = child
            elif child.isOfType(coin.SoCoordinate3.getClassTypeId()):
                points = child

        colours = node_colors(material) if material else []
        if binding is None or binding.value.getValue() == coin.SoMaterialBinding.OVERALL:
            drawn = set(colours[:1])
        else:
            drawn = {
                colours[at] for at in field_values(node.materialIndex) if 0 <= at < len(colours)
            }

        cells = field_values(node.coordIndex)
        found.append(
            {
                "cells": cells,
                "colours": drawn,
                "offset": (
                    (offset.factor.getValue(), offset.units.getValue()) if offset else (0.0, 0.0)
                ),
                "zs": {
                    round(points.point[at].getValue()[2], 3) for at in cells if at >= 0 and points
                },
            }
        )
    return found


def _category_colour(state, key):
    """The colour the view hands out to a category, by the key that names it."""
    for category in state.getCategories():
        if category["key"] == key:
            return tuple(round(channel, 3) for channel in category["color"][:3])
    raise AssertionError(f"no category {key!r} in {[c['key'] for c in state.getCategories()]}")


def _drawn_line_colours(vobj):
    """Colours the lines of a mesh are drawn in, over all the sets of them."""
    colours = set()
    for shape in _shapes_in(vobj, coin.SoIndexedLineSet, "IndexedLineSet"):
        if shape["cells"]:
            colours |= shape["colours"]
    return colours


def _drawn_face_sets(vobj):
    """
    The face sets that draw something, sorted by how far back the depth bias
    pushes them, so that they come in the order the depth test resolves.
    """
    sets = [
        {"faces": shape["cells"].count(-1), **shape}
        for shape in _shapes_in(vobj, coin.SoIndexedFaceSet, "IndexedFaceSet")
        if shape["cells"]
    ]
    return sorted(sets, key=lambda entry: entry["offset"])


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
        self.state = FemGui.getAnalysisViewState(assembly)
        self.state.setActiveStage("Mesh")
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

    def _placed_beams(self, quadratic=False):
        line = Part.makeLine(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(BOX_SIZE, 0, 0))
        return self._placed(
            "Quadratic beam" if quadratic else "Beam",
            line,
            _beam_mesh(BEAM_COUNT, quadratic),
        )

    def test_a_beam_mesh_draws_its_elements(self):
        """
        A beam has no face and no edge of its own to report, so what is drawn
        is the element itself, and once.

        The surface hands a beam over as a line of its own, so that is the copy
        taken. The walk over the elements claims the edge without drawing it,
        which is what still keeps a face lying along a beam from putting a dark
        element edge over the top of it.
        """
        placed = self._placed_beams()
        self.assertEqual(_drawn_lines(placed.ViewObject), BEAM_COUNT)

    def test_a_curved_beam_is_drawn_through_its_midpoint(self):
        """
        The one copy that is kept has to be the one that curves, so a quadratic
        beam counts double: one line of three points, and so two segments.
        """
        placed = self._placed_beams(quadratic=True)
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

    # -- the elements the mesher built the solid from ------------------------

    def _placed_skinned_tet(self):
        """
        A meshed solid with its skin shown, and nothing ghosted over it.

        The skin is what the mesher built the solid from, so it only appears
        once the construction elements are asked for. Coloured by element type,
        which is the mode that has anything to say about the elements a mesh is
        made of, and without the ghost of what is left out, that being faces as
        well and saying nothing about any of this.
        """
        placed = self._placed(
            "Skinned",
            Part.makeBox(BOX_SIZE, BOX_SIZE, BOX_SIZE),
            _skinned_tet_mesh(),
        )
        self.state.setOverlay(False)
        self.state.setColorMode("CellType")
        self.state.setShowConstruction(True)
        self.document.recompute()
        FreeCADGui.updateGui()
        return placed

    def test_a_1d_element_is_drawn_in_the_colour_of_its_category(self):
        """
        A 1D element is an element and is coloured as one. An element edge is
        a detail of the element it belongs to and stays dark, so the two cannot
        be drawn out of the same material: the edges of the tetrahedron are
        dark and the three edge elements are not.
        """
        placed = self._placed_skinned_tet()
        drawn = _drawn_line_colours(placed.ViewObject)

        self.assertIn(EDGE_GREY, drawn, "the element edges of the tetrahedron stay dark")
        coloured = drawn - {EDGE_GREY}
        self.assertTrue(
            coloured,
            "the edge elements have to be drawn in something other than the edge colour",
        )
        self.assertEqual(
            coloured,
            {_category_colour(self.state, "line:construction")},
            "and in the colour of the category they belong to",
        )

    def test_the_skin_of_a_solid_is_drawn_in_front_of_it(self):
        """
        A skin triangle and the face of the tetrahedron under it are the same
        triangle in the same place. Nothing about a depth test settles a tie,
        so the two have to be told apart by a bias, and the lower dimension is
        the one to win: the skin is what the user asked to see.
        """
        placed = self._placed_skinned_tet()
        sets = _drawn_face_sets(placed.ViewObject)

        self.assertEqual(len(sets), 2, "the skin and the solid are drawn apart from each other")
        skin, solid = sets
        self.assertLess(skin["offset"], solid["offset"], "the skin is the nearer of the two")

        self.assertEqual(skin["faces"], 1, "the one triangle the mesh skins the solid with")
        self.assertEqual(skin["zs"], {0.0}, "which is the one lying in the z = 0 plane")
        self.assertEqual(skin["colours"], {_category_colour(self.state, "tria3:construction")})

        self.assertEqual(solid["faces"], 4, "the four faces of the tetrahedron")
        self.assertEqual(solid["colours"], {_category_colour(self.state, "tetra4")})
