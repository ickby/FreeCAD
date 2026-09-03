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

#include <map>
#include <string>
#include <vector>

#include <App/GroupExtension.h>
#include <App/PropertyStandard.h>

#include "FemMeshShapeObject.h"
#include "FemMeshTopology.h"
#include "FemTopology.h"


namespace Fem
{

/**
 * Mesh container for the preprocessing workflow.
 *
 * Holds per-object mesh children (never listed in analysis.Group). execute()
 * validates component assignment only; the merged FemMesh is built lazily by
 * getMergedMesh() and kept transient. The container implements AnalysisTopology
 * over the result mesh.
 */
class FemExport FemMeshShapeGroup: public FemMeshShapeBaseObject,
                                   public App::GroupExtension,
                                   public AnalysisTopology
{
    PROPERTY_HEADER_WITH_EXTENSIONS(Fem::FemMeshShapeGroup);

public:
    FemMeshShapeGroup();
    ~FemMeshShapeGroup() override;

    /**
     * Per-cell provenance after a merge: child object Name for each element,
     * indexed as elementId - 1. Transient / not persisted.
     */
    App::PropertyStringList CellSources;

    /**
     * Analysis dimension of each merged cell (elementId - 1), or -1 when the
     * cell is not part of the model (internal skin). Transient / not persisted.
     */
    App::PropertyIntegerList CellDimension;

    /**
     * Effective analysis dimension per entity group name (Solid1, Face7, …).
     * Transient / not persisted.
     */
    App::PropertyMap EntityDimension;

    const char* getViewProviderName() const override
    {
        return "FemGui::ViewProviderFemMeshGroup";
    }

    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;

    bool allowObject(App::DocumentObject* obj) override;

    /**
     * Build or return the cached merged mesh. Children are merged sorted by
     * Name. Fills the transient FemMesh property, CellSources, CellDimension
     * and EntityDimension.
     */
    const ::Fem::FemMesh& getMergedMesh();

    /** Ensure FemMesh holds a current merge (used by PropertyFemMesh lazy access). */
    void ensureMergedMesh();

    /**
     * Counter bumped on every merge.
     *
     * The merge fills FemMesh and CellSources without a property change - it is
     * a cache fill, not a user edit, and notifying would mark the document
     * modified. Anything caching what it read from the merge therefore has no
     * signal to react to and has to compare this instead.
     */
    std::size_t mergeRevision() const
    {
        return m_mergeRevision;
    }

    void invalidateMergedCache();

    /**
     * Object claiming each component of the geometry, by 1-based index.
     *
     * A child with an empty Components sub-list claims every component, which
     * is the "all components" convention of that property. Where more than one
     * child claims a component the first one in group order is reported; such
     * an overlap makes execute() fail.
     */
    std::map<int, App::DocumentObject*> getComponentOwners() const;

    // AnalysisTopology
    std::size_t componentCount() const override;
    std::vector<std::string> toplevelElements(componentIdType component) const override;
    std::vector<std::string> entities(const std::string& toplevel) const override;
    std::vector<std::string> entityOwners(const std::string& entity) const override;
    int analysisDimension(const std::string& toplevel) const override;
    int entityDimensionMask(const std::string& entity) const override;
    std::size_t topologyRevision() const override;

    const MeshTopology& getMeshTopology();
    std::vector<int> groupElementsByName(const std::string& name) const;

    PyObject* getPyObject() override;

protected:
    void onChanged(const App::Property* prop) override;
    void onDocumentRestored() override;

    /**
     * Hiding the group is left to the scene graph.
     *
     * A group would put every mesh out of sight by writing its Visibility,
     * which is what a container with no scene graph of its own has to do. The
     * meshes hang under this one in 3D, so switching it off already takes them
     * with it. Writing each of them would throw away what it was set to, and
     * since showing the group is what the mesh stage is, that would happen on
     * every switch of stage.
     */
    void extensionOnChanged(const App::Property* prop) override;

private:
    /// Component claims of the mesh children, the base of every coverage check.
    struct ComponentClaims
    {
        /// Geometry all children agree on, null if there is none to check
        FemGeometry* geometry {nullptr};
        /// 1-based component index -> child that claimed it first
        std::map<int, const FemMeshShapeBaseObject*> owner;
        /// Claims on a component that another child already owns
        std::vector<std::pair<int, const FemMeshShapeBaseObject*>> conflicts;
        /// Children link different geometries, which coverage cannot resolve
        bool mixedGeometry {false};
    };

    ComponentClaims collectComponentClaims() const;
    void reconnectChildSignals();
    void slotChildChanged(const App::DocumentObject& obj, const App::Property& prop);
    std::string validateComponents(bool* hasOverlap = nullptr) const;
    void materialiseCatchAllGroups(Fem::FemMesh& mesh) const;
    void rebuildMergedMesh();
    void ensureTopology() const;

    bool m_mergedValid {false};
    bool m_merging {false};
    std::size_t m_mergeRevision {0};
    mutable MeshTopology m_topology;
    mutable bool m_topologyValid {false};
    std::map<const App::DocumentObject*, fastsignals::scoped_connection> m_childConns;
};

using FemMeshShapeGroupPython = App::FeaturePythonT<FemMeshShapeGroup>;

}  // namespace Fem
