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
Gui unit tests for the FEM colour palette.

The palette is the only colour source for geometry and mesh colouring. It is
not stored in the document, so a later FEM setting can replace it.
"""

__title__ = "FEM colour palette Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import os
import tempfile
import unittest

import FreeCAD
import FreeCADGui
import FemGui
import Part

import ObjectsFem

from femtools import geometryupdate

from femtest.app.support_utils import fcc_print
from femtest.gui.test_geometry_marks import face_material, node_colors


def _rgb(color):
    return tuple(round(channel, 3) for channel in color[:3])


class TestPaletteGui(unittest.TestCase):
    fcc_print("import TestPaletteGui")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)
        self.box = self.document.addObject("Part::Feature", "Box")
        self.box.Shape = Part.makeCompound(
            [
                Part.makeBox(10, 10, 10),
                Part.makeBox(10, 10, 10, FreeCAD.Vector(20, 0, 0)),
            ]
        )
        self.analysis = ObjectsFem.makeAnalysis(self.document)
        self.group = ObjectsFem.makeGeometryGroup(self.document)
        imp = ObjectsFem.makeGeometryImport(self.document)
        imp.Import = [self.box]
        self.group.Group = [imp]
        self.analysis.addObject(self.group)
        self.document.recompute()
        FemGui.setActiveAnalysis(self.analysis)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestPaletteGui tests {2}\n{0}".format(100 * "*", 10 * "*", 52 * "*")
        )

    def test_the_palette_has_thirty_two_distinct_colours(self):
        self.assertFalse(hasattr(self.group.ViewObject, "Colors"))

        state = FemGui.getAnalysisViewState(self.analysis)
        state.setColorMode("Component")
        cats = sorted(state.getCategories(), key=lambda cat: cat["key"])
        self.assertEqual([cat["key"] for cat in cats], ["Component1", "Component2"])
        first = _rgb(cats[0]["color"])
        second = _rgb(cats[1]["color"])
        self.assertNotEqual(first, second)
        self.assertEqual(first, (0.949, 0.459, 0.442))
        self.assertEqual(second, (0.090, 0.515, 0.649))

    def test_the_two_solids_are_drawn_in_the_first_two_palette_colours(self):
        """
        Component colouring hands out the palette in component order, so the
        first box is red and the second deep cyan. That is what a later
        setting would recolour by replacing the palette.
        """
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setColorMode("Component")
        self.group.ViewObject.Visibility = True
        FreeCADGui.updateGui()

        material = face_material(self.group.ViewObject)
        drawn = {_rgb(color) for color in node_colors(material)}
        self.assertIn((0.949, 0.459, 0.442), drawn)
        self.assertIn((0.090, 0.515, 0.649), drawn)

    def test_a_component_of_many_faces_is_drawn_in_one_colour(self):
        """
        What separates colouring by component from colouring by element: a
        shell is one component made of as many toplevel faces as it has faces,
        and the point of the mode is that the user sees the one part it is.
        """
        self.box.Shape = Part.makeShell(Part.makeBox(10, 10, 10).Faces)
        self.document.recompute()
        # An analysis geometry follows the model it was built from only when it
        # is told to, so what this test is about - one component of many faces -
        # exists once the update has been asked for.
        geometryupdate.update_group(self.group)
        state = FemGui.getAnalysisViewState(self.analysis)
        self.group.ViewObject.Visibility = True

        state.setColorMode("Subelement")
        FreeCADGui.updateGui()
        per_element = {_rgb(c) for c in node_colors(face_material(self.group.ViewObject))}

        state.setColorMode("Component")
        FreeCADGui.updateGui()
        cats = state.getCategories()
        self.assertEqual([cat["key"] for cat in cats], ["Component1"])
        per_component = {_rgb(c) for c in node_colors(face_material(self.group.ViewObject))}

        self.assertEqual(per_component, {_rgb(cats[0]["color"])})
        self.assertGreater(
            len(per_element),
            1,
            "colouring by element still tells the faces of the shell apart",
        )

    def test_colours_are_not_stored_in_the_document(self):
        """
        A palette change later has to recolour existing documents, so nothing
        of the palette may be written into the file.
        """
        state = FemGui.getAnalysisViewState(self.analysis)
        state.setColorMode("Component")
        self.document.recompute()

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "palette.FCStd")
            self.document.saveAs(path)
            xml = _archive_xml(path)

        self.assertNotIn("0.949", xml)
        self.assertNotIn("0.459", xml)
        self.assertNotIn(">Colors<", xml)
        self.assertFalse(hasattr(self.group.ViewObject, "Colors"))


def _archive_xml(path):
    """Document.xml and GuiDocument.xml of an FCStd, where properties are written."""
    import zipfile

    chunks = []
    with zipfile.ZipFile(path) as archive:
        for name in ("Document.xml", "GuiDocument.xml"):
            if name in archive.namelist():
                with archive.open(name) as handle:
                    chunks.append(handle.read().decode("utf-8"))
    return "\n".join(chunks)
