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

"""Gui unit tests for picking geometry references in an analysis: they go onto
the geometry the analysis builds, and nowhere else."""

__title__ = "FEM reference selection Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import FreeCADGui
import FemGui
import Part

from PySide import QtCore
from PySide import QtGui

import ObjectsFem

from femguiutils import selection_coordinator
from femguiutils import selection_handoff
from femguiutils import selection_slots

from femtest.app.support_utils import fcc_print


class _NoMessageBox:
    """Answer the message boxes of a picking widget instead of blocking on them."""

    def __init__(self):
        self.messages = []

    def __enter__(self):
        self._critical = QtGui.QMessageBox.critical
        QtGui.QMessageBox.critical = lambda parent, title, text, *a, **kw: self.messages.append(
            text
        )
        return self

    def __exit__(self, *args):
        QtGui.QMessageBox.critical = self._critical


class TestReferenceSelectionGui(unittest.TestCase):
    fcc_print("import TestReferenceSelectionGui")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)
        self.source = self.document.addObject("Part::Feature", "Source")
        self.source.Shape = Part.makeCompound(
            [
                Part.makeBox(20, 10, 10),
                Part.makeBox(10, 10, 10, FreeCAD.Vector(30, 0, 0)),
            ]
        )
        self.analysis = ObjectsFem.makeAnalysis(self.document)
        self.group = ObjectsFem.makeGeometryGroup(self.document)
        imp = ObjectsFem.makeGeometryImport(self.document)
        imp.Import = [self.source]
        self.group.Group = [imp]
        self.analysis.addObject(self.group)
        self.document.recompute()
        FemGui.setActiveAnalysis(self.analysis)
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.finish_selection()
        self.widgets = []
        selection_handoff.clear()
        FreeCADGui.Selection.clearSelection()
        if FreeCADGui.ActiveDocument and FreeCADGui.ActiveDocument.getInEdit():
            FreeCADGui.ActiveDocument.resetEdit()
        FreeCAD.closeDocument(self.document.Name)

    # -- helpers ------------------------------------------------------------

    def _picker(self, types, solid=False):
        """A reference picker listening to the 3D view, as a panel puts it up."""
        widget = selection_slots.for_references(
            None,
            types,
            homogeneous=True,
            promotion_latched=solid,
            property=None,
        )
        self.widgets.append(widget)
        widget.coordinator.install()
        widget.arm("References")
        return widget

    def _pick(self, obj, sub):
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.document.Name, obj.Name, sub)

    def _references(self, widget):
        return [(ref.Name, element) for ref, element in widget.references]

    def _open_constraint(self, constraint):
        """Open the panel of a constraint and press its reference add button."""
        FreeCADGui.ActiveDocument.setEdit(constraint.Name)
        buttons = [
            button
            for button in FreeCADGui.getMainWindow().findChildren(
                QtGui.QToolButton, "FemReferenceArm"
            )
            if button.isVisible()
        ]
        self.assertTrue(buttons, "the constraint panel offers a button to arm a slot")
        buttons[0].setChecked(True)

    # -- picking with the Python widget --------------------------------------

    def test_a_pick_on_the_analysis_geometry_is_taken(self):
        widget = self._picker(["Face"])
        self._pick(self.group, "Face3")
        self.assertEqual(self._references(widget), [(self.group.Name, "Face3")])

    def test_a_face_pick_reaches_the_solid_it_bounds(self):
        """Solid mode, which materials and body loads start in."""
        widget = self._picker(["Solid", "Face"], solid=True)
        self._pick(self.group, "Face3")
        self.assertEqual(self._references(widget), [(self.group.Name, "Solid1")])

    def test_a_pick_beside_the_analysis_geometry_is_refused(self):
        """
        The part the geometry was built from is still in the document and still
        pickable. Its elements are numbered differently from the ones the mesh
        is made of, so a reference on it would land somewhere else.
        """
        widget = self._picker(["Face"])
        self._pick(self.source, "Face1")
        self.assertEqual(widget.references, [])
        self.assertIn(self.group.Label, widget.slot("References").status.text())

    def test_without_a_geometry_a_part_feature_is_taken(self):
        """Analyses of older documents reference their part features directly."""
        legacy = ObjectsFem.makeAnalysis(self.document, "Legacy")
        self.document.recompute()
        FemGui.setActiveAnalysis(legacy)

        widget = self._picker(["Face"])
        self._pick(self.source, "Face1")
        self.assertEqual(self._references(widget), [(self.source.Name, "Face1")])

    # -- picking inside a placed analysis ------------------------------------

    def _placed_side(self):
        """
        The analysis places Side, and Side places Leg: a pick on the leg comes
        down through two instances, the way an assembly of assemblies is built.
        """
        from femtools import importtools

        leg = ObjectsFem.makeAnalysis(self.document, "Leg")
        geometry = ObjectsFem.makeGeometryGroup(self.document, "LegGeometry")
        leg.addObject(geometry)
        part = self.document.addObject("Part::Feature", "LegPart")
        part.Shape = Part.makeBox(10, 10, 10)
        step = ObjectsFem.makeGeometryImport(self.document)
        step.Import = [part]
        geometry.Group = [step]

        side = ObjectsFem.makeAnalysis(self.document, "Side")
        inner = ObjectsFem.makeAnalysisImport(self.document, "Inner")
        inner.Analysis = leg
        importtools.wire_import(side, inner)

        outer = ObjectsFem.makeAnalysisImport(self.document, "Outer")
        outer.Analysis = side
        container = importtools.wire_import(self.analysis, outer)
        self.document.recompute()
        return container, outer, inner

    def test_a_pick_on_a_placed_analysis_is_stored_on_the_instance(self):
        container, outer, _inner = self._placed_side()
        widget = self._picker(["Face"])
        self._pick(self.analysis, f"{container.Name}.{outer.Name}.Face1")
        self.assertEqual(self._references(widget), [(outer.Name, "Face1")])

    def test_a_pick_on_a_nested_instance_keeps_the_way_down_to_it(self):
        """
        Only the outer instance stands where the pick landed — the nested one
        stands in the analysis it was placed into, which may be placed here
        more than once. Stored on the nested instance, the reference names an
        element the analysis never drew, and the row reads as gone.
        """
        container, outer, inner = self._placed_side()
        widget = self._picker(["Face"])
        self._pick(self.analysis, f"{container.Name}.{outer.Name}.{inner.Name}.Face1")

        self.assertEqual(self._references(widget), [(outer.Name, f"{inner.Name}.Face1")])
        self.assertFalse(
            widget.slot("References").list.topLevelItem(0).data(0, selection_slots.STALE_ROLE),
            "the element the pick landed on is one the instance has",
        )

    def test_a_nested_pick_made_before_the_panel_is_handed_over_whole(self):
        """The create-command stash goes the same way as a pick in the panel."""
        container, outer, inner = self._placed_side()
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(
            self.document.Name,
            self.analysis.Name,
            f"{container.Name}.{outer.Name}.{inner.Name}.Face1",
        )
        selection_handoff.stash_for(constraint.Name)

        widget = selection_slots.for_references(constraint, ["Face"])
        self.widgets.append(widget)
        self.assertEqual(self._references(widget), [(outer.Name, f"{inner.Name}.Face1")])

    # -- picking with a C++ constraint panel ---------------------------------

    def test_a_constraint_panel_takes_the_analysis_geometry(self):
        """
        The panels rejected everything that was not a Part::Feature, which the
        geometry of an analysis is not, with "Selected object is not a part".
        """
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        self._open_constraint(constraint)
        self._pick(self.group, "Face3")

        self.assertEqual(constraint.References, [(self.group, ("Face3",))])

    def test_an_open_constraint_marks_its_references_on_the_geometry(self):
        """
        The geometry draws its own shape and carries none of the per element
        colours a part feature would be highlighted through, so the references
        are marked on it instead.
        """
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        constraint.References = [(self.group, "Face3")]
        self.document.recompute()
        role = f"selection:{constraint.Name}:References"

        self.assertEqual(self.group.ViewObject.getElementHighlight(role), [])
        FreeCADGui.ActiveDocument.setEdit(constraint.Name)
        try:
            self.assertEqual(self.group.ViewObject.getElementHighlight(role), ["Face3"])
        finally:
            FreeCADGui.ActiveDocument.resetEdit()
        self.assertEqual(
            self.group.ViewObject.getElementHighlight(role),
            [],
            "a closed panel leaves no marks behind",
        )

    # -- what the view shows while references are picked ---------------------

    def test_editing_a_member_puts_the_view_into_the_geometry_stage(self):
        """
        References are picked on geometry, so a mesh drawn over it would leave
        nothing to pick. Same rule as for an edited chain step.
        """
        ObjectsFem.makeMeshShapeGroup(self.document, geometry=self.group, analysis=self.analysis)
        self.document.recompute()

        state = FemGui.getAnalysisViewState(self.analysis)
        state.setActiveStage("Mesh")

        material = ObjectsFem.makeMaterialSolid(self.document)
        self.analysis.addObject(material)
        self.document.recompute()

        # The real path: entering edit mode is what opens the scope, whichever
        # view provider is entered and whatever language it is written in.
        guidoc = FreeCADGui.getDocument(self.document.Name)
        guidoc.setEdit(material.Name)
        FreeCADGui.updateGui()
        try:
            self.assertEqual(state.getActiveStage(), "Geometry")
            self.assertEqual(state.getEditIntent(), "Geometry")
            self.assertEqual(state.getEditedObject(), material)
        finally:
            guidoc.resetEdit()
            FreeCADGui.Control.closeDialog()
            FreeCADGui.updateGui()
        self.assertEqual(state.getActiveStage(), "Mesh")
        self.assertIsNone(state.getEditedObject())

    # -- the unified slot widget --------------------------------------------

    def test_two_slots_keep_their_own_rules_and_the_arm_does_not_move(self):
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        widget = selection_slots.from_slot_specs(
            constraint,
            [
                {
                    "id": "faces",
                    "property": "References",
                    "title": "Faces",
                    "types": ["Face"],
                    "armed": True,
                },
                {
                    "id": "axis",
                    "title": "Axis",
                    "types": ["Edge"],
                    "max_count": 1,
                },
            ],
        )
        self.widgets.append(widget)
        widget.coordinator.install()
        widget.arm("faces")

        self._pick(self.group, "Face3")
        self.assertEqual(self._references(widget), [(self.group.Name, "Face3")])
        self.assertTrue(widget.slot("faces").arm_btn.isChecked())
        self.assertFalse(widget.slot("axis").arm_btn.isChecked())
        self.assertEqual(widget.slot("axis").picks, [])

        widget.arm("axis")
        self._pick(self.group, "Edge1")
        self.assertEqual(
            [(obj.Name, sub) for obj, sub in widget.slot("axis").picks],
            [(self.group.Name, "Edge1")],
        )
        self.assertEqual(self._references(widget), [(self.group.Name, "Face3")])
        self.assertFalse(widget.slot("faces").arm_btn.isChecked())
        self.assertTrue(widget.slot("axis").arm_btn.isChecked())

    def test_the_arm_button_arms_on_the_first_click(self):
        """Switching slots via the arm toggle must stick on the first press."""
        constraint = ObjectsFem.makeConstraintForce(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        widget = selection_slots.from_slot_specs(
            constraint,
            [
                {
                    "id": "faces",
                    "property": "References",
                    "title": "References",
                    "types": ["Face"],
                    "armed": True,
                },
                {
                    "id": "Direction",
                    "title": "Direction",
                    "types": ["Edge"],
                    "max_count": 1,
                },
            ],
        )
        self.widgets.append(widget)
        widget.coordinator.install()
        widget.show()
        QtGui.QApplication.processEvents()

        direction = widget.slot("Direction")
        self.assertIs(widget.coordinator.armed_slot, widget.slot("faces"))

        direction.arm_btn.click()
        QtGui.QApplication.processEvents()

        self.assertIs(widget.coordinator.armed_slot, direction)
        self.assertTrue(direction.arm_btn.isChecked())
        self.assertFalse(widget.slot("faces").arm_btn.isChecked())

    def test_a_refused_pick_reaches_the_status_line_not_a_message_box(self):
        widget = self._picker(["Edge"])
        with _NoMessageBox() as boxes:
            self._pick(self.group, "Face3")
            self.assertEqual(widget.references, [])
            self.assertEqual(boxes.messages, [])
            status = widget.slot("References").status.text()
            self.assertTrue(status)
            self.assertIn("Face3", status)

    def test_marks_are_per_slot_and_teardown_clears_them(self):
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        widget = selection_slots.from_slot_specs(
            constraint,
            [
                {
                    "id": "faces",
                    "property": "References",
                    "title": "Faces",
                    "types": ["Face"],
                    "armed": True,
                },
                {
                    "id": "edges",
                    "title": "Edges",
                    "types": ["Edge"],
                    "max_count": 1,
                },
            ],
        )
        self.widgets.append(widget)
        widget.coordinator.install()
        widget.arm("faces")
        self._pick(self.group, "Face3")
        widget.arm("edges")
        self._pick(self.group, "Edge1")

        face_role = widget.slot("faces").mark_role()
        edge_role = widget.slot("edges").mark_role()
        self.assertNotEqual(face_role, edge_role)
        self.assertEqual(self.group.ViewObject.getElementHighlight(face_role), ["Face3"])
        self.assertEqual(self.group.ViewObject.getElementHighlight(edge_role), ["Edge1"])

        widget.finish_selection()
        self.widgets.remove(widget)
        self.assertEqual(self.group.ViewObject.getElementHighlight(face_role), [])
        self.assertEqual(self.group.ViewObject.getElementHighlight(edge_role), [])
        self.assertFalse(widget.coordinator._installed)

    # -- pre-selection handoff ----------------------------------------------

    def test_creation_with_a_valid_selection_fills_the_armed_slot(self):
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.document.Name, self.group.Name, "Face3")
        selection_handoff.stash_for(constraint.Name)

        widget = selection_slots.for_references(constraint, ["Face"])
        self.widgets.append(widget)

        self.assertEqual(self._references(widget), [(self.group.Name, "Face3")])
        self.assertEqual(FreeCADGui.Selection.getSelection(), [])

    def test_creation_with_a_partly_invalid_selection_keeps_the_valid_picks(self):
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.document.Name, self.group.Name, "Face3")
        FreeCADGui.Selection.addSelection(self.document.Name, self.source.Name, "Face1")
        selection_handoff.stash_for(constraint.Name)

        widget = selection_slots.for_references(constraint, ["Face"])
        self.widgets.append(widget)

        self.assertEqual(self._references(widget), [(self.group.Name, "Face3")])
        status = widget.slot("References").status.text()
        self.assertIn("1 of 2", status)

    def test_editing_while_an_unrelated_selection_is_live_shows_only_stored_marks(self):
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        constraint.References = [(self.group, "Face3")]
        self.document.recompute()

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.document.Name, self.source.Name, "Face1")

        widget = selection_slots.for_references(constraint, ["Face"])
        self.widgets.append(widget)
        widget.coordinator.install()
        for slot in widget.slots:
            slot._update_marks()

        self.assertEqual(self._references(widget), [(self.group.Name, "Face3")])
        self.assertEqual(FreeCADGui.Selection.getSelection(), [])
        role = widget.slot("References").mark_role()
        self.assertEqual(self.group.ViewObject.getElementHighlight(role), ["Face3"])

    def test_a_stash_is_consumed_once(self):
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.document.Name, self.group.Name, "Face3")
        selection_handoff.stash_for(constraint.Name)

        first = selection_slots.for_references(constraint, ["Face"])
        self.widgets.append(first)
        self.assertEqual(self._references(first), [(self.group.Name, "Face3")])
        first.finish_selection()
        self.widgets.remove(first)

        constraint.References = []
        second = selection_slots.for_references(constraint, ["Face"])
        self.widgets.append(second)
        self.assertEqual(second.references, [])

    def test_an_opted_out_command_prefills_nothing(self):
        """Tie has no obvious primary slot, so its command never stashes."""
        constraint = ObjectsFem.makeConstraintTie(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.document.Name, self.group.Name, "Face3")

        widget = selection_slots.from_slot_specs(
            constraint,
            [
                {
                    "id": "slave",
                    "property": "References",
                    "role": "slave",
                    "title": "Slave",
                    "types": ["Face"],
                    "armed": True,
                },
                {
                    "id": "master",
                    "property": "References",
                    "role": "master",
                    "title": "Master",
                    "types": ["Face"],
                    "max_count": 1,
                },
            ],
        )
        self.widgets.append(widget)

        self.assertEqual(widget.slot("slave").picks, [])
        self.assertEqual(widget.slot("master").picks, [])
        self.assertEqual(FreeCADGui.Selection.getSelection(), [])

    def test_a_hosted_panel_hides_the_old_chrome_and_keeps_its_own(self):
        """
        The .ui files still carry the Add / Remove / list chrome, which the
        host hides by object name. The names the new widget uses have to stay
        clear of that list, or a panel loses the button that arms its slots.
        """
        for maker in (ObjectsFem.makeConstraintContact, ObjectsFem.makeConstraintForce):
            constraint = maker(self.document)
            self.analysis.addObject(constraint)
            self.document.recompute()
            window = FreeCADGui.getMainWindow()
            FreeCADGui.ActiveDocument.setEdit(constraint.Name)
            try:
                arms = window.findChildren(QtGui.QToolButton, "FemReferenceArm")
                self.assertTrue(arms, f"{constraint.Name} puts up no arm button")
                self.assertTrue(
                    all(button.isVisible() for button in arms),
                    f"{constraint.Name} hid its own arm button",
                )
                for name in ("btnAdd", "btnAddMaster", "btnAddSlave", "listReferences"):
                    for legacy in window.findChildren(QtGui.QWidget, name):
                        self.assertFalse(
                            legacy.isVisible(), f"{name} is left over on {constraint.Name}"
                        )
            finally:
                FreeCADGui.Control.closeDialog()
                FreeCADGui.ActiveDocument.abortCommand()
                FreeCADGui.ActiveDocument.resetEdit()

    # -- two slots sharing one property --------------------------------------

    def _tie_widget(self, constraint):
        widget = selection_slots.from_slot_specs(
            constraint,
            [
                {
                    "id": "slave",
                    "property": "References",
                    "role": "slave",
                    "title": "Slave",
                    "types": ["Face"],
                    "armed": True,
                },
                {
                    "id": "master",
                    "property": "References",
                    "role": "master",
                    "title": "Master",
                    "types": ["Face"],
                    "max_count": 1,
                },
            ],
        )
        self.widgets.append(widget)
        widget.coordinator.install()
        return widget

    def test_master_and_slave_share_one_property_and_survive_a_reopen(self):
        """
        Tie and Contact store both roles in one References list, slaves first
        and the master last. The split has to come back the way it went in.
        """
        constraint = ObjectsFem.makeConstraintTie(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        widget = self._tie_widget(constraint)
        widget.arm("slave")
        self._pick(self.group, "Face3")
        self._pick(self.group, "Face5")
        widget.arm("master")
        self._pick(self.group, "Face7")

        stored = [
            (obj.Name, sub) for obj, sub in selection_slots.flatten_links(constraint.References)
        ]
        self.assertEqual(
            stored,
            [(self.group.Name, "Face3"), (self.group.Name, "Face5"), (self.group.Name, "Face7")],
        )

        widget.finish_selection()
        self.widgets.remove(widget)
        reopened = self._tie_widget(constraint)
        self.assertEqual([sub for _obj, sub in reopened.slot("slave").picks], ["Face3", "Face5"])
        self.assertEqual([sub for _obj, sub in reopened.slot("master").picks], ["Face7"])

    def test_a_lone_slave_pick_is_not_read_back_as_the_master(self):
        """
        The stored order alone cannot tell them apart while only one pick
        exists, so the write has to come from the slots, not from re-slicing.
        """
        constraint = ObjectsFem.makeConstraintTie(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        widget = self._tie_widget(constraint)
        widget.arm("slave")
        self._pick(self.group, "Face3")

        self.assertEqual([sub for _obj, sub in widget.slot("slave").picks], ["Face3"])
        self.assertEqual(widget.slot("master").picks, [])

        widget.arm("master")
        self._pick(self.group, "Face7")
        self.assertEqual([sub for _obj, sub in widget.slot("slave").picks], ["Face3"])
        self.assertEqual([sub for _obj, sub in widget.slot("master").picks], ["Face7"])

    def test_a_pick_for_another_slot_says_so(self):
        """
        The arm never moves on its own, so the refusal is what has to name the
        slot that would have taken the pick.
        """
        constraint = ObjectsFem.makeConstraintForce(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        widget = selection_slots.from_slot_specs(
            constraint,
            [
                {
                    "id": "references",
                    "property": "References",
                    "title": "Loaded geometry",
                    "types": ["Face"],
                    "armed": True,
                },
                {
                    "id": "direction",
                    "title": "Direction",
                    "types": ["Edge"],
                    "max_count": 1,
                },
            ],
        )
        self.widgets.append(widget)
        widget.coordinator.install()
        widget.arm("references")

        self.assertFalse(widget.coordinator.allow(self.document.Name, self.group, "Edge1"))
        status = widget.slot("references").status.text()
        self.assertIn("Direction", status)

    def test_a_duplicate_says_so_rather_than_naming_another_slot(self):
        constraint = ObjectsFem.makeConstraintForce(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        widget = selection_slots.from_slot_specs(
            constraint,
            [
                {
                    "id": "references",
                    "property": "References",
                    "title": "Loaded geometry",
                    "types": ["Face"],
                    "armed": True,
                },
                {
                    "id": "direction",
                    "title": "Direction",
                    "types": ["Face"],
                    "max_count": 1,
                },
            ],
        )
        self.widgets.append(widget)
        widget.coordinator.install()
        widget.arm("references")
        self._pick(self.group, "Face3")

        self.assertFalse(widget.coordinator.allow(self.document.Name, self.group, "Face3"))
        status = widget.slot("references").status.text()
        self.assertIn("already", status)
        self.assertNotIn("Direction", status)

    # -- what the slot puts on screen ----------------------------------------

    def test_the_list_counts_against_a_fixed_maximum_and_offers_the_rest(self):
        widget = selection_slots.for_references(None, ["Vertex"], max_count=3, property=None)
        self.widgets.append(widget)
        widget.coordinator.install()
        widget.arm("References")
        slot = widget.slot("References")

        self.assertEqual(slot.count_label.text(), "0 of 3")
        self.assertFalse(slot.clear_btn.isEnabled())
        self.assertEqual(slot.list.topLevelItemCount(), 3, "three outstanding placeholder rows")

        self._pick(self.group, "Vertex1")
        self._pick(self.group, "Vertex2")
        self.assertEqual(slot.count_label.text(), "2 of 3")
        self.assertTrue(slot.clear_btn.isEnabled())
        self.assertEqual(slot.list.topLevelItemCount(), 3, "two picks and one still to go")

    def test_a_row_can_be_dropped_from_the_list_alone(self):
        widget = self._picker(["Face"])
        slot = widget.slot("References")
        self._pick(self.group, "Face3")
        self._pick(self.group, "Face5")
        self.assertEqual(len(slot.picks), 2)

        slot._remove_row(0)
        self.assertEqual([sub for _obj, sub in slot.picks], ["Face5"])

        slot.list.selectAll()
        slot._remove_selected()
        self.assertEqual(slot.picks, [])
        self.assertFalse(slot.clear_btn.isEnabled())

    def test_a_single_pick_slot_is_a_field_and_the_next_pick_replaces(self):
        widget = selection_slots.for_references(None, ["Edge"], max_count=1, property=None)
        self.widgets.append(widget)
        widget.coordinator.install()
        widget.arm("References")
        slot = widget.slot("References")

        self.assertIsNone(slot.list, "one pick is a line edit, not a list")
        self.assertFalse(slot.field.text())
        self.assertTrue(slot.field.placeholderText())

        self._pick(self.group, "Edge1")
        self.assertIn("Edge1", slot.field.text())
        self._pick(self.group, "Edge2")
        self.assertEqual([sub for _obj, sub in slot.picks], ["Edge2"])
        self.assertIn("Edge2", slot.field.text())

    def test_an_unarmed_slot_says_nothing(self):
        widget = self._picker(["Face"])
        slot = widget.slot("References")
        self.assertTrue(slot.status.text(), "an armed slot names what it takes")
        widget.coordinator.disarm()
        self.assertEqual(slot.status.text(), "")

    def test_disarming_hands_the_3d_view_back(self):
        """
        A gate left standing while nothing is armed refuses every pick, so the
        view stays dead for the rest of the panel's life.
        """
        widget = self._picker(["Face"])
        self._pick(self.group, "Edge1")
        self.assertFalse(
            FreeCADGui.Selection.getSelection(), "an armed Face slot gates an edge out"
        )

        widget.coordinator.disarm()
        self._pick(self.group, "Edge1")
        self.assertTrue(
            FreeCADGui.Selection.getSelection(),
            "with no slot armed the view has to take a plain selection again",
        )

    def test_rearming_puts_the_gate_back(self):
        widget = self._picker(["Face"])
        widget.coordinator.disarm()
        widget.arm("References")
        self._pick(self.group, "Edge1")
        self.assertFalse(
            FreeCADGui.Selection.getSelection(), "arming again has to gate the view again"
        )

    # -- how long a refusal stays up ------------------------------------------

    def _with_blocked_pointer(self, blocked):
        """Stand in for the forbidden cursor the viewer puts up on a refusal."""
        original = selection_coordinator.pointer_is_blocked
        selection_coordinator.pointer_is_blocked = lambda: blocked
        self.addCleanup(setattr, selection_coordinator, "pointer_is_blocked", original)

    def test_a_refusal_goes_once_the_pointer_is_off_it(self):
        """
        The refusal path clears the preselection before it reports, so no
        RmvPreselect follows and nothing else would ever take the message down.
        """
        widget = self._picker(["Face"])
        slot = widget.slot("References")
        coordinator = widget.coordinator

        coordinator.allow(self.document, self.group, "Edge1")
        refusal = slot.status.text()
        self.assertTrue(refusal)

        self._with_blocked_pointer(False)
        coordinator._sweep_refusal()
        self.assertNotEqual(slot.status.text(), refusal, "the refusal outlived the hover")

    def test_a_refusal_stays_while_the_pointer_rests_on_it(self):
        """
        A still pointer sends no events at all, so nothing but the cursor can
        say the hover is still going on.
        """
        widget = self._picker(["Face"])
        slot = widget.slot("References")
        coordinator = widget.coordinator

        coordinator.allow(self.document, self.group, "Edge1")
        refusal = slot.status.text()

        self._with_blocked_pointer(True)
        for _ in range(5):
            coordinator._sweep_refusal()
        self.assertEqual(slot.status.text(), refusal, "the message left before the symbol did")

    def test_the_poll_stops_with_the_refusal(self):
        widget = self._picker(["Face"])
        coordinator = widget.coordinator

        self._with_blocked_pointer(True)
        coordinator.allow(self.document, self.group, "Edge1")
        self.assertTrue(coordinator._sweep.isActive(), "a refusal has to be watched")

        self._with_blocked_pointer(False)
        coordinator._sweep_refusal()
        self.assertFalse(coordinator._sweep.isActive(), "nothing left to watch")

    def test_an_allowed_hover_clears_the_last_refusal(self):
        widget = self._picker(["Face"])
        slot = widget.slot("References")
        coordinator = widget.coordinator

        coordinator.allow(self.document, self.group, "Edge1")
        self.assertIsNotNone(coordinator._refused_slot)
        coordinator.allow(self.document, self.group, "Face1")
        self.assertIsNone(coordinator._refused_slot, "an accepted hover ends the refusal")

    # -- changing the pick mode under a standing hover ------------------------

    def test_turning_on_promotion_rejudges_the_standing_hover(self):
        """
        setPreselect short-circuits on an element that is already preselected,
        before the gate sees it. A hover accepted as a face therefore survived
        Alt going down and kept looking pickable, under a plain pointer, until
        the pointer crossed onto something else.
        """
        widget = self._picker(["Solid", "Face"])
        slot = widget.slot("References")
        slot.accept_picks([(self.group, "Face1")])

        FreeCADGui.Selection.setPreselection(self.group, "Face3", 0.0, 0.0, 0.0, 0)
        self.assertEqual(
            FreeCADGui.Selection.getPreselection().SubElementNames,
            ("Face3",),
            "a face the slot takes is preselected",
        )

        slot.set_promotion_latched(True)
        self.assertNotIn(
            "Face3",
            FreeCADGui.Selection.getPreselection().SubElementNames,
            "the hover was judged as a face and has to be judged again as a solid",
        )
        self.assertIn("one kind", slot.status.text().lower())

    def test_the_header_row_stands_as_tall_as_its_clear_button(self):
        slot = self._picker(["Solid", "Face"]).slot("References")
        side = slot.clear_btn.sizeHint().height()

        for button in (slot.arm_btn, slot.solid_btn):
            self.assertEqual(button.height(), side)
            self.assertEqual(button.width(), side)
        self.assertGreater(slot.swatch.height(), 9, "the colour chip was hard to see")
        self.assertLess(slot.swatch.height(), side, "the chip is a mark, not a button")

    def _with_alt(self, held):
        """Alt is read live from the keyboard, in two module namespaces."""
        for module in (selection_coordinator, selection_slots):
            original = module.alt_held
            module.alt_held = lambda: held
            self.addCleanup(setattr, module, "alt_held", original)

    def test_the_alt_key_lands_without_waiting_for_the_poll(self):
        """
        The key press carries Alt on a platform whose query cannot.

        Wayland has no live modifier query, so Qt answers one out of the last
        input event it saw. Alt pressed over a resting pointer produces no
        such event, and the poll goes on reading the old state until the
        pointer twitches — which is the move the user should not have to make.
        """
        widget = self._picker(["Solid", "Face"])
        widget._watch_modifier(True)
        self.addCleanup(widget._watch_modifier, False)
        slot = widget.slot("References")
        slot.accept_picks([(self.group, "Face1")])
        FreeCADGui.Selection.setPreselection(self.group, "Face3", 0.0, 0.0, 0.0, 0)

        # Only the live read sees Alt; the poll is left as blind as Wayland's.
        original = selection_coordinator.alt_held
        selection_coordinator.alt_held = lambda: True
        self.addCleanup(setattr, selection_coordinator, "alt_held", original)
        QtGui.QApplication.sendEvent(
            slot,
            QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Alt, QtCore.Qt.AltModifier),
        )

        self.assertNotIn(
            "Face3",
            FreeCADGui.Selection.getPreselection().SubElementNames,
            "the key press has to rejudge the hover on its own",
        )

    def test_holding_alt_rejudges_the_standing_hover(self):
        """The same as the toggle, but over the poll that watches the key."""
        widget = self._picker(["Solid", "Face"])
        slot = widget.slot("References")
        slot.accept_picks([(self.group, "Face1")])
        FreeCADGui.Selection.setPreselection(self.group, "Face3", 0.0, 0.0, 0.0, 0)
        self.assertIn("Face3", FreeCADGui.Selection.getPreselection().SubElementNames)

        self._with_alt(True)
        widget._poll_modifier()

        self.assertNotIn(
            "Face3",
            FreeCADGui.Selection.getPreselection().SubElementNames,
            "Alt has to reach the standing hover without waiting for a move",
        )
        self.assertIn("one kind", slot.status.text().lower())

    def test_turning_promotion_back_off_rejudges_it_again(self):
        widget = self._picker(["Solid", "Face"], solid=True)
        slot = widget.slot("References")
        slot.accept_picks([(self.group, "Face1")])
        FreeCADGui.Selection.clearPreselection()

        slot.set_promotion_latched(False)
        self.assertFalse(slot.status.text().lower().startswith("one kind"))

    # -- the close glyph is the button, not the row ---------------------------

    def test_only_the_glyph_answers_the_pointer(self):
        widget = self._picker(["Face"])
        slot = widget.slot("References")
        self._pick(self.group, "Face1")
        self._pick(self.group, "Face3")
        slot.list.resize(240, 80)
        slot.list.show()
        try:
            index = slot.list.model().index(0, 0)
            row = slot.list.visualRect(index)
            glyph = slot.delegate.glyph_rect(row)

            slot.delegate.eventFilter(
                slot.list.viewport(), self._move_to(QtCore.QPoint(row.left() + 4, row.center().y()))
            )
            self.assertEqual(slot.delegate._hovered, -1, "the label is not the delete button")

            slot.delegate.eventFilter(slot.list.viewport(), self._move_to(glyph.center()))
            self.assertEqual(slot.delegate._hovered, 0, "the glyph is")

            slot.delegate.eventFilter(slot.list.viewport(), QtCore.QEvent(QtCore.QEvent.Leave))
            self.assertEqual(slot.delegate._hovered, -1, "leaving the list drops the hover")
        finally:
            slot.list.hide()

    def _move_to(self, point):
        return QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove,
            QtCore.QPointF(point),
            QtCore.Qt.NoButton,
            QtCore.Qt.NoButton,
            QtCore.Qt.NoModifier,
        )

    # -- following the theme --------------------------------------------------

    def _contrast(self, one, two):
        """WCAG relative-luminance ratio; AA wants 4.5 for body text."""

        def channel(value):
            value /= 255.0
            return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

        def luminance(color):
            return (
                0.2126 * channel(color.red())
                + 0.7152 * channel(color.green())
                + 0.0722 * channel(color.blue())
            )

        low, high = sorted((luminance(one), luminance(two)))
        return (high + 0.05) / (low + 0.05)

    def _palette(self, window, ink, base):
        palette = QtGui.QPalette()
        for role in (QtGui.QPalette.Window, QtGui.QPalette.Button):
            palette.setColor(role, QtGui.QColor(window))
        for role in (QtGui.QPalette.WindowText, QtGui.QPalette.Text, QtGui.QPalette.ButtonText):
            palette.setColor(role, QtGui.QColor(ink))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor(base))
        return palette

    def test_the_muted_text_stays_legible_on_a_dark_theme(self):
        """
        QPalette.Mid is derived from the button colour, so on FreeCAD's dark
        theme it lands within a hair of the background. The status line and the
        row glyph have to come off the text colour instead.
        """
        for name, window, ink, base in (
            ("dark", "#202326", "#fcfcfc", "#141618"),
            ("light", "#efefef", "#232629", "#ffffff"),
        ):
            palette = self._palette(window, ink, base)
            muted = selection_slots.muted_color(palette)
            glyph = selection_slots.muted_color(palette, on_base=True)
            self.assertGreater(
                self._contrast(muted, palette.color(QtGui.QPalette.Window)),
                4.5,
                f"the {name} status line is unreadable",
            )
            self.assertGreater(
                self._contrast(glyph, palette.color(QtGui.QPalette.Base)),
                4.5,
                f"the {name} row glyph is unreadable",
            )
            self.assertGreater(
                self._contrast(
                    selection_slots.warn_color(palette), palette.color(QtGui.QPalette.Window)
                ),
                4.5,
                f"the {name} refusal is unreadable",
            )
            self.assertGreater(
                self._contrast(
                    selection_slots.warn_color(palette, on_base=True),
                    palette.color(QtGui.QPalette.Base),
                ),
                4.5,
                f"the {name} stale row is unreadable",
            )

    def test_a_slot_restyles_itself_when_the_theme_changes(self):
        widget = self._picker(["Face"])
        slot = widget.slot("References")
        slot.setPalette(self._palette("#202326", "#fcfcfc", "#141618"))
        dark = slot.status.styleSheet()
        slot.setPalette(self._palette("#efefef", "#232629", "#ffffff"))
        self.assertNotEqual(
            dark, slot.status.styleSheet(), "the status line kept the other theme's colour"
        )

    def test_the_drawn_glyphs_fill_the_size_they_are_asked_for(self):
        """
        QPainter maps a pixmap's device ratio itself; scaling on top of that
        drew each glyph at twice the size and clipped away three quarters.
        """
        for name, pixmap in (
            ("warning", selection_slots.warn_pixmap(QtGui.QColor("#d08326"), 12)),
            ("close", selection_slots.close_icon(QtGui.QColor("#808080"), 14).pixmap(14, 14)),
        ):
            image = pixmap.toImage()
            painted = [
                (x, y)
                for x in range(image.width())
                for y in range(image.height())
                if image.pixelColor(x, y).alpha() > 40
            ]
            self.assertTrue(painted, f"the {name} glyph drew nothing")
            xs = [x for x, _y in painted]
            ys = [y for _x, y in painted]
            # Drawn oversized, the glyph runs off every side of the pixmap;
            # drawn right, it stops short of all four.
            self.assertGreater(min(xs), 0, f"the {name} glyph runs off the left")
            self.assertLess(max(xs), image.width() - 1, f"the {name} glyph runs off the right")
            self.assertGreater(min(ys), 0, f"the {name} glyph runs off the top")
            self.assertLess(max(ys), image.height() - 1, f"the {name} glyph runs off the bottom")
            self.assertGreater(
                (max(xs) - min(xs) + 1) / image.width(),
                0.4,
                f"the {name} glyph is too small to hit",
            )

    # -- cancelling a panel ---------------------------------------------------

    def test_cancel_rolls_back_what_the_slots_wrote(self):
        """
        A slot writes its property as it is picked, so the edit needs its own
        transaction — otherwise Cancel leaves the picks behind.
        """
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        constraint.References = [(self.group, "Face3")]
        self.document.recompute()

        FreeCADGui.ActiveDocument.setEdit(constraint.Name)
        try:
            widget = None
            for candidate in FreeCADGui.getMainWindow().findChildren(
                selection_slots.ReferenceSelection
            ):
                widget = candidate
            self.assertIsNotNone(widget, "the panel puts up a reference widget")
            widget.slots[0].accept_picks([(self.group, "Face5")])
            self.assertEqual(len(selection_slots.flatten_links(constraint.References)), 2)
            self.assertTrue(
                self.document.HasPendingTransaction,
                "an edit session that writes as it goes has to be undoable",
            )
        finally:
            FreeCADGui.Control.closeDialog()
            # What Cancel does: TaskDlgFemConstraint::reject() aborts the
            # transaction the view provider opened for the edit.
            FreeCADGui.ActiveDocument.abortCommand()
            FreeCADGui.ActiveDocument.resetEdit()

        self.assertEqual(
            [sub for _obj, sub in selection_slots.flatten_links(constraint.References)],
            ["Face3"],
            "cancelling the panel must undo the pick",
        )
