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

__title__ = "Geometry a mesh object meshes, resolved from its component assignment"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

## @package meshcomponents
#  \ingroup FEM
#  \brief resolve the Components assignment of a mesh object into a shape to mesh

import FreeCAD
from FreeCAD import Console

import Fem
import Part

COMPONENT_PREFIX = "Component"


def component_index(subname):
    """1-based index of a ComponentN subname, None for anything else."""
    if not subname.startswith(COMPONENT_PREFIX):
        return None
    try:
        return int(subname[len(COMPONENT_PREFIX) :])
    except ValueError:
        return None


def component_name(index):
    """Subname of a component from its 1-based index."""
    return f"{COMPONENT_PREFIX}{index}"


def split_element_name(name):
    """Entity type and 1-based index of a name like Face12, (None, 0) if malformed."""
    for prefix in ("Solid", "Face", "Edge", "Vertex"):
        if name.startswith(prefix) and name[len(prefix) :].isdigit():
            return prefix, int(name[len(prefix) :])
    return None, 0


def mesh_group(obj):
    """Mesh group a mesh object belongs to, None outside the component workflow."""
    group = obj.getParentGroup()
    if group is not None and group.isDerivedFrom("Fem::FemMeshShapeGroup"):
        return group
    return None


def geometry_of(obj):
    """
    FemGeometry a mesh object works on.

    Taken from its own assignment, falling back to the geometry of its mesh
    group, which is what a mesh object without any component selected still
    has to offer in the picker. None for the legacy Shape workflow.
    """
    comps = getattr(obj, "Components", None)
    if comps and comps[0] is not None:
        return comps[0]

    group = mesh_group(obj)
    if group is not None:
        shape = group.Shape
        if shape is not None and shape.isDerivedFrom("Fem::FemGeometry"):
            return shape
    return None


def component_count(geometry):
    """Number of components of a geometry, 0 if there is none."""
    return geometry.getComponentCount() if geometry is not None else 0


def component_owners(obj):
    """Mesh object meshing each component of the group geometry, by 1-based index."""
    group = mesh_group(obj)
    return group.getComponentOwners() if group is not None else {}


def meshes_all(obj):
    """
    True if the object meshes the whole geometry.

    An assignment without sub-values is what the Components property spells
    "all components", which keeps following the geometry as it grows.
    """
    comps = getattr(obj, "Components", None)
    if not comps or comps[0] is None:
        return False
    return not (len(comps) > 1 and comps[1])


def selected_components(obj):
    """1-based component indices a mesh object meshes."""
    comps = getattr(obj, "Components", None)
    if not comps or comps[0] is None:
        return []

    if meshes_all(obj):
        return list(range(1, component_count(comps[0]) + 1))

    indices = []
    for sub in comps[1]:
        index = component_index(sub)
        if index is not None:
            indices.append(index)
    return sorted(indices)


def assign_all(obj, geometry):
    """Let a mesh object mesh the whole geometry, components added later included."""
    previous = selected_components(obj)
    obj.Components = (geometry, [])
    # Gaining components leaves the mesh of the others valid, so nothing to do
    trim_mesh(obj, geometry, [i for i in previous if i not in selected_components(obj)])


def assign_components(obj, geometry, indices):
    """
    Write a component selection onto a mesh object.

    The components are always spelled out, even when they are all of them,
    because "all components" is a mode of its own that keeps following the
    geometry. An empty selection drops the geometry link, since a mesh object
    that meshes nothing must not claim components either.
    """
    indices = sorted(set(indices))
    previous = selected_components(obj)

    if indices:
        obj.Components = (geometry, [component_name(i) for i in indices])
    else:
        obj.Components = None

    trim_mesh(obj, geometry, [i for i in previous if i not in indices])


def component_element_names(geometry, index):
    """
    Every geometry entity name a component covers, its sub-entities included.

    Mesh groups are named after these entities, which is what makes the mesh of
    a single component identifiable. Components are topologically separate, so
    no entity of one of them shows up in another.
    """
    shape = geometry.Shape
    names = set()
    for toplevel in geometry.getToplevelElements(index - 1):
        names.add(toplevel)
        element = shape.getElement(toplevel)
        for sub in element.Solids + element.Faces + element.Edges + element.Vertexes:
            found = shape.findSubShape(sub)
            if found and found[1] > 0:
                names.add(f"{found[0]}{found[1]}")
    return names


def trim_mesh(obj, geometry, lost):
    """
    Take the mesh of the given components out of the mesh of an object.

    A mesh carries a group per geometry entity, so the elements of components
    that moved to another mesh object can be found and removed while the mesh
    of the components this object keeps stays as it is. Leaving them in would
    make the merged mesh of the group overlap where the new owner meshes them.
    """
    if not lost:
        return

    current = getattr(obj, "FemMesh", None)
    if current is None or current.NodeCount == 0:
        return

    names = set()
    if geometry is not None:
        for index in lost:
            names |= component_element_names(geometry, index)

    ids = []
    for group in current.Groups:
        if current.getGroupName(group) in names:
            ids.extend(current.getGroupElements(group))

    if not ids:
        # Nothing tells which elements belong to the lost components, so the
        # whole mesh is suspect
        clear_mesh(obj)
        return

    # The mesh of a property is handed out read-only
    mesh = current.copy()
    removed = mesh.removeElements(ids)
    obj.FemMesh = mesh
    lost_names = ", ".join(component_name(i) for i in sorted(lost))
    Console.PrintMessage(
        f"{obj.Label}: removed {removed} elements of {lost_names} from the mesh, "
        "the mesh of the other components was kept\n"
    )


def clear_mesh(obj):
    """Throw the whole mesh of an object away, for when no part of it can be kept."""
    mesh = getattr(obj, "FemMesh", None)
    if mesh is None or mesh.NodeCount == 0:
        return

    obj.FemMesh = Fem.FemMesh()
    Console.PrintMessage(
        f"{obj.Label}: components changed, the mesh was dropped, run the mesher again\n"
    )


def take_over(obj, indices, owners=None):
    """
    Move components to a mesh object, dropping them from their current owner.

    A sibling meshing all components is expanded into what it keeps, so that
    the group ends up with one owner per component.
    """
    if owners is None:
        owners = component_owners(obj)

    for owner in {owners.get(i) for i in indices} - {None, obj}:
        remaining = [i for i, m in owners.items() if m == owner and i not in indices]
        assign_components(owner, geometry_of(owner), remaining)


def assign_unclaimed(obj):
    """
    Give a mesh object the components of its group no other one meshes.

    A first mesh object ends up meshing the whole geometry, a later one only
    what is left over, and nothing at all once the geometry is fully covered.
    """
    geometry = geometry_of(obj)
    if geometry is None:
        return

    owners = component_owners(obj)
    count = component_count(geometry)
    free = [i for i in range(1, count + 1) if owners.get(i) in (None, obj)]
    if len(free) == count:
        assign_all(obj, geometry)
    else:
        assign_components(obj, geometry, free)


class ComponentGeometry:
    """
    Geometry a mesh object meshes, resolved into a shape a mesher can export.

    A mesh object either assigns components of a FemGeometry through the
    Components property, where an empty sub-list means all of them, or links a
    plain Part feature through the legacy Shape property.

    Meshing a subset of the components exports a shape of its own, whose entity
    numbering has nothing to do with the geometry it was cut from. Mesh groups
    and references are named after the geometry, so local_to_global maps the
    mesher-local names back before they are used.
    """

    def __init__(self, obj, label="Mesh"):
        self.obj = obj
        self.label = label

        # geometry link
        self.geometry_obj = None
        self.component_subs = []
        self.part_obj = None

        # resolved shapes, filled by resolve()
        self.global_shape = None
        self.export_shape = None
        self.local_to_global = {}

        # Netgen and legacy mesh objects have no Components property
        comps = getattr(obj, "Components", None)
        if comps:
            # PropertyLinkSub -> (DocumentObject, [subnames])
            self.geometry_obj = comps[0]
            self.component_subs = list(comps[1]) if len(comps) > 1 else []
            self.part_obj = self.geometry_obj
        else:
            self.part_obj = obj.Shape

    def resolve(self):
        """Fill global_shape, export_shape and local_to_global."""
        self.local_to_global = {}

        if self.part_obj is None:
            raise ValueError(
                f"{self.label}: mesh object '{self.obj.Name}' has no geometry to mesh, "
                "select the components it should mesh"
            )

        if self.geometry_obj is None:
            # Legacy Shape link (Part feature etc.)
            self.global_shape = self.part_obj.getPropertyOfGeometry()
            self.export_shape = self.global_shape
            self._map_identity()
            return

        # Hold ONE global TopoShape — findSubShape is cache-backed per instance
        self.global_shape = self.geometry_obj.Shape
        if not self.component_subs:
            self.export_shape = self.global_shape
            self._map_identity()
            return

        shapes = []
        for name in self.toplevel_names():
            shape = self.global_shape.getElement(name)
            if shape is not None and not shape.isNull():
                shapes.append(shape)

        if not shapes:
            Console.PrintError(
                f"{self.label}: Components sub-selection produced no shapes; "
                "falling back to full geometry.\n"
            )
            self.export_shape = self.global_shape
            self._map_identity()
            return

        self.export_shape = shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)
        self._map_sub_selection()

    def placed_export_shape(self):
        """Export shape moved to where the geometry sits in the document."""
        if self.export_shape is None:
            self.resolve()

        # A sub-shape carries its own location inside the geometry, so what
        # moves the geometry in the document is prepended to that rather than
        # replacing it. Taken relative to the placement of the whole shape,
        # the frame the sub-shape locations live in.
        placement = self.part_obj.getGlobalPlacement().multiply(
            self.global_shape.Placement.inverse()
        )
        shape = self.export_shape.copy()
        shape.Placement = placement.multiply(shape.Placement)
        return shape

    def toplevel_names(self):
        """Toplevel element names of the assigned components."""
        if self.geometry_obj is None:
            return []

        names = []
        if not self.component_subs:
            for i in range(self.geometry_obj.getComponentCount()):
                names.extend(self.geometry_obj.getToplevelElements(i))
            return names

        for sub in self.component_subs:
            index = component_index(sub)
            if index is None:
                # A toplevel element assigned directly
                names.append(sub)
            else:
                # Component indices are 1-based, FemGeometry is 0-based
                names.extend(self.geometry_obj.getToplevelElements(index - 1))
        return names

    def global_name(self, local_name):
        """Geometry name of a mesher-local entity name."""
        if self.export_shape is None:
            self.resolve()
        return self.local_to_global.get(local_name, local_name)

    def local_name(self, global_name):
        """Mesher-local name of a geometry entity, None if it is not exported."""
        if self.export_shape is None:
            self.resolve()
        for local, name in self.local_to_global.items():
            if name == global_name:
                return local
        return None

    def _map_identity(self):
        """Full-geometry export: local mesher indices already match global names."""
        shape = self.export_shape
        for prefix, subs in (
            ("Solid", shape.Solids),
            ("Face", shape.Faces),
            ("Edge", shape.Edges),
            ("Vertex", shape.Vertexes),
        ):
            for i in range(len(subs)):
                self.local_to_global[f"{prefix}{i + 1}"] = f"{prefix}{i + 1}"

    def _map_sub_selection(self):
        """Map mesher-local entity names to global names via findSubShape."""
        global_ts = self.global_shape

        for prefix, subs in (
            ("Solid", self.export_shape.Solids),
            ("Face", self.export_shape.Faces),
            ("Edge", self.export_shape.Edges),
            ("Vertex", self.export_shape.Vertexes),
        ):
            for i, sub in enumerate(subs):
                local_name = f"{prefix}{i + 1}"
                # findSubShape raises when the sub-shape is not part of the
                # global shape, which is exactly the unmappable case below.
                try:
                    found = global_ts.findSubShape(sub)
                except (ValueError, RuntimeError, FreeCAD.Base.FreeCADError):
                    found = None
                if found and found[1] > 0:
                    self.local_to_global[local_name] = f"{found[0]}{found[1]}"
                else:
                    Console.PrintWarning(
                        f"{self.label}: could not map local {local_name} to global geometry\n"
                    )
