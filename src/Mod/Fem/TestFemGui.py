# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2020 Bernd Hahnebach <bernd@bimstatik.org>              *
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

# Gui Unit tests for the FEM module
from femtest.gui.test_open import TestObjectOpen as FemGuiTest01
from femtest.gui.test_geometry_partition import TestGeometryPartitionGui as FemGuiTest02
from femtest.gui.test_geometry_marks import TestGeometryMarksGui as FemGuiTest03
from femtest.gui.test_geometry_update import TestGeometryUpdateGui as FemGuiTest16
from femtest.gui.test_view_panel import TestViewPanelGui as FemGuiTest04
from femtest.gui.test_reference_selection import TestReferenceSelectionGui as FemGuiTest05
from femtest.gui.test_palette import TestPaletteGui as FemGuiTest06
from femtest.gui.test_mesh_edges import TestMeshEdgesGui as FemGuiTest07
from femtest.gui.test_component_selection import TestComponentSelectionGui as FemGuiTest08
from femtest.gui.test_constraint_symbols import TestConstraintSymbolsGui as FemGuiTest09
from femtest.gui.test_analysis_visibility import TestAnalysisVisibilityGui as FemGuiTest10
from femtest.gui.test_import_selection import TestImportSelectionGui as FemGuiTest11
from femtest.gui.test_geometry_dimension import TestGeometryDimensionGui as FemGuiTest12
from femtest.gui.test_edit_scope import TestEditScopeGui as FemGuiTest13
from femtest.gui.test_post_modelfilter import TestPostModelFilterGui as FemGuiTest14
from femtest.gui.test_post_render import TestPostRenderGui as FemGuiTest15

# dummy usage to get flake8 and lgtm quiet
False if FemGuiTest01.__name__ else True
False if FemGuiTest02.__name__ else True
False if FemGuiTest03.__name__ else True
False if FemGuiTest04.__name__ else True
False if FemGuiTest05.__name__ else True
False if FemGuiTest06.__name__ else True
False if FemGuiTest07.__name__ else True
False if FemGuiTest08.__name__ else True
False if FemGuiTest09.__name__ else True
False if FemGuiTest10.__name__ else True
False if FemGuiTest11.__name__ else True
False if FemGuiTest12.__name__ else True
False if FemGuiTest13.__name__ else True
False if FemGuiTest14.__name__ else True
False if FemGuiTest15.__name__ else True
False if FemGuiTest16.__name__ else True
