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

import collections

import FreeCAD
import Part

import BOPTools.SplitAPI as SplitAPI

from . import geometry_base
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

# How a cutting tool is shown while a partition step is edited. Mode is kept
# separate from the Part shape so later methods can draw differently without
# changing the panel wiring.
PartitionToolPreview = collections.namedtuple("PartitionToolPreview", "mode shape")

TOOL_MODE_PLANE = "plane"
TOOL_MODE_EXTENDED_FACE = "extended_face"
TOOL_MODE_PATH = "path"
TOOL_MODE_EDGE_PLANE = "edge_plane"


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


def _leaf_sub_shape_type(sub):
    """Shape kind of the leaf element in a possibly nested sub-name."""
    return _sub_shape_type(sub.rsplit(".", 1)[-1]) if sub else None


def _link_sub(link):
    """Object and first sub-name from a PropertyLinkSub value."""
    if link is None or link[0] is None:
        return None, ""
    subs = link[1] if isinstance(link[1], (list, tuple)) else (link[1],)
    sub = subs[0] if subs else ""
    return link[0], sub or ""


def _resolve_sub_object(obj, sub, shape_type):
    """
    Sub-shape named by a reference, including nested import paths.

    Import picks keep paths such as Inner.Vertex3; only the leaf names the
    element, and getSubObject has to be called with the full path.
    """
    if _leaf_sub_shape_type(sub) != shape_type:
        return None
    shape = obj.getSubObject(sub)
    if shape is None or shape.isNull() or shape.ShapeType != shape_type:
        if obj.isDerivedFrom("Fem::FemAnalysisImport"):
            try:
                placed = obj.placedSubShape(sub)
            except Exception:
                placed = None
            if placed is not None and not placed.isNull() and placed.ShapeType == shape_type:
                shape = placed
    if shape is None or shape.isNull() or shape.ShapeType != shape_type:
        return None
    return shape


def _resolve_face(obj, sub):
    """Face named by a sub-element reference."""
    return _resolve_sub_object(obj, sub, "Face")


def _resolve_vertex(obj, sub):
    """Vertex named by a sub-element reference."""
    return _resolve_sub_object(obj, sub, "Vertex")


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
    """
    Side length of a square cutting face large enough to span the input.

    Twice the longest box edge covers the shape's projection onto any plane
    through its centre with margin; more than that is only visual noise in the
    preview.
    """
    span = max(bbox.XLength, bbox.YLength, bbox.ZLength, 1.0)
    return span * 2.0


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


def _expand_vertex_links(links):
    """Expand PropertyLinkSubList entries to one vertex per link."""
    expanded = []
    for link in links:
        if link[0] is None:
            raise ValueError("Partition points need a vertex reference")
        subs = link[1] if isinstance(link[1], (list, tuple)) else (link[1],)
        for sub in subs:
            if sub:
                expanded.append((link[0], (sub,)))
    return expanded


def _vertex_point(link):
    obj = link[0]
    if obj is None:
        raise ValueError("Partition points need a vertex reference")
    if len(link[1]) != 1:
        raise ValueError("Each point pick must be a single vertex")
    sub = link[1][0]
    vertex = _resolve_vertex(obj, sub)
    if vertex is None:
        raise ValueError("Point picks must be vertices")
    return vertex.Point


def _tool_plane_from_points(points, bbox):
    point_links = _expand_vertex_links(points)
    if len(point_links) != 3:
        raise ValueError("Plane by 3 points needs exactly three vertex picks")
    p1 = _vertex_point(point_links[0])
    p2 = _vertex_point(point_links[1])
    p3 = _vertex_point(point_links[2])
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
    face = _resolve_face(obj, sub)
    if face is not None:
        surf = face.Surface
        if not isinstance(surf, Part.Plane):
            raise ValueError("Reference face must be planar")
        return _plane_from_axes(surf.Position, surf.Axis, None, bbox)
    raise ValueError("Plane by reference needs a datum plane, planar face or sketch")


def _extended_face_tool(tool, bbox):
    """
    Tool face from a picked reference, which may sit on the input or on an import.

    Like plane by reference, the tool is sized from bbox, the shape being cut.
    """
    obj, sub = _link_sub(tool)
    if obj is None or not sub:
        raise ValueError("Extend face needs a face reference")
    face = _resolve_face(obj, sub)
    if face is None:
        raise ValueError("Extend face needs a face reference")
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
    face = _resolve_face(base_obj, face_link[1][0])
    if face is None:
        raise ValueError("Shortest path needs one face target on the input geometry")
    point_links = _expand_vertex_links(points)
    if len(point_links) != 2:
        raise ValueError("Shortest path needs two vertex picks on the face")
    p1 = _vertex_point(point_links[0])
    p2 = _vertex_point(point_links[1])
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


def _connected_groups(members):
    """
    The members grouped into the components they form, in input order.

    Two shapes are in one component when they share topology, which is what
    makes them a single part of the geometry. Shapes that merely touch, the
    coincident faces of two separate imports for example, share nothing and stay
    apart. Sharing a vertex is enough, and it is what tells shared topology
    apart from coincidence, so that is the test.
    """
    parent = list(range(len(members)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owner = {}
    for index, member in enumerate(members):
        for vertex in member.Vertexes:
            first = owner.setdefault(hash(vertex), index)
            low, high = sorted((root(index), root(first)))
            if low != high:
                parent[high] = low

    groups = {}
    for index, member in enumerate(members):
        groups.setdefault(root(index), []).append(member)
    return list(groups.values())


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


MEASURE_NAMES = ("volume", "area", "length")


def _measure(shape):
    """
    Volume of the solids, area of the loose faces, length of the loose edges.

    Three numbers rather than one, because an analysis geometry can hold all
    three kinds at once and one of them cannot stand for the others. Part's
    own Volume over such a compound is not the volume of its solids either:
    a face that bounds nothing still enters the integral, so a solid of 500
    beside a stray face reads as 485.7 — a size no partition can preserve.

    Faces that bound a solid and edges that bound a face are left out. Those
    are what a cut adds to: splitting a solid raises its face count, and the
    invariant is about what the cut must not consume.
    """
    if shape.isNull():
        return (0.0, 0.0, 0.0)
    volume = sum(solid.Volume for solid in shape.Solids)
    bounding = {face.hashCode() for solid in shape.Solids for face in solid.Faces}
    area = sum(face.Area for face in shape.Faces if face.hashCode() not in bounding)
    bounding = {edge.hashCode() for face in shape.Faces for edge in face.Edges}
    length = sum(edge.Length for edge in shape.Edges if edge.hashCode() not in bounding)
    return (volume, area, length)


def _measure_tolerance(value):
    return max(abs(value) * 1e-6, 1e-9)


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
    Replace every target solid by its pieces, one component at a time.

    All targets are cut in a single rebuild: splitting one solid at a time
    rebuilds the whole shape, which invalidates the sub-shapes the remaining
    targets point at.

    The pieces of a cut have to be glued for the mesher to see a conformal
    interface instead of two solids that merely touch, and gluing takes the rest
    of the component with it, so that the topology the component already shared
    survives the rebuild. A component the tool does not cut is handed through
    untouched: its faces may well be coincident with the cut ones, and a fuse
    reaching across would weld two separate parts of the geometry into one.
    """
    placement = _plane_placement(_tool_face(tool_shape))
    rebuilt = []
    split_any = False
    matched = 0
    for group in _connected_groups(_shape_members(base_shape)):
        shapes = []
        cut_here = False
        for child in group:
            if child.ShapeType == "Solid" and any(child.isSame(target) for target in targets):
                matched += 1
                if placement is not None:
                    pieces = _solid_pieces_by_plane(child, placement)
                else:
                    pieces = _solid_pieces_by_slice(child, tool_shape)
                if pieces:
                    shapes.extend(pieces)
                    cut_here = True
                    continue
            shapes.append(child)

        if cut_here:
            # A cut always yields at least two pieces, so there is something to
            # glue whenever it happened.
            split_any = True
            rebuilt.append(shapes[0].generalFuse(shapes[1:])[0])
        else:
            rebuilt.extend(shapes)

    if not matched:
        # Distinct from a tool that misses: the picks do not name a solid of the
        # input at all, so silently doing nothing would hide a broken selection.
        raise ValueError("None of the selected solids are part of the input geometry")
    if not split_any:
        # The tool misses every target, so there is nothing to separate.
        return base_shape
    if len(rebuilt) == 1:
        return rebuilt[0]
    return Part.makeCompound(rebuilt)


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
    if any(
        now < was - _measure_tolerance(was)
        for was, now in zip(_measure(base_shape), _measure(result))
    ):
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


def _point_pick_count(points):
    try:
        return len(_expand_vertex_links(points))
    except ValueError:
        return 0


def _unconfigured_for(method, points, tool):
    """
    Whether method still lacks the picks it needs.

    Used by the edit preview without touching the document object.
    """
    if method == METHOD_PLANE_3P:
        return _point_pick_count(points) < 3
    if method == METHOD_SHORTEST_PATH:
        return _point_pick_count(points) < 2
    if method in (METHOD_PLANE_REF, METHOD_EXTEND_FACE):
        return tool is None or tool[0] is None
    return False


def _unconfigured(obj, method):
    """
    Whether the step still lacks the picks its method needs.

    A step that was just added has nothing configured. Failing then would blank
    the chain result the moment the step appears, so the input is handed
    through until the method has what it needs. A configuration that is present
    but wrong is still an error.
    """
    return _unconfigured_for(method, obj.Points, obj.Tool)


def _tool_shape(base_obj, base_shape, method, elements, *, points, tool, parameter):
    """
    The cutting tool for method, or raise if the configuration is wrong.

    Shared by execute() and the edit preview so what the user sees is what the
    step will cut with.
    """
    if method == METHOD_EDGE_PARAM:
        element_shapes = _resolve_elements(base_obj, elements)
        if not element_shapes:
            element_shapes = _default_targets(base_shape)
        edges = [s for s in element_shapes if s.ShapeType == "Edge"]
        if len(edges) != len(element_shapes):
            raise ValueError("Edge parameter needs edge targets only")
        if not edges:
            raise ValueError("Edge parameter needs at least one edge target")
        tools = [_edge_parameter_tool(edge, parameter) for edge in edges]
        if len(tools) == 1:
            return TOOL_MODE_EDGE_PLANE, tools[0]
        return TOOL_MODE_EDGE_PLANE, Part.makeCompound(tools)

    bbox = base_shape.BoundBox
    if method == METHOD_PLANE_3P:
        return TOOL_MODE_PLANE, _tool_plane_from_points(points, bbox)
    if method == METHOD_PLANE_REF:
        return TOOL_MODE_PLANE, _tool_plane_from_reference(tool, bbox)
    if method == METHOD_EXTEND_FACE:
        return TOOL_MODE_EXTENDED_FACE, _extended_face_tool(tool, bbox)
    if method == METHOD_SHORTEST_PATH:
        if target_count(elements) != 1:
            raise ValueError("Shortest path needs exactly one face target")
        return TOOL_MODE_PATH, _shortest_path_tool(base_obj, points, elements[0])
    raise ValueError(f"Unknown partition method '{method}'")


def build_tool_preview_config(
    base_obj,
    method,
    elements,
    *,
    points=(),
    tool=None,
    parameter=0.5,
):
    """
    Cutting tool to show while the partition panel is open, or None.

    Builds from panel state without writing the partition object or recomputing
    the document.
    """
    if base_obj is None or base_obj.Shape.isNull():
        return None
    elements = elements or []
    if not method_available(method, elements):
        return None
    if _unconfigured_for(method, points, tool):
        return None
    try:
        mode, shape = _tool_shape(
            base_obj,
            base_obj.Shape,
            method,
            elements,
            points=points,
            tool=tool,
            parameter=parameter,
        )
    except ValueError:
        return None
    if shape is None or shape.isNull():
        return None
    return PartitionToolPreview(mode, shape)


def build_tool_preview(obj):
    """
    Cutting tool to show from a partition object's stored properties.

    Returns None when the method is still unfinished or the picks are invalid,
    so the panel can drop the overlay without reporting an error on every
    keystroke of an incomplete selection.
    """
    base_obj = getattr(obj, "Base", None)
    if base_obj is None:
        return None
    return build_tool_preview_config(
        base_obj,
        obj.Method,
        obj.Elements,
        points=obj.Points,
        tool=obj.Tool,
        parameter=obj.Parameter,
    )


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
    for name, was, now in zip(MEASURE_NAMES, _measure(base_shape), _measure(result)):
        if abs(now - was) > _measure_tolerance(was):
            raise ValueError(
                f"Partition changed the {name} of the geometry: {was:.6g} before, "
                f"{now:.6g} after. This is a partition bug, please report it."
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
                doc="Vertex picks for the cutting tool",
                value=None,
            ),
            _PropHelper(
                type="App::PropertyLinkSubGlobal",
                name="Tool",
                group="Geometry",
                doc="External plane reference, import face, or input face to extend",
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
        """
        Redo the partition, or pass on the result that is still the right one.

        A step is executed for anything at all that happens to a dependency,
        and almost none of it is a new input. Doing the work anyway would cost
        a full boolean on every recompute of the CAD model the analysis was
        built from, which is exactly what the deliberate update is meant to
        spare the user; should_rebuild() is where that is decided.
        """
        if not geometry_base.should_rebuild(self, obj):
            geometry_base.note_built(self, obj)
            return

        self._rebuild(obj)
        geometry_base.note_built(self, obj)

    def _rebuild(self, obj):
        base_obj = obj.Base
        if not base_obj or base_obj.Shape.isNull():
            raise ValueError("No input geometry to partition")

        method = obj.Method
        elements = obj.Elements
        if not method_available(method, elements):
            raise ValueError(f"Method '{method}' is not valid for the selected targets")

        if _unconfigured(obj, method):
            # A step that has not been given its tool yet hands its input on
            # unchanged, which is not a new geometry for anything downstream.
            geometry_base.assign_shape(obj, base_obj.Shape)
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

        _, tool_shape = _tool_shape(
            base_obj,
            base_shape,
            method,
            elements,
            points=obj.Points,
            tool=obj.Tool,
            parameter=obj.Parameter,
        )

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
