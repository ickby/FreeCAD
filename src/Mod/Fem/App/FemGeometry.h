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

namespace Fem
{

using componentIdType = unsigned int;

/**
 * Analysis geometry container: Shape plus connected-component cache and
 * per-toplevel-element declared analysis dimension.
 */
class FemExport FemGeometry: public App::GeoFeature
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

    const char* getViewProviderName() const override
    {
        return "FemGui::ViewProviderFemGeometry";
    }

    void onChanged(const App::Property* prop) override;

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

    std::vector<std::vector<Part::TopoShape>> m_components_cache;
    std::map<std::string, int> m_geometric_dimension;           ///< toplevel -> dim
    std::map<std::string, std::vector<std::string>> m_entity_owners;  ///< entity -> owners
};

using FemGeometryPython = App::FeaturePythonT<FemGeometry>;

}  // namespace Fem
