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
Bringing an analysis geometry back in step with the model it was built from.

A change to the CAD model marks the analysis geometry and stops there, because
following it costs the whole chain of geometry operations and every mesh made
against their result. This is the other half of that: what the user presses when
the cost is worth paying, in the three sizes the update comes in.
"""

__title__ = "FreeCAD FEM geometry update"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import FreeCAD

from femmesh import analysismesh
from femobjects import geometry_base
from femtools import membertools


def geometry_group_of(analysis):
    """The analysis geometry of *analysis*, or None if it builds none."""
    if analysis is None:
        return None
    groups = membertools.get_member(analysis, "Fem::GeometryGroup")
    return groups[0] if groups else None


def analysis_imports_of(analysis):
    """Every imported analysis instance held by *analysis*."""
    if analysis is None:
        return []
    return [m for m in analysis.Group if m.isDerivedFrom("Fem::FemAnalysisImport")]


def outdated_steps(group):
    """
    The steps of an analysis geometry that are waiting to follow their sources.

    Only steps are asked, never the group: the group's mark is the union of
    theirs, and updating is done to the step that knows what it reads.
    """
    if group is None:
        return []
    return [step for step in group.Group if getattr(step, "Outdated", False)]


def is_outdated(analysis):
    """Whether the geometry of *analysis* itself waits for an update."""
    group = geometry_group_of(analysis)
    return bool(group is not None and group.Outdated)


def has_stale_source(analysis):
    """
    Whether something *analysis* imports is behind, or has no mesh to import.

    This is what the third update entry repairs and the first two cannot: the
    geometry here is perfectly consistent with what it was built from, and the
    analysis that is behind is somewhere else entirely.
    """
    return any(
        imp.SourceGeometryOutdated or imp.SourceMeshMissing for imp in analysis_imports_of(analysis)
    )


def source_analyses(analysis, seen=None):
    """
    The analyses *analysis* imports, deepest first.

    Deepest first is the order an update has to run in: a source that is
    rebuilt takes the meshes of everything importing it with it, so meshing a
    caller before its source has been dealt with is work done twice. Cycles
    cannot be built through the import object, but a diamond can, so an
    analysis reached twice is only reported once.
    """
    if seen is None:
        seen = []

    for imp in analysis_imports_of(analysis):
        source = imp.Analysis
        if source is None or source in seen:
            continue
        source_analyses(source, seen)
        if source not in seen:
            seen.append(source)

    return seen


def update_geometry(analysis):
    """
    Let the analysis geometry follow the model it was built from.

    Every outdated step is asked at once. Updating half a geometry is not a
    thing a user can want: the steps form one chain, and the shape the later
    ones work on is the result of the earlier ones.

    The meshes made against the old shape are cleared by the mesh group as it
    always was - the geometry writes a new shape, its revision moves, and what
    was meshed against the old one goes. That is the price of the update, and
    the reason it is not paid on every recompute of the CAD model.
    """
    return update_group(geometry_group_of(analysis))


def update_group(group):
    """Update the steps of one analysis geometry. See update_geometry()."""
    steps = outdated_steps(group)
    for step in steps:
        geometry_base.request_update(step)

    if steps:
        group.Document.recompute()

    return steps


def update_geometry_and_mesh(analysis):
    """Follow the model, then mesh what the update emptied. Returns a report."""
    update_geometry(analysis)
    return analysismesh.mesh_analysis(analysis)


def update_with_sources(analysis):
    """
    Update every analysis this one imports as well, deepest first.

    The reach is the point and also the risk: analyses that are not on screen
    are rebuilt and remeshed here. Which ones were touched is therefore part of
    the result, so that the caller can say so rather than leave the user to
    find out.
    """
    reports = []
    for source in source_analyses(analysis):
        reports.append(update_geometry_and_mesh(source))

    # The importing analysis last: its own geometry may be behind as well, and
    # what it imports has only just been rebuilt underneath it.
    reports.append(update_geometry_and_mesh(analysis))
    return reports


def report_text(reports):
    """One line per analysis, for the report window."""
    lines = []
    for report in reports:
        if not report.has_meshers:
            lines.append(
                FreeCAD.Qt.translate(
                    "FEM", "{}: geometry updated, no mesher set up to mesh it"
                ).format(report.label)
            )
        elif report.failed:
            names = ", ".join(label for label, _ in report.failed)
            lines.append(
                FreeCAD.Qt.translate("FEM", "{}: geometry updated, meshing failed for {}").format(
                    report.label, names
                )
            )
        else:
            lines.append(
                FreeCAD.Qt.translate("FEM", "{}: geometry and mesh updated").format(report.label)
            )
    return "\n".join(lines)
