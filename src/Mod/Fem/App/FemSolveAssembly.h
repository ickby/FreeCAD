/***************************************************************************
 *   Copyright (c) 2026 Stefan Tröger <stefantroeger@gmx.net>              *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#pragma once

#include <map>
#include <string>
#include <vector>

#include <Mod/Fem/FemGlobal.h>
#include <Mod/Fem/App/FemMesh.h>
#include <Mod/Part/App/TopoShape.h>

namespace Fem
{

class FemAnalysis;
class FemMesh;

struct FemExport SolveAssemblyResult
{
    FemMesh mesh;
    Part::TopoShape shape;
    /**
     * Import path of the piece each cell came from, indexed as elementId - 1.
     * Empty for the cells the analysis meshed itself.
     */
    std::vector<std::string> cellSources;
    /**
     * Analysis dimension of each cell (elementId - 1), or -1 if dropped.
     */
    std::vector<int> cellDimensions;
    /**
     * Effective analysis dimension per entity group name. Import paths are
     * flattened with underscores so names match meshtools.get_femmesh_group_name.
     */
    std::map<std::string, int> entityDimensions;
    /**
     * Import path -> (node ID in the source mesh -> node ID in the assembly).
     *
     * A solver reports results per assembly node, and nothing else records
     * which instance a node belongs to once the meshes are merged.
     */
    std::map<std::string, std::map<int, int>> nodeSources;
};

/** Merge native mesh children and placed imports into one solve mesh. */
FemExport SolveAssemblyResult buildSolveAssembly(const FemAnalysis* analysis);

}  // namespace Fem
