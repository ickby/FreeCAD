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
# include <Inventor/nodes/SoSeparator.h>
# include <vtkAbstractArray.h>
#endif

#include "FemPreprocessMeshViewHelper.h"

#include <Gui/ViewProviderDocumentObject.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemGeometry.h>
#include <Mod/Fem/App/FemMesh.h>
#include <Mod/Fem/App/FemVTKTools.h>
#include <Mod/Part/App/TopoShape.h>

#include "FemPerfLog.h"
#include "FemVisibilityMask.h"

using namespace FemGui;

FemPreprocessMeshViewHelper::FemPreprocessMeshViewHelper() = default;

FemPreprocessMeshViewHelper::~FemPreprocessMeshViewHelper()
{
    disconnectViewState();
}

void FemPreprocessMeshViewHelper::ensureDisplayModes(SoSeparator* hiddenSeparator)
{
    if (!m_viewProvider || m_displayModesAdded) {
        m_hidden = hiddenSeparator;
        return;
    }
    m_hidden = hiddenSeparator;
    m_viewProvider->addDisplayMaskMode(m_renderer.root(), ViewMode::Preprocess);
    if (m_hidden) {
        m_viewProvider->addDisplayMaskMode(m_hidden, ViewMode::PreprocessHidden);
    }
    m_displayModesAdded = true;
}

bool FemPreprocessMeshViewHelper::hasDisplayModes() const
{
    return m_displayModesAdded;
}

void FemPreprocessMeshViewHelper::invalidateMesh()
{
    m_built = false;
}

bool FemPreprocessMeshViewHelper::isBuilt() const
{
    return m_built;
}

FemMeshRenderer& FemPreprocessMeshViewHelper::renderer()
{
    return m_renderer;
}

void FemPreprocessMeshViewHelper::setElementSubsetMask(std::vector<unsigned char> mask)
{
    if (m_elementSubsetMask == mask) {
        return;
    }
    m_elementSubsetMask = std::move(mask);
    // The subset is folded into the masks, so what was worked out under the
    // previous one says nothing about what this one hides.
    m_viewStateCacheValid = false;
}

void FemPreprocessMeshViewHelper::applyElementSubset(std::vector<unsigned char>& visibility) const
{
    if (m_elementSubsetMask.empty()) {
        return;
    }
    if (m_cellElementIds.size() != visibility.size()) {
        Base::Console().warning(
            "FemPreprocessMeshViewHelper: cell/element id mapping does not match the grid, "
            "rendering the whole mesh.\n"
        );
        return;
    }

    for (std::size_t cell = 0; cell < visibility.size(); ++cell) {
        const int elementId = m_cellElementIds[cell];
        const auto index = static_cast<std::size_t>(elementId - 1);
        if (elementId < 1 || index >= m_elementSubsetMask.size()
            || m_elementSubsetMask[index] == 0) {
            visibility[cell] = 0;
        }
    }
}

void FemPreprocessMeshViewHelper::onViewStateBound()
{
    registerGrid();
}

void FemPreprocessMeshViewHelper::onViewStateUnbound(AnalysisViewState* state)
{
    if (AnalysisViewState::isAlive(state)) {
        state->unregisterMeshGrid(m_registeredGrid);
    }
    m_registeredGrid = nullptr;
}

/// Hand the current grid to the bound state, taking back whatever it held before.
void FemPreprocessMeshViewHelper::registerGrid()
{
    if (!boundViewState() || !AnalysisViewState::isAlive(boundViewState())
        || m_registeredGrid == m_vtkmesh.Get()) {
        return;
    }
    boundViewState()->unregisterMeshGrid(m_registeredGrid);
    m_registeredGrid = m_vtkmesh.Get();
    boundViewState()->registerMeshGrid(
        m_registeredGrid,
        GridSource {m_pathPrefix, m_findGeometry ? m_findGeometry() : nullptr}
    );
}

void FemPreprocessMeshViewHelper::buildGrid(
    const Fem::FemMesh& femMesh,
    vtkUnstructuredGrid* grid,
    std::vector<int>& cellElementIds
)
{
    cellElementIds.clear();
    if (!grid) {
        return;
    }
    FEM_PERF_SCOPE("mesh.buildGrid");

    {
        // Keep all dimensions; FemVisibilityMask filters for display.
        FEM_PERF_SCOPE("mesh.buildGrid.exportMesh");
        Fem::FemVTKTools::exportVTKMesh(&femMesh, grid, false, 1.0, &cellElementIds);
    }

    // String entity names (Face7, Solid3, ...) when groups are present.
    try {
        FEM_PERF_SCOPE("mesh.buildGrid.exportCellGroups");
        Fem::FemVTKTools::exportVTKCellGroup(
            const_cast<Fem::FemMesh*>(&femMesh),
            grid,
            FemVisibilityMask::ArrayEntityIds,
            {},
            cellElementIds
        );
    }
    catch (const std::exception& e) {
        Base::Console().warning("FemPreprocessMeshViewHelper: cell group export failed: %s\n", e.what());
    }
}

void FemPreprocessMeshViewHelper::updateFromFemMesh(const Fem::FemMesh& femMesh)
{
    m_vtkmesh = vtkSmartPointer<vtkUnstructuredGrid>::New();
    buildGrid(femMesh, m_vtkmesh, m_cellElementIds);

    m_renderer.setMesh(m_vtkmesh);
    m_viewStateCacheValid = false;
    // An empty grid means the property has not delivered its data yet (restore
    // reads the mesh file after the view providers). Stay unbuilt so the next
    // trigger retries instead of showing nothing forever.
    m_built = m_vtkmesh->GetNumberOfCells() > 0;
    ensureViewStateConnection();
    registerGrid();
    applyViewState(true);
}

void FemPreprocessMeshViewHelper::updateFromSharedGrid(
    vtkUnstructuredGrid* sourceGrid,
    const std::vector<int>& cellElementIds
)
{
    if (!sourceGrid || sourceGrid->GetNumberOfCells() == 0) {
        m_built = false;
        return;
    }

    m_vtkmesh = vtkSmartPointer<vtkUnstructuredGrid>::New();
    m_vtkmesh->ShallowCopy(sourceGrid);

    auto* srcCd = sourceGrid->GetCellData();
    auto* dstCd = m_vtkmesh->GetCellData();
    if (srcCd && dstCd) {
        dstCd->Initialize();
        const int nArrays = srcCd->GetNumberOfArrays();
        for (int i = 0; i < nArrays; ++i) {
            // Abstract rather than data arrays: the element names each cell
            // belongs to are strings, and leaving them behind leaves the
            // instance with a mesh nothing can be hidden or coloured by.
            vtkAbstractArray* srcArr = srcCd->GetAbstractArray(i);
            if (!srcArr) {
                continue;
            }
            vtkAbstractArray* copy = srcArr->NewInstance();
            copy->DeepCopy(srcArr);
            dstCd->AddArray(copy);
            copy->Delete();
        }
    }

    m_cellElementIds = cellElementIds;
    m_renderer.setMesh(m_vtkmesh);
    m_viewStateCacheValid = false;
    m_built = true;
    ensureViewStateConnection();
    registerGrid();
    applyViewState(true);
}

void FemPreprocessMeshViewHelper::applyViewState(bool meshChanged)
{
    FEM_PERF_SCOPE("mesh.applyViewState");

    ensureViewStateConnection();
    auto* state = effectiveViewState();
    auto* geometry = m_findGeometry ? m_findGeometry() : nullptr;

    if (!state) {
        auto visibility =
            FemVisibilityMask::evaluate(m_vtkmesh, geometry, DimensionMode::Highest, false, {}, {});
        applyElementSubset(visibility);
        m_renderer.setVisibilityMask(visibility);
        m_renderer.setClipPlanes({});
        m_renderer.setOverlayMask({});
        m_renderer.setWireframe(false);
        m_renderer.setClassification(nullptr);
        m_renderer.update();
        m_viewStateCacheValid = false;
        return;
    }

    const DimensionMode dimMode = state->dimensionMode();
    const bool showConstruction = state->showConstruction();
    const bool wireframe = state->wireframe();
    const ColorMode colorMode = state->colorMode();
    const auto hidden = localHiddenElements(state->hiddenElements());
    const auto& hiddenTypes = state->hiddenCellTypes();
    const auto clips = localClipPlanes(state->clipPlanes());

    // Nothing that shapes the masks has moved. That is the usual case, because
    // every helper of the analysis is told of every change, and all but the one
    // or two the change is about see the same state they saw before. The clip
    // plane and the wireframe are not among them: the renderer applies both on
    // top of the masks, so moving a plane leaves what the model hides alone.
    const bool sameMasks = !meshChanged && m_viewStateCacheValid && m_cachedDimMode == dimMode
        && m_cachedShowConstruction == showConstruction && m_cachedHidden == hidden
        && m_cachedHiddenCellTypes == hiddenTypes;
    const bool colorOnly = sameMasks && m_cachedWireframe == wireframe && m_cachedClips == clips
        && m_cachedColorMode != colorMode;

    m_cachedDimMode = dimMode;
    m_cachedShowConstruction = showConstruction;
    m_cachedWireframe = wireframe;
    m_cachedColorMode = colorMode;
    m_cachedHidden = hidden;
    m_cachedHiddenCellTypes = hiddenTypes;
    m_cachedClips = clips;
    m_viewStateCacheValid = true;

    if (colorOnly) {
        {
            FEM_PERF_SCOPE("mesh.classify");
            m_renderer.setClassification(state->classification(m_vtkmesh));
        }
        m_renderer.updateColors();
        return;
    }

    if (!sameMasks) {
        FEM_PERF_SCOPE("mesh.visibilityMask");
        std::map<std::string, int> underAchieved;
        m_cachedVisibility = FemVisibilityMask::evaluate(
            m_vtkmesh,
            geometry,
            dimMode,
            showConstruction,
            hidden,
            hiddenTypes,
            &underAchieved
        );
        applyElementSubset(m_cachedVisibility);
        m_cachedUnderAchieved = std::move(underAchieved);
    }
    state->setUnderAchievedElements(m_cachedUnderAchieved);

    const std::vector<unsigned char>& visibility = m_cachedVisibility;
    m_renderer.setVisibilityMask(visibility);
    m_renderer.setClipPlanes(clips);
    m_renderer.setWireframe(wireframe);

    m_renderer.setOverlay(state->overlay());
    const bool overlayNeeded = state->overlay()
        && (wireframe || !clips.empty() || !hidden.empty() || !hiddenTypes.empty());
    if (overlayNeeded && m_vtkmesh) {
        if (!sameMasks || m_cachedOverlay.empty()) {
            FEM_PERF_SCOPE("mesh.visibilityMask.overlay");
            m_cachedOverlay =
                FemVisibilityMask::evaluate(m_vtkmesh, geometry, dimMode, showConstruction, {}, {});
            applyElementSubset(m_cachedOverlay);
        }
        m_renderer.setOverlayMask(m_cachedOverlay);
    }
    else {
        m_renderer.setOverlayMask({});
    }

    {
        FEM_PERF_SCOPE("mesh.classify");
        m_renderer.setClassification(state->classification(m_vtkmesh));
    }
    m_renderer.update();
}

void FemPreprocessMeshViewHelper::applyViewStateChange()
{
    // Display modes are only added by a helper that owns the stage switch of
    // its view provider. An instance renders under masks its import view
    // provider owns and still has to follow the state.
    if (!m_built) {
        return;
    }
    FEM_PERF_SCOPE("mesh.onViewStateChanged");

    syncStageVisibility();
    applyViewState(false);
}

void FemPreprocessMeshViewHelper::syncStageVisibility()
{
    if (!m_viewProvider || !m_displayModesAdded || !m_manageStageVisibility) {
        return;
    }
    bool meshStage = true;
    if (auto* state = effectiveViewState()) {
        meshStage = (state->activeStage() == ActiveStage::Mesh);
    }
    setStageMask(*m_viewProvider, meshStage ? ViewMode::Preprocess : ViewMode::PreprocessHidden);
}
