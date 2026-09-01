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
Snapshot of the 3D selection a create-command hands to a newly opened panel.

stash_for(name) is called by the command, keyed by document name plus object
name. take(obj) returns the picks once. Nothing writes a stash on the edit
path, so a double-click into an existing object finds nothing.
"""

__title__ = "FEM reference selection handoff"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import FreeCAD

_STASH = {}
_OBSERVER = None


def _key(doc_name, obj_name):
    return (doc_name, obj_name)


def _ensure_observer():
    global _OBSERVER
    if _OBSERVER is not None:
        return
    _OBSERVER = _DocumentObserver()
    FreeCAD.addDocumentObserver(_OBSERVER)


class _DocumentObserver:
    """Drop a stash whose document went away, so a later same-named object
    in a new document cannot inherit it."""

    def slotDeletedDocument(self, doc):
        gone = [key for key in _STASH if key[0] == doc.Name]
        for key in gone:
            _STASH.pop(key, None)


def stash_for(obj_name, doc_name=None):
    """
    Snapshot Gui.Selection.getSelectionEx('', 0) against this object name.

    Unresolved, so a click reported against a group keeps the whole way down
    to what was picked: resolve_pick() reads it when the panel takes the stash
    over. The object does not need to exist yet: only the name is stored.
    """
    import FreeCADGui

    _ensure_observer()
    if doc_name is None:
        active = FreeCAD.ActiveDocument
        if active is None:
            return
        doc_name = active.Name

    picks = []
    for sel in FreeCADGui.Selection.getSelectionEx("", 0):
        for sub in sel.SubElementNames or ("",):
            picks.append((sel.Object, sub))
    _STASH[_key(doc_name, obj_name)] = picks


def take(obj):
    """Return the stashed picks for *obj* and forget them. Empty if none."""
    if obj is None or obj.Document is None:
        return []
    return _STASH.pop(_key(obj.Document.Name, obj.Name), [])


def clear():
    """Drop every stash. Tests use this so cases cannot leak into each other."""
    _STASH.clear()
