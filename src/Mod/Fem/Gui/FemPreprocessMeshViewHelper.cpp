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
# include <Inventor/details/SoFaceDetail.h>
# include <Inventor/details/SoLineDetail.h>
# include <Inventor/details/SoPointDetail.h>
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

#include "FemVisibilityMask.h"

using namespace FemGui;

namespace
{
constexpr const char* PreprocessMode = "Preprocess";
constexpr const char* PreprocessHiddenMode = "PreprocessHidden";

std::string stripTrailingDot(std::string path)
{
    if (!path.empty() && path.back() == '.') {
        path.pop_back();
    }
    return path;
}

bool clipApplies(const ClippingPlane& plane, const std::string& pathPrefix)
{
    if (plane.Scope.empty()) {
        return true;
    }
    const std::string scope = stripTrailingDot(pathPrefix);
    if (scope.empty()) {
        return false;
    }
    return scope == plane.Scope || scope.starts_with(plane.Scope + ".");
}

}  // namespace

void FemPreprocessMeshViewHelper::setPathPrefix(const std::string& prefix)
{
    m_pathPrefix = prefix;
}

void FemPreprocessMeshViewHelper::setSelectionPrefix(const std::string& prefix)
{
    m_selectionPrefix = prefix;
}

void FemPreprocessMeshViewHelper::setLocalFrame(const Base::Placement& placement)
{
    m_localFrame = placement;
    m_viewStateCacheValid = false;
}

void FemPreprocessMeshViewHelper::setManageStageVisibility(bool on)
{
    m_manageStageVisibility = on;
}

std::set<std::string> FemPreprocessMeshViewHelper::localHiddenElements(
    const std::set<std::string>& hidden
) const
{
    std::set<std::string> local;
    if (m_pathPrefix.empty()) {
        for (const auto& name : hidden) {
            if (name.find('.') == std::string::npos) {
                local.insert(name);
            }
        }
        return local;
    }
    for (const auto& name : hidden) {
        if (name.starts_with(m_pathPrefix)) {
            local.insert(name.substr(m_pathPrefix.size()));
        }
    }
    return local;
}

std::map<std::string, ClippingPlane> FemPreprocessMeshViewHelper::localClipPlanes(
    const std::map<std::string, ClippingPlane>& clips
) const
{
    std::map<std::string, ClippingPlane> local;
    const Base::Placement toLocal = m_localFrame.inverse();
    for (const auto& entry : clips) {
        if (!clipApplies(entry.second, m_pathPrefix)) {
            continue;
        }
        // The grid holds the node coordinates of the source analysis while a
        // plane is placed in the frame of the importing one, so the plane has to
        // come back through the instance placement to cut where the user put it.
        ClippingPlane plane = entry.second;
        toLocal.multVec(entry.second.Origin, plane.Origin);
        plane.Direction = toLocal.getRotation().multVec(entry.second.Direction);
        local.emplace(entry.first, plane);
    }
    return local;
}

FemPreprocessMeshViewHelper::FemPreprocessMeshViewHelper() = default;

FemPreprocessMeshViewHelper::~FemPreprocessMeshViewHelper()
{
    disconnectViewState();
}

void FemPreprocessMeshViewHelper::setHost(
    Gui::ViewProviderDocumentObject* viewProvider,
    AnalysisFinder findAnalysis,
    GeometryFinder findGeometry
)
{
    m_viewProvider = viewProvider;
    m_findAnalysis = std::move(findAnalysis);
    m_findGeometry = std::move(findGeometry);
}

void FemPreprocessMeshViewHelper::ensureDisplayModes(SoSeparator* hiddenSeparator)
{
    if (!m_viewProvider || m_displayModesAdded) {
        m_hidden = hiddenSeparator;
        return;
    }
    m_hidden = hiddenSeparator;
    m_viewProvider->addDisplayMaskMode(m_renderer.root(), PreprocessMode);
    if (m_hidden) {
        m_viewProvider->addDisplayMaskMode(m_hidden, PreprocessHiddenMode);
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
    m_elementSubsetMask = std::move(mask);
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

AnalysisViewState* FemPreprocessMeshViewHelper::viewState() const
{
    if (!m_findAnalysis) {
        return nullptr;
    }
    auto* analysis = m_findAnalysis();
    if (!analysis) {
        return nullptr;
    }
    return AnalysisViewState::forAnalysis(analysis);
}

void FemPreprocessMeshViewHelper::disconnectViewState()
{
    m_viewStateConn.disconnect();
    if (m_boundViewState && AnalysisViewState::isAlive(m_boundViewState)) {
        m_boundViewState->unregisterMeshGrid(m_registeredGrid);
    }
    m_registeredGrid = nullptr;
    m_boundViewState = nullptr;
    m_viewStateCacheValid = false;
}

void FemPreprocessMeshViewHelper::connectViewState()
{
    ensureViewStateConnection();
}

void FemPreprocessMeshViewHelper::ensureViewStateConnection()
{
    auto* state = viewState();
    if (state == m_boundViewState && m_viewStateConn.connected()) {
        return;
    }
    disconnectViewState();
    m_boundViewState = state;
    if (state) {
        m_viewStateConn = state->connectChanged([this]() { onViewStateChanged(); });
        registerGrid();
        onViewStateChanged();
    }
}

void FemPreprocessMeshViewHelper::registerGrid()
{
    if (!m_boundViewState || !AnalysisViewState::isAlive(m_boundViewState)
        || m_registeredGrid == m_vtkmesh.Get()) {
        return;
    }
    m_boundViewState->unregisterMeshGrid(m_registeredGrid);
    m_registeredGrid = m_vtkmesh.Get();
    m_boundViewState->registerMeshGrid(
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

    // Keep all dimensions; FemVisibilityMask filters for display.
    Fem::FemVTKTools::exportVTKMesh(&femMesh, grid, false, 1.0, &cellElementIds);

    // String entity names (Face7, Solid3, ...) when groups are present.
    try {
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
    ensureViewStateConnection();
    auto* state = m_boundViewState ? m_boundViewState : viewState();
    auto* geometry = m_findGeometry ? m_findGeometry() : nullptr;

    if (!state) {
        auto visibility =
            FemVisibilityMask::evaluate(m_vtkmesh, geometry, DimensionMode::Highest, {}, {});
        applyElementSubset(visibility);
        m_renderer.setVisibilityMask(visibility);
        m_renderer.setClipPlanes({});
        m_renderer.setOverlayMask({});
        m_renderer.setWireframe(false);
        m_renderer.setClassification(nullptr);
        m_renderer.update();
        rebuildSelectionMaps();
        m_viewStateCacheValid = false;
        return;
    }

    const DimensionMode dimMode = state->dimensionMode();
    const bool wireframe = state->wireframe();
    const ColorMode colorMode = state->colorMode();
    const auto hidden = localHiddenElements(state->hiddenElements());
    const auto& hiddenTypes = state->hiddenCellTypes();
    const auto clips = localClipPlanes(state->clipPlanes());

    const bool colorOnly = !meshChanged && m_viewStateCacheValid && m_cachedDimMode == dimMode
        && m_cachedWireframe == wireframe && m_cachedHidden == hidden
        && m_cachedHiddenCellTypes == hiddenTypes && m_cachedClips == clips
        && m_cachedColorMode != colorMode;

    m_cachedDimMode = dimMode;
    m_cachedWireframe = wireframe;
    m_cachedColorMode = colorMode;
    m_cachedHidden = hidden;
    m_cachedHiddenCellTypes = hiddenTypes;
    m_cachedClips = clips;
    m_viewStateCacheValid = true;

    if (colorOnly) {
        m_renderer.setClassification(state->classification(m_vtkmesh));
        m_renderer.updateColors();
        return;
    }

    std::set<std::string> underAchieved;
    auto visibility = FemVisibilityMask::evaluate(
        m_vtkmesh,
        geometry,
        dimMode,
        hidden,
        hiddenTypes,
        &underAchieved
    );
    state->setUnderAchievedElements(std::move(underAchieved));

    applyElementSubset(visibility);
    m_renderer.setVisibilityMask(visibility);
    m_renderer.setClipPlanes(clips);
    m_renderer.setWireframe(wireframe);

    m_renderer.setOverlay(state->overlay());
    const bool overlayNeeded = state->overlay()
        && (wireframe || !clips.empty() || !hidden.empty() || !hiddenTypes.empty());
    if (overlayNeeded && m_vtkmesh) {
        auto overlayMask = FemVisibilityMask::evaluate(m_vtkmesh, geometry, dimMode, {}, {});
        applyElementSubset(overlayMask);
        m_renderer.setOverlayMask(overlayMask);
    }
    else {
        m_renderer.setOverlayMask({});
    }

    m_renderer.setClassification(state->classification(m_vtkmesh));
    m_renderer.update();
    rebuildSelectionMaps();
}

void FemPreprocessMeshViewHelper::onViewStateChanged()
{
    // Display modes are only added by a helper that owns the stage switch of
    // its view provider. An instance renders under masks its import view
    // provider owns and still has to follow the state.
    if (!m_built) {
        return;
    }
    syncStageVisibility();
    applyViewState(false);
}

void FemPreprocessMeshViewHelper::syncStageVisibility()
{
    if (!m_viewProvider || !m_displayModesAdded || !m_manageStageVisibility) {
        return;
    }
    bool meshStage = true;
    if (auto* state = m_boundViewState ? m_boundViewState : viewState()) {
        meshStage = (state->activeStage() == ActiveStage::Mesh);
    }
    m_viewProvider->setDisplayMaskMode(meshStage ? PreprocessMode : PreprocessHiddenMode);
}

void FemPreprocessMeshViewHelper::rebuildSelectionMaps()
{
    m_faceEntities.clear();
    m_lineEntities.clear();
    m_pointEntities.clear();
    m_entityToFace.clear();
    m_entityToLine.clear();
    m_entityToPoint.clear();

    if (!m_vtkmesh) {
        return;
    }

    auto mapCell = [this](vtkIdType orig, std::vector<std::string>& entities,
                          std::unordered_map<std::string, int>& lookup, int index) {
        std::string entity;
        if (orig >= 0) {
            entity = FemVisibilityMask::entityOfCell(m_vtkmesh, orig);
        }
        entities.push_back(entity);
        if (!entity.empty() && !lookup.count(entity)) {
            lookup[entity] = index;
        }
    };

    auto* visdata = m_renderer.currentPolyData();
    if (!visdata) {
        return;
    }

    const int nFaces = static_cast<int>(visdata->GetNumberOfPolys());
    m_faceEntities.reserve(static_cast<size_t>(nFaces));
    for (int i = 0; i < nFaces; ++i) {
        mapCell(m_renderer.originalCellOfFace(i), m_faceEntities, m_entityToFace, i);
    }

    const int nLines = static_cast<int>(visdata->GetNumberOfLines());
    m_lineEntities.reserve(static_cast<size_t>(nLines));
    for (int i = 0; i < nLines; ++i) {
        mapCell(m_renderer.originalCellOfLine(i), m_lineEntities, m_entityToLine, i);
    }

    const int nVerts = static_cast<int>(visdata->GetNumberOfVerts());
    m_pointEntities.reserve(static_cast<size_t>(nVerts));
    for (int i = 0; i < nVerts; ++i) {
        mapCell(m_renderer.originalCellOfMarker(i), m_pointEntities, m_entityToPoint, i);
    }
}

std::string FemPreprocessMeshViewHelper::elementFromDetail(const SoDetail* detail) const
{
    if (!detail) {
        return {};
    }
    std::string entity;
    if (detail->getTypeId() == SoFaceDetail::getClassTypeId()) {
        const auto* faceDetail = static_cast<const SoFaceDetail*>(detail);
        const int face = faceDetail->getFaceIndex();
        if (face >= 0 && static_cast<size_t>(face) < m_faceEntities.size()) {
            entity = m_faceEntities[static_cast<size_t>(face)];
        }
    }
    else if (detail->getTypeId() == SoLineDetail::getClassTypeId()) {
        const auto* lineDetail = static_cast<const SoLineDetail*>(detail);
        const int line = lineDetail->getLineIndex();
        if (line >= 0 && static_cast<size_t>(line) < m_lineEntities.size()) {
            entity = m_lineEntities[static_cast<size_t>(line)];
        }
    }
    else if (detail->getTypeId() == SoPointDetail::getClassTypeId()) {
        const auto* pointDetail = static_cast<const SoPointDetail*>(detail);
        const int vertex = pointDetail->getCoordinateIndex();
        if (vertex >= 0 && static_cast<size_t>(vertex) < m_pointEntities.size()) {
            entity = m_pointEntities[static_cast<size_t>(vertex)];
        }
    }
    if (entity.empty()) {
        return {};
    }
    if (!m_selectionPrefix.empty()) {
        return m_selectionPrefix + entity;
    }
    return entity;
}

SoDetail* FemPreprocessMeshViewHelper::detailFromElement(const char* subelement) const
{
    if (!subelement || !*subelement) {
        return nullptr;
    }
    std::string name(subelement);
    if (!m_selectionPrefix.empty()) {
        if (name.starts_with(m_selectionPrefix)) {
            name = name.substr(m_selectionPrefix.size());
        }
        else {
            return nullptr;
        }
    }
    else if (name.find('.') != std::string::npos) {
        // Addresses something further in; not an element of this instance.
        return nullptr;
    }
    auto type = Part::TopoShape::getElementTypeAndIndex(name.c_str());
    const std::string& element = type.first;

    if (element == "Face" || element == "Solid" || element.empty()) {
        if (auto it = m_entityToFace.find(name); it != m_entityToFace.end()) {
            auto* detail = new SoFaceDetail();
            detail->setFaceIndex(it->second);
            return detail;
        }
    }
    if (element == "Edge" || element.empty()) {
        if (auto it = m_entityToLine.find(name); it != m_entityToLine.end()) {
            auto* detail = new SoLineDetail();
            detail->setLineIndex(it->second);
            return detail;
        }
    }
    if (element == "Vertex" || element.empty()) {
        if (auto it = m_entityToPoint.find(name); it != m_entityToPoint.end()) {
            auto* detail = new SoPointDetail();
            detail->setCoordinateIndex(it->second);
            return detail;
        }
    }
    if (auto it = m_entityToFace.find(name); it != m_entityToFace.end()) {
        auto* detail = new SoFaceDetail();
        detail->setFaceIndex(it->second);
        return detail;
    }
    if (auto it = m_entityToLine.find(name); it != m_entityToLine.end()) {
        auto* detail = new SoLineDetail();
        detail->setLineIndex(it->second);
        return detail;
    }
    if (auto it = m_entityToPoint.find(name); it != m_entityToPoint.end()) {
        auto* detail = new SoPointDetail();
        detail->setCoordinateIndex(it->second);
        return detail;
    }
    return nullptr;
}
