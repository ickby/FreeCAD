# ***************************************************************************
# *   Copyright (c) 2025 Stefan Tröger <stefantroeger@gmx.net>              *
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

__title__ = "FreeCAD FEM geometry view providers"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

## @package view_geometry_base
#  \ingroup FEM
#  \brief Thin Python view providers for FemGeometry FeaturePython objects

import FreeCAD

from femtaskpanels import task_geometry

from . import view_base_femobject


def chain_group(obj):
    """The geometry group obj is a build step of, or None."""
    for parent in obj.InList:
        if parent.isDerivedFrom("Fem::FemGeometry") and obj in getattr(parent, "Group", []):
            return parent
    return None


def move_step(obj, offset):
    """
    Move a build step along its chain.

    The order of the group is what defines the chain, the group rewires the Base
    links from it, so moving a step is a reorder of the group members.
    """
    group = chain_group(obj)
    if group is None:
        return
    steps = list(group.Group)
    index = steps.index(obj)
    target = index + offset
    if target < 0 or target >= len(steps):
        return

    doc = obj.Document
    doc.openTransaction("Move geometry step")
    steps.insert(target, steps.pop(index))
    group.Group = steps
    doc.commitTransaction()
    doc.recompute()


def set_input_preview(obj, on):
    """Show the input shape of a chain step while its task panel is open."""
    base = obj.Base
    if base is not None and base.ViewObject is not None:
        base.ViewObject.setChainPreview(on)


def set_input_marks(obj, role, elements, color=None):
    """
    Colour the elements a chain step refers to on the input shape it is picked
    from, so the panel and the 3D view agree on what is already chosen.

    The role keeps one panel's marks apart from another's; passing no elements
    drops that role.
    """
    base = obj.Base
    if base is not None and base.ViewObject is not None:
        base.ViewObject.setElementHighlight(role, list(elements), color)


def clear_input_marks(obj, *roles):
    """Drop the given roles from the input shape of a chain step."""
    base = obj.Base
    if base is None or base.ViewObject is None:
        return
    for role in roles:
        base.ViewObject.clearElementHighlight(role)


def set_tool_preview(obj, preview):
    """
    Show the cutting tool of a chain step on the input shape it edits.

    preview is a PartitionToolPreview, or None to clear. Mode is kept on the
    Python side for later display variants; the VP tessellates the shape only.
    """
    base = obj.Base
    if base is None or base.ViewObject is None:
        return
    if preview is None:
        base.ViewObject.clearToolPreview()
        return
    base.ViewObject.setToolPreview(preview.shape)


def clear_tool_preview(obj):
    """Drop the cutting-tool overlay from the input shape of a chain step."""
    base = obj.Base
    if base is not None and base.ViewObject is not None:
        base.ViewObject.clearToolPreview()


class VPGeometryGroup(view_base_femobject.VPBaseFemObject):
    """
    View provider for GeometryGroup. Adds the geo-feature-group extension
    so children are claimed; rendering is handled by ViewProviderFemGeometry.
    """

    def __init__(self, vobj):
        super().__init__(vobj)
        vobj.addExtension("Gui::ViewProviderGeoFeatureGroupExtensionPython")

    def getIcon(self):
        return ":/icons/fem-post-geo-box.svg"

    def dumps(self):
        return None

    def loads(self, state):
        return None


class VPGeometryStep(view_base_femobject.VPBaseFemObject):
    """
    Base view provider for the build steps of a geometry chain.

    A step has no visual of its own, the group renders the result of the chain.
    What the step brings to the tree is its place in the order, so it offers to
    move along the chain.
    """

    def getDisplayModes(self, obj):
        return []

    def setupContextMenu(self, vobj, menu):
        group = chain_group(vobj.Object)
        if group is None:
            return False

        steps = list(group.Group)
        index = steps.index(vobj.Object)

        up = menu.addAction(FreeCAD.Qt.translate("FEM", "Move step up"))
        up.setEnabled(index > 0)
        up.triggered.connect(self.move_up)

        down = menu.addAction(FreeCAD.Qt.translate("FEM", "Move step down"))
        down.setEnabled(index < len(steps) - 1)
        down.triggered.connect(self.move_down)

        # Falsy keeps the standard entries, the edit action among them
        return False

    def move_up(self):
        move_step(self.Object, -1)

    def move_down(self):
        move_step(self.Object, 1)


class VPGeometryImport(VPGeometryStep):
    """
    View provider for GeometryImport. Rendering is handled by
    ViewProviderFemGeometry (C++ / ViewProviderFemGeometryPython).
    """

    def __init__(self, vobj):
        super().__init__(vobj)

    def getIcon(self):
        return ":/icons/fem-post-geo-box.svg"

    def setEdit(self, vobj, mode=0):
        return super().setEdit(vobj, mode, task_geometry._ImportTaskPanel, hide_mesh=False)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class VPGeometryPartition(VPGeometryStep):
    """View provider for GeometryPartition."""

    def __init__(self, vobj):
        super().__init__(vobj)

    def getIcon(self):
        return ":/icons/FEM_GeometryPartition.svg"

    def setEdit(self, vobj, mode=0):
        from femtaskpanels import task_geometry_partition

        set_input_preview(vobj.Object, True)
        return super().setEdit(
            vobj, mode, task_geometry_partition._PartitionTaskPanel, hide_mesh=False
        )

    def unsetEdit(self, vobj, mode=0):
        set_input_preview(vobj.Object, False)
        clear_tool_preview(vobj.Object)
        return super().unsetEdit(vobj, mode)

    def dumps(self):
        return None

    def loads(self, state):
        return None
