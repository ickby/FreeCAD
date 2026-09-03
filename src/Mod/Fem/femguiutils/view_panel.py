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

import collections
import re

import FreeCAD
import FreeCADGui
import FemGui

import femtools.membertools as mt

from femtools import femutils
from femtools import importmembers

from PySide import QtCore, QtGui
from PySide.QtCore import QModelIndex, Qt, QAbstractItemModel

# store of current dock
__dock = None

# The dimension the mode picks out, None standing for all of them. Shapes are
# what the mesh is made of, dimensions are what the analysis is about, and the
# panel filters by the latter: a "Surface" is a shell to one part and the skin
# of a solid to the next, whereas 2D is 2D.
_DIM_MODES = {"All": None, "3D": 3, "2D": 2, "1D": 1, "0D": 0}
_ALL_DIMENSIONS = "All"
_COLOR_MODES = ["Subelement", "Component", "Material", "CellType"]
# Colour modes that describe mesh elements and mean nothing to the geometry.
_MESH_COLOR_MODES = {"CellType"}
_TREE_ICON_SIZE = 16
_COLOR_COLUMN_WIDTH = _TREE_ICON_SIZE + 12
_VIS_COLUMN_WIDTH = 32
# The stage where neither geometry nor mesh is drawn, which is what clears the
# view for the results. Reads back off the analysis as the state where neither
# the geometry group nor the mesh group is visible.
_NO_STAGE = "NoStage"
_ELEMENT_NAME = re.compile(r"^(Component|CompSolid|Compound|Solid|Shell|Face|Wire|Edge|Vertex)\d+$")

# One placed instance in the tree of an analysis:
#   imp          the FemAnalysisImport object
#   geom         the geometry it draws, or None while its source has none
#   mesh         the mesh container it draws, or None while its source has none
#   parent_path  analysis-relative path of the instance it sits in
#   path_prefix  analysis-relative path of this instance
#   outer        outermost instance, the one a pick is reported on
#   sub_prefix   path of this instance as *outer* names it
#   suppressed   component ids this instance leaves out
_ImportPlace = collections.namedtuple(
    "_ImportPlace", "imp geom mesh parent_path path_prefix outer sub_prefix suppressed"
)


def _drawn_analyses(analysis):
    """
    Every analysis an analysis draws, itself included, one per placement.

    Yields (analysis, suppressed) pairs, where suppressed names the components
    that placement leaves out. A source placed twice is yielded twice: what is
    drawn is one copy per placement, and counting it once would describe
    something other than what is on screen.
    """
    if analysis is None:
        return

    def walk(current, suppressed, chain):
        yield current, suppressed
        for imp in importmembers.collect_imports(current):
            if imp in chain:
                continue
            try:
                source = imp.Analysis
            except (AttributeError, ReferenceError, RuntimeError):
                continue
            if source is None:
                continue
            yield from walk(
                source,
                frozenset(getattr(imp, "SuppressedComponents", ()) or ()),
                chain + [imp],
            )

    yield from walk(analysis, frozenset(), [])


def _ui_path(name):
    return FreeCAD.getHomePath() + "Mod/Fem/Resources/ui/" + name


def _clip_sort_key(name):
    """
    Order clip planes the way their names count.

    They are named "Clip 1", "Clip 2" and so on, and sorted as text the tenth
    lands between the first and the second.
    """
    head = name.rstrip("0123456789")
    tail = name[len(head) :]
    return (head, int(tail) if tail else -1)


def _thousands(number):
    """Group an element count, thin space rather than comma or point.

    Element counts run to six figures, where the eye needs the grouping, and
    the thin space is the one separator that reads the same wherever the user
    is from.
    """
    return f"{number:,}".replace(",", "\u202f")


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


def _chain_preview_input(viewprovider):
    """
    Shape that an edited geometry chain step is picked on, or None for any other
    editor.

    A step builds on its input and holds references into it, so that is the
    shape drawn in its place while the step is open — and the one the panel has
    to describe, down to which parts are on screen.
    """
    obj = _vp_object(viewprovider)
    if obj is None:
        return None
    try:
        base = getattr(obj, "Base", None)
        if base is None:
            return None
        view = base.ViewObject
        if view is None or not hasattr(view, "isChainPreview"):
            return None
        return base if view.isChainPreview() else None
    except (AttributeError, ReferenceError, RuntimeError):
        return None


def _picks_references(viewprovider, analysis):
    """
    Whether the open editor picks references on the geometry of the analysis.

    Constraints, materials, mesh refinements and equations all hold references
    into that geometry, so they are picked on the same shape a chain step is.
    """
    if analysis is None:
        return False
    obj = _vp_object(viewprovider)
    if obj is None or not hasattr(obj, "References"):
        return False
    return femutils.get_analysis(obj) == analysis


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


def _analysis_holds(analysis, obj):
    """Whether *obj* is *analysis* or something reachable from it."""
    if analysis is None or obj is None:
        return False
    if obj == analysis:
        return True
    seen = {obj.Name}
    pending = [obj]
    while pending:
        for parent in pending.pop().InList:
            if parent == analysis:
                return True
            if parent.Name not in seen:
                seen.add(parent.Name)
                pending.append(parent)
    return False


def _changes_imports(analysis, obj, prop):
    """
    Whether a property change adds, drops or alters an import of *analysis*.

    An import sits in a container group inside the analysis rather than in the
    analysis itself, so neither it nor the group appearing is a change of the
    analysis' own Group property.
    """
    if prop not in ("Group", "Analysis", "SuppressedComponents"):
        return False
    try:
        if obj.isDerivedFrom("Fem::FemAnalysisImport"):
            return prop != "Group" and _analysis_holds(analysis, obj)
        if prop == "Group" and obj.isDerivedFrom("App::DocumentObjectGroup"):
            return _analysis_holds(analysis, obj)
    except (AttributeError, ReferenceError, RuntimeError):
        return False
    return False


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

    def slotInEdit(self, viewprovider):
        self.owner.slotInEdit(viewprovider)

    def slotResetEdit(self, viewprovider):
        self.owner.slotResetEdit(viewprovider)


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


class ElementNode:
    """Tree node: geometry hierarchy or classification category/member."""

    def __init__(
        self,
        name=None,
        parent=None,
        *,
        element=None,
        target_obj=None,
        sub_name=None,
        category_key=None,
        color=None,
        dim_badge=None,
        mesh_achieved=None,
        count_badge=None,
        is_category=False,
        cell_type=False,
        construction_group=False,
        selectable=True,
    ):
        self.name = name
        self.children = []
        self._parent = parent
        self.element = element  # analysis-relative path for hide/select, if any
        # Whether the row stands for something Selection can be told about. A
        # mesh toplevel hides and shows like any other row but names nothing the
        # 3D view can pick, so it carries an element without being selectable.
        self.selectable = selectable
        self.target_obj = target_obj  # document object to select on
        # Subname as target_obj names it, which for an import is the path
        # without its own name; Selection and the 3D view expect that form.
        self.sub_name = sub_name if sub_name is not None else element
        self.category_key = category_key
        self._color = color
        self.dim_badge = dim_badge
        # Dimension the mesh reached where that is below the declared one, None
        # where it met it.
        self.mesh_achieved = mesh_achieved
        # Elements the row stands for, where the tree cannot count them itself.
        self.count_badge = count_badge
        self.is_category = is_category
        self.cell_type = cell_type  # hide via cell-type set
        # Head of the construction elements: its tick is the construction
        # setting itself, not a hide of its own.
        self.construction_group = construction_group
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

    def enabled(self):
        """
        False for a row whose tick cannot reach the 3D view: the construction
        elements answer to their own setting first, and while that is off none
        of them is drawn whatever their own box says.
        """
        if not self.view_state:
            return True
        parent = self._parent
        if parent is not None and parent.construction_group:
            return bool(self.view_state.getShowConstruction())
        return True

    def visible(self):
        if not self.view_state:
            return True
        if self.construction_group:
            return bool(self.view_state.getShowConstruction())
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
        if self.construction_group:
            # One state, two ways in: the panel checkbox and this row. Leaving
            # the per-type hides below untouched means the group comes back the
            # way the user last had it.
            self.view_state.setShowConstruction(bool(value))
            return
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

    def display_name(self):
        label = self.name or ""
        extras = []
        if self.dim_badge is not None:
            extras.append(f"{self.dim_badge}D")
        if self.count_badge is not None:
            extras.append(_thousands(self.count_badge))
        if self.mesh_achieved is not None:
            # The mesher did not fail, it came up one dimension short, and the
            # analysis runs on what it did reach. Saying which one that is
            # spares a trip to the mesh to find out.
            extras.append(
                QtCore.QCoreApplication.translate("FEM_ViewPanel", "meshed {}D").format(
                    self.mesh_achieved
                )
            )
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
        self.mesh_obj = None
        self.view_state = None
        self.geometry_only = False
        self.analysis = None

    def set_context(
        self, geom_obj, view_state, geometry_only=False, analysis=None, mesh_obj=None
    ):
        """
        Describe geom_obj. With geometry_only the colour modes that group by
        category are passed over: their categories are keyed by the elements of
        the analysis geometry, which say nothing about a chain step's input.
        mesh_obj is the analysis mesh container; the Mesh stage builds its tree
        from that topology instead of the geometry.
        """
        self.geom_obj = geom_obj
        self.mesh_obj = mesh_obj
        self.view_state = view_state
        self.geometry_only = geometry_only
        self.analysis = analysis
        self.update_model()

    def clear(self):
        self.geom_obj = None
        self.mesh_obj = None
        self.view_state = None
        self.geometry_only = False
        self.analysis = None
        self.update_model()

    def _attach_state(self, node):
        node.view_state = self.view_state
        for child in node.children:
            self._attach_state(child)

    def update_model(self):
        # An analysis that only places others has no geometry of its own, and
        # the instances it places are all there is to describe.
        if not self.view_state or (
            not self.geom_obj and not self.mesh_obj and not self.analysis
        ):
            self.root = None
            return

        color_mode = self.view_state.getColorMode()
        under = self.view_state.getUnderAchievedElements() or {}
        mesh_stage = self.view_state.getActiveStage() == "Mesh"

        if color_mode in ("Material", "CellType") and not self.geometry_only:
            # Materials are assigned to geometry references and CellType lists
            # no topology, so both stay geometry-based in every stage.
            self.root = self._build_category_tree(color_mode, under)
        else:
            self.root = self._build_geometry_tree(color_mode, under, mesh_stage=mesh_stage)

        if self.root:
            self._attach_state(self.root)

    def _import_places(self, need_mesh=False):
        """
        Every instance reachable from the analysis, outer ones before the
        instances nested in them. need_mesh also resolves the mesh container
        each instance draws, which only the Mesh stage has a use for.

        An import draws its nested imports itself, so a pick anywhere in the
        subtree is reported on the outermost import; that is the object to hand
        to Selection, with the rest of the path as the subname.
        """
        places = []
        if not self.analysis:
            return places

        def walk(imp, parent_path, outer, sub_prefix, chain):
            if imp in chain:
                return
            path_prefix = f"{parent_path}{imp.Name}."
            try:
                src = imp.Analysis
            except (AttributeError, ReferenceError, RuntimeError):
                src = None
            # sourceGeometry() is C++ only; an import has no Python type.
            src_geom = femutils.get_reference_geometry(src) if src is not None else None
            src_meshes = (
                mt.get_member(src, "Fem::FemMeshShapeGroup")
                if need_mesh and src is not None
                else []
            )
            src_mesh = src_meshes[0] if src_meshes else None
            places.append(
                _ImportPlace(
                    imp,
                    src_geom,
                    src_mesh,
                    parent_path,
                    path_prefix,
                    outer,
                    sub_prefix,
                    tuple(getattr(imp, "SuppressedComponents", ()) or ()),
                )
            )
            if src is None:
                return
            for nested in importmembers.collect_imports(src):
                walk(
                    nested,
                    path_prefix,
                    outer,
                    f"{sub_prefix}{nested.Name}.",
                    chain + [imp],
                )

        for imp in importmembers.collect_imports(self.analysis):
            walk(imp, "", imp, "", [])
        return places

    def _root_node(self, mesh_stage=False):
        """
        Head of the tree: the geometry or mesh it describes, or the analysis
        itself when that has none of its own and only places other analyses.
        """
        if mesh_stage and self.mesh_obj is not None:
            owner = self.mesh_obj
        elif self.geom_obj is not None:
            owner = self.geom_obj
        else:
            owner = self.analysis
        target = None if mesh_stage else self.geom_obj
        return ElementNode(owner.Label if owner is not None else "", target_obj=target)

    def _build_geometry_tree(self, color_mode, under, mesh_stage=False):
        root = self._root_node(mesh_stage=mesh_stage)
        categories = {c["key"]: c for c in (self.view_state.getCategories() or [])}
        if mesh_stage:
            if self.mesh_obj is not None:
                self._append_topology_components(
                    self.mesh_obj,
                    root,
                    "",
                    None,
                    "",
                    categories,
                    color_mode,
                    under=None,
                    selectable=False,
                )
        elif self.geom_obj is not None:
            self._append_topology_components(
                self.geom_obj,
                root,
                "",
                self.geom_obj,
                "",
                categories,
                color_mode,
                under,
            )
        if self.analysis and not self.geometry_only:
            nodes = {"": root}
            for place in self._import_places(need_mesh=mesh_stage):
                parent = nodes.get(place.parent_path, root)
                # Mesh rows carry no 3D selection link: the preprocess mesh VP
                # returns no subelement names.
                target = None if mesh_stage else place.outer
                imp_node = ElementNode(place.imp.Label, parent, target_obj=target)
                parent.children.append(imp_node)
                nodes[place.path_prefix] = imp_node
                if mesh_stage:
                    if place.mesh is None:
                        continue
                    self._append_topology_components(
                        place.mesh,
                        imp_node,
                        place.path_prefix,
                        None,
                        "",
                        categories,
                        color_mode,
                        under=None,
                        selectable=False,
                        suppressed=set(place.suppressed),
                    )
                else:
                    if place.geom is None:
                        continue
                    self._append_topology_components(
                        place.geom,
                        imp_node,
                        place.path_prefix,
                        place.outer,
                        place.sub_prefix,
                        categories,
                        color_mode,
                        under,
                        suppressed=set(place.suppressed),
                    )
        return root

    def _append_topology_components(
        self,
        provider,
        root,
        path_prefix,
        target,
        sub_prefix,
        categories,
        color_mode,
        under,
        suppressed=(),
        selectable=True,
    ):
        # Which row carries the swatch is the colour mode itself. Colouring by
        # component makes one statement about the whole component, and painting
        # it again on every element under it repeats that statement without
        # adding to it — worse, it reads as if the elements had been told apart.
        #
        # provider is either FemGeometry or FemMeshShapeGroup: both expose
        # getComponentCount / getToplevelElements / getAnalysisDimension. The
        # mesh group answers these from the merge cache, which rebuilds only
        # when a child mesh changed, so reading it per rebuild costs nothing.
        per_component = color_mode == "Component"
        for i in range(provider.getComponentCount()):
            # A component an instance leaves out is neither drawn nor solved
            # with, so it has nothing to say in the tree either.
            if (i + 1) in suppressed:
                continue
            component_cat = categories.get(f"{path_prefix}Component{i + 1}")
            geometry_node = ElementNode(
                f"Component{i + 1}",
                root,
                target_obj=target,
                color=_color_tuple(component_cat["color"]) if component_cat else None,
            )
            root.children.append(geometry_node)
            for sub in provider.getToplevelElements(i):
                dim = None
                try:
                    dim = provider.getAnalysisDimension(sub)
                except Exception:
                    pass
                element_path = f"{path_prefix}{sub}"
                cat = None if per_component else categories.get(element_path)
                node = ElementNode(
                    sub,
                    geometry_node,
                    # Kept even where the row is not selectable: element is also
                    # the key the row hides and shows itself by.
                    element=element_path,
                    target_obj=target,
                    sub_name=f"{sub_prefix}{sub}" if selectable else None,
                    color=_color_tuple(cat["color"]) if cat else None,
                    dim_badge=dim if dim is not None and dim >= 0 else None,
                    mesh_achieved=under.get(element_path) if under else None,
                    selectable=selectable,
                )
                geometry_node.children.append(node)

    def _build_category_tree(self, color_mode, under):
        root = self._root_node()
        cats = self.view_state.getCategories() or []
        if color_mode == "CellType":
            # Cell types are mesh-local, so no element of the geometry is going
            # to end up under one of them.
            return self._append_cell_types(root, cats)

        # (element, analysis-relative path, geometry, select-on object, subname)
        all_elements = []

        def collect(geom, path_prefix, target, sub_prefix, suppressed=()):
            for i in range(geom.getComponentCount()):
                if (i + 1) in suppressed:
                    continue
                for e in geom.getToplevelElements(i):
                    all_elements.append((e, f"{path_prefix}{e}", geom, target, f"{sub_prefix}{e}"))

        if self.geom_obj is not None:
            collect(self.geom_obj, "", self.geom_obj, "")
        for place in self._import_places():
            if place.geom is not None:
                collect(
                    place.geom,
                    place.path_prefix,
                    place.outer,
                    place.sub_prefix,
                    set(place.suppressed),
                )

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
            )
            root.children.append(cat_node)

            for e, element_path, geom, target, sub_name in all_elements:
                if self.view_state.categoryOfElement(element_path) != cat_idx:
                    continue
                dim = None
                try:
                    dim = geom.getAnalysisDimension(e)
                except Exception:
                    pass
                # No swatch: the colour is the category's, and the row is under
                # it precisely because it has nothing of its own to say.
                member = ElementNode(
                    e,
                    cat_node,
                    element=element_path,
                    target_obj=target,
                    sub_name=sub_name,
                    category_key=key,
                    dim_badge=dim if dim is not None and dim >= 0 else None,
                    mesh_achieved=under.get(element_path),
                )
                cat_node.children.append(member)

            count = len(cat_node.children)
            cat_node.name = f"{label} ({count})"

        return root

    def _append_cell_types(self, root, cats):
        """
        The element types under the two heads that say what they are for.

        Which types the analysis solves on and which ones only got the mesher
        there is the one thing the cell-type colouring is asked to teach, and a
        type can sit on both sides at once: the triangles skinning a solid and
        the triangles of a shell are both tria3. Grouping says which is which
        without the list having to shrink and grow as the view is filtered,
        which is not something the tree does for any other setting.
        """
        groups = {}

        def group_for(construction):
            node = groups.get(construction)
            if node is not None:
                return node
            name = (
                QtCore.QCoreApplication.translate("FEM_ViewPanel", "Construction elements")
                if construction
                else QtCore.QCoreApplication.translate("FEM_ViewPanel", "Analysis elements")
            )
            node = ElementNode(
                name,
                root,
                is_category=True,
                construction_group=construction,
            )
            groups[construction] = node
            return node

        # Analysis first whatever order the categories arrive in; the mesh is
        # the point and the scaffolding is the footnote.
        for construction in (False, True):
            for cat in cats:
                if bool(cat.get("construction")) != construction:
                    continue
                key = cat["key"]
                label = cat.get("label") or key
                parent = group_for(construction)
                parent.children.append(
                    ElementNode(
                        label,
                        parent,
                        category_key=key,
                        color=_color_tuple(cat.get("color")),
                        count_badge=cat.get("count"),
                        is_category=True,
                        cell_type=True,
                    )
                )

        for construction in (False, True):
            node = groups.get(construction)
            if node is not None:
                root.children.append(node)

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

        if role == Qt.ItemDataRole.ToolTipRole and column == 0:
            return node.display_name()

        # Stable key for selection sync (DisplayRole includes badges like "[3D]")
        if role == Qt.ItemDataRole.UserRole and column == 0:
            return node.element or node.name

        if role == Qt.DecorationRole and column == 1:
            color = node.color()
            if color:
                size = _TREE_ICON_SIZE
                pixmap = QtGui.QPixmap(size, size)
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

        node = self.get_item(index)
        if node is not None and not node.enabled():
            # Still selectable: a row the user cannot tick right now is one
            # they should still be able to pick out in the 3D view.
            return Qt.ItemIsSelectable

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
            # A node without an element of its own hides one descendant at a
            # time, and every one of them would otherwise reach the renderers as
            # a change of its own. What the user did was tick one box.
            state = node.view_state
            if state is not None:
                state.beginUpdate()
            try:
                node.set_visible(checked)
            finally:
                if state is not None:
                    state.endUpdate()
                if explorer is not None:
                    explorer._suspend_vs_rebuild = False
            self._emit_check_column(index)
            return True
        return False

    def _emit_check_column(self, index):
        """
        Refresh this node, its ancestors and its descendants.

        The whole row, not only the box: turning the construction elements off
        greys out the types under them, and a row that changed how it is drawn
        has to be repainted for the user to see it.
        """
        if not index.isValid():
            return

        def refresh(row):
            first = row.sibling(row.row(), 0)
            last = row.sibling(row.row(), self.columnCount(row.parent()) - 1)
            if first.isValid() and last.isValid():
                self.dataChanged.emit(first, last)

        # Descendants (parent toggle propagates hide to children). Off the first
        # column an index has no children to walk, and the box that was ticked
        # sits in the last one.
        stack = [index.sibling(index.row(), 0)]
        while stack:
            cur = stack.pop()
            refresh(cur)
            item = cur.internalPointer()
            if not item:
                continue
            for r in range(item.child_count()):
                stack.append(self.index(r, 0, cur))
        # Ancestors (parent partial/all visibility)
        parent = index.parent()
        while parent.isValid():
            refresh(parent)
            parent = parent.parent()


class GeometryExplorer(QtGui.QTreeView):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_analysis = None
        self.geom_obj = None
        self.mesh_obj = None
        self.view_state = None
        self._vs_callback = None
        self._suspend_vs_rebuild = False
        self.edit_obj = None
        self._edit_step = None
        self._pre_edit_hidden = None
        self._color_mode = None
        self._updating_color_mode = False

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

        self.setHeaderHidden(True)
        self.setIconSize(QtCore.QSize(_TREE_ICON_SIZE, _TREE_ICON_SIZE))
        if hasattr(QtCore.Qt, "TextElideMode"):
            self.setTextElideMode(QtCore.Qt.TextElideMode.ElideRight)
        else:
            self.setTextElideMode(QtCore.Qt.ElideRight)
        self._configure_columns()

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

    def _configure_columns(self):
        """Keep colour and visibility columns minimal and pinned to the right."""
        header = self.header()
        header.setStretchLastSection(False)
        header.setCascadingSectionResizes(False)
        header.setSectionsMovable(False)
        header.setMinimumSectionSize(1)
        if hasattr(header, "setSectionResizeMode"):
            fixed = QtGui.QHeaderView.ResizeMode.Fixed
            stretch = QtGui.QHeaderView.ResizeMode.Stretch
            set_mode = header.setSectionResizeMode
        else:
            fixed = QtGui.QHeaderView.Fixed
            stretch = QtGui.QHeaderView.Stretch
            set_mode = header.setResizeMode
        set_mode(0, stretch)
        set_mode(1, fixed)
        set_mode(2, fixed)
        header.resizeSection(1, _COLOR_COLUMN_WIDTH)
        header.resizeSection(2, _VIS_COLUMN_WIDTH)

    def attach_color_mode(self, combo):
        """Wire the tree header combo that selects the colour layout."""
        self._color_mode = combo
        combo.currentIndexChanged.connect(self._colormode_changed)
        self._sync_color_mode()

    def _sync_color_mode(self):
        combo = self._color_mode
        if combo is None:
            return
        stage = self.view_state.getActiveStage() if self.view_state else None
        # Nothing is drawn outside the two preprocessing stages, so there is no
        # colouring to choose either.
        combo.setEnabled(stage in ("Geometry", "Mesh"))
        if not self.view_state:
            return
        self._sync_color_mode_entries(combo, stage)
        cm = self.view_state.getColorMode()
        idx = combo.findText(cm)
        if idx < 0:
            return
        self._updating_color_mode = True
        try:
            combo.setCurrentIndex(idx)
        finally:
            self._updating_color_mode = False

    @staticmethod
    def _sync_color_mode_entries(combo, stage):
        """
        Grey out the entries that say nothing about the stage on show.

        The view state coerces a mesh colouring back to Subelement outside the
        mesh stage, and a combo that springs back the moment it is let go is a
        riddle. Greyed out it is an answer instead.
        """
        why = QtCore.QCoreApplication.translate(
            "FEM_ViewPanel", "Colours mesh elements, so only the mesh stage has it"
        )
        model = combo.model()
        for index in range(combo.count()):
            item = model.item(index) if hasattr(model, "item") else None
            if item is None:
                continue
            mesh_only = combo.itemText(index) in _MESH_COLOR_MODES
            item.setEnabled(not mesh_only or stage == "Mesh")
            combo.setItemData(
                index,
                why if mesh_only else None,
                QtCore.Qt.ItemDataRole.ToolTipRole,
            )

    def _colormode_changed(self, index):
        if self._updating_color_mode or not self.view_state or self._color_mode is None:
            return
        text = self._color_mode.itemText(index)
        self.view_state.setColorMode(text)

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
            self._sync_color_mode()
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

    def _forget_edit_session(self):
        """
        Give up on an edit session, gone analysis or gone input: there is
        nothing left to describe, and no view state to hand the hidden elements
        back to.
        """
        self._edit_step = None
        self.edit_obj = None
        self._pre_edit_hidden = None

    def setup_analysis(self):
        self._model.beginResetModel()
        self.view_state = None
        self.geom_obj = None
        self.mesh_obj = None

        if self.active_analysis:
            self.view_state = FemGui.getAnalysisViewState(self.active_analysis)
            geom_list = mt.get_member(self.active_analysis, "Fem::FemGeometry")
            self.geom_obj = geom_list[0] if geom_list else None
            mesh_list = mt.get_member(self.active_analysis, "Fem::FemMeshShapeGroup")
            self.mesh_obj = mesh_list[0] if mesh_list else None
            self._model.set_context(
                self._tree_object(),
                self.view_state,
                geometry_only=self.edit_obj is not None,
                analysis=self.active_analysis,
                mesh_obj=self.mesh_obj,
            )
        else:
            self._forget_edit_session()
            self._model.clear()

        self._connect_view_state()
        self._model.endResetModel()
        self._sync_color_mode()
        self.expandAll()
        # A model reset drops the highlight; restore it from Gui.Selection.
        self._request_tree_sync()

    def slotActiveFemAnalysisUpdated(self, analysis):
        if analysis != self.active_analysis:
            self.active_analysis = analysis
            self._forget_edit_session()
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
        if not self.active_analysis or not obj:
            return
        if obj.isDerivedFrom("Fem::FemGeometry") or obj.isDerivedFrom("Fem::FemMeshShapeGroup"):
            self.setup_analysis()

    def _app_changed_object(self, obj, prop=None):
        if not self.active_analysis or prop is None:
            return
        # An import contributes rows of its own, so what it places and what it
        # leaves out change the tree just like a geometry change does. The mesh
        # container's Group is what the Mesh-stage tree is built from, and a
        # child that re-meshes changes that tree without the Group moving.
        if prop not in ("Shape", "Group", "Analysis", "SuppressedComponents", "FemMesh"):
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
                return
            if obj.isDerivedFrom("Fem::FemMeshShapeGroup") and prop in ("Group", "Shape"):
                self.setup_analysis()
                return
            # A child that re-meshes rebuilds the merged topology the Mesh stage
            # reads. The group derives from FemMeshObject too, but its own
            # FemMesh is that merge and is written without notifying.
            if (
                prop == "FemMesh"
                and obj.isDerivedFrom("Fem::FemMeshObject")
                and not obj.isDerivedFrom("Fem::FemMeshShapeGroup")
            ):
                self.setup_analysis()
                return
            if _changes_imports(self.active_analysis, obj, prop):
                self.setup_analysis()
        except (AttributeError, ReferenceError, RuntimeError):
            return

    def slotInEdit(self, viewprovider):
        """
        Follow an edited chain step onto its input geometry.

        The tree then lists what the 3D view draws, so hiding a part clears the
        way to the one behind it and clicking a row selects on the object the
        step's panel is waiting to hear about.
        """
        base = _chain_preview_input(viewprovider)
        if base is None or self._edit_step is not None:
            return
        if base not in self._geometry_chain():
            return

        self._edit_step = _vp_object(viewprovider)
        self.edit_obj = base
        # Parts switched off to reach a reference are scratch: the result view
        # numbers its elements differently and must not inherit them.
        if self.view_state:
            self._pre_edit_hidden = list(self.view_state.getHiddenElements() or [])
        self.setup_analysis()

    def slotResetEdit(self, viewprovider):
        if self._edit_step is None or _vp_object(viewprovider) != self._edit_step:
            return

        self._edit_step = None
        self.edit_obj = None
        hidden = self._pre_edit_hidden
        self._pre_edit_hidden = None
        if self.view_state and hidden is not None:
            self.view_state.setHiddenElements(hidden)
        self.setup_analysis()

    def _tree_object(self):
        """
        Geometry the tree describes: the input of an edited chain step, or the
        chain result when nothing is being edited.
        """
        if self.edit_obj is not None:
            try:
                if self.edit_obj.Name and self.edit_obj in self._geometry_chain():
                    return self.edit_obj
            except (AttributeError, ReferenceError, RuntimeError):
                pass
            self._forget_edit_session()
        return self.geom_obj

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
        Object to select on: whichever geometry draws the shape the tree
        describes — the group normally, the edited step's input while one is
        open. Picking in the 3D view reports the same object, so both directions
        produce identical selection entries.
        """
        return self._tree_object()

    def _element_from_selection(self, doc, obj, sub):
        """
        Resolve a Selection entry to an analysis-relative element path, or None.
        """
        # An analysis that only places others has no geometry to go by, but the
        # instances it places are still picked in the 3D view.
        owner = self.geom_obj if self.geom_obj is not None else self.active_analysis
        if not owner or not doc or not obj:
            return None
        if doc != owner.Document.Name:
            return None

        chain = {o.Name for o in self._geometry_chain()}
        imports = set()
        if self.active_analysis:
            imports = {imp.Name for imp in importmembers.collect_imports(self.active_analysis)}

        sub = sub or ""
        if not sub:
            return None

        # A pick is recorded against the top of the tree, so the object named is
        # the analysis and the way down to what was picked sits in the subname.
        # Read the whole way: the object in front of it names the analysis, not
        # what it holds.
        path = [obj] + sub.split(".")
        leaf = path[-1]
        if not _ELEMENT_NAME.match(leaf):
            return None

        for index, step in enumerate(path[:-1]):
            if step in imports:
                # An instance draws a copy of everything the nested ones hold,
                # so the first one on the way owns the pick, and names it with
                # the nested instances still in front.
                return ".".join(path[index:])

        if any(step in chain for step in path[:-1]):
            # The chain shares one shape and one numbering, so which of its
            # steps was named says nothing: only the element does.
            return leaf

        return None

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
        # An analysis that only places others has no geometry of its own, and
        # the rows for what it places still answer to a selection.
        owner = self.geom_obj if self.geom_obj is not None else self.active_analysis
        # While the tree propagates its own change the selection is still being
        # built up; the deferred pass reconciles the final state.
        if not owner or self.selection_lock:
            return
        self._sync_pending = False

        try:
            doc = owner.Document.Name
        except (AttributeError, ReferenceError, RuntimeError):
            # The deferred pass can outlive the document it was scheduled for
            return
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
        if self.selection_lock:
            return

        def _names(item):
            """
            Rows of *item* as Selection entries. An analysis that only places
            others has no geometry to fall back on, so a row that names no
            object of its own stands for nothing that can be selected.
            """
            if not item:
                return []
            names = []

            def walk(node):
                if node.element and node.selectable and (node.target_obj or target):
                    names.append((node.target_obj or target, node.sub_name or node.element))
                for child in node.children:
                    walk(child)

            if item.element:
                if item.selectable and (item.target_obj or target):
                    names.append((item.target_obj or target, item.sub_name or item.element))
                return names

            walk(item)
            return names

        self.selection_lock = True
        for idx in selected.indexes():
            if idx.column() == 0:
                for obj, name in _names(self._model.get_item(idx)):
                    FreeCADGui.Selection.addSelection(obj, name)
        for idx in deselected.indexes():
            if idx.column() == 0:
                for obj, name in _names(self._model.get_item(idx)):
                    FreeCADGui.Selection.removeSelection(obj, name)
        self.selection_lock = False
        # The rows are where the user put them; do not scroll on the resync that
        # reconciles this change.
        self._suppress_scroll = True


class GeometryTreePanel(QtGui.QWidget):
    """Colour-mode header row and geometry tree."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.color_mode = QtGui.QComboBox()
        self.color_mode.addItems(_COLOR_MODES)
        self.color_mode.setToolTip(
            QtCore.QCoreApplication.translate(
                "FEM_ViewPanel",
                "How the tree is grouped and which colours are shown",
            )
        )

        self.explorer = GeometryExplorer(self)
        self.explorer.attach_color_mode(self.color_mode)
        if hasattr(QtGui.QFrame, "Shape"):
            self.explorer.setFrameShape(QtGui.QFrame.Shape.StyledPanel)
            self.explorer.setFrameShadow(QtGui.QFrame.Shadow.Sunken)
        else:
            self.explorer.setFrameShape(QtGui.QFrame.StyledPanel)
            self.explorer.setFrameShadow(QtGui.QFrame.Sunken)

        layout = QtGui.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.color_mode)
        layout.addWidget(self.explorer)
        self.setLayout(layout)

        size_policy = QtGui.QSizePolicy(
            QtGui.QSizePolicy.Policy.Expanding, QtGui.QSizePolicy.Policy.Expanding
        )
        self.setSizePolicy(size_policy)

    def shutdown(self):
        self.explorer.shutdown()


class _clipEditWidget(QtGui.QWidget):
    """
    Popup with the exact values of one clip plane.

    Origin and normal belong to the plane, the step size does not: it is a
    preference that the handle shares with every other clip plane.

    The spin boxes have keyboard tracking off, so a typed value only arrives
    once the field is left and the clipping is not recomputed per keystroke.
    """

    def __init__(self, handle, analysis=None, on_scope_changed=None, parent=None):
        super().__init__(parent)
        self.handle = handle
        self.analysis = analysis
        self.on_scope_changed = on_scope_changed
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
        scope_tip = QtCore.QCoreApplication.translate(
            "FEM_ViewPanel",
            "What the plane cuts: the whole analysis, or one imported instance "
            "and everything inside it",
        )
        self.widget.ScopeLabel.setToolTip(scope_tip)
        self.widget.Scope.setToolTip(scope_tip)
        for button, axis in self._axis_buttons():
            button.setToolTip(
                QtCore.QCoreApplication.translate(
                    "FEM_ViewPanel", "Cut along {}, keeping the far side"
                ).format(axis)
            )
        self.widget.FlipButton.setToolTip(
            QtCore.QCoreApplication.translate(
                "FEM_ViewPanel", "Keep the other side of the plane instead"
            )
        )

        self.layout = QtGui.QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.widget)
        self.setLayout(self.layout)

        self.widget.OffsetStep.valueChanged.connect(self.offset_step_changed)
        self.widget.AngleStep.valueChanged.connect(self.angle_step_changed)
        self.widget.Scope.currentIndexChanged.connect(self.scope_changed)
        for box in self._plane_boxes():
            box.valueChanged.connect(self.plane_changed)
        self.widget.NormalXButton.clicked.connect(self.normal_x_clicked)
        self.widget.NormalYButton.clicked.connect(self.normal_y_clicked)
        self.widget.NormalZButton.clicked.connect(self.normal_z_clicked)
        self.widget.FlipButton.clicked.connect(self.flip_clicked)

    def _scope_paths(self):
        """
        Selectable scopes, the whole analysis first, then every instance path.
        """
        paths = [""]
        if self.analysis is None:
            return paths

        def walk(imp, prefix, chain):
            if imp in chain:
                return
            path = f"{prefix}{imp.Name}"
            paths.append(path)
            try:
                src = imp.Analysis
            except (AttributeError, ReferenceError, RuntimeError):
                return
            if src is None:
                return
            for nested in importmembers.collect_imports(src):
                walk(nested, f"{path}.", chain + [imp])

        try:
            for imp in importmembers.collect_imports(self.analysis):
                walk(imp, "", [])
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        return paths

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
            # An import may have come or gone since the popup was last filled.
            paths = self._scope_paths()
            whole = QtCore.QCoreApplication.translate("FEM_ViewPanel", "Whole analysis")
            self.widget.Scope.clear()
            for path in paths:
                self.widget.Scope.addItem(whole if not path else path, path)
            scope = self.handle.getScope()
            index = paths.index(scope) if scope in paths else 0
            self.widget.Scope.setCurrentIndex(index)
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

    def scope_changed(self, index=None):
        if self._updating or not self.handle:
            return
        scope = self.widget.Scope.currentData()
        self.handle.setScope(scope if scope else "")
        if self.on_scope_changed:
            self.on_scope_changed()

    def _axis_buttons(self):
        return (
            (self.widget.NormalXButton, "X"),
            (self.widget.NormalYButton, "Y"),
            (self.widget.NormalZButton, "Z"),
        )

    def _set_normal(self, normal):
        """
        Point the plane along a new normal, leaving it where it is.

        Six of the directions a clipping plane is ever given are the axes, and
        typing three numbers to reach one of them is three chances to end up
        with a plane at some angle nobody asked for.
        """
        if not self.handle:
            return
        self.handle.setPlane(self.handle.getOrigin(), normal)
        self.refresh()

    def normal_x_clicked(self, value=None):
        self._set_normal(FreeCAD.Vector(1, 0, 0))

    def normal_y_clicked(self, value=None):
        self._set_normal(FreeCAD.Vector(0, 1, 0))

    def normal_z_clicked(self, value=None):
        self._set_normal(FreeCAD.Vector(0, 0, 1))

    def flip_clicked(self, value=None):
        if self.handle:
            self._set_normal(self.handle.getNormal().negative())

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
    the handle, which belongs to the analysis rather than to this row. So the
    row can come and go with the panel while the plane keeps cutting, and a
    plane added from the toolbar grows a row here without being asked to.
    """

    def __init__(self, handle, analysis=None, parent=None):
        super().__init__(parent)
        self.handle = handle

        self.widget = FreeCADGui.PySideUic.loadUi(_ui_path("ViewClipWidget.ui"))
        self.widget.ClipButton.setChecked(handle.isActive())
        self.widget.WidgetButton.setChecked(handle.isWidgetVisible())
        # Without an icon a QToolButton falls back to its text, and a row of
        # three buttons one of which is a word does not read as a row.
        self.widget.WidgetButton.setIcon(FreeCADGui.getIcon("Std_Placement.svg"))
        self.widget.DeleteButton.setIcon(FreeCADGui.getIcon("delete.svg"))
        self.widget.EditButton.setIcon(FreeCADGui.getIcon("preferences-general.svg"))
        self.widget.DeleteButton.setToolTip(
            QtCore.QCoreApplication.translate("FEM_ViewPanel", "Remove this clipping plane")
        )
        self.setup_label()
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
        self.editor = _clipEditWidget(handle, analysis, on_scope_changed=self.setup_label)
        self.edit_menu = QtGui.QMenu(self.widget.EditButton)
        edit_action = QtGui.QWidgetAction(self.edit_menu)
        edit_action.setDefaultWidget(self.editor)
        self.edit_menu.addAction(edit_action)

        # Parts this row from the one above it. Hidden on the first row, where
        # the frame of the group box is line enough.
        self.separator = QtGui.QFrame()
        if hasattr(QtGui.QFrame, "Shape"):
            self.separator.setFrameShape(QtGui.QFrame.Shape.HLine)
            self.separator.setFrameShadow(QtGui.QFrame.Shadow.Sunken)
        else:
            self.separator.setFrameShape(QtGui.QFrame.HLine)
            self.separator.setFrameShadow(QtGui.QFrame.Sunken)
        self.separator.setVisible(False)

        self.layout = QtGui.QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        self.layout.addWidget(self.separator)
        self.layout.addWidget(self.widget)
        self.setLayout(self.layout)

        self.widget.ClipButton.clicked.connect(self.clip_changed)
        self.widget.WidgetButton.clicked.connect(self.widget_changed)
        self.widget.EditButton.clicked.connect(self.edit_clicked)
        self.widget.DeleteButton.clicked.connect(self.delete_clicked)

    @property
    def name(self):
        return self.handle.getName() if self.handle else ""

    def setup_label(self):
        """
        Name the row, and say what it cuts where that is not everything.

        Planes are called 1, 2, 3, which tells the rows apart and nothing else.
        The one thing that distinguishes them at a glance is what they reach,
        so a plane confined to an instance carries its path.
        """
        if not self.handle:
            return
        name = self.handle.getName()
        scope = self.handle.getScope()
        label = f"{name} · {scope}" if scope else name
        self.widget.ClipButton.setText(label)
        self.widget.ClipButton.setToolTip(
            QtCore.QCoreApplication.translate("FEM_ViewPanel", "Cut {} with this plane").format(
                scope
            )
            if scope
            else QtCore.QCoreApplication.translate(
                "FEM_ViewPanel", "Cut the whole analysis with this plane"
            )
        )

    def set_separated(self, on):
        """Draw, or drop, the rule that parts this row from the one above."""
        self.separator.setVisible(bool(on))

    def shutdown(self):
        """
        Retire the row. The plane stays.

        Closing the panel, or leaving the workbench, is not a request to stop
        clipping: the analysis is expected to come back cut the way it was
        left. Dropping a plane is delete_clicked().
        """
        self.editor.shutdown()
        self.handle = None
        self.setParent(None)
        self.deleteLater()

    def refresh(self):
        """Re-fit the plane indicator and resync the buttons with the handle."""
        if not self.handle:
            return
        self.handle.refresh()
        self.widget.ClipButton.setChecked(self.handle.isActive())
        self.setup_label()
        if self.editor.isVisible():
            self.editor.refresh()

    def edit_clicked(self, value=None):
        button = self.widget.EditButton
        self.edit_menu.popup(button.mapToGlobal(QtCore.QPoint(0, button.height())))

    def delete_clicked(self, value):
        """Drop the plane, which is what takes this row and the dragger with it."""
        if self.handle:
            self.handle.remove()

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

        self.widget.Dimension.clear()
        self.widget.Dimension.addItems(list(_DIM_MODES))
        self.widget.Dimension.setToolTip(
            QtCore.QCoreApplication.translate(
                "FEM_ViewPanel",
                "Which dimensions to show. Only the ones the analysis has can be "
                "picked, unless the construction elements are taken in as well.",
            )
        )
        self.widget.Construction.setToolTip(
            QtCore.QCoreApplication.translate(
                "FEM_ViewPanel",
                "Also show the elements the mesher built the mesh from, such as the "
                "skin of a solid. The analysis does not solve them.",
            )
        )
        self.widget.ElementCount.setToolTip(
            QtCore.QCoreApplication.translate(
                "FEM_ViewPanel", "Elements shown, of the elements in the mesh"
            )
        )

        self.layout = QtGui.QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.widget)
        self.setLayout(self.layout)

        self.active_analysis = FemGui.getActiveAnalysis()
        self.view_state = None
        self.geom_obj = None
        self.mesh_obj = None
        self._has_geometry = False
        self._has_mesh = False
        self._vs_callback = None
        self._updating = False
        self._edit_obj = None
        self._edit_stage = None
        self._counts = None
        self._geometry_counts = None
        self.setup_analysis()

        self.widget.GeometryButton.clicked.connect(self.geometry_button_checked)
        self.widget.MeshButton.clicked.connect(self.mesh_button_checked)
        self.widget.Dimension.currentIndexChanged.connect(self.dimension_changed)
        self.widget.Construction.clicked.connect(self.construction_changed)
        self.widget.ViewMode.currentIndexChanged.connect(self.viewmode_changed)
        self.widget.Overlay.clicked.connect(self.overlay_changed)
        self.widget.ClipButton.clicked.connect(self.add_clipping_plane)

        FemGui.addActiveAnalysisObserver(self)
        self._gui_observer = _GuiDocObserver(self)
        self._app_observer = _AppDocObserver(self)
        FreeCADGui.addDocumentObserver(self._gui_observer)
        FreeCAD.addDocumentObserver(self._app_observer)

    def shutdown(self):
        self.clear_clipping_planes()
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
            # A plane may have been added or dropped from anywhere: the
            # toolbar, another row, a macro. The list of rows is worked out
            # from the planes rather than tracked alongside them.
            self.setup_clipping_planes()
            self.setup_widgets()

        self._vs_callback = _on_changed
        self.view_state.connectChanged(self._vs_callback)

    def setup_analysis(self):
        self.geom_obj = None
        self.mesh_obj = None
        self.view_state = None

        from femtools import importtools

        if self.active_analysis:
            self.view_state = FemGui.getAnalysisViewState(self.active_analysis)
            geom_list = mt.get_member(self.active_analysis, "Fem::FemGeometry")
            self.geom_obj = geom_list[0] if geom_list else None
            mesh_list = mt.get_member(self.active_analysis, "Fem::FemMeshShapeGroup")
            self.mesh_obj = mesh_list[0] if mesh_list else None
            # An analysis that only places others has neither geometry nor mesh
            # of its own, and both stages still show what the instances draw.
            places = importtools.analysis_has_imports(self.active_analysis)
            self._has_geometry = self.geom_obj is not None or places
            self._has_mesh = self.mesh_obj is not None or places
            # A mesh can go away under the panel, and the stage it left behind
            # draws nothing and offers no way back. Showing neither is a
            # deliberate choice on the other hand, so that one is left alone.
            if self.view_state and not self._has_mesh:
                if self.view_state.getActiveStage() == "Mesh":
                    self.view_state.setActiveStage("Geometry" if self._has_geometry else _NO_STAGE)
        else:
            self._has_geometry = False
            self._has_mesh = False
            # No analysis left to put the stage back on.
            self._edit_obj = None
            self._edit_stage = None

        self._connect_view_state()
        self._counts = self._read_element_counts()
        self._geometry_counts = self._read_geometry_counts()

        # setup_analysis() also runs on every geometry or mesh change, where
        # the planes stay put and only their indicators need re-fitting to a
        # model that may have changed size.
        self.setup_clipping_planes()
        for widget in self.clip_widgets():
            widget.refresh()

        self.setup_widgets()

    # -- how many elements there are, and of which dimension ------------------

    def _read_element_counts(self):
        """
        Mesh elements per dimension, counted once per change of the mesh.

        Two tallies: what the analysis solves, taken from the classification the
        merge leaves behind, and what the mesh holds altogether. The difference
        between them is the construction elements. Walking every element is too
        much to do from setup_widgets(), which runs on every change of the view
        state, so the numbers are kept until the mesh itself moves.

        Over every mesh drawn rather than the one the analysis owns: an assembly
        draws the mesh of all it places, and its own is a part of that view
        being described as though it were the whole of it.
        """
        total = 0
        analysis = {0: 0, 1: 0, 2: 0, 3: 0}
        topology = {0: 0, 1: 0, 2: 0, 3: 0}
        # A placement that leaves components out still has them in its mesh,
        # which knows nothing of the components; the elements can only be told
        # apart by the geometry they were built on, and that is more work than
        # a count of what is available is worth.
        for placed, _ in _drawn_analyses(self.active_analysis):
            for mesh in mt.get_member(placed, "Fem::FemMeshShapeGroup"):
                try:
                    # The merged mesh first: it is what fills the
                    # classification, and asking the other way round reads
                    # yesterday's answer.
                    femmesh = mesh.FemMesh
                    edges = femmesh.EdgeCount
                    faces = femmesh.FaceCount
                    volumes = femmesh.VolumeCount
                    cell_dim = mesh.CellDimension
                except (AttributeError, ReferenceError, RuntimeError):
                    continue

                cells = len(cell_dim)
                total += cells
                # Counted in one step rather than element by element: an
                # assembly reaches this with everything it places at once.
                tally = collections.Counter(cell_dim)
                for dim in analysis:
                    analysis[dim] += tally[dim]
                topology[1] += edges
                topology[2] += faces
                topology[3] += volumes
                # SMESH keeps no count of the 0D elements of its own; whatever
                # the other three leave over is what they are.
                topology[0] += max(0, cells - edges - faces - volumes)

        if not total:
            return None
        return {"total": total, "analysis": analysis, "topology": topology}

    def _read_geometry_counts(self):
        """
        Toplevel elements per declared dimension, over every geometry drawn.

        What the geometry stage draws is geometry, so this and not the mesh is
        what its dimension entries have to be judged by: a solid is one element
        of dimension three whether or not anything has meshed it yet, and a
        shell placed in an assembly of solids is the 2D of that view however
        the assembly meshed itself.
        """
        counts = {0: 0, 1: 0, 2: 0, 3: 0}
        found = False
        for placed, suppressed in _drawn_analyses(self.active_analysis):
            for geom in mt.get_member(placed, "Fem::FemGeometry"):
                try:
                    components = geom.getComponentCount()
                except (AttributeError, ReferenceError, RuntimeError):
                    continue
                for i in range(components):
                    # A component a placement leaves out is not drawn, so it is
                    # not among the dimensions on offer either.
                    if (i + 1) in suppressed:
                        continue
                    for sub in geom.getToplevelElements(i):
                        try:
                            dim = geom.getAnalysisDimension(sub)
                        except Exception:
                            continue
                        if 0 <= dim <= 3:
                            counts[dim] += 1
                            found = True

        return counts if found else None

    def _dimension_counts(self, construction):
        """
        Elements per dimension of whatever the active stage draws.

        Only a mesh is made of elements a mesher built, so the construction
        setting has something to say about the mesh stage alone.
        """
        if self.view_state and self.view_state.getActiveStage() == "Geometry":
            return self._geometry_counts
        if not self._counts:
            return None
        return self._counts["topology"] if construction else self._counts["analysis"]

    def _shown_count(self, mode, construction):
        counts = self._dimension_counts(construction)
        if counts is None:
            return None
        dim = _DIM_MODES.get(mode)
        return sum(counts.values()) if dim is None else counts.get(dim, 0)

    def _dimension_available(self, mode, construction=None):
        """Whether anything at all would be drawn in this dimension mode."""
        if construction is None:
            construction = bool(self.view_state and self.view_state.getShowConstruction())
        shown = self._shown_count(mode, construction)
        # Without counts to go by, nothing is ruled out.
        return shown is None or shown > 0

    # -- keeping the widgets in step with the state ---------------------------

    def setup_widgets(self):
        self._updating = True
        try:
            has_vs = self.view_state is not None
            editing = self._edit_obj is not None
            stage = self.view_state.getActiveStage() if has_vs else None
            # Outside the two preprocessing stages nothing of the model is
            # drawn, so there is no content to describe. The scene settings
            # below stay live: they still apply to whatever is on screen.
            content = stage in ("Geometry", "Mesh")
            self.widget.GeometryButton.setEnabled(has_vs and self._has_geometry)
            self.widget.MeshButton.setEnabled(has_vs and self._has_mesh and not editing)
            self.widget.ClipButton.setEnabled(has_vs)
            self.widget.Dimension.setEnabled(content)
            # Only a mesh has elements the mesher built it from; the faces of a
            # solid are the solid, not scaffolding around it.
            self.widget.Construction.setEnabled(stage == "Mesh")
            self.widget.ViewMode.setEnabled(has_vs)
            self.widget.Overlay.setEnabled(has_vs)
            self.setup_clip_list()

            if not has_vs:
                self.widget.ElementCount.clear()
                return

            self.widget.Overlay.setChecked(self.view_state.getOverlay())

            self.widget.GeometryButton.setChecked(stage == "Geometry")
            self.widget.MeshButton.setChecked(stage == "Mesh")

            construction = self.view_state.getShowConstruction()
            self.widget.Construction.setChecked(construction)
            self.setup_dimension_entries(stage, construction)
            self.setup_element_count(stage, construction)

            dim = self.view_state.getDimensionMode()
            idx = self.widget.Dimension.findText(dim)
            if idx >= 0:
                self.widget.Dimension.setCurrentIndex(idx)

            if self.view_state.getWireframe():
                self.widget.ViewMode.setCurrentIndex(0)
            else:
                self.widget.ViewMode.setCurrentIndex(1)
        finally:
            self._updating = False

    def setup_dimension_entries(self, stage, construction):
        """
        Grey out the dimensions that nothing would be drawn in.

        This is where the two kinds of element are told apart without a word of
        prose: a solid meshed with tetrahedra offers 3D and nothing else, and
        the 2D entry comes alive the moment the construction elements are taken
        in. What the greying leaves out is exactly what the stage leaves out.
        """
        counts = self._dimension_counts(construction)
        combo = self.widget.Dimension
        model = combo.model()
        for index in range(combo.count()):
            item = model.item(index) if hasattr(model, "item") else None
            if item is None:
                continue
            mode = combo.itemText(index)
            shown = self._shown_count(mode, construction)
            item.setEnabled(counts is None or shown > 0)
            combo.setItemData(
                index,
                self._dimension_tooltip(mode, shown, stage, construction),
                QtCore.Qt.ItemDataRole.ToolTipRole,
            )

    @staticmethod
    def _dimension_tooltip(mode, shown, stage, construction):
        if shown is None or mode == _ALL_DIMENSIONS:
            return None
        if stage == "Geometry":
            # Counted in solids and shells here, not in the elements a mesher
            # would fill them with, so say which of the two the number is.
            if shown > 0:
                return QtCore.QCoreApplication.translate(
                    "FEM_ViewPanel", "{} geometry elements"
                ).format(_thousands(shown))
            return QtCore.QCoreApplication.translate(
                "FEM_ViewPanel", "The geometry has nothing of this dimension"
            )
        if shown > 0:
            return QtCore.QCoreApplication.translate("FEM_ViewPanel", "{} elements").format(
                _thousands(shown)
            )
        if construction:
            return QtCore.QCoreApplication.translate(
                "FEM_ViewPanel", "The mesh has no elements of this dimension"
            )
        return QtCore.QCoreApplication.translate(
            "FEM_ViewPanel",
            "The analysis has no elements of this dimension. Show the construction "
            "elements to see the ones the mesher built the mesh from.",
        )

    def setup_element_count(self, stage, construction):
        """The count only means anything where there are elements to count."""
        shown = self._shown_count(self.view_state.getDimensionMode(), construction)
        if stage != "Mesh" or shown is None:
            self.widget.ElementCount.clear()
            return
        self.widget.ElementCount.setText(
            f"{_thousands(shown)} / {_thousands(self._counts['total'])}"
        )

    def slotActiveFemAnalysisUpdated(self, analysis):
        if analysis != self.active_analysis:
            # The stage to go back to belonged to the analysis being left.
            self._edit_obj = None
            self._edit_stage = None
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
        # An analysis that only places others has no mesh of its own, so an
        # import coming or going decides whether the Mesh stage is reachable.
        if property not in ("Shape", "Group", "Analysis", "SuppressedComponents"):
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
                return
            if _changes_imports(self.active_analysis, obj, property):
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
        """
        Put the view into the geometry stage for as long as geometry is picked,
        be it by a chain step or by a member holding references into the
        geometry. What is picked is geometry, and a mesh drawn over it only gets
        in the way, so the stage stays where it is put.
        """
        if self._edit_obj is not None or not self.view_state:
            return
        if _chain_preview_input(viewprovider) is None and not _picks_references(
            viewprovider, self.active_analysis
        ):
            return

        self._edit_obj = _vp_object(viewprovider)
        self._edit_stage = self.view_state.getActiveStage()
        self.view_state.setActiveStage("Geometry")
        self.setup_widgets()

    def slotResetEdit(self, viewprovider):
        if self._edit_obj is None or _vp_object(viewprovider) != self._edit_obj:
            return

        stage = self._edit_stage
        self._edit_obj = None
        self._edit_stage = None
        if self.view_state and stage:
            self.view_state.setActiveStage(stage)
        self.setup_widgets()

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
        Retire all clip rows, leaving the planes themselves alone.

        A row describes the plane of one analysis, so switching analysis or
        closing the document has to drop it instead of leaving a stale one
        behind. The planes stay where they are, ready for the rows that the
        next analysis, or the next opening of this panel, builds for them.
        """
        layout = self.widget.ClippingGroup.layout()
        for widget in self.clip_widgets():
            layout.removeWidget(widget)
            widget.shutdown()
        self.setup_clip_list()

    def setup_clip_list(self):
        """
        Make the rows read as a list, however many of them there are.

        With none the group is a frame around a single button, and a frame
        around nothing reads as a bug, so one dimmed line says it is a list
        that happens to be empty. With several the rows run together, each
        being three buttons much like the row above, so all but the first are
        parted by a rule.
        """
        widgets = self.clip_widgets()
        self.widget.ClipHint.setVisible(not widgets)
        for position, widget in enumerate(widgets):
            widget.set_separated(position > 0)

    def setup_clipping_planes(self):
        """
        Give every plane of the analysis a row, and no other.

        The planes are the truth here, not the rows: one may have been added
        from the toolbar, dropped by another row, or restored from a saved
        document, and all three arrive as the same list being different from
        the one on screen. Rows that are still wanted are kept rather than
        rebuilt, so a plane being dragged does not lose its open editor.
        """
        planes = (
            sorted(self.view_state.getClipPlanes(), key=_clip_sort_key) if self.view_state else []
        )
        layout = self.widget.ClippingGroup.layout()
        widgets = self.clip_widgets()

        # This runs on every change of the view state, and almost none of them
        # are about clipping, so the list that already matches is left alone
        # rather than taken apart and put back together the same.
        if [widget.name for widget in widgets] == planes:
            self.setup_clip_list()
            return

        rows = {widget.name: widget for widget in widgets}

        # Out of the layout first, all of them, so that re-inserting the ones
        # that stay cannot leave a row listed twice.
        for name, widget in rows.items():
            layout.removeWidget(widget)
            if name not in planes:
                widget.shutdown()

        # Rows go under the hint and above the add button, both of which the
        # group box holds whether there are planes or not.
        base = layout.indexOf(self.widget.ClipHint) + 1
        for position, name in enumerate(planes):
            widget = rows.get(name) or self._build_clip_widget(name)
            if widget is None:
                continue
            layout.insertWidget(base + position, widget)

        self.setup_clip_list()

    def _build_clip_widget(self, name):
        handle = FemGui.getClipPlane(self.active_analysis, name)
        return _clipWidget(handle, self.active_analysis) if handle else None

    def add_clipping_plane(self, value):
        """
        Add a plane, which grows its own row through the view state.

        The same call the toolbar command makes: nothing here builds a row by
        hand, so the two ways of adding a plane cannot drift apart.
        """
        if not self.active_analysis or not self.view_state:
            return
        try:
            FemGui.addClipPlane(self.active_analysis)
        except Exception as exc:
            FreeCAD.Console.PrintError(f"FEM view panel: cannot add clipping plane: {exc}\n")

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

    def construction_changed(self, value):
        if self._updating or not self.view_state:
            return
        construction = bool(value)
        self.view_state.beginUpdate()
        try:
            self.view_state.setShowConstruction(construction)
            # A dimension only the construction elements reach leaves an empty
            # view behind when they go, and the entry greys out along with them,
            # so it is no way back out either.
            if not self._dimension_available(self.view_state.getDimensionMode(), construction):
                self.view_state.setDimensionMode(_ALL_DIMENSIONS)
        finally:
            self.view_state.endUpdate()

    def _stage_button_clicked(self, stage, checked):
        """
        The two stage buttons switch rather than choose: pressing the lit one
        turns it off instead of handing the view to the other, leaving neither
        stage drawn. That is the way to get the preprocessing out of the way of
        the results.
        """
        if self._updating or not self.view_state:
            return
        self.view_state.beginUpdate()
        try:
            self.view_state.setActiveStage(stage if checked else _NO_STAGE)
            # The stages are counted in different things, so a dimension one of
            # them holds can be one the other has nothing in, and the entry
            # greys out under the very selection that is standing on it.
            if not self._dimension_available(self.view_state.getDimensionMode()):
                self.view_state.setDimensionMode(_ALL_DIMENSIONS)
        finally:
            self.view_state.endUpdate()

    def geometry_button_checked(self, value):
        self._stage_button_clicked("Geometry", value)

    def mesh_button_checked(self, value):
        self._stage_button_clicked("Mesh", value)


class MainWidget(QtGui.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = ViewSettings(self)
        self._tree_panel = GeometryTreePanel(self)
        self._explorer = self._tree_panel.explorer

        layout = QtGui.QVBoxLayout()
        layout.addWidget(self._settings)
        layout.addWidget(self._tree_panel)
        self.setLayout(layout)

    def shutdown(self):
        self._tree_panel.shutdown()
        self._settings.shutdown()


class Panel(QtGui.QDockWidget):

    def __init__(self, parent=None):
        super().__init__("FEM View", parent)
        self.setObjectName("FEMView")
        self._widget = MainWidget()
        self.setWidget(self._widget)
        # Docking and floating a panel that is only being put back where it
        # came from must not be mistaken for the user moving it.
        self.restoring = False
        self._settle_to = None
        # All owned by the panel, so a pending one dies with it
        self._stay_above_timer = QtCore.QTimer(self)
        self._stay_above_timer.setSingleShot(True)
        self._stay_above_timer.timeout.connect(self._deferred_stay_above)
        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_placement)
        self._settle_timer = QtCore.QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._settle)
        self.topLevelChanged.connect(self._top_level_changed)
        self.dockLocationChanged.connect(self._dock_location_changed)

    def _dock_location_changed(self, area):
        save_panel_placement(self)

    def moveEvent(self, event):
        super().moveEvent(event)
        self._placement_changed()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._placement_changed()

    def _placement_changed(self):
        """
        Note where the panel has got to, once it stops getting there.

        Dragging a floating panel around is the ordinary way of placing it, and
        Qt says nothing about it beyond the move itself: there is no signal for
        the panel having been put somewhere, so the moves are watched and the
        last one of a run wins. A drag is a move per pixel, which is why the
        record is not written on the spot.
        """
        if self.restoring:
            return
        self._save_timer.start(_PLACEMENT_QUIET_MS)

    def _save_placement(self):
        save_panel_placement(self)

    def settle_at(self, pos, size):
        """
        Insist on a placement once the window is up, then start listening again.

        A window is placed by the window manager as it is mapped, and plenty of
        them put a new one where they think best rather than where it was asked
        to go, which is how a panel that was left at the edge of the screen
        opens in the middle of it. Asking again afterwards is the ask that
        sticks. *pos* is None for a docked panel, which the main window places.
        """
        self._settle_to = (pos, size)
        self._settle_timer.start(0)

    def _settle(self):
        pos, size = self._settle_to or (None, None)
        self._settle_to = None
        if pos is not None and self.isFloating():
            self.resize(size)
            self.move(pos)
        self.restoring = False
        save_panel_placement(self)

    def _top_level_changed(self, floating):
        if not floating:
            save_panel_placement(self)
            return
        # Qt says so in the middle of the drag that tears the panel off, and
        # rebuilding the window right there would pull it out from under the
        # drag, so the flag waits until the mouse is let go.
        self._stay_above_timer.start(0)

    def _deferred_stay_above(self):
        if not self.isFloating():
            return
        if QtGui.QApplication.mouseButtons() != QtCore.Qt.MouseButton.NoButton:
            self._stay_above_timer.start(100)
            return
        # Where the user dropped it, kept across the window being rebuilt under
        # the new flags and put up again.
        pos, size = self.pos(), self.size()
        self.restoring = True
        self.stay_above_main_window()
        self.settle_at(pos, size)

    def stay_above_main_window(self):
        """
        Keep the floating panel over the main window.

        Wherever the window manager decorates a floated dock, Qt gives it the
        plain Window flag, and such a window sinks behind the main one the
        moment that is clicked. Tool is the same window tied to its parent: it
        stays over FreeCAD without climbing over other applications. Qt writes
        the flags afresh on every undock, so this has to run again each time.
        """
        tool = QtCore.Qt.WindowType.Tool
        flags = self.windowFlags()
        if (flags & tool) == tool:
            return

        # New flags mean a new native window, which loses both the placement
        # and the shown state.
        visible = self.isVisible()
        geometry = self.geometry()
        self.setWindowFlags(flags | tool)
        self.setGeometry(geometry)
        if visible:
            self.show()

    def shutdown(self):
        self._widget.shutdown()


def _panel_pref():
    return FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")


# Where the panel goes when it is docked rather than floating; the ints are
# the Qt::DockWidgetArea values the preference is written in.
_DOCK_AREAS = {
    1: QtCore.Qt.DockWidgetArea.LeftDockWidgetArea,
    2: QtCore.Qt.DockWidgetArea.RightDockWidgetArea,
    4: QtCore.Qt.DockWidgetArea.TopDockWidgetArea,
    8: QtCore.Qt.DockWidgetArea.BottomDockWidgetArea,
}
_DEFAULT_PANEL_SIZE = (360, 620)
# Gap the panel starts out at from the main window edges, a toolbar or so, to
# keep it clear of the toolbars and of whatever sits in the right dock area.
_DEFAULT_PANEL_MARGIN = 40
# How long a floating panel has to hold still before where it is counts as
# where the user put it.
_PLACEMENT_QUIET_MS = 200


def _enum_int(value):
    """Qt6 hands out enum objects where Qt5 handed out plain ints."""
    return int(value.value) if hasattr(value, "value") else int(value)


def _default_panel_geometry():
    """
    Where the panel opens before the user has moved it anywhere: a palette in
    the top right corner of the main window, over the 3D view rather than
    beside it.
    """
    width, height = _DEFAULT_PANEL_SIZE
    mw = FreeCADGui.getMainWindow()
    frame = mw.frameGeometry() if mw is not None else QtCore.QRect(0, 0, 1280, 800)
    height = min(height, max(240, frame.height() - 2 * _DEFAULT_PANEL_MARGIN))
    x = max(frame.left(), frame.right() - width - _DEFAULT_PANEL_MARGIN)
    y = frame.top() + _DEFAULT_PANEL_MARGIN
    return QtCore.QRect(x, y, width, height)


def save_panel_placement(dock):
    """Remember where the panel was left, so recreating it does not move it."""
    if dock.restoring:
        return

    pref = _panel_pref()
    floating = dock.isFloating()
    pref.SetBool("ViewPanelFloating", floating)
    pref.SetInt("ViewPanelWidth", dock.width())
    pref.SetInt("ViewPanelHeight", dock.height())
    if floating:
        # pos() counts the window decoration in, and move() puts the panel back
        # measured the same way. geometry() measures from inside the title bar,
        # so pairing the two would walk the panel up the screen a title bar at
        # a time, once per workbench switch.
        pref.SetInt("ViewPanelPosX", dock.pos().x())
        pref.SetInt("ViewPanelPosY", dock.pos().y())
        return
    mw = FreeCADGui.getMainWindow()
    if mw is not None:
        pref.SetInt("ViewPanelArea", _enum_int(mw.dockWidgetArea(dock)))


def restore_panel_placement(dock, visible):
    """
    Put the panel back where it was left, showing it if that is how it was left.

    The panel is destroyed on every workbench switch, so without this it would
    fall back into the dock area on each return to the FEM workbench. Showing
    belongs here rather than to the caller because a window is placed as it
    goes up, and only a placement applied after that is the one it keeps.
    """
    pref = _panel_pref()
    default = _default_panel_geometry()
    area = _DOCK_AREAS.get(pref.GetInt("ViewPanelArea", 2))
    floating = pref.GetBool("ViewPanelFloating", True)
    size = QtCore.QSize(
        pref.GetInt("ViewPanelWidth", default.width()),
        pref.GetInt("ViewPanelHeight", default.height()),
    )
    pos = QtCore.QPoint(
        pref.GetInt("ViewPanelPosX", default.x()),
        pref.GetInt("ViewPanelPosY", default.y()),
    )

    dock.restoring = True
    mw = FreeCADGui.getMainWindow()
    if mw is not None:
        mw.addDockWidget(area or QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock)
    if floating:
        dock.setFloating(True)
        # Straight away rather than over the deferred route: nothing is being
        # dragged here, and the panel is still to be shown, so the rebuilt
        # window costs no flicker.
        dock.stay_above_main_window()
        dock.resize(size)
        dock.move(pos)
    dock.setVisible(visible)
    dock.settle_at(pos if floating else None, size)


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
    restore_panel_placement(__dock, _panel_pref().GetBool("ShowViewPanel", True))


def unsetup_visualization_panel():
    """Tear down the panel when leaving the FEM workbench (prototype behaviour)."""
    global __dock
    if __dock is None:
        return

    _panel_pref().SetBool("ShowViewPanel", __dock.isVisible())
    save_panel_placement(__dock)
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
    if visible:
        # Showing puts the window up afresh, which is another chance for the
        # window manager to place it somewhere of its own choosing, so it goes
        # up the same way it does on a workbench switch.
        restore_panel_placement(__dock, True)
        __dock.raise_()
    else:
        save_panel_placement(__dock)
        __dock.setVisible(False)
    _panel_pref().SetBool("ShowViewPanel", visible)
