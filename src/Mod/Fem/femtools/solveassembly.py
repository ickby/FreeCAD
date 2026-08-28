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

"""Build a single solve mesh from native geometry and placed analysis imports."""

__title__ = "FEM solve assembly"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import Fem


class AssemblyGeometry:
    """
    Stand-in for the geometry a mesh object links to.

    A mesh object carries its geometry as a link, so ``mesh.Shape`` is an object
    and the shape itself is ``mesh.Shape.Shape``. Both the Elmer writer and
    MeshSetsGetter read it that way, so the assembly has to offer the same two
    steps rather than the shape directly.
    """

    def __init__(self, name, shape):
        self.Name = name
        self.Label = name
        self.Shape = shape


class SolveAssembly:
    """Ephemeral mesh object returned by build()."""

    def __init__(self, name, fem_mesh, shape, cell_sources, node_sources):
        self.Name = name
        self.Label = name
        self.FemMesh = fem_mesh
        self.Shape = AssemblyGeometry(f"{name}_Geometry", shape)
        self.CellSources = cell_sources
        self.NodeSources = node_sources
        self.Suppressed = False
        self._nodes_by_assembly_id = None

    def path_of_cell(self, element_id):
        """Import path the cell with *element_id* came from, or an empty string."""
        index = element_id - 1
        if 0 <= index < len(self.CellSources):
            return self.CellSources[index]
        return ""

    def source_node_of(self, node_id):
        """(import path, node ID in the source mesh) for an assembly node."""
        if self._nodes_by_assembly_id is None:
            self._nodes_by_assembly_id = {
                assembly_id: (path, source_id)
                for path, mapping in self.NodeSources.items()
                for source_id, assembly_id in mapping.items()
            }
        return self._nodes_by_assembly_id.get(node_id, ("", None))


def build(analysis):
    """Return a duck-typed mesh object for solver input generation."""
    mesh, shape, sources, node_sources = Fem.buildSolveAssembly(analysis)
    return SolveAssembly(
        f"{analysis.Name}_Assembly",
        mesh,
        shape,
        list(sources),
        {path: dict(nodes) for path, nodes in node_sources.items()},
    )
