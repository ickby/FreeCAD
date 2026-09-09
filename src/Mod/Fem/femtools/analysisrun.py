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
Running the work an analysis needs, one step at a time and out of the way.

Meshing is slow - minutes on anything real - and it runs in a process of its
own, which is the only reason FreeCAD stays usable while it happens. What was
missing was somewhere to drive that from when no mesher panel is open: pressing
one button should mesh a whole analysis, or update a geometry and then mesh it,
without the application going deaf for the duration.

So a run is a list of steps, executed in order. A geometry update is done here
and now; a mesher is started and the run waits for it, picking up the next step
when the process ends. Cancelling stops the queue rather than the one process,
because that is what a user pressing Cancel means, and whatever was finished
before it stays finished.

Only one run at a time. Two of them would race for the same meshes, and the
commands that start runs are switched off while one is going.
"""

__title__ = "FreeCAD FEM analysis runs"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import time

from PySide import QtCore

import FreeCAD


class _PrepareThread(QtCore.QThread):
    """
    Writing a mesher's input files, off the main thread.

    Preparing is not the quick half: it exports the shape and writes the input
    the mesher reads, which on a large model takes long enough to be felt. The
    mesher task panels have always done this on a thread of their own and this
    follows them, so that a run started from a button is no more blocking than
    one started from a panel.
    """

    def __init__(self, tool):
        super().__init__()
        self.tool = tool
        self.error = None

    def run(self):
        try:
            self.tool.prepare()
        except Exception as error:  # noqa: BLE001 - handed to the run, not swallowed
            self.error = str(error)


class Step:
    """One thing a run does. Subclasses say whether they wait for a process."""

    #: What the panel says while this step is the one in hand.
    label = ""

    def start(self, run):
        raise NotImplementedError


class GeometryStep(Step):
    """Let an analysis geometry follow the model. Immediate; nothing to wait for."""

    def __init__(self, analysis):
        self.analysis = analysis
        self.label = analysis.Label

    def start(self, run):
        from femtools import geometryupdate

        geometryupdate.update_geometry(self.analysis)
        run.step_finished()


class MeshStep(Step):
    """Run one mesher, in a process of its own."""

    def __init__(self, mesher):
        self.mesher = mesher
        self.label = mesher.Label
        self.tool = None
        self._thread = None
        self._log = []

    def start(self, run):
        from femmesh import analysismesh

        self.tool = analysismesh.tool_for(self.mesher)
        if self.tool is None:
            run.step_finished()
            return

        self._thread = _PrepareThread(self.tool)
        self._thread.finished.connect(lambda: self._prepared(run))
        self._thread.start()

    def _prepared(self, run):
        if run.cancelled:
            return
        if self._thread.error is not None:
            run.step_failed(self, self._thread.error)
            return

        process = self.tool.process
        process.readyReadStandardOutput.connect(self._read_output)
        process.readyReadStandardError.connect(self._read_error)
        process.finished.connect(lambda code, status: self._finished(run, code, status))
        process.errorOccurred.connect(lambda error: self._failed(run, error))
        self.tool.compute()

    def cancel(self):
        if self.tool is not None and self.tool.process.state() != QtCore.QProcess.NotRunning:
            self.tool.process.kill()

    # -- what the process had to say ---------------------------------------

    def _read_output(self):
        self._log.append(
            self.tool.process.readAllStandardOutput().data().decode("utf-8", "replace")
        )

    def _read_error(self):
        self._log.append(self.tool.process.readAllStandardError().data().decode("utf-8", "replace"))

    def _keep_log(self):
        """
        Leave the output where the mesher's own panel will find it.

        The notification says which mesher failed and offers to open it; the
        details belong in the panel that already knows how to show a log. It is
        kept on the proxy rather than in a property, because it describes one
        run in one session and has no business in the file.

        Whatever is still in the pipe is taken first. A process that writes and
        exits in one breath can be finished before Qt has delivered a single
        readyRead, and the last thing it said is usually the part worth
        reading - it is where a mesher explains why it gave up.
        """
        if self.tool is not None:
            self._read_output()
            self._read_error()
        proxy = getattr(self.mesher, "Proxy", None)
        if proxy is not None:
            proxy._last_log = "".join(self._log)

    def _finished(self, run, code, status):
        self._keep_log()
        if run.cancelled:
            return
        if status == QtCore.QProcess.ExitStatus.NormalExit and code == 0:
            run.step_finished()
        else:
            run.step_failed(self, FreeCAD.Qt.translate("FEM", "the mesher stopped with an error"))

    def _failed(self, run, error):
        self._keep_log()
        if not run.cancelled:
            run.step_failed(self, FreeCAD.Qt.translate("FEM", "the mesher could not be started"))


class Run:
    """
    A queue of steps and the state a panel can report about it.

    The state is deliberately not derived from the document: whether something
    is running, and what it was that failed, is true of this session and of
    nothing that is saved. What is derived from the document - a geometry that
    is behind, a mesh that is missing - is asked of the document as before.
    """

    def __init__(self, steps):
        self.steps = list(steps)
        self.index = -1
        self.cancelled = False
        self.failures = []
        self.finished = False
        self.started_at = None
        self.stopped_at = None

    # -- what a panel asks -------------------------------------------------

    @property
    def running(self):
        return not self.finished and not self.cancelled and self.index >= 0

    @property
    def current(self):
        if 0 <= self.index < len(self.steps):
            return self.steps[self.index]
        return None

    @property
    def position(self):
        """(this step, how many there are), counting from one, for a status line."""
        return (self.index + 1, len(self.steps))

    def touches(self, analysis):
        """
        Whether *analysis* is one of the analyses this run is working on.

        A run can span several - updating an analysis and the ones it imports -
        and the panel of an analysis it never touches has no business reporting
        it.
        """
        for step in self.steps:
            owner = getattr(step, "analysis", None)
            if owner is None:
                mesher = getattr(step, "mesher", None)
                owner = mesher.getParentGroup() if mesher is not None else None
                if owner is not None and not owner.isDerivedFrom("Fem::FemAnalysis"):
                    owner = owner.getParentGroup()
            if owner == analysis:
                return True
        return False

    # -- driving it --------------------------------------------------------

    @property
    def elapsed(self):
        """
        Seconds this run has been going, or took.

        A wall clock, not a measure of work: what it is for is telling a user
        that something is still happening, which is the question a long mesh
        raises and the one a status line can actually answer.
        """
        if self.started_at is None:
            return 0.0
        return (self.stopped_at or time.monotonic()) - self.started_at

    def start(self):
        self.started_at = time.monotonic()
        self._advance()
        return self

    def cancel(self):
        """
        Stop the queue, not just the process in it.

        Whatever earlier steps finished stays finished - a mesh already made is
        not thrown away because a later one was interrupted - and the analysis
        is recomputed so that what it publishes matches what its meshers now
        hold.
        """
        if self.finished or self.cancelled:
            return
        self.cancelled = True
        step = self.current
        if step is not None:
            step.cancel()
        self._finish()

    def step_finished(self):
        self._advance()

    def step_failed(self, step, reason):
        """
        Record it and carry on with the rest.

        One mesher failing on one component is no reason to leave the others
        unmeshed, and the panel can name them all at the end.
        """
        self.failures.append((step, reason))
        self._advance()

    def _advance(self):
        if self.cancelled:
            return
        self.index += 1
        if self.index >= len(self.steps):
            self._finish()
            return
        self._changed()
        self.steps[self.index].start(self)

    def _finish(self):
        self.finished = True
        self.stopped_at = time.monotonic()
        self._recompute()
        self._changed()

    def _recompute(self):
        """
        Publish what the run left behind.

        A mesher writes its own mesh and stops there; what the analysis
        publishes is the merge its mesh group rebuilds on a recompute. Cancelled
        or failed makes no difference to that - the merge has to say what the
        meshers actually hold either way.
        """
        documents = []
        for step in self.steps:
            obj = getattr(step, "mesher", None) or getattr(step, "analysis", None)
            if obj is not None and obj.Document not in documents:
                documents.append(obj.Document)
        for document in documents:
            document.recompute()

    def _changed(self):
        _notify()


_current = None
_listeners = []


def add_listener(listener):
    """Be told whenever a run starts, moves on, or ends."""
    if listener not in _listeners:
        _listeners.append(listener)


def remove_listener(listener):
    if listener in _listeners:
        _listeners.remove(listener)


def _notify():
    for listener in list(_listeners):
        listener()


def current():
    """The run in progress, or the one that just failed and has not been seen yet."""
    return _current


def active():
    """Whether something is going on that other work must not walk into."""
    return _current is not None and _current.running


def start(steps):
    """
    Begin a run, unless one is already going.

    Refusing rather than queueing is deliberate: two runs would race for the
    same meshes, and the commands that start them are switched off while one is
    in progress, so a second call is a mistake rather than a request.
    """
    global _current

    if active():
        return None
    # A new run replaces whatever the last one left behind: a failure that has
    # been answered by running the thing again is not a failure any more.
    _current = Run(steps)
    _notify()
    return _current.start()


def clear():
    """Forget the last run, once its outcome has been acknowledged."""
    global _current

    _current = None
    _notify()
