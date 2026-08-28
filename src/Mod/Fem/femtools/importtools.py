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

"""Helpers for analysis import reference paths."""

__title__ = "FEM analysis import tools"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"


def is_import_group(member):
    """Whether *member* is a container an analysis keeps its imports in."""
    if not member.isDerivedFrom("App::DocumentObjectGroup"):
        return False
    if any(child.isDerivedFrom("Fem::FemAnalysisImport") for child in member.Group):
        return True
    # Internal names are unique across the document, so the container of the
    # second analysis in one is called Imports001. An empty container carries
    # nothing else to recognize it by.
    return member.Name.rstrip("0123456789") == "Imports"


def find_import_group(analysis):
    """Return the Imports container group of *analysis*, if any."""
    groups = [member for member in analysis.Group if is_import_group(member)]
    if not groups:
        return None
    # One that already holds imports is the one to settle on, so that an
    # analysis left with several by an earlier version keeps the populated one.
    for group in groups:
        if group.Group:
            return group
    return groups[0]


def wire_import(analysis, import_obj):
    """
    Register *import_obj* in the analysis Imports container.

    Creates the container when the analysis has none yet, and folds away the
    spare containers an earlier version created alongside it.
    """
    import ObjectsFem

    group = find_import_group(analysis)
    if group is None:
        group = ObjectsFem.makeImportGroup(analysis.Document)
        analysis.addObject(group)
    if import_obj not in group.Group:
        group.addObject(import_obj)
    _fold_spare_import_groups(analysis, group)
    return group


def _fold_spare_import_groups(analysis, group):
    """Move the imports of every other container into *group* and drop the empties."""
    for member in list(analysis.Group):
        if member is group or not is_import_group(member):
            continue
        for child in list(member.Group):
            member.removeObject(child)
            group.addObject(child)
        if not member.Group:
            analysis.Document.removeObject(member.Name)


def analysis_has_imports(analysis):
    """Return True if *analysis* contains at least one AnalysisImport."""
    for member in analysis.Group:
        if member.isDerivedFrom("Fem::FemAnalysisImport"):
            return True
        if member.isDerivedFrom("App::DocumentObjectGroup"):
            for child in member.Group:
                if child.isDerivedFrom("Fem::FemAnalysisImport"):
                    return True
    return False


def validate_imports(analysis):
    """
    Validate that every import in *analysis* can be resolved for solving.

    Raises FreeCADError when a source analysis has no geometry or mesh.
    """
    from . import importmembers

    importmembers.validate(analysis)
