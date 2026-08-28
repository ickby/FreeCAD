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

"""Transient views of analysis members with import reference translation."""

__title__ = "FEM analysis import members"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

from FreeCAD import Base

from . import femutils
from . import importtools

_UNSET = object()


class MemberView:
    """Transparent proxy that rewrites References and Name for import resolution."""

    __slots__ = ("_source", "_import_chain", "_name", "_references")

    def __init__(self, source, import_chain=(), name=None, references=_UNSET):
        self._source = source
        self._import_chain = tuple(import_chain)
        self._name = name
        self._references = references

    @property
    def Name(self):
        if self._name is not None:
            return self._name
        return self._source.Name

    @property
    def References(self):
        if self._references is _UNSET:
            return _translate_references(self._import_chain, self._source)
        return self._references

    def __getattr__(self, name):
        return getattr(self._source, name)

    def __bool__(self):
        return bool(self._source)

    def isDerivedFrom(self, t):
        return self._source.isDerivedFrom(t)

    def hasExtension(self, name):
        return self._source.hasExtension(name)


def _path_prefix(import_chain):
    if not import_chain:
        return ""
    return ".".join(imp.Name for imp in import_chain) + "."


def translate_reference(import_chain, obj, sub):
    """
    Map a reference on a source member to (outer_import, dotted_path).

    *import_chain* lists imports outermost first.
    """
    if not import_chain:
        return obj, sub
    if not sub:
        raise Base.FreeCADError("FEM: empty element name in import reference")

    # A member of an imported analysis may itself reference an import of that
    # analysis. Such a subname is relative to that inner import, so its name is
    # part of the path even though the import is not in the chain we walked.
    if obj is not None and obj.isDerivedFrom("Fem::FemAnalysisImport"):
        sub = f"{obj.Name}.{sub}"

    outer = import_chain[0]
    prefix = _path_prefix(import_chain[1:])
    return outer, f"{prefix}{sub}" if prefix else sub


def _references_empty(refs):
    if not refs:
        return True
    return all(not subs for _obj, subs in refs)


def _expand_empty_material_refs(import_chain):
    """Empty inherited material covers this import's toplevel elements only."""
    if not import_chain:
        return []

    src_geom = femutils.get_reference_geometry(import_chain[-1].Analysis)
    if src_geom is None:
        return []

    outer = import_chain[0]
    prefix = _path_prefix(import_chain[1:])
    flat_subs = []
    for index in range(src_geom.getComponentCount()):
        for name in src_geom.getToplevelElements(index):
            flat_subs.append(f"{prefix}{name}" if prefix else name)

    if not flat_subs:
        return []
    return [(outer, flat_subs)]


def _translate_references(import_chain, member):
    if not hasattr(member, "References"):
        return member.References

    refs = member.References
    if _references_empty(refs):
        if femutils.is_derived_from(member, "Fem::MaterialCommon") or femutils.is_derived_from(
            member, "Fem::MaterialReinforced"
        ):
            return _expand_empty_material_refs(import_chain)
        return refs

    translated = []
    for obj, subs in refs:
        flat_subs = []
        for sub in subs:
            _, flat = translate_reference(import_chain, obj, sub)
            flat_subs.append(flat)
        translated.append((import_chain[0], flat_subs))
    return translated


def _member_view_name(import_chain, source):
    if not import_chain:
        return source.Name
    prefix = "_".join(imp.Name for imp in import_chain)
    return f"{prefix}_{source.Name}"


def _wrap_member(import_chain, member):
    name = _member_view_name(import_chain, member)
    refs = _translate_references(import_chain, member)
    return MemberView(member, import_chain=import_chain, name=name, references=refs)


def collect_imports(analysis):
    """
    The imports of *analysis*, each listed once.

    An import sits either directly in the analysis or in a container group
    inside it; imports of an imported analysis are not included.
    """
    imports = []
    seen = set()

    def add(imp):
        if imp is None or imp.Name in seen:
            return
        seen.add(imp.Name)
        imports.append(imp)

    for member in analysis.Group:
        if member.isDerivedFrom("Fem::FemAnalysisImport"):
            add(member)
        elif member.isDerivedFrom("App::DocumentObjectGroup"):
            for child in member.Group:
                if child.isDerivedFrom("Fem::FemAnalysisImport"):
                    add(child)

    return imports


def _source_members(source_analysis, fem_type):
    from . import membertools

    return membertools.get_member(source_analysis, fem_type)


def is_suppressed(import_chain, member):
    """
    Whether *member* is switched off for the instance chain leading to it.

    *import_chain* lists the imports outermost first, the innermost one being
    the instance *member* belongs to. An instance names a member of a nested
    instance by the path to it, so switching a member off in one instance
    leaves the other instances of the same analysis alone.
    """
    for index, imp in enumerate(import_chain):
        suppressed = getattr(imp, "SuppressedMembers", None) or []
        if not suppressed:
            continue
        prefix = "".join(f"{inner.Name}." for inner in import_chain[index + 1 :])
        if f"{prefix}{member.Name}" in suppressed:
            return True
    return False


def inherited_members(analysis, fem_type):
    """Yield MemberView proxies for members inherited from imported analyses."""
    result = []

    def walk(current_analysis, chain):
        for imp in collect_imports(current_analysis):
            if imp in chain:
                continue
            new_chain = chain + (imp,)
            src = imp.Analysis
            if src is None:
                continue
            for member in _source_members(src, fem_type):
                if is_suppressed(new_chain, member):
                    continue
                result.append(_wrap_member(new_chain, member))
            walk(src, new_chain)

    walk(analysis, ())
    return result


def validate(analysis):
    """Raise FreeCADError when an import source is unusable."""

    def check_sources(current_analysis, chain):
        for imp in collect_imports(current_analysis):
            if imp in chain:
                continue
            src = imp.Analysis
            if src is None:
                raise Base.FreeCADError(f"FEM: import {imp.Label} has no source analysis")
            src_geom = femutils.get_reference_geometry(src)
            if src_geom is None or src_geom.Shape.isNull():
                raise Base.FreeCADError(
                    f"FEM: source analysis of import {imp.Label} has no geometry"
                )
            # An analysis that only places other analyses has no mesh of its
            # own; the meshes it contributes come from those.
            has_mesh = importtools.analysis_has_imports(src) or any(
                m.isDerivedFrom("Fem::FemMeshShapeGroup") and not m.Suppressed for m in src.Group
            )
            if not has_mesh:
                raise Base.FreeCADError(f"FEM: source analysis of import {imp.Label} has no mesh")
            check_sources(src, chain + (imp,))

    check_sources(analysis, ())
