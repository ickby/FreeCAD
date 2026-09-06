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
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

"""Unit tests for result attribution and the filter that reads it."""

__title__ = "FEM result attribution tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import os
import tempfile
import unittest

import FreeCAD
import Part

import Fem
import ObjectsFem

from femobjects import post_attributefilter
from femtools import importtools, membertools

from .support_utils import fcc_print


def _tet(mesh, offset, solid, first_face):
    """One tetrahedron with its four faces, each in a group of its own."""
    base = mesh.NodeCount
    mesh.addNode(offset, 0, 0, base + 1)
    mesh.addNode(offset + 1, 0, 0, base + 2)
    mesh.addNode(offset, 1, 0, base + 3)
    mesh.addNode(offset, 0, 1, base + 4)
    nodes = [base + 1, base + 2, base + 3, base + 4]

    volume = mesh.addVolume(nodes)
    group = mesh.addGroup(f"Solid{solid}", "Volume")
    mesh.addGroupElements(group, [volume])

    faces = [
        mesh.addFace([nodes[0], nodes[1], nodes[2]]),
        mesh.addFace([nodes[0], nodes[1], nodes[3]]),
        mesh.addFace([nodes[0], nodes[2], nodes[3]]),
        mesh.addFace([nodes[1], nodes[2], nodes[3]]),
    ]
    for i, face in enumerate(faces, start=first_face):
        gid = mesh.addGroup(f"Face{i}", "Face")
        mesh.addGroupElements(gid, [face])
    return mesh


def _one_solid_mesh():
    return _tet(Fem.FemMesh(), 0.0, 1, 1)


def _two_solid_mesh():
    mesh = _tet(Fem.FemMesh(), 0.0, 1, 1)
    return _tet(mesh, 4.0, 2, 5)


class TestResultAttribution(unittest.TestCase):
    """
    What a result says about itself once the analysis is over.

    Every test here goes through the same three steps a solve does - build the
    mesh to solve, load a result of it into a pipeline, attribute the pipeline -
    without actually calling a solver, because what is under test is the
    attribution and not the solver that triggers it.
    """

    fcc_print("import TestResultAttribution")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestResultAttribution tests {2}\n{0}".format(
                100 * "*", 10 * "*", 42 * "*"
            )
        )

    # Building blocks
    # ###############

    def _analysis(self, name="Analysis", mesh=None, solids=1):
        """An analysis with a geometry of *solids* pieces, a mesh group and a mesh.

        The shape only has to carry the names - Solid1, Solid2, Component1 - the
        mesh groups are written in; nothing here reads its coordinates. So it is
        a row of boxes, one per solid the mesh knows about.
        """
        analysis = ObjectsFem.makeAnalysis(self.document, name)
        geometry = ObjectsFem.makeGeometryGroup(self.document, name + "Geometry")
        analysis.addObject(geometry)

        source = self.document.addObject("Part::Feature", name + "Part")
        boxes = [Part.makeBox(1, 1, 1, FreeCAD.Vector(4 * i, 0, 0)) for i in range(solids)]
        source.Shape = boxes[0] if solids == 1 else Part.makeCompound(boxes)
        imported = ObjectsFem.makeGeometryImport(self.document)
        imported.Import = [source]
        geometry.Group = [imported]

        group = ObjectsFem.makeMeshShapeGroup(self.document, geometry=geometry, analysis=analysis)
        holder = self.document.addObject("Fem::FemMeshObject", name + "Mesh")
        holder.FemMesh = mesh if mesh is not None else _one_solid_mesh()
        group.addObject(holder)

        self.document.recompute()
        return analysis, geometry, group

    def _material(self, analysis, geometry, name, elements, card_name="Steel"):
        material = ObjectsFem.makeMaterialSolid(self.document, name)
        card = material.Material
        card["Name"] = card_name
        material.Material = card
        if elements is not None:
            material.References = [(geometry, elements)]
        analysis.addObject(material)
        self.document.recompute()
        return material

    def _pipeline(self, analysis, fem_mesh=None, frames=1):
        """A pipeline holding a result computed on *fem_mesh*, not yet attributed."""
        if fem_mesh is None:
            fem_mesh = membertools.get_mesh_to_solve(analysis).FemMesh

        holder = self.document.addObject("Fem::FemMeshObject", "ResultMesh")
        holder.FemMesh = fem_mesh
        self.document.recompute()

        results = []
        for frame in range(frames):
            result = ObjectsFem.makeResultMechanical(self.document, f"Result{frame}")
            result.Mesh = holder
            nodes = holder.FemMesh.Nodes
            result.NodeNumbers = list(nodes.keys())
            result.DisplacementVectors = [FreeCAD.Vector(0, 0, 0)] * len(nodes)
            analysis.addObject(result)
            results.append(result)
        self.document.recompute()

        pipeline = self.document.addObject("Fem::FemPostPipeline", "Pipeline")
        if frames == 1:
            pipeline.load(results[0])
        else:
            pipeline.load(results, [float(i) for i in range(frames)], FreeCAD.Units.Unit(), "Steps")
        analysis.addObject(pipeline)
        self.document.recompute()
        return pipeline

    def _attribution(self, pipeline):
        """What a filter placed on *pipeline* can read off it."""
        filter_obj = ObjectsFem.makePostFilterAttribute(self.document, pipeline)
        self.document.recompute()
        return filter_obj, post_attributefilter.Attribution(filter_obj.getInputData())

    @staticmethod
    def _cells(obj):
        obj.recompute()
        return obj.getOutputAlgorithm().GetOutputDataObject(0).GetNumberOfCells()

    # The stored data
    # ###############

    def test_a_fresh_result_names_the_entity_of_every_cell(self):
        analysis, geometry, _ = self._analysis(mesh=_two_solid_mesh(), solids=2)
        mesh = membertools.get_mesh_to_solve(analysis)
        pipeline = self._pipeline(analysis, mesh.FemMesh)
        pipeline.attribute(mesh, analysis)

        _, attribution = self._attribution(pipeline)
        self.assertEqual(attribution.entities, ["Solid1", "Solid2"])
        self.assertEqual(attribution.unattributed_cells, 0)

    def test_component_and_material_are_stored_resolved(self):
        analysis, geometry, _ = self._analysis(mesh=_two_solid_mesh(), solids=2)
        self._material(analysis, geometry, "Steel", ["Solid1"], "CalculiX-Steel")
        mesh = membertools.get_mesh_to_solve(analysis)
        pipeline = self._pipeline(analysis, mesh.FemMesh)
        pipeline.attribute(mesh, analysis)

        _, attribution = self._attribution(pipeline)
        self.assertIn("Component", attribution.categories)
        self.assertIn("Material", attribution.categories)
        # A material of the analysis itself is keyed by its object name and
        # labelled with the card it carries, the same way the colouring keys it.
        self.assertEqual(attribution.categories["Material"]["Solid1"], ("Steel", "CalculiX-Steel"))
        self.assertEqual(attribution.categories["Component"]["Solid1"][0], "Component1")
        self.assertEqual(attribution.categories["Component"]["Solid2"][0], "Component2")

    def test_a_material_naming_nothing_claims_what_is_left(self):
        analysis, geometry, _ = self._analysis(mesh=_two_solid_mesh(), solids=2)
        self._material(analysis, geometry, "Named", ["Solid1"], "Named")
        self._material(analysis, geometry, "Rest", None, "Rest")
        mesh = membertools.get_mesh_to_solve(analysis)
        pipeline = self._pipeline(analysis, mesh.FemMesh)
        pipeline.attribute(mesh, analysis)

        _, attribution = self._attribution(pipeline)
        materials = attribution.categories["Material"]
        self.assertEqual(materials["Solid1"][1], "Named")
        self.assertEqual(materials["Solid2"][1], "Rest")

    def test_attribution_survives_a_reload_without_mesh_or_geometry(self):
        analysis, geometry, _ = self._analysis(mesh=_two_solid_mesh(), solids=2)
        self._material(analysis, geometry, "Steel", ["Solid1"], "CalculiX-Steel")
        mesh = membertools.get_mesh_to_solve(analysis)
        pipeline = self._pipeline(analysis, mesh.FemMesh)
        pipeline.attribute(mesh, analysis)

        path = os.path.join(tempfile.mkdtemp(), "attribution.FCStd")
        self.document.saveAs(path)
        name = self.document.Name
        FreeCAD.closeDocument(name)
        self.document = FreeCAD.openDocument(path)

        # Everything the attribution was resolved from goes away; the answer has
        # to stand on its own, or it was never worth storing.
        for obj in list(self.document.Objects):
            if obj.isDerivedFrom("Fem::FemMeshObject") or obj.isDerivedFrom("Fem::FemGeometry"):
                self.document.removeObject(obj.Name)
        self.document.recompute()

        pipeline = self.document.getObject("Pipeline")
        _, attribution = self._attribution(pipeline)
        self.assertEqual(attribution.entities, ["Solid1", "Solid2"])
        self.assertEqual(attribution.categories["Material"]["Solid1"][1], "CalculiX-Steel")

    def test_a_later_material_does_not_reach_an_old_result(self):
        analysis, geometry, _ = self._analysis(mesh=_two_solid_mesh(), solids=2)
        self._material(analysis, geometry, "First", ["Solid1"], "First")
        mesh = membertools.get_mesh_to_solve(analysis)
        pipeline = self._pipeline(analysis, mesh.FemMesh)
        pipeline.attribute(mesh, analysis)

        material = self.document.getObject("First")
        card = material.Material
        card["Name"] = "Second"
        material.Material = card
        self.document.recompute()

        _, attribution = self._attribution(pipeline)
        self.assertEqual(attribution.categories["Material"]["Solid1"][1], "First")

    def test_deleting_the_mesh_leaves_the_pipeline_attributed(self):
        analysis, _, group = self._analysis(mesh=_two_solid_mesh(), solids=2)
        mesh = membertools.get_mesh_to_solve(analysis)
        pipeline = self._pipeline(analysis, mesh.FemMesh)
        pipeline.attribute(mesh, analysis)

        for child in list(group.Group):
            self.document.removeObject(child.Name)
        self.document.removeObject(group.Name)
        self.document.recompute()

        _, attribution = self._attribution(pipeline)
        self.assertEqual(attribution.entities, ["Solid1", "Solid2"])

    def test_a_result_that_was_never_attributed_carries_nothing(self):
        analysis, _, _ = self._analysis(mesh=_two_solid_mesh(), solids=2)
        pipeline = self._pipeline(analysis)

        filter_obj, attribution = self._attribution(pipeline)
        self.assertEqual(attribution.entities, [])
        self.assertEqual(self._cells(filter_obj), self._cells(pipeline))

    def test_every_frame_of_a_multiframe_result_is_attributed(self):
        analysis, _, _ = self._analysis(mesh=_two_solid_mesh(), solids=2)
        mesh = membertools.get_mesh_to_solve(analysis)
        pipeline = self._pipeline(analysis, mesh.FemMesh, frames=3)
        pipeline.attribute(mesh, analysis)

        for frame in range(3):
            pipeline.Frame = frame
            self.document.recompute()
            _, attribution = self._attribution(pipeline)
            self.assertEqual(attribution.entities, ["Solid1", "Solid2"], f"frame {frame}")

    def test_cells_the_mesh_does_not_hold_stay_unattributed(self):
        analysis, _, _ = self._analysis(mesh=_one_solid_mesh())
        mesh = membertools.get_mesh_to_solve(analysis)

        # A result mesh that reaches past the model, the way a beam expanded to
        # solid elements does. The extra cell belongs to nothing that was meshed
        # and has to come out saying so rather than borrowing a neighbour.
        wider = _tet(Fem.FemMesh(), 0.0, 1, 1)
        base = wider.NodeCount
        wider.addNode(50, 0, 0, base + 1)
        wider.addNode(51, 0, 0, base + 2)
        wider.addNode(50, 1, 0, base + 3)
        wider.addNode(50, 0, 1, base + 4)
        wider.addVolume([base + 1, base + 2, base + 3, base + 4])

        pipeline = self._pipeline(analysis, wider)
        pipeline.attribute(mesh, analysis)

        _, attribution = self._attribution(pipeline)
        self.assertEqual(attribution.entities, ["Solid1"])
        self.assertEqual(attribution.unattributed_cells, 1)

    # Imports
    # #######

    def _import(self, host, source, name, offset):
        """Place *source* in *host*, moved out of the way of what is there.

        The offset is not decoration: attribution matches a result cell to the
        assembly cell it sits on, and two instances left on top of each other
        would be one cell as far as any mesh is concerned.
        """
        imp = ObjectsFem.makeAnalysisImport(self.document, name)
        imp.Analysis = source
        imp.Placement = FreeCAD.Placement(offset, FreeCAD.Rotation())
        importtools.wire_import(host, imp)
        self.document.recompute()
        return imp

    def test_two_instances_of_one_source_stay_apart(self):
        source, _, _ = self._analysis("Leg")
        host, _, _ = self._analysis("Table")
        self._import(host, source, "Leg1", FreeCAD.Vector(20, 0, 0))
        self._import(host, source, "Leg2", FreeCAD.Vector(40, 0, 0))

        mesh = membertools.get_mesh_to_solve(host)
        pipeline = self._pipeline(host, mesh.FemMesh)
        pipeline.attribute(mesh, host)

        _, attribution = self._attribution(pipeline)
        self.assertIn("Leg1.Solid1", attribution.entities)
        self.assertIn("Leg2.Solid1", attribution.entities)

    def test_a_nested_import_carries_the_whole_path(self):
        inner, _, _ = self._analysis("Inner")
        middle, _, _ = self._analysis("Middle")
        outer, _, _ = self._analysis("Outer")
        self._import(middle, inner, "Inner1", FreeCAD.Vector(20, 0, 0))
        self._import(outer, middle, "Middle1", FreeCAD.Vector(0, 40, 0))

        mesh = membertools.get_mesh_to_solve(outer)
        pipeline = self._pipeline(outer, mesh.FemMesh)
        pipeline.attribute(mesh, outer)

        _, attribution = self._attribution(pipeline)
        self.assertIn("Middle1.Inner1.Solid1", attribution.entities)

    # The filter
    # ##########

    def test_the_filter_keeps_only_what_is_checked(self):
        analysis, _, _ = self._analysis(mesh=_two_solid_mesh(), solids=2)
        mesh = membertools.get_mesh_to_solve(analysis)
        pipeline = self._pipeline(analysis, mesh.FemMesh)
        pipeline.attribute(mesh, analysis)

        filter_obj, _ = self._attribution(pipeline)
        self.assertEqual(self._cells(pipeline), 2)

        filter_obj.Elements = ["Solid1"]
        self.assertEqual(self._cells(filter_obj), 1)

        filter_obj.Elements = ["Solid2"]
        self.assertEqual(self._cells(filter_obj), 1)

    def test_the_filter_passes_everything_through_when_it_cannot_narrow(self):
        analysis, _, _ = self._analysis(mesh=_two_solid_mesh(), solids=2)
        mesh = membertools.get_mesh_to_solve(analysis)
        pipeline = self._pipeline(analysis, mesh.FemMesh)
        pipeline.attribute(mesh, analysis)

        filter_obj, _ = self._attribution(pipeline)
        whole = self._cells(pipeline)

        for elements in ([], ["Solid1", "Solid2"], ["NoSuchThing"]):
            filter_obj.Elements = elements
            self.assertEqual(self._cells(filter_obj), whole, f"for {elements}")

    def test_the_filter_offers_only_the_attributes_the_result_carries(self):
        analysis, geometry, _ = self._analysis(mesh=_two_solid_mesh(), solids=2)
        mesh = membertools.get_mesh_to_solve(analysis)
        pipeline = self._pipeline(analysis, mesh.FemMesh)
        pipeline.attribute(mesh, analysis)

        filter_obj, _ = self._attribution(pipeline)
        offered = filter_obj.getEnumerationsOfProperty("Attribute")
        self.assertIn("Subelement", offered)
        self.assertIn("Component", offered)
        # No material was assigned, so there is no material table to group by.
        self.assertNotIn("Material", offered)
