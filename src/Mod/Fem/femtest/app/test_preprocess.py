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


def _sub_names(shape, kind):
    """{"Face3": <shape>} for every sub-element of the given kind."""
    elements = {
        "Solid": shape.Solids,
        "Face": shape.Faces,
        "Edge": shape.Edges,
        "Vertex": shape.Vertexes,
    }[kind]
    return {f"{kind}{i}": sub for i, sub in enumerate(elements, 1)}


def _find_sub(shape, kind, predicate):
    """Name of the first sub-element matching predicate, by index in the shape."""
    for name, sub in _sub_names(shape, kind).items():
        if predicate(sub):
            return name
    raise AssertionError(f"no {kind} matching the predicate")


def _find_subs(shape, kind, predicate):
    return [name for name, sub in _sub_names(shape, kind).items() if predicate(sub)]


def _measure(shape):
    """Volume, area or length, whichever describes the shape."""
    if shape.isNull():
        return 0.0
    if shape.Solids:
        return shape.Volume
    if shape.Faces:
        return shape.Area
    return shape.Length


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

    def test_a_bridge_joins_the_components_it_touches(self):
        """
        A candidate went to the first component it shared topology with, so a
        candidate bridging two of them left the second behind: geometry that is
        connected throughout was reported as two components.
        """
        left = Part.makeBox(10, 10, 10)
        right = Part.makeBox(10, 10, 10, FreeCAD.Vector(20, 0, 0))
        bridge = Part.makeBox(10, 10, 10, FreeCAD.Vector(10, 0, 0))
        pieces = sorted(
            left.generalFuse([right, bridge])[0].Solids,
            key=lambda solid: solid.CenterOfMass.x,
        )

        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        # The bridge comes last, so by the time it arrives the two ends are
        # components of their own and both of them have to be joined.
        geom.Shape = Part.makeCompound([pieces[0], pieces[2], pieces[1]])
        self.document.recompute()

        self.assertEqual(geom.getComponentCount(), 1)
        self.assertEqual(len(geom.getToplevelElements(0)), 3)

    def test_shapes_that_only_touch_stay_apart(self):
        """
        Coincident faces are not shared faces. Two boxes brought in separately
        touch without sharing topology, and that is what keeps them two
        components the bridge test must not paper over.
        """
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = Part.makeCompound(
            [Part.makeBox(10, 10, 10), Part.makeBox(10, 10, 10, FreeCAD.Vector(10, 0, 0))]
        )
        self.document.recompute()

        self.assertEqual(geom.getComponentCount(), 2)

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


class TestGeometryPartition(unittest.TestCase):
    fcc_print("import TestGeometryPartition")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def _chain(self, *shapes):
        """Geometry group holding an import of shapes plus a partition step."""
        sources = []
        for i, shape in enumerate(shapes):
            obj = self.document.addObject("Part::Feature", f"Source{i}")
            obj.Shape = shape
            sources.append(obj)

        group = ObjectsFem.makeGeometryGroup(self.document)
        imp = ObjectsFem.makeGeometryImport(self.document)
        imp.Import = sources
        group.Group = [imp]
        self.document.recompute()

        part = ObjectsFem.makeGeometryPartition(self.document)
        # The group wires Base from the chain order, so it is not set here
        group.Group = [imp, part]
        self.document.recompute()
        self.assertEqual(part.Base, imp, "the group must wire the step input")
        return group, imp, part

    def _datum(self, base, normal, name="Datum"):
        plane = self.document.addObject("Part::DatumPlane", name)
        plane.Placement = FreeCAD.Placement(base, FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), normal))
        return plane

    def assertValid(self, obj):
        self.assertNotIn("Invalid", obj.State, f"{obj.Name} failed to recompute")

    def assertInvalid(self, obj):
        self.assertIn("Invalid", obj.State, f"{obj.Name} should have refused to recompute")

    def assertMeasurePreserved(self, before, after):
        """A partition only adds cuts, so volume/area/length cannot change."""
        self.assertAlmostEqual(
            _measure(after),
            _measure(before),
            delta=max(_measure(before) * 1e-6, 1e-9),
            msg="partition changed the total measure of the shape",
        )

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestGeometryPartition tests {2}\n{0}".format(
                100 * "*", 10 * "*", 49 * "*"
            )
        )

    # -- method availability ------------------------------------------------

    def test_method_availability_follows_target_types(self):
        from femobjects import geometry_partition as gp

        _, imp, _ = self._chain(_box())
        edges = [(imp, ("Edge1", "Edge2"))]
        faces = [(imp, ("Face1",))]
        two_faces = [(imp, ("Face1", "Face2"))]
        solids = [(imp, ("Solid1",))]

        self.assertTrue(gp.method_available(gp.METHOD_EDGE_PARAM, edges))
        self.assertFalse(gp.method_available(gp.METHOD_EDGE_PARAM, faces))
        self.assertFalse(gp.method_available(gp.METHOD_EDGE_PARAM, []))

        self.assertTrue(gp.method_available(gp.METHOD_SHORTEST_PATH, faces))
        # two faces in one link is still two targets
        self.assertFalse(gp.method_available(gp.METHOD_SHORTEST_PATH, two_faces))
        self.assertFalse(gp.method_available(gp.METHOD_SHORTEST_PATH, solids))

        for method in (gp.METHOD_PLANE_3P, gp.METHOD_PLANE_REF, gp.METHOD_EXTEND_FACE):
            self.assertTrue(gp.method_available(method, []))
            self.assertTrue(gp.method_available(method, solids))

    def test_first_available_method_keeps_a_valid_preference(self):
        from femobjects import geometry_partition as gp

        _, imp, _ = self._chain(_box())
        edges = [(imp, ("Edge1",))]
        self.assertEqual(
            gp.first_available_method(edges, gp.METHOD_EDGE_PARAM), gp.METHOD_EDGE_PARAM
        )
        # shortest path cannot run on an edge, so a runnable method is offered
        fallback = gp.first_available_method(edges, gp.METHOD_SHORTEST_PATH)
        self.assertTrue(gp.method_available(fallback, edges))

    # -- tool construction --------------------------------------------------

    def test_tool_plane_is_centred_on_the_shape(self):
        """
        Part.makePlane anchors at a corner, so an uncentred tool covers only one
        quadrant of the intended cut and misses most of the target.
        """
        from femobjects import geometry_partition as gp

        box = Part.makeBox(20, 20, 20)
        tool = gp._plane_from_axes(
            FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0), None, box.BoundBox
        )
        bbox = tool.BoundBox
        self.assertAlmostEqual(bbox.XMin, 10.0, places=6)
        self.assertAlmostEqual(bbox.XMax, 10.0, places=6)
        for lo, hi in ((bbox.YMin, bbox.YMax), (bbox.ZMin, bbox.ZMax)):
            self.assertLess(lo, 0.0, "tool must reach past the low side of the box")
            self.assertGreater(hi, 20.0, "tool must reach past the high side of the box")

    def test_tool_plane_ignores_the_reference_extent(self):
        """
        A datum plane reports a practically infinite bounding box and a small
        reference face a tiny one; both must yield a tool sized to the target.
        """
        from femobjects import geometry_partition as gp

        _, imp, _ = self._chain(Part.makeBox(200, 200, 10))
        bbox = imp.Shape.BoundBox
        datum = self._datum(FreeCAD.Vector(100, 0, 0), FreeCAD.Vector(1, 0, 0))
        small = self.document.addObject("Part::Feature", "SmallRef")
        small.Shape = Part.makePlane(2, 2, FreeCAD.Vector(100, 0, 0), FreeCAD.Vector(1, 0, 0))
        self.document.recompute()

        for tool in (
            gp._tool_plane_from_reference((datum, ()), bbox),
            gp._tool_plane_from_reference((small, ("Face1",)), bbox),
        ):
            diagonal = tool.BoundBox.DiagonalLength
            self.assertGreater(diagonal, bbox.DiagonalLength)
            self.assertLess(diagonal, bbox.DiagonalLength * 100)

    # -- plane by reference -------------------------------------------------

    def test_plane_reference_splits_a_solid(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 10, 10))
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 2)
        self.assertMeasurePreserved(imp.Shape, part.Shape)

    def test_plane_reference_accepts_a_planar_face(self):
        """Face references went through tangentAt, which returns a tuple."""
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 10, 10))
        reference = self.document.addObject("Part::Feature", "Reference")
        reference.Shape = Part.makePlane(4, 4, FreeCAD.Vector(10, 2, 2), FreeCAD.Vector(1, 0, 0))
        self.document.recompute()

        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (reference, "Face1")
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 2)
        self.assertMeasurePreserved(imp.Shape, part.Shape)

    def test_plane_reference_rejects_a_curved_face(self):
        from femobjects import geometry_partition as gp

        _, _, part = self._chain(Part.makeBox(20, 10, 10))
        reference = self.document.addObject("Part::Feature", "Reference")
        reference.Shape = Part.makeCylinder(5, 20, FreeCAD.Vector(10, 5, -5))
        self.document.recompute()
        lateral = _find_sub(reference.Shape, "Face", lambda f: isinstance(f.Surface, Part.Cylinder))

        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (reference, lateral)
        self.document.recompute()
        self.assertInvalid(part)

    def test_plane_reference_without_a_tool_passes_the_input_through(self):
        """
        A step is added before it is configured, so it must not fail: the group
        renders the last step, and a failed step blanks the whole chain.
        """
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(_box())
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = None
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), len(imp.Shape.Solids))
        self.assertMeasurePreserved(imp.Shape, part.Shape)

    # -- plane by three points ----------------------------------------------

    def test_plane_by_three_points_splits_a_solid(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 10, 10))
        vertexes = _sub_names(imp.Shape, "Vertex")
        picks = [name for name, v in vertexes.items() if abs(v.Point.x) < 1e-6][:2]
        picks += [
            name
            for name, v in vertexes.items()
            if abs(v.Point.x - 20) < 1e-6 and abs(v.Point.y - 10) < 1e-6
        ][:1]
        self.assertEqual(len(picks), 3)

        part.Method = gp.METHOD_PLANE_3P
        part.Points = [(imp, tuple(picks))]
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 2)
        self.assertMeasurePreserved(imp.Shape, part.Shape)

    def test_plane_by_three_points_counts_picks_not_links(self):
        """
        Three vertexes of one object land in a single PropertyLinkSubList entry,
        so counting links instead of sub-elements rejects a valid selection.
        """
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 10, 10))
        part.Method = gp.METHOD_PLANE_3P

        # two picks is an unfinished selection, so the input passes through
        part.Points = [(imp, ("Vertex1", "Vertex2"))]
        self.document.recompute()
        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 1)

        part.Points = [(imp, ("Vertex1", "Vertex2", "Vertex7"))]
        self.document.recompute()
        self.assertEqual(len(part.Points), 1, "the picks stay in one link")
        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 2, "three picks must cut")

    def test_plane_by_three_points_rejects_collinear_picks(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 10, 10))
        edge = _sub_names(imp.Shape, "Edge")["Edge1"]
        on_edge = _find_subs(imp.Shape, "Vertex", lambda v: edge.distToShape(v)[0] < 1e-7)
        # two edge ends plus a point on the same line
        picks = tuple(on_edge[:2]) + (on_edge[0],)

        part.Method = gp.METHOD_PLANE_3P
        part.Points = [(imp, picks)]
        self.document.recompute()
        self.assertInvalid(part)

    # -- extend face --------------------------------------------------------

    def test_extend_face_cuts_a_neighbouring_solid(self):
        from femobjects import geometry_partition as gp

        step = Part.makeBox(10, 20, 20)
        neighbour = Part.makeBox(20, 20, 20, FreeCAD.Vector(10, 0, 0))
        _, imp, part = self._chain(step, neighbour)
        top_of_step = _find_sub(
            imp.Shape,
            "Face",
            lambda f: abs(f.CenterOfMass.z - 20) < 1e-6 and f.CenterOfMass.x < 10,
        )

        part.Method = gp.METHOD_EXTEND_FACE
        part.Tool = (imp, top_of_step)
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 2)
        self.assertMeasurePreserved(imp.Shape, part.Shape)

    def test_extend_face_keeps_a_curved_tool_curved(self):
        """
        Reducing every tool face to a plane silently cut along the surface axis
        instead of the surface itself.
        """
        from femobjects import geometry_partition as gp

        _, imp, _ = self._chain(Part.makeCylinder(10, 20))
        lateral = _find_sub(imp.Shape, "Face", lambda f: isinstance(f.Surface, Part.Cylinder))
        tool = gp._extended_face_tool(imp, (imp, (lateral,)), imp.Shape.BoundBox)

        self.assertIsInstance(tool.Faces[0].Surface, Part.Cylinder)
        self.assertIsNone(
            gp._plane_placement(tool.Faces[0]),
            "a curved tool must not be treated as a half-space plane",
        )

    def test_extend_face_needs_a_face_of_the_input(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(_box())
        part.Method = gp.METHOD_EXTEND_FACE
        part.Tool = (imp, "Edge1")
        self.document.recompute()
        self.assertInvalid(part)

    # -- edge parameter -----------------------------------------------------

    def test_edge_parameter_adds_a_vertex_per_target(self):
        """
        The split point came from the underlying curve range, which for a line
        is unbounded, and the cutting plane contained the edge instead of
        crossing it, so nothing was ever split.
        """
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 10, 10))
        edges = len(imp.Shape.Edges)
        part.Method = gp.METHOD_EDGE_PARAM
        part.Parameter = 0.5

        part.Elements = [(imp, ("Edge1",))]
        self.document.recompute()
        self.assertValid(part)
        self.assertEqual(len(part.Shape.Edges), edges + 1)
        self.assertMeasurePreserved(imp.Shape, part.Shape)

        part.Elements = [(imp, ("Edge1", "Edge3"))]
        self.document.recompute()
        self.assertValid(part)
        self.assertEqual(len(part.Shape.Edges), edges + 2, "the second target must be split too")
        self.assertMeasurePreserved(imp.Shape, part.Shape)

    def test_edge_parameter_splits_at_the_requested_position(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 10, 10))
        target = _find_sub(
            imp.Shape,
            "Edge",
            lambda e: e.Length == 20
            and abs(e.BoundBox.YMin) < 1e-6
            and abs(e.BoundBox.ZMin) < 1e-6,
        )
        edge = _sub_names(imp.Shape, "Edge")[target]
        before = {
            (round(v.Point.x, 6), round(v.Point.y, 6), round(v.Point.z, 6))
            for v in imp.Shape.Vertexes
        }

        part.Method = gp.METHOD_EDGE_PARAM
        part.Elements = [(imp, (target,))]
        part.Parameter = 0.25
        self.document.recompute()
        self.assertValid(part)

        after = {
            (round(v.Point.x, 6), round(v.Point.y, 6), round(v.Point.z, 6))
            for v in part.Shape.Vertexes
        }
        new_points = after - before
        self.assertEqual(len(new_points), 1)
        expected = edge.valueAt(
            edge.FirstParameter + 0.25 * (edge.LastParameter - edge.FirstParameter)
        )
        got = FreeCAD.Vector(*next(iter(new_points)))
        self.assertLess(got.distanceToPoint(expected), 1e-6)

    def test_edge_parameter_refuses_non_edge_targets(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(_box())
        part.Method = gp.METHOD_EDGE_PARAM
        part.Elements = [(imp, ("Face1",))]
        self.document.recompute()
        self.assertInvalid(part)

    # -- shortest path ------------------------------------------------------

    def test_shortest_path_splits_the_target_face(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 20, 20))
        top = _find_sub(imp.Shape, "Face", lambda f: abs(f.CenterOfMass.z - 20) < 1e-6)
        face = _sub_names(imp.Shape, "Face")[top]
        on_top = _find_subs(imp.Shape, "Vertex", lambda v: face.distToShape(v)[0] < 1e-7)
        diagonal = (on_top[0], on_top[3])

        part.Method = gp.METHOD_SHORTEST_PATH
        part.Elements = [(imp, (top,))]
        part.Points = [(imp, diagonal)]
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Faces), len(imp.Shape.Faces) + 1)
        self.assertMeasurePreserved(imp.Shape, part.Shape)

    def test_shortest_path_rejects_points_off_the_face(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 20, 20))
        top = _find_sub(imp.Shape, "Face", lambda f: abs(f.CenterOfMass.z - 20) < 1e-6)
        face = _sub_names(imp.Shape, "Face")[top]
        off_face = _find_subs(imp.Shape, "Vertex", lambda v: face.distToShape(v)[0] > 1e-7)

        part.Method = gp.METHOD_SHORTEST_PATH
        part.Elements = [(imp, (top,))]
        part.Points = [(imp, tuple(off_face[:2]))]
        self.document.recompute()
        self.assertInvalid(part)

    def test_shortest_path_with_one_point_passes_the_input_through(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 20, 20))
        top = _find_sub(imp.Shape, "Face", lambda f: abs(f.CenterOfMass.z - 20) < 1e-6)
        part.Method = gp.METHOD_SHORTEST_PATH
        part.Elements = [(imp, (top,))]
        part.Points = [(imp, ("Vertex1",))]
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Faces), len(imp.Shape.Faces))

    # -- targets ------------------------------------------------------------

    def test_targets_restrict_the_cut(self):
        from femobjects import geometry_partition as gp

        first = Part.makeBox(20, 10, 10)
        second = Part.makeBox(20, 10, 10, FreeCAD.Vector(0, 30, 0))
        _, imp, part = self._chain(first, second)
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")

        # no targets means every solid the plane crosses
        part.Elements = []
        self.document.recompute()
        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 4)
        self.assertMeasurePreserved(imp.Shape, part.Shape)

        # one target means only that solid
        part.Elements = [(imp, ("Solid1",))]
        self.document.recompute()
        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 3)
        self.assertMeasurePreserved(imp.Shape, part.Shape)

    def _two_step_chain(self, first_shapes, second_shapes):
        """
        A chain whose partition input comes from two import steps.

        Each import wraps what it contributes in a compound of its own, so the
        input of the partition is a compound of compounds rather than the flat
        compound a single import produces. That is the shape a real analysis
        builds as soon as geometry arrives in more than one step.
        """
        group = ObjectsFem.makeGeometryGroup(self.document)
        steps = []
        for step_index, shapes in enumerate((first_shapes, second_shapes)):
            sources = []
            for index, shape in enumerate(shapes):
                obj = self.document.addObject("Part::Feature", f"Source{step_index}_{index}")
                obj.Shape = shape
                sources.append(obj)
            imp = ObjectsFem.makeGeometryImport(self.document)
            imp.Import = sources
            steps.append(imp)

        part = ObjectsFem.makeGeometryPartition(self.document)
        group.Group = steps + [part]
        self.document.recompute()

        base = steps[-1]
        self.assertEqual(part.Base, base)
        direct_solids = [child for child in base.Shape.childShapes() if child.ShapeType == "Solid"]
        self.assertLess(
            len(direct_solids),
            len(base.Shape.Solids),
            "this test is only meaningful while nesting hides solids from the direct children",
        )
        return group, base, part

    def test_a_target_in_a_nested_input_cuts_only_that_solid(self):
        """
        Members were read one level down only. Two import steps nest a compound
        per step, so the input held compounds where the code looked for solids:
        a targeted solid matched nothing, which was reported as targets that are
        not part of the input, and an empty selection meant the wrappers instead
        of the solids, cutting everything the plane crossed.
        """
        from femobjects import geometry_partition as gp

        _, base, part = self._two_step_chain(
            [Part.makeBox(20, 10, 10), Part.makeBox(20, 10, 10, FreeCAD.Vector(0, 30, 0))],
            [Part.makeBox(20, 10, 10, FreeCAD.Vector(0, 60, 0))],
        )
        self.assertEqual(len(base.Shape.Solids), 3)

        # A solid the earlier step brought in, so it sits inside the nested
        # compound rather than among the direct children of the input.
        target = _find_sub(base.Shape, "Solid", lambda s: abs(s.CenterOfMass.y - 35) < 1e-6)
        target_shape = base.getSubObject(target)
        self.assertFalse(
            any(child.isSame(target_shape) for child in base.Shape.childShapes()),
            "the target has to sit inside the nesting for this test to bite",
        )
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        part.Elements = [(base, (target,))]
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(
            len(part.Shape.Solids),
            4,
            "only the targeted solid may be cut, the other two stay whole",
        )
        self.assertMeasurePreserved(base.Shape, part.Shape)

        # The two solids that were not targeted have to come out untouched, one
        # from the nested compound and one from the direct children.
        for centre_y in (5, 65):
            kept = [
                solid
                for solid in part.Shape.Solids
                if abs(solid.CenterOfMass.y - centre_y) < 1e-6 and abs(solid.Volume - 2000) < 1e-6
            ]
            self.assertEqual(len(kept), 1, f"the solid at y={centre_y} must be left alone")

    def test_a_nested_input_without_targets_cuts_every_solid(self):
        """The default target list has to find the solids inside the wrappers."""
        from femobjects import geometry_partition as gp

        _, base, part = self._two_step_chain(
            [Part.makeBox(20, 10, 10)],
            [Part.makeBox(20, 10, 10, FreeCAD.Vector(0, 30, 0))],
        )
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        part.Elements = []
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 4)
        self.assertMeasurePreserved(base.Shape, part.Shape)

    def test_face_target_only_gains_an_edge(self):
        """A face target imprints the cut without separating the solid."""
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 20, 20))
        top = _find_sub(imp.Shape, "Face", lambda f: abs(f.CenterOfMass.z - 20) < 1e-6)

        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        part.Elements = [(imp, (top,))]
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 1)
        self.assertEqual(len(part.Shape.Faces), len(imp.Shape.Faces) + 1)
        self.assertMeasurePreserved(imp.Shape, part.Shape)

    def test_every_solid_target_is_cut_exactly_once(self):
        """
        Cutting one solid at a time rebuilds the shape, so the picks for the
        remaining solids went stale and their cuts landed on top of a solid
        that was still there, duplicating its volume.
        """
        from femobjects import geometry_partition as gp

        boxes = [Part.makeBox(20, 10, 10, FreeCAD.Vector(0, 20 * i, 0)) for i in range(4)]
        _, imp, part = self._chain(*boxes)
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 2 * len(boxes))
        self.assertMeasurePreserved(imp.Shape, part.Shape)

    def test_solid_split_leaves_a_conformal_interface(self):
        """
        The pieces have to share the face at the cut, otherwise the mesher
        meshes both sides independently and the nodes do not line up.
        """
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 10, 10))
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        self.document.recompute()
        self.assertValid(part)

        first, second = part.Shape.Solids
        shared = [face for face in first.Faces if any(face.isSame(other) for other in second.Faces)]
        self.assertEqual(len(shared), 1, "the two pieces must share the cut face")
        # 6 + 6 faces minus the one they share
        self.assertEqual(len(part.Shape.Faces), 11)

    def _plane_cut(self, imp, part, target, x=10):
        from femobjects import geometry_partition as gp

        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(x, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        part.Elements = [(imp, (target,))]
        self.document.recompute()
        self.assertValid(part)

    def test_a_cut_leaves_the_component_beside_it_alone(self):
        """
        The pieces of a cut were glued by fusing the whole input at once, which
        also welded parts that merely touch: two components ended up sharing the
        face and the edges they were coincident on, so what the user built as
        separate parts came out as one piece of geometry.
        """
        left = Part.makeBox(20, 10, 10)
        right = Part.makeBox(20, 10, 10, FreeCAD.Vector(20, 0, 0))
        _, imp, part = self._chain(left, right)
        self.assertEqual(
            imp.getComponentCount(),
            2,
            "the boxes are imported separately, so they only touch",
        )

        target = _find_sub(imp.Shape, "Solid", lambda solid: solid.CenterOfMass.x < 20)
        self._plane_cut(imp, part, target)

        self.assertEqual(len(part.Shape.Solids), 3)
        self.assertMeasurePreserved(imp.Shape, part.Shape)
        self.assertEqual(part.getComponentCount(), 2, "the cut may not join the two boxes")

        beside = [solid for solid in part.Shape.Solids if solid.CenterOfMass.x > 20][0]
        for piece in [solid for solid in part.Shape.Solids if solid.CenterOfMass.x < 20]:
            self.assertFalse(
                any(face.isSame(other) for face in piece.Faces for other in beside.Faces),
                "a piece of the cut solid shares a face with the box next to it",
            )
            self.assertFalse(
                any(vertex.isSame(other) for vertex in piece.Vertexes for other in beside.Vertexes),
                "a piece of the cut solid shares a vertex with the box next to it",
            )

    def test_a_cut_keeps_its_own_component_connected(self):
        """
        Gluing has to reach the rest of the component: the solid that was cut
        shared a face with its neighbour, and that connection has to survive the
        rebuild or the mesh comes out non-conformal where it used to be fine.
        """
        left = Part.makeBox(20, 10, 10)
        right = Part.makeBox(20, 10, 10, FreeCAD.Vector(20, 0, 0))
        _, imp, part = self._chain(left, right)
        imp.Embed = "Embed import"
        self.document.recompute()
        self.assertEqual(imp.getComponentCount(), 1, "an embedded import fuses what it brings in")

        target = _find_sub(imp.Shape, "Solid", lambda solid: solid.CenterOfMass.x < 20)
        self._plane_cut(imp, part, target)

        self.assertEqual(len(part.Shape.Solids), 3)
        self.assertMeasurePreserved(imp.Shape, part.Shape)
        self.assertEqual(part.getComponentCount(), 1)

        pieces = sorted(part.Shape.Solids, key=lambda solid: solid.CenterOfMass.x)
        for first, second in zip(pieces, pieces[1:]):
            shared = [
                face for face in first.Faces if any(face.isSame(other) for other in second.Faces)
            ]
            self.assertEqual(len(shared), 1, "neighbours in a component share their interface")

    def test_mixed_solid_and_sub_element_targets_are_rejected(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 20, 20))
        top = _find_sub(imp.Shape, "Face", lambda f: abs(f.CenterOfMass.z - 20) < 1e-6)

        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        part.Elements = [(imp, ("Solid1", top))]
        self.document.recompute()
        self.assertInvalid(part)

    def test_solid_target_that_names_nothing_is_reported(self):
        """A stale pick must not pass as a partition that quietly did nothing."""
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 10, 10))
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        part.Elements = [(imp, ("Solid7",))]
        self.document.recompute()
        self.assertInvalid(part)

    def test_free_faces_are_partitioned_without_solids(self):
        from femobjects import geometry_partition as gp

        first = Part.makePlane(20, 20)
        second = Part.makePlane(20, 20, FreeCAD.Vector(0, 40, 0))
        _, imp, part = self._chain(first, second)
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 0)
        self.assertEqual(len(part.Shape.Faces), 2 * len(imp.Shape.Faces))
        self.assertMeasurePreserved(imp.Shape, part.Shape)

    def test_foreign_target_is_rejected(self):
        from femobjects import geometry_partition as gp

        _, _, part = self._chain(_box())
        foreign = self.document.addObject("Part::Feature", "Foreign")
        foreign.Shape = Part.makeBox(5, 5, 5)
        self.document.recompute()

        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(5, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        part.Elements = [(foreign, ("Solid1",))]
        self.document.recompute()
        self.assertInvalid(part)

    def test_plane_that_misses_the_target_is_a_no_op(self):
        """
        The half-space boxes were derived from the distance to the cut, so a
        plane outside the shape asked OCC for a negative box length.
        """
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 10, 10))
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(-5000, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 1)
        self.assertMeasurePreserved(imp.Shape, part.Shape)

    def test_a_freshly_added_step_keeps_the_chain_rendering(self):
        """
        The command adds the step and opens its panel, so the default state has
        to be a working pass-through rather than a failed recompute.
        """
        group, imp, _ = self._chain(Part.makeBox(20, 10, 10))
        fresh = ObjectsFem.makeGeometryPartition(self.document)
        group.Group = list(group.Group) + [fresh]
        self.document.recompute()

        self.assertValid(fresh)
        self.assertFalse(fresh.Shape.isNull())
        self.assertEqual(len(fresh.Shape.Solids), len(imp.Shape.Solids))
        self.assertMeasurePreserved(imp.Shape, fresh.Shape)

    def test_no_input_is_rejected(self):
        from femobjects import geometry_partition as gp

        part = ObjectsFem.makeGeometryPartition(self.document)
        part.Method = gp.METHOD_PLANE_REF
        self.document.recompute()
        self.assertInvalid(part)

    # -- chain integration --------------------------------------------------

    def test_result_flows_on_to_the_next_step(self):
        from femobjects import geometry_partition as gp

        group, imp, part = self._chain(Part.makeBox(20, 10, 10))
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        self.document.recompute()

        second = ObjectsFem.makeGeometryPartition(self.document)
        group.Group = [imp, part, second]
        self.document.recompute()
        self.assertEqual(second.Base, part, "the chain must feed the partition result on")

        second.Method = gp.METHOD_PLANE_REF
        second.Tool = (self._datum(FreeCAD.Vector(0, 5, 0), FreeCAD.Vector(0, 1, 0), "D2"), "")
        self.document.recompute()

        self.assertValid(second)
        self.assertEqual(len(second.Shape.Solids), 4)
        self.assertMeasurePreserved(imp.Shape, second.Shape)

    def test_partition_survives_save_and_reload(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 10, 10))
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        part.Elements = [(imp, ("Solid1",))]
        self.document.recompute()
        self.assertValid(part)

        name = part.Name
        volume = part.Shape.Volume
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "partition.FCStd")
            self.document.saveAs(path)
            FreeCAD.closeDocument(self.document.Name)
            # tearDown closes self.document, so hand it the reloaded one
            self.document = FreeCAD.openDocument(path)
            restored = self.document.getObject(name)

            self.assertTrue(restored.isDerivedFrom("Fem::FemGeometryPython"))
            self.assertEqual(restored.Proxy.Type, "Fem::GeometryPartition")
            self.assertEqual(restored.Method, gp.METHOD_PLANE_REF)
            self.assertEqual(len(restored.Elements), 1)
            self.assertEqual(len(restored.Shape.Solids), 2)
            self.assertAlmostEqual(restored.Shape.Volume, volume, places=6)

            restored.touch()
            self.document.recompute()
            self.assertValid(restored)
            self.assertEqual(len(restored.Shape.Solids), 2)


class TestGeometryReferences(unittest.TestCase):
    """Members of an analysis reference the geometry it builds, which is a
    Fem::FemGeometry and not the Part::Feature the constraints once held."""

    fcc_print("import TestGeometryReferences")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)
        self.source = self.document.addObject("Part::Feature", "Source")
        self.source.Shape = Part.makeBox(20, 10, 10)
        self.analysis = ObjectsFem.makeAnalysis(self.document)
        self.group = ObjectsFem.makeGeometryGroup(self.document)
        imp = ObjectsFem.makeGeometryImport(self.document)
        imp.Import = [self.source]
        self.group.Group = [imp]
        self.analysis.addObject(self.group)
        self.document.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestGeometryReferences tests {2}\n{0}".format(
                100 * "*", 10 * "*", 47 * "*"
            )
        )

    def test_the_geometry_of_an_analysis_is_what_members_reference(self):
        from femtools import femutils

        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        self.assertIs(femutils.get_analysis(constraint), self.analysis)
        self.assertIs(femutils.get_reference_geometry(constraint), self.group)

    def test_a_member_of_a_member_finds_the_analysis(self):
        """A mesh refinement hangs two groups deep, in the mesher of the mesh."""
        from femtools import femutils

        mesh = ObjectsFem.makeMeshShapeGroup(
            self.document, geometry=self.group, analysis=self.analysis
        )
        mesher = ObjectsFem.makeMeshGmsh(self.document)
        ObjectsFem.addMeshToShapeGroup(mesh, mesher)
        region = ObjectsFem.makeMeshRegion(self.document, mesher)
        self.document.recompute()

        self.assertIs(femutils.get_analysis(region), self.analysis)
        self.assertIs(femutils.get_reference_geometry(region), self.group)

    def test_an_analysis_without_geometry_leaves_references_free(self):
        from femtools import femutils

        analysis = ObjectsFem.makeAnalysis(self.document, "Legacy")
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        analysis.addObject(constraint)
        self.document.recompute()

        self.assertIsNone(
            femutils.get_reference_geometry(constraint),
            "documents that reference part features directly have to keep working",
        )

    def test_a_constraint_reads_the_geometry_it_references(self):
        """
        The constraint reads the referenced face to aim its symbols. It used to
        cast every referenced object to a Part::Feature, which a geometry is
        not, so this went through unrelated memory.
        """
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        constraint.References = [(self.group, "Face1")]
        self.document.recompute()

        self.assertNotIn("Invalid", constraint.State)
        normal = constraint.NormalDirection
        expected = self.group.Shape.getElement("Face1").normalAt(0, 0)
        self.assertAlmostEqual(abs(normal.dot(expected)), 1.0, places=6)

    def test_a_force_takes_its_direction_from_the_geometry(self):
        constraint = ObjectsFem.makeConstraintForce(self.document)
        self.analysis.addObject(constraint)
        constraint.References = [(self.group, "Face2")]
        constraint.Direction = (self.group, ["Face2"])
        self.document.recompute()

        self.assertNotIn("Invalid", constraint.State)
        self.assertAlmostEqual(constraint.DirectionVector.Length, 1.0, places=6)

    def test_a_reference_without_a_shape_is_passed_over(self):
        """Nothing to read from, but nothing to crash over either."""
        shapeless = self.document.addObject("App::FeaturePython", "Shapeless")
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        constraint.References = [(shapeless, "Face1")]
        self.document.recompute()

        self.assertNotIn("Invalid", constraint.State)


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
