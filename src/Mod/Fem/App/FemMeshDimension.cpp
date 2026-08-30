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
# include <string_view>
#endif

#include <SMDS_MeshElement.hxx>
#include <SMDS_MeshNode.hxx>
#include <SMESHDS_GroupBase.hxx>
#include <SMESHDS_Mesh.hxx>
#include <SMESH_Group.hxx>
#include <SMESH_Mesh.hxx>

#include <Base/Console.h>

#include "FemGeometry.h"
#include "FemMesh.h"
#include "FemMeshDimension.h"

using namespace Fem;

namespace
{

/**
 * True when some element of ownerType contains every node of elem.
 * Cost is proportional to the elements adjacent to elem's first node.
 */
bool isSubElementOf(const SMDS_MeshElement* elem, SMDSAbs_ElementType ownerType)
{
    if (!elem) {
        return false;
    }
    const int nbNodes = elem->NbNodes();
    if (nbNodes < 1) {
        return false;
    }
    const SMDS_MeshNode* first = elem->GetNode(0);
    if (!first) {
        return false;
    }

    SMDS_ElemIteratorPtr ownerIt = first->GetInverseElementIterator(ownerType);
    while (ownerIt->more()) {
        const SMDS_MeshElement* owner = ownerIt->next();
        if (!owner || owner == elem) {
            continue;
        }
        bool containsAll = true;
        for (int i = 1; i < nbNodes; ++i) {
            const SMDS_MeshNode* node = elem->GetNode(i);
            if (!node || owner->GetNodeIndex(node) < 0) {
                containsAll = false;
                break;
            }
        }
        if (containsAll) {
            return true;
        }
    }
    return false;
}

/**
 * Dimension of the structure elem belongs to, judged from topology alone.
 * Equal to the element's own dimension when nothing higher-dimensional
 * contains it, which is exactly the condition for keeping it as a model
 * element. A skin triangle of a tetrahedron answers 3, a free triangle 2.
 */
int topologyDimension(const SMDS_MeshElement* elem)
{
    switch (elem->GetType()) {
        case SMDSAbs_Volume:
            return 3;
        case SMDSAbs_Face:
            return isSubElementOf(elem, SMDSAbs_Volume) ? 3 : 2;
        case SMDSAbs_Edge:
            if (isSubElementOf(elem, SMDSAbs_Volume)) {
                return 3;
            }
            return isSubElementOf(elem, SMDSAbs_Face) ? 2 : 1;
        case SMDSAbs_0DElement:
            if (isSubElementOf(elem, SMDSAbs_Volume)) {
                return 3;
            }
            if (isSubElementOf(elem, SMDSAbs_Face)) {
                return 2;
            }
            return isSubElementOf(elem, SMDSAbs_Edge) ? 1 : 0;
        default:
            return -1;
    }
}

int maxBitDimension(int mask)
{
    int dim = -1;
    for (int d = 0; d <= 3; ++d) {
        if (mask & (1 << d)) {
            dim = d;
        }
    }
    return dim;
}

}  // namespace

std::set<int> DimensionClassification::modelElementIds() const
{
    std::set<int> ids;
    for (std::size_t i = 0; i < cellDimension.size(); ++i) {
        if (cellDimension[i] >= 0) {
            ids.insert(static_cast<int>(i) + 1);
        }
    }
    return ids;
}

int Fem::effectiveAnalysisDimension(int declared, int achieved)
{
    if (achieved >= 0 && (declared < 0 || achieved < declared)) {
        return achieved;
    }
    return declared;
}

bool Fem::isEntityGroupName(const char* name)
{
    if (!name) {
        return false;
    }
    std::string_view n(name);
    std::string_view prefix;
    for (std::string_view candidate : {"Solid", "Face", "Edge", "Vertex"}) {
        if (n.starts_with(candidate)) {
            prefix = candidate;
            break;
        }
    }
    if (prefix.empty()) {
        return false;
    }
    const auto rest = n.substr(prefix.size());
    return !rest.empty()
        && std::all_of(rest.begin(), rest.end(), [](unsigned char c) { return std::isdigit(c); });
}

int Fem::smeshElementDimension(int smdsAbsType)
{
    switch (static_cast<SMDSAbs_ElementType>(smdsAbsType)) {
        case SMDSAbs_Volume:
            return 3;
        case SMDSAbs_Face:
            return 2;
        case SMDSAbs_Edge:
            return 1;
        case SMDSAbs_0DElement:
            return 0;
        default:
            return -1;
    }
}

DimensionClassification Fem::classifyDimensions(
    const FemMesh& mesh,
    const std::vector<std::string>& cellSources,
    const FemGeometry* geometry
)
{
    DimensionClassification result;
    SMESH_Mesh* smesh = const_cast<FemMesh&>(mesh).getSMesh();
    if (!smesh) {
        return result;
    }
    const SMESHDS_Mesh* meshDS = smesh->GetMeshDS();
    if (!meshDS) {
        return result;
    }

    // Element id -> entity group name from Solid*/Face*/Edge*/Vertex* groups.
    // Groups are always scanned: provenance alone does not name entities.
    std::map<int, std::string> elemEntity;
    for (int gid : smesh->GetGroupIds()) {
        SMESH_Group* group = smesh->GetGroup(gid);
        if (!group || !group->GetGroupDS() || !group->GetName()) {
            continue;
        }
        if (!isEntityGroupName(group->GetName())) {
            continue;
        }
        SMDS_ElemIteratorPtr eIt = group->GetGroupDS()->GetElements();
        while (eIt->more()) {
            const SMDS_MeshElement* elem = eIt->next();
            if (elem && elem->GetType() != SMDSAbs_Node) {
                elemEntity[elem->GetID()] = group->GetName();
            }
        }
    }

    // Achieved dimension per (source, owner). Scoping by source is what lets
    // Solid1 be meshed 3D while a CompSolid neighbour sharing a face is meshed
    // 2D by a different mesh object.
    std::map<std::pair<std::string, std::string>, int> achievedOfOwner;
    if (geometry && !elemEntity.empty()) {
        for (const auto& [eid, entity] : elemEntity) {
            const SMDS_MeshElement* elem = meshDS->FindElement(eid);
            const int dim = elem ? smeshElementDimension(static_cast<int>(elem->GetType())) : -1;
            if (dim < 0) {
                continue;
            }
            std::string source;
            if (!cellSources.empty() && eid >= 1
                && static_cast<std::size_t>(eid - 1) < cellSources.size()) {
                source = cellSources[static_cast<std::size_t>(eid - 1)];
            }
            auto owners = geometry->getEntityOwners(entity);
            if (owners.empty()) {
                owners.push_back(entity);
            }
            for (const auto& owner : owners) {
                auto key = std::make_pair(source, owner);
                auto it = achievedOfOwner.find(key);
                if (it == achievedOfOwner.end() || dim > it->second) {
                    achievedOfOwner[key] = dim;
                }
            }
        }
    }

    std::map<std::string, int> maskOfEntity;
    auto entityMask = [&](const std::string& entity, const std::string& source) {
        // Cache key includes source so the same Face on two mesh objects can
        // keep different achieved dimensions.
        const std::string cacheKey = source + '\x1f' + entity;
        auto cached = maskOfEntity.find(cacheKey);
        if (cached != maskOfEntity.end()) {
            return cached->second;
        }
        int mask = 0;
        if (!geometry) {
            maskOfEntity[cacheKey] = 0;
            return 0;
        }
        auto owners = geometry->getEntityOwners(entity);
        if (owners.empty()) {
            owners.push_back(entity);
        }
        for (const auto& owner : owners) {
            int dim = geometry->getAnalysisDimension(owner);
            auto ait = achievedOfOwner.find(std::make_pair(source, owner));
            const int achieved = ait != achievedOfOwner.end() ? ait->second : -1;
            dim = effectiveAnalysisDimension(dim, achieved);
            if (dim >= 0 && dim <= 3) {
                mask |= (1 << dim);
            }
        }
        // Embedded shell / rebar: an override on the entity itself counts even
        // when the entity is owned by a solid.
        const auto& overrides = geometry->DimensionOverride.getValue();
        auto oit = overrides.find(entity);
        if (oit != overrides.end() && !oit->second.empty()) {
            try {
                int dim = std::stoi(oit->second);
                auto ait = achievedOfOwner.find(std::make_pair(source, entity));
                if (ait != achievedOfOwner.end()) {
                    dim = effectiveAnalysisDimension(dim, ait->second);
                }
                if (dim >= 0 && dim <= 3) {
                    mask |= (1 << dim);
                }
            }
            catch (const std::exception&) {
                Base::Console().warning(
                    "FemMeshDimension: invalid DimensionOverride for '%s': '%s'\n",
                    entity.c_str(),
                    oit->second.c_str()
                );
            }
        }
        maskOfEntity[cacheKey] = mask;
        return mask;
    };

    // Size cellDimension to the highest element id so indexing by id-1 is safe.
    // An id is smIdType, which is int against the bundled SMESH and 64 bit
    // against an external one, so the two cannot be handed to std::max
    // together and the comparison is spelled out instead.
    const auto highest = meshDS->MaxElementID();
    result.cellDimension.assign(highest > 0 ? static_cast<std::size_t>(highest) : 0, -1);

    auto raiseEntityDimension = [&result](const std::string& entity, int dim) {
        if (dim < 0) {
            return;
        }
        auto it = result.entityDimension.find(entity);
        if (it == result.entityDimension.end() || dim > it->second) {
            result.entityDimension[entity] = dim;
        }
    };

    SMDS_ElemIteratorPtr elemIt = meshDS->elementsIterator();
    while (elemIt->more()) {
        const SMDS_MeshElement* elem = elemIt->next();
        if (!elem || elem->GetType() == SMDSAbs_Node) {
            continue;
        }
        const int dim = smeshElementDimension(static_cast<int>(elem->GetType()));
        if (dim < 0) {
            continue;
        }
        const int eid = elem->GetID();
        std::string source;
        if (!cellSources.empty() && eid >= 1
            && static_cast<std::size_t>(eid - 1) < cellSources.size()) {
            source = cellSources[static_cast<std::size_t>(eid - 1)];
        }

        auto entity = elemEntity.find(eid);
        const int mask = (entity != elemEntity.end()) ? entityMask(entity->second, source) : 0;

        bool keep = false;
        int entityDim = -1;
        if (mask != 0) {
            keep = (mask & (1 << dim)) != 0;
            entityDim = maxBitDimension(mask);
        }
        else {
            // Nothing declared for this entity: decide from topology alone. The
            // dimension of the structure the element belongs to doubles as the
            // entity dimension, so a skin triangle still reports that its face
            // is owned by a solid.
            entityDim = topologyDimension(elem);
            keep = (entityDim == dim);
        }
        if (entity != elemEntity.end()) {
            raiseEntityDimension(entity->second, entityDim);
        }

        if (keep && eid >= 1) {
            result.cellDimension[static_cast<std::size_t>(eid - 1)] = dim;
        }
    }

    return result;
}
