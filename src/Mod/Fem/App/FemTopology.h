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

#pragma once

#include <cstddef>
#include <map>
#include <numeric>
#include <string>
#include <unordered_map>
#include <vector>

#include <Mod/Fem/FemGlobal.h>

namespace Fem
{

using componentIdType = unsigned int;

/**
 * Shared analysis-topology view of geometry or mesh.
 *
 * Both FemGeometry and FemMeshShapeGroup answer the same four questions:
 * components, toplevels per component, entities per toplevel, and dimension of
 * each. Consumers (view panel, selection, writers) talk only to this interface.
 *
 * Components are always derived, never persisted. Connectivity rule is the same
 * on both sides: share a vertex (geometry) or a node (mesh) => same component.
 */
class FemExport AnalysisTopology
{
public:
    virtual ~AnalysisTopology() = default;

    virtual std::size_t componentCount() const = 0;
    virtual std::vector<std::string> toplevelElements(componentIdType component) const = 0;
    virtual std::vector<std::string> entities(const std::string& toplevel) const = 0;
    virtual std::vector<std::string> entityOwners(const std::string& entity) const = 0;
    virtual int analysisDimension(const std::string& toplevel) const = 0;
    virtual int entityDimensionMask(const std::string& entity) const = 0;
    virtual std::size_t topologyRevision() const = 0;
};

/**
 * Union-find over free candidates joined by a shared key (vertex hash or node id).
 *
 * Extracted from FemGeometry so the mesh-side component analysis reuses the
 * same algorithm and numbering convention (smaller index stays the root).
 */
class FemExport ComponentUnion
{
public:
    /**
     * @param count     How many candidates there are.
     * @param keyRange  One past the largest key shareKey() will be given, when
     *                  the keys are dense small numbers. A mesh joins by node
     *                  id and has millions of those to look up, and finding
     *                  them in an array rather than a hash map is most of what
     *                  the join costs. Zero leaves every key to the map, which
     *                  is what a hashed key needs.
     */
    explicit ComponentUnion(std::size_t count, std::size_t keyRange = 0)
        : m_parent(count)
        , m_ownerOfKey(keyRange, npos)
    {
        std::iota(m_parent.begin(), m_parent.end(), static_cast<std::size_t>(0));
    }

    /// Put the candidates that share key @a hash in the same component.
    void shareKey(std::size_t hash, std::size_t candidate)
    {
        if (hash < m_ownerOfKey.size()) {
            std::size_t& owner = m_ownerOfKey[hash];
            if (owner == npos) {
                owner = candidate;
            }
            else {
                join(candidate, owner);
            }
            return;
        }
        auto [it, inserted] = m_owner.try_emplace(hash, candidate);
        if (!inserted) {
            join(candidate, it->second);
        }
    }

    /// The component a candidate ended up in, numbered in candidate order.
    std::size_t componentOf(std::size_t candidate)
    {
        auto [it, inserted] = m_number.try_emplace(root(candidate), m_number.size());
        return it->second;
    }

private:
    std::size_t root(std::size_t candidate)
    {
        while (m_parent[candidate] != candidate) {
            m_parent[candidate] = m_parent[m_parent[candidate]];
            candidate = m_parent[candidate];
        }
        return candidate;
    }

    void join(std::size_t first, std::size_t second)
    {
        first = root(first);
        second = root(second);
        if (first != second) {
            // The smaller index stays the root, which keeps the components
            // numbered in the order their first candidate appears.
            m_parent[std::max(first, second)] = std::min(first, second);
        }
    }

    static constexpr std::size_t npos = static_cast<std::size_t>(-1);

    std::vector<std::size_t> m_parent;
    /// Owner per key when the keys are dense; empty when they are hashes.
    std::vector<std::size_t> m_ownerOfKey;
    std::unordered_map<std::size_t, std::size_t> m_owner;
    std::unordered_map<std::size_t, std::size_t> m_number;
};

}  // namespace Fem
