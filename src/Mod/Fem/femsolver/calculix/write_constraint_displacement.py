# ***************************************************************************
# *   Copyright (c) 2021 Bernd Hahnebach <bernd@bimstatik.org>              *
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

__title__ = "FreeCAD FEM calculix constraint displacement"
__author__ = "Bernd Hahnebach"
__url__ = "https://www.freecad.org"

import FreeCAD


def get_analysis_types():
    return "all"  # write for all analysis types


def get_sets_name():
    return "constraints_displacement_node_sets"


def get_constraint_title():
    return "Displacement constraint applied"


def get_before_write_meshdata_constraint():
    return ""


def get_after_write_meshdata_constraint():
    return ""


def get_before_write_constraint():
    return ""


def get_after_write_constraint():
    return "\n"


def _nodes_are_split(femobj):
    """True when the mesh data getter separated solid from shell/beam nodes.

    It only does so where solid elements meet shell or beam elements, which is
    the case a constraint has to prescribe different degrees of freedom for.
    """
    return "NodesSolid" in femobj


def write_meshdata_constraint(f, femobj, disp_obj, ccxwriter):
    if _nodes_are_split(femobj):
        if femobj.get("NodesSolid"):
            f.write(f"*NSET,NSET={disp_obj.Name}Solid\n")
            for n in femobj["NodesSolid"]:
                f.write(f"{n},\n")
        if femobj.get("NodesFaceEdge"):
            f.write(f"*NSET,NSET={disp_obj.Name}FaceEdge\n")
            for n in femobj["NodesFaceEdge"]:
                f.write(f"{n},\n")
    else:
        f.write(f"*NSET,NSET={disp_obj.Name}\n")
        for n in femobj["Nodes"]:
            f.write(f"{n},\n")


def _write_disp_dofs(f, nset, disp_obj, include_rotations):
    if not disp_obj.xFree:
        f.write("{},1,1,{:.13G}\n".format(nset, disp_obj.xDisplacement.getValueAs("mm").Value))
    if not disp_obj.yFree:
        f.write("{},2,2,{:.13G}\n".format(nset, disp_obj.yDisplacement.getValueAs("mm").Value))
    if not disp_obj.zFree:
        f.write("{},3,3,{:.13G}\n".format(nset, disp_obj.zDisplacement.getValueAs("mm").Value))
    if include_rotations:
        if not disp_obj.rotxFree:
            f.write("{},4,4,{:.13G}\n".format(nset, disp_obj.xRotation.getValueAs("rad").Value))
        if not disp_obj.rotyFree:
            f.write("{},5,5,{:.13G}\n".format(nset, disp_obj.yRotation.getValueAs("rad").Value))
        if not disp_obj.rotzFree:
            f.write("{},6,6,{:.13G}\n".format(nset, disp_obj.zRotation.getValueAs("rad").Value))


def write_constraint(f, femobj, disp_obj, ccxwriter):

    # floats read from ccx should use {:.13G}, see comment in writer module

    if disp_obj.EnableAmplitude:
        f.write(f"*BOUNDARY, AMPLITUDE={disp_obj.Name}\n")
    else:
        f.write("*BOUNDARY\n")

    has_shell_or_beam = bool(
        ccxwriter.member.geos_beamsection or ccxwriter.member.geos_shellthickness
    )
    if _nodes_are_split(femobj):
        if femobj.get("NodesSolid"):
            _write_disp_dofs(f, f"{disp_obj.Name}Solid", disp_obj, include_rotations=False)
        if femobj.get("NodesFaceEdge"):
            _write_disp_dofs(
                f, f"{disp_obj.Name}FaceEdge", disp_obj, include_rotations=has_shell_or_beam
            )
    else:
        _write_disp_dofs(f, disp_obj.Name, disp_obj, include_rotations=has_shell_or_beam)
