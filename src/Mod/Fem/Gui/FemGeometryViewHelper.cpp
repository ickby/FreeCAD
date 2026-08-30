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
# include <algorithm>
# include <cctype>

# include <Inventor/details/SoFaceDetail.h>
# include <Inventor/details/SoLineDetail.h>
# include <Inventor/details/SoPointDetail.h>
# include <Inventor/nodes/SoCoordinate3.h>
# include <Inventor/nodes/SoDrawStyle.h>
# include <Inventor/nodes/SoIndexedFaceSet.h>
# include <Inventor/nodes/SoMaterial.h>
# include <Inventor/nodes/SoNormal.h>
# include <Inventor/nodes/SoPickStyle.h>
# include <Inventor/nodes/SoPolygonOffset.h>
# include <Inventor/nodes/SoSeparator.h>
# include <Inventor/nodes/SoShapeHints.h>
#endif

#include "FemGeometryViewHelper.h"

#include <Base/Console.h>
#include <Base/Parameter.h>
#include <Gui/Selection/SoFCUnifiedSelection.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Gui/Window.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemGeometry.h>
#include <Mod/Part/Gui/SoBrepEdgeSet.h>
#include <Mod/Part/Gui/SoBrepFaceSet.h>
#include <Mod/Part/Gui/SoBrepPointSet.h>

#include <IVtk_Types.hxx>
#include <IVtkVTK_ShapeData.hxx>
#include <Standard_Failure.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopoDS_Shape.hxx>
#include <vtkAppendPolyData.h>
#include <vtkCellData.h>
#include <vtkIdList.h>
#include <vtkIdTypeArray.h>
#include <vtkNew.h>
#include <vtkObject.h>
#include <vtkPlane.h>
#include <vtkPlaneCollection.h>
#include <vtkPointData.h>
#include <vtkPolyData.h>
#include <vtkSortDataArray.h>

#include "Classification.h"
#include "FemMeshRenderer.h"
#include "FemPerfLog.h"

using namespace FemGui;

namespace
{

constexpr const char* GeometryMode = "Geometry";
constexpr const char* GeometryHiddenMode = "GeometryHidden";

/// Surface cells, which is all the ghost overlay of a shape is made of.
const std::vector<VTKCellType> cells_2d = {
    VTK_TRIANGLE,
    VTK_TRIANGLE_STRIP,
    VTK_POLYGON,
    VTK_PIXEL,
    VTK_QUAD,
    VTK_POLYHEDRON,
    VTK_QUADRATIC_TRIANGLE,
    VTK_QUADRATIC_QUAD,
    VTK_QUADRATIC_POLYGON,
};

/// Colour the user picked for @a key, or @a fallback when there is none.
SbColor preferenceColor(const char* key, const SbColor& fallback)
{
    ParameterGrp::handle hGrp = Gui::WindowParameter::getDefaultParameter()->GetGroup("View");
    SbColor color = fallback;
    const auto packed = hGrp->GetUnsigned(key, static_cast<unsigned long>(color.getPackedValue()));
    float transparency = 0.0f;
    color.setPackedValue(static_cast<uint32_t>(packed), transparency);
    return color;
}

bool isVolumeElementName(const std::string& element)
{
    std::size_t digits = element.size();
    while (digits > 0 && std::isdigit(static_cast<unsigned char>(element[digits - 1]))) {
        --digits;
    }
    if (digits == 0 || digits == element.size()) {
        return false;
    }
    const std::string kind = element.substr(0, digits);
    return kind == "Solid" || kind == "Shell" || kind == "CompSolid" || kind == "Compound";
}

std::string stripTrailingDot(std::string path)
{
    if (!path.empty() && path.back() == '.') {
        path.pop_back();
    }
    return path;
}

bool clipApplies(const ClippingPlane& plane, const std::string& pathPrefix)
{
    if (!plane.Active) {
        return false;
    }
    if (plane.Scope.empty()) {
        return true;
    }
    const std::string scope = stripTrailingDot(pathPrefix);
    if (scope.empty()) {
        return false;
    }
    return scope == plane.Scope || scope.starts_with(plane.Scope + ".");
}

}  // namespace

FemGeometryViewHelper::FemGeometryViewHelper()
{
    m_visdata = vtkSmartPointer<vtkPolyData>::New();
    m_shape = new IVtkOCC_Shape(TopoDS_Shape());
    m_vtksource = vtkSmartPointer<IVtkTools_ShapeDataSource>::New();
    m_vtksource->SetShape(m_shape);
    m_vtkshapefilter = vtkSmartPointer<IVtkTools_SubPolyDataFilter>::New();
    m_vtkshapefilter->SetInputConnection(m_vtksource->GetOutputPort());

    m_vtkclipfilter = vtkSmartPointer<vtkTableBasedClipDataSet>::New();
    m_vtkclipgeometryfilter = vtkSmartPointer<vtkGeometryFilter>::New();
    m_vtkclipgeometryfilter->SetInputConnection(m_vtkclipfilter->GetOutputPort());
    m_vtkclipshapesource = vtkSmartPointer<IVtkTools_ShapeDataSource>::New();
    m_vtkclipcleaner = vtkSmartPointer<vtkCleanPolyData>::New();
    m_vtkclipcleaner->SetInputConnection(m_vtkclipshapesource->GetOutputPort());
    m_vtkclipsurfacefilter = vtkSmartPointer<vtkClipClosedSurface>::New();
    m_vtkclipsurfacefilter->SetInputConnection(m_vtkclipcleaner->GetOutputPort());
    m_vtkclipsurfacefilter->GenerateFacesOn();
    m_vtkclipsurfacefilter->GenerateClipFaceOutputOn();
    m_vtkclipnormals = vtkSmartPointer<vtkPolyDataNormals>::New();
    m_vtkclipnormals->SetInputConnection(m_vtkclipsurfacefilter->GetOutputPort(1));

    // Straight off the shape source, so the ghost keeps showing the whole of
    // the instance no matter how much of it is filtered or clipped away.
    m_vtkoverlayextract = vtkSmartPointer<vtkExtractCellsByType>::New();
    for (const auto& cell : cells_2d) {
        m_vtkoverlayextract->AddCellType(cell);
    }
    m_vtkoverlayextract->SetInputConnection(m_vtksource->GetOutputPort());

    m_separator = new SoSeparator();
    m_separator->ref();
    m_hidden = new SoSeparator();
    m_hidden->ref();

    m_facematerialbinding = new SoMaterialBinding();
    m_facematerialbinding->ref();
    m_facematerial = new SoMaterial();
    m_facematerial->ref();
    m_pointlinematerialbinding = new SoMaterialBinding();
    m_pointlinematerialbinding->ref();
    m_pointlinematerialbinding->value = SoMaterialBinding::OVERALL;
    m_pointlinematerial = new SoMaterial();
    m_pointlinematerial->ref();
    m_pointlinematerial->diffuseColor.setValue(0.2f, 0.2f, 0.2f);
    m_shapehints = new SoShapeHints();
    m_shapehints->ref();
    m_shapehints->vertexOrdering = SoShapeHints::COUNTERCLOCKWISE;
    m_pointlinestyle = new SoDrawStyle();
    m_pointlinestyle->ref();
    m_pointlinestyle->lineWidth.setValue(3);
    m_pointlinestyle->pointSize.setValue(6);
    m_coordinates = new SoCoordinate3();
    m_coordinates->ref();
    m_faces = new PartGui::SoBrepFaceSet();
    m_faces->ref();
    m_markers = new PartGui::SoBrepPointSet();
    m_markers->ref();
    m_lines = new PartGui::SoBrepEdgeSet();
    m_lines->ref();
    m_normalBinding = new SoNormalBinding();
    m_normalBinding->ref();
    m_normals = new SoNormal();
    m_normals->ref();

    // Coin starts an index set off with a single terminator, which bounds a
    // point at the origin. A source that has no shape never writes over it,
    // and the point would drag the bounding box of the scene to the instance.
    m_faces->coordIndex.setNum(0);
    m_faces->partIndex.setNum(0);
    m_lines->coordIndex.setNum(0);
    m_markers->numPoints = 0;

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

    // The overlay fields of SoBrepFaceSet default to a red highlight, which is
    // not the colour the user picked for one.
    m_faces->highlightColor = preferenceColor("HighlightColor", SbColor(1.0f, 0.6f, 0.0f));
    m_faces->selectionColor = preferenceColor("SelectionColor", SbColor(0.1f, 0.8f, 0.1f));
}

FemGeometryViewHelper::~FemGeometryViewHelper()
{
    disconnectViewState();
    m_separator->unref();
    m_hidden->unref();
    m_facematerialbinding->unref();
    m_facematerial->unref();
    m_pointlinematerialbinding->unref();
    m_pointlinematerial->unref();
    m_shapehints->unref();
    m_pointlinestyle->unref();
    m_coordinates->unref();
    m_faces->unref();
    m_markers->unref();
    m_lines->unref();
    m_normalBinding->unref();
    m_normals->unref();
    m_overlaymaterialbinding->unref();
    m_overlaymaterial->unref();
    m_overlaycoordinates->unref();
    m_overlaynormalBinding->unref();
    m_overlaynormals->unref();
    m_overlayfaces->unref();
}

void FemGeometryViewHelper::setHost(
    Gui::ViewProviderDocumentObject* viewProvider,
    AnalysisFinder findAnalysis,
    GeometryFinder findGeometry
)
{
    m_viewProvider = viewProvider;
    m_findAnalysis = std::move(findAnalysis);
    m_findGeometry = std::move(findGeometry);
}

void FemGeometryViewHelper::setPathPrefix(const std::string& prefix)
{
    m_pathPrefix = prefix;
}

void FemGeometryViewHelper::setSelectionPrefix(const std::string& prefix)
{
    m_selectionPrefix = prefix;
}

void FemGeometryViewHelper::setLocalFrame(const Base::Placement& placement)
{
    m_localFrame = placement;
    m_viewStateCacheValid = false;
}

void FemGeometryViewHelper::setElementHighlight(
    const std::string& role,
    const std::set<std::string>& elements,
    const Base::Color& color
)
{
    auto it = std::ranges::find_if(m_highlights, [&role](const auto& entry) {
        return entry.role == role;
    });

    if (elements.empty()) {
        if (it == m_highlights.end()) {
            return;
        }
        m_highlights.erase(it);
    }
    else if (it != m_highlights.end()) {
        if (it->elements == elements && it->color == color) {
            return;
        }
        it->elements = elements;
        it->color = color;
    }
    else {
        m_highlights.push_back({role, elements, color});
    }

    updateColors();
}

const Base::Color* FemGeometryViewHelper::highlightColorFor(
    const std::string& element,
    vtkIdType id
) const
{
    if (m_highlights.empty()) {
        return nullptr;
    }
    // Marks name elements the way a reference does, relative to the instance
    // they were picked on.
    const std::string named = m_selectionPrefix + element;
    // Backwards: of two roles naming the same element, the one set last wins.
    for (auto it = m_highlights.rbegin(); it != m_highlights.rend(); ++it) {
        if (it->elements.contains(named)) {
            return &it->color;
        }
        // A mark on a solid has to reach the faces it is built from.
        for (const auto& mark : it->elements) {
            if (mark.starts_with(m_selectionPrefix)
                && idHasElement(id, mark.substr(m_selectionPrefix.size()))) {
                return &it->color;
            }
        }
    }
    return nullptr;
}

void FemGeometryViewHelper::setManageStageVisibility(bool on)
{
    m_manageStageVisibility = on;
}

void FemGeometryViewHelper::setSuppressedComponents(const std::vector<long>& indices)
{
    m_suppressedComponents = indices;
}

void FemGeometryViewHelper::attachToSeparator(SoSeparator* root)
{
    if (m_attached || !root) {
        return;
    }
    auto* offset = new SoPolygonOffset();
    offset->factor.setValue(1.5f);
    root->addChild(m_shapehints);
    root->addChild(m_coordinates);
    root->addChild(m_pointlinematerialbinding);
    root->addChild(m_pointlinematerial);
    root->addChild(m_pointlinestyle);
    root->addChild(m_markers);
    root->addChild(m_lines);
    root->addChild(offset);
    root->addChild(m_normals);
    root->addChild(m_normalBinding);
    root->addChild(m_facematerialbinding);
    root->addChild(m_facematerial);
    root->addChild(m_faces);

    // The ghost must never take part in picking, or it would stand between the
    // user and everything it is drawn over.
    auto* ghost = new SoSeparator();
    auto* pick = new SoPickStyle();
    pick->style.setValue(SoPickStyle::Style::UNPICKABLE);
    auto* ghostOffset = new SoPolygonOffset();
    ghostOffset->factor.setValue(2);
    root->addChild(ghost);
    ghost->addChild(pick);
    ghost->addChild(ghostOffset);
    ghost->addChild(m_overlaymaterialbinding);
    ghost->addChild(m_overlaymaterial);
    ghost->addChild(m_overlaycoordinates);
    ghost->addChild(m_overlaynormalBinding);
    ghost->addChild(m_overlaynormals);
    ghost->addChild(m_overlayfaces);
    m_attached = true;
    m_attachedSeparator = root;
}

void FemGeometryViewHelper::ensureDisplayModes(SoSeparator* hiddenSeparator)
{
    m_hidden = hiddenSeparator;
    if (!m_viewProvider || m_displayModesAdded) {
        return;
    }
    m_viewProvider->addDisplayMaskMode(m_separator, GeometryMode);
    if (m_hidden) {
        m_viewProvider->addDisplayMaskMode(m_hidden, GeometryHiddenMode);
    }
    m_displayModesAdded = true;
}

AnalysisViewState* FemGeometryViewHelper::viewState() const
{
    if (!m_findAnalysis) {
        return nullptr;
    }
    auto* analysis = m_findAnalysis();
    if (!analysis) {
        return nullptr;
    }
    return AnalysisViewState::forAnalysis(analysis);
}

void FemGeometryViewHelper::disconnectViewState()
{
    m_viewStateConn.disconnect();
    m_boundViewState = nullptr;
    m_viewStateCacheValid = false;
}

void FemGeometryViewHelper::connectViewState()
{
    ensureViewStateConnection();
}

void FemGeometryViewHelper::ensureViewStateConnection()
{
    auto* state = viewState();
    if (state == m_boundViewState && m_viewStateConn.connected()) {
        return;
    }
    disconnectViewState();
    m_boundViewState = state;
    if (state) {
        m_viewStateConn = state->connectChanged([this]() { onViewStateChanged(); });
        onViewStateChanged();
    }
}

std::set<std::string> FemGeometryViewHelper::localHiddenElements(
    const std::set<std::string>& hidden
) const
{
    std::set<std::string> local;
    if (m_pathPrefix.empty()) {
        for (const auto& name : hidden) {
            if (name.find('.') == std::string::npos) {
                local.insert(name);
            }
        }
        return local;
    }
    for (const auto& name : hidden) {
        if (name.starts_with(m_pathPrefix)) {
            local.insert(name.substr(m_pathPrefix.size()));
        }
    }
    return local;
}

std::map<std::string, ClippingPlane> FemGeometryViewHelper::localClipPlanes(
    const std::map<std::string, ClippingPlane>& clips
) const
{
    std::map<std::string, ClippingPlane> local;
    const Base::Placement toLocal = m_localFrame.inverse();
    for (const auto& entry : clips) {
        if (!clipApplies(entry.second, m_pathPrefix)) {
            continue;
        }
        // The shape is triangulated in the frame of its source analysis while a
        // plane is placed in the frame of the importing one, so the plane has to
        // come back through the instance placement to cut where the user put it.
        ClippingPlane plane = entry.second;
        toLocal.multVec(entry.second.Origin, plane.Origin);
        plane.Direction = toLocal.getRotation().multVec(entry.second.Direction);
        local.emplace(entry.first, plane);
    }
    return local;
}

std::set<std::string> FemGeometryViewHelper::suppressedToplevels(Fem::FemGeometry* geom) const
{
    std::set<std::string> hidden;
    if (!geom || m_suppressedComponents.empty()) {
        return hidden;
    }
    std::set<long> suppressed(m_suppressedComponents.begin(), m_suppressedComponents.end());
    Fem::componentIdType compId = 0;
    for (auto& component : geom->getComponents()) {
        ++compId;
        if (!suppressed.count(compId)) {
            continue;
        }
        for (const auto& name : geom->getToplevelElements(component)) {
            hidden.insert(name);
        }
    }
    return hidden;
}

void FemGeometryViewHelper::updateFromShape(
    const Part::TopoShape& shape,
    Fem::FemGeometry* metadata
)
{
    m_topoShape = shape;
    m_metadata = metadata;
    m_shape = new IVtkOCC_Shape(shape.getShape());
    m_vtksource->SetShape(m_shape);
    m_vtksource->Modified();
    ensureViewStateConnection();
    updateVTK();
}

void FemGeometryViewHelper::onViewStateChanged()
{
    if (!m_attached && !m_displayModesAdded) {
        return;
    }
    FEM_PERF_SCOPE("geometry.onViewStateChanged");

    auto* state = m_boundViewState;
    if (state && m_manageStageVisibility && m_viewProvider && m_displayModesAdded) {
        const bool geometryStage = state->activeStage() == ActiveStage::Geometry;
        m_viewProvider->setDisplayMaskMode(geometryStage ? GeometryMode : GeometryHiddenMode);
    }

    if (!state) {
        m_viewStateCacheValid = false;
        updateVTK();
        return;
    }

    const DimensionMode dimMode = state->dimensionMode();
    const bool wireframe = state->wireframe();
    const ColorMode colorMode = state->colorMode();
    const auto hidden = localHiddenElements(state->hiddenElements());
    const auto clips = localClipPlanes(state->clipPlanes());
    const ActiveStage stage = state->activeStage();

    const bool colorOnly = m_viewStateCacheValid && m_cachedDimMode == dimMode
        && m_cachedWireframe == wireframe && m_cachedHidden == hidden && m_cachedClips == clips
        && m_cachedColorMode != colorMode && m_cachedStage == stage;

    m_cachedDimMode = dimMode;
    m_cachedWireframe = wireframe;
    m_cachedColorMode = colorMode;
    m_cachedStage = stage;
    m_cachedHidden = hidden;
    m_cachedClips = clips;
    m_viewStateCacheValid = true;

    if (colorOnly) {
        updateColors();
        return;
    }
    updateVTK();
}

void FemGeometryViewHelper::addIdElement(vtkIdType id, const std::string& element)
{
    auto& owners = m_id_elements[id];
    if (std::find(owners.begin(), owners.end(), element) == owners.end()) {
        owners.push_back(element);
    }
}

std::string FemGeometryViewHelper::idElementForColor(vtkIdType id) const
{
    auto it = m_id_elements.find(id);
    if (it == m_id_elements.end() || it->second.empty()) {
        return {};
    }
    return it->second.front();
}

bool FemGeometryViewHelper::idHasElement(vtkIdType id, const std::string& element) const
{
    auto it = m_id_elements.find(id);
    if (it == m_id_elements.end()) {
        return false;
    }
    return std::find(it->second.begin(), it->second.end(), element) != it->second.end();
}

bool FemGeometryViewHelper::idHasAnyElement(vtkIdType id, const std::set<std::string>& elements)
    const
{
    auto it = m_id_elements.find(id);
    if (it == m_id_elements.end()) {
        return false;
    }
    return std::ranges::any_of(it->second, [&elements](const std::string& owner) {
        return elements.count(owner) > 0;
    });
}

bool FemGeometryViewHelper::isVolumeShapeId(vtkIdType id) const
{
    if (id <= 0 || m_shape.IsNull()) {
        return false;
    }
    auto sub = m_shape->GetSubShape(id);
    if (sub.IsNull()) {
        return false;
    }
    const auto type = sub.ShapeType();
    return type == TopAbs_SOLID || type == TopAbs_SHELL || type == TopAbs_COMPSOLID
        || type == TopAbs_COMPOUND;
}

std::string FemGeometryViewHelper::localElementName(const std::string& sub) const
{
    if (sub.empty()) {
        return {};
    }
    if (!m_selectionPrefix.empty()) {
        if (!sub.starts_with(m_selectionPrefix)) {
            return {};
        }
        std::string name = sub.substr(m_selectionPrefix.size());
        return name.find('.') == std::string::npos ? name : std::string {};
    }
    // Anything with a path in it belongs to an instance further in.
    return sub.find('.') == std::string::npos ? sub : std::string {};
}

bool FemGeometryViewHelper::ownsElement(const char* subelement) const
{
    return subelement && *subelement && !localElementName(subelement).empty();
}

void FemGeometryViewHelper::setSelectionState(
    const std::set<std::string>& selected,
    const std::set<std::string>& preselected
)
{
    auto local = [this](const std::set<std::string>& subs) {
        std::set<std::string> out;
        for (const auto& sub : subs) {
            if (auto name = localElementName(sub); !name.empty()) {
                out.insert(std::move(name));
            }
        }
        return out;
    };
    m_selected = local(selected);
    m_preselected = local(preselected);
    applySelectionHighlight();
}

void FemGeometryViewHelper::applySelectionHighlight()
{
    if (!m_faces) {
        return;
    }

    auto appendPartIndices = [this](const std::set<std::string>& elements, SoMFInt32& field) {
        std::set<int> parts;
        for (std::size_t i = 0; i < m_part_shape_ids.size(); ++i) {
            const vtkIdType sid = m_part_shape_ids[i];
            // Every face of a named solid, and the cut face that stands in for
            // it once a clip plane has been through, both answer to its name.
            if (idHasAnyElement(sid, elements)) {
                parts.insert(static_cast<int>(i));
                continue;
            }
            // A face named in its own right, which the element map above only
            // knows under the toplevel that owns it.
            const auto own = elementForShapeId(sid, "Face");
            if (!own.empty() && elements.count(own) > 0) {
                parts.insert(static_cast<int>(i));
            }
        }

        int soIdx = 0;
        field.startEditing();
        for (int part : parts) {
            field.set1Value(soIdx++, part);
        }
        field.setNum(soIdx);
        field.finishEditing();
    };

    appendPartIndices(m_selected, m_faces->selectionPartIndex);

    // Hovering a face highlights exactly the part that was picked, which the
    // detail already names. A solid has no part of its own, so every face of it
    // has to be lit here instead - including the cut face, which reports the
    // solid it cuts rather than a face.
    std::set<std::string> volumePreselect;
    for (const auto& el : m_preselected) {
        if (isVolumeElementName(el)) {
            volumePreselect.insert(el);
        }
    }
    appendPartIndices(volumePreselect, m_faces->highlightPartIndex);
    m_faces->touch();
}

void FemGeometryViewHelper::resetSelectionVisuals()
{
    FEM_PERF_SCOPE("geometry.resetSelectionVisuals");

    // Coin keeps the picked part index on the node, so a rebuild that shifts the
    // parts around would leave the highlight on whatever inherited that index.
    Gui::SoSelectionElementAction selection(Gui::SoSelectionElementAction::None);
    Gui::SoHighlightElementAction highlight;
    for (SoNode* node : {static_cast<SoNode*>(m_faces),
                         static_cast<SoNode*>(m_lines),
                         static_cast<SoNode*>(m_markers)}) {
        if (node) {
            selection.apply(node);
            highlight.apply(node);
        }
    }
    applySelectionHighlight();
}

std::string FemGeometryViewHelper::elementForShapeId(vtkIdType id, const char* fallbackPrefix) const
{
    if (id <= 0 || m_shape.IsNull()) {
        return {};
    }
    auto sub = m_shape->GetSubShape(id);
    if (sub.IsNull()) {
        return {};
    }
    const int idx = m_topoShape.findShape(sub);
    if (idx <= 0) {
        return {};
    }

    // The cut faces a clip plane leaves behind are tagged with the id of the
    // solid they cut, so the type of the subshape has the last word on the name
    // and the caller only guesses for the types that have no name of their own.
    std::string prefix = fallbackPrefix ? fallbackPrefix : "";
    switch (sub.ShapeType()) {
        case TopAbs_SOLID:
        case TopAbs_SHELL:
        case TopAbs_FACE:
        case TopAbs_EDGE:
        case TopAbs_VERTEX:
            prefix = Part::TopoShape::shapeName(sub.ShapeType());
            break;
        default:
            break;
    }
    if (prefix.empty()) {
        return {};
    }
    return prefix + std::to_string(idx);
}

void FemGeometryViewHelper::updateVTK()
{
    if (m_topoShape.isNull() || !m_metadata) {
        return;
    }
    FEM_PERF_SCOPE("geometry.updateVTK");

    auto* state = m_boundViewState;
    auto hidden = state ? localHiddenElements(state->hiddenElements()) : std::set<std::string> {};
    for (const auto& name : suppressedToplevels(m_metadata)) {
        hidden.insert(name);
    }
    const auto clipper = state ? localClipPlanes(state->clipPlanes())
                               : std::map<std::string, ClippingPlane> {};
    const DimensionMode dimMode = state ? state->dimensionMode() : DimensionMode::Highest;

    IVtk_ShapeIdList passthrough_ids;
    collectVisibleIds(hidden, passthrough_ids);

    {
        FEM_PERF_SCOPE("geometry.updateVTK.subPolyDataFilter");
        m_vtkshapefilter->SetData(passthrough_ids);
        m_vtkshapefilter->Modified();
        m_vtkshapefilter->Update();
        m_visdata = m_vtkshapefilter->GetOutput();
    }

    applyClipPlanes(clipper, dimMode, passthrough_ids);

    {
        FEM_PERF_SCOPE("geometry.updateVTK.overlayExtract");
        m_vtkoverlayextract->Update();
        m_visoverlay = vtkPolyData::SafeDownCast(m_vtkoverlayextract->GetOutput());
    }

    update3D();
}

void FemGeometryViewHelper::collectVisibleIds(
    const std::set<std::string>& hidden,
    IVtk_ShapeIdList& passthrough_ids
)
{
    FEM_PERF_SCOPE("geometry.updateVTK.collectVisibleIds");

    m_id_elements.clear();

    Fem::componentIdType component_id = 0;
    for (auto& component : m_metadata->getComponents()) {
        component_id++;
        const auto component_name = std::string("Component") + std::to_string(component_id);
        if (hidden.count(component_name)) {
            continue;
        }

        for (const auto& name : m_metadata->getToplevelElements(component)) {
            if (hidden.count(name)) {
                continue;
            }

            auto sub = m_metadata->getSubShapes(name);
            if (sub.empty()) {
                continue;
            }
            auto& sub_shape = sub[0];
            auto sub_vtk_id = m_shape->GetSubShapeId(sub_shape.getShape());

            auto faces = sub_shape.getSubShapes(TopAbs_FACE);
            if (faces.empty() && sub_shape.shapeType() == TopAbs_FACE) {
                faces.push_back(sub_shape.getShape());
            }
            for (auto& face : faces) {
                auto fid = m_shape->GetSubShapeId(face);
                if (fid > 0) {
                    if (!passthrough_ids.Contains(fid)) {
                        passthrough_ids.Append(fid);
                    }
                    addIdElement(fid, name);
                }
            }

            if (sub_vtk_id > 0) {
                auto ids = m_shape->GetSubIds(sub_vtk_id);
                for (const auto& id : ids) {
                    if (!passthrough_ids.Contains(id)) {
                        passthrough_ids.Append(id);
                    }
                    addIdElement(id, name);
                }
                addIdElement(sub_vtk_id, name);
                passthrough_ids.Append(sub_vtk_id);
            }
        }
    }
}

void FemGeometryViewHelper::applyClipPlanes(
    const std::map<std::string, ClippingPlane>& clipper,
    DimensionMode dimMode,
    const IVtk_ShapeIdList& passthrough_ids
)
{
    if (clipper.empty() || !m_visdata) {
        return;
    }
    FEM_PERF_SCOPE("geometry.updateVTK.clip");

    try {
        auto clip_planes = vtkSmartPointer<vtkPlaneCollection>::New();
        for (const auto& clip : clipper) {
            const Base::Vector3d& dir = clip.second.Direction;
            if (dir.Length() < 1e-9) {
                continue;
            }
            auto plane = vtkSmartPointer<vtkPlane>::New();
            plane->SetNormal(dir.x, dir.y, dir.z);
            plane->SetOrigin(clip.second.Origin.x, clip.second.Origin.y, clip.second.Origin.z);
            clip_planes->AddItem(plane);

            m_vtkclipfilter->SetClipFunction(plane);
            m_vtkclipfilter->SetInputData(m_visdata);
            const int warn = vtkObject::GetGlobalWarningDisplay();
            vtkObject::SetGlobalWarningDisplay(0);
            {
                FEM_PERF_SCOPE("geometry.updateVTK.clip.cutBody");
                m_vtkclipgeometryfilter->Update();
            }
            vtkObject::SetGlobalWarningDisplay(warn);

            vtkPolyData* clip_out = m_vtkclipgeometryfilter->GetOutput();
            if (!clip_out) {
                return;
            }
            FEM_PERF_SCOPE("geometry.updateVTK.clip.copyBody");
            vtkNew<vtkPolyData> clipped;
            clipped->DeepCopy(clip_out);
            m_visdata = clipped;
        }

        const bool solidClipInterior =
            (dimMode == DimensionMode::Volume || dimMode == DimensionMode::Highest);
        if (clip_planes->GetNumberOfItems() == 0 || !solidClipInterior) {
            return;
        }

        auto shape = m_topoShape;
        for (TopoDS_Shape& solid : shape.getSubShapes(TopAbs_ShapeEnum::TopAbs_SOLID)) {
            vtkIdType solid_id =
                (shape.shapeType() == TopAbs_SOLID) ? 1 : m_shape->GetSubShapeId(solid);
            if (!passthrough_ids.Contains(solid_id)) {
                continue;
            }

            vtkPolyData* solid_clip_plane = nullptr;
            {
                // Every pass makes a shape source of its own, so this is where a
                // clip pays for triangulating the solid all over again.
                FEM_PERF_SCOPE("geometry.updateVTK.clip.capFaces");
                IVtkOCC_Shape::Handle vtk_shape = new IVtkOCC_Shape(solid);
                m_vtkclipshapesource->SetShape(vtk_shape);
                m_vtkclipsurfacefilter->SetClippingPlanes(clip_planes);
                m_vtkclipnormals->Update();
                solid_clip_plane = m_vtkclipnormals->GetOutput();
            }
            if (!solid_clip_plane || solid_clip_plane->GetNumberOfCells() == 0) {
                continue;
            }

            vtkNew<vtkIdTypeArray> id_data;
            vtkNew<vtkIdTypeArray> mesh_data;
            id_data->SetNumberOfValues(solid_clip_plane->GetNumberOfCells());
            mesh_data->SetNumberOfValues(solid_clip_plane->GetNumberOfCells());
            for (vtkIdType i = 0; i < solid_clip_plane->GetNumberOfCells(); i++) {
                id_data->SetValue(i, solid_id);
                mesh_data->SetValue(i, IVtk_MeshType::MT_ShadedFace);
            }
            // Named, or the append below has nothing to match them against and
            // drops the shape ids of both inputs, leaving the result with no
            // cell metadata to draw from at all.
            id_data->SetName(IVtkVTK_ShapeData::ARRNAME_SUBSHAPE_IDS());
            mesh_data->SetName(IVtkVTK_ShapeData::ARRNAME_MESH_TYPES());
            solid_clip_plane->GetCellData()->AddArray(id_data);
            solid_clip_plane->GetCellData()->AddArray(mesh_data);

            // So that hovering the cut face resolves it to the solid it cuts.
            const int sid = shape.findShape(solid);
            if (sid > 0) {
                addIdElement(
                    solid_id,
                    Part::TopoShape::shapeName(TopAbs_SOLID) + std::to_string(sid)
                );
            }

            FEM_PERF_SCOPE("geometry.updateVTK.clip.appendCap");
            vtkNew<vtkAppendPolyData> appender;
            appender->AddInputData(m_visdata);
            appender->AddInputData(solid_clip_plane);
            appender->Update();
            if (!appender->GetOutput()) {
                continue;
            }
            vtkNew<vtkPolyData> merged;
            merged->DeepCopy(appender->GetOutput());
            m_visdata = merged;
        }
    }
    catch (const Standard_Failure& e) {
        Base::Console().warning("FemGeometryViewHelper: clip failed: %s\n", e.GetMessageString());
    }
}

void FemGeometryViewHelper::updateColors()
{
    if (!m_metadata || m_part_shape_ids.empty()) {
        return;
    }
    FEM_PERF_SCOPE("geometry.colors");

    auto* state = m_boundViewState;
    const Classification* classification = nullptr;
    {
        // Builds the classification unless the state still has one, so a first
        // colouring after a stage or mode change pays for it here.
        FEM_PERF_SCOPE("geometry.colors.classify");
        classification = state ? state->classification() : nullptr;
    }
    const auto cats = classification ? classification->categories() : std::vector<Category> {};

    // SoBrepFaceSet remaps materials by partIndex, one entry per BREP face.
    // Without this the whole shape takes the first colour.
    m_facematerialbinding->value.setValue(SoMaterialBinding::PER_PART);

    // A cell type mode says nothing about geometry, and without categories
    // there is nothing to look an element up in.
    if (!cats.empty() && state->colorMode() != ColorMode::CellType) {
        colorFromClassification(*classification, cats, state->colorMode());
    }
    else {
        colorFromPalette();
    }
}

void FemGeometryViewHelper::colorFromClassification(
    const Classification& classification,
    const std::vector<Category>& cats,
    ColorMode colorMode
)
{
    FEM_PERF_SCOPE("geometry.colors.fromClassification");

    auto shape = m_metadata->Shape.getShape();

    std::set<std::string> keys;
    for (const auto& c : cats) {
        keys.insert(c.key);
    }

    m_facematerial->diffuseColor.startEditing();
    m_facematerial->diffuseColor.setNum(static_cast<int>(m_part_shape_ids.size()));
    for (size_t i = 0; i < m_part_shape_ids.size(); ++i) {
        const auto vtkid = m_part_shape_ids[i];
        std::string element;
        if (colorMode == ColorMode::Subelement) {
            FEM_PERF_SCOPE("geometry.colors.fromClassification.subelementLookup");
            auto subshape = m_shape->GetSubShape(vtkid);
            if (!subshape.IsNull()) {
                const int id = shape.findShape(subshape);
                if (id > 0) {
                    element = shape.shapeName(subshape.ShapeType()) + std::to_string(id);
                }
            }
            if (element.empty()) {
                element = idElementForColor(vtkid);
            }
        }
        else {
            element = idElementForColor(vtkid);
        }
        if (const Base::Color* marked = highlightColorFor(element, vtkid)) {
            m_facematerial->diffuseColor
                .set1Value(static_cast<int>(i), marked->r, marked->g, marked->b);
            continue;
        }
        // Categories are keyed the way the importing analysis names elements,
        // which for an instance is the path to it and not the bare element.
        std::string key = m_pathPrefix + element;
        if (!keys.contains(key)) {
            // Categories are usually per toplevel, so a face of a solid has no
            // key of its own and has to take the colour of its solid. Without
            // this every face falls through to category 0 and the whole shape
            // ends up in one colour.
            const auto owner = idElementForColor(vtkid);
            if (!owner.empty()) {
                key = m_pathPrefix + owner;
            }
        }
        int cat = classification.categoryOfElement(key);
        cat = cat < 0 ? 0 : cat % static_cast<int>(cats.size());
        const Base::Color c = cats[static_cast<size_t>(cat)].color;
        m_facematerial->diffuseColor.set1Value(static_cast<int>(i), c.r, c.g, c.b);
    }
    m_facematerial->diffuseColor.finishEditing();
}

void FemGeometryViewHelper::colorFromPalette()
{
    FEM_PERF_SCOPE("geometry.colors.fromPalette");

    // One colour per toplevel element, taken from the palette in the order the
    // classification would have used, so switching a colour mode off does not
    // change what the geometry looks like.
    std::vector<std::string> names;
    for (auto& component : m_metadata->getComponents()) {
        auto comp_names = m_metadata->getToplevelElements(component);
        names.insert(names.end(), comp_names.begin(), comp_names.end());
    }
    std::sort(names.begin(), names.end());

    std::map<std::string, Base::Color> elementColor;
    for (size_t i = 0; i < names.size(); ++i) {
        elementColor[names[i]] = Classification::colorForIndex(static_cast<int>(i));
    }

    m_facematerial->diffuseColor.startEditing();
    m_facematerial->diffuseColor.setNum(static_cast<int>(m_part_shape_ids.size()));
    for (size_t i = 0; i < m_part_shape_ids.size(); ++i) {
        const auto vtkid = m_part_shape_ids[i];
        Base::Color color = Classification::colorForIndex(0);
        const auto owner = idElementForColor(vtkid);
        if (!owner.empty()) {
            auto it = elementColor.find(owner);
            if (it != elementColor.end()) {
                color = it->second;
            }
        }
        if (const Base::Color* marked = highlightColorFor(owner, vtkid)) {
            color = *marked;
        }
        m_facematerial->diffuseColor.set1Value(static_cast<int>(i), color.r, color.g, color.b);
    }
    m_facematerial->diffuseColor.finishEditing();
}

void FemGeometryViewHelper::updateGhostOverlay()
{
    auto* state = m_boundViewState;
    // A ghost of what is drawn anyway says nothing, so it only appears once
    // something is missing from the instance. A suppressed component is
    // missing in the same way a hidden element is.
    const bool anythingMissing = !suppressedToplevels(m_metadata).empty()
        || (state
            && (state->wireframe() || !localClipPlanes(state->clipPlanes()).empty()
                || !localHiddenElements(state->hiddenElements()).empty()));
    const bool wanted = (!state || state->overlay()) && anythingMissing;
    if (!wanted || !m_visoverlay || m_visoverlay->GetNumberOfPolys() == 0) {
        m_overlayfaces->coordIndex.setNum(0);
        return;
    }
    FEM_PERF_SCOPE("geometry.toCoin.ghostOverlay");

    auto* pntData = m_visoverlay->GetPointData();
    FemMeshRenderer::writePointData(
        m_overlaycoordinates,
        m_overlaynormals,
        m_overlaynormalBinding,
        m_visoverlay->GetPoints(),
        pntData->GetNormals(),
        pntData->GetTCoords()
    );

    m_overlayfaces->coordIndex.startEditing();
    vtkIdType npts = 0;
    const vtkIdType* indx = nullptr;
    int soidx = 0;
    auto* cells = m_visoverlay->GetPolys();
    for (cells->InitTraversal(); cells->GetNextCell(npts, indx);) {
        for (vtkIdType i = 0; i < npts; i++) {
            m_overlayfaces->coordIndex.set1Value(soidx++, static_cast<int>(indx[i]));
        }
        m_overlayfaces->coordIndex.set1Value(soidx++, -1);
    }
    m_overlayfaces->coordIndex.setNum(soidx);
    m_overlayfaces->coordIndex.finishEditing();
}

void FemGeometryViewHelper::update3D()
{
    FEM_PERF_SCOPE("geometry.toCoin");

    // Before anything that gives up on the geometry: a clip plane that takes
    // the whole instance is exactly when the ghost is the only thing left to
    // say where it went.
    updateGhostOverlay();

    if (!m_visdata || m_visdata->GetNumberOfCells() == 0) {
        m_faces->coordIndex.setNum(0);
        m_faces->partIndex.setNum(0);
        m_lines->coordIndex.setNum(0);
        m_markers->numPoints = 0;
        m_faceids.clear();
        m_lineids.clear();
        m_pointids.clear();
        m_part_shape_ids.clear();
        m_face_id_to_part_index.clear();
        m_line_id_to_index.clear();
        m_point_id_to_index.clear();
        resetSelectionVisuals();
        return;
    }

    m_faceids.clear();
    m_lineids.clear();
    m_pointids.clear();
    m_part_shape_ids.clear();
    m_face_id_to_part_index.clear();
    m_line_id_to_index.clear();
    m_point_id_to_index.clear();

    {
        FEM_PERF_SCOPE("geometry.toCoin.points");
        auto* pntData = m_visdata->GetPointData();
        FemMeshRenderer::writePointData(
            m_coordinates,
            m_normals,
            m_normalBinding,
            m_visdata->GetPoints(),
            pntData->GetNormals(),
            pntData->GetTCoords()
        );
    }

    auto* cd = m_visdata->GetCellData();
    vtkIdTypeArray* shape_ids =
        vtkIdTypeArray::SafeDownCast(cd->GetArray(IVtkVTK_ShapeData::ARRNAME_SUBSHAPE_IDS()));
    vtkIdTypeArray* mesh_types =
        vtkIdTypeArray::SafeDownCast(cd->GetArray(IVtkVTK_ShapeData::ARRNAME_MESH_TYPES()));
    if (!shape_ids || !mesh_types) {
        m_faces->coordIndex.setNum(0);
        m_faces->partIndex.setNum(0);
        m_lines->coordIndex.setNum(0);
        m_markers->numPoints = 0;
        return;
    }

    const vtkIdType nCells = m_visdata->GetNumberOfCells();
    const vtkIdType nMeta = std::min(
        {nCells, shape_ids->GetNumberOfTuples(), mesh_types->GetNumberOfTuples()}
    );

    m_faces->coordIndex.startEditing();
    m_faces->partIndex.startEditing();
    m_lines->coordIndex.startEditing();

    uint line_soidx = 0;
    uint face_soidx = 0;
    int face_current_shape_id = -1;
    uint face_shape_id_cnt = 0;
    uint face_shape_id_soidx = 0;
    vtkNew<vtkIdList> points;

    vtkNew<vtkIdList> sorted_indices;
    {
        FEM_PERF_SCOPE("geometry.toCoin.sortCells");
        sorted_indices->SetNumberOfIds(nMeta);
        for (vtkIdType i = 0; i < nMeta; i++) {
            sorted_indices->SetId(i, i);
        }
        vtkNew<vtkIdTypeArray> sicc;
        sicc->SetNumberOfTuples(nMeta);
        for (vtkIdType i = 0; i < nMeta; ++i) {
            sicc->SetValue(i, shape_ids->GetValue(i));
        }
        vtkSortDataArray::Sort(sicc, sorted_indices);
    }

    auto* state = m_boundViewState;
    const DimensionMode dimMode = state ? state->dimensionMode() : DimensionMode::Highest;
    const bool wireframe = state ? state->wireframe() : false;
    const bool draw_faces = !wireframe && dimMode != DimensionMode::Curve
        && dimMode != DimensionMode::Point;

    for (vtkIdType sort_id = 0; sort_id < sorted_indices->GetNumberOfIds(); sort_id++) {
        const auto cell_id = sorted_indices->GetId(sort_id);
        const auto shape_id = shape_ids->GetValue(cell_id);
        const auto mesh_type = mesh_types->GetValue(cell_id);

        if (draw_faces
            && (mesh_type == IVtk_MeshType::MT_ShadedFace
                || mesh_type == IVtk_MeshType::MT_WireFrameFace)) {
            m_visdata->GetCellPoints(cell_id, points);
            const vtkIdType npts = points->GetNumberOfIds();
            uint created = 0;
            if (npts == 4) {
                m_faces->coordIndex.set1Value(static_cast<int>(face_soidx), points->GetId(0));
                m_faces->coordIndex.set1Value(static_cast<int>(face_soidx + 1), points->GetId(1));
                m_faces->coordIndex.set1Value(static_cast<int>(face_soidx + 2), points->GetId(3));
                m_faces->coordIndex.set1Value(static_cast<int>(face_soidx + 3), -1);
                m_faces->coordIndex.set1Value(static_cast<int>(face_soidx + 4), points->GetId(1));
                m_faces->coordIndex.set1Value(static_cast<int>(face_soidx + 5), points->GetId(2));
                m_faces->coordIndex.set1Value(static_cast<int>(face_soidx + 6), points->GetId(3));
                m_faces->coordIndex.set1Value(static_cast<int>(face_soidx + 7), -1);
                face_soidx += 8;
                created = 2;
                m_faceids.push_back(shape_id);
                m_faceids.push_back(shape_id);
            }
            else if (npts >= 3) {
                for (vtkIdType i = 1; i + 1 < npts; ++i) {
                    m_faces->coordIndex.set1Value(
                        static_cast<int>(face_soidx),
                        points->GetId(0)
                    );
                    m_faces->coordIndex.set1Value(
                        static_cast<int>(face_soidx + 1),
                        points->GetId(i)
                    );
                    m_faces->coordIndex.set1Value(
                        static_cast<int>(face_soidx + 2),
                        points->GetId(i + 1)
                    );
                    m_faces->coordIndex.set1Value(static_cast<int>(face_soidx + 3), -1);
                    face_soidx += 4;
                    m_faceids.push_back(shape_id);
                    ++created;
                }
            }
            if (created == 0) {
                continue;
            }
            if (shape_id == face_current_shape_id) {
                face_shape_id_cnt += created;
            }
            else {
                if (face_current_shape_id > 0) {
                    m_faces->partIndex.set1Value(
                        static_cast<int>(face_shape_id_soidx),
                        static_cast<int>(face_shape_id_cnt)
                    );
                    face_shape_id_soidx += 1;
                }
                face_current_shape_id = static_cast<int>(shape_id);
                face_shape_id_cnt = created;
                m_face_id_to_part_index[shape_id] = static_cast<int>(face_shape_id_soidx);
                m_part_shape_ids.push_back(shape_id);
            }
        }
        else if (
            mesh_type == IVtk_MeshType::MT_FreeEdge || mesh_type == IVtk_MeshType::MT_BoundaryEdge
            || mesh_type == IVtk_MeshType::MT_SharedEdge || mesh_type == IVtk_MeshType::MT_SeamEdge
        ) {
            m_visdata->GetCellPoints(cell_id, points);
            for (vtkIdType i = 0; i < points->GetNumberOfIds(); i++) {
                m_lines->coordIndex.set1Value(static_cast<int>(line_soidx), points->GetId(i));
                line_soidx++;
            }
            m_lines->coordIndex.set1Value(static_cast<int>(line_soidx), -1);
            line_soidx++;
            m_line_id_to_index.emplace(shape_id, static_cast<int>(m_lineids.size()));
            m_lineids.push_back(shape_id);
        }
        else if (mesh_type == IVtk_MeshType::MT_FreeVertex) {
            m_point_id_to_index.emplace(shape_id, static_cast<int>(m_pointids.size()));
            m_pointids.push_back(shape_id);
        }
    }

    // Truncate: the fields keep whatever was written last time, and an update
    // that draws less than the one before it would leave stale indices behind,
    // which come out as triangles between unrelated points.
    m_faces->coordIndex.setNum(static_cast<int>(face_soidx));
    m_lines->coordIndex.setNum(static_cast<int>(line_soidx));

    if (face_current_shape_id > 0) {
        m_faces->partIndex.set1Value(
            static_cast<int>(face_shape_id_soidx),
            static_cast<int>(face_shape_id_cnt)
        );
        m_faces->partIndex.setNum(static_cast<int>(++face_shape_id_soidx));
    }
    else {
        m_faces->partIndex.setNum(0);
    }

    m_faces->coordIndex.finishEditing();
    m_faces->partIndex.finishEditing();
    m_lines->coordIndex.finishEditing();
    m_markers->numPoints = static_cast<int>(m_pointids.size());

    updateColors();
    resetSelectionVisuals();
}

std::string FemGeometryViewHelper::elementFromDetail(const SoDetail* detail) const
{
    if (!detail) {
        return {};
    }
    vtkIdType vtk_id = -1;
    const char* prefix = nullptr;

    if (detail->getTypeId() == SoFaceDetail::getClassTypeId()) {
        const auto* face_detail = static_cast<const SoFaceDetail*>(detail);
        const int face = face_detail->getFaceIndex();
        const int part = face_detail->getPartIndex();
        if (face >= 0 && static_cast<size_t>(face) < m_faceids.size()) {
            vtk_id = m_faceids[face];
        }
        else if (part >= 0 && static_cast<size_t>(part) < m_part_shape_ids.size()) {
            vtk_id = m_part_shape_ids[part];
        }
        prefix = "Face";
    }
    else if (detail->getTypeId() == SoLineDetail::getClassTypeId()) {
        const auto* line_detail = static_cast<const SoLineDetail*>(detail);
        const int edge = line_detail->getLineIndex();
        if (edge < 0 || static_cast<size_t>(edge) >= m_lineids.size()) {
            return {};
        }
        vtk_id = m_lineids[edge];
        prefix = "Edge";
    }
    else if (detail->getTypeId() == SoPointDetail::getClassTypeId()) {
        const auto* point_detail = static_cast<const SoPointDetail*>(detail);
        const int vertex = point_detail->getCoordinateIndex();
        if (vertex < 0 || static_cast<size_t>(vertex) >= m_pointids.size()) {
            return {};
        }
        vtk_id = m_pointids[vertex];
        prefix = "Vertex";
    }
    else {
        return {};
    }

    if (vtk_id <= 0 || !prefix) {
        return {};
    }
    std::string element = elementForShapeId(vtk_id, prefix);
    if (element.empty()) {
        return {};
    }
    if (!m_selectionPrefix.empty()) {
        return m_selectionPrefix + element;
    }
    return element;
}

SoDetail* FemGeometryViewHelper::detailFromElement(const char* subelement) const
{
    if (!subelement || !*subelement) {
        return nullptr;
    }
    std::string name(subelement);
    if (!m_selectionPrefix.empty()) {
        if (name.starts_with(m_selectionPrefix)) {
            name = name.substr(m_selectionPrefix.size());
        }
        else {
            return nullptr;
        }
    }
    else if (name.find('.') != std::string::npos) {
        // Addresses something further in; not an element of this instance.
        return nullptr;
    }

    auto type = Part::TopoShape::getElementTypeAndIndex(name.c_str());
    const std::string& element = type.first;

    if (element == "Edge") {
        for (const auto& entry : m_line_id_to_index) {
            if (elementForShapeId(entry.first, "Edge") == name) {
                auto* detail = new SoLineDetail();
                detail->setLineIndex(entry.second);
                return detail;
            }
        }
    }
    if (element == "Vertex") {
        for (const auto& entry : m_point_id_to_index) {
            if (elementForShapeId(entry.first, "Vertex") == name) {
                auto* detail = new SoPointDetail();
                detail->setCoordinateIndex(entry.second);
                return detail;
            }
        }
    }
    // A toplevel solid or shell: the cut face a clip plane left behind is the
    // part that stands for it, and it carries the id of the solid. Any face of
    // the solid still beats no detail at all, which would light the whole
    // instance instead.
    if (element.empty() && isVolumeElementName(name)) {
        int fallback = -1;
        for (std::size_t i = 0; i < m_part_shape_ids.size(); ++i) {
            const vtkIdType sid = m_part_shape_ids[i];
            if (!idHasElement(sid, name)) {
                continue;
            }
            if (isVolumeShapeId(sid)) {
                auto* detail = new SoFaceDetail();
                detail->setPartIndex(static_cast<int>(i));
                return detail;
            }
            if (fallback < 0) {
                fallback = static_cast<int>(i);
            }
        }
        if (fallback >= 0) {
            auto* detail = new SoFaceDetail();
            detail->setPartIndex(fallback);
            return detail;
        }
        return nullptr;
    }

    if (element == "Face" || element.empty()) {
        for (const auto& entry : m_face_id_to_part_index) {
            if (elementForShapeId(entry.first, "Face") == name || idHasElement(entry.first, name)) {
                auto* detail = new SoFaceDetail();
                detail->setPartIndex(entry.second);
                return detail;
            }
        }
    }
    return nullptr;
}
