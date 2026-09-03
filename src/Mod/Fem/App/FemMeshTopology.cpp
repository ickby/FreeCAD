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
# include <sstream>
# include <unordered_map>
#endif

#include <SMDS_MeshElement.hxx>
#include <SMDS_MeshNode.hxx>
#include <SMESHDS_GroupBase.hxx>
#include <SMESHDS_Mesh.hxx>
#include <SMESH_Group.hxx>
#include <SMESH_Mesh.hxx>

#include "FemMesh.h"
#include "FemMeshDimension.h"
#include "FemMeshTopology.h"
#include "FemPerfLog.h"

using namespace Fem;

namespace
{

int groupElementDimension(SMDSAbs_ElementType type)
{
    return smeshElementDimension(static_cast<int>(type));
}

}  // namespace

bool Fem::isCatchAllGroupName(const std::string& name)
{
    // ComponentN_Volume / _Surface / _Curve / _Point
    if (!name.starts_with("Component")) {
        return false;
    }
    const auto under = name.find('_');
    if (under == std::string::npos || under <= 9) {
        return false;
    }
    const auto number = name.substr(9, under - 9);
    if (number.empty()
        || !std::all_of(number.begin(), number.end(), [](unsigned char c) {
               return std::isdigit(c);
           })) {
        return false;
    }
    const auto suffix = name.substr(under + 1);
    return suffix == "Volume" || suffix == "Surface" || suffix == "Curve" || suffix == "Point";
}

const char* Fem::catchAllSuffix(int dimension)
{
    switch (dimension) {
        case 3:
            return "Volume";
        case 2:
            return "Surface";
        case 1:
            return "Curve";
        case 0:
            return "Point";
        default:
            return "Unknown";
    }
}

MeshTopology Fem::buildMeshTopology(
    const FemMesh& mesh,
    const DimensionClassification& classification
)
{
    FEM_PERF_SCOPE("merge.topology");

    MeshTopology result;

    SMESH_Mesh* smesh = const_cast<FemMesh&>(mesh).getSMesh();
    if (!smesh) {
        return result;
    }
    const SMESHDS_Mesh* meshDS = smesh->GetMeshDS();
    if (!meshDS) {
        return result;
    }

    const auto modelIds = classification.modelElementIds();
    if (modelIds.empty()) {
        return result;
    }

    // Stable candidate order: sorted model element IDs. Membership is asked for
    // once per element of every group below, so it is kept as a flat array over
    // the id range rather than looked up in the set each time.
    std::vector<int> candidates(modelIds.begin(), modelIds.end());
    std::sort(candidates.begin(), candidates.end());

    const auto elementIdRange = static_cast<std::size_t>(std::max(meshDS->MaxElementID(), 0)) + 1;

    // MaxNodeID() is only brought up to date when the mesh is compacted, and a
    // mesh that has just been merged never is, so it answers zero and the flat
    // lookups keyed by node below would reach nothing at all. Count the nodes
    // out instead; one pass over them is nothing beside what follows.
    std::size_t nodeIdRange = 1;
    for (SMDS_NodeIteratorPtr nIt = meshDS->nodesIterator(); nIt->more();) {
        const SMDS_MeshNode* node = nIt->next();
        if (node && node->GetID() >= 0) {
            nodeIdRange = std::max(nodeIdRange, static_cast<std::size_t>(node->GetID()) + 1);
        }
    }

    std::vector<char> isModelElement(elementIdRange, 0);
    for (int eid : candidates) {
        if (eid >= 0 && static_cast<std::size_t>(eid) < elementIdRange) {
            isModelElement[static_cast<std::size_t>(eid)] = 1;
        }
    }

    // Union-find over model elements joined by shared nodes. The element
    // pointers are kept, because every pass below walks the same candidates and
    // finding them again in the mesh is not free.
    std::vector<const SMDS_MeshElement*> candidateElement(candidates.size(), nullptr);
    ComponentUnion unions(candidates.size(), nodeIdRange);
    {
        FEM_PERF_SCOPE("merge.topology.unionFind");
        for (std::size_t i = 0; i < candidates.size(); ++i) {
            const SMDS_MeshElement* elem = meshDS->FindElement(candidates[i]);
            if (!elem) {
                continue;
            }
            candidateElement[i] = elem;

            // By index: nodesIterator() would allocate an iterator per element.
            const int nbNodes = elem->NbNodes();
            for (int k = 0; k < nbNodes; ++k) {
                const SMDS_MeshNode* node = elem->GetNode(k);
                if (node && node->GetID() >= 0) {
                    unions.shareKey(static_cast<std::size_t>(node->GetID()), i);
                }
            }
        }
    }

    std::vector<int> componentOfCandidate(candidates.size(), -1);
    for (std::size_t i = 0; i < candidates.size(); ++i) {
        const auto comp = static_cast<int>(unions.componentOf(i));
        componentOfCandidate[i] = comp;
        if (static_cast<std::size_t>(comp) >= result.componentElements.size()) {
            result.componentElements.resize(static_cast<std::size_t>(comp) + 1);
        }
        result.componentElements[static_cast<std::size_t>(comp)].push_back(candidates[i]);
    }
    result.componentToplevels.resize(result.componentElements.size());

    // Per-component max dimension (from model cellDimension).
    std::vector<int> componentDim(result.componentElements.size(), -1);
    for (std::size_t c = 0; c < result.componentElements.size(); ++c) {
        for (int eid : result.componentElements[c]) {
            if (eid >= 1
                && static_cast<std::size_t>(eid - 1) < classification.cellDimension.size()) {
                const int dim = classification.cellDimension[static_cast<std::size_t>(eid - 1)];
                if (dim > componentDim[c]) {
                    componentDim[c] = dim;
                }
            }
        }
    }

    // Which component a node belongs to, so a group can be placed by the nodes
    // its elements stand on. An entity group holds the skin of a solid, and
    // skin is not a model element, so element membership alone would place no
    // entity anywhere at all.
    std::vector<int> componentOfNode(nodeIdRange, -1);
    {
        FEM_PERF_SCOPE("merge.topology.componentOfNode");
        for (std::size_t i = 0; i < candidates.size(); ++i) {
            const SMDS_MeshElement* elem = candidateElement[i];
            if (!elem) {
                continue;
            }
            const int nbNodes = elem->NbNodes();
            for (int k = 0; k < nbNodes; ++k) {
                const SMDS_MeshNode* node = elem->GetNode(k);
                if (!node) {
                    continue;
                }
                const auto nid = static_cast<std::size_t>(node->GetID());
                if (nid < nodeIdRange && componentOfNode[nid] < 0) {
                    componentOfNode[nid] = componentOfCandidate[i];
                }
            }
        }
    }

    struct GroupInfo
    {
        std::string name;
        int dimension {-1};
        /// Elements of this group, split by the component they stand on. A
        /// group is not bound to one component: a user may collect elements
        /// across disconnected bodies, and each of those has to hear about it.
        std::map<int, std::vector<int>> byComponent;
        /// The subset of those that are model elements, which is what a
        /// toplevel claims and what a reference resolves to.
        std::map<int, std::vector<int>> modelByComponent;
    };
    std::vector<GroupInfo> groups;

    {
        FEM_PERF_SCOPE("merge.topology.readGroups");
        for (int gid : smesh->GetGroupIds()) {
            SMESH_Group* group = smesh->GetGroup(gid);
            if (!group || !group->GetGroupDS() || !group->GetName()) {
                continue;
            }
            GroupInfo info;
            info.name = group->GetName();
            if (isCatchAllGroupName(info.name)) {
                // The container writes catch-alls onto the merged mesh so the
                // leftovers of a component can be named like anything else, but
                // a catch-all is still whatever is left over after this build,
                // not before it. Reading one back would let the leftovers of an
                // earlier build, or of a deck imported from one, stand in for
                // elements they no longer cover, so they are always derived
                // again below.
                continue;
            }
            info.dimension = groupElementDimension(group->GetGroupDS()->GetType());
            if (info.dimension < 0) {
                continue;  // node groups carry no elements of their own
            }
            SMDS_ElemIteratorPtr eIt = group->GetGroupDS()->GetElements();
            while (eIt->more()) {
                const SMDS_MeshElement* elem = eIt->next();
                if (!elem || elem->GetType() == SMDSAbs_Node) {
                    continue;
                }
                const int eid = elem->GetID();

                int comp = -1;
                // By index: nodesIterator() would allocate an iterator per
                // element of every group, and the first node that knows its
                // component answers the question.
                const int nbNodes = elem->NbNodes();
                for (int k = 0; k < nbNodes && comp < 0; ++k) {
                    const SMDS_MeshNode* node = elem->GetNode(k);
                    if (!node) {
                        continue;
                    }
                    const auto nid = static_cast<std::size_t>(node->GetID());
                    if (nid < nodeIdRange) {
                        comp = componentOfNode[nid];
                    }
                }
                if (comp < 0) {
                    continue;
                }
                info.byComponent[comp].push_back(eid);
                if (eid >= 0 && static_cast<std::size_t>(eid) < elementIdRange
                    && isModelElement[static_cast<std::size_t>(eid)]) {
                    info.modelByComponent[comp].push_back(eid);
                }
            }
            if (!info.byComponent.empty()) {
                groups.push_back(std::move(info));
            }
        }
    }

    // A named group at the dimension of a component it touches is a toplevel
    // of that component. Anything below that dimension names part of one.
    // An element stands in one component only, so one flat array over the id
    // range says whether a toplevel has claimed it, whichever component it is.
    std::vector<char> claimed(elementIdRange, 0);

    for (const auto& group : groups) {
        result.componentOfGroup[group.name] = group.byComponent.begin()->first;
        for (const auto& [comp, ids] : group.modelByComponent) {
            const int cdim = componentDim[static_cast<std::size_t>(comp)];
            if (group.dimension != cdim) {
                continue;
            }
            result.componentToplevels[static_cast<std::size_t>(comp)].push_back(group.name);
            result.dimensionOfToplevel[group.name] = group.dimension;
            auto& owned = result.elementsOfToplevel[group.name];
            owned.insert(owned.end(), ids.begin(), ids.end());
            for (int eid : ids) {
                if (eid >= 0 && static_cast<std::size_t>(eid) < elementIdRange) {
                    claimed[static_cast<std::size_t>(eid)] = 1;
                }
            }
        }
    }

    // Catch-all toplevels for unclaimed top-dimension model elements.
    {
        FEM_PERF_SCOPE("merge.topology.catchAlls");
        for (std::size_t c = 0; c < result.componentElements.size(); ++c) {
            const int cdim = componentDim[c];
            if (cdim < 0) {
                continue;
            }
            std::vector<int> remainder;
            for (int eid : result.componentElements[c]) {
                if (eid >= 1
                    && static_cast<std::size_t>(eid - 1) < classification.cellDimension.size()
                    && classification.cellDimension[static_cast<std::size_t>(eid - 1)] == cdim
                    && static_cast<std::size_t>(eid) < elementIdRange
                    && !claimed[static_cast<std::size_t>(eid)]) {
                    remainder.push_back(eid);
                }
            }
            if (remainder.empty() && !result.componentToplevels[c].empty()) {
                continue;
            }
            // Always ensure at least one toplevel when the component has model elements.
            if (remainder.empty() && result.componentToplevels[c].empty()) {
                remainder = result.componentElements[c];
            }
            if (remainder.empty()) {
                continue;
            }
            std::ostringstream name;
            name << "Component" << (c + 1) << "_" << catchAllSuffix(cdim);
            const std::string catchAll = name.str();
            result.componentToplevels[c].push_back(catchAll);
            result.dimensionOfToplevel[catchAll] = cdim;
            result.componentOfGroup[catchAll] = static_cast<int>(c);
            result.elementsOfToplevel[catchAll] = std::move(remainder);
        }
    }

    // Sorted and deduplicated rather than a set: these hold the nodes of whole
    // toplevels, hundreds of thousands of them on a mesh of any size, and
    // filling a tree one node at a time is the bulk of what deriving the
    // topology costs. All that is asked of them afterwards is whether two of
    // them meet, which two sorted runs answer by walking together.
    auto nodesOf = [meshDS](const std::vector<int>& ids) {
        std::vector<int> nodes;
        for (int eid : ids) {
            const SMDS_MeshElement* elem = meshDS->FindElement(eid);
            if (!elem) {
                continue;
            }
            const int nbNodes = elem->NbNodes();
            for (int k = 0; k < nbNodes; ++k) {
                if (const SMDS_MeshNode* node = elem->GetNode(k)) {
                    nodes.push_back(node->GetID());
                }
            }
        }
        std::sort(nodes.begin(), nodes.end());
        nodes.erase(std::unique(nodes.begin(), nodes.end()), nodes.end());
        return nodes;
    };

    auto meet = [](const std::vector<int>& first, const std::vector<int>& second) {
        auto a = first.begin();
        auto b = second.begin();
        while (a != first.end() && b != second.end()) {
            if (*a < *b) {
                ++a;
            }
            else if (*b < *a) {
                ++b;
            }
            else {
                return true;
            }
        }
        return false;
    };

    std::map<std::string, std::vector<int>> nodesOfToplevel;
    {
        FEM_PERF_SCOPE("merge.topology.nodesOfToplevel");
        for (const auto& [name, ids] : result.elementsOfToplevel) {
            nodesOfToplevel[name] = nodesOf(ids);
        }
    }

    // An entity belongs to the toplevels it actually touches. Two materials on
    // one body are two toplevels of the same component, and a face between
    // them is not part of both.
    {
        FEM_PERF_SCOPE("merge.topology.entityOwners");
        for (const auto& group : groups) {
            for (const auto& [comp, ids] : group.byComponent) {
                const auto component = static_cast<std::size_t>(comp);
                const int cdim = componentDim[component];
                if (group.dimension == cdim) {
                    continue;  // toplevel, not an entity of another toplevel
                }
                const auto entityNodes = nodesOf(ids);
                for (const auto& toplevel : result.componentToplevels[component]) {
                    if (!meet(entityNodes, nodesOfToplevel[toplevel])) {
                        continue;
                    }
                    result.ownersOfEntity[group.name].push_back(toplevel);
                    result.entitiesOfToplevel[toplevel].push_back(group.name);
                }
                int mask = result.dimensionMaskOfEntity[group.name];
                if (group.dimension >= 0) {
                    mask |= (1 << group.dimension);
                }
                if (cdim >= 0) {
                    mask |= (1 << cdim);
                }
                result.dimensionMaskOfEntity[group.name] = mask;
            }
        }
    }

    // Free toplevels own themselves for dimension-mask queries.
    for (const auto& [name, dim] : result.dimensionOfToplevel) {
        if (!result.dimensionMaskOfEntity.contains(name) && dim >= 0) {
            result.dimensionMaskOfEntity[name] = (1 << dim);
        }
    }

    return result;
}
