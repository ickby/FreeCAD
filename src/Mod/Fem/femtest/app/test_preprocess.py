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

"""Unit tests for the FEM preprocessing foundation (geometry, merge, export)."""

__title__ = "FEM preprocessing foundation tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import os
import tempfile
import unittest

import FreeCAD
import Part

import Fem
import ObjectsFem

from .support_utils import fcc_print


def _box():
    return Part.makeBox(10, 10, 10)


def _face_xy():
    return Part.makePlane(5, 5)


def _make_tet_mesh():
    """Single tetrahedron volume plus surface triangles."""
    mesh = Fem.FemMesh()
    mesh.addNode(0, 0, 0, 1)
    mesh.addNode(1, 0, 0, 2)
    mesh.addNode(0, 1, 0, 3)
    mesh.addNode(0, 0, 1, 4)
    vol = mesh.addVolume([1, 2, 3, 4])
    f1 = mesh.addFace([1, 2, 3])
    f2 = mesh.addFace([1, 2, 4])
    f3 = mesh.addFace([1, 3, 4])
    f4 = mesh.addFace([2, 3, 4])
    g_solid = mesh.addGroup("Solid1", "Volume")
    mesh.addGroupElements(g_solid, [vol])
    for name, face in (("Face1", f1), ("Face2", f2), ("Face3", f3), ("Face4", f4)):
        gid = mesh.addGroup(name, "Face")
        mesh.addGroupElements(gid, [face])
    return mesh, vol, [f1, f2, f3, f4]


def _exported_element_ids(mesh, elem_param):
    """Element ids written to an ABAQUS input deck, keyed by element type."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "mesh.inp")
        mesh.writeABAQUS(path, elem_param, False)
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()

    by_type = {}
    current = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("*"):
            current = None
            if stripped.upper().startswith("*ELEMENT"):
                for part in stripped.split(","):
                    key, _, value = part.partition("=")
                    if key.strip().lower() == "type":
                        current = value.strip()
        elif current and stripped:
            by_type.setdefault(current, []).append(int(stripped.split(",")[0]))
    return {key: sorted(ids) for key, ids in by_type.items()}


def _vtk_cells_with_groups(mesh, highest, index_map):
    """(cell type, group id) of every cell in a VTK export, sorted."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "mesh.vtk")
        mesh.write(
            path,
            highest=highest,
            vtk_cell_group_array="group",
            vtk_group_id_map=index_map,
        )
        with open(path, encoding="utf-8") as fh:
            tokens = fh.read().split()

    types_at = tokens.index("CELL_TYPES")
    count = int(tokens[types_at + 1])
    cell_types = [int(t) for t in tokens[types_at + 2 : types_at + 2 + count]]
    # "group 1 <count> int" followed by one value per cell
    group_at = tokens.index("group")
    groups = [int(v) for v in tokens[group_at + 4 : group_at + 4 + count]]
    return sorted(zip(cell_types, groups))


def _make_tri_mesh(group_name="Face12"):
    """Free triangular face mesh (shell)."""
    mesh = Fem.FemMesh()
    mesh.addNode(10, 0, 0, 1)
    mesh.addNode(11, 0, 0, 2)
    mesh.addNode(10, 1, 0, 3)
    face = mesh.addFace([1, 2, 3])
    gid = mesh.addGroup(group_name, "Face")
    mesh.addGroupElements(gid, [face])
    return mesh, face


class TestFemGeometry(unittest.TestCase):
    fcc_print("import TestFemGeometry")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestFemGeometry tests {2}\n{0}".format(
                100 * "*", 10 * "*", 55 * "*"
            )
        )

    def test_component_detection_solid(self):
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = _box()
        self.document.recompute()
        self.assertEqual(geom.getComponentCount(), 1)
        tops = geom.getToplevelElements(0)
        self.assertTrue(any(t.startswith("Solid") for t in tops))
        for t in tops:
            if t.startswith("Solid"):
                self.assertEqual(geom.getGeometricDimension(t), 3)
                self.assertEqual(geom.getAnalysisDimension(t), 3)

    def test_component_detection_mixed(self):
        """Disconnected box + free face → components with dims 3 and 2."""
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        face = _face_xy()
        face.translate(FreeCAD.Vector(50, 0, 0))
        geom.Shape = Part.makeCompound([_box(), face])
        self.document.recompute()
        self.assertGreaterEqual(geom.getComponentCount(), 2)

        dims = set()
        for i in range(geom.getComponentCount()):
            for t in geom.getToplevelElements(i):
                d = geom.getGeometricDimension(t)
                if d >= 0:
                    dims.add(d)
        self.assertIn(3, dims)
        self.assertIn(2, dims)

    def test_dimension_override(self):
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = _box()
        self.document.recompute()
        tops = [t for t in geom.getToplevelElements(0) if t.startswith("Solid")]
        self.assertTrue(tops)
        solid = tops[0]
        self.assertEqual(geom.getAnalysisDimension(solid), 3)
        geom.DimensionOverride = {solid: "2"}
        self.assertEqual(geom.getAnalysisDimension(solid), 2)
        self.assertEqual(geom.getGeometricDimension(solid), 3)

    def test_get_subshapes_component(self):
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = _box()
        self.document.recompute()
        # Component1 must resolve (prototype substr/off-by-one bug)
        if hasattr(geom, "getSubShapes"):
            shapes = geom.getSubShapes("Component1")
            self.assertTrue(len(shapes) >= 1)
        else:
            sub = geom.getSubObject("Component1")
            self.assertIsNotNone(sub)

    def test_get_subshapes_rejects_bad_component_name(self):
        """A malformed component name must not raise out of std::stoull."""
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = _box()
        self.document.recompute()
        if not hasattr(geom, "getSubShapes"):
            self.skipTest("getSubShapes not available")
        for name in ("Component", "ComponentX", "Component0", "Component99"):
            self.assertEqual(geom.getSubShapes(name), [], msg=f"for {name}")

    def test_caches_survive_save_and_reload(self):
        """
        Restoring properties does not go through onChanged, so the component and
        dimension caches must be rebuilt when the document is loaded.
        """
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = _box()
        self.document.recompute()
        solids = [t for t in geom.getToplevelElements(0) if t.startswith("Solid")]
        self.assertTrue(solids)

        geom_name = geom.Name
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "geometry.FCStd")
            self.document.saveAs(path)
            FreeCAD.closeDocument(self.document.Name)
            # tearDown closes self.document, so hand it the reloaded one
            self.document = FreeCAD.openDocument(path)
            restored = self.document.getObject(geom_name)

            self.assertEqual(restored.getComponentCount(), 1)
            self.assertEqual(
                [t for t in restored.getToplevelElements(0) if t.startswith("Solid")],
                solids,
            )
            self.assertEqual(restored.getAnalysisDimension(solids[0]), 3)


class TestMeshMerge(unittest.TestCase):
    fcc_print("import TestMeshMerge")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestMeshMerge tests {2}\n{0}".format(100 * "*", 10 * "*", 57 * "*")
        )

    def test_lazy_merge_two_children(self):
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child_a = self.document.addObject("Fem::FemMeshObject", "MeshA")
        child_b = self.document.addObject("Fem::FemMeshObject", "MeshB")

        mesh_a, _, _ = _make_tet_mesh()
        mesh_b, _ = _make_tri_mesh("Face12")
        child_a.FemMesh = mesh_a
        child_b.FemMesh = mesh_b

        group.Group = [child_a, child_b]
        self.document.recompute()

        merged = group.FemMesh
        self.assertEqual(merged.NodeCount, mesh_a.NodeCount + mesh_b.NodeCount)
        self.assertEqual(
            merged.VolumeCount + merged.FaceCount,
            mesh_a.VolumeCount + mesh_a.FaceCount + mesh_b.VolumeCount + mesh_b.FaceCount,
        )

        names = {merged.getGroupName(g) for g in merged.Groups}
        self.assertIn("Solid1", names)
        self.assertIn("Face12", names)

        self.assertEqual(set(group.CellSources), {child_a.Name, child_b.Name})

    def test_reading_merged_mesh_does_not_touch_the_group(self):
        """
        The merge is a cache filled on read. Reading it must not mark anything
        touched, which would mark the document modified and force a recompute.
        """
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        mesh, _, _ = _make_tet_mesh()
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()
        for obj in self.document.Objects:
            obj.purgeTouched()

        self.assertEqual(group.FemMesh.VolumeCount, mesh.VolumeCount)
        self.assertEqual([o.Name for o in self.document.Objects if "Touched" in o.State], [])

    def test_merge_order_independent_of_group_order(self):
        """Children merged sorted by Name, not Group order."""
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child_z = self.document.addObject("Fem::FemMeshObject", "ZMesh")
        child_a = self.document.addObject("Fem::FemMeshObject", "AMesh")
        mesh_z, _ = _make_tri_mesh("Face1")
        mesh_a, _, _ = _make_tet_mesh()
        child_z.FemMesh = mesh_z
        child_a.FemMesh = mesh_a

        group.Group = [child_z, child_a]
        self.document.recompute()
        merged1 = group.FemMesh
        self.assertEqual(merged1.VolumeCount, mesh_a.VolumeCount)
        self.assertEqual(merged1.NodeCount, mesh_a.NodeCount + mesh_z.NodeCount)

        group.Group = [child_a, child_z]
        self.document.recompute()
        merged2 = group.FemMesh
        self.assertEqual(merged2.NodeCount, merged1.NodeCount)
        self.assertEqual(merged2.VolumeCount, merged1.VolumeCount)
        self.assertEqual(merged1.Nodes[1], merged2.Nodes[1])

    def test_analysis_group_has_single_mesh(self):
        """Mesh children live in the mesh group, not analysis.Group."""
        analysis = ObjectsFem.makeAnalysis(self.document)
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        mesh, _, _ = _make_tet_mesh()
        child.FemMesh = mesh
        group.Group = [child]
        analysis.addObject(group)
        self.document.recompute()

        from femtools import membertools

        meshes = membertools.get_member(analysis, "Fem::FemMeshObject")
        self.assertEqual(len(meshes), 1)
        self.assertEqual(meshes[0].Name, group.Name)


class TestExportHighest(unittest.TestCase):
    fcc_print("import TestExportHighest")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestExportHighest tests {2}\n{0}".format(
                100 * "*", 10 * "*", 52 * "*"
            )
        )

    @staticmethod
    def _mixed_mesh():
        """A tet with one skin triangle, plus a disconnected free shell triangle."""
        mesh = Fem.FemMesh()
        for node_id, point in enumerate(
            [
                (0, 0, 0),
                (1, 0, 0),
                (0, 1, 0),
                (0, 0, 1),
                (10, 0, 0),
                (11, 0, 0),
                (10, 1, 0),
            ],
            start=1,
        ):
            mesh.addNode(point[0], point[1], point[2], node_id)

        ids = {
            "volume": mesh.addVolume([1, 2, 3, 4]),
            "skin": mesh.addFace([1, 2, 3]),
            "shell": mesh.addFace([5, 6, 7]),
        }
        for name, group_type, members in (
            ("Solid1", "Volume", [ids["volume"]]),
            ("Face1", "Face", [ids["skin"]]),
            ("Face12", "Face", [ids["shell"]]),
        ):
            gid = mesh.addGroup(name, group_type)
            mesh.addGroupElements(gid, members)
        return mesh, ids

    def test_solid_plus_free_face_exports_both(self):
        """
        Volumes and a free face group both belong to the highest dimension
        export, while the skin of the solid does not.
        """
        mesh, ids = self._mixed_mesh()
        exported = _exported_element_ids(mesh, 1)

        self.assertEqual(
            sorted(sum(exported.values(), [])),
            sorted([ids["volume"], ids["shell"]]),
            msg=f"unexpected export {exported}",
        )

    def test_ungrouped_element_is_not_dropped(self):
        """
        An element no entity group claims must fall back to the mesh topology
        instead of silently disappearing from the export.
        """
        mesh = Fem.FemMesh()
        for node_id, point in enumerate(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)], start=1
        ):
            mesh.addNode(point[0], point[1], point[2], node_id)
        grouped = mesh.addVolume([1, 2, 3, 4])
        ungrouped = mesh.addVolume([2, 3, 4, 5])
        gid = mesh.addGroup("Solid1", "Volume")
        mesh.addGroupElements(gid, [grouped])

        exported = sorted(sum(_exported_element_ids(mesh, 1).values(), []))
        self.assertEqual(exported, sorted([grouped, ungrouped]))

    def test_vtk_groups_align_with_cells(self):
        """
        exportVTKMesh orders cells by element type, so the group array has to be
        indexed by cell position rather than by element id.
        """
        mesh, _ = self._mixed_mesh()
        index_map = {"Solid1": 11, "Face1": 12, "Face12": 13}
        vtk_tetra = 10
        vtk_triangle = 5

        self.assertEqual(
            _vtk_cells_with_groups(mesh, False, index_map),
            sorted([(vtk_triangle, 12), (vtk_triangle, 13), (vtk_tetra, 11)]),
        )
        # highest=True drops the skin triangle and must not raise about
        # non-continuous element ids
        self.assertEqual(
            _vtk_cells_with_groups(mesh, True, index_map),
            sorted([(vtk_triangle, 13), (vtk_tetra, 11)]),
        )

    def test_faces_and_edges_only(self):
        """The skin of a volume is not a free face; a lone triangle's edges are."""
        mesh, ids = self._mixed_mesh()
        edge = mesh.addEdge([5, 6])

        self.assertEqual(set(mesh.FacesOnly), {ids["shell"]})
        self.assertEqual(set(mesh.EdgesOnly), set())
        self.assertIn(edge, mesh.Edges)


class TestViewStatePersistence(unittest.TestCase):
    fcc_print("import TestViewStatePersistence")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestViewStatePersistence tests {2}\n{0}".format(
                100 * "*", 10 * "*", 45 * "*"
            )
        )

    def test_hidden_elements_prop_is_output(self):
        """ViewHiddenElements is Prop_Output so it does not touch the document."""
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for AnalysisViewState persistence props")

        analysis = ObjectsFem.makeAnalysis(self.document)
        self.document.recompute()
        vp = analysis.ViewObject
        self.assertTrue(hasattr(vp, "ViewHiddenElements"))

        self.document.purgeTouched()
        vp.ViewHiddenElements = ["Face1", "Solid2"]
        self.assertNotIn("Touched", analysis.State)
        self.assertEqual(set(vp.ViewHiddenElements), {"Face1", "Solid2"})

    def test_hidden_elements_are_persisted_to_the_view_provider(self):
        """Changing the view state writes through to the persisted properties."""
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for AnalysisViewState persistence props")

        import FemGui

        analysis = ObjectsFem.makeAnalysis(self.document)
        self.document.recompute()

        state = FemGui.getAnalysisViewState(analysis)
        self.assertIsNotNone(state)

        state.setElementHidden("Face3", True)
        self.assertEqual(set(analysis.ViewObject.ViewHiddenElements), {"Face3"})

        state.setElementHidden("Face3", False)
        self.assertEqual(set(analysis.ViewObject.ViewHiddenElements), set())

    def test_clip_planes_are_persisted_to_the_view_provider(self):
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for AnalysisViewState persistence props")

        import FemGui

        analysis = ObjectsFem.makeAnalysis(self.document)
        self.document.recompute()

        state = FemGui.getAnalysisViewState(analysis)
        state.setClipPlane("clip", FreeCAD.Vector(1, 2, 3), FreeCAD.Vector(0, 0, 1))
        self.assertEqual(list(analysis.ViewObject.ViewClipPlaneNames), ["clip"])
        self.assertEqual(len(analysis.ViewObject.ViewClipPlaneData), 1)

        state.removeClipPlane("clip")
        self.assertEqual(list(analysis.ViewObject.ViewClipPlaneNames), [])
        self.assertEqual(list(analysis.ViewObject.ViewClipPlaneData), [])

    def test_view_state_is_restored_from_the_view_provider(self):
        """A reloaded document restores the hidden elements into the view state."""
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for AnalysisViewState persistence props")

        import FemGui

        analysis = ObjectsFem.makeAnalysis(self.document)
        self.document.recompute()
        FemGui.getAnalysisViewState(analysis).setElementHidden("Solid1", True)

        analysis_name = analysis.Name
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "view_state.FCStd")
            self.document.saveAs(path)
            FreeCAD.closeDocument(self.document.Name)
            # tearDown closes self.document, so hand it the reloaded one
            self.document = FreeCAD.openDocument(path)
            reloaded = self.document.getObject(analysis_name)

            state = FemGui.getAnalysisViewState(reloaded)
            self.assertTrue(state.isElementHidden("Solid1"))
