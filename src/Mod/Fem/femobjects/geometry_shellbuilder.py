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

__title__ = "FreeCAD FEM shell builder geometry object"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import collections

import FreeCAD
import Part

from . import geometry_base
from .geometry_base import GeometryBase
from . import base_fempythonobject

_PropHelper = base_fempythonobject._PropHelper

METHOD_SKIN = "Skin offset"
METHOD_MIDSURFACE = "Midsurface"

SHELL_METHODS = (METHOD_SKIN, METHOD_MIDSURFACE)

SIDE_OUTER = "Outer"
SIDE_INNER = "Inner"

SHELL_SIDES = (SIDE_OUTER, SIDE_INNER)

# How anti-parallel two face normals must be before the faces can bound one
# wall. A wall is allowed to be a little out of parallel - the draft angle of a
# moulded part is the usual reason - and 0.995 is about eight degrees, which
# covers draft without letting a chamfer pair with the wall it chamfers.
FACING_LIMIT = -0.995

# Where across a face its distance to the partner is sampled, as fractions of
# the parameter range in each direction. They reach close to the edges on
# purpose: a rounded corner is at its thinnest where it meets the flats, and a
# grid that only looks at the middle reported a wall varying by a fifth as
# varying by a thirtieth. Samples that land off the face are dropped, so
# reaching for the edge costs nothing on a face that does not fill its range.
SAMPLE_FRACTIONS = (0.02, 0.25, 0.5, 0.75, 0.98)

# How much more material the sheets of a solid may account for than the solid
# held before the step says so. Over-counting comes from walls that meet: both
# sheets run into the corner and claim it, and until the sheets are trimmed
# against each other that is expected rather than wrong.
COVERAGE_TOLERANCE = 0.05

# How far a mid-surface may reach past its own wall to find the wall it meets,
# as a multiple of the thickest wall being built. Every mid-surface is built
# halfway across its own wall, so where two walls meet the two surfaces stop
# short of one another and never cross - the web of a beam ends at the face of
# the flange, half a thickness before the flange's own surface. Reaching that
# far is the least that closes the joint; the reach has to clear a fillet in
# the root as well, and twice the thickness covers both. Growth is clipped to
# the material afterwards, so reaching too far costs time and nothing else.
JUNCTION_REACH = 2.0


# A wall of a solid: the two faces bounding it, which of them lies towards the
# outside of the body, how far apart they are, and how much that distance
# varies across them. The variation is carried because it is what the tolerance
# was judged against, and a reader of the wall has as much right to it as the
# test that let the wall through.
Wall = collections.namedtuple("Wall", "outer inner thickness spread")
Wall.__new__.__defaults__ = (0.0,)

# What a wall contributes to the result: the face to emit, the shell thickness
# it carries, and where the material sits relative to that face.
Sheet = collections.namedtuple("Sheet", "face thickness offset")

# A pair that bounds material but was not taken, and what stopped it. These are
# the ones worth reporting: the faces do face each other across the body, so
# something the user can change - the bound, the tolerance - is all that stands
# between them and a wall.
NearMiss = collections.namedtuple("NearMiss", "outer inner thickness spread reason")

NEAR_MISS_THICK = "thicker than the bound"
NEAR_MISS_VARIES = "varies across the wall"

# How far past the bound a pair may be and still be worth mentioning. The two
# ends of a length of tube face each other across the whole of it and bound
# material the entire way, so they are a pair by every test here - and reporting
# them as a wall the bound only just missed would be nonsense. A near miss is
# one a nudge of the bound would reach.
NEAR_MISS_FACTOR = 3.0


def sample_point(face):
    """
    A point that really lies on the face, and the outward normal there.

    The middle of the parameter range is the obvious sample and it is wrong for
    any face that is not a rectangle in its own parameter space: on the end cap
    of a tube it lands in the hollow, on a face with a hole it can land in the
    hole. The point is then on the surface but not on the face, and every test
    built from it - which way the partner lies, whether material is between
    them - answers about somewhere that is not part of the body. So the centre
    of mass is projected onto the surface and only accepted once the face
    agrees it is inside, with the tessellation as the fallback because a
    triangle centroid lies on the face by construction.

    normalAt already accounts for the orientation of the face. Flipping it
    again by Orientation - the idiom that belongs to normals taken from the
    surface - inverts half the faces of a solid, after which pairing quietly
    finds nothing at all.
    """
    try:
        u, v = face.Surface.parameter(face.CenterOfMass)
        if _on_the_face(face, u, v):
            return face.valueAt(u, v), face.normalAt(u, v)
    except Exception:
        pass

    try:
        nodes, triangles = face.tessellate(max(face.BoundBox.DiagonalLength / 10.0, 1e-3))
    except Exception:
        return None
    for triangle in triangles:
        centroid = (nodes[triangle[0]] + nodes[triangle[1]] + nodes[triangle[2]]) * (1.0 / 3.0)
        try:
            u, v = face.Surface.parameter(centroid)
        except Exception:
            continue
        if _on_the_face(face, u, v):
            return face.valueAt(u, v), face.normalAt(u, v)
    return None


def _sample_grid(face):
    """
    Points spread over a face with the normal at each, for testing whether a
    wall keeps its thickness.
    """
    u0, u1, v0, v1 = face.ParameterRange
    samples = []
    for fraction_u in SAMPLE_FRACTIONS:
        for fraction_v in SAMPLE_FRACTIONS:
            u = u0 + (u1 - u0) * fraction_u
            v = v0 + (v1 - v0) * fraction_v
            if _on_the_face(face, u, v):
                samples.append((face.valueAt(u, v), face.normalAt(u, v)))
    return samples


def _sampled_thickness(face_a, face_b, nominal):
    """
    How much the wall thickness varies across the pair, as a fraction of it.

    The distance is measured to the partner's surface rather than to the
    trimmed face on purpose: a partner is often cut into several faces by
    fillets or holes, and how thick the wall is should not depend on which
    piece of it happens to be opposite.

    A sample counts only when it found a foot on the partner's surface: the
    nearest point lies straight along the partner's normal there. A plane runs
    on forever and every sample finds its foot, so a sample past the end of
    the partner still reads the true distance and nothing changes on a flat
    wall - and a taper, whose foot is on the partner's plane but not along
    this face's normal, still reads its varying distance and is still
    refused. The surface of a swept flange stops where the flange does, and a
    sample past its end is clamped to that end: it lands on the edge of the
    partner at a slant, reading the distance to the edge rather than the
    thickness. On a bent beam that made every flange three times as thick as
    it was and varying by more than its own thickness, so not one of them was
    a wall.
    """
    samples = _sample_grid(face_a)
    if not samples:
        return nominal, 0.0
    distances = []
    for point, _ in samples:
        try:
            landed = face_b.Surface.projectPoint(point, "NearestPoint")
            _, normal, _, _, _ = _project(face_b, landed)
        except Exception:
            continue
        across = landed - point
        sideways = across - normal * across.dot(normal)
        if sideways.Length > 1e-4 * max(across.Length, 1.0):
            continue
        distances.append(across.Length)
    if not distances:
        return nominal, 0.0

    # The average is what the wall is worth as one number. Taking the value
    # where the faces happened to be sampled would put the thickness of a
    # rounded corner at its widest point, on the diagonal, which is neither
    # what the corner weighs nor what it resists with.
    average = sum(distances) / len(distances)
    return average, (max(distances) - min(distances)) / max(nominal, 1e-9)


def walls_of_solid(solid, max_thickness, tolerance, rejected=None):
    """
    The walls of a solid: face pairs with material between them.

    Three tests, cheapest first, and all three earn their place. The normals
    must point opposite ways or the faces do not bound one wall. The partner
    must lie behind the face rather than in front of it, which rejects the two
    inner faces of a hollow section staring at each other across the cavity.
    And material must actually lie between them, which is the only one of the
    three that rejects the two *outer* faces of that same section: travelling
    backwards from one of them does arrive at the other, through the hollow.

    A surviving pair is a wall only if its thickness holds across the face, so
    the separation is sampled and its spread compared against the tolerance,
    which is a fraction rather than a percentage.

    Pairs thrown out by either of those two numbers are appended to rejected,
    when a list is passed for them. They are the interesting near misses - a
    rounded corner whose inner fillet is not concentric with its outer one is
    one of these, too thick and too uneven at once - and the user has no way to
    tell them from faces that never paired at all unless they are reported. Both
    reasons have to be carried: which one it was decides which number to change.
    """
    faces = solid.Faces
    centre = solid.CenterOfMass
    samples = [sample_point(face) for face in faces]

    rejected = [] if rejected is None else rejected
    walls = []
    for i, face_a in enumerate(faces):
        if samples[i] is None:
            continue
        point_a, normal_a = samples[i]
        for j in range(i + 1, len(faces)):
            face_b = faces[j]
            if samples[j] is None:
                continue
            if type(face_a.Surface).__name__ != type(face_b.Surface).__name__:
                continue
            point_b, normal_b = samples[j]

            wall = _wall_between(solid, centre, face_a, samples[i], face_b, samples[j])
            if wall is None:
                continue

            # The bound is judged against what the wall is worth as one number,
            # so that a pair is not taken or refused on the strength of
            # wherever the two faces happened to be sampled.
            # Measured from the outer face inwards, always. Sampling from
            # whichever face came first in the loop makes the thickness of a
            # corner depend on which of its two arcs was reached first, and
            # they are of different lengths.
            average, spread = _sampled_thickness(wall.outer, wall.inner, wall.thickness)
            wall = Wall(wall.outer, wall.inner, average, spread)
            if average > max_thickness:
                if average <= max_thickness * NEAR_MISS_FACTOR:
                    rejected.append(
                        NearMiss(wall.outer, wall.inner, average, spread, NEAR_MISS_THICK)
                    )
                continue
            if spread > tolerance:
                rejected.append(
                    NearMiss(wall.outer, wall.inner, average, spread, NEAR_MISS_VARIES)
                )
                continue
            walls.append(wall)
    return walls


def _partner_sample(face, point):
    """
    Where a face is seen from a point, or None when the point looks past it.

    The point is dropped onto the face's surface and taken up again only if it
    landed on the face itself, so this cannot invent a partner out of a surface
    that carries on beyond the material.
    """
    try:
        u, v = face.Surface.parameter(point)
    except Exception:
        return None
    if not _on_the_face(face, u, v):
        return None
    return face.valueAt(u, v), face.normalAt(u, v)


def _wall_between(solid, centre, face_a, sample_a, face_b, sample_b, max_thickness=None):
    """
    The wall two faces bound, or None when they bound none.

    Everything but the thickness bound is a question about the geometry rather
    than about what the user is looking for, which is why a pair picked by hand
    runs through the same tests with the bound left off.

    The last of those tests - whether the body has material midway between the
    two faces - is far and away the most expensive thing this module does. On
    a bent beam it is asked ninety-odd times at about 70 ms a time, which is
    two thirds of the whole step, because the body is swept from B-splines and
    each answer is a ray cast against it. It is not Python's to fix: the time
    is inside OpenCASCADE, and the calls cannot be reduced, since a pair that
    reaches here has already passed the facing, direction, bound and
    projection tests, and surveying the thickness first to weed more out costs
    more than it saves.

    What would fix it is not asking the question from scratch every time.
    Part.Shape.isInside builds a BRepClass3d_SolidClassifier, performs one
    point and destroys it, and that classifier is meant to be loaded once and
    performed on many points: measured natively on this very beam, 25.6 ms a
    call rebuilt against 9.9 ms a call kept, so about two and a half times.
    Exposing it - Part.BRepClass3d.SolidClassifier, following the way
    Part.BRepOffsetAPI.MakeFilling is already exposed - would let this loop
    load one classifier per solid and keep it for the whole search.

    The same trap sits one dimension down. Face.isPartOfDomain, which
    _on_the_face uses, builds a BRepTopAdaptor_FClass2d per call for want of
    anywhere to keep it; that one is 0.030 ms rebuilt against 0.0004 ms kept.
    Smaller, but it is the same fix, and the two together are the whole of
    what a C++ binding would be worth here.
    """
    point_a, normal_a = sample_a
    point_b, normal_b = sample_b

    # Where the partner is seen from this face, rather than where the partner
    # happens to have been sampled. On two flats the two are the same thing. On
    # a pipe they are not: each face is sampled at its own place on the round,
    # the two places sit at different angles, and the normals there are not
    # anti-parallel however truly the two faces bound a wall. Looking straight
    # across from one sample settles it.
    #
    # Both ways round, and the squarer of the two is the one that measures the
    # wall - not merely the first that lands. A face cut short by an earlier
    # step has its centre off where the two surfaces are parallel, and looking
    # from there strikes the partner at a slant: on a corner of a section left
    # over from a first shell builder, that reads 30 degrees out and 7.86 mm
    # thick where looking from the whole face reads square and 9.66. Taking
    # whichever direction happened to be tried first made the answer depend on
    # nothing better than which face the search reached first, and the same
    # corner was found on one side of a profile and missed on the other.
    # Looking across comes first and the faces' own samples last, so that a
    # tie goes to a reading taken at one place on the wall. Two parallel flats
    # face each other exactly however they are sampled, and comparing their own
    # two samples - which sit wherever each face's middle happens to be - is
    # then deciding which face looks outwards by comparing points that are not
    # opposite one another.
    seen = []
    forward = _partner_sample(face_b, point_a)
    if forward is not None:
        seen.append((point_a, normal_a, forward[0], forward[1]))
    backward = _partner_sample(face_a, point_b)
    if backward is not None:
        seen.append((backward[0], backward[1], point_b, normal_b))
    seen.append((point_a, normal_a, point_b, normal_b))
    point_a, normal_a, point_b, normal_b = min(
        seen, key=lambda across: across[1].dot(across[3])
    )

    if normal_a.dot(normal_b) > FACING_LIMIT:
        return None
    along = (point_b - point_a).dot(normal_a)
    if along >= 0.0:
        return None
    thickness = abs(along)
    if thickness < 1e-7 or (max_thickness is not None and thickness > max_thickness):
        return None
    if not solid.isInside(point_a - normal_a * (thickness / 2.0), 1e-6, True):
        return None

    # Which face looks outwards decides what keeping the skin means later on.
    # Distance from the centre of mass is a crude test, but it is right for what
    # this is aimed at - the wall of a box or a tube - and it is stable: both
    # faces of one wall always come out the same way round, whichever of them is
    # examined first.
    if (point_a - centre).Length >= (point_b - centre).Length:
        return Wall(face_a, face_b, thickness)
    return Wall(face_b, face_a, thickness)


def wall_from_faces(solid, face_a, face_b):
    """
    The wall behind two faces a user paired by hand.

    No thickness bound and no test that the thickness holds across the pair:
    the bound says which walls to go looking for, and the spread rejects a
    taper the search cannot describe. Someone pointing at two faces has already
    decided both questions, so all that is left is whether the pair really does
    bound material - which is not theirs to overrule. The thickness is then the
    separation where the faces were sampled.
    """
    sample_a = sample_point(face_a)
    sample_b = sample_point(face_b)
    if sample_a is None or sample_b is None:
        return None
    wall = _wall_between(solid, solid.CenterOfMass, face_a, sample_a, face_b, sample_b)
    if wall is None:
        return None
    # From the outer face inwards, so that picking the two faces the other way
    # round describes the same wall and not a slightly different one.
    average, spread = _sampled_thickness(wall.outer, wall.inner, wall.thickness)
    return Wall(wall.outer, wall.inner, average, spread)


def _offset_plane(face, distance, normal):
    """A planar face moved along its own normal, which is exact."""
    moved = face.copy()
    moved.translate(normal * -distance)
    return moved


def _offset_cylinder(face, distance, point, normal):
    """
    A cylindrical face rebuilt at another radius.

    Offsetting the surface analytically instead of going through
    makeOffsetShape keeps the result exact and takes away the one way it could
    fail, which matters because every corner of an extruded profile is a
    cylinder and a profile that loses a corner is of no use. The sign follows
    from whether the face bulges away from its axis: on the outside of a corner
    the normal points away from the axis and moving inwards shrinks the radius,
    on the inside of one it is the other way about.
    """
    # The general offset first, because it keeps the outline. A corner of a
    # section is rarely the clean rectangle its parameter range describes: a
    # fillet in the root of a joint notches it, a mitre cuts it at an angle,
    # and rebuilding it from the range alone would fill all of that back in.
    # It is the same call that serves a free-form face, and it only refuses
    # when asked to close the offset into a solid, which it is not.
    rebuilt = _offset_general(face, distance)
    if rebuilt is not None and type(rebuilt.Surface).__name__ == "Cylinder":
        return rebuilt

    cylinder = face.Surface
    radial = point - cylinder.Center
    radial = radial - cylinder.Axis * radial.dot(cylinder.Axis)
    sign = -1.0 if normal.dot(radial) > 0 else 1.0

    radius = cylinder.Radius + sign * distance
    if radius <= 1e-7:
        return None
    offset = Part.Cylinder(cylinder)
    offset.Radius = radius
    u0, u1, v0, v1 = face.ParameterRange
    return offset.toShape(u0, u1, v0, v1)


def _offset_general(face, distance):
    """Anything else, through the general offset, which is free to refuse."""
    try:
        result = face.makeOffsetShape(-distance, 1e-7)
    except Exception:
        return None
    faces = result.Faces if not result.isNull() else []
    return faces[0] if len(faces) == 1 else None


def shared_faces(walls):
    """
    The faces that more than one of these walls is bounded by.

    Two walls really can share a face. The top of a beam is the outer face of
    the flange either side of the web, because the web divides the flange into
    two walls without dividing the face they are both under.
    """
    shared = []
    for index, wall in enumerate(walls):
        for face in (wall.outer, wall.inner):
            if any(
                face.isSame(other)
                for position, neighbour in enumerate(walls)
                if position != index
                for other in (neighbour.outer, neighbour.inner)
            ):
                shared.append(face)
    return shared


def _base_face_of(wall, ratio, shared=()):
    """
    The face a mid-surface is built from, how far it moves, and what it carries.

    The outer face, ordinarily: it is the face the whole step is oriented by,
    and building every sheet from the same side keeps the corners of a profile
    turning the way they were drawn.

    Not when another wall is bounded by that same face. Both walls would then be
    built from it and both would get the same sheet, one laid on the other,
    instead of half of it each - which is exactly what the two halves of a
    beam's flange are. The face that is theirs alone is the one to use.

    Building from the inner face turns the sheet around, because the two faces
    of a wall look at each other, so the distance to travel and the offset the
    sheet carries are both measured the other way about.
    """
    outer_is_shared = any(wall.outer.isSame(face) for face in shared)
    inner_is_shared = any(wall.inner.isSame(face) for face in shared)
    if outer_is_shared and not inner_is_shared:
        return wall.inner, wall.thickness * (1.0 - ratio), 0.5 - ratio
    return wall.outer, wall.thickness * ratio, ratio - 0.5


def sheet_for_wall(wall, method, ratio, side, shared=()):
    """
    The face a wall contributes, with the thickness and offset it carries.

    Skin offset hands back the wall face itself. That is not a cheaper route to
    where a ratio of zero would land: the face is reused rather than rebuilt,
    so the result is exact, nothing can fail, and the face keeps the identity
    that anything referring to it depends on. Where the material sits is then
    carried by the offset rather than by the position of the surface.

    Midsurface builds a new face between the two. That is what lets the sheets
    of neighbouring walls meet, and it is also what can fail.

    The offset is the fraction of the thickness from the emitted face to the
    middle of the wall, measured along that face's outward normal, so keeping
    the outer face gives -0.5: the material lies behind it.
    """
    if method == METHOD_SKIN:
        face = wall.outer if side == SIDE_OUTER else wall.inner
        return Sheet(face.copy(), wall.thickness, -0.5 if side == SIDE_OUTER else 0.5)

    source, distance, offset = _base_face_of(wall, ratio, shared)
    sample = sample_point(source)
    if sample is None:
        return None
    point, normal = sample

    kind = type(source.Surface).__name__
    if kind == "Plane":
        face = _offset_plane(source, distance, normal)
    elif kind == "Cylinder":
        face = _offset_cylinder(source, distance, point, normal)
    else:
        face = _offset_general(source, distance)

    if face is None or face.isNull():
        return None
    return Sheet(face, wall.thickness, offset)


def _side_of(sheet, point):
    """
    Which side of a sheet a point falls on, as a signed distance.

    None where the surface is of a kind this cannot answer for, and the caller
    then leaves that neighbour out of the reckoning rather than guessing.
    """
    surface = sheet.Surface
    kind = type(surface).__name__
    if kind == "Plane":
        return (point - surface.Position).dot(surface.Axis)
    if kind == "Cylinder":
        radial = point - surface.Center
        radial = radial - surface.Axis * radial.dot(surface.Axis)
        return radial.Length - surface.Radius
    return None


def _wall_contains(wall, point, tolerance):
    """
    Whether a point lies in the material of this wall.

    The wall is the space between its two faces, so a point belongs to it when
    it projects onto the outer face - which bounds it sideways - and sits no
    further behind that face than the thickness. Asking the geometry this way
    rather than building a solid for the wall keeps it exact for a cylinder,
    where a straight extrusion of the face would be the wrong shape entirely.
    """
    face = wall.outer
    try:
        u, v = face.Surface.parameter(point)
    except Exception:
        return False
    if not _on_the_face(face, u, v):
        return False

    projected = face.valueAt(u, v)
    inward = (point - projected).dot(face.normalAt(u, v))
    return -tolerance <= -inward <= wall.thickness + tolerance


def _face_normal(face):
    """The outward normal of a face, taken where the face certainly is."""
    sample = sample_point(face)
    if sample is not None:
        return sample[1]
    u, v = face.Surface.parameter(face.CenterOfMass)
    return face.normalAt(u, v)


def _plane_normal(face):
    """
    The normal of a planar face as its orientation means it.

    Not the axis of its surface: a face built from a surface may be turned
    round, and the pieces that are fused into it have to agree with it about
    which way is out or the fuse will not merge them.
    """
    normal = face.Surface.Axis
    return -normal if face.Orientation == "Reversed" else normal


def _material_beyond(solid, edge, outward, at, step):
    """
    Whether the body carries on past an edge of a mid-surface.

    This is the whole of the decision about where a sheet may grow, and it is
    asked of the solid rather than of the neighbouring walls on purpose. A wall
    ends at another wall through whatever the modeller put in the root of the
    joint - a fillet, a chamfer, a boss - and none of that is a wall itself, so
    a test that looked for a neighbouring sheet would find nothing there. The
    material does not care: at the mid-surface, just past the edge, it is either
    there or it is not, and where it is the sheet has a joint to reach.
    """
    return solid.isInside(edge.valueAt(at) + outward * step, 1e-7, False)


def _oriented(face, normal):
    """A copy of a face turned to agree with a normal, or the face as it is."""
    if _plane_normal(face).dot(normal) < 0:
        turned = face.copy()
        turned.reverse()
        return turned
    return face


def _merged_face(pieces, normal):
    """
    One face out of coplanar pieces, or a compound when they will not merge.

    removeSplitter only merges faces whose orientations agree, and the
    orientation a strip comes out of an extrusion with depends on which way its
    edge ran in the face it was taken from - which varies from edge to edge of
    the same face. Rather than reason about it, both readings are tried and the
    one that leaves fewer faces is kept; a single face means the growth really
    did become part of the sheet rather than being laid against it.
    """
    base, rest = pieces[0], pieces[1:]
    if not rest:
        return base
    best = None
    for flipped in (False, True):
        turned = []
        for piece in rest:
            # Only a plane can be turned by its axis. Pieces of a curved
            # surface are handed over as they came and the fuse is left to
            # sort them, which it can because they are the same surface.
            piece = piece if normal is None else _oriented(piece, normal)
            if flipped:
                piece = piece.copy()
                piece.reverse()
            turned.append(piece)
        try:
            fused = base.fuse(turned).removeSplitter()
        except Exception:
            continue
        if best is None or len(fused.Faces) < len(best.Faces):
            best = fused
        if len(fused.Faces) == 1:
            break
    return best if best is not None else Part.Compound(pieces)


def _project(face, point):
    """
    A point dropped onto a face's surface: where it lands, the outward normal
    there, how far in front of the surface it was, and where on the surface.

    This is the one question the trim asks of a surface it cannot name, so it
    is asked through the surface's own parametrisation rather than through a
    formula per kind. It raises rather than guessing when the surface cannot
    place the point at all.

    The parameters come back with the point because whether the landing is on
    the face is nearly always the next question, and asking it by parameter
    rather than by point is what makes it cheap - see _on_the_face.
    """
    u, v = face.Surface.parameter(point)
    landed = face.valueAt(u, v)
    normal = face.normalAt(u, v)
    return landed, normal, (point - landed).dot(normal), u, v


def _on_the_face(face, u, v):
    """
    Whether a point already placed on a face's surface lies on the face.

    isPartOfDomain asks the face's own boundary classifier about a parameter
    pair. Face.isInside answers the same question about a point, but has to
    find the parameters again and check the point really is on the surface,
    which on a free-form face is a projection: measured, 3.9 ms against
    0.12 ms, and this is asked hundreds of times for every wall surveyed. So
    it is only ever asked this way where the parameters are already in hand -
    where they are not, finding them costs as much as the old question did.
    """
    return face.isPartOfDomain(u, v)


def _edge_outward(face, edge, at):
    """
    Which way leaves the face at a point on an edge, and whether it is a seam.

    Along the edge crossed with the normal of the face gives the direction
    across it; which of the two it is depends on how the edge is oriented in
    this face, so it is settled by asking the face whether a step that way is
    still inside it.

    When both ways are inside, the edge is not a boundary of the material at
    all but the seam where a closed surface is cut open to be described - the
    line down the side of a pipe. There is nothing beyond a seam to grow into,
    and probing across one lands in the wall's own material, so it would report
    growth everywhere.
    """
    point = edge.valueAt(at)
    try:
        normal = _project(face, point)[1]
    except Exception:
        return None, False
    outward = edge.tangentAt(at).cross(normal)
    if outward.Length < 1e-9:
        return None, False
    outward.normalize()

    forward = face.isInside(point + outward * 1e-3, 1e-6, True)
    backward = face.isInside(point - outward * 1e-3, 1e-6, True)
    if forward and backward:
        return None, True
    return (-outward if forward else outward), False


def _growing_edges(face, solid, step):
    """
    The edges of a sheet the body carries on past, with the way out.

    Material beyond an edge is taken to mean a joint beyond it, and that is
    very nearly always so. It is not so for a wall that steps from one
    thickness to another - a tube 6.3 thick above and 5.65 below, sharing its
    inner face, is the case that shows it. Each section has material beyond the
    edge where they meet and both grow towards the other, but their
    mid-surfaces are cylinders about one axis a third of a millimetre apart:
    they never cross, so the trim finds no line to cut at, and each keeps the
    whole of its reach. The two overlap by the reach instead of meeting at the
    step. Nothing is lost by it and the result is sound - the material is
    claimed twice over that stretch, which is what a junction does anyway - but
    a step in thickness is not a junction and the sections should simply end at
    it, each on its own radius.

    Refusing to grow there needs one thing this cannot answer: which wall owns
    the material immediately beyond an edge. Three ways of asking were tried
    and each broke a case that works. Whether the neighbour is crossed within
    the reach turns "grows but falls short" into "does not grow", which is what
    a reach set too small is supposed to look like - an I-beam at a reach of 5
    with a 5.5 mm joint then built nothing. Whether it is crossed at any
    distance lets in surfaces that cross far away and have nothing to do with
    this edge, and a beam's flange overgrew by a quarter. Asking _wall_contains
    which wall holds the point beyond the edge fails where two walls share a
    face: the material past a flange half's web-side edge is reported as
    belonging to the other half, which is coplanar with it and so looks like a
    surface it can never meet, and the beam stopped growing altogether.

    What would answer it is the walls' own faces rather than a projection:
    which wall's two faces actually enclose the neighbourhood just past the
    edge. That is worth doing properly rather than fitting another predicate
    to the fixtures.
    """
    growing = {}
    for index, edge in enumerate(face.Edges):
        middle = (edge.FirstParameter + edge.LastParameter) / 2.0
        outward, seam = _edge_outward(face, edge, middle)
        if seam or outward is None:
            continue
        if _material_beyond(solid, edge, outward, middle, step):
            growing[index] = outward
    return growing


def _parameter_scale(face, along_u):
    """
    How far a step of one parameter unit carries across a surface.

    A cylinder's first parameter is an angle and its second a length, so a
    margin in millimetres means a different amount in each. Measuring it on the
    surface itself covers every analytic kind without a case for each, and
    getting it wrong is not subtle: taking a ten millimetre margin as ten
    radians sweeps the face round on top of itself.
    """
    u0, u1, v0, v1 = face.ParameterRange
    middle_u, middle_v = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    try:
        step = 1e-4
        here = face.Surface.value(middle_u, middle_v)
        there = (
            face.Surface.value(middle_u + step, middle_v)
            if along_u
            else face.Surface.value(middle_u, middle_v + step)
        )
        return max((there - here).Length / step, 1e-9)
    except Exception:
        return 1.0


def _tube_around(edge, radius):
    """A rod of the given radius following an edge, used to mask growth to it."""
    start = edge.valueAt(edge.FirstParameter)
    disc = Part.Face(Part.Wire([Part.makeCircle(radius, start, edge.tangentAt(edge.FirstParameter))]))
    tube = Part.Wire([edge]).makePipe(disc)
    if tube.ShapeType != "Solid" and tube.Faces:
        tube = Part.Solid(Part.Shell(tube.Faces))
    return tube


def _slab_of(face, normal, thickness):
    """A thin solid enclosing a planar face, for use as a mask."""
    lowered = face.copy()
    lowered.translate(normal * -thickness)
    return lowered.extrude(normal * (2.0 * thickness))


def _unified(mask):
    """
    A mask with its own seams taken out, so that it cannot stamp them on.

    The mask a sheet is cut out with is a union: the sheet's own footprint and
    a rod along each edge that has a joint beyond it. The union keeps the
    faces it was assembled from, and every one of them scores the sheet where
    it lands - a flat that should have four edges comes out with twelve, split
    at the reach of a rod, and a mesher can no longer lay a mapped grid on it.
    Merging the faces of the mask first costs one call and the sheet comes out
    with the outline the wall actually has.
    """
    try:
        tidy = mask.removeSplitter()
    except Exception:
        return mask
    return tidy if not tidy.isNull() and tidy.Solids else mask


def _grown_planar(base, solid, margin, step):
    """
    A planar sheet widened across every edge the body carries on past.

    Growing the whole face uniformly will not do: an edge with nothing beyond
    it is the end of the wall, and widening there puts a tab of material into
    the air that no trim can take back. So the decision is made edge by edge.

    Nor will laying a strip against each growing edge and fusing the lot: a
    fuse along a long free-form edge - the top of the web of a bent beam - is
    left as separate faces, and a sheet in pieces is no sheet. So no face is
    ever joined to another here. The body is cut by the sheet's plane, which
    gives the whole of its section in that plane as one face, and the section
    is then masked to what the sheet may have: its own footprint, a rod's
    reach along each growing edge, and the inside of any hole every edge of
    which has material beyond it - where something stands on the wall, and
    the wall runs on underneath. One intersection, one face out.
    """
    growing = _growing_edges(base, solid, step)
    if not growing:
        return base

    normal = _plane_normal(base)
    size = max(solid.BoundBox.DiagonalLength, base.BoundBox.DiagonalLength) * 2.0
    plane = Part.makePlane(size, size)
    plane.Placement = FreeCAD.Placement(
        FreeCAD.Vector(), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), normal)
    )
    # The centroid of a planar region lies in its plane even when it lies off
    # the face, so it will do to place the plane by.
    plane.translate(base.CenterOfMass - plane.CenterOfMass)
    try:
        section = plane.common(solid)
    except Exception:
        return base
    if section.isNull() or not section.Faces:
        return base

    masks = [_slab_of(base, normal, step)]
    for wire in base.Wires:
        if wire.isSame(base.OuterWire):
            continue
        indices = [
            index
            for index, edge in enumerate(base.Edges)
            if any(edge.isSame(other) for other in wire.Edges)
        ]
        if indices and all(index in growing for index in indices):
            try:
                masks.append(_slab_of(Part.Face(Part.Wire(wire.Edges)), normal, step))
            except Exception:
                pass
    for index in growing:
        try:
            masks.append(_tube_around(base.Edges[index], margin))
        except Exception:
            pass

    # Where two growing edges meet, the ground beyond their shared corner is
    # reached by neither rod: a rod stops at the end of its own edge, so the
    # square between the two of them is covered by nothing and the sheet comes
    # back notched - a flange running into an end plate lost the very corner
    # where its two joints meet, and the shell was left open exactly there.
    #
    # The filler is that square and nothing more: the two ways out, spanned.
    # Anything rounder - a ball at the corner, say - reaches in directions
    # neither edge grows towards, and a flange then runs on past the web it
    # should have stopped at.
    for first in growing:
        for second in growing:
            if second <= first:
                continue
            meeting = [
                one.Point
                for one in base.Edges[first].Vertexes
                for other in base.Edges[second].Vertexes
                if (one.Point - other.Point).Length < 1e-7
            ]
            here, there = growing[first], growing[second]
            if not meeting or abs(here.dot(there)) > 0.999:
                continue
            corner = meeting[0]
            try:
                square = Part.Face(
                    Part.makePolygon(
                        [
                            corner,
                            corner + here * margin,
                            corner + here * margin + there * margin,
                            corner + there * margin,
                            corner,
                        ]
                    )
                )
                masks.append(_slab_of(square, normal, step))
            except Exception:
                pass

    try:
        mask = masks[0] if len(masks) == 1 else _unified(masks[0].fuse(masks[1:]))
        grown = section.common(mask)
    except Exception:
        return base
    if grown.isNull() or not grown.Faces:
        return base
    return grown


def _grown_curved(base, solid, margin, step):
    """
    An analytic curved sheet widened only along the edges that have a joint.

    The parameter rectangle is let out by the margin, which is exact and cheap
    because the band beyond an arc is another piece of the same cylinder. On
    its own that grows the sheet everywhere at once, which is right for a clean
    rectangular patch and wrong for one notched by a fillet or cut off by a
    mitre: a corner of a section would gain material along its whole length in
    order to reach a rib at one end of it.

    So the extension is masked to the edges that actually have material beyond
    them, by intersecting it with a rod following each of those edges. What is
    left is on the same surface as the sheet, which is what lets it merge back
    into one face rather than being laid against it.

    A closed direction is never let out: going round a full circle again would
    put the surface on top of itself.
    """
    surface = base.Surface
    u0, u1, v0, v1 = base.ParameterRange

    growing = _growing_edges(base, solid, step)
    if not growing:
        return base

    across_u = margin / _parameter_scale(base, True)
    across_v = margin / _parameter_scale(base, False)
    if getattr(surface, "isUPeriodic", lambda: False)() and (u1 - u0) >= surface.UPeriod() - 1e-6:
        across_u = 0.0
    if getattr(surface, "isVPeriodic", lambda: False)() and (v1 - v0) >= surface.VPeriod() - 1e-6:
        across_v = 0.0

    try:
        wider = surface.toShape(u0 - across_u, u1 + across_u, v0 - across_v, v1 + across_v)
    except Exception:
        return base
    try:
        region = wider.common(solid)
    except Exception:
        return base
    if region.isNull() or not region.Faces:
        return base

    tubes = []
    for index in growing:
        try:
            tubes.append(_tube_around(base.Edges[index], margin))
        except Exception:
            pass
    if not tubes:
        return base
    try:
        reach = tubes[0] if len(tubes) == 1 else _unified(tubes[0].fuse(tubes[1:]))
        growth = region.common(reach)
    except Exception:
        return base

    pieces = [face for face in growth.Faces if face.Area > 1e-9]
    if not pieces:
        return base
    return _merged_face([base] + pieces, None)


def _grown_bands(base, solid, margin, step, samples=24):
    """
    Growth for a surface that cannot be let out: a band laid along each edge.

    A free-form wall is described by a surface that stops where the wall does.
    There is no way in Part to extend one - the offset surface a mid-surface of
    such a wall is made of returns nonsense when it is evaluated past its
    basis, and a boolean against it comes back either whole and invalid or
    empty. So nothing here asks the surface about anywhere it does not go.

    Instead the sheet is carried on from its edge by a band that leaves the
    edge along the surface, is straight after that, and is cut back to the
    body. Over the few millimetres of a joint the difference between that and
    the surface's own continuation is far below anything a mesh would show.

    The band stays a face of its own rather than becoming part of the sheet,
    because a ruled surface will not merge into an offset one. It is emitted as
    a sheet in its own right, carrying the same thickness, and from there it is
    trimmed, sewn and recorded like any other.

    All of this is a workaround for something Part does not expose, and it
    would go away if it did. OpenCASCADE can extend such a surface properly:
    converting it with GeomConvert::SurfaceToBSplineSurface and then calling
    GeomLib::ExtendSurfByLength gives a true continuation of the sheet on its
    own surface. Measured on the swept flanges of a bent beam, the conversion
    deviates from the offset surface by 4.7e-6 mm, the extension comes out
    valid, and the sheet then grows into both of its joints as one face -
    38607 mm2 becoming 48044 - instead of a base with two bands leaning on it.
    BRepLib::ExtendFace, which sounds like the same thing, is not: handed an
    offset surface it returns it unchanged.

    Nothing in FreeCAD binds ExtendSurfByLength. The natural home is a method
    on Part.BSplineSurface, beside increaseDegree and insertUKnot, which are
    the same shape of thing - the OCC call takes the handle by reference and
    replaces it, and a B-spline in gives a B-spline out, so mutating self is
    well defined. The route from a sheet is already there:
    OffsetSurface.toBSpline() and then extend. Two guards the binding would
    have to add, because OCC is silent about both: the continuity must be 1, 2
    or 3, and OCC quietly does nothing at all otherwise; and the surface must
    not be periodic in the direction being extended.

    With that, this function and the sheets-carry-bands handling that follows
    it - the origins taken per wall in trim_sheets, and the sibling reasoning
    that exists for bands - collapse into the same few lines the planar and
    cylindrical paths already use.
    """
    made = []
    for edge in base.Edges:
        middle = (edge.FirstParameter + edge.LastParameter) / 2.0
        outward, seam = _edge_outward(base, edge, middle)
        if seam or outward is None or edge.Length < step:
            continue
        if not _material_beyond(solid, edge, outward, middle, step):
            continue

        far = []
        span = edge.LastParameter - edge.FirstParameter
        for step_number in range(samples + 1):
            at = edge.FirstParameter + span * step_number / float(samples)
            point = edge.valueAt(at)
            try:
                normal = _project(base, point)[1]
            except Exception:
                far = []
                break
            across = edge.tangentAt(at).cross(normal)
            if across.Length < 1e-9:
                far = []
                break
            across.normalize()
            if across.dot(outward) < 0.0:
                across = -across
            far.append(point + across * margin)
        if not far:
            continue

        # Where the way out is the same all along the edge - a wall that is
        # straight across meeting a plate, which is nearly every joint - the
        # band is the edge swept that way, exactly. A ruled surface between the
        # edge and a curve interpolated through samples of it is only reached
        # for where the direction turns, because on a long free-form edge the
        # interpolation can fold the band on itself, and a boolean then leaves
        # nothing of it.
        directions = [
            (far[number] - edge.valueAt(edge.FirstParameter + span * number / float(samples)))
            for number in range(samples + 1)
        ]
        turning = max(
            (direction - directions[0]).Length for direction in directions
        ) / max(margin, 1e-9)
        try:
            if turning < 1e-3:
                band = edge.extrude(directions[0])
            else:
                curve = Part.BSplineCurve()
                curve.interpolate(far)
                band = Part.makeRuledSurface(edge, curve.toShape())
            clipped = band.common(solid)
        except Exception:
            continue
        made.extend(face for face in clipped.Faces if face.Area > 1e-9)
    return made


def grow_sheet(sheet, solid, margin):
    """
    Reach a sheet into the walls beside it, and cut it back to the material.

    Two mid-surfaces of walls that meet never cross. Each is built halfway
    across its own wall, so the web of a beam stops at the face of the flange
    while the flange's own surface is another half thickness past it: the two
    stand apart by exactly the gap the joint needs closed, and no amount of
    trimming - which only ever removes - will bring them together. Growing them
    until they overlap is what gives the trim something to cut, and after the
    cut they end on the same line.

    What makes this safe is that every kind of growth is cut from the body
    rather than added to the sheet: there is no material beyond a free edge, so
    growth that reached into thin air is never there to begin with, instead of
    having to be reasoned away. The intersection hands back one face per
    connected region, so the sheet comes back as a face and not as the handful
    of pieces that laying strips against it would give.
    """
    kind = type(sheet.face.Surface).__name__
    step = max(margin * 0.05, 1e-5)
    if kind == "Plane":
        mask = _grown_planar(sheet.face, solid, margin, step)
    elif kind == "Cylinder":
        mask = _grown_curved(sheet.face, solid, margin, step)
    else:
        # Nothing analytic to let out, so the sheet keeps its own extent and is
        # carried into the joints by bands beside it.
        return [sheet] + [
            Sheet(band, sheet.thickness, sheet.offset)
            for band in _grown_bands(sheet.face, solid, margin, step)
        ]

    region = mask
    if len(region.Faces) > 1:
        try:
            region = region.removeSplitter()
        except Exception:
            pass

    # The body's section in this plane is the whole of it, and what the widened
    # outline crossed somewhere else entirely is in there too, so the piece
    # that overlaps the sheet it grew from is the one that is its own.
    overlapping = []
    for face in region.Faces:
        try:
            shared = face.common(sheet.face).Area
        except Exception:
            shared = 0.0
        if shared > 1e-9:
            overlapping.append((shared, face))
    if not overlapping:
        return [sheet]
    overlapping.sort(key=lambda entry: -entry[0])
    grown = overlapping[0][1]

    # A boolean is free to hand the face back turned round, and the offset the
    # sheet carries is measured along its normal, so it is put back the way the
    # sheet it grew from was facing.
    if type(grown.Surface).__name__ == "Plane":
        grown = _oriented(grown, _plane_normal(sheet.face))
    return [Sheet(grown, sheet.thickness, sheet.offset)]


def _sheet_holds(sheet, point, tolerance=1e-6):
    """
    Whether a point lies in the material a sheet stands for.

    The sheet is the middle of its wall, so its material reaches half a
    thickness either side of it and no further sideways than the face itself.
    This is what tells a piece cut off inside a neighbour from a piece cut off
    somewhere else: the tools are whole surfaces and a plane does not stop at
    the wall it belongs to, so without this a far-away wall could reach across
    the body and cut a sheet it never touches.
    """
    surface = sheet.face.Surface
    kind = type(surface).__name__
    # An analytic surface says where the point lands by formula; where on the
    # surface that is has still to be asked for, which is cheap on a plane or
    # a cylinder and is what a free-form projection hands back for free.
    parameters = None
    if kind == "Plane":
        away = (point - surface.Position).dot(surface.Axis)
        if abs(away) > sheet.thickness / 2.0 + tolerance:
            return False
        projected = point - surface.Axis * away
    elif kind == "Cylinder":
        radial = point - surface.Center
        radial = radial - surface.Axis * radial.dot(surface.Axis)
        if radial.Length < tolerance:
            return False
        away = radial.Length - surface.Radius
        if abs(away) > sheet.thickness / 2.0 + tolerance:
            return False
        projected = point - radial * (away / radial.Length)
    else:
        # Anything else is asked through its own parametrisation. A swept or
        # lofted wall has no formula here, but it can still say where a point
        # lands on it and how far in front of it that point was, which is the
        # whole of the question - and the parameters it landed at, which saves
        # finding them again.
        try:
            projected, _, away, u, v = _project(sheet.face, point)
        except Exception:
            return False
        if abs(away) > sheet.thickness / 2.0 + tolerance:
            return False
        parameters = (u, v)

    if parameters is None:
        try:
            parameters = sheet.face.Surface.parameter(projected)
        except Exception:
            return False
    return _on_the_face(sheet.face, *parameters)


def _tangential(plane, cylinder):
    """Whether a plane runs along a cylinder and touches it."""
    if abs(plane.Axis.dot(cylinder.Axis)) > 1e-6:
        return False
    return abs(abs((cylinder.Center - plane.Position).dot(plane.Axis)) - cylinder.Radius) < 1e-4


def _radial_tool(plane, cylinder, first, second):
    """
    Where a flat and the round it runs into hand over to one another.

    Two tangential surfaces do not cross, so neither can cut the other and a
    corner of a section would be left overlapping the flat beside it. What does
    divide them is the plane through the axis of the round at right angles to
    the flat, which passes exactly through the line where the two touch.
    """
    normal = plane.Axis.cross(cylinder.Axis)
    if normal.Length < 1e-9:
        return None
    normal.normalize()
    size = max(first.BoundBox.DiagonalLength, second.BoundBox.DiagonalLength) * 2.0
    tool = Part.makePlane(size, size)
    tool.Placement = FreeCAD.Placement(
        FreeCAD.Vector(), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), normal)
    )
    tool.translate(cylinder.Center - tool.CenterOfMass)
    centre = cylinder.Center
    return tool, lambda point: (point - centre).dot(normal)


def _trim_tool(sheet, other):
    """
    What cuts one sheet where its neighbour ends, and which side is which.

    Usually the neighbour's own surface, extended as far as it needs to go. Two
    sheets on one surface have nothing to divide and are left to the pass that
    settles overlaps; a flat and a round that only touch are divided by the
    plane through the tangency instead.
    """
    face, neighbour = sheet.face, other.face
    if _surfaces_match(face, neighbour):
        return None

    kind, other_kind = type(face.Surface).__name__, type(neighbour.Surface).__name__
    if other_kind == "Plane":
        if kind == "Cylinder" and _tangential(neighbour.Surface, face.Surface):
            return _radial_tool(neighbour.Surface, face.Surface, face, neighbour)
        plane = neighbour.Surface
        return neighbour, lambda point: (point - plane.Position).dot(plane.Axis)

    if other_kind == "Cylinder":
        cylinder = neighbour.Surface
        if kind == "Plane" and _tangential(face.Surface, cylinder):
            return _radial_tool(face.Surface, cylinder, face, neighbour)

        def side(point, cylinder=cylinder):
            radial = point - cylinder.Center
            radial = radial - cylinder.Axis * radial.dot(cylinder.Axis)
            return radial.Length - cylinder.Radius

        return neighbour, side

    def side(point, neighbour=neighbour):
        # A surface with no formula of its own still divides space, and where
        # a point falls is settled by dropping it onto the surface. Off the end
        # of the surface the projection is meaningless, so a neighbour that
        # cannot place the point does not get a say rather than getting a wrong
        # one.
        try:
            return _project(neighbour, point)[2]
        except Exception:
            return 0.0

    return neighbour, side


def _walls_share_a_face(first, second):
    """Whether two walls are bounded by one and the same face."""
    return any(
        mine.isSame(theirs)
        for mine in (first.outer, first.inner)
        for theirs in (second.outer, second.inner)
    )


def _boxes_touch(first, second, tolerance=1e-4):
    """Whether two shapes are near enough that one could cut the other."""
    box = FreeCAD.BoundBox(first.BoundBox)
    box.enlarge(tolerance)
    return box.intersect(second.BoundBox)


def trim_sheets(pairs, tolerance=1e-6):
    """
    Cut every sheet back to the material its own wall owns.

    Where two walls meet, both mid-surfaces have been grown into the joint and
    both now claim the material there. Splitting each sheet against the others
    puts a cut exactly where the two surfaces cross, and the piece beyond that
    cut is the piece lying inside the neighbour's material - the neighbour's to
    represent, so this sheet drops it. Both survivors end on the crossing line,
    which is what makes them meet.

    A piece is only dropped when it is both past a neighbour and inside what
    something else already stands for. Past on its own is not enough: the tools
    are whole surfaces, so the plane of a stiffener halfway along a web reaches
    the far end of it, and a sheet would lose the half of itself that the
    stiffener never touches.

    A sheet that a neighbour crosses in the middle keeps both halves. That is a
    flange, which carries on past the web rather than being ended by it, and it
    shows as the sheet's own origin lying on the neighbour rather than to one
    side of it.
    """
    # Where each sheet stands is judged from its wall, not from itself. A wall
    # can contribute several sheets - its surface and the bands that carry it
    # into its joints - and a band lies almost wholly beyond the neighbour it
    # reaches for, so judged from its own middle it would keep the far half
    # and drop the half that is the joint. The wall's own surface is the first
    # sheet it contributes, and its middle is where the wall is.
    origins = []
    for wall, _ in pairs:
        origins.append(
            next(other.face.CenterOfMass for other_wall, other in pairs if other_wall is wall)
        )

    # Every sheet is split against every other in one go, and which pieces
    # came from which sheet is read off the map the fuse hands back. Splitting
    # each sheet on its own instead asks for a fuse per sheet, which on a bent
    # beam is fourteen of them and four times the work of one. What comes back
    # is finer than what a sheet's own tools would have cut - a sheet is now
    # parted by its siblings too - so the pieces that are kept are joined back
    # together afterwards.
    faces = [sheet.face for _, sheet in pairs]
    areas = [face.Area for face in faces]
    history = None
    if len(faces) > 1:
        try:
            _, history = faces[0].generalFuse(faces[1:], tolerance)
        except Exception:
            history = None

    trimmed = []
    for index, (wall, sheet) in enumerate(pairs):
        # A wall bounded by one of this wall's own faces lies on the same
        # surface as it does, or carries on from it tangentially, and can never
        # cut it across: slicing by a surface that only grazes the sheet leaves
        # shreds behind rather than pieces. Those walls have a say in what is
        # beyond a neighbour, below, but they are not tools.
        tools = []
        for position, (other_wall, other) in enumerate(pairs):
            if other_wall is wall or _walls_share_a_face(wall, other_wall):
                continue
            if not _boxes_touch(sheet.face, other.face):
                continue
            tool = _trim_tool(sheet, other)
            if tool is not None:
                # Which side of this tool the sheet's own middle falls on does
                # not depend on the piece being judged, and on a free-form
                # neighbour answering it is a projection, so it is answered
                # once for the sheet rather than once for every piece of it.
                tools.append((other, tool[0], tool[1], tool[1](origins[index])))

        # The sheets of the walls that lie on this one's own surface, or that
        # are bounded by one of the very same faces. A flange split in two by
        # the web running through it is the case: each half grows across the
        # web into ground the other half is already standing for, and since the
        # two are coplanar neither can cut the other. They are not tools, they
        # are the answer to who owns what is beyond the web. Sharing a face is
        # what says so - both halves are under the one top face - and it is
        # asked of the walls rather than the sheets because a band that grew
        # from a half is on no surface its sibling would recognise.
        siblings = [
            (other, origins[position])
            for position, (other_wall, other) in enumerate(pairs)
            if other_wall is not wall
            and (
                _walls_share_a_face(wall, other_wall)
                or _surfaces_match(sheet.face, other.face)
            )
        ]

        pieces = list(history[index]) if history else []
        if not pieces:
            pieces = [sheet.face]

        # A split along a free-form surface leaves slivers behind - shreds of
        # a hundredth of a square millimetre along the cut - and those are the
        # boolean's, not the wall's.
        slight = max(1e-4, areas[index] * 1e-6)
        pieces = [piece for piece in pieces if piece.Area > slight]

        kept = []
        for piece in pieces:
            sample = sample_point(piece)
            centre = sample[0] if sample is not None else piece.CenterOfMass
            if _beyond_a_neighbour(centre, tools, siblings, tolerance):
                continue
            kept.append(piece)

        # A sheet the trim took nothing from is the sheet it was. The pieces
        # are a partition of it, so putting them back would be arithmetic at
        # best - and on an offset surface it is not even that, because nothing
        # in Part will merge two pieces of one back into it.
        if len(kept) == len(pieces):
            trimmed.append((wall, sheet))
            continue
        for face in _rejoined(kept):
            trimmed.append((wall, Sheet(face, sheet.thickness, sheet.offset)))

    return trimmed


def _rejoined(pieces):
    """
    The kept pieces of one sheet, put back together where they will go.

    They are all pieces of one face, so anything still touching after the trim
    belongs to one face again; leaving them apart would hand the mesher a seam
    down the middle of a wall for no reason. Pieces that no longer touch stay
    apart, which is a wall the trim really did cut in two.
    """
    if len(pieces) < 2:
        return pieces
    try:
        joined = pieces[0].fuse(pieces[1:]).removeSplitter()
    except Exception:
        return pieces
    return joined.Faces if joined.Faces else pieces


def _beyond_a_neighbour(centre, tools, siblings, tolerance):
    """
    Whether a piece of a sheet lies past a neighbour on ground already spoken for.

    Asking only whether the piece sits inside the neighbour's wall reads the
    same on a corner and the opposite on a T: the web of a beam has to reach
    the middle of the flange, which is inside the flange the whole way, so that
    question would cut off the very piece the junction needs. Asking only
    whether it is past the neighbour cuts sheets that a distant wall's surface
    happens to sweep across. It has to be both.

    Beyond the neighbour, the piece may belong to the neighbour itself - the
    ordinary corner or T - or to a wall on this sheet's own surface that the
    neighbour divides it from, which is a flange either side of a web. The
    second is only allowed when that wall lies on the same side of the
    neighbour as the piece does, so that the one dropping the piece and the one
    keeping it are never the same two sheets looking at each other.
    """
    for other, _, side, there in tools:
        if abs(there) < tolerance:
            continue
        here = side(centre)
        if here * there >= 0.0:
            continue
        if _sheet_holds(other, centre):
            return True
        for sibling, sibling_origin in siblings:
            if side(sibling_origin) * here > 0.0 and _sheet_holds(sibling, centre):
                return True
    return False


def settle_overlaps(pairs, tolerance=1e-6):
    """
    Give material claimed twice on one surface to one of the sheets only.

    Two sheets on the same surface cannot trim each other - there is no
    crossing line between them - yet they can grow into the same place: the
    plate under a boss, or a plate a rib divides into two walls that each reach
    under the rib. The overlap is handed to the first of them and cut out of
    the second, so nothing is counted twice and the boundary between them comes
    out as one shared edge. A sheet the cut leaves nothing of was entirely
    inside its neighbour and is not emitted at all.
    """
    settled = list(pairs)
    for index in range(len(settled)):
        for position in range(index + 1, len(settled)):
            if settled[index] is None or settled[position] is None:
                continue
            first = settled[index][1].face
            second = settled[position][1].face
            # Boxes first: asking two free-form faces whether they share a
            # surface costs a distance computation, and most pairs are nowhere
            # near each other.
            if not _boxes_touch(first, second) or not _surfaces_match(first, second):
                continue
            try:
                if first.common(second).Area < tolerance:
                    continue
                remainder = second.cut(first)
            except Exception:
                continue
            if len(remainder.Faces) > 1:
                try:
                    remainder = remainder.removeSplitter()
                except Exception:
                    pass
            wall, sheet = settled[position]
            if not remainder.Faces or remainder.Area < tolerance:
                settled[position] = None
            elif len(remainder.Faces) == 1:
                settled[position] = (
                    wall,
                    Sheet(remainder.Faces[0], sheet.thickness, sheet.offset),
                )
            else:
                settled[position] = (
                    wall,
                    Sheet(Part.Compound(remainder.Faces), sheet.thickness, sheet.offset),
                )
    return [entry for entry in settled if entry is not None]


def _pieces_by_plane(solid, point, normal):
    """
    The two halves a plane cuts a solid into, or [] when it does not cut it.

    A boolean common against a half-space box does the cutting, because fusing
    a solid against a plane face leaves it in one piece - the same reason the
    partition step builds its half-spaces rather than using a face as a tool.
    """
    box = solid.BoundBox
    pad = max(box.DiagonalLength, 1.0)
    frame = FreeCAD.Placement(point, FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), normal))

    pieces = []
    for base in (FreeCAD.Vector(-pad, -pad, 0), FreeCAD.Vector(-pad, -pad, -pad)):
        half = Part.makeBox(2 * pad, 2 * pad, pad, base)
        half.Placement = frame.multiply(half.Placement)
        piece = solid.common(half)
        if piece.isNull() or not piece.Solids:
            continue
        # One side of a cut is not one solid. A plane through a tube leaves two
        # separate pieces on the same side of it, and keeping only the first
        # would quietly drop the other - which is the body losing material.
        pieces.extend(piece.Solids)
    return pieces if len(pieces) > 1 else []


CUT_AT_OUTER = "outer"
CUT_AT_INNER = "inner"
CUT_AT_MIDDLE = "middle"


def cut_place_of(method, side):
    """
    Which of a wall's two ends the body is cut at when the wall is freed.

    A wall ends twice over: its outer face stops at one line and its inner face
    at another, and on a corner whose fillets are not concentric those lines are
    four millimetres apart. The cut goes where the emitted face ends, so the
    face covers what was taken - the outer skin at the outer line, the inner
    skin at the inner one, and a mid-surface midway between the two.
    """
    if method == METHOD_MIDSURFACE:
        # Halfway between the two ends is where a mid-surface looks as though
        # it should stop, and it is not where it does. A mid-surface is the
        # outer face moved along its own normal, and moving a face that way
        # slides its edge along the cut plane rather than off it, so the
        # mid-surface ends where the outer face does whatever the ratio - and
        # so does a corner arc refitted to its neighbours, which keeps the
        # angles it was built with.
        return CUT_AT_OUTER
    return CUT_AT_INNER if side == SIDE_INNER else CUT_AT_OUTER


def cut_face_of(wall, method, side):
    """
    The face whose edge the body is cut at when this wall is freed.

    The material a sheet stands for is the sheet swept through its thickness,
    so the cut has to follow the face that is emitted. A profile whose corner
    fillets are not concentric has an outer face and an inner face of different
    extents - the outer flat runs from tangent to tangent of the outer fillets,
    the inner one from tangent to tangent of the inner ones - and cutting at the
    outer edge while emitting the inner face leaves the corner arc hanging over
    the solid at one end and the flat stopping short of it at the other.

    A mid-surface is the outer face moved along its own normal, and the edge
    moves with it inside the same plane, so the outer face answers for that too.

    Only a flat inner face is taken up on this. A corner's two arcs cover
    different angles, so cutting at the inner one frees a piece holding far more
    material than the wall stands for, and it is refused rather than have the
    difference disappear. The corner is left cut at its outer edge, where the
    inner arc still hangs over the solid by the width of the fillet mismatch -
    a real fault, and a smaller one than deleting the material would be.
    """
    if method == METHOD_SKIN and side == SIDE_INNER:
        if type(wall.inner.Surface).__name__ == "Plane":
            return wall.inner
    return wall.outer


def transition_planes(solid, wall, tolerance=1e-6, face=None, where=CUT_AT_OUTER):
    """
    Where a wall stops and the body carries on, as (point, normal) planes.

    A wall face ends either at the outside of the body or against more
    material, and only the second kind is a transition. Which one an edge is
    can be asked directly: step just past it, stay at the middle of the wall,
    and see whether that point is still inside the solid. On a flexure the two
    ends of the blade answer yes and its long sides answer no, which is exactly
    where the blade has to be cut out of the stubs.

    Only the outer boundary of the wall is considered. The cut is made with a
    plane, which reaches across the whole body, and a plane taken from the edge
    of a hole in the middle of a wall carves up everything else on its way -
    four of them around a boss standing on a plate leave nine pieces. A wall
    interrupted in its middle is not something this can free, so it is left to
    be reported instead.

    A straight edge gives a plane. A curved one cannot: the web of a bent beam
    ends against its flanges along a curve, and a plane through the middle of
    that curve cuts the beam at a slant somewhere in the bend, nowhere near
    the joint. What stands square to the wall along a curved edge is the edge
    itself swept along the wall's normal, and that is what is handed back for
    one - as the surface, since it is not a plane and cannot be named by a
    point and a normal.
    """
    face = face if face is not None else wall.outer
    # Half a thickness past the edge, not a whole one. What the wall runs into
    # is usually as thick as the wall itself, and a probe a whole thickness
    # out lands exactly on that neighbour's far surface - inside by a hair on
    # a flat beam, outside by a hair where the neighbour curves away, and the
    # web of a bent beam was found to end in thin air on three sides.
    step = min(wall.thickness / 2.0, face.BoundBox.DiagonalLength / 10.0)
    partners = _straight_edges(wall.inner)
    curved_partners = _curved_edges(wall.inner)

    planes = []
    for edge in face.OuterWire.Edges:
        middle = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
        try:
            u, v = face.Surface.parameter(middle)
            normal = face.normalAt(u, v)
            tangent = edge.tangentAt((edge.FirstParameter + edge.LastParameter) / 2.0)
        except Exception:
            continue

        outward = tangent.cross(normal)
        if outward.Length < 1e-9:
            continue
        outward.normalize()
        # tangent x normal can point either way along the face, so the side
        # that leaves the face is found by trying one and taking the other.
        if face.isInside(middle + outward * (step / 10.0), tolerance, True):
            outward = -outward

        probe = middle + outward * step - normal * (wall.thickness / 2.0)
        if not solid.isInside(probe, tolerance, True):
            continue

        # The cut stands square to the wall and slides along it to the end the
        # emitted face has. Square, because that is the face the shell will be
        # tied to and a slanted one serves it badly; and at the right end,
        # because a face that stops short of the cut leaves a strip of solid
        # beside the shell and one that runs past it lies on top of the solid.
        if type(edge.Curve).__name__ == "Line":
            planes.append((_cut_point(edge, middle, partners, where), outward))
            continue
        sweep = _swept_cut(solid, edge, normal, middle, curved_partners, where)
        if sweep is not None:
            planes.append(sweep)
    return planes


def _curved_edges(face):
    """The edges of a face's outer boundary that are not straight."""
    if face is None:
        return []
    try:
        wire = face.OuterWire
    except Exception:
        return []
    if wire is None:
        return []
    return [
        edge
        for edge in wire.Edges
        if type(edge.Curve).__name__ != "Line" and edge.Length > 1e-9
    ]


def _swept_cut(solid, edge, normal, middle, partners, where):
    """
    The surface square to a wall along one of its curved edges, or None.

    The edge is swept along the wall's normal far enough to pass right through
    the body either way. Where along the wall it goes is settled as for a
    plane: at the emitted face's own edge, at the far face's, or halfway
    between - the far face's edge being the one of its curved edges nearest to
    this one and much the same length, since the two run side by side.
    """
    shift = FreeCAD.Vector()
    if where != CUT_AT_OUTER and partners:
        nearest = None
        for other in partners:
            if abs(other.Length - edge.Length) > 0.5 * edge.Length:
                continue
            try:
                distance = edge.distToShape(other)[0]
            except Exception:
                continue
            if nearest is None or distance < nearest[0]:
                nearest = (distance, other)
        if nearest is not None:
            other = nearest[1]
            far = other.valueAt((other.FirstParameter + other.LastParameter) / 2.0)
            shift = far - middle
            if where == CUT_AT_MIDDLE:
                shift = shift * 0.5

    reach = max(solid.BoundBox.DiagonalLength, 1.0)
    try:
        start = edge.copy()
        start.translate(shift - normal * reach)
        return start.extrude(normal * (2.0 * reach))
    except Exception:
        return None


def _cut_point(edge, middle, partners, where):
    """Where along the wall the cut goes: at one face's end, or between them."""
    if where == CUT_AT_OUTER:
        return middle
    partner = _parallel_partner(edge, partners)
    if partner is None:
        return middle
    other = partner.valueAt((partner.FirstParameter + partner.LastParameter) / 2.0)
    if where == CUT_AT_INNER:
        return other
    return middle + (other - middle) * 0.5


def _straight_edges(face):
    """The straight edges of a face's outer boundary, which can span a plane."""
    if face is None:
        return []
    try:
        wire = face.OuterWire
    except Exception:
        return []
    if wire is None:
        return []
    return [
        edge
        for edge in wire.Edges
        if type(edge.Curve).__name__ == "Line" and edge.Length > 1e-9
    ]


def _parallel_partner(edge, partners):
    """
    The far face's edge at the same end of the wall as this one.

    Only an edge running the same way can be it. A rectangular face has short
    edges at its ends that are no further off than the long one opposite, and
    taking one of those would put the cut across the wall rather than at the end
    of it.
    """
    if type(edge.Curve).__name__ != "Line" or edge.Length <= 1e-9:
        return None
    along = edge.tangentAt((edge.FirstParameter + edge.LastParameter) / 2.0)

    candidates = []
    for other in partners:
        if other.Length <= 1e-9:
            continue
        direction = other.tangentAt((other.FirstParameter + other.LastParameter) / 2.0)
        if abs(abs(direction.dot(along)) - 1.0) > 1e-6:
            continue
        candidates.append(other)
    if not candidates:
        return None

    try:
        return min(candidates, key=lambda other: edge.distToShape(other)[0])
    except Exception:
        return None


def _split_at_transitions(solid, walls, where=CUT_AT_OUTER):
    """Cut a solid apart where its walls run into the rest of the body."""
    planes = []
    sweeps = []
    for wall in walls:
        for cut in transition_planes(solid, wall, where=where):
            if not isinstance(cut, tuple):
                sweeps.append(cut)
                continue
            # Two walls that meet share the plane between them, and each of
            # them asks for it. Cutting on it twice costs a boolean and gains
            # nothing.
            if not any(_same_plane(cut, existing) for existing in planes):
                planes.append(cut)
    if not planes and not sweeps:
        return []

    pieces = [solid]
    if sweeps:
        # A swept surface has no half-space to intersect with, so the body is
        # split by it as a tool instead - which a plane could be too, but the
        # half-spaces were there first and are proven.
        import BOPTools.SplitAPI as SplitAPI

        try:
            split = SplitAPI.slice(solid, sweeps, mode="Split")
            if not split.isNull() and len(split.Solids) > 1:
                pieces = list(split.Solids)
        except Exception:
            pass

    for point, normal in planes:
        cut = []
        for piece in pieces:
            # A plane that passes wide of a piece cannot divide it, and finding
            # that out from the bounding box costs nothing next to asking the
            # boolean.
            if not _plane_crosses(piece, point, normal):
                cut.append(piece)
                continue
            halves = _pieces_by_plane(piece, point, normal)
            cut.extend(halves if halves else [piece])
        pieces = cut
    return pieces if len(pieces) > 1 else []


def _same_plane(first, second, tolerance=1e-7):
    """Whether two (point, normal) pairs describe the same plane."""
    point, normal = first
    other_point, other_normal = second
    if abs(abs(normal.dot(other_normal)) - 1.0) > 1e-9:
        return False
    return abs((other_point - point).dot(normal)) < tolerance


def _plane_crosses(shape, point, normal, tolerance=1e-7):
    """Whether a plane passes through a shape's bounding box at all."""
    box = shape.BoundBox
    corners = [
        FreeCAD.Vector(x, y, z)
        for x in (box.XMin, box.XMax)
        for y in (box.YMin, box.YMax)
        for z in (box.ZMin, box.ZMax)
    ]
    distances = [(corner - point).dot(normal) for corner in corners]
    return min(distances) < -tolerance and max(distances) > tolerance


def solids_share_a_face(one, other):
    """
    Whether two solids are joined, rather than merely touching.

    A shared face is one face, in both of them: the modeller imprinted the
    interface, and a mesh laid on it is conforming across it. Two solids that
    only touch have a face each, lying against one another - a bolted joint,
    or anything else held together by a constraint - and what happens on one
    side of that is not what happens on the other.

    The distinction is the whole of the rule for closing a junction between two
    bodies. Joined, their walls are one wall interrupted by a boundary that
    exists only in the file, and their mid-surfaces should meet. Touching, they
    are two parts, and running their mid-surfaces together would weld them.
    """
    theirs = {face.hashCode() for face in other.Faces}
    return any(
        face.hashCode() in theirs and any(face.isSame(one_of) for one_of in other.Faces)
        for face in one.Faces
    )


def joined_neighbours(bodies):
    """
    For each body, the bodies it is joined to, in the order they came.

    One answer for both callers. The step and the panel each have to know which
    bodies close on which, and working it out twice is how the drawing and the
    result come to disagree - which they already did once, over a body that had
    to be cut.
    """
    return [
        [
            (other, theirs)
            for position, (other, theirs) in enumerate(bodies)
            if position != index and theirs and solids_share_a_face(solid, other)
        ]
        for index, (solid, _) in enumerate(bodies)
    ]


def joined_region(solid, neighbours):
    """
    A body and the ones joined to it, as one shape a sheet may be grown into.

    Growth asks a body whether its material carries on past an edge, and at the
    face two solids share the answer is yes on both sides - but only if the
    body it is asked of is both of them. Where they will not join into one
    shape the solid is handed over on its own, and the sheets then end at its
    boundary as they did before.
    """
    if not neighbours:
        return solid
    try:
        joined = solid.fuse(list(neighbours)).removeSplitter()
    except Exception:
        return solid
    if joined.isNull() or len(joined.Solids) != 1:
        return solid
    return joined.Solids[0]


def face_names(shape):
    """
    Which face of a shape each face is, so that a wall can be named by it.

    By what the face is, not by where its middle is. A flange has faces that
    share a centre of mass - an annulus and the disc it rings, a tube's outer
    round and its bore - and naming by position gives all of them the name of
    whichever came first. Three different walls of one solid were then listed
    under the same two faces, and since a wall switched off is remembered by
    that name, switching one off switched off another.
    """
    names = {}
    for index, face in enumerate(shape.Faces, 1):
        names.setdefault(face.hashCode(), []).append((face, f"Face{index}"))
    return names


def face_name(names, face):
    """The name of a face in a shape those names were taken from, or None."""
    # A hash can be shared by faces that are not the same one, so the
    # candidates it gathers are told apart by asking the shapes themselves.
    for other, name in names.get(face.hashCode(), ()):
        if face.isSame(other):
            return name
    return None


def _resolve_face_picks(links):
    """Faces named by a reference list, in the order they were picked."""
    faces = []
    for link in links or []:
        source = link[0]
        subs = link[1] if isinstance(link[1], (list, tuple)) else (link[1],)
        for sub in subs:
            if not sub:
                continue
            try:
                shape = source.getSubObject(sub)
            except Exception:
                shape = None
            if shape is not None and not shape.isNull() and shape.ShapeType == "Face":
                faces.append(shape)
    return faces


def manual_walls(obj, base_shape):
    """
    The walls behind the pairs picked by hand, each with the solid it belongs to.

    The two lists are read side by side, so the first source goes with the first
    partner. A pick that no longer resolves, or a pair that turns out not to
    bound any material, drops out here rather than making the whole step fail:
    an edit upstream should cost the pair it invalidated, not the result.
    """
    sources = _resolve_face_picks(obj.PairSources)
    partners = _resolve_face_picks(obj.PairPartners)

    walls = []
    for face_a, face_b in zip(sources, partners):
        for solid in base_shape.Solids:
            if not any(face.isSame(face_a) for face in solid.Faces):
                continue
            wall = wall_from_faces(solid, face_a, face_b)
            if wall is not None:
                walls.append((solid, wall))
            break
    return walls


# How far a curved sheet may be moved to reach the sheets beside it, as a
# fraction of the wall it stands for. The move is small by nature - it exists
# because neighbouring walls are of different thicknesses - and a large one
# means the surfaces were never neighbours in the way this assumes.
CONNECT_LIMIT = 0.5


def _plane_of(face):
    """(point, normal) of a planar sheet, or None."""
    if type(face.Surface).__name__ != "Plane":
        return None
    return face.Surface.Position, face.Surface.Axis


def connect_curved_sheets(pairs, report=None):
    """
    Re-fit a curved sheet so that it meets the flat ones on either side of it.

    A corner and the walls it joins are rarely the same thickness, and each
    mid-surface is built halfway across its own wall, so the corner arc ends
    short of the flats - on a hollow section with a 12 mm outer fillet and an
    8 mm inner one, half a millimetre short. Extending will not help: the arc
    and the plane are concentric-ish, they never meet however far either runs.

    What does meet is the arc drawn tangent to both neighbours, which is the
    mid-line of the profile as a draughtsman would draw it. Its radius is the
    distance from the corner axis to the neighbouring mid-plane, and at that
    radius the ends of the arc land exactly where the flats end - so the sheets
    join end to end with nothing to trim, and the joint is smooth rather than
    merely closed.

    The thickness the corner carries does not change; only where its surface
    sits. That does move a little material, which is why the move is limited and
    reported rather than made quietly.
    """
    planes = [
        (wall, sheet, _plane_of(sheet.face))
        for wall, sheet in pairs
    ]

    connected = []
    for wall, sheet in pairs:
        surface = sheet.face.Surface
        if type(surface).__name__ != "Cylinder":
            connected.append((wall, sheet))
            continue

        targets = []
        for other_wall, other_sheet, plane in planes:
            if plane is None or other_wall is wall:
                continue
            # Only a wall that actually touches this one has a say in where its
            # corner goes, and only a plane running along the corner axis can
            # be reached by changing a radius.
            if abs(plane[1].dot(surface.Axis)) > 1e-6:
                continue
            try:
                if wall.outer.distToShape(other_wall.outer)[0] > 1e-6:
                    continue
            except Exception:
                continue
            targets.append(abs((surface.Center - plane[0]).dot(plane[1])))

        if not targets:
            connected.append((wall, sheet))
            continue

        target = sum(targets) / len(targets)
        move = abs(target - surface.Radius)
        if move > CONNECT_LIMIT * wall.thickness or target <= 1e-7:
            if report is not None:
                report.append((wall.thickness, move))
            connected.append((wall, sheet))
            continue

        fitted = Part.Cylinder(surface)
        fitted.Radius = target
        u0, u1, v0, v1 = sheet.face.ParameterRange
        face = fitted.toShape(u0, u1, v0, v1)
        if face is None or face.isNull():
            connected.append((wall, sheet))
            continue
        connected.append((wall, Sheet(face, sheet.thickness, sheet.offset)))

    return connected


def _surfaces_match(face, other, tolerance=1e-6):
    """
    Whether two faces lie on the same underlying surface.

    A cut hands back pieces whose faces are parts of the faces that went in,
    rebuilt and renamed, so nothing about them can be compared by identity. What
    survives a cut untouched is the surface each face lies on, and that is
    enough to recognise a wall on the far side of one.
    """
    kind = type(face.Surface).__name__
    if kind != type(other.Surface).__name__:
        return False

    if kind == "Plane":
        normal = face.Surface.Axis
        if abs(abs(normal.dot(other.Surface.Axis)) - 1.0) > 1e-6:
            return False
        return abs((other.Surface.Position - face.Surface.Position).dot(normal)) < tolerance

    if kind == "Cylinder":
        first, second = face.Surface, other.Surface
        if abs(abs(first.Axis.dot(second.Axis)) - 1.0) > 1e-6:
            return False
        if abs(first.Radius - second.Radius) > tolerance:
            return False
        offset = second.Center - first.Center
        offset = offset - first.Axis * offset.dot(first.Axis)
        return offset.Length < tolerance

    # Anything else is asked through its own parametrisation: a point the
    # other face certainly holds is dropped onto this face's surface, and the
    # two lie on one surface when it lands where it started with the same
    # normal. Asking the distance between the faces instead would say yes to
    # any two that so much as touch - a band and the sheet it leans on - and
    # costs a distance computation between two free-form faces every time.
    try:
        landed, normal, away, _, _ = _project(face, sample_point(other)[0])
    except Exception:
        return False
    if abs(away) > tolerance:
        return False
    return abs(abs(normal.dot(_face_normal(other))) - 1.0) < 1e-6


def walls_carried_to_piece(piece, walls):
    """
    The walls of a body that a piece cut from it still has both faces of.

    This is what makes shelling part of a body possible. Asking a piece what
    walls it has would find whatever is thin about it, including the walls the
    user switched off, which come back the moment they are looked for again.
    Carrying the chosen walls across instead means a piece can only become the
    wall it was cut out to be.

    Each is returned with the position of the wall it came from, because the
    piece's version of a wall says which pieces are freed and nothing more: the
    faces to emit are the wall's own.
    """
    carried = []
    for index, wall in enumerate(walls):
        outer = next((face for face in piece.Faces if _surfaces_match(face, wall.outer)), None)
        inner = next((face for face in piece.Faces if _surfaces_match(face, wall.inner)), None)
        if outer is None or inner is None:
            continue

        # The roles come across with the wall rather than being worked out
        # again. Which side of a wall faces out is a property of the body, and
        # a piece cut from it is too small to tell: on a corner of a section the
        # piece sits between the two arcs and its centre of mass is nearer the
        # outer one, so asking it would turn the wall inside out.
        sample = sample_point(outer)
        if sample is None:
            continue
        point, normal = sample
        thickness, spread = _sampled_thickness(outer, inner, wall.thickness)
        if thickness < 1e-7:
            continue
        if not piece.isInside(point - normal * (thickness / 2.0), 1e-6, True):
            continue
        carried.append((index, Wall(outer, inner, thickness, spread)))
    return carried


def _sheet_under(face, sheets):
    """
    The sheet a face of the result came out of, found by where the face lies.

    Only sheets on the same surface can be the answer, and among those it is
    the one the face sits inside. A point the face certainly holds is used
    rather than its centre of mass, because the centre of a face with a hole in
    it can fall outside the face altogether.
    """
    sample = sample_point(face)
    point = sample[0] if sample is not None else face.CenterOfMass
    for sheet in sheets:
        if not _surfaces_match(face, sheet.face):
            continue
        if sheet.face.isInside(point, 1e-6, True):
            return sheet
    return None


def _remainder_of(solid, taken, kept):
    """
    What is left of a body once the freed walls are taken out of it.

    Not the pieces that were not taken. A wall is freed with planes, and a plane
    does not stop at the wall: it runs on through the body and scores every face
    it passes, so putting those pieces back together leaves vertices strewn
    across the fillets of corners that had nothing to do with any of it. Taking
    the freed pieces out of the untouched body instead cuts it only where they
    were.
    """
    if not taken:
        return merge_touching(kept)
    try:
        remainder = solid.cut(taken).removeSplitter()
    except Exception:
        return merge_touching(kept)
    if remainder.isNull() or not remainder.Solids:
        return merge_touching(kept)
    return list(remainder.Solids)


def merge_touching(solids, tolerance=1e-6):
    """
    Put back together the pieces that were only ever separated by a cut.

    The cuts are made to free the walls, not to divide what is left, so the
    remainder is fused wherever it still touches. Otherwise shelling one wall of
    a section would hand back the rest of it in eight parts.
    """
    groups = []
    for solid in solids:
        touching = []
        for group in groups:
            if any(solid.distToShape(other)[0] <= tolerance for other in group):
                touching.append(group)
        merged = [solid]
        for group in touching:
            merged.extend(group)
            groups.remove(group)
        groups.append(merged)

    result = []
    for group in groups:
        if len(group) == 1:
            result.append(group[0])
            continue
        try:
            fused = group[0].fuse(group[1:]).removeSplitter()
            result.extend(fused.Solids if fused.Solids else group)
        except Exception:
            result.extend(group)
    return result


def _one_edge_per_boundary(shape):
    """
    Merge the edges of a result that lie on one and the same curve.

    A sheet is assembled and cut several times over - a footprint fused with
    the rods that grow it, then split against every other sheet at once - and
    each of those leaves its mark where its boundary crossed the sheet's own.
    The marks are not wrong: the pieces meet exactly, on the same line or the
    same circle. They are simply extra, and a mesher offered a four-sided face
    described by seven edges will not lay a mapped grid on it. On a beam the
    tapered end of a flange came back as three arcs of one circle.

    removeSplitter will not do this. It merges faces that share a surface and
    leaves the edges within a wire where they are, which is why the sheets come
    back with the same count however often it is called. UnifySameDomain asked
    for edges only is the tool for it.

    Faces are deliberately not merged. Two sheets can lie on one plane - the
    halves of a flange that a web divides - and each carries its own thickness,
    so joining them would leave the result unable to say what it stands for.
    """
    try:
        tool = Part.ShapeUpgrade.UnifySameDomain(
            Shape=shape, UnifyEdges=True, UnifyFaces=False
        )
        tool.build()
        tidy = tool.shape()
    except Exception:
        return shape
    if tidy.isNull() or len(tidy.Faces) != len(shape.Faces):
        return shape
    return tidy


def sew_sheets(sheets, tolerance=1e-6):
    """
    Gather the sheets that meet into shells, and leave the lone ones as faces.

    Two faces that touch are not connected: each carries its own edges, and a
    mesher handed both meshes them separately, so the wall of a box comes out as
    four surfaces that happen to line up rather than one that carries load
    around the corner. The joint needs a single edge that both faces name, and
    the mesh then runs through it.

    Putting the faces in a shell is not enough to get that. Part.makeShell only
    collects faces into a container and leaves every edge where it was, so a
    shell built that way has two edges lying on top of each other at every
    joint and the mesher still sees two separate surfaces. A general fuse is
    what actually merges the coincident edges into one, and the shell is built
    from what comes out of it.

    Everything is fused at once, and which sheets belong together is read off
    the result: two faces that came out of the fuse naming the same edge meet,
    and nothing else does. That is what a shell is, and it is free to read,
    where asking every pair of sheets how far apart they are cost longer than
    the fuse itself on a part with free-form walls.

    The shell is a container and nothing more - the faces inside it stay the
    unit everything downstream works with. Solids are deliberately left out of
    this: a shell has six degrees of freedom against a solid's three and the two
    are joined by a constraint, never by sharing an edge.
    """
    faces = [sheet.face for sheet in sheets]
    if len(faces) < 2:
        return faces
    try:
        fused, _ = faces[0].generalFuse(faces[1:], tolerance)
        pieces = list(fused.Faces)
    except Exception:
        # Without the fuse the faces are at least handed over, so the result
        # is the same shape as before even if the joints are not shared. That
        # is worse for the mesh but better than losing them.
        return faces
    if not pieces:
        return faces

    # Faces that name one edge belong to one shell, and a face joined to one
    # that is joined to another belongs with both of them.
    leader = list(range(len(pieces)))

    def find(index):
        while leader[index] != index:
            leader[index] = leader[leader[index]]
            index = leader[index]
        return index

    first_owner = {}
    for index, face in enumerate(pieces):
        for edge in face.Edges:
            key = edge.hashCode()
            if key in first_owner:
                leader[find(first_owner[key])] = find(index)
            else:
                first_owner[key] = index

    groups = {}
    for index, face in enumerate(pieces):
        groups.setdefault(find(index), []).append(face)

    shapes = []
    for group in groups.values():
        if len(group) == 1:
            shapes.append(_one_edge_per_boundary(group[0]))
            continue
        try:
            # Tidied as a shell rather than a face at a time, so that an edge
            # two sheets share is merged for both of them at once and they are
            # still joined afterwards.
            shapes.append(_one_edge_per_boundary(Part.makeShell(group)))
        except Exception:
            shapes.extend(group)
    return shapes


def junction_reach(walls, given=0.0):
    """
    How far a sheet may reach past its own wall to close a joint.

    What is given, when anything is; otherwise twice the thickest wall being
    built. The reach has to clear the neighbour's half thickness and whatever
    fillet sits in the root of the joint, and twice the thickness covers both
    on an ordinary part. It is worth setting by hand where it does not: a
    large fillet needs more, and there is nothing to lose by asking for it,
    since growth is cut back to the material either way.
    """
    if given and given > 0.0:
        return float(given)
    if not walls:
        return 0.0
    return JUNCTION_REACH * max(wall.thickness for wall in walls)


def sheets_from_walls(
    walls,
    method,
    ratio,
    side,
    solid=None,
    close_junctions=True,
    reach=0.0,
    own=None,
    report=None,
):
    """
    The faces a set of walls contributes, connected to each other and trimmed.

    Taking the settings rather than the step means the panel can ask what a
    result would look like before anything is written to the object, and get the
    same answer the step will give.

    The body is wanted as well, because a mid-surface cannot be finished
    without it: growing a sheet into the joints beside it is decided by where
    the material carries on, and clipped by where it stops. Without a body, or
    with the joints left open on purpose, the sheets are still built and
    trimmed - they simply end where their own walls end, half a thickness
    short of one another, which is what a mid-surface is before anything is
    done about the joints.

    More walls may be given than are wanted back. A wall of a solid joined to
    this one has to take part - it is what the sheets here grow towards and are
    cut against - but its sheet belongs to that solid and is asked for when
    that solid is reduced. Naming which walls are this body's own is what keeps
    the junction between them exact: both bodies build the same sheets from the
    same walls and each keeps its half, so the two meet on the line the trim
    put there rather than on two lines that nearly agree.
    """
    def mine(built):
        if own is None:
            return [sheet for _, sheet in built]
        return [sheet for wall, sheet in built if any(wall is one for one in own)]

    shared = shared_faces(walls)
    pairs = [(wall, sheet_for_wall(wall, method, ratio, side, shared)) for wall in walls]
    pairs = [(wall, sheet) for wall, sheet in pairs if sheet is not None]
    if not pairs:
        return []

    # Only surfaces built between the walls can meet one another. Two skins kept
    # on the outside of a corner never do, so there is nothing to grow towards
    # and nothing to cut, and the corner material stays in both.
    if method != METHOD_MIDSURFACE:
        return mine(pairs)

    # Fitting the corners to their neighbours first means the sheets of an
    # extruded profile meet end to end without any growth at all, and the trim
    # that follows finds nothing left to cut there.
    pairs = connect_curved_sheets(pairs, report=report)

    if solid is not None and close_junctions:
        margin = junction_reach([wall for wall, _ in pairs], reach)
        # A wall may hand back more than one sheet: a free-form one is
        # carried into its joints by bands, and those are sheets in their
        # own right rather than part of the surface they lean on.
        pairs = [
            (wall, grown)
            for wall, sheet in pairs
            for grown in grow_sheet(sheet, solid, margin)
        ]

    if len(pairs) == 1:
        return mine(pairs)
    return mine(settle_overlaps(trim_sheets(pairs)))


def _target_solids(obj, base_shape):
    """The solids this step was pointed at, or every solid when it was not."""
    solids = base_shape.Solids
    if not obj.Elements:
        return solids

    picked = []
    for link in obj.Elements:
        source = link[0]
        subs = link[1] if isinstance(link[1], (list, tuple)) else (link[1],)
        for sub in subs:
            if not sub:
                continue
            try:
                shape = source.getSubObject(sub)
            except Exception:
                shape = None
            if shape is None or shape.isNull() or shape.ShapeType != "Solid":
                continue
            picked.append(shape)

    # A pick names a sub-shape of the input, so it is matched back onto the
    # solids of the shape this step works on instead of being used directly.
    return [
        solid
        for solid in solids
        if any(solid.isSame(shape) or solid.isPartner(shape) for shape in picked)
    ]


def wall_coverage(walls, solid):
    """
    The share of a solid its walls account for, whatever is emitted for them.

    Judging that on the sheets punishes the skin: kept on the outside they run
    round the long way and carry more material than the body holds, kept on the
    inside they run short and carry less. Neither says anything about whether
    the walls explain the body, which is the only question this is asked for, so
    it is measured on the walls themselves - a wall being worth the area midway
    between its two faces, times its thickness.
    """
    if solid.Volume < 1e-12:
        return 0.0
    carried = sum(
        (wall.outer.Area + wall.inner.Area) / 2.0 * wall.thickness for wall in walls
    )
    return carried / solid.Volume


def coverage(sheets, solid):
    """
    The share of a solid's material the sheets account for.

    A wall reduced to a surface carries area times thickness, and that should
    come to the volume of the solid it replaced. It never quite does, because
    the rim around the edge of a wall belongs to no pair, so this is a report
    rather than a test - and it is the honest way to say that a solid was only
    partly understood.
    """
    if solid.Volume < 1e-12:
        return 0.0
    return sum(sheet.face.Area * sheet.thickness for sheet in sheets) / solid.Volume


def _shell_builder_steps(source):
    """Shell builder steps of the geometry chain a reference points into."""
    members = getattr(source, "Group", None) or []
    return [
        member
        for member in members
        if getattr(getattr(member, "Proxy", None), "Type", "") == GeometryShellBuilder.Type
    ]


def shell_data_for_reference(source, sub, tolerance=1e-7):
    """
    The thickness and offset a shell builder recorded for a referenced face.

    A shell thickness object names a face of the analysis geometry, and the
    step that made that face is the only place its thickness was ever known -
    the solid it was measured from is gone by then. The face is looked up by
    where it sits rather than by its index, because a step added after the
    shell builder can renumber the faces without moving them.
    """
    try:
        face = source.getSubObject(sub)
    except Exception:
        return None
    if face is None or face.isNull() or face.ShapeType != "Face":
        return None

    centre = face.CenterOfMass
    for step in _shell_builder_steps(source):
        shape = step.Shape
        if shape.isNull():
            continue
        for built, thickness, offset in zip(shape.Faces, step.Thickness, step.Offset):
            if thickness > 0 and (built.CenterOfMass - centre).Length < tolerance:
                return thickness, offset
    return None


# Below what share of a body its walls have to fall before cutting them free is
# the right answer. A blade between two stubs is a few percent of it and has to
# be freed; a tube whose corners were not recognised is nine tenths wall, and
# cutting that apart replaces one clean body by a heap of pieces to fix a gap
# that is better reported.
CUT_SHARE_LIMIT = 0.5

OUTCOME_REDUCE = "reduce"
OUTCOME_CUT = "cut"
OUTCOME_KEEP = "keep"


def near_miss_report(near_misses, max_thickness, tolerance):
    """
    What to say about the pairs that bound material but were not taken.

    Grouped by what stopped them, because that is what says which number to
    change. A pair too thick for the bound is not helped by a wider tolerance,
    and telling a user only that something was missed is telling them nothing.
    """
    lines = []
    thick = [miss for miss in near_misses if miss.reason == NEAR_MISS_THICK]
    varies = [miss for miss in near_misses if miss.reason == NEAR_MISS_VARIES]

    if thick:
        thinnest = min(miss.thickness for miss in thick)
        lines.append(
            f"{len(thick)} more pair(s) are {thinnest:.2f} mm and up, over the "
            f"{max_thickness:.2f} mm bound"
        )
    if varies:
        worst = max(miss.spread for miss in varies)
        lines.append(
            f"{len(varies)} more pair(s) vary by up to {worst * 100:.0f}%, over "
            f"the {tolerance * 100:.0f}% allowed"
        )
    return lines


def solid_outcome(solid, walls, sheets, min_coverage, curated=False):
    """
    What is going to become of a solid, and the share its walls account for.

    The panel has to say the same thing the step will do, and the decision is
    not obvious from the walls alone: a body whose walls fall short is cut apart
    when they run into the rest of it, and only left alone when they do not. So
    the choice lives here and both callers ask it rather than each deciding.

    The share is measured on the walls rather than on what is emitted for them,
    so that choosing which skin to keep cannot decide whether a body is reduced
    at all.
    """
    share = wall_coverage(walls, solid)
    if share >= min_coverage:
        return OUTCOME_REDUCE, share

    # Whether the walls can be freed is answered by whether they end against
    # more material, not by cutting the body to find out. Cutting to decide and
    # then cutting to do it was two thirds of the time this step took, and
    # every boolean of the wasted half reported its progress, which is what set
    # the cursor flickering. A cut that turns out to yield nothing is handled
    # where it is made.
    #
    # How far short the walls fall decides whether cutting is worth it, unless
    # the user has already said which walls they want. A body whose walls were
    # only found by the search and cover nine tenths of it is one the search
    # very likely missed something on, and cutting it apart to chase that gap
    # replaces a clean body by pieces where a word about the near miss serves
    # better - so that is still what happens.
    #
    # A wall switched off by hand is not a gap of that kind. It is an
    # instruction: shell the others and leave this one alone. Refusing the
    # whole body then leaves nothing built, nothing drawn, and no way to shell
    # a part of anything - switching one wall off in a body of five turned the
    # step off with it. A profile with one wall switched off comes back as the
    # sheets of the rest and the one solid that wall would have been, to within
    # a third of a percent of the material, which is exactly what was asked for.
    if (curated or share < CUT_SHARE_LIMIT) and any(
        transition_planes(solid, wall) for wall in walls
    ):
        return OUTCOME_CUT, share
    return OUTCOME_KEEP, share



# What the step was asked for, gathered so that the panel can ask the same
# question of the same code before anything is written to the object. The
# preview once built its sheets by calling the sheet builder directly while the
# step went a different way round for a body it had to cut, and the two drifted
# apart: the preview showed a closed shell and the result was open.
ShellSettings = collections.namedtuple(
    "ShellSettings",
    "method ratio side min_coverage close_junctions reach curated",
)


def settings_of(obj):
    """The settings of a shell builder step, as the geometry wants them."""
    return ShellSettings(
        method=obj.Method,
        ratio=obj.Ratio,
        side=obj.Side,
        min_coverage=obj.MinCoverage,
        close_junctions=obj.CloseJunctions,
        reach=float(obj.JunctionReach),
        # Walls switched off or picked by hand: the user has said which walls
        # they want, and a body that falls short of the coverage is then cut
        # rather than kept whole.
        curated=bool(obj.ExcludedWalls) or bool(obj.PairSources),
    )


def sheets_of(walls, settings, solid=None, warn=None, own=None):
    """The faces a set of walls contributes, with anything worth saying said."""
    too_far = []
    sheets = sheets_from_walls(
        walls,
        settings.method,
        settings.ratio,
        settings.side,
        solid=solid,
        close_junctions=settings.close_junctions,
        reach=settings.reach,
        own=own,
        report=too_far,
    )
    if warn is not None:
        for thickness, move in too_far:
            warn(
                f"a curved sheet ends {move:.3f} mm from the walls beside it, "
                f"more than half the {thickness:.2f} mm it stands for, so it was "
                f"left where it is."
            )
    return sheets


def shell_of_solid(solid, walls, settings, allow_cut=True, warn=None, neighbours=()):
    """
    What a solid becomes: the sheets that replace it, and what is left of it.

    A solid is only given up when the sheets really do stand in for it. When
    they do not, the body is not simply refused: a wall that runs into heavier
    material - a flexure blade between two stubs is the case that matters - is
    cut out at the transitions and each piece asked again. The blade then
    accounts for its own piece and becomes a face, while the stubs come back as
    solids, capped by the very cut that freed the blade.

    The second pass may not cut again. One cut is what separates a wall from
    what it runs into, and letting the pieces cut themselves further would
    chase the shape apart rather than converge.

    This is the whole of what the step does to one body, and it is here rather
    than on the object so that the panel can ask for it with the settings the
    user is still editing and draw exactly what pressing OK would build.

    Bodies joined to this one - sharing a face with it, not merely touching -
    come in as neighbours with their walls. Their sheets are built alongside,
    grown into the same joined region and trimmed against these, and then left
    behind: they belong to their own body and are asked for when it is reduced.
    What that buys is a junction between two solids that closes exactly, since
    both sides work it out from the same walls and keep their half of the same
    trim.
    """
    region = solid
    building = list(walls)
    if settings.close_junctions and neighbours:
        region = joined_region(solid, [other for other, _ in neighbours])
        for _, theirs in neighbours:
            building.extend(theirs)

    built = sheets_of(building, settings, region, warn, own=walls)
    if not built:
        return [], [solid], OUTCOME_KEEP, 0.0

    outcome, share = solid_outcome(
        solid, walls, built, settings.min_coverage, settings.curated
    )
    if outcome == OUTCOME_REDUCE:
        carried = coverage(built, solid)
        if warn is not None and carried > 1.0 + COVERAGE_TOLERANCE:
            warn(
                f"the sheets of one solid carry {carried * 100:.1f}% of its "
                f"material. Where two walls meet, both mid-surfaces run through "
                f"the joint and the material there is counted twice; a skin kept "
                f"on the outside of a corner runs round the long way and claims "
                f"it as well."
            )
        return built, [], outcome, share

    if allow_cut and outcome == OUTCOME_CUT:
        produced, remainder = _cut_and_free(solid, walls, settings, warn)
        # Cutting is only worth it if something came of it. With nothing
        # reduced the pieces would replace a whole solid by the same material
        # in more parts, which is a worse shape for no gain.
        if produced:
            return produced, remainder, outcome, share

    return [], [solid], OUTCOME_KEEP, share


def _sheets_account_for(sheets, piece, tolerance=COVERAGE_TOLERANCE):
    """
    Whether the shell already stands for the whole of a piece of the body.

    Area times thickness, over the part of each sheet that lies in the piece.
    A junction between two walls comes out over a hundred percent, because both
    mid-surfaces run through it and the material is claimed twice; that is the
    right answer here, since what is asked is whether anything of the piece is
    left unrepresented, not whether it is represented once.
    """
    if piece.Volume < 1e-12:
        return False
    carried = 0.0
    for sheet in sheets:
        try:
            common = sheet.face.common(piece)
        except Exception:
            continue
        if common.Faces:
            carried += common.Area * sheet.thickness
    return carried / piece.Volume >= 1.0 - tolerance


def _freed_region(pieces):
    """
    The pieces becoming shell, as one body a sheet may be grown into.

    Growth is decided by asking a body whether its material carries on past an
    edge, so which body is asked settles how far a sheet may reach. Handing
    over the pieces that are going rather than the whole solid is what keeps a
    sheet out of material that is staying. Where they will not join into one
    body nothing is handed over at all, and the sheets then end where their own
    walls end.
    """
    if not pieces:
        return None
    if len(pieces) == 1:
        return pieces[0]
    try:
        joined = pieces[0].fuse(pieces[1:]).removeSplitter()
    except Exception:
        return None
    if joined.isNull() or len(joined.Solids) != 1:
        return None
    return joined.Solids[0]


def _cut_and_free(solid, walls, settings, warn=None):  # noqa: C901
    """
    Free the chosen walls from a body and leave the rest of it solid.

    The body is cut where those walls end, and each piece is asked only whether
    it is one of them - carried across by the surfaces they lie on, because the
    pieces are new shapes and nothing else about them survives. A piece that is
    a chosen wall becomes its face; every other piece stays solid, and the
    pieces that were only ever parted by a cut are put back together so the
    remainder does not come back in fragments.

    A piece that no wall claims is not always the body's to keep. Where two
    chosen walls meet, the corner between them is such a piece, and once their
    sheets are closed on one another the shell runs right through it: leaving
    it solid would put a solid inside the material the shell already stands
    for. So the sheets are first grown as far as they would ever go, and any
    piece they then account for entirely goes with them. A stub at the end of a
    blade is accounted for by a fraction of itself and stays, which is the
    whole difference between a junction and the material a wall runs into.
    """
    pieces = _split_at_transitions(solid, walls, cut_place_of(settings.method, settings.side))
    if not pieces:
        return [], []

    freed = []
    taken = []
    kept = []
    for piece in pieces:
        carried = walls_carried_to_piece(piece, walls)
        if not carried:
            kept.append(piece)
            continue
        # A piece that carries a chosen wall is that wall's to become - as long
        # as the wall really is what the piece is. How much of the piece a sheet
        # is worth is not asked to the last few percent: a sheet on the inner
        # skin of a corner stands for less material than the corner holds, and
        # the difference is not lost, it is carried by the shell rather than by
        # a solid. But a piece the cuts failed to separate - the web of a bent
        # beam still attached to both its flanges - is not a wall with a rim, it
        # is most of the body, and giving it to the web would make the flanges
        # leave the model altogether. Such a piece stays solid, and the wall
        # inside it is not freed.
        #
        # Half is the line, not the coverage the whole body is held to: a skin
        # kept on the inside of a corner stands for well under the corner's
        # material and is meant to, while a web still carrying its flanges
        # stands for a twentieth of its piece.
        share = wall_coverage([wall for _, wall in carried], piece)
        if share < CUT_SHARE_LIMIT:
            if warn is not None:
                warn(
                    f"a wall could not be freed from the body. It accounts for "
                    f"only {share * 100:.0f}% of the piece cut out around it, so "
                    f"the piece stays solid."
                )
            kept.append(piece)
            continue
        for index, _ in carried:
            if index not in freed:
                freed.append(index)
        taken.append(piece)

    if not freed:
        return [], []

    # The sheets are built from all the freed walls at once, not piece by piece.
    # Two walls that meet are cut into different pieces by the very cut that
    # frees them - a flat and the corner beside it always are - and a piece
    # holding one wall has no neighbour to be fitted or trimmed against. Built
    # together they meet, exactly as they would have if the body had never been
    # cut at all.
    chosen = [walls[index] for index in freed]

    if settings.close_junctions and kept:
        # How far the sheets would reach if nothing stopped them, used only to
        # find out which of the kept pieces the shell would then stand for.
        # These are not the sheets that are emitted: grown against the whole
        # body a sheet runs on into whatever it meets, and a blade would end up
        # inside a stub that is staying.
        reaching = sheets_of(chosen, settings, solid)
        absorbed = [piece for piece in kept if _sheets_account_for(reaching, piece)]
        if absorbed:
            taken.extend(absorbed)
            kept = [
                piece
                for piece in kept
                if not any(piece.isSame(other) for other in absorbed)
            ]

    produced = sheets_of(chosen, settings, _freed_region(taken), warn)
    if not produced:
        return [], []
    return produced, _remainder_of(solid, taken, kept)


class GeometryShellBuilder(GeometryBase):
    """Replace thin solids of the input by faces that carry a thickness."""

    Type = "Fem::GeometryShellBuilder"

    # Written by execute(), one entry per face of the result, and not a setting
    # anyone made. Said here so that publishing them is not read back as the
    # user having edited this step.
    OUTPUTS = ("Thickness", "Offset")

    def __init__(self, obj):
        super().__init__(obj)
        self.setup_properties(obj)

    def _get_properties(self):
        prop = [
            _PropHelper(
                type="App::PropertyEnumeration",
                name="Method",
                group="Geometry",
                doc="What the step emits for a wall it recognises",
                value=list(SHELL_METHODS),
            ),
            _PropHelper(
                type="App::PropertyLinkSubList",
                name="Elements",
                group="Geometry",
                doc="Solids to reduce; empty means every solid of the input",
                value=None,
            ),
            _PropHelper(
                type="App::PropertyLinkSubList",
                name="PairSources",
                group="Geometry",
                doc="First face of each wall paired by hand",
                value=None,
            ),
            _PropHelper(
                type="App::PropertyLinkSubList",
                name="PairPartners",
                group="Geometry",
                doc="Second face of each wall paired by hand, in the same order",
                value=None,
            ),
            _PropHelper(
                type="App::PropertyLinkSubList",
                name="ExcludedWalls",
                group="Geometry",
                doc="Walls the scan found that are not to be used, named by their outer face",
                value=None,
            ),
            _PropHelper(
                type="App::PropertyLength",
                name="MaxThickness",
                group="Geometry",
                doc="Largest separation of two faces that still counts as a wall",
                value="6 mm",
            ),
            _PropHelper(
                type="App::PropertyFloatConstraint",
                name="Tolerance",
                group="Geometry",
                doc="How much the thickness may vary across a wall, as a fraction",
                value=(0.02, 0.0, 1.0, 0.005),
            ),
            _PropHelper(
                type="App::PropertyEnumeration",
                name="Side",
                group="Geometry",
                doc="Skin offset: which face of the wall is kept",
                value=list(SHELL_SIDES),
            ),
            _PropHelper(
                type="App::PropertyFloatConstraint",
                name="Ratio",
                group="Geometry",
                doc="Midsurface: where the surface sits, 0 at the outer face, 1 at the inner",
                value=(0.5, 0.0, 1.0, 0.05),
            ),
            _PropHelper(
                type="App::PropertyBool",
                name="CloseJunctions",
                group="Geometry",
                doc="Midsurface: grow the sheets of walls that meet until they close",
                value=True,
            ),
            _PropHelper(
                type="App::PropertyLength",
                name="JunctionReach",
                group="Geometry",
                doc=(
                    "Midsurface: how far a sheet may reach past its own wall to close a "
                    "joint; 0 takes it from the walls being built"
                ),
                value="0 mm",
            ),
            _PropHelper(
                type="App::PropertyFloatConstraint",
                name="MinCoverage",
                group="Geometry",
                doc="Share of a solid its walls must account for before it is replaced",
                value=(0.95, 0.0, 1.0, 0.05),
            ),
            _PropHelper(
                type="App::PropertyFloatList",
                name="Thickness",
                group="Shell",
                doc="Thickness per face of the result; 0 for a face that is not a shell",
                value=[],
            ),
            _PropHelper(
                type="App::PropertyFloatList",
                name="Offset",
                group="Shell",
                doc="Offset per face of the result, as a fraction of its thickness",
                value=[],
            ),
        ]
        return super()._get_properties() + prop

    def execute(self, obj):
        """
        Redo the reduction, or pass on the result that is still the right one.

        A step is executed for anything at all that happens to a dependency,
        and almost none of it is a new input. Doing the work anyway would cost
        a full wall search and reduction on every recompute of the CAD model the analysis was
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
            raise ValueError("No input geometry to reduce")

        base_shape = base_obj.Shape
        reduced = []
        sheets = []
        remainder = []
        picked = manual_walls(obj, base_shape)
        excluded = _resolve_face_picks(obj.ExcludedWalls)

        # Every body's walls are gathered before any of them is reduced,
        # because a body joined to another needs to know that one's walls to
        # close the junction between them.
        prepared = []
        for solid in _target_solids(obj, base_shape):
            extra = [wall for owner, wall in picked if owner.isSame(solid)]
            prepared.append((solid,) + self._walls_of(obj, solid, extra, excluded))

        joined = joined_neighbours([(solid, walls) for solid, walls, _, _ in prepared])
        for index, (solid, walls, near_misses, curated) in enumerate(prepared):
            produced, kept = self._reduce(
                obj, solid, walls, near_misses, curated, joined[index]
            )
            if not produced:
                continue
            reduced.append(solid)
            sheets.extend(produced)
            remainder.extend(kept)

        if not sheets:
            # Nothing was understood, so nothing changes downstream. Passing the
            # input on is not the same as an empty result, which would throw
            # away the geometry the rest of the chain is built on.
            geometry_base.assign_shape(obj, base_shape)
            obj.Thickness = []
            obj.Offset = []
            return

        # Whatever the input carries that was not reduced stays as it is, and
        # the sheets take the place of the solids that were. The features are
        # read without their compounds so the result is never nested.
        kept = [
            feature
            for feature in geometry_base._get_features_without_compounds(base_shape)
            if not any(feature.isSame(solid) for solid in reduced)
        ]
        geometry_base.assign_shape(
            obj, Part.makeCompound(kept + remainder + sew_sheets(sheets))
        )
        self._store_shell_data(obj, sheets)
        self._report_material(obj, base_shape)

    @staticmethod
    def _walls_of(obj, solid, extra_walls=(), excluded=()):
        """
        The walls of a body that are to be used, and what was said about them.

        Gathered on its own so that it can be done for every body before any of
        them is built, which is what lets a body see the walls of the one it is
        joined to.
        """
        near_misses = []
        walls = walls_of_solid(
            solid, float(obj.MaxThickness), obj.Tolerance, rejected=near_misses
        )
        # A pair picked by hand is added to what the search found, unless the
        # search already found it: asking for a wall twice would carry its
        # material twice.
        for extra in extra_walls:
            if not any(
                wall.outer.isSame(extra.outer) and wall.inner.isSame(extra.inner)
                for wall in walls
            ):
                walls.append(extra)

        # A wall the user switched off is not a wall this step knows better
        # about: it is dropped before anything is built from it, and before the
        # body is judged on what its walls account for, so that switching one
        # off can leave the rest of the body solid rather than half represented.
        curated = bool(extra_walls)
        if excluded:
            kept_walls = [
                wall
                for wall in walls
                if not any(wall.outer.isSame(face) for face in excluded)
            ]
            curated = curated or len(kept_walls) != len(walls)
            walls = kept_walls
        return walls, near_misses, curated

    def _reduce(self, obj, solid, walls, near_misses=(), curated=False, neighbours=()):
        """
        What a solid becomes: the sheets that replace it, and what is left of it.

        A solid is only given up when the sheets really do stand in for it. When
        they do not, the body is not simply refused: a wall that runs into
        heavier material - a flexure blade between two stubs is the case that
        matters - is cut out at the transitions and each piece asked again. The
        blade then accounts for its own piece and becomes a face, while the
        stubs come back as solids, capped by the very cut that freed the blade.

        The second pass may not cut again. One cut is what separates a wall from
        what it runs into, and letting the pieces cut themselves further would
        chase the shape apart rather than converge.
        """

        def warn(text):
            FreeCAD.Console.PrintWarning(f"{obj.Name}: {text}\n")

        produced, remainder, outcome, share = shell_of_solid(
            solid, walls, settings_of(obj), warn=warn, neighbours=neighbours
        )
        if outcome != OUTCOME_KEEP:
            return produced, remainder

        message = (
            f"{obj.Name}: a solid stays solid. Its walls account for "
            f"{share * 100:.1f}% of its material, below the "
            f"{obj.MinCoverage * 100:.0f}% this step needs to replace it.\n"
        )
        if curated:
            message += (
                "  The walls left switched on do not stand in for the whole "
                "body, and what is switched off cannot be left out of part of "
                "a solid - it is the whole body or none of it.\n"
            )
        for line in near_miss_report(near_misses, float(obj.MaxThickness), obj.Tolerance):
            message += f"  {line}\n"
        FreeCAD.Console.PrintMessage(message)
        return [], [solid]

    @staticmethod
    def _report_material(obj, base_shape):
        """
        Say so if material has left the model, and only then.

        A sheet standing for less material than the wall it replaced is not a
        loss: what the shell does not carry stays in the solid beside it, still
        in the model and still meshed. Only material that is in neither - taken
        out by a cut and represented by nothing - has gone, and that is the one
        thing worth watching. Measuring the shell against its own wall instead
        refuses perfectly good work over a difference the model never feels.
        """
        before = sum(solid.Volume for solid in base_shape.Solids)
        if before < 1e-9:
            return
        after = sum(solid.Volume for solid in obj.Shape.Solids) + sum(
            face.Area * thickness
            for face, thickness in zip(obj.Shape.Faces, obj.Thickness)
            if thickness > 0
        )
        drift = (after - before) / before
        if abs(drift) > COVERAGE_TOLERANCE:
            FreeCAD.Console.PrintWarning(
                f"{obj.Name}: the result carries {after / before * 100:.1f}% of "
                f"the material that went in. Every joint between two walls is "
                f"counted twice, because both mid-surfaces run through it, and a "
                f"skin kept outside a corner runs long while one kept inside runs "
                f"short - a few percent either way is the shape of the part "
                f"rather than a fault.\n"
            )

    @staticmethod
    def _store_shell_data(obj, sheets):
        """
        Record the thickness and offset of every face of the result.

        The thickness of a wall can only be measured while the solid is still
        there, and by the time anything downstream asks for it the solid is
        gone, so it is written down here instead of being derived later. The
        lists are indexed by the faces of the result, which is the only handle
        that survives the step, and a face that is not a shell carries zero.

        A face of the result need not be the sheet that was built. Sewing the
        sheets fuses them so that they share their edges, and a fuse is free to
        hand a face back rebuilt, or split where another sheet crosses it. So a
        face is matched by where it lies rather than by what it measures: on the
        same surface as a sheet, and inside it. The centres are tried first
        because they answer at once for the faces that did come through whole.
        """
        # A face that bounds a solid is never a sheet, whatever it lies on. A
        # skin is the wall's own face, so the body it was taken from carries a
        # face in exactly the same place, and without this the solid left beside
        # a shell would be given the shell's thickness.
        of_solids = [face for solid in obj.Shape.Solids for face in solid.Faces]

        # Where each sheet is, asked once. The centre of mass of a free-form
        # face costs about as much to work out as a small boolean, and asking
        # for it again inside the search would ask for every sheet's once per
        # face of the result.
        centres = [sheet.face.CenterOfMass for sheet in sheets]

        thickness = []
        offset = []
        for face in obj.Shape.Faces:
            if any(face.isSame(other) for other in of_solids):
                thickness.append(0.0)
                offset.append(0.0)
                continue
            here = face.CenterOfMass
            match = next(
                (
                    sheet
                    for sheet, centre in zip(sheets, centres)
                    if (centre - here).Length < 1e-7
                ),
                None,
            )
            if match is None:
                match = _sheet_under(face, sheets)
            thickness.append(match.thickness if match else 0.0)
            offset.append(match.offset if match else 0.0)
        obj.Thickness = thickness
        obj.Offset = offset
