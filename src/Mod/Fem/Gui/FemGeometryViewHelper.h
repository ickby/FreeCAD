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
#include "FemInstanceViewHelper.h"
#include "FemViewTypes.h"

class SoCoordinate3;
class SoDepthBuffer;
class SoDetail;
class SoDrawStyle;
class SoIndexedFaceSet;
class SoIndexedLineSet;
class SoIndexedPointSet;
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
class FemGuiExport FemGeometryViewHelper: public FemInstanceViewHelper
{
public:
    FemGeometryViewHelper();
    ~FemGeometryViewHelper() override;

    /**
     * Prefix for the subnames the 3D view reports and accepts.
     *
     * Relative to the object the view provider belongs to, which is what
     * Selection and every reference built from a pick expect - unlike the
     * analysis-relative path of setPathPrefix(), which names the same element
     * from the analysis this instance was imported into.
     */
    void setSelectionPrefix(const std::string& prefix);
    void setSuppressedComponents(const std::vector<long>& indices);

    void attachToSeparator(SoSeparator* root);
    void ensureDisplayModes(SoSeparator* hiddenSeparator);

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
     * While true, a preselected Face/Edge/Vertex is mapped to its owning
     * volume toplevels before highlight is applied.
     */
    void setPreselectPromotion(bool on);
    bool isPreselectPromotion() const
    {
        return m_preselectPromotion;
    }

    /**
     * Mark @a elements in a colour of their own, named as a reference on this
     * instance names them, until the same @a role is set again or cleared.
     *
     * Elements may name toplevels (Solid2) or sub-elements (Face7, Edge3,
     * Vertex1). A toplevel marks its faces and only those: a solid reads from
     * its faces, and drawing its edges and vertices as well would swamp the
     * ones marked in their own right. Edges and vertices named outright are
     * drawn by the highlight overlay, see updateElementHighlight().
     *
     * A role separates consumers, so two open panels do not overwrite each
     * other and each clears only its own marks. Where roles overlap, the one
     * set last wins.
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
    /** Elements currently marked by that role. */
    std::set<std::string> elementHighlight(const std::string& role) const;
    /**
     * Colour marking @a element by that name alone, or null if it carries no
     * mark of its own. Without the inheritance highlightColorFor() does from a
     * marked toplevel down onto the faces it is built from.
     */
    const Base::Color* elementHighlightColor(const std::string& element) const;

protected:
    void applyViewStateChange() override;

private:
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
    std::set<std::string> suppressedToplevels(Fem::FemGeometry* geom) const;
    const Base::Color* highlightColorFor(const std::string& element, vtkIdType id) const;
    /** Colour marking any toplevel the shape with this vtk id belongs to. */
    const Base::Color* idHighlightColor(vtkIdType id) const;
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
    std::vector<std::string> volumeOwnersOf(const std::string& element) const;

    struct ElementHighlight
    {
        std::string role;
        std::set<std::string> elements;
        Base::Color color;
    };
    std::vector<ElementHighlight> m_highlights;
    std::set<std::string> m_selected;
    std::set<std::string> m_preselected;
    bool m_preselectPromotion {false};

    std::string m_selectionPrefix;
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

    SoMaterialBinding* m_overlaymaterialbinding {nullptr};
    SoMaterial* m_overlaymaterial {nullptr};
    SoCoordinate3* m_overlaycoordinates {nullptr};
    SoNormalBinding* m_overlaynormalBinding {nullptr};
    SoNormal* m_overlaynormals {nullptr};
    SoIndexedFaceSet* m_overlayfaces {nullptr};

    bool m_displayModesAdded {false};
    bool m_attached {false};

    DimensionMode m_cachedDimMode {DimensionMode::Highest};
    bool m_cachedWireframe {false};
    ColorMode m_cachedColorMode {ColorMode::Subelement};
    bool m_cachedOverlay {true};
    std::set<std::string> m_cachedHidden;
    std::map<std::string, ClippingPlane> m_cachedClips;
};

}  // namespace FemGui
