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
from femtest.gui.test_view_panel import TestViewPanelGui as FemGuiTest04
from femtest.gui.test_reference_selection import TestReferenceSelectionGui as FemGuiTest05
from femtest.gui.test_palette import TestPaletteGui as FemGuiTest06
from femtest.gui.test_mesh_edges import TestMeshEdgesGui as FemGuiTest07
from femtest.gui.test_component_selection import TestComponentSelectionGui as FemGuiTest08
from femtest.gui.test_constraint_symbols import TestConstraintSymbolsGui as FemGuiTest09

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
