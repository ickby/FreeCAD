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
Gui unit tests for marking geometry elements in a colour of their own.

The marks are what a task panel uses to show which elements it already holds a
reference to. Everything here reads the Coin nodes rather than the API that set
them, because a mark that does not reach a node is not a mark.
"""

__title__ = "FEM geometry element mark Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import FreeCADGui
import Part

from pivy import coin

import ObjectsFem

from femtest.app.support_utils import fcc_print

RED = (1.0, 0.0, 0.0)
BLUE = (0.0, 0.0, 1.0)
GREEN = (0.0, 1.0, 0.0)
YELLOW = (1.0, 1.0, 0.0)
DEFAULT_MARK = (0.85, 0.15, 0.85)


def children_of_type(node, type_name):
    """
    Direct children of exactly that type.

    Exactly, because SoBrepEdgeSet is an indexed line set too and would be
    mistaken for the mark overlay, and only direct children, because the steps
    of a geometry chain hang in the same graph.
    """
    wanted = coin.SoType.fromName(type_name)
    return [
        node.getChild(i)
        for i in range(node.getNumChildren())
        if node.getChild(i).getTypeId() == wanted
    ]


def own_render(vobj):
    """
    The separator holding this view provider's own render.

    Child 0 of the mode switch is the "Default" mask, which is where
    ViewProviderFemGeometry::attach puts it.
    """
    return vobj.SwitchNode.getChild(0)


def face_material(vobj):
    """
    The material updateColors fills, one colour per rendered face.

    The last one in the separator, which is where attach puts the face material,
    after the one the plain edges and vertices share.
    """
    return children_of_type(own_render(vobj), "SoMaterial")[-1]


def node_colors(material):
    return [
        tuple(round(channel, 3) for channel in material.diffuseColor[i].getValue())
        for i in range(material.diffuseColor.getNum())
    ]


def field_values(field):
    return [field[i] for i in range(field.getNum())]


class TestGeometryMarksGui(unittest.TestCase):
    fcc_print("import TestGeometryMarksGui")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)
        source = self.document.addObject("Part::Feature", "Source")
        source.Shape = Part.makeCompound(
            [
                Part.makeBox(20, 10, 10),
                Part.makeBox(10, 10, 10, FreeCAD.Vector(30, 0, 0)),
            ]
        )
        self.group = ObjectsFem.makeGeometryGroup(self.document)
        self.imp = ObjectsFem.makeGeometryImport(self.document)
        self.imp.Import = [source]
        self.group.Group = [self.imp]
        self.document.recompute()
        FreeCADGui.Selection.clearSelection()

        self.vobj = self.group.ViewObject
        own = own_render(self.vobj)
        overlays = [
            sep
            for sep in children_of_type(own, "SoSeparator")
            if children_of_type(sep, "SoIndexedLineSet")
        ]
        self.assertEqual(len(overlays), 1, "the mark overlay must be built exactly once")
        self.overlay = overlays[0]
        self.lines = children_of_type(self.overlay, "SoIndexedLineSet")[0]
        self.points = children_of_type(self.overlay, "SoIndexedPointSet")[0]
        line_material, point_material = children_of_type(self.overlay, "SoMaterial")
        self.line_material = line_material
        self.point_material = point_material
        self.face_material = face_material(self.vobj)

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        FreeCAD.closeDocument(self.document.Name)

    def _face_colors(self):
        return node_colors(self.face_material)

    def _marked_polylines(self):
        return field_values(self.lines.coordIndex).count(-1)

    def _marked_points(self):
        return len(field_values(self.points.coordIndex))

    def test_nothing_is_marked_to_begin_with(self):
        self.assertEqual(self._marked_polylines(), 0)
        self.assertEqual(self._marked_points(), 0)
        self.assertNotIn(DEFAULT_MARK, self._face_colors())

    def test_a_marked_face_takes_the_mark_colour(self):
        self.vobj.setElementHighlight("test", ["Face1"], RED)
        self.assertEqual(
            self._face_colors().count(RED),
            1,
            "exactly the marked face may change colour",
        )
        self.assertEqual(
            self._marked_polylines(),
            0,
            "a face mark has no business in the edge overlay",
        )

    def test_a_mark_without_a_colour_uses_the_default(self):
        self.vobj.setElementHighlight("test", ["Face1"])
        self.assertIn(DEFAULT_MARK, self._face_colors())

    def test_a_marked_edge_reaches_the_line_overlay(self):
        self.vobj.setElementHighlight("test", ["Edge1"], RED)
        index = field_values(self.lines.coordIndex)
        self.assertEqual(index.count(-1), 1, "one polyline for one edge")
        self.assertGreater(len(index), 2, "a polyline needs points to be drawn")
        self.assertEqual(index[-1], -1, "the polyline has to be terminated")
        self.assertEqual(node_colors(self.line_material), [RED])
        self.assertEqual(
            self._face_colors().count(RED),
            0,
            "an edge mark must not spill onto the faces",
        )

    def test_a_marked_vertex_reaches_the_point_overlay(self):
        self.vobj.setElementHighlight("test", ["Vertex1"], BLUE)
        self.assertEqual(field_values(self.points.coordIndex), [0])
        self.assertEqual(node_colors(self.point_material), [BLUE])

    def test_a_marked_solid_reaches_its_faces(self):
        solid = self.group.Shape.Solids[0]
        self.vobj.setElementHighlight("test", ["Solid1"], GREEN)
        self.assertEqual(
            self._face_colors().count(GREEN),
            len(solid.Faces),
            "a mark on a solid has to cover all of its faces",
        )

    def test_a_marked_solid_leaves_its_edges_and_vertices_alone(self):
        """
        A solid reads from its faces. Colouring its edges and vertices as well
        turns it into one block of colour and swamps the edges and vertices that
        carry a mark in their own right.
        """
        self.vobj.setElementHighlight("test", ["Solid1"], GREEN)
        self.assertEqual(self._marked_polylines(), 0)
        self.assertEqual(self._marked_points(), 0)

    def test_a_marked_solid_still_leaves_room_for_an_edge_mark(self):
        self.vobj.setElementHighlight("targets", ["Solid1"], GREEN)
        self.vobj.setElementHighlight("tool", ["Edge1"], RED)
        self.assertEqual(
            self._marked_polylines(),
            1,
            "only the edge named outright may reach the overlay",
        )
        self.assertEqual(node_colors(self.line_material), [RED])

    def test_a_marked_solid_leaves_the_other_one_alone(self):
        self.vobj.setElementHighlight("test", ["Solid1"], GREEN)
        colors = self._face_colors()
        self.assertEqual(colors.count(GREEN), len(self.group.Shape.Solids[0].Faces))
        self.assertLess(colors.count(GREEN), len(colors))

    def test_an_unknown_element_marks_nothing(self):
        self.vobj.setElementHighlight("test", ["Face999", "Solid7"], RED)
        self.assertNotIn(RED, self._face_colors())
        self.assertEqual(self._marked_polylines(), 0)

    def test_two_roles_hold_their_own_marks(self):
        self.vobj.setElementHighlight("targets", ["Solid1"], GREEN)
        self.vobj.setElementHighlight("tool", ["Face1"], YELLOW)
        colors = self._face_colors()
        self.assertEqual(colors.count(YELLOW), 1)
        self.assertGreater(colors.count(GREEN), 0)

        self.vobj.clearElementHighlight("tool")
        colors = self._face_colors()
        self.assertEqual(colors.count(YELLOW), 0, "clearing a role has to undo its marks")
        self.assertGreater(colors.count(GREEN), 0, "and leave the other role standing")

    def test_the_role_set_last_wins_an_overlap(self):
        self.vobj.setElementHighlight("first", ["Face1"], GREEN)
        self.vobj.setElementHighlight("second", ["Face1"], YELLOW)
        self.assertEqual(self._face_colors().count(YELLOW), 1)
        self.assertEqual(self._face_colors().count(GREEN), 0)

    def test_a_role_reports_what_it_marks(self):
        self.vobj.setElementHighlight("test", ["Face2", "Face1"], RED)
        self.assertEqual(sorted(self.vobj.getElementHighlight("test")), ["Face1", "Face2"])
        self.assertEqual(self.vobj.getElementHighlight("other"), [])

    def test_an_empty_mark_clears_the_role(self):
        self.vobj.setElementHighlight("test", ["Edge1"], RED)
        self.vobj.setElementHighlight("test", [])
        self.assertEqual(self.vobj.getElementHighlight("test"), [])
        self.assertEqual(self._marked_polylines(), 0)

    def test_the_overlay_holds_a_colour_per_polyline(self):
        """
        Two roles of different colours have to survive in one overlay node. The
        material is bound per polyline for exactly this reason; a single colour
        for the whole set would silently repaint one role in the other's colour.
        """
        self.vobj.setElementHighlight("first", ["Edge1"], RED)
        self.vobj.setElementHighlight("second", ["Edge2"], BLUE)
        self.assertEqual(self._marked_polylines(), 2)
        self.assertEqual(sorted(node_colors(self.line_material)), sorted([RED, BLUE]))

    def test_a_selected_edge_keeps_its_selection_colour(self):
        """
        A mark must not swallow the feedback that tells the user their click
        landed, so a selected edge steps out of the overlay for as long as it is
        selected.
        """
        self.vobj.setElementHighlight("test", ["Edge1"], RED)
        self.assertEqual(self._marked_polylines(), 1)

        FreeCADGui.Selection.addSelection(self.group, "Edge1")
        self.assertEqual(self._marked_polylines(), 0)

        FreeCADGui.Selection.clearSelection()
        self.assertEqual(self._marked_polylines(), 1, "the mark has to come back")

    def test_marks_survive_a_rebuild(self):
        """
        Every recompute renumbers the parts and refills the coordinates, so the
        overlay indices of the previous render point at foreign geometry. The
        marks are kept by element name and have to be laid out again.
        """
        solid = self.group.Shape.Solids[0]
        self.vobj.setElementHighlight("targets", ["Solid1"], GREEN)
        self.vobj.setElementHighlight("tool", ["Edge1"], RED)
        self.imp.touch()
        self.document.recompute()
        self.assertEqual(self._face_colors().count(GREEN), len(solid.Faces))
        self.assertEqual(self._marked_polylines(), 1)
        self.assertEqual(node_colors(self.line_material), [RED])

    def test_the_overlay_cannot_be_picked(self):
        """
        A mark sits right on the element it marks. If it took the pick, the user
        could no longer select what is underneath it.
        """
        self.vobj.setElementHighlight("test", ["Edge1"], GREEN)
        style = children_of_type(self.overlay, "SoPickStyle")
        self.assertEqual(len(style), 1)
        self.assertEqual(style[0].style.getValue(), coin.SoPickStyle.UNPICKABLE)

    def test_the_overlay_is_drawn_unlit(self):
        """
        A mark has to come out in the colour it was given. The normals in scope
        belong to the faces, and lighting would shade the mark by them.
        """
        light = children_of_type(self.overlay, "SoLightModel")
        self.assertEqual(len(light), 1)
        self.assertEqual(light[0].model.getValue(), coin.SoLightModel.BASE_COLOR)

    def test_the_overlay_does_not_write_depth(self):
        """
        The marks share their pixels with the edges they mark, so the depth test
        has to let an equal value pass. Writing depth would let a mark shadow the
        geometry drawn after it.
        """
        depth = children_of_type(self.overlay, "SoDepthBuffer")
        self.assertEqual(len(depth), 1)
        self.assertEqual(depth[0].function.getValue(), coin.SoDepthBuffer.LEQUAL)
        # By name, because SoNode::write() shadows the field of the same name
        self.assertFalse(depth[0].getField("write").getValue())
