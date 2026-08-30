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

"""Gui unit tests for the component picker of the mesh task panels.

The components of a geometry are a closed set that the mesh objects of a
group divide between them, so the picker is a checklist and not a collected
list of picks: what is left out matters as much as what is taken, and a
component a sibling meshes can only be had by taking it over.

Clicking in the 3D view is an input method on top of that, and the tests
below drive it through the selection singleton so that the gate and the
observer are exercised the way the view does it.
"""

__title__ = "FEM component selection Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

from PySide import QtCore
from PySide import QtGui

import FreeCAD
import FreeCADGui
import ObjectsFem
import Part

from femguiutils.component_selection import ComponentSelection
from femmesh import meshcomponents
from femtest.app.support_utils import fcc_print


class TestComponentSelectionGui(unittest.TestCase):
    fcc_print("import TestComponentSelectionGui")

    def setUp(self):
        self.document = FreeCAD.newDocument("ComponentSelection")
        self.analysis = ObjectsFem.makeAnalysis(self.document)

        # Two boxes far enough apart to stay separate, plus a loose plane: a
        # component whose toplevel element is a face and not a solid is what
        # tells a pick mapped through the owning solid from one mapped by the
        # element itself.
        source = self.document.addObject("Part::Feature", "Source")
        source.Shape = Part.makeCompound(
            [
                Part.makeBox(10, 10, 10),
                Part.makeBox(10, 10, 10, FreeCAD.Vector(30, 0, 0)),
                Part.makePlane(10, 10, FreeCAD.Vector(60, 0, 0)),
            ]
        )
        self.source = source

        self.geometry = ObjectsFem.makeGeometryGroup(self.document)
        step = ObjectsFem.makeGeometryImport(self.document)
        step.Import = [source]
        self.geometry.Group = [step]
        self.analysis.addObject(self.geometry)

        self.group = ObjectsFem.makeMeshShapeGroup(
            self.document, geometry=self.geometry, analysis=self.analysis
        )
        self.document.recompute()
        self.assertEqual(self.geometry.getComponentCount(), 3)

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        FreeCAD.closeDocument(self.document.Name)

    # -- fixtures ------------------------------------------------------------

    def _mesh(self, name="Mesh"):
        obj = ObjectsFem.makeMeshGmsh(self.document, name)
        self.group.addObject(obj)
        self.document.recompute()
        return obj

    def _widget(self, obj=None):
        widget = ComponentSelection(obj if obj is not None else self._mesh())
        self.addCleanup(widget.finish_selection)
        return widget

    def _rows(self, widget):
        return [
            widget.tree.topLevelItem(row) for row in range(widget.tree.topLevelItemCount())
        ]

    def _row_of(self, widget, index):
        for item in self._rows(widget):
            if item.data(0, QtCore.Qt.UserRole) == index:
                return item
        self.fail(f"no row for component {index}")

    def _plane_component(self):
        """The component whose toplevel elements are all faces."""
        for index in range(self.geometry.getComponentCount()):
            tops = self.geometry.getToplevelElements(index)
            if all(name.startswith("Face") for name in tops):
                return index + 1
        self.fail("the geometry has no loose face")

    def _solid_component(self):
        for index in range(self.geometry.getComponentCount()):
            tops = self.geometry.getToplevelElements(index)
            if any(name.startswith("Solid") for name in tops):
                return index + 1
        self.fail("the geometry has no solid")

    def _click(self, widget, element):
        """A pick in the 3D view, through the gate and the observer."""
        FreeCADGui.Selection.addSelection(self.document.Name, self.geometry.Name, element)

    # -- the list ------------------------------------------------------------

    def test_the_list_shows_every_component_of_the_geometry(self):
        widget = self._widget()
        self.assertEqual(len(self._rows(widget)), 3)
        for index, item in enumerate(self._rows(widget), start=1):
            self.assertEqual(item.data(0, QtCore.Qt.UserRole), index)
            self.assertIn(meshcomponents.component_name(index), item.text(0))

    def test_a_row_carries_the_elements_the_component_is_made_of(self):
        """
        What "Component2" stands for is not something a number can say, so the
        entities it covers hang under it.
        """
        widget = self._widget()
        for index, item in enumerate(self._rows(widget), start=1):
            expected = list(self.geometry.getToplevelElements(index - 1))
            drawn = [item.child(row).text(0) for row in range(item.childCount())]
            self.assertEqual(drawn, expected)

    def test_ticking_a_row_writes_the_property(self):
        widget = self._widget()
        item = self._row_of(widget, 2)
        item.setCheckState(0, QtCore.Qt.Checked)

        self.assertEqual(meshcomponents.selected_components(widget.obj), [2])
        self.assertIs(widget.obj.Components[0], self.geometry)

    def test_unticking_the_last_row_leaves_nothing_to_mesh(self):
        widget = self._widget()
        self._row_of(widget, 1).setCheckState(0, QtCore.Qt.Checked)
        self._row_of(widget, 1).setCheckState(0, QtCore.Qt.Unchecked)

        self.assertEqual(meshcomponents.selected_components(widget.obj), [])
        self.assertTrue(widget.hint(), "an empty selection has to say what is missing")

    def test_all_components_keeps_following_the_geometry(self):
        """
        "All" is a mode and not a full checklist: it has no components spelled
        out, which is what makes one added later fall to this mesh object too.
        """
        widget = self._widget()
        widget.all_check.setChecked(True)

        self.assertTrue(meshcomponents.meshes_all(widget.obj))
        self.assertEqual(meshcomponents.selected_components(widget.obj), [1, 2, 3])
        self.assertFalse(widget.tree.isEnabled(), "there is nothing left to pick under all")
        self.assertFalse(widget.pick_btn.isEnabled())

    def test_leaving_all_keeps_the_components_spelled_out(self):
        widget = self._widget()
        widget.all_check.setChecked(True)
        widget.all_check.setChecked(False)

        self.assertFalse(meshcomponents.meshes_all(widget.obj))
        self.assertEqual(meshcomponents.selected_components(widget.obj), [1, 2, 3])
        self.assertTrue(widget.tree.isEnabled())

    # -- what a sibling holds ------------------------------------------------

    def test_a_component_a_sibling_meshes_is_locked_and_names_its_owner(self):
        other = self._mesh("Other")
        meshcomponents.assign_components(other, self.geometry, [2])
        widget = self._widget()

        item = self._row_of(widget, 2)
        self.assertFalse(item.flags() & QtCore.Qt.ItemIsUserCheckable)
        self.assertIn(other.Label, item.text(0))
        self.assertIn(other.Label, item.toolTip(0))

    def test_all_components_is_off_the_table_while_a_sibling_holds_one(self):
        other = self._mesh("Other")
        meshcomponents.assign_components(other, self.geometry, [2])
        widget = self._widget()

        self.assertFalse(widget.all_check.isEnabled())

    def test_taking_a_component_over_leaves_its_owner_without_it(self):
        """
        Two mesh objects meshing the same component would mesh the geometry
        twice over, so gaining one is always the other one losing it.
        """
        other = self._mesh("Other")
        meshcomponents.assign_components(other, self.geometry, [2, 3])
        widget = self._widget()

        meshcomponents.take_over(widget.obj, {2}, widget.owners)
        meshcomponents.assign_components(widget.obj, self.geometry, widget.mine | {2})

        self.assertEqual(meshcomponents.selected_components(widget.obj), [2])
        self.assertEqual(meshcomponents.selected_components(other), [3])

    def test_the_summary_names_the_components_nobody_meshes(self):
        widget = self._widget()
        self._row_of(widget, 1).setCheckState(0, QtCore.Qt.Checked)

        text = widget.summary.text()
        self.assertIn(meshcomponents.component_name(2), text)
        self.assertIn(meshcomponents.component_name(3), text)
        self.assertNotIn(meshcomponents.component_name(1), text)

    def test_a_fully_covered_geometry_says_so(self):
        widget = self._widget()
        widget.all_check.setChecked(True)

        for index in (1, 2, 3):
            self.assertNotIn(meshcomponents.component_name(index), widget.summary.text())

    # -- picking in the 3D view ----------------------------------------------

    def test_a_click_on_a_solid_ticks_its_component(self):
        widget = self._widget()
        widget.pick_btn.setChecked(True)
        index = self._solid_component()
        self._click(widget, self.geometry.getToplevelElements(index - 1)[0])

        self.assertEqual(meshcomponents.selected_components(widget.obj), [index])

    def test_a_click_on_a_face_of_a_solid_finds_the_component_behind_it(self):
        """
        A click reports the face under the pointer, which is no toplevel
        element of anything. The component still has to be found.
        """
        widget = self._widget()
        widget.pick_btn.setChecked(True)
        index = self._solid_component()
        solid = self.geometry.getToplevelElements(index - 1)[0]
        face = sorted(meshcomponents.component_element_names(self.geometry, index))
        face = next(name for name in face if name.startswith("Face"))
        self.assertNotEqual(face, solid)
        self._click(widget, face)

        self.assertEqual(meshcomponents.selected_components(widget.obj), [index])

    def test_a_click_on_a_loose_face_finds_its_own_component(self):
        """
        The plane bounds no solid, so mapping a pick through the owning solid
        finds nothing: the element itself is the toplevel one here.
        """
        widget = self._widget()
        widget.pick_btn.setChecked(True)
        index = self._plane_component()
        self._click(widget, self.geometry.getToplevelElements(index - 1)[0])

        self.assertEqual(meshcomponents.selected_components(widget.obj), [index])

    def test_clicking_the_same_component_again_takes_it_back_out(self):
        widget = self._widget()
        widget.pick_btn.setChecked(True)
        index = self._solid_component()
        element = self.geometry.getToplevelElements(index - 1)[0]
        self._click(widget, element)
        self._click(widget, element)

        self.assertEqual(meshcomponents.selected_components(widget.obj), [])

    def test_a_pick_outside_the_geometry_never_arrives(self):
        """
        The part the analysis was built from carries a Solid1 of its own, and
        it is no component of anything.
        """
        widget = self._widget()
        widget.pick_btn.setChecked(True)
        FreeCADGui.Selection.addSelection(self.document.Name, self.source.Name, "Solid1")

        self.assertEqual(meshcomponents.selected_components(widget.obj), [])
        self.assertFalse(widget.picker.allow(self.document, self.source, "Solid1"))
        self.assertTrue(widget.picker.notAllowedReason)

    def test_a_component_a_sibling_holds_does_not_answer_a_click(self):
        other = self._mesh("Other")
        index = self._solid_component()
        meshcomponents.assign_components(other, self.geometry, [index])
        widget = self._widget()
        widget.pick_btn.setChecked(True)
        self._click(widget, self.geometry.getToplevelElements(index - 1)[0])

        self.assertEqual(meshcomponents.selected_components(widget.obj), [])
        self.assertEqual(meshcomponents.selected_components(other), [index])

    def test_a_pick_puts_its_row_on_screen(self):
        widget = self._widget()
        widget.pick_btn.setChecked(True)
        index = self._solid_component()
        self._click(widget, self.geometry.getToplevelElements(index - 1)[0])

        selected = [item.data(0, QtCore.Qt.UserRole) for item in widget.tree.selectedItems()]
        self.assertEqual(selected, [index])

    # -- who holds the 3D view -----------------------------------------------

    def test_the_gate_only_stands_while_the_picker_is_on(self):
        widget = self._widget()
        self.assertFalse(widget.picker.active)

        widget.pick_btn.setChecked(True)
        self.assertTrue(widget.picker.active)

        widget.pick_btn.setChecked(False)
        self.assertFalse(widget.picker.active)

    def test_closing_the_panel_hands_the_3d_view_back(self):
        widget = self._widget()
        widget.pick_btn.setChecked(True)
        widget.finish_selection()

        self.assertFalse(widget.picker.active)
        self.assertFalse(widget.pick_btn.isChecked())
        # Nothing refuses picks any more, whatever they land on
        FreeCADGui.Selection.addSelection(self.document.Name, self.source.Name, "Solid1")
        self.assertTrue(FreeCADGui.Selection.getSelection())

    # -- inside the mesh task panels -----------------------------------------

    def _open_panel(self, obj):
        FreeCADGui.ActiveDocument.setEdit(obj.Name)
        self.addCleanup(FreeCADGui.Control.closeDialog)
        return [
            frame
            for frame in FreeCADGui.getMainWindow().findChildren(
                QtGui.QFrame, "FemComponentSelection"
            )
            if frame.isVisible()
        ]

    def test_the_gmsh_panel_carries_the_checklist(self):
        mesh = self._mesh("GmshMesh")
        meshcomponents.assign_unclaimed(mesh)
        frames = self._open_panel(mesh)

        self.assertEqual(len(frames), 1, "the Gmsh panel offers one component checklist")
        self.assertEqual(frames[0].tree.topLevelItemCount(), 3)

    def test_the_netgen_panel_carries_the_same_checklist(self):
        mesh = ObjectsFem.makeMeshNetgen(self.document, "NetgenMesh")
        self.group.addObject(mesh)
        self.document.recompute()
        meshcomponents.assign_unclaimed(mesh)
        frames = self._open_panel(mesh)

        self.assertEqual(len(frames), 1, "the Netgen panel offers one component checklist")
        self.assertEqual(frames[0].tree.topLevelItemCount(), 3)

    def test_a_legacy_mesh_object_gets_no_checklist(self):
        """
        A mesh object that links a Part feature meshes it whole, so there is
        no component to pick and nothing to show.
        """
        mesh = ObjectsFem.makeMeshGmsh(self.document, "LegacyMesh")
        mesh.Shape = self.source
        self.document.recompute()

        self.assertIsNone(meshcomponents.geometry_of(mesh))
        self.assertFalse(self._open_panel(mesh))

    def test_highlighting_a_row_does_not_read_as_a_pick(self):
        """
        A row puts its elements in the 3D selection, which comes back through
        the observer. Left alone it would undo the tick that caused it.
        """
        widget = self._widget()
        widget.pick_btn.setChecked(True)
        index = self._solid_component()
        self._row_of(widget, index).setCheckState(0, QtCore.Qt.Checked)
        self._row_of(widget, index).setSelected(True)

        self.assertEqual(meshcomponents.selected_components(widget.obj), [index])
