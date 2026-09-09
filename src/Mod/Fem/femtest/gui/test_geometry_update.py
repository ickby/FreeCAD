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
Gui unit tests for offering the geometry update where the user can take it.

An analysis geometry follows the model it was built from only when told to, and
what tells the user that there is something to tell is the task watcher: it
appears when an update is available and is absent the rest of the time. The
tests read the watchers the workbench installs, because a state that never
reaches one is a state nobody is offered.
"""

__title__ = "FEM geometry update Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import FreeCADGui
import Part

import FemGui
import ObjectsFem

from femguiutils import notifications, update_watcher
from femtools import analysisrun
from femobjects import geometry_base
from femtools import geometryupdate

from femtest.app.support_utils import fcc_print
from femtest.app.test_preprocess import _make_tet_mesh


def _tet_mesh():
    return _make_tet_mesh()[0]


class _FakeStep(analysisrun.Step):
    """
    A step that waits to be told, standing in for a mesher.

    Meshing is a process on the machine and a minute of wall clock; what these
    tests are about is the order the steps run in and what the panel says while
    they do, so the waiting is made explicit instead.
    """

    def __init__(self, analysis, label):
        self.analysis = analysis
        self.label = label
        self.started = False
        self.cancelled = False
        self._run = None

    def start(self, run):
        self.started = True
        self._run = run

    def finish(self):
        self._run.step_finished()

    def fail(self, reason="something went wrong"):
        self._run.step_failed(self, reason)

    def cancel(self):
        self.cancelled = True


class TestAnalysisWatcherGui(unittest.TestCase):
    """
    The watcher that speaks before there is anything to speak about.

    Its two states are the ones the others cannot reach: a document with no
    analysis at all, and one with several where none has been chosen. Both are
    states in which there is no active analysis, which is why the panel had to
    stop insisting on one.
    """

    fcc_print("import TestAnalysisWatcherGui")

    def setUp(self):
        FreeCADGui.activateWorkbench("FemWorkbench")
        self.document = FreeCAD.newDocument(self.__class__.__name__)
        FreeCAD.setActiveDocument(self.document.Name)
        self.study, self.geometry, self.mesh = update_watcher.watchers()

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def _showing(self, watcher):
        watcher.widget.refresh(watcher._analysis_of())
        return [p.notification.key for p in watcher.widget.panels if not p.isHidden()]

    def _panel(self, watcher, key):
        for panel in watcher.widget.panels:
            if panel.notification.key == key:
                return panel
        raise AssertionError(f"no notification {key!r}")

    def test_an_empty_document_is_offered_an_analysis(self):
        """
        Nothing in the document at all, which is where a user starts. The other
        watchers have nothing to say, and would have said nothing anyway.
        """
        self.assertEqual(self._showing(self.study), ["analysis-missing"])
        self.assertEqual(self._showing(self.geometry), [])
        self.assertEqual(self._showing(self.mesh), [])

        panel = self._panel(self.study, "analysis-missing")
        self.assertEqual([a.command for a, _ in panel.buttons], ["FEM_Analysis"])

    def test_a_document_with_things_but_no_analysis_is_offered_one_too(self):
        """Being busy with something else is not a reason to hide the first step."""
        self.document.addObject("Part::Box", "Box")
        self.document.recompute()
        self.assertEqual(self._showing(self.study), ["analysis-missing"])

    def test_a_lone_analysis_needs_no_choosing(self):
        """
        FreeCAD activates the only analysis of a document by itself, so the
        chooser never sees this case and must not offer itself for it.
        """
        analysis = ObjectsFem.makeAnalysis(self.document, "Only")
        FemGui.setActiveAnalysis(analysis)
        self.document.recompute()
        self.assertEqual(self._showing(self.study), [])

    def test_several_analyses_and_no_choice_made(self):
        """One button per analysis, named after it, in the document's order."""
        first = ObjectsFem.makeAnalysis(self.document, "Beam")
        second = ObjectsFem.makeAnalysis(self.document, "Bracket")
        self.document.recompute()

        self.assertEqual(self._showing(self.study), ["analysis-unchosen"])
        panel = self._panel(self.study, "analysis-unchosen")
        self.assertEqual([b.text() for _, b in panel.buttons], [first.Label, second.Label])

    def test_choosing_one_answers_the_question(self):
        """The point of the buttons: pressing one leaves nothing to report."""
        ObjectsFem.makeAnalysis(self.document, "Beam")
        second = ObjectsFem.makeAnalysis(self.document, "Bracket")
        self.document.recompute()
        self.assertEqual(self._showing(self.study), ["analysis-unchosen"])

        panel = self._panel(self.study, "analysis-unchosen")
        action = panel.buttons[1][0]
        action.trigger(self.document)

        self.assertEqual(FemGui.getActiveAnalysis(), second)
        self.assertEqual(self._showing(self.study), [])

    def test_the_buttons_follow_the_document(self):
        """
        The choices are not known when the watcher is built, so the row is
        rebuilt from what the document holds at the time it is asked.
        """
        ObjectsFem.makeAnalysis(self.document, "Beam")
        ObjectsFem.makeAnalysis(self.document, "Bracket")
        self.document.recompute()
        panel = self._panel(self.study, "analysis-unchosen")
        self._showing(self.study)
        self.assertEqual(len(panel.buttons), 2)

        ObjectsFem.makeAnalysis(self.document, "Housing")
        self.document.recompute()
        self._showing(self.study)
        self.assertEqual([b.text() for _, b in panel.buttons], ["Beam", "Bracket", "Housing"])


class TestGeometryUpdateGui(unittest.TestCase):
    fcc_print("import TestGeometryUpdateGui")

    def setUp(self):
        # The commands the panels bind to are registered when the workbench is
        # first activated, and a bare test run has never activated one.
        FreeCADGui.activateWorkbench("FemWorkbench")
        self.document = FreeCAD.newDocument(self.__class__.__name__)
        self.source = self.document.addObject("Part::Feature", "Source")
        self.source.Shape = Part.makeBox(20, 10, 10)

        self.analysis = ObjectsFem.makeAnalysis(self.document, "Analysis")
        self.group = ObjectsFem.makeGeometryGroup(self.document)
        self.imp = ObjectsFem.makeGeometryImport(self.document)
        self.imp.Import = [self.source]
        self.group.Group = [self.imp]
        self.analysis.addObject(self.group)
        self.document.recompute()
        FemGui.setActiveAnalysis(self.analysis)

        self.study, self.geometry, self.mesh = update_watcher.watchers()

    def _add_mesher(self):
        """A mesh group with one mesher in it, and no mesh yet."""
        mesh_group = ObjectsFem.makeMeshShapeGroup(
            self.document, "Mesh", geometry=self.group, analysis=self.analysis
        )
        gmsh = ObjectsFem.makeMeshGmsh(self.document, "MeshGmsh")
        mesh_group.Group = [gmsh]
        self.document.recompute()
        return gmsh

    def _panel(self, watcher, key):
        for panel in watcher.widget.panels:
            if panel.notification.key == key:
                return panel
        raise AssertionError(f"no notification {key!r} in {watcher.title}")

    def _showing(self, watcher):
        """Which notifications of *watcher* are on show, by key."""
        watcher.widget.refresh(update_watcher.active_analysis())
        # isHidden(), not isVisible(): a widget that has never been put on
        # screen is not visible even when nothing has hidden it, and these
        # panels are asked about outside a shown task panel.
        return [p.notification.key for p in watcher.widget.panels if not p.isHidden()]

    def tearDown(self):
        analysisrun.clear()
        FreeCAD.closeDocument(self.document.Name)

    def test_a_watcher_with_nothing_to_say_is_not_there(self):
        """
        The rule the whole thing rests on. An analysis in order leaves the task
        panel empty: no box, no header, nothing to dismiss.
        """
        mesh_group = ObjectsFem.makeMeshShapeGroup(
            self.document, "Mesh", geometry=self.group, analysis=self.analysis
        )
        gmsh = ObjectsFem.makeMeshGmsh(self.document, "MeshGmsh")
        mesh_group.Group = [gmsh]
        gmsh.FemMesh = _tet_mesh()
        self.document.recompute()

        self.assertEqual(self._showing(self.geometry), [])
        self.assertEqual(self._showing(self.mesh), [])
        self.assertFalse(self.geometry.shouldShow())
        self.assertFalse(self.mesh.shouldShow())

    def test_the_update_is_offered_once_the_model_has_moved(self):
        """The geometry kept what it had, so the offer is the only thing that says so."""
        self.source.Shape = Part.makeBox(30, 10, 10)
        self.document.recompute()

        self.assertTrue(self.imp.Outdated)
        self.assertEqual(self._showing(self.geometry), ["geometry-outdated"])
        self.assertTrue(self.geometry.shouldShow())

        panel = self._panel(self.geometry, "geometry-outdated")
        self.assertEqual(
            [action.command for action, _ in panel.buttons],
            ["FEM_GeometryUpdate", "FEM_GeometryUpdateMesh"],
            "both sizes of update, the one that leaves an analysis whole last",
        )

    def test_the_offer_goes_away_with_the_reason_for_it(self):
        """Nothing to update, nothing in the panel."""
        self.source.Shape = Part.makeBox(30, 10, 10)
        self.document.recompute()
        self.assertTrue(self.geometry.shouldShow())

        geometryupdate.update_group(self.group)

        self.assertFalse(self.imp.Outdated)
        self.assertNotIn("geometry-outdated", self._showing(self.geometry))

    def test_an_analysis_of_its_own_never_offers_the_linked_update(self):
        """
        The panel that reaches into other analyses is shown only to an analysis
        that imports one: updating this analysis cannot repair a source that is
        behind, so offering the entry that would is worse than offering nothing.
        """
        self.source.Shape = Part.makeBox(30, 10, 10)
        self.document.recompute()
        self.assertNotIn("source-behind", self._showing(self.geometry))

    def test_an_analysis_in_another_document_offers_nothing_here(self):
        """
        The offer belongs to the document on screen. An analysis left behind in
        another one is not what the user is looking at, and a box in the task
        panel that acts on something out of sight is worse than no box.
        """
        self.source.Shape = Part.makeBox(30, 10, 10)
        self.document.recompute()
        self.assertTrue(self.geometry.shouldShow())

        other = FreeCAD.newDocument("SomewhereElse")
        try:
            FreeCAD.setActiveDocument(other.Name)
            self.assertFalse(self.geometry.shouldShow())
            self.assertFalse(self.mesh.shouldShow())
        finally:
            FreeCAD.closeDocument(other.Name)
            FreeCAD.setActiveDocument(self.document.Name)

        self.assertTrue(self.geometry.shouldShow(), "and comes back with the document")

    def test_an_analysis_with_no_geometry_is_pointed_at_the_first_step(self):
        """
        The one notification that is not a fault. A fresh analysis has nothing
        to draw and nothing to mesh, and the panel is where a user finds out
        what to do about it.
        """
        self.group.Group = []
        self.document.recompute()
        self.assertEqual(self._showing(self.geometry), ["geometry-missing"])

        panel = self._panel(self.geometry, "geometry-missing")
        self.assertEqual([a.command for a, _ in panel.buttons], ["FEM_GeometryImport"])

    def test_the_mesh_stage_speaks_for_itself(self):
        """
        A geometry with nothing meshing it, and then a mesh an update emptied.
        Two states of the same stage, in a box of its own - a user reading
        about the mesh is not being told about the geometry above it.
        """
        self.assertEqual(self._showing(self.mesh), ["mesh-missing"])

        mesh_group = ObjectsFem.makeMeshShapeGroup(
            self.document, "Mesh", geometry=self.group, analysis=self.analysis
        )
        gmsh = ObjectsFem.makeMeshGmsh(self.document, "MeshGmsh")
        mesh_group.Group = [gmsh]
        self.document.recompute()

        self.assertEqual(self._showing(self.mesh), ["mesh-empty"], "a mesher with no mesh")
        gmsh.FemMesh = _tet_mesh()
        self.document.recompute()
        self.assertEqual(self._showing(self.mesh), [], "and nothing once it has one")

    def test_the_mesh_notice_goes_as_soon_as_there_is_a_mesh_again(self):
        """
        The panel has to answer to the meshers, not to the merge of them.

        A mesher writes its own mesh; the merge the analysis publishes is
        rebuilt by the mesh group at the next recompute, and meshing does not
        ask for one. A notice that read the merge therefore stayed up after a
        remesh - and, since nothing else was going to recompute the document,
        stayed up for good.
        """
        mesh_group = ObjectsFem.makeMeshShapeGroup(
            self.document, "Mesh", geometry=self.group, analysis=self.analysis
        )
        gmsh = ObjectsFem.makeMeshGmsh(self.document, "MeshGmsh")
        mesh_group.Group = [gmsh]
        gmsh.FemMesh = _tet_mesh()
        self.document.recompute()
        self.assertEqual(self._showing(self.mesh), [])

        # An update of the geometry takes the mesh with it.
        self.source.Shape = Part.makeBox(30, 10, 10)
        self.document.recompute()
        geometryupdate.update_group(self.group)
        self.assertEqual(gmsh.FemMesh.NodeCount, 0)
        self.assertEqual(self._showing(self.mesh), ["mesh-empty"])

        # Meshing again, and deliberately without a recompute after it: this is
        # the moment the panel used to get stuck at.
        gmsh.FemMesh = _tet_mesh()
        self.assertEqual(mesh_group.FemMesh.NodeCount, 0, "the merge is still a step behind")
        self.assertEqual(self._showing(self.mesh), [], "and the notice goes all the same")

    def test_meshing_an_analysis_publishes_what_it_meshed(self):
        """
        A mesher stops at its own mesh. What the solver is handed is the merge,
        so meshing that leaves the merge behind has not finished the job.
        """
        mesh_group = ObjectsFem.makeMeshShapeGroup(
            self.document, "Mesh", geometry=self.group, analysis=self.analysis
        )
        gmsh = ObjectsFem.makeMeshGmsh(self.document, "MeshGmsh")
        mesh_group.Group = [gmsh]
        self.document.recompute()

        # The mesh is put there by hand, standing in for a mesher run - the
        # point here is not that Gmsh works but that what it leaves behind is
        # published. Whether the run itself succeeds is beside it, and on a
        # machine without Gmsh it will not.
        from femmesh import analysismesh

        gmsh.FemMesh = _tet_mesh()
        self.assertEqual(mesh_group.FemMesh.NodeCount, 0, "nothing has collected it yet")

        analysismesh.mesh_analysis(self.analysis)
        self.assertGreater(
            mesh_group.FemMesh.NodeCount, 0, "the merge has to be published, not left stale"
        )

    # -- runs ---------------------------------------------------------------

    def test_a_run_takes_its_steps_one_at_a_time(self):
        """
        The point of a run: nothing else starts until the step in hand is done,
        because two meshers writing at once would race for the same merge.
        """
        first = _FakeStep(self.analysis, "First")
        second = _FakeStep(self.analysis, "Second")
        run = analysisrun.start([first, second])

        self.assertTrue(run.running)
        self.assertTrue(first.started)
        self.assertFalse(second.started, "the second waits for the first")
        self.assertEqual(run.position, (1, 2))

        first.finish()
        self.assertTrue(second.started)
        self.assertEqual(run.position, (2, 2))

        second.finish()
        self.assertFalse(run.running)
        self.assertTrue(run.finished)

    def test_a_failed_step_does_not_stop_the_rest(self):
        """One mesher failing is no reason to leave the others unmeshed."""
        first = _FakeStep(self.analysis, "First")
        second = _FakeStep(self.analysis, "Second")
        run = analysisrun.start([first, second])

        first.fail()
        self.assertTrue(second.started, "the rest still runs")
        second.finish()

        self.assertEqual([step.label for step, _ in run.failures], ["First"])
        self.assertTrue(run.finished)

    def test_cancelling_stops_the_queue_not_only_the_step(self):
        """
        What a user pressing Cancel means. What finished stays finished; what
        had not started never does.
        """
        first = _FakeStep(self.analysis, "First")
        second = _FakeStep(self.analysis, "Second")
        third = _FakeStep(self.analysis, "Third")
        run = analysisrun.start([first, second, third])

        first.finish()
        run.cancel()

        self.assertTrue(second.cancelled, "the one in hand is stopped")
        self.assertFalse(third.started, "and the rest never starts")
        self.assertTrue(run.cancelled)
        self.assertFalse(run.running)

    def test_only_one_run_at_a_time(self):
        """Two would race for the same meshes."""
        first = _FakeStep(self.analysis, "First")
        run = analysisrun.start([first])
        self.assertIsNotNone(run)

        self.assertIsNone(analysisrun.start([_FakeStep(self.analysis, "Other")]))
        first.finish()

    def test_the_update_commands_stand_back_while_a_run_is_going(self):
        """
        Updating a geometry while its meshers run would clear exactly what they
        are writing, so the commands that could do it are switched off.
        """
        self.source.Shape = Part.makeBox(30, 10, 10)
        self.document.recompute()
        self.assertTrue(FreeCADGui.Command.get("FEM_GeometryUpdateMesh").isActive())

        step = _FakeStep(self.analysis, "Meshing")
        analysisrun.start([step])
        self.assertFalse(FreeCADGui.Command.get("FEM_GeometryUpdateMesh").isActive())
        self.assertFalse(FreeCADGui.Command.get("FEM_GeometryUpdate").isActive())

        step.finish()
        self.assertTrue(FreeCADGui.Command.get("FEM_GeometryUpdateMesh").isActive())

    def test_a_run_says_what_it_is_doing_and_offers_to_stop(self):
        """
        The panel reports the run rather than the document while one is going -
        the derived states would be describing the very thing being worked on.
        """
        step = _FakeStep(self.analysis, "MeshGmsh")
        analysisrun.start([step, _FakeStep(self.analysis, "MeshNetgen")])

        self.assertEqual(self._showing(self.mesh), ["mesh-running"])
        panel = self._panel(self.mesh, "mesh-running")
        self.assertIn("MeshGmsh", panel.message.text())
        self.assertIn("1 of 2", panel.message.text())
        self.assertEqual([b.text() for _, b in panel.buttons], ["Cancel"])

        self.assertEqual(self._showing(self.geometry), [], "and the geometry holds its tongue")
        step.finish()

    def test_a_failure_stays_until_it_is_acknowledged(self):
        """
        An error the user never saw is an error that did not happen. It waits,
        and the panel offers the mesher that produced it.
        """
        self._add_mesher()
        step = _FakeStep(self.analysis, "MeshGmsh")
        analysisrun.start([step])
        step.fail()

        self.assertEqual(self._showing(self.mesh), ["mesh-failed"])
        panel = self._panel(self.mesh, "mesh-failed")
        self.assertIn("MeshGmsh", panel.message.text())
        self.assertEqual([b.text() for _, b in panel.buttons], ["Acknowledge", "Open mesher"])

        action = panel.buttons[0][0]
        action.trigger(self.analysis)
        self.assertEqual(
            self._showing(self.mesh),
            ["mesh-empty"],
            "acknowledged; what is left is the plain truth that there is no mesh",
        )

    def test_a_new_run_replaces_what_the_last_one_left(self):
        """
        A failure answered by running the thing again is not a failure any
        more, so it does not need acknowledging first.
        """
        gmsh = self._add_mesher()
        first = _FakeStep(self.analysis, "MeshGmsh")
        analysisrun.start([first])
        first.fail()
        self.assertEqual(self._showing(self.mesh), ["mesh-failed"])

        second = _FakeStep(self.analysis, "MeshGmsh")
        analysisrun.start([second])
        self.assertEqual(self._showing(self.mesh), ["mesh-running"])

        gmsh.FemMesh = _tet_mesh()
        second.finish()
        self.assertEqual(self._showing(self.mesh), [])

    def test_a_run_elsewhere_is_not_this_analysis_business(self):
        """A run spans the analyses it was given, and reports to those only."""
        other = ObjectsFem.makeAnalysis(self.document, "Elsewhere")
        step = _FakeStep(other, "Meshing")
        analysisrun.start([step])

        self.assertNotIn("mesh-running", self._showing(self.mesh))
        step.finish()

    def test_a_notification_can_say_that_it_is_work_in_progress(self):
        """
        The activity bar and its clock belong to the notification system, not
        to meshing: a solver reporting a run of its own says it the same way,
        with the same two hooks and no widget of its own.
        """
        ticks = []
        note = notifications.Notification(
            key="working",
            icon="FEM_StateMeshMissing",
            message="Working",
            condition=lambda analysis: True,
            busy=lambda analysis: True,
            status=lambda analysis: "0:%02d" % len(ticks),
        )
        widget = notifications.NotificationWidget([note])
        panel = widget.panels[0]

        widget.refresh(self.analysis)
        self.assertTrue(panel.busy)
        self.assertFalse(panel.activity.isHidden(), "the activity bar is shown")
        self.assertEqual(panel.status.text(), "0:00")

        # It moves under its own steam: this application runs with UI effects
        # off, so a bar that left its animation to the style would stand still.
        before = panel.activity.phase
        panel.activity.advance()
        self.assertNotEqual(panel.activity.phase, before)

        # The clock updates without every condition being asked again.
        ticks.append(1)
        panel.update_status(self.analysis)
        self.assertEqual(panel.status.text(), "0:01")

    def test_a_notification_that_is_not_working_shows_no_bar(self):
        """The bar is the exception, and a plain state must not carry one."""
        note = notifications.Notification(
            key="plain",
            icon="FEM_StateMeshMissing",
            message="Nothing is happening",
            condition=lambda analysis: True,
        )
        widget = notifications.NotificationWidget([note])
        widget.refresh(self.analysis)

        panel = widget.panels[0]
        self.assertFalse(panel.busy)
        self.assertTrue(panel.activity.isHidden())
        self.assertTrue(panel.status.isHidden())

    def test_the_running_notification_counts_the_seconds(self):
        """What the user sees while a mesh is going: a bar, and a clock."""
        step = _FakeStep(self.analysis, "MeshGmsh")
        analysisrun.start([step])
        self._showing(self.mesh)

        panel = self._panel(self.mesh, "mesh-running")
        self.assertTrue(panel.busy)
        self.assertRegex(panel.status.text(), r"^\d+:\d\d$")
        step.finish()

    def test_an_action_needs_a_command_or_a_function_but_not_both(self):
        """
        The two kinds of action, and the rules that keep either usable. A
        command brings its own label; a function has to be given one, or the
        button would have nothing to say.
        """
        by_command = notifications.Action(command="FEM_GeometryImport")
        self.assertEqual(by_command.text(), "Import Geometry")
        self.assertIsNotNone(by_command.icon(), "and its icon comes with it")

        called = []
        by_function = notifications.Action(
            text="Mesh now", run=lambda analysis: called.append(analysis)
        )
        self.assertEqual(by_function.text(), "Mesh now")
        by_function.trigger(self.analysis)
        self.assertEqual(called, [self.analysis], "and it is handed the analysis it was shown for")

        with self.assertRaises(ValueError):
            notifications.Action()
        with self.assertRaises(ValueError):
            notifications.Action(command="FEM_GeometryImport", run=lambda analysis: None)
        with self.assertRaises(ValueError):
            notifications.Action(run=lambda analysis: None)

    def test_a_supplied_action_looks_like_any_other(self):
        """
        Whether a button runs a command or a function is not the user's
        business, so nothing on screen may give it away.
        """
        mesh_group = ObjectsFem.makeMeshShapeGroup(
            self.document, "Mesh", geometry=self.group, analysis=self.analysis
        )
        mesh_group.Group = [ObjectsFem.makeMeshGmsh(self.document, "MeshGmsh")]
        self.document.recompute()
        self._showing(self.mesh)

        panel = self._panel(self.mesh, "mesh-empty")
        action, button = panel.buttons[0]
        self.assertIsNone(action.command, "no command meshes a whole analysis")
        self.assertTrue(button.text())
        self.assertFalse(button.icon().isNull(), "and it carries an icon like the rest")

    def test_each_offered_update_is_told_apart_by_its_icon(self):
        """
        The toolbar button shows and runs whichever entry was used last, so
        entries that share an icon leave the user unable to see what a press
        would do. The group names no icon of its own for the same reason.
        """
        commands = ["FEM_GeometryUpdate", "FEM_GeometryUpdateMesh", "FEM_GeometryUpdateLinked"]
        pixmaps = [FreeCADGui.Command.get(name).getInfo()["pixmap"] for name in commands]
        self.assertEqual(len(set(pixmaps)), 3, f"one icon each, got {pixmaps}")
        self.assertEqual(
            FreeCADGui.Command.get("FEM_GeometryUpdateGroup").getInfo()["pixmap"],
            "",
            "the group wears the icon of the entry it would run",
        )
        for pixmap in pixmaps:
            self.assertFalse(
                FreeCADGui.getIcon(pixmap) is None, f"{pixmap} is missing from the resources"
            )
