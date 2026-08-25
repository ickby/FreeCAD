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

from femtaskpanels import task_geometry

from . import view_base_femobject


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

    def getDisplayModes(self, obj):
        return ["Group", "Surface", "Wireframe", "Hidden"]

    def setDisplayMode(self, mode):
        if mode == "Group":
            return "Group"
        if mode == "Hidden":
            return "Hidden"
        return "Default"

    def dumps(self):
        return None

    def loads(self, state):
        return None


class VPGeometryImport(view_base_femobject.VPBaseFemObject):
    """
    View provider for GeometryImport. Rendering is handled by
    ViewProviderFemGeometry (C++ / ViewProviderFemGeometryPython).
    """

    def __init__(self, vobj):
        super().__init__(vobj)

    def getIcon(self):
        return ":/icons/fem-post-geo-box.svg"

    def getDisplayModes(self, obj):
        return ["Surface", "Wireframe", "Hidden"]

    def setDisplayMode(self, mode):
        if mode == "Hidden":
            return "Hidden"
        return "Default"

    def setEdit(self, vobj, mode=0):
        return super().setEdit(vobj, mode, task_geometry._ImportTaskPanel, hide_mesh=False)

    def dumps(self):
        return None

    def loads(self, state):
        return None
