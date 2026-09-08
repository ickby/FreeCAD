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
import FreeCADGui

from femtaskpanels import task_geometry

from . import view_base_femobject

# Faint enough that the overlay guides without hiding the geometry underneath.
TOOL_PREVIEW_TRANSPARENCY = 0.85


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


def edit_subject(obj):
    """
    The geometry an open panel for obj is picked on, or None.

    Asked of FemGui rather than worked out here, so that the rule - the input
    for a step that stores element references, the step itself for one that
    does not - is stated once. Which geometry is drawn for the panel follows
    from the same answer, and is arranged by the edit scope; nothing here has
    to switch a render on.
    """
    import FemGui

    return FemGui.geometryEditSubject(obj)


def set_input_marks(obj, role, elements, color=None):
    """
    Colour the elements a chain step refers to on the geometry it is picked on,
    so the panel and the 3D view agree on what is already chosen.

    Addressed to the edit subject rather than to Base: the marks belong on
    whatever is drawn for the panel, and for a step that makes geometry rather
    than altering it that is the step itself.

    The role keeps one panel's marks apart from another's; passing no elements
    drops that role.
    """
    subject = edit_subject(obj)
    if subject is not None and subject.ViewObject is not None:
        subject.ViewObject.setElementHighlight(role, list(elements), color)


def clear_input_marks(obj, *roles):
    """Drop the given roles from the geometry a chain step is picked on."""
    subject = edit_subject(obj)
    if subject is None or subject.ViewObject is None:
        return
    for role in roles:
        subject.ViewObject.clearElementHighlight(role)


def set_tool_preview(obj, preview):
    """
    Show the cutting tool of a chain step on the input shape it edits.

    preview is a PartitionToolPreview, or None to clear. Mode is kept on the
    Python side for later display variants; the VP tessellates the shape only.
    """
    subject = edit_subject(obj)
    if subject is None or subject.ViewObject is None:
        return
    if preview is None:
        subject.ViewObject.clearToolPreview()
        return
    subject.ViewObject.setToolPreview(preview.shape, None, TOOL_PREVIEW_TRANSPARENCY)


def set_shape_preview(obj, shape, color=None, transparency=TOOL_PREVIEW_TRANSPARENCY):
    """
    Show any shape over the geometry a chain step edits.

    The same overlay the partition step shows its cutting plane on. Nothing
    about it is particular to a cutting tool: a step that makes faces can show
    the faces it would make, which is worth more to the user than a description
    of them.
    """
    subject = edit_subject(obj)
    if subject is None or subject.ViewObject is None:
        return
    if shape is None or shape.isNull():
        subject.ViewObject.clearToolPreview()
        return
    subject.ViewObject.setToolPreview(shape, color, transparency)


def clear_tool_preview(obj):
    """Drop the cutting-tool overlay from the geometry a chain step is picked on."""
    subject = edit_subject(obj)
    if subject is not None and subject.ViewObject is not None:
        subject.ViewObject.clearToolPreview()


def _geometry_icon(obj):
    """
    The box, marked when what it shows is behind the model it was built from.

    The mark is drawn into the artwork rather than composed over the icon here:
    a badge painted at runtime has to be told about the icon size, the theme and
    the device pixel ratio, and gets all three wrong somewhere. A second file
    costs a few lines of SVG and is right everywhere the first one is.
    """
    if getattr(obj, "Outdated", False):
        return ":/icons/fem-post-geo-box-outdated.svg"
    return ":/icons/fem-post-geo-box.svg"


UPDATE_COMMANDS = (
    "FEM_GeometryUpdate",
    "FEM_GeometryUpdateMesh",
    "FEM_GeometryUpdateLinked",
)


def add_update_actions(menu):
    """
    Offer the update where the mark is seen, not only where the toolbar is.

    A user meets an out of date geometry in the tree, so the repair belongs in
    the menu the tree opens. Only what can do something is offered: the entries
    grey themselves out on the toolbar, and an entry that would do nothing is
    better left out of a context menu than shown dead in it.
    """
    added = False
    for name in UPDATE_COMMANDS:
        command = FreeCADGui.Command.get(name)
        if command is None or not command.isActive():
            continue
        info = command.getInfo()
        action = menu.addAction(info["menuText"].replace("&", ""))
        action.setToolTip(info["toolTip"])
        action.triggered.connect(lambda checked=False, cmd=name: FreeCADGui.runCommand(cmd))
        added = True
    return added


class _OutdatedIconMixin:
    """Keeps the tree icon in step with the mark the object carries."""

    def updateData(self, obj, prop):
        # The property is an output of execute(), so it arrives without the
        # object having otherwise changed; nothing else would repaint the row.
        if prop == "Outdated" and self.ViewObject is not None:
            self.ViewObject.signalChangeIcon()


class VPGeometryGroup(_OutdatedIconMixin, view_base_femobject.VPBaseFemObject):
    """
    View provider for GeometryGroup. Adds the geo-feature-group extension
    so children are claimed; rendering is handled by ViewProviderFemGeometry.
    """

    def __init__(self, vobj):
        super().__init__(vobj)
        vobj.addExtension("Gui::ViewProviderGeoFeatureGroupExtensionPython")

    def getIcon(self):
        return _geometry_icon(self.Object)

    def setupContextMenu(self, vobj, menu):
        add_update_actions(menu)
        # Falsy keeps the standard entries
        return False

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

        if add_update_actions(menu):
            menu.insertSeparator(menu.actions()[2])

        # Falsy keeps the standard entries, the edit action among them
        return False

    def move_up(self):
        move_step(self.Object, -1)

    def move_down(self):
        move_step(self.Object, 1)


class VPGeometryImport(_OutdatedIconMixin, VPGeometryStep):
    """
    View provider for GeometryImport. Rendering is handled by
    ViewProviderFemGeometry (C++ / ViewProviderFemGeometryPython).
    """

    def __init__(self, vobj):
        super().__init__(vobj)

    def getIcon(self):
        return _geometry_icon(self.Object)

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

        # Nothing to switch on here: opening the panel opens an edit scope, and
        # the scope is what puts the geometry this step is picked on on show.
        return super().setEdit(
            vobj, mode, task_geometry_partition._PartitionTaskPanel, hide_mesh=False
        )

    def unsetEdit(self, vobj, mode=0):
        clear_tool_preview(vobj.Object)
        return super().unsetEdit(vobj, mode)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class VPGeometryShellBuilder(VPGeometryStep):
    """View provider for GeometryShellBuilder."""

    def __init__(self, vobj):
        super().__init__(vobj)

    def getIcon(self):
        return ":/icons/FEM_GeometryShellBuilder.svg"

    def setEdit(self, vobj, mode=0):
        from femtaskpanels import task_geometry_shellbuilder

        return super().setEdit(
            vobj, mode, task_geometry_shellbuilder._ShellBuilderTaskPanel, hide_mesh=False
        )

    def dumps(self):
        return None

    def loads(self, state):
        return None
