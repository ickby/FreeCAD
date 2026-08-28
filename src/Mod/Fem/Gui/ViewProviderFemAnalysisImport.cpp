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
# include <cstring>
# include <functional>
# include <set>
# include <Inventor/nodes/SoSeparator.h>
# include <Inventor/nodes/SoTransform.h>
#endif

#include "ViewProviderFemAnalysisImport.h"

#include <App/Application.h>
#include <App/Document.h>
#include <App/SuppressibleExtension.h>
#include <Base/Parameter.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/Control.h>
#include <Gui/Inventor/Draggers/SoTransformDragger.h>
#include <Gui/Document.h>
#include <Gui/Selection/Selection.h>
#include <Gui/View3DInventor.h>
#include <Gui/View3DInventorViewer.h>
#include <Gui/ViewParams.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemAnalysisImport.h>
#include <Mod/Fem/App/FemConstraint.h>
#include <Mod/Fem/App/FemGeometry.h>
#include <Mod/Fem/App/FemMesh.h>
#include <Mod/Fem/App/FemMeshObject.h>
#include <Mod/Fem/App/FemMeshShapeGroup.h>
#include <Mod/Fem/App/FemTools.h>
#include <SMESHDS_Group.hxx>
#include <SMESHDS_Mesh.hxx>
#include <SMESH_Group.hxx>
#include <SMESH_Mesh.hxx>
#include <SMDS_MeshElement.hxx>

#include "AnalysisViewState.h"
#include "TaskFemAnalysisImport.h"
#include "ViewProviderFemConstraint.h"

using namespace FemGui;

namespace
{

constexpr const char* GeometryMode = "Geometry";
constexpr const char* MeshMode = "Mesh";
constexpr const char* HiddenMode = "Hidden";

/// Preferences holding the drag steps shared by all instance draggers.
constexpr const char* draggerStepGroup = "User parameter:BaseApp/Preferences/Mod/Fem/General";
constexpr const char* translationStepEntry = "ImportDraggerTranslationStep";
constexpr const char* angleStepEntry = "ImportDraggerAngleStep";
constexpr double defaultTranslationStep = 1.0;
constexpr double defaultAngleStep = 15.0;
/// Smallest steps, a step of 0 would freeze the dragger.
constexpr double minTranslationStep = 1e-6;
constexpr double minAngleStep = 0.01;

/**
 * VTK grids of source meshes, one per source whatever the number of instances.
 *
 * Turning a mesh into a grid is the expensive part of drawing an instance, and
 * two instances of one analysis would otherwise do it twice over. What an
 * instance needs of its own is the cell data the renderer writes its masks
 * into, which updateFromSharedGrid() gives it around the shared points and
 * cells. Keyed by mesh group and merge revision, so a remesh is picked up.
 */
class MeshGridCache
{
public:
    struct Entry
    {
        std::size_t revision {0};
        vtkSmartPointer<vtkUnstructuredGrid> grid;
        std::vector<int> cellElementIds;
    };

    static MeshGridCache& instance()
    {
        static MeshGridCache cache;
        return cache;
    }

    const Entry* entryFor(Fem::FemMeshShapeGroup* group)
    {
        if (!group) {
            return nullptr;
        }
        const Fem::FemMesh& mesh = group->getMergedMesh();
        Entry& entry = m_entries[group];
        if (entry.grid && entry.revision == group->mergeRevision()) {
            return entry.grid->GetNumberOfCells() > 0 ? &entry : nullptr;
        }
        entry.revision = group->mergeRevision();
        entry.grid = vtkSmartPointer<vtkUnstructuredGrid>::New();
        FemPreprocessMeshViewHelper::buildGrid(mesh, entry.grid, entry.cellElementIds);
        return entry.grid->GetNumberOfCells() > 0 ? &entry : nullptr;
    }

private:
    MeshGridCache()
        : m_deleted(App::GetApplication().signalDeletedObject.connect(
              [this](const App::DocumentObject& obj) {
                  m_entries.erase(&obj);
              }
          ))
        // Closing a document does not announce its objects one by one, and an
        // address that is freed here is handed to the next group that is made.
        // With a revision that starts at the same number as the one it replaces
        // that group would be drawn with a mesh it never had.
        , m_documentClosed(App::GetApplication().signalDeleteDocument.connect(
              [this](const App::Document&) {
                  m_entries.clear();
              }
          ))
    {}

    std::map<const App::DocumentObject*, Entry> m_entries;
    fastsignals::scoped_connection m_deleted;
    fastsignals::scoped_connection m_documentClosed;
};

Fem::FemMeshShapeGroup* meshGroupOf(const Fem::FemAnalysis* analysis)
{
    if (!analysis) {
        return nullptr;
    }
    for (auto* obj : analysis->Group.getValues()) {
        if (auto* group = Base::freecad_cast<Fem::FemMeshShapeGroup*>(obj)) {
            return group;
        }
    }
    return nullptr;
}

/**
 * Document-wide selection observer.
 *
 * The view provider only hears about a selection that names it, and a solid of
 * an instance is highlighted by its faces rather than by a detail, so every
 * import has to re-read the selection whenever it moves.
 */
class ImportSelectionObserver: public Gui::SelectionObserver
{
public:
    static void init()
    {
        static ImportSelectionObserver* instance = nullptr;
        if (!instance) {
            instance = new ImportSelectionObserver();
        }
    }

    ImportSelectionObserver()
        : SelectionObserver(true, Gui::ResolveMode::NoResolve)
    {}

    void onSelectionChanged(const Gui::SelectionChanges& msg) override
    {
        switch (msg.Type) {
            case Gui::SelectionChanges::AddSelection:
            case Gui::SelectionChanges::RmvSelection:
            case Gui::SelectionChanges::ClrSelection:
            case Gui::SelectionChanges::SetSelection:
            case Gui::SelectionChanges::SetPreselect:
            case Gui::SelectionChanges::RmvPreselect:
                break;
            default:
                return;
        }

        auto syncDoc = [](App::Document* doc) {
            if (!doc) {
                return;
            }
            for (auto* obj : doc->getObjectsOfType(Fem::FemAnalysisImport::getClassTypeId())) {
                auto* vp = Base::freecad_cast<ViewProviderFemAnalysisImport*>(
                    Gui::Application::Instance->getViewProvider(obj)
                );
                if (vp) {
                    vp->syncSelectionHighlight();
                }
            }
        };

        // Clearing every document leaves no name behind to go by.
        if (!msg.pDocName || !msg.pDocName[0]) {
            for (auto* doc : App::GetApplication().getDocuments()) {
                syncDoc(doc);
            }
            return;
        }
        syncDoc(App::GetApplication().getDocument(msg.pDocName));
    }
};

void setTransformFromPlacement(SoTransform* node, const Base::Placement& pla)
{
    if (!node) {
        return;
    }
    const Base::Rotation rot = pla.getRotation();
    node->rotation.setValue(
        rot[0],
        rot[1],
        rot[2],
        rot[3]
    );
    const Base::Vector3d pos = pla.getPosition();
    node->translation.setValue(
        static_cast<float>(pos.x),
        static_cast<float>(pos.y),
        static_cast<float>(pos.z)
    );
}

}  // namespace

struct FemGui::ViewProviderFemAnalysisImport::ImportRenderNode
{
    Fem::FemAnalysisImport* importObj {nullptr};
    SoSeparator* geometryBranch {nullptr};
    SoSeparator* meshBranch {nullptr};
    SoTransform* transform {nullptr};
    FemGeometryViewHelper geometry;
    FemPreprocessMeshViewHelper mesh;
    std::vector<std::unique_ptr<ImportRenderNode>> nested;
};

PROPERTY_SOURCE(FemGui::ViewProviderFemAnalysisImport, Gui::ViewProviderDocumentObject)

ViewProviderFemAnalysisImport::ViewProviderFemAnalysisImport()
{
    ImportSelectionObserver::init();

    sPixmap = "FEM_AnalysisImport";

    ADD_PROPERTY_TYPE(
        ShowInheritedConstraints,
        (true),
        "FEM Import",
        App::Prop_None,
        "Draw constraint symbols inherited from the source analysis"
    );

    m_geometryRoot = new SoSeparator();
    m_geometryRoot->ref();
    m_meshRoot = new SoSeparator();
    m_meshRoot->ref();
    m_hidden = new SoSeparator();
    m_hidden->ref();
}

ViewProviderFemAnalysisImport::~ViewProviderFemAnalysisImport()
{
    m_viewStateConn.disconnect();
    m_treeConn.disconnect();
    m_connections.clear();
    clearRenderTree();
    if (pInheritedSymbols) {
        pInheritedSymbols->removeAllChildren();
        pInheritedSymbols->unref();
        pInheritedSymbols = nullptr;
    }
    m_geometryRoot->unref();
    m_meshRoot->unref();
    m_hidden->unref();
}

void ViewProviderFemAnalysisImport::attach(App::DocumentObject* obj)
{
    Gui::ViewProviderDocumentObject::attach(obj);

    addDisplayMaskMode(m_geometryRoot, GeometryMode);
    addDisplayMaskMode(m_meshRoot, MeshMode);
    addDisplayMaskMode(m_hidden, HiddenMode);
    setDisplayMaskMode(GeometryMode);

    pInheritedSymbols = new SoSeparator();
    pInheritedSymbols->ref();
    // The symbols are built in the frame of this instance, so that moving it
    // takes them along without any of them having to be built again.
    m_symbolTransform = new SoTransform();
    pInheritedSymbols->addChild(m_symbolTransform);
    // Under the display masks rather than the root, so that hiding the import
    // or leaving its stages takes the inherited symbols with it.
    m_geometryRoot->addChild(pInheritedSymbols);
    m_meshRoot->addChild(pInheritedSymbols);

    // Which analysis an import follows depends on where it sits, and it is put
    // into one only after attach(). Nothing about the import itself changes at
    // that point, so the container is what has to be watched.
    m_treeConn = obj->getDocument()->signalChangedObject.connect(
        [this](const App::DocumentObject&, const App::Property& prop) {
            const char* name = prop.getName();
            if (name && std::strcmp(name, "Group") == 0) {
                connectViewState();
            }
        }
    );

    connectSource();
    connectViewState();
    rebuildRenderTree();
    rebuildInheritedSymbols();
}

std::vector<std::string> ViewProviderFemAnalysisImport::getDisplayModes() const
{
    // What an instance draws follows the stage of the analysis it is placed in
    // rather than a choice of its own, so there is a single mode. It is there
    // because an object without one cannot be shown or hidden like the rest.
    return {"Default"};
}

void ViewProviderFemAnalysisImport::setDisplayMode(const char* mode)
{
    Gui::ViewProviderDocumentObject::setDisplayMode(mode);
    syncStageVisibility();
}

void ViewProviderFemAnalysisImport::finishRestoring()
{
    Gui::ViewProviderDocumentObject::finishRestoring();
    rebuildRenderTree();
    rebuildInheritedSymbols();
}

Fem::FemAnalysis* ViewProviderFemAnalysisImport::findAnalysis() const
{
    auto* obj = getObject();
    if (!obj) {
        return nullptr;
    }
    // An import usually sits in the Imports container rather than in the
    // analysis itself, so the analysis is a parent of a parent.
    std::set<const App::DocumentObject*> seen;
    std::vector<const App::DocumentObject*> pending {obj};
    while (!pending.empty()) {
        const App::DocumentObject* current = pending.back();
        pending.pop_back();
        for (auto* parent : current->getInList()) {
            if (!seen.insert(parent).second) {
                continue;
            }
            if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(parent)) {
                return analysis;
            }
            pending.push_back(parent);
        }
    }
    return nullptr;
}

void ViewProviderFemAnalysisImport::connectNodeViewState(ImportRenderNode& node)
{
    node.geometry.connectViewState();
    node.mesh.connectViewState();
    for (auto& child : node.nested) {
        connectNodeViewState(*child);
    }
}

void ViewProviderFemAnalysisImport::connectViewState()
{
    auto* analysis = findAnalysis();
    auto* state = analysis ? AnalysisViewState::forAnalysis(analysis) : nullptr;
    if (state == m_boundViewState && m_viewStateConn.connected()) {
        return;
    }
    m_viewStateConn.disconnect();
    m_boundViewState = state;
    if (state) {
        m_viewStateConn = state->connectChanged([this]() { onViewStateChanged(); });
        // The helpers follow the same state, and the render tree is usually
        // built before the import is in an analysis, so they were left without
        // one and have to catch up. Until they do, they draw as if no colour
        // mode, hidden element or clip plane were set.
        for (auto& node : m_renderNodes) {
            connectNodeViewState(*node);
        }
        onViewStateChanged();
    }
}

void ViewProviderFemAnalysisImport::onViewStateChanged()
{
    syncStageVisibility();
    for (auto& node : m_renderNodes) {
        node->geometry.onViewStateChanged();
        node->mesh.onViewStateChanged();
    }
}

void ViewProviderFemAnalysisImport::syncStageVisibility()
{
    // An import is put into its analysis after the view provider is attached,
    // so the state it has to follow is only reachable later on.
    connectViewState();
    if (!m_boundViewState) {
        setDisplayMaskMode(GeometryMode);
        return;
    }
    switch (m_boundViewState->activeStage()) {
        case ActiveStage::Mesh:
            setDisplayMaskMode(MeshMode);
            break;
        case ActiveStage::Geometry:
            setDisplayMaskMode(GeometryMode);
            break;
        default:
            setDisplayMaskMode(HiddenMode);
            break;
    }
}

std::vector<unsigned char> ViewProviderFemAnalysisImport::buildComponentSubsetMask(
    const Fem::FemMesh& mesh,
    Fem::FemGeometry* geom,
    const std::vector<long>& suppressedComponents
)
{
    if (!geom || suppressedComponents.empty()) {
        return {};
    }

    std::set<long> suppressed(suppressedComponents.begin(), suppressedComponents.end());
    std::set<std::string> hiddenNames;
    Fem::componentIdType compId = 0;
    for (auto& component : geom->getComponents()) {
        ++compId;
        if (!suppressed.count(compId)) {
            continue;
        }
        for (const auto& name : geom->getToplevelElements(component)) {
            hiddenNames.insert(name);
        }
    }
    if (hiddenNames.empty()) {
        return {};
    }

    const SMESH_Mesh* smesh = mesh.getSMesh();
    if (!smesh) {
        return {};
    }

    int maxId = 0;
    SMDS_ElemIteratorPtr it = smesh->GetMeshDS()->elementsIterator(SMDSAbs_All);
    while (it->more()) {
        maxId = std::max(maxId, it->next()->GetID());
    }
    if (maxId <= 0) {
        return {};
    }

    std::vector<unsigned char> mask(static_cast<size_t>(maxId), 1);
    SMESH_Mesh::GroupIteratorPtr gIt = smesh->GetGroups();
    while (gIt->more()) {
        SMESH_Group* group = gIt->next();
        const char* gname = group->GetName();
        if (!gname || !hiddenNames.count(gname)) {
            continue;
        }
        SMDS_ElemIteratorPtr eIt = group->GetGroupDS()->GetElements();
        while (eIt->more()) {
            const int id = eIt->next()->GetID();
            if (id > 0 && id <= maxId) {
                mask[static_cast<size_t>(id - 1)] = 0;
            }
        }
    }
    return mask;
}

void ViewProviderFemAnalysisImport::clearRenderTree()
{
    std::function<void(ImportRenderNode*)> releaseNode = [&](ImportRenderNode* node) {
        if (!node) {
            return;
        }
        for (auto& child : node->nested) {
            releaseNode(child.get());
        }
        node->mesh.disconnectViewState();
        node->geometry.disconnectViewState();
        if (node->geometryBranch) {
            node->geometryBranch->removeAllChildren();
            node->geometryBranch->unref();
            node->geometryBranch = nullptr;
        }
        if (node->meshBranch) {
            node->meshBranch->removeAllChildren();
            node->meshBranch->unref();
            node->meshBranch = nullptr;
        }
    };

    for (auto& node : m_renderNodes) {
        releaseNode(node.get());
    }
    m_renderNodes.clear();
    // Leave the inherited symbols in place: they share these roots but are
    // rebuilt on their own occasions.
    for (SoSeparator* root : {m_geometryRoot, m_meshRoot}) {
        for (int i = root->getNumChildren() - 1; i >= 0; --i) {
            if (root->getChild(i) != pInheritedSymbols) {
                root->removeChild(i);
            }
        }
    }
}

ViewProviderFemAnalysisImport::ImportRenderNode* ViewProviderFemAnalysisImport::buildRenderNode(
    Fem::FemAnalysisImport* importObj,
    const Base::Placement& outer,
    const std::string& pathPrefix,
    const std::string& selectionPrefix,
    std::vector<const Fem::FemAnalysisImport*>& chain
)
{
    if (!importObj) {
        return nullptr;
    }
    if (std::ranges::find(chain, importObj) != chain.end()) {
        return nullptr;
    }

    auto node = std::make_unique<ImportRenderNode>();
    node->importObj = importObj;
    const Base::Placement placement = outer * importObj->Placement.getValue();
    const std::string localPrefix = pathPrefix + importObj->getNameInDocument() + ".";

    node->geometryBranch = new SoSeparator();
    node->geometryBranch->ref();
    node->meshBranch = new SoSeparator();
    node->meshBranch->ref();
    node->transform = new SoTransform();
    // The branch of a nested instance hangs inside this one, where the
    // traversal already carries everything above it; only what this instance
    // adds belongs in the node. The helpers below want the whole chain,
    // because they work in the frame of the analysis rather than the graph.
    setTransformFromPlacement(node->transform, importObj->Placement.getValue());
    node->geometryBranch->addChild(node->transform);
    node->meshBranch->addChild(node->transform);

    auto* geomSep = new SoSeparator();
    node->geometryBranch->addChild(geomSep);

    auto* meshSep = new SoSeparator();
    node->meshBranch->addChild(meshSep);
    meshSep->addChild(node->mesh.renderer().root());

    node->geometry.setHost(this, [this]() { return findAnalysis(); }, [importObj]() {
        return importObj->sourceGeometry();
    });
    node->geometry.setPathPrefix(localPrefix);
    node->geometry.setSelectionPrefix(selectionPrefix);
    node->geometry.setLocalFrame(placement);
    node->geometry.setManageStageVisibility(false);
    node->geometry.setSuppressedComponents(importObj->SuppressedComponents.getValues());
    node->geometry.attachToSeparator(geomSep);
    node->geometry.connectViewState();

    node->mesh.setHost(this, [this]() { return findAnalysis(); }, [importObj]() {
        return importObj->sourceGeometry();
    });
    node->mesh.setPathPrefix(localPrefix);
    node->mesh.setSelectionPrefix(selectionPrefix);
    node->mesh.setLocalFrame(placement);
    node->mesh.setManageStageVisibility(false);
    node->mesh.connectViewState();

    if (auto* srcGeom = importObj->sourceGeometry()) {
        // In the frame of the source analysis: the placement is the transform
        // above this subtree, applying it here as well would double it.
        node->geometry.updateFromShape(srcGeom->Shape.getShape(), srcGeom);
    }

    auto* srcMeshGroup =
        meshGroupOf(Base::freecad_cast<Fem::FemAnalysis*>(importObj->Analysis.getValue()));
    if (const auto* shared = MeshGridCache::instance().entryFor(srcMeshGroup)) {
        node->mesh.updateFromSharedGrid(shared->grid, shared->cellElementIds);
        node->mesh.setElementSubsetMask(buildComponentSubsetMask(
            importObj->sourceMesh(),
            importObj->sourceGeometry(),
            importObj->SuppressedComponents.getValues()
        ));
        node->mesh.onViewStateChanged();
    }

    chain.push_back(importObj);
    auto* src = Base::freecad_cast<Fem::FemAnalysis*>(importObj->Analysis.getValue());
    if (src) {
        for (auto* nested : Fem::Tools::analysisImports(src)) {
            const char* nestedName = nested->getNameInDocument();
            const std::string nestedSelection =
                selectionPrefix + (nestedName ? nestedName : "") + ".";
            if (ImportRenderNode* child =
                    buildRenderNode(nested, placement, localPrefix, nestedSelection, chain)) {
                node->geometryBranch->addChild(child->geometryBranch);
                node->meshBranch->addChild(child->meshBranch);
                node->nested.emplace_back(child);
            }
        }
    }
    chain.pop_back();

    return node.release();
}

void ViewProviderFemAnalysisImport::rebuildRenderTree()
{
    clearRenderTree();

    auto* importObj = getObject<Fem::FemAnalysisImport>();
    if (!importObj) {
        return;
    }

    std::vector<const Fem::FemAnalysisImport*> chain;
    // The root instance is the object the view provider belongs to, so its own
    // elements need no selection prefix at all.
    if (auto* root = buildRenderNode(
            importObj,
            Base::Placement(),
            std::string(),
            std::string(),
            chain
        )) {
        m_geometryRoot->addChild(root->geometryBranch);
        m_meshRoot->addChild(root->meshBranch);
        m_renderNodes.emplace_back(root);
    }

    // A tree built while something of it was already selected knows nothing of
    // that selection until the next time it moves.
    syncSelectionHighlight();
}

void ViewProviderFemAnalysisImport::updateNodePlacement(
    ImportRenderNode& node,
    const Base::Placement& outer,
    const Base::Placement* own
)
{
    if (!node.importObj) {
        return;
    }
    const Base::Placement local = own ? *own : node.importObj->Placement.getValue();
    const Base::Placement placement = outer * local;
    setTransformFromPlacement(node.transform, local);
    node.geometry.setLocalFrame(placement);
    node.mesh.setLocalFrame(placement);
    // The frame is only there to say where a clip plane of the analysis cuts
    // through this instance. Without one, what the helpers draw is the same
    // wherever the instance stands, and rebuilding it would cost a drag its
    // smoothness for nothing.
    if (m_boundViewState && !m_boundViewState->clipPlanes().empty()) {
        node.geometry.onViewStateChanged();
        node.mesh.onViewStateChanged();
    }
    for (auto& child : node.nested) {
        updateNodePlacement(*child, placement);
    }
}

void ViewProviderFemAnalysisImport::updatePlacements(const Base::Placement* rootPlacement)
{
    for (auto& node : m_renderNodes) {
        updateNodePlacement(*node, Base::Placement(), rootPlacement);
    }
    if (m_symbolTransform) {
        auto* importObj = getObject<Fem::FemAnalysisImport>();
        Base::Placement placement;
        if (rootPlacement) {
            placement = *rootPlacement;
        }
        else if (importObj) {
            placement = importObj->Placement.getValue();
        }
        setTransformFromPlacement(m_symbolTransform, placement);
    }
}

void ViewProviderFemAnalysisImport::setDraggerVisible(bool on)
{
    if (on == (m_dragger != nullptr)) {
        return;
    }

    if (!on) {
        m_dragger->removeStartCallback(dragStartCB, this);
        m_dragger->removeMotionCallback(dragMotionCB, this);
        m_dragger->removeFinishCallback(dragFinishCB, this);
        pcRoot->removeChild(m_dragger);
        m_dragger = nullptr;
        // A drag left half shown has to give the instance back to what is
        // written for it.
        m_dragging = false;
        updatePlacements();
        return;
    }

    m_dragger = new Gui::SoTransformDragger();
    m_dragger->setAxisColors(
        Gui::ViewParams::instance()->getAxisXColor(),
        Gui::ViewParams::instance()->getAxisYColor(),
        Gui::ViewParams::instance()->getAxisZColor()
    );
    m_dragger->draggerSize.setValue(
        static_cast<float>(Gui::ViewParams::instance()->getDraggerScale())
    );
    updateDraggerSteps();
    m_dragger->addStartCallback(dragStartCB, this);
    m_dragger->addMotionCallback(dragMotionCB, this);
    m_dragger->addFinishCallback(dragFinishCB, this);
    syncDraggerToPlacement();
    setUpDraggerScale();
    pcRoot->addChild(m_dragger);
}

double ViewProviderFemAnalysisImport::translationStep()
{
    ParameterGrp::handle group = App::GetApplication().GetParameterGroupByPath(draggerStepGroup);
    const double step = group->GetFloat(translationStepEntry, defaultTranslationStep);
    return step >= minTranslationStep ? step : defaultTranslationStep;
}

void ViewProviderFemAnalysisImport::setTranslationStep(double step)
{
    ParameterGrp::handle group = App::GetApplication().GetParameterGroupByPath(draggerStepGroup);
    group->SetFloat(translationStepEntry, std::max(step, minTranslationStep));
}

double ViewProviderFemAnalysisImport::angleStep()
{
    ParameterGrp::handle group = App::GetApplication().GetParameterGroupByPath(draggerStepGroup);
    const double step = group->GetFloat(angleStepEntry, defaultAngleStep);
    return step >= minAngleStep ? step : defaultAngleStep;
}

void ViewProviderFemAnalysisImport::setAngleStep(double degree)
{
    ParameterGrp::handle group = App::GetApplication().GetParameterGroupByPath(draggerStepGroup);
    group->SetFloat(angleStepEntry, std::max(degree, minAngleStep));
}

void ViewProviderFemAnalysisImport::updateDraggerSteps()
{
    if (!m_dragger) {
        return;
    }
    m_dragger->translationIncrement.setValue(translationStep());
    m_dragger->rotationIncrement.setValue(Base::toRadians<double>(angleStep()));
}

void ViewProviderFemAnalysisImport::setUpDraggerScale(Gui::View3DInventorViewer* viewer)
{
    if (!viewer) {
        // The panel puts the dragger up while the editing viewer is still
        // being handed over, and the view it is put up from is that viewer.
        auto* doc = getDocument();
        auto* view = doc ? dynamic_cast<Gui::View3DInventor*>(doc->getActiveView()) : nullptr;
        viewer = view ? view->getViewer() : nullptr;
    }
    if (!m_dragger || !viewer) {
        return;
    }

    // The size preference is a fraction of the screen, which means something
    // only to a dragger that follows a camera. Without one it reads the number
    // as a length in millimetres and draws itself far too small to see.
    if (SoCamera* camera = viewer->getSoRenderManager()->getCamera()) {
        m_dragger->setUpAutoScale(camera);
    }
}

void ViewProviderFemAnalysisImport::setEditViewer(Gui::View3DInventorViewer* viewer, int ModNum)
{
    setUpDraggerScale(viewer);
    Gui::ViewProviderDocumentObject::setEditViewer(viewer, ModNum);
}

void ViewProviderFemAnalysisImport::unsetEditViewer(Gui::View3DInventorViewer* viewer)
{
    setDraggerVisible(false);
    Gui::ViewProviderDocumentObject::unsetEditViewer(viewer);
}

void ViewProviderFemAnalysisImport::syncDraggerToPlacement()
{
    auto* importObj = getObject<Fem::FemAnalysisImport>();
    if (!m_dragger || !importObj) {
        return;
    }
    const Base::Placement pla = importObj->Placement.getValue();
    const Base::Vector3d pos = pla.getPosition();
    const Base::Rotation rot = pla.getRotation();
    m_dragger->translation.setValue(
        static_cast<float>(pos.x),
        static_cast<float>(pos.y),
        static_cast<float>(pos.z)
    );
    m_dragger->rotation.setValue(
        static_cast<float>(rot[0]),
        static_cast<float>(rot[1]),
        static_cast<float>(rot[2]),
        static_cast<float>(rot[3])
    );
    m_dragger->clearIncrementCounts();
}

Base::Placement ViewProviderFemAnalysisImport::draggedPlacement() const
{
    if (!m_dragger) {
        return m_dragOrigin;
    }

    const Base::Rotation rotation = m_dragOrigin.getRotation();
    const double step = m_dragger->translationIncrement.getValue();
    const Base::Vector3d offset =
        rotation.multVec(Base::Vector3d(1, 0, 0))
            * (step * m_dragger->translationIncrementCountX.getValue())
        + rotation.multVec(Base::Vector3d(0, 1, 0))
            * (step * m_dragger->translationIncrementCountY.getValue())
        + rotation.multVec(Base::Vector3d(0, 0, 1))
            * (step * m_dragger->translationIncrementCountZ.getValue());

    const double angle = m_dragger->rotationIncrement.getValue();
    Base::Rotation turned = rotation;
    turned = turned
        * Base::Rotation(
                 Base::Vector3d(1, 0, 0),
                 m_dragger->rotationIncrementCountX.getValue() * angle
        )
        * Base::Rotation(
                 Base::Vector3d(0, 1, 0),
                 m_dragger->rotationIncrementCountY.getValue() * angle
        )
        * Base::Rotation(
                 Base::Vector3d(0, 0, 1),
                 m_dragger->rotationIncrementCountZ.getValue() * angle
        );

    return Base::Placement(m_dragOrigin.getPosition() + offset, turned);
}

Base::Placement ViewProviderFemAnalysisImport::shownPlacement() const
{
    if (m_dragging) {
        return draggedPlacement();
    }
    auto* importObj = getObject<Fem::FemAnalysisImport>();
    return importObj ? importObj->Placement.getValue() : Base::Placement();
}

void ViewProviderFemAnalysisImport::dragStartCB(void* data, SoDragger*)
{
    auto* self = static_cast<ViewProviderFemAnalysisImport*>(data);
    auto* importObj = self ? self->getObject<Fem::FemAnalysisImport>() : nullptr;
    if (!importObj) {
        return;
    }
    self->m_dragOrigin = importObj->Placement.getValue();
    self->m_dragging = true;
    self->m_dragger->clearIncrementCounts();
}

void ViewProviderFemAnalysisImport::dragMotionCB(void* data, SoDragger*)
{
    auto* self = static_cast<ViewProviderFemAnalysisImport*>(data);
    if (!self || !self->m_dragger) {
        return;
    }
    // Writing the instance on every motion would send the dragger the placement
    // it is being dragged to and make it fight the hand holding it, so only
    // what is drawn follows along until the drag is over.
    const Base::Placement dragged = self->draggedPlacement();
    self->updatePlacements(&dragged);
    self->signalPlacementChanged();
}

void ViewProviderFemAnalysisImport::dragFinishCB(void* data, SoDragger*)
{
    auto* self = static_cast<ViewProviderFemAnalysisImport*>(data);
    auto* importObj = self ? self->getObject<Fem::FemAnalysisImport>() : nullptr;
    if (!importObj) {
        return;
    }

    const Base::Placement dragged = self->draggedPlacement();
    self->m_dragging = false;
    importObj->Placement.setValue(dragged);
    self->m_dragOrigin = dragged;
    self->m_dragger->clearIncrementCounts();
}

void ViewProviderFemAnalysisImport::updateData(const App::Property* prop)
{
    Gui::ViewProviderDocumentObject::updateData(prop);

    auto* importObj = getObject<Fem::FemAnalysisImport>();
    if (!importObj) {
        return;
    }

    // The analysis an import is added to is only known once it is in the tree,
    // and attach() runs before that.
    connectViewState();

    if (prop == &importObj->Placement) {
        // Dragging an instance must not retriangulate anything: the placement
        // only moves the subtree the source already built.
        updatePlacements();
        rebuildInheritedSymbols();
        // The panel writes the placement too, and then the dragger is stale.
        syncDraggerToPlacement();
        signalPlacementChanged();
        return;
    }

    if (prop == &importObj->Analysis || prop == &importObj->SuppressedComponents
        || prop == &importObj->SuppressedMembers) {
        if (prop == &importObj->Analysis) {
            connectSource();
        }
        rebuildRenderTree();
        rebuildInheritedSymbols();
    }
}

void ViewProviderFemAnalysisImport::onChanged(const App::Property* prop)
{
    Gui::ViewProviderDocumentObject::onChanged(prop);
    if (prop == &ShowInheritedConstraints) {
        rebuildInheritedSymbols();
    }
}

void ViewProviderFemAnalysisImport::clearInheritedSymbols()
{
    if (!pInheritedSymbols) {
        return;
    }
    // The frame the symbols are built in outlives them.
    for (int i = pInheritedSymbols->getNumChildren() - 1; i >= 0; --i) {
        if (pInheritedSymbols->getChild(i) != m_symbolTransform) {
            pInheritedSymbols->removeChild(i);
        }
    }
}

bool ViewProviderFemAnalysisImport::sourceProvides(const App::DocumentObject* obj) const
{
    if (!obj) {
        return false;
    }
    const bool renders = obj->isDerivedFrom<Fem::FemGeometry>()
        || obj->isDerivedFrom<Fem::FemMeshObject>()
        || obj->isDerivedFrom<Fem::FemAnalysisImport>();
    if (!renders) {
        return false;
    }

    std::set<const Fem::FemAnalysis*> sources;
    std::vector<const Fem::FemAnalysisImport*> pending;
    if (auto* importObj = getObject<Fem::FemAnalysisImport>()) {
        pending.push_back(importObj);
    }
    while (!pending.empty()) {
        const Fem::FemAnalysisImport* current = pending.back();
        pending.pop_back();
        auto* src = Base::freecad_cast<Fem::FemAnalysis*>(current->Analysis.getValue());
        if (!src || !sources.insert(src).second) {
            continue;
        }
        for (auto* nested : Fem::Tools::analysisImports(src)) {
            pending.push_back(nested);
        }
    }
    if (sources.empty()) {
        return false;
    }

    for (auto* parent : obj->getInListRecursive()) {
        if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(parent)) {
            if (sources.contains(analysis)) {
                return true;
            }
        }
    }
    return false;
}

void ViewProviderFemAnalysisImport::connectSource()
{
    m_connections.clear();

    auto* importObj = getObject<Fem::FemAnalysisImport>();
    if (!importObj) {
        return;
    }
    auto* src = Base::freecad_cast<Fem::FemAnalysis*>(importObj->Analysis.getValue());
    if (!src) {
        return;
    }

    m_connections.push_back(src->getDocument()->signalChangedObject.connect(
        [this, src](const App::DocumentObject& obj, const App::Property& prop) {
            if (&obj == src) {
                if (&prop == &src->Group) {
                    rebuildInheritedSymbols();
                    rebuildRenderTree();
                }
                return;
            }
            if (const auto* constraint = Base::freecad_cast<Fem::Constraint*>(&obj)) {
                if (&prop == &constraint->Points || &prop == &constraint->Normals
                    || &prop == &constraint->Scale) {
                    rebuildInheritedSymbols();
                }
                return;
            }
            // Editing the source geometry or remeshing it changes what this
            // instance draws, and nothing about the import itself says so.
            if (sourceProvides(&obj)) {
                rebuildRenderTree();
            }
        }
    ));
}

void ViewProviderFemAnalysisImport::addInheritedSymbols(
    Fem::FemAnalysisImport* importObj,
    const Base::Placement& transform,
    std::vector<const Fem::FemAnalysisImport*>& chain
)
{
    auto* src = Base::freecad_cast<Fem::FemAnalysis*>(importObj->Analysis.getValue());
    if (!src) {
        return;
    }

    chain.push_back(importObj);
    for (auto* member : src->Group.getValues()) {
        if (!member) {
            continue;
        }
        if (member->hasExtension(App::SuppressibleExtension::getExtensionClassTypeId())
            && member->getExtensionByType<App::SuppressibleExtension>()->Suppressed.getValue()) {
            continue;
        }
        auto* constraint = Base::freecad_cast<Fem::Constraint*>(member);
        if (!constraint) {
            continue;
        }
        if (Fem::Tools::isMemberSuppressed(chain, member)) {
            continue;
        }

        auto* vp = dynamic_cast<ViewProviderFemConstraint*>(
            Gui::Application::Instance->getViewProvider(constraint)
        );
        if (!vp) {
            continue;
        }

        if (SoSeparator* symbols = vp->makeSymbolInstance(transform)) {
            pInheritedSymbols->addChild(symbols);
        }
    }

    for (auto* nested : Fem::Tools::analysisImports(src)) {
        if (std::ranges::find(chain, nested) != chain.end()) {
            continue;
        }
        addInheritedSymbols(nested, transform * nested->Placement.getValue(), chain);
    }
    chain.pop_back();
}

void ViewProviderFemAnalysisImport::rebuildInheritedSymbols()
{
    if (!pInheritedSymbols) {
        return;
    }

    clearInheritedSymbols();

    if (!ShowInheritedConstraints.getValue()) {
        return;
    }

    auto* importObj = getObject<Fem::FemAnalysisImport>();
    if (!importObj) {
        return;
    }

    setTransformFromPlacement(m_symbolTransform, importObj->Placement.getValue());

    // The symbols hang below the frame of this instance, which is therefore no
    // part of what each of them is built with.
    std::vector<const Fem::FemAnalysisImport*> chain;
    addInheritedSymbols(importObj, Base::Placement(), chain);
}

bool ViewProviderFemAnalysisImport::setEdit(int ModNum)
{
    if (ModNum == ViewProvider::Default) {
        Gui::Control().showDialog(new TaskDlgFemAnalysisImport(this));
        return true;
    }
    return Gui::ViewProviderDocumentObject::setEdit(ModNum);
}

void ViewProviderFemAnalysisImport::unsetEdit(int ModNum)
{
    if (ModNum == ViewProvider::Default) {
        Gui::Control().closeDialog();
    }
    else {
        Gui::ViewProviderDocumentObject::unsetEdit(ModNum);
    }
}

bool ViewProviderFemAnalysisImport::doubleClicked()
{
    Gui::Application::Instance->activeDocument()->setEdit(this, static_cast<int>(ViewProvider::Default));
    return true;
}

void ViewProviderFemAnalysisImport::setElementHighlight(
    const std::string& role,
    const std::set<std::string>& elements,
    const Base::Color& color
)
{
    std::function<void(ImportRenderNode&)> walk = [&](ImportRenderNode& node) {
        node.geometry.setElementHighlight(role, elements, color);
        for (auto& child : node.nested) {
            walk(*child);
        }
    };
    for (auto& node : m_renderNodes) {
        walk(*node);
    }
}

void ViewProviderFemAnalysisImport::clearElementHighlight(const std::string& role)
{
    setElementHighlight(role, {}, Base::Color());
}

std::string ViewProviderFemAnalysisImport::getElement(const SoDetail* detail) const
{
    std::function<std::string(const ImportRenderNode&)> walk;
    walk = [&](const ImportRenderNode& node) -> std::string {
        if (auto el = node.geometry.elementFromDetail(detail); !el.empty()) {
            return el;
        }
        if (auto el = node.mesh.elementFromDetail(detail); !el.empty()) {
            return el;
        }
        for (const auto& child : node.nested) {
            if (auto el = walk(*child); !el.empty()) {
                return el;
            }
        }
        return {};
    };
    for (const auto& node : m_renderNodes) {
        if (auto el = walk(*node); !el.empty()) {
            return el;
        }
    }
    return {};
}

void ViewProviderFemAnalysisImport::syncSelectionHighlight()
{
    auto* importObj = getObject<Fem::FemAnalysisImport>();
    if (!importObj || !importObj->getDocument()) {
        return;
    }
    const char* docName = importObj->getDocument()->getName();
    const char* objName = importObj->getNameInDocument();
    if (!objName) {
        return;
    }

    std::set<std::string> selected;
    for (const auto& sel : Gui::Selection().getSelectionEx(
             docName,
             App::DocumentObject::getClassTypeId(),
             Gui::ResolveMode::NoResolve
         )) {
        if (std::strcmp(sel.getFeatName(), objName) != 0) {
            continue;
        }
        for (const auto& sub : sel.getSubNames()) {
            selected.insert(sub);
        }
    }

    // Preselection is a single slot on the selection singleton.
    std::set<std::string> preselected;
    const auto& pre = Gui::Selection().getPreselection();
    if (pre.pDocName && pre.pObjectName && pre.pSubName
        && std::strcmp(pre.pDocName, docName) == 0
        && std::strcmp(pre.pObjectName, objName) == 0) {
        preselected.insert(pre.pSubName);
    }

    std::function<void(ImportRenderNode&)> walk = [&](ImportRenderNode& node) {
        node.geometry.setSelectionState(selected, preselected);
        for (auto& child : node.nested) {
            walk(*child);
        }
    };
    for (auto& node : m_renderNodes) {
        walk(*node);
    }
}

SoDetail* ViewProviderFemAnalysisImport::getDetail(const char* subelement) const
{
    if (!subelement) {
        return nullptr;
    }
    std::function<SoDetail*(const ImportRenderNode&)> walk;
    walk = [&](const ImportRenderNode& node) -> SoDetail* {
        if (SoDetail* detail = node.geometry.detailFromElement(subelement)) {
            return detail;
        }
        if (SoDetail* detail = node.mesh.detailFromElement(subelement)) {
            return detail;
        }
        for (const auto& child : node.nested) {
            if (SoDetail* detail = walk(*child)) {
                return detail;
            }
        }
        return nullptr;
    };
    for (const auto& node : m_renderNodes) {
        if (SoDetail* detail = walk(*node)) {
            return detail;
        }
    }
    return nullptr;
}
