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

"""Gui unit tests for picking geometry references in an analysis: they go onto
the geometry the analysis builds, and nowhere else."""

__title__ = "FEM reference selection Gui tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD
import FreeCADGui
import FemGui
import Part

from PySide import QtGui

import ObjectsFem

from femguiutils import selection_widgets

from femtest.app.support_utils import fcc_print


class _NoMessageBox:
    """Answer the message boxes of a picking widget instead of blocking on them."""

    def __init__(self):
        self.messages = []

    def __enter__(self):
        self._critical = QtGui.QMessageBox.critical
        QtGui.QMessageBox.critical = lambda parent, title, text, *a, **kw: self.messages.append(
            text
        )
        return self

    def __exit__(self, *args):
        QtGui.QMessageBox.critical = self._critical


class TestReferenceSelectionGui(unittest.TestCase):
    fcc_print("import TestReferenceSelectionGui")

    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)
        self.source = self.document.addObject("Part::Feature", "Source")
        self.source.Shape = Part.makeCompound(
            [
                Part.makeBox(20, 10, 10),
                Part.makeBox(10, 10, 10, FreeCAD.Vector(30, 0, 0)),
            ]
        )
        self.analysis = ObjectsFem.makeAnalysis(self.document)
        self.group = ObjectsFem.makeGeometryGroup(self.document)
        imp = ObjectsFem.makeGeometryImport(self.document)
        imp.Import = [self.source]
        self.group.Group = [imp]
        self.analysis.addObject(self.group)
        self.document.recompute()
        FemGui.setActiveAnalysis(self.analysis)
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.finish_selection()
        self.widgets = []
        FreeCADGui.Selection.clearSelection()
        if FreeCADGui.ActiveDocument and FreeCADGui.ActiveDocument.getInEdit():
            FreeCADGui.ActiveDocument.resetEdit()
        FreeCAD.closeDocument(self.document.Name)

    # -- helpers ------------------------------------------------------------

    def _picker(self, types, solid=False):
        """A reference picker listening to the 3D view, as a panel puts it up."""
        widget = selection_widgets.GeometryElementsSelection([], types, False, True)
        self.widgets.append(widget)
        if solid:
            widget.rb_solid.setChecked(True)
        widget.add_references()
        return widget

    def _pick(self, obj, sub):
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.document.Name, obj.Name, sub)

    def _references(self, widget):
        return [(ref.Name, element) for ref, element in widget.references]

    def _open_constraint(self, constraint):
        """Open the panel of a constraint and press its reference add button."""
        FreeCADGui.ActiveDocument.setEdit(constraint.Name)
        buttons = FreeCADGui.getMainWindow().findChildren(QtGui.QToolButton, "btnAdd")
        self.assertTrue(buttons, "the constraint panel offers a button to add references")
        buttons[-1].setChecked(True)

    # -- picking with the Python widget --------------------------------------

    def test_a_pick_on_the_analysis_geometry_is_taken(self):
        widget = self._picker(["Face"])
        self._pick(self.group, "Face3")
        self.assertEqual(self._references(widget), [(self.group.Name, "Face3")])

    def test_a_face_pick_reaches_the_solid_it_bounds(self):
        """Solid mode, which materials and body loads start in."""
        widget = self._picker(["Solid", "Face"], solid=True)
        self._pick(self.group, "Face3")
        self.assertEqual(self._references(widget), [(self.group.Name, "Solid1")])

    def test_a_pick_beside_the_analysis_geometry_is_refused(self):
        """
        The part the geometry was built from is still in the document and still
        pickable. Its elements are numbered differently from the ones the mesh
        is made of, so a reference on it would land somewhere else.
        """
        widget = self._picker(["Face"])
        with _NoMessageBox() as boxes:
            self._pick(self.source, "Face1")
            self.assertEqual(widget.references, [])
            self.assertTrue(boxes.messages, "the refusal has to be told")
            self.assertIn(self.group.Label, boxes.messages[0])

    def test_without_a_geometry_a_part_feature_is_taken(self):
        """Analyses of older documents reference their part features directly."""
        legacy = ObjectsFem.makeAnalysis(self.document, "Legacy")
        self.document.recompute()
        FemGui.setActiveAnalysis(legacy)

        widget = self._picker(["Face"])
        self._pick(self.source, "Face1")
        self.assertEqual(self._references(widget), [(self.source.Name, "Face1")])

    # -- picking with a C++ constraint panel ---------------------------------

    def test_a_constraint_panel_takes_the_analysis_geometry(self):
        """
        The panels rejected everything that was not a Part::Feature, which the
        geometry of an analysis is not, with "Selected object is not a part".
        """
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        self.document.recompute()

        self._open_constraint(constraint)
        self._pick(self.group, "Face3")

        self.assertEqual(constraint.References, [(self.group, ("Face3",))])

    def test_an_open_constraint_marks_its_references_on_the_geometry(self):
        """
        The geometry draws its own shape and carries none of the per element
        colours a part feature would be highlighted through, so the references
        are marked on it instead.
        """
        constraint = ObjectsFem.makeConstraintFixed(self.document)
        self.analysis.addObject(constraint)
        constraint.References = [(self.group, "Face3")]
        self.document.recompute()
        role = f"constraint:{constraint.Name}"

        self.assertEqual(self.group.ViewObject.getElementHighlight(role), [])
        FreeCADGui.ActiveDocument.setEdit(constraint.Name)
        try:
            self.assertEqual(self.group.ViewObject.getElementHighlight(role), ["Face3"])
        finally:
            FreeCADGui.ActiveDocument.resetEdit()
        self.assertEqual(
            self.group.ViewObject.getElementHighlight(role),
            [],
            "a closed panel leaves no marks behind",
        )

    # -- what the view shows while references are picked ---------------------

    def test_editing_a_member_puts_the_view_into_the_geometry_stage(self):
        """
        References are picked on geometry, so a mesh drawn over it would leave
        nothing to pick. Same rule as for an edited chain step.
        """
        from femguiutils import view_panel

        view_panel.setup_visualization_panel()
        dock = FreeCADGui.getMainWindow().findChild(QtGui.QDockWidget, "FEMView")
        self.assertIsNotNone(dock, "the FEM workbench puts up the view panel")
        settings = dock.widget()._settings

        ObjectsFem.makeMeshShapeGroup(self.document, geometry=self.group, analysis=self.analysis)
        self.document.recompute()
        settings.setup_analysis()

        state = FemGui.getAnalysisViewState(self.analysis)
        state.setActiveStage("Mesh")

        material = ObjectsFem.makeMaterialSolid(self.document)
        self.analysis.addObject(material)
        self.document.recompute()

        settings.slotInEdit(material.ViewObject)
        try:
            self.assertEqual(state.getActiveStage(), "Geometry")
        finally:
            settings.slotResetEdit(material.ViewObject)
        self.assertEqual(state.getActiveStage(), "Mesh")
