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
# include <Inventor/nodes/SoCoordinate3.h>
# include <Inventor/nodes/SoDrawStyle.h>
# include <Inventor/nodes/SoIndexedFaceSet.h>
# include <Inventor/nodes/SoIndexedLineSet.h>
# include <Inventor/nodes/SoIndexedMarkerSet.h>
# include <Inventor/nodes/SoMaterial.h>
# include <Inventor/nodes/SoMaterialBinding.h>
# include <Inventor/nodes/SoNormal.h>
# include <Inventor/nodes/SoNormalBinding.h>
# include <Inventor/nodes/SoPickStyle.h>
# include <Inventor/nodes/SoPolygonOffset.h>
# include <Inventor/nodes/SoSeparator.h>
# include <Inventor/nodes/SoShapeHints.h>

# include <vtkCellArray.h>
# include <vtkCellData.h>
# include <vtkCellTypes.h>
# include <vtkVersionMacros.h>
# if VTK_VERSION_NUMBER >= VTK_VERSION_CHECK(9, 6, 0)
#  include <vtkCellTypeUtilities.h>
# endif
# include <vtkDoubleArray.h>
# include <vtkGenericCell.h>
# include <vtkIdList.h>
# include <vtkImplicitBoolean.h>
# include <vtkIntArray.h>
# include <vtkPlane.h>
# include <vtkPointData.h>
# include <vtkPoints.h>
# include <vtkSphere.h>

# include <algorithm>
# include <cstdint>
#endif

#include "Classification.h"
#include "FemMeshRenderer.h"
#include "FemPerfLog.h"
#include "FemVisibilityMask.h"

#include <App/Application.h>
#include <Base/Console.h>
#include <Gui/Inventor/MarkerBitmaps.h>

using namespace FemGui;

const std::vector<Base::Color>& FemMeshRenderer::distinctColors()
{
    // Twelve hue families in three tones (mid, deep, pale), ordered so that
    // every prefix is as separable as a palette of that size can be. A later
    // FEM setting can replace this list; nothing in a document stores it.
    static const std::vector<Base::Color> colors = {
        Base::Color(0.949f, 0.459f, 0.442f),  //  1 red
        Base::Color(0.090f, 0.515f, 0.649f),  //  2 deep cyan
        Base::Color(0.810f, 0.715f, 0.950f),  //  3 pale violet
        Base::Color(0.356f, 0.475f, 0.122f),  //  4 deep lime
        Base::Color(0.520f, 0.569f, 0.948f),  //  5 indigo
        Base::Color(0.599f, 0.337f, 0.638f),  //  6 deep violet
        Base::Color(0.637f, 0.372f, 0.133f),  //  7 deep orange
        Base::Color(0.697f, 0.829f, 0.594f),  //  8 pale green
        Base::Color(0.144f, 0.500f, 0.243f),  //  9 deep green
        Base::Color(0.707f, 0.286f, 0.499f),  // 10 deep magenta
        Base::Color(0.130f, 0.611f, 0.947f),  // 11 blue
        Base::Color(0.090f, 0.538f, 0.433f),  // 12 deep emerald
        Base::Color(0.950f, 0.702f, 0.889f),  // 13 pale magenta
        Base::Color(0.589f, 0.776f, 0.950f),  // 14 pale blue
        Base::Color(0.740f, 0.587f, 0.212f),  // 15 amber
        Base::Color(0.817f, 0.800f, 0.545f),  // 16 pale lime
        Base::Color(0.130f, 0.746f, 0.725f),  // 17 teal
        Base::Color(0.742f, 0.519f, 0.877f),  // 18 violet
        Base::Color(0.435f, 0.393f, 0.724f),  // 19 deep indigo
        Base::Color(0.090f, 0.445f, 0.763f),  // 20 deep blue
        Base::Color(0.090f, 0.528f, 0.540f),  // 21 deep teal
        Base::Color(0.926f, 0.762f, 0.547f),  // 22 pale amber
        Base::Color(0.538f, 0.464f, 0.096f),  // 23 deep amber
        Base::Color(0.383f, 0.675f, 0.344f),  // 24 green
        Base::Color(0.714f, 0.312f, 0.252f),  // 25 deep red
        Base::Color(0.950f, 0.691f, 0.696f),  // 26 pale red
        Base::Color(0.130f, 0.718f, 0.862f),  // 27 cyan
        Base::Color(0.577f, 0.640f, 0.235f),  // 28 lime
        Base::Color(0.895f, 0.459f, 0.730f),  // 29 magenta
        Base::Color(0.880f, 0.516f, 0.301f),  // 30 orange
        Base::Color(0.134f, 0.760f, 0.552f),  // 31 emerald
        Base::Color(0.950f, 0.699f, 0.603f),  // 32 pale orange
    };
    return colors;
}

namespace
{

constexpr const char* ArrayFilter = "filter";
constexpr const char* ArrayOverlayFilter = "overlayfilter";

/// Element edges and anything no classification names are drawn in this.
constexpr float EdgeGrey = 0.2f;

/// One key per undirected point pair, naming an element edge by its two ends.
inline std::uint64_t edgeKey(vtkIdType a, vtkIdType b)
{
    const auto lo = static_cast<std::uint64_t>(std::min(a, b));
    const auto hi = static_cast<std::uint64_t>(std::max(a, b));
    return (lo << 32) | (hi & 0xFFFFFFFFULL);
}

/// Whether any element of the mesh carries points between its corners.
bool hasCurvedCells(vtkUnstructuredGrid* grid)
{
    // The distinct types, which the grid works out once and remembers, rather
    // than the type of every cell of a mesh that may run to millions.
    auto* types = grid->GetDistinctCellTypesArray();
    if (!types) {
        return false;
    }
    for (vtkIdType i = 0; i < types->GetNumberOfTuples(); ++i) {
#if VTK_VERSION_NUMBER < VTK_VERSION_CHECK(9, 6, 0)
        const bool linear = vtkCellTypes::IsLinear(types->GetValue(i)) != 0;
#else
        const bool linear = vtkCellTypeUtilities::IsLinear(types->GetValue(i)) != 0;
#endif
        if (!linear) {
            return true;
        }
    }
    return false;
}

vtkSmartPointer<vtkThreshold> makeMaskThreshold(const char* arrayname)
{
    auto filter = vtkSmartPointer<vtkThreshold>::New();
    filter->AllScalarsOff();
    filter->SetThresholdFunction(vtkThreshold::THRESHOLD_UPPER);
    filter->SetUpperThreshold(0.5);
    filter->SetInputArrayToProcess(0, 0, 0, vtkDataObject::FIELD_ASSOCIATION_CELLS, arrayname);
    return filter;
}

/// Size a Coin index field and put the same entry in every slot.
void fillMaterialIndex(SoMFInt32& field, std::size_t num, int value)
{
    field.setNum(static_cast<int>(num));
    if (num == 0) {
        return;
    }
    int32_t* indices = field.startEditing();
    std::fill(indices, indices + num, static_cast<int32_t>(value));
    field.finishEditing();
}

/**
 * Deal the cells of @a cells out between two Coin index fields.
 *
 * Every cell is written as its point indices followed by the -1 that closes a
 * Coin index list, and goes to the second field when @a second says so of the
 * mesh cell @a owner names for it. @a cellbase is where the cells of this
 * array start within the cell data of the polydata they belong to, verts,
 * lines and polys being numbered in that order.
 *
 * The lists of owners, either of which may be left out, come back holding one
 * entry per cell written to their field, in the order the field holds them:
 * that is the whole of what colouring the result needs afterwards.
 *
 * Coin grows a multi-field to exactly the size asked for, so set1Value past
 * the end reallocates and copies the whole field on every single index. Hence
 * the two passes: the first only measures, and the second writes through the
 * edit pointer. On a mesh of any size that is the difference between
 * milliseconds and seconds.
 */
template<typename OwnerFn, typename SecondFn>
void writeSplitCellIndices(
    SoMFInt32& firstfield,
    std::vector<int>* firstcells,
    SoMFInt32& secondfield,
    std::vector<int>* secondcells,
    vtkCellArray* cells,
    vtkIdType cellbase,
    OwnerFn owner,
    SecondFn second
)
{
    if (firstcells) {
        firstcells->clear();
    }
    if (secondcells) {
        secondcells->clear();
    }

    vtkIdType firstnum = 0;
    vtkIdType secondnum = 0;
    vtkIdType at = 0;
    vtkIdType npts = 0;
    const vtkIdType* indx = nullptr;
    for (cells->InitTraversal(); cells->GetNextCell(npts, indx); ++at) {
        const int from = owner(cellbase + at);
        if (second(from)) {
            secondnum += npts + 1;
            if (secondcells) {
                secondcells->push_back(from);
            }
        }
        else {
            firstnum += npts + 1;
            if (firstcells) {
                firstcells->push_back(from);
            }
        }
    }

    firstfield.setNum(static_cast<int>(firstnum));
    secondfield.setNum(static_cast<int>(secondnum));
    int32_t* firstat = firstnum > 0 ? firstfield.startEditing() : nullptr;
    int32_t* secondat = secondnum > 0 ? secondfield.startEditing() : nullptr;
    int firstwrite = 0;
    int secondwrite = 0;

    at = 0;
    for (cells->InitTraversal(); cells->GetNextCell(npts, indx); ++at) {
        const bool tosecond = second(owner(cellbase + at));
        int32_t* target = tosecond ? secondat : firstat;
        int& write = tosecond ? secondwrite : firstwrite;
        for (vtkIdType i = 0; i < npts; ++i) {
            target[write++] = static_cast<int32_t>(indx[i]);
        }
        target[write++] = -1;
    }

    if (firstat) {
        firstfield.finishEditing();
    }
    if (secondat) {
        secondfield.finishEditing();
    }
}

/// Write a per-cell 0/1 mask onto the grid; missing entries default to visible.
void writeMaskArray(
    vtkUnstructuredGrid* grid,
    const char* arrayname,
    const std::vector<unsigned char>& mask
)
{
    const vtkIdType num = grid->GetNumberOfCells();
    auto* array = vtkDoubleArray::SafeDownCast(grid->GetCellData()->GetArray(arrayname));
    if (!array) {
        auto fresh = vtkSmartPointer<vtkDoubleArray>::New();
        fresh->SetName(arrayname);
        fresh->SetNumberOfComponents(1);
        grid->GetCellData()->AddArray(fresh);
        array = vtkDoubleArray::SafeDownCast(grid->GetCellData()->GetArray(arrayname));
    }
    array->SetNumberOfTuples(num);

    const vtkIdType n = std::min(num, static_cast<vtkIdType>(mask.size()));
    for (vtkIdType i = 0; i < n; ++i) {
        array->SetValue(i, mask[static_cast<size_t>(i)] ? 1.0 : 0.0);
    }
    for (vtkIdType i = n; i < num; ++i) {
        array->SetValue(i, 1.0);
    }
}

}  // namespace

FemMeshRenderer::FemMeshRenderer()
    : m_palette(distinctColors())
{
    buildSceneGraph();

    m_vtkfilter = makeMaskThreshold(ArrayFilter);

    // Dimension filtering is applied via the per-cell visibility mask
    // (FemVisibilityMask), not vtkExtractCellsByType.
    m_vtkclipper = vtkSmartPointer<vtkExtractGeometry>::New();
    m_vtkclipper->SetExtractInside(false);
    m_vtkclipper->SetInputConnection(m_vtkfilter->GetOutputPort());

    // Only for a mesh with curved elements, whose faces the surface filter
    // would triangulate past recognition. This one keeps a face a face, and
    // its output is what the element edges are read from. See setMesh().
    m_vtkfacefilter = vtkSmartPointer<vtkUnstructuredGridGeometryFilter>::New();
    m_vtkfacefilter->SetInputConnection(m_vtkclipper->GetOutputPort());

    m_vtkpolyfilter = vtkSmartPointer<vtkGeometryFilter>::New();
    // Level 1 triangulates a quadratic face over its midpoints, so the surface
    // follows the curvature of the elements instead of cutting the corners.
    m_vtkpolyfilter->SetNonlinearSubdivisionLevel(1);
    m_vtkpolyfilter->SetInputConnection(m_vtkclipper->GetOutputPort());

    m_realedges = vtkSmartPointer<vtkPolyData>::New();

    m_vtkwireedges = vtkSmartPointer<vtkExtractEdges>::New();
    m_vtkwireedges->UseAllPointsOn();
    m_vtkwireedges->SetInputConnection(m_vtkclipper->GetOutputPort());

    m_vtksurface = vtkSmartPointer<vtkAppendPolyData>::New();
    m_vtksurface->AddInputData(m_realedges);
    m_vtksurface->AddInputConnection(m_vtkpolyfilter->GetOutputPort());

    // The overlay shows what the display filter takes away, so it bypasses both
    // the visibility mask and the clipper and only follows the dimension mask.
    m_vtkoverlayfilter = makeMaskThreshold(ArrayOverlayFilter);
    m_vtkoverlaypoly = vtkSmartPointer<vtkGeometryFilter>::New();
    m_vtkoverlaypoly->SetInputConnection(m_vtkoverlayfilter->GetOutputPort());

    m_vtkcurrentalgorithm = m_vtksurface;
}

FemMeshRenderer::~FemMeshRenderer()
{
    if (m_separator) {
        m_separator->unref();
    }
    if (m_shapehints) {
        m_shapehints->unref();
    }
    if (m_coordinates) {
        m_coordinates->unref();
    }
    if (m_normalBinding) {
        m_normalBinding->unref();
    }
    if (m_normals) {
        m_normals->unref();
    }
    if (m_pointlinestyle) {
        m_pointlinestyle->unref();
    }
    if (m_markermaterialbinding) {
        m_markermaterialbinding->unref();
    }
    if (m_markermaterial) {
        m_markermaterial->unref();
    }
    if (m_markers) {
        m_markers->unref();
    }
    if (m_edgematerialbinding) {
        m_edgematerialbinding->unref();
    }
    if (m_edgematerial) {
        m_edgematerial->unref();
    }
    if (m_lines) {
        m_lines->unref();
    }
    if (m_celllinestyle) {
        m_celllinestyle->unref();
    }
    if (m_celllinematerialbinding) {
        m_celllinematerialbinding->unref();
    }
    if (m_celllinematerial) {
        m_celllinematerial->unref();
    }
    if (m_celllines) {
        m_celllines->unref();
    }
    if (m_facematerialbinding) {
        m_facematerialbinding->unref();
    }
    if (m_facematerial) {
        m_facematerial->unref();
    }
    if (m_offset) {
        m_offset->unref();
    }
    if (m_faces) {
        m_faces->unref();
    }
    if (m_volumeoffset) {
        m_volumeoffset->unref();
    }
    if (m_volumefaces) {
        m_volumefaces->unref();
    }
    if (m_overlayseparator) {
        m_overlayseparator->unref();
    }
    if (m_overlaymaterialbinding) {
        m_overlaymaterialbinding->unref();
    }
    if (m_overlaymaterial) {
        m_overlaymaterial->unref();
    }
    if (m_overlaycoordinates) {
        m_overlaycoordinates->unref();
    }
    if (m_overlaynormalBinding) {
        m_overlaynormalBinding->unref();
    }
    if (m_overlaynormals) {
        m_overlaynormals->unref();
    }
    if (m_overlayfaces) {
        m_overlayfaces->unref();
    }
}

void FemMeshRenderer::buildSceneGraph()
{
    m_separator = new SoSeparator();
    m_separator->ref();

    m_shapehints = new SoShapeHints();
    m_shapehints->ref();
    m_shapehints->vertexOrdering = SoShapeHints::COUNTERCLOCKWISE;
    m_shapehints->shapeType = SoShapeHints::UNKNOWN_SHAPE_TYPE;

    m_coordinates = new SoCoordinate3();
    m_coordinates->ref();

    m_pointlinestyle = new SoDrawStyle();
    m_pointlinestyle->ref();
    m_pointlinestyle->lineWidth.setValue(2);
    m_pointlinestyle->pointSize.setValue(4);

    // A marker stands for a 0D element and takes the colour of its category.
    // Coin reads the material index of every marker with no release-build
    // bounds check, exactly as it reads the marker index, so the field has to
    // hold one valid entry per drawn marker at all times.
    m_markermaterialbinding = new SoMaterialBinding();
    m_markermaterialbinding->ref();
    m_markermaterialbinding->value = SoMaterialBinding::PER_VERTEX_INDEXED;

    m_markermaterial = new SoMaterial();
    m_markermaterial->ref();

    m_markers = new SoIndexedMarkerSet();
    m_markers->ref();
    // Coin's SoIndexedMarkerSet indexes markerIndex[i] per vertex with no
    // release-build bounds check. Keep a valid default; writeIndexedVerts
    // expands this to one entry per displayed vertex.
    m_markers->markerIndex.setValue(Gui::Inventor::MarkerBitmaps::getMarkerIndex(
        "CIRCLE_FILLED",
        static_cast<int>(App::GetApplication()
                             .GetParameterGroupByPath("User parameter:BaseApp/Preferences/View")
                             ->GetInt("MarkerSize", 7))
    ));

    // The element edges, which are the bulk of everything drawn as a line and
    // are all one colour. Coin only renders an indexed line set through vertex
    // arrays while its material binding is OVERALL, so this set keeps that
    // binding and the handful of lines that are elements get their own.
    m_edgematerialbinding = new SoMaterialBinding();
    m_edgematerialbinding->ref();
    m_edgematerialbinding->value = SoMaterialBinding::OVERALL;

    m_edgematerial = new SoMaterial();
    m_edgematerial->ref();
    m_edgematerial->diffuseColor.setValue(EdgeGrey, EdgeGrey, EdgeGrey);

    m_lines = new SoIndexedLineSet();
    m_lines->ref();

    // The 1D elements. Drawn after the edges and a little wider, because a beam
    // along the edge of a shell is the same line in the same place: the depth
    // test lets an equal value through, so the last one drawn is the one seen,
    // and no polygon offset can help here as it does not reach line primitives.
    m_celllinestyle = new SoDrawStyle();
    m_celllinestyle->ref();
    m_celllinestyle->lineWidth.setValue(3);

    m_celllinematerialbinding = new SoMaterialBinding();
    m_celllinematerialbinding->ref();
    // What an indexed line set reads as PER_LINE_INDEXED.
    m_celllinematerialbinding->value = SoMaterialBinding::PER_FACE_INDEXED;

    m_celllinematerial = new SoMaterial();
    m_celllinematerial->ref();

    m_celllines = new SoIndexedLineSet();
    m_celllines->ref();

    m_normalBinding = new SoNormalBinding();
    m_normalBinding->ref();
    m_normals = new SoNormal();
    m_normals->ref();

    m_facematerialbinding = new SoMaterialBinding();
    m_facematerialbinding->ref();
    m_facematerialbinding->value = SoMaterialBinding::PER_FACE_INDEXED;

    m_facematerial = new SoMaterial();
    m_facematerial->ref();

    // Faces up to a shell sit in front of the faces of the solid elements they
    // may be skinning, and the lines in front of both. Both terms of the offset
    // have to separate the two: the factor alone says nothing about a surface
    // facing the camera, where the depth across a polygon hardly changes.
    m_offset = new SoPolygonOffset();
    m_offset->ref();
    m_offset->factor.setValue(1);
    m_offset->units.setValue(1);

    m_faces = new SoIndexedFaceSet();
    m_faces->ref();

    m_volumeoffset = new SoPolygonOffset();
    m_volumeoffset->ref();
    m_volumeoffset->factor.setValue(2);
    m_volumeoffset->units.setValue(2);

    m_volumefaces = new SoIndexedFaceSet();
    m_volumefaces->ref();

    m_separator->addChild(m_shapehints);
    m_separator->addChild(m_coordinates);
    m_separator->addChild(m_pointlinestyle);
    m_separator->addChild(m_markermaterialbinding);
    m_separator->addChild(m_markermaterial);
    m_separator->addChild(m_markers);
    m_separator->addChild(m_edgematerialbinding);
    m_separator->addChild(m_edgematerial);
    m_separator->addChild(m_lines);
    m_separator->addChild(m_celllinestyle);
    m_separator->addChild(m_celllinematerialbinding);
    m_separator->addChild(m_celllinematerial);
    m_separator->addChild(m_celllines);
    m_separator->addChild(m_normals);
    m_separator->addChild(m_normalBinding);
    m_separator->addChild(m_facematerialbinding);
    m_separator->addChild(m_facematerial);
    m_separator->addChild(m_offset);
    m_separator->addChild(m_faces);
    m_separator->addChild(m_volumeoffset);
    m_separator->addChild(m_volumefaces);

    m_overlayseparator = new SoSeparator();
    m_overlayseparator->ref();
    // The ghost must never take part in picking, otherwise hover and selection
    // would report faces that are not really displayed.
    auto* overlaypick = new SoPickStyle();
    overlaypick->style.setValue(SoPickStyle::Style::UNPICKABLE);
    auto* overlayoffset = new SoPolygonOffset();
    // Behind every real face, the solid elements included.
    overlayoffset->factor.setValue(3);
    overlayoffset->units.setValue(3);

    m_overlaymaterialbinding = new SoMaterialBinding();
    m_overlaymaterialbinding->ref();
    m_overlaymaterialbinding->value = SoMaterialBinding::OVERALL;
    m_overlaymaterial = new SoMaterial();
    m_overlaymaterial->ref();
    m_overlaymaterial->transparency.setValue(0.9f);
    m_overlaycoordinates = new SoCoordinate3();
    m_overlaycoordinates->ref();
    m_overlaynormalBinding = new SoNormalBinding();
    m_overlaynormalBinding->ref();
    m_overlaynormals = new SoNormal();
    m_overlaynormals->ref();
    m_overlayfaces = new SoIndexedFaceSet();
    m_overlayfaces->ref();

    m_separator->addChild(m_overlayseparator);
    m_overlayseparator->addChild(overlaypick);
    m_overlayseparator->addChild(overlayoffset);
    m_overlayseparator->addChild(m_overlaymaterialbinding);
    m_overlayseparator->addChild(m_overlaymaterial);
    m_overlayseparator->addChild(m_overlaycoordinates);
    m_overlayseparator->addChild(m_overlaynormalBinding);
    m_overlayseparator->addChild(m_overlaynormals);
    m_overlayseparator->addChild(m_overlayfaces);

    writePalette();
}

void FemMeshRenderer::writePalette()
{
    const int num = static_cast<int>(m_palette.size());

    m_facematerial->diffuseColor.setNum(num);
    for (int i = 0; i < num; ++i) {
        const auto& c = m_palette[i];
        m_facematerial->diffuseColor.set1Value(i, c.r, c.g, c.b);
    }

    // Points and 1D elements carry one slot past the palette, in the colour of
    // the element edges, for everything the classification does not name.
    for (SoMaterial* material : {m_markermaterial, m_celllinematerial}) {
        material->diffuseColor.setNum(num + 1);
        for (int i = 0; i < num; ++i) {
            const auto& c = m_palette[i];
            material->diffuseColor.set1Value(i, c.r, c.g, c.b);
        }
        material->diffuseColor.set1Value(num, EdgeGrey, EdgeGrey, EdgeGrey);
    }
}

SoSeparator* FemMeshRenderer::root() const
{
    return m_separator;
}

void FemMeshRenderer::setMesh(vtkSmartPointer<vtkUnstructuredGrid> mesh)
{
    m_vtkmesh = mesh;
    forgetPipelineState();
    if (m_vtkmesh) {
        FemVisibilityMask::bakeCellArrays(m_vtkmesh);
        m_vtkfilter->SetInputData(m_vtkmesh);
        m_vtkoverlayfilter->SetInputData(m_vtkmesh);
    }

    // A mesh of straight elements needs no help: the surface filter already
    // hands out one polygon per face, and its sides are the element edges.
    // A curved one it would triangulate, so the outer faces are gathered
    // first, as faces, and the surface is then made of those. That way round
    // costs a little, and the other way round costs a great deal more, the
    // surface filter having a path for straight elements that this has not.
    m_curvedmesh = m_vtkmesh && hasCurvedCells(m_vtkmesh);
    m_vtkpolyfilter->SetInputConnection(
        m_curvedmesh ? m_vtkfacefilter->GetOutputPort() : m_vtkclipper->GetOutputPort()
    );
}

void FemMeshRenderer::forgetPipelineState()
{
    m_writtenvisibility.clear();
    m_writtenoverlay.clear();
    m_writtenclipper.clear();
    m_inputswritten = false;
    m_boundaryfrom = nullptr;
    m_boundarymtime = 0;
    m_pusheddata = nullptr;
    m_pushedmtime = 0;
    m_overlaypushed = nullptr;
    m_overlaypushedmtime = 0;
}

void FemMeshRenderer::setVisibilityMask(const std::vector<unsigned char>& mask)
{
    m_visibilityMask = mask;
}

void FemMeshRenderer::setClipPlanes(const std::map<std::string, ClippingPlane>& planes)
{
    m_clipper = planes;
}

void FemMeshRenderer::setDimensionMode(DimensionMode mode)
{
    // Dimension is applied by consumers through FemVisibilityMask::evaluate +
    // setVisibilityMask. Keep the mode stored for query / future per-dim branches.
    m_dimensionMode = mode;
}

void FemMeshRenderer::setClassification(const Classification* classification)
{
    m_classification = classification;
    if (m_classification) {
        const auto cats = m_classification->categories();
        if (!cats.empty()) {
            std::vector<Base::Color> colors;
            colors.reserve(cats.size());
            for (const auto& c : cats) {
                colors.push_back(c.color);
            }
            setPalette(colors);
        }
    }
}

void FemMeshRenderer::applyVisibilityMask(
    const Fem::FemGeometry* geometry,
    DimensionMode dimMode,
    bool showConstruction,
    const std::set<std::string>& hiddenElements,
    const std::set<std::string>& hiddenCellTypes,
    std::map<std::string, int>* underAchieved
)
{
    m_dimensionMode = dimMode;
    if (!m_vtkmesh) {
        m_visibilityMask.clear();
        if (underAchieved) {
            underAchieved->clear();
        }
        return;
    }
    m_visibilityMask = FemVisibilityMask::evaluate(
        m_vtkmesh,
        geometry,
        dimMode,
        showConstruction,
        hiddenElements,
        hiddenCellTypes,
        underAchieved
    );
}

void FemMeshRenderer::setPalette(const std::vector<Base::Color>& colors)
{
    if (colors.empty()) {
        m_palette = distinctColors();
    }
    else {
        m_palette = colors;
    }
    writePalette();
}

void FemMeshRenderer::setWireframe(bool wireframe)
{
    // The two branches end in different outputs, and each of them may still
    // hold, unchanged, what it produced before the last switch away. What Coin
    // holds is whichever was pushed last, so the swap has to be remembered.
    m_pusheddata = nullptr;
    m_pushedmtime = 0;

    m_wireframe = wireframe;
    m_vtkcurrentalgorithm = m_wireframe
        ? static_cast<vtkPolyDataAlgorithm*>(m_vtkwireedges.Get())
        : static_cast<vtkPolyDataAlgorithm*>(m_vtksurface.Get());
}

void FemMeshRenderer::setOverlay(bool on)
{
    m_overlayEnabled = on;
}

void FemMeshRenderer::setOverlayMask(const std::vector<unsigned char>& mask)
{
    m_overlayMask = mask;
}

void FemMeshRenderer::clearGeometry()
{
    m_markers->coordIndex.setNum(0);
    m_markers->markerIndex.setNum(0);
    m_markers->materialIndex.setNum(0);
    m_lines->coordIndex.setNum(0);
    m_celllines->coordIndex.setNum(0);
    m_celllines->materialIndex.setNum(0);
    m_faces->coordIndex.setNum(0);
    m_faces->materialIndex.setNum(0);
    m_volumefaces->coordIndex.setNum(0);
    m_volumefaces->materialIndex.setNum(0);

    m_markercells.clear();
    m_celllinecells.clear();
    m_facecells.clear();
    m_volumecells.clear();
}

void FemMeshRenderer::updateVTK()
{
    if (!m_vtkmesh) {
        clearGeometry();
        m_overlayfaces->coordIndex.setNum(0);
        forgetPipelineState();
        return;
    }

    FEM_PERF_SCOPE("mesh.render.vtk");

    // Everything below is written only when it differs from what the filter was
    // last given. Writing values into an array does not mark it modified, which
    // is why the threshold has to be told by hand, and telling it is exactly
    // what throws away the whole pipeline VTK has cached behind it. An update
    // that changes neither what is hidden nor where the clip plane is -- a
    // change of stage, or of any instance other than the one being touched --
    // then costs nothing at all.
    {
        FEM_PERF_SCOPE("mesh.render.vtk.writeMasks");
        if (!m_inputswritten || m_writtenvisibility != m_visibilityMask) {
            writeMaskArray(m_vtkmesh, ArrayFilter, m_visibilityMask);
            m_vtkfilter->Modified();
            m_writtenvisibility = m_visibilityMask;
        }
        if (!m_inputswritten || m_writtenoverlay != m_overlayMask) {
            writeMaskArray(m_vtkmesh, ArrayOverlayFilter, m_overlayMask);
            m_vtkoverlayfilter->Modified();
            m_writtenoverlay = m_overlayMask;
        }
    }

    if (!m_inputswritten || m_writtenclipper != m_clipper) {
        if (!m_clipper.empty()) {
            auto clip_function = vtkSmartPointer<vtkImplicitBoolean>::New();
            clip_function->SetOperationType(vtkImplicitBoolean::VTK_UNION);
            for (const auto& clip : m_clipper) {
                auto plane = vtkSmartPointer<vtkPlane>::New();
                plane->SetNormal(
                    clip.second.Direction.x,
                    clip.second.Direction.y,
                    clip.second.Direction.z
                );
                plane->SetOrigin(clip.second.Origin.x, clip.second.Origin.y, clip.second.Origin.z);
                clip_function->AddFunction(plane);
            }
            m_vtkclipper->SetImplicitFunction(clip_function);
        }
        else {
            auto sphere = vtkSmartPointer<vtkSphere>::New();
            sphere->SetRadius(1e9);
            m_vtkclipper->SetImplicitFunction(sphere);
        }
        m_vtkclipper->SetExtractInside(m_clipper.empty());
        m_writtenclipper = m_clipper;
    }

    m_inputswritten = true;

    {
        // Pulled one filter at a time rather than only at the end, so that the
        // perf log can say which of them an update is waiting for. A filter
        // that is up to date returns from Update() without running, so asking
        // in order costs nothing over asking the last one.
        FEM_PERF_SCOPE("mesh.render.vtk.pipeline");
        {
            FEM_PERF_SCOPE("mesh.render.vtk.pipeline.threshold");
            m_vtkfilter->Update();
        }
        {
            FEM_PERF_SCOPE("mesh.render.vtk.pipeline.clip");
            m_vtkclipper->Update();
        }
        if (!m_wireframe) {
            FEM_PERF_SCOPE("mesh.render.vtk.pipeline.surface");
            m_vtkpolyfilter->Update();
        }
        if (m_wireframe) {
            FEM_PERF_SCOPE("mesh.render.vtk.pipeline.edges");
            m_vtkwireedges->Update();
        }
        else {
            buildBoundaryEdges();
        }
        m_vtkcurrentalgorithm->Update();
    }

    auto* visdata = m_vtkcurrentalgorithm->GetOutput();
    if (visdata != m_pusheddata || visdata->GetMTime() != m_pushedmtime) {
        pushPolyDataToCoin(visdata);
        m_pusheddata = visdata;
        m_pushedmtime = visdata->GetMTime();
    }
    updateOverlay();
}

void FemMeshRenderer::buildBoundaryEdges()
{
    // What is on the outside of the mesh, one cell per face of it: polygons
    // from the surface filter for a mesh of straight elements, and the faces
    // themselves for a curved one, which the surface filter would have
    // triangulated. Either way the edges wanted are the sides of these.
    vtkPointSet* surface = m_curvedmesh ? static_cast<vtkPointSet*>(m_vtkfacefilter->GetOutput())
                                        : static_cast<vtkPointSet*>(m_vtkpolyfilter->GetOutput());
    if (surface && surface == m_boundaryfrom && surface->GetMTime() == m_boundarymtime) {
        return;
    }
    m_boundaryfrom = surface;
    m_boundarymtime = surface ? surface->GetMTime() : 0;

    FEM_PERF_SCOPE("mesh.render.vtk.pipeline.elementEdges");

    m_realedges->Initialize();
    // Which cell of the mesh each face came from. Not vtkOriginalCellIds: the
    // surface filter numbers those by the intermediate faces it makes of a
    // quadratic cell, not by the cells it was given, so on a quadratic mesh
    // they name the wrong cells and run off the end of it. The baked array
    // says it outright and is carried through as ordinary cell data.
    auto* origin =
        surface ? vtkIntArray::SafeDownCast(
                      surface->GetCellData()->GetArray(FemVisibilityMask::ArrayOrigCell)
                  )
                : nullptr;
    if (!origin) {
        m_realedges->Modified();
        return;
    }

    // Points are numbered as they are met rather than looked up by position.
    // A locator exists to work out which points coincide, and here nothing
    // does: the ids say it already. What is drawn stays as small as the edges
    // need, instead of carrying the interior of the mesh to Coin.
    m_pointmap.assign(static_cast<size_t>(surface->GetNumberOfPoints()), -1);

    const vtkIdType numfaces = surface->GetNumberOfCells();
    const auto edgeguess = static_cast<std::size_t>(numfaces) * 4;

    auto points = vtkSmartPointer<vtkPoints>::New();
    if (auto* source = surface->GetPoints()) {
        points->SetDataType(source->GetDataType());
    }
    auto lines = vtkSmartPointer<vtkCellArray>::New();
    lines->AllocateEstimate(static_cast<vtkIdType>(edgeguess), 3);

    // Of everything the cells carry, only the cell each drawn one came from is
    // ever asked for again, by the colouring. Copying the rest through costs
    // more than the edges themselves, and here it is the id we already walk by.
    auto outcell = vtkSmartPointer<vtkIntArray>::New();
    outcell->SetName(FemVisibilityMask::ArrayOrigCell);
    outcell->SetNumberOfComponents(1);
    outcell->Allocate(static_cast<vtkIdType>(edgeguess));

    // Neighbouring cells share edges, and an edge drawn twice is an edge drawn
    // twice as slowly. Its two ends name it, whichever cell reports it.
    //
    // The plainest hash set there is: a power-of-two table of keys, probed
    // linearly, empty where it is zero, which no edge can be since an edge
    // joins two different points. A general one spends more time following
    // pointers than this whole walk does enumerating the edges.
    std::size_t capacity = 16;
    while (capacity < edgeguess * 2 + 16) {
        capacity <<= 1;
    }
    m_edgeseen.assign(capacity, 0);
    const std::size_t mask = capacity - 1;
    auto unseen = [this, mask](std::uint64_t key) {
        std::size_t at = static_cast<std::size_t>((key * 0x9E3779B97F4A7C15ULL) >> 32) & mask;
        while (true) {
            std::uint64_t& slot = m_edgeseen[at];
            if (slot == 0) {
                slot = key;
                return true;
            }
            if (slot == key) {
                return false;
            }
            at = (at + 1) & mask;
        }
    };

    std::vector<vtkIdType> chain;
    std::vector<vtkIdType> mapped;

    auto pointOf = [this, &points, surface](vtkIdType id) {
        vtkIdType& at = m_pointmap[static_cast<size_t>(id)];
        if (at < 0) {
            double xyz[3];
            surface->GetPoint(id, xyz);
            at = points->InsertNextPoint(xyz);
        }
        return at;
    };

    // The whole edge goes in as one line, curved ones included. Two lines
    // meeting at a midpoint leave it to chance whether the midpoint is drawn,
    // and OpenGL tends to decide that it is not; within one line there is no
    // such question.
    //
    // A 1D element is claimed without being drawn. It is not an element edge:
    // the surface filter hands it over as a line of its own, through the same
    // points, and that copy is the one coloured as the element it is. Claiming
    // it here is still what keeps a face lying along it from drawing a dark
    // edge over the top of it.
    auto emit = [&](vtkIdType owner, bool draw = true) {
        // An edge that ends where it starts has no key of its own, zero being
        // the one the table reads as an empty slot, and nothing to draw either.
        if (chain.size() < 2 || chain.front() == chain.back()) {
            return;
        }
        if (!unseen(edgeKey(chain.front(), chain.back()))) {
            return;
        }
        if (!draw) {
            return;
        }
        mapped.clear();
        for (vtkIdType id : chain) {
            mapped.push_back(pointOf(id));
        }
        lines->InsertNextCell(static_cast<int>(mapped.size()), mapped.data());
        outcell->InsertNextValue(static_cast<int>(owner));
    };

    // VTK numbers a curved edge with its two ends first and the points between
    // them after, so walking one means going out to the middle and back.
    auto chainOf = [&chain](vtkIdList* ids) {
        chain.clear();
        const vtkIdType num = ids->GetNumberOfIds();
        if (num < 2) {
            return;
        }
        chain.push_back(ids->GetId(0));
        for (vtkIdType i = 2; i < num; ++i) {
            chain.push_back(ids->GetId(i));
        }
        chain.push_back(ids->GetId(1));
    };

    if (m_curvedmesh) {
        // Asking each face for its edges, which is what knows where the points
        // between the corners belong. It reads a whole cell out to answer, and
        // is the reason the straight case does not go this way.
        auto cell = vtkSmartPointer<vtkGenericCell>::New();
        for (vtkIdType face = 0; face < numfaces; ++face) {
            surface->GetCell(face, cell);
            const int owner = origin->GetValue(face);
            const int numedges = cell->GetNumberOfEdges();

            // A point or a beam has no edges of its own to report; its own
            // points are where an element edge would run.
            if (numedges == 0) {
                chainOf(cell->GetPointIds());
                emit(owner, false);
                continue;
            }
            for (int e = 0; e < numedges; ++e) {
                chainOf(cell->GetEdge(e)->GetPointIds());
                emit(owner);
            }
        }
    }
    else {
        // Straight elements have nothing between their corners, so the sides
        // of a polygon can be read off the connectivity as it lies. The cell
        // data counts the vertices and the lines before the polygons.
        auto* poly = static_cast<vtkPolyData*>(surface);
        const vtkIdType numverts = poly->GetNumberOfVerts();
        const vtkIdType numlines = poly->GetNumberOfLines();
        auto ids = vtkSmartPointer<vtkIdList>::New();

        // Claimed before the faces are walked, so that a beam always wins the
        // edge it shares with one. The grid is written in rising dimension,
        // and the filters keep that order, so the curved branch above meets
        // them in the same order for the same reason.
        auto* beams = poly->GetLines();
        for (vtkIdType at = 0; at < numlines; ++at) {
            beams->GetCellAtId(at, ids);
            chain.assign(ids->begin(), ids->end());
            emit(origin->GetValue(numverts + at), false);
        }

        auto* faces = poly->GetPolys();
        const vtkIdType numfacecells = faces->GetNumberOfCells();
        for (vtkIdType at = 0; at < numfacecells; ++at) {
            faces->GetCellAtId(at, ids);
            const vtkIdType corners = ids->GetNumberOfIds();
            const int owner = origin->GetValue(numverts + numlines + at);
            for (vtkIdType i = 0; i < corners; ++i) {
                chain.clear();
                chain.push_back(ids->GetId(i));
                chain.push_back(ids->GetId((i + 1) % corners));
                emit(owner);
            }
        }
    }

    m_realedges->SetPoints(points);
    m_realedges->SetLines(lines);
    m_realedges->GetCellData()->AddArray(outcell);
    m_realedges->Modified();
}

void FemMeshRenderer::updateOverlay()
{
    // Nothing is missing from the view when the overlay mask matches what is
    // displayed and no clipping or wireframe hides anything, so drawing a ghost
    // on top of the mesh itself would only dull its colours.
    const bool anythingFiltered =
        m_wireframe || !m_clipper.empty() || m_overlayMask != m_visibilityMask;
    if (!m_overlayEnabled || m_overlayMask.empty() || !anythingFiltered) {
        m_overlayfaces->coordIndex.setNum(0);
        m_overlaypushed = nullptr;
        return;
    }
    FEM_PERF_SCOPE("mesh.render.overlay");

    m_vtkoverlaypoly->Update();
    auto* visdata = m_vtkoverlaypoly->GetOutput();
    if (!visdata || visdata->GetNumberOfPolys() == 0) {
        m_overlayfaces->coordIndex.setNum(0);
        m_overlaypushed = nullptr;
        return;
    }

    if (visdata == m_overlaypushed && visdata->GetMTime() == m_overlaypushedmtime) {
        return;
    }
    m_overlaypushed = visdata;
    m_overlaypushedmtime = visdata->GetMTime();

    auto* pntData = visdata->GetPointData();
    writePointData(
        m_overlaycoordinates,
        m_overlaynormals,
        m_overlaynormalBinding,
        visdata->GetPoints(),
        pntData ? pntData->GetNormals() : nullptr,
        pntData ? pntData->GetTCoords() : nullptr
    );
    writeIndexedPolys(m_overlayfaces, visdata->GetPolys());
}

void FemMeshRenderer::pushPolyDataToCoin(vtkPolyData* visdata)
{
    if (!visdata || visdata->GetNumberOfCells() == 0) {
        clearGeometry();
        return;
    }

    FEM_PERF_SCOPE("mesh.toCoin");

    {
        FEM_PERF_SCOPE("mesh.toCoin.points");
        auto pntData = visdata->GetPointData();
        writePointData(
            m_coordinates,
            m_normals,
            m_normalBinding,
            visdata->GetPoints(),
            pntData ? pntData->GetNormals() : nullptr,
            pntData ? pntData->GetTCoords() : nullptr
        );
    }

    // Which mesh cell each drawn cell came from, and of what dimension. The
    // first is carried through the whole pipeline as ordinary cell data, the
    // second is baked on the input grid once, so both are a single array read.
    // A wireframe answers neither -- its edges belong to no one cell -- and
    // then everything falls into the group it would have been in before any
    // of this: the edges dark, the faces under the nearer of the two offsets.
    auto* origin = vtkIntArray::SafeDownCast(
        visdata->GetCellData()->GetArray(FemVisibilityMask::ArrayOrigCell)
    );
    auto* celldim = m_vtkmesh ? vtkIntArray::SafeDownCast(
                        m_vtkmesh->GetCellData()->GetArray(FemVisibilityMask::ArrayCellDim)
                    )
                              : nullptr;
    const vtkIdType numorigin = origin ? origin->GetNumberOfTuples() : 0;
    const vtkIdType numdim = celldim ? celldim->GetNumberOfTuples() : 0;

    auto ownerOf = [&](vtkIdType cell) {
        return (cell < numorigin) ? origin->GetValue(cell) : -1;
    };
    auto dimensionOf = [&](int owner) {
        return (owner >= 0 && owner < numdim) ? celldim->GetValue(owner) : -1;
    };

    // Verts, lines and polys are numbered in that order within the cell data
    // of a polydata, which is what the cell of a drawn one has to be found by.
    const vtkIdType numverts = visdata->GetNumberOfVerts();
    const vtkIdType numlines = visdata->GetNumberOfLines();

    if (visdata->GetNumberOfPolys() > 0) {
        FEM_PERF_SCOPE("mesh.toCoin.faces");
        writeSplitCellIndices(
            m_faces->coordIndex,
            &m_facecells,
            m_volumefaces->coordIndex,
            &m_volumecells,
            visdata->GetPolys(),
            numverts + numlines,
            ownerOf,
            [&](int owner) {
                return dimensionOf(owner) == 3;
            }
        );
    }
    else {
        m_faces->coordIndex.setNum(0);
        m_volumefaces->coordIndex.setNum(0);
        m_facecells.clear();
        m_volumecells.clear();
    }

    if (numlines > 0) {
        FEM_PERF_SCOPE("mesh.toCoin.lines");
        // The element edges are all one colour, so which cell each of them
        // came from is of no further interest and the list of that is the one
        // list here that would run to the size of the surface.
        writeSplitCellIndices(
            m_lines->coordIndex,
            nullptr,
            m_celllines->coordIndex,
            &m_celllinecells,
            visdata->GetLines(),
            numverts,
            ownerOf,
            [&](int owner) {
                return dimensionOf(owner) == 1;
            }
        );
    }
    else {
        m_lines->coordIndex.setNum(0);
        m_celllines->coordIndex.setNum(0);
        m_celllinecells.clear();
    }

    if (numverts > 0) {
        FEM_PERF_SCOPE("mesh.toCoin.markers");
        writeIndexedVerts(m_markers, visdata->GetVerts(), &m_markercells);
        for (int& cell : m_markercells) {
            cell = ownerOf(cell);
        }
    }
    else {
        m_markers->coordIndex.setNum(0);
        m_markers->markerIndex.setNum(0);
        m_markercells.clear();
    }

    // Nothing may be left indexing a material that is not there: Coin reads
    // the index of every primitive of an indexed binding and only clamps it
    // when it was built for debugging. The colours themselves come later.
    const int edge = edgePaletteSlot();
    fillMaterialIndex(m_markers->materialIndex, m_markercells.size(), edge);
    fillMaterialIndex(m_celllines->materialIndex, m_celllinecells.size(), edge);
    fillMaterialIndex(m_faces->materialIndex, m_facecells.size(), 0);
    fillMaterialIndex(m_volumefaces->materialIndex, m_volumecells.size(), 0);
}

void FemMeshRenderer::writeMaterialIndex(
    SoMFInt32& field,
    const std::vector<int>& cells,
    int fallback
) const
{
    const int num = static_cast<int>(cells.size());
    field.setNum(num);
    if (num == 0) {
        return;
    }

    const int categories = m_classification
        ? static_cast<int>(m_classification->categories().size())
        : 0;

    int32_t* indices = field.startEditing();
    if (categories <= 0) {
        std::fill(indices, indices + num, static_cast<int32_t>(fallback));
    }
    else {
        for (int i = 0; i < num; ++i) {
            // categoryOfCell uses the classification built from input-grid
            // cells (with FaceN→SolidN resolution). The cell ids here come
            // from the origcell array, which survives the VTK threshold and
            // clip; do not fall back to vtkOriginalCellIds.
            int category = cells[i] >= 0 ? m_classification->categoryOfCell(cells[i]) : 0;
            if (category < 0) {
                category = 0;
            }
            indices[i] = static_cast<int32_t>(category % categories);
        }
    }
    field.finishEditing();
}

void FemMeshRenderer::updateColors()
{
    FEM_PERF_SCOPE("mesh.colors");

    m_facematerialbinding->value.setValue(SoMaterialBinding::PER_FACE_INDEXED);

    // A face of an element the classification says nothing about keeps the
    // first palette entry, as it did before there were categories. A point or
    // a 1D element falls back to the colour of the element edges instead, so
    // that an unclassified mesh is drawn in one colour and its edges.
    const int edge = edgePaletteSlot();
    writeMaterialIndex(m_markers->materialIndex, m_markercells, edge);
    writeMaterialIndex(m_celllines->materialIndex, m_celllinecells, edge);
    writeMaterialIndex(m_faces->materialIndex, m_facecells, 0);
    writeMaterialIndex(m_volumefaces->materialIndex, m_volumecells, 0);
}

void FemMeshRenderer::update()
{
    updateVTK();
    updateColors();
}

vtkPolyData* FemMeshRenderer::currentPolyData() const
{
    return m_vtkcurrentalgorithm ? m_vtkcurrentalgorithm->GetOutput() : nullptr;
}

namespace
{

// Writes every cell of the array as its point indices followed by the -1 that
// closes a Coin index list.
//
// Coin grows a multi-field to exactly the size asked for, so set1Value past the
// end reallocates and copies the whole field on every single index. Sizing the
// field once and writing through the edit pointer is the same loop without the
// quadratic behaviour, and on a mesh of any size it is the difference between
// milliseconds and seconds.
void writeCellIndices(SoMFInt32& field, vtkCellArray* cells)
{
    const vtkIdType nCells = cells->GetNumberOfCells();
    const vtkIdType nIndices = cells->GetNumberOfConnectivityIds() + nCells;

    field.setNum(static_cast<int>(nIndices));
    if (nIndices == 0) {
        return;
    }

    int32_t* indices = field.startEditing();
    int soidx = 0;
    vtkIdType npts = 0;
    const vtkIdType* indx = nullptr;
    for (cells->InitTraversal(); cells->GetNextCell(npts, indx);) {
        for (vtkIdType i = 0; i < npts; ++i) {
            indices[soidx++] = static_cast<int32_t>(indx[i]);
        }
        indices[soidx++] = -1;
    }
    field.finishEditing();
}

}  // namespace

void FemMeshRenderer::writePointData(
    SoCoordinate3* coord_node,
    SoNormal* normal_node,
    SoNormalBinding* normal_binding,
    vtkPoints* points,
    vtkDataArray* normals,
    vtkDataArray* tcoords
)
{
    (void)tcoords;

    if (!points || !coord_node) {
        return;
    }

    coord_node->point.setNum(points->GetNumberOfPoints());
    SbVec3f* pnts = coord_node->point.startEditing();
    for (vtkIdType i = 0; i < points->GetNumberOfPoints(); ++i) {
        double* p = points->GetPoint(i);
        pnts[i].setValue(static_cast<float>(p[0]), static_cast<float>(p[1]), static_cast<float>(p[2]));
    }
    coord_node->point.finishEditing();

    if (normal_node && normal_binding && normals) {
        normal_node->vector.setNum(normals->GetNumberOfTuples());
        SbVec3f* dirs = normal_node->vector.startEditing();
        for (vtkIdType i = 0; i < normals->GetNumberOfTuples(); ++i) {
            double* p = normals->GetTuple(i);
            dirs[i].setValue(
                static_cast<float>(p[0]),
                static_cast<float>(p[1]),
                static_cast<float>(p[2])
            );
        }
        normal_node->vector.finishEditing();
        normal_binding->value = SoNormalBinding::PER_VERTEX_INDEXED;
        normal_binding->value.touch();
    }
}

void FemMeshRenderer::writeIndexedPolys(SoIndexedFaceSet* faces, vtkCellArray* cells)
{
    if (!faces || !cells) {
        return;
    }

    writeCellIndices(faces->coordIndex, cells);
}

void FemMeshRenderer::writeIndexedVerts(
    SoIndexedMarkerSet* markers,
    vtkCellArray* cells,
    std::vector<int>* drawn
)
{
    if (drawn) {
        drawn->clear();
    }
    if (!markers || !cells) {
        return;
    }

    const int markerId = Gui::Inventor::MarkerBitmaps::getMarkerIndex(
        "CIRCLE_FILLED",
        static_cast<int>(App::GetApplication()
                             .GetParameterGroupByPath("User parameter:BaseApp/Preferences/View")
                             ->GetInt("MarkerSize", 7))
    );

    // Must match coordIndex length: Coin reads markerIndex[i] for every vertex
    // without clamping when COIN_DEBUG is off.
    const int nCells = static_cast<int>(cells->GetNumberOfCells());
    markers->coordIndex.setNum(nCells);
    markers->markerIndex.setNum(nCells);
    if (nCells == 0) {
        return;
    }
    if (drawn) {
        drawn->reserve(static_cast<std::size_t>(nCells));
    }

    int32_t* coords = markers->coordIndex.startEditing();
    int32_t* ids = markers->markerIndex.startEditing();
    int soidx = 0;
    vtkIdType at = 0;
    vtkIdType npts = 0;
    const vtkIdType* indx = nullptr;
    for (cells->InitTraversal(); cells->GetNextCell(npts, indx); ++at) {
        if (npts < 1) {
            continue;
        }
        coords[soidx] = static_cast<int32_t>(indx[0]);
        ids[soidx] = markerId;
        ++soidx;
        if (drawn) {
            drawn->push_back(static_cast<int>(at));
        }
    }
    markers->coordIndex.finishEditing();
    markers->markerIndex.finishEditing();

    // An empty cell is not expected, but a shorter list must not leave stale
    // indices behind for Coin to draw.
    if (soidx < nCells) {
        markers->coordIndex.setNum(soidx);
        markers->markerIndex.setNum(soidx);
    }
}
