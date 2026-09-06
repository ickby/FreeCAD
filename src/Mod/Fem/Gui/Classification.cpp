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
#include "FemPerfLog.h"
#include "FemVisibilityMask.h"

#include <App/DocumentObject.h>
#include <App/DocumentObjectGroup.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <Base/Console.h>
#include <Base/Tools.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemGeometry.h>
#include <Mod/Fem/App/FemTopology.h>
#include <Mod/Fem/App/FemTools.h>

using namespace FemGui;

namespace
{

int ensureCategory(
    std::vector<Category>& categories,
    std::map<std::string, int>& keyToIndex,
    const std::string& key,
    const std::string& label,
    const std::map<std::string, int>* paletteOrder = nullptr,
    int forcedPaletteIndex = -1
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
    int palette = forcedPaletteIndex;
    if (palette < 0 && paletteOrder) {
        auto pit = paletteOrder->find(key);
        if (pit != paletteOrder->end()) {
            palette = pit->second;
        }
    }
    if (palette < 0) {
        palette = idx;
    }
    cat.color = Classification::colorForIndex(palette);
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
    // A toplevel in its own right answers for itself, whoever else owns it. An
    // embedded shell is a face of the solid it was fused into, so the solid can
    // be the first owner and paint the shell in its colour -- and that patch is
    // out where it can be seen, unlike the face two solids share. What is being
    // looked at there is the shell, so it is the shell's colour it wants.
    if (std::find(owners.begin(), owners.end(), entity) != owners.end()) {
        return entity;
    }
    // Otherwise the first owner speaks for it. A face between two solids is
    // inside the model and takes one of the two, whichever comes first.
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

}  // namespace

std::vector<Category> Classification::categories() const
{
    return m_categories;
}

int Classification::categoryOfCell(vtkIdType cell) const
{
    if (cell < 0 || static_cast<size_t>(cell) >= m_cellCategory.size()) {
        return 0;
    }
    return m_cellCategory[static_cast<size_t>(cell)];
}

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

Base::Color Classification::constructionColor(const Base::Color& color)
{
    // Far enough towards a light grey to read as scaffolding at a glance, not
    // so far that two of them stop being different colours.
    constexpr float Target = 0.82f;
    constexpr float Mix = 0.55f;
    auto wash = [](float c) { return c + (Target - c) * Mix; };
    return Base::Color(wash(color.r), wash(color.g), wash(color.b), color.a);
}

std::unique_ptr<Classification> Classification::create(
    ColorMode mode,
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource,
    const Fem::AnalysisTopology* meshTopology,
    const std::map<std::string, int>* paletteOrder
)
{
    FEM_PERF_SCOPE("classification.build");

    switch (mode) {
        case ColorMode::Component:
            return std::make_unique<ComponentClassification>(
                analysis,
                geometry,
                meshGrid,
                gridSource,
                meshTopology,
                paletteOrder
            );
        case ColorMode::Material:
            return std::make_unique<MaterialClassification>(
                analysis,
                geometry,
                meshGrid,
                gridSource,
                paletteOrder
            );
        case ColorMode::CellType:
            return std::make_unique<CellTypeClassification>(meshGrid, geometry, gridSource);
        case ColorMode::Subelement:
        default:
            return std::make_unique<SubelementClassification>(
                analysis,
                geometry,
                meshGrid,
                gridSource,
                // Mesh catch-alls belong in the key set so a mesh-only name
                // cannot shift the colours of the geometry elements around it.
                meshTopology,
                paletteOrder
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
    const GridSource& gridSource,
    const Fem::AnalysisTopology* meshTopology,
    const std::map<std::string, int>* paletteOrder
)
    : Classification(geometry)
{
    build(analysis, geometry, meshGrid, gridSource, meshTopology, paletteOrder);
}

void SubelementClassification::build(
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource,
    const Fem::AnalysisTopology* meshTopology,
    const std::map<std::string, int>* paletteOrder
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

    // Mesh catch-alls (ComponentN_Volume, …) that geometry never names. Asking
    // the topology rather than scanning the grid keeps the category set stable
    // without a VTK walk, and puts them in the shared palette order so they
    // cannot shove Solid1 onto a different colour.
    if (meshTopology) {
        const auto n = meshTopology->componentCount();
        for (Fem::componentIdType i = 0; i < n; ++i) {
            for (const auto& name : meshTopology->toplevelElements(i)) {
                entities.insert(name);
            }
        }
        for (const auto& [component, elements] : Fem::Tools::importedMeshComponents(analysis)) {
            (void)component;
            entities.insert(elements.begin(), elements.end());
        }
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
        ensureCategory(m_categories, m_keyToIndex, key, key, paletteOrder);
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

// ---------------------------------------------------------------------------
// ComponentClassification
// ---------------------------------------------------------------------------

ComponentClassification::ComponentClassification(
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource,
    const Fem::AnalysisTopology* meshTopology,
    const std::map<std::string, int>* paletteOrder
)
    : Classification(geometry)
{
    build(analysis, geometry, meshGrid, gridSource, meshTopology, paletteOrder);
}

void ComponentClassification::build(
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource,
    const Fem::AnalysisTopology* meshTopology,
    const std::map<std::string, int>* paletteOrder
)
{
    m_categories.clear();
    m_keyToIndex.clear();
    m_elementCategory.clear();
    m_cellCategory.clear();

    auto addComponent = [this, paletteOrder](
                            const std::string& key,
                            const std::vector<std::string>& elements,
                            int forcedPalette = -1
                        ) {
        const int index =
            ensureCategory(m_categories, m_keyToIndex, key, key, paletteOrder, forcedPalette);
        for (const auto& element : elements) {
            m_elementCategory[element] = index;
        }
        return index;
    };

    // Geometry toplevel -> 0-based geometry component id, for anchoring a mesh
    // component onto the colour of the geometry piece it mostly overlaps.
    std::map<std::string, Fem::componentIdType> geomTopToComp;
    if (geometry) {
        const auto n = geometry->componentCount();
        for (Fem::componentIdType i = 0; i < n; ++i) {
            for (const auto& name : geometry->toplevelElements(i)) {
                geomTopToComp[name] = i;
            }
        }
    }

    // Past everything the analysis-wide order has spoken for, so a component the
    // geometry knows nothing about cannot land on a colour that is already
    // meaningful. Indices a whole palette apart are the same colour, so the
    // search compares hues; once every hue is taken it has to repeat one.
    const int paletteSize = static_cast<int>(FemMeshRenderer::distinctColors().size());
    auto nextFreePalette = [paletteOrder, paletteSize](const std::set<int>& used) {
        int candidate = 0;
        if (paletteOrder) {
            for (const auto& [key, idx] : *paletteOrder) {
                (void)key;
                candidate = std::max(candidate, idx + 1);
            }
        }
        if (paletteSize <= 0) {
            return candidate;
        }
        const auto hue = [paletteSize](int idx) {
            return ((idx % paletteSize) + paletteSize) % paletteSize;
        };
        std::set<int> usedHues;
        for (int idx : used) {
            usedHues.insert(hue(idx));
        }
        for (int step = 0; step < paletteSize && usedHues.contains(hue(candidate)); ++step) {
            ++candidate;
        }
        return candidate;
    };

    if (meshTopology) {
        // Mesh components first, anchored onto the geometry colours they share
        // the most toplevels with. Ties go to the lowest geometry component id.
        // An already-claimed geometry colour, or no overlap at all, takes the
        // next free palette slot.
        std::set<int> claimedPalette;
        const auto n = meshTopology->componentCount();
        for (Fem::componentIdType i = 0; i < n; ++i) {
            const auto tops = meshTopology->toplevelElements(i);
            std::map<Fem::componentIdType, int> overlap;
            for (const auto& name : tops) {
                auto it = geomTopToComp.find(name);
                if (it != geomTopToComp.end()) {
                    ++overlap[it->second];
                }
            }
            int forced = -1;
            if (!overlap.empty()) {
                Fem::componentIdType best = overlap.begin()->first;
                int bestCount = overlap.begin()->second;
                for (const auto& [comp, count] : overlap) {
                    if (count > bestCount || (count == bestCount && comp < best)) {
                        best = comp;
                        bestCount = count;
                    }
                }
                const std::string geomKey = "Component" + std::to_string(best + 1);
                if (paletteOrder) {
                    auto pit = paletteOrder->find(geomKey);
                    if (pit != paletteOrder->end() && !claimedPalette.count(pit->second)) {
                        forced = pit->second;
                    }
                }
                else if (!claimedPalette.count(static_cast<int>(best))) {
                    forced = static_cast<int>(best);
                }
            }
            if (forced < 0) {
                forced = nextFreePalette(claimedPalette);
            }
            claimedPalette.insert(forced);
            addComponent("Component" + std::to_string(i + 1), tops, forced);
        }

        // The same anchoring for the imports, whose elements carry the path of
        // the instance they came from ("Import.Solid1") and whose component keys
        // carry it too ("Import.Component1"). One pass over the geometry side
        // names the owner of every element; the path makes each one unique, so
        // there is no need to match import against import afterwards.
        std::map<std::string, std::string> geomImportOwner;
        for (const auto& [geomComp, geomElements] : Fem::Tools::importedComponents(analysis)) {
            for (const auto& path : geomElements) {
                geomImportOwner.emplace(path, geomComp);
            }
        }

        for (const auto& [component, elements] : Fem::Tools::importedMeshComponents(analysis)) {
            std::map<std::string, int> overlap;
            for (const auto& path : elements) {
                auto it = geomImportOwner.find(path);
                if (it != geomImportOwner.end()) {
                    ++overlap[it->second];
                }
            }
            int forced = -1;
            if (!overlap.empty()) {
                std::string best = overlap.begin()->first;
                int bestCount = overlap.begin()->second;
                for (const auto& [comp, count] : overlap) {
                    if (count > bestCount || (count == bestCount && comp < best)) {
                        best = comp;
                        bestCount = count;
                    }
                }
                if (paletteOrder) {
                    auto pit = paletteOrder->find(best);
                    if (pit != paletteOrder->end() && !claimedPalette.count(pit->second)) {
                        forced = pit->second;
                    }
                }
            }
            if (forced < 0) {
                forced = nextFreePalette(claimedPalette);
            }
            claimedPalette.insert(forced);
            addComponent(component, elements, forced);
        }
    }
    else {
        // Geometry stage: components in geometry order, which is also the order
        // the panel tree lists them in. Component10 sorts before Component2, and
        // the colours would then run in an order nothing else in the UI follows.
        if (geometry) {
            const auto n = geometry->componentCount();
            for (Fem::componentIdType i = 0; i < n; ++i) {
                addComponent("Component" + std::to_string(i + 1), geometry->toplevelElements(i));
            }
        }

        for (const auto& [component, elements] : Fem::Tools::importedComponents(analysis)) {
            addComponent(component, elements);
        }
    }

    if (meshGrid) {
        const vtkIdType n = meshGrid->GetNumberOfCells();
        m_cellCategory.assign(static_cast<size_t>(n), 0);
        for (vtkIdType i = 0; i < n; ++i) {
            for (const auto& key : cellKeyCandidates(meshGrid, i, geometry, gridSource)) {
                auto it = m_elementCategory.find(key);
                if (it != m_elementCategory.end()) {
                    m_cellCategory[static_cast<size_t>(i)] = it->second;
                    break;
                }
            }
        }
    }
}

int ComponentClassification::categoryOfElement(const std::string& element) const
{
    // A component is asked about by name where the panel tree colours its row
    auto known = m_keyToIndex.find(element);
    if (known != m_keyToIndex.end()) {
        return known->second;
    }
    auto it = m_elementCategory.find(element);
    if (it != m_elementCategory.end()) {
        return it->second;
    }
    // Sub-entity (Face7): resolve to owning toplevel (Solid3), then its component
    const auto top = toplevelOfEntity(m_geometry, element);
    if (top != element) {
        it = m_elementCategory.find(top);
        if (it != m_elementCategory.end()) {
            return it->second;
        }
    }
    return 0;
}

// ---------------------------------------------------------------------------
// MaterialClassification
// ---------------------------------------------------------------------------

MaterialClassification::MaterialClassification(
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource,
    const std::map<std::string, int>* paletteOrder
)
    : Classification(geometry)
{
    build(analysis, geometry, meshGrid, gridSource, paletteOrder);
}

void MaterialClassification::build(
    Fem::FemAnalysis* analysis,
    Fem::FemGeometry* geometry,
    vtkUnstructuredGrid* meshGrid,
    const GridSource& gridSource,
    const std::map<std::string, int>* paletteOrder
)
{
    m_categories.clear();
    m_keyToIndex.clear();
    m_elementCategory.clear();
    m_cellCategory.clear();

    // Which material every element was given is a question the solve asks too,
    // so it is answered in App and only turned into colours here.
    const auto materials = Fem::Tools::analysisMaterials(analysis);
    const auto elementMaterial = Fem::Tools::materialOfElements(analysis, geometry, materials);

    // An element App left out is one no material names, and that is a category
    // of its own here: the panel has to be able to show what was forgotten.
    std::vector<std::string> missed;
    for (const auto& element : Fem::Tools::analysisToplevelElements(analysis, geometry)) {
        if (!elementMaterial.count(element)) {
            missed.push_back(element);
        }
    }

    std::map<std::string, std::string> elementToMatKey;
    for (const auto& [element, material] : elementMaterial) {
        elementToMatKey[element] = material.key;
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
        ensureCategory(m_categories, m_keyToIndex, key, label, paletteOrder);
    }

    if (!missed.empty()) {
        ensureCategory(m_categories, m_keyToIndex, NoMaterialKey, "no material", paletteOrder);
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

// ---------------------------------------------------------------------------
// CellTypeClassification
// ---------------------------------------------------------------------------

CellTypeClassification::CellTypeClassification(
    vtkUnstructuredGrid* meshGrid,
    Fem::FemGeometry* geometry,
    const GridSource& gridSource
)
{
    build(meshGrid, geometry, gridSource);
}

void CellTypeClassification::build(
    vtkUnstructuredGrid* meshGrid,
    Fem::FemGeometry* geometry,
    const GridSource& gridSource
)
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

    // Which side of the analysis every cell falls on. Cheap enough to ask for
    // outright: the answer only moves when the geometry does, and that is what
    // throws this whole classification away. The names on the grid of a placed
    // instance belong to the analysis it was meshed in, so it is that geometry
    // the split has to be read against, the same one the mask reads.
    const auto* owner = gridSource.geometry ? gridSource.geometry : geometry;
    const auto analysis = FemVisibilityMask::analysisCells(meshGrid, owner);

    // Base type of a cell, and the two-sided key it is filtered and coloured by.
    std::vector<std::string> cellKeys(static_cast<size_t>(n));
    std::set<std::string> baseKeys;
    // key -> (base type, construction), in the order categories will be numbered
    std::set<std::pair<std::string, bool>> present;
    for (vtkIdType i = 0; i < n; ++i) {
        const int t = celltypeArr->GetValue(i);
        const bool construction =
            static_cast<size_t>(i) < analysis.size() && analysis[static_cast<size_t>(i)] == 0;
        const std::string base = FemVisibilityMask::cellTypeKey(t);
        cellKeys[static_cast<size_t>(i)] = FemVisibilityMask::cellTypeKey(t, construction);
        baseKeys.insert(base);
        present.insert({base, construction});
    }

    // The colour belongs to the base type, so the two sides of a type stay one
    // hue apart from every other type instead of taking a palette slot each.
    // The slot is asked of the type itself rather than counted off the types
    // this grid holds: the tree shows the meshes of the analysis as one list,
    // and ranking each mesh on its own would give the first type of every mesh
    // the same colour.
    std::map<std::string, int> baseIndex;
    for (const auto& base : baseKeys) {
        baseIndex[base] = FemVisibilityMask::cellTypeOrder(base);
    }

    for (const auto& [base, construction] : present) {
        Category cat;
        cat.key = construction ? base + FemVisibilityMask::ConstructionSuffix : base;
        // The group the tree hangs the row under already says "construction",
        // so the label stays the bare type name on both sides.
        cat.label = base;
        cat.construction = construction;
        const Base::Color color = Classification::colorForIndex(baseIndex[base]);
        cat.color = construction ? Classification::constructionColor(color) : color;
        m_keyToIndex[cat.key] = static_cast<int>(m_categories.size());
        m_categories.push_back(std::move(cat));
    }

    m_cellCategory.resize(static_cast<size_t>(n), 0);
    for (vtkIdType i = 0; i < n; ++i) {
        const int idx = m_keyToIndex[cellKeys[static_cast<size_t>(i)]];
        m_cellCategory[static_cast<size_t>(i)] = idx;
        ++m_categories[static_cast<size_t>(idx)].count;
    }
}

int CellTypeClassification::categoryOfElement(const std::string& /*element*/) const
{
    // Cell type is mesh-local; geometry elements have no cell-type category.
    return 0;
}

