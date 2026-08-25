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
# include <vtkDoubleArray.h>
# include <vtkIdTypeArray.h>
# include <vtkImplicitBoolean.h>
# include <vtkIntArray.h>
# include <vtkPlane.h>
# include <vtkPointData.h>
# include <vtkSphere.h>
#endif

#include "Classification.h"
#include "FemMeshRenderer.h"
#include "FemVisibilityMask.h"

#include <App/Application.h>
#include <Base/Console.h>
#include <Gui/Inventor/MarkerBitmaps.h>

using namespace FemGui;

const std::vector<Base::Color>& FemMeshRenderer::distinctColors()
{
    static const std::vector<Base::Color> colors = {
        Base::Color(0.863f, 0.196f, 0.184f),  //  1 Crimson red
        Base::Color(0.102f, 0.451f, 0.910f),  //  2 Cobalt blue
        Base::Color(0.196f, 0.804f, 0.314f),  //  3 Lime green
        Base::Color(1.000f, 0.647f, 0.000f),  //  4 Amber orange
        Base::Color(0.706f, 0.235f, 0.824f),  //  5 Violet purple
        Base::Color(0.000f, 0.784f, 0.824f),  //  6 Cyan teal
        Base::Color(0.941f, 0.863f, 0.118f),  //  7 Vivid yellow
        Base::Color(0.863f, 0.353f, 0.588f),  //  8 Hot pink
        Base::Color(0.118f, 0.627f, 0.392f),  //  9 Emerald green
        Base::Color(1.000f, 0.392f, 0.118f),  // 10 Burnt orange
        Base::Color(0.314f, 0.314f, 0.863f),  // 11 Royal blue
        Base::Color(0.784f, 0.784f, 0.235f),  // 12 Olive yellow
        Base::Color(0.627f, 0.118f, 0.235f),  // 13 Deep crimson
        Base::Color(0.235f, 0.784f, 0.706f),  // 14 Aquamarine
        Base::Color(1.000f, 0.784f, 0.471f),  // 15 Peach
        Base::Color(0.471f, 0.157f, 0.784f),  // 16 Indigo
        Base::Color(0.392f, 0.784f, 0.157f),  // 17 Chartreuse
        Base::Color(0.784f, 0.157f, 0.471f),  // 18 Magenta rose
        Base::Color(0.157f, 0.471f, 0.784f),  // 19 Sky blue
        Base::Color(0.824f, 0.627f, 0.196f),  // 20 Gold
        Base::Color(0.314f, 0.784f, 0.627f),  // 21 Seafoam
        Base::Color(0.784f, 0.314f, 0.157f),  // 22 Tomato
        Base::Color(0.549f, 0.314f, 0.863f),  // 23 Lavender purple
        Base::Color(0.157f, 0.627f, 0.157f),  // 24 Forest green
        Base::Color(0.863f, 0.510f, 0.706f),  // 25 Orchid pink
        Base::Color(0.078f, 0.314f, 0.706f),  // 26 Navy blue
        Base::Color(0.706f, 0.863f, 0.314f),  // 27 Yellow-green
        Base::Color(0.784f, 0.235f, 0.784f),  // 28 Fuchsia
        Base::Color(0.118f, 0.706f, 0.863f),  // 29 Azure
        Base::Color(0.941f, 0.706f, 0.235f),  // 30 Sunflower
        Base::Color(0.235f, 0.549f, 0.314f),  // 31 Sage green
        Base::Color(0.706f, 0.157f, 0.157f),  // 32 Dark red
    };
    return colors;
}

namespace
{

constexpr const char* ArrayFilter = "filter";
constexpr const char* ArrayOverlayFilter = "overlayfilter";

vtkSmartPointer<vtkThreshold> makeMaskThreshold(const char* arrayname)
{
    auto filter = vtkSmartPointer<vtkThreshold>::New();
    filter->AllScalarsOff();
    filter->SetThresholdFunction(vtkThreshold::THRESHOLD_UPPER);
    filter->SetUpperThreshold(0.5);
    filter->SetInputArrayToProcess(0, 0, 0, vtkDataObject::FIELD_ASSOCIATION_CELLS, arrayname);
    return filter;
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

    m_vtksurfedges = vtkSmartPointer<vtkExtractEdges>::New();
    m_vtksurfedges->SetInputConnection(m_vtkclipper->GetOutputPort());

    // vtkGeometryFilter linearises quadratic cells; append raw edges for correct wireframe.
    m_vtkpolyfilter = vtkSmartPointer<vtkGeometryFilter>::New();
    m_vtkpolyfilter->SetInputConnection(m_vtkclipper->GetOutputPort());

    m_vtksurface = vtkSmartPointer<vtkAppendPolyData>::New();
    m_vtksurface->AddInputConnection(m_vtksurfedges->GetOutputPort());
    m_vtksurface->AddInputConnection(m_vtkpolyfilter->GetOutputPort());

    m_vtkwireedges = vtkSmartPointer<vtkExtractEdges>::New();
    m_vtkwireedges->SetInputConnection(m_vtkclipper->GetOutputPort());

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
    if (m_pointlinematerialbinding) {
        m_pointlinematerialbinding->unref();
    }
    if (m_pointlinematerial) {
        m_pointlinematerial->unref();
    }
    if (m_pointlinestyle) {
        m_pointlinestyle->unref();
    }
    if (m_markers) {
        m_markers->unref();
    }
    if (m_lines) {
        m_lines->unref();
    }
    if (m_facematerialbinding) {
        m_facematerialbinding->unref();
    }
    if (m_facematerial) {
        m_facematerial->unref();
    }
    if (m_faces) {
        m_faces->unref();
    }
    if (m_offset) {
        m_offset->unref();
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

    m_pointlinematerialbinding = new SoMaterialBinding();
    m_pointlinematerialbinding->ref();
    m_pointlinematerialbinding->value = SoMaterialBinding::OVERALL;

    m_pointlinematerial = new SoMaterial();
    m_pointlinematerial->ref();
    m_pointlinematerial->diffuseColor.setValue(0.2f, 0.2f, 0.2f);

    m_pointlinestyle = new SoDrawStyle();
    m_pointlinestyle->ref();
    m_pointlinestyle->lineWidth.setValue(2);
    m_pointlinestyle->pointSize.setValue(4);

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
    m_lines = new SoIndexedLineSet();
    m_lines->ref();

    m_offset = new SoPolygonOffset();
    m_offset->ref();
    m_offset->factor.setValue(1);

    m_normalBinding = new SoNormalBinding();
    m_normalBinding->ref();
    m_normals = new SoNormal();
    m_normals->ref();

    m_facematerialbinding = new SoMaterialBinding();
    m_facematerialbinding->ref();
    m_facematerialbinding->value = SoMaterialBinding::PER_FACE_INDEXED;

    m_facematerial = new SoMaterial();
    m_facematerial->ref();

    m_faces = new SoIndexedFaceSet();
    m_faces->ref();

    m_separator->addChild(m_shapehints);
    m_separator->addChild(m_coordinates);
    m_separator->addChild(m_pointlinematerialbinding);
    m_separator->addChild(m_pointlinematerial);
    m_separator->addChild(m_pointlinestyle);
    m_separator->addChild(m_markers);
    m_separator->addChild(m_lines);
    m_separator->addChild(m_offset);
    m_separator->addChild(m_normals);
    m_separator->addChild(m_normalBinding);
    m_separator->addChild(m_facematerialbinding);
    m_separator->addChild(m_facematerial);
    m_separator->addChild(m_faces);

    m_overlayseparator = new SoSeparator();
    m_overlayseparator->ref();
    // The ghost must never take part in picking, otherwise hover and selection
    // would report faces that are not really displayed.
    auto* overlaypick = new SoPickStyle();
    overlaypick->style.setValue(SoPickStyle::Style::UNPICKABLE);
    auto* overlayoffset = new SoPolygonOffset();
    overlayoffset->factor.setValue(2);

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

    // Seed palette into SoMaterial for PER_FACE_INDEXED
    m_facematerial->diffuseColor.setNum(static_cast<int>(m_palette.size()));
    for (size_t i = 0; i < m_palette.size(); ++i) {
        const auto& c = m_palette[i];
        m_facematerial->diffuseColor.set1Value(static_cast<int>(i), c.r, c.g, c.b);
    }
}

SoSeparator* FemMeshRenderer::root() const
{
    return m_separator;
}

void FemMeshRenderer::setMesh(vtkSmartPointer<vtkUnstructuredGrid> mesh)
{
    m_vtkmesh = mesh;
    if (m_vtkmesh) {
        FemVisibilityMask::bakeCellArrays(m_vtkmesh);
        m_vtkfilter->SetInputData(m_vtkmesh);
        m_vtkoverlayfilter->SetInputData(m_vtkmesh);
    }
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
    const std::set<std::string>& hiddenElements,
    const std::set<std::string>& hiddenCellTypes,
    std::set<std::string>* underAchieved
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
    m_facematerial->diffuseColor.setNum(static_cast<int>(m_palette.size()));
    for (size_t i = 0; i < m_palette.size(); ++i) {
        const auto& c = m_palette[i];
        m_facematerial->diffuseColor.set1Value(static_cast<int>(i), c.r, c.g, c.b);
    }
}

void FemMeshRenderer::setWireframe(bool wireframe)
{
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

void FemMeshRenderer::updateVTK()
{
    if (!m_vtkmesh) {
        m_faces->coordIndex.setNum(0);
        m_lines->coordIndex.setNum(0);
        m_markers->coordIndex.setNum(0);
        m_markers->markerIndex.setNum(0);
        m_overlayfaces->coordIndex.setNum(0);
        return;
    }

    writeMaskArray(m_vtkmesh, ArrayFilter, m_visibilityMask);
    m_vtkfilter->Modified();
    writeMaskArray(m_vtkmesh, ArrayOverlayFilter, m_overlayMask);
    m_vtkoverlayfilter->Modified();

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

    m_vtkcurrentalgorithm->Update();
    pushPolyDataToCoin(m_vtkcurrentalgorithm->GetOutput());
    updateOverlay();
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
        return;
    }

    m_vtkoverlaypoly->Update();
    auto* visdata = m_vtkoverlaypoly->GetOutput();
    if (!visdata || visdata->GetNumberOfPolys() == 0) {
        m_overlayfaces->coordIndex.setNum(0);
        return;
    }

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
        m_faces->coordIndex.setNum(0);
        m_lines->coordIndex.setNum(0);
        m_markers->coordIndex.setNum(0);
        m_markers->markerIndex.setNum(0);
        return;
    }

    auto pntData = visdata->GetPointData();
    writePointData(
        m_coordinates,
        m_normals,
        m_normalBinding,
        visdata->GetPoints(),
        pntData ? pntData->GetNormals() : nullptr,
        pntData ? pntData->GetTCoords() : nullptr
    );

    if (visdata->GetNumberOfPolys() > 0) {
        writeIndexedPolys(m_faces, visdata->GetPolys());
    }
    else {
        m_faces->coordIndex.setNum(0);
    }

    if (visdata->GetNumberOfLines() > 0) {
        writeIndexedLines(m_lines, visdata->GetLines());
    }
    else {
        m_lines->coordIndex.setNum(0);
    }

    if (visdata->GetNumberOfVerts() > 0) {
        writeIndexedVerts(m_markers, visdata->GetVerts());
    }
    else {
        m_markers->coordIndex.setNum(0);
        m_markers->markerIndex.setNum(0);
    }
}

void FemMeshRenderer::updateColors()
{
    m_facematerialbinding->value.setValue(SoMaterialBinding::PER_FACE_INDEXED);

    auto visdata = m_vtkcurrentalgorithm ? m_vtkcurrentalgorithm->GetOutput() : nullptr;
    if (!visdata) {
        return;
    }

    const vtkIdType nFaces = visdata->GetNumberOfPolys();
    m_faces->materialIndex.setNum(static_cast<int>(nFaces));

    if (nFaces == 0) {
        return;
    }

    // Poly cells sit after verts and lines in the appended polydata cell array.
    const vtkIdType polyOffset = visdata->GetNumberOfVerts() + visdata->GetNumberOfLines();

    const int nCats = m_classification
        ? static_cast<int>(m_classification->categories().size())
        : 0;

    auto* origcell = vtkIntArray::SafeDownCast(
        visdata->GetCellData()->GetArray(FemVisibilityMask::ArrayOrigCell)
    );

    int32_t* indices = m_faces->materialIndex.startEditing();
    for (vtkIdType i = 0; i < nFaces; ++i) {
        int category = 0;
        if (m_classification && nCats > 0) {
            const vtkIdType polyCell = polyOffset + i;
            vtkIdType orig = polyCell;
            if (origcell && polyCell < origcell->GetNumberOfTuples()) {
                orig = origcell->GetValue(polyCell);
            }
            // categoryOfCell uses the classification built from input-grid
            // cells (with FaceN→SolidN resolution). origcell survives the VTK
            // threshold/clip pipeline; do not fall back to vtkOriginalCellIds.
            if (orig >= 0) {
                category = m_classification->categoryOfCell(orig);
            }
            if (category < 0) {
                category = 0;
            }
            category = category % nCats;
        }
        indices[i] = category;
    }
    m_faces->materialIndex.finishEditing();
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

vtkIdType resolveOriginalCell(vtkPolyData* visdata, vtkIdType polyCellIndex)
{
    if (!visdata || polyCellIndex < 0 || polyCellIndex >= visdata->GetNumberOfCells()) {
        return -1;
    }
    auto* origcell = vtkIntArray::SafeDownCast(
        visdata->GetCellData()->GetArray(FemVisibilityMask::ArrayOrigCell)
    );
    if (origcell && polyCellIndex < origcell->GetNumberOfTuples()) {
        return origcell->GetValue(polyCellIndex);
    }
    auto* vtkOrig = vtkIdTypeArray::SafeDownCast(
        visdata->GetCellData()->GetArray("vtkOriginalCellIds")
    );
    if (vtkOrig && polyCellIndex < vtkOrig->GetNumberOfTuples()) {
        return vtkOrig->GetValue(polyCellIndex);
    }
    return polyCellIndex;
}

}  // namespace

vtkIdType FemMeshRenderer::originalCellOfFace(int faceIndex) const
{
    auto* visdata = currentPolyData();
    if (!visdata || faceIndex < 0 || faceIndex >= visdata->GetNumberOfPolys()) {
        return -1;
    }
    const vtkIdType polyOffset = visdata->GetNumberOfVerts() + visdata->GetNumberOfLines();
    return resolveOriginalCell(visdata, polyOffset + faceIndex);
}

vtkIdType FemMeshRenderer::originalCellOfLine(int lineIndex) const
{
    auto* visdata = currentPolyData();
    if (!visdata || lineIndex < 0 || lineIndex >= visdata->GetNumberOfLines()) {
        return -1;
    }
    const vtkIdType lineOffset = visdata->GetNumberOfVerts();
    return resolveOriginalCell(visdata, lineOffset + lineIndex);
}

vtkIdType FemMeshRenderer::originalCellOfMarker(int markerIndex) const
{
    auto* visdata = currentPolyData();
    if (!visdata || markerIndex < 0 || markerIndex >= visdata->GetNumberOfVerts()) {
        return -1;
    }
    return resolveOriginalCell(visdata, markerIndex);
}

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

    faces->coordIndex.startEditing();
    int soidx = 0;
    vtkIdType npts = 0;
    const vtkIdType* indx = nullptr;
    for (cells->InitTraversal(); cells->GetNextCell(npts, indx);) {
        for (vtkIdType i = 0; i < npts; ++i) {
            faces->coordIndex.set1Value(soidx, static_cast<int>(indx[i]));
            ++soidx;
        }
        faces->coordIndex.set1Value(soidx, -1);
        ++soidx;
    }
    faces->coordIndex.setNum(soidx);
    faces->coordIndex.finishEditing();
}

void FemMeshRenderer::writeIndexedLines(SoIndexedLineSet* lines, vtkCellArray* cells)
{
    if (!lines || !cells) {
        return;
    }

    lines->coordIndex.startEditing();
    int soidx = 0;
    vtkIdType npts = 0;
    const vtkIdType* indx = nullptr;
    for (cells->InitTraversal(); cells->GetNextCell(npts, indx);) {
        for (vtkIdType i = 0; i < npts; ++i) {
            lines->coordIndex.set1Value(soidx, static_cast<int>(indx[i]));
            ++soidx;
        }
        lines->coordIndex.set1Value(soidx, -1);
        ++soidx;
    }
    lines->coordIndex.setNum(soidx);
    lines->coordIndex.finishEditing();
}

void FemMeshRenderer::writeIndexedVerts(SoIndexedMarkerSet* markers, vtkCellArray* cells)
{
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
    markers->coordIndex.startEditing();
    markers->markerIndex.startEditing();
    int soidx = 0;
    vtkIdType npts = 0;
    const vtkIdType* indx = nullptr;
    for (cells->InitTraversal(); cells->GetNextCell(npts, indx);) {
        if (npts < 1) {
            continue;
        }
        markers->coordIndex.set1Value(soidx, static_cast<int>(indx[0]));
        markers->markerIndex.set1Value(soidx, markerId);
        ++soidx;
    }
    markers->coordIndex.setNum(soidx);
    markers->markerIndex.setNum(soidx);
    markers->coordIndex.finishEditing();
    markers->markerIndex.finishEditing();
}
