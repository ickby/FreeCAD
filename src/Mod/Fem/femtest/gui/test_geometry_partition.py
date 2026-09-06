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

import FemGui
import ObjectsFem

from femguiutils import selection_handoff
from femguiutils.selection_rules import shape_kind
from femguiutils.selection_slots import ReferenceSelection
from femobjects import geometry_partition
from femtaskpanels import task_geometry_partition
from femviewprovider import view_geometry_base

from femtest.app.support_utils import fcc_print
from femtest.gui.test_geometry_marks import children_of_type, face_material, node_colors, own_render


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


def _tool_preview_node(vobj):
    """
    The SoPreviewShape ViewProviderFemGeometry hangs under its Default mask.

    Exactly one is built at attach(); an empty one is still present when no
    cutting tool is being shown, switched out of the traversal so that the
    point it holds at the origin stays out of every bounding box.
    """
    own = own_render(vobj)
    # The switch it sits in counts as a place to look, not as a place it is
    candidates = [own.getChild(i) for i in range(own.getNumChildren())]
    for child in list(candidates):
        if child.isOfType(coin.SoSwitch.getClassTypeId()):
            candidates += [child.getChild(i) for i in range(child.getNumChildren())]

    preview_type = coin.SoType.fromName("SoPreviewShape")
    if preview_type != coin.SoType.badType():
        matches = [node for node in candidates if node.getTypeId() == preview_type]
        if matches:
            return matches[-1]

    # Fallback when the typed name is not registered in pivy: look for the
    # separator that carries a matrix transform and an unpickable pick style.
    for child in candidates:
        if not child.isOfType(coin.SoSeparator.getClassTypeId()):
            continue
        if not children_of_type(child, "SoMatrixTransform"):
            continue
        if not children_of_type(child, "SoPickStyle"):
            continue
        if not children_of_type(child, "SoCoordinate3"):
            continue
        return child
    return None


def _preview_coord_count(preview):
    coords = children_of_type(preview, "SoCoordinate3")
    if not coords:
        return 0
    return coords[0].point.getNum()


class _Picker:
    """
    One reference box, driven the way the panel drives its own.

    The panel holds five of these in a single group; a test that is only
    about the picking rules wants one, so it gets a group of its own.
    """

    def __init__(self, geometry, kind, max_count=None, rule=None):
        self.max_count = max_count
        self.group = ReferenceSelection(None, geometry=geometry, auto_install=False)
        self.slot = self.group.add_slot(
            "Targets",
            "Targets",
            rule or task_geometry_partition._sub_element_rule(kind, max_count),
            marks=False,
        )

    @property
    def references(self):
        return list(self.slot.picks)

    def set_target_kind(self, kind):
        self.slot.set_rule(task_geometry_partition._sub_element_rule(kind, self.max_count))
        self.slot.set_picks([ref for ref in self.slot.picks if shape_kind(ref[1]) == kind])

    def start_selection(self):
        self.group.begin_selection()
        self.group.consume_current_selection()

    def finish_selection(self):
        self.group.finish_selection()


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
        self.analysis = ObjectsFem.makeAnalysis(self.document)
        self.group = ObjectsFem.makeGeometryGroup(self.document)
        self.analysis.addObject(self.group)
        self.imp = ObjectsFem.makeGeometryImport(self.document)
        self.imp.Import = [source]
        self.group.Group = [self.imp]
        self.document.recompute()
        self.part = ObjectsFem.makeGeometryPartition(self.document)
        self.group.Group = [self.imp, self.part]
        self.document.recompute()
        FemGui.setActiveAnalysis(self.analysis)
        self.state = FemGui.getAnalysisViewState(self.analysis)
        FreeCADGui.Selection.clearSelection()

    def _enter_edit(self):
        """Open the edit scope of the partition, which is what puts its input on show."""
        self.state.beginEdit(self.part, "Geometry")

    def _leave_edit(self):
        self.state.endEdit(self.part)

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        FreeCAD.closeDocument(self.document.Name)

    def _face_of_second_box(self):
        for index, face in enumerate(self.imp.Shape.Faces, 1):
            if face.CenterOfMass.x > 25:
                return f"Face{index}"
        raise AssertionError("no face on the second box")

    def _picker(self, kind, max_count=None, rule=None):
        return _Picker(self.imp, kind, max_count=max_count, rule=rule)

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestGeometryPartitionGui tests {2}\n{0}".format(
                100 * "*", 10 * "*", 46 * "*"
            )
        )

    def test_the_result_badge_follows_the_last_step(self):
        """
        The group takes its shape from the last step of its chain, and that step
        is the one the tree badges. Membership decides it, so it has to move
        when the chain does: the group says only that something changed and each
        step reads its own answer, including one that has just left.
        """
        self.assertFalse(self.imp.ViewObject.isChainResult())
        self.assertTrue(self.part.ViewObject.isChainResult())

        self.group.Group = [self.imp]
        self.document.recompute()

        self.assertTrue(self.imp.ViewObject.isChainResult())
        self.assertFalse(self.part.ViewObject.isChainResult())
        self.assertEqual(
            self.part.ViewObject.getChainRole(),
            "Owner",
            "a step that left the chain draws for itself again",
        )
        # The mask, not just the answer: nobody writes one into the object that
        # left, so this only holds if it was told to look again and did.
        self.assertEqual(
            _mask_mode(self.part.ViewObject),
            "Default",
            "and its render has to be switched back on without anyone pushing it",
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

        self._enter_edit()
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
        self.assertEqual(self.group.ViewObject.getChainRole(), "SteppedAside")

        self._leave_edit()
        self.assertEqual(_mask_mode(self.imp.ViewObject), "Hidden")
        self.assertEqual(
            _mask_mode(self.group.ViewObject),
            "Default",
            "the group has to render again once the panel is closed",
        )
        self.assertEqual(self.group.ViewObject.getChainRole(), "Owner")

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

        self._enter_edit()
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

        self._leave_edit()
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
        self._enter_edit()
        self.document.recompute()
        self.assertEqual(_mask_mode(self.group.ViewObject), "Group")
        self.assertEqual(_mask_mode(self.imp.ViewObject), "Default")
        self.assertIsNotNone(
            _drawn_extent(self.group.ViewObject),
            "a recompute behind the panel must not empty the viewport",
        )
        self.assertTrue(_pickable_at(self.group.ViewObject, 10, 5))
        self._leave_edit()

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
            self._enter_edit()
        self.assertEqual(_mask_mode(self.imp.ViewObject), "Default")
        for _ in range(2):
            self._leave_edit()
        self.assertEqual(_mask_mode(self.group.ViewObject), "Default")

    def test_preview_offers_display_modes_on_the_step(self):
        self.assertEqual(self.imp.ViewObject.listDisplayModes(), [])
        self._enter_edit()
        self.assertEqual(self.imp.ViewObject.listDisplayModes(), ["Surface", "Wireframe"])
        self._leave_edit()
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

    def test_pick_reported_against_the_analysis_reaches_the_step(self):
        """
        Once the group sits in an analysis the click comes down another level,
        because the analysis holds its members in 3D as well. Reading only as
        far as the group left the gate comparing a face of the chain result
        against the step it was picked on, and every field stayed empty with
        no way to fill it.
        """
        analysis = ObjectsFem.makeAnalysis(self.document)
        analysis.addObject(self.group)
        self.document.recompute()

        picker = self._picker("Solid")
        picker.start_selection()
        FreeCADGui.Selection.addSelection(
            self.document.Name,
            analysis.Name,
            f"{self.group.Name}.{self.imp.Name}.Face1",
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
        self.assertIn(
            (self.imp, "Vertex1"), picker.references, "a full slot refuses the extra pick"
        )
        self.assertNotIn((self.imp, "Vertex4"), picker.references)

    def test_object_picker_takes_an_external_datum_plane(self):
        datum = self.document.addObject("Part::DatumPlane", "Datum")
        datum.Placement = FreeCAD.Placement(
            FreeCAD.Vector(10, 0, 0),
            FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(1, 0, 0)),
        )
        self.document.recompute()

        picker = self._picker("Face", rule=task_geometry_partition._tool_rule())
        FreeCADGui.Selection.addSelection(self.document.Name, datum.Name, "")
        picker.start_selection()
        picker.finish_selection()

        self.assertEqual([obj for obj, _sub in picker.references], [datum])

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

    def test_create_handoff_prefills_targets(self):
        """Selecting first and then opening the panel fills the Targets slot."""
        FreeCADGui.Selection.addSelection(self.document.Name, self.imp.Name, "Face1")
        selection_handoff.stash_for(self.part.Name, self.document.Name)
        FreeCADGui.Selection.clearSelection()
        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            self.assertEqual(panel.targets.picks, [(self.imp, "Solid1")])
            self.assertEqual(FreeCADGui.Selection.getSelection(), [])
        finally:
            panel.deactivate()
            selection_handoff.clear()

    # -- panel --------------------------------------------------------------

    def test_panel_opens_on_the_kind_of_the_stored_targets(self):
        self.part.Elements = [(self.imp, ("Edge1",))]
        self.document.recompute()

        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            self.assertEqual(panel.kind_combo.currentData(), "Edge")
            self.assertEqual(panel.targets.picks, [(self.imp, "Edge1")])
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
            self.assertEqual(panel.targets.picks, [])
        finally:
            panel.deactivate()

    def test_an_open_panel_takes_a_pick_into_targets(self):
        """
        Nothing between opening the panel and clicking in the 3D view.

        Every box used to carry a coordinator of its own and none of them was
        ever installed, so no observer was listening: the Targets arm button
        lit up over nothing and no pick ever arrived.
        """
        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            FreeCADGui.Selection.addSelection(self.document.Name, self.imp.Name, "Face1")
            self.assertEqual(panel.targets.picks, [(self.imp, "Solid1")])
        finally:
            panel.deactivate()

    def test_arming_one_box_disarms_the_other(self):
        """A pick lands in one box, so only one may be armed to take it."""
        self.part.Method = geometry_partition.METHOD_PLANE_3P
        self.document.recompute()

        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            self.assertTrue(panel.targets._armed, "the panel opens ready to take targets")

            panel.points_3.arm()
            self.assertTrue(panel.points_3._armed)
            self.assertFalse(panel.targets._armed)
            self.assertIs(panel.picker.coordinator.armed_slot, panel.points_3)
        finally:
            panel.deactivate()

    def test_the_plane_points_box_takes_vertices(self):
        """The three-point method's box is armable and picks land in it."""
        self.part.Method = geometry_partition.METHOD_PLANE_3P
        self.document.recompute()

        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            panel.points_3.arm()
            for sub in ("Vertex1", "Vertex2", "Vertex3"):
                FreeCADGui.Selection.addSelection(self.document.Name, self.imp.Name, sub)

            self.assertEqual(
                [sub for _obj, sub in panel.points_3.picks],
                ["Vertex1", "Vertex2", "Vertex3"],
            )
            self.assertEqual(len(self.part.Points), 0, "picks stay in the panel until accept")
        finally:
            panel.deactivate()

    def test_panel_picks_reach_the_object_only_on_accept(self):
        """Editing must not recompute or write properties on every pick."""
        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            panel.targets.set_picks([(self.imp, "Solid1")])
            self.assertEqual(panel.targets.picks, [(self.imp, "Solid1")])
            self.assertEqual(self.part.Elements, [])

            panel.commit_properties()
            self.assertEqual(self.part.Elements, [(self.imp, ("Solid1",))])
        finally:
            panel.deactivate()

    def test_a_box_the_method_hides_gives_up_the_arm(self):
        """Picking may not go on filling a box that has left the screen."""
        self.part.Method = geometry_partition.METHOD_PLANE_3P
        self.document.recompute()

        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            panel.points_3.arm()
            panel.kind_combo.setCurrentIndex(panel.kind_combo.findData("Edge"))
            index = panel.method_combo.findText(geometry_partition.METHOD_EDGE_PARAM)
            panel.method_combo.setCurrentIndex(index)

            self.assertIs(panel.picker.coordinator.armed_slot, panel.targets)
        finally:
            panel.deactivate()

    def test_changing_the_method_arms_its_selection_box(self):
        """After a method change the new picker is ready without an extra click."""
        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            self.assertIs(panel.picker.coordinator.armed_slot, panel.targets)

            index = panel.method_combo.findText(geometry_partition.METHOD_EXTEND_FACE)
            panel.method_combo.setCurrentIndex(index)
            self.assertIs(panel.picker.coordinator.armed_slot, panel.tool_face)

            index = panel.method_combo.findText(geometry_partition.METHOD_PLANE_3P)
            panel.method_combo.setCurrentIndex(index)
            self.assertIs(panel.picker.coordinator.armed_slot, panel.points_3)
        finally:
            panel.deactivate()

    def test_closing_the_panel_hands_the_3d_view_back(self):
        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        self.assertTrue(panel.picker.coordinator._gated)
        panel.deactivate()
        self.assertFalse(panel.picker.coordinator._gated)
        self.assertFalse(panel.picker.coordinator._installed)

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
        self._enter_edit()
        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            self.assertEqual(
                self.imp.ViewObject.getElementHighlight(task_geometry_partition.MARK_TARGETS),
                [],
            )
            self.assertEqual(self._marked_face_count(task_geometry_partition.MARK_TARGETS), 0)

            # No arming step: an open panel is already listening on Targets.
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
            self._leave_edit()

    def test_panel_marks_are_gone_once_it_closes(self):
        self.part.Elements = [(self.imp, ("Solid1",))]
        self.document.recompute()

        self._enter_edit()
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
            self._leave_edit()

    def test_panel_marks_points_only_for_the_method_that_uses_them(self):
        """
        Points belong to two methods and a face tool to a third. Marks of a
        method that is not chosen would claim references the step does not use.
        """
        self.part.Method = geometry_partition.METHOD_PLANE_3P
        self.document.recompute()

        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            panel.points_3.set_picks([(self.imp, "Vertex1"), (self.imp, "Vertex2")])
            panel._update_panel()
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

    # -- cutting-tool preview -----------------------------------------------

    def test_tool_preview_shows_a_configured_plane(self):
        """
        Once the cutting tool is defined the panel has to put it on the screen,
        so the user can see where the cut will land before accepting.
        """
        datum = self.document.addObject("Part::DatumPlane", "Datum")
        datum.Placement = FreeCAD.Placement(
            FreeCAD.Vector(10, 0, 0),
            FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(1, 0, 0)),
        )
        self.document.recompute()
        self.part.Method = geometry_partition.METHOD_PLANE_REF
        self.part.Tool = (datum, "")
        self.document.recompute()

        self._enter_edit()
        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            preview = _tool_preview_node(self.imp.ViewObject)
            self.assertIsNotNone(preview, "the input VP must own a tool-preview node")
            self.assertGreater(
                _preview_coord_count(preview),
                0,
                "a configured plane must reach the Coin overlay",
            )
            pick = children_of_type(preview, "SoPickStyle")
            self.assertTrue(pick, "the tool preview must declare a pick style")
            self.assertEqual(
                pick[0].style.getValue(),
                coin.SoPickStyle.UNPICKABLE,
                "the tool must not stand between the user and the geometry",
            )
        finally:
            panel.deactivate()
            self._leave_edit()

    def test_tool_preview_is_cleared_when_the_panel_closes(self):
        datum = self.document.addObject("Part::DatumPlane", "Datum")
        datum.Placement = FreeCAD.Placement(
            FreeCAD.Vector(10, 0, 0),
            FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(1, 0, 0)),
        )
        self.document.recompute()
        self.part.Method = geometry_partition.METHOD_PLANE_REF
        self.part.Tool = (datum, "")
        self.document.recompute()

        self._enter_edit()
        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        preview = _tool_preview_node(self.imp.ViewObject)
        self.assertGreater(_preview_coord_count(preview), 0)
        panel.deactivate()
        self.assertEqual(
            _preview_coord_count(preview),
            0,
            "closing the panel must drop the cutting-tool overlay",
        )
        self._leave_edit()

    def test_tool_preview_outside_the_solid_is_not_pickable(self):
        """
        A ray that only meets the oversized tool plane, not the solid, must
        miss. Otherwise the plane would steal clicks meant for nothing.
        """
        datum = self.document.addObject("Part::DatumPlane", "Datum")
        datum.Placement = FreeCAD.Placement(
            FreeCAD.Vector(10, 0, 0),
            FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(1, 0, 0)),
        )
        self.document.recompute()
        self.part.Method = geometry_partition.METHOD_PLANE_REF
        self.part.Tool = (datum, "")
        self.document.recompute()

        self._enter_edit()
        panel = task_geometry_partition._PartitionTaskPanel(self.part)
        try:
            # The tool plane sits at x=10 and extends far past the solid in Y.
            # A ray along +X at y=-80 meets only the plane.
            action = coin.SoRayPickAction(coin.SbViewportRegion(400, 400))
            action.setRay(coin.SbVec3f(-50, -80, 5), coin.SbVec3f(1, 0, 0))
            action.setPickAll(False)
            action.apply(self.imp.ViewObject.RootNode)
            self.assertIsNone(
                action.getPickedPoint(),
                "the tool plane must not answer a pick outside the solid",
            )
        finally:
            panel.deactivate()
            self._leave_edit()
