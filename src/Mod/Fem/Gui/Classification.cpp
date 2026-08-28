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

#include "PreCompiled.h"

#ifndef _PreComp_
# include <algorithm>
# include <set>

# include <vtkCellData.h>
# include <vtkIntArray.h>
#endif

#include "Classification.h"
#include "FemMeshRenderer.h"
#include "FemVisibilityMask.h"

#include <App/DocumentObject.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <Base/Console.h>
#include <Base/Tools.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemGeometry.h>

using namespace FemGui;

namespace
{

int ensureCategory(
    std::vector<Category>& categories,
    std::map<std::string, int>& keyToIndex,
    const std::string& key,
    const std::string& label
)
{
    auto it = keyToIndex.find(key);
    if (it != keyToIndex.end()) {
        return it->second;
    }
    Category cat;
    cat.key = key;
    cat.label = label.empty() ? key : label;
    const int idx = static_cast<int>(categories.size());
    cat.color = Classification::colorForIndex(idx);
    categories.push_back(std::move(cat));
    keyToIndex[key] = idx;
    return idx;
}

std::string toplevelOfEntity(const Fem::FemGeometry* geometry, const std::string& entity)
{
    if (!geometry || entity.empty()) {
        return entity;
    }
    auto owners = FemVisibilityMask::ownersOfEntity(geometry, entity);
    // Prefer the first owner; multi-owner faces share colour of the first owner
    // for toplevel mode (tree grouping still lists the entity under each owner later).
    if (!owners.empty()) {
        return owners.front();
    }
    return entity;
}

}  // namespace

Base::Color Classification::colorForIndex(int index)
{
    const auto& colors = FemMeshRenderer::distinctColors();
    if (colors.empty()) {
        return Base::Color(0.8f, 0.8f, 0.8f);
    }
    const int n = static_cast<int>(colors.size());
    const int wrapped = ((index % n) + n) % n;
    return colors[static_cast<size_t>(wrapped)];
}

std::unique_ptr<Classification> Classification::create(
    ColorMode mode,
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid
)
{
    switch (mode) {
        case ColorMode::Toplevel:
            return std::make_unique<ToplevelClassification>(geometry, meshGrid);
        case ColorMode::Material:
            return std::make_unique<MaterialClassification>(analysis, geometry, meshGrid);
        case ColorMode::CellType:
            return std::make_unique<CellTypeClassification>(meshGrid);
        case ColorMode::Subelement:
        default:
            return std::make_unique<SubelementClassification>(geometry, meshGrid);
    }
}

// ---------------------------------------------------------------------------
// SubelementClassification
// ---------------------------------------------------------------------------

SubelementClassification::SubelementClassification(
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid
)
    : m_geometry(geometry)
{
    build(geometry, meshGrid);
}

void SubelementClassification::build(Fem::FemGeometry* geometry, vtkUnstructuredGrid* meshGrid)
{
    m_categories.clear();
    m_keyToIndex.clear();
    m_cellCategory.clear();

    std::set<std::string> entities;

    if (geometry) {
        const auto n = geometry->getComponents().size();
        for (Fem::componentIdType i = 0; i < n; ++i) {
            for (const auto& name : geometry->getToplevelElements(i)) {
                entities.insert(name);
            }
        }
    }

    if (meshGrid) {
        const vtkIdType n = meshGrid->GetNumberOfCells();
        for (vtkIdType i = 0; i < n; ++i) {
            auto e = FemVisibilityMask::entityOfCell(meshGrid, i);
            if (e.empty()) {
                continue;
            }
            // Resolve FaceN/EdgeN under a solid to the owning toplevel so mesh
            // categories match geometry / the view-panel tree (solids stay
            // per-toplevel; free faces keep their own key).
            entities.insert(toplevelOfEntity(geometry, e));
        }
    }

    // Stable order by key so category indices are deterministic for a given set
    std::vector<std::string> sorted(entities.begin(), entities.end());
    std::sort(sorted.begin(), sorted.end());
    for (const auto& key : sorted) {
        ensureCategory(m_categories, m_keyToIndex, key, key);
    }

    if (meshGrid) {
        const vtkIdType n = meshGrid->GetNumberOfCells();
        m_cellCategory.assign(static_cast<size_t>(n), 0);
        for (vtkIdType i = 0; i < n; ++i) {
            const auto entity = FemVisibilityMask::entityOfCell(meshGrid, i);
            const auto key = toplevelOfEntity(geometry, entity);
            auto it = m_keyToIndex.find(key);
            if (it == m_keyToIndex.end()) {
                it = m_keyToIndex.find(entity);
            }
            if (it != m_keyToIndex.end()) {
                m_cellCategory[static_cast<size_t>(i)] = it->second;
            }
        }
    }
}

std::vector<Category> SubelementClassification::categories() const
{
    return m_categories;
}

int SubelementClassification::categoryOfElement(const std::string& element) const
{
    auto it = m_keyToIndex.find(element);
    if (it != m_keyToIndex.end()) {
        return it->second;
    }
    // Faces/edges under a solid share the solid's category (tree is per-toplevel).
    const auto key = toplevelOfEntity(m_geometry, element);
    it = m_keyToIndex.find(key);
    return it != m_keyToIndex.end() ? it->second : 0;
}

int SubelementClassification::categoryOfCell(vtkIdType cell) const
{
    if (cell < 0 || static_cast<size_t>(cell) >= m_cellCategory.size()) {
        return 0;
    }
    return m_cellCategory[static_cast<size_t>(cell)];
}

// ---------------------------------------------------------------------------
// ToplevelClassification
// ---------------------------------------------------------------------------

ToplevelClassification::ToplevelClassification(
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid
)
    : m_geometry(geometry)
{
    build(geometry, meshGrid);
}

void ToplevelClassification::build(Fem::FemGeometry* geometry, vtkUnstructuredGrid* meshGrid)
{
    m_categories.clear();
    m_keyToIndex.clear();
    m_cellCategory.clear();

    std::set<std::string> toplevels;
    if (geometry) {
        const auto n = geometry->getComponents().size();
        for (Fem::componentIdType i = 0; i < n; ++i) {
            for (const auto& name : geometry->getToplevelElements(i)) {
                toplevels.insert(name);
            }
        }
    }

    if (meshGrid) {
        const vtkIdType n = meshGrid->GetNumberOfCells();
        for (vtkIdType i = 0; i < n; ++i) {
            auto e = FemVisibilityMask::entityOfCell(meshGrid, i);
            if (!e.empty()) {
                toplevels.insert(toplevelOfEntity(geometry, e));
            }
        }
    }

    std::vector<std::string> sorted(toplevels.begin(), toplevels.end());
    std::sort(sorted.begin(), sorted.end());
    for (const auto& key : sorted) {
        ensureCategory(m_categories, m_keyToIndex, key, key);
    }

    if (meshGrid) {
        const vtkIdType n = meshGrid->GetNumberOfCells();
        m_cellCategory.assign(static_cast<size_t>(n), 0);
        for (vtkIdType i = 0; i < n; ++i) {
            auto e = FemVisibilityMask::entityOfCell(meshGrid, i);
            if (e.empty()) {
                continue;
            }
            const auto top = toplevelOfEntity(geometry, e);
            auto it = m_keyToIndex.find(top);
            if (it != m_keyToIndex.end()) {
                m_cellCategory[static_cast<size_t>(i)] = it->second;
            }
        }
    }
}

std::vector<Category> ToplevelClassification::categories() const
{
    return m_categories;
}

int ToplevelClassification::categoryOfElement(const std::string& element) const
{
    auto it = m_keyToIndex.find(element);
    if (it != m_keyToIndex.end()) {
        return it->second;
    }
    // Sub-entity (Face7): resolve to owning toplevel (Solid3)
    const auto top = toplevelOfEntity(m_geometry, element);
    if (top != element) {
        it = m_keyToIndex.find(top);
        if (it != m_keyToIndex.end()) {
            return it->second;
        }
    }
    return 0;
}

int ToplevelClassification::categoryOfCell(vtkIdType cell) const
{
    if (cell < 0 || static_cast<size_t>(cell) >= m_cellCategory.size()) {
        return 0;
    }
    return m_cellCategory[static_cast<size_t>(cell)];
}

// ---------------------------------------------------------------------------
// MaterialClassification
// ---------------------------------------------------------------------------

MaterialClassification::MaterialClassification(
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid
)
    : m_geometry(geometry)
{
    build(analysis, geometry, meshGrid);
}

void MaterialClassification::build(
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid
)
{
    m_categories.clear();
    m_keyToIndex.clear();
    m_elementCategory.clear();
    m_cellCategory.clear();

    // Collect all toplevel element names that need a material assignment
    std::set<std::string> allElements;
    if (geometry) {
        const auto n = geometry->getComponents().size();
        for (Fem::componentIdType i = 0; i < n; ++i) {
            for (const auto& name : geometry->getToplevelElements(i)) {
                allElements.insert(name);
            }
        }
    }

    struct MatInfo
    {
        App::DocumentObject* obj {nullptr};
        std::string key;
        std::string label;
        bool emptyRefs {false};
        std::vector<std::string> refs;
    };
    std::vector<MatInfo> materials;
    int emptyRefIndex = -1;

    if (analysis) {
        for (auto* obj : analysis->Group.getValues()) {
            if (!obj) {
                continue;
            }
            // Material features expose References (PropertyLinkSubList*) and Material
            auto* prop = dynamic_cast<App::PropertyLinkSubList*>(
                obj->getPropertyByName("References")
            );
            if (!prop || !obj->getPropertyByName("Material")) {
                continue;
            }

            MatInfo info;
            info.obj = obj;
            info.key = obj->getNameInDocument() ? obj->getNameInDocument() : "Material";
            if (auto* nameProp = dynamic_cast<App::PropertyString*>(
                    obj->getPropertyByName("MaterialName")
                )) {
                info.label = nameProp->getValue();
            }
            if (info.label.empty()) {
                info.label = obj->Label.getStrValue();
            }

            const auto subsets = prop->getSubListValues();
            if (subsets.empty()) {
                info.emptyRefs = true;
            }
            else {
                for (const auto& subset : subsets) {
                    for (const auto& sub : subset.second) {
                        // Sub names like "Solid1", "Face2", or "Solid1."
                        std::string s = sub;
                        while (!s.empty() && s.back() == '.') {
                            s.pop_back();
                        }
                        // Strip leading path components if present
                        auto pos = s.find_last_of('.');
                        if (pos != std::string::npos) {
                            s = s.substr(pos + 1);
                        }
                        if (!s.empty()) {
                            info.refs.push_back(s);
                        }
                    }
                }
                if (info.refs.empty()) {
                    info.emptyRefs = true;
                }
            }
            if (info.emptyRefs && emptyRefIndex < 0) {
                emptyRefIndex = static_cast<int>(materials.size());
            }
            materials.push_back(std::move(info));
        }
    }

    std::map<std::string, std::string> elementToMatKey;
    std::set<std::string> assigned;

    for (const auto& m : materials) {
        if (m.emptyRefs) {
            continue;
        }
        for (const auto& ref : m.refs) {
            elementToMatKey[ref] = m.key;
            assigned.insert(ref);
        }
    }

    std::vector<std::string> missed;
    for (const auto& e : allElements) {
        if (!assigned.count(e)) {
            missed.push_back(e);
        }
    }

    if (emptyRefIndex >= 0) {
        const std::string& defKey = materials[static_cast<size_t>(emptyRefIndex)].key;
        for (const auto& e : missed) {
            elementToMatKey[e] = defKey;
        }
        missed.clear();
    }

    // Build categories: materials first (stable by key), then optional no-material
    std::vector<std::string> matKeys;
    matKeys.reserve(materials.size());
    for (const auto& m : materials) {
        matKeys.push_back(m.key);
    }
    std::sort(matKeys.begin(), matKeys.end());
    matKeys.erase(std::unique(matKeys.begin(), matKeys.end()), matKeys.end());

    for (const auto& key : matKeys) {
        std::string label = key;
        for (const auto& m : materials) {
            if (m.key == key) {
                label = m.label;
                break;
            }
        }
        ensureCategory(m_categories, m_keyToIndex, key, label);
    }

    if (!missed.empty()) {
        ensureCategory(m_categories, m_keyToIndex, NoMaterialKey, "no material");
        for (const auto& e : missed) {
            elementToMatKey[e] = NoMaterialKey;
        }
    }

    for (const auto& [elem, matKey] : elementToMatKey) {
        auto it = m_keyToIndex.find(matKey);
        if (it != m_keyToIndex.end()) {
            m_elementCategory[elem] = it->second;
        }
    }

    // Cells: map entity -> toplevel -> material
    if (meshGrid) {
        const vtkIdType n = meshGrid->GetNumberOfCells();
        m_cellCategory.assign(static_cast<size_t>(n), 0);
        for (vtkIdType i = 0; i < n; ++i) {
            auto e = FemVisibilityMask::entityOfCell(meshGrid, i);
            if (e.empty()) {
                continue;
            }
            const auto top = toplevelOfEntity(geometry, e);
            auto it = m_elementCategory.find(top);
            if (it != m_elementCategory.end()) {
                m_cellCategory[static_cast<size_t>(i)] = it->second;
            }
            else if (!missed.empty() || m_keyToIndex.count(NoMaterialKey)) {
                auto nit = m_keyToIndex.find(NoMaterialKey);
                if (nit != m_keyToIndex.end()) {
                    m_cellCategory[static_cast<size_t>(i)] = nit->second;
                }
            }
        }
    }
}

std::vector<Category> MaterialClassification::categories() const
{
    return m_categories;
}

int MaterialClassification::categoryOfElement(const std::string& element) const
{
    auto it = m_elementCategory.find(element);
    if (it != m_elementCategory.end()) {
        return it->second;
    }
    // Sub-entity: resolve to owning toplevel then look up material
    const auto top = toplevelOfEntity(m_geometry, element);
    if (top != element) {
        it = m_elementCategory.find(top);
        if (it != m_elementCategory.end()) {
            return it->second;
        }
    }
    auto nit = m_keyToIndex.find(NoMaterialKey);
    return nit != m_keyToIndex.end() ? nit->second : 0;
}

int MaterialClassification::categoryOfCell(vtkIdType cell) const
{
    if (cell < 0 || static_cast<size_t>(cell) >= m_cellCategory.size()) {
        return 0;
    }
    return m_cellCategory[static_cast<size_t>(cell)];
}

// ---------------------------------------------------------------------------
// CellTypeClassification
// ---------------------------------------------------------------------------

CellTypeClassification::CellTypeClassification(vtkUnstructuredGrid* meshGrid)
{
    build(meshGrid);
}

void CellTypeClassification::build(vtkUnstructuredGrid* meshGrid)
{
    m_categories.clear();
    m_keyToIndex.clear();
    m_cellCategory.clear();

    if (!meshGrid) {
        return;
    }

    if (!meshGrid->GetCellData()->HasArray(FemVisibilityMask::ArrayCellType)) {
        FemVisibilityMask::bakeCellArrays(meshGrid);
    }

    auto* celltypeArr = vtkIntArray::SafeDownCast(
        meshGrid->GetCellData()->GetArray(FemVisibilityMask::ArrayCellType)
    );
    if (!celltypeArr) {
        return;
    }

    const vtkIdType n = meshGrid->GetNumberOfCells();
    std::set<std::string> keys;
    std::vector<std::string> cellKeys(static_cast<size_t>(n));
    for (vtkIdType i = 0; i < n; ++i) {
        const int t = celltypeArr->GetValue(i);
        cellKeys[static_cast<size_t>(i)] = FemVisibilityMask::cellTypeKey(t);
        keys.insert(cellKeys[static_cast<size_t>(i)]);
    }

    std::vector<std::string> sorted(keys.begin(), keys.end());
    std::sort(sorted.begin(), sorted.end());
    for (const auto& key : sorted) {
        ensureCategory(m_categories, m_keyToIndex, key, key);
    }

    m_cellCategory.resize(static_cast<size_t>(n), 0);
    for (vtkIdType i = 0; i < n; ++i) {
        m_cellCategory[static_cast<size_t>(i)] = m_keyToIndex[cellKeys[static_cast<size_t>(i)]];
    }
}

std::vector<Category> CellTypeClassification::categories() const
{
    return m_categories;
}

int CellTypeClassification::categoryOfElement(const std::string& /*element*/) const
{
    // Cell type is mesh-local; geometry elements have no cell-type category.
    return 0;
}

int CellTypeClassification::categoryOfCell(vtkIdType cell) const
{
    if (cell < 0 || static_cast<size_t>(cell) >= m_cellCategory.size()) {
        return 0;
    }
    return m_cellCategory[static_cast<size_t>(cell)];
}
