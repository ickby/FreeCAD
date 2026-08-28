# ***************************************************************************
# *   Copyright (c) 2015 Przemo Fiszt <przemo@firszt.eu>                    *
# *   Copyright (c) 2016 Bernd Hahnebach <bernd@bimstatik.org>              *
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

__title__ = "FreeCAD FEM command base class"
__author__ = "Przemo Firszt, Bernd Hahnebach"
__url__ = "https://www.freecad.org"

## @package manager
#  \ingroup FEM
#  \brief FreeCAD FEM command base class

import FreeCAD

from femtools.femutils import expandParentObject
from femtools.femutils import is_of_type

if FreeCAD.GuiUp:
    from PySide import QtCore
    import FreeCADGui
    import FemGui


class CommandManager:

    def __init__(self):

        self.command = "FEM" + self.__class__.__name__
        self.pixmap = self.command
        self.menutext = self.__class__.__name__.lstrip("_")
        self.accel = ""
        self.tooltip = f"Creates a {self.menutext}"
        self.resources = None

        self.is_active = None
        self.do_activated = None
        self.selobj = None
        self.selobj2 = None
        self.active_analysis = None

    def GetResources(self):
        if self.resources is None:
            self.resources = {
                "Pixmap": self.pixmap,
                "MenuText": QtCore.QT_TRANSLATE_NOOP(self.command, self.menutext),
                "Accel": self.accel,
                "ToolTip": QtCore.QT_TRANSLATE_NOOP(self.command, self.tooltip),
            }
        return self.resources

    def IsActive(self):
        if not self.is_active:
            active = False
        elif self.is_active == "always":
            active = True
        elif self.is_active == "with_document":
            active = FreeCADGui.ActiveDocument is not None
        elif self.is_active == "with_analysis":
            active = FemGui.getActiveAnalysis() is not None and self.active_analysis_in_active_doc()
        elif self.is_active == "with_geometry_chain_input":
            active = (
                FemGui.getActiveAnalysis() is not None
                and self.active_analysis_in_active_doc()
                and self.geometry_chain_has_input()
            )
        elif self.is_active == "with_results":
            active = (
                FemGui.getActiveAnalysis() is not None
                and self.active_analysis_in_active_doc()
                and (self.results_present() or self.result_mesh_present())
            )
        elif self.is_active == "with_selresult":
            active = (
                # on import of Frd file in a empty document not Analysis will be there
                FreeCADGui.ActiveDocument is not None
                and self.result_selected()
            )
        elif self.is_active == "with_vtk_selresult":
            active = self.vtk_result_selected()
        elif self.is_active == "with_part_feature":
            active = FreeCADGui.ActiveDocument is not None and self.part_feature_selected()
        elif self.is_active == "with_analysis_geometry_or_part":
            # New workflow: analysis already has FemGeometry → no selection needed.
            # Legacy: a Part feature must be selected to mesh.
            active = FreeCADGui.ActiveDocument is not None and (
                self.analysis_has_geometry() or self.part_feature_selected()
            )
        elif self.is_active == "with_femmesh":
            active = FreeCADGui.ActiveDocument is not None and self.femmesh_selected()
        elif self.is_active == "with_gmsh_femmesh":
            active = FreeCADGui.ActiveDocument is not None and self.gmsh_femmesh_selected()
        elif self.is_active == "with_femmesh_andor_res":
            active = (
                FreeCADGui.ActiveDocument is not None and self.with_femmesh_andor_res_selected()
            )
        elif self.is_active == "with_material":
            active = (
                FemGui.getActiveAnalysis() is not None
                and self.active_analysis_in_active_doc()
                and self.material_selected()
            )
        elif self.is_active == "with_material_solid":
            active = (
                FemGui.getActiveAnalysis() is not None
                and self.active_analysis_in_active_doc()
                and self.material_solid_selected()
            )
        elif self.is_active == "with_solver":
            active = (
                FemGui.getActiveAnalysis() is not None
                and self.active_analysis_in_active_doc()
                and self.solver_selected()
            )
        elif self.is_active == "with_solver_elmer":
            active = (
                FemGui.getActiveAnalysis() is not None
                and self.active_analysis_in_active_doc()
                and self.solver_elmer_selected()
            )
        elif self.is_active == "with_analysis_without_solver":
            active = (
                FemGui.getActiveAnalysis() is not None
                and self.active_analysis_in_active_doc()
                and not self.analysis_has_solver()
            )
        return active

    def Activated(self):
        if self.do_activated == "add_obj_on_gui_noset_edit":
            self.add_obj_on_gui_noset_edit(self.__class__.__name__.lstrip("_"))
        elif self.do_activated == "add_obj_on_gui_expand_noset_edit":
            self.add_obj_on_gui_expand_noset_edit(self.__class__.__name__.lstrip("_"))
        elif self.do_activated == "add_obj_on_gui_set_edit":
            self.add_obj_on_gui_set_edit(self.__class__.__name__.lstrip("_"))
        elif self.do_activated == "add_obj_on_gui_selobj_noset_edit":
            self.add_obj_on_gui_selobj_noset_edit(self.__class__.__name__.lstrip("_"))
        elif self.do_activated == "add_obj_on_gui_selobj_set_edit":
            self.add_obj_on_gui_selobj_set_edit(self.__class__.__name__.lstrip("_"))
        elif self.do_activated == "add_obj_on_gui_selobj_expand_noset_edit":
            self.add_obj_on_gui_selobj_expand_noset_edit(self.__class__.__name__.lstrip("_"))
        elif self.do_activated == "add_filter_set_edit":
            self.add_filter_set_edit(self.__class__.__name__.lstrip("_"))
        elif self.do_activated == "add_geometry_set_edit":
            self.add_geometry_set_edit(self.__class__.__name__.lstrip("_"))
        # in all other cases Activated is implemented it the command class

    def results_present(self):
        results = False
        analysis_members = FemGui.getActiveAnalysis().Group
        for o in analysis_members:
            if o.isDerivedFrom("Fem::FemResultObject"):
                results = True
        return results

    def result_mesh_present(self):
        result_mesh = False
        analysis_members = FemGui.getActiveAnalysis().Group
        for o in analysis_members:
            if is_of_type(o, "Fem::MeshResult"):
                result_mesh = True
        return result_mesh

    def result_selected(self):
        sel = FreeCADGui.Selection.getSelection()
        if len(sel) == 1 and sel[0].isDerivedFrom("Fem::FemResultObject"):
            self.selobj = sel[0]
            return True
        return False

    def vtk_result_selected(self):
        sel = FreeCADGui.Selection.getSelection()
        if len(sel) == 1 and sel[0].isDerivedFrom("Fem::FemPostObject"):
            self.selobj = sel[0]
            return True
        return False

    def part_feature_selected(self):
        sel = FreeCADGui.Selection.getSelection()
        if len(sel) == 1 and sel[0].isDerivedFrom("Part::Feature"):
            self.selobj = sel[0]
            return True
        else:
            return False

    def analysis_has_geometry(self):
        analysis = FemGui.getActiveAnalysis()
        if analysis is None or not self.active_analysis_in_active_doc():
            return False
        from femtools import membertools

        return bool(membertools.get_member(analysis, "Fem::FemGeometry"))

    def geometry_chain_has_input(self):
        analysis = FemGui.getActiveAnalysis()
        if analysis is None or not self.active_analysis_in_active_doc():
            return False
        from femtools import membertools

        groups = membertools.get_member(analysis, "Fem::GeometryGroup")
        return bool(groups and groups[0].Group)

    def femmesh_selected(self):
        sel = FreeCADGui.Selection.getSelection()
        if len(sel) == 1 and sel[0].isDerivedFrom("Fem::FemMeshObject"):
            self.selobj = sel[0]
            return True
        else:
            return False

    def gmsh_femmesh_selected(self):
        sel = FreeCADGui.Selection.getSelection()
        if len(sel) == 1 and is_of_type(sel[0], "Fem::FemMeshGmsh"):
            self.selobj = sel[0]
            return True
        else:
            return False

    def material_selected(self):
        sel = FreeCADGui.Selection.getSelection()
        if len(sel) == 1 and sel[0].isDerivedFrom("App::MaterialObjectPython"):
            return True
        else:
            return False

    def material_solid_selected(self):
        sel = FreeCADGui.Selection.getSelection()
        if (
            len(sel) == 1
            and sel[0].isDerivedFrom("App::MaterialObjectPython")
            and hasattr(sel[0], "Category")
            and sel[0].Category == "Solid"
        ):
            self.selobj = sel[0]
            return True
        else:
            return False

    def with_femmesh_andor_res_selected(self):
        sel = FreeCADGui.Selection.getSelection()
        if len(sel) == 1 and sel[0].isDerivedFrom("Fem::FemMeshObject"):
            self.selobj = sel[0]
            self.selobj2 = None
            return True
        elif len(sel) == 2:
            if sel[0].isDerivedFrom("Fem::FemMeshObject"):
                if sel[1].isDerivedFrom("Fem::FemResultObject"):
                    self.selobj = sel[0]  # mesh
                    self.selobj2 = sel[1]  # res
                    return True
                else:
                    return False
            elif sel[1].isDerivedFrom("Fem::FemMeshObject"):
                if sel[0].isDerivedFrom("Fem::FemResultObject"):
                    self.selobj = sel[1]  # mesh
                    self.selobj2 = sel[0]  # res
                    return True
                else:
                    return False
            else:
                return False
        else:
            return False

    def active_analysis_in_active_doc(self):
        analysis = FemGui.getActiveAnalysis()
        if analysis.Document is FreeCAD.ActiveDocument:
            self.active_analysis = analysis
            return True
        else:
            return False

    def solver_selected(self):
        sel = FreeCADGui.Selection.getSelection()
        if len(sel) == 1 and sel[0].isDerivedFrom("Fem::FemSolverObjectPython"):
            self.selobj = sel[0]
            return True
        else:
            return False

    def solver_elmer_selected(self):
        sel = FreeCADGui.Selection.getSelection()
        if len(sel) == 1 and is_of_type(sel[0], "Fem::SolverElmer"):
            self.selobj = sel[0]
            return True
        else:
            return False

    def analysis_has_solver(self):
        solver = False
        analysis_members = FemGui.getActiveAnalysis().Group
        for o in analysis_members:
            if o.isDerivedFrom("Fem::FemSolverObjectPython"):
                solver = True
        if solver is True:
            return True
        else:
            return False

    def hide_meshes_show_parts_constraints(self):
        if FreeCAD.GuiUp:
            for acnstrmesh in FemGui.getActiveAnalysis().Group:
                if "Constraint" in acnstrmesh.TypeId:
                    acnstrmesh.ViewObject.Visibility = True
                if "Mesh" in acnstrmesh.TypeId:
                    # OvG: Hide meshes and show constraints and meshed part
                    # e.g. on purging results
                    acnstrmesh.ViewObject.Visibility = False

    # ****************************************************************************************
    # methods to add the objects to the document in FreeCADGui mode

    def add_obj_on_gui_set_edit(self, objtype):
        FreeCAD.ActiveDocument.openTransaction(f"Create Fem{objtype}")
        FreeCADGui.addModule("ObjectsFem")
        FreeCADGui.addModule("FemGui")
        FreeCADGui.doCommand(
            "FemGui.getActiveAnalysis().addObject(ObjectsFem."
            "make{}(FreeCAD.ActiveDocument))".format(objtype)
        )
        # no other obj should be selected if we go in task panel
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.doCommand(
            "FreeCADGui.ActiveDocument.setEdit(FreeCAD.ActiveDocument.ActiveObject.Name)"
        )

    def add_obj_on_gui_noset_edit(self, objtype):
        FreeCAD.ActiveDocument.openTransaction(f"Create Fem{objtype}")
        FreeCADGui.addModule("ObjectsFem")
        FreeCADGui.addModule("FemGui")
        FreeCADGui.doCommand(
            "FemGui.getActiveAnalysis().addObject(ObjectsFem."
            "make{}(FreeCAD.ActiveDocument))".format(objtype)
        )
        # FreeCAD.ActiveDocument.commitTransaction()  # solver command class had this line
        # no clear selection is done

    def add_obj_on_gui_expand_noset_edit(self, objtype):
        # like add_obj_on_gui_noset_edit but the parent object
        # is expanded in the tree to see the added obj
        # the added obj is also selected to enable direct additions to it
        FreeCAD.ActiveDocument.openTransaction(f"Create Fem{objtype}")
        FreeCADGui.addModule("ObjectsFem")
        FreeCADGui.addModule("FemGui")
        # expand parent obj in tree view if selected
        expandParentObject()
        # add the object
        FreeCADGui.doCommand(
            "addedObj = FemGui.getActiveAnalysis().addObject(ObjectsFem."
            "make{}(FreeCAD.ActiveDocument))[0]".format(objtype)
        )
        # select only added object
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.doCommand("addedObjDocObj = FreeCAD.ActiveDocument.getObject(addedObj.Name)")
        FreeCADGui.doCommand("FreeCADGui.Selection.addSelection(addedObjDocObj)")

    def add_obj_on_gui_selobj_set_edit(self, objtype):
        FreeCAD.ActiveDocument.openTransaction(f"Create Fem{objtype}")
        FreeCADGui.addModule("ObjectsFem")
        FreeCADGui.doCommand(
            "ObjectsFem.make{}("
            "FreeCAD.ActiveDocument, FreeCAD.ActiveDocument.{})".format(objtype, self.selobj.Name)
        )
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.doCommand(
            "FreeCADGui.ActiveDocument.setEdit(FreeCAD.ActiveDocument.ActiveObject.Name)"
        )

    def add_obj_on_gui_selobj_noset_edit(self, objtype):
        FreeCAD.ActiveDocument.openTransaction(f"Create Fem{objtype}")
        FreeCADGui.addModule("ObjectsFem")
        FreeCADGui.doCommand(
            "ObjectsFem.make{}("
            "FreeCAD.ActiveDocument, FreeCAD.ActiveDocument.{})".format(objtype, self.selobj.Name)
        )
        FreeCADGui.Selection.clearSelection()

    def add_obj_on_gui_selobj_expand_noset_edit(self, objtype):
        # like add_obj_on_gui_selobj_noset_edit but the selection is kept
        # and the selobj is expanded in the tree to see the added obj
        FreeCAD.ActiveDocument.openTransaction(f"Create Fem{objtype}")
        FreeCADGui.addModule("ObjectsFem")
        FreeCADGui.doCommand(
            "ObjectsFem.make{}("
            "FreeCAD.ActiveDocument, FreeCAD.ActiveDocument.{})".format(objtype, self.selobj.Name)
        )
        # expand selobj in tree view
        expandParentObject()

    def add_filter_set_edit(self, filtertype):
        # like add_obj_on_gui_selobj_noset_edit but the selection is kept
        # and the selobj is expanded in the tree to see the added obj

        # check if we should use python filter
        from femguiutils.vtk_module_handling import vtk_compatibility_abort

        if vtk_compatibility_abort(True):
            return

        # Note: we know selobj is a FemPostObject as otherwise the command should not have been active
        # We also assume the all filters are in PostGroups and not astray
        group = None
        if self.selobj.hasExtension("Fem::FemPostGroupExtension"):
            group = self.selobj
        else:
            group = self.selobj.getParentPostGroup()

        FreeCAD.ActiveDocument.openTransaction(f"Create Fem{filtertype}")
        FreeCADGui.addModule("ObjectsFem")
        FreeCADGui.doCommand(
            "ObjectsFem.make{}("
            "FreeCAD.ActiveDocument, FreeCAD.ActiveDocument.{})".format(filtertype, group.Name)
        )
        # set display and selection style to assure the user sees the new object
        FreeCADGui.doCommand(
            'FreeCAD.ActiveDocument.ActiveObject.ViewObject.DisplayMode = "Surface"'
        )
        FreeCADGui.doCommand(
            'FreeCAD.ActiveDocument.ActiveObject.ViewObject.SelectionStyle = "BoundBox"'
        )
        FreeCADGui.doCommand(
            f"FreeCAD.ActiveDocument.ActiveObject.ViewObject.NoneFieldColor = {self.selobj.ViewObject.NoneFieldColor}"
        )

        # hide selected filter
        FreeCADGui.doCommand(
            "FreeCAD.ActiveDocument.{}.ViewObject.Visibility = False".format(self.selobj.Name)
        )

        # recompute, expand selobj in tree view
        expandParentObject()
        FreeCADGui.doCommand("FreeCAD.ActiveDocument.ActiveObject.recompute()")

        # set edit
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.doCommand(
            "FreeCADGui.ActiveDocument.setEdit(FreeCAD.ActiveDocument.ActiveObject.Name)"
        )

    def add_geometry_set_edit(self, geometrytype):
        """Add a geometry tool under the analysis GeometryGroup and open edit."""
        from femtools import membertools

        analysis = FemGui.getActiveAnalysis()
        groups = membertools.get_member(analysis, "Fem::GeometryGroup")

        # The order of the group is the order of the chain, so a new step goes
        # right behind the selected one and takes over what it produced. Without
        # a step selected it is appended and builds on the whole chain.
        predecessor = None
        if groups:
            selection = FreeCADGui.Selection.getSelection()
            if len(selection) == 1 and selection[0] in groups[0].Group:
                predecessor = selection[0]

        FreeCAD.ActiveDocument.openTransaction(f"Create Fem{geometrytype}")
        FreeCADGui.addModule("ObjectsFem")
        FreeCADGui.addModule("FemGui")
        FreeCADGui.addModule("femtools.membertools")
        FreeCADGui.doCommand("_analysis = FemGui.getActiveAnalysis()")

        if groups:
            FreeCADGui.doCommand(
                "_group = femtools.membertools.get_member(" "_analysis, 'Fem::GeometryGroup')[0]"
            )
        else:
            FreeCADGui.doCommand("_group = ObjectsFem.makeGeometryGroup(FreeCAD.ActiveDocument)")
            FreeCADGui.doCommand("_analysis.addObject(_group)")

        FreeCADGui.doCommand(
            f"geometry_obj = _group.addObject("
            f"ObjectsFem.make{geometrytype}(FreeCAD.ActiveDocument))[0]"
        )
        if predecessor is not None:
            FreeCADGui.doCommand("_steps = list(_group.Group)")
            FreeCADGui.doCommand("_steps.remove(geometry_obj)")
            FreeCADGui.doCommand(
                "_steps.insert("
                f"_steps.index(FreeCAD.ActiveDocument.{predecessor.Name}) + 1, geometry_obj)"
            )
            FreeCADGui.doCommand("_group.Group = _steps")

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.doCommand("FreeCADGui.ActiveDocument.setEdit(geometry_obj.Name)")

    def add_analysis_import(self):
        """
        Add an analysis import under the Imports group.

        membertools.get_member() does not recurse into the Imports container;
        later recursive import resolution must look there explicitly.
        """
        import FreeCAD
        import FreeCADGui
        import ObjectsFem
        from femtools import importtools

        analysis = FemGui.getActiveAnalysis()
        selection = FreeCADGui.Selection.getSelection()
        source = None
        for obj in selection:
            if obj.isDerivedFrom("Fem::FemAnalysis") and obj != analysis:
                source = obj
                break
        if source is None:
            FreeCAD.Console.PrintError(
                "Select a source Fem analysis in the tree, then run Import Analysis again.\n"
            )
            return

        FreeCAD.ActiveDocument.openTransaction("Create Analysis Import")

        import_obj = ObjectsFem.makeAnalysisImport(FreeCAD.ActiveDocument)
        import_obj.Analysis = source
        importtools.wire_import(analysis, import_obj)

        FreeCAD.ActiveDocument.commitTransaction()
        FreeCAD.ActiveDocument.recompute()
