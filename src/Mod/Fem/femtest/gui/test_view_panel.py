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

"""Gui unit tests for the FEM view panel, above all its behaviour while a
geometry chain step is being edited."""

__title__ = "FEM view panel Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import FreeCADGui
import Fem
import FemGui
import Part

from PySide import QtCore, QtGui

import ObjectsFem

# SwitchNode hands out a Coin node, which needs the pivy bindings loaded
from pivy import coin  # noqa: F401

from femguiutils import view_panel
from femtaskpanels import task_geometry_partition
from femviewprovider import view_geometry_base

from femtest.app.support_utils import fcc_print


def _drawn_size(vobj):
    """
    Extent of everything a traversal from this view provider reaches, or None
    when nothing is drawn. Chain steps hang under the mode switch of their
    group, so only a traversal answers what the user sees.
    """
    action = coin.SoGetBoundingBoxAction(coin.SbViewportRegion(400, 400))
    action.apply(vobj.RootNode)
    box = action.getBoundingBox()
    if box.isEmpty():
        return None
    return box.getSize().getValue()


def _flush_deletions():
    """
    Let the widgets that were told to delete themselves actually go.

    A dock that has been shut down is still a child of the main window until
    then, so two of them answer to the name FEMView and a lookup finds the
    dead one first. The application does this between workbench switches by
    running its event loop; a test has to ask.
    """
    event = QtCore.QEvent
    deferred = event.Type.DeferredDelete if hasattr(event, "Type") else event.DeferredDelete
    QtCore.QCoreApplication.sendPostedEvents(None, deferred)


def _row_names(model, parent=None):
    """Element names the tree offers, whatever the depth they sit at."""
    if parent is None:
        parent = view_panel.QModelIndex()
    names = []
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        node = model.get_item(index)
        if node.element:
            names.append(node.element)
        names.extend(_row_names(model, index))
    return names


def _category_rows(model, parent=None):
    """Labels of the rows that stand for a category rather than an element."""
    if parent is None:
        parent = view_panel.QModelIndex()
    labels = []
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        node = model.get_item(index)
        if node.is_category:
            labels.append(node.name)
        labels.extend(_category_rows(model, index))
    return labels


def _two_solid_tet_mesh():
    """
    One tetrahedron per solid, each with its four skin triangles.

    The volumes are what the analysis solves and the triangles are what the
    mesher built them from, which is the whole distinction the panel is about:
    two analysis elements out of ten.
    """
    mesh = Fem.FemMesh()
    for solid, offset in ((1, 0.0), (2, 30.0)):
        base = mesh.NodeCount
        nodes = [base + 1, base + 2, base + 3, base + 4]
        mesh.addNode(offset, 0, 0, nodes[0])
        mesh.addNode(offset + 1, 0, 0, nodes[1])
        mesh.addNode(offset, 1, 0, nodes[2])
        mesh.addNode(offset, 0, 1, nodes[3])
        volume = mesh.addVolume(nodes)
        group = mesh.addGroup(f"Solid{solid}", "Volume")
        mesh.addGroupElements(group, [volume])
        faces = [
            mesh.addFace([nodes[0], nodes[1], nodes[2]]),
            mesh.addFace([nodes[0], nodes[1], nodes[3]]),
            mesh.addFace([nodes[0], nodes[2], nodes[3]]),
            mesh.addFace([nodes[1], nodes[2], nodes[3]]),
        ]
        for i, face in enumerate(faces, start=1 + (solid - 1) * 4):
            group = mesh.addGroup(f"Face{i}", "Face")
            mesh.addGroupElements(group, [face])
    return mesh


def _cell_type_groups(model):
    """Element type rows under the head that says what they are for."""
    groups = {}
    root = view_panel.QModelIndex()
    for row in range(model.rowCount(root)):
        head = model.index(row, 0, root)
        types = []
        for child in range(model.rowCount(head)):
            node = model.get_item(model.index(child, 0, head))
            types.append((node.name, node.count_badge))
        groups[model.get_item(head).name] = types
    return groups


def _group_index(model, name):
    """Index of a top-level row by its label."""
    root = view_panel.QModelIndex()
    for row in range(model.rowCount(root)):
        index = model.index(row, 0, root)
        if model.get_item(index).name == name:
            return index
    return root


def _cell_type_index(model, group, label):
    """Index of an element type row under the named head."""
    head = _group_index(model, group)
    for row in range(model.rowCount(head)):
        index = model.index(row, 0, head)
        if model.get_item(index).name == label:
            return index
    return view_panel.QModelIndex()


def _enabled_dimensions(combo):
    """Texts of the dimension entries that can be picked."""
    model = combo.model()
    return [combo.itemText(i) for i in range(combo.count()) if model.item(i).isEnabled()]


def _index_of(model, element, parent=None):
    """Index of the row for an element name, or an invalid index."""
    if parent is None:
        parent = view_panel.QModelIndex()
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        if model.get_item(index).element == element:
            return index
        found = _index_of(model, element, index)
        if found.isValid():
            return found
    return view_panel.QModelIndex()


class TestViewPanelGui(unittest.TestCase):
    fcc_print("import TestViewPanelGui")

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
        self.imp = ObjectsFem.makeGeometryImport(self.document)
        self.imp.Import = [source]
        self.group.Group = [self.imp]
        self.analysis.addObject(self.group)
        self.document.recompute()
        self.part = ObjectsFem.makeGeometryPartition(self.document)
        self.group.Group = [self.imp, self.part]
        self.document.recompute()
        FemGui.setActiveAnalysis(self.analysis)

        # The live panel, not a copy of it: two instances would both answer the
        # edit notifications and take turns putting the stage back.
        view_panel.setup_visualization_panel()
        dock = FreeCADGui.getMainWindow().findChild(QtGui.QDockWidget, "FEMView")
        self.assertIsNotNone(dock, "the FEM workbench puts up the view panel")
        self.explorer = dock.widget()._explorer
        self.settings = dock.widget()._settings

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        FreeCAD.closeDocument(self.document.Name)

    def _add_mesh(self):
        mesh = ObjectsFem.makeMeshShapeGroup(
            self.document, geometry=self.group, analysis=self.analysis
        )
        self.document.recompute()
        # The panel picks the mesh up from the analysis members
        self.settings.setup_analysis()
        return mesh

    def _add_meshed_mesh(self):
        """A mesh group with elements in it, in the mesh stage, ready to count."""
        group = self._add_mesh()
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        child.FemMesh = _two_solid_tet_mesh()
        group.Group = [child]
        self.document.recompute()
        FemGui.getAnalysisViewState(self.analysis).setActiveStage("Mesh")
        self.settings.setup_analysis()
        return group

    def _enter_edit(self):
        """Enter the partition step the way the view provider does, then hand the
        panels the notification the document observer would deliver."""
        view_geometry_base.set_input_preview(self.part, True)
        self.explorer.slotInEdit(self.part.ViewObject)
        self.settings.slotInEdit(self.part.ViewObject)

    def _leave_edit(self):
        view_geometry_base.set_input_preview(self.part, False)
        self.explorer.slotResetEdit(self.part.ViewObject)
        self.settings.slotResetEdit(self.part.ViewObject)

    # -- what the tree describes --------------------------------------------

    def test_the_tree_describes_the_chain_result(self):
        self.assertIs(self.explorer._tree_object(), self.group)
        self.assertIs(self.explorer._selection_target(), self.group)

    def test_editing_a_step_moves_the_tree_onto_its_input(self):
        self._enter_edit()
        self.assertIs(self.explorer._tree_object(), self.imp)
        self.assertIs(self.explorer._model.geom_obj, self.imp)
        # Selecting from the tree has to land on the object that is drawn,
        # which is the input while the step is open.
        self.assertIs(self.explorer._selection_target(), self.imp)

    def test_closing_the_step_brings_the_tree_back(self):
        self._enter_edit()
        self._leave_edit()
        self.assertIs(self.explorer._tree_object(), self.group)
        self.assertIs(self.explorer._model.geom_obj, self.group)

    def test_the_tree_lists_the_elements_of_the_input(self):
        self._enter_edit()
        try:
            expected = []
            for component in range(self.imp.getComponentCount()):
                expected += self.imp.getToplevelElements(component)
            self.assertEqual(_row_names(self.explorer._model), expected)
        finally:
            self._leave_edit()

    def test_a_category_colour_mode_does_not_take_over_the_edit_tree(self):
        """
        Material and CellType group the rows by categories of the analysis
        geometry, whose element names say nothing about a step's input. The edit
        session stays on the geometry tree, where a row still addresses the
        shape on screen.
        """
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setColorMode("Material")
        self.assertTrue(
            _category_rows(self.explorer._model),
            "material mode groups the result by category",
        )
        self._enter_edit()
        try:
            self.assertEqual(_category_rows(self.explorer._model), [])
            self.assertIn("Solid2", _row_names(self.explorer._model))
        finally:
            self._leave_edit()
            state.setColorMode("Subelement")

    def test_an_unrelated_editor_leaves_the_tree_alone(self):
        """Only a step that previews its input takes the tree with it."""
        self.explorer.slotInEdit(self.group.ViewObject)
        self.assertIs(self.explorer._tree_object(), self.group)
        self.assertIsNone(self.explorer.edit_obj)

    def test_a_step_that_is_not_previewing_leaves_the_tree_alone(self):
        self.explorer.slotInEdit(self.part.ViewObject)
        self.assertIs(self.explorer._tree_object(), self.group)

    def test_the_tree_survives_the_step_being_deleted_mid_edit(self):
        self._enter_edit()
        self.document.removeObject(self.imp.Name)
        self.document.recompute()
        self.assertIs(self.explorer._tree_object(), self.group)

    # -- hiding parts to reach a reference -----------------------------------

    def test_hiding_a_part_of_the_input_reaches_the_render(self):
        """
        The whole point of the tree following the step: switching a part off has
        to take it out of the previewed shape, or it cannot clear the way to a
        reference buried behind it.
        """
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setOverlay(False)
        self._enter_edit()
        try:
            whole = _drawn_size(self.group.ViewObject)
            self.assertIsNotNone(whole, "editing a step must show its input")
            state.setElementHidden("Solid1", True)
            rest = _drawn_size(self.group.ViewObject)
            self.assertIsNotNone(rest, "the other solid stays on screen")
            self.assertLess(rest[0], whole[0], "the hidden solid must be gone")

            # And the ghost of what was switched off, for orientation
            state.setOverlay(True)
            self.assertEqual(_drawn_size(self.group.ViewObject), whole)
        finally:
            state.setOverlay(True)
            self._leave_edit()

    def test_parts_hidden_while_editing_do_not_outlive_the_step(self):
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setElementHidden("Solid2", True)
        self._enter_edit()
        state.setElementHidden("Solid1", True)
        self.assertEqual(set(state.getHiddenElements()), {"Solid1", "Solid2"})
        self._leave_edit()
        self.assertEqual(
            set(state.getHiddenElements()),
            {"Solid2"},
            "hiding to clear the way for a pick is scratch, what was hidden before is not",
        )

    def test_the_ghost_outlives_a_clip_that_takes_everything(self):
        """
        The ghost is what says where the geometry went, so a clip plane that
        leaves nothing of it is the one moment it matters most. Writing it
        after the surfaces means an empty result never reaches it.
        """
        state = FemGui.getAnalysisViewState(self.analysis)
        whole = _drawn_size(self.group.ViewObject)
        self.assertIsNotNone(whole)

        # Well above the geometry, so the clip keeps none of it
        state.setClipPlane("clip", FreeCAD.Vector(0, 0, 1000), FreeCAD.Vector(0, 0, 1))
        try:
            self.assertEqual(_drawn_size(self.group.ViewObject), whole)
            state.setOverlay(False)
            self.assertIsNone(
                _drawn_size(self.group.ViewObject),
                "with the ghost off there is nothing left to draw",
            )
        finally:
            state.setOverlay(True)
            state.removeClipPlane("clip")
        self.assertEqual(_drawn_size(self.group.ViewObject), whole)

    def test_a_lost_analysis_drops_what_was_hidden_for_the_step(self):
        state = FemGui.getAnalysisViewState(self.analysis)
        self._enter_edit()
        state.setElementHidden("Solid1", True)
        self.explorer.remove_analysis()
        self.assertIsNone(self.explorer.edit_obj)
        self._leave_edit()
        self.assertEqual(set(state.getHiddenElements()), {"Solid1"})

    # -- picking from the tree ----------------------------------------------

    def test_a_row_clicked_in_the_tree_reaches_the_step_panel(self):
        """
        The other half of the point: with the tree on the input, a solid can be
        handed to the open step by clicking its row, which is the way out of
        picking solids that are hard to reach in the 3D view.
        """
        self._enter_edit()
        try:
            index = _index_of(self.explorer._model, "Solid2")
            self.assertTrue(index.isValid(), "the input's solids are in the tree")
            self.explorer.selectionModel().select(
                index, QtCore.QItemSelectionModel.SelectionFlag.Select
            )
            picks = [(obj.Name, sub) for obj, sub in task_geometry_partition._current_picks()]
            self.assertIn((self.imp.Name, "Solid2"), picks)
        finally:
            self._leave_edit()

    # -- switching the stages on and off -------------------------------------

    def test_pressing_the_lit_stage_button_switches_it_off(self):
        """
        Showing neither is what clears the view for the results, so the button
        that is on turns itself off instead of handing over to the other stage.
        """
        self._add_mesh()
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setActiveStage("Geometry")
        self.settings.widget.GeometryButton.click()
        self.assertEqual(state.getActiveStage(), view_panel._NO_STAGE)
        self.assertFalse(self.settings.widget.GeometryButton.isChecked())
        self.assertFalse(self.settings.widget.MeshButton.isChecked())

    def test_the_geometry_switches_off_with_no_mesh_to_fall_back_to(self):
        """An empty view is the point, so having nothing else is no obstacle."""
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setActiveStage("Geometry")
        self.assertFalse(self.settings.widget.MeshButton.isEnabled())
        self.settings.widget.GeometryButton.click()
        self.assertEqual(state.getActiveStage(), view_panel._NO_STAGE)
        self.assertFalse(self.settings.widget.GeometryButton.isChecked())

    def test_the_other_stage_button_still_switches_over(self):
        self._add_mesh()
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setActiveStage("Geometry")
        self.settings.widget.MeshButton.click()
        self.assertEqual(state.getActiveStage(), "Mesh")
        self.assertFalse(self.settings.widget.GeometryButton.isChecked())

    def test_a_stage_switched_off_comes_back_on(self):
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setActiveStage("Geometry")
        self.settings.widget.GeometryButton.click()
        self.settings.widget.GeometryButton.click()
        self.assertEqual(state.getActiveStage(), "Geometry")

    def test_showing_neither_survives_a_rescan_of_the_analysis(self):
        """
        The panel re-reads the analysis on every geometry or mesh change, and
        must not take a deliberately blank view for a stage to correct.
        """
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setActiveStage("Geometry")
        self.settings.widget.GeometryButton.click()
        self.settings.setup_analysis()
        self.assertEqual(state.getActiveStage(), view_panel._NO_STAGE)

    def test_a_mesh_that_goes_away_hands_the_stage_back_to_the_geometry(self):
        """The mesh stage draws nothing once the mesh is gone, and the buttons
        offer no way out of it either, so the panel has to leave it."""
        mesh = self._add_mesh()
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setActiveStage("Mesh")
        self.document.removeObject(mesh.Name)
        self.document.recompute()
        self.settings.setup_analysis()
        self.assertEqual(state.getActiveStage(), "Geometry")

    # -- the stage while a step is open --------------------------------------

    def test_editing_a_step_puts_the_view_into_the_geometry_stage(self):
        self._add_mesh()
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setActiveStage("Mesh")
        self._enter_edit()
        try:
            self.assertEqual(state.getActiveStage(), "Geometry")
            self.assertFalse(
                self.settings.widget.MeshButton.isEnabled(),
                "the stage must stay put while geometry is being picked",
            )
        finally:
            self._leave_edit()
        self.assertEqual(state.getActiveStage(), "Mesh")
        self.assertTrue(self.settings.widget.MeshButton.isEnabled())

    def test_the_geometry_stage_is_kept_when_the_step_closes(self):
        self._add_mesh()
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setActiveStage("Geometry")
        self._enter_edit()
        self._leave_edit()
        self.assertEqual(state.getActiveStage(), "Geometry")

    # -- analysis elements and the ones the mesher built them from -----------

    def test_the_dimension_modes_are_dimensions(self):
        """
        Shapes are what a mesh is made of, dimensions are what an analysis is
        about, and the panel filters by the latter.
        """
        combo = self.settings.widget.Dimension
        offered = [combo.itemText(i) for i in range(combo.count())]
        self.assertEqual(offered, ["All", "3D", "2D", "1D", "0D"])
        state = FemGui.getAnalysisViewState(self.analysis)
        self.assertEqual(state.getDimensionMode(), "All")
        state.setDimensionMode("2D")
        self.assertEqual(state.getDimensionMode(), "2D")

    def test_only_the_dimensions_the_analysis_has_can_be_picked(self):
        """
        Two tetrahedra with their skin: the analysis solves the volumes and
        nothing else, so 3D is the only dimension there is to pick out of it.
        """
        self._add_meshed_mesh()
        self.assertEqual(_enabled_dimensions(self.settings.widget.Dimension), ["All", "3D"])

    def test_the_construction_elements_open_up_the_other_dimensions(self):
        """The skin triangles are 2D, and taking them in is what says so."""
        self._add_meshed_mesh()
        self.settings.widget.Construction.click()
        self.assertTrue(FemGui.getAnalysisViewState(self.analysis).getShowConstruction())
        self.assertEqual(_enabled_dimensions(self.settings.widget.Dimension), ["All", "3D", "2D"])

    def test_the_count_says_how_much_of_the_mesh_the_analysis_solves(self):
        """
        The number nobody has to read anything to notice: two of ten, closing
        to ten of ten the moment the construction elements are taken in.
        """
        self._add_meshed_mesh()
        self.assertEqual(self.settings.widget.ElementCount.text(), "2 / 10")
        self.settings.widget.Construction.click()
        self.assertEqual(self.settings.widget.ElementCount.text(), "10 / 10")

    def test_the_count_follows_the_dimension_that_is_picked(self):
        self._add_meshed_mesh()
        self.settings.widget.Construction.click()
        FemGui.getAnalysisViewState(self.analysis).setDimensionMode("2D")
        self.assertEqual(self.settings.widget.ElementCount.text(), "8 / 10")

    def test_dropping_the_construction_elements_leaves_no_empty_view_behind(self):
        """
        2D is the construction elements here, and switching them off greys the
        entry out, which is no way back out of an empty view. So the mode goes
        back to showing everything the analysis has.
        """
        self._add_meshed_mesh()
        state = FemGui.getAnalysisViewState(self.analysis)
        self.settings.widget.Construction.click()
        state.setDimensionMode("2D")
        self.settings.widget.Construction.click()
        self.assertFalse(state.getShowConstruction())
        self.assertEqual(state.getDimensionMode(), "All")

    def test_a_dimension_the_analysis_does_have_survives_the_switch(self):
        self._add_meshed_mesh()
        state = FemGui.getAnalysisViewState(self.analysis)
        self.settings.widget.Construction.click()
        state.setDimensionMode("3D")
        self.settings.widget.Construction.click()
        self.assertEqual(state.getDimensionMode(), "3D")

    def test_only_a_mesh_has_construction_elements(self):
        """The faces of a solid are the solid, not scaffolding around it."""
        self._add_meshed_mesh()
        state = FemGui.getAnalysisViewState(self.analysis)
        self.assertTrue(self.settings.widget.Construction.isEnabled())
        state.setActiveStage("Geometry")
        self.assertFalse(self.settings.widget.Construction.isEnabled())
        self.assertEqual(self.settings.widget.ElementCount.text(), "")

    def test_nothing_drawn_means_nothing_to_describe(self):
        """
        With neither stage lit there is no content, so the controls that
        describe it go with it. The scene settings stay, they still apply to
        whatever results are on screen.
        """
        self._add_meshed_mesh()
        FemGui.getAnalysisViewState(self.analysis).setActiveStage(view_panel._NO_STAGE)
        self.assertFalse(self.settings.widget.Dimension.isEnabled())
        self.assertFalse(self.settings.widget.Construction.isEnabled())
        self.assertFalse(self.explorer._color_mode.isEnabled())
        self.assertTrue(self.settings.widget.ViewMode.isEnabled())
        self.assertTrue(self.settings.widget.Overlay.isEnabled())
        self.assertTrue(self.settings.widget.ClipButton.isEnabled())

    def test_a_toplevel_the_mesh_came_up_short_on_says_what_it_reached(self):
        """
        The mesher did not fail, it came up one dimension short, and the
        analysis runs on what it did reach.
        """
        node = view_panel.ElementNode("Solid1", dim_badge=3, mesh_achieved=2)
        self.assertEqual(node.display_name(), "Solid1 [3D, meshed 2D]")
        self.assertEqual(
            view_panel.ElementNode("Solid1", dim_badge=3).display_name(), "Solid1 [3D]"
        )

    def test_the_dimension_a_toplevel_reached_reaches_the_panel(self):
        """The tree reads the achieved dimension off the view state by name."""
        self._add_meshed_mesh()
        under = FemGui.getAnalysisViewState(self.analysis).getUnderAchievedElements()
        self.assertIsInstance(under, dict)
        for achieved in under.values():
            self.assertIsInstance(achieved, int)

    def test_a_colouring_of_mesh_elements_is_greyed_out_off_the_mesh(self):
        """
        The view state pushes CellType back to Subelement outside the mesh
        stage, and a combo that springs back when let go is a riddle.
        """
        self._add_mesh()
        combo = self.explorer._color_mode
        model = combo.model()
        cell_type = combo.findText("CellType")
        state = FemGui.getAnalysisViewState(self.analysis)

        state.setActiveStage("Geometry")
        self.assertFalse(model.item(cell_type).isEnabled())
        state.setActiveStage("Mesh")
        self.assertTrue(model.item(cell_type).isEnabled())

    # -- placed instances in the tree ---------------------------------------

    def _import_another_analysis(self, name="Leg1", analysis=None):
        """A second analysis, placed in the one the panel describes."""
        from femtools import importtools

        analysis = analysis if analysis is not None else self.analysis

        source = self.document.addObject("Part::Feature", "LegPart")
        source.Shape = Part.makeBox(5, 5, 5)
        leg = ObjectsFem.makeAnalysis(self.document, "LegAnalysis")
        leg_geom = ObjectsFem.makeGeometryGroup(self.document, "LegGeometry")
        leg.addObject(leg_geom)
        leg_step = ObjectsFem.makeGeometryImport(self.document)
        leg_step.Import = [source]
        leg_geom.Group = [leg_step]
        ObjectsFem.makeMeshShapeGroup(self.document, geometry=leg_geom, analysis=leg)
        self.document.recompute()

        imp = ObjectsFem.makeAnalysisImport(self.document, name)
        imp.Analysis = leg
        importtools.wire_import(analysis, imp)
        self.document.recompute()
        return imp

    def test_an_import_added_later_shows_up_in_the_tree(self):
        """
        An import lands in a container group inside the analysis, so neither it
        nor the analysis' own Group property announces it. Without watching the
        container the tree keeps describing the analysis as it was.
        """
        self.assertNotIn("Leg1.Solid1", _row_names(self.explorer._model))
        imp = self._import_another_analysis()
        names = _row_names(self.explorer._model)
        self.assertIn("Leg1.Solid1", names, "the placed analysis brings elements of its own")

        # And the row is gone again once the instance is
        self.document.removeObject(imp.Name)
        self.document.recompute()
        self.assertNotIn("Leg1.Solid1", _row_names(self.explorer._model))

    def test_suppressing_a_component_of_an_import_updates_the_tree(self):
        imp = self._import_another_analysis()
        self.assertIn("Leg1.Solid1", _row_names(self.explorer._model))
        imp.SuppressedComponents = [1]
        self.document.recompute()
        self.assertNotIn("Leg1.Solid1", _row_names(self.explorer._model))

    def test_an_import_makes_the_mesh_stage_reachable(self):
        """
        An analysis that only places others has no mesh of its own, and the
        meshes it solves with come from its imports.
        """
        self.assertFalse(self.settings.widget.MeshButton.isEnabled())
        self._import_another_analysis()
        self.assertTrue(self.settings.widget.MeshButton.isEnabled())

    def _assembly_analysis(self):
        """An analysis that has nothing of its own but a placed instance."""
        assembly = ObjectsFem.makeAnalysis(self.document, "Assembly")
        FemGui.setActiveAnalysis(assembly)
        imp = self._import_another_analysis(name="Placed1", analysis=assembly)
        self.explorer.setup_analysis()
        self.settings.setup_analysis()
        return imp

    def test_an_analysis_of_nothing_but_instances_lists_them(self):
        """
        What such an analysis is made of is entirely what it places, so a tree
        that only describes geometry of its own has nothing to say about it.
        """
        self._assembly_analysis()
        self.assertIn("Placed1.Solid1", _row_names(self.explorer._model))

    def test_both_stages_are_reachable_with_nothing_but_instances(self):
        """
        Both stages draw what the instances draw, and the way back from the
        mesh must not depend on geometry the analysis does not have.
        """
        self._assembly_analysis()
        self.assertTrue(self.settings.widget.MeshButton.isEnabled())
        self.assertTrue(self.settings.widget.GeometryButton.isEnabled())

    # -- the clipping list ---------------------------------------------------

    def test_the_empty_clipping_list_says_it_is_empty(self):
        """
        A frame around a lone button reads as a bug. One dimmed line turns it
        into a list that happens to have nothing in it yet.
        """
        self.assertTrue(self.settings.widget.ClipHint.isVisible())
        self.settings.widget.ClipButton.click()
        self.assertEqual(len(self.settings.clip_widgets()), 1)
        self.assertFalse(self.settings.widget.ClipHint.isVisible())

    def test_the_hint_comes_back_when_the_last_plane_goes(self):
        self.settings.widget.ClipButton.click()
        row = self.settings.clip_widgets()[0]
        row.widget.DeleteButton.click()
        self.assertEqual(self.settings.clip_widgets(), [])
        self.assertTrue(self.settings.widget.ClipHint.isVisible())

    def test_a_clip_row_carries_what_it_cuts(self):
        """
        Planes are called 1, 2, 3, which tells the rows apart and nothing else.
        What distinguishes them at a glance is how far they reach.
        """
        imp = self._import_another_analysis()
        self.settings.widget.ClipButton.click()
        row = self.settings.clip_widgets()[0]
        self.assertEqual(row.widget.ClipButton.text(), row.name)

        row.handle.setScope(imp.Name)
        row.setup_label()
        self.assertEqual(row.widget.ClipButton.text(), f"{row.name} · {imp.Name}")

    def test_the_clip_normal_reaches_an_axis_without_being_typed(self):
        """
        Six of the directions a clipping plane is ever given are the axes, and
        typing three numbers to reach one is three chances to miss.
        """
        self.settings.widget.ClipButton.click()
        editor = self.settings.clip_widgets()[0].editor
        handle = editor.handle
        origin = handle.getOrigin()

        # The normal comes back off the single precision dragger, so it is the
        # direction that is asserted rather than the digits.
        def assert_normal(expected):
            for got, want in zip(handle.getNormal(), expected):
                self.assertAlmostEqual(got, want, places=5)

        editor.widget.NormalYButton.click()
        assert_normal([0.0, 1.0, 0.0])
        self.assertEqual(list(handle.getOrigin()), list(origin), "the plane stays where it is")

        editor.widget.FlipButton.click()
        assert_normal([0.0, -1.0, 0.0])

    # -- planes belong to the analysis, rows only reach them ------------------

    def test_the_planes_outlive_the_panel_that_made_them(self):
        """
        Closing the panel, or leaving the workbench, is not a request to stop
        clipping: the analysis is expected to come back cut the way it was
        left. So the rows go and the planes stay, and reopening builds the
        rows again rather than a second set of planes.
        """
        self.settings.widget.ClipButton.click()
        state = FemGui.getAnalysisViewState(self.analysis)
        planes = dict(state.getClipPlanes())
        self.assertEqual(len(planes), 1)

        view_panel.unsetup_visualization_panel()
        _flush_deletions()
        self.assertEqual(dict(state.getClipPlanes()), planes, "the panel took the plane with it")

        view_panel.setup_visualization_panel()
        dock = FreeCADGui.getMainWindow().findChild(QtGui.QDockWidget, "FEMView")
        self.explorer = dock.widget()._explorer
        self.settings = dock.widget()._settings
        self.assertEqual([row.name for row in self.settings.clip_widgets()], list(planes))
        self.assertEqual(dict(state.getClipPlanes()), planes, "and no second plane came of it")

    def test_a_plane_added_from_outside_grows_its_own_row(self):
        """
        What the toolbar command does, and all it has to do: put a plane in
        the view state. The row, the dragger and the cut follow from there, so
        nothing outside the panel needs to know the panel exists.
        """
        self.assertEqual(self.settings.clip_widgets(), [])
        FemGui.addClipPlane(self.analysis)

        rows = self.settings.clip_widgets()
        self.assertEqual(len(rows), 1)
        self.assertIn(rows[0].name, FemGui.getAnalysisViewState(self.analysis).getClipPlanes())
        self.assertFalse(self.settings.widget.ClipHint.isVisible())

    def test_a_plane_switched_off_keeps_its_place(self):
        """
        Off is not gone. The row stays, so switching back on picks the plane
        up where it was left rather than back in the middle of the model.
        """
        self.settings.widget.ClipButton.click()
        row = self.settings.clip_widgets()[0]
        row.handle.setPlane(FreeCAD.Vector(5, 0, 0), FreeCAD.Vector(1, 0, 0))

        row.widget.ClipButton.click()
        self.assertFalse(row.handle.isActive())
        self.assertEqual(
            [widget.name for widget in self.settings.clip_widgets()],
            [row.name],
            "a plane that cuts nothing is still a plane",
        )

        row.widget.ClipButton.click()
        self.assertTrue(row.handle.isActive())
        self.assertAlmostEqual(row.handle.getOrigin().x, 5.0, places=4)

    def test_the_command_cuts_along_the_face_it_was_given(self):
        """
        The old command read a picked face the same way, and the direction is
        the part worth pinning down: a face normal points out of the material,
        so a plane keeping that half would keep everything but the solid.
        """
        from femcommands import commands as femcommands

        source = self.document.getObject("Source")
        face = source.Shape.Faces[0]
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.document.Name, source.Name, "Face1")

        femcommands._ClippingPlaneAdd().Activated()

        planes = FemGui.getAnalysisViewState(self.analysis).getClipPlanes()
        self.assertEqual(len(planes), 1)
        origin, direction, scope = next(iter(planes.values()))

        centre = face.CenterOfMass
        u, v = face.Surface.parameter(centre)
        outward = face.normalAt(u, v).negative()
        for got, want in zip(origin, centre):
            self.assertAlmostEqual(got, want, places=5)
        for got, want in zip(direction, outward):
            self.assertAlmostEqual(got, want, places=5)
        self.assertEqual(scope, "", "a picked face says where to cut, not what to cut")

    def test_the_command_clears_every_plane_at_once(self):
        """
        One change of the view state rather than one per plane, so the
        geometry and the mesh are recomputed once between them.
        """
        from femcommands import commands as femcommands

        FemGui.addClipPlane(self.analysis)
        FemGui.addClipPlane(self.analysis)
        self.assertEqual(len(self.settings.clip_widgets()), 2)

        femcommands._ClippingPlaneRemoveAll().Activated()
        self.assertEqual(dict(FemGui.getAnalysisViewState(self.analysis).getClipPlanes()), {})
        self.assertEqual(self.settings.clip_widgets(), [])
        self.assertTrue(self.settings.widget.ClipHint.isVisible())

    # -- the entry point the user takes -------------------------------------

    def test_double_click_edit_moves_the_tree_and_the_stage(self):
        """
        Once more over the document observer, so the wiring from the edit
        session to the panels is covered and not only the slots themselves.
        """
        self._add_mesh()
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setActiveStage("Mesh")
        try:
            FreeCADGui.ActiveDocument.setEdit(self.part.Name)
            self.assertIs(self.explorer._tree_object(), self.imp)
            self.assertEqual(state.getActiveStage(), "Geometry")
        finally:
            FreeCADGui.ActiveDocument.resetEdit()
        self.assertIs(self.explorer._tree_object(), self.group)
        self.assertEqual(state.getActiveStage(), "Mesh")


class _CellTypeState:
    """
    Stand-in for the view state, handing out cell-type categories.

    The real ones come off the mesh grid a view provider registers, which needs
    the whole VTK pipeline on screen; what is asked here is what the tree makes
    of them, and that is answered without a mesh in sight.
    """

    def __init__(self, categories):
        self._categories = categories
        self.hidden_types = set()
        self.show_construction = False

    def getColorMode(self):
        return "CellType"

    def getCategories(self):
        return self._categories

    def getUnderAchievedElements(self):
        return {}

    def isCellTypeHidden(self, key):
        return key in self.hidden_types

    def setCellTypeHidden(self, key, hidden):
        self.hidden_types.add(key) if hidden else self.hidden_types.discard(key)

    def getShowConstruction(self):
        return self.show_construction

    def setShowConstruction(self, value):
        self.show_construction = bool(value)

    def isElementHidden(self, name):
        return False

    def beginUpdate(self):
        pass

    def endUpdate(self):
        pass


class _NamedObject:
    def __init__(self, label):
        self.Label = label


def _cell_type(label, construction, count, key=None):
    return {
        "key": key or (f"{label}:construction" if construction else label),
        "label": label,
        "color": (0.5, 0.5, 0.5, 1.0),
        "construction": construction,
        "count": count,
    }


class TestCellTypeTreeGui(unittest.TestCase):
    """The element types of a mesh, and which side of the analysis each is on."""

    fcc_print("import TestCellTypeTreeGui")

    def _tree(self, categories):
        state = _CellTypeState(categories)
        model = view_panel.GeometryModel()
        model.set_context(_NamedObject("Mesh"), state)
        return model, state

    def _both_sides(self):
        """
        A solid meshed with tetrahedra and skinned with triangles, plus a shell
        of triangles of its own: the one case where a type is on both sides.
        """
        return self._tree(
            [
                _cell_type("tetra4", False, 2),
                _cell_type("tria3", False, 1),
                _cell_type("tria3", True, 7),
            ]
        )

    def test_the_element_types_say_which_side_of_the_analysis_they_are_on(self):
        """
        Two heads, and every type under the one that says what it is for. The
        tetrahedra are the analysis, the triangles skinning them are what the
        mesher needed to get there.
        """
        model, _ = self._tree([_cell_type("tetra4", False, 2), _cell_type("tria3", True, 8)])
        self.assertEqual(
            _cell_type_groups(model),
            {"Analysis elements": [("tetra4", 2)], "Construction elements": [("tria3", 8)]},
        )

    def test_a_type_that_is_both_is_listed_on_both_sides(self):
        """
        The triangles of a shell and the triangles skinning a solid are all
        tria3, and which of the two a row means is not something the type name
        can say. So it is offered twice, once under each head.
        """
        model, _ = self._both_sides()
        groups = _cell_type_groups(model)
        self.assertEqual(groups["Analysis elements"], [("tetra4", 2), ("tria3", 1)])
        self.assertEqual(groups["Construction elements"], [("tria3", 7)])

    def test_hiding_the_skin_triangles_leaves_the_shell_triangles_alone(self):
        """Two rows of one type are two rows, or splitting them was pointless."""
        model, state = self._both_sides()
        shell = model.get_item(_cell_type_index(model, "Analysis elements", "tria3"))
        skin = model.get_item(_cell_type_index(model, "Construction elements", "tria3"))
        self.assertNotEqual(shell.category_key, skin.category_key)

        skin.set_visible(False)
        self.assertFalse(skin.visible())
        self.assertTrue(shell.visible())
        self.assertEqual(state.hidden_types, {"tria3:construction"})

    def test_the_construction_head_is_the_construction_setting(self):
        """
        One state, two ways in. The tree is otherwise no place to filter the
        view from, and a head that only looked like the panel checkbox would be
        a second switch to keep in step with the first.
        """
        model, state = self._both_sides()
        head = _group_index(model, "Construction elements")
        self.assertFalse(model.get_item(head).visible())

        model.setData(
            head.sibling(head.row(), 2), view_panel.Qt.Checked, view_panel.Qt.CheckStateRole
        )
        self.assertTrue(state.getShowConstruction())
        self.assertTrue(model.get_item(head).visible())

    def test_the_construction_head_leaves_the_hides_below_it_alone(self):
        """Turning the group off and on again gives it back the way it was."""
        model, state = self._both_sides()
        skin = model.get_item(_cell_type_index(model, "Construction elements", "tria3"))
        state.setShowConstruction(True)
        skin.set_visible(False)

        head = model.get_item(_group_index(model, "Construction elements"))
        head.set_visible(False)
        head.set_visible(True)
        self.assertEqual(state.hidden_types, {"tria3:construction"})

    def test_a_construction_type_cannot_be_ticked_while_the_group_is_off(self):
        """
        None of them is drawn while the head is off, whatever its own box says,
        and a tick that changes nothing is worse than one that cannot be given.
        """
        model, state = self._both_sides()

        def checkable():
            index = _cell_type_index(model, "Construction elements", "tria3")
            return bool(
                model.flags(index.sibling(index.row(), 2)) & view_panel.Qt.ItemIsUserCheckable
            )

        self.assertFalse(checkable())
        state.setShowConstruction(True)
        self.assertTrue(checkable())

    def test_an_analysis_type_is_never_greyed_out(self):
        """The construction setting has no say over the elements that are solved."""
        model, _ = self._both_sides()
        index = _cell_type_index(model, "Analysis elements", "tria3")
        self.assertTrue(model.get_item(index).enabled())

    def test_the_types_stay_put_when_the_construction_elements_go(self):
        """
        The tree says what the mesh is made of, not what is on screen: no other
        setting shortens it, and this one having done would have been the odd
        one out.
        """
        model, state = self._both_sides()
        before = _cell_type_groups(model)
        state.setShowConstruction(True)
        model.update_model()
        self.assertEqual(_cell_type_groups(model), before)

    def test_the_count_rides_behind_the_element_type(self):
        """Same badge the dimension of a toplevel gets, for the same reason."""
        node = view_panel.ElementNode("tetra4", count_badge=1234)
        self.assertEqual(node.display_name(), "tetra4 [1\u202f234]")
