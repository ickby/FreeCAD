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

#include <algorithm>
#include <map>
#include <set>
#include <sstream>
#include <string_view>
#include <tuple>
#include <utility>
#include <vector>

#include <BRepBndLib.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <Bnd_Box.hxx>
#include <Precision.hxx>
#include <TopoDS_Shape.hxx>

#include <SMDS_Mesh.hxx>
#include <SMDS_MeshElement.hxx>
#include <SMDS_MeshInfo.hxx>
#include <SMDS_MeshNode.hxx>
#include <SMESHDS_GroupBase.hxx>
#include <SMESHDS_Mesh.hxx>
#include <SMESH_Group.hxx>
#include <SMESH_Mesh.hxx>

#include <App/Document.h>
#include <App/FeaturePythonPyImp.h>
#include <App/GeoFeaturePy.h>
#include <Base/Console.h>
#include <Base/Tools.h>
#include <Mod/Part/App/TopoShape.h>

#include "FemGeometry.h"
#include "FemMesh.h"
#include "FemMeshDimension.h"
#include "FemMeshShapeGroup.h"
#include "FemMeshShapeGroupPy.h"
#include "FemMeshTopology.h"
#include "FemPerfLog.h"


using namespace Fem;
using namespace App;

namespace
{

/// Internal name of an object, safe to print for objects not (yet) in a document.
const char* objectName(const App::DocumentObject* obj)
{
    const char* name = obj ? obj->getNameInDocument() : nullptr;
    return name ? name : "?";
}

/// Nodes and cells of a mesh, the two numbers a merge of it contributes.
std::pair<int, int> meshCounts(const Fem::FemMesh& mesh)
{
    if (const auto* smesh = mesh.getSMesh()) {
        if (const auto* meshDS = smesh->GetMeshDS()) {
            return {meshDS->NbNodes(), meshDS->GetMeshInfo().NbElements()};
        }
    }
    return {0, 0};
}

}  // namespace

PROPERTY_SOURCE_WITH_EXTENSIONS(Fem::FemMeshShapeGroup, Fem::FemMeshShapeBaseObject)

FemMeshShapeGroup::FemMeshShapeGroup()
{
    GroupExtension::initExtension(this);

    // A child being shown or hidden says nothing about the merge, and the group
    // extension would otherwise touch us for it. What does change the merge
    // reaches us through the Group link like any other dependency.
    _GroupTouched.setStatus(App::Property::Output, true);

    // The merged mesh is what execute() produces out of the children, and the
    // children are what gets persisted. Output keeps publishing it from
    // touching the group - it is the result of a recompute, not an input to
    // the next one - and NoModify keeps putting a derived value back from
    // asking the user to save a document whose file contents never changed.
    FemMesh.setStatus(App::Property::Transient, true);
    FemMesh.setStatus(App::Property::Output, true);
    FemMesh.setStatus(App::Property::NoModify, true);

    ADD_PROPERTY_TYPE(
        CellSources,
        (),
        "FEM Mesh",
        App::PropertyType(App::Prop_Transient | App::Prop_Output | App::Prop_Hidden),
        "Child object name for each merged cell (elementId - 1)"
    );
    ADD_PROPERTY_TYPE(
        CellDimension,
        (),
        "FEM Mesh",
        App::PropertyType(App::Prop_Transient | App::Prop_Output | App::Prop_Hidden),
        "Analysis dimension of each merged cell (elementId - 1), or -1 if dropped"
    );
    ADD_PROPERTY_TYPE(
        EntityDimension,
        (),
        "FEM Mesh",
        App::PropertyType(App::Prop_Transient | App::Prop_Output | App::Prop_Hidden),
        "Effective analysis dimension per entity group name"
    );

    // Derived alongside the merged mesh and just as transient, so republishing
    // them says nothing about whether the document needs saving.
    CellSources.setStatus(App::Property::NoModify, true);
    CellDimension.setStatus(App::Property::NoModify, true);
    EntityDimension.setStatus(App::Property::NoModify, true);
}

FemMeshShapeGroup::~FemMeshShapeGroup() = default;

bool FemMeshShapeGroup::allowObject(App::DocumentObject* obj)
{
    return obj && obj->isDerivedFrom<FemMeshObject>();
}

short FemMeshShapeGroup::mustExecute() const
{
    // A request is the only thing execute() has work for. Group and Shape are
    // still asked because a restore or an undo can put them back without the
    // change reaching onChanged(); execute() returns at once when it finds
    // nothing requested.
    if (m_meshRebuildRequested || m_topologyRebuildRequested) {
        return 1;
    }
    if (Group.isTouched() || Shape.isTouched()) {
        return 1;
    }
    return FemMeshShapeBaseObject::mustExecute();
}

void FemMeshShapeGroup::requestRebuild(bool withTopology)
{
    m_meshRebuildRequested = true;
    if (withTopology) {
        m_topologyRebuildRequested = true;
    }

    // FreeCAD schedules us for a child that changed inside a recompute, but a
    // mesh assigned from a script or put back by an undo raises the signal with
    // nothing else to follow it. Restoring is the one case where the request
    // alone is enough: onDocumentRestored() rebuilds directly, and touching the
    // object there would leave a freshly opened document wanting a recompute.
    if (isAttachedToDocument() && !isRestoring()) {
        enforceRecompute();
    }
}

void FemMeshShapeGroup::reconnectChildSignals()
{
    m_childConns.clear();
    auto connect = [this](const std::vector<App::DocumentObject*>& objects) {
        for (auto* obj : objects) {
            if (!obj || !obj->isAttachedToDocument()) {
                continue;
            }
            m_childConns[obj] = obj->signalChanged.connect(
                [this](const App::DocumentObject& o, const App::Property& p) {
                    this->slotChildChanged(o, p);
                }
            );
        }
    };
    connect(Group.getValues());
}

void FemMeshShapeGroup::slotChildChanged(const App::DocumentObject& obj, const App::Property& prop)
{
    auto* meshObj = Base::freecad_cast<FemMeshObject*>(&obj);
    if (!meshObj) {
        return;
    }
    if (&prop == &meshObj->FemMesh) {
        // A new child mesh brings new cells, new groups and new provenance;
        // nothing derived from the old one survives it.
        requestRebuild(true);
        return;
    }
    if (&prop == &meshObj->Placement) {
        // A rigid move leaves connectivity, groups and element ids exactly as
        // they were, so only the coordinates have to be laid down again.
        requestRebuild(false);
    }

    // Everything else a child has - mesher settings, Components, visibility,
    // its label - reaches the merge only through the mesh it produces, which
    // arrives above as an assignment of its own.
}

void FemMeshShapeGroup::onChanged(const App::Property* prop)
{
    if (prop == &Group) {
        // Membership and order decide which meshes are appended and in which
        // order, so the merge and everything derived from it start over.
        reconnectChildSignals();
        requestRebuild(true);
    }

    // A change of Shape alone is geometry metadata for the next merge, not a
    // reason to redo the current one; the next child mesh picks it up.

    FemMeshShapeBaseObject::onChanged(prop);
}

void FemMeshShapeGroup::extensionOnChanged(const App::Property* prop)
{
    if (prop == &Visibility) {
        App::Extension::extensionOnChanged(prop);
        return;
    }
    App::GroupExtension::extensionOnChanged(prop);
}

void FemMeshShapeGroup::onDocumentRestored()
{
    // The status of a transient property is written to the file, so a document
    // saved before this was set brings the old one back with it.
    _GroupTouched.setStatus(App::Property::Output, true);

    // The child meshes live in their own files inside the archive, and those
    // are read before the dependency-ordered restore hooks run, so by the time
    // a group is reached its children hold their meshes. Restoring them raises
    // no property change, which makes this the only point at which the merged
    // mesh - transient, and so absent from the file - can be put back.
    reconnectChildSignals();
    m_meshRebuildRequested = true;
    m_topologyRebuildRequested = true;
    if (auto* ret = execute(); ret != App::DocumentObject::StdReturn) {
        Base::Console().warning(
            "FemMeshShapeGroup '%s': %s\n",
            objectName(this),
            ret->Why.c_str()
        );
        delete ret;
    }

    FemMeshShapeBaseObject::onDocumentRestored();
}

namespace
{
int componentIndexFromSubname(const std::string& sub)
{
    constexpr std::string_view prefix = "Component";
    if (!sub.starts_with(prefix)) {
        return -1;
    }
    try {
        const auto idx = std::stoll(sub.substr(prefix.size()));
        return static_cast<int>(idx);  // 1-based ComponentN
    }
    catch (...) {
        return -1;
    }
}
}  // namespace

FemMeshShapeGroup::ComponentClaims FemMeshShapeGroup::collectComponentClaims() const
{
    ComponentClaims claims;
    if (auto* shapeObj = Shape.getValue()) {
        claims.geometry = Base::freecad_cast<FemGeometry*>(shapeObj);
    }

    for (auto* obj : Group.getValues()) {
        auto* mesh = Base::freecad_cast<FemMeshShapeBaseObject*>(obj);
        if (!mesh) {
            continue;
        }
        auto* geo = Base::freecad_cast<FemGeometry*>(mesh->Components.getValue());
        if (!geo) {
            continue;
        }
        if (!claims.geometry) {
            claims.geometry = geo;
        }
        else if (claims.geometry != geo) {
            claims.mixedGeometry = true;
            return claims;
        }

        // Empty sub-values means the mesh covers all components of the linked
        // geometry (same convention as the Gmsh/Netgen commands).
        std::vector<int> indices;
        const auto subs = mesh->Components.getSubValues();
        if (subs.empty()) {
            const auto count = static_cast<int>(geo->getComponents().size());
            for (int idx = 1; idx <= count; ++idx) {
                indices.push_back(idx);
            }
        }
        else {
            for (const auto& sub : subs) {
                const int idx = componentIndexFromSubname(sub);
                if (idx >= 1) {
                    indices.push_back(idx);
                }
            }
        }

        for (int idx : indices) {
            if (claims.owner.contains(idx)) {
                claims.conflicts.emplace_back(idx, mesh);
            }
            else {
                claims.owner[idx] = mesh;
            }
        }
    }

    return claims;
}

std::map<int, App::DocumentObject*> FemMeshShapeGroup::getComponentOwners() const
{
    const ComponentClaims claims = collectComponentClaims();

    std::map<int, App::DocumentObject*> owners;
    for (const auto& [idx, mesh] : claims.owner) {
        owners[idx] = const_cast<FemMeshShapeBaseObject*>(mesh);
    }
    return owners;
}

std::string FemMeshShapeGroup::validateComponents(bool* hasOverlap) const
{
    if (hasOverlap) {
        *hasOverlap = false;
    }

    const ComponentClaims claims = collectComponentClaims();
    if (claims.mixedGeometry) {
        return "All mesh Components must reference the same FemGeometry";
    }

    FemGeometry* geometry = claims.geometry;
    const auto& componentOwner = claims.owner;
    const bool overlapFound = !claims.conflicts.empty();

    std::ostringstream overlap;
    for (const auto& [idx, mesh] : claims.conflicts) {
        if (overlap.tellp() > 0) {
            overlap << ", ";
        }
        overlap << "Component" << idx << " (" << objectName(mesh) << ")";
    }

    if (hasOverlap) {
        *hasOverlap = overlapFound;
    }

    std::ostringstream msg;
    if (overlapFound) {
        msg << "Overlapping component assignment: " << overlap.str();
    }

    if (geometry) {
        const auto n = static_cast<int>(geometry->getComponents().size());
        std::ostringstream uncovered;
        for (int i = 1; i <= n; ++i) {
            if (!componentOwner.contains(i)) {
                if (uncovered.tellp() > 0) {
                    uncovered << ", ";
                }
                uncovered << "Component" << i;
            }
        }
        if (uncovered.tellp() > 0) {
            if (msg.tellp() > 0) {
                msg << "; ";
            }
            msg << "Uncovered components: " << uncovered.str();
            Base::Console().warning(
                "FemMeshShapeGroup '%s': uncovered components: %s\n",
                objectName(this),
                uncovered.str().c_str()
            );
        }

        // Soft adjacency warning: components on different mesh children that touch
        // share an interface that will not be welded — use tie/contact instead.
        const double tol = Precision::Confusion() * 10.0;

        // Collect the shapes and their bounding boxes once. The exact distance
        // computation below is expensive, so it is only reached for pairs whose
        // bounding boxes actually overlap.
        struct ComponentShapes
        {
            std::vector<TopoDS_Shape> shapes;
            std::vector<Bnd_Box> bounds;
        };
        std::map<int, ComponentShapes> componentShapes;
        for (const auto& [idx, mesh] : componentOwner) {
            ComponentShapes entry;
            // Component indices are 1-based; FemGeometry cache is 0-based.
            for (const auto& shape : geometry->getComponent(static_cast<componentIdType>(idx - 1))) {
                if (shape.isNull()) {
                    continue;
                }
                Bnd_Box box;
                BRepBndLib::Add(shape.getShape(), box);
                if (box.IsVoid()) {
                    continue;
                }
                box.Enlarge(tol);
                entry.shapes.push_back(shape.getShape());
                entry.bounds.push_back(box);
            }
            if (!entry.shapes.empty()) {
                componentShapes.emplace(idx, std::move(entry));
            }
        }

        std::vector<int> indices;
        indices.reserve(componentOwner.size());
        for (const auto& [idx, mesh] : componentOwner) {
            indices.push_back(idx);
        }
        for (std::size_t i = 0; i < indices.size(); ++i) {
            for (std::size_t j = i + 1; j < indices.size(); ++j) {
                const int a = indices[i];
                const int b = indices[j];
                const auto* meshA = componentOwner.at(a);
                const auto* meshB = componentOwner.at(b);
                if (!meshA || !meshB || meshA == meshB) {
                    continue;
                }
                auto itA = componentShapes.find(a);
                auto itB = componentShapes.find(b);
                if (itA == componentShapes.end() || itB == componentShapes.end()) {
                    continue;
                }

                bool adjacent = false;
                for (std::size_t sa = 0; sa < itA->second.shapes.size() && !adjacent; ++sa) {
                    for (std::size_t sb = 0; sb < itB->second.shapes.size(); ++sb) {
                        if (itA->second.bounds[sa].IsOut(itB->second.bounds[sb])) {
                            continue;
                        }
                        BRepExtrema_DistShapeShape dist(itA->second.shapes[sa], itB->second.shapes[sb]);
                        if (dist.IsDone() && dist.Value() <= tol) {
                            adjacent = true;
                            break;
                        }
                    }
                }
                if (adjacent) {
                    Base::Console().warning(
                        "FemMeshShapeGroup '%s': Component%d (%s) and Component%d (%s) are "
                        "adjacent but meshed separately. Shared nodes are not welded; use a "
                        "tie or contact constraint at the interface.\n",
                        objectName(this),
                        a,
                        objectName(meshA),
                        b,
                        objectName(meshB)
                    );
                }
            }
        }
    }

    return msg.str();
}

App::DocumentObjectExecReturn* FemMeshShapeGroup::execute()
{
    // The Group link makes us a dependent of every child, so FreeCAD sends a
    // recompute for anything at all that happens to one - a mesher setting, a
    // label, a component assignment. Almost none of that changes the merge, and
    // the two requests are what the changes that do leave behind. Everything
    // else stops here, at the cost of two bools.
    if (!m_meshRebuildRequested && !m_topologyRebuildRequested) {
        return StdReturn;
    }

    // A child that only moved keeps the merge it is part of intact apart from
    // its coordinates, so the classification and the topology of the last full
    // merge are still the right answer and are left alone.
    if (!m_topologyRebuildRequested && rebuildPlacementOnly()) {
        return StdReturn;
    }

    bool overlap = false;
    const std::string msg = validateComponents(&overlap);
    if (overlap) {
        // Two children meshing the same component would merge into a mesh with
        // the geometry in it twice. Publishing nothing is what says so; leaving
        // the previous merge up would show a mesh that no longer follows from
        // the children, and the request stays open so a corrected assignment
        // still rebuilds.
        clearMergedOutput();
        return new App::DocumentObjectExecReturn(msg.c_str());
    }

    rebuildFull();
    return StdReturn;
}

const ::Fem::FemMesh& FemMeshShapeGroup::getMergedMesh() const
{
    return FemMesh.getValue();
}

std::vector<FemMeshObject*> FemMeshShapeGroup::sortedChildren() const
{
    std::vector<FemMeshObject*> children;
    const auto& values = Group.getValues();
    children.reserve(values.size());
    for (auto* obj : values) {
        if (auto* meshObj = Base::freecad_cast<FemMeshObject*>(obj)) {
            children.push_back(meshObj);
        }
    }

    // Deterministic merge order so that CellSources and the merged element ids
    // do not depend on the order the children were added in.
    std::sort(
        children.begin(),
        children.end(),
        [](const FemMeshObject* a, const FemMeshObject* b) {
            const char* na = a->getNameInDocument();
            const char* nb = b->getNameInDocument();
            return std::string_view(na ? na : "") < std::string_view(nb ? nb : "");
        }
    );
    return children;
}

std::vector<FemMeshShapeGroup::ChildStamp>
FemMeshShapeGroup::stampsOf(const std::vector<FemMeshObject*>& children)
{
    std::vector<ChildStamp> stamps;
    stamps.reserve(children.size());
    for (const auto* meshObj : children) {
        ChildStamp stamp;
        const char* name = meshObj->getNameInDocument();
        stamp.name = name ? name : "";
        std::tie(stamp.nodes, stamp.elements) = meshCounts(meshObj->FemMesh.getValue());
        stamps.push_back(std::move(stamp));
    }
    return stamps;
}

Fem::FemMesh FemMeshShapeGroup::mergeChildren(
    const std::vector<FemMeshObject*>& children,
    std::vector<std::string>* sources,
    std::vector<int>* nodeIds
) const
{
    Fem::FemMesh merged;
    for (auto* meshObj : children) {
        const char* name = meshObj->getNameInDocument();
        // No transform override: appendMeshData applies the transform the child
        // carries, which its Placement wrote, and so places it in our frame.
        merged.appendMeshData(
            meshObj->FemMesh.getValue(),
            std::string(name ? name : ""),
            sources,
            nullptr,
            nullptr,
            nullptr,
            nullptr,
            nodeIds
        );
    }
    return merged;
}

void FemMeshShapeGroup::rebuildFull()
{
    FEM_PERF_SCOPE("merge");

    const auto children = sortedChildren();
    std::vector<std::string> sources;
    std::vector<int> nodeIds;
    Fem::FemMesh merged = mergeChildren(children, &sources, &nodeIds);

    {
        FEM_PERF_SCOPE("merge.properties");
        CellSources.setValues(sources);
    }

    FemGeometry* geometry = nullptr;
    if (auto* shapeObj = Shape.getValue()) {
        geometry = Base::freecad_cast<FemGeometry*>(shapeObj);
    }
    const auto classification = classifyDimensions(merged, sources, geometry);
    std::vector<long> dims;
    dims.reserve(classification.cellDimension.size());
    for (int d : classification.cellDimension) {
        dims.push_back(d);
    }
    std::map<std::string, std::string> entityMap;
    for (const auto& [name, dim] : classification.entityDimension) {
        entityMap[name] = std::to_string(dim);
    }
    {
        FEM_PERF_SCOPE("merge.properties");
        CellDimension.setValues(dims);
        EntityDimension.setValues(entityMap);
    }

    m_topology = buildMeshTopology(merged, classification);

    // After the topology, because that is what names them, and before the
    // property takes the mesh over.
    {
        FEM_PERF_SCOPE("merge.catchAllGroups");
        materialiseCatchAllGroups(merged);
    }

    // What the placement-only path has to find unchanged before it may reuse
    // any of the above, and the nodes it will write into.
    {
        FEM_PERF_SCOPE("merge.stamps");
        m_mergeInputs = stampsOf(children);
    }
    m_mergeNodeIds = std::move(nodeIds);

    // Bumped before the write, because the write is what tells the view to read
    // the merge back, and a view that recorded the old number there believes
    // the merge to be stale ever after and rebuilds its whole grid on the next
    // thing that asks it to look.
    ++m_mergeRevision;
    ++m_topologyRevision;

    // Moved, not copied: the property would otherwise build every node and
    // every element of it a second time, for a mesh this function is done with.
    // What is left in the scope is releasing the merge this one replaces.
    {
        FEM_PERF_SCOPE("merge.publish");
        FemMesh.setValue(std::move(merged));
    }

    m_meshRebuildRequested = false;
    m_topologyRebuildRequested = false;
}

bool FemMeshShapeGroup::rebuildPlacementOnly()
{
    // Reusing the last full merge only holds while the children still append the
    // same nodes and cells in the same order: same children, same names, same
    // counts. Then every merged node is still the node it was, every element
    // still stands on the same ones, and the groups, CellSources, dimensions
    // and topology all still describe the result. Anything else is not a move,
    // and the caller falls back to the full rebuild.
    if (m_mergeInputs.empty() || m_mergeNodeIds.empty()) {
        return false;
    }
    const auto children = sortedChildren();
    if (stampsOf(children) != m_mergeInputs) {
        return false;
    }
    std::size_t expected = 0;
    for (const auto& stamp : m_mergeInputs) {
        expected += static_cast<std::size_t>(stamp.nodes);
    }
    if (expected != m_mergeNodeIds.size()) {
        return false;
    }

    FEM_PERF_SCOPE("merge.placement");

    // Only where the nodes are has changed, so only that is written. Merging
    // the children again to move them would rebuild the whole mesh, and the
    // property would then build it once more when it took it over; neither is
    // work a rigid transform asks for.
    bool coherent = true;
    FemMesh.modifyValue([&](Fem::FemMesh& merged) {
        auto* mergedMesh = merged.getSMesh();
        SMESHDS_Mesh* mergedDS = mergedMesh ? mergedMesh->GetMeshDS() : nullptr;
        if (!mergedDS) {
            coherent = false;
            return;
        }

        std::size_t next = 0;
        for (auto* meshObj : children) {
            const Fem::FemMesh& childMesh = meshObj->FemMesh.getValue();
            const auto* childSMesh = childMesh.getSMesh();
            const SMESHDS_Mesh* childDS = childSMesh ? childSMesh->GetMeshDS() : nullptr;
            if (!childDS) {
                coherent = false;
                return;
            }

            const Base::Matrix4D trsf = childMesh.getTransform();
            const bool applyTrsf = (trsf != Base::Matrix4D());

            SMDS_NodeIteratorPtr nIt = childDS->nodesIterator();
            while (nIt->more()) {
                const SMDS_MeshNode* source = nIt->next();
                const SMDS_MeshNode* target = next < m_mergeNodeIds.size()
                    ? mergedDS->FindNode(m_mergeNodeIds[next])
                    : nullptr;
                ++next;
                if (!source || !target) {
                    coherent = false;
                    return;
                }

                double x = source->X();
                double y = source->Y();
                double z = source->Z();
                if (applyTrsf) {
                    Base::Vector3d p(x, y, z);
                    p = trsf * p;
                    x = p.x;
                    y = p.y;
                    z = p.z;
                }
                // The base version on purpose: the override records the move in
                // the SMESHDS journal, which nothing reads for a mesh derived
                // from the children and which would grow with every drag.
                mergedDS->SMDS_Mesh::MoveNode(target, x, y, z);
            }
        }
        if (next != m_mergeNodeIds.size()) {
            coherent = false;
        }
    });

    if (!coherent) {
        // The counts were checked before anything was written, so this is not
        // reachable by a change of the children; if it happens anyway the mesh
        // may be half moved, and returning false has the caller publish a whole
        // one over it in the same execute().
        return false;
    }

    ++m_mergeRevision;
    m_meshRebuildRequested = false;
    return true;
}

void FemMeshShapeGroup::clearMergedOutput()
{
    m_mergeInputs.clear();
    m_mergeNodeIds.clear();

    // The request stays open while the assignment is wrong, so a failing group
    // is executed again on every recompute. Republishing the same emptiness
    // each time would walk a view through a rebuild for nothing.
    const auto counts = meshCounts(FemMesh.getValue());
    if (CellSources.getSize() == 0 && counts.first == 0 && counts.second == 0) {
        return;
    }

    m_topology = MeshTopology();
    CellSources.setValues(std::vector<std::string>());
    CellDimension.setValues(std::vector<long>());
    EntityDimension.setValues(std::map<std::string, std::string>());

    ++m_mergeRevision;
    ++m_topologyRevision;
    FemMesh.setValue(Fem::FemMesh());
}

void FemMeshShapeGroup::materialiseCatchAllGroups(Fem::FemMesh& mesh) const
{
    // A catch-all names the top-dimension elements of a component that no group
    // claims. Derived, it exists only in the topology, and everything that reads
    // element names off the mesh itself -- the colouring of the view, references
    // into the mesh, the solver writers -- passes those elements by as unnamed.
    // Writing the group makes the derived name as real as one a mesher left
    // behind, so the leftovers of a component are addressable like anything else.
    static const std::map<int, const char*> typeOfDimension =
        {{3, "Volume"}, {2, "Face"}, {1, "Edge"}, {0, "Node"}};

    for (const auto& [name, elements] : m_topology.elementsOfToplevel) {
        if (elements.empty() || !isCatchAllGroupName(name)) {
            continue;
        }
        auto dim = m_topology.dimensionOfToplevel.find(name);
        if (dim == m_topology.dimensionOfToplevel.end()) {
            continue;
        }
        auto type = typeOfDimension.find(dim->second);
        if (type == typeOfDimension.end()) {
            continue;
        }
        try {
            const int gid = mesh.addGroup(type->second, name);
            mesh.addGroupElements(gid, std::set<int>(elements.begin(), elements.end()));
        }
        catch (const std::exception& e) {
            Base::Console().warning(
                "FemMeshShapeGroup: could not write catch-all group %s: %s\n",
                name.c_str(),
                e.what()
            );
        }
    }
}

const MeshTopology& FemMeshShapeGroup::getMeshTopology() const
{
    return m_topology;
}

std::vector<int> FemMeshShapeGroup::groupElementsByName(const std::string& name) const
{
    if (auto* smesh = const_cast<Fem::FemMesh&>(FemMesh.getValue()).getSMesh()) {
        for (int gid : smesh->GetGroupIds()) {
            SMESH_Group* group = smesh->GetGroup(gid);
            if (!group || !group->GetName() || name != group->GetName() || !group->GetGroupDS()) {
                continue;
            }
            std::vector<int> ids;
            SMDS_ElemIteratorPtr eIt = group->GetGroupDS()->GetElements();
            while (eIt->more()) {
                if (const SMDS_MeshElement* elem = eIt->next()) {
                    ids.push_back(elem->GetID());
                }
            }
            return ids;
        }
    }

    auto it = m_topology.elementsOfToplevel.find(name);
    if (it != m_topology.elementsOfToplevel.end()) {
        return it->second;
    }
    return {};
}

std::size_t FemMeshShapeGroup::componentCount() const
{
    return m_topology.componentCount();
}

std::vector<std::string> FemMeshShapeGroup::toplevelElements(componentIdType component) const
{
    if (component >= m_topology.componentToplevels.size()) {
        return {};
    }
    return m_topology.componentToplevels[component];
}

std::vector<std::string> FemMeshShapeGroup::entities(const std::string& toplevel) const
{
    auto it = m_topology.entitiesOfToplevel.find(toplevel);
    if (it == m_topology.entitiesOfToplevel.end()) {
        return {};
    }
    return it->second;
}

std::vector<std::string> FemMeshShapeGroup::entityOwners(const std::string& entity) const
{
    auto it = m_topology.ownersOfEntity.find(entity);
    if (it == m_topology.ownersOfEntity.end()) {
        return {};
    }
    return it->second;
}

int FemMeshShapeGroup::analysisDimension(const std::string& toplevel) const
{
    auto it = m_topology.dimensionOfToplevel.find(toplevel);
    if (it == m_topology.dimensionOfToplevel.end()) {
        return -1;
    }
    return it->second;
}

int FemMeshShapeGroup::entityDimensionMask(const std::string& entity) const
{
    auto it = m_topology.dimensionMaskOfEntity.find(entity);
    if (it == m_topology.dimensionMaskOfEntity.end()) {
        return 0;
    }
    return it->second;
}

std::size_t FemMeshShapeGroup::topologyRevision() const
{
    // Only the merges that reclassified. A child that moved republishes the
    // mesh under a new mergeRevision(), but names the same elements the same
    // way, and a classification stamped against this stays good across it.
    return m_topologyRevision;
}


PyObject* FemMeshShapeGroup::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        PythonObject = Py::Object(new FemMeshShapeGroupPy(this), true);
    }
    return Py::new_reference_to(PythonObject);
}


// Python feature ---------------------------------------------------------

namespace App
{

PROPERTY_SOURCE_TEMPLATE(Fem::FemMeshShapeGroupPython, Fem::FemMeshShapeGroup)

template<>
const char* Fem::FemMeshShapeGroupPython::getViewProviderName() const
{
    return "FemGui::ViewProviderFemMeshGroupPython";
}

template<>
PyObject* Fem::FemMeshShapeGroupPython::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        PythonObject = Py::asObject(new App::FeaturePythonPyT<Fem::FemMeshShapeGroupPy>(this));
    }
    return Py::new_reference_to(PythonObject);
}

template class FemExport FeaturePythonT<Fem::FemMeshShapeGroup>;

}  // namespace App
