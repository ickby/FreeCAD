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
import FreeCADGui

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


def _shape_type(subname):
    if not subname:
        return None
    for prefix in ("Solid", "Shell", "Face", "Edge", "Vertex"):
        if subname.startswith(prefix):
            return prefix
    return None


def _current_picks():
    """
    Selected (object, sub-element) pairs, resolved out of their container.

    The geometry group is a GeoFeatureGroup, so a click on a chain step is
    reported against the group with the step and the element map encoded into
    the sub-element path. Letting the selection resolve that is the only
    reliable way to get back the step and a plain element name.
    """
    picks = []
    for sel in FreeCADGui.Selection.getSelectionEx("", 1):
        for sub in sel.SubElementNames or ("",):
            picks.append((sel.Object, sub))
    return picks


def _contains_sub(solid, picked):
    members = {
        "Face": solid.Faces,
        "Edge": solid.Edges,
        "Vertex": solid.Vertexes,
    }.get(picked.ShapeType, ())
    return any(picked.isSame(member) for member in members)


def _owning_solid(obj, sub):
    """
    Name of the solid a picked sub-element belongs to.

    Picking in the 3D view can only ever hit a face, edge or vertex, so a solid
    target has to be derived from what was hit.
    """
    if sub.startswith("Solid"):
        return sub
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return None
    try:
        picked = obj.getSubObject(sub)
    except Exception:
        return None
    if picked is None or picked.isNull():
        return None
    for index, solid in enumerate(shape.Solids, 1):
        if _contains_sub(solid, picked):
            return f"Solid{index}"
    return None


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
        parent=None,
    ):
        super().__init__(title, parent)
        self.base_obj = base_obj
        self.types = set(types)
        self.max_count = max_count
        self.allow_external = allow_external
        self.references = []
        self.promote_to_solid = False
        self._observer = None

        self.list = QtGui.QListWidget()
        self.add_btn = QtGui.QPushButton(FreeCAD.Qt.translate("FEM", "Add"))
        self.clear_btn = QtGui.QPushButton(FreeCAD.Qt.translate("FEM", "Clear"))
        self.add_btn.clicked.connect(self.start_selection)
        self.clear_btn.clicked.connect(self.clear_all)

        row = QtGui.QHBoxLayout()
        row.addWidget(self.add_btn)
        row.addWidget(self.clear_btn)

        layout = QtGui.QVBoxLayout()
        layout.addWidget(self.list)
        layout.addLayout(row)
        self.setLayout(layout)

    def set_references(self, references):
        self.references = list(references)
        self._rebuild_list()

    def set_target_kind(self, kind):
        """Restrict picking to one shape type, dropping picks of the others."""
        self.types = {kind}
        self.promote_to_solid = kind == "Solid"
        kept = [ref for ref in self.references if _shape_type(ref[1]) == kind]
        if len(kept) != len(self.references):
            self.references = kept
            self._rebuild_list()
            self.changed.emit()

    def _rebuild_list(self):
        self.list.clear()
        for obj, sub in self.references:
            label = obj.Label if not sub else f"{obj.Label}.{sub}"
            self.list.addItem(label)

    def start_selection(self):
        self.finish_selection()
        self._observer = _PickerObserver(self.consume_selection)
        # Whatever is already selected counts, so picking first and then
        # clicking Add works the same way round as Add and then picking.
        self.consume_selection()
        type_text = ", ".join(sorted(self.types))
        FreeCAD.Console.PrintMessage(
            FreeCAD.Qt.translate(
                "FEM",
                "Select {type} on the input geometry and click Add, "
                "or pick directly while this panel is open.\n",
            ).format(type=type_text)
        )

    def finish_selection(self):
        if self._observer:
            FreeCADGui.Selection.removeObserver(self._observer)
            self._observer = None

    def clear_all(self):
        self.references = []
        self._rebuild_list()
        self.changed.emit()

    def consume_selection(self):
        for obj, sub in _current_picks():
            self._add_reference(obj, sub)

    def _add_reference(self, obj, sub):
        if obj is None:
            return
        if not self.allow_external and obj != self.base_obj:
            return
        if self.promote_to_solid and not self.allow_external:
            solid = _owning_solid(obj, sub)
            if solid is None:
                return
            sub = solid
        if self.allow_external:
            if not (
                obj.isDerivedFrom("Part::DatumPlane")
                or obj.isDerivedFrom("Sketcher::SketchObject")
                or (obj.isDerivedFrom("Part::Feature") and sub and sub.startswith("Face"))
            ):
                return
        stype = _shape_type(sub)
        if self.types and stype not in self.types and not self.allow_external:
            return
        if not sub and not self.allow_external:
            return
        entry = (obj, sub)
        if entry in self.references:
            return
        if self.max_count is not None and len(self.references) >= self.max_count:
            self.references.pop(0)
        self.references.append(entry)
        self._rebuild_list()
        self.changed.emit()


class _PickerObserver:
    """
    Re-reads the resolved selection whenever it changes.

    The raw callback arguments carry the unresolved container path, so the
    selection itself is asked to resolve them instead.
    """

    def __init__(self, callback):
        self.callback = callback
        FreeCADGui.Selection.addObserver(self)

    def addSelection(self, docName, objName, sub, pos):
        self.callback()


class _ObjectPicker(QtGui.QGroupBox):
    """Pick a single external or internal reference object."""

    changed = QtCore.Signal()

    def __init__(self, title, base_obj, parent=None):
        super().__init__(title, parent)
        self.base_obj = base_obj
        self.reference = None
        self._observer = None

        self.label = QtGui.QLabel(FreeCAD.Qt.translate("FEM", "None"))
        self.add_btn = QtGui.QPushButton(FreeCAD.Qt.translate("FEM", "Add"))
        self.clear_btn = QtGui.QPushButton(FreeCAD.Qt.translate("FEM", "Clear"))
        self.add_btn.clicked.connect(self.start_selection)
        self.clear_btn.clicked.connect(self.clear_all)

        row = QtGui.QHBoxLayout()
        row.addWidget(self.add_btn)
        row.addWidget(self.clear_btn)

        layout = QtGui.QVBoxLayout()
        layout.addWidget(self.label)
        layout.addLayout(row)
        self.setLayout(layout)

    def set_reference(self, reference):
        self.reference = reference
        if reference is None:
            self.label.setText(FreeCAD.Qt.translate("FEM", "None"))
        else:
            obj, subs = reference[0], reference[1]
            sub = subs[0] if subs else ""
            self.label.setText(f"{obj.Label}.{sub}" if sub else obj.Label)

    def start_selection(self):
        self.finish_selection()
        self._observer = _PickerObserver(self.consume_selection)
        self.consume_selection()

    def finish_selection(self):
        if self._observer:
            FreeCADGui.Selection.removeObserver(self._observer)
            self._observer = None

    def clear_all(self):
        self.reference = None
        self.label.setText(FreeCAD.Qt.translate("FEM", "None"))
        self.changed.emit()

    def consume_selection(self):
        for obj, sub in _current_picks():
            self._set_reference(obj, sub)

    def _set_reference(self, obj, sub):
        if obj is None:
            return
        if obj.isDerivedFrom("Part::DatumPlane") or obj.isDerivedFrom("Sketcher::SketchObject"):
            self.reference = (obj, ())
        elif obj.isDerivedFrom("Part::Feature") and sub and sub.startswith("Face"):
            self.reference = (obj, (sub,))
        else:
            return
        self.set_reference(self.reference)
        self.changed.emit()


class _PartitionTaskPanel(base_femtaskpanel._BaseTaskPanel):
    """Task panel for partitioning geometry in the analysis chain."""

    def __init__(self, obj):
        super().__init__(obj)
        self._selectionWidget = None
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
