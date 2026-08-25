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

#include <App/PropertyStandard.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Gui/ViewProviderFeaturePython.h>

#include <IVtkOCC_Shape.hxx>
#include <IVtkTools_ShapeDataSource.hxx>
#include <IVtkTools_SubPolyDataFilter.hxx>
#include <vtkCleanPolyData.h>
#include <vtkClipClosedSurface.h>
#include <vtkExtractCellsByType.h>
#include <vtkGeometryFilter.h>
#include <vtkPolyDataNormals.h>
#include <vtkTableBasedClipDataSet.h>

#include <Inventor/fields/SoSFColor.h>

#include "AnalysisViewState.h"
#include "FemViewTypes.h"

class SoCoordinate3;
class SoSeparator;
class SoNormalBinding;
class SoNormal;
class SoMaterial;
class SoMaterialBinding;
class SoIndexedFaceSet;
class SoShapeHints;
class SoDrawStyle;

namespace PartGui
{
class SoBrepPointSet;
class SoBrepEdgeSet;
class SoBrepFaceSet;
}

namespace FemGui
{

/**
 * View provider for Fem::FemGeometry.
 *
 * Display filter, dimension mode, wireframe and clipping come from
 * AnalysisViewState (not owned as properties). Geometry overlay is rendered
 * only here.
 */
class FemGuiExport ViewProviderFemGeometry: public Gui::ViewProviderDocumentObject
{
    PROPERTY_HEADER_WITH_OVERRIDE(FemGui::ViewProviderFemGeometry);

public:
    ViewProviderFemGeometry();
    ~ViewProviderFemGeometry() override;

    App::PropertyColorList Colors;

    /// Convenience API: forwards to the active analysis AnalysisViewState.
    void setClippingPlane(const std::string& name, const ClippingPlane& plane);
    void removeClippingPlane(const std::string& name);

    void attach(App::DocumentObject* pcObject) override;
    void setDisplayMode(const char* ModeName) override;
    std::vector<std::string> getDisplayModes() const override;

    void updateData(const App::Property* prop) override;
    void onChanged(const App::Property* prop) override;

    std::string getElement(const SoDetail*) const override;
    SoDetail* getDetail(const char*) const override;
    void onSelectionChanged(const Gui::SelectionChanges&) override;

    /** Rebuild 3D selection/preselection highlight from Gui::Selection. */
    void syncSelectionHighlight();

    PyObject* getPyObject() override;

protected:
    void updateColors();
    void updateVTK();
    void update3D();
    void applySelectionHighlight();
    /**
     * Drop selection state that indexes into the part table and rebuild it.
     * Every mesh rebuild renumbers the parts, so both the Coin selection
     * contexts and our overlay fields would otherwise point at foreign faces.
     */
    void resetSelectionVisuals();
    /** Map a Selection message onto a shape element of this geometry, or empty. */
    std::string elementFromSelection(
        const char* docName,
        const char* objName,
        const char* subName
    ) const;

    void ensureViewStateConnection();
    void onViewStateChanged();
    AnalysisViewState* viewState() const;

    /** Record that the shape with this vtk id belongs to a toplevel element. */
    void addIdElement(vtkIdType id, const std::string& element);
    /** Whether the shape with this vtk id belongs to that toplevel element. */
    bool idHasElement(vtkIdType id, const std::string& element) const;
    /** Whether the shape with this vtk id belongs to any of these elements. */
    bool idHasAnyElement(vtkIdType id, const std::set<std::string>& elements) const;
    /** Toplevel element used to colour the shape with this vtk id, or empty. */
    std::string idElementForColor(vtkIdType id) const;

    // vtk elements
    vtkSmartPointer<vtkPolyData> m_visdata;
    vtkSmartPointer<vtkPolyData> m_visgeometryoverlay;

    IVtkOCC_Shape::Handle m_shape;
    vtkSmartPointer<IVtkTools_ShapeDataSource> m_vtksource;
    vtkSmartPointer<IVtkTools_SubPolyDataFilter> m_vtkshapefilter;
    // Surface clip: TableBasedClip → GeometryFilter. The clipper keeps the
    // Shape_ID/mesh-type cell arrays attached to the surviving cells.
    // Solid interiors: ShapeDataSource → CleanPolyData → ClipClosedSurface.
    vtkSmartPointer<vtkTableBasedClipDataSet> m_vtkclipfilter;
    vtkSmartPointer<vtkGeometryFilter> m_vtkclipgeometryfilter;
    vtkSmartPointer<vtkCleanPolyData> m_vtkclipcleaner;
    vtkSmartPointer<vtkClipClosedSurface> m_vtkclipsurfacefilter;
    vtkSmartPointer<IVtkTools_ShapeDataSource> m_vtkclipshapesource;
    vtkSmartPointer<vtkPolyDataNormals> m_vtkclipnormals;

    vtkSmartPointer<vtkExtractCellsByType> m_vtkgeometryoverlayextract;

    // Idx in vector corresponds to FaceIndex / LineIndex / PointIndex of the BrepSets
    std::vector<vtkIdType> m_faceids;
    std::vector<vtkIdType> m_lineids;
    std::vector<vtkIdType> m_pointids;
    // One VTK shape id per SoBrepFaceSet part (BREP face); materials use PER_PART
    std::vector<vtkIdType> m_part_shape_ids;

    // Prebuilt maps for getDetail / selection (avoids linear scans on preselect)
    std::unordered_map<vtkIdType, int> m_face_id_to_part_index;
    std::unordered_map<vtkIdType, int> m_line_id_to_index;
    std::unordered_map<vtkIdType, int> m_point_id_to_index;

    // A face can belong to several toplevel elements: an embedded import
    // general-fuses overlapping solids, so the interface face is shared by both
    // neighbours. Every owner is recorded; the first one is used for colouring.
    std::map<vtkIdType, std::vector<std::string>> m_id_elements;

    std::set<std::string> m_selected;
    std::set<std::string> m_preselected;

    // coin display nodes
    SoSeparator* m_separator {nullptr};
    SoSeparator* m_hidden {nullptr};
    SoMaterialBinding* m_facematerialbinding {nullptr};
    SoMaterialBinding* m_pointlinematerialbinding {nullptr};
    SoMaterial* m_facematerial {nullptr};
    SoMaterial* m_pointlinematerial {nullptr};
    SoShapeHints* m_shapehints {nullptr};
    SoDrawStyle* m_pointlinestyle {nullptr};
    SoCoordinate3* m_coordinates {nullptr};
    SoNormalBinding* m_normalBinding {nullptr};
    SoNormal* m_normals {nullptr};
    PartGui::SoBrepPointSet* m_markers {nullptr};
    PartGui::SoBrepEdgeSet* m_lines {nullptr};
    PartGui::SoBrepFaceSet* m_faces {nullptr};

    // geometry overlay (owned only by this view provider)
    SoMaterial* m_geometryoverlaymaterial {nullptr};
    SoMaterialBinding* m_geometryoverlaymaterialbinding {nullptr};
    SoCoordinate3* m_geometryoverlaycoordinates {nullptr};
    SoNormalBinding* m_geometryoverlaynormalBinding {nullptr};
    SoNormal* m_geometryoverlaynormals {nullptr};
    SoIndexedFaceSet* m_geometryoverlay {nullptr};

    SoSFColor m_colorhighlight;
    SoSFColor m_colorselection;

    AnalysisViewState::Connection m_viewStateConn;
    AnalysisViewState* m_boundViewState {nullptr};

    // Cached view-state snapshot so colour-mode switches skip VTK rebuild
    bool m_viewStateCacheValid {false};
    DimensionMode m_cachedDimMode {DimensionMode::Highest};
    bool m_cachedWireframe {false};
    ColorMode m_cachedColorMode {ColorMode::Subelement};
    ActiveStage m_cachedStage {ActiveStage::Geometry};
    std::set<std::string> m_cachedHidden;
    std::map<std::string, ClippingPlane> m_cachedClips;
};

using ViewProviderFemGeometryPython = Gui::ViewProviderFeaturePythonT<ViewProviderFemGeometry>;

}  // namespace FemGui
