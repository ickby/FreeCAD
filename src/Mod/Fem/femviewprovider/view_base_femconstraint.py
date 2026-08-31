# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2017 Markus Hovorka <m.hovorka@live.de>                 *
# *   Copyright (c) 2018 Bernd Hahnebach <bernd@bimstatik.org>              *
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

__title__ = "FreeCAD FEM base constraint ViewProvider"
__author__ = "Markus Hovorka, Bernd Hahnebach"
__url__ = "https://www.freecad.org"

## @package view_base_femconstraint
#  \ingroup FEM
#  \brief view provider for Python base constraint object

from FreeCAD import Placement, Rotation, Vector, getResourceDir
from femviewprovider import view_base_femobject

# A constraint symbol is modelled standing on the surface and reaching along its
# own Y, so a half turn about Z is what sinks it through to the other side.
UPRIGHT = Placement()
REVERSED = Placement(Vector(), Rotation(Vector(0, 0, 1), 180))

# Properties which decide the side a symbol is drawn on. PointsPerReference is
# in the list because editing the references changes how many symbols there are
# to hand a side to, not because it says anything about sides itself.
SIDE_PROPERTIES = ("ReversedMaster", "ReversedSlave", "PointsPerReference")


class VPBaseFemConstraint(view_base_femobject.VPBaseFemObject):
    """Proxy View Provider for Pythons base constraint."""

    resource_symbol_dir = getResourceDir() + "Mod/Fem/Resources/symbols/"


def reference_count(obj):
    """How many single references the constraint holds, sub-elements counted."""
    return sum(len(subs) for _, subs in obj.References)


def master_slave_sides(obj):
    """
    One placement per reference, reversed ones turned over.

    References holds the slaves first and the single master last, the same
    order the solver writers read it back in, so a side can be handed out by
    position alone.

    A reversal only reaches the deck for a reference meshed with shell or beam
    elements, where the element has two skins to choose between. The mark is
    drawn wherever the box is ticked all the same: a symbol contradicting the
    checkbox next to it would teach the user something worse than nothing.
    """
    count = reference_count(obj)
    if count < 1:
        return []

    # One checkbox fills a whole list, and a document written before the panel
    # filled it may hold a shorter one, so the first entry stands for the side.
    slave = bool(obj.ReversedSlave) and bool(obj.ReversedSlave[0])
    master = bool(obj.ReversedMaster) and bool(obj.ReversedMaster[0])
    sides = [slave] * (count - 1) + [master]
    return [REVERSED if flip else UPRIGHT for flip in sides]


def apply_sides(vobj, placements):
    """
    Hand *placements* to the view provider, unless it already has them.

    Restoring a document recomputes the points, which lands here, and writing
    a property that is already right would redraw every symbol for nothing.
    """
    current = vobj.SymbolPlacements
    if len(current) == len(placements) and all(
        a.Base.isEqual(b.Base, 1e-9) and a.Rotation.isSame(b.Rotation, 1e-9)
        for a, b in zip(current, placements)
    ):
        return
    vobj.SymbolPlacements = placements
