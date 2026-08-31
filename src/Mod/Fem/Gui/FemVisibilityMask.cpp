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
# include <functional>
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
#include <Mod/Fem/App/FemMeshDimension.h>

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

/// Bits 0..3 of a dimension bitmask, i.e. every dimension a cell can have.
constexpr unsigned AllDimensions = 0xFu;

/// Dimensions @a mode asks for, as a bitmask. Highest asks for all of them and
/// leaves it to the analysis dimension of each entity to narrow it down.
unsigned requestedDimensions(DimensionMode mode)
{
    switch (mode) {
        case DimensionMode::Point:
            return 1u << 0u;
        case DimensionMode::Curve:
            return 1u << 1u;
        case DimensionMode::Surface:
            return 1u << 2u;
        case DimensionMode::Volume:
            return 1u << 3u;
        case DimensionMode::Highest:
        default:
            return AllDimensions;
    }
}

unsigned dimensionBit(int dim)
{
    return (dim >= 0 && dim <= 3) ? (1u << static_cast<unsigned>(dim)) : 0u;
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

int FemVisibilityMask::cellTypeOrder(const std::string& key)
{
    // Rising dimension and then rising node count, so that neighbouring slots
    // fall to types that are told apart by more than their colour anyway.
    static const std::vector<std::string> order = {
        "vertex",
        "polyvertex",
        "line",
        "polyline",
        "edge3",
        "edge4",
        "tria3",
        "quad4",
        "tria6",
        "quad8",
        "quad9",
        "tetra4",
        "hexa8",
        "penta6",
        "pyra5",
        "tetra10",
        "hexa20",
        "penta15",
        "pyra13",
        "hexa27",
    };
    const auto it = std::find(order.begin(), order.end(), key);
    if (it != order.end()) {
        return static_cast<int>(std::distance(order.begin(), it));
    }

    // A type VTK grew and cellTypeKey() spells "vtk<n>". Keeping it out of the
    // range above is what stops it taking the colour of a named type; two of
    // them may still meet, which is a far smaller surprise than a tetra and a
    // triangle sharing a hue.
    const std::size_t known = order.size();
    std::size_t hash = std::hash<std::string> {}(key);
    return static_cast<int>(known + (hash % known));
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

std::string FemVisibilityMask::cellTypeKey(int vtkCellType, bool construction)
{
    std::string key = cellTypeKey(vtkCellType);
    if (construction) {
        key += ConstructionSuffix;
    }
    return key;
}

std::vector<unsigned char> FemVisibilityMask::analysisCells(
    vtkUnstructuredGrid* grid,
    const Fem::FemGeometry* geometry
)
{
    // Every dimension asked for and no construction let through leaves exactly
    // the cells the analysis solves on, which is the definition, so there is
    // nothing here to keep in step with evaluate().
    return evaluate(grid, geometry, DimensionMode::Highest, false, {}, {});
}

std::vector<unsigned char> FemVisibilityMask::evaluate(
    vtkUnstructuredGrid* grid,
    const Fem::FemGeometry* geometry,
    DimensionMode dimMode,
    bool showConstruction,
    const std::set<std::string>& hiddenElements,
    const std::set<std::string>& hiddenCellTypes,
    std::map<std::string, int>* underAchieved
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

    const unsigned requested = requestedDimensions(dimMode);

    // What the analysis dimension of an entity permits, narrowed to what was
    // asked for. Showing the construction elements drops the first half: every
    // element of the requested dimension is then fair game, whether or not the
    // analysis reaches down that far.
    auto keepBits = [&](unsigned analysisBits) {
        return showConstruction ? requested : (requested & analysisBits);
    };

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

    // Mesh-derived analysis dimension (no entity info): nothing declares what
    // the analysis solves, so the highest dimension the mesh reaches stands in
    // for it and everything below it counts as construction.
    if (!hasEntityInfo || !geometry) {
        int maxDim = -1;
        for (vtkIdType i = 0; i < n; ++i) {
            maxDim = std::max(maxDim, celldimArr->GetValue(i));
        }
        const unsigned analysisBits = dimensionBit(maxDim);
        const unsigned bits = keepBits(analysisBits);
        for (vtkIdType i = 0; i < n; ++i) {
            const int cdim = celldimArr->GetValue(i);
            const int ctype = celltypeArr->GetValue(i);
            const bool dimOk = (bits & dimensionBit(cdim)) != 0;
            const bool construction = (analysisBits & dimensionBit(cdim)) == 0;
            const bool typeOk = hiddenCellTypes.empty()
                || !hiddenCellTypes.count(cellTypeKey(ctype, construction));
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
    // The same OR taken over every owner, hidden ones included. Only this one
    // may name a cell construction or not: hiding a shell must not turn the
    // faces it shares with a solid into scaffolding behind the user's back, or
    // the keys here and the keys the tree offers would part ways.
    std::map<std::string, unsigned> analysisOf;

    auto effectiveDim = [&](const std::string& owner, bool record) -> int {
        int declared = geometry->getAnalysisDimension(owner);
        if (declared < 0) {
            // Unknown name (e.g. numeric group id): fall back to achieved
            auto it = achieved.find(owner);
            return it != achieved.end() ? it->second : -1;
        }
        auto it = achieved.find(owner);
        const int ach = it != achieved.end() ? it->second : -1;
        const int effective = Fem::effectiveAnalysisDimension(declared, ach);
        if (ach >= 0 && ach < declared && record && underAchieved) {
            (*underAchieved)[owner] = ach;
            Base::Console().warning(
                "FemVisibilityMask: '%s' declared dim %d but mesh only achieved %d — "
                "widening display mask\n",
                owner.c_str(),
                declared,
                ach
            );
        }
        return effective;
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
        // What the analysis solves on this entity. Independent of the mode, so
        // that a fixed dimension can still be told apart from construction.
        unsigned analysisBits = 0;
        unsigned allOwnerBits = 0;
        // An entity all of whose owners are hidden goes with them; the mode is
        // no way back in.
        bool visible = false;
        for (const auto& owner : ownersOfEntity(geometry, entity)) {
            const bool hidden = isOwnerHidden(owner);
            // A hidden owner still says what the entity is; it has no say in
            // what is drawn, and no badge to earn in the tree either.
            const unsigned bit = dimensionBit(effectiveDim(owner, !hidden));
            allOwnerBits |= bit;
            if (hidden) {
                continue;
            }
            visible = true;
            analysisBits |= bit;
        }
        // Embedded shell / rebar: DimensionOverride on the entity itself is
        // OR'd in even when the entity is owned by a solid (matches
        // FemGeometry::getEntityDimensionMask).
        const auto& overrides = geometry->DimensionOverride.getValue();
        auto oit = overrides.find(entity);
        if (oit != overrides.end() && !oit->second.empty()) {
            try {
                int d = std::stoi(oit->second);
                auto ait = achieved.find(entity);
                if (ait != achieved.end() && ait->second >= 0 && ait->second < d) {
                    if (underAchieved) {
                        (*underAchieved)[entity] = ait->second;
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
                if (dimensionBit(d) != 0) {
                    visible = true;
                    analysisBits |= dimensionBit(d);
                    allOwnerBits |= dimensionBit(d);
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
        dimmask[entity] = visible ? keepBits(analysisBits) : 0u;
        analysisOf[entity] = allOwnerBits;
    }

    // Cells no entity claims decide from the mesh alone: the highest dimension
    // among them stands in for what the analysis solves there.
    const unsigned ungroupedAnalysisBits = dimensionBit(ungroupedMaxDim);
    const unsigned ungroupedBits = keepBits(ungroupedAnalysisBits);

    // Evaluate keep(cell)
    for (vtkIdType i = 0; i < n; ++i) {
        const int cdim = celldimArr->GetValue(i);
        const int ctype = celltypeArr->GetValue(i);

        if (cdim < 0) {
            mask[static_cast<size_t>(i)] = 0;
            continue;
        }

        const std::string& entity = entityOf[static_cast<size_t>(i)];
        // Hiding an unclaimed cell outright would make partially grouped meshes
        // lose elements without any hint, so they get the ungrouped fallback.
        unsigned bits = ungroupedBits;
        unsigned analysisBits = ungroupedAnalysisBits;
        if (!entity.empty()) {
            auto it = dimmask.find(entity);
            bits = (it != dimmask.end()) ? it->second : 0u;
            auto ait = analysisOf.find(entity);
            analysisBits = (ait != analysisOf.end()) ? ait->second : 0u;
        }

        // Which of the two keys the cell answers to has to be settled before
        // the hidden types can be asked about it.
        const bool construction = (analysisBits & dimensionBit(cdim)) == 0;
        const bool typeOk = hiddenCellTypes.empty()
            || !hiddenCellTypes.count(cellTypeKey(ctype, construction));

        mask[static_cast<size_t>(i)] =
            (typeOk && (bits & dimensionBit(cdim)) != 0) ? 1 : 0;
    }

    return mask;
}
