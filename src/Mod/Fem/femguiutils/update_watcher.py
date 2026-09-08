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
What the FEM workbench reports in the task panel, and what it offers to do.

Two watchers, one per stage. They are separate because the stages are: a user
reading that nothing meshes this geometry yet is being told about the mesh, not
about the geometry above it. Each is absent while it has nothing to report, so
an analysis in order leaves the task panel empty.

Deliberately not in the view panel. That panel is for looking at an analysis -
what is drawn, in what colour, clipped where - and none of it changes the model.
A button that rebuilds the geometry and throws away the meshes does not belong
among controls that only change the view.
"""

__title__ = "FreeCAD FEM task panel watchers"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import FreeCAD
import FreeCADGui
import FemGui

from PySide import QtCore

from .notifications import Action, Notification, NotificationWatcher


def active_analysis():
    """The analysis on screen, or None if there is none in the active document."""
    if FreeCAD.ActiveDocument is None:
        return None
    analysis = FemGui.getActiveAnalysis()
    if analysis is None or analysis.Document != FreeCAD.ActiveDocument:
        return None
    return analysis


def _tr(text):
    return FreeCAD.Qt.translate("FEM", text)


def _geometry_notifications():
    from femtools import geometryupdate

    return [
        Notification(
            key="geometry-missing",
            icon="FEM_StateGeometryMissing",
            message=_tr("This analysis has no geometry yet."),
            aside=_tr("Import a part or a sketch to build the analysis geometry from."),
            condition=lambda analysis: not geometryupdate.has_geometry(analysis),
            actions=[Action(command="FEM_GeometryImport")],
        ),
        Notification(
            key="geometry-outdated",
            icon="FEM_StateGeometryOutdated",
            message=_tr("The geometry is behind the model it was built from."),
            aside=_tr("Updating rebuilds the chain and clears the mesh."),
            condition=geometryupdate.is_outdated,
            actions=[
                Action(command="FEM_GeometryUpdate"),
                Action(command="FEM_GeometryUpdateMesh"),
            ],
        ),
        Notification(
            key="source-behind",
            icon="FEM_StateSourceBehind",
            message=_tr("An analysis imported here is behind its model."),
            aside=_tr("This geometry is current; the one it is built on is not."),
            condition=geometryupdate.has_stale_source,
            actions=[Action(command="FEM_GeometryUpdateLinked")],
        ),
    ]


def _mesh_notifications():
    from femmesh import analysismesh
    from femtools import geometryupdate

    def mesh_now(analysis):
        report = analysismesh.mesh_analysis(analysis)
        if report.failed:
            names = ", ".join(label for label, _ in report.failed)
            FreeCAD.Console.PrintError(f"Meshing failed for {names}\n")

    return [
        Notification(
            key="mesh-missing",
            icon="FEM_StateMeshMissing",
            message=_tr("Nothing meshes this geometry yet."),
            condition=lambda analysis: (
                geometryupdate.has_geometry(analysis) and not analysismesh.has_meshers(analysis)
            ),
            actions=[
                # Short labels on purpose: the sentence above already says what
                # these do, and the menu wording ("Mesh From Shape by Gmsh")
                # does not fit a docked panel. Everything else about the button
                # - icon, tooltip, whether it can be pressed - is the command's.
                Action(command="FEM_MeshGmshFromShape", text=_tr("Gmsh")),
                Action(command="FEM_MeshNetgenFromShape", text=_tr("Netgen")),
            ],
        ),
        Notification(
            key="mesh-cleared",
            icon="FEM_StateMeshCleared",
            message=_tr("The mesh was cleared when the geometry was updated."),
            aside=_tr("The mesher and its settings were kept."),
            condition=lambda analysis: (
                analysismesh.has_meshers(analysis) and analysismesh.mesh_is_empty(analysis)
            ),
            # No command meshes a whole analysis - there is a function for it,
            # and inventing a command to hang a button on would be the tail
            # wagging the dog.
            actions=[Action(text=_tr("Mesh now"), icon="FEM_StateMeshCleared", run=mesh_now)],
        ),
    ]


def watchers():
    """The watchers this workbench installs, in the order they should appear."""
    return [
        NotificationWatcher(
            _tr("Geometry"), "fem-post-geo-box", _geometry_notifications(), active_analysis
        ),
        # A neutral mesh icon rather than one mesher's: the box is about the
        # stage, and the analysis may be meshed by either of them.
        NotificationWatcher(
            _tr("Mesh"), "fem-femmesh-from-shape", _mesh_notifications(), active_analysis
        ),
    ]


class _Coalescer:
    """
    Turns a burst of document events into one refresh.

    A recompute delivers a change for every object it touches, and every one of
    them asks the same question of the same analysis. Answering once, at the
    end of the event loop turn, is the difference between a few reads and a few
    hundred.
    """

    def __init__(self, refresh):
        self._refresh = refresh
        self._pending = False

    def request(self, *args):
        if self._pending:
            return
        self._pending = True
        QtCore.QTimer.singleShot(0, self._run)

    def _run(self):
        self._pending = False
        self._refresh()


class _AppObserver:
    """
    What the watchers report follows from a recompute - a geometry falls behind,
    an update clears a mesh - and FreeCAD does not re-ask a task watcher for
    that. Without this the panel keeps whatever it was showing until the user
    happens to click something, which for a box that appears and disappears on
    its own is the difference between useful and untrustworthy.
    """

    def __init__(self, coalescer):
        self._request = coalescer.request

    def slotCreatedObject(self, obj):
        self._request()

    def slotDeletedObject(self, obj):
        self._request()

    def slotChangedObject(self, obj, prop):
        self._request()

    def slotRecomputedDocument(self, doc):
        self._request()

    def slotActivateDocument(self, doc):
        self._request()

    def slotFinishRestoreDocument(self, doc):
        self._request()

    def slotDeletedDocument(self, doc):
        self._request()


class _GuiObserver:
    """
    The analysis on screen changing is a Gui event, not a document one.

    Deliberately without slotChangedObject and slotBeforeChangeObject, as the
    view panel's observer is and for the same reason: those two Gui slots ask
    the view provider for a property name in C++ before they call Python, and
    during ViewProviderFemMesh construction that reads property data before
    BackfaceCulling has been registered - which fails the creation of every FEM
    mesh object with "Cannot add static property". The App observer above
    carries the property changes; this one only needs the active analysis.
    """

    def __init__(self, coalescer):
        self._request = coalescer.request

    def slotActiveFemAnalysisUpdated(self, analysis):
        self._request()

    def slotDeletedDocument(self, guidoc):
        self._request()


_installed = []
_observers = []


def refresh():
    """Bring every installed watcher, and the box around it, up to date."""
    for watcher in _installed:
        watcher.refresh()


def install():
    """
    Report the analysis' state for as long as this workbench is up.

    Installing twice is not additive and not harmless: the task view appends a
    stretch after the widgets it is given, so a second set arrives below it and
    the panel ends up bottom-aligned. Since the workbench pairs this with
    remove(), a second call is a mistake rather than a request.
    """
    if _installed:
        return

    _installed[:] = watchers()
    FreeCADGui.Control.addTaskWatcher(_installed)

    coalescer = _Coalescer(refresh)
    app_observer = _AppObserver(coalescer)
    gui_observer = _GuiObserver(coalescer)
    FreeCAD.addDocumentObserver(app_observer)
    FreeCADGui.addDocumentObserver(gui_observer)
    _observers[:] = [app_observer, gui_observer]


def remove():
    if _observers:
        FreeCAD.removeDocumentObserver(_observers[0])
        FreeCADGui.removeDocumentObserver(_observers[1])
        _observers.clear()
    _installed.clear()
    FreeCADGui.Control.clearTaskWatcher()
