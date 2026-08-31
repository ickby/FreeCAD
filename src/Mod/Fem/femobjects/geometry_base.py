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

from . import base_fempythonobject

_PropHelper = base_fempythonobject._PropHelper


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

    def __init__(self, obj):
        super().__init__(obj)

    def setup_properties(self, obj):
        for prop in self._get_properties():
            prop.add_to_object(obj)

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
            obj.Group[0].Base = None
            last = obj.Group[0]
            for child in obj.Group[1:]:
                child.Base = last
                last = child

    def execute(self, obj):
        obj.Shape = obj.Group[-1].Shape if obj.Group else Part.Shape()


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
            obj.Shape = base_shape
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
