# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2015 Bernd Hahnebach <bernd@bimstatik.org>              *
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

__title__ = "FreeCAD FEM element geometry 2D document object"
__author__ = "Bernd Hahnebach"
__url__ = "https://www.freecad.org"

## @package element_geometry2D
#  \ingroup FEM
#  \brief element geometry 2D object

import FreeCAD

from . import base_femelement
from . import geometry_shellbuilder
from .base_fempythonobject import _PropHelper

MODE_MANUAL = "Manual"
MODE_FROM_GEOMETRY = "From geometry"

THICKNESS_MODES = (MODE_MANUAL, MODE_FROM_GEOMETRY)


class ElementGeometry2D(base_femelement.BaseFemElement):
    """
    The ElementGeometry2D object
    """

    Type = "Fem::ElementGeometry2D"

    def __init__(self, obj):
        super().__init__(obj)

    def _get_properties(self):
        prop = super()._get_properties()

        prop.append(
            _PropHelper(
                type="App::PropertyEnumeration",
                name="ThicknessMode",
                group="ShellThickness",
                doc="Where the thickness comes from: typed in, or measured by the shell builder",
                value=list(THICKNESS_MODES),
            )
        )
        prop.append(
            _PropHelper(
                type="App::PropertyLength",
                name="Thickness",
                group="ShellThickness",
                doc="Set thickness of the shell elements",
                value="0 mm",
            )
        )
        prop.append(
            _PropHelper(
                type="App::PropertyFloat",
                name="Offset",
                group="ShellThickness",
                doc="Set thickness offset of the shell elements",
                value=0.0,
            )
        )

        return prop

    def onChanged(self, obj, prop):
        if prop != "ThicknessMode":
            return
        # The mode is added before the two properties it governs, so the first
        # change arrives while they do not exist yet.
        if not hasattr(obj, "Thickness") or not hasattr(obj, "Offset"):
            return

        # A measured value is not the user's to edit: it belongs to the wall the
        # shell builder found, and typing over it would claim a thickness the
        # geometry does not have.
        measured = obj.ThicknessMode == MODE_FROM_GEOMETRY
        for name in ("Thickness", "Offset"):
            obj.setPropertyStatus(name, "ReadOnly" if measured else "-ReadOnly")

    def execute(self, obj):
        """
        Take the thickness from the geometry when it was measured there.

        The shell builder wrote down what each face it produced was made from,
        because the solid it measured is gone by the time anything asks. This
        reads that back for the faces this object refers to, so a thickness
        reaches the solver without anybody copying a number by hand.

        All the faces of one shell section have to agree: the section is written
        once for the whole element set, so two thicknesses under one object
        would silently pick one of them.
        """
        if obj.ThicknessMode != MODE_FROM_GEOMETRY:
            return

        found = []
        for link in obj.References:
            source = link[0]
            subs = link[1] if isinstance(link[1], (list, tuple)) else (link[1],)
            for sub in subs:
                data = geometry_shellbuilder.shell_data_for_reference(source, sub)
                if data is not None:
                    found.append(data)

        if not found:
            raise ValueError(
                f"{obj.Name}: no shell builder recorded a thickness for these faces"
            )

        thicknesses = {round(value, 7) for value, _ in found}
        if len(thicknesses) > 1:
            raise ValueError(
                f"{obj.Name}: the faces carry different thicknesses "
                f"({', '.join(f'{value:g}' for value in sorted(thicknesses))} mm). "
                "One shell thickness object can only hold one of them."
            )

        thickness, offset = found[0]
        if abs(obj.Thickness.getValueAs("mm").Value - thickness) > 1e-9:
            obj.Thickness = thickness
        if abs(obj.Offset - offset) > 1e-9:
            obj.Offset = offset

    def onDocumentRestored(self, obj):
        # update old project with new properties
        super().onDocumentRestored(obj)
