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
# include <functional>
# include <set>
# include <sstream>
# include <utility>
#endif

#include "AnalysisViewState.h"
#include "Classification.h"
#include "FemPerfLog.h"
#include "ViewProviderAnalysis.h"

#include <App/DocumentObject.h>
#include <App/PropertyLinks.h>
#include <Base/Console.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Mod/Fem/App/FemGeometry.h>
#include <Base/Interpreter.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/Document.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemAnalysisImport.h>
#include <Mod/Fem/App/FemGeometry.h>
#include <Mod/Fem/App/FemMeshShapeGroup.h>
#include <Mod/Fem/App/FemTopology.h>
#include <Mod/Fem/App/FemTools.h>

using namespace FemGui;

namespace
{

Gui::ViewProviderDocumentObject* viewProviderOf(App::DocumentObject* obj)
{
    if (!obj || !Gui::Application::Instance) {
        return nullptr;
    }
    auto* guiDoc = Gui::Application::Instance->getDocument(obj->getDocument());
    if (!guiDoc) {
        return nullptr;
    }
    return freecad_cast<Gui::ViewProviderDocumentObject*>(guiDoc->getViewProvider(obj));
}

bool isShown(App::DocumentObject* obj)
{
    auto* vp = viewProviderOf(obj);
    return vp && vp->Visibility.getValue();
}

void setShown(App::DocumentObject* obj, bool shown)
{
    if (auto* vp = viewProviderOf(obj)) {
        if (vp->Visibility.getValue() != shown) {
            vp->Visibility.setValue(shown);
        }
    }
}

}  // namespace

void FemGui::setStageMask(Gui::ViewProviderDocumentObject& vp, const char* mode)
{
    vp.setDisplayMaskMode(mode);
    if (!vp.Visibility.getValue()) {
        vp.Gui::ViewProvider::hide();
    }
}

App::DocumentObject* FemGui::editSubjectFor(App::DocumentObject* edited)
{
    if (!edited || !edited->isDerivedFrom<Fem::FemGeometry>()) {
        return nullptr;
    }
    // Elements are named against the geometry this step was handed, so that is
    // the geometry the panel needs on show. Without such a property the step
    // makes geometry rather than altering it, and it is its own subject.
    if (!edited->getPropertyByName("Elements")) {
        return edited;
    }
    if (auto* base = freecad_cast<App::PropertyLink*>(edited->getPropertyByName("Base"))) {
        if (auto* input = base->getValue()) {
            return input;
        }
    }
    // A step that wants an input and has none: nothing to show it on. Its own
    // shape is not the answer, that is what it would have produced from the
    // input it is missing.
    return nullptr;
}

const std::vector<ColorMode>& FemGui::allColorModes()
{
    static const std::vector<ColorMode> modes {
        ColorMode::Subelement,
        ColorMode::Component,
        ColorMode::Material,
        ColorMode::CellType,
    };
    return modes;
}

bool FemGui::colorModeAppliesTo(ColorMode mode, ActiveStage stage)
{
    return mode != ColorMode::CellType || stage == ActiveStage::Mesh;
}

const char* FemGui::colorModeName(ColorMode mode)
{
    switch (mode) {
        case ColorMode::Subelement:
            return "Subelement";
        case ColorMode::Component:
            return "Component";
        case ColorMode::Material:
            return "Material";
        case ColorMode::CellType:
            return "CellType";
    }
    return "Subelement";
}

ColorMode FemGui::colorModeFromName(const std::string& name)
{
    for (ColorMode mode : allColorModes()) {
        if (name == colorModeName(mode)) {
            return mode;
        }
    }
    return ColorMode::Subelement;
}

const char* FemGui::activeStageName(ActiveStage stage)
{
    switch (stage) {
        case ActiveStage::Geometry:
            return "Geometry";
        case ActiveStage::Mesh:
            return "Mesh";
        case ActiveStage::Result:
            return "Result";
        case ActiveStage::NoStage:
            return "NoStage";
    }
    return "Geometry";
}

ActiveStage FemGui::activeStageFromName(const std::string& name)
{
    if (name == "Mesh") {
        return ActiveStage::Mesh;
    }
    if (name == "Result") {
        return ActiveStage::Result;
    }
    if (name == "NoStage") {
        return ActiveStage::NoStage;
    }
    return ActiveStage::Geometry;
}

std::map<Fem::FemAnalysis*, std::unique_ptr<AnalysisViewState>> AnalysisViewState::s_states;

AnalysisViewState::AnalysisViewState(Fem::FemAnalysis* analysis)
    : m_analysis(analysis)
{
    m_colorMode[ActiveStage::Geometry] = ColorMode::Subelement;
    m_colorMode[ActiveStage::Mesh] = ColorMode::Subelement;
    m_colorMode[ActiveStage::Result] = ColorMode::Subelement;
    m_colorMode[ActiveStage::NoStage] = ColorMode::Subelement;
}

AnalysisViewState::~AnalysisViewState() = default;

AnalysisViewState* AnalysisViewState::forAnalysis(Fem::FemAnalysis* analysis)
{
    if (!analysis) {
        return nullptr;
    }
    auto it = s_states.find(analysis);
    if (it != s_states.end()) {
        return it->second.get();
    }
    auto state = std::make_unique<AnalysisViewState>(analysis);
    auto* raw = state.get();

    // Restore persisted subset from the view provider if available
    if (Gui::Application::Instance) {
        auto* guiDoc = Gui::Application::Instance->getDocument(analysis->getDocument());
        if (guiDoc) {
            auto* vp = freecad_cast<ViewProviderFemAnalysis*>(guiDoc->getViewProvider(analysis));
            if (vp) {
                raw->loadFromViewProvider(vp);
            }
        }
    }

    s_states.emplace(analysis, std::move(state));
    return raw;
}

AnalysisViewState* AnalysisViewState::find(Fem::FemAnalysis* analysis)
{
    if (!analysis) {
        return nullptr;
    }
    auto it = s_states.find(analysis);
    return it != s_states.end() ? it->second.get() : nullptr;
}

void AnalysisViewState::destroyForAnalysis(Fem::FemAnalysis* analysis)
{
    s_states.erase(analysis);
}

bool AnalysisViewState::isAlive(const AnalysisViewState* state)
{
    if (!state) {
        return false;
    }
    for (const auto& entry : s_states) {
        if (entry.second.get() == state) {
            return true;
        }
    }
    return false;
}

void AnalysisViewState::beginUpdate()
{
    ++m_batchDepth;
}

void AnalysisViewState::endUpdate()
{
    if (m_batchDepth > 0) {
        --m_batchDepth;
    }
    if (m_batchDepth > 0) {
        return;
    }
    if (m_pendingPersist) {
        m_pendingPersist = false;
        persist();
    }
    if (m_pendingNotify) {
        m_pendingNotify = false;
        FEM_PERF_SCOPE("viewstate.notify");
        m_changed();
    }
}

void AnalysisViewState::notifyChanged()
{
    if (m_batchDepth > 0) {
        m_pendingNotify = true;
        return;
    }
    FEM_PERF_SCOPE("viewstate.notify");
    m_changed();
}

void AnalysisViewState::chainChanged()
{
    notifyChanged();
}

AnalysisViewState::Connection AnalysisViewState::connectChanged(Slot slot)
{
    return m_changed.connect(std::move(slot));
}

ActiveStage AnalysisViewState::activeStage() const
{
    m_stage = readStage();
    return m_stage;
}

ActiveStage AnalysisViewState::readStage() const
{
    // Whichever group is on show names the stage, geometry asked first so that
    // a document written before the stage was kept here, where both groups are
    // on, comes back in the stage it always came back in.
    if (isShown(findGeometry())) {
        return ActiveStage::Geometry;
    }
    if (isShown(findMeshGroup())) {
        return ActiveStage::Mesh;
    }
    // A stage whose group the analysis does not build cannot be read off
    // anything, so there the last stage asked for stands. That is how an
    // analysis which only places others has a stage at all, and how the mesh
    // stage survives in one that places meshes but has not meshed its own.
    const bool missing = (m_stage == ActiveStage::Geometry) ? !findGeometry() : !findMeshGroup();
    if (missing
        && (m_stage == ActiveStage::Geometry || m_stage == ActiveStage::Mesh)) {
        return m_stage;
    }
    return ActiveStage::NoStage;
}

void AnalysisViewState::applyStageToGroups()
{
    Base::StateLocker lock(m_writingStage);
    setShown(findGeometry(), m_stage == ActiveStage::Geometry);
    setShown(findMeshGroup(), m_stage == ActiveStage::Mesh);
}

void AnalysisViewState::setActiveStage(ActiveStage stage)
{
    if (activeStage() == stage) {
        return;
    }
    m_stage = stage;
    applyStageToGroups();
    notifyChanged();
}

void AnalysisViewState::stageVisibilityChanged(ActiveStage owner)
{
    if (m_writingStage) {
        return;
    }
    const ActiveStage before = m_stage;
    const bool shown = (owner == ActiveStage::Mesh) ? isShown(findMeshGroup())
                                                    : isShown(findGeometry());
    if (shown) {
        // Showing a group is choosing its stage, and the two are exclusive, so
        // the other one steps aside rather than being drawn over it.
        m_stage = owner;
        applyStageToGroups();
    }
    else {
        m_stage = readStage();
    }
    if (m_stage != before) {
        notifyChanged();
    }
}

namespace
{

/**
 * What an object being edited needs the view to show.
 *
 * Decided here, once, from what the object is. Every task panel in the
 * workbench arrives through the same two signals, so this is the only place
 * that has to know - and a panel that used to switch visibilities on its own
 * way in cannot disagree with one that did it differently.
 */
EditIntent intentFor(const App::DocumentObject* obj)
{
    if (!obj) {
        return EditIntent::None;
    }
    // A geometry step is edited on the geometry it builds from.
    if (obj->isDerivedFrom<Fem::FemGeometry>()) {
        return EditIntent::Geometry;
    }
    // And so is anything holding references into it - constraints, materials,
    // mesh refinements, equations. What they have in common is the References
    // property, which is what says the panel will ask for something to be
    // picked on the shape.
    if (const_cast<App::DocumentObject*>(obj)->getPropertyByName("References")) {
        return EditIntent::Geometry;
    }
    return EditIntent::None;
}

/// The analysis @a obj belongs to, directly or through a group inside it.
Fem::FemAnalysis* analysisOf(App::DocumentObject* obj)
{
    if (!obj) {
        return nullptr;
    }
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
    return nullptr;
}

/**
 * Opens and closes the edit scope of whatever the user is editing.
 *
 * Every view provider goes into edit mode through these two signals, whichever
 * language it is written in and whether or not it calls up to its base, which
 * is what makes this the one place the workbench needs.
 */
class EditScopeObserver
{
public:
    void connect()
    {
        if (m_connected || !Gui::Application::Instance) {
            return;
        }
        m_inEdit = Gui::Application::Instance->signalInEdit.connect(
            [](const Gui::ViewProviderDocumentObject& vp) {
                auto* obj = const_cast<Gui::ViewProviderDocumentObject&>(vp).getObject();
                if (auto* analysis = analysisOf(obj)) {
                    if (auto* state = AnalysisViewState::find(analysis)) {
                        state->beginEdit(obj, intentFor(obj));
                    }
                }
            }
        );
        m_resetEdit = Gui::Application::Instance->signalResetEdit.connect(
            [](const Gui::ViewProviderDocumentObject& vp) {
                auto* obj = const_cast<Gui::ViewProviderDocumentObject&>(vp).getObject();
                if (auto* analysis = analysisOf(obj)) {
                    if (auto* state = AnalysisViewState::find(analysis)) {
                        state->endEdit(obj);
                    }
                }
            }
        );
        m_connected = true;
    }

private:
    bool m_connected {false};
    fastsignals::scoped_connection m_inEdit;
    fastsignals::scoped_connection m_resetEdit;
};

EditScopeObserver& editScopeObserver()
{
    static EditScopeObserver observer;
    return observer;
}

}  // namespace

void FemGui::observeEditScopes()
{
    editScopeObserver().connect();
}

void AnalysisViewState::beginEdit(App::DocumentObject* edited, EditIntent intent)
{
    if (!edited) {
        return;
    }
    if (m_editedObject && m_editedObject != edited) {
        // FreeCAD edits one object at a time, so this is a scope somebody
        // forgot to close rather than a nested edit. Closing it here leaves the
        // view where that edit found it, which is what its own endEdit would
        // have done.
        Base::Console().warning(
            "FemGui: edit scope of '%s' was still open when '%s' opened one\n",
            m_editedObject->getNameInDocument() ? m_editedObject->getNameInDocument() : "?",
            edited->getNameInDocument() ? edited->getNameInDocument() : "?"
        );
        endEdit(m_editedObject);
    }

    m_editedObject = edited;
    m_editSubject = editSubjectFor(edited);
    m_editIntent = intent;
    m_editStageBefore = activeStage();
    m_editStageApplied = ActiveStage::NoStage;

    const ActiveStage wanted = (intent == EditIntent::Geometry)  ? ActiveStage::Geometry
        : (intent == EditIntent::Mesh)                           ? ActiveStage::Mesh
                                                                 : m_editStageBefore;
    if (intent != EditIntent::None && wanted != m_editStageBefore) {
        m_editStageApplied = wanted;
        setActiveStage(wanted);
    }
    else {
        notifyChanged();
    }
}

void AnalysisViewState::endEdit(App::DocumentObject* edited)
{
    // An unsetEdit for an object that never opened a scope, or a second one for
    // the same object, has nothing to put back.
    if (!edited || m_editedObject != edited) {
        return;
    }

    const ActiveStage applied = m_editStageApplied;
    const ActiveStage before = m_editStageBefore;

    m_editedObject = nullptr;
    m_editSubject = nullptr;
    m_editIntent = EditIntent::None;
    m_editStageApplied = ActiveStage::NoStage;

    // Only a stage still standing as this scope left it goes back. One the user
    // switched to while the panel was open is a choice, not scenery.
    if (applied != ActiveStage::NoStage && activeStage() == applied) {
        setActiveStage(before);
    }
    else {
        notifyChanged();
    }
}

void AnalysisViewState::setDimensionMode(DimensionMode mode)
{
    if (m_dimensionMode == mode) {
        return;
    }
    m_dimensionMode = mode;
    notifyChanged();
}

void AnalysisViewState::setShowConstruction(bool on)
{
    if (m_showConstruction == on) {
        return;
    }
    m_showConstruction = on;
    notifyChanged();
}

void AnalysisViewState::setWireframe(bool on)
{
    if (m_wireframe == on) {
        return;
    }
    m_wireframe = on;
    notifyChanged();
}

void AnalysisViewState::setOverlay(bool on)
{
    if (m_overlay == on) {
        return;
    }
    m_overlay = on;
    notifyChanged();
}

ColorMode AnalysisViewState::colorMode(ActiveStage stage) const
{
    auto it = m_colorMode.find(stage);
    if (it == m_colorMode.end()) {
        return ColorMode::Subelement;
    }
    return it->second;
}

void AnalysisViewState::setColorMode(ActiveStage stage, ColorMode mode)
{
    if (!colorModeAppliesTo(mode, stage)) {
        mode = ColorMode::Subelement;
    }
    if (colorMode(stage) == mode) {
        return;
    }
    m_colorMode[stage] = mode;
    notifyChanged();
}

void AnalysisViewState::setElementHidden(const std::string& element, bool hidden)
{
    bool changed = false;
    if (hidden) {
        changed = m_hiddenElements.insert(element).second;
    }
    else {
        changed = m_hiddenElements.erase(element) > 0;
    }
    if (changed) {
        persist();
        notifyChanged();
    }
}

void AnalysisViewState::setHiddenElements(const std::set<std::string>& elements)
{
    if (m_hiddenElements == elements) {
        return;
    }
    m_hiddenElements = elements;
    persist();
    notifyChanged();
}

bool AnalysisViewState::isElementHidden(const std::string& element) const
{
    return m_hiddenElements.count(element) > 0;
}

void AnalysisViewState::setCellTypeHidden(const std::string& cellType, bool hidden)
{
    bool changed = false;
    if (hidden) {
        changed = m_hiddenCellTypes.insert(cellType).second;
    }
    else {
        changed = m_hiddenCellTypes.erase(cellType) > 0;
    }
    if (changed) {
        notifyChanged();
    }
}

bool AnalysisViewState::isCellTypeHidden(const std::string& cellType) const
{
    return m_hiddenCellTypes.count(cellType) > 0;
}

void AnalysisViewState::setClipPlane(const std::string& name, const ClippingPlane& plane)
{
    // A degenerate normal reaches VTK as a zero length plane normal, which
    // clips everything or nothing depending on the filter.
    ClippingPlane clip = plane;
    if (clip.Direction.Length() < 1e-9) {
        Base::Console().warning(
            "FEM view state: clip plane '%s' ignored, its normal is degenerate\n",
            name.c_str()
        );
        return;
    }
    clip.Direction.Normalize();

    auto it = m_clipPlanes.find(name);
    if (it != m_clipPlanes.end() && it->second == clip) {
        return;
    }
    m_clipPlanes[name] = clip;
    persist();
    notifyChanged();
}

void AnalysisViewState::removeClipPlane(const std::string& name)
{
    if (m_clipPlanes.erase(name) > 0) {
        persist();
        notifyChanged();
    }
}

void AnalysisViewState::clearClipPlanes()
{
    if (m_clipPlanes.empty()) {
        return;
    }
    m_clipPlanes.clear();
    persist();
    notifyChanged();
}

std::map<std::string, ClippingPlane> AnalysisViewState::activeClipPlanes() const
{
    std::map<std::string, ClippingPlane> active;
    for (const auto& entry : m_clipPlanes) {
        if (entry.second.Active) {
            active.emplace(entry);
        }
    }
    return active;
}

void AnalysisViewState::setUnderAchievedElements(std::map<std::string, int> elements)
{
    m_underAchieved = std::move(elements);
}

Fem::FemGeometry* AnalysisViewState::findGeometry() const
{
    if (!m_analysis) {
        return nullptr;
    }
    for (auto* obj : m_analysis->Group.getValues()) {
        if (auto* geo = Base::freecad_cast<Fem::FemGeometry*>(obj)) {
            return geo;
        }
    }
    return nullptr;
}

Fem::FemMeshShapeGroup* AnalysisViewState::findMeshGroup() const
{
    if (!m_analysis) {
        return nullptr;
    }
    for (auto* obj : m_analysis->Group.getValues()) {
        if (auto* mesh = Base::freecad_cast<Fem::FemMeshShapeGroup*>(obj)) {
            return mesh;
        }
    }
    return nullptr;
}

std::size_t AnalysisViewState::importRevision() const
{
    std::size_t hash = 0;
    auto mix = [&hash](std::size_t value) {
        hash ^= value + 0x9e3779b9 + (hash << 6) + (hash >> 2);
    };

    std::vector<const Fem::FemAnalysisImport*> chain;
    std::function<void(const Fem::FemAnalysis*)> walk = [&](const Fem::FemAnalysis* analysis) {
        for (auto* imp : Fem::Tools::analysisImports(analysis)) {
            if (std::ranges::find(chain, imp) != chain.end()) {
                continue;
            }
            const char* name = imp->getNameInDocument();
            mix(std::hash<std::string> {}(name ? name : ""));
            if (auto* geom = imp->sourceGeometry()) {
                mix(geom->revision());
            }
            for (long component : imp->SuppressedComponents.getValues()) {
                mix(static_cast<std::size_t>(component));
            }
            if (auto* src = Base::freecad_cast<Fem::FemAnalysis*>(imp->Analysis.getValue())) {
                chain.push_back(imp);
                walk(src);
                chain.pop_back();
            }
        }
    };
    walk(m_analysis);
    return hash;
}

const Classification* AnalysisViewState::classification(vtkUnstructuredGrid* meshGrid)
{
    const ColorMode mode = colorMode();
    const ActiveStage stage = activeStage();

    // Categories are keyed by the toplevel element names of the geometry, so a
    // geometry that gained or lost elements outdates all of them, and an element
    // with no category falls back to the first one. Checking the revision here
    // rather than having whoever changed the geometry invalidate keeps the answer
    // right no matter who asks first: the view panel observes the document before
    // the view providers do, so invalidating from a view provider would still
    // hand the panel the previous set.
    auto* geometry = findGeometry();
    const std::size_t revision = geometry ? geometry->revision() : 0;
    if (m_classificationRevision != revision) {
        m_classifications.clear();
        m_paletteOrder.clear();
        m_classificationRevision = revision;
    }

    // The placed instances contribute categories of their own, so an import
    // coming, going or changing what it shows outdates them the same way a
    // change of the native geometry does.
    const std::size_t importRevision = this->importRevision();
    if (m_classificationImportRevision != importRevision) {
        m_classifications.clear();
        m_paletteOrder.clear();
        m_classificationImportRevision = importRevision;
    }

    // A remeshed group renames what the Mesh stage colours by. The revision is
    // the number of the last recompute and reading it costs nothing, so it is
    // compared whichever stage is up. A child that only moved republishes the
    // mesh without touching it, and the classification survives the move.
    auto* meshGroup = findMeshGroup();
    if (meshGroup) {
        const std::size_t meshRevision = meshGroup->topologyRevision();
        if (m_classificationMeshRevision != meshRevision) {
            m_classifications.clear();
            m_paletteOrder.clear();
            m_classificationMeshRevision = meshRevision;
        }
    }

    auto& entry = m_classifications[{mode, stage, meshGrid}];
    if (!entry) {
        const auto source = m_meshGrids.find(meshGrid);
        const bool useMesh = (stage == ActiveStage::Mesh && meshGroup);
        const auto& order = paletteOrder(mode, useMesh);
        entry = Classification::create(
            mode,
            m_analysis,
            geometry,
            meshGrid,
            source != m_meshGrids.end() ? source->second : GridSource {},
            useMesh ? static_cast<const Fem::AnalysisTopology*>(meshGroup) : nullptr,
            &order
        );
    }
    return entry.get();
}

const std::map<std::string, int>& AnalysisViewState::paletteOrder(ColorMode mode, bool withMesh)
{
    const auto cacheKey = std::make_pair(mode, withMesh);
    auto it = m_paletteOrder.find(cacheKey);
    if (it == m_paletteOrder.end()) {
        rebuildPaletteOrder(mode, withMesh);
        it = m_paletteOrder.find(cacheKey);
    }
    return it->second;
}

void AnalysisViewState::rebuildPaletteOrder(ColorMode mode, bool withMesh)
{
    std::map<std::string, int> order;
    auto* geometry = findGeometry();
    // The Geometry stage colours geometry names only. Its shorter map is a
    // prefix of the one the Mesh stage gets, which is what keeps a name on the
    // same colour across the switch.
    auto* meshGroup = withMesh ? findMeshGroup() : nullptr;

    auto assign = [&order](const std::string& key) {
        if (!order.count(key)) {
            order[key] = static_cast<int>(order.size());
        }
    };

    switch (mode) {
        case ColorMode::Component: {
            if (geometry) {
                const auto n = geometry->componentCount();
                for (Fem::componentIdType i = 0; i < n; ++i) {
                    assign("Component" + std::to_string(i + 1));
                }
            }
            for (const auto& [component, elements] : Fem::Tools::importedComponents(m_analysis)) {
                (void)elements;
                assign(component);
            }
            // A mesh that fuses components has fewer of them than the geometry
            // and so adds nothing here; one that splits them adds the surplus.
            if (meshGroup) {
                const auto n = meshGroup->componentCount();
                for (Fem::componentIdType i = 0; i < n; ++i) {
                    assign("Component" + std::to_string(i + 1));
                }
            }
            if (withMesh) {
                for (const auto& [component, elements] :
                     Fem::Tools::importedMeshComponents(m_analysis)) {
                    (void)elements;
                    assign(component);
                }
            }
            break;
        }
        case ColorMode::Subelement: {
            // Sorted, so that the numbering follows the key set rather than the
            // order it was gathered in. Geometry names are numbered on their own
            // first: a mesh-only catch-all sorting before Solid1 would otherwise
            // push it onto another colour than the Geometry stage gave it.
            std::set<std::string> geometryKeys;
            if (geometry) {
                const auto n = geometry->componentCount();
                for (Fem::componentIdType i = 0; i < n; ++i) {
                    for (const auto& name : geometry->toplevelElements(i)) {
                        geometryKeys.insert(name);
                    }
                }
            }
            for (const auto& path : Fem::Tools::importedToplevelElements(m_analysis)) {
                geometryKeys.insert(path);
            }
            for (const auto& key : geometryKeys) {
                assign(key);
            }

            std::set<std::string> meshKeys;
            if (meshGroup) {
                const auto n = meshGroup->componentCount();
                for (Fem::componentIdType i = 0; i < n; ++i) {
                    for (const auto& name : meshGroup->toplevelElements(i)) {
                        meshKeys.insert(name);
                    }
                }
            }
            if (withMesh) {
                for (const auto& [component, elements] :
                     Fem::Tools::importedMeshComponents(m_analysis)) {
                    (void)component;
                    meshKeys.insert(elements.begin(), elements.end());
                }
            }
            for (const auto& key : meshKeys) {
                assign(key);
            }
            break;
        }
        case ColorMode::Material:
        case ColorMode::CellType:
        default:
            // Material sorts its own keys; CellType uses cellTypeOrder(). An
            // empty map makes ensureCategory fall back to the local index.
            break;
    }

    m_paletteOrder[{mode, withMesh}] = std::move(order);
}

void AnalysisViewState::registerMeshGrid(vtkUnstructuredGrid* meshGrid, const GridSource& source)
{
    if (meshGrid) {
        m_meshGrids[meshGrid] = source;
        // Force a fresh classification so entity→toplevel mapping uses current geometry.
        forgetClassificationsOf(meshGrid);
    }
}

void AnalysisViewState::unregisterMeshGrid(vtkUnstructuredGrid* meshGrid)
{
    m_meshGrids.erase(meshGrid);
    forgetClassificationsOf(meshGrid);
}

void AnalysisViewState::forgetClassificationsOf(vtkUnstructuredGrid* meshGrid)
{
    for (auto it = m_classifications.begin(); it != m_classifications.end();) {
        it = (std::get<2>(it->first) == meshGrid) ? m_classifications.erase(it) : std::next(it);
    }
}

std::vector<Category> AnalysisViewState::categories() const
{
    auto* self = const_cast<AnalysisViewState*>(this);

    std::vector<Category> result;
    std::map<std::string, size_t> seen;
    auto collect = [&result, &seen](const Classification* cls) {
        if (!cls) {
            return;
        }
        for (const auto& cat : cls->categories()) {
            auto [it, fresh] = seen.emplace(cat.key, result.size());
            if (fresh) {
                result.push_back(cat);
                continue;
            }
            // A category several meshes have is one category, and the count
            // the tree shows for it is what all of them add up to.
            result[it->second].count += cat.count;
        }
    };

    // Geometry derived categories first so their order stays stable, then
    // whatever the individual meshes add on top.
    collect(self->classification(nullptr));
    for (const auto& entry : m_meshGrids) {
        collect(self->classification(entry.first));
    }
    return result;
}

namespace
{
std::string encodeClipPlane(const ClippingPlane& p)
{
    std::ostringstream os;
    os << p.Origin.x << ' ' << p.Origin.y << ' ' << p.Origin.z << ' ' << p.Direction.x << ' '
       << p.Direction.y << ' ' << p.Direction.z;
    if (!p.Scope.empty()) {
        os << ' ' << p.Scope;
    }
    return os.str();
}

bool decodeClipPlane(const std::string& s, ClippingPlane& p)
{
    p.Scope.clear();
    std::istringstream is(s);
    if (!(is >> p.Origin.x >> p.Origin.y >> p.Origin.z >> p.Direction.x >> p.Direction.y
          >> p.Direction.z)) {
        return false;
    }
    std::string rest;
    std::getline(is >> std::ws, rest);
    if (!rest.empty()) {
        p.Scope = rest;
    }
    return true;
}
}  // namespace

void AnalysisViewState::loadFromViewProvider(ViewProviderFemAnalysis* vp)
{
    if (!vp) {
        return;
    }

    beginUpdate();
    m_hiddenElements.clear();
    for (const auto& e : vp->ViewHiddenElements.getValues()) {
        m_hiddenElements.insert(e);
    }

    m_clipPlanes.clear();
    const auto& names = vp->ViewClipPlaneNames.getValues();
    const auto& data = vp->ViewClipPlaneData.getValues();
    const size_t n = std::min(names.size(), data.size());
    for (size_t i = 0; i < n; ++i) {
        ClippingPlane plane;
        if (decodeClipPlane(data[i], plane)) {
            m_clipPlanes[names[i]] = plane;
        }
    }
    // Restored state has to reach the renderers, so announce it like any other
    // change. endUpdate() collapses this into a single notification.
    notifyChanged();
    endUpdate();
}

void AnalysisViewState::persist() const
{
    // Each of these rewrites three property lists in full, so hiding a subtree
    // one element at a time would write the whole hidden set once per element.
    if (m_batchDepth > 0) {
        m_pendingPersist = true;
        return;
    }
    if (!m_analysis || !Gui::Application::Instance) {
        return;
    }
    auto* guiDoc = Gui::Application::Instance->getDocument(m_analysis->getDocument());
    if (!guiDoc) {
        return;
    }
    saveToViewProvider(freecad_cast<ViewProviderFemAnalysis*>(guiDoc->getViewProvider(m_analysis)));
}

void AnalysisViewState::saveToViewProvider(ViewProviderFemAnalysis* vp) const
{
    if (!vp) {
        return;
    }

    // These live on the view provider, so they are saved with the document and
    // never trigger a recompute of the analysis.
    std::vector<std::string> hidden(m_hiddenElements.begin(), m_hiddenElements.end());
    vp->ViewHiddenElements.setValues(hidden);

    std::vector<std::string> names;
    std::vector<std::string> data;
    names.reserve(m_clipPlanes.size());
    data.reserve(m_clipPlanes.size());
    // Only the planes that cut: a switched off one is a runtime convenience,
    // and saving it would reopen the document already clipping nothing.
    for (const auto& entry : m_clipPlanes) {
        if (!entry.second.Active) {
            continue;
        }
        names.push_back(entry.first);
        data.push_back(encodeClipPlane(entry.second));
    }
    vp->ViewClipPlaneNames.setValues(names);
    vp->ViewClipPlaneData.setValues(data);
}

// ---------------------------------------------------------------------------
// ViewStateBinding
// ---------------------------------------------------------------------------

ViewStateBinding::~ViewStateBinding()
{
    m_conn.disconnect();
}

bool ViewStateBinding::isBoundTo(const AnalysisViewState* state) const
{
    return m_state == state && m_conn.connected();
}

void ViewStateBinding::bind(AnalysisViewState* state, AnalysisViewState::Slot onChanged)
{
    m_conn.disconnect();
    m_state = state;
    if (m_state) {
        m_conn = m_state->connectChanged(std::move(onChanged));
    }
}

AnalysisViewState* ViewStateBinding::release()
{
    m_conn.disconnect();
    AnalysisViewState* state = m_state;
    m_state = nullptr;
    return state;
}
