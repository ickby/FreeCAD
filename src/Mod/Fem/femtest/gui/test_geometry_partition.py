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

"""Gui unit tests for the FEM geometry partition panel and its edit preview."""

__title__ = "FEM geometry partition Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import FreeCADGui
import Part

# SwitchNode hands out a Coin node, which needs the pivy bindings loaded
from pivy import coin  # noqa: F401

import ObjectsFem

from femobjects import geometry_partition
from femtaskpanels import task_geometry_partition
from femviewprovider import view_geometry_base

from femtest.app.support_utils import fcc_print
from femtest.gui.test_geometry_marks import face_material, node_colors


def _mask_mode(vobj):
    """
    Which display mask the view provider currently shows.

    The mode switch is what actually gates rendering; the display mode list
    says nothing about whether anything reaches the screen.
    """
    switch = vobj.SwitchNode
    index = switch.whichChild.getValue()
    if index < 0:
        return "None"
    # addDisplayMaskMode order in ViewProviderFemGeometry::attach, followed by
    # the "Group" mask that ViewProviderGeoFeatureGroupExtension adds
    return {0: "Default", 1: "Hidden", 2: "Group"}.get(index, f"Child{index}")


def _drawn_extent(vobj):
    """
    Size of everything a traversal starting at this view provider reaches.

    A mask read off a single view provider proves nothing on its own: the steps
    of a chain hang under the mode switch of their group, so a group on the
    Hidden mask takes the whole subtree off the screen no matter what the
    switches below it say. Only a traversal from the group answers what the
    user sees, because it honours every switch on the way down.
    """
    action = coin.SoGetBoundingBoxAction(coin.SbViewportRegion(400, 400))
    action.apply(vobj.RootNode)
    box = action.getBoundingBox()
    if box.isEmpty():
        return None
    return box.getSize().getValue()


def _pickable_at(vobj, x, y):
    """Whether a ray shot straight down at (x, y) hits anything."""
    action = coin.SoRayPickAction(coin.SbViewportRegion(400, 400))
    action.setRay(coin.SbVec3f(x, y, 500), coin.SbVec3f(0, 0, -1))
    action.setPickAll(False)
    action.apply(vobj.RootNode)
    return action.getPickedPoint() is not None


class TestGeometryPartitionGui(unittest.TestCase):
    fcc_print("import TestGeometryPartitionGui")

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
        self.part = ObjectsFem.makeGeometryPartition(self.document)
        self.group.Group = [self.imp, self.part]
        self.document.recompute()
        FreeCADGui.Selection.clearSelection()

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        FreeCAD.closeDocument(self.document.Name)

    def _face_of_second_box(self):
        for index, face in enumerate(self.imp.Shape.Faces, 1):
            if face.CenterOfMass.x > 25:
                return f"Face{index}"
        raise AssertionError("no face on the second box")

    def _picker(self, kind, max_count=None):
        picker = task_geometry_partition._SubElementPicker(
            "Targets", self.imp, (kind,), max_count=max_count
        )
        picker.set_target_kind(kind)
        return picker

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestGeometryPartitionGui tests {2}\n{0}".format(
                100 * "*", 10 * "*", 46 * "*"
            )
        )

    # -- edit preview -------------------------------------------------------

    def test_preview_shows_the_input_and_restores_the_group(self):
        """
        Opening the panel used to leave an empty viewport: the input step had
        its geometry built but stayed on the Hidden mask, and the group never
        got its render back after the panel closed.
        """
        self.assertEqual(_mask_mode(self.group.ViewObject), "Default")
        self.assertEqual(_mask_mode(self.imp.ViewObject), "Hidden")

        view_geometry_base.set_input_preview(self.part, True)
        self.assertEqual(
            _mask_mode(self.imp.ViewObject),
            "Default",
            "the input geometry must be rendered so it can be picked",
        )
        self.assertEqual(
            _mask_mode(self.group.ViewObject),
            "Group",
            "the group must drop its own result but keep its children reachable",
        )
        self.assertTrue(self.group.ViewObject.isChainRenderSuppressed())

        view_geometry_base.set_input_preview(self.part, False)
        self.assertEqual(_mask_mode(self.imp.ViewObject), "Hidden")
        self.assertEqual(
            _mask_mode(self.group.ViewObject),
            "Default",
            "the group has to render again once the panel is closed",
        )
        self.assertFalse(self.group.ViewObject.isChainRenderSuppressed())

    def test_the_previewed_input_really_reaches_the_screen(self):
        """
        The step used to be switched on while its group was switched off. A
        switch traverses one child only, and the steps of a chain hang under the
        Group mask of that switch, so the group being on Hidden dropped the
        previewed step with it: the viewport went empty and nothing could be
        picked, even though the step's own mask read Default.
        """
        source = _drawn_extent(self.group.ViewObject)
        self.assertIsNotNone(source, "the group renders the chain result to begin with")

        view_geometry_base.set_input_preview(self.part, True)
        drawn = _drawn_extent(self.group.ViewObject)
        self.assertIsNotNone(
            drawn,
            "opening the panel must leave the input geometry on the screen",
        )
        for got, want in zip(drawn, source):
            self.assertAlmostEqual(got, want, places=3)
        self.assertTrue(
            _pickable_at(self.group.ViewObject, 10, 5),
            "the input geometry has to be pickable, that is what the panel is for",
        )

        view_geometry_base.set_input_preview(self.part, False)
        restored = _drawn_extent(self.group.ViewObject)
        self.assertIsNotNone(restored, "closing the panel must bring the result back")
        for got, want in zip(restored, source):
            self.assertAlmostEqual(got, want, places=3)
        self.assertTrue(_pickable_at(self.group.ViewObject, 10, 5))

    def test_preview_survives_a_recompute_while_the_panel_is_open(self):
        """
        The document recomputes behind an open panel, and a step that is not yet
        configured recomputes to a pass-through. Neither may take the input
        geometry off the screen.
        """
        view_geometry_base.set_input_preview(self.part, True)
        self.document.recompute()
        self.assertEqual(_mask_mode(self.group.ViewObject), "Group")
        self.assertEqual(_mask_mode(self.imp.ViewObject), "Default")
        self.assertIsNotNone(
            _drawn_extent(self.group.ViewObject),
            "a recompute behind the panel must not empty the viewport",
        )
        self.assertTrue(_pickable_at(self.group.ViewObject, 10, 5))
        view_geometry_base.set_input_preview(self.part, False)

    def test_double_click_edit_shows_the_input(self):
        """
        The same thing once more over the entry point the user takes, so the
        wiring from the view provider through the task panel is covered and not
        just the preview call underneath it.
        """
        try:
            FreeCADGui.ActiveDocument.setEdit(self.part.Name)
            self.assertIsNotNone(
                _drawn_extent(self.group.ViewObject),
                "editing a step must show the geometry it builds on",
            )
            self.assertTrue(_pickable_at(self.group.ViewObject, 10, 5))
        finally:
            FreeCADGui.ActiveDocument.resetEdit()
        self.document.recompute()
        self.assertEqual(_mask_mode(self.group.ViewObject), "Default")
        self.assertIsNotNone(_drawn_extent(self.group.ViewObject))

    def test_preview_is_idempotent(self):
        for _ in range(2):
            view_geometry_base.set_input_preview(self.part, True)
        self.assertEqual(_mask_mode(self.imp.ViewObject), "Default")
        for _ in range(2):
            view_geometry_base.set_input_preview(self.part, False)
        self.assertEqual(_mask_mode(self.group.ViewObject), "Default")

    def test_preview_offers_display_modes_on_the_step(self):
        self.assertEqual(self.imp.ViewObject.listDisplayModes(), [])
        view_geometry_base.set_input_preview(self.part, True)
        self.assertEqual(self.imp.ViewObject.listDisplayModes(), ["Surface", "Wireframe"])
        view_geometry_base.set_input_preview(self.part, False)
        self.assertEqual(self.imp.ViewObject.listDisplayModes(), [])

    # -- picking ------------------------------------------------------------

    def test_pick_reported_against_the_group_reaches_the_step(self):
        """
        The geometry group is a GeoFeatureGroup, so the selection reports the
        group plus an element-map encoded path. Comparing that object against
        the step rejected every pick made in the 3D view.
        """
        picker = self._picker("Solid")
        picker.start_selection()
        FreeCADGui.Selection.addSelection(
            self.document.Name, self.group.Name, f"{self.imp.Name}.Face1"
        )
        picker.finish_selection()

        self.assertEqual(picker.references, [(self.imp, "Solid1")])

    def test_face_pick_becomes_the_owning_solid(self):
        """A 3D click can only hit a face, so solid targets are derived."""
        picker = self._picker("Solid")
        picker.start_selection()
        FreeCADGui.Selection.addSelection(self.document.Name, self.imp.Name, "Face1")
        FreeCADGui.Selection.addSelection(
            self.document.Name, self.imp.Name, self._face_of_second_box()
        )
        picker.finish_selection()

        self.assertEqual(picker.references, [(self.imp, "Solid1"), (self.imp, "Solid2")])

    def test_second_face_of_the_same_solid_is_not_added_twice(self):
        picker = self._picker("Solid")
        picker.start_selection()
        for sub in ("Face1", "Face2", "Face3"):
            FreeCADGui.Selection.addSelection(self.document.Name, self.imp.Name, sub)
        picker.finish_selection()

        self.assertEqual(picker.references, [(self.imp, "Solid1")])

    def test_preselection_is_taken_over_by_add(self):
        FreeCADGui.Selection.addSelection(
            self.document.Name, self.imp.Name, self._face_of_second_box()
        )
        picker = self._picker("Solid")
        picker.start_selection()
        picker.finish_selection()

        self.assertEqual(picker.references, [(self.imp, "Solid2")])

    def test_face_and_edge_kinds_keep_the_picked_element(self):
        for kind, sub in (("Face", "Face1"), ("Edge", "Edge1"), ("Vertex", "Vertex1")):
            with self.subTest(kind=kind):
                FreeCADGui.Selection.clearSelection()
                picker = self._picker(kind)
                picker.start_selection()
                FreeCADGui.Selection.addSelection(self.document.Name, self.imp.Name, sub)
                picker.finish_selection()
                self.assertEqual(picker.references, [(self.imp, sub)])

    def test_a_pick_of_the_wrong_kind_is_refused(self):
        picker = self._picker("Edge")
        picker.start_selection()
        FreeCADGui.Selection.addSelection(self.document.Name, self.imp.Name, "Face1")
        picker.finish_selection()

        self.assertEqual(picker.references, [])

    def test_switching_kind_drops_picks_of_the_other_kind(self):
        picker = self._picker("Face")
        picker.start_selection()
        FreeCADGui.Selection.addSelection(self.document.Name, self.imp.Name, "Face1")
        picker.finish_selection()
        self.assertEqual(picker.references, [(self.imp, "Face1")])

        picker.set_target_kind("Solid")
        self.assertEqual(picker.references, [])

    def test_picker_respects_the_maximum_count(self):
        picker = self._picker("Vertex", max_count=3)
        picker.start_selection()
        for sub in ("Vertex1", "Vertex2", "Vertex3", "Vertex4"):
            FreeCADGui.Selection.addSelection(self.document.Name, self.imp.Name, sub)
        picker.finish_selection()

        self.assertEqual(len(picker.references), 3)
        self.assertNotIn((self.imp, "Vertex1"), picker.references, "oldest pick drops out")

    def test_object_picker_takes_an_external_datum_plane(self):
        datum = self.document.addObject("Part::DatumPlane", "Datum")
        datum.Placement = FreeCAD.Placement(
            FreeCAD.Vector(10, 0, 0),
            FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(1, 0, 0)),
        )
        self.document.recompute()

        picker = task_geometry_partition._ObjectPicker("Reference", self.imp)
        FreeCADGui.Selection.addSelection(self.document.Name, datum.Name, "")
        picker.start_selection()
        picker.finish_selection()

        self.assertIsNotNone(picker.reference)
        self.assertEqual(picker.reference[0], datum)

    def test_picked_solids_drive_the_partition(self):
        picker = self._picker("Solid")
        picker.start_selection()
        FreeCADGui.Selection.addSelection(self.document.Name, self.imp.Name, "Face1")
        picker.finish_selection()

        datum = self.document.addObject("Part::DatumPlane", "Datum")
        datum.Placement = FreeCAD.Placement(
            FreeCAD.Vector(10, 0, 0),
            FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(1, 0, 0)),
        )
        self.document.recompute()

        self.part.Method = geometry_partition.METHOD_PLANE_REF
        self.part.Tool = (datum, "")
        self.part.Elements = task_geometry_partition._references_to_links(picker.references)
        self.document.recompute()

        self.assertNotIn("Invalid", self.part.State)
        # only the targeted box is cut, the second one is left alone
        self.assertEqual(len(self.part.Shape.Solids), 3)
        self.assertAlmostEqual(self.part.Shape.Volume, self.imp.Shape.Volume, places=6)

    # -- panel --------------------------------------------------------------

    def test_panel_opens_on_the_kind_of_the_stored_targets(self):
        self.part.Elements = [(self.imp, ("Edge1",))]
        self.document.recompute()

        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            self.assertEqual(panel.kind_combo.currentData(), "Edge")
            self.assertEqual(panel.target_picker.references, [(self.imp, "Edge1")])
            self.assertTrue(
                geometry_partition.method_available(
                    panel.method_combo.currentText(), self.part.Elements
                ),
                "the panel must not open on a method that cannot run",
            )
        finally:
            panel.deactivate()

    def test_panel_replaces_a_method_the_targets_rule_out(self):
        """Shortest path needs one face, so edge targets have to move it off."""
        self.part.Method = geometry_partition.METHOD_SHORTEST_PATH
        self.part.Elements = [(self.imp, ("Edge1",))]
        self.document.recompute()

        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            self.assertNotEqual(
                panel.method_combo.currentText(), geometry_partition.METHOD_SHORTEST_PATH
            )
            self.assertTrue(
                geometry_partition.method_available(
                    panel.method_combo.currentText(), self.part.Elements
                )
            )
        finally:
            panel.deactivate()

    def test_panel_kind_switch_clears_incompatible_targets(self):
        self.part.Elements = [(self.imp, ("Solid1",))]
        self.document.recompute()

        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            self.assertEqual(panel.kind_combo.currentData(), "Solid")
            index = panel.kind_combo.findData("Edge")
            panel.kind_combo.setCurrentIndex(index)
            self.assertEqual(panel.target_picker.references, [])
        finally:
            panel.deactivate()

    # -- marks --------------------------------------------------------------

    def _marked_face_count(self, role):
        """Faces of the previewed input step drawn in that role's colour."""
        color = tuple(round(channel, 3) for channel in task_geometry_partition.MARK_COLORS[role])
        return node_colors(face_material(self.imp.ViewObject)).count(color)

    def test_panel_marks_its_stored_targets_on_the_input(self):
        """
        The panel picks on the input step, so that is where the marks have to
        land: marking the group would put them on a shape that is not on screen
        while the panel is open.
        """
        self.part.Elements = [(self.imp, ("Solid1",))]
        self.document.recompute()

        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            self.assertEqual(
                self.imp.ViewObject.getElementHighlight(task_geometry_partition.MARK_TARGETS),
                ["Solid1"],
            )
        finally:
            panel.deactivate()

    def test_panel_marks_follow_a_new_pick(self):
        """
        With the preview on, because that is when the input step renders and a
        mark can reach the screen at all.
        """
        view_geometry_base.set_input_preview(self.part, True)
        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            self.assertEqual(
                self.imp.ViewObject.getElementHighlight(task_geometry_partition.MARK_TARGETS),
                [],
            )
            self.assertEqual(self._marked_face_count(task_geometry_partition.MARK_TARGETS), 0)

            panel.target_picker.start_selection()
            FreeCADGui.Selection.addSelection(self.document.Name, self.imp.Name, "Face1")
            self.assertEqual(
                self.imp.ViewObject.getElementHighlight(task_geometry_partition.MARK_TARGETS),
                ["Solid1"],
                "the mark has to show the solid the pick was promoted to",
            )
            self.assertEqual(
                self._marked_face_count(task_geometry_partition.MARK_TARGETS),
                len(self.imp.Shape.Solids[0].Faces),
                "a marked solid has to reach the faces of that solid",
            )
        finally:
            panel.deactivate()
            view_geometry_base.set_input_preview(self.part, False)

    def test_panel_marks_are_gone_once_it_closes(self):
        self.part.Elements = [(self.imp, ("Solid1",))]
        self.document.recompute()

        view_geometry_base.set_input_preview(self.part, True)
        try:
            panel = task_geometry_partition._PartitionTaskPanel(self.part)
            self.assertEqual(
                self._marked_face_count(task_geometry_partition.MARK_TARGETS),
                len(self.imp.Shape.Solids[0].Faces),
                "the stored targets have to be marked while the panel is open",
            )

            panel.deactivate()
            for role in (
                task_geometry_partition.MARK_TARGETS,
                task_geometry_partition.MARK_POINTS,
                task_geometry_partition.MARK_TOOL,
            ):
                self.assertEqual(self.imp.ViewObject.getElementHighlight(role), [])
            self.assertEqual(self._marked_face_count(task_geometry_partition.MARK_TARGETS), 0)
        finally:
            view_geometry_base.set_input_preview(self.part, False)

    def test_panel_marks_points_only_for_the_method_that_uses_them(self):
        """
        Points belong to two methods and a face tool to a third. Marks of a
        method that is not chosen would claim references the step does not use.
        """
        self.part.Method = geometry_partition.METHOD_PLANE_3P
        self.document.recompute()

        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            panel.points_3.set_references([(self.imp, "Vertex1"), (self.imp, "Vertex2")])
            panel.apply_properties()
            self.assertEqual(
                sorted(
                    self.imp.ViewObject.getElementHighlight(task_geometry_partition.MARK_POINTS)
                ),
                ["Vertex1", "Vertex2"],
            )

            index = panel.method_combo.findText(geometry_partition.METHOD_EDGE_PARAM)
            panel.kind_combo.setCurrentIndex(panel.kind_combo.findData("Edge"))
            panel.method_combo.setCurrentIndex(index)
            self.assertEqual(
                self.imp.ViewObject.getElementHighlight(task_geometry_partition.MARK_POINTS),
                [],
                "edge parameter takes no points, so none may stay marked",
            )
        finally:
            panel.deactivate()

    def test_panel_does_not_mark_an_external_tool(self):
        """A datum plane is no part of the input shape and has nothing to mark."""
        datum = self.document.addObject("Part::DatumPlane", "Datum")
        datum.Placement = FreeCAD.Placement(
            FreeCAD.Vector(10, 0, 0),
            FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(1, 0, 0)),
        )
        self.document.recompute()
        self.part.Method = geometry_partition.METHOD_PLANE_REF
        self.part.Tool = (datum, "")
        self.document.recompute()

        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            self.assertEqual(
                self.imp.ViewObject.getElementHighlight(task_geometry_partition.MARK_TOOL),
                [],
            )
        finally:
            panel.deactivate()
