# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Stefan Tröger <stefantroeger@gmx.net>
# SPDX-FileNotice: Part of the FreeCAD project.

################################################################################
#                                                                              #
#   FreeCAD is free software: you can redistribute it and/or modify            #
#   it under the terms of the GNU Lesser General Public License as             #
#   published by the Free Software Foundation, either version 2.1              #
#   of the License, or (at your option) any later version.                     #
#                                                                              #
#   FreeCAD is distributed in the hope that it will be useful,                 #
#   but WITHOUT ANY WARRANTY; without even the implied warranty                #
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                    #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with FreeCAD. If not, see https://www.gnu.org/licenses       #
#                                                                              #
################################################################################

__title__ = "GMSH FEM unit tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest
import importlib
import shutil
import subprocess
import tempfile
from os.path import join

import FreeCAD
import Part

import Fem
import ObjectsFem
from femexamples import manager
from femtools.femutils import is_derived_from
from femmesh import entityorder
from femmesh import gmshtools
from . import support_utils as testtools
from .support_utils import fcc_print


def generate_gmesh_samples_from_example_doc(doc, datapath):
    # used to process a example file into vtk mesh files and store it in datapath
    # this is intended as manual step to generate the correct meshes to witch the tests
    # later compare. Run this only if you want to recreate the golden test meshes which
    # are added into the source code
    # Note: Run this from the source folder!
    #
    # from within freecad with the example files open, run:
    # from femtest.app import test_gmsh
    # test_gmsh.generate_gmesh_samples_from_example_doc(App.ActiveDocument, path_to_src_data_folder)

    # collect all gmsh objects
    gmsh = []
    for obj in doc.Objects:
        if is_derived_from(obj, "Fem::FemMeshGmsh"):
            gmsh.append(obj)

    # process all gmsh objects
    for mesh in gmsh:

        # 1. Run gmsh to create the mesh
        tool = gmshtools.GmshTools(mesh)
        tool.create_mesh()

        # 2. Derive file name from group name and build path
        filename = mesh.getParentGroup().Label + ".vtk"
        path = join(datapath, filename)

        # find the vtk file gmsh created and copy it into the location
        # (we do not export from FemMesh, as the exporter is extremely limited and reimport
        #  gives other results)
        shutil.copyfile(tool.temp_file_mesh, path)


class TestGMSHBase(unittest.TestCase):

    # ********************************************************************************************
    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    # ********************************************************************************************
    def tearDown(self):
        # tearDown is executed after every test
        FreeCAD.closeDocument(self.document.Name)

    # ********************************************************************************************
    def load_example_file(self, name):
        # opens a example file to process for testing
        module = importlib.import_module(f"femexamples.{name}")
        self.doc = module.setup(doc=self.document)

        if FreeCAD.GuiUp:
            import FreeCADGui

            FreeCADGui.ActiveDocument.ActiveView.sendMessage("ViewFit")

    def load_and_run_example_file(self, name):
        # opens and runs example file to process for testing
        self.doc = manager.run_example(name, run_solver=True, doc=self.document)

        if FreeCAD.GuiUp:
            import FreeCADGui

            FreeCADGui.ActiveDocument.ActiveView.sendMessage("ViewFit")

    def get_gmsh_objects(self):
        result = []
        for obj in self.doc.Objects:
            if is_derived_from(obj, "Fem::FemMeshGmsh"):
                result.append(obj)

        return result

    def execute_gmsh(self, obj):
        tool = gmshtools.GmshTools(obj)
        tool.create_mesh()

    # ********************************************************************************************
    def compare_exact_mesh_to_sample(self, mesh_obj):
        # compare generated mesh to sample to be the exact same. This should only be used for
        # meshing algorithms that guarantee to define exact node counts and locations, as well as
        # elements. If things can vary over gmsh versions this should not be used.

        # load the sample mesh we want to compare to
        name = mesh_obj.getParentGroup().Label
        path = join(testtools.get_fem_test_home_dir(), "gmsh", name + ".vtk")
        sample = Fem.FemMesh()
        sample.read(path)

        # test reading the test mesh
        mesh = mesh_obj.FemMesh

        self.assertEqual(
            mesh.NodeCount,
            sample.NodeCount,
            f"Generated mesh does not have the same Node count as the golden sample: {name}",
        )

        # compare node locations!
        for idx in range(1, mesh.NodeCount + 1):
            self.assertTrue(
                mesh.Nodes[idx].isEqual(sample.Nodes[idx], 1e-3),
                f"Generated mesh does not have the same Node locations as golden sample: {name}",
            )

        self.assertEqual(
            mesh.EdgeCount,
            sample.EdgeCount,
            f"Generated mesh does not have the same edge count as the golden sample: {name}",
        )

        self.assertEqual(
            mesh.TriangleCount,
            sample.TriangleCount,
            f"Generated mesh does not have the same triangle count as the golden sample: {name}",
        )

        self.assertEqual(
            mesh.QuadrangleCount,
            sample.QuadrangleCount,
            f"Generated mesh does not have the same quadrangle count as the golden sample: {name}",
        )

        self.assertEqual(
            mesh.PolygonCount,
            sample.PolygonCount,
            f"Generated mesh does not have the same polygon count as the golden sample: {name}",
        )

        self.assertEqual(
            mesh.VolumeCount,
            sample.VolumeCount,
            f"Generated mesh does not have the same volume count as the golden sample: {name}",
        )

        self.assertEqual(
            mesh.TetraCount,
            sample.TetraCount,
            f"Generated mesh does not have the same tetrahedra count as the golden sample: {name}",
        )

        self.assertEqual(
            mesh.HexaCount,
            sample.HexaCount,
            f"Generated mesh does not have the same hexahedra count as the golden sample: {name}",
        )

        self.assertEqual(
            mesh.PyramidCount,
            sample.PyramidCount,
            f"Generated mesh does not have the same pyramid count as the golden sample: {name}",
        )

        self.assertEqual(
            mesh.PrismCount,
            sample.PrismCount,
            f"Generated mesh does not have the same prism count as the golden sample: {name}",
        )

        self.assertEqual(
            mesh.PolyhedronCount,
            sample.PolyhedronCount,
            f"Generated mesh does not have the same polyhedra count as the golden sample: {name}",
        )

    def compare_fuzzy_mesh_to_sample(self, mesh_obj, allowed_diff=0.05):
        # compare generated mesh to sample to be the roughly the same. This accounts for slight variations
        # between gmsh versions. The meshes do not to be the exact same, but can vary slightly.
        #
        # allowed_diff is given as relation to 1 (5% = 0.05)

        # load the sample mesh we want to compare to
        name = mesh_obj.getParentGroup().Label
        path = join(testtools.get_fem_test_home_dir(), "gmsh", name + ".vtk")
        sample = Fem.FemMesh()
        sample.read(path)

        # test reading the test mesh
        mesh = mesh_obj.FemMesh

        def diff(val1, val2):
            if val2 == 0:
                if val1 == 0:
                    return 0
                else:
                    return 1

            return abs(1 - val1 / val2)

        self.assertLess(
            diff(mesh.NodeCount, sample.NodeCount),
            allowed_diff,
            f"Generated mesh does not have the same Node count as the golden sample: {name}",
        )

        self.assertLess(
            diff(mesh.EdgeCount, sample.EdgeCount),
            allowed_diff,
            f"Generated mesh does not have the same edge count as the golden sample: {name}",
        )

        self.assertLess(
            diff(mesh.TriangleCount, sample.TriangleCount),
            allowed_diff,
            f"Generated mesh does not have the same triangle count as the golden sample: {name}",
        )

        self.assertLess(
            diff(mesh.QuadrangleCount, sample.QuadrangleCount),
            allowed_diff,
            f"Generated mesh does not have the same quadrangle count as the golden sample: {name}",
        )

        self.assertLess(
            diff(mesh.PolygonCount, sample.PolygonCount),
            allowed_diff,
            f"Generated mesh does not have the same polygon count as the golden sample: {name}",
        )

        self.assertLess(
            diff(mesh.VolumeCount, sample.VolumeCount),
            allowed_diff,
            f"Generated mesh does not have the same volume count as the golden sample: {name}",
        )

        self.assertLess(
            diff(mesh.TetraCount, sample.TetraCount),
            allowed_diff,
            f"Generated mesh does not have the same tetrahedra count as the golden sample: {name}",
        )

        self.assertLess(
            diff(mesh.HexaCount, sample.HexaCount),
            allowed_diff,
            f"Generated mesh does not have the same hexahedra count as the golden sample: {name}",
        )

        self.assertLess(
            diff(mesh.PyramidCount, sample.PyramidCount),
            allowed_diff,
            f"Generated mesh does not have the same pyramid count as the golden sample: {name}",
        )

        self.assertLess(
            diff(mesh.PrismCount, sample.PrismCount),
            allowed_diff,
            f"Generated mesh does not have the same prism count as the golden sample: {name}",
        )

        self.assertLess(
            diff(mesh.PolyhedronCount, sample.PolyhedronCount),
            allowed_diff,
            f"Generated mesh does not have the same polyhedra count as the golden sample: {name}",
        )


# ************************************************************************************************
# ************************************************************************************************
class TestGMSHTransfinite(TestGMSHBase):
    fcc_print("import TestGMSHTransfinite")

    # ********************************************************************************************
    def test_00print(self):
        # since method name starts with 00 this will be run first
        # this test just prints a line with stars

        fcc_print(
            "\n{0}\n{1} run FEM TestGMSHTransfinite tests {2}\n{0}".format(
                100 * "*", 10 * "*", 56 * "*"
            )
        )

    # ********************************************************************************************
    def test_GMSHTransfiniteManual(self):

        try:
            self.load_example_file("gmsh_transfinite_manual")
            gmshs = self.get_gmsh_objects()
            for gmsh in gmshs:
                self.execute_gmsh(gmsh)
                self.compare_exact_mesh_to_sample(gmsh)

                if FreeCAD.GuiUp:
                    import FreeCADGui

                    FreeCADGui.updateGui()
        except gmshtools.GmshError:
            # this exception is thrown if gmsh is not available. We pass in this case
            pass

    def test_GMSHTransfiniteAutomation(self):

        try:
            self.load_example_file("gmsh_transfinite_automation")
            gmshs = self.get_gmsh_objects()
            for gmsh in gmshs:
                self.execute_gmsh(gmsh)
                self.compare_exact_mesh_to_sample(gmsh)

                if FreeCAD.GuiUp:
                    import FreeCADGui

                    FreeCADGui.updateGui()

        except gmshtools.GmshError:
            # this exception is thrown if gmsh is not available. We pass in this case
            pass


class TestGMSHEntityOrder(TestGMSHBase):
    fcc_print("import TestGMSHEntityOrder")

    # ********************************************************************************************
    def test_00print(self):
        # since method name starts with 00 this will be run first
        # this test just prints a line with stars

        fcc_print(
            "\n{0}\n{1} run FEM TestGMSHEntityOrder tests {2}\n{0}".format(
                100 * "*", 10 * "*", 54 * "*"
            )
        )

    # ********************************************************************************************
    def entity_order_shapes(self):
        # shapes whose entity numbering FreeCAD and Gmsh disagree about, plus the
        # single dimension shapes they used to agree about

        box = Part.makeBox(10, 10, 10)
        plane = Part.makePlane(10, 10, FreeCAD.Vector(20, 0, 5))
        line = Part.makeLine(FreeCAD.Vector(0, 40, 0), FreeCAD.Vector(10, 40, 0))
        vertex = Part.Vertex(FreeCAD.Vector(0, 60, 0))
        cylinder = Part.makeCylinder(3, 10, FreeCAD.Vector(0, -30, 0))
        shell = Part.Shell(
            [
                Part.makePlane(5, 5, FreeCAD.Vector(0, 80, 0)),
                Part.makePlane(5, 5, FreeCAD.Vector(5, 80, 0)),
            ]
        )
        wire = Part.Wire(
            [
                Part.makeLine(FreeCAD.Vector(0, 100, 0), FreeCAD.Vector(5, 100, 0)),
                Part.makeLine(FreeCAD.Vector(5, 100, 0), FreeCAD.Vector(5, 105, 0)),
            ]
        )
        hollow = Part.makeBox(10, 10, 10, FreeCAD.Vector(0, 140, 0)).cut(
            Part.makeSphere(3, FreeCAD.Vector(5, 145, 5))
        )

        return {
            "solid": box,
            "solid_with_void": hollow,
            "face_before_solid": Part.makeCompound([plane, box]),
            "solid_before_face": Part.makeCompound([box, plane]),
            "three_dimensions": Part.makeCompound([plane, line, box]),
            "shell_and_solid": Part.makeCompound([shell, box]),
            "nested_compound": Part.makeCompound([Part.makeCompound([plane, line]), box]),
            "every_kind": Part.makeCompound([vertex, wire, plane, shell, line, box, cylinder]),
        }

    def gmsh_entities(self, binary, shape, workdir, name):
        # entity tags Gmsh binds for a shape, with the bounding box of each, so
        # the entity behind a tag can be recognized without trusting any numbering

        kinds = {"Solid": "Volume", "Face": "Surface", "Edge": "Curve", "Vertex": "Point"}

        brep = join(workdir, name + ".brep")
        shape.exportBrep(brep)

        geo = join(workdir, name + ".geo")
        with open(geo, "w") as handle:
            handle.write(f'Merge "{brep}";\n')
            for kind, gmsh_kind in kinds.items():
                handle.write(f"entities[] = {gmsh_kind}{{:}};\n")
                handle.write("For i In {0:#entities[]-1}\n")
                handle.write("  tag = entities[i];\n")
                handle.write(f"  bb[] = BoundingBox {gmsh_kind}{{tag}};\n")
                handle.write(
                    f'  Printf("{kind} %g box %.9g %.9g %.9g %.9g %.9g %.9g", tag,'
                    " bb[0], bb[1], bb[2], bb[3], bb[4], bb[5]);\n"
                )
                handle.write("EndFor\n")
            handle.write("Exit;\n")

        output = subprocess.run(
            [binary, geo, "-"], capture_output=True, text=True, cwd=workdir
        ).stdout

        entities = {kind: [] for kind in kinds}
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 9 and parts[0] in kinds and parts[2] == "box":
                entities[parts[0]].append(
                    (int(float(parts[1])), tuple(float(v) for v in parts[3:9]))
                )
        for kind in entities:
            entities[kind].sort(key=lambda entity: entity[0])
        return entities

    def gmsh_binary(self):
        # the binary gmshtools would run, None when Gmsh is not installed

        probe = ObjectsFem.makeMeshGmsh(self.document, "GmshBinaryProbe")
        try:
            tool = gmshtools.GmshTools(probe)
            tool.get_gmsh_command()
            return tool.gmsh_bin
        except gmshtools.GmshError:
            return None

    # ********************************************************************************************
    def test_EntityOrderMatchesGmsh(self):
        # This test pins an assumption FreeCAD makes about Gmsh, and it is the only
        # thing between that assumption and silently wrong meshes.
        #
        # FreeCAD writes entity numbers into the geo file: Physical groups name the
        # geometry entity a mesh group stands for, and refinements, boundary layers
        # and transfinite settings select the entities they act on. Those numbers
        # are Gmsh entity tags, computed by femmesh.entityorder, which mimics the
        # order in which Gmsh binds what it reads from a BREP. Gmsh does not promise
        # that order, so this test compares the prediction against a real Gmsh.
        #
        # WHAT IT MEANS WHEN THIS FAILS: Gmsh changed how it numbers imported
        # entities, and femmesh.entityorder no longer describes it.
        #
        # WHAT THE CONSEQUENCES ARE: nothing crashes and no other test needs to
        # fail. Meshing keeps working, but every entity number FreeCAD writes then
        # names a different entity than intended. Mesh groups carry the name of the
        # wrong geometry entity, so materials, constraints and element dimensions
        # are applied to the wrong faces, the solver deck is wrong without saying
        # so, refinements act on the wrong entities, and the mesh is coloured and
        # hidden by the wrong component in the view.
        #
        # WHAT TO DO: do not relax this test and do not delete the shapes it checks.
        # Read the reported entity from the failure message, work out the new order,
        # and update femmesh.entityorder to mimic it. If the order turns out not to
        # be predictable any more, the mimicking approach itself has to go and the
        # mapping has to be queried from Gmsh instead, see the comment in
        # femmesh/entityorder.py.

        binary = self.gmsh_binary()
        if binary is None:
            # no Gmsh installed, same handling as the other tests in this file
            return

        with tempfile.TemporaryDirectory() as workdir:
            for name, shape in self.entity_order_shapes().items():
                predicted = entityorder.entity_order(shape)
                actual = self.gmsh_entities(binary, shape, workdir, name)
                subshapes = {
                    "Solid": shape.Solids,
                    "Face": shape.Faces,
                    "Edge": shape.Edges,
                    "Vertex": shape.Vertexes,
                }

                for kind in entityorder.ENTITY_KINDS:
                    self.assertEqual(
                        len(predicted[kind]),
                        len(actual[kind]),
                        f"Gmsh binds {len(actual[kind])} {kind} entities of the shape "
                        f"'{name}', femmesh.entityorder predicts {len(predicted[kind])}",
                    )

                    for index, (tag, box) in zip(predicted[kind], actual[kind]):
                        bound = subshapes[kind][index - 1].BoundBox
                        expected = (
                            bound.XMin,
                            bound.YMin,
                            bound.ZMin,
                            bound.XMax,
                            bound.YMax,
                            bound.ZMax,
                        )
                        for got, want in zip(box, expected):
                            self.assertAlmostEqual(
                                got,
                                want,
                                places=4,
                                msg=(
                                    f"Gmsh gives the tag {tag} of the shape '{name}' to an "
                                    f"entity at {box}, femmesh.entityorder predicts "
                                    f"{kind}{index} at {expected}. Gmsh changed the order in "
                                    "which it binds imported entities, read the comment on "
                                    "this test"
                                ),
                            )

    def test_EntityOrderOfMixedCompound(self):
        # The rule femmesh.entityorder implements, spelled out on the shape that
        # exposed it: a compound of a plane and a box, where FreeCAD numbers the
        # plane Face1 because it comes first in the compound, while Gmsh numbers the
        # six faces of the box first because it takes solids before free faces.
        #
        # Unlike test_EntityOrderMatchesGmsh this needs no Gmsh installation, it
        # only guards the implementation against being changed by accident. A
        # failure here means the prediction changed; whether the new one is right is
        # what test_EntityOrderMatchesGmsh answers.

        box = Part.makeBox(10, 10, 10)
        plane = Part.makePlane(10, 10, FreeCAD.Vector(20, 0, 5))
        compound = Part.makeCompound([plane, box])

        order = entityorder.entity_order(compound)
        self.assertEqual(order["Solid"], [1])
        self.assertEqual(order["Face"], [2, 3, 4, 5, 6, 7, 1])

        tags = entityorder.entity_tags(compound)
        self.assertEqual(tags["Face"][1], 7, "the free plane is the last surface for Gmsh")
        self.assertEqual(tags["Face"][2], 1, "the first box face is the first surface for Gmsh")

    def test_PhysicalGroupsUseGmshTags(self):
        # The Physical statements are what carries a geometry name into the mesh, so
        # they have to hold Gmsh tags rather than FreeCAD indices. Needs no Gmsh
        # installation, the geo data is built without running the mesher.
        #
        # A failure means the mapping is not applied when the groups are built, and
        # mesh groups end up named after the wrong geometry entity.

        part_obj = self.document.addObject("Part::Feature", "Geometry")
        part_obj.Shape = Part.makeCompound(
            [Part.makePlane(10, 10, FreeCAD.Vector(20, 0, 5)), Part.makeBox(10, 10, 10)]
        )
        mesh_obj = ObjectsFem.makeMeshGmsh(self.document, "Mesh")
        mesh_obj.Shape = part_obj
        self.document.recompute()

        tool = gmshtools.GmshTools(mesh_obj)
        tool.get_dimension()
        tool.get_group_data()

        entity_ids = {
            physical["global"]: physical["entity_id"]
            for physical in tool.group_physicals
            if physical["phy_shape"] == "Surface"
        }
        self.assertEqual(entity_ids["Face1"], 7, "the plane is surface 7 for Gmsh")
        self.assertEqual(entity_ids["Face2"], 1, "the first box face is surface 1 for Gmsh")

    def test_MeshGroupsMatchGeometry(self):
        # End to end check of what the entity numbering is there for: every mesh
        # group has to hold the mesh of the geometry entity it is named after.
        #
        # A failure means a mesh group is named after a different entity than the
        # one it covers. Everything that resolves a reference through mesh groups -
        # materials, constraints, element dimensions, the mesh colouring in the view
        # - then works on the wrong part of the model without reporting anything.

        if self.gmsh_binary() is None:
            # no Gmsh installed, same handling as the other tests in this file
            return

        part_obj = self.document.addObject("Part::Feature", "Geometry")
        part_obj.Shape = Part.makeCompound(
            [Part.makePlane(10, 10, FreeCAD.Vector(20, 0, 5)), Part.makeBox(10, 10, 10)]
        )
        mesh_obj = ObjectsFem.makeMeshGmsh(self.document, "Mesh")
        mesh_obj.Shape = part_obj
        mesh_obj.CharacteristicLengthMax = 10
        self.document.recompute()

        gmshtools.GmshTools(mesh_obj).create_mesh()
        femmesh = mesh_obj.FemMesh
        self.assertTrue(femmesh.GroupCount > 0, "meshing produced no groups to check")

        checked = 0
        for group in femmesh.Groups:
            name = femmesh.getGroupName(group)
            if not (name.startswith("Face") and name[4:].isdigit()):
                continue

            face = part_obj.Shape.Faces[int(name[4:]) - 1]
            on_face = set(femmesh.getNodesByFace(face))
            nodes = set()
            for element in femmesh.getGroupElements(group):
                nodes.update(femmesh.getElementNodes(element))

            self.assertTrue(
                nodes and nodes <= on_face,
                f"the mesh group {name} does not lie on the geometry {name}, it covers "
                "a different face of the shape",
            )
            checked += 1

        self.assertEqual(checked, 7, "not all faces of the compound ended up as mesh groups")

    def test_ComponentSelectionKeepsGeometryNames(self):
        # Meshing a single component exports a shape of its own, so an entity
        # carries three numbers: its index in the geometry, its index in the
        # exported shape and the tag Gmsh gives it. Only the first one names the
        # entity a group stands for, and it is the one that has to end up on the
        # group while the geo file gets the last one.
        #
        # A failure means the mesh of a component is named after the entities of
        # the exported piece rather than of the geometry. Every reference to that
        # component then resolves to whatever geometry entity happens to carry the
        # number, so a mesh group is combined with the wrong part of the model.

        if self.gmsh_binary() is None:
            # no Gmsh installed, same handling as the other tests in this file
            return

        source = self.document.addObject("Part::Feature", "Source")
        source.Shape = Part.makeCompound(
            [Part.makePlane(10, 10, FreeCAD.Vector(20, 0, 5)), Part.makeBox(10, 10, 10)]
        )
        geometry = ObjectsFem.makeGeometryGroup(self.document)
        step = ObjectsFem.makeGeometryImport(self.document)
        step.Import = [source]
        geometry.Group = [step]
        self.document.recompute()

        # the component holding the plane, the one Gmsh numbers last as long as
        # the solid is meshed along with it
        plane_component = None
        for index in range(geometry.getComponentCount()):
            toplevel = geometry.getToplevelElements(index)
            if all(name.startswith("Face") for name in toplevel):
                plane_component = index + 1
        self.assertIsNotNone(plane_component, "the imported geometry has no free face")

        mesh_obj = ObjectsFem.makeMeshGmsh(self.document, "Mesh")
        mesh_obj.Components = (geometry, [f"Component{plane_component}"])
        mesh_obj.CharacteristicLengthMax = 10
        self.document.recompute()

        gmshtools.GmshTools(mesh_obj).create_mesh()
        femmesh = mesh_obj.FemMesh

        faces = [
            femmesh.getGroupName(group)
            for group in femmesh.Groups
            if femmesh.getGroupName(group).startswith("Face")
        ]
        self.assertEqual(len(faces), 1, "meshing one free face has to give one face group")

        face = geometry.Shape.Faces[int(faces[0][4:]) - 1]
        self.assertAlmostEqual(
            face.Area,
            100.0,
            places=4,
            msg=f"the mesh group {faces[0]} names a geometry face that is not the meshed plane",
        )

        # The other direction: refinements, boundary layers and transfinite
        # settings select entities of the geometry, and the geo file needs the tag
        # of the same entity in the exported shape, here the only surface there.
        tool = gmshtools.GmshTools(mesh_obj)
        self.assertEqual(
            tool._gmsh_id("Face", int(faces[0][4:])),
            1,
            f"the geometry face {faces[0]} is the only surface of the exported shape, a "
            "refinement on it would otherwise be written for a different entity",
        )


class TestGMSHRefinements(TestGMSHBase):
    fcc_print("import TestGMSHRefinements")

    # ********************************************************************************************
    def test_00print(self):
        # since method name starts with 00 this will be run first
        # this test just prints a line with stars

        fcc_print(
            "\n{0}\n{1} run FEM TestGMSHRefinement tests {2}\n{0}".format(
                100 * "*", 10 * "*", 56 * "*"
            )
        )

    # ********************************************************************************************
    def test_GMSHAdaptiv(self):

        try:
            self.load_and_run_example_file("gmsh_adaptive")
            gmshs = self.get_gmsh_objects()
            for gmsh in gmshs:
                # increased fuzzy factor, as man refinements mean small differences add up
                self.compare_fuzzy_mesh_to_sample(gmsh, 0.1)
        except gmshtools.GmshError:
            # this exception is thrown if gmsh is not available. We pass in this case
            pass
