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

from PySide import QtCore, QtGui

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


_active_picker = None


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


def _arm_picker(picker):
    global _active_picker
    if _active_picker is not None and _active_picker is not picker:
        _active_picker.finish_selection()
    _active_picker = picker


def _disarm_picker(picker):
    global _active_picker
    if _active_picker is picker:
        _active_picker = None


class _SubElementPicker(QtGui.QGroupBox):
    """Pick sub-elements on a geometry object for partition references."""

    changed = QtCore.Signal()

    def __init__(
        self,
        title,
        base_obj,
        types,
        max_count=None,
        allow_external=False,
        feature=None,
        parent=None,
    ):
        super().__init__(title, parent)
        self.base_obj = base_obj
        self.max_count = max_count
        self.allow_external = allow_external
        scope = "any" if allow_external else "geometry"
        self.group = ReferenceSelection(feature, geometry=base_obj, auto_install=False)
        rule = ReferenceRule(
            types=tuple(types),
            max_count=max_count,
            homogeneous=True,
            scope=scope,
        )
        self.slot = self.group.add_slot("Targets", title, rule, marks=False)
        self.slot.picksChanged.connect(lambda *_: self.changed.emit())
        layout = QtGui.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.group)
        self.setLayout(layout)

    @property
    def references(self):
        return list(self.slot.picks)

    def set_references(self, references):
        self.slot.picks = list(references)
        self.slot._commit()

    def set_target_kind(self, kind):
        """Restrict picking to one shape type, dropping picks of the others."""
        self.slot.set_rule(
            ReferenceRule(
                types=(kind,),
                max_count=self.max_count,
                homogeneous=True,
                scope="any" if self.allow_external else "geometry",
            )
        )
        kept = [ref for ref in self.slot.picks if shape_kind(ref[1]) == kind]
        if kept != self.slot.picks:
            self.slot.picks = kept
            self.slot._commit()
            self.changed.emit()

    def start_selection(self):
        _arm_picker(self)
        self.group.coordinator.install()
        self.group.arm(self.slot.slot_id)
        # Whatever is already selected counts, so picking first and then
        # clicking Add works the same way round as Add and then picking.
        self.group.consume_current_selection()

    def finish_selection(self):
        self.group.coordinator.remove()
        _disarm_picker(self)

    def clear_all(self):
        self.slot.clear()


class _ObjectPicker(QtGui.QGroupBox):
    """Pick a single external or internal reference object."""

    changed = QtCore.Signal()

    def __init__(self, title, base_obj, parent=None):
        super().__init__(title, parent)
        self.base_obj = base_obj
        self.group = ReferenceSelection(None, geometry=base_obj, auto_install=False)
        rule = ReferenceRule(
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
        self.slot = self.group.add_slot("Tool", title, rule, marks=False)
        self.slot.picksChanged.connect(lambda *_: self.changed.emit())
        layout = QtGui.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.group)
        self.setLayout(layout)

    @property
    def reference(self):
        if not self.slot.picks:
            return None
        obj, sub = self.slot.picks[0]
        return (obj, (sub,) if sub else ())

    def set_reference(self, reference):
        if reference is None:
            self.slot.picks = []
        else:
            obj, subs = reference[0], reference[1]
            sub = ""
            if subs:
                sub = subs[0] if not isinstance(subs, str) else subs
            self.slot.picks = [(obj, sub or "")]
        self.slot._commit()

    def start_selection(self):
        _arm_picker(self)
        self.group.coordinator.install()
        self.group.arm(self.slot.slot_id)
        self.group.consume_current_selection()

    def finish_selection(self):
        self.group.coordinator.remove()
        _disarm_picker(self)

    def clear_all(self):
        self.slot.clear()


class _PartitionTaskPanel(base_femtaskpanel._BaseTaskPanel):
    """Task panel for partitioning geometry in the analysis chain."""

    def __init__(self, obj):
        super().__init__(obj)
        self._selectionWidget = None
        # Restoring the widgets from the object fires their change signals, and
        # a write-back before every widget holds its stored value would clear
        # the ones not restored yet.
        self._loading = True
        self.base_obj = obj.Base
        self._solids_before = len(obj.Base.Shape.Solids) if obj.Base else 0

        self.form = QtGui.QWidget()
        layout = QtGui.QVBoxLayout()

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

        self.target_picker = _SubElementPicker(
            FreeCAD.Qt.translate("FEM", "Targets"),
            self.base_obj,
            ("Solid",),
            max_count=None,
            feature=obj,
        )
        self.target_picker.set_references(_links_to_references(obj.Elements))
        existing = geometry_partition.target_types(obj.Elements)
        kind_index = self.kind_combo.findData(next(iter(existing)) if existing else "Solid")
        if kind_index >= 0:
            self.kind_combo.setCurrentIndex(kind_index)
        self.target_picker.set_target_kind(self.kind_combo.currentData())
        self.kind_combo.currentIndexChanged.connect(self.kind_changed)
        self.target_picker.changed.connect(self.targets_changed)

        self.method_combo = QtGui.QComboBox()
        for method in geometry_partition.PARTITION_METHODS:
            self.method_combo.addItem(method)
        self.method_combo.currentIndexChanged.connect(self.method_changed)

        self.method_hint = QtGui.QLabel()
        self.method_hint.setWordWrap(True)

        self.stack = QtGui.QStackedWidget()

        self.points_3 = _SubElementPicker(
            FreeCAD.Qt.translate("FEM", "Plane points"),
            self.base_obj,
            ("Vertex",),
            max_count=3,
        )
        self.points_3.changed.connect(self.apply_properties)

        self.tool_ref = _ObjectPicker(
            FreeCAD.Qt.translate("FEM", "Plane reference"),
            self.base_obj,
        )
        self.tool_ref.changed.connect(self.apply_properties)

        self.tool_face = _SubElementPicker(
            FreeCAD.Qt.translate("FEM", "Face to extend"),
            self.base_obj,
            ("Face",),
            max_count=1,
        )
        self.tool_face.changed.connect(self.apply_properties)

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
        param_page = QtGui.QWidget()
        param_page.setLayout(param_row)

        self.points_2 = _SubElementPicker(
            FreeCAD.Qt.translate("FEM", "Path vertices"),
            self.base_obj,
            ("Vertex",),
            max_count=2,
        )
        self.points_2.changed.connect(self.apply_properties)

        self.stack.addWidget(QtGui.QWidget())  # 0 plane 3p -> points_3 shown separately
        self.stack.addWidget(self.tool_ref)
        self.stack.addWidget(self.tool_face)
        self.stack.addWidget(param_page)
        self.stack.addWidget(self.points_2)

        self.summary = QtGui.QLabel()

        kind_row = QtGui.QHBoxLayout()
        kind_row.addWidget(QtGui.QLabel(FreeCAD.Qt.translate("FEM", "Target kind")))
        kind_row.addWidget(self.kind_combo)
        layout.addLayout(kind_row)
        layout.addWidget(self.target_picker)
        layout.addWidget(QtGui.QLabel(FreeCAD.Qt.translate("FEM", "Method")))
        layout.addWidget(self.method_combo)
        layout.addWidget(self.method_hint)
        layout.addWidget(self.points_3)
        layout.addWidget(self.stack)
        layout.addWidget(self.summary)
        self.form.setLayout(layout)

        # A stored method can have become invalid for the stored targets, so the
        # panel opens on one that can actually run instead of a greyed-out entry.
        method = geometry_partition.first_available_method(obj.Elements, obj.Method)
        index = self.method_combo.findText(method)
        if index >= 0:
            self.method_combo.setCurrentIndex(index)
        self.points_3.set_references(_links_to_references(obj.Points))
        if obj.Tool:
            tool = obj.Tool
            subs = tool[1] if isinstance(tool[1], (list, tuple)) else (tool[1],)
            if obj.Method == geometry_partition.METHOD_EXTEND_FACE:
                self.tool_face.set_references([(tool[0], subs[0])] if subs and subs[0] else [])
            else:
                self.tool_ref.set_reference((tool[0], subs))

        self.param_spin.valueChanged.connect(self.apply_properties)
        self._loading = False
        # Prefill the Targets slot from a create-command stash. Subordinate
        # pickers (points, tool, plane) are never a prefill destination.
        self.target_picker.group.arm("Targets")
        self.target_picker.group.consume_handoff()
        self._update_method_availability()
        self._update_method_page()
        self._update_summary()
        self._update_marks()
        self._update_tool_preview()

    def _element_links(self):
        return _references_to_links(self.target_picker.references)

    def kind_changed(self):
        self.target_picker.set_target_kind(self.kind_combo.currentData())
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
        self.points_3.setVisible(method == geometry_partition.METHOD_PLANE_3P)
        pages = {
            geometry_partition.METHOD_PLANE_3P: 0,
            geometry_partition.METHOD_PLANE_REF: 1,
            geometry_partition.METHOD_EXTEND_FACE: 2,
            geometry_partition.METHOD_EDGE_PARAM: 3,
            geometry_partition.METHOD_SHORTEST_PATH: 4,
        }
        self.stack.setCurrentIndex(pages.get(method, 0))
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
            self.obj.Points = _references_to_links(self.points_3.references)
            self.obj.Tool = None
        elif method == geometry_partition.METHOD_PLANE_REF:
            self.obj.Points = []
            self.obj.Tool = self.tool_ref.reference
        elif method == geometry_partition.METHOD_EXTEND_FACE:
            self.obj.Points = []
            refs = self.tool_face.references
            if refs:
                self.obj.Tool = (refs[0][0], (refs[0][1],))
            else:
                self.obj.Tool = None
        elif method == geometry_partition.METHOD_EDGE_PARAM:
            self.obj.Points = []
            self.obj.Tool = None
        elif method == geometry_partition.METHOD_SHORTEST_PATH:
            self.obj.Points = _references_to_links(self.points_2.references)
            self.obj.Tool = None

        self.obj.Document.recompute()
        self._update_summary()
        self._update_marks()
        self._update_tool_preview()

    def _marked_elements(self):
        """Element names to mark per role, for the method currently chosen."""
        method = self.method_combo.currentText()
        points = []
        if method == geometry_partition.METHOD_PLANE_3P:
            points = self.points_3.references
        elif method == geometry_partition.METHOD_SHORTEST_PATH:
            points = self.points_2.references
        tool = []
        if method == geometry_partition.METHOD_EXTEND_FACE:
            tool = self.tool_face.references
        return {
            MARK_TARGETS: self.target_picker.references,
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
        for picker in (
            self.target_picker,
            self.points_3,
            self.tool_ref,
            self.tool_face,
            self.points_2,
        ):
            picker.finish_selection()
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
