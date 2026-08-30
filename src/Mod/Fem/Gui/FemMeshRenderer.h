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

#include <cstdint>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

#include <Base/Color.h>
#include <Base/Vector3D.h>
#include <Mod/Fem/FemGlobal.h>

#include "FemViewTypes.h"

#include <vtkSmartPointer.h>
#include <vtkUnstructuredGrid.h>
#include <vtkPolyData.h>
#include <vtkPolyDataAlgorithm.h>
#include <vtkThreshold.h>
#include <vtkExtractGeometry.h>
#include <vtkExtractEdges.h>
#include <vtkGeometryFilter.h>
#include <vtkUnstructuredGridGeometryFilter.h>
#include <vtkAppendPolyData.h>

class SoCoordinate3;
class SoSeparator;
class SoNormalBinding;
class SoNormal;
class SoIndexedMarkerSet;
class SoIndexedLineSet;
class SoIndexedFaceSet;
class SoShapeHints;
class SoMaterial;
class SoMaterialBinding;
class SoDrawStyle;
class SoPolygonOffset;
class vtkPoints;
class vtkDataArray;
class vtkCellArray;

namespace Fem
{
class FemGeometry;
}

namespace FemGui
{

class Classification;

/**
 * Shared VTK-to-Coin mesh rendering core.
 *
 * Helper object (not a base class) so geometry and mesh view providers with
 * incompatible inheritance can compose it. Recolouring does not re-run the VTK
 * pipeline. Face materials use PER_FACE_INDEXED with a small palette.
 */
class FemGuiExport FemMeshRenderer
{
public:
    FemMeshRenderer();
    ~FemMeshRenderer();

    FemMeshRenderer(const FemMeshRenderer&) = delete;
    FemMeshRenderer& operator=(const FemMeshRenderer&) = delete;

    /** Coin root to register as a display mask mode. */
    SoSeparator* root() const;

    /** Replace the input unstructured grid (takes ownership of a shallow copy). */
    void setMesh(vtkSmartPointer<vtkUnstructuredGrid> mesh);

    /**
     * Per-cell visibility: 1 = visible, 0 = hidden. Length must match the
     * number of cells in the current mesh; empty clears the filter.
     *
     * Dimension filtering is done via this mask (entity-based highest), not
     * via vtkExtractCellsByType. Prefer FemVisibilityMask::evaluate().
     */
    void setVisibilityMask(const std::vector<unsigned char>& mask);

    void setClipPlanes(const std::map<std::string, ClippingPlane>& planes);

    /**
     * Stored for consumers; dimension filtering itself is applied through
     * setVisibilityMask (FemVisibilityMask::evaluate). Does not re-run VTK.
     */
    void setDimensionMode(DimensionMode mode);
    DimensionMode dimensionMode() const
    {
        return m_dimensionMode;
    }

    /**
     * Optional classification for smart colouring. When set, updateColors()
     * uses categoryOfCell; otherwise materialIndex stays at palette entry 0.
     */
    void setClassification(const Classification* classification);

    /**
     * Evaluate FemVisibilityMask into setVisibilityMask and store dimMode.
     * Call before updateVTK(). underAchieved (optional) receives toplevels
     * where achieved mesh dim < declared analysis dim, mapped to the dimension
     * the mesh did reach.
     */
    void applyVisibilityMask(
        const Fem::FemGeometry* geometry,
        DimensionMode dimMode,
        bool showConstruction,
        const std::set<std::string>& hiddenElements,
        const std::set<std::string>& hiddenCellTypes,
        std::map<std::string, int>* underAchieved = nullptr
    );

    /** Replace the material palette (distinctColors by default). */
    void setPalette(const std::vector<Base::Color>& colors);

    /** Surface vs wireframe display. */
    void setWireframe(bool wireframe);

    /** Draw the ghost overlay of the cells the display filter removes. */
    void setOverlay(bool on);

    /**
     * Per-cell mask of the mesh as it would look with nothing hidden, i.e. with
     * the dimension filter alone. Its surface is rendered unclipped and
     * transparent, so hidden and clipped away parts keep their outline. Empty
     * disables the overlay.
     */
    void setOverlayMask(const std::vector<unsigned char>& mask);

    /** Rebuild the VTK pipeline and push geometry to Coin. Does not touch colours. */
    void updateVTK();

    /** Recolour faces from the current classification / palette. No VTK update. */
    void updateColors();

    /** Run updateVTK then updateColors. */
    void update();

    /** Stable 32-entry palette shared by geometry and mesh colouring. */
    static const std::vector<Base::Color>& distinctColors();

    /** Transfer VTK points/normals into Coin nodes. */
    static void writePointData(
        SoCoordinate3* coord_node,
        SoNormal* normal_node,
        SoNormalBinding* normal_binding,
        vtkPoints* points,
        vtkDataArray* normals,
        vtkDataArray* tcoords
    );

    static void writeIndexedPolys(SoIndexedFaceSet* faces, vtkCellArray* cells);
    static void writeIndexedLines(SoIndexedLineSet* lines, vtkCellArray* cells);
    static void writeIndexedVerts(SoIndexedMarkerSet* markers, vtkCellArray* cells);

    /** Accessors for selection / detail mapping. */
    vtkPolyData* currentPolyData() const;
    vtkUnstructuredGrid* mesh() const
    {
        return m_vtkmesh;
    }

    SoIndexedFaceSet* faces() const
    {
        return m_faces;
    }
    SoIndexedLineSet* lines() const
    {
        return m_lines;
    }
    SoIndexedMarkerSet* markers() const
    {
        return m_markers;
    }

private:
    void buildSceneGraph();
    void pushPolyDataToCoin(vtkPolyData* visdata);
    void updateOverlay();

    /**
     * Fill m_realedges with the element edges of the cells the surface came
     * from, each edge as one line however many points it curves through.
     *
     * Taking them from the cells rather than from the surface is what keeps
     * them element edges: the surface filter linearises a quadratic face, and
     * its edges are the triangulation of that face, not the elements. The
     * edges that point into the interior are drawn too and are hidden behind
     * the surface, which costs less than working out which ones those are.
     */
    void buildBoundaryEdges();

    /// Drop the record of what the pipeline was last fed and last produced, so
    /// that the next update rebuilds and re-pushes everything.
    void forgetPipelineState();

    SoSeparator* m_separator {nullptr};
    SoShapeHints* m_shapehints {nullptr};
    SoCoordinate3* m_coordinates {nullptr};
    SoNormalBinding* m_normalBinding {nullptr};
    SoNormal* m_normals {nullptr};
    SoMaterialBinding* m_pointlinematerialbinding {nullptr};
    SoMaterial* m_pointlinematerial {nullptr};
    SoDrawStyle* m_pointlinestyle {nullptr};
    SoIndexedMarkerSet* m_markers {nullptr};
    SoIndexedLineSet* m_lines {nullptr};
    SoMaterialBinding* m_facematerialbinding {nullptr};
    SoMaterial* m_facematerial {nullptr};
    SoIndexedFaceSet* m_faces {nullptr};
    SoPolygonOffset* m_offset {nullptr};

    // ghost overlay of the cells removed by the display filter
    SoSeparator* m_overlayseparator {nullptr};
    SoMaterialBinding* m_overlaymaterialbinding {nullptr};
    SoMaterial* m_overlaymaterial {nullptr};
    SoCoordinate3* m_overlaycoordinates {nullptr};
    SoNormalBinding* m_overlaynormalBinding {nullptr};
    SoNormal* m_overlaynormals {nullptr};
    SoIndexedFaceSet* m_overlayfaces {nullptr};

    vtkSmartPointer<vtkUnstructuredGrid> m_vtkmesh;
    vtkSmartPointer<vtkPolyDataAlgorithm> m_vtkcurrentalgorithm;
    vtkSmartPointer<vtkThreshold> m_vtkfilter;
    vtkSmartPointer<vtkExtractGeometry> m_vtkclipper;
    // Only in the pipeline of a mesh with curved elements; see setMesh().
    vtkSmartPointer<vtkUnstructuredGridGeometryFilter> m_vtkfacefilter;
    vtkSmartPointer<vtkGeometryFilter> m_vtkpolyfilter;
    vtkSmartPointer<vtkExtractEdges> m_vtkwireedges;
    // Element edges of the faces on the surface; an input of m_vtksurface.
    vtkSmartPointer<vtkPolyData> m_realedges;
    vtkSmartPointer<vtkAppendPolyData> m_vtksurface;
    // Overlay branch: threshold on its own mask, no clipping.
    vtkSmartPointer<vtkThreshold> m_vtkoverlayfilter;
    vtkSmartPointer<vtkGeometryFilter> m_vtkoverlaypoly;

    std::map<std::string, ClippingPlane> m_clipper;
    DimensionMode m_dimensionMode {DimensionMode::Highest};
    bool m_curvedmesh {false};
    bool m_wireframe {false};
    bool m_overlayEnabled {true};
    std::vector<unsigned char> m_overlayMask;
    const Classification* m_classification {nullptr};
    std::vector<Base::Color> m_palette;
    std::vector<unsigned char> m_visibilityMask;

    // What the pipeline was last fed. An update is only allowed to disturb it
    // where it differs, because a filter told it changed forgets everything it
    // and everything behind it had computed.
    std::vector<unsigned char> m_writtenvisibility;
    std::vector<unsigned char> m_writtenoverlay;
    std::map<std::string, ClippingPlane> m_writtenclipper;
    bool m_inputswritten {false};

    // What was last read out of it. The pointers are compared, never followed,
    // and paired with a timestamp that VTK never reuses.
    vtkPointSet* m_boundaryfrom {nullptr};
    vtkMTimeType m_boundarymtime {0};
    vtkPolyData* m_pusheddata {nullptr};
    vtkMTimeType m_pushedmtime {0};
    vtkPolyData* m_overlaypushed {nullptr};
    vtkMTimeType m_overlaypushedmtime {0};

    // Scratch of buildBoundaryEdges(), kept between updates for the capacity
    // alone: the drawn number of each surface point, and the open-addressed
    // table of the edges already drawn.
    std::vector<vtkIdType> m_pointmap;
    std::vector<std::uint64_t> m_edgeseen;
};

}  // namespace FemGui
