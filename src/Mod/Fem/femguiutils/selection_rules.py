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

"""
What a FEM reference slot will take, with no Qt and no 3D view.

evaluate() is the single filter: the selection gate, the observer, and the
prefill handoff all call it. pick_mode is slot state, not a field of the rule,
because the user flips it mid-pick with Alt or the header toggle.
"""

from dataclasses import dataclass, field

import FreeCAD

from femtools import geomtools

__title__ = "FEM reference selection rules"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

PICK_DIRECT = "direct"
PICK_SOLID = "solid"

PROMOTION_LOCKED = "locked"
PROMOTION_OFFERED = "offered"
PROMOTION_UNAVAILABLE = "unavailable"

SHAPE_KINDS = ("Vertex", "Edge", "Face", "Solid", "Shell", "CompSolid", "Compound")
PROMOTABLE_KINDS = ("Face", "Edge")
VOLUME_KINDS = ("Solid", "Shell", "CompSolid", "Compound")

_PLURAL = {
    "Vertex": "vertices",
    "Edge": "edges",
    "Face": "faces",
    "Solid": "solids",
    "Shell": "shells",
    "CompSolid": "compsolids",
    "Compound": "compounds",
    "Component": "components",
}

_SINGULAR = {
    "Vertex": "vertex",
    "Edge": "edge",
    "Face": "face",
    "Solid": "solid",
    "Shell": "shell",
    "CompSolid": "compsolid",
    "Compound": "compound",
    "Component": "component",
}


def _tr(text, **kwargs):
    translated = FreeCAD.Qt.translate("FEM", text)
    if kwargs:
        return translated.format(**kwargs)
    return translated


def shape_kind(sub):
    """Leaf kind of a sub-element name, or None for a whole-object pick."""
    if not sub:
        return None
    leaf = sub.rsplit(".", 1)[-1]
    for kind in SHAPE_KINDS + ("Component",):
        if leaf.startswith(kind) and (len(leaf) == len(kind) or leaf[len(kind) :].isdigit()):
            return kind
    return None


def display_name(obj, sub=""):
    """What a row shows: Label, or Label.sub for an element."""
    label = obj.Label if hasattr(obj, "Label") else obj.Name
    if not sub:
        return label
    return f"{label}.{sub}"


def leaf_name(sub):
    return sub.rsplit(".", 1)[-1] if sub else ""


def with_prefix(sub, new_leaf):
    prefix = sub.rpartition(".")[0] if sub else ""
    return f"{prefix}.{new_leaf}" if prefix else new_leaf


def resolve_pick(obj, sub):
    """
    Unpack a GeoFeatureGroup-encoded (obj, sub) into the child and element.

    A click on a chain step is reported against the group with the step name
    encoded into the sub-element path. The gate and the observer both have to
    see the same object the slot will store.
    """
    if obj is None:
        return None, ""
    if not sub:
        return obj, ""
    parts = sub.split(".")
    current = obj
    index = 0
    while index < len(parts):
        leaf = parts[index]
        if shape_kind(leaf):
            break
        child = None
        if hasattr(current, "getObject"):
            try:
                child = current.getObject(leaf)
            except Exception:
                child = None
        if child is None:
            document = getattr(current, "Document", None)
            if document is not None:
                child = document.getObject(leaf)
        if child is None:
            break
        current = child
        index += 1
    return current, ".".join(parts[index:])


@dataclass(frozen=True)
class ReferenceRule:
    """
    Declared per slot.

    types: shape kinds this slot stores (Face, Edge, Vertex, Solid, ...).
    An empty types with object_kinds means whole objects of those types.
    An empty types without object_kinds means any whole object.
    """

    types: tuple = ()
    max_count: int | None = None
    homogeneous: bool = True
    scope: str = "geometry"
    object_kinds: tuple = ()
    allow_empty_sub: bool = False

    def __post_init__(self):
        object.__setattr__(self, "types", tuple(self.types))
        object.__setattr__(self, "object_kinds", tuple(self.object_kinds))

    @property
    def promotion(self):
        """locked | offered | unavailable, derived from types the way today's radio was."""
        if self.object_kinds or self.allow_empty_sub:
            return PROMOTION_UNAVAILABLE
        has_solid = "Solid" in self.types
        has_surface = any(kind in self.types for kind in ("Face", "Edge", "Vertex", "Shell"))
        if has_solid and not has_surface:
            return PROMOTION_LOCKED
        if has_solid and has_surface:
            return PROMOTION_OFFERED
        return PROMOTION_UNAVAILABLE

    @property
    def gated_types(self):
        """Union of stored types and the kinds a promoting pick can come in on."""
        types = set(self.types)
        if self.promotion != PROMOTION_UNAVAILABLE:
            types.update(PROMOTABLE_KINDS)
        if self.object_kinds or self.allow_empty_sub:
            types.add("")
        return types


@dataclass(frozen=True)
class Accept:
    picks: list = field(default_factory=list)


@dataclass(frozen=True)
class Refuse:
    reason: str
    # Whether "it belongs in that other slot" would be the better thing to
    # say. A pick of the wrong type for this slot might suit another one; a
    # duplicate or a full slot is about this slot alone, and pointing
    # elsewhere would bury the reason the pick was actually turned away.
    redirectable: bool = True


@dataclass(frozen=True)
class NeedsChoice:
    candidates: list = field(default_factory=list)
    source: tuple | None = None


def owning_solids(obj, sub):
    """
    Solid names (same path as *sub*) that contain the picked element.

    One name for an unambiguous pick, several when a face or edge is shared,
    empty when the element belongs to no solid.

    Both sides of the comparison are taken out of the one counting shape.
    isSame() is identity on the underlying TShape, and an element fetched
    through getSubObject() need not share one with the shape it is numbered
    in — an imported analysis hands out a transformed copy, so every face of
    it used to come back owned by nothing at all.
    """
    kind = shape_kind(sub)
    if kind == "Solid":
        return [sub]
    if kind not in PROMOTABLE_KINDS:
        return []

    owner_shape = _counting_shape(obj, sub)
    if owner_shape is None or owner_shape.isNull():
        return []
    members = owner_shape.Faces if kind == "Face" else owner_shape.Edges
    try:
        index = int(leaf_name(sub)[len(kind) :]) - 1
    except ValueError:
        return []
    if not 0 <= index < len(members):
        return []

    element = members[index]
    found = []
    for position, solid in enumerate(owner_shape.Solids):
        pool = solid.Faces if kind == "Face" else solid.Edges
        if any(element.isSame(item) for item in pool):
            found.append(with_prefix(sub, f"Solid{position + 1}"))
    return found


def _counting_shape(obj, sub):
    """
    The shape *sub* is numbered in, unplaced.

    get_element_shape() places the shape so it can be compared against an
    element; counting elements needs no placement, and skipping it keeps this
    cheap enough to run for every row on every rebuild.
    """
    owner = obj
    head = sub.rpartition(".")[0]
    if head and hasattr(obj, "getSubObject"):
        owner = obj.getSubObject(f"{head}.", 1) or obj
    if owner.isDerivedFrom("Fem::FemAnalysisImport"):
        from femtools import femutils

        geometry = femutils.get_reference_geometry(owner.Analysis)
        return geometry.Shape if geometry is not None else None
    return getattr(owner, "Shape", None)


def element_exists(obj, sub):
    """
    Whether a stored reference still resolves. False marks a row stale.

    Everything unknown counts as present: a row wrongly painted as gone is
    worse than one that quietly still points at nothing.
    """
    if obj is None:
        return False
    if not sub:
        return True
    kind = shape_kind(sub)
    if kind is None or kind == "Component":
        return True
    try:
        shape = _counting_shape(obj, sub)
        if shape is None or shape.isNull():
            return True
        pool = {
            "Vertex": "Vertexes",
            "Edge": "Edges",
            "Face": "Faces",
            "Solid": "Solids",
            "Shell": "Shells",
            "CompSolid": "CompSolids",
            "Compound": "Compounds",
        }.get(kind)
        members = getattr(shape, pool, None) if pool else None
        if members is None:
            return True
        index = int(leaf_name(sub)[len(kind) :])
    except (AttributeError, ValueError, RuntimeError):
        return True
    return 1 <= index <= len(members)


def current_kind(current):
    """Shape kind already stored in a homogeneous slot, or None if empty."""
    for _obj, sub in current:
        kind = shape_kind(sub)
        if kind:
            return kind
    return None


def _join(names, *, capitalize):
    if not names:
        return _tr("Objects") if capitalize else _tr("objects")
    head = names[0].capitalize() if capitalize else names[0]
    if len(names) == 1:
        return head
    if len(names) == 2:
        return _tr("{first} or {second}", first=head, second=names[1])
    middle = ", ".join(names[1:-1])
    return _tr("{head}, {middle} or {last}", head=head, middle=middle, last=names[-1])


def _join_types(types, *, capitalize=True):
    return _join([_PLURAL.get(kind, kind.lower() + "s") for kind in types], capitalize=capitalize)


def _join_types_singular(types, *, capitalize=True):
    """ "a face or an edge" — how a slot that takes exactly one pick reads."""
    names = []
    for kind in types:
        word = _SINGULAR.get(kind, kind.lower())
        article = _tr("an") if word[:1] in "aeiou" else _tr("a")
        names.append(f"{article} {word}")
    return _join(names, capitalize=capitalize)


def humanize_object_kind(kind):
    """ "Part::DatumPlane" -> "datum plane", so a refusal reads as English."""
    leaf = kind.rsplit("::", 1)[-1]
    words = []
    current = ""
    for char in leaf:
        if char.isupper() and current:
            words.append(current)
            current = char
        else:
            current += char
    if current:
        words.append(current)
    return " ".join(word.lower() for word in words) or leaf.lower()


def _join_object_kinds(kinds, *, capitalize=False):
    return _join([humanize_object_kind(kind) for kind in kinds], capitalize=capitalize)


def pickable_phrase(rule, pick_mode=PICK_DIRECT, current=()):
    """Idle status-line text: what can be picked right now."""
    if rule.promotion == PROMOTION_LOCKED:
        return _tr("Solids — click any of their faces or edges.")
    if rule.promotion == PROMOTION_OFFERED and pick_mode == PICK_SOLID:
        return _tr("Solids, from the face or edge you click.")
    if rule.promotion == PROMOTION_OFFERED:
        return _tr("Solids, faces or edges — hold Alt to take the owning solid.")
    if rule.max_count == 1 and rule.types:
        types = _join_types_singular(rule.types)
        if current:
            return _tr("{types} replaces this one.", types=types)
        return _tr("{types}.", types=types)
    if rule.homogeneous and current_kind(current) and len(rule.types) > 1:
        kind = current_kind(current)
        return _tr("{types} only — one type per feature.", types=_join_types((kind,)))
    if rule.object_kinds:
        return _tr("Click an object in the 3D view or the tree.")
    if not rule.types:
        return _tr("Click an object in the 3D view or the tree.")
    return _tr("{types}.", types=_join_types(rule.types))


def placeholder_text(rule, pick_mode=PICK_DIRECT):
    """Empty-field / empty-row prompt."""
    if rule.promotion == PROMOTION_LOCKED or (
        rule.promotion == PROMOTION_OFFERED and pick_mode == PICK_SOLID
    ):
        return _tr("click a face or edge in the 3D view")
    if rule.max_count == 1 and rule.types:
        return _tr(
            "click {types} in the 3D view",
            types=_join_types_singular(rule.types, capitalize=False),
        )
    if rule.object_kinds or not rule.types:
        return _tr("click an object in the 3D view or the tree")
    return _tr(
        "click {types} in the 3D view",
        types=_join_types(rule.types, capitalize=False),
    )


def _has_shape(obj):
    if obj is None:
        return False
    if obj.isDerivedFrom("Fem::FemGeometry") or obj.isDerivedFrom("Fem::FemAnalysisImport"):
        return True
    shape = getattr(obj, "Shape", None)
    return shape is not None and not getattr(shape, "isNull", lambda: True)()


def is_alive(obj):
    """Whether a document object proxy still stands for a live object."""
    if obj is None:
        return False
    try:
        obj.Name
    except ReferenceError:
        return False
    return True


def _in_geometry_chain(geometry, obj, seen=None):
    """
    Whether *obj* is a step of the chain *geometry* is built from.

    Only the Group members count, not the whole OutList: the part an import
    was made from hangs off the import, and picking on it is exactly the
    mistake the scope check exists to catch.
    """
    seen = seen if seen is not None else set()
    for member in getattr(geometry, "Group", None) or ():
        if member is None or member.Name in seen:
            continue
        seen.add(member.Name)
        if member == obj or _in_geometry_chain(member, obj, seen):
            return True
    return False


def _in_scope(rule, obj, geometry):
    if rule.scope == "any":
        return True
    if geometry is None:
        return _has_shape(obj)
    if obj == geometry:
        return True
    # A nested imported analysis draws its own geometry and numbers its own
    # elements, so a reference on it addresses the same shape the mesh uses.
    if obj.isDerivedFrom("Fem::FemAnalysisImport"):
        return True
    return _in_geometry_chain(geometry, obj)


def _matches_object_kind(rule, obj):
    if not rule.object_kinds:
        return True
    return any(obj.isDerivedFrom(kind) for kind in rule.object_kinds)


def evaluate(
    rule,
    pick_mode,
    obj,
    sub,
    current,
    *,
    geometry=None,
    document=None,
    solids_of=None,
):
    """
    Accept(picks) | Refuse(reason) | NeedsChoice(candidates).

    picks is a list of (obj, sub) the slot should store. For max_count == 1 a
    filled slot still Accepts: the widget replaces. A full fixed-count slot
    greater than one Refuses.
    """
    if obj is None:
        return Refuse(_tr("Nothing selected."))

    # A gate can outlive what it was armed against — a closed document leaves
    # every proxy behind it dangling — and touching one raises out of the
    # selection machinery, where nothing is there to catch it.
    if not is_alive(obj) or (geometry is not None and not is_alive(geometry)):
        return Refuse(_tr("Nothing selected."))

    if document is not None and obj.Document != document:
        return Refuse(_tr("External object selection is not supported"))

    if not _in_scope(rule, obj, geometry):
        if geometry is not None:
            return Refuse(
                _tr(
                    "Pick on the geometry of the analysis, {label}.",
                    label=geometry.Label,
                )
            )
        return Refuse(_tr("Selected object is not a part."))

    # Empty types means a whole object (import picker, object-kind scopes).
    if not rule.types:
        if rule.object_kinds and not _matches_object_kind(rule, obj):
            return Refuse(
                _tr(
                    "{label} is not a {kinds}.",
                    label=obj.Label,
                    kinds=_join_object_kinds(rule.object_kinds),
                )
            )
        return _accept_stored(rule, obj, "", current, pick_mode)

    kind = shape_kind(sub)
    if kind is None:
        if rule.object_kinds or rule.allow_empty_sub:
            if rule.object_kinds and not _matches_object_kind(rule, obj):
                return Refuse(
                    _tr(
                        "{label} is not a {kinds}.",
                        label=obj.Label,
                        kinds=_join_object_kinds(rule.object_kinds),
                    )
                )
            return _accept_stored(rule, obj, "", current, pick_mode)
        return Refuse(_tr("Click a sub-element, not the whole object."))

    promoting = pick_mode == PICK_SOLID or rule.promotion == PROMOTION_LOCKED

    if promoting and rule.promotion != PROMOTION_UNAVAILABLE:
        if kind == "Vertex":
            return Refuse(_tr("A vertex cannot name a solid."))
        if kind in PROMOTABLE_KINDS:
            finder = solids_of if solids_of is not None else owning_solids
            solids = finder(obj, sub)
            if not solids:
                return Refuse(
                    _tr(
                        "{leaf} does not belong to any solid.",
                        leaf=leaf_name(sub),
                    )
                )
            if len(solids) > 1:
                return NeedsChoice([(obj, name) for name in solids], source=(obj, sub))
            return _accept_stored(rule, obj, solids[0], current, pick_mode)
        if kind == "Solid":
            return _accept_stored(rule, obj, sub, current, pick_mode)
        return Refuse(
            _tr(
                "{leaf} is a {kind} — this feature takes solids.",
                leaf=leaf_name(sub) or obj.Label,
                kind=kind.lower(),
            )
        )

    if kind not in rule.types:
        if (
            rule.promotion == PROMOTION_OFFERED
            and kind in PROMOTABLE_KINDS
            and current_kind(current) == "Solid"
        ):
            return Refuse(
                _tr(
                    "The list holds solids — hold Alt to take the solid behind {leaf}.",
                    leaf=leaf_name(sub),
                ),
                redirectable=False,
            )
        allowed = _join_types(rule.types, capitalize=False)
        return Refuse(
            _tr(
                "{leaf} is a {kind} — this feature takes {allowed} only.",
                leaf=leaf_name(sub) or obj.Label,
                kind=kind.lower(),
                allowed=allowed,
            )
        )

    return _accept_stored(rule, obj, sub, current, pick_mode)


def _accept_stored(rule, obj, sub, current, pick_mode):
    pick = (obj, sub)
    if pick in current:
        return Refuse(
            _tr("{name} is already in the list.", name=leaf_name(sub) or display_name(obj, sub)),
            redirectable=False,
        )

    kind = shape_kind(sub)
    if rule.homogeneous and kind:
        held = current_kind(current)
        if held and held != kind:
            if (
                held == "Solid"
                and kind in PROMOTABLE_KINDS
                and rule.promotion == PROMOTION_OFFERED
                and pick_mode != PICK_SOLID
            ):
                return Refuse(
                    _tr(
                        "The list holds solids — hold Alt to take the solid behind {leaf}.",
                        leaf=leaf_name(sub),
                    ),
                    redirectable=False,
                )
            # Naming both kinds is not enough: it reads as a bare mismatch and
            # leaves open whether the slot only ever takes the one it holds.
            # Say the rule, then the way out of it.
            return Refuse(
                _tr(
                    "One kind at a time: the list holds {held}, so it cannot also"
                    " take {leaf}. Clear it to collect {picked} instead.",
                    held=_PLURAL.get(held, held.lower() + "s"),
                    leaf=leaf_name(sub) or obj.Label,
                    picked=_PLURAL.get(kind, kind.lower() + "s"),
                ),
                redirectable=False,
            )

    if rule.max_count is not None and rule.max_count > 1 and len(current) >= rule.max_count:
        return Refuse(
            _tr(
                "Full at {count} — remove one to pick another.",
                count=rule.max_count,
            ),
            redirectable=False,
        )

    if (
        kind
        and kind not in rule.types
        and not (kind == "Solid" and rule.promotion != PROMOTION_UNAVAILABLE)
    ):
        return Refuse(
            _tr(
                "{leaf} is a {kind} — this feature takes {allowed} only.",
                leaf=leaf_name(sub) or obj.Label,
                kind=kind.lower(),
                allowed=_join_types(rule.types, capitalize=False),
            )
        )

    return Accept([pick])
