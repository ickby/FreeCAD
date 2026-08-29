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
#include <unordered_map>
#include <vector>

#include <Base/Color.h>
#include <Base/Placement.h>
#include <Mod/Fem/FemGlobal.h>
#include <Mod/Part/App/TopoShape.h>

#include <IVtkOCC_Shape.hxx>
#include <IVtkTools_ShapeDataSource.hxx>
#include <IVtkTools_SubPolyDataFilter.hxx>
#include <vtkCleanPolyData.h>
#include <vtkClipClosedSurface.h>
#include <vtkExtractCellsByType.h>
#include <vtkGeometryFilter.h>
#include <vtkPolyDataNormals.h>
#include <vtkSmartPointer.h>
#include <vtkTableBasedClipDataSet.h>

#include "AnalysisViewState.h"
#include "FemViewTypes.h"

class SoCoordinate3;
class SoDetail;
class SoDrawStyle;
class SoIndexedFaceSet;
class SoMaterial;
class SoMaterialBinding;
class SoNormal;
class SoNormalBinding;
class SoSeparator;
class SoShapeHints;

namespace PartGui
{
class SoBrepEdgeSet;
class SoBrepFaceSet;
class SoBrepPointSet;
}

namespace Fem
{
class FemAnalysis;
class FemGeometry;
}

namespace Gui
{
class ViewProviderDocumentObject;
}

namespace FemGui
{

/**
 * Shared IVtk + AnalysisViewState wiring for geometry rendering on import VPs.
 */
class FemGuiExport FemGeometryViewHelper
{
public:
    using AnalysisFinder = std::function<Fem::FemAnalysis*()>;
    using GeometryFinder = std::function<Fem::FemGeometry*()>;

    FemGeometryViewHelper();
    ~FemGeometryViewHelper();

    void setHost(
        Gui::ViewProviderDocumentObject* viewProvider,
        AnalysisFinder findAnalysis,
        GeometryFinder findGeometry
    );

    /** Analysis-relative path prefix (e.g. "Import2.") for hidden/clip lookups. */
    void setPathPrefix(const std::string& prefix);
    /**
     * Prefix for the subnames the 3D view reports and accepts.
     *
     * Relative to the object the view provider belongs to, which is what
     * Selection and every reference built from a pick expect - unlike the
     * analysis-relative path of setPathPrefix(), which names the same element
     * from the analysis this instance was imported into.
     */
    void setSelectionPrefix(const std::string& prefix);
    /** Placement of this instance, used to bring clip planes into its frame. */
    void setLocalFrame(const Base::Placement& placement);
    void setManageStageVisibility(bool on);
    void setSuppressedComponents(const std::vector<long>& indices);

    void attachToSeparator(SoSeparator* root);
    void ensureDisplayModes(SoSeparator* hiddenSeparator);
    void connectViewState();
    void disconnectViewState();
    void onViewStateChanged();

    /**
     * @a shape in the frame of its own analysis.
     *
     * The instance placement belongs on the scene graph above this subtree, so
     * that moving an instance costs a transform update and not a retriangulation.
     */
    void updateFromShape(const Part::TopoShape& shape, Fem::FemGeometry* metadata);

    SoSeparator* root() const
    {
        return m_separator;
    }

    /**
     * The separator the nodes of this instance hang under, null until attached.
     *
     * Every instance of one source analysis draws the same shape out of the
     * same tables, so where it sits in the scene graph is the only thing that
     * tells a pick or a highlight which of them it belongs to.
     */
    SoSeparator* attachedSeparator() const
    {
        return m_attachedSeparator;
    }

    std::string elementFromDetail(const SoDetail* detail) const;
    SoDetail* detailFromElement(const char* subelement) const;

    /** True when @a subelement is named as an element of this instance. */
    bool ownsElement(const char* subelement) const;

    /**
     * Selected and preselected subnames, as the view provider this instance
     * renders under names them.
     *
     * Names that address another instance are ignored, so the whole set can be
     * handed to every helper of a render tree.
     */
    void setSelectionState(
        const std::set<std::string>& selected,
        const std::set<std::string>& preselected
    );

    /**
     * Colour the faces of @a elements, named as a reference on this instance
     * names them, until the same @a role is set again or cleared.
     *
     * Faces only: an instance draws its edges and vertices from the same
     * coordinates as its faces, and there is no overlay here to mark them
     * without also swamping the ones under a marked solid.
     */
    void setElementHighlight(
        const std::string& role,
        const std::set<std::string>& elements,
        const Base::Color& color
    );
    void clearElementHighlight(const std::string& role)
    {
        setElementHighlight(role, {}, Base::Color());
    }

private:
    void ensureViewStateConnection();
    /** The VTK ids of everything that is not hidden, and who owns each of them. */
    void collectVisibleIds(const std::set<std::string>& hidden, IVtk_ShapeIdList& passthrough_ids);
    void applyClipPlanes(
        const std::map<std::string, ClippingPlane>& clipper,
        DimensionMode dimMode,
        const IVtk_ShapeIdList& passthrough_ids
    );
    void updateVTK();
    void update3D();
    void updateGhostOverlay();
    void updateColors();
    void colorFromClassification(
        const Classification& classification,
        const std::vector<Category>& cats,
        ColorMode colorMode
    );
    void colorFromPalette();
    void addIdElement(vtkIdType id, const std::string& element);
    std::string idElementForColor(vtkIdType id) const;
    bool idHasElement(vtkIdType id, const std::string& element) const;
    bool idHasAnyElement(vtkIdType id, const std::set<std::string>& elements) const;
    bool isVolumeShapeId(vtkIdType id) const;
    std::string localElementName(const std::string& sub) const;
    void applySelectionHighlight();
    void resetSelectionVisuals();
    std::string elementForShapeId(vtkIdType id, const char* fallbackPrefix) const;
    std::set<std::string> localHiddenElements(const std::set<std::string>& hidden) const;
    std::map<std::string, ClippingPlane> localClipPlanes(
        const std::map<std::string, ClippingPlane>& clips
    ) const;
    std::set<std::string> suppressedToplevels(Fem::FemGeometry* geom) const;
    const Base::Color* highlightColorFor(const std::string& element, vtkIdType id) const;
    AnalysisViewState* viewState() const;

    struct ElementHighlight
    {
        std::string role;
        std::set<std::string> elements;
        Base::Color color;
    };
    std::vector<ElementHighlight> m_highlights;
    std::set<std::string> m_selected;
    std::set<std::string> m_preselected;

    Gui::ViewProviderDocumentObject* m_viewProvider {nullptr};
    AnalysisFinder m_findAnalysis;
    GeometryFinder m_findGeometry;
    std::string m_pathPrefix;
    std::string m_selectionPrefix;
    Base::Placement m_localFrame;
    bool m_manageStageVisibility {true};
    std::vector<long> m_suppressedComponents;

    Part::TopoShape m_topoShape;
    Fem::FemGeometry* m_metadata {nullptr};

    vtkSmartPointer<vtkPolyData> m_visdata;
    IVtkOCC_Shape::Handle m_shape;
    vtkSmartPointer<IVtkTools_ShapeDataSource> m_vtksource;
    vtkSmartPointer<IVtkTools_SubPolyDataFilter> m_vtkshapefilter;
    vtkSmartPointer<vtkTableBasedClipDataSet> m_vtkclipfilter;
    vtkSmartPointer<vtkGeometryFilter> m_vtkclipgeometryfilter;
    vtkSmartPointer<vtkCleanPolyData> m_vtkclipcleaner;
    vtkSmartPointer<vtkClipClosedSurface> m_vtkclipsurfacefilter;
    vtkSmartPointer<IVtkTools_ShapeDataSource> m_vtkclipshapesource;
    vtkSmartPointer<vtkPolyDataNormals> m_vtkclipnormals;
    vtkSmartPointer<vtkExtractCellsByType> m_vtkoverlayextract;
    vtkSmartPointer<vtkPolyData> m_visoverlay;

    std::vector<vtkIdType> m_faceids;
    std::vector<vtkIdType> m_lineids;
    std::vector<vtkIdType> m_pointids;
    std::vector<vtkIdType> m_part_shape_ids;
    std::unordered_map<vtkIdType, int> m_face_id_to_part_index;
    std::unordered_map<vtkIdType, int> m_line_id_to_index;
    std::unordered_map<vtkIdType, int> m_point_id_to_index;
    std::map<vtkIdType, std::vector<std::string>> m_id_elements;

    SoSeparator* m_separator {nullptr};
    SoSeparator* m_attachedSeparator {nullptr};
    SoSeparator* m_hidden {nullptr};
    SoMaterialBinding* m_facematerialbinding {nullptr};
    SoMaterial* m_facematerial {nullptr};
    SoMaterialBinding* m_pointlinematerialbinding {nullptr};
    SoMaterial* m_pointlinematerial {nullptr};
    SoShapeHints* m_shapehints {nullptr};
    SoDrawStyle* m_pointlinestyle {nullptr};
    SoCoordinate3* m_coordinates {nullptr};
    SoNormalBinding* m_normalBinding {nullptr};
    SoNormal* m_normals {nullptr};
    PartGui::SoBrepPointSet* m_markers {nullptr};
    PartGui::SoBrepEdgeSet* m_lines {nullptr};
    PartGui::SoBrepFaceSet* m_faces {nullptr};

    SoMaterialBinding* m_overlaymaterialbinding {nullptr};
    SoMaterial* m_overlaymaterial {nullptr};
    SoCoordinate3* m_overlaycoordinates {nullptr};
    SoNormalBinding* m_overlaynormalBinding {nullptr};
    SoNormal* m_overlaynormals {nullptr};
    SoIndexedFaceSet* m_overlayfaces {nullptr};

    bool m_displayModesAdded {false};
    bool m_attached {false};
    AnalysisViewState::Connection m_viewStateConn;
    AnalysisViewState* m_boundViewState {nullptr};

    bool m_viewStateCacheValid {false};
    DimensionMode m_cachedDimMode {DimensionMode::Highest};
    bool m_cachedWireframe {false};
    ColorMode m_cachedColorMode {ColorMode::Subelement};
    ActiveStage m_cachedStage {ActiveStage::Geometry};
    std::set<std::string> m_cachedHidden;
    std::map<std::string, ClippingPlane> m_cachedClips;
};

}  // namespace FemGui
