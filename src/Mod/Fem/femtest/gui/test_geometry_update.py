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

from femguiutils import update_watcher
from femobjects import geometry_base
from femtools import geometryupdate

from femtest.app.support_utils import fcc_print


class TestGeometryUpdateGui(unittest.TestCase):
    fcc_print("import TestGeometryUpdateGui")

    def setUp(self):
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

        self.geometry_watcher, self.linked_watcher = update_watcher.watchers()

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def test_nothing_is_offered_while_nothing_is_behind(self):
        """A watcher that is always there is a notice, and notices get ignored."""
        self.assertFalse(self.geometry_watcher.shouldShow())
        self.assertFalse(self.linked_watcher.shouldShow())

    def test_the_update_is_offered_once_the_model_has_moved(self):
        """The geometry kept what it had, so the offer is the only thing that says so."""
        self.source.Shape = Part.makeBox(30, 10, 10)
        self.document.recompute()

        self.assertTrue(self.imp.Outdated)
        self.assertTrue(self.geometry_watcher.shouldShow())
        self.assertEqual(
            self.geometry_watcher.commands,
            ["FEM_GeometryUpdateMesh", "FEM_GeometryUpdate"],
            "both sizes of update are offered, the one that leaves a mesh first",
        )

    def test_the_offer_goes_away_with_the_reason_for_it(self):
        """Nothing to update, nothing in the panel."""
        self.source.Shape = Part.makeBox(30, 10, 10)
        self.document.recompute()
        self.assertTrue(self.geometry_watcher.shouldShow())

        geometryupdate.update_group(self.group)

        self.assertFalse(self.imp.Outdated)
        self.assertFalse(self.geometry_watcher.shouldShow())

    def test_an_analysis_of_its_own_never_offers_the_linked_update(self):
        """
        The entry that reaches into other analyses is offered only to an
        analysis that has one, and updating this analysis cannot repair a
        source that is behind - which is why the two are separate watchers.
        """
        self.source.Shape = Part.makeBox(30, 10, 10)
        self.document.recompute()
        self.assertFalse(self.linked_watcher.shouldShow())

    def test_an_analysis_in_another_document_offers_nothing_here(self):
        """
        The offer belongs to the document on screen. An analysis left behind in
        another one is not what the user is looking at, and a box in the task
        panel that acts on something out of sight is worse than no box.
        """
        self.source.Shape = Part.makeBox(30, 10, 10)
        self.document.recompute()
        self.assertTrue(self.geometry_watcher.shouldShow())

        other = FreeCAD.newDocument("SomewhereElse")
        try:
            FreeCAD.setActiveDocument(other.Name)
            self.assertFalse(self.geometry_watcher.shouldShow())
            self.assertFalse(self.linked_watcher.shouldShow())
        finally:
            FreeCAD.closeDocument(other.Name)
            FreeCAD.setActiveDocument(self.document.Name)

        self.assertTrue(self.geometry_watcher.shouldShow(), "and comes back with the document")

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
