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
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#include "PreCompiled.h"

#ifndef _PreComp_
# include <algorithm>
# include <vtkCellData.h>
# include <vtkDataArray.h>
# include <vtkDataSet.h>
# include <vtkIntArray.h>
# include <vtkStringArray.h>
# include <vtkUnstructuredGrid.h>
#endif

#include "FemPerfLog.h"
#include "FemVisibilityMask.h"

#include <Base/Console.h>
#include <Mod/Fem/App/FemGeometry.h>

using namespace FemGui;

namespace
{

vtkIntArray* ensureIntArray(vtkUnstructuredGrid* grid, const char* name, vtkIdType n)
{
    vtkIntArray* arr = vtkIntArray::SafeDownCast(grid->GetCellData()->GetArray(name));
    if (!arr) {
        arr = vtkIntArray::New();
        arr->SetName(name);
        arr->SetNumberOfComponents(1);
        grid->GetCellData()->AddArray(arr);
        arr->Delete();
        arr = vtkIntArray::SafeDownCast(grid->GetCellData()->GetArray(name));
    }
    arr->SetNumberOfTuples(n);
    return arr;
}

int fixedDimension(DimensionMode mode)
{
    switch (mode) {
        case DimensionMode::Point:
            return 0;
        case DimensionMode::Curve:
            return 1;
        case DimensionMode::Surface:
            return 2;
        case DimensionMode::Volume:
            return 3;
        case DimensionMode::Highest:
        default:
            return -1;
    }
}

bool isHiddenElement(
    const std::string& name,
    const Fem::FemGeometry* geometry,
    const std::set<std::string>& hidden
)
{
    if (hidden.count(name)) {
        return true;
    }
    if (!geometry) {
        return false;
    }
    // ComponentN hide cascades to all toplevels in that component
    const auto n = geometry->getComponents().size();
    for (Fem::componentIdType i = 0; i < n; ++i) {
        const std::string compName = "Component" + std::to_string(i + 1);
        if (!hidden.count(compName)) {
            continue;
        }
        for (const auto& t : geometry->getToplevelElements(i)) {
            if (t == name) {
                return true;
            }
        }
    }
    return false;
}

}  // namespace

int FemVisibilityMask::dimensionOfCellType(int vtkCellType)
{
    switch (vtkCellType) {
        case VTK_VERTEX:
        case VTK_POLY_VERTEX:
            return 0;
        case VTK_LINE:
        case VTK_POLY_LINE:
        case VTK_QUADRATIC_EDGE:
        case VTK_CUBIC_LINE:
            return 1;
        case VTK_TRIANGLE:
        case VTK_TRIANGLE_STRIP:
        case VTK_POLYGON:
        case VTK_PIXEL:
        case VTK_QUAD:
        case VTK_QUADRATIC_TRIANGLE:
        case VTK_QUADRATIC_QUAD:
        case VTK_QUADRATIC_POLYGON:
        case VTK_BIQUADRATIC_QUAD:
        case VTK_BIQUADRATIC_TRIANGLE:
        case VTK_QUADRATIC_LINEAR_QUAD:
            return 2;
        case VTK_TETRA:
        case VTK_VOXEL:
        case VTK_HEXAHEDRON:
        case VTK_WEDGE:
        case VTK_PYRAMID:
        case VTK_PENTAGONAL_PRISM:
        case VTK_HEXAGONAL_PRISM:
        case VTK_QUADRATIC_TETRA:
        case VTK_QUADRATIC_HEXAHEDRON:
        case VTK_QUADRATIC_WEDGE:
        case VTK_QUADRATIC_PYRAMID:
        case VTK_TRIQUADRATIC_HEXAHEDRON:
        case VTK_TRIQUADRATIC_PYRAMID:
        case VTK_QUADRATIC_LINEAR_WEDGE:
        case VTK_BIQUADRATIC_QUADRATIC_WEDGE:
        case VTK_BIQUADRATIC_QUADRATIC_HEXAHEDRON:
        case VTK_POLYHEDRON:
            return 3;
        default:
            return -1;
    }
}

std::string FemVisibilityMask::cellTypeKey(int vtkCellType)
{
    switch (vtkCellType) {
        case VTK_VERTEX:
            return "vertex";
        case VTK_POLY_VERTEX:
            return "polyvertex";
        case VTK_LINE:
            return "line";
        case VTK_POLY_LINE:
            return "polyline";
        case VTK_QUADRATIC_EDGE:
            return "edge3";
        case VTK_CUBIC_LINE:
            return "edge4";
        case VTK_TRIANGLE:
            return "tria3";
        case VTK_QUAD:
            return "quad4";
        case VTK_QUADRATIC_TRIANGLE:
            return "tria6";
        case VTK_QUADRATIC_QUAD:
            return "quad8";
        case VTK_BIQUADRATIC_QUAD:
            return "quad9";
        case VTK_TETRA:
            return "tetra4";
        case VTK_HEXAHEDRON:
            return "hexa8";
        case VTK_WEDGE:
            return "penta6";
        case VTK_PYRAMID:
            return "pyra5";
        case VTK_QUADRATIC_TETRA:
            return "tetra10";
        case VTK_QUADRATIC_HEXAHEDRON:
            return "hexa20";
        case VTK_QUADRATIC_WEDGE:
            return "penta15";
        case VTK_QUADRATIC_PYRAMID:
            return "pyra13";
        case VTK_TRIQUADRATIC_HEXAHEDRON:
            return "hexa27";
        default:
            return "vtk" + std::to_string(vtkCellType);
    }
}

void FemVisibilityMask::bakeCellArrays(vtkUnstructuredGrid* grid)
{
    if (!grid) {
        return;
    }
    const vtkIdType n = grid->GetNumberOfCells();
    auto* celldim = ensureIntArray(grid, ArrayCellDim, n);
    auto* celltype = ensureIntArray(grid, ArrayCellType, n);
    auto* origcell = ensureIntArray(grid, ArrayOrigCell, n);

    for (vtkIdType i = 0; i < n; ++i) {
        const int type = grid->GetCellType(i);
        celltype->SetValue(i, type);
        celldim->SetValue(i, dimensionOfCellType(type));
        origcell->SetValue(i, static_cast<int>(i));
    }
}

std::vector<std::string> FemVisibilityMask::ownersOfEntity(
    const Fem::FemGeometry* geometry,
    const std::string& entity
)
{
    if (!geometry || entity.empty()) {
        return {};
    }
    auto owners = geometry->getEntityOwners(entity);
    if (owners.empty()) {
        // Entity is itself a toplevel free element (or unknown solid/volume group).
        owners.push_back(entity);
    }
    return owners;
}

std::string FemVisibilityMask::entityOfCell(vtkDataSet* grid, vtkIdType cell)
{
    if (!grid || cell < 0 || cell >= grid->GetNumberOfCells()) {
        return {};
    }
    auto* cd = grid->GetCellData();

    if (auto* sarr = vtkStringArray::SafeDownCast(cd->GetAbstractArray(ArrayEntityIds))) {
        if (cell < sarr->GetNumberOfTuples()) {
            return sarr->GetValue(cell);
        }
    }
    if (auto* sarr = vtkStringArray::SafeDownCast(cd->GetAbstractArray("group"))) {
        if (cell < sarr->GetNumberOfTuples()) {
            return sarr->GetValue(cell);
        }
    }
    // Integer encoded groups (meshes read from a VTK file) carry no entity name.
    // The decimal id is returned as an opaque group key: it can never collide
    // with a geometry entity name, which always starts with a letter, so the
    // callers fall back to per-group mesh topology for it.
    if (auto* iarr = vtkIntArray::SafeDownCast(cd->GetArray(ArrayEntityIds))) {
        if (cell < iarr->GetNumberOfTuples()) {
            const int v = iarr->GetValue(cell);
            if (v >= 0) {
                return std::to_string(v);
            }
        }
    }
    if (auto* iarr = vtkIntArray::SafeDownCast(cd->GetArray("group"))) {
        if (cell < iarr->GetNumberOfTuples()) {
            const int v = iarr->GetValue(cell);
            if (v >= 0) {
                return std::to_string(v);
            }
        }
    }
    return {};
}

std::vector<unsigned char> FemVisibilityMask::evaluate(
    vtkUnstructuredGrid* grid,
    const Fem::FemGeometry* geometry,
    DimensionMode dimMode,
    const std::set<std::string>& hiddenElements,
    const std::set<std::string>& hiddenCellTypes,
    std::set<std::string>* underAchieved
)
{
    if (underAchieved) {
        underAchieved->clear();
    }
    if (!grid) {
        return {};
    }

    const vtkIdType n = grid->GetNumberOfCells();
    std::vector<unsigned char> mask(static_cast<size_t>(n), 1);

    if (n == 0) {
        return mask;
    }

    // Ensure baked arrays exist
    if (!grid->GetCellData()->HasArray(ArrayCellDim)
        || !grid->GetCellData()->HasArray(ArrayCellType)) {
        bakeCellArrays(grid);
    }

    auto* celldimArr = vtkIntArray::SafeDownCast(grid->GetCellData()->GetArray(ArrayCellDim));
    auto* celltypeArr = vtkIntArray::SafeDownCast(grid->GetCellData()->GetArray(ArrayCellType));

    const int fixedDim = fixedDimension(dimMode);

    // Resolve the entity of every cell once; the lookup walks the cell data
    // arrays and is used by several passes below.
    std::vector<std::string> entityOf(static_cast<size_t>(n));
    bool hasEntityInfo = false;
    {
        FEM_PERF_SCOPE("mesh.visibilityMask.entityOfCell");
        for (vtkIdType i = 0; i < n; ++i) {
            entityOf[static_cast<size_t>(i)] = entityOfCell(grid, i);
            hasEntityInfo = hasEntityInfo || !entityOf[static_cast<size_t>(i)].empty();
        }
    }

    // Mesh-derived highest (no entity info): keep only max dimension present
    if (!hasEntityInfo || !geometry) {
        int maxDim = -1;
        for (vtkIdType i = 0; i < n; ++i) {
            maxDim = std::max(maxDim, celldimArr->GetValue(i));
        }
        const int keepDim = (fixedDim >= 0) ? fixedDim : maxDim;
        for (vtkIdType i = 0; i < n; ++i) {
            const int cdim = celldimArr->GetValue(i);
            const int ctype = celltypeArr->GetValue(i);
            const bool dimOk = (cdim == keepDim);
            const bool typeOk = hiddenCellTypes.empty()
                || !hiddenCellTypes.count(cellTypeKey(ctype));
            mask[static_cast<size_t>(i)] = (dimOk && typeOk) ? 1 : 0;
        }
        return mask;
    }

    // Achieved dimension per toplevel owner (max celldim of cells belonging to it)
    // plus the maximum dimension among the cells no entity claims, which serves
    // as their fallback so that they are not silently hidden.
    std::map<std::string, int> achieved;
    int ungroupedMaxDim = -1;
    {
        FEM_PERF_SCOPE("mesh.visibilityMask.ownersOfEntity");
        for (vtkIdType i = 0; i < n; ++i) {
            const int cdim = celldimArr->GetValue(i);
            const std::string& entity = entityOf[static_cast<size_t>(i)];
            if (entity.empty()) {
                ungroupedMaxDim = std::max(ungroupedMaxDim, cdim);
                continue;
            }
            for (const auto& owner : ownersOfEntity(geometry, entity)) {
                achieved[owner] = std::max(achieved[owner], cdim);
            }
        }
    }

    // Per-entity dimension bitmask
    // dimmask[entity] = OR over non-hidden owners: (1 << effective_dim(o))
    std::map<std::string, unsigned> dimmask;

    auto effectiveDim = [&](const std::string& owner) -> int {
        if (fixedDim >= 0) {
            return fixedDim;
        }
        int declared = geometry->getAnalysisDimension(owner);
        if (declared < 0) {
            // Unknown name (e.g. numeric group id): fall back to achieved
            auto it = achieved.find(owner);
            return it != achieved.end() ? it->second : -1;
        }
        auto it = achieved.find(owner);
        if (it != achieved.end() && it->second >= 0 && it->second < declared) {
            // Only the caller asking for the report gets the log line, so that
            // secondary evaluations (overlay mask) stay quiet.
            if (underAchieved) {
                underAchieved->insert(owner);
                Base::Console().warning(
                    "FemVisibilityMask: '%s' declared dim %d but mesh only achieved %d — "
                    "widening display mask\n",
                    owner.c_str(),
                    declared,
                    it->second
                );
            }
            return it->second;
        }
        return declared;
    };

    auto isOwnerHidden = [&](const std::string& owner) {
        return isHiddenElement(owner, geometry, hiddenElements);
    };

    // Collect entities present in the mesh
    std::set<std::string> entities;
    for (vtkIdType i = 0; i < n; ++i) {
        const auto& e = entityOf[static_cast<size_t>(i)];
        if (!e.empty()) {
            entities.insert(e);
        }
    }

    for (const auto& entity : entities) {
        if (hiddenElements.count(entity) || isOwnerHidden(entity)) {
            dimmask[entity] = 0;
            continue;
        }
        unsigned bits = 0;
        for (const auto& owner : ownersOfEntity(geometry, entity)) {
            if (isOwnerHidden(owner)) {
                continue;
            }
            const int dim = effectiveDim(owner);
            if (dim >= 0 && dim <= 3) {
                bits |= (1u << static_cast<unsigned>(dim));
            }
        }
        // Embedded shell / rebar: DimensionOverride on the entity itself is
        // OR'd in even when the entity is owned by a solid (matches
        // FemGeometry::getEntityDimensionMask).
        if (fixedDim < 0) {
            const auto& overrides = geometry->DimensionOverride.getValue();
            auto oit = overrides.find(entity);
            if (oit != overrides.end() && !oit->second.empty()) {
                try {
                    int d = std::stoi(oit->second);
                    auto ait = achieved.find(entity);
                    if (ait != achieved.end() && ait->second >= 0 && ait->second < d) {
                        if (underAchieved) {
                            underAchieved->insert(entity);
                            Base::Console().warning(
                                "FemVisibilityMask: '%s' declared dim %d but mesh only "
                                "achieved %d — widening display mask\n",
                                entity.c_str(),
                                d,
                                ait->second
                            );
                        }
                        d = ait->second;
                    }
                    if (d >= 0 && d <= 3) {
                        bits |= (1u << static_cast<unsigned>(d));
                    }
                }
                catch (...) {
                    Base::Console().warning(
                        "FemVisibilityMask: invalid DimensionOverride for '%s': '%s'\n",
                        entity.c_str(),
                        oit->second.c_str()
                    );
                }
            }
        }
        dimmask[entity] = bits;
    }

    // Evaluate keep(cell)
    for (vtkIdType i = 0; i < n; ++i) {
        const int cdim = celldimArr->GetValue(i);
        const int ctype = celltypeArr->GetValue(i);
        const bool typeOk = hiddenCellTypes.empty()
            || !hiddenCellTypes.count(cellTypeKey(ctype));

        if (!typeOk || cdim < 0) {
            mask[static_cast<size_t>(i)] = 0;
            continue;
        }

        const std::string& entity = entityOf[static_cast<size_t>(i)];
        if (entity.empty()) {
            // Nothing declares a dimension for this cell, so decide from the
            // mesh alone: keep it when it is of the highest dimension among the
            // other cells no entity claims. Hiding it outright would make
            // partially grouped meshes lose elements without any hint.
            const int keepDim = (fixedDim >= 0) ? fixedDim : ungroupedMaxDim;
            mask[static_cast<size_t>(i)] = (cdim == keepDim) ? 1 : 0;
            continue;
        }

        auto it = dimmask.find(entity);
        const unsigned bits = (it != dimmask.end()) ? it->second : 0u;
        const bool dimOk = (bits & (1u << static_cast<unsigned>(cdim))) != 0;
        mask[static_cast<size_t>(i)] = dimOk ? 1 : 0;
    }

    return mask;
}
