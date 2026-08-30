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

__title__ = "FreeCAD FEM geometry partition task panel"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

from PySide import QtGui

import FreeCAD

from femguiutils.selection_rules import ReferenceRule, shape_kind
from femguiutils.selection_slots import ReferenceSelection

from femobjects import geometry_partition
from femviewprovider import view_geometry_base

from . import base_femtaskpanel

# What a mark means is told by its colour, so the three kinds of reference this
# panel holds are kept apart and clear of the green of a selection and the orange
# of a hover.
MARK_TARGETS = "GeometryPartition.Targets"
MARK_POINTS = "GeometryPartition.Points"
MARK_TOOL = "GeometryPartition.Tool"

MARK_COLORS = {
    MARK_TARGETS: (0.85, 0.15, 0.85),
    MARK_POINTS: (0.0, 0.75, 0.95),
    MARK_TOOL: (0.15, 0.4, 1.0),
}


def _references_to_links(references):
    """Convert picker tuples to PropertyLinkSubList assignment."""
    grouped = {}
    for obj, sub in references:
        grouped.setdefault(obj, []).append(sub)
    return [(obj, subs) for obj, subs in grouped.items()]


def _links_to_references(links):
    references = []
    if not links:
        return references
    for link in links:
        obj = link[0]
        subs = link[1] if isinstance(link[1], (list, tuple)) else (link[1],)
        for sub in subs:
            if sub:
                references.append((obj, sub))
    return references


def _sub_element_rule(kind, max_count=None):
    """Elements of one kind, on the geometry the step builds on."""
    return ReferenceRule(
        types=(kind,),
        max_count=max_count,
        homogeneous=True,
        scope="geometry",
    )


def _tool_rule():
    """A whole datum, sketch or face, on any object in the document."""
    return ReferenceRule(
        types=("Face",),
        max_count=1,
        homogeneous=False,
        scope="any",
        object_kinds=(
            "Part::DatumPlane",
            "Sketcher::SketchObject",
            "Part::Feature",
        ),
        allow_empty_sub=True,
    )


class _PartitionTaskPanel(base_femtaskpanel._BaseTaskPanel):
    """Task panel for partitioning geometry in the analysis chain."""

    def __init__(self, obj):
        super().__init__(obj)
        # Restoring the widgets from the object fires their change signals, and
        # a write-back before every widget holds its stored value would clear
        # the ones not restored yet.
        self._loading = True
        self.base_obj = obj.Base
        self._solids_before = len(obj.Base.Shape.Solids) if obj.Base else 0

        self.form = QtGui.QWidget()
        layout = QtGui.QVBoxLayout()

        # One group for the whole panel, not one per box. The coordinator it
        # owns keeps a single slot armed and a single gate on the 3D view, so
        # arming any box disarms the last and a pick has one place to land.
        self.picker = ReferenceSelection(
            obj, parent=self.form, geometry=self.base_obj, auto_install=False
        )
        self.picker.hide()

        # A step cuts either solids or sub-elements, never both, so the kind is
        # chosen up front. It also tells the picker how to read a 3D click,
        # which can only ever land on a face, edge or vertex.
        self.kind_combo = QtGui.QComboBox()
        for kind, label in (
            ("Solid", FreeCAD.Qt.translate("FEM", "Solids")),
            ("Face", FreeCAD.Qt.translate("FEM", "Faces")),
            ("Edge", FreeCAD.Qt.translate("FEM", "Edges")),
        ):
            self.kind_combo.addItem(label, kind)

        # The panel draws its own marks, in the colours below, so the slots
        # are told to leave the marking alone and only to match the colour.
        self.targets = self._add_slot(
            "Targets",
            FreeCAD.Qt.translate("FEM", "Targets"),
            _sub_element_rule("Solid"),
            MARK_TARGETS,
        )
        self.targets.set_picks(_links_to_references(obj.Elements))
        existing = geometry_partition.target_types(obj.Elements)
        kind_index = self.kind_combo.findData(next(iter(existing)) if existing else "Solid")
        if kind_index >= 0:
            self.kind_combo.setCurrentIndex(kind_index)
        self.apply_target_kind()
        self.kind_combo.currentIndexChanged.connect(self.kind_changed)

        self.method_combo = QtGui.QComboBox()
        for method in geometry_partition.PARTITION_METHODS:
            self.method_combo.addItem(method)
        self.method_combo.currentIndexChanged.connect(self.method_changed)

        self.method_hint = QtGui.QLabel()
        self.method_hint.setWordWrap(True)

        self.points_3 = self._add_slot(
            "Points3",
            FreeCAD.Qt.translate("FEM", "Plane points"),
            _sub_element_rule("Vertex", max_count=3),
            MARK_POINTS,
        )
        self.tool_ref = self._add_slot(
            "Tool",
            FreeCAD.Qt.translate("FEM", "Plane reference"),
            _tool_rule(),
            MARK_TOOL,
        )
        self.tool_face = self._add_slot(
            "ToolFace",
            FreeCAD.Qt.translate("FEM", "Face to extend"),
            _sub_element_rule("Face", max_count=1),
            MARK_TOOL,
        )

        self.param_spin = QtGui.QDoubleSpinBox()
        self.param_spin.setRange(0.0, 1.0)
        self.param_spin.setSingleStep(0.05)
        self.param_spin.setValue(obj.Parameter)
        self.param_mid = QtGui.QPushButton(FreeCAD.Qt.translate("FEM", "Midpoint"))
        self.param_mid.clicked.connect(lambda: self.param_spin.setValue(0.5))
        param_row = QtGui.QHBoxLayout()
        param_row.addWidget(QtGui.QLabel(FreeCAD.Qt.translate("FEM", "Parameter")))
        param_row.addWidget(self.param_spin)
        param_row.addWidget(self.param_mid)
        self.param_page = QtGui.QWidget()
        self.param_page.setLayout(param_row)

        self.points_2 = self._add_slot(
            "Points2",
            FreeCAD.Qt.translate("FEM", "Path vertices"),
            _sub_element_rule("Vertex", max_count=2),
            MARK_POINTS,
        )

        # What a method asks for is shown and the rest is hidden. Stacking
        # them instead would hold the height of the tallest page open under
        # every method, and most of them ask for one line or nothing at all.
        self.method_pages = {
            geometry_partition.METHOD_PLANE_3P: self.points_3,
            geometry_partition.METHOD_PLANE_REF: self.tool_ref,
            geometry_partition.METHOD_EXTEND_FACE: self.tool_face,
            geometry_partition.METHOD_EDGE_PARAM: self.param_page,
            geometry_partition.METHOD_SHORTEST_PATH: self.points_2,
        }

        self.summary = QtGui.QLabel()

        kind_row = QtGui.QHBoxLayout()
        kind_row.addWidget(QtGui.QLabel(FreeCAD.Qt.translate("FEM", "Target kind")))
        kind_row.addWidget(self.kind_combo)
        layout.addLayout(kind_row)
        layout.addWidget(self.targets)
        layout.addWidget(QtGui.QLabel(FreeCAD.Qt.translate("FEM", "Method")))
        layout.addWidget(self.method_combo)
        layout.addWidget(self.method_hint)
        for page in self.method_pages.values():
            layout.addWidget(page)
        layout.addWidget(self.summary)
        layout.addStretch(1)
        self.form.setLayout(layout)

        # A stored method can have become invalid for the stored targets, so the
        # panel opens on one that can actually run instead of a greyed-out entry.
        method = geometry_partition.first_available_method(obj.Elements, obj.Method)
        index = self.method_combo.findText(method)
        if index >= 0:
            self.method_combo.setCurrentIndex(index)
        stored_points = _links_to_references(obj.Points)
        if obj.Method == geometry_partition.METHOD_SHORTEST_PATH:
            self.points_2.set_picks(stored_points)
        else:
            self.points_3.set_picks(stored_points)
        if obj.Tool:
            tool = obj.Tool
            subs = tool[1] if isinstance(tool[1], (list, tuple)) else (tool[1],)
            sub = subs[0] if subs else ""
            if obj.Method == geometry_partition.METHOD_EXTEND_FACE:
                self.tool_face.set_picks([(tool[0], sub)] if sub else [])
            else:
                self.tool_ref.set_picks([(tool[0], sub)])

        self.param_spin.valueChanged.connect(self.apply_properties)
        # Only now, so restoring the boxes above does not write back over the
        # ones that have not been restored yet.
        self.targets.picksChanged.connect(lambda *_: self.targets_changed())
        for slot in (self.points_3, self.tool_ref, self.tool_face, self.points_2):
            slot.picksChanged.connect(lambda *_: self.apply_properties())
        self._loading = False

        self._update_method_availability()
        self._update_method_page()
        # Picking starts on Targets, and a create-command stash lands there.
        # Subordinate boxes are never a prefill destination.
        self.picker.begin_selection()
        self.picker.arm("Targets")
        self.picker.consume_handoff()
        self._update_summary()
        self._update_marks()
        self._update_tool_preview()

    def _add_slot(self, slot_id, title, rule, mark_role):
        return self.picker.add_slot(slot_id, title, rule, marks=False, color=MARK_COLORS[mark_role])

    def _element_links(self):
        return _references_to_links(self.targets.picks)

    def apply_target_kind(self):
        """Restrict the target box to one shape kind, dropping picks of the others."""
        kind = self.kind_combo.currentData()
        self.targets.set_rule(_sub_element_rule(kind))
        kept = [ref for ref in self.targets.picks if shape_kind(ref[1]) == kind]
        if kept != self.targets.picks:
            self.targets.set_picks(kept)

    def kind_changed(self):
        self.apply_target_kind()
        self.targets_changed()

    def targets_changed(self):
        self._update_method_availability()
        current = self.method_combo.currentText()
        if not geometry_partition.method_available(current, self._element_links()):
            fallback = geometry_partition.first_available_method(self._element_links(), current)
            index = self.method_combo.findText(fallback)
            if index >= 0:
                self.method_hint.setText(
                    FreeCAD.Qt.translate(
                        "FEM",
                        "Method '{old}' is not valid for the selected targets; "
                        "switched to '{new}'.",
                    ).format(old=current, new=fallback)
                )
                self.method_combo.setCurrentIndex(index)
        self.apply_properties()

    def method_changed(self):
        self._update_method_page()
        self.apply_properties()

    def _method_reasons(self):
        """(available, requirement) per method for the current target list."""
        links = self._element_links()
        requirements = {
            geometry_partition.METHOD_EDGE_PARAM: FreeCAD.Qt.translate(
                "FEM", "All targets must be edges."
            ),
            geometry_partition.METHOD_SHORTEST_PATH: FreeCAD.Qt.translate(
                "FEM", "Exactly one face target is required."
            ),
        }
        return {
            method: (
                geometry_partition.method_available(method, links),
                requirements.get(method, ""),
            )
            for method in geometry_partition.PARTITION_METHODS
        }

    def _update_method_availability(self):
        reasons = self._method_reasons()
        for index, method in enumerate(geometry_partition.PARTITION_METHODS):
            available, reason = reasons[method]
            item = self.method_combo.model().item(index)
            item.setEnabled(available)
            item.setToolTip(reason if reason else method)

    def _update_method_page(self):
        method = self.method_combo.currentText()
        for name, page in self.method_pages.items():
            page.setVisible(name == method)
        # A box the method just hid cannot be clicked any more, so picking
        # would go on filling one the user can no longer see.
        armed = self.picker.coordinator.armed_slot
        if armed is not None and not armed.isVisibleTo(self.form):
            self.picker.arm("Targets")
        if not self.method_hint.text():
            self.method_hint.setText("")

    def apply_properties(self):
        if self._loading:
            return
        method = self.method_combo.currentText()
        self.obj.Method = method
        self.obj.Elements = self._element_links()
        self.obj.Parameter = self.param_spin.value()

        if method == geometry_partition.METHOD_PLANE_3P:
            self.obj.Points = _references_to_links(self.points_3.picks)
            self.obj.Tool = None
        elif method == geometry_partition.METHOD_PLANE_REF:
            self.obj.Points = []
            self.obj.Tool = self._tool_link(self.tool_ref, keep_whole_object=True)
        elif method == geometry_partition.METHOD_EXTEND_FACE:
            self.obj.Points = []
            self.obj.Tool = self._tool_link(self.tool_face)
        elif method == geometry_partition.METHOD_EDGE_PARAM:
            self.obj.Points = []
            self.obj.Tool = None
        elif method == geometry_partition.METHOD_SHORTEST_PATH:
            self.obj.Points = _references_to_links(self.points_2.picks)
            self.obj.Tool = None

        self.obj.Document.recompute()
        self._update_summary()
        self._update_marks()
        self._update_tool_preview()

    def _tool_link(self, slot, keep_whole_object=False):
        """The slot's single pick as a PropertyLinkSub value, or None."""
        if not slot.picks:
            return None
        obj, sub = slot.picks[0]
        if not sub and not keep_whole_object:
            return None
        return (obj, (sub,) if sub else ())

    def _marked_elements(self):
        """Element names to mark per role, for the method currently chosen."""
        method = self.method_combo.currentText()
        points = []
        if method == geometry_partition.METHOD_PLANE_3P:
            points = self.points_3.picks
        elif method == geometry_partition.METHOD_SHORTEST_PATH:
            points = self.points_2.picks
        tool = []
        if method == geometry_partition.METHOD_EXTEND_FACE:
            tool = self.tool_face.picks
        return {
            MARK_TARGETS: self.targets.picks,
            MARK_POINTS: points,
            MARK_TOOL: tool,
        }

    def _update_marks(self):
        if not self.base_obj:
            return
        for role, references in self._marked_elements().items():
            # Only what sits on the input shape can be marked on it; a plane
            # reference picked off some other object is not part of it.
            elements = [sub for obj, sub in references if obj == self.base_obj and sub]
            view_geometry_base.set_input_marks(self.obj, role, elements, MARK_COLORS[role])

    def _update_tool_preview(self):
        preview = geometry_partition.build_tool_preview(self.obj)
        view_geometry_base.set_tool_preview(self.obj, preview)

    def _update_summary(self):
        if not self.base_obj:
            self.summary.setText("")
            return
        solids_after = len(self.obj.Shape.Solids) if not self.obj.Shape.isNull() else 0
        self.summary.setText(
            FreeCAD.Qt.translate(
                "FEM",
                "{before} solids before, {after} after the last recompute.",
            ).format(before=self._solids_before, after=solids_after)
        )

    def deactivate(self):
        self.picker.finish_selection()
        if self.base_obj:
            view_geometry_base.clear_input_marks(self.obj, MARK_TARGETS, MARK_POINTS, MARK_TOOL)
            view_geometry_base.clear_tool_preview(self.obj)

    def accept(self):
        self.apply_properties()
        self.deactivate()
        return super().accept()

    def reject(self):
        self.deactivate()
        return super().reject()
