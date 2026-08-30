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
# include <vector>

# include <QIcon>
# include <QPixmap>

# include <Inventor/details/SoFaceDetail.h>
# include <Inventor/details/SoLineDetail.h>
# include <Inventor/details/SoPointDetail.h>
# include <Inventor/nodes/SoCoordinate3.h>
# include <Inventor/nodes/SoDepthBuffer.h>
# include <Inventor/nodes/SoDrawStyle.h>
# include <Inventor/nodes/SoIndexedFaceSet.h>
# include <Inventor/nodes/SoIndexedLineSet.h>
# include <Inventor/nodes/SoIndexedPointSet.h>
# include <Inventor/nodes/SoLightModel.h>
# include <Inventor/nodes/SoMaterial.h>
# include <Inventor/nodes/SoNormal.h>
# include <Inventor/nodes/SoPickStyle.h>
# include <Inventor/nodes/SoPolygonOffset.h>
# include <Inventor/nodes/SoSeparator.h>
# include <Inventor/nodes/SoShapeHints.h>
#endif

#include <Base/Console.h>
#include <App/Document.h>
#include <App/GroupExtension.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Selection/SoFCUnifiedSelection.h>
#include <Gui/Utilities.h>
#include <Gui/Window.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemGeometry.h>
#include <Mod/Part/Gui/SoBrepEdgeSet.h>
#include <Mod/Part/Gui/SoBrepFaceSet.h>
#include <Mod/Part/Gui/SoBrepPointSet.h>
#include <Mod/Part/Gui/ViewProviderExt.h>
#include <Mod/Part/Gui/ViewProviderPreviewExtension.h>

#include <IVtk_Types.hxx>
#include <IVtkVTK_ShapeData.hxx>
#include <Standard_Failure.hxx>
#include <vtkAppendPolyData.h>
#include <vtkCellData.h>
#include <vtkFloatArray.h>
#include <vtkIdTypeArray.h>
#include <vtkPlane.h>
#include <vtkPlaneCollection.h>
#include <vtkPointData.h>
#include <vtkPolyData.h>
#include <vtkSortDataArray.h>

#include "ActiveAnalysisObserver.h"
#include "AnalysisViewState.h"
#include "Classification.h"
#include "FemMeshRenderer.h"
#include "ViewProviderFemGeometry.h"
#include "ViewProviderFemGeometryPy.h"

using namespace FemGui;

PROPERTY_SOURCE(FemGui::ViewProviderFemGeometry, Gui::ViewProviderDocumentObject)

namespace
{

std::vector<VTKCellType> cells_2d = {
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

/**
 * True for FemGeometry toplevel names that address a volume (Solid1, Shell2, …).
 * TopoShape::getElementTypeAndIndex only matches Face/Edge/Vertex and returns an
 * empty kind for these, so the name has to be split here.
 */
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

/**
 * Document-wide selection observer (Path-style).
 * Avoid SelectionObserver MI on the FeaturePython view provider.
 */
class FemGeometrySelectionObserver: public Gui::SelectionObserver
{
public:
    static void init()
    {
        static FemGeometrySelectionObserver* instance = nullptr;
        if (!instance) {
            instance = new FemGeometrySelectionObserver();
        }
    }

    FemGeometrySelectionObserver()
        : SelectionObserver(true, Gui::ResolveMode::NoResolve)
    {}

    void onSelectionChanged(const Gui::SelectionChanges& msg) override
    {
        if (msg.Type != Gui::SelectionChanges::AddSelection
            && msg.Type != Gui::SelectionChanges::RmvSelection
            && msg.Type != Gui::SelectionChanges::ClrSelection
            && msg.Type != Gui::SelectionChanges::SetSelection
            && msg.Type != Gui::SelectionChanges::SetPreselect
            && msg.Type != Gui::SelectionChanges::RmvPreselect) {
            return;
        }

        auto syncDoc = [](App::Document* doc) {
            if (!doc) {
                return;
            }
            for (auto* obj : doc->getObjectsOfType(Fem::FemGeometry::getClassTypeId())) {
                auto* vp = Base::freecad_cast<ViewProviderFemGeometry*>(
                    Gui::Application::Instance->getViewProvider(obj)
                );
                if (vp) {
                    vp->syncSelectionHighlight();
                }
            }
        };

        if (msg.Type == Gui::SelectionChanges::ClrSelection) {
            if (msg.pDocName && msg.pDocName[0]) {
                syncDoc(App::GetApplication().getDocument(msg.pDocName));
            }
            else {
                for (auto* doc : App::GetApplication().getDocuments()) {
                    syncDoc(doc);
                }
            }
            return;
        }

        if (msg.pDocName && msg.pDocName[0]) {
            syncDoc(App::GetApplication().getDocument(msg.pDocName));
        }
    }
};

}  // namespace

ViewProviderFemGeometry::ViewProviderFemGeometry()
{
    FemGeometrySelectionObserver::init();

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

    m_vtkgeometryoverlayextract = vtkSmartPointer<vtkExtractCellsByType>::New();
    for (auto& cell : cells_2d) {
        m_vtkgeometryoverlayextract->AddCellType(cell);
    }
    m_vtkgeometryoverlayextract->SetInputConnection(m_vtksource->GetOutputPort());

    sPixmap = "Part_3D_object";

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
    m_shapehints->shapeType = SoShapeHints::UNKNOWN_SHAPE_TYPE;
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

    m_geometryoverlaymaterialbinding = new SoMaterialBinding();
    m_geometryoverlaymaterialbinding->ref();
    m_geometryoverlaymaterial = new SoMaterial();
    m_geometryoverlaymaterial->ref();
    m_geometryoverlaymaterial->transparency.setValue(0.9f);
    m_geometryoverlaymaterialbinding->value = SoMaterialBinding::OVERALL;
    m_geometryoverlaycoordinates = new SoCoordinate3();
    m_geometryoverlaycoordinates->ref();
    m_geometryoverlay = new SoIndexedFaceSet();
    m_geometryoverlay->ref();
    m_geometryoverlaynormalBinding = new SoNormalBinding();
    m_geometryoverlaynormalBinding->ref();
    m_geometryoverlaynormals = new SoNormal();
    m_geometryoverlaynormals->ref();

    m_highlightoverlay = new SoSeparator();
    m_highlightoverlay->ref();
    m_highlightoverlaydepth = new SoDepthBuffer();
    m_highlightoverlaydepth->ref();
    // The marks sit exactly on the edges they mark, so the depth test has to let
    // an equal value through or the two would fight over the same pixels. Depth
    // stays unwritten and the test is not switched off: a mark is a lasting
    // thing and must not shine through the solid it is on the far side of.
    m_highlightoverlaydepth->function.setValue(SoDepthBuffer::LEQUAL);
    m_highlightoverlaydepth->write.setValue(FALSE);
    m_highlightoverlaylinebinding = new SoMaterialBinding();
    m_highlightoverlaylinebinding->ref();
    m_highlightoverlaylinebinding->value = SoMaterialBinding::PER_FACE;
    m_highlightoverlaylinematerial = new SoMaterial();
    m_highlightoverlaylinematerial->ref();
    m_highlightoverlaypointbinding = new SoMaterialBinding();
    m_highlightoverlaypointbinding->ref();
    m_highlightoverlaypointbinding->value = SoMaterialBinding::PER_VERTEX;
    m_highlightoverlaypointmaterial = new SoMaterial();
    m_highlightoverlaypointmaterial->ref();
    m_highlightoverlaystyle = new SoDrawStyle();
    m_highlightoverlaystyle->ref();
    // Wider and larger than the plain ones, so a mark reads as a mark even where
    // it lies on top of the edge it marks.
    m_highlightoverlaystyle->lineWidth.setValue(4.0f);
    m_highlightoverlaystyle->pointSize.setValue(9.0f);
    m_highlightoverlaylines = new SoIndexedLineSet();
    m_highlightoverlaylines->ref();
    m_highlightoverlaypoints = new SoIndexedPointSet();
    m_highlightoverlaypoints->ref();

    // Unpickable translucent cutting tool; empty until setToolPreview fills it.
    m_toolPreview = new PartGui::SoPreviewShape();
    m_toolPreview->ref();
    const Base::Color toolColor = defaultToolPreviewColor();
    m_toolPreview->color.setValue(toolColor.r, toolColor.g, toolColor.b);
    m_toolPreview->transparency.setValue(0.55f);

    float transparency = 0.0f;
    ParameterGrp::handle hGrp = Gui::WindowParameter::getDefaultParameter()->GetGroup("View");
    SbColor highlightColor(1.0f, 0.6f, 0.0f);
    auto highlight = static_cast<unsigned long>(highlightColor.getPackedValue());
    highlight = hGrp->GetUnsigned("HighlightColor", highlight);
    highlightColor.setPackedValue(static_cast<uint32_t>(highlight), transparency);
    m_colorhighlight.setValue(highlightColor);

    SbColor selectionColor(0.1f, 0.8f, 0.1f);
    auto selection = static_cast<unsigned long>(selectionColor.getPackedValue());
    selection = hGrp->GetUnsigned("SelectionColor", selection);
    selectionColor.setPackedValue(static_cast<uint32_t>(selection), transparency);
    m_colorselection.setValue(selectionColor);

    m_faces->selectionColor = m_colorselection;
    m_faces->highlightColor = m_colorhighlight;
}

ViewProviderFemGeometry::~ViewProviderFemGeometry()
{
    m_viewStateConn.disconnect();

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
    m_geometryoverlaymaterialbinding->unref();
    m_geometryoverlaymaterial->unref();
    m_geometryoverlaycoordinates->unref();
    m_geometryoverlay->unref();
    m_geometryoverlaynormalBinding->unref();
    m_geometryoverlaynormals->unref();
    m_highlightoverlay->unref();
    m_highlightoverlaydepth->unref();
    m_highlightoverlaylinebinding->unref();
    m_highlightoverlaylinematerial->unref();
    m_highlightoverlaypointbinding->unref();
    m_highlightoverlaypointmaterial->unref();
    m_highlightoverlaystyle->unref();
    m_highlightoverlaylines->unref();
    m_highlightoverlaypoints->unref();
    m_toolPreview->unref();
}

AnalysisViewState* ViewProviderFemGeometry::viewState() const
{
    auto* obj = getObject();
    if (obj) {
        // Prefer the analysis that owns this geometry in the tree. Relying only
        // on ActiveAnalysisObserver can miss connections when the VP attaches
        // before the analysis is marked active.
        for (auto* parent : obj->getInList()) {
            if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(parent)) {
                return AnalysisViewState::forAnalysis(analysis);
            }
            for (auto* grand : parent->getInList()) {
                if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(grand)) {
                    return AnalysisViewState::forAnalysis(analysis);
                }
            }
        }
    }
    auto* analysis = ActiveAnalysisObserver::instance()->getActiveObject();
    if (!analysis) {
        return nullptr;
    }
    return AnalysisViewState::forAnalysis(analysis);
}

void ViewProviderFemGeometry::ensureViewStateConnection()
{
    auto* state = viewState();
    if (state == m_boundViewState) {
        return;
    }
    m_viewStateConn.disconnect();
    m_boundViewState = state;
    if (state) {
        m_viewStateConn = state->connectChanged([this]() {
            onViewStateChanged();
        });
        // Apply the current stage immediately; otherwise we miss the state that
        // was active before this VP connected (e.g. Mesh stage after Gmsh create).
        onViewStateChanged();
    }
}

Fem::FemGeometry* ViewProviderFemGeometry::chainOwner() const
{
    auto* obj = getObject();
    if (!obj) {
        return nullptr;
    }
    for (auto* parent : obj->getInList()) {
        auto* group = Base::freecad_cast<Fem::FemGeometry*>(parent);
        if (!group) {
            continue;
        }
        auto* ext = group->getExtensionByType<App::GroupExtension>(true);
        if (ext && ext->hasObject(obj)) {
            return group;
        }
    }
    return nullptr;
}

void ViewProviderFemGeometry::applyChainRole()
{
    const bool step = isChainStep();
    if (step == m_isChainStep) {
        return;
    }
    m_isChainStep = step;

    // A build step is not a thing you can look at on its own: the group holds
    // the result and renders it. Take the visibility control away instead of
    // leaving a switch that does nothing, the same way objects without a
    // representation do it.
    setToggleVisibility(
        step ? ToggleVisibilityMode::NoToggleVisibility : ToggleVisibilityMode::CanToggleVisibility
    );
    if (step) {
        setDisplayMaskMode("Hidden");
    }
    else {
        // Shape changes were ignored while this was a step, so the vtk source
        // has to be caught up before it can be rendered again.
        if (auto* geom_obj = getObject<Fem::FemGeometry>()) {
            m_shape = new IVtkOCC_Shape(geom_obj->Shape.getShape().getShape());
            m_vtksource->SetShape(m_shape);
        }
        m_viewStateCacheValid = false;
        setDisplayMaskMode("Default");
        // Rebuilds the render and lets the active stage have the final say on
        // the mask. applyChainRole is a no-op from there, the role is set.
        onViewStateChanged();
    }
}

void ViewProviderFemGeometry::refreshChainSteps()
{
    auto* obj = getObject();
    if (!obj) {
        return;
    }
    auto* ext = obj->getExtensionByType<App::GroupExtension>(true);
    if (!ext) {
        return;
    }
    auto* doc = Gui::Application::Instance->getDocument(obj->getDocument());
    if (!doc) {
        return;
    }

    // The result of the chain is its last step, that is the one the group takes
    // its shape from.
    Fem::FemGeometry* result = nullptr;
    for (auto* child : ext->Group.getValues()) {
        if (auto* geometry = Base::freecad_cast<Fem::FemGeometry*>(child)) {
            result = geometry;
        }
    }

    // Objects that just left the chain have to get their own visual back, so
    // former members are refreshed along with the current ones.
    std::set<std::string> members = m_chainMembers;
    m_chainMembers.clear();
    for (auto* child : ext->Group.getValues()) {
        if (child && child->isAttachedToDocument()) {
            m_chainMembers.insert(child->getNameInDocument());
            members.insert(child->getNameInDocument());
        }
    }

    for (const auto& name : members) {
        auto* member = obj->getDocument()->getObject(name.c_str());
        if (!member) {
            continue;
        }
        auto* vp = Base::freecad_cast<ViewProviderFemGeometry*>(doc->getViewProvider(member));
        if (!vp) {
            continue;
        }
        vp->applyChainRole();
        vp->setChainResult(member == result);
    }
}

void ViewProviderFemGeometry::setChainResult(bool result)
{
    if (result == m_isChainResult) {
        return;
    }
    m_isChainResult = result;
    signalChangeIcon();
}

ViewProviderFemGeometry* ViewProviderFemGeometry::groupViewProvider(Fem::FemGeometry* group) const
{
    if (!group) {
        return nullptr;
    }
    auto* doc = Gui::Application::Instance->getDocument(group->getDocument());
    if (!doc) {
        return nullptr;
    }
    return Base::freecad_cast<ViewProviderFemGeometry*>(doc->getViewProvider(group));
}

const char* ViewProviderFemGeometry::suppressedMaskMode() const
{
    // A switch traverses one child only, and the children of a GeoFeatureGroup
    // hang under the extension-owned "Group" mask. Hiding the group outright
    // would therefore cut off the previewed step along with the group's own
    // result, leaving nothing to look at or pick. Stepping aside onto the
    // children mask drops the result and keeps the step reachable instead.
    return getDisplayMaskMode("Group") ? "Group" : "Hidden";
}

void ViewProviderFemGeometry::setChainRenderSuppressed(bool on)
{
    if (on == m_suppressChainRender) {
        return;
    }
    m_suppressChainRender = on;
    onViewStateChanged();
}

void ViewProviderFemGeometry::setChainPreview(bool on)
{
    if (on == m_chainPreview) {
        return;
    }
    m_chainPreview = on;

    if (on) {
        if (auto* geom_obj = getObject<Fem::FemGeometry>()) {
            m_shape = new IVtkOCC_Shape(geom_obj->Shape.getShape().getShape());
            m_vtksource->SetShape(m_shape);
        }
        m_viewStateCacheValid = false;

        if (auto* group = chainOwner()) {
            if (auto* gvp = groupViewProvider(group)) {
                gvp->setChainRenderSuppressed(true);
                // By name, because the group can be removed while the panel is
                // open and a cached pointer would dangle on the way out.
                m_previewSuppressedGroup = group->getNameInDocument();
            }
        }
    }
    else if (!m_previewSuppressedGroup.empty()) {
        auto* obj = getObject();
        if (obj && obj->getDocument()) {
            auto* group = Base::freecad_cast<Fem::FemGeometry*>(
                obj->getDocument()->getObject(m_previewSuppressedGroup.c_str())
            );
            if (auto* gvp = group ? groupViewProvider(group) : nullptr) {
                gvp->setChainRenderSuppressed(false);
            }
        }
        m_previewSuppressedGroup.clear();
    }

    onViewStateChanged();
}

QIcon ViewProviderFemGeometry::mergeColorfulOverlayIcons(const QIcon& orig) const
{
    QIcon icon = orig;
    if (m_isChainResult) {
        static QPixmap badge(
            Gui::BitmapFactory().pixmapFromSvg("FEM_Overlay_Result", QSize(10, 10))
        );
        icon = Gui::BitmapFactoryInst::mergePixmap(
            icon,
            badge,
            Gui::BitmapFactoryInst::BottomRight
        );
    }
    return Gui::ViewProviderDocumentObject::mergeColorfulOverlayIcons(icon);
}

void ViewProviderFemGeometry::onViewStateChanged()
{
    applyChainRole();
    if (m_isChainStep && !m_chainPreview) {
        // Nothing to show and nothing to filter: the group renders the result.
        setDisplayMaskMode("Hidden");
        return;
    }
    if (m_suppressChainRender) {
        setDisplayMaskMode(suppressedMaskMode());
        return;
    }

    auto* state = m_boundViewState;
    if (!state) {
        // No stage to consult, but the mask still has to be opened. Without
        // this a previewed step keeps the Hidden mask applyChainRole left
        // behind, and a group coming out of suppression never gets its render
        // back, leaving an empty viewport either way.
        setDisplayMaskMode("Default");
        m_viewStateCacheValid = false;
        updateVTK();
        return;
    }

    const DimensionMode dimMode = state->dimensionMode();
    const bool wireframe = state->wireframe();
    const ColorMode colorMode = state->colorMode();
    const auto& hidden = state->hiddenElements();
    const auto& clips = state->clipPlanes();
    const ActiveStage stage = state->activeStage();

    // Exclusive geometry/mesh visibility is ActiveStage, not hand-rolled VP flags.
    // Always the own VTK render: the group draws the result of its chain, the
    // steps below it draw nothing, so the extension-owned Group mask would leave
    // an empty view. A previewed step overrides the stage, because picking
    // geometry for a chain step is a geometry operation by definition.
    setDisplayMaskMode(
        (m_chainPreview || stage == ActiveStage::Geometry) ? "Default" : "Hidden"
    );

    const bool colorOnly = m_viewStateCacheValid && m_cachedDimMode == dimMode
        && m_cachedWireframe == wireframe && m_cachedHidden == hidden
        && m_cachedClips == clips && m_cachedColorMode != colorMode
        && m_cachedStage == stage;

    m_cachedDimMode = dimMode;
    m_cachedWireframe = wireframe;
    m_cachedColorMode = colorMode;
    m_cachedStage = stage;
    m_cachedHidden = hidden;
    m_cachedClips = clips;
    m_viewStateCacheValid = true;

    if (colorOnly) {
        // Colour-mode switch must not re-run the VTK pipeline (Stage 7).
        updateColors();
        return;
    }
    updateVTK();
}

void ViewProviderFemGeometry::attach(App::DocumentObject* pcObj)
{
    ViewProviderDocumentObject::attach(pcObj);

    SoPolygonOffset* offset = new SoPolygonOffset();
    offset->factor.setValue(1.5f);
    m_separator->addChild(m_shapehints);
    m_separator->addChild(m_coordinates);
    m_separator->addChild(m_pointlinematerialbinding);
    m_separator->addChild(m_pointlinematerial);
    m_separator->addChild(m_pointlinestyle);
    m_separator->addChild(m_markers);
    m_separator->addChild(m_lines);
    m_separator->addChild(offset);
    m_separator->addChild(m_normals);
    m_separator->addChild(m_normalBinding);
    m_separator->addChild(m_facematerialbinding);
    m_separator->addChild(m_facematerial);
    m_separator->addChild(m_faces);

    auto sep = new SoSeparator();
    auto pick = new SoPickStyle();
    offset = new SoPolygonOffset();
    offset->factor.setValue(2);
    pick->style.setValue(SoPickStyle::Style::UNPICKABLE);
    m_separator->addChild(sep);
    sep->addChild(pick);
    sep->addChild(offset);
    sep->addChild(m_geometryoverlaymaterialbinding);
    sep->addChild(m_geometryoverlaymaterial);
    sep->addChild(m_geometryoverlaycoordinates);
    sep->addChild(m_geometryoverlaynormalBinding);
    sep->addChild(m_geometryoverlaynormals);
    sep->addChild(m_geometryoverlay);

    // Marked edges and vertices, drawn last so they land over the plain ones.
    // The coordinates are the same node the normal render uses, so a mark costs
    // an index list and nothing else. Unpickable, because a mark must not stand
    // between the user and the element underneath it.
    auto* highlight_pick = new SoPickStyle();
    highlight_pick->style.setValue(SoPickStyle::Style::UNPICKABLE);
    m_highlightoverlay->addChild(highlight_pick);
    // Unlit, so the mark comes out in the colour that was asked for. The normals
    // in scope belong to the faces and would shade it into something else.
    auto* highlight_light = new SoLightModel();
    highlight_light->model.setValue(SoLightModel::BASE_COLOR);
    m_highlightoverlay->addChild(highlight_light);
    m_highlightoverlay->addChild(m_highlightoverlaydepth);
    m_highlightoverlay->addChild(m_highlightoverlaystyle);
    m_highlightoverlay->addChild(m_coordinates);
    m_highlightoverlay->addChild(m_highlightoverlaylinebinding);
    m_highlightoverlay->addChild(m_highlightoverlaylinematerial);
    m_highlightoverlay->addChild(m_highlightoverlaylines);
    m_highlightoverlay->addChild(m_highlightoverlaypointbinding);
    m_highlightoverlay->addChild(m_highlightoverlaypointmaterial);
    m_highlightoverlay->addChild(m_highlightoverlaypoints);
    m_separator->addChild(m_highlightoverlay);
    m_separator->addChild(m_toolPreview);

    addDisplayMaskMode(m_separator, "Default");
    addDisplayMaskMode(m_hidden, "Hidden");
    // Do not register "Group" here: ViewProviderGeoFeatureGroupExtension owns
    // that mask (pcGroupChildren). A group normally renders the result of its
    // chain itself, and only steps aside onto that mask while a step below it
    // is previewed, see suppressedMaskMode.
    setDisplayMaskMode("Default");

    applyChainRole();
    ensureViewStateConnection();
}

void ViewProviderFemGeometry::setDisplayMode(const char* ModeName)
{
    if (m_isChainStep && !m_chainPreview) {
        setDisplayMaskMode("Hidden");
        return;
    }
    if (m_suppressChainRender) {
        setDisplayMaskMode(suppressedMaskMode());
        return;
    }
    if (ModeName) {
        setDisplayMaskMode(strcmp(ModeName, "Hidden") == 0 ? "Hidden" : "Default");
    }
    update3D();
}

std::vector<std::string> ViewProviderFemGeometry::getDisplayModes() const
{
    if (m_isChainStep && !m_chainPreview) {
        return {};
    }
    return {"Surface", "Wireframe"};
}

void ViewProviderFemGeometry::setElementHighlight(
    const std::string& role,
    const std::set<std::string>& elements,
    const Base::Color& color
)
{
    auto it = std::find_if(
        m_elementHighlights.begin(),
        m_elementHighlights.end(),
        [&role](const auto& entry) { return entry.role == role; }
    );

    if (elements.empty()) {
        if (it == m_elementHighlights.end()) {
            return;
        }
        m_elementHighlights.erase(it);
    }
    else if (it != m_elementHighlights.end()) {
        if (it->elements == elements && it->color == color) {
            return;
        }
        it->elements = elements;
        it->color = color;
    }
    else {
        m_elementHighlights.push_back({role, elements, color});
    }

    updateColors();
    updateElementHighlight();
}

void ViewProviderFemGeometry::clearElementHighlight(const std::string& role)
{
    setElementHighlight(role, {}, Base::Color());
}

std::set<std::string> ViewProviderFemGeometry::elementHighlight(const std::string& role) const
{
    for (const auto& entry : m_elementHighlights) {
        if (entry.role == role) {
            return entry.elements;
        }
    }
    return {};
}

Base::Color ViewProviderFemGeometry::defaultElementHighlightColor()
{
    // Apart from the green of a selection and the orange of a hover, so a mark
    // is never mistaken for either.
    return Base::Color(0.85f, 0.15f, 0.85f);
}

Base::Color ViewProviderFemGeometry::defaultToolPreviewColor()
{
    // Matches the partition panel's MARK_TOOL colour.
    return Base::Color(0.15f, 0.4f, 1.0f);
}

void ViewProviderFemGeometry::setToolPreview(
    const Part::TopoShape& shape,
    const Base::Color& color,
    float transparency
)
{
    if (!m_toolPreview) {
        return;
    }
    m_toolPreview->color.setValue(color.r, color.g, color.b);
    m_toolPreview->transparency.setValue(std::clamp(transparency, 0.0f, 1.0f));
    try {
        PartGui::ViewProviderPartExt::setupCoinGeometry(
            shape.getShape(),
            m_toolPreview,
            0.2,
            0.35
        );
        m_toolPreview->transform.setValue(Base::convertTo<SbMatrix>(shape.getTransform()));
    }
    catch (const Standard_Failure&) {
        clearToolPreview();
    }
}

void ViewProviderFemGeometry::clearToolPreview()
{
    if (!m_toolPreview) {
        return;
    }
    PartGui::ViewProviderPartExt::setupCoinGeometry(TopoDS_Shape(), m_toolPreview, 0.2, 0.35);
    m_toolPreview->transform.setValue(SbMatrix::identity());
}

const Base::Color* ViewProviderFemGeometry::elementHighlightColor(const std::string& element) const
{
    if (element.empty()) {
        return nullptr;
    }
    // Backwards: of two roles naming the same element, the one set last wins.
    for (auto it = m_elementHighlights.rbegin(); it != m_elementHighlights.rend(); ++it) {
        if (it->elements.count(element) > 0) {
            return &it->color;
        }
    }
    return nullptr;
}

const Base::Color* ViewProviderFemGeometry::idHighlightColor(vtkIdType id) const
{
    if (m_elementHighlights.empty()) {
        return nullptr;
    }
    // A mark on a toplevel covers the faces below it, and m_id_elements is what
    // ties a rendered face back to the toplevels it belongs to.
    auto it = m_id_elements.find(id);
    if (it == m_id_elements.end()) {
        return nullptr;
    }
    for (const auto& owner : it->second) {
        if (const auto* color = elementHighlightColor(owner)) {
            return color;
        }
    }
    return nullptr;
}

const Base::Color* ViewProviderFemGeometry::highlightColorForPart(
    const std::string& element,
    vtkIdType id
) const
{
    if (m_elementHighlights.empty()) {
        return nullptr;
    }
    if (const auto* color = elementHighlightColor(element)) {
        return color;
    }
    return idHighlightColor(id);
}

std::string ViewProviderFemGeometry::elementForShapeId(vtkIdType id, const char* fallbackPrefix)
    const
{
    if (id <= 0 || m_shape.IsNull()) {
        return {};
    }
    auto* geom_obj = getObject<Fem::FemGeometry>();
    if (!geom_obj) {
        return {};
    }
    auto subshape = m_shape->GetSubShape(id);
    if (subshape.IsNull()) {
        return {};
    }

    // Clip-plane interiors are tagged with the solid id, so the type of the
    // subshape has the last word on the name and the caller's guess is only used
    // for types that have no name of their own here.
    const char* prefix = fallbackPrefix;
    switch (subshape.ShapeType()) {
        case TopAbs_SOLID:
            prefix = "Solid";
            break;
        case TopAbs_SHELL:
            prefix = "Shell";
            break;
        case TopAbs_FACE:
            prefix = "Face";
            break;
        case TopAbs_EDGE:
            prefix = "Edge";
            break;
        case TopAbs_VERTEX:
            prefix = "Vertex";
            break;
        default:
            break;
    }
    if (!prefix) {
        return {};
    }

    const auto shape_id = geom_obj->Shape.getShape().findShape(subshape);
    if (shape_id <= 0) {
        return {};
    }
    return std::string(prefix) + std::to_string(shape_id);
}

void ViewProviderFemGeometry::updateElementHighlight()
{
    m_highlightoverlaylines->coordIndex.setNum(0);
    m_highlightoverlaypoints->coordIndex.setNum(0);
    if (m_elementHighlights.empty()) {
        return;
    }

    // Only elements named outright, never one inherited from a toplevel: a mark
    // on a solid reads from its faces, and drawing its edges and vertices too
    // would swamp the ones marked in their own right.
    //
    // A marked element that is also selected or hovered keeps the feedback of
    // the selection: drawing the mark over it would swallow the very colour that
    // tells the user their click landed. Faces need no such rule, there
    // SoBrepFaceSet paints the selection over the material by itself.
    const auto marked_color = [this](const std::string& element) -> const Base::Color* {
        if (element.empty() || m_selected.count(element) > 0
            || m_preselected.count(element) > 0) {
            return nullptr;
        }
        return elementHighlightColor(element);
    };

    std::vector<int32_t> indices;
    std::vector<Base::Color> colors;

    // Edges: every polyline of m_lines is one line cell, in the order of
    // m_lineids, so walking the runs pairs an index range with its shape id.
    const int32_t* source = m_lines->coordIndex.getValues(0);
    const int source_count = m_lines->coordIndex.getNum();
    size_t polyline = 0;
    int run_start = 0;
    for (int i = 0; i < source_count; ++i) {
        if (source[i] >= 0) {
            continue;
        }
        if (polyline < m_lineids.size()) {
            const auto shape_id = m_lineids[polyline];
            const auto* color = marked_color(elementForShapeId(shape_id, "Edge"));
            if (color) {
                indices.insert(indices.end(), source + run_start, source + i);
                indices.push_back(-1);
                colors.push_back(*color);
            }
        }
        ++polyline;
        run_start = i + 1;
    }

    if (!indices.empty()) {
        m_highlightoverlaylines->coordIndex.setNum(static_cast<int>(indices.size()));
        int32_t* target = m_highlightoverlaylines->coordIndex.startEditing();
        std::copy(indices.begin(), indices.end(), target);
        m_highlightoverlaylines->coordIndex.finishEditing();

        m_highlightoverlaylinematerial->diffuseColor.setNum(static_cast<int>(colors.size()));
        for (size_t i = 0; i < colors.size(); ++i) {
            m_highlightoverlaylinematerial->diffuseColor
                .set1Value(static_cast<int>(i), colors[i].r, colors[i].g, colors[i].b);
        }
    }

    // Vertices: SoBrepPointSet draws the leading coordinates in the order of
    // m_pointids, the same mapping getElement resolves a picked point through.
    indices.clear();
    colors.clear();
    for (size_t i = 0; i < m_pointids.size(); ++i) {
        const auto shape_id = m_pointids[i];
        const auto* color = marked_color(elementForShapeId(shape_id, "Vertex"));
        if (color) {
            indices.push_back(static_cast<int32_t>(i));
            colors.push_back(*color);
        }
    }

    if (!indices.empty()) {
        m_highlightoverlaypoints->coordIndex.setNum(static_cast<int>(indices.size()));
        int32_t* target = m_highlightoverlaypoints->coordIndex.startEditing();
        std::copy(indices.begin(), indices.end(), target);
        m_highlightoverlaypoints->coordIndex.finishEditing();

        m_highlightoverlaypointmaterial->diffuseColor.setNum(static_cast<int>(colors.size()));
        for (size_t i = 0; i < colors.size(); ++i) {
            m_highlightoverlaypointmaterial->diffuseColor
                .set1Value(static_cast<int>(i), colors[i].r, colors[i].g, colors[i].b);
        }
    }
}

void ViewProviderFemGeometry::addIdElement(vtkIdType id, const std::string& element)
{
    auto& owners = m_id_elements[id];
    if (std::find(owners.begin(), owners.end(), element) == owners.end()) {
        owners.push_back(element);
    }
}

bool ViewProviderFemGeometry::idHasElement(vtkIdType id, const std::string& element) const
{
    auto it = m_id_elements.find(id);
    if (it == m_id_elements.end()) {
        return false;
    }
    return std::find(it->second.begin(), it->second.end(), element) != it->second.end();
}

bool ViewProviderFemGeometry::idHasAnyElement(
    vtkIdType id,
    const std::set<std::string>& elements
) const
{
    auto it = m_id_elements.find(id);
    if (it == m_id_elements.end()) {
        return false;
    }
    return std::any_of(it->second.begin(), it->second.end(), [&elements](const auto& owner) {
        return elements.count(owner) > 0;
    });
}

std::string ViewProviderFemGeometry::idElementForColor(vtkIdType id) const
{
    auto it = m_id_elements.find(id);
    if (it == m_id_elements.end() || it->second.empty()) {
        return {};
    }
    return it->second.front();
}

std::vector<std::string> ViewProviderFemGeometry::volumeOwnersOf(const std::string& element) const
{
    if (isVolumeElementName(element)) {
        return {element};
    }
    const char* prefix = nullptr;
    if (element.rfind("Face", 0) == 0) {
        prefix = "Face";
    }
    else if (element.rfind("Edge", 0) == 0) {
        prefix = "Edge";
    }
    else if (element.rfind("Vertex", 0) == 0) {
        prefix = "Vertex";
    }
    std::set<std::string> owners;
    for (const auto& [id, names] : m_id_elements) {
        bool hit = std::find(names.begin(), names.end(), element) != names.end();
        if (!hit && prefix) {
            hit = elementForShapeId(id, prefix) == element;
        }
        if (!hit) {
            continue;
        }
        for (const auto& name : names) {
            if (isVolumeElementName(name)) {
                owners.insert(name);
            }
        }
    }
    return {owners.begin(), owners.end()};
}

void ViewProviderFemGeometry::setPreselectPromotion(bool on)
{
    if (m_preselectPromotion == on) {
        return;
    }
    m_preselectPromotion = on;
    syncSelectionHighlight();
}

std::string ViewProviderFemGeometry::getElement(const SoDetail* detail) const
{
    if (!detail) {
        return {};
    }
    if (!getObject<Fem::FemGeometry>()) {
        return {};
    }

    vtkIdType vtk_id = -1;
    const char* prefix = nullptr;

    if (detail->getTypeId() == SoFaceDetail::getClassTypeId()) {
        // m_faceids is filled per emitted triangle, so the triangle index maps
        // the picked primitive directly. partIndex (which SoBrepFaceSet derives
        // from the same triangle index) is the fallback for synthetic details.
        const auto* face_detail = static_cast<const SoFaceDetail*>(detail);
        const int face = face_detail->getFaceIndex();
        const int part = face_detail->getPartIndex();
        if (face >= 0 && static_cast<size_t>(face) < m_faceids.size()) {
            vtk_id = m_faceids[face];
        }
        else if (part >= 0 && static_cast<size_t>(part) < m_part_shape_ids.size()) {
            vtk_id = m_part_shape_ids[part];
        }
        else {
            return {};
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

    // Clip-plane interiors are tagged with the solid id; the name follows the
    // type of the subshape so the highlight matches the cut face rather than a
    // random Face of that solid.
    return elementForShapeId(vtk_id, prefix);
}

SoDetail* ViewProviderFemGeometry::getDetail(const char* subelement) const
{
    if (!subelement || !subelement[0]) {
        return nullptr;
    }

    auto type = Part::TopoShape::getElementTypeAndIndex(subelement);
    const std::string& element = type.first;

    // Toplevel solids/shells: prefer the clip-plane interior part (tagged with the
    // solid vtk id). Falling back to the first mapped face keeps a valid detail
    // for SoHighlightElementAction (null would highlight the whole object).
    if (element.empty() && isVolumeElementName(subelement)) {
        int fallback = -1;
        for (std::size_t i = 0; i < m_part_shape_ids.size(); ++i) {
            const vtkIdType sid = m_part_shape_ids[i];
            auto sub = m_shape->GetSubShape(sid);
            if (!sub.IsNull()
                && (sub.ShapeType() == TopAbs_SOLID || sub.ShapeType() == TopAbs_SHELL
                    || sub.ShapeType() == TopAbs_COMPSOLID
                    || sub.ShapeType() == TopAbs_COMPOUND)) {
                if (idHasElement(sid, subelement)) {
                    SoFaceDetail* detail = new SoFaceDetail();
                    detail->setPartIndex(static_cast<int>(i));
                    return detail;
                }
            }
            if (fallback < 0 && idHasElement(sid, subelement)) {
                fallback = static_cast<int>(i);
            }
        }
        if (fallback >= 0) {
            SoFaceDetail* detail = new SoFaceDetail();
            detail->setPartIndex(fallback);
            return detail;
        }
        return nullptr;
    }

    // Exact face / edge / vertex. findShape can miss once an element map is
    // present, so also resolve faces through the part map built for rendering.
    for (std::size_t i = 0; i < m_part_shape_ids.size(); ++i) {
        // Only when the part itself is that element (2D toplevel Face), not when
        // a face is tagged with its owning Solid name.
        if (idHasElement(m_part_shape_ids[i], subelement) && element != "Face"
            && element != "Edge" && element != "Vertex") {
            SoFaceDetail* detail = new SoFaceDetail();
            detail->setPartIndex(static_cast<int>(i));
            return detail;
        }
    }

    auto geometry = getObject<Fem::FemGeometry>()->Shape.getShape();
    auto subshape = geometry.findShape(subelement);
    if (subshape.IsNull()) {
        return nullptr;
    }
    auto vtk_id = m_shape->GetSubShapeId(subshape);
    if (vtk_id <= 0) {
        return nullptr;
    }

    if (element == "Face") {
        auto it = m_face_id_to_part_index.find(vtk_id);
        if (it == m_face_id_to_part_index.end()) {
            return nullptr;
        }
        SoFaceDetail* detail = new SoFaceDetail();
        detail->setPartIndex(it->second);
        return detail;
    }
    if (element == "Edge") {
        auto it = m_line_id_to_index.find(vtk_id);
        if (it == m_line_id_to_index.end()) {
            return nullptr;
        }
        SoLineDetail* detail = new SoLineDetail();
        detail->setLineIndex(it->second);
        return detail;
    }
    if (element == "Vertex") {
        auto it = m_point_id_to_index.find(vtk_id);
        if (it == m_point_id_to_index.end()) {
            return nullptr;
        }
        SoPointDetail* detail = new SoPointDetail();
        detail->setCoordinateIndex(it->second);
        return detail;
    }

    return nullptr;
}

std::string ViewProviderFemGeometry::elementFromSelection(
    const char* docName,
    const char* objName,
    const char* subName
) const
{
    auto* geom_obj = getObject<Fem::FemGeometry>();
    if (!geom_obj || !docName || !objName || !geom_obj->getDocument()) {
        return {};
    }
    auto* doc = geom_obj->getDocument();
    if (strcmp(docName, doc->getName()) != 0) {
        return {};
    }

    auto* target = doc->getObject(objName);
    if (!target) {
        return {};
    }

    // A selection subname addresses a path of objects followed by the shape
    // element, and the element may carry an element-map prefix:
    //   "Solid1"  "GeometryImport.Solid1"  ";Face1;:H…,F.Face1"
    // Follow the object path; the trailing component is the element.
    const std::string sub(subName ? subName : "");
    std::string element;
    std::size_t pos = 0;
    while (true) {
        const auto dot = sub.find('.', pos);
        if (dot == std::string::npos) {
            element = sub.substr(pos);
            break;
        }
        const std::string component = sub.substr(pos, dot - pos);
        if (auto* child = doc->getObject(component.c_str())) {
            target = child;
        }
        pos = dot + 1;
    }
    if (element.empty()) {
        return {};
    }

    if (target == geom_obj) {
        return element;
    }

    // The group and the last step of its chain share one shape, and the group is
    // the object that renders it. Accept element names selected on that step, so
    // selections made on either object highlight what is on screen.
    if (auto* ext = geom_obj->getExtensionByType<App::GroupExtension>(true)) {
        const auto& children = ext->Group.getValues();
        for (auto it = children.rbegin(); it != children.rend(); ++it) {
            if (*it && (*it)->isDerivedFrom(Fem::FemGeometry::getClassTypeId())) {
                return (*it == target) ? element : std::string();
            }
        }
    }

    return {};
}

void ViewProviderFemGeometry::applySelectionHighlight()
{
    auto* geom_obj = getObject<Fem::FemGeometry>();
    if (!geom_obj || !m_faces) {
        return;
    }

    auto appendPartIndices = [this, geom_obj](const std::set<std::string>& elements, SoMFInt32& field) {
        std::set<int> parts;
        auto geometry = geom_obj->Shape.getShape();

        // 1) Toplevel names (Solid1, …): faces tagged with that name, and clip-
        //    plane interiors whose shape id is the solid itself.
        for (size_t i = 0; i < m_part_shape_ids.size(); ++i) {
            const vtkIdType sid = m_part_shape_ids[i];
            if (idHasAnyElement(sid, elements)) {
                parts.insert(static_cast<int>(i));
                continue;
            }
            auto sub = m_shape->GetSubShape(sid);
            if (sub.IsNull()) {
                continue;
            }
            const auto st = sub.ShapeType();
            if (st != TopAbs_SOLID && st != TopAbs_SHELL && st != TopAbs_COMPSOLID
                && st != TopAbs_COMPOUND) {
                continue;
            }
            const auto id = geometry.findShape(sub);
            if (id <= 0) {
                continue;
            }
            const std::string name = Part::TopoShape::shapeName(st) + std::to_string(id);
            if (elements.count(name)) {
                parts.insert(static_cast<int>(i));
            }
        }

        // 2) Single faces below a toplevel (a face of a selected solid).
        for (const auto& name : elements) {
            auto sub = geometry.findShape(name.c_str());
            if (sub.IsNull() || sub.ShapeType() != TopAbs_FACE) {
                continue;
            }
            const vtkIdType faceId = m_shape->GetSubShapeId(sub);
            if (faceId <= 0) {
                continue;
            }
            for (size_t i = 0; i < m_part_shape_ids.size(); ++i) {
                if (m_part_shape_ids[i] == faceId) {
                    parts.insert(static_cast<int>(i));
                }
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

    // Face/Edge/Vertex hover stays on SoHighlightElementAction + getDetail only,
    // which highlights exactly the picked part. Solid/Shell hover (including the
    // clip-plane cut faces, which report their solid) must light every face of
    // that solid, and a detail can only name one part — so those go through the
    // overlay field.
    std::set<std::string> solidPreselect;
    for (const auto& el : m_preselected) {
        if (isVolumeElementName(el)) {
            solidPreselect.insert(el);
        }
    }
    appendPartIndices(solidPreselect, m_faces->highlightPartIndex);
    m_faces->touch();

    // The marks yield to the selection, so they follow it. This is also the one
    // place every rebuild passes through, by way of resetSelectionVisuals.
    updateElementHighlight();
}

void ViewProviderFemGeometry::resetSelectionVisuals()
{
    // Coin stores the picked part index per node, so the contexts survive a
    // mesh rebuild and then highlight whatever face inherited that index.
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

    // Our own overlay fields index the same table, so refill them from the
    // selection that is actually current.
    syncSelectionHighlight();
}

void ViewProviderFemGeometry::syncSelectionHighlight()
{
    auto* geom_obj = getObject<Fem::FemGeometry>();
    if (!geom_obj || !geom_obj->getDocument()) {
        return;
    }

    m_selected.clear();
    m_preselected.clear();

    auto sels = Gui::Selection().getSelectionEx(
        geom_obj->getDocument()->getName(),
        App::DocumentObject::getClassTypeId(),
        Gui::ResolveMode::NoResolve
    );
    for (const auto& sel : sels) {
        for (const auto& sub : sel.getSubNames()) {
            auto el = elementFromSelection(sel.getDocName(), sel.getFeatName(), sub.c_str());
            if (!el.empty()) {
                m_selected.insert(std::move(el));
            }
        }
    }

    // Preselection is a single slot on SelectionSingleton
    const auto& pre = Gui::Selection().getPreselection();
    if (pre.pDocName && pre.pObjectName) {
        auto el = elementFromSelection(pre.pDocName, pre.pObjectName, pre.pSubName);
        if (!el.empty()) {
            if (m_preselectPromotion) {
                auto owners = volumeOwnersOf(el);
                if (!owners.empty()) {
                    m_preselected.insert(owners.begin(), owners.end());
                }
                else {
                    m_preselected.insert(std::move(el));
                }
            }
            else {
                m_preselected.insert(std::move(el));
            }
        }
    }

    applySelectionHighlight();
}

void ViewProviderFemGeometry::onSelectionChanged(const Gui::SelectionChanges& /*change*/)
{
    // Also invoked via notifyDocumentObjectViewProvider when this object is the
    // selection target. The document-wide FemGeometrySelectionObserver covers
    // remapped parent selections; keep this as a fast path for direct hits.
    syncSelectionHighlight();
}

void ViewProviderFemGeometry::updateData(const App::Property* prop)
{
    Fem::FemGeometry* geometryObject = getObject<Fem::FemGeometry>();
    if (prop == &geometryObject->Shape && (!isChainStep() || m_chainPreview)) {
        auto shape = geometryObject->Shape.getShape();
        m_shape = new IVtkOCC_Shape(shape.getShape());
        m_vtksource->SetShape(m_shape);
        ensureViewStateConnection();
        updateVTK();
    }

    // Joining or leaving the chain is what makes a step a step, and the step
    // itself gets no property change for it.
    if (auto* ext = geometryObject->getExtensionByType<App::GroupExtension>(true);
        ext && prop == &ext->Group) {
        refreshChainSteps();
    }

    ViewProviderDocumentObject::updateData(prop);
}

void ViewProviderFemGeometry::finishRestoring()
{
    ViewProviderDocumentObject::finishRestoring();
    applyChainRole();
    refreshChainSteps();
}

void ViewProviderFemGeometry::onChanged(const App::Property* prop)
{
    if (prop == &DisplayMode) {
        update3D();
    }

    ViewProviderDocumentObject::onChanged(prop);
}

void ViewProviderFemGeometry::updateVTK()
{
    auto* geom_obj = getObject<Fem::FemGeometry>();
    if (!geom_obj || (m_isChainStep && !m_chainPreview)) {
        return;
    }

    ensureViewStateConnection();
    auto* state = m_boundViewState;

    const std::set<std::string> empty_hidden;
    const std::map<std::string, ClippingPlane> empty_clips;
    // Hiding applies to the previewed input too: while a step is edited the
    // view panel describes that shape, and switching parts off is how the user
    // reaches what is buried inside.
    const auto& filtered = state ? state->hiddenElements() : empty_hidden;
    const auto clipper = state ? state->activeClipPlanes() : empty_clips;
    const DimensionMode dimMode = state ? state->dimensionMode() : DimensionMode::Highest;

    IVtk_ShapeIdList passthrough_ids;

    m_id_elements.clear();
    Fem::componentIdType component_id = 0;
    for (auto& component : geom_obj->getComponents()) {
        component_id++;

        auto component_name = std::string("Component") + std::to_string(component_id);
        if (filtered.count(component_name)) {
            continue;
        }

        auto names = geom_obj->getToplevelElements(component);
        for (const auto& name : names) {
            if (filtered.count(name)) {
                continue;
            }

            auto sub = geom_obj->getSubShapes(name);
            if (sub.empty()) {
                continue;
            }
            auto& sub_shape = sub[0];
            auto sub_vtk_id = m_shape->GetSubShapeId(sub_shape.getShape());

            // Map every visible face of this toplevel to its name. Solids often
            // fail GetSubShapeId (IVtk IsSame), so always walk faces explicitly.
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

            if (sub_shape.shapeType() == TopAbs_FACE) {
                // GetSubIds for faces do not include edges and vertices.
                auto vertices = sub_shape.getSubShapes(TopAbs_VERTEX);
                for (auto& vertex : vertices) {
                    auto vid = m_shape->GetSubShapeId(vertex);
                    if (vid > 0 && !passthrough_ids.Contains(vid)) {
                        passthrough_ids.Append(vid);
                    }
                }
                auto edges = sub_shape.getSubShapes(TopAbs_EDGE);
                for (auto& edge : edges) {
                    auto eid = m_shape->GetSubShapeId(edge);
                    if (eid > 0 && !passthrough_ids.Contains(eid)) {
                        passthrough_ids.Append(eid);
                    }
                }
            }
            else if (sub_vtk_id > 0) {
                auto ids = m_shape->GetSubIds(sub_vtk_id);
                for (const auto& id : ids) {
                    if (!passthrough_ids.Contains(id)) {
                        passthrough_ids.Append(id);
                    }
                    addIdElement(id, name);
                }
            }
            if (sub_vtk_id > 0) {
                addIdElement(sub_vtk_id, name);
                passthrough_ids.Append(sub_vtk_id);
            }
        }
    }

    m_vtkshapefilter->SetData(passthrough_ids);
    m_vtkshapefilter->Modified();

    m_vtkshapefilter->Update();
    m_visdata = m_vtkshapefilter->GetOutput();

    applyClipPlanes(clipper, dimMode, passthrough_ids);

    m_vtkgeometryoverlayextract->Update();
    auto overlay_data = m_vtkgeometryoverlayextract->GetOutput();
    m_visgeometryoverlay = vtkPolyData::SafeDownCast(overlay_data);

    update3D();
}

void ViewProviderFemGeometry::applyClipPlanes(
    const std::map<std::string, ClippingPlane>& clipper,
    DimensionMode dimMode,
    const IVtk_ShapeIdList& passthrough_ids
)
{
    auto* geom_obj = getObject<Fem::FemGeometry>();
    if (clipper.empty() || !geom_obj || !m_visdata) {
        return;
    }

    try {
        auto clip_planes = vtkSmartPointer<vtkPlaneCollection>::New();
        for (const auto& clip : clipper) {
            const Base::Vector3d& dir = clip.second.Direction;
            if (dir.Length() < 1e-9) {
                Base::Console().warning(
                    "FEM geometry: skipping clip plane '%s' with a degenerate normal\n",
                    clip.first.c_str()
                );
                continue;
            }

            auto plane = vtkSmartPointer<vtkPlane>::New();
            plane->SetNormal(dir.x, dir.y, dir.z);
            plane->SetOrigin(clip.second.Origin.x, clip.second.Origin.y, clip.second.Origin.z);
            clip_planes->AddItem(plane);

            m_vtkclipfilter->SetClipFunction(plane);
            m_vtkclipfilter->SetInputData(m_visdata);
            // IVtk stores edges as polylines, which vtkTableBasedClipDataSet reports
            // as unsupported: only its output *points* are duplicated, the Shape_ID
            // cell data stays attached to the right cells. Silence that one warning.
            const int warn = vtkObject::GetGlobalWarningDisplay();
            vtkObject::SetGlobalWarningDisplay(0);
            m_vtkclipgeometryfilter->Update();
            vtkObject::SetGlobalWarningDisplay(warn);

            vtkPolyData* clip_out = m_vtkclipgeometryfilter->GetOutput();
            if (!clip_out) {
                Base::Console().warning(
                    "FEM geometry: clip plane '%s' produced no data, geometry left unclipped\n",
                    clip.first.c_str()
                );
                return;
            }
            vtkNew<vtkPolyData> clipped;
            clipped->DeepCopy(clip_out);
            m_visdata = clipped;
        }

        const bool solidClipInterior =
            (dimMode == DimensionMode::Volume || dimMode == DimensionMode::Highest);
        if (clip_planes->GetNumberOfItems() == 0 || !solidClipInterior) {
            return;
        }

        auto shape = geom_obj->Shape.getShape();
        for (TopoDS_Shape& solid : shape.getSubShapes(TopAbs_ShapeEnum::TopAbs_SOLID)) {
            vtkIdType solid_id =
                (shape.shapeType() == TopAbs_SOLID) ? 1 : m_shape->GetSubShapeId(solid);

            if (!passthrough_ids.Contains(solid_id)) {
                continue;
            }

            // Re-tessellate each solid alone so shared faces are not duplicated
            // with opposing normals (which breaks vtkClipClosedSurface).
            IVtkOCC_Shape::Handle vtk_shape = new IVtkOCC_Shape(solid);
            m_vtkclipshapesource->SetShape(vtk_shape);

            m_vtkclipsurfacefilter->SetClippingPlanes(clip_planes);
            m_vtkclipnormals->Update();
            vtkPolyData* solid_clip_plane = m_vtkclipnormals->GetOutput();

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
            id_data->SetName(IVtkVTK_ShapeData::ARRNAME_SUBSHAPE_IDS());
            mesh_data->SetName(IVtkVTK_ShapeData::ARRNAME_MESH_TYPES());
            solid_clip_plane->GetCellData()->AddArray(id_data);
            solid_clip_plane->GetCellData()->AddArray(mesh_data);

            // Ensure hover/selection can resolve the cut face to SolidN.
            const auto sid = shape.findShape(solid);
            if (sid > 0) {
                addIdElement(
                    solid_id,
                    Part::TopoShape::shapeName(TopAbs_SOLID) + std::to_string(sid)
                );
            }

            vtkNew<vtkAppendPolyData> append;
            append->AddInputData(m_visdata);
            append->AddInputData(solid_clip_plane);
            append->Update();
            if (!append->GetOutput()) {
                continue;
            }
            vtkNew<vtkPolyData> merged;
            merged->DeepCopy(append->GetOutput());
            m_visdata = merged;
        }
    }
    catch (const Standard_Failure& e) {
        Base::Console().warning("FEM geometry: clipping failed in OCC: %s\n", e.GetMessageString());
    }
    catch (const Base::Exception& e) {
        Base::Console().warning("FEM geometry: clipping failed: %s\n", e.what());
    }
    catch (const std::exception& e) {
        Base::Console().warning("FEM geometry: clipping failed: %s\n", e.what());
    }
}

void ViewProviderFemGeometry::updateColors()
{
    auto* geom_obj = getObject<Fem::FemGeometry>();
    if (!geom_obj) {
        return;
    }

    ensureViewStateConnection();
    auto* state = m_boundViewState;
    const Classification* classification = state ? state->classification() : nullptr;

    // SoBrepFaceSet remaps materials by partIndex (BREP faces). PER_FACE triggers a
    // Coin warning on hover and falls back to slower overlay passes.
    m_facematerialbinding->value.setValue(SoMaterialBinding::PER_PART);

    // Prefer shared classification colours when a colour mode is active
    if (classification && !classification->categories().empty()
        && state && state->colorMode() != ColorMode::CellType) {

        const auto cats = classification->categories();
        auto shape = geom_obj->Shape.getShape();

        m_facematerial->diffuseColor.startEditing();
        m_facematerial->diffuseColor.setNum(static_cast<int>(m_part_shape_ids.size()));
        for (size_t i = 0; i < m_part_shape_ids.size(); ++i) {
            const auto& vtkid = m_part_shape_ids[i];
            std::string element;
            if (state->colorMode() == ColorMode::Subelement) {
                auto subshape = m_shape->GetSubShape(vtkid);
                if (!subshape.IsNull()) {
                    auto id = shape.findShape(subshape);
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
            // Classification categories are often toplevel-only (Solid1, …). FaceN
            // lookups would all fall through to category 0 and paint uniformly —
            // map unknown names back to the owning toplevel.
            int cat = classification->categoryOfElement(element);
            bool known = false;
            for (const auto& c : cats) {
                if (c.key == element) {
                    known = true;
                    break;
                }
            }
            if (!known) {
                auto owner = idElementForColor(vtkid);
                if (!owner.empty()) {
                    element = std::move(owner);
                    cat = classification->categoryOfElement(element);
                }
            }
            if (cat < 0 || cats.empty()) {
                cat = 0;
            }
            else {
                cat = cat % static_cast<int>(cats.size());
            }
            Base::Color c = cats[static_cast<size_t>(cat)].color;
            // A mark outranks the colour mode: it is there to answer "did my
            // pick land", which a category colour cannot.
            if (const auto* marked = highlightColorForPart(element, vtkid)) {
                c = *marked;
            }
            m_facematerial->diffuseColor.set1Value(
                static_cast<int>(i),
                c.r,
                c.g,
                c.b
            );
        }
        m_facematerial->diffuseColor.finishEditing();
        return;
    }

    // No colour mode, or the colour mode has nothing to say: paint from the
    // live palette in the same order as the classification would, so a later
    // palette setting recolouring reaches this path too. Nothing is stored.
    std::vector<std::string> names;
    auto components = geom_obj->getComponents();
    for (auto& component : components) {
        auto comp_names = geom_obj->getToplevelElements(component);
        names.insert(names.end(), comp_names.begin(), comp_names.end());
    }
    std::sort(names.begin(), names.end());

    std::map<std::string, Base::Color> element_color;
    for (size_t i = 0; i < names.size(); i++) {
        element_color[names[i]] = Classification::colorForIndex(static_cast<int>(i));
    }

    m_facematerial->diffuseColor.startEditing();
    m_facematerial->diffuseColor.setNum(static_cast<int>(m_part_shape_ids.size()));
    for (size_t i = 0; i < m_part_shape_ids.size(); i++) {
        auto& vtkid = m_part_shape_ids[i];
        // Never index the maps with operator[]: an id without a toplevel name
        // would insert a default-constructed (black) colour and paint that part
        // black instead of leaving it in its component colour.
        Base::Color face_color = Classification::colorForIndex(0);
        auto owner = idElementForColor(vtkid);
        if (!owner.empty()) {
            auto color_it = element_color.find(owner);
            if (color_it != element_color.end()) {
                face_color = color_it->second;
            }
        }
        if (const auto* marked = highlightColorForPart(elementForShapeId(vtkid, "Face"), vtkid)) {
            face_color = *marked;
        }
        m_facematerial->diffuseColor.set1Value(
            static_cast<int>(i),
            face_color.r,
            face_color.g,
            face_color.b
        );
    }
    m_facematerial->diffuseColor.finishEditing();
}

void ViewProviderFemGeometry::update3D()
{
    // Before anything that gives up on the geometry: a clip plane that takes
    // the whole shape is exactly when the ghost is the only thing left to say
    // where it went.
    updateGeometryOverlay();

    if (!m_visdata || m_visdata->GetNumberOfCells() == 0) {
        m_faces->coordIndex.setNum(0);
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

    auto pntData = m_visdata->GetPointData();
    FemMeshRenderer::writePointData(
        m_coordinates,
        m_normals,
        m_normalBinding,
        m_visdata->GetPoints(),
        pntData->GetNormals(),
        pntData->GetTCoords()
    );

    auto cd = m_visdata->GetCellData();

    vtkIdTypeArray* shape_ids =
        vtkIdTypeArray::SafeDownCast(cd->GetArray(IVtkVTK_ShapeData::ARRNAME_SUBSHAPE_IDS()));
    vtkIdTypeArray* mesh_types =
        vtkIdTypeArray::SafeDownCast(cd->GetArray(IVtkVTK_ShapeData::ARRNAME_MESH_TYPES()));
    if (!shape_ids || !mesh_types) {
        m_faces->coordIndex.setNum(0);
        m_lines->coordIndex.setNum(0);
        m_markers->numPoints = 0;
        resetSelectionVisuals();
        return;
    }

    // Shape_ID / mesh-type should be 1:1 with cells. If a filter left them
    // mismatched, still render what we can rather than blanking the mesh.
    const vtkIdType nCells = m_visdata->GetNumberOfCells();
    const vtkIdType nMeta = std::min(
        {nCells, shape_ids->GetNumberOfTuples(), mesh_types->GetNumberOfTuples()}
    );
    if (nMeta != nCells) {
        Base::Console().warning(
            "FemGeometry: clipped mesh cell data truncated "
            "(%lld cells, %lld shape ids)\n",
            static_cast<long long>(nCells),
            static_cast<long long>(shape_ids->GetNumberOfTuples())
        );
    }

    m_faces->coordIndex.startEditing();
    m_faces->partIndex.startEditing();
    m_lines->coordIndex.startEditing();

    uint pnt_cnt = 0;
    uint line_soidx = 0;
    uint face_soidx = 0;
    int face_current_shape_id = -1;
    uint face_shape_id_cnt = 0;
    uint face_shape_id_soidx = 0;
    vtkNew<vtkIdList> points;

    // SoBrep*Sets require all cells with the same shape_id in one run
    vtkNew<vtkIdList> sorted_indices;
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

    ensureViewStateConnection();
    auto* state = m_boundViewState;
    const DimensionMode dimMode = state ? state->dimensionMode() : DimensionMode::Highest;
    const bool wireframe = state ? state->wireframe() : (DisplayMode.getValue() == 1);
    const bool draw_faces = !wireframe && dimMode != DimensionMode::Curve
        && dimMode != DimensionMode::Point;

    for (vtkIdType sort_id = 0; sort_id < sorted_indices->GetNumberOfIds(); sort_id++) {
        auto cell_id = sorted_indices->GetId(sort_id);
        auto shape_id = shape_ids->GetValue(cell_id);
        auto mesh_type = mesh_types->GetValue(cell_id);

        if (draw_faces
            && (mesh_type == IVtk_MeshType::MT_ShadedFace
                || mesh_type == IVtk_MeshType::MT_WireFrameFace)) {

            m_visdata->GetCellPoints(cell_id, points);

            const vtkIdType npts = points->GetNumberOfIds();
            uint created_triangles = 0;
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

                created_triangles = 2;
                m_faceids.push_back(shape_id);
                m_faceids.push_back(shape_id);
            }
            else if (npts >= 3) {
                // Triangles and (defensively) fan-triangulated n-gons. Never
                // throw here — an exception during clip update aborts the GUI
                // notify and leaves only the overlay wireframe visible.
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
                    ++created_triangles;
                }
            }
            else {
                continue;
            }

            if (created_triangles == 0) {
                continue;
            }

            if (shape_id == face_current_shape_id) {
                face_shape_id_cnt += created_triangles;
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
                face_shape_id_cnt = created_triangles;
                m_face_id_to_part_index[shape_id] = static_cast<int>(face_shape_id_soidx);
                m_part_shape_ids.push_back(shape_id);
            }
        }
        else if (
            mesh_type == IVtk_MeshType::MT_FreeEdge || mesh_type == IVtk_MeshType::MT_BoundaryEdge
            || mesh_type == IVtk_MeshType::MT_SharedEdge || mesh_type == IVtk_MeshType::MT_SeamEdge
        ) {

            auto topo_shape = m_shape->GetSubShape(shape_id);
            if (topo_shape.ShapeType() != TopAbs_ShapeEnum::TopAbs_EDGE) {
                continue;
            }

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
        else if (mesh_type == MT_FreeVertex || mesh_type == MT_SharedVertex) {
            pnt_cnt++;
            m_point_id_to_index.emplace(shape_id, static_cast<int>(m_pointids.size()));
            m_pointids.push_back(shape_id);
        }
    }

    m_faces->coordIndex.setNum(static_cast<int>(face_soidx));
    m_lines->coordIndex.setNum(static_cast<int>(line_soidx));
    m_markers->numPoints = static_cast<int>(pnt_cnt);

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

    updateColors();
    resetSelectionVisuals();
}

void ViewProviderFemGeometry::updateGeometryOverlay()
{
    auto* state = m_boundViewState;
    const auto clipper = state ? state->activeClipPlanes() : std::map<std::string, ClippingPlane> {};
    const std::set<std::string> empty_hidden;
    const auto& hidden = state ? state->hiddenElements() : empty_hidden;
    const bool wireframe = state ? state->wireframe() : (DisplayMode.getValue() == 1);
    const bool overlay_enabled = !state || state->overlay();
    const bool show_geometry_overlay =
        overlay_enabled && (wireframe || !clipper.empty() || !hidden.empty());
    if (!show_geometry_overlay || !m_visgeometryoverlay) {
        m_geometryoverlay->coordIndex.setNum(0);
        return;
    }

    auto* visdata = m_visgeometryoverlay.Get();
    auto* pntData = visdata->GetPointData();
    FemMeshRenderer::writePointData(
        m_geometryoverlaycoordinates,
        m_geometryoverlaynormals,
        m_geometryoverlaynormalBinding,
        visdata->GetPoints(),
        pntData->GetNormals(),
        pntData->GetTCoords()
    );

    if (visdata->GetNumberOfPolys() > 0) {
        m_geometryoverlay->coordIndex.startEditing();
        vtkIdType npts = 0;
        const vtkIdType* indx = nullptr;
        int soidx = 0;
        auto cells = visdata->GetPolys();
        for (cells->InitTraversal(); cells->GetNextCell(npts, indx);) {
            for (vtkIdType i = 0; i < npts; i++) {
                m_geometryoverlay->coordIndex.set1Value(soidx, static_cast<int>(indx[i]));
                ++soidx;
            }
            m_geometryoverlay->coordIndex.set1Value(soidx, -1);
            ++soidx;
        }
        m_geometryoverlay->coordIndex.setNum(soidx);
        m_geometryoverlay->coordIndex.finishEditing();
    }
    else {
        m_geometryoverlay->coordIndex.setNum(0);
    }
}

void ViewProviderFemGeometry::setClippingPlane(const std::string& name, const ClippingPlane& plane)
{
    ensureViewStateConnection();
    if (m_boundViewState) {
        m_boundViewState->setClipPlane(name, plane);
    }
}

void ViewProviderFemGeometry::removeClippingPlane(const std::string& name)
{
    ensureViewStateConnection();
    if (m_boundViewState) {
        m_boundViewState->removeClipPlane(name);
    }
}

PyObject* ViewProviderFemGeometry::getPyObject()
{
    if (!pyViewObject) {
        pyViewObject = new ViewProviderFemGeometryPy(this);
    }
    pyViewObject->IncRef();
    return pyViewObject;
}

namespace Gui
{
PROPERTY_SOURCE_TEMPLATE(FemGui::ViewProviderFemGeometryPython, FemGui::ViewProviderFemGeometry)

template class FemGuiExport ViewProviderFeaturePythonT<FemGui::ViewProviderFemGeometry>;

}  // namespace Gui
