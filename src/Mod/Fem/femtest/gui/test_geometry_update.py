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
from femobjects import geometry_base
from femtools import geometryupdate

from femtest.app.support_utils import fcc_print
from femtest.app.test_preprocess import _make_tet_mesh


def _tet_mesh():
    return _make_tet_mesh()[0]


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

        self.geometry, self.mesh = update_watcher.watchers()

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

        self.assertEqual(self._showing(self.mesh), ["mesh-cleared"], "a mesher with no mesh")
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
        self.assertEqual(self._showing(self.mesh), ["mesh-cleared"])

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

        panel = self._panel(self.mesh, "mesh-cleared")
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
