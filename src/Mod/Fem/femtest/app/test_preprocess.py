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

from femmesh import meshcomponents

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
    """Solid volume, loose-face area and loose-edge length, as the step measures them."""
    from femobjects.geometry_partition import _measure as measure

    return measure(shape)


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


def _embedded_shell(document, wrapped=False):
    """
    A plate fused halfway into a box, and the names the fuse leaves behind.

    The piece of the plate inside the box is a face of the solid and a model
    element in its own right at the same time, which is the whole of the
    embedded shell case. Returns the geometry, that face, and one of the
    edges bounding it.

    wrapped hands the same surface in as a Shell rather than as a bare Face,
    which is the difference between a shell the user extruded and a face
    they drew. The component analysis takes free shells and free faces in
    the same sweep and expands a shell into its faces, so the two are meant
    to arrive as the same toplevel and be classified alike; the callers run
    both to hold that.
    """
    box = Part.makeBox(10, 10, 10)
    plate = Part.makePlane(10, 10, FreeCAD.Vector(5, 0, 5), FreeCAD.Vector(0, 0, 1))
    geom = document.addObject("Fem::FemGeometry", "Geometry")
    geom.Shape = box.generalFuse([Part.Shell([plate]) if wrapped else plate])[0]
    document.recompute()

    inside = [
        name
        for name in geom.getToplevelElements(0)
        if name.startswith("Face") and geom.getEntityOwners(name)
    ]
    assert len(inside) == 1, f"the plate reaches into the box once, not {len(inside)} times"
    face = inside[0]

    shape = geom.Shape
    bound = shape.getElement(face).Edges[0]
    edge = next(
        f"Edge{i}" for i, other in enumerate(shape.Edges, 1) if other.isSame(bound)
    )
    return geom, face, edge



def _embedded_bar(document, host="Solid"):
    """
    A bar fused into a solid, or into a face, and the names the fuse leaves.

    The 1D twin of _embedded_shell: the bar is an edge of the shape it was
    fused into and a model element in its own right at the same time. Returns
    the geometry, the name of the host toplevel, the bar's entity name, and an
    edge that belongs to the host alone -- the two edges have to come out
    differently or the bar is not being told apart from the host's own wires.
    """
    if host == "Solid":
        base = Part.makeBox(10, 10, 10)
        bar = Part.makeLine(FreeCAD.Vector(2, 5, 5), FreeCAD.Vector(8, 5, 5))
    else:
        base = Part.makePlane(10, 10)
        bar = Part.makeLine(FreeCAD.Vector(0, 5, 0), FreeCAD.Vector(10, 5, 0))

    geom = document.addObject("Fem::FemGeometry", "Geometry")
    geom.Shape = base.generalFuse([bar])[0]
    document.recompute()

    toplevels = geom.getToplevelElements(0)
    bar_name = next(name for name in toplevels if name.startswith("Edge"))
    host_name = next(name for name in toplevels if not name.startswith("Edge"))
    # An edge the host owns and nothing else does. A solid reaches its own edges
    # twice, once through each face, so the owners are compared as a set.
    plain = next(
        f"Edge{i}"
        for i in range(1, len(geom.Shape.Edges) + 1)
        if set(geom.getEntityOwners(f"Edge{i}")) == {host_name}
    )
    return geom, host_name, bar_name, plain


def _make_two_solid_tet_mesh():
    """Two tetrahedra in a group each, so one solid can be hidden by name."""
    mesh = Fem.FemMesh()
    for solid, offset in ((1, 0.0), (2, 4.0)):
        base = mesh.NodeCount
        mesh.addNode(offset, 0, 0, base + 1)
        mesh.addNode(offset + 1, 0, 0, base + 2)
        mesh.addNode(offset, 1, 0, base + 3)
        mesh.addNode(offset, 0, 1, base + 4)
        nodes = [base + 1, base + 2, base + 3, base + 4]
        vol = mesh.addVolume(nodes)
        gid = mesh.addGroup(f"Solid{solid}", "Volume")
        mesh.addGroupElements(gid, [vol])
        faces = [
            mesh.addFace([nodes[0], nodes[1], nodes[2]]),
            mesh.addFace([nodes[0], nodes[1], nodes[3]]),
            mesh.addFace([nodes[0], nodes[2], nodes[3]]),
            mesh.addFace([nodes[1], nodes[2], nodes[3]]),
        ]
        for i, face in enumerate(faces, start=1 + (solid - 1) * 4):
            fid = mesh.addGroup(f"Face{i}", "Face")
            mesh.addGroupElements(fid, [face])
    return mesh


def _exported_element_ids(mesh, elem_param, element_ids=None):
    """Element ids written to an ABAQUS input deck, keyed by element type."""
    kwargs = {} if element_ids is None else {"elementIds": element_ids}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "mesh.inp")
        mesh.writeABAQUS(path, elem_param, False, **kwargs)
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

    def test_pieces_are_found_however_deep_the_compounds_are_stacked(self):
        """
        Compounds and compsolids group pieces without being pieces themselves.

        A chain stacks them: every step that keeps its input compounds it with
        what it adds, so three steps leave three levels, and a partition
        compounds the pieces it cut inside that again. A compsolid arrives the
        same way from a glued import. None of that changes what was handed in,
        so the walk descends through every layer of grouping and stops at the
        first thing that is not one.
        """
        box = _box()
        far = Part.makeBox(10, 10, 10, FreeCAD.Vector(20, 0, 0))
        plate = Part.makePlane(10, 10, FreeCAD.Vector(0, 0, 30), FreeCAD.Vector(0, 0, 1))
        glued = _box().generalFuse([Part.makeBox(10, 10, 10, FreeCAD.Vector(10, 0, 0))])[0]
        compsolid = Part.CompSolid(glued.Solids)

        for label, shape, expected in (
            ("one level", Part.makeCompound([Part.makeCompound([box]), far]),
             ["Solid1", "Solid2"]),
            ("five levels", Part.makeCompound([Part.makeCompound([Part.makeCompound(
                [Part.makeCompound([Part.makeCompound([box])])])])]), ["Solid1"]),
            ("an empty compound has nothing to give",
             Part.makeCompound([Part.makeCompound([]), box]), ["Solid1"]),
            ("a compsolid is a grouping too", compsolid, ["Solid1", "Solid2"]),
            ("and stays one when compounded",
             Part.makeCompound([Part.makeCompound([compsolid]), plate]),
             ["Solid1", "Solid2", "Face12"]),
        ):
            with self.subTest(shape=label):
                geom = self.document.addObject("Fem::FemGeometry", "Geometry")
                geom.Shape = shape
                self.document.recompute()
                toplevels = []
                for component in range(geom.getComponentCount()):
                    toplevels += geom.getToplevelElements(component)
                self.assertEqual(sorted(toplevels), sorted(expected))

    def test_a_bar_fused_through_a_solid_is_one_toplevel(self):
        """
        The fuse leaves the bar twice over.

        Once as a piece of its result, and once imprinted inside the solid as an
        edge that belongs to no wire. Only the first was handed in to be
        analysed; taking the second for a piece as well gives the tree two rows
        for one bar and counts a 1D element that is not there.
        """
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        bar = Part.makeLine(FreeCAD.Vector(2, 5, 5), FreeCAD.Vector(8, 5, 5))
        geom.Shape = _box().generalFuse([bar])[0]
        self.document.recompute()

        toplevels = geom.getToplevelElements(0)
        self.assertEqual(sorted(toplevels), ["Edge1", "Solid1"])
        self.assertEqual(len(toplevels), len(set(toplevels)), "one row to a piece")
        self.assertEqual(
            geom.getEntityOwners("Edge1"),
            ["Solid1", "Edge1"],
            "and it is still the bar embedded in the solid",
        )

    def test_a_bar_landing_on_a_face_leaves_no_vertex_toplevel(self):
        """
        Where the bar meets the face the fuse imprints a vertex, and it belongs
        to no edge. That is a mark the fuse left behind rather than anything
        handed in, so it is no piece of the model and gets no row of its own.
        """
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        bar = Part.makeLine(FreeCAD.Vector(5, 5, 0), FreeCAD.Vector(5, 5, 10))
        geom.Shape = Part.makePlane(10, 10).generalFuse([bar])[0]
        self.document.recompute()

        toplevels = geom.getToplevelElements(0)
        self.assertEqual(sorted(toplevels), ["Edge1", "Face1"])
        self.assertFalse(
            [name for name in toplevels if name.startswith("Vertex")],
            f"a vertex the fuse imprinted is no piece: {toplevels}",
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

    def test_every_entity_of_a_component_leads_back_to_it(self):
        """
        A 3D click reports the entity under the pointer, which is as likely to
        be a face of a solid as the toplevel element itself. The component
        picker maps one to the other through this, so the sub-entities have to
        be in it and no name may land in two components.
        """
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        face = _face_xy()
        face.translate(FreeCAD.Vector(50, 0, 0))
        geom.Shape = Part.makeCompound([_box(), face])
        self.document.recompute()

        lookup = meshcomponents.component_lookup(geom)
        for index in range(1, geom.getComponentCount() + 1):
            names = meshcomponents.component_element_names(geom, index)
            self.assertTrue(names)
            for name in names:
                self.assertEqual(lookup.get(name), index, f"{name} does not lead to {index}")

        # The box carries its faces and edges, the loose face only its own
        self.assertTrue(any(name.startswith("Solid") for name in lookup))
        self.assertTrue(any(name.startswith("Vertex") for name in lookup))

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

    def _vertex_names(self, shape, *points):
        """Sub-element names of the vertices sitting at those positions."""
        names = []
        for point in points:
            for index, vertex in enumerate(shape.Vertexes, 1):
                if (vertex.Point - point).Length < 1e-7:
                    names.append(f"Vertex{index}")
                    break
            else:
                raise AssertionError(f"no vertex at {point}")
        return tuple(names)

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
        from femobjects.geometry_partition import MEASURE_NAMES

        for name, was, now in zip(MEASURE_NAMES, _measure(before), _measure(after)):
            self.assertAlmostEqual(
                now,
                was,
                delta=max(abs(was) * 1e-6, 1e-9),
                msg=f"partition changed the {name} of the shape",
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

    def test_build_tool_preview_returns_none_while_unconfigured(self):
        from femobjects import geometry_partition as gp

        _, _, part = self._chain(Part.makeBox(20, 10, 10))
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = None
        self.assertIsNone(gp.build_tool_preview(part))

    def test_build_tool_preview_for_plane_by_reference(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(Part.makeBox(20, 10, 10))
        part.Method = gp.METHOD_PLANE_REF
        part.Tool = (self._datum(FreeCAD.Vector(10, 0, 0), FreeCAD.Vector(1, 0, 0)), "")
        preview = gp.build_tool_preview(part)
        self.assertIsNotNone(preview)
        self.assertEqual(preview.mode, gp.TOOL_MODE_PLANE)
        self.assertFalse(preview.shape.isNull())
        self.assertGreater(preview.shape.BoundBox.DiagonalLength, imp.Shape.BoundBox.DiagonalLength)

    def test_build_tool_preview_for_plane_by_three_points(self):
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
        part.Points = [(imp, ("Vertex1", "Vertex2"))]
        self.assertIsNone(gp.build_tool_preview(part), "two picks is unfinished")

        part.Points = [(imp, tuple(picks))]
        preview = gp.build_tool_preview(part)
        self.assertIsNotNone(preview)
        self.assertEqual(preview.mode, gp.TOOL_MODE_PLANE)
        self.assertFalse(preview.shape.isNull())

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
        tool = gp._extended_face_tool((imp, (lateral,)), imp.Shape.BoundBox)

        self.assertIsInstance(tool.Faces[0].Surface, Part.Cylinder)
        self.assertIsNone(
            gp._plane_placement(tool.Faces[0]),
            "a curved tool must not be treated as a half-space plane",
        )

    def test_extend_face_needs_a_face_reference(self):
        from femobjects import geometry_partition as gp

        _, imp, part = self._chain(_box())
        part.Method = gp.METHOD_EXTEND_FACE
        part.Tool = (imp, "Edge1")
        self.document.recompute()
        self.assertInvalid(part)

    def test_extend_face_accepts_a_face_from_a_placed_import(self):
        """
        The cutting tool may come from a placed analysis import; only the
        targets have to sit on the step input.
        """
        from femobjects import geometry_partition as gp
        from femtools import importtools

        donor = ObjectsFem.makeAnalysis(self.document, "Donor")
        donor_geom = ObjectsFem.makeGeometryGroup(self.document)
        donor.addObject(donor_geom)
        donor_part = self.document.addObject("Part::Feature", "DonorPart")
        donor_part.Shape = Part.makeBox(20, 20, 5)
        donor_imp = ObjectsFem.makeGeometryImport(self.document)
        donor_imp.Import = [donor_part]
        donor_geom.Group = [donor_imp]
        self.document.recompute()

        host = ObjectsFem.makeAnalysis(self.document, "Host")
        host_geom = ObjectsFem.makeGeometryGroup(self.document)
        host.addObject(host_geom)
        host_part = self.document.addObject("Part::Feature", "HostPart")
        host_part.Shape = Part.makeBox(40, 20, 20)
        host_imp = ObjectsFem.makeGeometryImport(self.document)
        host_imp.Import = [host_part]
        host_geom.Group = [host_imp]
        self.document.recompute()

        placed = ObjectsFem.makeAnalysisImport(self.document, "DonorPlaced")
        placed.Analysis = donor
        importtools.wire_import(host, placed)
        self.document.recompute()

        part = ObjectsFem.makeGeometryPartition(self.document)
        host_geom.Group = [host_imp, part]
        self.document.recompute()

        part.Method = gp.METHOD_EXTEND_FACE
        part.Tool = (placed, ("Face6",))
        self.document.recompute()

        self.assertValid(part)
        self.assertMeasurePreserved(host_imp.Shape, part.Shape)

    def test_extend_face_accepts_a_nested_import_face_path(self):
        """
        A face picked inside a nested placed import is stored as Inner.Face3,
        not Face3 alone; the tool builder has to read the leaf, not the prefix.
        """
        from femobjects import geometry_partition as gp
        from femtools import importtools

        def _one_box(name):
            analysis = ObjectsFem.makeAnalysis(self.document, name)
            geometry = ObjectsFem.makeGeometryGroup(self.document, name + "Geometry")
            analysis.addObject(geometry)
            part = self.document.addObject("Part::Feature", name + "Part")
            part.Shape = Part.makeBox(10, 10, 10)
            step = ObjectsFem.makeGeometryImport(self.document)
            step.Import = [part]
            geometry.Group = [step]
            return analysis

        def _place(source, into, name):
            placed = ObjectsFem.makeAnalysisImport(self.document, name)
            placed.Analysis = source
            container = importtools.wire_import(into, placed)
            return placed, container

        leg = _one_box("Leg")
        side = _one_box("Side")
        inner, _ = _place(leg, side, "Inner")
        table = _one_box("Table")
        outer, _ = _place(side, table, "Outer")
        self.document.recompute()

        host_geom = table.Group[0]
        host_imp = host_geom.Group[0]
        part = ObjectsFem.makeGeometryPartition(self.document)
        host_geom.Group = [host_imp, part]
        self.document.recompute()

        nested_sub = f"{inner.Name}.Face1"
        tool = gp._extended_face_tool((outer, (nested_sub,)), host_imp.Shape.BoundBox)
        self.assertFalse(tool.isNull())

        part.Method = gp.METHOD_EXTEND_FACE
        part.Tool = (outer, (nested_sub,))
        self.document.recompute()
        self.assertValid(part)

    def test_plane_by_three_points_accepts_nested_import_vertices(self):
        from femobjects import geometry_partition as gp
        from femtools import importtools

        donor = ObjectsFem.makeAnalysis(self.document, "Donor")
        donor_geom = ObjectsFem.makeGeometryGroup(self.document)
        donor.addObject(donor_geom)
        donor_part = self.document.addObject("Part::Feature", "DonorPart")
        donor_part.Shape = Part.makeBox(20, 10, 10)
        donor_imp = ObjectsFem.makeGeometryImport(self.document)
        donor_imp.Import = [donor_part]
        donor_geom.Group = [donor_imp]
        self.document.recompute()

        host = ObjectsFem.makeAnalysis(self.document, "Host")
        host_geom = ObjectsFem.makeGeometryGroup(self.document)
        host.addObject(host_geom)
        host_part = self.document.addObject("Part::Feature", "HostPart")
        host_part.Shape = Part.makeBox(40, 20, 20)
        host_imp = ObjectsFem.makeGeometryImport(self.document)
        host_imp.Import = [host_part]
        host_geom.Group = [host_imp]
        self.document.recompute()

        placed = ObjectsFem.makeAnalysisImport(self.document, "DonorPlaced")
        placed.Analysis = donor
        importtools.wire_import(host, placed)
        self.document.recompute()

        part = ObjectsFem.makeGeometryPartition(self.document)
        host_geom.Group = [host_imp, part]
        self.document.recompute()

        picks = tuple(f"Vertex{index}" for index in (1, 2, 7))
        part.Method = gp.METHOD_PLANE_3P
        part.Points = [(placed, picks)]
        self.document.recompute()
        self.assertValid(part)

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

    def test_a_solid_is_cut_beside_a_loose_face(self):
        """
        Mixed geometry: a solid to cut and a face that is no part of it.

        Part's Volume over such a compound is not the volume of its solids —
        the loose face enters the integral too — so measuring the shape as a
        single number made every cut here look like it had eaten geometry,
        and the step refused a partition that was perfectly sound.
        """
        from femobjects import geometry_partition as gp

        solid = Part.makeBox(10, 10, 5)
        loose = Part.makePlane(10, 10, FreeCAD.Vector(10, 0, 2))
        _, imp, part = self._chain(solid, loose)
        self.assertNotAlmostEqual(
            imp.Shape.Volume,
            solid.Volume,
            msg="this test is pointless unless the compound misreports its volume",
        )

        # A slanted plane through three corners of the box. Named by position,
        # because the loose face takes the first vertex numbers of the compound.
        corners = self._vertex_names(
            imp.Shape,
            FreeCAD.Vector(0, 0, 0),
            FreeCAD.Vector(10, 0, 5),
            FreeCAD.Vector(0, 10, 0),
        )
        part.Method = gp.METHOD_PLANE_3P
        part.Elements = [(imp, ("Solid1",))]
        part.Points = [(imp, corners)]
        self.document.recompute()

        self.assertValid(part)
        self.assertEqual(len(part.Shape.Solids), 2, "the solid has to come out cut in two")
        self.assertMeasurePreserved(imp.Shape, part.Shape)
        self.assertAlmostEqual(
            sum(face.Area for face in part.Shape.Faces if face.Area == loose.Area),
            loose.Area,
            msg="the loose face has to survive the cut untouched",
        )

    def test_a_loose_face_is_not_counted_as_volume(self):
        """The three measures are kept apart, so neither can mask the other."""
        from femobjects import geometry_partition as gp

        solid = Part.makeBox(10, 10, 5)
        loose = Part.makePlane(10, 10, FreeCAD.Vector(10, 0, 2))
        mixed = Part.makeCompound([solid, loose])

        volume, area, length = gp._measure(mixed)
        self.assertAlmostEqual(volume, solid.Volume)
        self.assertAlmostEqual(area, loose.Area, msg="only the face that bounds no solid counts")
        self.assertAlmostEqual(length, 0.0, msg="every edge here bounds a face")

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

    def test_the_symbol_points_say_which_reference_they_came_from(self):
        """
        Points is one flat list over all references, so anything wanting to
        draw one reference differently from another, as a tie does with its
        master, has nothing to tell them apart by. PointsPerReference is the
        run lengths that cut the list back up.
        """
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        constraint.References = [(self.group, ["Face1", "Face2"])]
        self.document.recompute()

        groups = list(constraint.PointsPerReference)
        self.assertEqual(len(groups), 2, "a run per reference, sub-elements counted apart")
        self.assertEqual(sum(groups), len(constraint.Points))
        self.assertTrue(all(count > 0 for count in groups), groups)

        # Editing the references has to re-cut the list, not add to it.
        constraint.References = [(self.group, ["Face1"])]
        self.document.recompute()
        self.assertEqual(len(list(constraint.PointsPerReference)), 1)
        self.assertEqual(sum(constraint.PointsPerReference), len(constraint.Points))

    def test_a_path_into_the_chain_names_the_step_it_ends_at(self):
        """
        A click on a chain step, while a task panel previews it, arrives as a
        path down through the analysis and the geometry group. Answering it
        with a container is answering with the wrong shape: the result of the
        chain is not what was clicked, and its Face1 is a different face from
        the step's. A selection gate asking what the reference is then refuses
        every pick, which leaves no way to fill an empty reference field.
        """
        step = self.group.Group[0]
        path = f"{step.Name}.Face1"

        self.assertIs(self.group.getSubObject(path, retType=1), step)
        self.assertIs(
            self.analysis.getSubObject(f"{self.group.Name}.{path}", retType=1),
            step,
        )

    def test_a_path_of_one_word_still_names_the_group(self):
        """The result of the chain is what the group itself holds and draws."""
        self.assertIs(self.group.getSubObject("Face1", retType=1), self.group)
        self.assertIs(
            self.analysis.getSubObject(f"{self.group.Name}.Face1", retType=1),
            self.group,
        )
        self.assertIsNotNone(self.group.getSubObject("Face1"), "the shape comes with it")

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


class TestElementSetsFromGroups(unittest.TestCase):
    """Element sets of a mesh that has groups are read out, not searched for.

    A mesh made from geometry names a group after every solid, face and edge
    it was meshed from, so which elements a reference stands for is already
    written down. The search that replaces a missing group has to ask the
    geometry kernel for the nodes of the reference and then walk the elements
    looking for them, which on an assembly of a few parts is the bulk of the
    time a solver write takes.
    """

    fcc_print("import TestElementSetsFromGroups")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)
        self.analysis = ObjectsFem.makeAnalysis(self.document, "Analysis")
        self.solver = ObjectsFem.makeSolverCalculiX(self.document, "Solver")
        self.analysis.addObject(self.solver)
        # A solid and a free face, so that Solid1 and Face7 are both real
        # references and the mesh below can be of two dimensions.
        self.geometry = self.document.addObject("Part::Feature", "Geometry")
        self.geometry.Shape = Part.makeCompound([_box(), _face_xy()])

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def _mixed_mesh_object(self, with_groups=True):
        """A tet and a free triangle, each in a group named after its geometry."""
        mesh = Fem.FemMesh()
        for node_id, point in enumerate(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (10, 0, 0), (11, 0, 0), (10, 1, 0)],
            start=1,
        ):
            mesh.addNode(point[0], point[1], point[2], node_id)
        self.volume = mesh.addVolume([1, 2, 3, 4])
        self.shell = mesh.addFace([5, 6, 7])
        if with_groups:
            for name, group_type, members in (
                ("Solid1", "Volume", [self.volume]),
                ("Face7", "Face", [self.shell]),
            ):
                mesh.addGroupElements(mesh.addGroup(name, group_type), members)

        mesh_obj = self.document.addObject("Fem::FemMeshObject", "Mesh")
        mesh_obj.FemMesh = mesh
        self.analysis.addObject(mesh_obj)
        return mesh_obj

    def _materials(self, rest_has_references=False):
        """One material on the solid and one for whatever is left over.

        A material without references is how a model says "the rest of it",
        and a mixed mesh leaves the rest in a dimension of its own.
        """
        solid = ObjectsFem.makeMaterialSolid(self.document, "SolidMaterial")
        solid.References = [(self.geometry, ["Solid1"])]
        self.analysis.addObject(solid)

        rest = ObjectsFem.makeMaterialSolid(self.document, "RestMaterial")
        if rest_has_references:
            rest.References = [(self.geometry, ["Face7"])]
        self.analysis.addObject(rest)

        # Without a section the shell elements are nothing the writer asks
        # about, and the face dimension is never looked at.
        shell = ObjectsFem.makeElementGeometry2D(self.document, 1.0, "Thickness")
        self.analysis.addObject(shell)
        self.document.recompute()
        return solid, rest

    def _getter(self, mesh_obj):
        from femmesh import meshsetsgetter
        from femtools import membertools

        return meshsetsgetter.MeshSetsGetter(
            self.analysis, self.solver, mesh_obj, membertools.AnalysisMember(self.analysis)
        )

    def _count_searches(self):
        """Calls that fall through to the geometric search, as they happen."""
        from femmesh import meshtools

        calls = []
        original = meshtools.get_femelements_by_references

        def counted(femmesh, table, references, *args, **kwargs):
            calls.append([sub for _, subs in references for sub in subs])
            return original(femmesh, table, references, *args, **kwargs)

        meshtools.get_femelements_by_references = counted
        self.addCleanup(setattr, meshtools, "get_femelements_by_references", original)
        return calls

    @staticmethod
    def _elements_of(getter, material):
        for femobj in getter.member.mats_linear:
            if femobj["Object"].Name == material.Name:
                return sorted(femobj["FEMElements"])
        raise AssertionError(f"{material.Name} is no member of the analysis")

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestElementSetsFromGroups tests {2}\n{0}".format(
                100 * "*", 10 * "*", 45 * "*"
            )
        )

    def test_every_dimension_is_read_from_the_groups(self):
        # The solid dimension has been read from the groups for a long time,
        # the others were searched for even when the group was right there.
        mesh_obj = self._mixed_mesh_object()
        solid, rest = self._materials(rest_has_references=True)
        getter = self._getter(mesh_obj)
        searches = self._count_searches()

        getter.get_material_elements()

        self.assertFalse(searches, "a reference the mesh has a group for was searched for")
        self.assertEqual(self._elements_of(getter, solid), [self.volume])
        self.assertEqual(self._elements_of(getter, rest), [self.shell])

    def test_the_material_without_references_takes_what_the_groups_leave(self):
        # Reading the groups only answers for the references that name one, so
        # a material standing for the remainder used to send every other
        # material through the search as well, one dimension at a time.
        mesh_obj = self._mixed_mesh_object()
        solid, rest = self._materials()
        getter = self._getter(mesh_obj)
        searches = self._count_searches()

        getter.get_material_elements()

        self.assertFalse(searches, "the remainder was worked out by searching")
        self.assertEqual(self._elements_of(getter, solid), [self.volume])
        self.assertEqual(self._elements_of(getter, rest), [self.shell])

    def test_a_mesh_without_groups_is_still_searched(self):
        # The groups are a shortcut, not a requirement; an imported mesh has
        # none and has to keep working.
        mesh_obj = self._mixed_mesh_object(with_groups=False)
        solid, _ = self._materials()
        getter = self._getter(mesh_obj)
        searches = self._count_searches()

        getter.get_material_elements()

        self.assertTrue(searches, "a mesh without groups left the elements unaccounted for")
        self.assertEqual(self._elements_of(getter, solid), [self.volume])


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

    def test_merge_two_children(self):
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
        The merge is an output of execute(). Reading it must not mark anything
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


def _make_groupless_tet_mesh():
    """Tetrahedron without SMESH groups — triggers catch-all toplevels."""
    mesh = Fem.FemMesh()
    mesh.addNode(0, 0, 0, 1)
    mesh.addNode(1, 0, 0, 2)
    mesh.addNode(0, 1, 0, 3)
    mesh.addNode(0, 0, 1, 4)
    vol = mesh.addVolume([1, 2, 3, 4])
    return mesh, vol


def _make_fused_two_solid_tet_mesh():
    """
    Two volume groups that share nodes, so the mesh is one component while
    geometry that names the same solids as two components stays two. Models
    what Gmsh CoherenceMesh does to touching parts.
    """
    mesh = Fem.FemMesh()
    # Shared face nodes 1,2,3; Solid1 apex at 4, Solid2 apex at 5.
    mesh.addNode(0, 0, 0, 1)
    mesh.addNode(1, 0, 0, 2)
    mesh.addNode(0, 1, 0, 3)
    mesh.addNode(0, 0, 1, 4)
    mesh.addNode(0, 0, -1, 5)
    vol1 = mesh.addVolume([1, 2, 3, 4])
    vol2 = mesh.addVolume([1, 2, 3, 5])
    g1 = mesh.addGroup("Solid1", "Volume")
    mesh.addGroupElements(g1, [vol1])
    g2 = mesh.addGroup("Solid2", "Volume")
    mesh.addGroupElements(g2, [vol2])
    return mesh


class TestMeshTopology(unittest.TestCase):
    fcc_print("import TestMeshTopology")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestMeshTopology tests {2}\n{0}".format(100 * "*", 10 * "*", 54 * "*")
        )

    def test_catchall_for_groupless_mesh(self):
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        mesh, vol = _make_groupless_tet_mesh()
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()

        _ = group.FemMesh  # trigger merge + topology
        self.assertEqual(group.getComponentCount(), 1)
        toplevels = group.getToplevelElements(0)
        self.assertEqual(toplevels, ["Component1_Volume"])
        self.assertEqual(group.getAnalysisDimension("Component1_Volume"), 3)

    def test_a_shell_in_a_solid_is_a_mesh_toplevel_and_names_the_solid(self):
        """
        The mesh answers this for itself, from its own nodes.

        A group holding model elements is a toplevel whatever its dimension, so
        the shell is listed beside the solid rather than filed away as a part of
        it. Which of its neighbours it belongs to is then a question about nodes
        alone: the whole of the shell covering the block sits on the block's
        nodes and is part of it, while the piece hanging off the side merely
        shares the seam and is part of nothing. Meeting a solid is not being
        inside one, and only the second is worth saying.
        """
        geom, covered, _ = _embedded_shell(self.document)
        free = next(
            name
            for name in geom.getToplevelElements(0)
            if name.startswith("Face") and name != covered
        )

        mesh = Fem.FemMesh()
        for node, (x, y, z) in enumerate(
            [
                (0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
                (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10),
                (20, 0, 10), (20, 10, 10),
            ],
            start=1,
        ):  # fmt: skip
            mesh.addNode(x, y, z, node)
        volume = mesh.addVolume([1, 2, 3, 4, 5, 6, 7, 8])
        # The whole top of the block, on nothing but the block's own nodes.
        covering = [mesh.addFace([5, 6, 7]), mesh.addFace([5, 7, 8])]
        # Hanging off the side, holding the seam nodes 6 and 7 in common.
        overhang = [mesh.addFace([6, 9, 10]), mesh.addFace([6, 10, 7])]
        for name, kind, ids in (
            ("Solid1", "Volume", [volume]),
            (covered, "Face", covering),
            (free, "Face", overhang),
        ):
            mesh.addGroupElements(mesh.addGroup(name, kind), ids)

        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        group.Shape = geom
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()
        _ = group.FemMesh

        self.assertEqual(
            sorted(group.getToplevelElements(0)),
            sorted(["Solid1", covered, free]),
            "a group of model elements is a toplevel whatever its dimension",
        )
        self.assertEqual(group.getEntityOwners(covered), ["Solid1"])
        self.assertEqual(
            group.getEntityOwners(free), [], "sharing a seam is not sitting inside"
        )
        self.assertEqual(group.getAnalysisDimension(covered), 2)
        self.assertEqual(group.getAnalysisDimension("Solid1"), 3)

    def test_a_bar_in_a_solid_is_a_mesh_toplevel_and_names_the_solid(self):
        """
        The 1D twin of the shell case, and a sharper test of the same rule.

        A bar can touch a solid at a single node, which is all "shares nodes"
        ever asked for, so a rule built on meeting rather than on being inside
        would call the bar that merely ends on the block part of it. Only the
        bar whose every node is the block's is inside it.
        """
        box = Part.makeBox(10, 10, 10)
        inside = Part.makeLine(FreeCAD.Vector(2, 5, 5), FreeCAD.Vector(8, 5, 5))
        touching = Part.makeLine(FreeCAD.Vector(10, 10, 10), FreeCAD.Vector(20, 10, 10))
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = box.generalFuse([inside, touching])[0]
        self.document.recompute()

        bars = [n for n in geom.getToplevelElements(0) if n.startswith("Edge")]
        self.assertEqual(len(bars), 2, f"both bars are pieces of their own: {bars}")
        embedded = next(n for n in bars if geom.getEntityOwners(n))
        beside = next(n for n in bars if not geom.getEntityOwners(n))

        mesh = Fem.FemMesh()
        for node, (x, y, z) in enumerate(
            [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
             (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10), (20, 10, 10)],
            start=1,
        ):  # fmt: skip
            mesh.addNode(x, y, z, node)
        volume = mesh.addVolume([1, 2, 3, 4, 5, 6, 7, 8])
        # Both of its nodes are the block's, so it runs inside it.
        within = mesh.addEdge([1, 7])
        # One end on the block and one beyond it: it meets the block, no more.
        outside = mesh.addEdge([7, 9])
        for name, ids in (("Solid1", [volume]),):
            mesh.addGroupElements(mesh.addGroup(name, "Volume"), ids)
        for name, ids in ((embedded, [within]), (beside, [outside])):
            mesh.addGroupElements(mesh.addGroup(name, "Edge"), ids)

        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        group.Shape = geom
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()
        _ = group.FemMesh

        self.assertEqual(
            sorted(group.getToplevelElements(0)),
            sorted(["Solid1", embedded, beside]),
            "a bar is a toplevel of the mesh like anything else that is solved",
        )
        self.assertEqual(group.getEntityOwners(embedded), ["Solid1"])
        self.assertEqual(
            group.getEntityOwners(beside), [], "ending on the block is not running through it"
        )
        self.assertEqual(group.getAnalysisDimension(embedded), 1)

    def test_two_disconnected_solids_are_two_components(self):
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        child.FemMesh = _make_two_solid_tet_mesh()
        group.Group = [child]
        self.document.recompute()
        _ = group.FemMesh
        self.assertEqual(group.getComponentCount(), 2)

    def test_the_catchall_is_written_onto_the_mesh(self):
        """
        A catch-all is derived, so nothing on the mesh named the elements behind
        it and everything reading names off the mesh -- the colouring, the
        solver writers -- passed them by. The container writes the group.
        """
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        mesh, vol = _make_groupless_tet_mesh()
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()

        merged = group.FemMesh
        gid = merged.getGroupIdByName("Component1_Volume")
        self.assertGreaterEqual(gid, 0)
        self.assertEqual(list(merged.getGroupElements(gid)), [vol])
        self.assertEqual(merged.getGroupElementType(gid), "Volume")

    def test_a_catchall_carried_in_by_a_mesh_is_not_read_back(self):
        """
        A deck exported from us and imported again carries our catch-all names.
        They describe the leftovers of the build that wrote them, so reading one
        back would let it stand in for elements it no longer covers.
        """
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")

        mesh, vol = _make_groupless_tet_mesh()
        # A stale catch-all, naming a component number this mesh does not have.
        gid = mesh.addGroup("Component7_Volume", "Volume")
        mesh.addGroupElements(gid, [vol])
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()

        _ = group.FemMesh
        self.assertEqual(group.getToplevelElements(0), ["Component1_Volume"])

    def test_entity_is_owned_only_by_the_toplevel_it_touches(self):
        """
        Two named volume groups on disconnected bodies are a toplevel each. A
        face group on one of them belongs to that one, not to both.
        """
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")

        mesh = Fem.FemMesh()
        volumes = []
        first_face = None
        for body, offset in enumerate((0, 10)):
            base = body * 4 + 1
            for i, (x, y, z) in enumerate([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]):
                mesh.addNode(x + offset, y, z, base + i)
            volumes.append(mesh.addVolume([base, base + 1, base + 2, base + 3]))
            face = mesh.addFace([base, base + 1, base + 2])
            if first_face is None:
                first_face = face
            gid = mesh.addGroup(f"Body{body + 1}", "Volume")
            mesh.addGroupElements(gid, [volumes[-1]])
        gid = mesh.addGroup("Skin", "Face")
        mesh.addGroupElements(gid, [first_face])

        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()

        self.assertEqual(group.getComponentCount(), 2)
        self.assertEqual(group.getEntityOwners("Skin"), ["Body1"])
        self.assertEqual(group.getEntities("Body1"), ["Skin"])
        self.assertEqual(group.getEntities("Body2"), [])

    def test_group_elements_by_name(self):
        """
        getGroupElementsByName returns the element ids behind a named group,
        including catch-alls the merge wrote onto the mesh.
        """
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        mesh, vol = _make_groupless_tet_mesh()
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()

        _ = group.FemMesh
        self.assertEqual(group.getGroupElementsByName("Component1_Volume"), [vol])
        self.assertEqual(group.getGroupElementsByName("NoSuchGroup"), [])

    def test_topology_reads_never_merge(self):
        """
        Reading the topology merges nothing at all.

        The panel rebuilds on every view-state notify, and a getter that merged
        would run the whole classification once per notify - and would do it
        outside the recompute the document schedules for it.
        """
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        mesh, _ = _make_groupless_tet_mesh()
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()

        Fem.perfReset()
        Fem.perfEnable(True)
        try:
            for _ in range(5):
                self.assertEqual(group.getComponentCount(), 1)
                self.assertEqual(group.getToplevelElements(0), ["Component1_Volume"])
                self.assertEqual(group.FemMesh.VolumeCount, 1)
        finally:
            Fem.perfEnable(False)

        report = {name: count for name, count, _total, _self in Fem.perfReport()}
        self.assertEqual(report.get("merge", 0), 0)
        self.assertEqual(report.get("merge.placement", 0), 0)

    def _fused_analysis(self):
        """
        Two geometry components whose mesh shares nodes (one mesh component).
        """
        analysis = ObjectsFem.makeAnalysis(self.document, "Analysis")
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        # Touching boxes share a face geometrically but not topologically, so
        # they stay two components — the same setup CoherenceMesh then fuses.
        geom.Shape = Part.makeCompound(
            [Part.makeBox(10, 10, 10), Part.makeBox(10, 10, 10, FreeCAD.Vector(10, 0, 0))]
        )
        analysis.addObject(geom)

        group = self.document.addObject("Fem::FemMeshShapeGroup", "Mesh")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        child.FemMesh = _make_fused_two_solid_tet_mesh()
        group.Group = [child]
        group.Shape = geom
        analysis.addObject(group)
        self.document.recompute()
        return analysis, geom, group

    def test_fused_mesh_is_one_component_while_geometry_stays_two(self):
        """Gmsh CoherenceMesh leaves geometry apart and joins the mesh."""
        _, geom, group = self._fused_analysis()
        self.assertEqual(geom.getComponentCount(), 2)
        self.assertEqual(sorted(geom.getToplevelElements(0)), ["Solid1"])
        self.assertEqual(sorted(geom.getToplevelElements(1)), ["Solid2"])

        _ = group.FemMesh
        self.assertEqual(group.getComponentCount(), 1)
        self.assertEqual(sorted(group.getToplevelElements(0)), ["Solid1", "Solid2"])

    def test_component_colour_follows_mesh_partition_and_keeps_shared_colour(self):
        """
        Mesh-stage Component categories come from the mesh, not the geometry.
        A fusion that joins Solid1 and Solid2 into one mesh component yields a
        single category, and that category keeps the colour of the geometry
        component that contributed the most (here Component1, one solid each
        so the tie goes to the lower id).
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for AnalysisViewState")

        import FemGui

        analysis, geom, group = self._fused_analysis()
        state = FemGui.getAnalysisViewState(analysis)

        # Colour mode is stage-scoped, so it has to be set again after each
        # switch rather than once up front.
        state.setActiveStage("Geometry")
        state.setColorMode("Component")
        geom_cats = {c["key"]: tuple(c["color"][:3]) for c in state.getCategories()}
        self.assertEqual(sorted(geom_cats), ["Component1", "Component2"])
        colour1 = geom_cats["Component1"]

        state.setActiveStage("Mesh")
        state.setColorMode("Component")
        mesh_cats = {c["key"]: tuple(c["color"][:3]) for c in state.getCategories()}
        self.assertEqual(
            sorted(k for k in mesh_cats if k.startswith("Component")),
            ["Component1"],
            "the fused mesh is one component in the Mesh stage",
        )
        self.assertEqual(
            mesh_cats["Component1"],
            colour1,
            "the surviving mesh component keeps Component1's geometry colour",
        )
        self.assertEqual(state.categoryOfElement("Solid1"), state.categoryOfElement("Solid2"))
        self.assertEqual(state.categoryOfElement("Solid1"), 0)

    def test_subelement_catch_all_does_not_shift_geometry_colours(self):
        """
        A mesh-only catch-all name must not shove Solid1 onto a different
        palette slot than the Geometry stage used.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for AnalysisViewState")

        import FemGui

        analysis = ObjectsFem.makeAnalysis(self.document, "Analysis")
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = Part.makeBox(10, 10, 10)
        analysis.addObject(geom)

        group = self.document.addObject("Fem::FemMeshShapeGroup", "Mesh")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        mesh, _ = _make_groupless_tet_mesh()
        child.FemMesh = mesh
        group.Group = [child]
        group.Shape = geom
        analysis.addObject(group)
        self.document.recompute()

        state = FemGui.getAnalysisViewState(analysis)

        # Colour mode is stage-scoped, so it has to be set again after each
        # switch rather than once up front.
        state.setActiveStage("Geometry")
        state.setColorMode("Subelement")
        geom_solid = next(
            c for c in state.getCategories() if c["key"] == "Solid1"
        )
        geom_colour = tuple(geom_solid["color"][:3])

        state.setActiveStage("Mesh")
        state.setColorMode("Subelement")
        mesh_cats = {c["key"]: tuple(c["color"][:3]) for c in state.getCategories()}
        self.assertIn("Component1_Volume", mesh_cats)
        self.assertIn("Solid1", mesh_cats)
        self.assertEqual(
            mesh_cats["Solid1"],
            geom_colour,
            "Solid1 keeps its geometry-stage colour when a catch-all appears",
        )


class TestExecuteDrivenOutputs(unittest.TestCase):
    """
    When the merge runs, rather than what it produces.

    The merged mesh, its provenance and its topology are outputs of execute(),
    and the group is a dependent of every child, so FreeCAD hands it a recompute
    for anything at all that happens to one. What is under test here is which
    change asks for the whole thing, which asks only for new coordinates, and
    which asks for nothing.
    """

    fcc_print("import TestExecuteDrivenOutputs")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestExecuteDrivenOutputs tests {2}\n{0}".format(
                100 * "*", 10 * "*", 47 * "*"
            )
        )

    # -- helpers ----------------------------------------------------------

    def _group_with_child(self, name="MeshA"):
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", name)
        mesh, _, _ = _make_tet_mesh()
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()
        return group, child

    def _merge_counts(self, action):
        """Merge stages a single action ran, by scope name."""
        Fem.perfReset()
        Fem.perfEnable(True)
        try:
            action()
        finally:
            Fem.perfEnable(False)
        report = {name: count for name, count, _total, _self in Fem.perfReport()}
        return report.get("merge", 0), report.get("merge.placement", 0)

    def _assert_output_matches_children(self, group):
        """The published merge is exactly what the children of the moment add up to."""
        children = sorted(group.Group, key=lambda obj: obj.Name)
        cells = group.FemMesh.VolumeCount + group.FemMesh.FaceCount
        self.assertEqual(group.FemMesh.NodeCount, sum(c.FemMesh.NodeCount for c in children))
        self.assertEqual(cells, sum(c.FemMesh.VolumeCount + c.FemMesh.FaceCount for c in children))
        self.assertEqual(len(group.CellSources), cells)
        self.assertEqual(len(group.CellDimension), cells)

    def _topology_snapshot(self, group):
        return {
            "components": group.getComponentCount(),
            "toplevels": [group.getToplevelElements(c) for c in range(group.getComponentCount())],
            "cell_sources": list(group.CellSources),
            "cell_dimension": list(group.CellDimension),
            "entity_dimension": dict(group.EntityDimension),
        }

    # -- what asks for a full rebuild --------------------------------------

    def test_child_mesh_assignment_merges_once(self):
        """One assignment of a child mesh, one full merge, and a new topology."""
        group, child = self._group_with_child()
        before_merge = group.getMergeRevision()
        before_topology = group.getTopologyRevision()

        def remesh():
            child.FemMesh = _make_two_solid_tet_mesh()
            self.document.recompute()

        full, placement = self._merge_counts(remesh)
        self.assertEqual(full, 1)
        self.assertEqual(placement, 0)

        self.assertEqual(group.getMergeRevision(), before_merge + 1)
        self.assertEqual(group.getTopologyRevision(), before_topology + 1)
        self.assertEqual(group.FemMesh.VolumeCount, 2)
        self.assertEqual(group.getComponentCount(), 2)
        self.assertEqual(
            len(group.CellSources), group.FemMesh.VolumeCount + group.FemMesh.FaceCount
        )

        # And the getters stay pure afterwards.
        full, placement = self._merge_counts(lambda: self._topology_snapshot(group))
        self.assertEqual((full, placement), (0, 0))

    def test_group_membership_change_rebuilds_once(self):
        """Adding a child is one rebuild, and the result stays name-sorted."""
        group, child_a = self._group_with_child("AMesh")
        child_z = self.document.addObject("Fem::FemMeshObject", "ZMesh")
        mesh_z, _ = _make_tri_mesh("Face12")
        child_z.FemMesh = mesh_z

        def add():
            group.Group = [child_z, child_a]
            self.document.recompute()

        full, placement = self._merge_counts(add)
        self.assertEqual(full, 1)
        self.assertEqual(placement, 0)

        # Sorted by Name, not by Group order: the tet of AMesh comes first.
        self.assertEqual(group.CellSources[0], child_a.Name)
        self.assertEqual(group.CellSources[-1], child_z.Name)

        ordered = list(group.CellSources)
        nodes = list(group.FemMesh.Nodes.values())

        def reorder():
            group.Group = [child_a, child_z]
            self.document.recompute()

        full, placement = self._merge_counts(reorder)
        self.assertEqual(full, 1)
        self.assertEqual(list(group.CellSources), ordered)
        self.assertEqual(list(group.FemMesh.Nodes.values()), nodes)

        def remove():
            group.Group = [child_a]
            self.document.recompute()

        full, placement = self._merge_counts(remove)
        self.assertEqual(full, 1)
        self.assertEqual(set(group.CellSources), {child_a.Name})

    # -- what asks for nothing ---------------------------------------------

    def test_a_geometry_change_clears_the_meshes(self):
        """
        A mesh is made for one shape and fits no other, so a geometry that has
        been rebuilt takes the meshes made against it with it. The mesher stays:
        its settings are the user's work and meshing again is one press.
        """
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = Part.makeBox(10, 10, 10)
        group = ObjectsFem.makeMeshShapeGroup(self.document, "Mesh", geometry=geom)
        child = self.document.addObject("Fem::FemMeshShapeBaseObjectPython", "MeshA")
        group.Group = [child]
        child.FemMesh = _make_tet_mesh()[0]
        self.document.recompute()
        self.assertGreater(child.FemMesh.NodeCount, 0)

        # A recompute that leaves the geometry alone must leave the mesh alone.
        self.document.recompute()
        self.assertGreater(
            child.FemMesh.NodeCount,
            0,
            "only a rebuilt geometry invalidates a mesh, not any recompute",
        )

        geom.Shape = Part.makeBox(20, 10, 10)
        self.document.recompute()
        self.assertEqual(
            child.FemMesh.NodeCount, 0, "the mesh of a geometry that changed has to go"
        )
        self.assertEqual(group.FemMesh.NodeCount, 0, "and so does the merge of it")
        self.assertIsNotNone(
            self.document.getObject("MeshA"), "the mesher itself is not thrown away"
        )

    def test_mesher_parameter_change_merges_nothing(self):
        """
        A mesher setting reaches the group as a recompute and stops there.

        Changing it does not produce a mesh by itself - the mesher has to be run
        - so nothing the group published follows from it yet.
        """
        group = ObjectsFem.makeMeshShapeGroup(self.document, "Mesh")
        mesher = ObjectsFem.makeMeshGmsh(self.document)
        ObjectsFem.addMeshToShapeGroup(group, mesher)
        mesher.FemMesh = _make_tet_mesh()[0]
        self.document.recompute()

        before_merge = group.getMergeRevision()
        before_topology = group.getTopologyRevision()
        before = self._topology_snapshot(group)
        nodes = dict(group.FemMesh.Nodes)

        def retune():
            mesher.CharacteristicLengthMax = 3.0
            self.document.recompute()

        full, placement = self._merge_counts(retune)
        self.assertEqual((full, placement), (0, 0))
        self.assertEqual(group.getMergeRevision(), before_merge)
        self.assertEqual(group.getTopologyRevision(), before_topology)
        self.assertEqual(self._topology_snapshot(group), before)
        self.assertEqual(dict(group.FemMesh.Nodes), nodes)

    def test_child_components_change_merges_nothing_until_remesh(self):
        """
        A component claim is checked when a mesh arrives, not when it is made.

        Claiming a component says which part of the geometry the child is going
        to mesh. Until it has meshed it, nothing about the merge has changed -
        but the claim in force when the mesh does arrive is the one that counts.
        """
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = Part.makeCompound(
            [Part.makeBox(10, 10, 10), Part.makeBox(10, 10, 10, FreeCAD.Vector(20, 0, 0))]
        )
        group = ObjectsFem.makeMeshShapeGroup(self.document, "Mesh", geometry=geom)
        child = self.document.addObject("Fem::FemMeshShapeBaseObjectPython", "MeshA")
        child.Components = (geom, ["Component1", "Component2"])
        group.Group = [child]
        child.FemMesh = _make_tet_mesh()[0]
        self.document.recompute()

        before_merge = group.getMergeRevision()
        before_topology = group.getTopologyRevision()

        def reclaim():
            child.Components = (geom, ["Component1"])
            self.document.recompute()

        full, placement = self._merge_counts(reclaim)
        self.assertEqual((full, placement), (0, 0))
        self.assertEqual(group.getMergeRevision(), before_merge)
        self.assertEqual(group.getTopologyRevision(), before_topology)

        # Component2 is now unclaimed, and the next mesh is validated against
        # that, not against the claim the last merge ran under.
        def remesh():
            child.FemMesh = _make_two_solid_tet_mesh()
            self.document.recompute()

        full, placement = self._merge_counts(remesh)
        self.assertEqual(full, 1)
        self.assertEqual(group.getComponentOwners(), {1: child})

    # -- what asks only for coordinates ------------------------------------

    def test_child_placement_remerges_coordinates_only(self):
        """
        Moving a child moves the merged nodes and leaves everything else alone.

        A rigid move renames nothing and reconnects nothing, so the element ids,
        the groups, the provenance and the dimensions of the last merge all
        still describe the mesh - only the coordinates are new.
        """
        group, child = self._group_with_child()
        before_merge = group.getMergeRevision()
        before_topology = group.getTopologyRevision()
        before = self._topology_snapshot(group)
        origin = group.FemMesh.Nodes[1]

        def move():
            child.Placement = FreeCAD.Placement(FreeCAD.Vector(5, 0, 0), FreeCAD.Rotation())
            self.document.recompute()

        full, placement = self._merge_counts(move)
        self.assertEqual(placement, 1)
        self.assertEqual(full, 0)

        self.assertEqual(group.getMergeRevision(), before_merge + 1)
        self.assertEqual(group.getTopologyRevision(), before_topology)
        self.assertEqual(self._topology_snapshot(group), before)
        self.assertAlmostEqual(group.FemMesh.Nodes[1].x, origin.x + 5)
        self.assertAlmostEqual(group.FemMesh.Nodes[1].y, origin.y)

    def test_import_placement_still_transforms_the_placed_merge(self):
        """An import places the group's merge, which already places its children."""
        from femtools import importtools

        source = ObjectsFem.makeAnalysis(self.document, "Source")
        group = ObjectsFem.makeMeshShapeGroup(self.document, "Mesh", analysis=source)
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        child.FemMesh = _make_tet_mesh()[0]
        child.Placement = FreeCAD.Placement(FreeCAD.Vector(5, 0, 0), FreeCAD.Rotation())
        group.Group = [child]

        assembly = ObjectsFem.makeAnalysis(self.document, "Assembly")
        placed = ObjectsFem.makeAnalysisImport(self.document, "Placed")
        placed.Analysis = source
        placed.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 7, 0), FreeCAD.Rotation())
        importtools.wire_import(assembly, placed)
        self.document.recompute()

        native = group.FemMesh.Nodes[1]
        assembled = Fem.buildSolveAssembly(assembly)[0]
        self.assertTrue(
            any(
                abs(node.x - native.x) < 1e-9 and abs(node.y - (native.y + 7)) < 1e-9
                for node in assembled.Nodes.values()
            ),
            "the import places the already placed native merge",
        )

    # -- restore and undo ---------------------------------------------------

    def test_reopened_document_rebuilds_the_transient_merge(self):
        """
        The merged mesh is not in the file; the children are.

        Restoring has to put it back, once, without leaving the freshly opened
        document looking edited.
        """
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = _box()
        group = ObjectsFem.makeMeshShapeGroup(self.document, "Mesh", geometry=geom)
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        child.FemMesh = _make_tet_mesh()[0]
        group.Group = [child]
        self.document.recompute()

        expected = self._topology_snapshot(group)
        volumes = group.FemMesh.VolumeCount
        names = (geom.Name, group.Name, child.Name)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "merge.FCStd")
            self.document.saveAs(path)
            FreeCAD.closeDocument(self.document.Name)

            Fem.perfReset()
            Fem.perfEnable(True)
            try:
                # tearDown closes self.document, so hand it the reloaded one
                self.document = FreeCAD.openDocument(path)
            finally:
                Fem.perfEnable(False)
            report = {name: count for name, count, _t, _s in Fem.perfReport()}

            restored_geom = self.document.getObject(names[0])
            restored_group = self.document.getObject(names[1])
            restored_child = self.document.getObject(names[2])

            # Exactly one merge, and no leftover work for a recompute to do.
            self.assertEqual(report.get("merge", 0), 1)
            self.assertEqual(report.get("merge.placement", 0), 0)
            self.assertEqual([o.Name for o in self.document.Objects if "Touched" in o.State], [])

            # The geometry Shape is in the file, its topology is derived again.
            self.assertFalse(restored_geom.Shape.isNull())
            self.assertEqual(restored_geom.getComponentCount(), 1)

            # The child mesh is in the file, the merge is not.
            self.assertEqual(restored_child.FemMesh.VolumeCount, 1)
            self.assertEqual(restored_group.FemMesh.VolumeCount, volumes)
            self.assertEqual(self._topology_snapshot(restored_group), expected)

    def test_undo_and_redo_of_group_membership_rebuild_coherent_output(self):
        """
        Undo and redo change the children behind the group's back.

        Neither carries a merged mesh - it is transient and was never in the
        transaction - so the next execute is what has to put a coherent one
        back, both on the way out and on the way in again.
        """
        self.document.UndoMode = 1
        group, child_a = self._group_with_child("AMesh")
        child_z = self.document.addObject("Fem::FemMeshObject", "ZMesh")
        child_z.FemMesh = _make_tri_mesh("Face12")[0]
        self._assert_output_matches_children(group)

        self.document.openTransaction("add mesh")
        group.Group = [child_a, child_z]
        self.document.commitTransaction()
        self.document.recompute()
        self.assertEqual(len(group.Group), 2)
        self._assert_output_matches_children(group)

        self.document.undo()
        self.document.recompute()
        self.assertEqual(len(group.Group), 1)
        self._assert_output_matches_children(group)

        self.document.redo()
        self.document.recompute()
        self.assertEqual(len(group.Group), 2)
        self._assert_output_matches_children(group)

    # -- geometry -----------------------------------------------------------

    def test_geometry_topology_follows_the_shape_through_recompute(self):
        """
        A geometry chain classifies its result once, at the recompute.

        An unrelated property on a step leaves the shape as it was, so the group
        hands the same shape on again and nothing behind it is reclassified.
        """
        group = ObjectsFem.makeGeometryGroup(self.document, "Geometry")
        step = ObjectsFem.makeGeometryImport(self.document, "Import")
        box = self.document.addObject("Part::Box", "Box")
        step.Import = [box]
        group.Group = [step]
        self.document.recompute()

        revision = group.getTopologyRevision()
        self.assertEqual(group.getComponentCount(), 1)

        # An irrelevant property on a step: the shape it produces is the same
        # one, so the group must not republish and nothing is reclassified.
        step.Label = "Renamed import"
        self.document.recompute()
        self.assertEqual(group.getTopologyRevision(), revision)

        # A changed input is a changed shape, and the topology follows it - but
        # only once the document has recomputed to it.
        box.Length = 20
        self.document.recompute()
        self.assertNotEqual(group.getTopologyRevision(), revision)
        self.assertEqual(group.getComponentCount(), 1)
        self.assertAlmostEqual(group.Shape.BoundBox.XLength, 20)

    def test_geometry_shape_assignment_is_finalised_by_recompute(self):
        """A Shape written by hand reaches the topology at the next recompute."""
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = _box()
        self.document.recompute()
        self.assertEqual(geom.getComponentCount(), 1)
        revision = geom.getTopologyRevision()

        geom.Shape = Part.makeCompound([Part.makeBox(10, 10, 10), _face_xy()])
        self.document.recompute()
        self.assertEqual(geom.getTopologyRevision(), revision + 1)
        self.assertEqual(geom.getComponentCount(), 2)


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

    def test_solid_meshed_as_2d_keeps_faces(self):
        """A solid whose mesh only achieved surface elements still exports them."""
        mesh = Fem.FemMesh()
        for node_id, point in enumerate([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)], start=1):
            mesh.addNode(point[0], point[1], point[2], node_id)
        # No volume: surface mesh of a solid (under-achieved).
        faces = [
            mesh.addFace([1, 2, 3]),
            mesh.addFace([1, 2, 4]),
            mesh.addFace([1, 3, 4]),
            mesh.addFace([2, 3, 4]),
        ]
        for i, face in enumerate(faces, start=1):
            fid = mesh.addGroup(f"Face{i}", "Face")
            mesh.addGroupElements(fid, [face])

        # Topology fallback (no geometry passed to writeABAQUS): all free faces kept.
        exported = sorted(sum(_exported_element_ids(mesh, 1).values(), []))
        self.assertEqual(exported, sorted(faces))
        self.assertEqual(sorted(mesh.HighestElements), sorted(faces))

    def test_beam_on_shell_boundary_exports_both(self):
        """A free edge (beam) that is not the skin of a face is kept with the shell."""
        mesh = Fem.FemMesh()
        for node_id, point in enumerate(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (10, 0, 0), (11, 0, 0)], start=1
        ):
            mesh.addNode(point[0], point[1], point[2], node_id)
        shell = mesh.addFace([1, 2, 3])
        beam = mesh.addEdge([4, 5])
        # Skin edge of the triangle — must be dropped.
        skin_edge = mesh.addEdge([1, 2])
        gid = mesh.addGroup("Face1", "Face")
        mesh.addGroupElements(gid, [shell])
        gid = mesh.addGroup("Edge1", "Edge")
        mesh.addGroupElements(gid, [beam])
        gid = mesh.addGroup("Edge2", "Edge")
        mesh.addGroupElements(gid, [skin_edge])

        exported = set(sum(_exported_element_ids(mesh, 1).values(), []))
        self.assertEqual(exported, {shell, beam})
        self.assertNotIn(skin_edge, exported)

    def test_write_abaqus_element_ids_override(self):
        """elementIds replaces the highest-element filter when elemParam is 1."""
        mesh, ids = self._mixed_mesh()
        exported = _exported_element_ids(mesh, 1, element_ids=[ids["shell"]])
        self.assertEqual(exported, {"S3": [ids["shell"]]})
        # The filter would have kept the volume, the explicit list must not.
        self.assertIn(ids["volume"], mesh.HighestElements)

    def test_write_abaqus_mixed_dimensions(self):
        """Model volume, face and edge elements are written side by side."""
        mesh = Fem.FemMesh()
        points = [
            (0, 0, 0),
            (1, 0, 0),
            (0, 1, 0),
            (0, 0, 1),
            (10, 0, 0),
            (11, 0, 0),
            (10, 1, 0),
            (20, 0, 0),
            (21, 0, 0),
        ]
        for node_id, point in enumerate(points, start=1):
            mesh.addNode(point[0], point[1], point[2], node_id)
        volume = mesh.addVolume([1, 2, 3, 4])
        shell = mesh.addFace([5, 6, 7])
        beam = mesh.addEdge([8, 9])

        # All three are free standing, so the filter keeps them without any help.
        self.assertEqual(sorted(mesh.HighestElements), sorted([volume, shell, beam]))
        exported = _exported_element_ids(mesh, 1)
        self.assertEqual(exported, {"C3D4": [volume], "S3": [shell], "B31": [beam]})

    def test_mesh_group_fills_cell_dimension(self):
        """FemMeshShapeGroup classifies merged cells into CellDimension."""
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        mesh, ids = self._mixed_mesh()
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()
        # Accessing FemMesh triggers lazy merge + classification.
        _ = group.FemMesh
        dims = list(group.CellDimension)
        self.assertGreaterEqual(len(dims), max(ids.values()))
        self.assertEqual(dims[ids["volume"] - 1], 3)
        self.assertEqual(dims[ids["shell"] - 1], 2)
        self.assertEqual(dims[ids["skin"] - 1], -1)

    def test_mesh_group_fills_entity_dimension(self):
        """Entities report the dimension of the structure they belong to.

        Face1 only holds the skin of the tet and still answers 3, so a reference
        to it is resolved as the boundary of volume elements. Face12 holds the
        free shell and answers 2, which makes it an element set of its own.
        """
        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        mesh, _ = self._mixed_mesh()
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()
        _ = group.FemMesh
        entities = {name: int(value) for name, value in group.EntityDimension.items()}
        self.assertEqual(entities, {"Solid1": 3, "Face1": 3, "Face12": 2})

    def test_dimension_override_turns_a_solid_into_a_shell(self):
        """A solid declared 2D exports its skin and not its volume elements.

        The mesher reached 3D but the geometry says the component is to be
        analysed as a shell, and the lower of the two wins.
        """
        geom = self.document.addObject("Fem::FemGeometry", "Geometry")
        geom.Shape = _box()
        self.document.recompute()
        geom.DimensionOverride = {"Solid1": "2"}

        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        group.Shape = geom
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        mesh, volume, faces = _make_tet_mesh()
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()
        _ = group.FemMesh

        dims = list(group.CellDimension)
        self.assertEqual(dims[volume - 1], -1)
        for face in faces:
            self.assertEqual(dims[face - 1], 2)
        entities = {name: int(value) for name, value in group.EntityDimension.items()}
        self.assertEqual(entities["Solid1"], 2)

    def test_an_embedded_shell_is_one_of_its_own_owners(self):
        """
        The solid it was fused into is not all a shell inside one belongs to.

        Ownership is recorded from the toplevel down, so a solid is heard
        saying it owns the face; nothing says the face is a toplevel too, and
        without that the shell has no dimension of its own to be judged by.
        """
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                self._an_embedded_shell_is_one_of_its_own_owners(wrapped)

    def _an_embedded_shell_is_one_of_its_own_owners(self, wrapped):
        geom, face, edge = _embedded_shell(self.document, wrapped)

        self.assertIn("Solid1", geom.getEntityOwners(face))
        self.assertIn(face, geom.getEntityOwners(face), "an embedded toplevel owns itself")
        self.assertEqual(
            geom.getEntityDimensionMask(face),
            (1 << 2) | (1 << 3),
            "the face is 2D of its own and 3D as part of the solid",
        )
        self.assertEqual(geom.getEntityDimensionMask(edge), (1 << 2) | (1 << 3))

    def test_an_embedded_shell_is_meshed_but_its_boundary_is_not(self):
        """
        The elements on the shell are solved, the ones bounding it are not.

        A shell that cannot speak for itself is only ever reached through the
        edges around it, so the highest dimension it is seen to hold is one:
        its own triangles are then dropped as the solid's skin, and the edges
        that found it are promoted to beams the analysis would solve.
        """
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                self._an_embedded_shell_is_meshed_but_its_boundary_is_not(wrapped)

    def _an_embedded_shell_is_meshed_but_its_boundary_is_not(self, wrapped):
        geom, face, edge = _embedded_shell(self.document, wrapped)

        mesh = Fem.FemMesh()
        mesh.addNode(0, 0, 0, 1)
        mesh.addNode(1, 0, 0, 2)
        mesh.addNode(0, 1, 0, 3)
        mesh.addNode(0, 0, 1, 4)
        volume = mesh.addVolume([1, 2, 3, 4])
        # The shell is conformal with the solid around it, so its triangles are
        # faces of the elements it runs through and its edges are their edges.
        triangle = mesh.addFace([1, 2, 3])
        segment = mesh.addEdge([1, 2])
        for name, kind, ids in (
            ("Solid1", "Volume", [volume]),
            (face, "Face", [triangle]),
            (edge, "Edge", [segment]),
        ):
            mesh.addGroupElements(mesh.addGroup(name, kind), ids)

        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        group.Shape = geom
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()
        _ = group.FemMesh

        dims = list(group.CellDimension)
        self.assertEqual(dims[volume - 1], 3)
        self.assertEqual(dims[triangle - 1], 2, "the shell inside the solid is solved on")
        self.assertEqual(dims[segment - 1], -1, "what bounds the shell is not a beam")

    def test_an_embedded_bar_is_meshed_but_its_host_edges_are_not(self):
        """
        The 1D twin of the embedded shell, for both kinds of host.

        A bar fused into a solid or a face is solved on, while the wires of the
        host it runs through are where its elements end and are not. Nothing in
        the mesh tells the two apart -- both are segments on the host's nodes --
        so it is the bar being a model element of the geometry that has to carry
        it, exactly as for the shell one dimension up.
        """
        for host in ("Solid", "Face"):
            with self.subTest(host=host):
                self._an_embedded_bar_is_meshed(host)

    def _an_embedded_bar_is_meshed(self, host):
        geom, host_name, bar, plain = _embedded_bar(self.document, host)

        mesh = Fem.FemMesh()
        for node, (x, y, z) in enumerate(
            [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
             (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10)],
            start=1,
        ):  # fmt: skip
            mesh.addNode(x, y, z, node)
        if host == "Solid":
            host_elements = [mesh.addVolume([1, 2, 3, 4, 5, 6, 7, 8])]
            host_kind, host_dimension = "Volume", 3
        else:
            host_elements = [mesh.addFace([1, 2, 3]), mesh.addFace([1, 3, 4])]
            host_kind, host_dimension = "Face", 2
        beam = mesh.addEdge([1, 3])
        host_edge = mesh.addEdge([1, 2])
        for name, kind, ids in (
            (host_name, host_kind, host_elements),
            (bar, "Edge", [beam]),
            (plain, "Edge", [host_edge]),
        ):
            mesh.addGroupElements(mesh.addGroup(name, kind), ids)

        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        group.Shape = geom
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()
        _ = group.FemMesh

        dims = list(group.CellDimension)
        for element in host_elements:
            self.assertEqual(dims[element - 1], host_dimension)
        self.assertEqual(dims[beam - 1], 1, "the bar inside the host is solved on")
        self.assertEqual(dims[host_edge - 1], -1, "a wire of the host is no beam")

    def test_model_element_ids_read_the_classification(self):
        """meshtools reads the dimensions off the group instead of guessing."""
        from femmesh import meshtools

        group = self.document.addObject("Fem::FemMeshShapeGroup", "MeshGroup")
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        mesh, ids = self._mixed_mesh()
        child.FemMesh = mesh
        group.Group = [child]
        self.document.recompute()
        femmesh = group.FemMesh

        self.assertEqual(meshtools.get_model_dimensions(group, femmesh), {2, 3})
        self.assertEqual(meshtools.get_model_element_ids(group, femmesh, 3), [ids["volume"]])
        self.assertEqual(meshtools.get_model_element_ids(group, femmesh, 2), [ids["shell"]])
        self.assertEqual(
            meshtools.get_model_element_ids(group, femmesh),
            sorted([ids["volume"], ids["shell"]]),
        )
        # The skin of the tetrahedron is no model element of any dimension.
        self.assertNotIn(ids["skin"], meshtools.get_model_element_ids(group, femmesh))

    def test_model_element_ids_without_a_classification(self):
        """A plain mesh has no CellDimension and is classified on the spot."""
        from femmesh import meshtools

        mesh, ids = self._mixed_mesh()
        obj = self.document.addObject("Fem::FemMeshObject", "MeshA")
        obj.FemMesh = mesh

        self.assertEqual(meshtools.get_model_dimensions(obj, mesh), {2, 3})
        self.assertEqual(meshtools.get_model_element_ids(obj, mesh, 2), [ids["shell"]])

    def test_table_of_dimension_sieves_a_mixed_table(self):
        """A mixed table is split by element type, which node counts cannot do."""
        from femmesh import meshtools

        mesh, ids = self._mixed_mesh()
        table = {eid: mesh.getElementNodes(eid) for eid in (ids["volume"], ids["shell"])}
        # Both entries hold four and three nodes respectively, and only the mesh
        # can say which of them is a volume.
        self.assertEqual(list(meshtools.table_of_dimension(mesh, table, 3)), [ids["volume"]])
        self.assertEqual(list(meshtools.table_of_dimension(mesh, table, 2)), [ids["shell"]])
        self.assertEqual(meshtools.table_of_dimension(mesh, table, 1), {})


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

    def test_a_clip_plane_can_be_restricted_to_one_instance(self):
        """
        A clip plane carries the path of what it cuts, empty for the whole
        analysis, and keeps it across a save and reload.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for AnalysisViewState persistence props")

        import FemGui

        analysis = ObjectsFem.makeAnalysis(self.document)
        self.document.recompute()

        state = FemGui.getAnalysisViewState(analysis)
        state.setClipPlane("all", FreeCAD.Vector(), FreeCAD.Vector(0, 0, 1))
        state.setClipPlane("one", FreeCAD.Vector(1, 0, 0), FreeCAD.Vector(1, 0, 0), "Import1")

        planes = state.getClipPlanes()
        self.assertEqual(planes["all"][2], "")
        self.assertEqual(planes["one"][2], "Import1")

        name = analysis.Name
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "clip_scope.FCStd")
            self.document.saveAs(path)
            FreeCAD.closeDocument(self.document.Name)
            self.document = FreeCAD.openDocument(path)

        restored = FemGui.getAnalysisViewState(self.document.getObject(name)).getClipPlanes()
        self.assertEqual(restored["all"][2], "")
        self.assertEqual(restored["one"][2], "Import1")

    def test_hidden_elements_of_an_instance_are_named_by_path(self):
        """
        The same element of two instances is hidden independently, because the
        name it is hidden under is the path to it.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for AnalysisViewState persistence props")

        import FemGui

        analysis = ObjectsFem.makeAnalysis(self.document)
        self.document.recompute()

        state = FemGui.getAnalysisViewState(analysis)
        state.setElementHidden("Import1.Face3", True)
        self.assertTrue(state.isElementHidden("Import1.Face3"))
        self.assertFalse(state.isElementHidden("Import2.Face3"))
        self.assertFalse(state.isElementHidden("Face3"))
        self.assertEqual(set(analysis.ViewObject.ViewHiddenElements), {"Import1.Face3"})

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


class TestAnalysisImport(unittest.TestCase):
    fcc_print("import TestAnalysisImport")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def _leg_analysis(self):
        leg, geom, mesh_group, _, _ = self._leg_analysis_with_members(with_members=False)
        return leg, geom, mesh_group

    def _leg_analysis_with_members(self, with_members=False):
        leg = ObjectsFem.makeAnalysis(self.document, "LegAnalysis")
        geom = ObjectsFem.makeGeometryGroup(self.document, "LegGeometry")
        leg.addObject(geom)
        source = self.document.addObject("Part::Feature", "LegPart")
        source.Shape = _box()
        imp = ObjectsFem.makeGeometryImport(self.document)
        imp.Import = [source]
        geom.Group = [imp]

        mesh_group = ObjectsFem.makeMeshShapeGroup(self.document, geometry=geom, analysis=leg)
        mesh_obj = self.document.addObject("Fem::FemMeshObject", "LegMesh")
        mesh_obj.FemMesh = _make_tet_mesh()[0]
        mesh_group.addObject(mesh_obj)
        mat = fixed = None
        if with_members:
            mat = ObjectsFem.makeMaterialSolid(self.document, "LegMaterial")
            card = mat.Material
            card["Name"] = "CalculiX-Steel"
            card["YoungsModulus"] = "210000 MPa"
            card["PoissonRatio"] = "0.30"
            card["Density"] = "7900 kg/m^3"
            mat.Material = card
            mat.References = [(geom, ["Solid1"])]
            leg.addObject(mat)
            fixed = ObjectsFem.makeConstraintFixed(self.document, "LegFixed")
            fixed.References = [(geom, ["Face1"])]
            leg.addObject(fixed)
        self.document.recompute()
        return leg, geom, mesh_group, mat, fixed

    def _add_import(self, table, leg, name="Leg1", vector=None):
        from femtools import importtools

        imp = ObjectsFem.makeAnalysisImport(self.document, name)
        imp.Analysis = leg
        if vector is not None:
            imp.Placement = FreeCAD.Placement(vector, FreeCAD.Rotation())
        return imp, importtools.wire_import(table, imp)

    def _table_analysis(self, mesh_group=False, native=False):
        """
        The analysis that imports others.

        With *native* it brings a geometry and a mesh of its own, so the solve
        assembly has to join native and imported pieces rather than only place
        the imported ones.
        """
        table = ObjectsFem.makeAnalysis(self.document, "Table")
        geometry = ObjectsFem.makeGeometryGroup(self.document, "TableGeometry")
        table.addObject(geometry)
        if native:
            source = self.document.addObject("Part::Feature", "TablePart")
            source.Shape = _box()
            imp = ObjectsFem.makeGeometryImport(self.document)
            imp.Import = [source]
            geometry.Group = [imp]
        group = None
        if mesh_group:
            group = ObjectsFem.makeMeshShapeGroup(self.document, geometry=geometry, analysis=table)
            if native:
                mesh_obj = self.document.addObject("Fem::FemMeshObject", "TableMesh")
                mesh_obj.FemMesh = _make_tet_mesh()[0]
                group.addObject(mesh_obj)
        self.document.recompute()
        return table, geometry, group

    @staticmethod
    def _group_names(mesh):
        return {mesh.getGroupName(gid) for gid in mesh.Groups}

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestAnalysisImport tests {2}\n{0}".format(
                100 * "*", 10 * "*", 49 * "*"
            )
        )

    def test_import_group_created_once(self):
        from femtools import importtools

        leg, _, _ = self._leg_analysis()
        table, _, _ = self._table_analysis()
        self._add_import(table, leg, "Leg1")
        self._add_import(table, leg, "Leg2")
        groups = [m for m in table.Group if importtools.is_import_group(m)]
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0].Group), 2)

    def test_a_second_analysis_keeps_one_import_group(self):
        """
        Internal names are unique across a document, so the container of the
        second analysis to import anything cannot be called Imports. Looking
        for that name alone never finds it again and every further import
        leaves another container behind.
        """
        from femtools import importtools

        leg, _, _ = self._leg_analysis()
        first, _, _ = self._table_analysis()
        self._add_import(first, leg, "Leg1")

        second, _, _ = self._table_analysis()
        self._add_import(second, leg, "Leg2")
        self._add_import(second, leg, "Leg3")

        groups = [m for m in second.Group if importtools.is_import_group(m)]
        self.assertEqual(len(groups), 1)
        self.assertNotEqual(groups[0].Name, "Imports")
        self.assertEqual(len(groups[0].Group), 2)

    def test_spare_import_groups_are_folded_together(self):
        """An analysis left with several containers settles back on one."""
        from femtools import importtools

        leg, _, _ = self._leg_analysis()
        table, _, _ = self._table_analysis()
        populated = ObjectsFem.makeImportGroup(self.document)
        table.addObject(populated)
        stray = ObjectsFem.makeAnalysisImport(self.document, "Stray")
        stray.Analysis = leg
        populated.addObject(stray)
        empty = ObjectsFem.makeImportGroup(self.document).Name
        table.addObject(self.document.getObject(empty))

        imp, group = self._add_import(table, leg, "Leg1")

        self.assertEqual([m for m in table.Group if importtools.is_import_group(m)], [group])
        self.assertEqual(set(group.Group), {imp, stray})
        self.assertIsNone(self.document.getObject(empty))

    def test_import_into_a_fresh_analysis_wires_itself(self):
        """A fresh analysis only needs an Imports container; geometry is not merged."""
        from femtools import importtools, membertools

        leg, _, _ = self._leg_analysis()
        fresh = ObjectsFem.makeAnalysis(self.document, "Fresh")
        self.assertEqual(membertools.get_member(fresh, "Fem::GeometryGroup"), [])

        imp, import_group = self._add_import(fresh, leg)
        self.document.recompute()

        self.assertEqual(importtools.find_import_group(fresh), import_group)
        self.assertEqual(list(import_group.Group), [imp])
        self.assertNotIn("Invalid", imp.State)
        solid = imp.getSubObject("Solid1")
        self.assertIsNotNone(solid)
        self.assertGreater(solid.Volume, 0.0)

        self._add_import(fresh, leg, "Leg2")
        self.document.recompute()
        self.assertEqual(len(import_group.Group), 2)
        self.assertEqual(len(membertools.get_member(fresh, "Fem::GeometryGroup")), 0)

    def test_import_icon_resource_loads(self):
        """The tree and toolbar both address the import icon by this name."""
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for icon resources")

        from PySide import QtGui

        pixmap = QtGui.QPixmap(":/icons/FEM_AnalysisImport.svg")
        self.assertFalse(pixmap.isNull())

    def test_import_view_provider_can_be_shown(self):
        """The import renders itself and exposes a display mode."""
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        leg, _, _ = self._leg_analysis()
        table, _, _ = self._table_analysis()
        imp, _ = self._add_import(table, leg)
        self.document.recompute()

        view = imp.ViewObject
        self.assertGreater(len(view.listDisplayModes()), 0)
        view.Visibility = True
        self.assertTrue(view.isVisible())

    def test_colour_categories_grow_with_a_second_import(self):
        """Every imported solid needs its own colour category.

        The categories are cached on the analysis view state and used to be
        dropped only on a stage or colour mode switch, so the solids of a later
        import found no category, fell back to the first one and came out in a
        single colour. Reading them before the second import is the point of the
        test: that is what fills the cache, and it is what the view panel does,
        since it observes the document before the view providers do.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for the analysis view state")

        import FemGui

        leg, _, _ = self._leg_analysis()
        table, table_geom, _ = self._table_analysis()
        self._add_import(table, leg, "Leg1")
        self.document.recompute()

        state = FemGui.getAnalysisViewState(table)
        first = {c["key"] for c in state.getCategories()}
        self.assertTrue(first)

        self._add_import(table, leg, "Leg2", FreeCAD.Vector(200, 0, 0))
        self.document.recompute()

        second = {c["key"] for c in state.getCategories()}
        self.assertGreater(len(second), len(first))

    def _two_solid_leg(self, with_material=False, per_solid_mesh=False):
        """A source analysis with two solids, so a colour per solid is visible."""
        leg = ObjectsFem.makeAnalysis(self.document, "LegAnalysis")
        geom = ObjectsFem.makeGeometryGroup(self.document, "LegGeometry")
        leg.addObject(geom)
        first = self.document.addObject("Part::Feature", "PartA")
        first.Shape = _box()
        second = self.document.addObject("Part::Feature", "PartB")
        second.Shape = _box()
        second.Placement = FreeCAD.Placement(FreeCAD.Vector(30, 0, 0), FreeCAD.Rotation())
        step = ObjectsFem.makeGeometryImport(self.document)
        step.Import = [first, second]
        geom.Group = [step]
        mesh_group = ObjectsFem.makeMeshShapeGroup(self.document, geometry=geom, analysis=leg)
        mesh_obj = self.document.addObject("Fem::FemMeshObject", "LegMesh")
        mesh_obj.FemMesh = _make_two_solid_tet_mesh() if per_solid_mesh else _make_tet_mesh()[0]
        mesh_group.addObject(mesh_obj)
        if with_material:
            mat = ObjectsFem.makeMaterialSolid(self.document, "LegMaterial")
            card = mat.Material
            card["Name"] = "CalculiX-Steel"
            card["YoungsModulus"] = "210000 MPa"
            card["PoissonRatio"] = "0.30"
            card["Density"] = "7900 kg/m^3"
            mat.Material = card
            mat.References = [(geom, ["Solid1", "Solid2"])]
            leg.addObject(mat)
        self.document.recompute()
        return leg, geom

    @staticmethod
    def _geometry_face_colours(view_object):
        """
        Colours the import paints its geometry faces in.

        Only the branch that is traversed for rendering is searched, so this is
        the geometry of the active stage and not the mesh. A symbol material
        carries a single colour, a face material one per BREP face.
        """
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoMaterial.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(view_object.RootNode)
        paths = search.getPaths()
        colours = []
        for i in range(paths.getLength()):
            material = paths[i].getTail()
            count = material.diffuseColor.getNum()
            if count < 2:
                continue
            colours.extend(
                tuple(round(v, 3) for v in material.diffuseColor[j].getValue())
                for j in range(count)
            )
        return colours

    def test_imported_geometry_is_coloured_per_solid(self):
        """
        Each solid of an instance takes the colour of its own category. The
        faces of a solid have no category of their own, so they have to fall
        back to the solid they belong to rather than to the first category —
        which would paint the whole instance in one colour.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FemGui

        leg, _ = self._two_solid_leg()
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        self.document.recompute()

        state = FemGui.getAnalysisViewState(table)
        state.setColorMode("Component")
        by_key = {
            c["key"]: tuple(round(v, 3) for v in c["color"][:3]) for c in state.getCategories()
        }
        self.assertIn("Leg1.Component1", by_key)
        self.assertIn("Leg1.Component2", by_key)

        colours = self._geometry_face_colours(imp.ViewObject)
        self.assertTrue(colours, "the instance draws its source geometry")
        self.assertEqual(
            set(colours),
            {by_key["Leg1.Component1"], by_key["Leg1.Component2"]},
            "each solid of the instance wears the colour of the component it is",
        )

    def test_imported_geometry_follows_a_colour_mode_switch(self):
        """
        An import is put into its analysis after its view provider is attached,
        so the helpers that draw it start out without a view state. Unless they
        pick one up they keep drawing what they guessed at build time and no
        panel setting ever reaches them.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FemGui

        leg, _ = self._two_solid_leg(with_material=True)
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        self.document.recompute()

        state = FemGui.getAnalysisViewState(table)
        state.setColorMode("Component")
        self.assertEqual(
            len(set(self._geometry_face_colours(imp.ViewObject))),
            2,
            "one colour per component while the colour follows the geometry",
        )

        # Both solids share a material, so the instance turns into one colour
        state.setColorMode("Material")
        material_colours = set(self._geometry_face_colours(imp.ViewObject))
        self.assertEqual(len(material_colours), 1)
        by_key = {
            c["key"]: tuple(round(v, 3) for v in c["color"][:3]) for c in state.getCategories()
        }
        self.assertIn("CalculiX-Steel", by_key)
        self.assertEqual(material_colours, {by_key["CalculiX-Steel"]})

    @staticmethod
    def _drawn_geometry(view_object):
        """
        What an instance hands to Coin for its geometry.

        Returns the face indices, the parts they are grouped into and the points
        those indices address, all of the branch that is traversed for
        rendering.
        """
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoIndexedFaceSet.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(view_object.RootNode)
        paths = search.getPaths()
        for i in range(paths.getLength()):
            path = paths[i]
            node = path.getTail()
            if node.getTypeId().getName() != "SoBrepFaceSet":
                continue
            parent = path.getNodeFromTail(1)
            points = []
            for child in range(parent.getNumChildren()):
                candidate = parent.getChild(child)
                if candidate.isOfType(coin.SoCoordinate3.getClassTypeId()):
                    points = [
                        candidate.point[j].getValue() for j in range(candidate.point.getNum())
                    ]
            indices = [node.coordIndex[j] for j in range(node.coordIndex.getNum())]
            parts = [node.partIndex[j] for j in range(node.partIndex.getNum())]
            return indices, parts, points
        return None

    @staticmethod
    def _drawn_height(drawn):
        """
        Extent along z of the surfaces that are drawn.

        Only the points the faces address: the edges share the same coordinates
        and are not cut by a clip plane, so they say nothing about the surfaces.
        """
        indices, _, points = drawn
        zs = [points[i][2] for i in set(indices) if i >= 0]
        return max(zs) - min(zs)

    def _assert_geometry_is_consistent(self, drawn, what):
        """Every index names a point that exists and belongs to exactly one part."""
        indices, parts, points = drawn
        self.assertTrue(indices, f"{what}: something has to be drawn")
        self.assertLess(
            max(indices),
            len(points),
            f"{what}: an index past the last point draws a triangle between unrelated points",
        )
        self.assertEqual(
            sum(parts),
            indices.count(-1),
            f"{what}: the parts have to add up to the triangles that were written",
        )

    def test_hiding_an_imported_solid_leaves_no_stale_triangles(self):
        """
        Coin fields keep what was written last time, so an update that draws
        less than the one before it has to truncate them. Without that the tail
        of the previous, longer geometry stays behind and is drawn as triangles
        between whatever points are now at those indices.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FemGui

        leg, _ = self._two_solid_leg()
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        self.document.recompute()

        state = FemGui.getAnalysisViewState(table)
        whole = self._drawn_geometry(imp.ViewObject)
        self._assert_geometry_is_consistent(whole, "both solids")

        state.setElementHidden("Leg1.Solid1", True)
        rest = self._drawn_geometry(imp.ViewObject)
        self._assert_geometry_is_consistent(rest, "one solid hidden")
        self.assertLess(len(rest[0]), len(whole[0]), "the hidden solid must be gone")

        state.setElementHidden("Leg1.Solid1", False)
        again = self._drawn_geometry(imp.ViewObject)
        self._assert_geometry_is_consistent(again, "both solids again")
        self.assertEqual(len(again[0]), len(whole[0]))

    def test_clipping_an_import_cuts_its_surfaces(self):
        """
        A clip plane cuts the instance and caps the solids it cuts. The cap is
        appended to the clipped geometry, which only keeps the cell metadata the
        two share — so a cap without it takes the shape ids down with it and
        leaves nothing that can be drawn.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FemGui

        leg, _ = self._two_solid_leg()
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        self.document.recompute()

        state = FemGui.getAnalysisViewState(table)
        whole = self._drawn_geometry(imp.ViewObject)
        self._assert_geometry_is_consistent(whole, "unclipped")

        # Halfway up the boxes, in the coordinates of the importing analysis
        state.setClipPlane("clip", FreeCAD.Vector(80, 0, 5), FreeCAD.Vector(0, 0, 1))
        clipped = self._drawn_geometry(imp.ViewObject)
        self._assert_geometry_is_consistent(clipped, "clipped")
        self.assertAlmostEqual(
            self._drawn_height(clipped),
            self._drawn_height(whole) / 2.0,
            delta=0.5,
            msg="half of the instance is cut away",
        )

        state.removeClipPlane("clip")
        restored = self._drawn_geometry(imp.ViewObject)
        self._assert_geometry_is_consistent(restored, "clip removed")
        self.assertEqual(len(restored[0]), len(whole[0]))
        self.assertAlmostEqual(self._drawn_height(restored), self._drawn_height(whole), places=4)

    @staticmethod
    def _picked_element(view_object, origin, direction):
        """Name the instance gives the surface a ray from *origin* first meets."""
        from pivy import coin

        action = coin.SoRayPickAction(coin.SbViewportRegion(64, 64))
        action.setRay(coin.SbVec3f(*origin), coin.SbVec3f(*direction))
        action.setPickAll(False)
        action.apply(view_object.RootNode)
        point = action.getPickedPoint()
        if point is None:
            return None
        return view_object.getElementPicked(point)

    @staticmethod
    def _part_indices(view_object, field):
        """Face parts of an instance listed in *field*, e.g. selectionPartIndex."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoIndexedFaceSet.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(True)
        search.apply(view_object.RootNode)
        paths = search.getPaths()
        indices = []
        for i in range(paths.getLength()):
            node = paths[i].getTail()
            if node.getTypeId().getName() != "SoBrepFaceSet":
                continue
            values = node.getField(field)
            indices += [values[j] for j in range(values.getNum())]
        return indices

    @staticmethod
    def _face_sets_below(node):
        """The geometry face sets an action applied to *node* would reach."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoIndexedFaceSet.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(True)
        search.apply(node)
        paths = search.getPaths()
        return [
            paths[i].getTail()
            for i in range(paths.getLength())
            if paths[i].getTail().getTypeId().getName() == "SoBrepFaceSet"
        ]

    @staticmethod
    def _drawn_ghost(view_object):
        """
        Faces of the ghost overlay an instance draws over its geometry.

        Only the branch that is traversed for rendering, so in the geometry
        stage the ghost of the mesh is out of reach. Counted by the separators
        that close the faces, an index set that draws nothing still holds one
        index.
        """
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoIndexedFaceSet.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(view_object.RootNode)
        paths = search.getPaths()
        faces = 0
        for i in range(paths.getLength()):
            node = paths[i].getTail()
            if node.getTypeId().getName() != "IndexedFaceSet":
                continue
            faces += sum(1 for j in range(node.coordIndex.getNum()) if node.coordIndex[j] < 0)
        return faces

    def test_an_import_highlights_in_the_colour_the_user_picked(self):
        """
        Solids are highlighted through the overlay fields of the face set,
        whose colours default to a red of their own rather than to the ones
        every other preselection in the view uses.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        from pivy import coin

        leg, _ = self._two_solid_leg()
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        self.document.recompute()

        parameters = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View")
        expected = {}
        for field, key, fallback in (
            ("highlightColor", "HighlightColor", 0xFF9900FF),
            ("selectionColor", "SelectionColor", 0x1ACC1AFF),
        ):
            packed = parameters.GetUnsigned(key, fallback)
            expected[field] = tuple(
                round(((packed >> shift) & 0xFF) / 255.0, 3) for shift in (24, 16, 8)
            )

        search = coin.SoSearchAction()
        search.setType(coin.SoIndexedFaceSet.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(True)
        search.apply(imp.ViewObject.RootNode)
        paths = search.getPaths()
        seen = 0
        for i in range(paths.getLength()):
            node = paths[i].getTail()
            if node.getTypeId().getName() != "SoBrepFaceSet":
                continue
            seen += 1
            for field, colour in expected.items():
                value = node.getField(field).getValue().getValue()
                self.assertEqual(tuple(round(c, 3) for c in value), colour, field)
        self.assertTrue(seen, "the instance has to draw its faces through a BREP face set")

    def test_an_import_ghosts_what_it_leaves_out(self):
        """
        The ghost overlay stands for the geometry that is not drawn, so it only
        appears once something is missing — and above all when a clip plane
        takes the whole instance, which is when nothing else is left to say
        where it went.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FemGui

        leg, _ = self._two_solid_leg()
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        self.document.recompute()

        state = FemGui.getAnalysisViewState(table)
        self.assertEqual(self._drawn_ghost(imp.ViewObject), 0, "nothing is missing yet")

        state.setElementHidden("Leg1.Solid1", True)
        whole = self._drawn_ghost(imp.ViewObject)
        self.assertGreater(whole, 0, "the hidden solid is what the ghost is there for")

        # Well below the instance, so the clip leaves nothing of it
        state.setElementHidden("Leg1.Solid1", False)
        state.setClipPlane("clip", FreeCAD.Vector(0, 0, 1000), FreeCAD.Vector(0, 0, 1))
        self.assertEqual(
            self._drawn_ghost(imp.ViewObject),
            whole,
            "an instance clipped away entirely still has a ghost",
        )

        state.setOverlay(False)
        self.assertEqual(self._drawn_ghost(imp.ViewObject), 0, "the user turned it off")

        state.setOverlay(True)
        state.removeClipPlane("clip")
        self.assertEqual(self._drawn_ghost(imp.ViewObject), 0, "nothing is missing again")

    def test_a_cut_face_of_an_import_names_the_solid_it_cuts(self):
        """
        The cut face a clip plane leaves behind stands for the whole solid, and
        is tagged with its shape id rather than one of a face. Naming it from
        the kind of element the caller expected turns that id into a face that
        is somewhere else entirely.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FemGui

        leg, _ = self._two_solid_leg()
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        self.document.recompute()

        state = FemGui.getAnalysisViewState(table)
        above = ((85, 5, 100), (0, 0, -1))
        below = ((85, 5, -100), (0, 0, 1))

        for origin, direction in (above, below):
            picked = self._picked_element(imp.ViewObject, origin, direction)
            self.assertTrue(
                picked and picked.startswith("Face"),
                f"an uncut surface is a face of its own, got {picked}",
            )

        # Halfway up the boxes, in the coordinates of the importing analysis
        state.setClipPlane("clip", FreeCAD.Vector(80, 0, 5), FreeCAD.Vector(0, 0, 1))
        picks = {
            self._picked_element(imp.ViewObject, origin, direction)
            for origin, direction in (above, below)
        }
        self.assertIn("Solid1", picks, f"the cut face names the solid it cuts, got {picks}")

    def _nested_instances(self):
        """
        An instance whose source imports the same analysis twice.

        The two nested instances draw one shape out of one set of tables, so
        nothing but where they sit in the scene graph tells them apart.
        """
        leg, _ = self._two_solid_leg()
        middle, _, _ = self._table_analysis(mesh_group=True, native=True)
        first, _ = self._add_import(middle, leg, "Leg1", vector=FreeCAD.Vector(0, 100, 0))
        second, _ = self._add_import(middle, leg, "Leg2", vector=FreeCAD.Vector(0, 200, 0))
        self.document.recompute()

        outer, _, _ = self._table_analysis(mesh_group=True, native=True)
        outer_imp, _ = self._add_import(outer, middle, "Middle1", vector=FreeCAD.Vector(0, 0, 100))
        self.document.recompute()
        return outer_imp, first, second

    def test_a_pick_names_the_nested_instance_it_landed_on(self):
        """
        A Coin detail is nothing but indices into the arrays of the node that
        made it, and every instance of one source analysis has the same
        arrays. Named without the path the pick came down, an element belongs
        to whichever instance reads those indices first, and the status bar,
        the selection and the highlight all end up on another leg.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        outer_imp, first, second = self._nested_instances()

        for element in (f"{first.Name}.Solid1", f"{second.Name}.Solid1", "Solid1"):
            box = outer_imp.getSubObject(element).BoundBox
            picked = self._picked_element(
                outer_imp.ViewObject,
                (box.Center.x, box.Center.y, box.ZMax + 50),
                (0, 0, -1),
            )
            self.assertTrue(picked, f"the ray has to meet {element}")
            path = element.rpartition(".")[0]
            self.assertEqual(
                picked.rpartition(".")[0],
                path,
                f"picked on {element}, named {picked}",
            )

    def test_the_path_to_a_nested_element_stops_at_its_instance(self):
        """
        The caller applies its highlight to everything below the end of the
        path it is handed. Left at the mode switch that is every instance the
        view provider draws, each of which lights the part of the index the
        detail carries - a different face in every one of them.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        from pivy import coin

        outer_imp, first, second = self._nested_instances()
        self.assertEqual(
            len(self._face_sets_below(outer_imp.ViewObject.RootNode)),
            3,
            "the instance itself and the two legs nested in it",
        )

        for element in (f"{first.Name}.Solid1", f"{second.Name}.Solid1", "Solid1"):
            path = coin.SoPath()
            self.assertIsNotNone(
                outer_imp.ViewObject.getDetailPath(element, path, True),
                f"{element} has a face to highlight",
            )
            self.assertEqual(
                len(self._face_sets_below(path.getTail())),
                1,
                f"{element} reaches a single instance",
            )

            action = coin.SoGetBoundingBoxAction(coin.SbViewportRegion(400, 400))
            action.apply(path)
            self.assertAlmostEqual(
                action.getBoundingBox().getCenter().getValue()[1],
                outer_imp.getSubObject(element).BoundBox.Center.y,
                delta=1e-3,
                msg=f"{element} leads to the instance that draws it",
            )

    def test_selecting_an_imported_solid_lights_up_its_faces(self):
        """
        A solid has no part of its own to highlight, so the instance lights
        every face of it. Nothing tells the view provider that a solid it never
        rendered under its own name was selected, so it has to watch.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FreeCADGui

        leg, _ = self._two_solid_leg()
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        self.document.recompute()

        FreeCADGui.Selection.clearSelection()
        self.assertEqual(self._part_indices(imp.ViewObject, "selectionPartIndex"), [])

        FreeCADGui.Selection.addSelection(self.document.Name, imp.Name, "Solid1")
        selected = self._part_indices(imp.ViewObject, "selectionPartIndex")
        self.assertEqual(len(selected), 6, "every face of the box the solid is")

        FreeCADGui.Selection.addSelection(self.document.Name, imp.Name, "Solid2")
        both = self._part_indices(imp.ViewObject, "selectionPartIndex")
        self.assertEqual(len(both), 12, "the faces of both solids")

        FreeCADGui.Selection.clearSelection()
        self.assertEqual(self._part_indices(imp.ViewObject, "selectionPartIndex"), [])

    def test_hovering_an_imported_solid_lights_up_its_faces(self):
        """
        Hovering a cut face preselects the solid, which the detail behind the
        pick can only name one face of. The rest of them go through the
        highlight overlay instead.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FreeCADGui

        leg, _ = self._two_solid_leg()
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        self.document.recompute()

        FreeCADGui.Selection.clearPreselection()
        self.assertEqual(self._part_indices(imp.ViewObject, "highlightPartIndex"), [])

        FreeCADGui.Selection.setPreselection(imp, "Solid2")
        self.assertEqual(len(self._part_indices(imp.ViewObject, "highlightPartIndex")), 6)

        # A face is highlighted by the detail the pick already carries, so it
        # has no business in the overlay.
        FreeCADGui.Selection.setPreselection(imp, "Face1")
        self.assertEqual(self._part_indices(imp.ViewObject, "highlightPartIndex"), [])

        FreeCADGui.Selection.clearPreselection()
        self.assertEqual(self._part_indices(imp.ViewObject, "highlightPartIndex"), [])

    @staticmethod
    def _drawn_mesh(view_object):
        """
        Number of mesh faces an instance hands to Coin, 0 while it draws none.

        Counted by the separators that close them, since the field of an index
        set that draws nothing is not empty but holds a single index. The mesh
        renderer writes plain index sets, the geometry BREP ones.
        """
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoIndexedFaceSet.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(True)
        search.apply(view_object.RootNode)
        paths = search.getPaths()
        drawn = 0
        for i in range(paths.getLength()):
            node = paths[i].getTail()
            if node.getTypeId().getName() != "IndexedFaceSet":
                continue
            faces = sum(1 for j in range(node.coordIndex.getNum()) if node.coordIndex[j] < 0)
            drawn = max(drawn, faces)
        return drawn

    @staticmethod
    def _mesh_categories(view_object):
        """Category indices the mesh of an instance is coloured by."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoIndexedFaceSet.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(True)
        search.apply(view_object.RootNode)
        paths = search.getPaths()
        used = set()
        for i in range(paths.getLength()):
            node = paths[i].getTail()
            if node.getTypeId().getName() != "IndexedFaceSet":
                continue
            if node.coordIndex.getNum() == 0:
                continue
            used.update(node.materialIndex[j] for j in range(node.materialIndex.getNum()))
        return used

    def test_an_import_draws_its_mesh_after_a_reload(self):
        """
        A mesh comes out of its own file in the archive, later than the objects
        that ask for it. An instance that read the merge of the source mesh
        group in that window got an empty one, and nothing about restoring the
        children afterwards says so.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FemGui

        leg, _ = self._two_solid_leg()
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        self.document.recompute()

        table_name = table.Name
        import_name = imp.Name
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "import_mesh.FCStd")
            self.document.saveAs(path)
            FreeCAD.closeDocument(self.document.Name)
            # tearDown closes self.document, so hand it the reloaded one
            self.document = FreeCAD.openDocument(path)

        table = self.document.getObject(table_name)
        imp = self.document.getObject(import_name)
        state = FemGui.getAnalysisViewState(table)
        state.setActiveStage("Mesh")
        self.assertGreater(
            self._drawn_mesh(imp.ViewObject),
            0,
            "the instance draws the mesh of its source in the mesh stage",
        )

    def test_hiding_an_imported_solid_hides_its_mesh(self):
        """
        The mesh of an instance follows the panel like its geometry does. The
        element names its cells carry are those of the source analysis, and
        losing them on the way into the instance leaves a mesh that nothing can
        be hidden from.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FemGui

        leg, _ = self._two_solid_leg(per_solid_mesh=True)
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        self.document.recompute()

        state = FemGui.getAnalysisViewState(table)
        state.setActiveStage("Mesh")
        # The ghost of what is hidden is drawn too, and says nothing about this
        state.setOverlay(False)
        whole = self._drawn_mesh(imp.ViewObject)
        self.assertGreater(whole, 0, "the instance draws the mesh of its source")

        state.setElementHidden("Leg1.Solid1", True)
        rest = self._drawn_mesh(imp.ViewObject)
        self.assertLess(rest, whole, "the cells of the hidden solid must be gone")
        self.assertGreater(rest, 0, "the other solid keeps its cells")

        state.setElementHidden("Leg1.Solid1", False)
        self.assertEqual(self._drawn_mesh(imp.ViewObject), whole)

    def test_two_instances_colour_their_meshes_apart(self):
        """
        Two instances of one source place the same mesh, and its cells name
        their elements as the source does. Read without the path they lead to
        the same categories for both instances, and to categories of a native
        element where the names happen to meet.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FemGui

        leg, _ = self._two_solid_leg(per_solid_mesh=True)
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        first, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        second, _ = self._add_import(table, leg, "Leg2", vector=FreeCAD.Vector(160, 0, 0))
        self.document.recompute()

        state = FemGui.getAnalysisViewState(table)
        state.setActiveStage("Mesh")
        state.setColorMode("Component")

        keys = [c["key"] for c in state.getCategories()]
        self.assertIn("Leg1.Component1", keys)
        self.assertIn("Leg2.Component1", keys)
        self.assertEqual(
            len(keys),
            len(set(keys)),
            "a category is named once",
        )

        by_key = {key: index for index, key in enumerate(keys)}
        drawn_first = self._mesh_categories(first.ViewObject)
        drawn_second = self._mesh_categories(second.ViewObject)
        self.assertTrue(drawn_first and drawn_second, "both instances draw a mesh")
        self.assertFalse(
            drawn_first & drawn_second,
            "the mesh of an instance wears the colours of its own elements",
        )
        self.assertEqual(
            drawn_first,
            {by_key["Leg1.Component1"], by_key["Leg1.Component2"]},
            "a component of an instance is coloured by the category of its path",
        )
        self.assertEqual(drawn_second, {by_key["Leg2.Component1"], by_key["Leg2.Component2"]})

    def test_hiding_an_imported_element_reaches_the_view(self):
        """Switching a solid of an instance off has to take it off the screen."""
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FemGui
        from pivy import coin

        def drawn_width(view_object):
            action = coin.SoGetBoundingBoxAction(coin.SbViewportRegion(400, 400))
            action.apply(view_object.RootNode)
            box = action.getBoundingBox()
            return None if box.isEmpty() else box.getSize().getValue()[0]

        leg, _ = self._two_solid_leg()
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(80, 0, 0))
        self.document.recompute()

        state = FemGui.getAnalysisViewState(table)
        state.setOverlay(False)
        whole = drawn_width(imp.ViewObject)
        self.assertIsNotNone(whole, "the instance draws both solids")

        state.setElementHidden("Leg1.Solid1", True)
        rest = drawn_width(imp.ViewObject)
        self.assertIsNotNone(rest, "the other solid stays on screen")
        self.assertLess(rest, whole, "the hidden solid must be gone")

        state.setElementHidden("Leg1.Solid1", False)
        self.assertAlmostEqual(drawn_width(imp.ViewObject), whole, places=4)

    @staticmethod
    def _drawn_bound_box(view_object):
        """Where in the analysis an instance puts the surfaces it draws."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoIndexedFaceSet.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(view_object.RootNode)
        paths = search.getPaths()
        box = coin.SbBox3f()
        for i in range(paths.getLength()):
            if paths[i].getTail().getTypeId().getName() != "SoBrepFaceSet":
                continue
            action = coin.SoGetBoundingBoxAction(coin.SbViewportRegion(400, 400))
            action.apply(paths[i])
            box.extendBy(action.getBoundingBox())
        return box

    def test_a_nested_instance_is_drawn_where_the_model_places_it(self):
        """
        The branch of a nested instance hangs inside the branch of the one it
        belongs to, which already carries that placement. Writing the whole
        chain into it as well applies everything above twice, and the deeper a
        level sits the further it drifts from the rest.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        leg, _ = self._two_solid_leg()
        middle, _, _ = self._table_analysis(mesh_group=True)
        inner, _ = self._add_import(middle, leg, "Leg1", vector=FreeCAD.Vector(0, 0, 30))
        self.document.recompute()

        outer, _, _ = self._table_analysis(mesh_group=True)
        outer_imp, _ = self._add_import(outer, middle, "Middle1", vector=FreeCAD.Vector(0, 0, 100))
        self.document.recompute()

        expected = outer_imp.getSubObject(f"{inner.Name}.Solid1").BoundBox
        drawn = self._drawn_bound_box(outer_imp.ViewObject)
        self.assertFalse(drawn.isEmpty(), "the nested instance has to draw something")
        self.assertAlmostEqual(drawn.getMin().getValue()[2], expected.ZMin, delta=1e-3)
        self.assertAlmostEqual(drawn.getMax().getValue()[2], expected.ZMax, delta=1e-3)

    def test_the_placement_panel_opens_with_a_dragger(self):
        """
        Placing the instance is what the panel is for, so the dragger is up
        from the start. Its size is a fraction of the screen, which means
        nothing to a dragger that follows no camera: it reads the number as a
        length in millimetres and draws itself too small to find.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FreeCADGui
        from pivy import coin

        leg, _ = self._two_solid_leg()
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(0, -200, 40))
        self.document.recompute()

        gui_document = FreeCADGui.getDocument(self.document.Name)
        self.assertTrue(gui_document.setEdit(imp.ViewObject, 0))
        try:
            search = coin.SoSearchAction()
            search.setType(coin.SoDragger.getClassTypeId())
            search.setInterest(coin.SoSearchAction.FIRST)
            search.setSearchingAll(True)
            search.apply(imp.ViewObject.RootNode)
            path = search.getPath()
            self.assertIsNotNone(path, "the panel comes up with the dragger already there")

            dragger = path.getTail()
            self.assertFalse(
                dragger.getField("autoScaleResult").isConnectedFromField(),
                "a dragger that follows no camera is drawn microscopically small",
            )
            self.assertEqual(
                dragger.getField("translation").getValue().getValue(),
                (0.0, -200.0, 40.0),
            )
        finally:
            gui_document.resetEdit()

    def test_the_placement_panel_leaves_the_instance_where_it_is(self):
        """
        Setting a field up makes it report a value, and an empty field reports
        zero. Read back as an edit, opening the panel drops the instance at the
        origin before it has been touched.
        """
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for view providers")

        import FreeCADGui

        leg, _ = self._two_solid_leg()
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(0, -200, 40))
        self.document.recompute()
        before = imp.Placement.Base

        gui_document = FreeCADGui.getDocument(self.document.Name)
        self.assertTrue(gui_document.setEdit(imp.ViewObject, 0))
        try:
            self.assertEqual(imp.Placement.Base, before)
        finally:
            gui_document.resetEdit()

    def test_import_subobject_respects_placement(self):
        """References on the import resolve through getSubObject with placement."""
        leg, leg_geom, _ = self._leg_analysis()
        table, _, _ = self._table_analysis()
        offset = FreeCAD.Vector(100, 0, 0)
        imp, _ = self._add_import(table, leg, "Leg1", offset)
        self.document.recompute()

        source = leg_geom.Shape.getElement("Face1").BoundBox.Center
        placed = imp.getSubObject("Face1").BoundBox.Center
        self.assertEqual(placed, source + offset)

    def test_dragging_import_does_not_rebuild_source(self):
        """Moving an import must not touch the source analysis mesh revision."""
        leg, _, mesh_group = self._leg_analysis()
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1")
        self.document.recompute()
        before = mesh_group.FemMesh.NodeCount

        imp.Placement = FreeCAD.Placement(FreeCAD.Vector(50, 0, 0), FreeCAD.Rotation())
        self.document.recompute()
        self.assertEqual(mesh_group.FemMesh.NodeCount, before)

    def test_import_cycle_is_rejected(self):
        leg, _, _ = self._leg_analysis()
        table, _, _ = self._table_analysis()
        self._add_import(table, leg)
        self.document.recompute()
        back, _ = self._add_import(leg, table, "BackImport")

        # A link cycle is a cycle in the dependency graph too, and whether the
        # document recompute still reaches the import depends on the rest of the
        # graph. Recompute the import itself so this pins the guard rather than
        # that ordering.
        self.document.recompute()
        back.recompute()
        self.assertIn("Invalid", back.State)

    def test_self_import_is_rejected(self):
        leg, _, _ = self._leg_analysis()
        imp, _ = self._add_import(leg, leg, "SelfImport")
        self.document.recompute()
        imp.recompute()
        self.assertIn("Invalid", imp.State)

    def test_imported_analysis_can_be_prepared_for_solving(self):
        from femtools import membertools

        leg, _, _, _, _ = self._leg_analysis_with_members(with_members=True)
        table, _, _ = self._table_analysis(mesh_group=True)
        self._add_import(table, leg)
        self.document.recompute()
        mesh = membertools.get_mesh_to_solve(table)
        self.assertIsNotNone(mesh)
        self.assertTrue(mesh.FemMesh.NodeCount > 0)

    def test_solve_assembly_follows_import_placement(self):
        from femtools import membertools

        leg, _, _ = self._leg_analysis()
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1")
        self.document.recompute()
        assembly = membertools.get_mesh_to_solve(table)
        self.assertEqual(assembly.FemMesh.Nodes[1], FreeCAD.Vector(0, 0, 0))

        offset = FreeCAD.Vector(50, 0, 0)
        imp.Placement = FreeCAD.Placement(offset, FreeCAD.Rotation())
        self.document.recompute()
        assembly = membertools.get_mesh_to_solve(table)
        self.assertEqual(assembly.FemMesh.Nodes[1], offset)

    def test_solve_assembly_groups_use_path_names(self):
        """
        A group of an instance is named after the path to it, joined the way an
        inherited member name is, so that the group-data lookup of meshtools
        finds a member's group by name instead of searching geometrically.
        """
        from femtools import membertools

        leg, _, _ = self._leg_analysis()
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1")
        self.document.recompute()
        assembly = membertools.get_mesh_to_solve(table)
        names = self._group_names(assembly.FemMesh)
        self.assertIn(f"{imp.Name}_Solid1", names)
        self.assertNotIn(f"{imp.Name}.Solid1", names)

    def test_two_instances_share_template_distinct_assembly_nodes(self):
        from femtools import membertools

        leg, _, mesh_group = self._leg_analysis()
        table, _, _ = self._table_analysis(mesh_group=True)
        self._add_import(table, leg, "Leg1")
        self._add_import(table, leg, "Leg2", vector=FreeCAD.Vector(20, 0, 0))
        self.document.recompute()

        source_nodes = mesh_group.FemMesh.NodeCount
        assembly = membertools.get_mesh_to_solve(table)
        self.assertEqual(assembly.FemMesh.NodeCount, 2 * source_nodes)

    def test_inherited_members_use_path_references(self):
        from femtools import importmembers, membertools

        leg, _, _, mat, fixed = self._leg_analysis_with_members(with_members=True)
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1")
        self.document.recompute()

        member = membertools.AnalysisMember(table)
        self.assertEqual(len(member.mats_linear), 1)
        inherited_mat = member.mats_linear[0]["Object"]
        self.assertEqual(inherited_mat.Name, f"Leg1_{mat.Name}")
        self.assertEqual(inherited_mat.References[0], (imp, ["Solid1"]))

        self.assertEqual(len(member.cons_fixed), 1)
        inherited_fixed = member.cons_fixed[0]["Object"]
        self.assertEqual(inherited_fixed.Name, f"Leg1_{fixed.Name}")
        self.assertEqual(inherited_fixed.References[0], (imp, ["Face1"]))

        _, sub = importmembers.translate_reference((imp,), leg, "Solid1")
        self.assertEqual(sub, "Solid1")

    def test_suppressed_members_are_omitted(self):
        from femtools import membertools

        leg, _, _, _, fixed = self._leg_analysis_with_members(with_members=True)
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1")
        imp.SuppressedMembers = [fixed.Name]
        self.document.recompute()

        member = membertools.AnalysisMember(table)
        self.assertEqual(len(member.cons_fixed), 0)
        self.assertEqual(len(member.mats_linear), 1)

    def test_two_imports_yield_distinct_member_names(self):
        from femtools import membertools

        leg, _, _, mat, _ = self._leg_analysis_with_members(with_members=True)
        table, _, _ = self._table_analysis(mesh_group=True)
        imp1, _ = self._add_import(table, leg, "Leg1")
        imp2, _ = self._add_import(table, leg, "Leg2", vector=FreeCAD.Vector(20, 0, 0))
        self.document.recompute()

        member = membertools.AnalysisMember(table)
        self.assertEqual(len(member.mats_linear), 2)
        names = {entry["Object"].Name for entry in member.mats_linear}
        self.assertEqual(names, {f"Leg1_{mat.Name}", f"Leg2_{mat.Name}"})
        ref_objs = {entry["Object"].References[0][0] for entry in member.mats_linear}
        ref_subs = {entry["Object"].References[0][1][0] for entry in member.mats_linear}
        self.assertEqual(ref_objs, {imp1, imp2})
        self.assertEqual(ref_subs, {"Solid1"})

    def test_empty_material_references_cover_the_import_only(self):
        from femtools import membertools

        leg, leg_geom, _, _, _ = self._leg_analysis_with_members(with_members=False)
        mat = ObjectsFem.makeMaterialSolid(self.document, "LegMaterial")
        mat.References = []
        leg.addObject(mat)
        self.document.recompute()

        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1")
        self.document.recompute()

        member = membertools.AnalysisMember(table)
        self.assertEqual(len(member.mats_linear), 1)
        entry = member.mats_linear[0]
        refs = entry["Object"].References
        self.assertEqual(refs[0][0], imp)
        self.assertEqual(set(refs[0][1]), {"Solid1"})
        self.assertEqual(entry["RefShapeType"], "Solid")

    def test_an_empty_import_material_does_not_claim_native_elements(self):
        from femtools import membertools

        leg, _, _, _, _ = self._leg_analysis_with_members(with_members=False)
        mat = ObjectsFem.makeMaterialSolid(self.document, "LegMaterial")
        mat.References = []
        leg.addObject(mat)
        self.document.recompute()

        table, table_geom, _ = self._table_analysis(mesh_group=True)
        native = self.document.addObject("Part::Feature", "TablePart")
        native.Shape = _box()
        native_import = ObjectsFem.makeGeometryImport(self.document)
        native_import.Import = [native]
        table_geom.Group = [native_import]
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(40, 0, 0))
        self.document.recompute()

        member = membertools.AnalysisMember(table)
        claimed = set(member.mats_linear[0]["Object"].References[0][1])
        self.assertEqual(claimed, {"Solid1"})
        self.assertEqual(member.mats_linear[0]["Object"].References[0][0], imp)

    def test_nested_import_resolves_transitively(self):
        from femtools import membertools

        leg, _, _, mat, fixed = self._leg_analysis_with_members(with_members=True)

        middle, _, _ = self._table_analysis(mesh_group=True)
        middle.Label = "Middle"
        inner, _ = self._add_import(middle, leg, "Leg1")
        self.document.recompute()

        outer, _, _ = self._table_analysis(mesh_group=True)
        outer.Label = "Outer"
        outer_imp, _ = self._add_import(outer, middle, "Middle1")
        self.document.recompute()

        member = membertools.AnalysisMember(outer)
        self.assertEqual(len(member.mats_linear), 1)
        self.assertEqual(len(member.cons_fixed), 1)

        inherited_mat = member.mats_linear[0]["Object"]
        self.assertEqual(inherited_mat.Name, f"Middle1_{inner.Name}_{mat.Name}")
        self.assertEqual(inherited_mat.References[0], (outer_imp, [f"{inner.Name}.Solid1"]))

        inherited_fixed = member.cons_fixed[0]["Object"]
        self.assertEqual(inherited_fixed.Name, f"Middle1_{inner.Name}_{fixed.Name}")
        self.assertEqual(inherited_fixed.References[0], (outer_imp, [f"{inner.Name}.Face1"]))
        self.assertEqual(member.cons_fixed[0]["RefShapeType"], "Face")

    def test_path_references_survive_save_and_reload(self):
        from femtools import membertools

        leg, _, _, mat, _ = self._leg_analysis_with_members(with_members=True)
        table, _, _ = self._table_analysis(mesh_group=True)
        self._add_import(table, leg, "Leg1")
        self.document.recompute()
        refs = membertools.AnalysisMember(table).mats_linear[0]["Object"].References[0]
        before_obj_name = refs[0].Name
        before_subs = list(refs[1])

        name = table.Name
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "import.FCStd")
            self.document.saveAs(path)
            FreeCAD.closeDocument(self.document.Name)
            self.document = FreeCAD.openDocument(path)

        table = self.document.getObject(name)
        after_obj, after_subs = (
            membertools.AnalysisMember(table).mats_linear[0]["Object"].References[0]
        )
        self.assertEqual(after_subs, before_subs)
        self.assertEqual(after_obj.Name, before_obj_name)

    def test_suppressed_component_absent_from_deck(self):
        import tempfile

        from femtools import ccxtools, membertools

        leg, leg_geom, _, mat, _ = self._leg_analysis_with_members(with_members=True)
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1")
        imp.SuppressedComponents = [1]
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.document)
        table.addObject(solver)
        self.document.recompute()

        tools = ccxtools.FemToolsCcx(analysis=table, solver=solver, test_mode=True)
        tools.update_objects()
        with tempfile.TemporaryDirectory() as working_dir:
            tools.setup_working_dir(working_dir)
            tools.write_inp_file()
            with open(tools.inp_file_name, encoding="utf-8") as deck_file:
                deck = deck_file.read()

        assembly = membertools.get_mesh_to_solve(table)
        self.assertNotIn(f"{imp.Name}.Solid1", self._group_names(assembly.FemMesh))
        self.assertNotIn("Leg1_LegMaterialSolid", deck)

    def test_solve_assembly_follows_a_rotated_placement(self):
        """
        A rotation reaches the assembly nodes, not just a translation: the mesh
        of an instance is transformed by the whole placement.
        """
        from femtools import membertools

        leg, _, _ = self._leg_analysis()
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1")
        # The source tet has a node at (1, 0, 0); a quarter turn about z puts it
        # on the y axis.
        imp.Placement = FreeCAD.Placement(
            FreeCAD.Vector(), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 90)
        )
        self.document.recompute()

        assembly = membertools.get_mesh_to_solve(table)
        turned = [
            node
            for node in assembly.FemMesh.Nodes.values()
            if node.distanceToPoint(FreeCAD.Vector(0, 1, 0)) < 1e-7
        ]
        self.assertEqual(len(turned), 1)
        self.assertFalse(
            any(
                node.distanceToPoint(FreeCAD.Vector(1, 0, 0)) < 1e-7
                for node in assembly.FemMesh.Nodes.values()
            )
        )

    def test_solve_assembly_records_where_each_piece_came_from(self):
        """
        The assembly says which instance a cell and a node came from; a solver
        reports per element and node, and nothing else survives the merge.
        """
        from femtools import membertools

        leg, _, leg_mesh_group = self._leg_analysis()
        table, _, _ = self._table_analysis(mesh_group=True, native=True)
        first, _ = self._add_import(table, leg, "Leg1")
        second, _ = self._add_import(table, leg, "Leg2", vector=FreeCAD.Vector(20, 0, 0))
        self.document.recompute()

        assembly = membertools.get_mesh_to_solve(table)
        paths = set(assembly.CellSources)
        self.assertIn("", paths)
        self.assertIn(first.Name, paths)
        self.assertIn(second.Name, paths)

        # Every cell of the merged mesh is accounted for.
        mesh = assembly.FemMesh
        self.assertEqual(
            len(assembly.CellSources), mesh.VolumeCount + mesh.FaceCount + mesh.EdgeCount
        )
        for element_id in list(mesh.Volumes) + list(mesh.Faces):
            self.assertIn(assembly.path_of_cell(element_id), paths)

        # Two instances of one source: the same source node twice over, each
        # under the instance it belongs to.
        source_node = min(leg_mesh_group.FemMesh.Nodes.keys())
        self.assertEqual(set(assembly.NodeSources.keys()), {first.Name, second.Name})
        for name in (first.Name, second.Name):
            assembly_id = assembly.NodeSources[name][source_node]
            self.assertEqual(assembly.source_node_of(assembly_id), (name, source_node))
        self.assertNotEqual(
            assembly.NodeSources[first.Name][source_node],
            assembly.NodeSources[second.Name][source_node],
        )

    def test_solve_assembly_picks_up_a_changed_source(self):
        """
        Nothing about an import changes when its source is remeshed, so the
        assembly has to be built from the source as it is now.
        """
        from femtools import membertools

        leg, _, leg_mesh_group = self._leg_analysis()
        table, _, _ = self._table_analysis(mesh_group=True)
        self._add_import(table, leg, "Leg1")
        self.document.recompute()
        before = membertools.get_mesh_to_solve(table).FemMesh.NodeCount

        second = self.document.addObject("Fem::FemMeshObject", "LegMesh2")
        mesh = Fem.FemMesh()
        mesh.addNode(5, 5, 5, 1)
        mesh.addNode(6, 5, 5, 2)
        mesh.addNode(5, 6, 5, 3)
        mesh.addNode(5, 5, 6, 4)
        mesh.addVolume([1, 2, 3, 4])
        second.FemMesh = mesh
        leg_mesh_group.addObject(second)
        self.document.recompute()

        after = membertools.get_mesh_to_solve(table).FemMesh.NodeCount
        self.assertEqual(after, before + 4)

    def test_mixed_native_and_inherited_members_reach_the_deck(self):
        """
        An analysis that meshes something of its own and places another keeps
        both in one deck, the native member on the native geometry and the
        inherited one on the instance.
        """
        from femtools import ccxtools, membertools

        leg, _, _, leg_mat, leg_fixed = self._leg_analysis_with_members(with_members=True)
        table, table_geom, _ = self._table_analysis(mesh_group=True, native=True)
        # Away from the native part, so that the deck can tell the two apart.
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(20, 0, 0))

        table_mat = ObjectsFem.makeMaterialSolid(self.document, "TableMaterial")
        card = table_mat.Material
        card["Name"] = "CalculiX-Steel"
        card["YoungsModulus"] = "210000 MPa"
        card["PoissonRatio"] = "0.30"
        card["Density"] = "7900 kg/m^3"
        table_mat.Material = card
        table_mat.References = [(table_geom, ["Solid1"])]
        table.addObject(table_mat)

        tie = ObjectsFem.makeConstraintTie(self.document, "TableTie")
        tie.References = [(table_geom, ["Face1"]), (imp, ["Face1"])]
        table.addObject(tie)

        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.document)
        table.addObject(solver)
        self.document.recompute()

        member = membertools.AnalysisMember(table)
        self.assertEqual(len(member.mats_linear), 2)
        self.assertEqual(len(member.cons_tie), 1)

        tools = ccxtools.FemToolsCcx(analysis=table, solver=solver, test_mode=True)
        tools.update_objects()
        with tempfile.TemporaryDirectory() as working_dir:
            tools.setup_working_dir(working_dir)
            tools.write_inp_file()
            with open(tools.inp_file_name, encoding="utf-8") as deck_file:
                deck = deck_file.read()

        self.assertIn(table_mat.Name, deck)
        self.assertIn(f"Leg1_{leg_mat.Name}", deck)
        self.assertIn(f"Leg1_{leg_fixed.Name}", deck)
        self.assertIn(tie.Name, deck)
        self.assertIn("*TIE", deck)

    def test_a_member_referencing_an_inner_import_keeps_the_whole_path(self):
        """
        A member of an imported analysis may reference an instance that analysis
        places, and then the inner instance is part of the path as well.
        """
        from femtools import importmembers, membertools

        leg, _, _ = self._leg_analysis()

        middle, middle_geom, _ = self._table_analysis(mesh_group=True)
        middle.Label = "Middle"
        inner, _ = self._add_import(middle, leg, "Leg1")
        fixed = ObjectsFem.makeConstraintFixed(self.document, "MiddleFixed")
        fixed.References = [(inner, ["Face1"])]
        middle.addObject(fixed)
        self.document.recompute()

        outer, _, _ = self._table_analysis(mesh_group=True)
        outer.Label = "Outer"
        outer_imp, _ = self._add_import(outer, middle, "Middle1")
        self.document.recompute()

        # Seen from the middle analysis the reference is already a path.
        _, sub = importmembers.translate_reference((), inner, "Face1")
        self.assertEqual(sub, "Face1")
        _, sub = importmembers.translate_reference((outer_imp,), inner, "Face1")
        self.assertEqual(sub, f"{inner.Name}.Face1")

        member = membertools.AnalysisMember(outer)
        inherited = [
            m["Object"] for m in member.cons_fixed if m["Object"].Name.endswith(fixed.Name)
        ]
        self.assertEqual(len(inherited), 1)
        self.assertEqual(inherited[0].References[0], (outer_imp, [f"{inner.Name}.Face1"]))

    def test_an_instance_suppresses_a_nested_member_by_path(self):
        """
        Switching a member of a nested instance off names it by the path to it,
        so the other instances of the same analysis keep it.
        """
        from femtools import membertools

        leg, _, _, _, fixed = self._leg_analysis_with_members(with_members=True)

        middle, _, _ = self._table_analysis(mesh_group=True)
        middle.Label = "Middle"
        inner, _ = self._add_import(middle, leg, "Leg1")
        self.document.recompute()

        outer, _, _ = self._table_analysis(mesh_group=True)
        outer.Label = "Outer"
        first, _ = self._add_import(outer, middle, "Middle1")
        second, _ = self._add_import(outer, middle, "Middle2", vector=FreeCAD.Vector(30, 0, 0))
        self.document.recompute()
        self.assertEqual(len(membertools.AnalysisMember(outer).cons_fixed), 2)

        first.SuppressedMembers = [f"{inner.Name}.{fixed.Name}"]
        self.document.recompute()

        remaining = membertools.AnalysisMember(outer).cons_fixed
        self.assertEqual(len(remaining), 1)
        self.assertTrue(remaining[0]["Object"].Name.startswith(f"{second.Name}_"))

    def test_element_shape_of_an_imported_element_is_the_source_shape(self):
        """
        An element of an instance is numbered in the shape of the analysis it
        came from; an import carries no shape of its own.
        """
        from femtools import geomtools

        leg, leg_geom, _ = self._leg_analysis()
        middle, _, _ = self._table_analysis(mesh_group=True)
        inner, _ = self._add_import(middle, leg, "Leg1")
        self.document.recompute()

        outer, _, _ = self._table_analysis(mesh_group=True)
        outer_imp, _ = self._add_import(outer, middle, "Middle1")
        self.document.recompute()

        shape = geomtools.get_element_shape(inner, "Face1")
        self.assertIsNotNone(shape)
        self.assertEqual(len(shape.Faces), len(leg_geom.Shape.Faces))

        nested = geomtools.get_element_shape(outer_imp, f"{inner.Name}.Face1")
        self.assertIsNotNone(nested)
        self.assertEqual(len(nested.Faces), len(leg_geom.Shape.Faces))

    def test_imported_analysis_mesh_sets_resolve(self):
        from femmesh import meshtools
        from femtools import membertools

        leg, _, _, _, _ = self._leg_analysis_with_members(with_members=True)
        table, _, _ = self._table_analysis(mesh_group=True)
        self._add_import(table, leg, "Leg1")
        self.document.recompute()

        member = membertools.AnalysisMember(table)
        mesh = membertools.get_mesh_to_solve(table)
        self.assertEqual(len(member.cons_fixed), 1)
        nodes = meshtools.get_femnodes_by_references(
            mesh.FemMesh, member.cons_fixed[0]["Object"].References
        )
        self.assertTrue(nodes)

    def test_calculix_deck_names_the_inherited_members(self):
        import tempfile

        from femtools import ccxtools

        leg, _, _, mat, fixed = self._leg_analysis_with_members(with_members=True)
        table, _, _ = self._table_analysis(mesh_group=True)
        self._add_import(table, leg, "Leg1")
        solver = ObjectsFem.makeSolverCalculiXCcxTools(self.document)
        table.addObject(solver)
        self.document.recompute()

        tools = ccxtools.FemToolsCcx(analysis=table, solver=solver, test_mode=True)
        tools.update_objects()
        with tempfile.TemporaryDirectory() as working_dir:
            tools.setup_working_dir(working_dir)
            tools.write_inp_file()
            self.assertTrue(tools.inp_file_name)
            with open(tools.inp_file_name, encoding="utf-8") as deck_file:
                deck = deck_file.read()

        self.assertIn(f"Leg1_{fixed.Name}", deck)
        self.assertIn(f"Leg1_{mat.Name}", deck)
        self.assertIn("*BOUNDARY", deck)
        self.assertIn("*MATERIAL", deck)

    @staticmethod
    def _symbol_copies(view_object, traverse_hidden=False):
        """The SoMultipleCopy nodes of a view provider, one per drawn constraint.

        By default only the branch that is actually traversed for rendering is
        searched, so the result also tells whether the symbols are visible.
        """
        from pivy import coin

        root = view_object.RootNode
        search = coin.SoSearchAction()
        search.setType(coin.SoMultipleCopy.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(traverse_hidden)
        search.apply(root)
        paths = search.getPaths()
        return [paths[i].getTail() for i in range(paths.getLength())]

    @staticmethod
    def _copy_translation(multi_copy, index=0):
        rows = multi_copy.matrix[index].getValue()
        return FreeCAD.Vector(rows[3][0], rows[3][1], rows[3][2])

    @staticmethod
    def _symbol_position(view_object, index=0):
        """
        Where a symbol of *view_object* is drawn, in analysis coordinates.

        The symbols hang below the placement of the instance rather than
        carrying it each, so where they end up is what the scene graph makes of
        their matrices on the way down.
        """
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoMultipleCopy.getClassTypeId())
        search.setInterest(coin.SoSearchAction.FIRST)
        search.apply(view_object.RootNode)
        path = search.getPath()
        if path is None:
            return None

        action = coin.SoGetMatrixAction(coin.SbViewportRegion())
        action.apply(path)
        # Coin matrices multiply a row vector from the left, so the first three
        # rows are the axes of the frame and the last one is its origin.
        rows = action.getMatrix().getValue()
        local = TestAnalysisImport._copy_translation(path.getTail(), index)
        placed = FreeCAD.Vector(rows[3][0], rows[3][1], rows[3][2])
        for distance, row in zip((local.x, local.y, local.z), rows[:3]):
            placed += FreeCAD.Vector(row[0], row[1], row[2]) * distance
        return placed

    def test_inherited_constraint_symbols_follow_import_placement(self):
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for inherited constraint symbols")

        leg, leg_geom, _, _, fixed = self._leg_analysis_with_members(with_members=True)
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(50, 0, 0))
        self.document.recompute()

        source_points = list(fixed.Points)
        self.assertTrue(source_points)

        vp = imp.ViewObject
        self.assertTrue(vp.ShowInheritedConstraints)

        copies = self._symbol_copies(vp)
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].matrix.getNum(), len(source_points))

        # The symbols are drawn in the coordinates of the importing analysis:
        # the source point moved by the instance placement.
        local = leg_geom.getGlobalPlacement().inverse().multVec(source_points[0])
        expected = local + FreeCAD.Vector(50, 0, 0)
        self.assertAlmostEqual((self._symbol_position(vp) - expected).Length, 0.0, places=4)

        imp.Placement = FreeCAD.Placement(FreeCAD.Vector(90, 0, 0), FreeCAD.Rotation())
        self.document.recompute()
        copies = self._symbol_copies(vp)
        self.assertEqual(len(copies), 1)
        expected = local + FreeCAD.Vector(90, 0, 0)
        self.assertAlmostEqual((self._symbol_position(vp) - expected).Length, 0.0, places=4)

    def test_hiding_inherited_symbols_removes_them(self):
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for inherited constraint symbols")

        leg, _, _, _, fixed = self._leg_analysis_with_members(with_members=True)
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1")
        self.document.recompute()

        vp = imp.ViewObject
        self.assertEqual(len(self._symbol_copies(vp)), 1)

        vp.ShowInheritedConstraints = False
        self.assertEqual(len(self._symbol_copies(vp)), 0)

        vp.ShowInheritedConstraints = True
        self.assertEqual(len(self._symbol_copies(vp)), 1)

        imp.SuppressedMembers = [fixed.Name]
        self.document.recompute()
        self.assertEqual(len(self._symbol_copies(vp)), 0)

    def test_hiding_the_import_hides_inherited_symbols(self):
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for inherited constraint symbols")

        leg, _, _, _, _ = self._leg_analysis_with_members(with_members=True)
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1")
        self.document.recompute()

        vp = imp.ViewObject
        self.assertEqual(len(self._symbol_copies(vp)), 1)

        vp.Visibility = False
        self.assertEqual(len(self._symbol_copies(vp)), 0)
        # Still built, just not traversed.
        self.assertTrue(self._symbol_copies(vp, traverse_hidden=True))

        vp.Visibility = True
        self.assertEqual(len(self._symbol_copies(vp)), 1)

    def test_a_source_constraint_added_later_gets_a_symbol(self):
        if not FreeCAD.GuiUp:
            self.skipTest("GUI required for inherited constraint symbols")

        leg, leg_geom, _, _, _ = self._leg_analysis_with_members(with_members=False)
        table, _, _ = self._table_analysis(mesh_group=True)
        imp, _ = self._add_import(table, leg, "Leg1")
        self.document.recompute()

        vp = imp.ViewObject
        self.assertEqual(len(self._symbol_copies(vp)), 0)

        fixed = ObjectsFem.makeConstraintFixed(self.document, "LegFixed")
        fixed.References = [(leg_geom, ["Face1"])]
        leg.addObject(fixed)
        self.document.recompute()

        self.assertEqual(len(self._symbol_copies(vp)), 1)

        self.document.removeObject(fixed.Name)
        self.document.recompute()
        self.assertEqual(len(self._symbol_copies(vp)), 0)

    def test_a_constraint_on_an_instance_gets_its_symbol_points(self):
        """
        An instance carries no shape property of its own, so the symbol
        placement found nothing to measure and a constraint referencing an
        instance drew no symbol at all.
        """
        leg, _, _ = self._leg_analysis()
        table, _, _ = self._table_analysis()
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(0, 0, 20))
        self.document.recompute()

        fixed = ObjectsFem.makeConstraintFixed(self.document, "TableFixed")
        fixed.References = [(imp, ["Face1"])]
        table.addObject(fixed)
        self.document.recompute()

        self.assertTrue(fixed.Points)
        self.assertEqual(len(fixed.Points), len(fixed.Normals))
        # The symbols stand where the instance draws the face, not where the
        # source analysis keeps it.
        self.assertGreaterEqual(min(p.z for p in fixed.Points), 20.0 - 1e-6)

    def test_group_data_answers_a_reference_on_an_instance(self):
        """
        The assembly names the group of an instance after its path, which is
        the name a reference on that instance has to reach for. Missing it
        sends the writer into a geometric search of the whole mesh.
        """
        from femmesh import meshtools
        from femtools import solveassembly

        leg, _, _ = self._leg_analysis()
        table, geometry, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(0, 0, 20))
        self.document.recompute()

        mesh = solveassembly.build(table).FemMesh
        self.assertEqual(meshtools.get_femmesh_group_name(imp, "Solid1"), "Leg1_Solid1")

        imported = meshtools.get_femmesh_groupdata_sets_by_refs(mesh, [(imp, ["Solid1"])], "Volume")
        native = meshtools.get_femmesh_groupdata_sets_by_refs(
            mesh, [(geometry, ["Solid1"])], "Volume"
        )
        self.assertEqual(len(imported), 1)
        self.assertEqual(len(native), 1)
        self.assertFalse(set(imported) & set(native))

    def test_solve_assembly_carries_the_cell_dimensions(self):
        """
        The dimension of a cell is classified by the mesh group of the analysis
        it came from and has to survive the merge. A cell whose dimension went
        missing would either be dropped from the deck or exported as an internal
        face of a solid.
        """
        from femmesh import meshtools
        from femtools import solveassembly

        leg, _, _ = self._leg_analysis()
        table, geometry, _ = self._table_analysis(mesh_group=True, native=True)
        self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(0, 0, 20))
        self.document.recompute()

        assembly = solveassembly.build(table)
        mesh = assembly.FemMesh
        # One entry per cell, or the entries behind a gap mean another cell.
        self.assertEqual(len(assembly.CellDimension), len(assembly.CellSources))
        self.assertEqual(
            len(assembly.CellDimension), mesh.VolumeCount + mesh.FaceCount + mesh.EdgeCount
        )

        # Both tetrahedra are model elements, none of their eight skin
        # triangles is, and the same has to come out of meshtools.
        volumes = set(mesh.Volumes)
        self.assertEqual(set(assembly.model_element_ids(3)), volumes)
        self.assertEqual(assembly.model_element_ids(2), [])
        self.assertEqual(
            set(meshtools.get_model_element_ids(assembly, mesh)),
            volumes,
        )
        self.assertEqual(meshtools.get_model_dimensions(assembly, mesh), {3})

    def test_solve_assembly_carries_the_entity_dimensions(self):
        """An entity of an instance answers under the name of its path."""
        from femmesh import meshtools
        from femtools import solveassembly

        leg, _, _ = self._leg_analysis()
        table, geometry, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(0, 0, 20))
        self.document.recompute()

        assembly = solveassembly.build(table)
        entities = meshtools.get_entity_dimension_map(assembly)
        # The skin of a solid answers the dimension of the solid, so a face
        # reference is resolved as a boundary rather than as an element set.
        self.assertEqual(entities.get(meshtools.get_femmesh_group_name(imp, "Solid1")), 3)
        self.assertEqual(entities.get(meshtools.get_femmesh_group_name(imp, "Face1")), 3)
        self.assertEqual(entities.get("Solid1"), 3)
        self.assertEqual(entities.get("Face1"), 3)

    def test_an_unknown_reference_leaves_the_group_data_empty(self):
        """A partial answer would leave an element set short without saying so."""
        from femmesh import meshtools
        from femtools import solveassembly

        leg, _, _ = self._leg_analysis()
        table, geometry, _ = self._table_analysis(mesh_group=True, native=True)
        imp, _ = self._add_import(table, leg, "Leg1")
        self.document.recompute()

        mesh = solveassembly.build(table).FemMesh
        self.assertEqual(
            meshtools.get_femmesh_groupdata_sets_by_refs(
                mesh, [(imp, ["Solid1"]), (geometry, ["Solid9"])], "Volume"
            ),
            (),
        )

    def test_a_reference_on_an_instance_names_only_its_own_nodes(self):
        """
        Parts that touch share the surface a reference names but no nodes of
        it. A geometric search hands back the nodes of every part along that
        surface, which ties a part to itself and buries the solver in
        zero-coefficient warnings; the group of the instance answers with the
        nodes of that instance alone.
        """
        from femmesh import meshtools
        from femtools import solveassembly

        leg, _, _ = self._leg_analysis()
        table, geometry, _ = self._table_analysis(mesh_group=True, native=True)
        # No offset, so both parts occupy the same place and any search that
        # goes by position alone cannot tell one from the other.
        imp, _ = self._add_import(table, leg, "Leg1")
        self.document.recompute()

        mesh = solveassembly.build(table).FemMesh
        imported = meshtools.get_femnodes_by_refs_group_data(mesh, [(imp, ["Face1"])])
        native = meshtools.get_femnodes_by_refs_group_data(mesh, [(geometry, ["Face1"])])

        self.assertEqual(len(imported), 3)
        self.assertEqual(len(native), 3)
        self.assertFalse(set(imported) & set(native))

    def test_material_element_sets_come_from_group_data(self):
        """
        The element counts of the fast path have to add up over native and
        imported materials alike, or every set is searched for geometrically.
        """
        from femmesh import meshtools
        from femtools import membertools, solveassembly

        leg, _, _, _, _ = self._leg_analysis_with_members(with_members=True)
        table, geometry, _ = self._table_analysis(mesh_group=True, native=True)
        table_material = ObjectsFem.makeMaterialSolid(self.document, "TableMaterial")
        table_material.References = [(geometry, ["Solid1"])]
        table.addObject(table_material)
        self._add_import(table, leg, "Leg1", vector=FreeCAD.Vector(0, 0, 20))
        self.document.recompute()

        mesh = solveassembly.build(table).FemMesh
        materials = membertools.AnalysisMember(table).mats_linear
        self.assertEqual(len(materials), 2)
        self.assertTrue(meshtools.get_femelement_sets_from_group_data(mesh, materials))
        self.assertEqual(sum(len(m["FEMElements"]) for m in materials), mesh.VolumeCount)

    # -- what reaches an instance, and what does not -------------------------

    def _touched(self):
        return sorted(o.Name for o in self.document.Objects if "Touched" in o.State)

    def test_showing_and_hiding_in_the_source_asks_for_no_recompute(self):
        """
        A group is told when a member is shown or hidden, and used to pass that
        on as a change of its own. Every instance of the analysis then had to be
        drawn again, which for a mesh of any size is a wait for something that
        is only a scene graph switch.
        """
        leg, geom, mesh_group = self._leg_analysis()
        table, _, _ = self._table_analysis()
        imp, _ = self._add_import(table, leg, "Leg1")
        self.document.recompute()
        self.assertEqual(self._touched(), [])

        before = imp.SourceRevision
        for obj in (geom.Group[0], mesh_group.Group[0], geom, mesh_group, leg):
            obj.Visibility = not obj.Visibility
        self.assertEqual(self._touched(), [], "showing or hiding is not a change to recompute")

        self.document.recompute()
        self.assertEqual(imp.SourceRevision, before, "the instance was drawn again for nothing")

    def test_a_changed_source_reaches_every_instance_of_it(self):
        leg, _, _ = self._leg_analysis()
        table, _, _ = self._table_analysis()
        first, _ = self._add_import(table, leg, "Leg1")
        second, _ = self._add_import(table, leg, "Leg2", vector=FreeCAD.Vector(0, 0, 20))
        self.document.recompute()

        before = (first.SourceRevision, second.SourceRevision)
        part = self.document.getObject("LegPart")
        part.Shape = _box().scaled(2.0, FreeCAD.Vector())
        self.document.recompute()

        self.assertNotEqual(first.SourceRevision, before[0])
        self.assertNotEqual(second.SourceRevision, before[1])

    def test_a_change_at_the_bottom_of_a_chain_reaches_the_top(self):
        """
        The link that carries this runs to the source analysis, not to the
        geometry and mesh it holds, so an instance nested inside that analysis
        is on the way like everything else it keeps.
        """
        leg, _, _ = self._leg_analysis()
        side = ObjectsFem.makeAnalysis(self.document, "Side")
        ObjectsFem.makeGeometryGroup(self.document, "SideGeometry")
        side.addObject(self.document.getObject("SideGeometry"))
        inner, _ = self._add_import(side, leg, "LegInSide")
        table, _, _ = self._table_analysis()
        outer, _ = self._add_import(table, side, "SideInTable")
        self.document.recompute()

        before = (inner.SourceRevision, outer.SourceRevision)
        part = self.document.getObject("LegPart")
        part.Shape = _box().scaled(2.0, FreeCAD.Vector())
        self.document.recompute()

        self.assertNotEqual(inner.SourceRevision, before[0])
        self.assertNotEqual(outer.SourceRevision, before[1], "the outer instance draws Leg too")
