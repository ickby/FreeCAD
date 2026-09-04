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
Gui unit tests for the edit scope of AnalysisViewState.

A task panel is about one object, and what the view shows while it is open
follows from what that object needs picked. The scope is what puts the view
there and what puts it back, and it is opened from the edit-mode signals, so
creating an object and editing it later go through exactly the same path.
"""

__title__ = "FEM edit scope Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import FreeCADGui
import Part

import Fem
import FemGui
import ObjectsFem

from femtest.app.support_utils import fcc_print

# Every constraint the workbench creates from a command of its own. The command
# is what used to switch visibilities on the way in, so each of them is a way
# the view could be left somewhere the user did not ask for.
CONSTRAINT_COMMANDS = (
    "FEM_ConstraintFixed",
    "FEM_ConstraintDisplacement",
    "FEM_ConstraintForce",
    "FEM_ConstraintPressure",
    "FEM_ConstraintSpring",
    "FEM_ConstraintContact",
    "FEM_ConstraintTemperature",
    "FEM_ConstraintHeatflux",
    "FEM_ConstraintInitialTemperature",
    "FEM_ConstraintTransform",
    "FEM_ConstraintBearing",
    "FEM_ConstraintGear",
    "FEM_ConstraintPulley",
    "FEM_ConstraintPlaneRotation",
    "FEM_ConstraintRigidBody",
)


class TestEditScopeGui(unittest.TestCase):
    fcc_print("import TestEditScopeGui")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)
        self.analysis = ObjectsFem.makeAnalysis(self.document, "Analysis")
        self.geometry = self.document.addObject("Fem::FemGeometry", "Geometry")
        self.geometry.Shape = Part.makeBox(10, 10, 10)
        self.analysis.addObject(self.geometry)
        self.mesh_group = ObjectsFem.makeMeshShapeGroup(
            self.document, "Mesh", geometry=self.geometry, analysis=self.analysis
        )
        child = self.document.addObject("Fem::FemMeshObject", "MeshA")
        mesh = Fem.FemMesh()
        mesh.addNode(0, 0, 0, 1)
        mesh.addNode(1, 0, 0, 2)
        mesh.addNode(0, 1, 0, 3)
        mesh.addNode(0, 0, 1, 4)
        mesh.addVolume([1, 2, 3, 4])
        child.FemMesh = mesh
        self.mesh_group.Group = [child]
        self.document.recompute()

        FemGui.setActiveAnalysis(self.analysis)
        self.state = FemGui.getAnalysisViewState(self.analysis)

    def tearDown(self):
        self._close_edit()
        FreeCAD.closeDocument(self.document.Name)

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestEditScopeGui tests {2}\n{0}".format(
                100 * "*", 10 * "*", 55 * "*"
            )
        )

    # -- helpers ----------------------------------------------------------

    def _close_edit(self):
        FreeCADGui.ActiveDocument.resetEdit()
        FreeCADGui.Control.closeDialog()
        FreeCADGui.updateGui()

    def _view(self):
        return (
            self.state.getActiveStage(),
            self.geometry.ViewObject.Visibility,
            self.mesh_group.ViewObject.Visibility,
        )

    def _create(self, command):
        before = set(self.analysis.Group)
        FreeCADGui.runCommand(command, 0)
        FreeCADGui.updateGui()
        made = [obj for obj in self.analysis.Group if obj not in before]
        self.assertEqual(len(made), 1, f"{command} made {len(made)} objects")
        return made[0]

    # -- what the scope has to leave behind --------------------------------

    def test_creating_a_constraint_leaves_the_geometry_stage_alone(self):
        """
        The Geometry stage is where a constraint is picked, so creating one
        while it is up changes nothing at all -- least of all the geometry,
        which is the thing being picked on.
        """
        self.state.setActiveStage("Geometry")
        FreeCADGui.updateGui()
        before = self._view()
        self.assertTrue(self.geometry.ViewObject.Visibility)

        self._create("FEM_ConstraintForce")
        self.assertTrue(
            self.geometry.ViewObject.Visibility,
            "the geometry a constraint is picked on has to stay on show",
        )
        self._close_edit()
        self.assertEqual(self._view(), before)

    def test_creating_a_constraint_from_the_mesh_stage_comes_back_to_it(self):
        """
        A constraint is picked on geometry, so the scope shows it; the stage the
        user was in is theirs and comes back when the panel closes.
        """
        self.state.setActiveStage("Mesh")
        FreeCADGui.updateGui()
        before = self._view()
        self.assertEqual(before[0], "Mesh")

        self._create("FEM_ConstraintForce")
        self.assertEqual(self.state.getActiveStage(), "Geometry")
        self.assertTrue(self.geometry.ViewObject.Visibility)

        self._close_edit()
        self.assertEqual(self._view(), before)

    def test_editing_and_creating_leave_the_same_view(self):
        """
        The difference this whole scope exists to remove: a create command and a
        later edit of the same object put the view in the same place.
        """
        self.state.setActiveStage("Mesh")
        FreeCADGui.updateGui()
        force = self._create("FEM_ConstraintForce")
        after_create_open = self._view()
        self._close_edit()
        after_create_closed = self._view()

        FreeCADGui.ActiveDocument.setEdit(force.Name)
        FreeCADGui.updateGui()
        self.assertEqual(self._view(), after_create_open)
        self._close_edit()
        self.assertEqual(self._view(), after_create_closed)

    def test_a_stage_chosen_while_editing_is_kept(self):
        """A stage the user picks with the panel open is a choice, not scenery."""
        self.state.setActiveStage("Mesh")
        FreeCADGui.updateGui()
        self._create("FEM_ConstraintForce")

        # The user switches back to the mesh while the panel is still open.
        self.state.setActiveStage("Mesh")
        FreeCADGui.updateGui()
        self._close_edit()
        self.assertEqual(self.state.getActiveStage(), "Mesh")

    def test_no_constraint_command_hides_the_geometry(self):
        """
        Every constraint command, not just the one this was noticed on.

        They all used to write visibilities of their own on the way in, and each
        was free to disagree with the next about what the view should show.
        """
        for command in CONSTRAINT_COMMANDS:
            with self.subTest(command=command):
                self.state.setActiveStage("Geometry")
                FreeCADGui.updateGui()
                self._create(command)
                self.assertTrue(
                    self.geometry.ViewObject.Visibility,
                    f"{command} hid the geometry it is picked on",
                )
                self._close_edit()
                self.assertEqual(self.state.getActiveStage(), "Geometry")
                self.assertTrue(self.geometry.ViewObject.Visibility)

    def test_editing_geometry_leaves_the_stage_to_the_chain_preview(self):
        """
        A geometry step previews itself while it is edited, so the scope keeps
        out of the way rather than switching a stage underneath it.
        """
        self.state.setActiveStage("Geometry")
        FreeCADGui.updateGui()
        self.assertEqual(self.state.getEditIntent(), "None")
        self.assertIsNone(self.state.getEditedObject())
