# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Stefan Tröger <stefantroeger@gmx.net>
# SPDX-FileNotice: Part of the FreeCAD project.

################################################################################
#                                                                              #
#   FreeCAD is free software: you can redistribute it and/or modify            #
#   it under the terms of the GNU Lesser General Public License as             #
#   published by the Free Software Foundation, either version 2.1              #
#   of the License, or (at your option) any later version.                     #
#                                                                              #
#   FreeCAD is distributed in the hope that it will be useful,                 #
#   but WITHOUT ANY WARRANTY; without even the implied warranty                #
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                    #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with FreeCAD. If not, see https://www.gnu.org/licenses       #
#                                                                              #
################################################################################

__title__ = "Netgen FEM unit tests"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import os
import unittest

import FreeCAD
import Part

import ObjectsFem
from femmesh import netgentools
from .support_utils import fcc_print


class TestNetgenBase(unittest.TestCase):

    # ********************************************************************************************
    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    # ********************************************************************************************
    def netgen_available(self):
        # Netgen meshes in an interpreter of its own, it is unusable when that
        # interpreter cannot import it
        return "Netgen:" in netgentools.NetgenTools.version()

    def netgen_mesh_object(self, shape, name="Mesh", max_size=10):
        part = self.document.addObject("Part::Feature", name + "Geometry")
        part.Shape = shape
        mesh_obj = ObjectsFem.makeMeshNetgen(self.document, name)
        mesh_obj.Shape = part
        mesh_obj.MaxSize = max_size
        # the step enumeration starts at geometry analysis, which builds no mesh
        mesh_obj.EndStep = "OptimizeVolume"
        self.document.recompute()
        return part, mesh_obj

    def run_netgen(self, mesh_obj):
        tool = netgentools.NetgenTools(mesh_obj)
        tool.run(blocking=True)
        self.assertTrue(
            os.path.exists(tool.result_file),
            f"Netgen produced no result for {mesh_obj.Name}",
        )
        # the finished signal of the process needs an event loop, which a test
        # does not run, so the result is picked up here instead
        mesh_obj.FemMesh = tool.fem_mesh_from_result()
        return mesh_obj.FemMesh


# ************************************************************************************************
# ************************************************************************************************
class TestNetgenEntityOrder(TestNetgenBase):
    fcc_print("import TestNetgenEntityOrder")

    # ********************************************************************************************
    def test_00print(self):
        # since method name starts with 00 this will be run first
        # this test just prints a line with stars

        fcc_print(
            "\n{0}\n{1} run FEM TestNetgenEntityOrder tests {2}\n{0}".format(
                100 * "*", 10 * "*", 53 * "*"
            )
        )

    # ********************************************************************************************
    def entity_order_shapes(self):
        # shapes whose entity numbering FreeCAD and Netgen disagree about, plus the
        # single dimension shape they used to agree about

        box = Part.makeBox(10, 10, 10)
        plane = Part.makePlane(10, 10, FreeCAD.Vector(20, 0, 5))
        line = Part.makeLine(FreeCAD.Vector(0, 40, 0), FreeCAD.Vector(10, 40, 0))
        shell = Part.Shell(
            [
                Part.makePlane(5, 5, FreeCAD.Vector(0, 80, 0)),
                Part.makePlane(5, 5, FreeCAD.Vector(5, 80, 0)),
            ]
        )
        hollow = Part.makeBox(10, 10, 10, FreeCAD.Vector(0, 140, 0)).cut(
            Part.makeSphere(3, FreeCAD.Vector(5, 145, 5))
        )

        return {
            "solid": box,
            "face_before_solid": Part.makeCompound([plane, box]),
            "three_dimensions": Part.makeCompound([plane, line, box]),
            "shell_and_solid": Part.makeCompound([shell, box]),
            "solid_with_void_and_face": Part.makeCompound([plane, hollow]),
        }

    def test_MeshGroupsMatchGeometry(self):
        # This test pins an assumption FreeCAD makes about Netgen, the same
        # assumption test_EntityOrderMatchesGmsh pins about Gmsh.
        #
        # A mesh element reports the number Netgen gave the entity it belongs to,
        # and mesh groups are named after those numbers. The number is not the
        # FreeCAD index: Netgen numbers by descending dimension, first the solids
        # with their boundary, then the faces belonging to no solid, and so on.
        # femmesh.entityorder mimics that so netgentools can translate back. Netgen
        # does not promise the order, so this test meshes shapes that expose it and
        # checks that every group holds the mesh of the entity it is named after.
        #
        # WHAT IT MEANS WHEN THIS FAILS: either Netgen changed how it numbers
        # imported entities, or the translation in netgentools was lost.
        #
        # WHAT THE CONSEQUENCES ARE: nothing crashes and the mesh itself stays
        # usable. But every mesh group carries the name of the wrong geometry
        # entity, so materials, constraints and element dimensions attach to the
        # wrong faces, the solver deck is wrong without saying so, and the mesh is
        # coloured and hidden by the wrong component in the view.
        #
        # WHAT TO DO: do not relax this test and do not drop the shapes it meshes.
        # Work out the new order and update femmesh.entityorder, remembering that
        # Gmsh reads the same numbering through the same module, so
        # test_EntityOrderMatchesGmsh has to keep passing as well. If the orders
        # drift apart, each mesher needs its own description.

        if not self.netgen_available():
            # no Netgen installed, same handling as the other mesher tests
            return

        for name, shape in self.entity_order_shapes().items():
            part, mesh_obj = self.netgen_mesh_object(shape, name=f"Mesh_{name}")
            femmesh = self.run_netgen(mesh_obj)
            self.assertTrue(femmesh.GroupCount > 0, f"meshing '{name}' produced no groups")

            checked = 0
            for group in femmesh.Groups:
                group_name = femmesh.getGroupName(group)
                prefix = "".join(c for c in group_name if c.isalpha())
                if prefix not in ("Solid", "Face", "Edge"):
                    continue

                index = int(group_name[len(prefix) :])
                if prefix == "Solid":
                    entity = part.Shape.Solids[index - 1]
                    on_entity = set(femmesh.getNodesBySolid(entity))
                elif prefix == "Face":
                    entity = part.Shape.Faces[index - 1]
                    on_entity = set(femmesh.getNodesByFace(entity))
                else:
                    entity = part.Shape.Edges[index - 1]
                    on_entity = set(femmesh.getNodesByEdge(entity))

                nodes = set()
                for element in femmesh.getGroupElements(group):
                    nodes.update(femmesh.getElementNodes(element))

                self.assertTrue(
                    nodes and nodes <= on_entity,
                    f"in the shape '{name}' the mesh group {group_name} does not lie on the "
                    f"geometry {group_name}, it covers a different entity of the shape",
                )
                checked += 1

            self.assertTrue(checked > 0, f"meshing '{name}' produced no entity groups to check")

    def test_RefinementReachesReferencedEntity(self):
        # The other direction of the same numbering question: a refinement names a
        # geometry entity and netgentools passes its FreeCAD index into the Netgen
        # script, which looks the entity up in the shape lists Netgen offers. That
        # only works while those lists are numbered the way FreeCAD numbers, which
        # is a second assumption about Netgen and unrelated to the order its mesh
        # elements report.
        #
        # WHAT IT MEANS WHEN THIS FAILS: Netgen changed the numbering of the entity
        # lists of an imported shape.
        #
        # WHAT THE CONSEQUENCES ARE: refinements silently act on a different entity
        # than the user selected. The mesh is valid and no message is printed, it is
        # simply fine in the wrong place and coarse where the user asked for detail.
        #
        # WHAT TO DO: map the FreeCAD index to the position in the Netgen list
        # before it is used, the way netgentools maps the numbers of the mesh
        # elements back through femmesh.entityorder.

        if not self.netgen_available():
            # no Netgen installed, same handling as the other mesher tests
            return

        shape = Part.makeCompound(
            [Part.makePlane(10, 10, FreeCAD.Vector(20, 0, 5)), Part.makeBox(10, 10, 10)]
        )
        part, mesh_obj = self.netgen_mesh_object(shape, name="MeshRefined")

        # a box edge, chosen for its high FreeCAD number: a wrong lookup lands on
        # another entity rather than staying within rounding distance of this one
        refined = "Edge16"
        region = ObjectsFem.makeMeshRegion(self.document, mesh_obj, 0.5, "Refinement")
        region.References = [(part, refined)]
        self.document.recompute()

        femmesh = self.run_netgen(mesh_obj)

        # counted on the geometry rather than through the mesh groups, so that this
        # test keeps answering the refinement question alone even when the naming
        # of the groups is broken
        def nodes_on(edge):
            return sum(
                1
                for node in femmesh.Nodes.values()
                if edge.distToShape(Part.Vertex(node))[0] < 1e-4
            )

        on_refined = nodes_on(part.Shape.Edges[int(refined[4:]) - 1])
        elsewhere = max(
            nodes_on(edge)
            for index, edge in enumerate(part.Shape.Edges, start=1)
            if index != int(refined[4:])
        )
        self.assertGreater(
            on_refined,
            2 * elsewhere,
            f"the refinement asked for a fine mesh along {refined}, but that edge carries "
            f"{on_refined} nodes while another edge carries {elsewhere}, so the size was "
            "set on a different entity than the one referenced",
        )
