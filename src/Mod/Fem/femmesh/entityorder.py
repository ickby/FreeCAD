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

__title__ = "Order in which meshers number the geometry FreeCAD hands them"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

## @package entityorder
#  \ingroup FEM
#  \brief predict the entity numbers a mesher assigns when it imports a BREP
#
#  FreeCAD and the meshers exchange geometry entities as numbers. FreeCAD writes
#  them into the Gmsh geo file, where Physical groups name the geometry entity a
#  mesh group stands for and refinements, boundary layers and transfinite
#  settings select the entities they act on. Netgen reports them back, as the
#  entity each mesh element belongs to, which is what its mesh groups are named
#  after. On both sides the number is the mesher's, while FreeCAD only knows its
#  own Solid/Face/Edge/Vertex indices.
#
#  The two numberings are not the same. Both meshers bind what they read from a
#  BREP by descending dimension: first every solid together with everything on
#  its boundary, then the faces that belong to no solid together with their
#  boundary, then free wires, then free edges, then free vertices. FreeCAD
#  numbers entities in plain OCC traversal order of the shape, which does not
#  reorder by dimension. For a shape of one dimension - a solid, a shell - both
#  walks visit the same entities in the same order and the numbers agree, which
#  is why passing FreeCAD indices worked for as long as only such shapes were
#  meshed. A shape mixing dimensions breaks it: in a compound of a plane and a
#  box the plane is FreeCAD's Face1, but both meshers number the six box faces
#  1 to 6 and the plane 7. Every entity number exchanged then means a different
#  entity than intended.
#
#  This module mimics that traversal so the mapping can be computed from the
#  shape alone. The alternative - asking the mesher - costs a separate run
#  before the input can be written, because the numbers have to be known while
#  it is written.
#
#  Mimicking means relying on behaviour neither mesher promises. The assumption
#  is pinned by TestGMSHEntityOrder in femtest/app/test_gmsh.py and by
#  TestNetgenEntityOrder in femtest/app/test_netgen.py, which compare what this
#  module predicts against what a real Gmsh and a real Netgen do. Read the
#  comment on those tests before changing anything here.

ENTITY_KINDS = ("Solid", "Face", "Edge", "Vertex")


def _index_lookup(subshapes):
    """Map the hash of each sub-shape to its 1-based FreeCAD index."""
    lookup = {}
    for index, sub in enumerate(subshapes, start=1):
        lookup.setdefault(sub.hashCode(), []).append((index, sub))
    return lookup


def _index_of(lookup, sub):
    """FreeCAD index of a sub-shape, 0 when it is not part of the shape."""
    candidates = lookup.get(sub.hashCode())
    if not candidates:
        return 0
    if len(candidates) == 1:
        return candidates[0][0]
    # Hashes ignore orientation but are not collision free.
    for index, candidate in candidates:
        if candidate.isSame(sub):
            return index
    return 0


def entity_order(shape):
    """FreeCAD entity indices in the order Gmsh tags them.

    Returns one list per entity kind, holding FreeCAD indices: the entity at
    position i of a list is the one Gmsh gives the tag i + 1. Entities Gmsh
    does not see, and shapes of a kind the shape does not hold, are absent.
    """
    order = {kind: [] for kind in ENTITY_KINDS}
    if shape is None or shape.isNull():
        return order

    lookup = {
        "Solid": _index_lookup(shape.Solids),
        "Face": _index_lookup(shape.Faces),
        "Edge": _index_lookup(shape.Edges),
        "Vertex": _index_lookup(shape.Vertexes),
    }
    seen = {kind: set() for kind in ENTITY_KINDS}

    def take(kind, sub):
        index = _index_of(lookup[kind], sub)
        if index and index not in seen[kind]:
            seen[kind].add(index)
            order[kind].append(index)

    def walk_edge(edge):
        take("Edge", edge)
        for vertex in edge.Vertexes:
            take("Vertex", vertex)

    def walk_face(face):
        take("Face", face)
        for wire in face.Wires:
            for edge in wire.Edges:
                walk_edge(edge)

    def hashes(subshapes):
        return {sub.hashCode() for sub in subshapes}

    # What a pass has to leave to the pass of the dimension above it, which
    # reaches those entities as part of its boundary.
    faces_of_solids = set()
    for solid in shape.Solids:
        faces_of_solids |= hashes(solid.Faces)
    wires_of_faces = set()
    for face in shape.Faces:
        wires_of_faces |= hashes(face.Wires)
    edges_of_wires = set()
    for wire in shape.Wires:
        edges_of_wires |= hashes(wire.Edges)
    vertices_of_edges = set()
    for edge in shape.Edges:
        vertices_of_edges |= hashes(edge.Vertexes)

    for solid in shape.Solids:
        take("Solid", solid)
        for face in solid.Faces:
            walk_face(face)

    for face in shape.Faces:
        if face.hashCode() not in faces_of_solids:
            walk_face(face)

    for wire in shape.Wires:
        if wire.hashCode() not in wires_of_faces:
            for edge in wire.Edges:
                walk_edge(edge)

    for edge in shape.Edges:
        if edge.hashCode() not in edges_of_wires:
            walk_edge(edge)

    for vertex in shape.Vertexes:
        if vertex.hashCode() not in vertices_of_edges:
            take("Vertex", vertex)

    return order


def entity_tags(shape):
    """Gmsh tag of every entity of a shape, keyed by FreeCAD index.

    Returns one dict per entity kind: {freecad_index: gmsh_tag}.
    """
    return {
        kind: {index: tag for tag, index in enumerate(indices, start=1)}
        for kind, indices in entity_order(shape).items()
    }
