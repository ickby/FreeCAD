# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2026 Stefan Tröger <stefantroeger@gmx.net>              *
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Headless tests for the FEM reference-selection rule layer."""

__title__ = "FEM selection rules unit tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import Part

import ObjectsFem

from femguiutils.selection_rules import (
    PICK_DIRECT,
    PICK_SOLID,
    PROMOTION_LOCKED,
    PROMOTION_OFFERED,
    PROMOTION_UNAVAILABLE,
    Accept,
    NeedsChoice,
    ReferenceRule,
    Refuse,
    element_exists,
    evaluate,
    humanize_object_kind,
    owning_solids,
    pickable_phrase,
    placeholder_text,
    resolve_pick,
    shape_kind,
)
from femtest.app.support_utils import fcc_print


class TestSelectionRules(unittest.TestCase):
    fcc_print("import TestSelectionRules")

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
        self.geometry = ObjectsFem.makeGeometryGroup(self.document)
        imported = ObjectsFem.makeGeometryImport(self.document)
        imported.Import = [self.source]
        self.geometry.Group = [imported]
        self.analysis.addObject(self.geometry)
        self.document.recompute()
        self.other = self.document.addObject("Part::Feature", "Other")
        self.other.Shape = Part.makeBox(5, 5, 5)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def _eval(self, rule, obj, sub, current=(), mode=PICK_DIRECT, **kwargs):
        return evaluate(
            rule,
            mode,
            obj,
            sub,
            list(current),
            geometry=self.geometry,
            document=self.document,
            **kwargs,
        )

    def test_a_face_on_the_analysis_geometry_is_taken(self):
        rule = ReferenceRule(types=("Face",))
        result = self._eval(rule, self.geometry, "Face3")
        self.assertIsInstance(result, Accept)
        self.assertEqual(result.picks, [(self.geometry, "Face3")])

    def test_a_pick_beside_the_analysis_geometry_is_refused(self):
        rule = ReferenceRule(types=("Face",))
        result = self._eval(rule, self.source, "Face1")
        self.assertIsInstance(result, Refuse)
        self.assertIn(self.geometry.Label, result.reason)

    def test_without_a_geometry_a_part_feature_is_taken(self):
        rule = ReferenceRule(types=("Face",))
        result = evaluate(
            rule,
            PICK_DIRECT,
            self.source,
            "Face1",
            [],
            geometry=None,
            document=self.document,
        )
        self.assertIsInstance(result, Accept)

    def test_without_a_geometry_a_non_part_is_refused(self):
        dummy = self.document.addObject("App::DocumentObjectGroup", "Dummy")
        rule = ReferenceRule(types=("Face",))
        result = evaluate(rule, PICK_DIRECT, dummy, "Face1", [], geometry=None)
        self.assertIsInstance(result, Refuse)
        self.assertIn("not a part", result.reason)

    def test_wrong_type_is_refused(self):
        rule = ReferenceRule(types=("Face",))
        result = self._eval(rule, self.geometry, "Edge1")
        self.assertIsInstance(result, Refuse)
        self.assertIn("edge", result.reason.lower())
        self.assertIn("face", result.reason.lower())

    def test_duplicate_is_refused(self):
        rule = ReferenceRule(types=("Face",))
        result = self._eval(rule, self.geometry, "Face3", current=[(self.geometry, "Face3")])
        self.assertIsInstance(result, Refuse)
        self.assertIn("already", result.reason)

    def test_homogeneity_refuses_a_mixed_type(self):
        rule = ReferenceRule(types=("Face", "Edge"), homogeneous=True)
        result = self._eval(rule, self.geometry, "Face3", current=[(self.geometry, "Edge1")])
        self.assertIsInstance(result, Refuse)
        self.assertIn("edges", result.reason)
        self.assertIn("Face3", result.reason)

    def test_a_mixed_type_names_the_rule_and_the_way_out(self):
        """
        Naming the two kinds alone leaves it open whether the slot only ever
        takes the one it holds, or whether the list can be started over.
        """
        rule = ReferenceRule(types=("Face", "Edge"), homogeneous=True)
        result = self._eval(rule, self.geometry, "Face3", current=[(self.geometry, "Edge1")])
        self.assertIn("One kind at a time", result.reason)
        self.assertIn("Clear", result.reason)
        self.assertIn("faces", result.reason, "the way out names what could be collected instead")

    def test_a_mixer_accepts_mixed_types(self):
        rule = ReferenceRule(types=("Face", "Edge"), homogeneous=False)
        result = self._eval(rule, self.geometry, "Face3", current=[(self.geometry, "Edge1")])
        self.assertIsInstance(result, Accept)

    def test_full_fixed_count_is_refused(self):
        rule = ReferenceRule(types=("Vertex",), max_count=3)
        current = [
            (self.geometry, "Vertex1"),
            (self.geometry, "Vertex2"),
            (self.geometry, "Vertex3"),
        ]
        result = self._eval(rule, self.geometry, "Vertex4", current=current)
        self.assertIsInstance(result, Refuse)
        self.assertIn("Full", result.reason)
        self.assertIn("3", result.reason)

    def test_max_one_still_accepts_so_the_slot_can_replace(self):
        rule = ReferenceRule(types=("Edge",), max_count=1)
        result = self._eval(rule, self.geometry, "Edge2", current=[(self.geometry, "Edge1")])
        self.assertIsInstance(result, Accept)
        self.assertEqual(result.picks, [(self.geometry, "Edge2")])

    def test_import_is_in_scope(self):
        imported = self.geometry.Group[0]
        rule = ReferenceRule(types=("Face",))
        result = self._eval(rule, imported, "Face1")
        self.assertIsInstance(result, Accept)

    def test_external_document_is_refused(self):
        other_doc = FreeCAD.newDocument("OtherDoc")
        try:
            box = other_doc.addObject("Part::Feature", "Box")
            box.Shape = Part.makeBox(1, 1, 1)
            rule = ReferenceRule(types=("Face",))
            result = evaluate(
                rule,
                PICK_DIRECT,
                box,
                "Face1",
                [],
                geometry=None,
                document=self.document,
            )
            self.assertIsInstance(result, Refuse)
            self.assertIn("External", result.reason)
        finally:
            FreeCAD.closeDocument(other_doc.Name)

    def test_promotion_mode_is_derived_from_types(self):
        self.assertEqual(ReferenceRule(types=("Solid",)).promotion, PROMOTION_LOCKED)
        self.assertEqual(ReferenceRule(types=("Solid", "Face")).promotion, PROMOTION_OFFERED)
        self.assertEqual(ReferenceRule(types=("Face", "Edge")).promotion, PROMOTION_UNAVAILABLE)

    def test_direct_face_pick_promotes_to_its_solid(self):
        rule = ReferenceRule(types=("Solid", "Face"))
        result = self._eval(rule, self.geometry, "Face3", mode=PICK_SOLID)
        self.assertIsInstance(result, Accept)
        self.assertEqual(shape_kind(result.picks[0][1]), "Solid")
        self.assertTrue(result.picks[0][1].startswith("Solid"))

    def test_locked_solid_slot_promotes_without_asking(self):
        rule = ReferenceRule(types=("Solid",))
        result = self._eval(rule, self.geometry, "Face3", mode=PICK_DIRECT)
        self.assertIsInstance(result, Accept)
        self.assertTrue(result.picks[0][1].startswith("Solid"))

    def test_vertex_under_promotion_is_refused(self):
        rule = ReferenceRule(types=("Solid", "Face"))
        result = self._eval(rule, self.geometry, "Vertex1", mode=PICK_SOLID)
        self.assertIsInstance(result, Refuse)
        self.assertIn("vertex", result.reason.lower())

    def test_shared_face_asks_which_solid(self):
        rule = ReferenceRule(types=("Solid", "Face"))
        result = self._eval(
            rule,
            self.geometry,
            "Face3",
            mode=PICK_SOLID,
            solids_of=lambda obj, sub: ["Solid1", "Solid2"],
        )
        self.assertIsInstance(result, NeedsChoice)
        self.assertEqual([name for _obj, name in result.candidates], ["Solid1", "Solid2"])

    def test_homogeneity_against_solids_hints_at_alt(self):
        rule = ReferenceRule(types=("Solid", "Face"), homogeneous=True)
        result = self._eval(
            rule,
            self.geometry,
            "Face18",
            current=[(self.geometry, "Solid1")],
            mode=PICK_DIRECT,
        )
        self.assertIsInstance(result, Refuse)
        self.assertIn("hold Alt", result.reason)
        self.assertIn("Face18", result.reason)

    def test_owning_solids_finds_one_solid_for_a_box_face(self):
        names = owning_solids(self.geometry, "Face3")
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith("Solid"))

    def test_owning_solids_covers_every_face_of_the_geometry(self):
        """Not just the first: Alt promotion is only useful if it always works."""
        faces = len(self.geometry.Shape.Faces)
        empty = [
            index
            for index in range(1, faces + 1)
            if not owning_solids(self.geometry, f"Face{index}")
        ]
        self.assertEqual(empty, [], "these faces were promoted to nothing")

    def test_a_face_of_an_imported_analysis_reaches_its_solid(self):
        """
        An imported analysis owns no shape and hands out its geometry through
        a transform, so an element fetched from it shares no TShape with the
        shape it is numbered in — isSame() between the two always said no, and
        every face of an import promoted to nothing.
        """
        outer = ObjectsFem.makeAnalysis(self.document, "Outer")
        imports = ObjectsFem.makeImportGroup(self.document)
        outer.addObject(imports)
        imported = ObjectsFem.makeAnalysisImport(self.document)
        imported.Analysis = self.analysis
        imports.addObject(imported)
        self.document.recompute()

        self.assertFalse(hasattr(imported, "Shape"), "the premise: no shape of its own")
        faces = len(self.geometry.Shape.Faces)
        promoted = {index: owning_solids(imported, f"Face{index}") for index in range(1, faces + 1)}
        self.assertEqual(
            [index for index, names in promoted.items() if not names],
            [],
            "these faces of the import promoted to nothing",
        )
        self.assertEqual(promoted[1], ["Solid1"])
        self.assertEqual(promoted[faces], ["Solid2"])

    def test_object_kind_scope(self):
        rule = ReferenceRule(object_kinds=("Part::Feature",), allow_empty_sub=True)
        result = evaluate(
            rule, PICK_DIRECT, self.source, "", [], geometry=None, document=self.document
        )
        self.assertIsInstance(result, Accept)
        dummy = self.document.addObject("App::DocumentObjectGroup", "NotAPart")
        result = evaluate(rule, PICK_DIRECT, dummy, "", [], geometry=None)
        self.assertIsInstance(result, Refuse)

    def test_nothing_selected(self):
        rule = ReferenceRule(types=("Face",))
        result = evaluate(rule, PICK_DIRECT, None, "", [])
        self.assertIsInstance(result, Refuse)
        self.assertIn("Nothing", result.reason)

    def test_pickable_phrase_names_the_offered_modifier(self):
        rule = ReferenceRule(types=("Solid", "Face", "Edge"))
        text = pickable_phrase(rule, PICK_DIRECT)
        self.assertIn("Alt", text)
        locked = pickable_phrase(ReferenceRule(types=("Solid",)))
        self.assertIn("faces or edges", locked.lower())

    def test_empty_types_take_the_whole_object(self):
        """Import picker: a face click still stores the object, not the face."""
        rule = ReferenceRule(types=(), allow_empty_sub=True, scope="any")
        result = evaluate(rule, PICK_DIRECT, self.source, "Face1", [], geometry=None)
        self.assertIsInstance(result, Accept)
        self.assertEqual(result.picks, [(self.source, "")])

    # -- which refusals may be answered with "try the other slot" -----------

    def test_a_wrong_type_may_be_redirected(self):
        """
        The one refusal a sibling slot can answer. The coordinator only looks
        for another taker when the pick simply does not suit this slot.
        """
        rule = ReferenceRule(types=("Face",))
        result = self._eval(rule, self.geometry, "Edge1")
        self.assertIsInstance(result, Refuse)
        self.assertTrue(result.redirectable)

    def test_a_duplicate_keeps_its_own_reason(self):
        rule = ReferenceRule(types=("Face",))
        result = self._eval(rule, self.geometry, "Face3", current=[(self.geometry, "Face3")])
        self.assertIsInstance(result, Refuse)
        self.assertFalse(
            result.redirectable,
            "'already in the list' must not be replaced by a pointer to another slot",
        )

    def test_a_full_slot_keeps_its_own_reason(self):
        rule = ReferenceRule(types=("Vertex",), max_count=2)
        current = [(self.geometry, "Vertex1"), (self.geometry, "Vertex2")]
        result = self._eval(rule, self.geometry, "Vertex3", current=current)
        self.assertIsInstance(result, Refuse)
        self.assertFalse(result.redirectable)

    def test_a_mixed_type_keeps_its_own_reason(self):
        rule = ReferenceRule(types=("Face", "Edge"), homogeneous=True)
        result = self._eval(rule, self.geometry, "Edge1", current=[(self.geometry, "Face3")])
        self.assertIsInstance(result, Refuse)
        self.assertFalse(result.redirectable)

    # -- scope reaches through the chain -------------------------------------

    def test_a_partition_step_is_in_scope(self):
        """
        A reference can name any step of the chain the geometry is built
        from, not only the group at the end of it.
        """
        part = ObjectsFem.makeGeometryPartition(self.document)
        part.Base = self.geometry.Group[0]
        self.geometry.Group = self.geometry.Group + [part]
        self.document.recompute()
        rule = ReferenceRule(types=("Face",))
        result = self._eval(rule, part, "Face1")
        self.assertIsInstance(result, Accept)

    def test_the_part_a_step_was_made_from_stays_out_of_scope(self):
        """
        The source hangs off the import, so walking the OutList would let it
        in — and a reference on it addresses a shape the mesh is not made of.
        """
        rule = ReferenceRule(types=("Face",))
        result = self._eval(rule, self.source, "Face1")
        self.assertIsInstance(result, Refuse)

    # -- guards ---------------------------------------------------------------

    def test_a_deleted_object_is_refused_rather_than_raising(self):
        """
        A gate outlives the document it was armed against, and it is called
        from the selection machinery, where an exception has nowhere to go.
        """
        dummy = self.document.addObject("Part::Feature", "Doomed")
        dummy.Shape = Part.makeBox(1, 1, 1)
        self.document.removeObject(dummy.Name)
        rule = ReferenceRule(types=("Face",))
        result = self._eval(rule, dummy, "Face1")
        self.assertIsInstance(result, Refuse)

    def test_a_stored_element_that_vanished_reads_as_gone(self):
        self.assertTrue(element_exists(self.geometry, "Face3"))
        self.assertFalse(element_exists(self.geometry, "Face9999"))
        self.assertTrue(
            element_exists(self.geometry, ""),
            "a whole-object reference has no element to lose",
        )

    # -- what a pick names ----------------------------------------------------

    def _one_box_analysis(self, name):
        analysis = ObjectsFem.makeAnalysis(self.document, name)
        geometry = ObjectsFem.makeGeometryGroup(self.document, name + "Geometry")
        analysis.addObject(geometry)
        part = self.document.addObject("Part::Feature", name + "Part")
        part.Shape = Part.makeBox(10, 10, 10)
        step = ObjectsFem.makeGeometryImport(self.document)
        step.Import = [part]
        geometry.Group = [step]
        return analysis

    def _place(self, source, into, name):
        from femtools import importtools

        placed = ObjectsFem.makeAnalysisImport(self.document, name)
        placed.Analysis = source
        container = importtools.wire_import(into, placed)
        self.document.recompute()
        return placed, container

    def _table(self):
        """Table places Side, and Side places Leg — two instances deep."""
        leg = self._one_box_analysis("Leg")
        side = self._one_box_analysis("Side")
        inner, _ = self._place(leg, side, "Inner")
        table = self._one_box_analysis("Table")
        outer, container = self._place(side, table, "Outer")
        return table, container, outer, inner

    def test_a_pick_on_an_instance_names_the_instance(self):
        table, container, outer, _inner = self._table()
        self.assertEqual(
            resolve_pick(table, f"{container.Name}.{outer.Name}.Face1"),
            (outer, "Face1"),
        )

    def test_a_pick_inside_a_nested_instance_names_the_outer_one(self):
        """
        The instance the analysis holds draws the nested ones too, and it is
        the only one that stands where the pick landed: the nested instance
        stands in the analysis it was placed into, which this one may place
        more than once.
        """
        table, container, outer, inner = self._table()
        self.assertEqual(
            resolve_pick(table, f"{container.Name}.{outer.Name}.{inner.Name}.Face1"),
            (outer, f"{inner.Name}.Face1"),
        )

    def test_an_element_named_on_an_instance_stays_as_it_is(self):
        """What the view panel selects with comes back through here unchanged."""
        _table, _container, outer, inner = self._table()
        self.assertEqual(
            resolve_pick(outer, f"{inner.Name}.Face1"),
            (outer, f"{inner.Name}.Face1"),
        )

    def test_a_pick_on_a_geometry_step_reaches_the_step(self):
        """No instance on the way, so the way is followed to its end."""
        step = self.geometry.Group[0]
        self.assertEqual(
            resolve_pick(self.analysis, f"{self.geometry.Name}.{step.Name}.Face3"),
            (step, "Face3"),
        )

    def test_the_mapped_name_a_pick_carries_is_left_out(self):
        """
        A pick names its element twice, mapped and plainly. Stored mapped, the
        reference reads as a name no shape of the analysis has.
        """
        self.assertEqual(
            resolve_pick(self.analysis, f"{self.geometry.Name}.;Face3;:H1,F.Face3"),
            (self.geometry, "Face3"),
        )

    def test_a_one_pick_slot_asks_for_one_thing(self):
        """Grammar, which is the whole reason the singular table exists."""
        rule = ReferenceRule(types=("Face", "Edge"), max_count=1)
        self.assertEqual(placeholder_text(rule), "click a face or an edge in the 3D view")
        self.assertIn(
            "replaces this one", pickable_phrase(rule, PICK_DIRECT, [(self.geometry, "Face3")])
        )

    def test_an_object_kind_refusal_reads_as_english(self):
        self.assertEqual(humanize_object_kind("Part::DatumPlane"), "datum plane")
        self.assertEqual(humanize_object_kind("Sketcher::SketchObject"), "sketch object")
