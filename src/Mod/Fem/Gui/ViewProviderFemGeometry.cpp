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

# include <Inventor/nodes/SoSeparator.h>
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
#include <Mod/Part/Gui/ViewProviderExt.h>
#include <Mod/Part/Gui/ViewProviderPreviewExtension.h>

#include <Standard_Failure.hxx>

#include "ActiveAnalysisObserver.h"
#include "AnalysisViewState.h"
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

    sPixmap = "Part_3D_object";

    m_separator = new SoSeparator();
    m_separator->ref();
    m_hidden = new SoSeparator();
    m_hidden->ref();

    // Unpickable translucent cutting tool; empty until setToolPreview fills it.
    m_toolPreview = new PartGui::SoPreviewShape();
    m_toolPreview->ref();
    const Base::Color toolColor = defaultToolPreviewColor();
    m_toolPreview->color.setValue(toolColor.r, toolColor.g, toolColor.b);
    m_toolPreview->transparency.setValue(0.85f);
    m_toolPreviewSwitch = new SoSwitch();
    m_toolPreviewSwitch->ref();
    m_toolPreviewSwitch->whichChild = SO_SWITCH_NONE;
    m_toolPreviewSwitch->addChild(m_toolPreview);
}

ViewProviderFemGeometry::~ViewProviderFemGeometry()
{
    m_viewStateBinding.release();

    m_separator->unref();
    m_hidden->unref();
    m_toolPreview->unref();
    m_toolPreviewSwitch->unref();
}

Fem::FemAnalysis* ViewProviderFemGeometry::owningAnalysis() const
{
    if (auto* obj = getObject()) {
        // Prefer the analysis that owns this geometry in the tree. Relying only
        // on ActiveAnalysisObserver can miss connections when the VP attaches
        // before the analysis is marked active.
        for (auto* parent : obj->getInList()) {
            if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(parent)) {
                return analysis;
            }
            for (auto* grand : parent->getInList()) {
                if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(grand)) {
                    return analysis;
                }
            }
        }
    }
    return ActiveAnalysisObserver::instance()->getActiveObject();
}

AnalysisViewState* ViewProviderFemGeometry::viewState() const
{
    auto* analysis = owningAnalysis();
    return analysis ? AnalysisViewState::forAnalysis(analysis) : nullptr;
}

void ViewProviderFemGeometry::ensureViewStateConnection()
{
    auto* state = viewState();
    if (m_viewStateBinding.isBoundTo(state)) {
        return;
    }
    m_viewStateBinding.bind(state, [this]() { onViewStateChanged(); });
    if (state) {
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

bool ViewProviderFemGeometry::isChainResult() const
{
    auto* obj = getObject();
    auto* owner = chainOwner();
    if (!obj || !owner) {
        return false;
    }
    auto* ext = owner->getExtensionByType<App::GroupExtension>(true);
    if (!ext) {
        return false;
    }
    // The group takes its shape from the last step of its chain.
    App::DocumentObject* last = nullptr;
    for (auto* child : ext->Group.getValues()) {
        if (Base::freecad_cast<Fem::FemGeometry*>(child)) {
            last = child;
        }
    }
    return last == obj;
}

ViewProviderFemGeometry::ChainRole ViewProviderFemGeometry::chainRole() const
{
    auto* obj = getObject();
    if (!obj) {
        return ChainRole::Owner;
    }

    auto* state = m_viewStateBinding.state();
    auto* subject = state ? state->editSubject() : nullptr;
    if (subject && subject == obj) {
        return ChainRole::Subject;
    }
    if (isChainStep()) {
        return ChainRole::Step;
    }
    // The owner of the chain the subject belongs to has to make room for it.
    if (subject) {
        if (auto* ext = obj->getExtensionByType<App::GroupExtension>(true);
            ext && ext->hasObject(subject)) {
            return ChainRole::SteppedAside;
        }
    }
    return ChainRole::Owner;
}

const char* ViewProviderFemGeometry::maskFor(ChainRole role, ActiveStage stage) const
{
    switch (role) {
        case ChainRole::Step:
            return ViewMode::Hidden;
        case ChainRole::SteppedAside:
            // A switch traverses one child only, and the children of a
            // GeoFeatureGroup hang under the extension-owned "Group" mask.
            // Hiding outright would cut off the subject along with this
            // object's own result, leaving nothing to look at or pick.
            return getDisplayMaskMode(ViewMode::Group) ? ViewMode::Group : ViewMode::Hidden;
        case ChainRole::Owner:
        case ChainRole::Subject:
            // The two draw for different reasons and under the same rule. The
            // stage is not overridden for a subject: opening the panel put the
            // stage on Geometry through the edit scope, and if the user moves
            // it from there while the panel is open that is his to decide.
            break;
    }
    return stage == ActiveStage::Geometry ? ViewMode::Default : ViewMode::Hidden;
}

void ViewProviderFemGeometry::applyChainVisuals()
{
    if (!isAttachedToDocument()) {
        return;
    }

    const ChainRole role = chainRole();
    const bool draws = (role == ChainRole::Owner || role == ChainRole::Subject);

    // A step that has just stopped being one has been ignoring its shape, so it
    // has to be caught up before anything asks it to draw.
    if (draws && m_wasChainStep) {
        pushShapeToHelper();
    }
    m_wasChainStep = (role == ChainRole::Step);

    // Told outright rather than left to work it out from the mask: a helper
    // rendering under a mask nobody traverses is work nobody sees.
    m_geometry.setRenderingEnabled(draws);

    auto* state = m_viewStateBinding.state();
    setStageMask(*this, maskFor(role, state ? state->activeStage() : ActiveStage::Geometry));

    // The tree draws the result badge when it is told to and not before, so the
    // one thing here that is remembered is whether it has been told. A stale
    // copy makes the badge late; it cannot make the object draw the wrong thing.
    if (const bool result = isChainResult(); result != m_badgedAsResult) {
        m_badgedAsResult = result;
        signalChangeIcon();
    }
}

void ViewProviderFemGeometry::applyChainRole()
{
    const bool step = isChainStep();

    // A build step is not a thing you can look at on its own: the group holds
    // the result and renders it. Take the visibility control away instead of
    // leaving a switch that does nothing, the same way objects without a
    // representation do it.
    setToggleVisibility(
        step ? ToggleVisibilityMode::NoToggleVisibility : ToggleVisibilityMode::CanToggleVisibility
    );
    if (step && !Visibility.getValue()) {
        // Visibility is not the user's to set for a step, so it must not be
        // left off: the object would be unable to draw even as the subject of
        // an open panel, with no switch left to turn it back on.
        Visibility.setValue(true);
    }

    applyChainVisuals();
}

QIcon ViewProviderFemGeometry::mergeColorfulOverlayIcons(const QIcon& orig) const
{
    QIcon icon = orig;
    if (isChainResult()) {
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
    applyChainVisuals();
}

/// Hand the current shape to the helper, which is what redraws it.
void ViewProviderFemGeometry::pushShapeToHelper()
{
    auto* geometryObject = getObject<Fem::FemGeometry>();
    if (!geometryObject) {
        return;
    }
    m_geometry.updateFromShape(geometryObject->Shape.getShape(), geometryObject);
}

void ViewProviderFemGeometry::attach(App::DocumentObject* pcObj)
{
    ViewProviderDocumentObject::attach(pcObj);

    // The native case of what the helper renders: an instance addressed by no
    // path and drawn in the frame it was built in. The masks stay here, because
    // which of them is on depends on the chain role as much as on the stage.
    m_geometry.setHost(
        this,
        [this]() { return owningAnalysis(); },
        [this]() { return getObject<Fem::FemGeometry>(); }
    );
    m_geometry.setManageStageVisibility(false);
    m_geometry.attachToSeparator(m_separator);

    m_separator->addChild(m_toolPreviewSwitch);

    addDisplayMaskMode(m_separator, ViewMode::Default);
    addDisplayMaskMode(m_hidden, ViewMode::Hidden);
    // Do not register "Group" here: ViewProviderGeoFeatureGroupExtension owns
    // that mask (pcGroupChildren). A group normally renders the result of its
    // chain itself, and only steps aside onto that mask while a step below it
    // is previewed, see suppressedMaskMode.
    setDisplayMaskMode(ViewMode::Default);

    applyChainRole();
    ensureViewStateConnection();
    m_geometry.connectViewState();
}

void ViewProviderFemGeometry::setDisplayMode(const char* ModeName)
{
    // The mask this asks for is only one of the things that has a say; the
    // chain and the stage have the others, and applyChainVisuals weighs them.
    (void)ModeName;
    applyChainVisuals();
}

std::vector<std::string> ViewProviderFemGeometry::getDisplayModes() const
{
    if (chainRole() == ChainRole::Step) {
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
    m_geometry.setElementHighlight(role, elements, color);
}

void ViewProviderFemGeometry::clearElementHighlight(const std::string& role)
{
    setElementHighlight(role, {}, Base::Color());
}

std::set<std::string> ViewProviderFemGeometry::elementHighlight(const std::string& role) const
{
    return m_geometry.elementHighlight(role);
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
    if (shape.isNull()) {
        clearToolPreview();
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
        m_toolPreviewSwitch->whichChild = 0;
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
    m_toolPreviewSwitch->whichChild = SO_SWITCH_NONE;
    PartGui::ViewProviderPartExt::setupCoinGeometry(TopoDS_Shape(), m_toolPreview, 0.2, 0.35);
    m_toolPreview->transform.setValue(SbMatrix::identity());
}

const Base::Color* ViewProviderFemGeometry::elementHighlightColor(
    const std::string& element
) const
{
    return m_geometry.elementHighlightColor(element);
}

void ViewProviderFemGeometry::setPreselectPromotion(bool on)
{
    m_geometry.setPreselectPromotion(on);
}

std::string ViewProviderFemGeometry::getElement(const SoDetail* detail) const
{
    return m_geometry.elementFromDetail(detail);
}

SoDetail* ViewProviderFemGeometry::getDetail(const char* subelement) const
{
    return m_geometry.detailFromElement(subelement);
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

void ViewProviderFemGeometry::syncSelectionHighlight()
{
    auto* geometryObject = getObject<Fem::FemGeometry>();
    if (!geometryObject || !geometryObject->getDocument()) {
        return;
    }

    // Only which elements of this object are named; what that means for the
    // picture, promotion of a hovered face to its solid included, is the
    // helper's.
    std::set<std::string> selected;
    auto sels = Gui::Selection().getSelectionEx(
        geometryObject->getDocument()->getName(),
        App::DocumentObject::getClassTypeId(),
        Gui::ResolveMode::NoResolve
    );
    for (const auto& sel : sels) {
        for (const auto& sub : sel.getSubNames()) {
            auto el = elementFromSelection(sel.getDocName(), sel.getFeatName(), sub.c_str());
            if (!el.empty()) {
                selected.insert(std::move(el));
            }
        }
    }

    // Preselection is a single slot on SelectionSingleton
    std::set<std::string> preselected;
    const auto& pre = Gui::Selection().getPreselection();
    if (pre.pDocName && pre.pObjectName) {
        auto el = elementFromSelection(pre.pDocName, pre.pObjectName, pre.pSubName);
        if (!el.empty()) {
            preselected.insert(std::move(el));
        }
    }

    m_geometry.setSelectionState(selected, preselected);
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
    if (prop == &geometryObject->Shape) {
        ensureViewStateConnection();
        // A step whose result the group draws keeps no picture of its own, and
        // catches up in applyChainVisuals if it is ever asked for one.
        if (chainRole() != ChainRole::Step) {
            pushShapeToHelper();
        }
    }

    // Joining or leaving the chain is what makes a step a step, and the step
    // itself gets no property change for it. The group is the only one that
    // hears, so it says so once and every member reads its own role again -
    // including one that has just left, which is still connected and finds
    // itself without an owner.
    if (auto* ext = geometryObject->getExtensionByType<App::GroupExtension>(true);
        ext && prop == &ext->Group) {
        if (auto* state = viewState()) {
            state->chainChanged();
        }
        applyChainRole();
    }

    ViewProviderDocumentObject::updateData(prop);
}

void ViewProviderFemGeometry::finishRestoring()
{
    ViewProviderDocumentObject::finishRestoring();
    applyChainRole();
}

void ViewProviderFemGeometry::onChanged(const App::Property* prop)
{
    if (prop == &DisplayMode) {
        m_geometry.onViewStateChanged();
    }

    ViewProviderDocumentObject::onChanged(prop);

    if (prop == &Visibility && isAttachedToDocument()) {
        // Showing the geometry is what the geometry stage is, so the stage has
        // to be read again whenever this changes, including when the user hits
        // space bar on the group in the tree.
        if (auto* state = viewState()) {
            state->stageVisibilityChanged(ActiveStage::Geometry);
        }
    }
}

void ViewProviderFemGeometry::setClippingPlane(const std::string& name, const ClippingPlane& plane)
{
    ensureViewStateConnection();
    if (m_viewStateBinding.state()) {
        m_viewStateBinding.state()->setClipPlane(name, plane);
    }
}

void ViewProviderFemGeometry::removeClippingPlane(const std::string& name)
{
    ensureViewStateConnection();
    if (m_viewStateBinding.state()) {
        m_viewStateBinding.state()->removeClipPlane(name);
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
