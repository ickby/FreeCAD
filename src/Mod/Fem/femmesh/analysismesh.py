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

"""
Mesh a whole analysis in one call.

Meshing has only ever been reached one object at a time, from the task panel of
the mesher being edited. That is the right place for setting a mesher up, but it
is no help to anything that has to put an analysis back in order - the update of
an analysis geometry throws away the meshes made against the shape it replaced,
and the user pressed one button for all of it. This is that call.
"""

__title__ = "FreeCAD FEM analysis meshing"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

from femtools.femutils import is_derived_from


class MeshReport:
    """What meshing an analysis did, in terms its caller can report to a user."""

    def __init__(self, analysis):
        self.analysis = analysis
        self.meshed = []
        self.failed = []
        self.has_meshers = False

    @property
    def label(self):
        return self.analysis.Label

    def __bool__(self):
        return not self.failed


def mesh_group_of(analysis):
    """The mesh group of *analysis*, or None if it has none."""
    if analysis is None:
        return None
    for member in analysis.Group:
        if member.isDerivedFrom("Fem::FemMeshShapeGroup"):
            return member
    return None


def meshers_of(analysis):
    """
    Every mesh generator of *analysis*, in the order the group holds them.

    A mesh group holds more than generators - refinements, groups and regions
    all sit under one - so what is meshable is asked for by type rather than
    taken to be everything present.
    """
    group = mesh_group_of(analysis)
    if group is None:
        return []
    return [
        child
        for child in group.Group
        if is_derived_from(child, "Fem::FemMeshGmsh")
        or is_derived_from(child, "Fem::FemMeshNetgen")
    ]


def tool_for(mesher):
    """The meshing tool that drives *mesher*, or None if it is not a generator."""
    if is_derived_from(mesher, "Fem::FemMeshGmsh"):
        from femmesh import gmshtools

        return gmshtools.GmshTools(mesher)

    if is_derived_from(mesher, "Fem::FemMeshNetgen"):
        from femmesh import netgentools

        return netgentools.NetgenTools(mesher)

    return None


def mesh_analysis(analysis):
    """
    Run every mesh generator of *analysis* and report what happened.

    Blocking, deliberately. Netgen meshes in a process of its own and would
    otherwise still be running when the caller moves on, which matters here more
    than it does in a task panel: an analysis that imports this one reads the
    mesh published by it, so the order in which analyses are meshed is the whole
    point of doing them together.

    A generator that throws is recorded and the rest are still meshed. One
    mesher failing on one component is no reason to leave the others empty, and
    the report is what lets the caller say which ones need looking at.
    """
    report = MeshReport(analysis)
    meshers = meshers_of(analysis)
    report.has_meshers = bool(meshers)

    for mesher in meshers:
        tool = tool_for(mesher)
        if tool is None:
            continue
        try:
            tool.run(True)
            report.meshed.append(mesher.Label)
        except Exception as error:  # noqa: BLE001 - reported, not swallowed
            report.failed.append((mesher.Label, str(error)))

    return report
