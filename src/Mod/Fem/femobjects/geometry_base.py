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

__title__ = "FreeCAD FEM geometry objects"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import Part
from FreeCAD import Base

from . import base_fempythonobject

_PropHelper = base_fempythonobject._PropHelper


def assign_shape(obj, shape):
    """
    Write a geometry step's result, but only when it is a different shape.

    Everything downstream of an analysis geometry - the component cache, the
    dimensions, the classification the view colours by, the component claims of
    the mesh children - is derived from this Shape, and is rebuilt whenever it
    is written. A step is executed for anything at all that changes on it or on
    a member of its group, and most of that leaves the result identical, so
    passing the same shape on again would throw that work away for nothing.
    """
    current = obj.Shape
    if current.isNull() and shape.isNull():
        return
    if not current.isNull() and not shape.isNull() and current.isSame(shape):
        return
    obj.Shape = shape


# What a step publishes, plus the settings that say nothing about its shape.
# Everything else a step carries is an input the user edits, and editing one is
# the user asking for the result to follow. Naming the outputs rather than the
# inputs keeps a step that gains a setting working without a change here.
#
# Properties whose name starts with an underscore are excluded wholesale: they
# are FreeCAD's own bookkeeping, and some of them are written after a document
# has been restored, when the restore state that would otherwise excuse them is
# already gone. _ElementMapVersion is the one that matters here - taken for an
# edit, it has every step of every chain rebuild itself on the first recompute
# after a file is opened.
_NOT_AN_INPUT = frozenset(
    {
        "Shape",
        "Outdated",
        "DimensionOverride",
        "Placement",
        "Label",
        "Label2",
        "Visibility",
        "Proxy",
        "ExpressionEngine",
    }
)


def _is_input(prop, outputs=()):
    return prop not in _NOT_AN_INPUT and prop not in outputs and not prop.startswith("_")


def request_update(obj):
    """
    Ask a geometry step to follow its sources at the next recompute.

    A step reached by a change from outside the analysis keeps the shape it has,
    because rebuilding costs the chain below it and every mesh made against the
    result. This is how the update command says that the user has now asked for
    exactly that. The recompute has to be enforced: nothing about the step
    itself changed, so the document would otherwise see no reason to run it.
    """
    proxy = getattr(obj, "Proxy", None)
    if proxy is not None:
        proxy._rebuild_requested = True
    obj.enforceRecompute()


def should_rebuild(proxy, obj):
    """
    Whether a step has to do its work again, or may pass on what it has.

    A step is executed for anything at all that happens to a dependency, and
    almost none of it is a new input: the shape it was built from is the same
    one, and its own settings are untouched. Doing the work anyway costs a full
    boolean per step on every recompute of the CAD model, so a step asks here
    first. Three things say yes - nothing has been built yet, the user changed
    a setting or asked for an update, or the step before published a new shape.

    What the step before published is compared by identity, not by geometry:
    the same shape handed on again is the same TopoDS_Shape, and a rebuilt one
    is never the same object even when it comes back geometrically identical.
    That is a pointer comparison, and it is the question actually being asked -
    "is my input the one I built from" - where comparing the geometry would
    cost about as much as rebuilding and still answer something else.

    Identity is also the only comparison that survives a restore. The revision
    counter FemGeometry keeps would be the obvious thing to compare, but it is
    raised while a document is being restored and the order in which objects
    are restored is not fixed, so a step can record a count that its base has
    already moved past - and then rebuild on the first recompute after opening
    a file, taking every mesh made against the old shape with it. A shape, by
    contrast, does not change while a document is being read.
    """
    if obj.Shape.isNull():
        return True
    if getattr(proxy, "_rebuild_requested", False):
        return True
    return not _same_shape(_base_shape(obj), getattr(proxy, "_built_from", None))


def note_built(proxy, obj):
    """Record what a step has just been built against. Follows every execute."""
    proxy._built_from = _base_shape(obj)
    proxy._rebuild_requested = False


def _base_shape(obj):
    base = obj.Base
    return base.Shape if base else None


def _same_shape(one, other):
    """Whether two step inputs are the same shape, either of them possibly absent."""
    if one is None or other is None:
        return one is None and other is None
    if one.isNull() or other.isNull():
        return one.isNull() and other.isNull()
    return one.isSame(other)


def _get_features_without_compounds(shape):
    result = shape.Solids
    result += shape.getChildShapes("Shell", "Solids")
    result += shape.getChildShapes("Face", "Shell")
    result += shape.getChildShapes("Wire", "Face")
    result += shape.getChildShapes("Edge", "Wire")
    result += shape.getChildShapes("Vertex", "Edge")
    return result


class GeometryBase(base_fempythonobject.BaseFemPythonObject):
    """The GeometryBase object"""

    Type = "Fem::GeometryBase"

    # Properties a step writes itself, as results of its own execute rather
    # than as settings anyone made. A step has to say which its own are: they
    # are ordinary properties, indistinguishable from a setting from outside,
    # and taken for one they leave the step asking to be rebuilt every time it
    # is built - which rebuilds the chain and clears the meshes on the next
    # recompute that comes along, whatever brought it.
    OUTPUTS = ()

    def __init__(self, obj):
        super().__init__(obj)

    def setup_properties(self, obj):
        for prop in self._get_properties():
            prop.add_to_object(obj)

    def onChanged(self, obj, prop):
        """
        Note that the user has edited what this step is built from.

        A step cannot tell from execute() alone why it was reached, and the two
        reasons ask for opposite answers: a source that recomputed outside the
        analysis is followed only when the user says so, while a setting the
        user just changed is that saying. This is the only place the difference
        is visible, so it is recorded here and read there.

        The restore pass writes every saved property and must not be mistaken
        for an edit - a document that is being opened has asked for nothing.
        """
        if _is_input(prop, self.OUTPUTS) and "Restore" not in obj.State:
            self._rebuild_requested = True

    def onDocumentRestored(self, obj):
        """
        Give an older document the properties its step has since gained.

        A property is written to the file only if it was there when the file
        was saved, and a step restored without one throws the moment its
        execute reaches for it - leaving the step invalid and its result the
        stale shape from the last save, which looks like the tool quietly
        ignoring every setting. Adding what is missing on the way in is what
        lets a step gain a setting without breaking the documents that were
        made before it had one.
        """
        for prop in self._get_properties():
            try:
                obj.getPropertyByName(prop.name)
            except Base.PropertyError:
                prop.add_to_object(obj)

        # The shape saved with this step is the one built from the shape saved
        # beside it, so what its base holds now is what it was built from.
        # Learning that here and not at the first execute matters: a step that
        # waited to be told would have no way of telling a base that has since
        # been rebuilt from one that never moved, and would skip the work that
        # a deliberate update had just asked it for.
        self._built_from = _base_shape(obj)
        self._rebuild_requested = False

    def _get_properties(self):
        return [
            _PropHelper(
                type="App::PropertyLink",
                name="Base",
                group="Geometry",
                doc="The base geometry operation preceding this one",
                value=None,
            )
        ]


class GeometryGroup(base_fempythonobject.BaseFemPythonObject):
    """Group that owns the analysis geometry chain and exposes Shape."""

    Type = "Fem::GeometryGroup"

    def __init__(self, obj):
        super().__init__(obj)
        obj.addExtension("App::GeoFeatureGroupExtensionPython")
        self._keep_visibility_out_of_the_recompute(obj)

    def onDocumentRestored(self, obj):
        self._keep_visibility_out_of_the_recompute(obj)

        # A saved group holds the result of its last step, saved beside it -
        # the same geometry written to the file twice, and restored as two
        # shapes that are equal and not identical. Taking note of the one the
        # step holds is what stops the first recompute after opening a file
        # from reading that difference as a new result, republishing it, and
        # clearing every mesh made against a geometry that never changed.
        self._published = self._last_shape(obj)

    @staticmethod
    def _keep_visibility_out_of_the_recompute(obj):
        # Showing or hiding a member says nothing about the shape, and the group
        # extension would otherwise touch us for it. What does change the shape
        # reaches us through the Group link like any other dependency. The status
        # of a transient property is written to the file, so a document saved
        # before this was set brings the old one back with it.
        obj.setPropertyStatus("_GroupTouched", "Output")

    def onChanged(self, obj, prop):
        if prop == "Group":
            if len(obj.Group) == 0:
                return
            if not hasattr(obj.Group[0], "Base"):
                return

            # Only where the order actually differs. Writing a link touches the
            # step that receives it whether or not the value changed, and a step
            # reads a touch of its own input as the user having edited it - so
            # rewiring a chain that is already wired that way, which is what a
            # restored document does, would have every step rebuild itself on
            # the first recompute after opening the file.
            last = None
            for child in obj.Group:
                if child.Base != last:
                    child.Base = last
                last = child

    @staticmethod
    def _last_shape(obj):
        """What the chain ends on, which is what this group publishes."""
        return obj.Group[-1].Shape if obj.Group else Part.Shape()

    def execute(self, obj):
        # Published by identity, not by content: the last step hands on the very
        # shape it holds, so the same object arriving again is the same result
        # and writing it a second time would be seen downstream as a geometry
        # that changed - which costs every mesh made against it.
        last = self._last_shape(obj)
        if not _same_shape(last, getattr(self, "_published", None)):
            assign_shape(obj, last)
            self._published = last

        # The mark is raised by the step that decided it, and a step is only
        # ever seen inside the chain. What the tree, the view panel and the
        # update command look at is the analysis geometry as a whole, so the
        # union is drawn here. Nothing has to be scheduled for it: the Group
        # link makes this group a dependent of every member, so a member that
        # has just marked itself brings us here in the same recompute.
        obj.Outdated = any(getattr(member, "Outdated", False) for member in obj.Group)


class GeometryImport(GeometryBase):
    """Import Part/Sketch geometry into the analysis geometry chain."""

    Type = "Fem::GeometryImport"

    def __init__(self, obj):
        super().__init__(obj)
        self.setup_properties(obj)

    def _get_properties(self):
        prop = [
            _PropHelper(
                type="App::PropertyLinkListGlobal",
                name="Import",
                group="Geometry",
                doc="The imported geometries",
                value=None,
            ),
            _PropHelper(
                type="App::PropertyEnumeration",
                name="Embed",
                group="Geometry",
                doc="Keep imported geometry separated, or embed it",
                value=["Seperated", "Embed import", "Embed all"],
            ),
        ]
        return super()._get_properties() + prop

    def execute(self, obj):
        """
        Read the sources again, or note that they have moved without us.

        This step is the only door through which the world outside the analysis
        enters it, so it is where the decision belongs. Following a change to
        the CAD model costs the whole chain of booleans below and every mesh
        made against the result, and nobody asked for either, so what arrives
        from outside is recorded and left. Keeping the Shape is what protects
        the meshes: FemGeometry raises its revision when a new shape was
        written, and the mesh group throws away what was meshed against the old
        one, so a step that writes nothing costs nothing anywhere.

        An edit to this step's own settings, and an update the user asked for,
        both arrive as a rebuild request and are acted on at once - the user is
        waiting for the result in both cases. A step that has nothing yet
        builds too; a chain that has never run is not born out of date.
        """
        if not should_rebuild(self, obj):
            obj.Outdated = True
            return

        self._rebuild(obj)
        obj.Outdated = False
        note_built(self, obj)

    def _rebuild(self, obj):
        import_shapes = []
        for link in obj.Import:
            if link.isDerivedFrom("Sketcher::SketchObject"):
                if link.MakeInternals:
                    import_shapes += link.InternalShape.Faces
                else:
                    import_shapes += link.Shape.Wires
            elif link.isDerivedFrom("App::GeoFeature"):
                import_shapes += _get_features_without_compounds(link.getPropertyOfGeometry())

        base_obj = obj.Base
        base_shape = base_obj.Shape if base_obj else Part.Shape()

        if not import_shapes:
            assign_shape(obj, base_shape)
            return

        # Cluster shapes that touch so each connected component can be
        # fused independently. A lone shape is its own cluster.
        clusters = [[import_shapes.pop(0)]]
        while import_shapes:
            grown = True
            while grown:
                grown = False
                for candidate in import_shapes[:]:
                    if any(candidate.distToShape(member)[0] < 1e-6 for member in clusters[-1]):
                        clusters[-1].append(candidate)
                        import_shapes.remove(candidate)
                        grown = True
            if import_shapes:
                clusters.append([import_shapes.pop(0)])

        ordered_shapes = [item for sublist in clusters for item in sublist]

        if obj.Embed == "Seperated":
            if not base_shape.isNull():
                obj.Shape = Part.makeCompound([base_shape] + ordered_shapes)
            else:
                obj.Shape = Part.makeCompound(ordered_shapes)

        elif obj.Embed == "Embed import":
            match len(ordered_shapes):
                case 1:
                    include_shapes = ordered_shapes
                case _:
                    include_shapes = []
                    for cluster in clusters:
                        if len(cluster) == 1:
                            include_shapes.append(cluster[0])
                        else:
                            include_shapes.append(cluster[0].generalFuse(cluster[1:])[0])

            if not base_shape.isNull():
                obj.Shape = Part.makeCompound([base_shape] + include_shapes)
            else:
                if len(include_shapes) == 1:
                    obj.Shape = include_shapes[0]
                else:
                    obj.Shape = Part.makeCompound(include_shapes)

        else:  # Embed all
            if not base_shape.isNull():
                obj.Shape = base_shape.generalFuse(ordered_shapes)[0]
            else:
                match len(ordered_shapes):
                    case 1:
                        obj.Shape = ordered_shapes[0]
                    case _:
                        obj.Shape = ordered_shapes[0].generalFuse(ordered_shapes[1:])[0]
