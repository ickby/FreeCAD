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
#include <set>
#include <string>
#include <vector>

#include <Mod/Fem/FemGlobal.h>

#include "FemViewTypes.h"

#include <vtkSmartPointer.h>
#include <vtkUnstructuredGrid.h>

namespace Fem
{
class FemGeometry;
}

namespace FemGui
{

/**
 * Per-cell mixed-dimension visibility mask for FemMeshRenderer.
 *
 * Entity-based "highest" resolution:
 *   cell -> CellEntityIds -> owners -> declared analysis dimension
 *
 * Bake celldim/celltype (and origcell) once on the input grid at mesh load.
 * Mask evaluation is a single O(cells) pass.
 */
class FemGuiExport FemVisibilityMask
{
public:
    static constexpr const char* ArrayCellDim = "celldim";
    static constexpr const char* ArrayCellType = "celltype";
    static constexpr const char* ArrayOrigCell = "origcell";
    static constexpr const char* ArrayEntityIds = "CellEntityIds";

    /** Bake celldim, celltype and origcell int arrays onto the input grid. */
    static void bakeCellArrays(vtkUnstructuredGrid* grid);

    /** VTK cell type -> topological dimension (0..3), or -1 if unknown. */
    static int dimensionOfCellType(int vtkCellType);

    /** Stable string key for cell-type filter / classification (e.g. "tetra10"). */
    static std::string cellTypeKey(int vtkCellType);

    /**
     * Build a per-cell visibility mask (1 = keep, 0 = drop).
     *
     * @param grid          Input unstructured grid (with baked arrays preferred)
     * @param geometry      Optional FemGeometry for entity owners / declared dims
     * @param dimMode       Highest uses per-owner declared dim; else fixed dim
     * @param hiddenElements Element / Component names to hide
     * @param hiddenCellTypes Cell-type keys to hide (empty = all visible)
     * @param underAchieved  Optional: toplevel elements where achieved < declared
     */
    static std::vector<unsigned char> evaluate(
        vtkUnstructuredGrid* grid,
        const Fem::FemGeometry* geometry,
        DimensionMode dimMode,
        const std::set<std::string>& hiddenElements,
        const std::set<std::string>& hiddenCellTypes,
        std::set<std::string>* underAchieved = nullptr
    );

    /** Resolve entity name for a cell from CellEntityIds / group cell data. */
    static std::string entityOfCell(vtkDataSet* grid, vtkIdType cell);

    /** Owners of an entity; empty owners means the entity is itself toplevel. */
    static std::vector<std::string> ownersOfEntity(
        const Fem::FemGeometry* geometry,
        const std::string& entity
    );
};

}  // namespace FemGui
