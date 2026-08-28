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
#include <App/DocumentObjectGroup.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <App/SuppressibleExtension.h>
#include <Base/Console.h>
#include <Base/Tools.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemAnalysisImport.h>
#include <Mod/Fem/App/FemGeometry.h>
#include <Mod/Fem/App/FemTools.h>

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

/**
 * Category keys a grid cell may belong to, best match first.
 *
 * The names on a grid are those of the analysis the mesh was built in, so for
 * an instance they have to be read under the path it is addressed by. An
 * instance never names a native element, hence no unprefixed fallback.
 */
std::vector<std::string> cellKeyCandidates(
    vtkUnstructuredGrid* grid,
    vtkIdType cell,
    const Fem::FemGeometry* analysisGeometry,
    const GridSource& source
)
{
    const std::string entity = FemVisibilityMask::entityOfCell(grid, cell);
    if (entity.empty()) {
        return {};
    }
    const Fem::FemGeometry* owner = source.geometry ? source.geometry : analysisGeometry;
    const std::string top = toplevelOfEntity(owner, entity);

    std::vector<std::string> keys;
    keys.push_back(source.pathPrefix + top);
    if (top != entity) {
        keys.push_back(source.pathPrefix + entity);
    }
    return keys;
}

struct MatInfo
{
    App::DocumentObject* obj {nullptr};
    std::string key;
    std::string label;
    bool emptyRefs {false};
    std::vector<std::string> refs;
};

void appendMaterialRef(
    App::DocumentObject* obj,
    const std::string& sub,
    std::vector<std::string>& refs
)
{
    std::string name = sub;
    while (!name.empty() && name.back() == '.') {
        name.pop_back();
    }
    if (name.empty()) {
        return;
    }
    if (auto* imp = Base::freecad_cast<Fem::FemAnalysisImport*>(obj)) {
        const char* impName = imp->getNameInDocument();
        refs.push_back(std::string(impName ? impName : "Import") + "." + name);
        return;
    }
    // A pick on the geometry chain carries the object path in front of the
    // element; only the element itself names anything of the shape.
    const auto pos = name.find_last_of('.');
    if (pos != std::string::npos) {
        name = name.substr(pos + 1);
    }
    if (!name.empty()) {
        refs.push_back(name);
    }
}

void expandEmptyImportMaterialRefs(
    Fem::FemAnalysisImport* imp,
    const std::string& pathPrefix,
    std::vector<std::string>& refs
)
{
    auto* src = Base::freecad_cast<Fem::FemAnalysis*>(imp->Analysis.getValue());
    auto* srcGeom = Fem::Tools::getAnalysisGeometry(src);
    if (!srcGeom) {
        return;
    }
    const char* impName = imp->getNameInDocument();
    const std::string base = pathPrefix.empty()
        ? std::string(impName ? impName : "Import")
        : pathPrefix;
    const auto n = srcGeom->getComponents().size();
    for (Fem::componentIdType i = 0; i < n; ++i) {
        for (const auto& name : srcGeom->getToplevelElements(i)) {
            refs.push_back(base + "." + name);
        }
    }
}

std::string materialColourKey(App::DocumentObject* obj)
{
    if (auto* nameProp = dynamic_cast<App::PropertyString*>(obj->getPropertyByName("MaterialName"))) {
        const char* value = nameProp->getValue();
        if (value && *value) {
            return value;
        }
    }
    return obj->getNameInDocument() ? obj->getNameInDocument() : "Material";
}

bool appendMaterial(App::DocumentObject* obj, std::vector<MatInfo>& materials)
{
    auto* prop = dynamic_cast<App::PropertyLinkSubList*>(obj->getPropertyByName("References"));
    if (!prop || !obj->getPropertyByName("Material")) {
        return false;
    }

    MatInfo info;
    info.obj = obj;
    info.key = obj->getNameInDocument() ? obj->getNameInDocument() : "Material";
    if (auto* nameProp = dynamic_cast<App::PropertyString*>(obj->getPropertyByName("MaterialName"))) {
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
                appendMaterialRef(subset.first, sub, info.refs);
            }
        }
        if (info.refs.empty()) {
            info.emptyRefs = true;
        }
    }

    materials.push_back(std::move(info));
    return true;
}

/**
 * Materials of the analyses reached through *analysis*' imports.
 *
 * Recursive, so a nested import contributes too, and keyed by the whole import
 * chain the way femtools/importmembers.py names its member views, which keeps
 * the colour keys and the solver member names in step.
 *
 * An inherited material with empty references means "everything of its source
 * analysis", so it is expanded to just that import's elements. It must not
 * become the catch-all for the importing analysis, which is why the empty-ref
 * bookkeeping of the native pass is deliberately not shared with this one.
 */
void appendInheritedMaterials(
    const Fem::FemAnalysis* analysis,
    const std::string& keyPrefix,
    std::vector<const Fem::FemAnalysisImport*>& chain,
    std::vector<MatInfo>& materials
)
{
    for (auto* imp : Fem::Tools::analysisImports(analysis)) {
        if (std::ranges::find(chain, imp) != chain.end()) {
            continue;
        }
        auto* src = Base::freecad_cast<Fem::FemAnalysis*>(imp->Analysis.getValue());
        if (!src) {
            continue;
        }
        const char* name = imp->getNameInDocument();
        const std::string pathPrefix =
            keyPrefix.empty() ? std::string(name ? name : "Import")
                              : keyPrefix + "." + (name ? name : "Import");

        chain.push_back(imp);
        for (auto* obj : src->Group.getValues()) {
            if (!obj || Fem::Tools::isMemberSuppressed(chain, obj)) {
                continue;
            }
            if (obj->hasExtension(App::SuppressibleExtension::getExtensionClassTypeId())
                && obj->getExtensionByType<App::SuppressibleExtension>()->Suppressed.getValue()) {
                continue;
            }
            if (!appendMaterial(obj, materials)) {
                continue;
            }
            MatInfo& added = materials.back();
            added.key = materialColourKey(obj);
            if (added.emptyRefs) {
                added.refs.clear();
                expandEmptyImportMaterialRefs(imp, pathPrefix, added.refs);
                added.emptyRefs = added.refs.empty();
            }
            else {
                std::vector<std::string> pathRefs;
                for (const auto& ref : added.refs) {
                    pathRefs.push_back(pathPrefix + "." + ref);
                }
                added.refs = std::move(pathRefs);
            }
        }

        appendInheritedMaterials(src, pathPrefix, chain, materials);
        chain.pop_back();
    }
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
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource
)
{
    switch (mode) {
        case ColorMode::Toplevel:
            return std::make_unique<ToplevelClassification>(
                analysis,
                geometry,
                meshGrid,
                gridSource
            );
        case ColorMode::Material:
            return std::make_unique<MaterialClassification>(
                analysis,
                geometry,
                meshGrid,
                gridSource
            );
        case ColorMode::CellType:
            return std::make_unique<CellTypeClassification>(meshGrid);
        case ColorMode::Subelement:
        default:
            return std::make_unique<SubelementClassification>(
                analysis,
                geometry,
                meshGrid,
                gridSource
            );
    }
}

// ---------------------------------------------------------------------------
// SubelementClassification
// ---------------------------------------------------------------------------

SubelementClassification::SubelementClassification(
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource
)
    : m_geometry(geometry)
{
    build(analysis, geometry, meshGrid, gridSource);
}

void SubelementClassification::build(
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource
)
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

    // A placed instance brings elements of its own, named by the path to them,
    // and each wants a colour of its own just like a native element.
    for (const auto& path : Fem::Tools::importedToplevelElements(analysis)) {
        entities.insert(path);
    }

    if (meshGrid) {
        const vtkIdType n = meshGrid->GetNumberOfCells();
        for (vtkIdType i = 0; i < n; ++i) {
            // Resolve FaceN/EdgeN under a solid to the owning toplevel so mesh
            // categories match geometry / the view-panel tree (solids stay
            // per-toplevel; free faces keep their own key).
            const auto keys = cellKeyCandidates(meshGrid, i, geometry, gridSource);
            if (!keys.empty()) {
                entities.insert(keys.front());
            }
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
            for (const auto& key : cellKeyCandidates(meshGrid, i, geometry, gridSource)) {
                auto it = m_keyToIndex.find(key);
                if (it != m_keyToIndex.end()) {
                    m_cellCategory[static_cast<size_t>(i)] = it->second;
                    break;
                }
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
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource
)
    : m_geometry(geometry)
{
    build(analysis, geometry, meshGrid, gridSource);
}

void ToplevelClassification::build(
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource
)
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

    for (const auto& path : Fem::Tools::importedToplevelElements(analysis)) {
        toplevels.insert(path);
    }

    if (meshGrid) {
        const vtkIdType n = meshGrid->GetNumberOfCells();
        for (vtkIdType i = 0; i < n; ++i) {
            const auto keys = cellKeyCandidates(meshGrid, i, geometry, gridSource);
            if (!keys.empty()) {
                toplevels.insert(keys.front());
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
            for (const auto& key : cellKeyCandidates(meshGrid, i, geometry, gridSource)) {
                auto it = m_keyToIndex.find(key);
                if (it != m_keyToIndex.end()) {
                    m_cellCategory[static_cast<size_t>(i)] = it->second;
                    break;
                }
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
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource
)
    : m_geometry(geometry)
{
    build(analysis, geometry, meshGrid, gridSource);
}

void MaterialClassification::build(
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource
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
    // What an instance places needs a material as much as a native element,
    // and says "no material" just as loudly when it has none.
    for (const auto& path : Fem::Tools::importedToplevelElements(analysis)) {
        allElements.insert(path);
    }

    std::vector<MatInfo> materials;
    int emptyRefIndex = -1;

    if (analysis) {
        for (auto* obj : analysis->Group.getValues()) {
            if (!obj) {
                continue;
            }
            if (appendMaterial(obj, materials) && materials.back().emptyRefs
                && emptyRefIndex < 0) {
                // Only a material of this analysis may claim what no other
                // material names; an inherited one is capped at its import.
                emptyRefIndex = static_cast<int>(materials.size()) - 1;
            }
        }
        std::vector<const Fem::FemAnalysisImport*> chain;
        appendInheritedMaterials(analysis, std::string(), chain, materials);
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
            const auto keys = cellKeyCandidates(meshGrid, i, geometry, gridSource);
            if (keys.empty()) {
                continue;
            }
            auto it = m_elementCategory.end();
            for (const auto& key : keys) {
                it = m_elementCategory.find(key);
                if (it != m_elementCategory.end()) {
                    break;
                }
            }
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
