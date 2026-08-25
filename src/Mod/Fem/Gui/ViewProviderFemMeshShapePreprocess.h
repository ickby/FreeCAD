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
#include <unordered_map>
#include <vector>

#include <Gui/ViewProviderFeaturePython.h>
#include <Mod/Fem/FemGlobal.h>

#include "AnalysisViewState.h"
#include "FemMeshRenderer.h"
#include "FemViewTypes.h"
#include "ViewProviderFemMeshShape.h"

#include <vtkSmartPointer.h>
#include <vtkUnstructuredGrid.h>

class SoSeparator;

namespace Fem
{
class FemAnalysis;
class FemGeometry;
class FemMeshShapeBaseObject;
}

namespace FemGui
{

/**
 * Per-object mesh view provider for the preprocessing workflow.
 *
 * Derives from the legacy ViewProviderFemMeshShapeBase so that objects which
 * are not part of the new workflow keep the full legacy behaviour and API
 * (node/element colouring, highlighted nodes, legacy display modes). This
 * matters because Gmsh and Netgen meshes share the App type and existing
 * documents and the result task panels rely on that API.
 *
 * When the object does participate in the new workflow -- it has Components
 * set on a FemGeometry, or it is a child of a FemMeshShapeGroup -- an extra
 * "Preprocess" display mask mode backed by a FemMeshRenderer is used instead.
 * That mode converts FemMesh to VTK, applies AnalysisViewState visibility and
 * classification, and maps Coin selection details to geometry entity names
 * (Face7, Edge3, ...).
 */
class FemGuiExport ViewProviderFemMeshShapePreprocess: public ViewProviderFemMeshShapeBase
{
    PROPERTY_HEADER_WITH_OVERRIDE(FemGui::ViewProviderFemMeshShapePreprocess);

public:
    ViewProviderFemMeshShapePreprocess();
    ~ViewProviderFemMeshShapePreprocess() override;

    void attach(App::DocumentObject* pcObject) override;
    void updateData(const App::Property* prop) override;
    void onChanged(const App::Property* prop) override;
    void finishRestoring() override;

    void setDisplayMode(const char* ModeName) override;
    std::vector<std::string> getDisplayModes() const override;

    std::string getElement(const SoDetail* detail) const override;
    SoDetail* getDetail(const char* subelement) const override;

    /**
     * True when the object takes part in the new preprocessing workflow, i.e.
     * it has Components pointing at a FemGeometry or lives inside a
     * FemMeshShapeGroup. Legacy objects answer false and behave exactly like
     * ViewProviderFemMeshShapeBase.
     */
    bool preprocessActive() const;

    /**
     * Build or drop the preprocess representation to match preprocessActive().
     *
     * preprocessActive() can turn true long after attach(), e.g. when the mesh
     * is assigned to a FemMeshShapeGroup or when a restored document resolves
     * its links. Until this runs, the legacy SMESH scene graph keeps rendering
     * and ignores the analysis view state, so anything that can change group or
     * analysis membership must call it.
     */
    void syncRepresentation();

protected:
    void ensureViewStateConnection();
    void onViewStateChanged();
    void updateMeshFromProperty();
    void applyViewState(bool meshChanged);
    void updateStageVisibility();
    void rebuildSelectionMaps();
    /// Keep the analysis view state informed about which grid this VP renders.
    void registerGrid();

    Fem::FemAnalysis* findAnalysis() const;
    Fem::FemGeometry* findGeometry() const;
    AnalysisViewState* viewState() const;

    FemMeshRenderer m_renderer;
    /// Empty scene graph used to hide the object outside the mesh stage.
    SoSeparator* m_hidden {nullptr};
    /// Set once the "Preprocess" display mask mode has been registered.
    bool m_preprocessModeAdded {false};
    /// Set while the preprocess representation reflects the current FemMesh.
    bool m_preprocessBuilt {false};

    vtkSmartPointer<vtkUnstructuredGrid> m_vtkmesh;

    AnalysisViewState::Connection m_viewStateConn;
    AnalysisViewState* m_boundViewState {nullptr};
    /// Grid currently registered with m_boundViewState, may be an older one.
    vtkUnstructuredGrid* m_registeredGrid {nullptr};

    // Selection: Coin index → entity name; entity → first Coin index
    std::vector<std::string> m_faceEntities;
    std::vector<std::string> m_lineEntities;
    std::vector<std::string> m_pointEntities;
    std::unordered_map<std::string, int> m_entityToFace;
    std::unordered_map<std::string, int> m_entityToLine;
    std::unordered_map<std::string, int> m_entityToPoint;

    // Cached view-state snapshot for colour-only updates
    bool m_viewStateCacheValid {false};
    DimensionMode m_cachedDimMode {DimensionMode::Highest};
    bool m_cachedWireframe {false};
    // Qualified: the inherited ColorMode property would shadow the enum name.
    FemGui::ColorMode m_cachedColorMode {FemGui::ColorMode::Subelement};
    std::set<std::string> m_cachedHidden;
    std::set<std::string> m_cachedHiddenCellTypes;
    std::map<std::string, ClippingPlane> m_cachedClips;
};

using ViewProviderFemMeshShapePreprocessPython
    = Gui::ViewProviderFeaturePythonT<ViewProviderFemMeshShapePreprocess>;

}  // namespace FemGui
