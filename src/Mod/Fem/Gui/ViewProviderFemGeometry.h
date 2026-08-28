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
class SoIndexedLineSet;
class SoIndexedPointSet;
class SoShapeHints;
class SoDrawStyle;
class SoDepthBuffer;

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

    /// Convenience API: forwards to the active analysis AnalysisViewState.
    void setClippingPlane(const std::string& name, const ClippingPlane& plane);
    void removeClippingPlane(const std::string& name);

    void attach(App::DocumentObject* pcObject) override;
    void setDisplayMode(const char* ModeName) override;
    std::vector<std::string> getDisplayModes() const override;

    void updateData(const App::Property* prop) override;
    void onChanged(const App::Property* prop) override;
    void finishRestoring() override;

    QIcon mergeColorfulOverlayIcons(const QIcon& orig) const override;

    /**
     * The geometry group this object is a build step of, or nullptr.
     *
     * Steps of a chain have no visual of their own: the group owns the result
     * shape and is the only object that renders it.
     */
    Fem::FemGeometry* chainOwner() const;
    bool isChainStep() const
    {
        return chainOwner() != nullptr;
    }
    /** Mark this step as the one the group takes its result from. */
    void setChainResult(bool result);

    /**
     * While a chain step is edited, show its own shape for picking instead of
     * staying hidden. Hides the geometry group for the duration.
     */
    void setChainPreview(bool on);
    /** True while this shape stands in for the chain result, see setChainPreview(). */
    bool isChainPreview() const
    {
        return m_chainPreview;
    }
    void setChainRenderSuppressed(bool on);
    bool isChainRenderSuppressed() const
    {
        return m_suppressChainRender;
    }
    ViewProviderFemGeometry* groupViewProvider(Fem::FemGeometry* group) const;
    const char* suppressedMaskMode() const;

    std::string getElement(const SoDetail*) const override;
    SoDetail* getDetail(const char*) const override;
    void onSelectionChanged(const Gui::SelectionChanges&) override;

    /** Rebuild 3D selection/preselection highlight from Gui::Selection. */
    void syncSelectionHighlight();

    /**
     * Mark shape elements in a colour of their own, independent of what is
     * selected.
     *
     * For panels that hold references to geometry -- partition targets,
     * constraint references -- so the user can see what is already picked while
     * still selecting freely. Marking is not selecting: it survives a
     * Gui::Selection change and does not answer to one.
     *
     * Elements may name toplevels (Solid2) or sub-elements (Face7, Edge3,
     * Vertex1). A toplevel marks its faces and only those: a solid reads from
     * its faces, and colouring its edges and vertices as well would swamp the
     * ones marked in their own right. A role separates consumers, so two open
     * panels do not overwrite each other and each clears only its own marks.
     * Where roles overlap, the one set last wins.
     */
    void setElementHighlight(
        const std::string& role,
        const std::set<std::string>& elements,
        const Base::Color& color
    );
    void clearElementHighlight(const std::string& role);
    /** Elements currently marked by that role. */
    std::set<std::string> elementHighlight(const std::string& role) const;
    /** Colour marking this element, or nullptr if it carries no mark. */
    const Base::Color* elementHighlightColor(const std::string& element) const;
    /** Colour used to mark elements when the caller names none. */
    static Base::Color defaultElementHighlightColor();

    PyObject* getPyObject() override;

protected:
    void updateColors();
    void updateVTK();
    /**
     * Clip m_visdata against the active planes and cap the cut open solids.
     *
     * Runs on every view state change, so a failure must leave the geometry
     * usable: on error the unclipped data of this step survives.
     *
     * @param clipper Active clip planes of the view state.
     * @param passthrough_ids Shape ids that made it through the visibility
     *        filter; only those solids get a cap face.
     */
    void applyClipPlanes(
        const std::map<std::string, ClippingPlane>& clipper,
        DimensionMode dimMode,
        const IVtk_ShapeIdList& passthrough_ids
    );
    void update3D();
    void updateGeometryOverlay();
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

    /** Apply the chain role of this object: build step or result owner. */
    void applyChainRole();
    /** Refresh the roles of the steps below this group. */
    void refreshChainSteps();

    /**
     * Rebuild the edge and vertex marks.
     *
     * SoBrepEdgeSet and SoBrepPointSet take one colour for the whole set, so
     * marked edges and vertices cannot be recoloured in place the way faces
     * can. They are drawn again on top instead, from the same coordinates, in
     * the colour of their mark. Only elements named outright end up here, never
     * ones inherited from a marked toplevel.
     */
    void updateElementHighlight();
    /** Element name of a vtk shape id, @a fallbackPrefix if its type is odd. */
    std::string elementForShapeId(vtkIdType id, const char* fallbackPrefix) const;
    /** Colour marking any element the shape with this vtk id belongs to. */
    const Base::Color* idHighlightColor(vtkIdType id) const;
    /**
     * Colour marking a rendered face, by its own name or by a toplevel it
     * belongs to, so a mark on a solid reaches the faces under it.
     */
    const Base::Color* highlightColorForPart(const std::string& element, vtkIdType id) const;

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

    // Marked elements per role, in the order the roles were first set, so a
    // later role wins where two of them name the same element.
    struct ElementHighlight
    {
        std::string role;
        std::set<std::string> elements;
        Base::Color color;
    };
    std::vector<ElementHighlight> m_elementHighlights;

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

    // Marked edges and vertices, drawn over the plain ones from the same
    // coordinates. Own separator, so the depth and style settings it needs stay
    // out of the way of the normal render.
    SoSeparator* m_highlightoverlay {nullptr};
    SoDepthBuffer* m_highlightoverlaydepth {nullptr};
    SoMaterialBinding* m_highlightoverlaylinebinding {nullptr};
    SoMaterial* m_highlightoverlaylinematerial {nullptr};
    SoMaterialBinding* m_highlightoverlaypointbinding {nullptr};
    SoMaterial* m_highlightoverlaypointmaterial {nullptr};
    SoDrawStyle* m_highlightoverlaystyle {nullptr};
    SoIndexedLineSet* m_highlightoverlaylines {nullptr};
    SoIndexedPointSet* m_highlightoverlaypoints {nullptr};

    SoSFColor m_colorhighlight;
    SoSFColor m_colorselection;

    AnalysisViewState::Connection m_viewStateConn;
    AnalysisViewState* m_boundViewState {nullptr};

    // Chain role: a step renders nothing, the result step carries a tree badge
    bool m_isChainStep {false};
    bool m_isChainResult {false};
    bool m_chainPreview {false};
    bool m_suppressChainRender {false};
    std::string m_previewSuppressedGroup;
    // Chain members of the last refresh, to hand their visual back when they go
    std::set<std::string> m_chainMembers;

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
