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
Task watchers offering the geometry update, when there is one to offer.

An analysis geometry that is behind the model it was built from is a state the
user has to be told about and then act on, and the task panel is where FreeCAD
puts work that is waiting to be done. A watcher there appears on its own when
there is something to update and is simply absent the rest of the time, which
is the whole of the interface: nothing to read, nothing to dismiss, and the
update itself one press away in the panel that exists for pressing things.

Deliberately not in the view panel. That panel is for looking at an analysis -
what is drawn, in what colour, clipped where - and none of it changes the model.
A button that rebuilds the geometry and throws away the meshes does not belong
among controls that only change the view.
"""

__title__ = "FreeCAD FEM geometry update task watchers"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import FreeCAD
import FreeCADGui
import FemGui


class _UpdateWatcher:
    """
    One state worth acting on, its explanation, and the updates that repair it.

    The attributes are read by FreeCAD when the watcher is installed - title and
    icon head the box, commands become the rows in it - so they are plain data
    rather than properties. The rows grey themselves out through the commands'
    own IsActive, which is why a watcher can offer more than one and let the
    user pick the size of the update they want.
    """

    def __init__(self, title, icon, commands, condition):
        self.title = title
        self.icon = icon
        self.commands = commands
        self._condition = condition

    def shouldShow(self):
        analysis = _active_analysis()
        if analysis is None:
            return False
        try:
            from femtools import geometryupdate

            return bool(self._condition(geometryupdate, analysis))
        except (AttributeError, ReferenceError, RuntimeError):
            # A document closing under us is not a reason to break the panel.
            return False


def _active_analysis():
    """The analysis on screen, or None if there is none in the active document."""
    if FreeCAD.ActiveDocument is None:
        return None
    analysis = FemGui.getActiveAnalysis()
    if analysis is None or analysis.Document != FreeCAD.ActiveDocument:
        return None
    return analysis


def watchers():
    """The watchers this workbench installs, in the order they should appear."""
    return [
        _UpdateWatcher(
            FreeCAD.Qt.translate("FEM", "Geometry is behind the model"),
            "FEM_GeometryUpdateMesh",
            ["FEM_GeometryUpdateMesh", "FEM_GeometryUpdate"],
            lambda module, analysis: module.is_outdated(analysis),
        ),
        # Kept apart from the first: an analysis whose own geometry is current
        # and whose source is not cannot be helped by updating itself, and
        # offering it the entries that would is worse than offering nothing.
        _UpdateWatcher(
            FreeCAD.Qt.translate("FEM", "An imported analysis is behind"),
            "FEM_GeometryUpdateLinked",
            ["FEM_GeometryUpdateLinked"],
            lambda module, analysis: module.has_stale_source(analysis),
        ),
    ]


def install():
    """Offer the updates in the task panel for as long as this workbench is up."""
    FreeCADGui.Control.addTaskWatcher(watchers())


def remove():
    FreeCADGui.Control.clearTaskWatcher()
