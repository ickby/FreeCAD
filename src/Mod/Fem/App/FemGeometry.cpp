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
# include <sstream>
# include <TopExp_Explorer.hxx>
# include <TopoDS.hxx>
# include <TopoDS_Shape.hxx>
#endif

#include "FemGeometry.h"
#include "FemGeometryPy.h"

#include <App/FeaturePythonPyImp.h>
#include <Base/Console.h>
#include <Mod/Part/App/PartPyCXX.h>
#include <Mod/Part/App/ShapeMapHasher.h>

using namespace Fem;

PROPERTY_SOURCE(Fem::FemGeometry, App::GeoFeature)

namespace
{
constexpr char geom_separator = '.';
constexpr size_t component_prefix_len = 9;  // "Component"
}  // namespace

FemGeometry::FemGeometry()
{
    ADD_PROPERTY(Shape, (Part::TopoShape()));
    ADD_PROPERTY_TYPE(
        DimensionOverride,
        (),
        "FEM",
        App::Prop_None,
        "Per-toplevel-element analysis dimension overrides (key=element name, value=0..3)"
    );
}

FemGeometry::~FemGeometry() = default;

void FemGeometry::onChanged(const App::Property* prop)
{
    if (prop == &Shape) {
        build_components();
    }
    else if (prop == &DimensionOverride) {
        // analysis dimension is derived; nothing to rebuild except dependents
    }

    App::GeoFeature::onChanged(prop);
}

void FemGeometry::onDocumentRestored()
{
    build_components();
    App::GeoFeature::onDocumentRestored();
}

void FemGeometry::transformPlacement(const Base::Placement& transform)
{
    // Update Placement so sub_shape_at_global_placement resolves correctly.
    App::GeoFeature::transformPlacement(transform);
}

const App::PropertyComplexGeoData* FemGeometry::getPropertyOfGeometry() const
{
    return &Shape;
}

std::vector<Part::TopoShape> FemGeometry::getSubShapes(std::string subname) const
{
    auto path = std::stringstream(subname);
    std::string segment;
    std::vector<std::string> seglist;

    while (std::getline(path, segment, geom_separator)) {
        seglist.push_back(segment);
    }

    if (seglist.size() != 1) {
        return {};
    }

    if (seglist[0].starts_with("Component")) {
        // "Component" is 9 characters; Component1 -> index 0
        std::size_t number = 0;
        try {
            number = std::stoull(seglist[0].substr(component_prefix_len));
        }
        catch (const std::exception&) {
            return {};
        }
        if (number == 0) {
            return {};
        }
        auto components = getComponents();
        const auto component_idx = number - 1;
        if (component_idx >= components.size()) {
            return {};
        }
        return components[component_idx];
    }

    auto shape = Shape.getShape();
    return {shape.findShape(subname.c_str())};
}

App::DocumentObject* FemGeometry::getSubObject(
    const char* subname,
    PyObject** pyObj,
    Base::Matrix4D* pmat,
    bool transform,
    int depth
) const
{
    if (subname == nullptr) {
        return nullptr;
    }

    std::string substr(subname);

    if (substr.empty()) {
        return const_cast<FemGeometry*>(this);
    }

    if (substr.back() == '.') {
        return App::GeoFeature::getSubObject(subname, pyObj, pmat, transform, depth);
    }

    while (!substr.empty() && substr.front() == '.') {
        substr.erase(0, 1);
    }

    Base::Matrix4D _mat;
    auto& mat = pmat ? *pmat : _mat;
    if (transform) {
        mat *= Placement.getValue().toMatrix();
    }

    if (!pyObj) {
        return const_cast<FemGeometry*>(this);
    }

    auto sub = getSubShapes(substr);
    if (sub.empty()) {
        return nullptr;
    }

    if (sub.size() == 1) {
        *pyObj = Py::new_reference_to(shape2pyshape(sub[0]));
    }
    else {
        // Multiple shapes (ComponentN): return a compound
        Part::TopoShape compound;
        compound.makeCompound(sub);
        *pyObj = Py::new_reference_to(shape2pyshape(compound));
    }
    return const_cast<FemGeometry*>(this);
}

namespace
{
struct Component
{
    std::set<std::size_t> vertices;
    std::vector<Part::TopoShape> shapes;
};

int dimensionOfShapeType(TopAbs_ShapeEnum type)
{
    switch (type) {
        case TopAbs_SOLID:
        case TopAbs_COMPSOLID:
            return 3;
        case TopAbs_SHELL:
        case TopAbs_FACE:
            return 2;
        case TopAbs_WIRE:
        case TopAbs_EDGE:
            return 1;
        case TopAbs_VERTEX:
            return 0;
        default:
            return -1;
    }
}
}  // namespace

void FemGeometry::build_components()
{
    m_components_cache.clear();
    m_geometric_dimension.clear();
    m_entity_owners.clear();

    auto& shape = Shape.getShape();
    if (shape.isNull()) {
        return;
    }

    // Bottom-up: collect free candidates, group by shared vertices.
    // Do not use Part::TopoShape::getSubShapes — too slow for large shapes.
    std::vector<TopoDS_Shape> free_candidate;

    TopExp_Explorer explorer(shape.getShape(), TopAbs_SOLID);
    for (; explorer.More(); explorer.Next()) {
        free_candidate.push_back(explorer.Current());
    }
    explorer.Init(shape.getShape(), TopAbs_SHELL, TopAbs_SOLID);
    for (; explorer.More(); explorer.Next()) {
        free_candidate.push_back(explorer.Current());
    }
    explorer.Init(shape.getShape(), TopAbs_FACE, TopAbs_SHELL);
    for (; explorer.More(); explorer.Next()) {
        free_candidate.push_back(explorer.Current());
    }
    explorer.Init(shape.getShape(), TopAbs_WIRE, TopAbs_FACE);
    for (; explorer.More(); explorer.Next()) {
        free_candidate.push_back(explorer.Current());
    }
    explorer.Init(shape.getShape(), TopAbs_EDGE, TopAbs_WIRE);
    for (; explorer.More(); explorer.Next()) {
        free_candidate.push_back(explorer.Current());
    }
    explorer.Init(shape.getShape(), TopAbs_VERTEX, TopAbs_EDGE);
    for (; explorer.More(); explorer.Next()) {
        free_candidate.push_back(explorer.Current());
    }

    std::vector<Component> components;
    Part::ShapeMapHasher hasher;
    for (auto& candidate : free_candidate) {
        int component_idx = -1;
        explorer.Init(candidate, TopAbs_VERTEX, TopAbs_SHAPE);
        std::set<std::size_t> candidate_vertices_indices;
        for (; explorer.More(); explorer.Next()) {
            auto hash = hasher(explorer.Current());
            if (component_idx < 0) {
                for (std::size_t i = 0; i < components.size(); ++i) {
                    if (components[i].vertices.contains(hash)) {
                        component_idx = static_cast<int>(i);
                        break;
                    }
                }
            }
            candidate_vertices_indices.insert(hash);
        }

        if (component_idx < 0) {
            components.push_back(
                Component {candidate_vertices_indices, std::vector<Part::TopoShape> {candidate}}
            );
        }
        else {
            auto& comp = components[static_cast<std::size_t>(component_idx)];
            comp.vertices.insert(
                candidate_vertices_indices.begin(),
                candidate_vertices_indices.end()
            );
            comp.shapes.push_back(candidate);
        }
    }

    for (auto& component : components) {
        m_components_cache.push_back(component.shapes);
    }

    rebuildDimensionCache();
}

void FemGeometry::rebuildDimensionCache()
{
    m_geometric_dimension.clear();
    m_entity_owners.clear();

    auto shape = Shape.getShape();
    if (shape.isNull()) {
        return;
    }

    // For each toplevel element, record geometric dimension and entity ownership.
    for (auto& component : m_components_cache) {
        for (const auto& name : getToplevelElements(component)) {
            auto sub = shape.findShape(name.c_str());
            if (sub.IsNull()) {
                continue;
            }
            int dim = dimensionOfShapeType(sub.ShapeType());
            // Shells/wires were expanded to faces/edges in getToplevelElements,
            // so names are Face/Edge/... — use the actual shape type.
            m_geometric_dimension[name] = dim;

            // Build entity ownership: a solid owns its faces/edges/vertices.
            if (dim == 3) {
                TopExp_Explorer ex(sub, TopAbs_FACE);
                for (; ex.More(); ex.Next()) {
                    auto idx = shape.findShape(ex.Current());
                    if (idx > 0) {
                        m_entity_owners["Face" + std::to_string(idx)].push_back(name);
                    }
                }
                ex.Init(sub, TopAbs_EDGE);
                for (; ex.More(); ex.Next()) {
                    auto idx = shape.findShape(ex.Current());
                    if (idx > 0) {
                        m_entity_owners["Edge" + std::to_string(idx)].push_back(name);
                    }
                }
                ex.Init(sub, TopAbs_VERTEX);
                for (; ex.More(); ex.Next()) {
                    auto idx = shape.findShape(ex.Current());
                    if (idx > 0) {
                        m_entity_owners["Vertex" + std::to_string(idx)].push_back(name);
                    }
                }
            }
            else if (dim == 2) {
                TopExp_Explorer ex(sub, TopAbs_EDGE);
                for (; ex.More(); ex.Next()) {
                    auto idx = shape.findShape(ex.Current());
                    if (idx > 0) {
                        m_entity_owners["Edge" + std::to_string(idx)].push_back(name);
                    }
                }
                ex.Init(sub, TopAbs_VERTEX);
                for (; ex.More(); ex.Next()) {
                    auto idx = shape.findShape(ex.Current());
                    if (idx > 0) {
                        m_entity_owners["Vertex" + std::to_string(idx)].push_back(name);
                    }
                }
            }
            else if (dim == 1) {
                TopExp_Explorer ex(sub, TopAbs_VERTEX);
                for (; ex.More(); ex.Next()) {
                    auto idx = shape.findShape(ex.Current());
                    if (idx > 0) {
                        m_entity_owners["Vertex" + std::to_string(idx)].push_back(name);
                    }
                }
            }
        }
    }
}

std::vector<std::vector<Part::TopoShape>> FemGeometry::getComponents() const
{
    return m_components_cache;
}

std::vector<Part::TopoShape> FemGeometry::getComponent(componentIdType id) const
{
    if (id >= m_components_cache.size()) {
        return {};
    }
    return m_components_cache[id];
}

std::vector<std::string> FemGeometry::getToplevelElements(
    std::vector<Part::TopoShape>& component
) const
{
    auto shape = Shape.getShape();
    std::vector<std::string> result;

    // findShape returns 0 for a sub-shape that is not part of Shape, which would
    // produce bogus names like "Face0". Skip those instead.
    for (auto& subshape : component) {
        auto type = subshape.shapeType();
        if (type == TopAbs_SHELL) {
            auto faces = subshape.getSubShapes(TopAbs_FACE);
            for (auto& face : faces) {
                auto idx = shape.findShape(face);
                if (idx > 0) {
                    result.push_back("Face" + std::to_string(idx));
                }
            }
        }
        else if (type == TopAbs_WIRE) {
            auto edges = subshape.getSubShapes(TopAbs_EDGE);
            for (auto& edge : edges) {
                auto idx = shape.findShape(edge);
                if (idx > 0) {
                    result.push_back("Edge" + std::to_string(idx));
                }
            }
        }
        else {
            auto idx = shape.findShape(subshape.getShape());
            if (idx > 0) {
                auto name = shape.shapeName(subshape.shapeType());
                result.push_back(name + std::to_string(idx));
            }
        }
    }

    return result;
}

std::vector<std::string> FemGeometry::getToplevelElements(componentIdType component_idx) const
{
    auto shapes = getComponent(component_idx);
    return getToplevelElements(shapes);
}

int FemGeometry::getGeometricDimension(const std::string& toplevel) const
{
    auto it = m_geometric_dimension.find(toplevel);
    if (it == m_geometric_dimension.end()) {
        return -1;
    }
    return it->second;
}

int FemGeometry::getAnalysisDimension(const std::string& toplevel) const
{
    const auto& overrides = DimensionOverride.getValue();
    auto oit = overrides.find(toplevel);
    if (oit != overrides.end() && !oit->second.empty()) {
        try {
            return std::stoi(oit->second);
        }
        catch (...) {
            Base::Console().warning(
                "FemGeometry: invalid DimensionOverride for '%s': '%s'\n",
                toplevel.c_str(),
                oit->second.c_str()
            );
        }
    }
    return getGeometricDimension(toplevel);
}

std::vector<std::string> FemGeometry::getEntityOwners(const std::string& entity) const
{
    auto it = m_entity_owners.find(entity);
    if (it == m_entity_owners.end()) {
        return {};
    }
    return it->second;
}

int FemGeometry::getEntityDimensionMask(const std::string& entity) const
{
    int mask = 0;
    auto owners = getEntityOwners(entity);
    if (owners.empty()) {
        // Free toplevel element (or unknown): the entity is its own owner.
        const int d = getAnalysisDimension(entity);
        if (d >= 0) {
            mask |= (1 << d);
        }
    }
    else {
        for (const auto& owner : owners) {
            const int d = getAnalysisDimension(owner);
            if (d >= 0) {
                mask |= (1 << d);
            }
        }
    }

    // Embedded shell / rebar: override on the entity itself, even when owned by a solid.
    const auto& overrides = DimensionOverride.getValue();
    auto oit = overrides.find(entity);
    if (oit != overrides.end() && !oit->second.empty()) {
        try {
            const int d = std::stoi(oit->second);
            if (d >= 0 && d <= 3) {
                mask |= (1 << d);
            }
        }
        catch (...) {
            Base::Console().warning(
                "FemGeometry: invalid DimensionOverride for '%s': '%s'\n",
                entity.c_str(),
                oit->second.c_str()
            );
        }
    }

    return mask;
}

PyObject* FemGeometry::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        PythonObject = Py::Object(new FemGeometryPy(this), true);
    }
    return Py::new_reference_to(PythonObject);
}

namespace App
{
/// @cond DOXERR
PROPERTY_SOURCE_TEMPLATE(Fem::FemGeometryPython, Fem::FemGeometry)
/// @endcond

template<>
const char* Fem::FemGeometryPython::getViewProviderName() const
{
    return "FemGui::ViewProviderFemGeometryPython";
}

template<>
PyObject* Fem::FemGeometryPython::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        PythonObject = Py::Object(new FeaturePythonPyT<Fem::FemGeometryPy>(this), true);
    }
    return Py::new_reference_to(PythonObject);
}

template class FemExport FeaturePythonT<Fem::FemGeometry>;

}  // namespace App
