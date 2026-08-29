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

"""Mixed solid, shell and beam analysis in one CalculiX deck."""

import FreeCAD
import Part

import Fem
import ObjectsFem

from . import manager
from .manager import get_meshname
from .manager import init_doc


def get_information():
    return {
        "name": "Mixed Solid Shell Beam",
        "meshtype": "mixed",
        "meshelement": "Hexa8, Quad4, Seg2",
        "constraints": ["fixed", "force"],
        "solvers": ["calculix"],
        "material": "solid",
        "equations": ["mechanical"],
    }


def get_explanation(header=""):
    return header + """

To run the example from Python console use:
from femexamples.mixed_solid_shell_beam import setup
setup()

A box, a plane and a line stand next to each other in one analysis. The box is
meshed with a volume element, the plane with a shell element and the line with a
beam element, so the mesh covers all three analysis dimensions at once.

The point of the example is the mesh export: the deck holds a C3D8, a S4 and a
B31 element side by side. Only the elements which make up the model are written,
the element faces and edges of the box are left out.

Each component is held on one side and loaded on the other, so a static run
produces a displacement field on the solid, the shell and the beam.

The mesh is as coarse as it can be, one element per component, so that the deck
stays readable. Do not read anything into the results.

"""


def _create_nodes(fem_mesh):
    """Nodes at the corners of the three geometry components."""
    points = [
        # box, 10 x 10 x 10 at the origin
        (0, 0, 0),
        (0, 10, 0),
        (10, 10, 0),
        (10, 0, 0),
        (0, 0, 10),
        (0, 10, 10),
        (10, 10, 10),
        (10, 0, 10),
        # plane, 10 x 10 in the xy plane at x = 30
        (30, 0, 0),
        (40, 0, 0),
        (40, 10, 0),
        (30, 10, 0),
        # line along x at y = z = 0
        (60, 0, 0),
        (70, 0, 0),
    ]
    for node_id, point in enumerate(points, start=1):
        fem_mesh.addNode(point[0], point[1], point[2], node_id)
    return True


def _create_elements(fem_mesh):
    """One element per component: a hexa8, a quad4 and a seg2."""
    fem_mesh.addVolume([1, 2, 3, 4, 5, 6, 7, 8], 1)
    fem_mesh.addFace([9, 10, 11, 12], 2)
    fem_mesh.addEdge([13, 14], 3)
    return True


def setup(doc=None, solvertype="calculix"):
    if doc is None:
        doc = init_doc()

    manager.add_explanation_obj(doc, get_explanation(manager.get_header(get_information())))

    # geometry, one component per analysis dimension
    box = doc.addObject("Part::Box", "Box")
    box.Length = 10
    box.Width = 10
    box.Height = 10

    plane = doc.addObject("Part::Feature", "Plane")
    plane.Shape = Part.makePlane(10, 10, FreeCAD.Vector(30, 0, 0))

    line = doc.addObject("Part::Feature", "Line")
    line.Shape = Part.makeLine(FreeCAD.Vector(60, 0, 0), FreeCAD.Vector(70, 0, 0))

    geom_obj = doc.addObject("Part::Compound", "Components")
    geom_obj.Links = [box, plane, line]
    doc.recompute()

    if FreeCAD.GuiUp:
        geom_obj.ViewObject.Document.activeView().viewAxonometric()
        geom_obj.ViewObject.Document.activeView().fitAll()

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")

    # solver
    if solvertype == "calculix":
        solver_obj = ObjectsFem.makeSolverCalculiX(doc, "SolverCalculiX")
    elif solvertype == "ccxtools":
        solver_obj = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiXCcxTools")
        solver_obj.WorkingDir = ""
    else:
        FreeCAD.Console.PrintWarning(
            "Unknown or unsupported solver type: {}. "
            "No solver object was created.\n".format(solvertype)
        )
        solver_obj = None
    if solver_obj is not None:
        solver_obj.AnalysisType = "static"
        solver_obj.GeometricalNonlinearity = False
        solver_obj.MatrixSolverType = "default"
        analysis.addObject(solver_obj)

    # material, one for all three components
    material_obj = ObjectsFem.makeMaterialSolid(doc, "Material")
    mat = material_obj.Material
    mat["Name"] = "Steel-Generic"
    mat["YoungsModulus"] = "200000 MPa"
    mat["PoissonRatio"] = "0.30"
    mat["Density"] = "7900 kg/m^3"
    material_obj.Material = mat
    analysis.addObject(material_obj)

    # element geometry, the shell and the beam need a cross section
    thickness_obj = ObjectsFem.makeElementGeometry2D(doc, 1.0, "ShellThickness")
    thickness_obj.References = [(plane, "Face1")]
    analysis.addObject(thickness_obj)

    beamsection_obj = ObjectsFem.makeElementGeometry1D(
        doc, sectiontype="Rectangular", width=2.0, height=4.0, name="BeamSection"
    )
    beamsection_obj.References = [(line, "Edge1")]
    analysis.addObject(beamsection_obj)

    # constraints: each component held on one side and loaded on the other
    con_fixed = ObjectsFem.makeConstraintFixed(doc, "ConstraintFixed")
    con_fixed.References = [(box, "Face1"), (plane, "Edge1"), (line, "Vertex1")]
    analysis.addObject(con_fixed)

    # Direction Edge5 of the box is vertical; Reversed sends the load to -Z.
    con_force_solid = ObjectsFem.makeConstraintForce(doc, "ConstraintForceSolid")
    con_force_solid.References = [(box, "Face2")]
    con_force_solid.Force = "10000 N"
    con_force_solid.Direction = (box, ["Edge5"])
    con_force_solid.Reversed = True
    analysis.addObject(con_force_solid)

    con_force_shell = ObjectsFem.makeConstraintForce(doc, "ConstraintForceShell")
    con_force_shell.References = [(plane, "Edge3")]
    con_force_shell.Force = "1000 N"
    con_force_shell.Direction = (box, ["Edge5"])
    con_force_shell.Reversed = True
    analysis.addObject(con_force_shell)

    con_force_beam = ObjectsFem.makeConstraintForce(doc, "ConstraintForceBeam")
    con_force_beam.References = [(line, "Vertex2")]
    con_force_beam.Force = "1000 N"
    con_force_beam.Direction = (box, ["Edge5"])
    con_force_beam.Reversed = True
    analysis.addObject(con_force_beam)

    # mesh
    fem_mesh = Fem.FemMesh()
    _create_nodes(fem_mesh)
    _create_elements(fem_mesh)
    femmesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, get_meshname()))[0]
    femmesh_obj.FemMesh = fem_mesh
    femmesh_obj.Shape = geom_obj
    femmesh_obj.SecondOrderLinear = False

    doc.recompute()
    return doc
