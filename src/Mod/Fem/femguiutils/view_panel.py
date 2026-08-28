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

__title__ = "FreeCAD FEM visualization control panel"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

## @package view_panel
#  \ingroup FEM
#  \brief Dockable panel controlling AnalysisViewState

import re

import FreeCAD
import FreeCADGui
import FemGui

import femtools.membertools as mt

from PySide import QtCore, QtGui
from PySide.QtCore import QModelIndex, Qt, QAbstractItemModel

# store of current dock
__dock = None

_DIM_MODES = ["Highest", "Volume", "Surface", "Curve", "Point"]
_COLOR_MODES = ["Subelement", "Toplevel", "Material", "CellType"]
_ELEMENT_NAME = re.compile(r"^(Component|CompSolid|Compound|Solid|Shell|Face|Wire|Edge|Vertex)\d+$")


def _ui_path(name):
    return FreeCAD.getHomePath() + "Mod/Fem/Resources/ui/" + name


def _color_tuple(color):
    """Accept (r,g,b[,a]) floats or Base.Color-like objects."""
    if color is None:
        return None
    if isinstance(color, (list, tuple)):
        return tuple(color[:4])
    return (color[0], color[1], color[2], color[3] if len(color) > 3 else 1.0)


def _vp_object(viewprovider):
    """
    Document object for a view provider, or None while the VP is still being
    constructed. Property writes in the VP constructor notify observers before
    Object is linked; accessing it then segfaults in C++ (not a Python
    exception — try/except cannot catch it). Prefer App document observers for
    Shape/Group, and never probe Object via hasattr().
    """
    try:
        # pcObject may be null during VP construction; the Python binding
        # dereferences it without a check.
        if not viewprovider:
            return None
        # Use the low-level pointer check if available; otherwise refuse.
        return viewprovider.Object
    except (AttributeError, ReferenceError, RuntimeError):
        return None


def _app_document_object(arg):
    """
    Return arg if it is an App DocumentObject. Never touches ViewProvider.Object.
    """
    try:
        if arg is not None and arg.isDerivedFrom("App::DocumentObject"):
            return arg
    except Exception:
        pass
    return None


class _GuiDocObserver:
    """
    Gui document observer without slotChangedObject / slotBeforeChangeObject.

    Those Gui slots call ViewProvider.getPropertyName() in C++ before invoking
    Python. During ViewProviderFemMesh construction that merge()s property data
    before BackfaceCulling is registered, causing "Cannot add static property".
    """

    def __init__(self, owner):
        self.owner = owner

    def slotDeletedDocument(self, guidoc):
        self.owner._gui_deleted_document(guidoc)

    def slotDeletedObject(self, viewprovider):
        self.owner._gui_deleted_object(viewprovider)


class _AppDocObserver:
    """App document observer for Shape/Group and object lifetime."""

    def __init__(self, owner):
        self.owner = owner

    def slotCreatedObject(self, obj):
        self.owner._app_created_object(obj)

    def slotDeletedObject(self, obj):
        self.owner._app_deleted_object(obj)

    def slotChangedObject(self, obj, prop):
        self.owner._app_changed_object(obj, prop)


def _child_entity_names(geom_obj, toplevel):
    """
    One level of sub-entities under a toplevel name for the view tree.

    Solids are shown as a single row (no Face children). Faces list Edges,
    Edges list Vertices — using the global FemGeometry Shape numbering.
    """
    shape = geom_obj.Shape
    if shape.isNull():
        return []
    try:
        parent = shape.getElement(toplevel)
    except Exception:
        return []
    if parent.isNull():
        return []

    def _match(children, all_of_type, prefix):
        names = []
        for i, candidate in enumerate(all_of_type, start=1):
            if any(candidate.isSame(child) for child in children):
                names.append(f"{prefix}{i}")
        return names

    st = parent.ShapeType
    # 3D solids: hide face clutter in the tree (colouring stays per-toplevel).
    if st == "Solid":
        return []
    if st == "Face":
        return _match(parent.Edges, shape.Edges, "Edge")
    if st == "Edge":
        return _match(parent.Vertexes, shape.Vertexes, "Vertex")
    return []


class ElementNode:
    """Tree node: geometry hierarchy or classification category/member."""

    def __init__(
        self,
        name=None,
        parent=None,
        *,
        element=None,
        category_key=None,
        color=None,
        dim_badge=None,
        mesh_failed=False,
        is_category=False,
        cell_type=False,
    ):
        self.name = name
        self.children = []
        self._parent = parent
        self.element = element  # geometry entity name for hide, if any
        self.category_key = category_key
        self._color = color
        self.dim_badge = dim_badge
        self.mesh_failed = mesh_failed
        self.is_category = is_category
        self.cell_type = cell_type  # hide via cell-type set
        self.view_state = None

    def parent(self):
        return self._parent

    def child(self, row):
        if row < 0 or row >= len(self.children):
            return None
        return self.children[row]

    def child_count(self):
        return len(self.children)

    def child_number(self):
        if self._parent:
            return self._parent.children.index(self)
        return 0

    def visible(self):
        if not self.view_state:
            return True
        if self.cell_type and self.category_key:
            return not self.view_state.isCellTypeHidden(self.category_key)
        if self.element:
            return not self.view_state.isElementHidden(self.element)
        # Category / component / root: visible if any child is visible
        if self.children:
            return any(c.visible() for c in self.children)
        return True

    def set_visible(self, value):
        if not self.view_state:
            return
        hidden = not value
        if self.cell_type and self.category_key:
            self.view_state.setCellTypeHidden(self.category_key, hidden)
            return
        if self.element:
            self.view_state.setElementHidden(self.element, hidden)
            return
        # Propagate to descendants that own an element / cell-type key
        for child in self.children:
            child.set_visible(value)

    def color(self):
        return self._color

    def set_color(self, color, geom_obj=None):
        """Read-modify-assign Colors on the geometry VP (toplevel swatch edit)."""
        self._color = color
        if not geom_obj or not self.element:
            return
        cmp = geom_obj.getComponentCount()
        toplevel = []
        for i in range(cmp):
            toplevel += geom_obj.getToplevelElements(i)
        if self.element not in toplevel:
            return
        idx = toplevel.index(self.element)
        colors = list(geom_obj.ViewObject.Colors)
        while len(colors) <= idx:
            colors.append((0.7, 0.7, 0.7, 1.0))
        colors[idx] = color
        geom_obj.ViewObject.Colors = colors

    def display_name(self):
        label = self.name or ""
        extras = []
        if self.dim_badge is not None:
            extras.append(f"{self.dim_badge}D")
        if self.mesh_failed:
            extras.append("mesh failed")
        if extras:
            return f"{label} [{', '.join(extras)}]"
        return label

    def __repr__(self):
        return f"<ElementNode {self.name!r} children={len(self.children)}>"


class GeometryModel(QAbstractItemModel):

    def __init__(self):
        super().__init__()
        self.root = None
        self.geom_obj = None
        self.view_state = None

    def set_context(self, geom_obj, view_state):
        self.geom_obj = geom_obj
        self.view_state = view_state
        self.update_model()

    def clear(self):
        self.geom_obj = None
        self.view_state = None
        self.update_model()

    def _attach_state(self, node):
        node.view_state = self.view_state
        for child in node.children:
            self._attach_state(child)

    def update_model(self):
        if not self.geom_obj or not self.view_state:
            self.root = None
            return

        color_mode = self.view_state.getColorMode()
        under = set(self.view_state.getUnderAchievedElements() or [])

        if color_mode in ("Material", "CellType"):
            self.root = self._build_category_tree(color_mode, under)
        else:
            self.root = self._build_geometry_tree(under)

        if self.root:
            self._attach_state(self.root)

    def _build_geometry_tree(self, under):
        root = ElementNode(self.geom_obj.Label)
        categories = {c["key"]: c for c in (self.view_state.getCategories() or [])}
        for i in range(self.geom_obj.getComponentCount()):
            geometry_node = ElementNode(f"Component{i + 1}", root)
            root.children.append(geometry_node)
            for sub in self.geom_obj.getToplevelElements(i):
                dim = None
                try:
                    dim = self.geom_obj.getAnalysisDimension(sub)
                except Exception:
                    pass
                cat = categories.get(sub)
                color = _color_tuple(cat["color"]) if cat else None
                if color is None:
                    color = self._toplevel_color(sub)
                node = ElementNode(
                    sub,
                    geometry_node,
                    element=sub,
                    color=color,
                    dim_badge=dim if dim is not None and dim >= 0 else None,
                    mesh_failed=sub in under,
                )
                geometry_node.children.append(node)
                for child_name in _child_entity_names(self.geom_obj, sub):
                    child_cat = categories.get(child_name)
                    child_color = _color_tuple(child_cat["color"]) if child_cat else None
                    child = ElementNode(
                        child_name,
                        node,
                        element=child_name,
                        color=child_color,
                        mesh_failed=child_name in under,
                    )
                    node.children.append(child)
        return root

    def _toplevel_color(self, name):
        if not self.geom_obj:
            return None
        try:
            cmp = self.geom_obj.getComponentCount()
            toplevel = []
            for i in range(cmp):
                toplevel += self.geom_obj.getToplevelElements(i)
            if name not in toplevel:
                return None
            idx = toplevel.index(name)
            colors = self.geom_obj.ViewObject.Colors
            if idx < len(colors):
                return _color_tuple(colors[idx])
        except Exception:
            return None
        return None

    def _build_category_tree(self, color_mode, under):
        root = ElementNode(self.geom_obj.Label)
        cats = self.view_state.getCategories() or []
        cell_type = color_mode == "CellType"

        # Collect toplevel members for material grouping
        all_elements = []
        for i in range(self.geom_obj.getComponentCount()):
            all_elements.extend(self.geom_obj.getToplevelElements(i))

        for cat_idx, cat in enumerate(cats):
            key = cat["key"]
            label = cat.get("label") or key
            color = _color_tuple(cat.get("color"))
            cat_node = ElementNode(
                label,
                root,
                category_key=key,
                color=color,
                is_category=True,
                cell_type=cell_type,
            )
            root.children.append(cat_node)

            if cell_type:
                # Category row itself is the hide target (cell-type set)
                cat_node.name = label
                continue

            for e in all_elements:
                if self.view_state.categoryOfElement(e) != cat_idx:
                    continue
                dim = None
                try:
                    dim = self.geom_obj.getAnalysisDimension(e)
                except Exception:
                    pass
                member = ElementNode(
                    e,
                    cat_node,
                    element=e,
                    category_key=key,
                    color=color,
                    dim_badge=dim if dim is not None and dim >= 0 else None,
                    mesh_failed=e in under,
                )
                cat_node.children.append(member)

            count = len(cat_node.children)
            cat_node.name = f"{label} ({count})"

        return root

    def columnCount(self, parent):
        return 3

    def data(self, index, role):
        if not index.isValid():
            return None

        node = self.get_item(index)
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole and column == 0:
            return node.display_name()

        # Stable key for selection sync (DisplayRole includes badges like "[3D]")
        if role == Qt.ItemDataRole.UserRole and column == 0:
            return node.element or node.name

        if role == Qt.DecorationRole and column == 1:
            color = node.color()
            if color:
                pixmap = QtGui.QPixmap(64, 64)
                pixmap.fill(
                    QtGui.QColor(
                        int(255 * color[0]),
                        int(255 * color[1]),
                        int(255 * color[2]),
                    )
                )
                return QtGui.QIcon(pixmap)
            return None

        if role == Qt.ItemDataRole.CheckStateRole and column == 2:
            return Qt.Checked if node.visible() else Qt.Unchecked

        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        if index.column() == 2:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def get_item(self, index=QModelIndex()):
        if index.isValid():
            item = index.internalPointer()
            if item:
                return item
        return self.root

    def index(self, row, column, parent=QModelIndex()):
        if parent.isValid() and parent.column() != 0:
            return QModelIndex()

        parent_item = self.get_item(parent)
        if not parent_item:
            return QModelIndex()

        child_item = parent_item.child(row)
        if child_item:
            return self.createIndex(row, column, child_item)
        return QModelIndex()

    def parent(self, index=QModelIndex()):
        if not index.isValid():
            return QModelIndex()

        child_item = self.get_item(index)
        parent_item = child_item.parent() if child_item else None

        if parent_item is None or parent_item is self.root:
            return QModelIndex()

        return self.createIndex(parent_item.child_number(), 0, parent_item)

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid() and parent.column() > 0:
            return 0
        parent_item = self.get_item(parent)
        if not parent_item:
            return 0
        return parent_item.child_count()

    def setData(self, index, value, role):
        if role == Qt.CheckStateRole and index.column() == 2:
            node = index.internalPointer()
            checked = value == Qt.Checked or value is True or value == 2
            # Avoid the view-state changed callback rebuilding the tree (which
            # collapses expansion). Visibility is already reflected by CheckState.
            explorer = getattr(self, "_explorer", None)
            if explorer is not None:
                explorer._suspend_vs_rebuild = True
            try:
                node.set_visible(checked)
            finally:
                if explorer is not None:
                    explorer._suspend_vs_rebuild = False
            self._emit_check_column(index)
            return True
        return False

    def _emit_check_column(self, index):
        """Refresh checkbox column for this node, ancestors, and descendants."""
        if not index.isValid():
            return
        # Descendants (parent toggle propagates hide to children)
        stack = [index]
        while stack:
            cur = stack.pop()
            check_idx = cur.sibling(cur.row(), 2)
            if check_idx.isValid():
                self.dataChanged.emit(check_idx, check_idx, [Qt.CheckStateRole])
            item = cur.internalPointer()
            if not item:
                continue
            for r in range(item.child_count()):
                stack.append(self.index(r, 0, cur))
        # Ancestors (parent partial/all visibility)
        parent = index.parent()
        while parent.isValid():
            check_idx = parent.sibling(parent.row(), 2)
            if check_idx.isValid():
                self.dataChanged.emit(check_idx, check_idx, [Qt.CheckStateRole])
            parent = parent.parent()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DecorationRole:
            if section == 2:
                return FreeCADGui.getIcon("dagViewVisible.svg")
            return ""
        return None


class GeometryExplorer(QtGui.QTreeView):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_analysis = None
        self.geom_obj = None
        self.view_state = None
        self._vs_callback = None
        self._suspend_vs_rebuild = False

        size_policy = QtGui.QSizePolicy(
            QtGui.QSizePolicy.Policy.Expanding, QtGui.QSizePolicy.Policy.Expanding
        )
        self.setSizePolicy(size_policy)

        self.selection_lock = False
        self._sync_pending = False
        self._suppress_scroll = False
        self.setSelectionMode(QtGui.QTreeView.ExtendedSelection)

        self._model = GeometryModel()
        self._model._explorer = self
        self.setModel(self._model)

        self.active_analysis = FemGui.getActiveAnalysis()
        if self.active_analysis:
            self.setup_analysis()

        FemGui.addActiveAnalysisObserver(self)
        self._gui_observer = _GuiDocObserver(self)
        self._app_observer = _AppDocObserver(self)
        FreeCADGui.addDocumentObserver(self._gui_observer)
        FreeCAD.addDocumentObserver(self._app_observer)
        # NoResolve (0): selection of geometry under Analysis is remapped to a
        # dotted parent path; OldStyle resolve may drop those events entirely.
        FreeCADGui.Selection.addObserver(self, 0)

    def shutdown(self):
        self._disconnect_view_state()
        FemGui.removeActiveAnalysisObserver(self)
        FreeCADGui.removeDocumentObserver(self._gui_observer)
        FreeCAD.removeDocumentObserver(self._app_observer)
        FreeCADGui.Selection.removeObserver(self)

    def _disconnect_view_state(self):
        if self.view_state and self._vs_callback:
            try:
                self.view_state.disconnectChanged(self._vs_callback)
            except Exception:
                pass
        self._vs_callback = None

    def _connect_view_state(self):
        self._disconnect_view_state()
        if not self.view_state:
            return

        def _on_changed():
            if self._suspend_vs_rebuild:
                return
            expanded = self._capture_expanded_paths()
            self._model.beginResetModel()
            self._model.update_model()
            self._model.endResetModel()
            self._restore_expanded_paths(expanded)
            self._request_tree_sync()

        self._vs_callback = _on_changed
        self.view_state.connectChanged(self._vs_callback)

    def _capture_expanded_paths(self):
        """Stable identity paths (node names) for currently expanded rows."""
        paths = set()

        def walk(index, path):
            if not index.isValid():
                return
            node = index.internalPointer()
            name = node.name if node else ""
            cur = path + (name,)
            if self.isExpanded(index):
                paths.add(cur)
            for r in range(self._model.rowCount(index)):
                walk(self._model.index(r, 0, index), cur)

        root = QModelIndex()
        for r in range(self._model.rowCount(root)):
            walk(self._model.index(r, 0, root), ())
        return paths

    def _restore_expanded_paths(self, paths):
        if not paths:
            self.expandAll()
            return

        def walk(index, path):
            if not index.isValid():
                return
            node = index.internalPointer()
            name = node.name if node else ""
            cur = path + (name,)
            if cur in paths:
                self.setExpanded(index, True)
            for r in range(self._model.rowCount(index)):
                walk(self._model.index(r, 0, index), cur)

        root = QModelIndex()
        for r in range(self._model.rowCount(root)):
            walk(self._model.index(r, 0, root), ())

    def remove_analysis(self):
        self.active_analysis = None
        self.setup_analysis()

    def setup_analysis(self):
        self._model.beginResetModel()
        self.view_state = None
        self.geom_obj = None

        if self.active_analysis:
            self.view_state = FemGui.getAnalysisViewState(self.active_analysis)
            geom_list = mt.get_member(self.active_analysis, "Fem::FemGeometry")
            self.geom_obj = geom_list[0] if geom_list else None
            self._model.set_context(self.geom_obj, self.view_state)
        else:
            self._model.clear()

        self._connect_view_state()
        self._model.endResetModel()
        self.expandAll()
        # A model reset drops the highlight; restore it from Gui.Selection.
        self._request_tree_sync()

    def slotActiveFemAnalysisUpdated(self, analysis):
        if analysis != self.active_analysis:
            self.active_analysis = analysis
            self.setup_analysis()

    def _gui_deleted_document(self, guidoc):
        if (
            self.active_analysis
            and self.active_analysis.ViewObject
            and self.active_analysis.ViewObject.Document == guidoc
        ):
            self.remove_analysis()

    def _gui_deleted_object(self, viewprovider):
        if self.active_analysis and viewprovider == self.active_analysis.ViewObject:
            self.remove_analysis()

    def _app_deleted_object(self, obj):
        obj = _app_document_object(obj)
        if self.active_analysis and obj == self.active_analysis:
            self.remove_analysis()

    def _app_created_object(self, obj):
        obj = _app_document_object(obj)
        if self.active_analysis and obj and obj.isDerivedFrom("Fem::FemGeometry"):
            self.setup_analysis()

    def _app_changed_object(self, obj, prop=None):
        if not self.active_analysis or prop is None:
            return
        if prop not in ("Shape", "Group"):
            return
        obj = _app_document_object(obj)
        if not obj:
            return
        try:
            if obj == self.active_analysis and prop == "Group":
                self.setup_analysis()
                return
            if obj.isDerivedFrom("Fem::FemGeometry") and prop in ("Shape", "Group"):
                self.setup_analysis()
        except (AttributeError, ReferenceError, RuntimeError):
            return

    def slotInEdit(self, viewprovider):
        pass

    def slotResetEdit(self, viewprovider):
        pass

    def _geometry_chain(self):
        """
        The analysis geometry object plus its geometry children. They share one
        shape and element numbering, and selections may be recorded on any of
        them (the group claims the children, so 3D picks report the group).
        """
        if not self.geom_obj:
            return []
        chain = [self.geom_obj]
        try:
            chain.extend(
                child for child in self.geom_obj.Group if child.isDerivedFrom("Fem::FemGeometry")
            )
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        return chain

    def _selection_target(self):
        """
        Object to select on: the geometry group, whose view provider draws the
        shape the tree describes. Picking in the 3D view reports the same
        object, so both directions produce identical selection entries.
        """
        return self.geom_obj

    def _element_from_selection(self, doc, obj, sub):
        """
        Resolve a Selection entry to a shape element name of the geometry, or
        None. Subnames address an object path followed by the element, and the
        element may carry an element-map prefix:
            "Solid1"  "GeometryImport.Solid1"  ";Face1;:H…,F.Face1"
        """
        if not self.geom_obj or not doc or not obj:
            return None
        if doc != self.geom_obj.Document.Name:
            return None
        if obj not in {o.Name for o in self._geometry_chain()}:
            return None
        element = (sub or "").rsplit(".", 1)[-1]
        return element if _ELEMENT_NAME.match(element) else None

    def _rows_for_elements(self, wanted):
        """
        Rows to highlight for a set of element names. A row without an element of
        its own (Component, category) has no counterpart in the selection, so it
        keeps its highlight while all its children are selected — enough to
        survive the resync after the user clicked it, without lighting up as a
        side effect of a child being selected elsewhere.
        """
        model = self.selectionModel()
        rows = []

        def walk(parent):
            covered = []
            for r in range(self._model.rowCount(parent)):
                idx = self._model.index(r, 0, parent)
                node = self._model.get_item(idx)
                children_covered = walk(idx)
                element = node.element if node else None
                if element:
                    hit = element in wanted
                else:
                    hit = children_covered and model.isSelected(idx)
                if hit:
                    rows.append(idx)
                covered.append(hit)
            return bool(covered) and all(covered)

        walk(QModelIndex())
        return rows

    def _request_tree_sync(self):
        """
        Reconcile the tree with Gui.Selection now, and once more when the current
        event is done: a replaced selection arrives as a burst of remove/add
        notifications, and the selection list may still be mid-update while one
        of them is delivered.
        """
        self._sync_tree_selection()
        if self._sync_pending:
            return
        self._sync_pending = True
        QtCore.QTimer.singleShot(0, self._sync_tree_selection)

    def _sync_tree_selection(self):
        """Make the tree highlight match the current FreeCAD selection."""
        # While the tree propagates its own change the selection is still being
        # built up; the deferred pass reconciles the final state.
        if not self.geom_obj or self.selection_lock:
            return
        self._sync_pending = False

        doc = self.geom_obj.Document.Name
        wanted = set()
        for sel in FreeCADGui.Selection.getSelectionEx(doc, 0):
            obj_name = sel.Object.Name
            for sub in sel.SubElementNames:
                el = self._element_from_selection(doc, obj_name, sub)
                if el:
                    wanted.add(el)

        scroll = not self._suppress_scroll
        self._suppress_scroll = False

        rows = self._rows_for_elements(wanted)
        selection = QtCore.QItemSelection()
        for idx in rows:
            selection.select(idx, idx)
            parent = idx.parent()
            while parent.isValid():
                self.setExpanded(parent, True)
                parent = parent.parent()

        self.selection_lock = True
        self.selectionModel().select(
            selection,
            QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows,
        )
        self.selection_lock = False

        if rows and scroll:
            self.scrollTo(rows[0])
        self.viewport().update()

    def addSelection(self, doc, obj, sub, point):
        self._request_tree_sync()

    def removeSelection(self, doc, obj, sub):
        self._request_tree_sync()

    def setSelection(self, doc, flags=None):
        # QAbstractItemView.setSelection(rect, flags) vs SelectionObserver, which
        # passes the document name only.
        if flags is not None:
            return super().setSelection(doc, flags)
        self._request_tree_sync()

    def clearSelection(self, doc=None):
        # QAbstractItemView.clearSelection() takes no args; SelectionObserver
        # passes the document name, which is empty when every document is
        # cleared — so never gate the resync on it.
        if doc is None:
            return super().clearSelection()
        self._request_tree_sync()

    def selectionChanged(self, selected, deselected):
        super().selectionChanged(selected, deselected)

        target = self._selection_target()
        if not target or self.selection_lock:
            return

        def _names(item):
            if not item:
                return []
            if item.element:
                return [item.element]
            names = []

            def walk(node):
                if node.element:
                    names.append(node.element)
                for child in node.children:
                    walk(child)

            walk(item)
            return names

        self.selection_lock = True
        for idx in selected.indexes():
            if idx.column() == 0:
                for name in _names(self._model.get_item(idx)):
                    FreeCADGui.Selection.addSelection(target, name)
        for idx in deselected.indexes():
            if idx.column() == 0:
                for name in _names(self._model.get_item(idx)):
                    FreeCADGui.Selection.removeSelection(target, name)
        self.selection_lock = False
        # The rows are where the user put them; do not scroll on the resync that
        # reconciles this change.
        self._suppress_scroll = True


class _clipEditWidget(QtGui.QWidget):
    """
    Popup with the exact values of one clip plane.

    Origin and normal belong to the plane, the step size does not: it is a
    preference that the handle shares with every other clip plane.

    The spin boxes have keyboard tracking off, so a typed value only arrives
    once the field is left and the clipping is not recomputed per keystroke.
    """

    def __init__(self, handle, parent=None):
        super().__init__(parent)
        self.handle = handle
        self._updating = False

        self.widget = FreeCADGui.PySideUic.loadUi(_ui_path("ViewClipEditWidget.ui"))
        self.widget.OffsetStep.setToolTip(
            QtCore.QCoreApplication.translate(
                "FEM_ViewPanel",
                "Step of the drag arrow, shared by all clipping planes. "
                "Zero follows the model size.",
            )
        )
        self.widget.AngleStep.setToolTip(
            QtCore.QCoreApplication.translate(
                "FEM_ViewPanel",
                "Step of the two angle handles, shared by all clipping planes",
            )
        )
        origin_tip = QtCore.QCoreApplication.translate(
            "FEM_ViewPanel", "Point the plane passes through, also the center it rotates about"
        )
        normal_tip = QtCore.QCoreApplication.translate(
            "FEM_ViewPanel", "Plane normal, pointing at the part that is kept"
        )
        self.widget.OriginLabel.setToolTip(origin_tip)
        self.widget.NormalLabel.setToolTip(normal_tip)
        for box in (self.widget.OriginX, self.widget.OriginY, self.widget.OriginZ):
            box.setToolTip(origin_tip)
        for box in (self.widget.NormalX, self.widget.NormalY, self.widget.NormalZ):
            box.setToolTip(normal_tip)

        self.layout = QtGui.QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.widget)
        self.setLayout(self.layout)

        self.widget.OffsetStep.valueChanged.connect(self.offset_step_changed)
        self.widget.AngleStep.valueChanged.connect(self.angle_step_changed)
        for box in self._plane_boxes():
            box.valueChanged.connect(self.plane_changed)

    def _plane_boxes(self):
        widget = self.widget
        return (
            widget.OriginX,
            widget.OriginY,
            widget.OriginZ,
            widget.NormalX,
            widget.NormalY,
            widget.NormalZ,
        )

    def shutdown(self):
        self.handle = None

    def showEvent(self, event):
        # The plane may well have been dragged since the popup was last up
        self.refresh()
        super().showEvent(event)

    def refresh(self):
        if not self.handle:
            return
        origin = self.handle.getOrigin()
        normal = self.handle.getNormal()
        self._updating = True
        try:
            # rawValue is the plain number in internal units, which spares the
            # popup any quantity juggling while the display stays unit aware.
            self.widget.OffsetStep.setProperty("rawValue", self.handle.getOffsetStep())
            self.widget.AngleStep.setProperty("rawValue", self.handle.getAngleStep())
            self.widget.OriginX.setProperty("rawValue", origin.x)
            self.widget.OriginY.setProperty("rawValue", origin.y)
            self.widget.OriginZ.setProperty("rawValue", origin.z)
            self.widget.NormalX.setValue(normal.x)
            self.widget.NormalY.setValue(normal.y)
            self.widget.NormalZ.setValue(normal.z)
        finally:
            self._updating = False

    def offset_step_changed(self, value=None):
        if self._updating or not self.handle:
            return
        self.handle.setOffsetStep(self.widget.OffsetStep.property("rawValue"))

    def angle_step_changed(self, value=None):
        if self._updating or not self.handle:
            return
        self.handle.setAngleStep(self.widget.AngleStep.property("rawValue"))

    def plane_changed(self, value=None):
        if self._updating or not self.handle:
            return
        origin = FreeCAD.Vector(
            self.widget.OriginX.property("rawValue"),
            self.widget.OriginY.property("rawValue"),
            self.widget.OriginZ.property("rawValue"),
        )
        normal = FreeCAD.Vector(
            self.widget.NormalX.value(),
            self.widget.NormalY.value(),
            self.widget.NormalZ.value(),
        )
        # Zeroing the normal is a step on the way to another direction, not a
        # plane; keep the old one until a usable direction is typed.
        if normal.Length < 1e-9:
            return
        self.handle.setPlane(origin, normal)


class _clipWidget(QtGui.QWidget):
    """
    One row of the clipping list, driving a FemGui clip plane handle.

    The 3D side -- dragger, plane indicator and view state updates -- lives in
    the handle, so this widget only mirrors button states. Dropping the handle
    removes the plane from the view, which is why shutdown() must run before
    the row goes away.
    """

    def __init__(self, handle, parent=None):
        super().__init__(parent)
        self.handle = handle

        self.widget = FreeCADGui.PySideUic.loadUi(_ui_path("ViewClipWidget.ui"))
        self.widget.ClipButton.setText(handle.getName())
        self.widget.ClipButton.setChecked(handle.isActive())
        self.widget.WidgetButton.setChecked(handle.isWidgetVisible())
        self.widget.DeleteButton.setIcon(FreeCADGui.getIcon("delete.svg"))
        self.widget.EditButton.setIcon(FreeCADGui.getIcon("preferences-general.svg"))
        self.widget.ClipButton.setToolTip(
            QtCore.QCoreApplication.translate("FEM_ViewPanel", "Apply this clipping plane")
        )
        self.widget.WidgetButton.setToolTip(
            QtCore.QCoreApplication.translate(
                "FEM_ViewPanel", "Show the plane and its drag handles in the 3D view"
            )
        )
        self.widget.EditButton.setToolTip(
            QtCore.QCoreApplication.translate(
                "FEM_ViewPanel", "Set drag steps, origin and normal by value"
            )
        )

        # A menu of our own instead of the button popup mode, which would turn
        # the button into a drop down with an arrow.
        self.editor = _clipEditWidget(handle)
        self.edit_menu = QtGui.QMenu(self.widget.EditButton)
        edit_action = QtGui.QWidgetAction(self.edit_menu)
        edit_action.setDefaultWidget(self.editor)
        self.edit_menu.addAction(edit_action)

        self.layout = QtGui.QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.widget)
        self.setLayout(self.layout)

        self.widget.ClipButton.clicked.connect(self.clip_changed)
        self.widget.WidgetButton.clicked.connect(self.widget_changed)
        self.widget.EditButton.clicked.connect(self.edit_clicked)
        self.widget.DeleteButton.clicked.connect(self.delete_clicked)

    @property
    def name(self):
        return self.handle.getName() if self.handle else ""

    def shutdown(self):
        """Drop the clip plane and its 3D widget, then retire the row."""
        self.editor.shutdown()
        if self.handle:
            self.handle.remove()
            self.handle = None
        self.setParent(None)
        self.deleteLater()

    def refresh(self):
        """Re-fit the plane indicator and resync the buttons with the handle."""
        if not self.handle:
            return
        self.handle.refresh()
        self.widget.ClipButton.setChecked(self.handle.isActive())
        if self.editor.isVisible():
            self.editor.refresh()

    def edit_clicked(self, value=None):
        button = self.widget.EditButton
        self.edit_menu.popup(button.mapToGlobal(QtCore.QPoint(0, button.height())))

    def delete_clicked(self, value):
        self.shutdown()

    def clip_changed(self, value):
        if self.handle:
            self.handle.setActive(bool(value))

    def widget_changed(self, value):
        if self.handle:
            self.handle.setWidgetVisible(bool(value))


class ViewSettings(QtGui.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget = FreeCADGui.PySideUic.loadUi(_ui_path("ViewSettingsWidget.ui"))

        size_policy = QtGui.QSizePolicy(
            QtGui.QSizePolicy.Policy.Minimum, QtGui.QSizePolicy.Policy.Minimum
        )
        self.setSizePolicy(size_policy)

        self.widget.Overlay.setIcon(FreeCADGui.getIcon("DrawStyleNoShading.svg"))
        self.widget.Overlay.setToolTip(
            QtCore.QCoreApplication.translate(
                "FEM_ViewPanel",
                "Show the hidden and clipped away parts as a transparent overlay",
            )
        )
        self.widget.ClipButton.setIcon(FreeCADGui.getIcon("list-add.svg"))

        # Colour mode combo (not in the legacy UI file)
        self.color_mode = QtGui.QComboBox()
        self.color_mode.addItems(_COLOR_MODES)
        self.widget.MeshGroup.layout().insertWidget(0, self.color_mode)

        # Dimension modes match AnalysisViewState::DimensionMode
        self.widget.Dimension.clear()
        self.widget.Dimension.addItems(_DIM_MODES)

        self.layout = QtGui.QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.widget)
        self.setLayout(self.layout)

        self.active_analysis = FemGui.getActiveAnalysis()
        self.view_state = None
        self.geom_obj = None
        self.mesh_obj = None
        self._vs_callback = None
        self._updating = False
        self._clip_key = None
        self.setup_analysis()

        self.widget.GeometryButton.clicked.connect(self.geometry_button_checked)
        self.widget.MeshButton.clicked.connect(self.mesh_button_checked)
        self.widget.Dimension.currentIndexChanged.connect(self.dimension_changed)
        self.widget.ViewMode.currentIndexChanged.connect(self.viewmode_changed)
        self.widget.Overlay.clicked.connect(self.overlay_changed)
        self.widget.ClipButton.clicked.connect(self.add_clipping_plane)
        self.color_mode.currentIndexChanged.connect(self.colormode_changed)

        FemGui.addActiveAnalysisObserver(self)
        self._gui_observer = _GuiDocObserver(self)
        self._app_observer = _AppDocObserver(self)
        FreeCADGui.addDocumentObserver(self._gui_observer)
        FreeCAD.addDocumentObserver(self._app_observer)

    def shutdown(self):
        self.clear_clipping_planes()
        self._clip_key = None
        self._disconnect_view_state()
        FemGui.removeActiveAnalysisObserver(self)
        FreeCADGui.removeDocumentObserver(self._gui_observer)
        FreeCAD.removeDocumentObserver(self._app_observer)

    def _disconnect_view_state(self):
        if self.view_state and self._vs_callback:
            try:
                self.view_state.disconnectChanged(self._vs_callback)
            except Exception:
                pass
        self._vs_callback = None

    def _connect_view_state(self):
        self._disconnect_view_state()
        if not self.view_state:
            return

        def _on_changed():
            self.setup_widgets()

        self._vs_callback = _on_changed
        self.view_state.connectChanged(self._vs_callback)

    def _analysis_key(self):
        """Identity of the current analysis that survives a dead wrapper."""
        if not self.active_analysis:
            return None
        try:
            return (self.active_analysis.Document.Name, self.active_analysis.Name)
        except (AttributeError, ReferenceError, RuntimeError):
            return None

    def setup_analysis(self):
        self.geom_obj = None
        self.mesh_obj = None
        self.view_state = None

        if self.active_analysis:
            self.view_state = FemGui.getAnalysisViewState(self.active_analysis)
            geom_list = mt.get_member(self.active_analysis, "Fem::FemGeometry")
            self.geom_obj = geom_list[0] if geom_list else None
            mesh_list = mt.get_member(self.active_analysis, "Fem::FemMeshShapeGroup")
            self.mesh_obj = mesh_list[0] if mesh_list else None
            # Importing geometry should put the view into the Geometry stage so
            # the Geometry button and 3D colouring stay in sync with the tree.
            if self.geom_obj and self.view_state and self.view_state.getActiveStage() != "Geometry":
                if not self.mesh_obj:
                    self.view_state.setActiveStage("Geometry")

        self._connect_view_state()

        # setup_analysis() also runs on every geometry or mesh change, where the
        # clip planes have to stay put and only re-fit their indicator.
        key = self._analysis_key()
        if key != self._clip_key:
            self._clip_key = key
            self.setup_clipping_planes()
        else:
            for widget in self.clip_widgets():
                widget.refresh()

        self.setup_widgets()

    def setup_widgets(self):
        self._updating = True
        try:
            has_vs = self.view_state is not None
            self.widget.GeometryButton.setEnabled(has_vs and self.geom_obj is not None)
            self.widget.MeshButton.setEnabled(has_vs and self.mesh_obj is not None)
            self.widget.ClipButton.setEnabled(has_vs)
            self.color_mode.setEnabled(has_vs)
            self.widget.Dimension.setEnabled(has_vs)
            self.widget.ViewMode.setEnabled(has_vs)
            self.widget.Overlay.setEnabled(has_vs)

            if not has_vs:
                return

            self.widget.Overlay.setChecked(self.view_state.getOverlay())

            stage = self.view_state.getActiveStage()
            self.widget.GeometryButton.setChecked(stage == "Geometry")
            self.widget.MeshButton.setChecked(stage == "Mesh")

            dim = self.view_state.getDimensionMode()
            idx = self.widget.Dimension.findText(dim)
            if idx >= 0:
                self.widget.Dimension.setCurrentIndex(idx)

            cm = self.view_state.getColorMode()
            idx = self.color_mode.findText(cm)
            if idx >= 0:
                self.color_mode.setCurrentIndex(idx)

            if self.view_state.getWireframe():
                self.widget.ViewMode.setCurrentIndex(0)
            else:
                self.widget.ViewMode.setCurrentIndex(1)
        finally:
            self._updating = False

    def slotActiveFemAnalysisUpdated(self, analysis):
        if analysis != self.active_analysis:
            self.active_analysis = analysis
            self.setup_analysis()

    def _app_created_object(self, obj):
        if not self.active_analysis:
            return
        obj = _app_document_object(obj)
        if not obj:
            return
        if obj.isDerivedFrom("Fem::FemGeometry") or obj.isDerivedFrom("Fem::FemMeshShapeGroup"):
            self.setup_analysis()

    def _app_changed_object(self, obj, property=None):
        if not self.active_analysis or property is None:
            return
        if property not in ("Shape", "Group"):
            return
        obj = _app_document_object(obj)
        if not obj:
            return
        try:
            if obj == self.active_analysis and property == "Group":
                self.setup_analysis()
                return
            if obj.isDerivedFrom("Fem::FemGeometry") and property in ("Shape", "Group"):
                self.setup_analysis()
                return
            if obj.isDerivedFrom("Fem::FemMeshShapeGroup") and property in ("Group", "Shape"):
                self.setup_analysis()
        except (AttributeError, ReferenceError, RuntimeError):
            return

    def _app_deleted_object(self, obj):
        obj = _app_document_object(obj)
        if not obj or not self.active_analysis:
            return
        if obj == self.active_analysis:
            self.active_analysis = None
            self.setup_analysis()
        elif obj.isDerivedFrom("Fem::FemGeometry") or obj.isDerivedFrom("Fem::FemMeshShapeGroup"):
            self.setup_analysis()

    def _gui_deleted_object(self, viewprovider):
        if self.active_analysis and viewprovider == getattr(
            self.active_analysis, "ViewObject", None
        ):
            self.active_analysis = None
            self.setup_analysis()

    def _gui_deleted_document(self, doc):
        if self.active_analysis and doc.Document == self.active_analysis.Document:
            self.active_analysis = None
            self.setup_analysis()

    def slotInEdit(self, viewprovider):
        pass

    def slotResetEdit(self, viewprovider):
        pass

    def clip_widgets(self):
        layout = self.widget.ClippingGroup.layout()
        widgets = []
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget() if item else None
            if isinstance(widget, _clipWidget):
                widgets.append(widget)
        return widgets

    def clear_clipping_planes(self):
        """
        Retire all clip rows.

        Rows outlive nothing: their handles reference the analysis they were
        made for, so switching analysis or closing the document has to drop
        them here instead of leaving stale rows behind.
        """
        layout = self.widget.ClippingGroup.layout()
        for widget in self.clip_widgets():
            layout.removeWidget(widget)
            widget.shutdown()

    def setup_clipping_planes(self):
        """Rebuild the clip rows for the current analysis, planes included."""
        self.clear_clipping_planes()
        if not self.active_analysis or not self.view_state:
            return
        # Planes restored from a saved document are already in the view state
        # and only need their handle back.
        for name in sorted(self.view_state.getClipPlanes().keys()):
            self._add_clip_widget(name)

    def _add_clip_widget(self, name=None):
        try:
            handle = (
                FemGui.createClipPlane(self.active_analysis, name)
                if name
                else FemGui.createClipPlane(self.active_analysis)
            )
        except Exception as exc:
            FreeCAD.Console.PrintError(f"FEM view panel: cannot create clipping plane: {exc}\n")
            return None
        if handle is None:
            return None

        layout = self.widget.ClippingGroup.layout()
        widget = _clipWidget(handle)
        layout.insertWidget(layout.count() - 1, widget)
        return widget

    def add_clipping_plane(self, value):
        if self.active_analysis and self.view_state:
            self._add_clip_widget()

    def viewmode_changed(self, value):
        if self._updating or not self.view_state:
            return
        # 0 = Wireframe, 1 = Surface
        self.view_state.setWireframe(value == 0)

    def overlay_changed(self, value):
        if self._updating or not self.view_state:
            return
        self.view_state.setOverlay(bool(value))

    def dimension_changed(self, index):
        if self._updating or not self.view_state:
            return
        text = self.widget.Dimension.itemText(index)
        self.view_state.setDimensionMode(text)

    def colormode_changed(self, index):
        if self._updating or not self.view_state:
            return
        text = self.color_mode.itemText(index)
        self.view_state.setColorMode(text)

    def geometry_button_checked(self, value):
        if self._updating or not self.view_state:
            return
        if value:
            self.view_state.setActiveStage("Geometry")
        elif self.mesh_obj:
            self.view_state.setActiveStage("Mesh")
        else:
            # No mesh yet — keep Geometry stage so colouring/tree stay consistent.
            self._updating = True
            try:
                self.widget.GeometryButton.setChecked(True)
            finally:
                self._updating = False

    def mesh_button_checked(self, value):
        if self._updating or not self.view_state:
            return
        if value:
            self.view_state.setActiveStage("Mesh")
        else:
            self.view_state.setActiveStage("Geometry")


class MainWidget(QtGui.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = ViewSettings(self)
        self._explorer = GeometryExplorer(self)

        layout = QtGui.QVBoxLayout()
        layout.addWidget(self._settings)
        layout.addWidget(self._explorer)
        self.setLayout(layout)

    def shutdown(self):
        self._explorer.shutdown()
        self._settings.shutdown()


class Panel(QtGui.QDockWidget):

    def __init__(self, parent=None):
        super().__init__("FEM View", parent)
        self.setObjectName("FEMView")
        self._widget = MainWidget()
        self.setWidget(self._widget)

    def shutdown(self):
        self._widget.shutdown()


def _panel_pref():
    return FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")


def setup_visualization_panel():
    """
    Create and show the panel when the FEM workbench activates.

    Match the prototype lifecycle: destroy on deactivate, recreate on activate.
    """
    global __dock
    if __dock is not None:
        return

    mw = FreeCADGui.getMainWindow()
    __dock = Panel(mw)
    mw.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, __dock)
    __dock.setVisible(_panel_pref().GetBool("ShowViewPanel", True))


def unsetup_visualization_panel():
    """Tear down the panel when leaving the FEM workbench (prototype behaviour)."""
    global __dock
    if __dock is None:
        return

    _panel_pref().SetBool("ShowViewPanel", __dock.isVisible())
    mw = FreeCADGui.getMainWindow()
    if mw is not None:
        mw.removeDockWidget(__dock)
    __dock.shutdown()
    __dock.deleteLater()
    __dock = None


def toggle_visualization_panel():
    global __dock
    if __dock is None:
        setup_visualization_panel()
        return

    visible = not __dock.isVisible()
    __dock.setVisible(visible)
    if visible:
        __dock.raise_()
    _panel_pref().SetBool("ShowViewPanel", visible)
