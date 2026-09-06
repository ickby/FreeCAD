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

    def getChainRole(self) -> str:
        """
        What this object is in its geometry chain right now.

        "Owner" draws the result of its chain, "Step" draws nothing because the
        owner draws its result instead, "Subject" is the geometry an open panel
        is picked on, and "SteppedAside" is an owner making room for a subject
        below it.
        """
        ...

    def setPreselectPromotion(self, on: bool, /) -> None:
        """
        While true, hovering a Face/Edge/Vertex lights the solid(s) that own it.

        Used while a promoting reference slot is armed. The solid becomes the
        preselected element, so the existing volume-preselect path colours
        every face of it.
        """
        ...

    def setElementHighlight(
        self, role: str, elements: object, color: object = None, /
    ) -> None:
        """
        Mark shape elements in a colour of their own, independent of the selection.

        For panels holding references to geometry, so the picked elements stay
        visible while the user goes on selecting. Marking is not selecting: it
        survives a selection change and does not answer to one.

        role : str
            Names the marking consumer. Two panels can mark at once and each
            clears only its own. Where roles overlap, the one set last wins.
        elements : sequence of str
            Element names, either toplevel (Solid2) or sub-element (Face7,
            Edge3, Vertex1). A toplevel marks its faces and only those, so its
            edges and vertices stay free for marks of their own. An empty
            sequence clears the role.
        color : tuple of float, optional
            (r, g, b) in 0..1. Defaults to a distinct marking colour.
        """
        ...

    def clearElementHighlight(self, role: str, /) -> None:
        """Remove the marks of one role, leaving other roles alone."""
        ...

    def getElementHighlight(self, role: str, /) -> list[str]:
        """Element names currently marked by that role."""
        ...

    def setToolPreview(
        self, shape: object, color: object = None, transparency: float = 0.55, /
    ) -> None:
        """
        Show a temporary cutting-tool shape over this geometry.

        Used while a partition panel is open. The overlay is unpickable and
        semi-transparent. Pass a null/empty shape to clear.

        shape : Part.Shape
            The tool geometry to tessellate.
        color : tuple of float, optional
            (r, g, b) in 0..1. Defaults to the partition tool mark colour.
        transparency : float, optional
            0 opaque, 1 fully transparent. Defaults to 0.55.
        """
        ...

    def clearToolPreview(self) -> None:
        """Remove the cutting-tool preview overlay."""
        ...
