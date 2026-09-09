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


def _run_in_progress():
    from femtools import analysisrun

    return analysisrun.active()


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
            condition=lambda analysis: (
                not _run_in_progress() and geometryupdate.is_outdated(analysis)
            ),
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


def _running(analysis):
    """The run in progress on *analysis*, or None."""
    from femtools import analysisrun

    run = analysisrun.current()
    if run is None or not run.running or not run.touches(analysis):
        return None
    return run


def _failed(analysis):
    """The run that ended with failures on *analysis* and has not been seen yet."""
    from femtools import analysisrun

    run = analysisrun.current()
    if run is None or run.running or not run.failures or not run.touches(analysis):
        return None
    return run


def _running_text(analysis):
    run = _running(analysis)
    if run is None:
        return ""
    step = run.current
    at, total = run.position
    if total > 1:
        return _tr("Meshing {} ({} of {})").format(step.label if step else "", at, total)
    return _tr("Meshing {}").format(step.label if step else "")


def _elapsed_text(analysis):
    """How long the run has been going, as a clock rather than a number."""
    run = _running(analysis)
    if run is None:
        return ""
    seconds = int(run.elapsed)
    if seconds >= 3600:
        return "{}:{:02d}:{:02d}".format(seconds // 3600, (seconds % 3600) // 60, seconds % 60)
    return "{}:{:02d}".format(seconds // 60, seconds % 60)


def _failed_text(analysis):
    run = _failed(analysis)
    if run is None:
        return ""
    names = ", ".join(step.label for step, _ in run.failures)
    return _tr("Meshing failed: {}").format(names)


def _mesh_notifications():
    from femmesh import analysismesh
    from femtools import analysisrun, geometryupdate

    def mesh_now(analysis):
        analysisrun.start(geometryupdate.mesh_steps(analysis))

    def cancel(analysis):
        run = _running(analysis)
        if run is not None:
            run.cancel()

    def open_mesher(analysis):
        run = _failed(analysis)
        if run is None:
            return
        mesher = getattr(run.failures[0][0], "mesher", None)
        if mesher is not None:
            # Where the log of the run that failed is waiting, and where the
            # settings that caused it can be changed.
            FreeCADGui.ActiveDocument.setEdit(mesher)

    def acknowledge(analysis):
        analysisrun.clear()

    return [
        Notification(
            key="mesh-running",
            icon="FEM_StateMeshMissing",
            message=_running_text,
            aside=_tr("This runs in a process of its own; FreeCAD stays usable meanwhile."),
            condition=lambda analysis: _running(analysis) is not None,
            busy=lambda analysis: _running(analysis) is not None,
            status=_elapsed_text,
            actions=[Action(text=_tr("Cancel"), run=cancel)],
        ),
        Notification(
            key="mesh-failed",
            icon="FEM_StateMeshCleared",
            message=_failed_text,
            aside=_tr("The mesher's own panel holds the output it left behind."),
            condition=lambda analysis: _failed(analysis) is not None,
            actions=[
                Action(text=_tr("Acknowledge"), run=acknowledge),
                Action(text=_tr("Open mesher"), run=open_mesher),
            ],
        ),
        Notification(
            key="mesh-missing",
            icon="FEM_StateMeshMissing",
            message=_tr("Nothing meshes this geometry yet."),
            condition=lambda analysis: (
                not analysisrun.active()
                and geometryupdate.has_geometry(analysis)
                and not analysismesh.has_meshers(analysis)
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
        # Deliberately not "the mesh was cleared by the update": the same state
        # is reached by a mesher that was just created, by one whose run failed
        # and by one the user cancelled, and the panel cannot tell them apart.
        # What it can say is what is true of all of them.
        Notification(
            key="mesh-empty",
            icon="FEM_StateMeshCleared",
            message=_tr("This analysis has no mesh yet."),
            aside=_tr("The meshers and their settings are set up; only the mesh is missing."),
            condition=lambda analysis: (
                not analysisrun.active()
                and _failed(analysis) is None
                and analysismesh.has_meshers(analysis)
                and analysismesh.mesh_is_empty(analysis)
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
    """
    Bring every installed watcher, and the box around it, up to date.

    Tolerant of the widgets having been deleted underneath: the task view owns
    them once they are handed over, and anything that clears the task watchers
    - another workbench activating, say - takes them with it while this list
    still holds the Python side. What is left then is a shell, and the only
    sensible thing to do with it is to let go.
    """
    for watcher in list(_installed):
        try:
            watcher.refresh()
        except RuntimeError:
            _installed.clear()
            return


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

    # A run moving from one mesher to the next changes nothing in the document,
    # so it has to say so itself.
    from femtools import analysisrun

    analysisrun.add_listener(coalescer.request)
    _observers.append(coalescer)


def remove():
    if _observers:
        from femtools import analysisrun

        FreeCAD.removeDocumentObserver(_observers[0])
        FreeCADGui.removeDocumentObserver(_observers[1])
        analysisrun.remove_listener(_observers[2].request)
        _observers.clear()
    _installed.clear()
    FreeCADGui.Control.clearTaskWatcher()
