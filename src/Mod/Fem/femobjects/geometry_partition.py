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

__title__ = "FreeCAD FEM geometry partition"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import FreeCAD
import Part

import BOPTools.SplitAPI as SplitAPI

from .geometry_base import GeometryBase
from . import base_fempythonobject

_PropHelper = base_fempythonobject._PropHelper

METHOD_PLANE_3P = "Plane by 3 points"
METHOD_PLANE_REF = "Plane by reference"
METHOD_EXTEND_FACE = "Extend face"
METHOD_EDGE_PARAM = "Edge parameter"
METHOD_SHORTEST_PATH = "Shortest path"

PARTITION_METHODS = (
    METHOD_PLANE_3P,
    METHOD_PLANE_REF,
    METHOD_EXTEND_FACE,
    METHOD_EDGE_PARAM,
    METHOD_SHORTEST_PATH,
)


def _sub_shape_type(subname):
    if not subname:
        return None
    for prefix, stype in (
        ("Solid", "Solid"),
        ("Shell", "Shell"),
        ("Face", "Face"),
        ("Edge", "Edge"),
        ("Vertex", "Vertex"),
    ):
        if subname.startswith(prefix):
            return stype
    return None


def target_types(elements):
    """Return the set of shape types referenced by Elements, or empty if all."""
    types = set()
    for link in elements:
        if not link[1]:
            continue
        for sub in link[1]:
            stype = _sub_shape_type(sub)
            if stype:
                types.add(stype)
    return types


def target_count(elements):
    """Number of picked sub-elements, which is not the number of links."""
    return sum(len(link[1]) for link in elements if link[1])


def method_available(method, elements):
    """Whether method can run with the given target selection."""
    types = target_types(elements)
    if method == METHOD_EDGE_PARAM:
        return bool(types) and types == {"Edge"}
    if method == METHOD_SHORTEST_PATH:
        return types == {"Face"} and target_count(elements) == 1
    return True


def first_available_method(elements, preferred=None):
    if preferred and method_available(preferred, elements):
        return preferred
    for method in PARTITION_METHODS:
        if method_available(method, elements):
            return method
    return PARTITION_METHODS[0]


def _resolve_elements(base_obj, elements):
    """
    Target shapes named by Elements.

    A name that no longer resolves is an error rather than a shape to skip:
    dropping it silently leaves an empty target list, which then means "cut
    everything" and quietly partitions far more than was asked for.
    """
    shapes = []
    for link in elements:
        if link[0] != base_obj:
            raise ValueError("Partition targets must belong to the input geometry")
        for sub in link[1]:
            try:
                shape = base_obj.getSubObject(sub)
            except Exception:
                shape = None
            if shape is None or shape.isNull():
                raise ValueError(f"Target '{sub}' is no longer part of the input geometry")
            shapes.append(shape)
    return shapes


def _plane_size(bbox):
    span = max(bbox.XLength, bbox.YLength, bbox.ZLength, 1.0)
    return span * 4.0


def _in_plane_axis(normal, u_hint=None):
    """A unit vector perpendicular to normal, following u_hint where possible."""
    if u_hint is not None:
        u_dir = FreeCAD.Vector(u_hint)
        u_dir = u_dir - normal * u_dir.dot(normal)
        if u_dir.Length > 1e-9:
            u_dir.normalize()
            return u_dir
    for seed in (
        FreeCAD.Vector(1, 0, 0),
        FreeCAD.Vector(0, 1, 0),
        FreeCAD.Vector(0, 0, 1),
    ):
        u_dir = normal.cross(seed)
        if u_dir.Length > 1e-9:
            u_dir.normalize()
            return u_dir
    raise ValueError("Cannot build a cutting plane for this direction")


def _square_plane(center, normal, size, u_hint=None):
    """
    Square tool face of the given size, centred on center.

    Part.makePlane anchors the face at a corner, so the centre has to be
    shifted by half the diagonal or the tool only covers one quadrant of the
    intended cut.
    """
    normal = FreeCAD.Vector(normal)
    if normal.Length < 1e-9:
        raise ValueError("Cutting plane needs a non-zero normal")
    normal.normalize()
    u_dir = _in_plane_axis(normal, u_hint)
    v_dir = normal.cross(u_dir)
    corner = center - (u_dir + v_dir) * (size / 2.0)
    return Part.makePlane(size, size, corner, normal, u_dir)


def _plane_from_axes(origin, normal, u_dir, bbox):
    """
    Tool plane through origin, sized and centred on bbox.

    The finite tool face has to straddle the shape that is being cut, so it is
    centred on the projection of the shape centre, not on the reference point,
    which may sit far outside.
    """
    normal = FreeCAD.Vector(normal)
    if normal.Length < 1e-9:
        raise ValueError("Cutting plane needs a non-zero normal")
    normal.normalize()
    center = FreeCAD.Vector(bbox.Center)
    center = center - normal * center.sub(FreeCAD.Vector(origin)).dot(normal)
    return _square_plane(center, normal, _plane_size(bbox), u_dir)


def _expand_vertex_links(base_obj, links):
    """Expand PropertyLinkSubList entries to one vertex per link."""
    expanded = []
    for link in links:
        if link[0] != base_obj:
            raise ValueError("Partition points must belong to the input geometry")
        subs = link[1] if isinstance(link[1], (list, tuple)) else (link[1],)
        for sub in subs:
            if sub:
                expanded.append((link[0], (sub,)))
    return expanded


def _vertex_point(base_obj, link):
    if link[0] != base_obj:
        raise ValueError("Partition points must belong to the input geometry")
    if len(link[1]) != 1:
        raise ValueError("Each point pick must be a single vertex")
    vertex = base_obj.getSubObject(link[1][0])
    if vertex is None or vertex.isNull() or vertex.ShapeType != "Vertex":
        raise ValueError("Point picks must be vertices of the input geometry")
    return vertex.Point


def _tool_plane_from_points(base_obj, points, bbox):
    point_links = _expand_vertex_links(base_obj, points)
    if len(point_links) != 3:
        raise ValueError("Plane by 3 points needs exactly three vertex picks")
    p1 = _vertex_point(base_obj, point_links[0])
    p2 = _vertex_point(base_obj, point_links[1])
    p3 = _vertex_point(base_obj, point_links[2])
    v1 = p2.sub(p1)
    v2 = p3.sub(p1)
    normal = v1.cross(v2)
    if normal.Length < 1e-9:
        raise ValueError("The three points must not be collinear")
    normal.normalize()
    return _plane_from_axes(p1, normal, v1.normalize(), bbox)


def _tool_plane_from_reference(tool, bbox):
    """
    Tool plane from an external datum plane, sketch or planar face.

    The tool is always sized from bbox, the shape being cut. Sizing it from the
    reference is wrong in both directions: a datum plane reports a practically
    infinite bounding box, a small reference face one that does not reach.
    """
    if tool is None or tool[0] is None:
        raise ValueError("Plane by reference needs a datum plane, planar face or sketch")
    obj = tool[0]
    subs = tool[1] if isinstance(tool[1], (list, tuple)) else (tool[1],)
    sub = subs[0] if subs else ""
    if obj.isDerivedFrom("Part::DatumPlane") or obj.isDerivedFrom("Sketcher::SketchObject"):
        pl = obj.Placement
        normal = pl.Rotation.multVec(FreeCAD.Vector(0, 0, 1))
        u_dir = pl.Rotation.multVec(FreeCAD.Vector(1, 0, 0))
        return _plane_from_axes(pl.Base, normal, u_dir, bbox)
    if sub.startswith("Face"):
        face = obj.getSubObject(sub)
        if face is None or face.isNull() or face.ShapeType != "Face":
            raise ValueError("Plane by reference needs a datum plane, planar face or sketch")
        surf = face.Surface
        if not isinstance(surf, Part.Plane):
            raise ValueError("Reference face must be planar")
        return _plane_from_axes(surf.Position, surf.Axis, None, bbox)
    raise ValueError("Plane by reference needs a datum plane, planar face or sketch")


def _extended_face_tool(base_obj, tool, bbox):
    if tool is None or tool[0] != base_obj or not tool[1]:
        raise ValueError("Extend face needs a face of the input geometry")
    subs = tool[1] if isinstance(tool[1], (list, tuple)) else (tool[1],)
    sub = subs[0] if subs else ""
    if not sub.startswith("Face"):
        raise ValueError("Extend face needs a face of the input geometry")
    face = base_obj.getSubObject(sub)
    if face is None or face.isNull() or face.ShapeType != "Face":
        raise ValueError("Extend face needs a face of the input geometry")
    surf = face.Surface
    # A planar face becomes the same tool as any other plane, which keeps the
    # sizing and centring in one place.
    if isinstance(surf, Part.Plane):
        return _plane_from_axes(surf.Position, surf.Axis, None, bbox)
    umin, umax, vmin, vmax = face.ParameterRange
    du = max((umax - umin) * 2.0, 1.0)
    dv = max((vmax - vmin) * 2.0, 1.0)
    extended = surf.toShape(umin - du, umax + du, vmin - dv, vmax + dv)
    if extended.isNull():
        raise ValueError(f"Cannot extend {sub} over its surface")
    return extended


def _shortest_path_tool(base_obj, points, face_link):
    if face_link[0] != base_obj or len(face_link[1]) != 1:
        raise ValueError("Shortest path needs one face target on the input geometry")
    face = base_obj.getSubObject(face_link[1][0])
    if face is None or face.ShapeType != "Face":
        raise ValueError("Shortest path needs one face target on the input geometry")
    point_links = _expand_vertex_links(base_obj, points)
    if len(point_links) != 2:
        raise ValueError("Shortest path needs two vertex picks on the face")
    p1 = _vertex_point(base_obj, point_links[0])
    p2 = _vertex_point(base_obj, point_links[1])
    tol = max(face.BoundBox.DiagonalLength * 1e-6, 1e-7)
    for point in (p1, p2):
        if face.distToShape(Part.Vertex(point))[0] > tol:
            raise ValueError("Shortest path points must lie on the target face")
    u1, v1 = face.Surface.parameter(p1)
    u2, v2 = face.Surface.parameter(p2)
    line = Part.Geom2d.Line2dSegment(
        FreeCAD.Base.Vector2d(u1, v1),
        FreeCAD.Base.Vector2d(u2, v2),
    )
    return line.toShape(face.Surface)


def _shape_members(shape):
    """
    The parts a shape is built from, with compound nesting resolved.

    Every import step wraps what it contributes in a compound of its own, so the
    input of a step further down the chain is a compound of compounds. Reading
    only the direct children would find those wrappers instead of the solids
    inside them, which leaves a targeted solid impossible to match and makes
    "no selection" mean the wrappers rather than the solids they hold.
    """
    if shape.ShapeType != "Compound":
        return [shape]
    members = []
    for child in shape.childShapes():
        members.extend(_shape_members(child))
    return members


def _default_targets(base_shape):
    """
    What "no targets selected" means: every element of the input.

    Solids take precedence so that a compound mixing solids with free faces
    partitions the solids, which is what the mesher cares about, rather than
    mixing solid and sub-element cuts in one step.
    """
    members = _shape_members(base_shape)
    solids = [member for member in members if member.ShapeType == "Solid"]
    return solids if solids else members


def _tool_face(tool_shape):
    if tool_shape.ShapeType == "Face":
        return tool_shape
    faces = tool_shape.Faces
    if not faces:
        raise ValueError("Partition tool must provide a face")
    return faces[0]


def _plane_placement(face):
    """Placement with local X along the plane normal, or None if not planar."""
    surf = face.Surface
    if not isinstance(surf, Part.Plane):
        return None
    normal = FreeCAD.Vector(surf.Axis)
    if normal.Length < 1e-9:
        return None
    rot = FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), normal)
    return FreeCAD.Placement(surf.Position, rot)


def _measure(shape):
    """Volume, area or length of a shape, whichever describes it."""
    if shape.isNull():
        return 0.0
    if shape.Solids:
        return shape.Volume
    if shape.Faces:
        return shape.Area
    return shape.Length


def _solid_pieces_by_plane(element, placement):
    """
    The pieces a plane cuts a solid into, or [] if it does not cut it.

    generalFuse against a plane face leaves the solid in one piece, so the two
    halves are cut out with boolean-common against half-space boxes built in
    the tool plane's local frame, where the cut is the local YZ plane.
    """
    local = element.copy()
    local.transformShape(placement.inverse().toMatrix())
    bb = local.BoundBox
    pad = max(bb.DiagonalLength, 1.0)
    # The cut is at local x=0, which may lie outside the element; clamping keeps
    # both boxes non-degenerate instead of asking for a negative length.
    low = min(bb.XMin, 0.0) - pad
    high = max(bb.XMax, 0.0) + pad
    origin_y = bb.YMin - pad
    origin_z = bb.ZMin - pad
    width = bb.YLength + 2 * pad
    height = bb.ZLength + 2 * pad
    neg = Part.makeBox(-low, width, height, FreeCAD.Vector(low, origin_y, origin_z))
    pos = Part.makeBox(high, width, height, FreeCAD.Vector(0, origin_y, origin_z))

    pieces = []
    for half in (neg, pos):
        piece = local.common(half)
        if piece.isNull() or not piece.Solids:
            continue
        piece.transformShape(placement.toMatrix())
        pieces.append(piece)
    return pieces if len(pieces) > 1 else []


def _solid_pieces_by_slice(element, tool_shape):
    """Pieces of a solid cut by a tool that is not a plane."""
    splitted = SplitAPI.slice(element, [tool_shape], mode="Standard")
    if splitted.isNull() or len(splitted.Solids) < 2:
        return []
    return list(splitted.Solids)


def _split_solids(base_shape, targets, tool_shape):
    """
    Replace every target solid by its pieces, rebuilding the shape once.

    Splitting one solid at a time rebuilds the whole shape, which invalidates
    the sub-shapes the remaining targets point at; those cuts are then either
    skipped or applied on top of a solid that is still there, duplicating it.
    """
    placement = _plane_placement(_tool_face(tool_shape))
    rebuilt = []
    split_any = False
    matched = 0
    for child in _shape_members(base_shape):
        if child.ShapeType == "Solid" and any(child.isSame(target) for target in targets):
            matched += 1
            if placement is not None:
                pieces = _solid_pieces_by_plane(child, placement)
            else:
                pieces = _solid_pieces_by_slice(child, tool_shape)
            if pieces:
                rebuilt.extend(pieces)
                split_any = True
                continue
        rebuilt.append(child)

    if not matched:
        # Distinct from a tool that misses: the picks do not name a solid of the
        # input at all, so silently doing nothing would hide a broken selection.
        raise ValueError("None of the selected solids are part of the input geometry")
    if not split_any:
        # The tool misses every target, so there is nothing to separate.
        return base_shape
    if len(rebuilt) == 1:
        return rebuilt[0]
    # generalFuse glues the coincident faces at the cut so the mesher sees a
    # conformal interface instead of two solids that merely touch.
    return rebuilt[0].generalFuse(rebuilt[1:])[0]


def _split_sub_elements(base_shape, targets, tool_shape):
    """
    Imprint the tool on face or edge targets in a single replaceShape call.

    replaceShape drops an element instead of replacing it when the pieces do
    not fit, which silently deletes geometry, so the measure is checked after.
    """
    pairs = []
    for element in targets:
        splitted = SplitAPI.slice(element, [tool_shape], mode="Standard")
        if splitted.isNull():
            raise ValueError("Partition tool produced an empty result")
        pairs.append((element, splitted))
    if not pairs:
        return base_shape

    result = base_shape.replaceShape(pairs)
    if result.isNull():
        raise ValueError("Partition left an empty shape")
    if _measure(result) < _measure(base_shape) - max(_measure(base_shape) * 1e-6, 1e-9):
        raise ValueError(
            "Partition would delete geometry; the tool does not cut the targets cleanly"
        )
    return result


def _edge_parameter_tool(edge, parameter):
    """Plane cutting an edge at a fraction of its length."""
    # The trimmed edge range, not the range of the underlying curve, which for
    # a line is unbounded and puts the split point anywhere.
    u = edge.FirstParameter + parameter * (edge.LastParameter - edge.FirstParameter)
    point = edge.valueAt(u)
    tangent = edge.tangentAt(u)
    if isinstance(tangent, tuple):
        tangent = tangent[0]
    tangent = FreeCAD.Vector(tangent)
    if tangent.Length < 1e-9:
        raise ValueError("Cannot split edge at the chosen parameter")
    # The cutting plane has to be perpendicular to the edge, so its normal is
    # the tangent; a plane containing the tangent never cuts the edge.
    return _square_plane(point, tangent, max(edge.BoundBox.DiagonalLength, 1.0) * 4.0)


def _split_edges(base_shape, edges, parameter):
    """Each edge gets its own tool, but they are all imprinted in one rebuild."""
    pairs = []
    for edge in edges:
        tool = _edge_parameter_tool(edge, parameter)
        splitted = SplitAPI.slice(edge, [tool], mode="Standard")
        if splitted.isNull():
            raise ValueError("Cannot split edge at the chosen parameter")
        pairs.append((edge, splitted))
    result = base_shape.replaceShape(pairs)
    if result.isNull():
        raise ValueError("Partition left an empty shape")
    return result


def _point_pick_count(base_obj, points):
    try:
        return len(_expand_vertex_links(base_obj, points))
    except ValueError:
        return 0


def _unconfigured(obj, method):
    """
    Whether the step still lacks the picks its method needs.

    A step that was just added has nothing configured. Failing then would blank
    the chain result the moment the step appears, so the input is handed
    through until the method has what it needs. A configuration that is present
    but wrong is still an error.
    """
    if method == METHOD_PLANE_3P:
        return _point_pick_count(obj.Base, obj.Points) < 3
    if method == METHOD_SHORTEST_PATH:
        return _point_pick_count(obj.Base, obj.Points) < 2
    if method in (METHOD_PLANE_REF, METHOD_EXTEND_FACE):
        return obj.Tool is None or obj.Tool[0] is None
    return False


def _checked(base_shape, result):
    """
    Guard the one invariant every partition has: it only adds cuts.

    Volume, area and length must come out unchanged. Boolean and rebuild steps
    can drop or duplicate pieces without reporting an error, so this is the
    last line of defence against a chain that silently continues on damaged
    geometry.
    """
    if result is None or result.isNull():
        raise ValueError("Partition produced an empty shape")
    before = _measure(base_shape)
    after = _measure(result)
    if abs(after - before) > max(before * 1e-6, 1e-9):
        raise ValueError(
            f"Partition changed the size of the geometry: {before:.6g} before, "
            f"{after:.6g} after. This is a partition bug, please report it."
        )
    return result


class GeometryPartition(GeometryBase):
    """Partition the input geometry with a plane, extended face or edge split."""

    Type = "Fem::GeometryPartition"

    def __init__(self, obj):
        super().__init__(obj)
        self.setup_properties(obj)

    def _get_properties(self):
        prop = [
            _PropHelper(
                type="App::PropertyEnumeration",
                name="Method",
                group="Geometry",
                doc="How the cutting tool is defined",
                value=list(PARTITION_METHODS),
            ),
            _PropHelper(
                type="App::PropertyLinkSubList",
                name="Elements",
                group="Geometry",
                doc="Elements to partition; empty means the whole input",
                value=None,
            ),
            _PropHelper(
                type="App::PropertyLinkSubList",
                name="Points",
                group="Geometry",
                doc="Vertex picks on the input geometry",
                value=None,
            ),
            _PropHelper(
                type="App::PropertyLinkSubGlobal",
                name="Tool",
                group="Geometry",
                doc="External plane reference or input face to extend",
                value=None,
            ),
            _PropHelper(
                type="App::PropertyFloatConstraint",
                name="Parameter",
                group="Geometry",
                doc="Parameter along target edges for Edge parameter (0=start, 1=end)",
                value=(0.5, 0.0, 1.0, 0.01),
            ),
        ]
        return super()._get_properties() + prop

    def execute(self, obj):
        base_obj = obj.Base
        if not base_obj or base_obj.Shape.isNull():
            raise ValueError("No input geometry to partition")

        method = obj.Method
        elements = obj.Elements
        if not method_available(method, elements):
            raise ValueError(f"Method '{method}' is not valid for the selected targets")

        if _unconfigured(obj, method):
            obj.Shape = base_obj.Shape
            return

        base_shape = base_obj.Shape
        element_shapes = _resolve_elements(base_obj, elements)
        if not element_shapes:
            element_shapes = _default_targets(base_shape)

        if method == METHOD_EDGE_PARAM:
            edges = [s for s in element_shapes if s.ShapeType == "Edge"]
            if len(edges) != len(element_shapes):
                raise ValueError("Edge parameter needs edge targets only")
            obj.Shape = _checked(base_shape, _split_edges(base_shape, edges, obj.Parameter))
            return

        bbox = base_shape.BoundBox
        if method == METHOD_PLANE_3P:
            tool_shape = _tool_plane_from_points(base_obj, obj.Points, bbox)
        elif method == METHOD_PLANE_REF:
            tool_shape = _tool_plane_from_reference(obj.Tool, bbox)
        elif method == METHOD_EXTEND_FACE:
            tool_shape = _extended_face_tool(base_obj, obj.Tool, bbox)
        elif method == METHOD_SHORTEST_PATH:
            if target_count(elements) != 1:
                raise ValueError("Shortest path needs exactly one face target")
            tool_shape = _shortest_path_tool(base_obj, obj.Points, elements[0])
        else:
            raise ValueError(f"Unknown partition method '{method}'")

        solids = [shape for shape in element_shapes if shape.ShapeType == "Solid"]
        sub_elements = [shape for shape in element_shapes if shape.ShapeType != "Solid"]
        if solids and sub_elements:
            # Cutting a solid rebuilds the shape and invalidates the sub-element
            # picks, so the two kinds have to be done in separate steps.
            raise ValueError(
                "Select either solids or faces and edges as targets, not both. "
                "Use a second partition step for the other kind."
            )

        if solids:
            result = _split_solids(base_shape, solids, tool_shape)
        else:
            result = _split_sub_elements(base_shape, sub_elements, tool_shape)

        obj.Shape = _checked(base_shape, result)
