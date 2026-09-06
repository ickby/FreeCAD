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
#include "FemInstanceViewHelper.h"
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
class FemGuiExport FemPreprocessMeshViewHelper: public FemInstanceViewHelper
{
public:
    FemPreprocessMeshViewHelper();
    ~FemPreprocessMeshViewHelper() override;

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

    void syncStageVisibility();

    FemMeshRenderer& renderer();

protected:
    void applyViewStateChange() override;

    /// Register the grid with the state that was just bound, so it can classify it.
    void onViewStateBound() override;
    /// Take the grid back off the state before letting go of it.
    void onViewStateUnbound(AnalysisViewState* state) override;

private:
    void registerGrid();
    void applyViewState(bool meshChanged);
    void applyElementSubset(std::vector<unsigned char>& visibility) const;

    FemMeshRenderer m_renderer;
    SoSeparator* m_hidden {nullptr};
    bool m_displayModesAdded {false};
    bool m_built {false};

    vtkSmartPointer<vtkUnstructuredGrid> m_vtkmesh;
    std::vector<unsigned char> m_elementSubsetMask;
    std::vector<int> m_cellElementIds;

    vtkUnstructuredGrid* m_registeredGrid {nullptr};

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
