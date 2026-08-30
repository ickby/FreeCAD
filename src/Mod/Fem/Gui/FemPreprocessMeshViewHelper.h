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

#include <functional>
#include <map>
#include <set>
#include <string>
#include <vector>

#include <Base/Placement.h>
#include <Mod/Fem/FemGlobal.h>

#include "AnalysisViewState.h"
#include "FemMeshRenderer.h"
#include "FemViewTypes.h"

#include <vtkSmartPointer.h>
#include <vtkUnstructuredGrid.h>

class SoSeparator;

namespace Fem
{
class FemAnalysis;
class FemGeometry;
class FemMesh;
}

namespace Gui
{
class ViewProviderDocumentObject;
}

namespace FemGui
{

/**
 * Shared FemMeshRenderer + AnalysisViewState wiring for preprocessing VPs.
 */
class FemGuiExport FemPreprocessMeshViewHelper
{
public:
    using AnalysisFinder = std::function<Fem::FemAnalysis*()>;
    using GeometryFinder = std::function<Fem::FemGeometry*()>;

    FemPreprocessMeshViewHelper();
    ~FemPreprocessMeshViewHelper();

    void setHost(
        Gui::ViewProviderDocumentObject* viewProvider,
        AnalysisFinder findAnalysis,
        GeometryFinder findGeometry
    );

    /** Analysis-relative path prefix (e.g. "Import2.") for hidden/clip lookups. */
    void setPathPrefix(const std::string& prefix);
    /** Placement of this instance, used to bring clip planes into its frame. */
    void setLocalFrame(const Base::Placement& placement);
    /** When false the host view provider manages stage display masks itself. */
    void setManageStageVisibility(bool on);

    void ensureDisplayModes(SoSeparator* hiddenSeparator);
    bool hasDisplayModes() const;
    void invalidateMesh();
    bool isBuilt() const;

    void updateFromFemMesh(const Fem::FemMesh& femMesh);
    /** ShallowCopy of @a sourceGrid with independent cell-data arrays for filtering. */
    void updateFromSharedGrid(vtkUnstructuredGrid* sourceGrid, const std::vector<int>& cellElementIds);
    /**
     * Convert @a femMesh into a VTK grid plus its cell-to-entity ids.
     *
     * Separate from updateFromFemMesh() so several instances of one source mesh
     * can be handed the same grid through updateFromSharedGrid().
     */
    static void buildGrid(
        const Fem::FemMesh& femMesh,
        vtkUnstructuredGrid* grid,
        std::vector<int>& cellElementIds
    );
    /**
     * Restrict rendering to a subset of the mesh (1 = render, 0 = drop).
     *
     * Indexed by SMESH element id - 1, the same way FemMeshShapeGroup indexes
     * CellSources. The VTK export groups cells by element type, so the helper
     * translates through the element ids it got from the export.
     */
    void setElementSubsetMask(std::vector<unsigned char> mask);

    void connectViewState();
    void disconnectViewState();
    void syncStageVisibility();
    void onViewStateChanged();

    FemMeshRenderer& renderer();

private:
    void ensureViewStateConnection();
    void registerGrid();
    void applyViewState(bool meshChanged);
    void applyElementSubset(std::vector<unsigned char>& visibility) const;
    std::set<std::string> localHiddenElements(const std::set<std::string>& hidden) const;
    std::map<std::string, ClippingPlane> localClipPlanes(
        const std::map<std::string, ClippingPlane>& clips
    ) const;
    AnalysisViewState* viewState() const;

    Gui::ViewProviderDocumentObject* m_viewProvider {nullptr};
    std::string m_pathPrefix;
    Base::Placement m_localFrame;
    bool m_manageStageVisibility {true};
    AnalysisFinder m_findAnalysis;
    GeometryFinder m_findGeometry;

    FemMeshRenderer m_renderer;
    SoSeparator* m_hidden {nullptr};
    bool m_displayModesAdded {false};
    bool m_built {false};

    vtkSmartPointer<vtkUnstructuredGrid> m_vtkmesh;
    std::vector<unsigned char> m_elementSubsetMask;
    std::vector<int> m_cellElementIds;

    AnalysisViewState::Connection m_viewStateConn;
    AnalysisViewState* m_boundViewState {nullptr};
    vtkUnstructuredGrid* m_registeredGrid {nullptr};

    bool m_viewStateCacheValid {false};
    DimensionMode m_cachedDimMode {DimensionMode::Highest};
    bool m_cachedShowConstruction {false};
    bool m_cachedWireframe {false};
    ColorMode m_cachedColorMode {ColorMode::Subelement};
    std::set<std::string> m_cachedHidden;
    std::set<std::string> m_cachedHiddenCellTypes;
    std::map<std::string, ClippingPlane> m_cachedClips;
    /// What the state above was last worked out to mean, cell by cell.
    std::vector<unsigned char> m_cachedVisibility;
    std::vector<unsigned char> m_cachedOverlay;
    std::map<std::string, int> m_cachedUnderAchieved;
};

}  // namespace FemGui
