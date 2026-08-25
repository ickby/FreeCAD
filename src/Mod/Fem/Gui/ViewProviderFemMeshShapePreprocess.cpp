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
# include <cstring>
# include <Inventor/details/SoFaceDetail.h>
# include <Inventor/details/SoLineDetail.h>
# include <Inventor/details/SoPointDetail.h>
# include <Inventor/nodes/SoSeparator.h>
#endif

#include "ViewProviderFemMeshShapePreprocess.h"

#include <Base/Console.h>
#include <Base/Tools.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemGeometry.h>
#include <Mod/Fem/App/FemMeshObject.h>
#include <Mod/Fem/App/FemMeshShapeGroup.h>
#include <Mod/Fem/App/FemMeshShapeObject.h>
#include <Mod/Fem/App/FemVTKTools.h>
#include <Mod/Part/App/TopoShape.h>

#include "FemVisibilityMask.h"

using namespace FemGui;

PROPERTY_SOURCE(FemGui::ViewProviderFemMeshShapePreprocess, FemGui::ViewProviderFemMeshShapeBase)

namespace
{
constexpr const char* PreprocessMode = "Preprocess";
constexpr const char* PreprocessHiddenMode = "PreprocessHidden";
}  // namespace

ViewProviderFemMeshShapePreprocess::ViewProviderFemMeshShapePreprocess()
{
    m_hidden = new SoSeparator();
    m_hidden->ref();
}

ViewProviderFemMeshShapePreprocess::~ViewProviderFemMeshShapePreprocess()
{
    m_viewStateConn.disconnect();
    // AnalysisViewState may already be destroyed (analysis VP tore down first).
    if (m_boundViewState && AnalysisViewState::isAlive(m_boundViewState)) {
        m_boundViewState->unregisterMeshGrid(m_registeredGrid);
    }
    m_boundViewState = nullptr;
    m_registeredGrid = nullptr;
    m_hidden->unref();
}

bool ViewProviderFemMeshShapePreprocess::preprocessActive() const
{
    auto* obj = getObject();
    if (!obj) {
        return false;
    }
    if (auto* shapeBase = Base::freecad_cast<Fem::FemMeshShapeBaseObject*>(obj)) {
        if (Base::freecad_cast<Fem::FemGeometry*>(shapeBase->Components.getValue())) {
            return true;
        }
    }
    for (auto* parent : obj->getInList()) {
        if (Base::freecad_cast<Fem::FemMeshShapeGroup*>(parent)) {
            return true;
        }
    }
    return false;
}

void ViewProviderFemMeshShapePreprocess::attach(App::DocumentObject* pcObject)
{
    ViewProviderFemMeshShapeBase::attach(pcObject);
    syncRepresentation();
}

void ViewProviderFemMeshShapePreprocess::setDisplayMode(const char* ModeName)
{
    if (ModeName && strcmp(ModeName, PreprocessMode) == 0) {
        if (m_preprocessModeAdded) {
            setDisplayMaskMode(PreprocessMode);
        }
        return;
    }
    ViewProviderFemMeshShapeBase::setDisplayMode(ModeName);
}

std::vector<std::string> ViewProviderFemMeshShapePreprocess::getDisplayModes() const
{
    auto modes = ViewProviderFemMeshShapeBase::getDisplayModes();
    if (preprocessActive()) {
        modes.emplace_back(PreprocessMode);
    }
    return modes;
}

void ViewProviderFemMeshShapePreprocess::updateData(const App::Property* prop)
{
    // The legacy representation is always kept up to date so that switching
    // back out of the new workflow, and the legacy postprocessing API, keep
    // working without a rebuild.
    ViewProviderFemMeshShapeBase::updateData(prop);
    if (!prop) {
        return;
    }
    auto* meshObj = Base::freecad_cast<Fem::FemMeshObject*>(getObject());
    if (!meshObj) {
        return;
    }
    if (prop == &meshObj->FemMesh) {
        m_preprocessBuilt = false;
        syncRepresentation();
        return;
    }
    auto* shapeBase = Base::freecad_cast<Fem::FemMeshShapeBaseObject*>(getObject());
    if (shapeBase && prop == &shapeBase->Components) {
        syncRepresentation();
    }
}

void ViewProviderFemMeshShapePreprocess::syncRepresentation()
{
    if (!preprocessActive()) {
        // Legacy object: drop the view state hook and let the base class drive
        // the scene graph. Nothing of the preprocess pipeline is built.
        if (m_boundViewState && AnalysisViewState::isAlive(m_boundViewState)) {
            m_boundViewState->unregisterMeshGrid(m_registeredGrid);
            m_registeredGrid = nullptr;
        }
        m_viewStateConn.disconnect();
        m_boundViewState = nullptr;
        m_viewStateCacheValid = false;
        return;
    }

    if (!m_preprocessModeAdded) {
        addDisplayMaskMode(m_renderer.root(), PreprocessMode);
        addDisplayMaskMode(m_hidden, PreprocessHiddenMode);
        m_preprocessModeAdded = true;
    }

    ensureViewStateConnection();
    if (!m_preprocessBuilt) {
        updateMeshFromProperty();
    }
    updateStageVisibility();
}

void ViewProviderFemMeshShapePreprocess::onChanged(const App::Property* prop)
{
    ViewProviderFemMeshShapeBase::onChanged(prop);
    if (prop == &Visibility && preprocessActive()) {
        // Visibility is also the first signal a freshly grouped mesh gets, so the
        // representation may still be the legacy one at this point.
        syncRepresentation();
    }
}

void ViewProviderFemMeshShapePreprocess::finishRestoring()
{
    ViewProviderFemMeshShapeBase::finishRestoring();
    // GuiDocument.xml is restored before FemMesh.unv, and the property change
    // that carries the mesh data does not reach view providers while the
    // document is restoring. Whatever was built earlier came from an empty
    // property, so discard it and rebuild from the now complete object.
    m_preprocessBuilt = false;
    syncRepresentation();
}

Fem::FemAnalysis* ViewProviderFemMeshShapePreprocess::findAnalysis() const
{
    auto* obj = getObject();
    if (!obj) {
        return nullptr;
    }
    for (auto* parent : obj->getInList()) {
        if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(parent)) {
            return analysis;
        }
        if (auto* group = Base::freecad_cast<Fem::FemMeshShapeGroup*>(parent)) {
            for (auto* grand : group->getInList()) {
                if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(grand)) {
                    return analysis;
                }
            }
        }
    }
    return nullptr;
}

Fem::FemGeometry* ViewProviderFemMeshShapePreprocess::findGeometry() const
{
    if (auto* shapeBase = Base::freecad_cast<Fem::FemMeshShapeBaseObject*>(getObject())) {
        if (auto* geo = Base::freecad_cast<Fem::FemGeometry*>(shapeBase->Components.getValue())) {
            return geo;
        }
    }
    auto* analysis = findAnalysis();
    if (!analysis) {
        return nullptr;
    }
    for (auto* obj : analysis->Group.getValues()) {
        if (auto* geo = Base::freecad_cast<Fem::FemGeometry*>(obj)) {
            return geo;
        }
    }
    return nullptr;
}

AnalysisViewState* ViewProviderFemMeshShapePreprocess::viewState() const
{
    auto* analysis = findAnalysis();
    if (!analysis) {
        return nullptr;
    }
    return AnalysisViewState::forAnalysis(analysis);
}

void ViewProviderFemMeshShapePreprocess::ensureViewStateConnection()
{
    auto* state = viewState();
    if (state == m_boundViewState && m_viewStateConn.connected()) {
        return;
    }
    m_viewStateConn.disconnect();
    if (m_boundViewState && AnalysisViewState::isAlive(m_boundViewState)) {
        m_boundViewState->unregisterMeshGrid(m_registeredGrid);
        m_registeredGrid = nullptr;
    }
    m_boundViewState = state;
    m_viewStateCacheValid = false;
    if (state) {
        m_viewStateConn = state->connectChanged([this]() { onViewStateChanged(); });
        registerGrid();
        onViewStateChanged();
    }
}

void ViewProviderFemMeshShapePreprocess::registerGrid()
{
    if (!m_boundViewState || !AnalysisViewState::isAlive(m_boundViewState)
        || m_registeredGrid == m_vtkmesh.Get()) {
        return;
    }
    m_boundViewState->unregisterMeshGrid(m_registeredGrid);
    m_registeredGrid = m_vtkmesh.Get();
    m_boundViewState->registerMeshGrid(m_registeredGrid);
}

void ViewProviderFemMeshShapePreprocess::onViewStateChanged()
{
    if (!preprocessActive()) {
        return;
    }
    if (!m_preprocessModeAdded || !m_preprocessBuilt) {
        syncRepresentation();
        return;
    }
    updateStageVisibility();
    applyViewState(false);
}

void ViewProviderFemMeshShapePreprocess::updateStageVisibility()
{
    if (!m_preprocessModeAdded) {
        return;
    }
    bool show = Visibility.getValue();
    if (auto* state = m_boundViewState ? m_boundViewState : viewState()) {
        show = show && (state->activeStage() == ActiveStage::Mesh);
    }
    setDisplayMaskMode(show ? PreprocessMode : PreprocessHiddenMode);
}

void ViewProviderFemMeshShapePreprocess::updateMeshFromProperty()
{
    auto* meshObj = Base::freecad_cast<Fem::FemMeshObject*>(getObject());
    if (!meshObj) {
        return;
    }

    const Fem::FemMesh& femMesh = meshObj->FemMesh.getValue();
    m_vtkmesh = vtkSmartPointer<vtkUnstructuredGrid>::New();

    // Keep all dimensions; FemVisibilityMask filters for display.
    std::vector<int> cellElementIds;
    Fem::FemVTKTools::exportVTKMesh(&femMesh, m_vtkmesh, false, 1.0, &cellElementIds);

    // String entity names (Face7, Solid3, ...) when groups are present.
    try {
        Fem::FemVTKTools::exportVTKCellGroup(
            const_cast<Fem::FemMesh*>(&femMesh),
            m_vtkmesh,
            FemVisibilityMask::ArrayEntityIds,
            {},
            cellElementIds
        );
    }
    catch (const std::exception& e) {
        Base::Console().warning(
            "ViewProviderFemMeshShapePreprocess: cell group export failed: %s\n",
            e.what()
        );
    }

    m_renderer.setMesh(m_vtkmesh);
    m_viewStateCacheValid = false;
    // An empty grid means the property has not delivered its data yet (restore
    // reads the mesh file after the view providers). Stay unbuilt so the next
    // trigger retries instead of showing nothing forever.
    m_preprocessBuilt = m_vtkmesh->GetNumberOfCells() > 0;
    ensureViewStateConnection();
    registerGrid();
    applyViewState(true);
}

void ViewProviderFemMeshShapePreprocess::applyViewState(bool meshChanged)
{
    ensureViewStateConnection();
    auto* state = m_boundViewState ? m_boundViewState : viewState();
    auto* geometry = findGeometry();

    if (!state) {
        m_renderer.applyVisibilityMask(geometry, DimensionMode::Highest, {}, {});
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
    const FemGui::ColorMode colorMode = state->colorMode();
    const auto& hidden = state->hiddenElements();
    const auto& hiddenTypes = state->hiddenCellTypes();
    const auto& clips = state->clipPlanes();

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
        const Classification* classification = state->classification(m_vtkmesh);
        m_renderer.setClassification(classification);
        m_renderer.updateColors();
        return;
    }

    std::set<std::string> underAchieved;
    m_renderer.applyVisibilityMask(geometry, dimMode, hidden, hiddenTypes, &underAchieved);
    state->setUnderAchievedElements(std::move(underAchieved));
    m_renderer.setClipPlanes(clips);
    m_renderer.setWireframe(wireframe);

    // Ghost of the full mesh: the same dimension filter, but with nothing
    // hidden. Only needed while something is actually taken out of the view.
    m_renderer.setOverlay(state->overlay());
    const bool overlayNeeded = state->overlay()
        && (wireframe || !clips.empty() || !hidden.empty() || !hiddenTypes.empty());
    if (overlayNeeded && m_vtkmesh) {
        m_renderer.setOverlayMask(
            FemVisibilityMask::evaluate(m_vtkmesh, geometry, dimMode, {}, {})
        );
    }
    else {
        m_renderer.setOverlayMask({});
    }

    const Classification* classification = state->classification(m_vtkmesh);
    m_renderer.setClassification(classification);
    m_renderer.update();
    rebuildSelectionMaps();
}

void ViewProviderFemMeshShapePreprocess::rebuildSelectionMaps()
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

std::string ViewProviderFemMeshShapePreprocess::getElement(const SoDetail* detail) const
{
    if (!preprocessActive()) {
        return ViewProviderFemMeshShapeBase::getElement(detail);
    }
    if (!detail) {
        return {};
    }

    if (detail->getTypeId() == SoFaceDetail::getClassTypeId()) {
        const auto* faceDetail = static_cast<const SoFaceDetail*>(detail);
        const int face = faceDetail->getFaceIndex();
        if (face < 0 || static_cast<size_t>(face) >= m_faceEntities.size()) {
            return {};
        }
        return m_faceEntities[static_cast<size_t>(face)];
    }
    if (detail->getTypeId() == SoLineDetail::getClassTypeId()) {
        const auto* lineDetail = static_cast<const SoLineDetail*>(detail);
        const int line = lineDetail->getLineIndex();
        if (line < 0 || static_cast<size_t>(line) >= m_lineEntities.size()) {
            return {};
        }
        return m_lineEntities[static_cast<size_t>(line)];
    }
    if (detail->getTypeId() == SoPointDetail::getClassTypeId()) {
        const auto* pointDetail = static_cast<const SoPointDetail*>(detail);
        const int vertex = pointDetail->getCoordinateIndex();
        if (vertex < 0 || static_cast<size_t>(vertex) >= m_pointEntities.size()) {
            return {};
        }
        return m_pointEntities[static_cast<size_t>(vertex)];
    }
    return {};
}

SoDetail* ViewProviderFemMeshShapePreprocess::getDetail(const char* subelement) const
{
    if (!preprocessActive()) {
        return ViewProviderFemMeshShapeBase::getDetail(subelement);
    }
    if (!subelement || !*subelement) {
        return nullptr;
    }

    const std::string name(subelement);
    auto type = Part::TopoShape::getElementTypeAndIndex(subelement);
    const std::string& element = type.first;

    if (element == "Face" || element == "Solid" || element.empty()) {
        auto it = m_entityToFace.find(name);
        if (it != m_entityToFace.end()) {
            auto* detail = new SoFaceDetail();
            detail->setFaceIndex(it->second);
            return detail;
        }
    }
    if (element == "Edge" || element.empty()) {
        auto it = m_entityToLine.find(name);
        if (it != m_entityToLine.end()) {
            auto* detail = new SoLineDetail();
            detail->setLineIndex(it->second);
            return detail;
        }
    }
    if (element == "Vertex" || element.empty()) {
        auto it = m_entityToPoint.find(name);
        if (it != m_entityToPoint.end()) {
            auto* detail = new SoPointDetail();
            detail->setCoordinateIndex(it->second);
            return detail;
        }
    }

    // Fallback: any display primitive that maps to this entity
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

// Python feature ---------------------------------------------------------

namespace Gui
{

PROPERTY_SOURCE_TEMPLATE(
    FemGui::ViewProviderFemMeshShapePreprocessPython,
    FemGui::ViewProviderFemMeshShapePreprocess
)

template class FemGuiExport ViewProviderFeaturePythonT<FemGui::ViewProviderFemMeshShapePreprocess>;

}  // namespace Gui
