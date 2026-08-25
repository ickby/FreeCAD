# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from typing import Any, Final

from Base.Metadata import export
from Base.Vector import Vector

from Gui.ViewProviderDocumentObject import ViewProviderDocumentObject

@export(
    Twin="ViewProviderFemGeometry",
    TwinPointer="ViewProviderFemGeometry",
    Include="Mod/Fem/Gui/ViewProviderFemGeometry.h",
    Namespace="FemGui",
    FatherInclude="Gui/ViewProviderDocumentObjectPy.h",
)
class ViewProviderFemGeometry(ViewProviderDocumentObject):
    """
    ViewProviderFemGeometry class

    Author: Stefan Tröger <stefantroeger@gmx.net>
    License: LGPL-2.1-or-later
    """

    def setClippingPlane(self, name: str, origin: Vector, direction: Vector, /) -> Any:
        """
        Adds or updates a clipping plane for the geometry visualization

        name : str
            Name of the clipping plane. Used to update and remove it later.
        origin: Vector
            A FreeCAD vector defining the origin point of the clipping plane.
        direction: Vector
            A FreeCAD vector defining the direction the plane normal is pointing to.
        """
        ...

    def removeClippingPlane(self, name: str, /) -> Any:
        """Removes the clipping plane with given name from the visualization"""
        ...

    def syncSelectionHighlight(self) -> None:
        """Rebuild 3D selection highlight from the current Gui.Selection"""
        ...
