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
# include <cmath>

# include <Inventor/nodes/SoCoordinate3.h>
# include <Inventor/nodes/SoDrawStyle.h>
# include <Inventor/nodes/SoLightModel.h>
# include <Inventor/nodes/SoLineSet.h>
# include <Inventor/nodes/SoMaterial.h>
# include <Inventor/nodes/SoPickStyle.h>
# include <Inventor/nodes/SoSeparator.h>
# include <Inventor/nodes/SoSwitch.h>
# include <Inventor/nodes/SoTransform.h>
#endif

#include "ClipPlaneHandle.h"

#include "AnalysisViewState.h"
#include "ViewProviderAnalysis.h"

#include <App/Application.h>
#include <App/PropertyLinks.h>
#include <Base/Parameter.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/Document.h>
#include <Gui/Inventor/Draggers/SoLinearDragger.h>
#include <Gui/Inventor/Draggers/SoTransformDragger.h>
#include <Gui/View3DInventor.h>
#include <Gui/View3DInventorViewer.h>
#include <Gui/ViewParams.h>
#include <Mod/Fem/App/FemAnalysis.h>

using namespace FemGui;

namespace
{

/// The plane indicator reaches past the model by this fraction of its size.
constexpr double indicatorMargin = 1.05;
/// Fallback indicator half size for an analysis without any geometry.
constexpr double indicatorFallbackSize = 10.0;
/// Rotation snapping of the two angle handles without a configured one.
constexpr double defaultAngleStep = 15.0;
/// Smallest rotation step, a step of 0 would freeze the angle handles.
constexpr double minAngleStep = 0.01;
/// Shorter normals are treated as unusable and replaced by the default one.
constexpr double minNormalLength = 1e-9;
/// Preferences holding the drag steps shared by all clip planes.
constexpr const char* stepGroup = "User parameter:BaseApp/Preferences/Mod/Fem/General";
constexpr const char* offsetStepEntry = "ClipPlaneOffsetStep";
constexpr const char* angleStepEntry = "ClipPlaneAngleStep";
/// Smallest offset step, a step of 0 would freeze the arrow.
constexpr double minOffsetStep = 1e-6;
/// The automatic step splits the plane indicator into this many notches.
constexpr double automaticStepNotches = 20.0;
/// Closed outline of the plane indicator, first corner repeated at the end.
constexpr int outlineVertices = 5;
/// Outline plus the two center lines forming the cross.
constexpr int indicatorVertices = outlineVertices + 4;

SbVec3f toSb(const Base::Vector3d& vec)
{
    return SbVec3f(static_cast<float>(vec.x), static_cast<float>(vec.y), static_cast<float>(vec.z));
}

Base::Vector3d fromSb(const SbVec3f& vec)
{
    return Base::Vector3d(vec[0], vec[1], vec[2]);
}

/**
 * Dragger orientation for a plane normal.
 *
 * The normal points at the half that survives the cut, while the arrow the
 * user pushes into the model points at the half that goes away, so the local
 * z axis of the dragger is the negated normal.
 */
SbRotation draggerRotation(const Base::Vector3d& normal)
{
    return SbRotation(SbVec3f(0, 0, 1), toSb(normal * -1.0));
}

/**
 * Bounding box of one object and its group children.
 *
 * Members are asked individually because the analysis view provider holds no
 * geometry of its own -- and asking it would include the clip handles, which
 * would grow the indicator on every refresh.
 */
void addObjectBoundingBox(
    App::DocumentObject* obj,
    const Gui::View3DInventorViewer* viewer,
    Base::BoundBox3d& box,
    int depth
)
{
    constexpr int maxDepth = 5;
    if (!obj || depth > maxDepth) {
        return;
    }

    if (auto* vp = Gui::Application::Instance->getViewProvider(obj)) {
        Base::BoundBox3d objBox = vp->getBoundingBox(nullptr, nullptr, true, viewer);
        if (objBox.IsValid()) {
            box.Add(objBox);
        }
    }

    if (auto* group = dynamic_cast<App::PropertyLinkList*>(obj->getPropertyByName("Group"))) {
        for (auto* child : group->getValues()) {
            addObjectBoundingBox(child, viewer, box, depth + 1);
        }
    }
}

/// The 3D view an analysis is shown in, preferring the active one.
Gui::View3DInventorViewer* viewerFor(Fem::FemAnalysis* analysis)
{
    if (!analysis || !Gui::Application::Instance) {
        return nullptr;
    }
    auto* guiDoc = Gui::Application::Instance->getDocument(analysis->getDocument());
    if (!guiDoc) {
        return nullptr;
    }
    if (auto* active = dynamic_cast<Gui::View3DInventor*>(guiDoc->getActiveView())) {
        return active->getViewer();
    }
    for (auto* mdi : guiDoc->getMDIViewsOfType(Gui::View3DInventor::getClassTypeId())) {
        if (auto* view = dynamic_cast<Gui::View3DInventor*>(mdi)) {
            return view->getViewer();
        }
    }
    return nullptr;
}

/// Extent of everything the analysis holds, the clip handles excluded.
Base::BoundBox3d modelBoxOf(Fem::FemAnalysis* analysis)
{
    Base::BoundBox3d box;
    if (!analysis || !Gui::Application::Instance) {
        return box;
    }
    // getBoundingBox() needs a viewport to evaluate screen sized nodes
    const Gui::View3DInventorViewer* view = viewerFor(analysis);
    if (!view) {
        return box;
    }
    for (auto* member : analysis->Group.getValues()) {
        addObjectBoundingBox(member, view, box, 0);
    }
    return box;
}

}  // namespace

std::vector<ClipPlaneHandle*> ClipPlaneHandle::s_handles;

std::unique_ptr<ClipPlaneHandle> ClipPlaneHandle::create(
    Fem::FemAnalysis* analysis,
    const std::string& name
)
{
    if (!analysis || name.empty() || !Gui::Application::Instance) {
        return nullptr;
    }
    auto* guiDoc = Gui::Application::Instance->getDocument(analysis->getDocument());
    if (!guiDoc) {
        return nullptr;
    }
    auto* vp = freecad_cast<ViewProviderFemAnalysis*>(guiDoc->getViewProvider(analysis));
    if (!vp) {
        return nullptr;
    }
    SoSeparator* parent = vp->getClipPlaneRoot();
    if (!parent) {
        return nullptr;
    }
    // The handle only ever looks up an existing state from here on
    AnalysisViewState::forAnalysis(analysis);

    std::unique_ptr<ClipPlaneHandle> handle(new ClipPlaneHandle(analysis, name, parent));
    handle->buildSceneGraph();
    handle->adoptPlane();
    return handle;
}

std::string ClipPlaneHandle::addPlane(Fem::FemAnalysis* analysis)
{
    const Base::BoundBox3d box = modelBoxOf(analysis);
    const Base::Vector3d center = box.IsValid() ? box.GetCenter() : Base::Vector3d(0, 0, 0);
    // Normal pointing down, so the upper half of the model is the one cut away
    return addPlane(analysis, center, Base::Vector3d(0, 0, -1));
}

std::string ClipPlaneHandle::addPlane(
    Fem::FemAnalysis* analysis,
    const Base::Vector3d& origin,
    const Base::Vector3d& normal,
    const std::string& scope
)
{
    auto* state = AnalysisViewState::forAnalysis(analysis);
    if (!state) {
        return {};
    }
    ClippingPlane plane;
    plane.Origin = origin;
    plane.Direction = normal.Length() < minNormalLength ? Base::Vector3d(0, 0, -1) : normal;
    plane.Scope = scope;
    // A plane is added to be used, so it cuts right away
    plane.Active = true;

    const std::string name = uniqueName(analysis);
    state->setClipPlane(name, plane);
    return name;
}

std::string ClipPlaneHandle::uniqueName(Fem::FemAnalysis* analysis)
{
    auto* state = AnalysisViewState::find(analysis);

    auto taken = [&](const std::string& candidate) {
        if (state && state->clipPlanes().count(candidate) > 0) {
            return true;
        }
        return std::any_of(s_handles.begin(), s_handles.end(), [&](ClipPlaneHandle* handle) {
            return handle->analysis() == analysis && handle->name() == candidate;
        });
    };

    for (int index = 1;; ++index) {
        std::string candidate = "Clip " + std::to_string(index);
        if (!taken(candidate)) {
            return candidate;
        }
    }
}

double ClipPlaneHandle::offsetStep()
{
    ParameterGrp::handle group = App::GetApplication().GetParameterGroupByPath(stepGroup);
    return group->GetFloat(offsetStepEntry, 0.0);
}

void ClipPlaneHandle::setOffsetStep(double step)
{
    ParameterGrp::handle group = App::GetApplication().GetParameterGroupByPath(stepGroup);
    group->SetFloat(offsetStepEntry, std::max(step, 0.0));
    for (auto* handle : s_handles) {
        handle->updateOffsetStep();
    }
}

double ClipPlaneHandle::appliedOffsetStep() const
{
    return m_dragger ? m_dragger->translationIncrement.getValue() : offsetStep();
}

double ClipPlaneHandle::angleStep()
{
    ParameterGrp::handle group = App::GetApplication().GetParameterGroupByPath(stepGroup);
    const double step = group->GetFloat(angleStepEntry, defaultAngleStep);
    return step >= minAngleStep ? step : defaultAngleStep;
}

void ClipPlaneHandle::setAngleStep(double degree)
{
    ParameterGrp::handle group = App::GetApplication().GetParameterGroupByPath(stepGroup);
    group->SetFloat(angleStepEntry, std::max(degree, minAngleStep));
    for (auto* handle : s_handles) {
        handle->updateAngleStep();
    }
}

ClipPlaneHandle::ClipPlaneHandle(Fem::FemAnalysis* analysis, std::string name, SoSeparator* parent)
    : m_analysis(analysis)
    , m_name(std::move(name))
    , m_parent(parent)
{
    s_handles.push_back(this);
}

ClipPlaneHandle::~ClipPlaneHandle()
{
    detach();
    s_handles.erase(std::remove(s_handles.begin(), s_handles.end(), this), s_handles.end());
}

void ClipPlaneHandle::buildSceneGraph()
{
    m_dragger = new Gui::SoTransformDragger();
    m_dragger->setAxisColors(
        Gui::ViewParams::instance()->getAxisXColor(),
        Gui::ViewParams::instance()->getAxisYColor(),
        Gui::ViewParams::instance()->getAxisZColor()
    );
    m_dragger->draggerSize.setValue(static_cast<float>(Gui::ViewParams::instance()->getDraggerScale()));
    updateAngleStep();

    // A plane needs to move along its normal and to be tilted. The in-plane
    // slider shifts the rotation center without changing the plane, spinning
    // around the normal changes nothing at all.
    m_dragger->hideTranslationX();
    m_dragger->hideTranslationY();
    m_dragger->showTranslationZ();
    m_dragger->showPlanarTranslationXY();
    m_dragger->hidePlanarTranslationYZ();
    m_dragger->hidePlanarTranslationZX();
    m_dragger->showRotationX();
    m_dragger->showRotationY();
    m_dragger->hideRotationZ();
    hideArrowLabel();

    m_dragger->addStartCallback(dragStartCB, this);
    m_dragger->addFinishCallback(dragFinishCB, this);

    // The indicator only follows position and orientation, never the screen
    // size scaling of the dragger, so it stays model sized.
    m_indicatorTransform = new SoTransform();
    m_indicatorTransform->setName("FemClipPlaneTransform");
    m_indicatorTransform->translation.connectFrom(&m_dragger->translation);
    m_indicatorTransform->rotation.connectFrom(&m_dragger->rotation);

    m_indicatorCoords = new SoCoordinate3();
    m_indicatorCoords->setName("FemClipPlaneCoords");

    auto* indicator = new SoSeparator();
    auto* pick = new SoPickStyle();
    pick->style = SoPickStyle::UNPICKABLE;
    indicator->addChild(pick);
    indicator->addChild(m_indicatorTransform);

    auto* lightModel = new SoLightModel();
    lightModel->model = SoLightModel::BASE_COLOR;
    indicator->addChild(lightModel);
    indicator->addChild(m_indicatorCoords);

    // Lines only: a filled quad hides the very geometry the plane cuts through
    auto* material = new SoMaterial();
    material->diffuseColor.setValue(0.35F, 0.55F, 0.9F);
    material->transparency.setValue(0.3F);
    indicator->addChild(material);
    auto* style = new SoDrawStyle();
    style->lineWidth.setValue(2.0F);
    indicator->addChild(style);
    auto* lines = new SoLineSet();
    const int32_t lineSizes[] = {outlineVertices, 2, 2};
    lines->numVertices.setNum(3);
    lines->numVertices.setValues(0, 3, lineSizes);
    indicator->addChild(lines);

    auto* content = new SoSeparator();
    content->addChild(m_dragger);
    content->addChild(indicator);

    m_switch = new SoSwitch();
    m_switch->setName("FemClipHandle");
    m_switch->addChild(content);
    m_switch->whichChild = SO_SWITCH_ALL;

    m_parent->addChild(m_switch);
}

void ClipPlaneHandle::hideArrowLabel()
{
    // The offset readout of the arrow is meaningless for a plane that is
    // positioned visually, and it is the only label left on the dragger.
    auto* container = static_cast<Gui::SoLinearDraggerContainer*>(
        m_dragger->getPart("zTranslatorDragger", TRUE)
    );
    if (container && container->getDragger()) {
        container->getDragger()->labelVisible.setValue(FALSE);
    }
}

void ClipPlaneHandle::adoptPlane()
{
    // Show where the plane already is. Nothing is written back: the plane was
    // put in the view state before this handle was asked for, and writing
    // during construction would notify the very code that is constructing us.
    if (auto* state = viewState()) {
        const auto& planes = state->clipPlanes();
        auto it = planes.find(m_name);
        if (it != planes.end()) {
            m_active = it->second.Active;
            m_scope = it->second.Scope;
            m_dragger->translation.setValue(toSb(it->second.Origin));
            Base::Vector3d dir = it->second.Direction;
            if (dir.Length() > minNormalLength) {
                dir.Normalize();
                m_dragger->rotation.setValue(draggerRotation(dir));
            }
            m_dragger->clearIncrementCounts();
        }
    }

    updateIndicatorSize();
    setUpViewportScale();
}

void ClipPlaneHandle::detach()
{
    if (m_removed) {
        return;
    }
    m_removed = true;

    if (m_dragger) {
        m_dragger->removeStartCallback(dragStartCB, this);
        m_dragger->removeFinishCallback(dragFinishCB, this);
    }
    if (m_indicatorTransform) {
        m_indicatorTransform->translation.disconnect();
        m_indicatorTransform->rotation.disconnect();
    }
    if (m_parent && m_switch) {
        m_parent->removeChild(m_switch);
    }

    m_indicatorCoords = nullptr;
    m_indicatorTransform = nullptr;
    m_dragger = nullptr;
    m_switch = nullptr;
    m_parent = nullptr;
}

Fem::FemAnalysis* ClipPlaneHandle::analysis() const
{
    if (m_removed) {
        return nullptr;
    }
    return m_analysis.get<Fem::FemAnalysis>();
}

AnalysisViewState* ClipPlaneHandle::viewState() const
{
    // find() rather than forAnalysis(): a handle may still be dropped while its
    // analysis is being deleted, and resurrecting the state then would register
    // it under a dying object.
    return AnalysisViewState::find(analysis());
}

Gui::View3DInventorViewer* ClipPlaneHandle::viewer() const
{
    return viewerFor(analysis());
}

void ClipPlaneHandle::setActive(bool on)
{
    if (m_removed || m_active == on) {
        return;
    }
    m_active = on;
    // Switched off the plane stays listed, only marked as cutting nothing, so
    // the row and this handle survive to switch it back on where it was left.
    applyToViewState();
}

void ClipPlaneHandle::setScope(const std::string& scope)
{
    if (m_removed || m_scope == scope) {
        return;
    }
    m_scope = scope;
    applyToViewState();
}

void ClipPlaneHandle::setWidgetVisible(bool on)
{
    m_widgetVisible = on;
    if (m_switch) {
        m_switch->whichChild = on ? SO_SWITCH_ALL : SO_SWITCH_NONE;
    }
}

Base::Vector3d ClipPlaneHandle::origin() const
{
    if (!m_dragger) {
        return Base::Vector3d();
    }
    return fromSb(m_dragger->translation.getValue());
}

Base::Vector3d ClipPlaneHandle::normal() const
{
    if (!m_dragger) {
        return Base::Vector3d(0, 0, 1);
    }
    SbVec3f dir(0, 0, 1);
    m_dragger->rotation.getValue().multVec(dir, dir);
    Base::Vector3d result = fromSb(dir) * -1.0;
    if (result.Length() < minNormalLength) {
        return Base::Vector3d(0, 0, 1);
    }
    result.Normalize();
    return result;
}

void ClipPlaneHandle::setPlane(const Base::Vector3d& origin, const Base::Vector3d& normal)
{
    if (!m_dragger) {
        return;
    }
    Base::Vector3d dir = normal;
    if (dir.Length() < minNormalLength) {
        dir = Base::Vector3d(0, 0, 1);
    }
    dir.Normalize();

    m_dragger->translation.setValue(toSb(origin));
    m_dragger->rotation.setValue(draggerRotation(dir));
    m_dragger->clearIncrementCounts();

    applyToViewState();
}

void ClipPlaneHandle::refresh()
{
    // Our own writes come straight back to us through the view state, and
    // re-reading them would only cost a model bounding box per drag.
    if (m_removed || m_applying) {
        return;
    }

    // The view state is the truth for a plane: it survives a reload, and other
    // code may have moved or switched the plane off behind our back.
    if (auto* state = viewState()) {
        const auto& planes = state->clipPlanes();
        auto it = planes.find(m_name);
        if (it != planes.end()) {
            m_active = it->second.Active;
            m_scope = it->second.Scope;
            m_dragger->translation.setValue(toSb(it->second.Origin));
            Base::Vector3d dir = it->second.Direction;
            if (dir.Length() > minNormalLength) {
                dir.Normalize();
                m_dragger->rotation.setValue(draggerRotation(dir));
            }
        }
    }

    updateIndicatorSize();
    setUpViewportScale();
}

void ClipPlaneHandle::applyToViewState()
{
    auto* state = viewState();
    if (!state) {
        return;
    }
    ClippingPlane plane;
    plane.Origin = origin();
    plane.Direction = normal();
    plane.Scope = m_scope;
    plane.Active = m_active;

    Base::StateLocker lock(m_applying, true);
    state->setClipPlane(m_name, plane);
}

Base::BoundBox3d ClipPlaneHandle::modelBoundingBox() const
{
    return modelBoxOf(analysis());
}

void ClipPlaneHandle::updateIndicatorSize()
{
    if (!m_indicatorCoords) {
        return;
    }

    Base::BoundBox3d box = modelBoundingBox();
    double half = indicatorFallbackSize;
    if (box.IsValid()) {
        // Half the diagonal covers any section through the model, whatever the
        // plane orientation is.
        const double diagonal = Base::Vector3d(box.LengthX(), box.LengthY(), box.LengthZ()).Length();
        if (diagonal > minNormalLength) {
            half = 0.5 * diagonal * indicatorMargin;
        }
    }

    const auto size = static_cast<float>(half);
    const SbVec3f points[indicatorVertices] = {
        SbVec3f(-size, -size, 0.0F),
        SbVec3f(size, -size, 0.0F),
        SbVec3f(size, size, 0.0F),
        SbVec3f(-size, size, 0.0F),
        SbVec3f(-size, -size, 0.0F),
        SbVec3f(-size, 0.0F, 0.0F),
        SbVec3f(size, 0.0F, 0.0F),
        SbVec3f(0.0F, -size, 0.0F),
        SbVec3f(0.0F, size, 0.0F),
    };
    m_indicatorCoords->point.setNum(indicatorVertices);
    m_indicatorCoords->point.setValues(0, indicatorVertices, points);

    m_indicatorHalfSize = half;
    updateOffsetStep();
}

void ClipPlaneHandle::updateOffsetStep()
{
    if (!m_dragger) {
        return;
    }
    double step = offsetStep();
    if (step <= 0.0) {
        // Without a configured step, stay in the order of magnitude of the
        // model so the arrow is usable on a bolt and on a bridge alike.
        step = m_indicatorHalfSize / automaticStepNotches;
    }
    m_dragger->translationIncrement.setValue(std::max(step, minOffsetStep));
}

void ClipPlaneHandle::updateAngleStep()
{
    if (m_dragger) {
        m_dragger->rotationIncrement.setValue(Base::toRadians<double>(angleStep()));
    }
}

void ClipPlaneHandle::setUpViewportScale()
{
    if (!m_dragger) {
        return;
    }
    auto* view = viewer();
    if (!view || !view->getSoRenderManager()) {
        return;
    }
    if (auto* camera = view->getSoRenderManager()->getCamera()) {
        m_dragger->setUpAutoScale(camera);
    }
}

void ClipPlaneHandle::dragStartCB(void* data, SoDragger*)
{
    auto* self = static_cast<ClipPlaneHandle*>(data);
    if (!self || !self->m_dragger) {
        return;
    }
    self->m_dragger->clearIncrementCounts();
}

void ClipPlaneHandle::dragFinishCB(void* data, SoDragger*)
{
    auto* self = static_cast<ClipPlaneHandle*>(data);
    if (!self || !self->m_dragger) {
        return;
    }
    self->m_dragger->clearIncrementCounts();
    self->applyToViewState();
}
