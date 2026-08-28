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
