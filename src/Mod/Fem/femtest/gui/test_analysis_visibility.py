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

"""
Gui unit tests for what hiding an analysis, or anything in it, does.

An analysis draws its contents under itself, so switching it off should take
them out of the view without writing what each of them was set to, and a
document that was saved with something hidden should open with it still hidden.
"""

__title__ = "FEM analysis visibility Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import os
import tempfile
import unittest

import FreeCAD
import FreeCADGui
import Part

import ObjectsFem

# The scene graph checks hand out Coin nodes, which needs the pivy bindings
from pivy import coin

from femtools import importtools

from femtest.app.support_utils import fcc_print


def _draws(parent, child):
    """Whether a traversal of *parent* reaches the scene graph of *child*."""
    search = coin.SoSearchAction()
    search.setNode(child.ViewObject.RootNode)
    search.setInterest(coin.SoSearchAction.FIRST)
    search.setSearchingAll(True)
    search.apply(parent.ViewObject.RootNode)
    return search.getPath() is not None


class TestAnalysisVisibilityGui(unittest.TestCase):
    fcc_print("import TestAnalysisVisibilityGui")

    def setUp(self):
        self.document = FreeCAD.newDocument("AnalysisVisibility")

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def _analysis(self, name):
        """An analysis with a geometry group, a mesh group and a shape to show."""
        analysis = ObjectsFem.makeAnalysis(self.document, name)
        geometry = ObjectsFem.makeGeometryGroup(self.document, name + "Geometry")
        analysis.addObject(geometry)

        source = self.document.addObject("Part::Feature", name + "Part")
        source.Shape = Part.makeBox(10, 10, 10)
        step = ObjectsFem.makeGeometryImport(self.document)
        step.Import = [source]
        geometry.Group = [step]

        ObjectsFem.makeMeshShapeGroup(self.document, geometry=geometry, analysis=analysis)
        self.document.recompute()
        return analysis

    def _assembly(self, name):
        """An analysis that holds another one through an import."""
        source = self._analysis(name + "Source")
        assembly = ObjectsFem.makeAnalysis(self.document, name)
        placed = ObjectsFem.makeAnalysisImport(self.document, name + "Placed")
        placed.Analysis = source
        container = importtools.wire_import(assembly, placed)
        self.document.recompute()
        return assembly, container, placed

    def test_the_analysis_draws_what_it_holds(self):
        """Its members hang under it, which is what lets one switch hide them all."""
        analysis = self._analysis("Solo")
        for member in analysis.Group:
            self.assertTrue(
                _draws(analysis, member),
                f"{member.Name} is not drawn under the analysis",
            )

    def test_hiding_the_analysis_leaves_its_members_alone(self):
        """
        What each member was set to is the user's, not the container's.

        A group hides its members by writing every one of them, which loses
        that. This one has them in its scene graph and needs no such thing.
        """
        analysis = self._analysis("Untouched")
        mesh_group = analysis.Group[-1]
        mesh_group.ViewObject.Visibility = False
        before = {m.Name: m.ViewObject.Visibility for m in analysis.Group}

        analysis.ViewObject.Visibility = False
        analysis.ViewObject.Visibility = True

        after = {m.Name: m.ViewObject.Visibility for m in analysis.Group}
        self.assertEqual(before, after)

    def test_hiding_the_mesh_group_leaves_its_meshes_alone(self):
        """The same for the group the meshes sit in, which a stage switch hides."""
        analysis = self._analysis("Meshes")
        group = analysis.Group[-1]
        first = self.document.addObject("Fem::FemMeshObject", "MeshA")
        second = self.document.addObject("Fem::FemMeshObject", "MeshB")
        group.addObject(first)
        group.addObject(second)
        second.ViewObject.Visibility = False

        group.ViewObject.Visibility = False
        group.ViewObject.Visibility = True

        self.assertTrue(first.ViewObject.Visibility)
        self.assertFalse(second.ViewObject.Visibility)

    def test_the_import_container_draws_its_imports(self):
        """
        The plain group the imports sit in is given a scene graph of its own.

        Without one the imports would be drawn at the top of the document, next
        to the analysis rather than in it, and the analysis could not hide them.
        """
        assembly, container, placed = self._assembly("Assembly")

        self.assertTrue(container.ViewObject.hasExtension("FemGui::ViewProviderChildRootExtension"))
        self.assertTrue(_draws(container, placed))
        self.assertTrue(_draws(assembly, container))
        self.assertTrue(_draws(assembly, placed))

    def test_what_was_hidden_is_still_hidden_after_a_reload(self):
        """
        Reopening a document draws what the document says, not everything.

        Picking a display mode shows an object whatever it was set to, and an
        analysis picks one for each of its parts while the document loads.
        """
        assembly, container, placed = self._assembly("Saved")
        hidden = (assembly.Name, container.Name, placed.Name)
        for obj in (placed, container, assembly):
            obj.ViewObject.Visibility = False

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "visibility.FCStd")
            self.document.saveAs(path)
            FreeCAD.closeDocument(self.document.Name)
            self.document = FreeCAD.open(path)

            for name in hidden:
                self.assertFalse(
                    self.document.getObject(name).ViewObject.Visibility,
                    f"{name} came back visible",
                )

    def test_a_container_is_given_a_scene_graph_whenever_it_joins(self):
        """
        Joining the analysis is what hands a plain group its scene graph.

        Which covers a container that comes with a document written before
        there were any, since restoring the analysis fills its Group the same
        way as putting something in it does.
        """
        analysis = self._analysis("Late")
        container = self.document.addObject("App::DocumentObjectGroup", "Container")
        extension = "FemGui::ViewProviderChildRootExtension"
        self.assertFalse(container.ViewObject.hasExtension(extension))

        analysis.addObject(container)

        self.assertTrue(container.ViewObject.hasExtension(extension))
        self.assertTrue(_draws(analysis, container))
