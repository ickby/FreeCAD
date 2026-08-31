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
Gui unit tests for placing the symbols of a constraint per reference.

A tie or a contact on a shell has to say which of the two skins of the expanded
element it holds, and its marker is the only place a user can see the answer
without reading the deck. Everything here reads the Coin matrices rather than
the property that set them, because a symbol that did not turn is not turned.
"""

__title__ = "FEM constraint symbol placement Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import math
import unittest

import FreeCAD
import FreeCADGui

from pivy import coin

import ObjectsFem

from femtest.app.support_utils import fcc_print


def symbol_copies(vobj):
    """The SoMultipleCopy holding one matrix per drawn symbol."""

    def walk(node):
        if isinstance(node, coin.SoMultipleCopy):
            return node
        if hasattr(node, "getNumChildren"):
            for index in range(node.getNumChildren()):
                found = walk(node.getChild(index))
                if found is not None:
                    return found
        return None

    return walk(vobj.RootNode)


def symbol_axes(obj):
    """Where the own +Y of each symbol points once it is placed in the scene.

    The symbols are modelled standing on the surface and reaching along their
    local Y, so this is the direction that has to turn round when a side is
    reversed.
    """
    node = symbol_copies(obj.ViewObject)
    axes = []
    for index in range(node.matrix.getNum()):
        out = node.matrix[index].multDirMatrix(coin.SbVec3f(0, 1, 0))
        axes.append(FreeCAD.Vector(*out.getValue()).normalize())
    return axes


class TestConstraintSymbolsGui(unittest.TestCase):
    fcc_print("import TestConstraintSymbolsGui")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)
        self.box = self.document.addObject("Part::Box", "Box")
        self.box.Length, self.box.Width, self.box.Height = 10, 10, 10
        self.plane = self.document.addObject("Part::Plane", "Plane")
        self.plane.Length, self.plane.Width = 10, 10
        self.plane.Placement.Base = FreeCAD.Vector(0, 0, 10)
        self.analysis = ObjectsFem.makeAnalysis(self.document, "Analysis")
        self.document.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def _paired(self, maker):
        """A constraint holding one slave and, last, one master."""
        obj = maker(self.document, "Paired")
        self.analysis.addObject(obj)
        obj.References = [(self.box, "Face6"), (self.plane, "Face1")]
        self.document.recompute()
        return obj

    def _split(self, obj):
        """How many of the symbols belong to the slave, and how many follow."""
        groups = list(obj.PointsPerReference)
        self.assertEqual(len(groups), 2, "a run per reference is what splits the symbols")
        return groups[0]

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestConstraintSymbolsGui tests {2}\n{0}".format(
                100 * "*", 10 * "*", 42 * "*"
            )
        )

    def test_a_fresh_constraint_leaves_every_symbol_upright(self):
        tie = self._paired(ObjectsFem.makeConstraintTie)

        placements = tie.ViewObject.SymbolPlacements
        self.assertEqual(len(placements), 2)
        self.assertTrue(all(placement.isIdentity() for placement in placements))

    def test_reversing_the_master_turns_only_the_master_symbols(self):
        tie = self._paired(ObjectsFem.makeConstraintTie)
        slave = self._split(tie)
        upright = symbol_axes(tie)

        tie.ReversedMaster = [True]
        flipped = symbol_axes(tie)

        for before, after in zip(upright[:slave], flipped[:slave]):
            self.assertTrue(before.isEqual(after, 1e-5), "a slave symbol moved")
        for before, after in zip(upright[slave:], flipped[slave:]):
            self.assertLess((before + after).Length, 1e-5, "a master symbol did not turn")

    def test_reversing_the_slave_turns_only_the_slave_symbols(self):
        tie = self._paired(ObjectsFem.makeConstraintTie)
        slave = self._split(tie)
        upright = symbol_axes(tie)

        tie.ReversedSlave = [True] * slave
        flipped = symbol_axes(tie)

        for before, after in zip(upright[:slave], flipped[:slave]):
            self.assertLess((before + after).Length, 1e-5, "a slave symbol did not turn")
        for before, after in zip(upright[slave:], flipped[slave:]):
            self.assertTrue(before.isEqual(after, 1e-5), "a master symbol moved")

    def test_a_contact_answers_the_same_way(self):
        # Contact is a C++ constraint and reaches the property from the other
        # side, so the two are worth asking separately.
        contact = self._paired(ObjectsFem.makeConstraintContact)
        slave = self._split(contact)
        upright = symbol_axes(contact)

        contact.ReversedMaster = [True]
        placements = contact.ViewObject.SymbolPlacements
        self.assertTrue(placements[0].isIdentity())
        self.assertAlmostEqual(placements[1].Rotation.Angle, math.pi, places=5)

        flipped = symbol_axes(contact)
        for before, after in zip(upright[slave:], flipped[slave:]):
            self.assertLess((before + after).Length, 1e-5, "a master symbol did not turn")

    def test_unticking_puts_the_symbols_back(self):
        tie = self._paired(ObjectsFem.makeConstraintTie)
        upright = symbol_axes(tie)

        tie.ReversedMaster = [True]
        tie.ReversedMaster = [False]

        for before, after in zip(upright, symbol_axes(tie)):
            self.assertTrue(before.isEqual(after, 1e-5), "a symbol stayed turned")

    def test_a_reference_added_later_is_drawn_upright(self):
        # The placements are indexed by reference, so a list left over from a
        # shorter one would hand the wrong side to the wrong symbols.
        tie = self._paired(ObjectsFem.makeConstraintTie)
        tie.ReversedMaster = [True]

        tie.References = [(self.box, "Face6"), (self.box, "Face5"), (self.plane, "Face1")]
        self.document.recompute()

        placements = tie.ViewObject.SymbolPlacements
        self.assertEqual(len(placements), 3)
        self.assertTrue(placements[0].isIdentity())
        self.assertTrue(placements[1].isIdentity())
        self.assertAlmostEqual(placements[2].Rotation.Angle, math.pi, places=5)

        # And every symbol still gets one, whichever reference it came from.
        self.assertEqual(sum(tie.PointsPerReference), len(tie.Points))
        self.assertEqual(len(symbol_axes(tie)), len(tie.Points))

    def test_the_panel_writes_the_side_before_it_is_closed(self):
        # The marker follows the properties, so a panel that only wrote them on
        # OK would leave the user ticking a box and seeing nothing.
        from femtaskpanels import task_constraint_tie

        tie = self._paired(ObjectsFem.makeConstraintTie)
        panel = task_constraint_tie._TaskPanel(tie)
        try:
            panel.parameter_widget.ckb_rev_master.setChecked(True)
            self.assertEqual(list(tie.ReversedMaster), [True])

            panel.parameter_widget.ckb_rev_master.setChecked(False)
            self.assertEqual(list(tie.ReversedMaster), [False])
        finally:
            panel.selection_widget.finish_selection()
            FreeCADGui.Selection.clearSelection()

    def test_the_reversed_boxes_are_marked_as_being_for_shell_surfaces(self):
        # The setting does nothing to a face of a solid, and a user who does
        # not know that has no way of telling a moot box from a broken one.
        from PySide import QtGui

        from femtaskpanels import task_constraint_tie

        tie = self._paired(ObjectsFem.makeConstraintTie)
        panel = task_constraint_tie._TaskPanel(tie)
        try:
            widget = panel.parameter_widget
            box = widget.ckb_rev_master.parentWidget()
            while box is not None and not isinstance(box, QtGui.QGroupBox):
                box = box.parentWidget()

            self.assertIsNotNone(box, "the reversed boxes stand in no frame of their own")
            self.assertIn("shell", box.title().lower())
            self.assertIs(widget.ckb_rev_slave.window(), box.window())
        finally:
            panel.selection_widget.finish_selection()
            FreeCADGui.Selection.clearSelection()
