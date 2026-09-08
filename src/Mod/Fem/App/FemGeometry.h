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

#include <App/FeaturePython.h>
#include <App/GeoFeature.h>
#include <App/PropertyStandard.h>
#include <Mod/Fem/FemGlobal.h>
#include <Mod/Part/App/PropertyTopoShape.h>

#include "FemTopology.h"

namespace Fem
{

/**
 * Analysis geometry container: Shape plus connected-component cache and
 * per-toplevel-element declared analysis dimension.
 *
 * The component and dimension caches are outputs of execute(), rebuilt from the
 * Shape whenever it changed. Assigning a Shape therefore only marks them stale;
 * they follow at the next recompute, which is what keeps a chain of geometry
 * operations from classifying every intermediate shape it writes.
 */
class FemExport FemGeometry: public App::GeoFeature, public AnalysisTopology
{
    PROPERTY_HEADER_WITH_OVERRIDE(Fem::FemGeometry);

public:
    FemGeometry();
    ~FemGeometry() override;

    Part::PropertyPartShape Shape;

    /**
     * Optional per-toplevel-element dimension overrides.
     * Keys are element names (e.g. "Face7", "Solid3"); values are "0"/"1"/"2"/"3".
     * Used for embedded shells/rebars whose dimension topology cannot infer.
     */
    App::PropertyMap DimensionOverride;

    /**
     * The step is behind what it was built from, and waits to be told to follow.
     *
     * A change to the CAD model reaches every step of an analysis geometry
     * through the dependency graph, and acting on it costs the user the whole
     * chain of booleans and every mesh made against the result. So a step that
     * is reached from outside keeps the Shape it has and says so here instead;
     * rebuilding is left to a deliberate update. Written by the step that
     * decided it - the import step for its own sources, the group as the union
     * over its members - and read by the view providers and by the commands
     * that offer the update.
     *
     * Output, so that saying it does not ask for another recompute, and saved,
     * because a geometry that was behind its model when the document was
     * closed is still behind it when the document is opened again.
     */
    App::PropertyBool Outdated;

    const char* getViewProviderName() const override
    {
        return "FemGui::ViewProviderFemGeometry";
    }

    void onChanged(const App::Property* prop) override;

    /// Rebuilds the component and dimension caches if the Shape has changed.
    App::DocumentObjectExecReturn* execute() override;

    /**
     * Restoring properties does not go through onChanged, so the component and
     * dimension caches have to be rebuilt explicitly after loading a document.
     */
    void onDocumentRestored() override;
    PyObject* getPyObject() override;

    void transformPlacement(const Base::Placement& transform) override;
    const App::PropertyComplexGeoData* getPropertyOfGeometry() const override;

    /**
     * SubShapes for a subname. ComponentN returns all shapes in that component;
     * Face/Edge/... returns a single shape.
     */
    std::vector<Part::TopoShape> getSubShapes(std::string subname) const;

    /**
     * Counter bumped every time the component cache is rebuilt.
     *
     * Lets a consumer that derives data from the element names of this geometry
     * tell that its own cache went stale. Reading this is O(1), where comparing
     * the toplevel names would cost about as much as rebuilding.
     */
    std::size_t revision() const
    {
        return m_revision;
    }

    // AnalysisTopology
    std::size_t componentCount() const override;
    std::vector<std::string> toplevelElements(componentIdType component) const override;
    std::vector<std::string> entities(const std::string& toplevel) const override;
    std::vector<std::string> entityOwners(const std::string& entity) const override;
    int analysisDimension(const std::string& toplevel) const override;
    int entityDimensionMask(const std::string& entity) const override;
    std::size_t topologyRevision() const override;

    std::vector<std::vector<Part::TopoShape>> getComponents() const;
    std::vector<Part::TopoShape> getComponent(componentIdType) const;
    std::vector<std::string> getToplevelElements(componentIdType component_idx) const;
    std::vector<std::string> getToplevelElements(std::vector<Part::TopoShape>& component) const;

    /**
     * Geometric dimension of a toplevel element from topology:
     * solid=3, free shell/face=2, free wire/edge=1, free vertex=0.
     * Returns -1 if the element is unknown.
     */
    int getGeometricDimension(const std::string& toplevel) const;

    /**
     * Analysis dimension: DimensionOverride if set, else getGeometricDimension.
     */
    int getAnalysisDimension(const std::string& toplevel) const;

    /**
     * Owners of an entity (e.g. Face7 owned by Solid3 and Solid4).
     * Empty if the entity is itself a toplevel free element.
     *
     * A toplevel that is not free is among its own owners: an embedded shell is
     * a face of the solid it was fused into and a model element in its own
     * right, and both have to be said or the shell is only ever heard of as the
     * solid's skin.
     */
    std::vector<std::string> getEntityOwners(const std::string& entity) const;

    /**
     * Dimension bitmask for export/display "highest" filtering (Stage 5b / Stage 6).
     * OR of (1 << analysisDim(owner)) over owners; free entities own themselves.
     * DimensionOverride on the entity itself is also OR'd in (embedded shell case).
     */
    int getEntityDimensionMask(const std::string& entity) const;

    App::DocumentObject* getSubObject(
        const char* subname,
        PyObject** pyObj = nullptr,
        Base::Matrix4D* pmat = nullptr,
        bool transform = true,
        int depth = 0
    ) const override;

private:
    void build_components();
    void rebuildDimensionCache();

    /// Set by a Shape assignment, cleared once execute() has caught up.
    bool m_topologyDirty {true};
    std::size_t m_revision {0};
    std::vector<std::vector<Part::TopoShape>> m_components_cache;
    std::map<std::string, int> m_geometric_dimension;           ///< toplevel -> dim
    std::map<std::string, std::vector<std::string>> m_entity_owners;  ///< entity -> owners
    std::map<std::string, std::vector<std::string>> m_entities_of_toplevel;  ///< toplevel -> entities
};

using FemGeometryPython = App::FeaturePythonT<FemGeometry>;

}  // namespace Fem
