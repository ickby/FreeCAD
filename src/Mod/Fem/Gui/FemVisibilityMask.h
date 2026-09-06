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

#include <vtkDataSet.h>
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

    /** Marks the construction half of a cell-type key; no VTK name contains ':'. */
    static constexpr const char* ConstructionSuffix = ":construction";

    /** Bake celldim, celltype and origcell int arrays onto the input grid. */
    static void bakeCellArrays(vtkUnstructuredGrid* grid);

    /** VTK cell type -> topological dimension (0..3), or -1 if unknown. */
    static int dimensionOfCellType(int vtkCellType);

    /**
     * Whether @a data holds any element with points between its corners.
     *
     * The two renderers both have to know, because a curved element is the one
     * case where the surface filter cannot be asked for the element edges: it
     * triangulates a curved face over its midpoints, and the sides of those
     * triangles cut across the face rather than round it.
     *
     * Answered from the distinct cell types, which a grid works out once and
     * remembers, rather than from the type of every cell of a mesh that may run
     * to millions. Anything that is not an unstructured grid carries no curved
     * element to begin with.
     */
    static bool hasCurvedCells(vtkDataSet* data);

    /** Stable string key for cell-type filter / classification (e.g. "tetra10"). */
    static std::string cellTypeKey(int vtkCellType);

    /**
     * The same key, told apart by which side of the analysis the cell is on.
     *
     * One VTK type can be both at once: the triangles skinning a solid and the
     * triangles of a shell are all tria3, but only the latter are solved on.
     * Keying them apart is what lets the two be coloured and hidden on their
     * own, so @a construction has to be answered the same way here as by
     * analysisCells(), never from the live dimension mode or hidden elements.
     */
    static std::string cellTypeKey(int vtkCellType, bool construction);

    /**
     * Palette slot of a cell type, the same one in every mesh of the analysis.
     *
     * A colour has to stand for the type wherever it is met, and a mesh only
     * ever knows the handful of types it happens to hold. Ranking them against
     * each other gives the first type of one mesh and the first of the next the
     * same slot, so a solid of one and a shell of another come out one colour.
     * The order below is over every type there is, so no mesh can shift it.
     *
     * @param key a base cell-type key as cellTypeKey() returns it, without the
     *            construction suffix.
     */
    static int cellTypeOrder(const std::string& key);

    /**
     * Per-cell flags (1 = the analysis solves on this cell, 0 = the mesher
     * built the mesh from it).
     *
     * This is the definition the construction elements are named after, and
     * the split behind the two-sided cell-type key. Deliberately blind to the
     * dimension mode and to hidden elements: what a cell is does not change
     * with what is on screen.
     */
    static std::vector<unsigned char> analysisCells(
        vtkUnstructuredGrid* grid,
        const Fem::FemGeometry* geometry
    );

    /**
     * Build a per-cell visibility mask (1 = keep, 0 = drop).
     *
     * Two questions are asked of every cell, and they are independent. Which
     * dimensions were asked for, that is @a dimMode, Highest standing for all
     * of them. And whether the cell is one the analysis solves or one the
     * mesher built the mesh from, which is what @a showConstruction lets
     * through. A cell is kept when it answers both, so asking for a dimension
     * the analysis does not have shows nothing until the construction elements
     * are taken in.
     *
     * @param grid          Input unstructured grid (with baked arrays preferred)
     * @param geometry      Optional FemGeometry for entity owners / declared dims
     * @param dimMode       Which dimensions to keep; Highest means all of them
     * @param showConstruction Keep cells below their entity's analysis dimension
     * @param hiddenElements Element / Component names to hide
     * @param hiddenCellTypes Two-sided cell-type keys to hide (empty = all
     *                       visible), as cellTypeKey(type, construction) reads
     *                       them, so that skin triangles can go without taking
     *                       the shell triangles with them
     * @param underAchieved  Optional: toplevel elements where achieved < declared,
     *                       mapped to the dimension the mesh did reach
     */
    static std::vector<unsigned char> evaluate(
        vtkUnstructuredGrid* grid,
        const Fem::FemGeometry* geometry,
        DimensionMode dimMode,
        bool showConstruction,
        const std::set<std::string>& hiddenElements,
        const std::set<std::string>& hiddenCellTypes,
        std::map<std::string, int>* underAchieved = nullptr
    );

    /**
     * Toplevel elements of @a geometry that @a dimMode leaves out.
     *
     * The geometry counterpart to the dimension half of evaluate(), and the
     * same reading of a mode: it names the elements whose declared analysis
     * dimension it is. So asking for 1D leaves a solid out whole rather than
     * baring the edges bounding it — those are where a volume element ends,
     * not elements in their own right, and only a free edge is 1D. Highest
     * leaves nothing out.
     */
    static std::set<std::string> excludedToplevels(
        const Fem::FemGeometry* geometry,
        DimensionMode dimMode
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
