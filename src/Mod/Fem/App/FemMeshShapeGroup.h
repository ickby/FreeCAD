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
 * Holds per-object mesh children (never listed in analysis.Group). The merged
 * FemMesh, its provenance and its topology are outputs of execute(), like the
 * Shape of any other feature; every getter here reads back what the last
 * execute() left behind and merges nothing of its own. The merged mesh stays
 * transient, so a document keeps only the child meshes and the group rebuilds
 * from them on restore. The container implements AnalysisTopology over the
 * result mesh.
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
     * The merged mesh as the last execute() published it.
     *
     * A pure read: it never merges. Children are merged sorted by Name, into
     * FemMesh, CellSources, CellDimension and EntityDimension. A caller that
     * has just changed an input has to recompute the document before the
     * change shows up here, as with any other output property.
     */
    const ::Fem::FemMesh& getMergedMesh() const;

    /**
     * Counter bumped every time the merged FemMesh is republished, including a
     * re-merge that only moved a child.
     *
     * The properties are written as outputs, so a view is told about the new
     * mesh, but a cache built from the merge still needs one number to compare
     * against rather than the mesh itself.
     */
    std::size_t mergeRevision() const
    {
        return m_mergeRevision;
    }

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

    const MeshTopology& getMeshTopology() const;
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

    /**
     * What the children contributed to the last full merge.
     *
     * The placement-only path reuses the element ids, groups and dimensions of
     * that merge, which only holds while the children still append the same
     * cells in the same order. Comparing this against the children of the
     * moment is what says whether that still holds; anything else falls back
     * to a full rebuild.
     */
    struct ChildStamp
    {
        std::string name;
        int nodes {0};
        int elements {0};

        bool operator==(const ChildStamp&) const = default;
    };

    ComponentClaims collectComponentClaims() const;
    void reconnectChildSignals();
    void slotChildChanged(const App::DocumentObject& obj, const App::Property& prop);
    std::string validateComponents(bool* hasOverlap = nullptr) const;
    void materialiseCatchAllGroups(Fem::FemMesh& mesh) const;

    /// Children of the group in merge order, which is sorted by internal Name.
    std::vector<FemMeshObject*> sortedChildren() const;
    static std::vector<ChildStamp> stampsOf(const std::vector<FemMeshObject*>& children);

    /// Merge the children into a mesh, applying their own transforms.
    Fem::FemMesh mergeChildren(
        const std::vector<FemMeshObject*>& children,
        std::vector<std::string>* sources
    ) const;

    void rebuildFull();
    bool rebuildPlacementOnly();
    void clearMergedOutput();

    /// Ask the next execute() for work, and make sure a recompute reaches it.
    void requestRebuild(bool withTopology);

    bool m_meshRebuildRequested {true};
    bool m_topologyRebuildRequested {true};
    std::size_t m_mergeRevision {0};
    std::size_t m_topologyRevision {0};
    MeshTopology m_topology;
    std::vector<ChildStamp> m_mergeInputs;
    std::map<const App::DocumentObject*, fastsignals::scoped_connection> m_childConns;
};

using FemMeshShapeGroupPython = App::FeaturePythonT<FemMeshShapeGroup>;

}  // namespace Fem
