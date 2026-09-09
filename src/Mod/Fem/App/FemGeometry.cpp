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
# include <numeric>
# include <sstream>
# include <unordered_map>
# include <TopExp_Explorer.hxx>
# include <TopoDS.hxx>
# include <TopoDS_Iterator.hxx>
# include <TopoDS_Shape.hxx>
#endif

#include "FemGeometry.h"
#include "FemGeometryPy.h"
#include "FemPerfLog.h"
#include "FemTopology.h"

#include <App/Document.h>
#include <App/ElementNamingUtils.h>
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
    ADD_PROPERTY_TYPE(
        Outdated,
        (false),
        "FEM",
        App::PropertyType(App::Prop_Output | App::Prop_ReadOnly),
        "The step is behind the geometry it was built from and waits for an update"
    );
}

FemGeometry::~FemGeometry() = default;

void FemGeometry::onChanged(const App::Property* prop)
{
    if (prop == &Shape) {
        // Only note it. Classifying here would run over every intermediate
        // shape a chain of operations writes on its way to the result, and
        // would answer a reader with a topology the document has not
        // recomputed to yet; execute() is where an output belongs.
        m_topologyDirty = true;
    }
    else if (prop == &DimensionOverride) {
        // analysis dimension is derived; nothing to rebuild except dependents
    }

    App::GeoFeature::onChanged(prop);
}

App::DocumentObjectExecReturn* FemGeometry::execute()
{
    if (m_topologyDirty) {
        build_components();
        m_topologyDirty = false;

        // The Shape was announced when it was written, which for a Python
        // geometry step is before this ran, so whoever drew it did so against
        // the topology of the shape before. Saying it again, now that the two
        // agree, is what lets a view colour what it has already drawn. The
        // property itself is untouched; only the notification is repeated.
        if (auto* doc = getDocument(); doc && !isRestoring()) {
            doc->signalChangedObject(*this, Shape);
        }
    }
    return App::DocumentObject::StdReturn;
}

void FemGeometry::onDocumentRestored()
{
    // The Shape is in the file; the caches derived from it are not. Rebuilding
    // them classifies a shape that is already there, which is a different and
    // far cheaper thing than rerunning the import or partition that made it.
    build_components();
    m_topologyDirty = false;
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
    // A mapped element name is answered by the shape itself, which is the only
    // thing that knows how the name maps onto the element it stands for. It has
    // to come first: the dots it carries are part of the name, and the split
    // below would read them as a path and find several segments where there is
    // one name.
    if (Data::isMappedElement(subname.c_str())) {
        auto mapped = Shape.getShape().getSubTopoShape(subname.c_str(), /*silent*/ true);
        if (mapped.isNull()) {
            return {};
        }
        return {mapped};
    }

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

    while (!substr.empty() && substr.front() == '.') {
        substr.erase(0, 1);
    }

    // Solid1, Face3, Component2: what this holds is named in one word. A dot
    // means the name runs on into a step of the chain below, and the group
    // extension is what knows the way there. Answering such a path with an
    // element of our own leaves whoever asked one object short of where they
    // clicked, and a picked face of a step reads as a face of the result.
    //
    // A mapped element name is the exception. It is one name however many dots
    // it carries, and it names an element of this shape, not a way down to a
    // step - which is exactly what makes it worth having: it survives a rebuild
    // of the chain, where Face7 becomes whichever face is seventh next time.
    // Read as a path it sends the lookup into a child that cannot exist, and
    // the answer is no object at all. Anything that asks for the unresolved
    // name of a picked face gets one of these, so the tools that measure or
    // attach to analysis geometry stand or fall here.
    if (!Data::isMappedElement(substr.c_str()) && substr.find('.') != std::string::npos) {
        return App::GeoFeature::getSubObject(substr.c_str(), pyObj, pmat, transform, depth);
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
    FEM_PERF_SCOPE("geometry.components");

    ++m_revision;
    m_components_cache.clear();
    m_geometric_dimension.clear();
    m_entity_owners.clear();
    m_entities_of_toplevel.clear();

    auto& shape = Shape.getShape();
    if (shape.isNull()) {
        return;
    }

    // The pieces the analysis is built from: the direct children of the Shape,
    // with the compounds holding them walked through.
    //
    // WHAT COUNTS AS A PIECE. A piece is something handed in to be analysed --
    // a solid, a shell, a loose face, a wire, a bar. It is emphatically not
    // "a shape contained in nothing else", and getting that backwards is the
    // trap this replaced. A shell fused into a solid is a face of that solid,
    // and a bar fused through one is an edge of it; being contained is exactly
    // what makes them interesting, and a rule that excluded contained shapes
    // would throw away every embedded element there is. What separates a piece
    // from the solid's own skin is not containment but provenance, and the
    // compound records provenance: the fuse leaves the pieces it was given as
    // the children of its result, and imprints their copies inside the shapes
    // they cut. So the children are the pieces, and nothing else is.
    //
    // HOW IT WALKS. Depth first over the children, in the order they were
    // built, descending only into compounds and compsolids -- which group
    // pieces without being pieces themselves -- and taking everything else as
    // it comes. Nesting is not a curiosity to guard against but the normal
    // shape of a chain: two import steps leave [Compound, Solid], and a
    // partition that cuts a solid leaves [Compound, Compound]. A Shape that is
    // no compound at all, which is what a single solid assigned from a script
    // is, is one piece and is taken whole.
    //
    // It is cheaper than the sweeps it replaces, which is worth having on a
    // shape of any size: those walked the whole shape once for every kind of
    // element they were looking for, down to its vertices, where this touches
    // the children and stops.
    //
    // A shell or a wire is kept as it stands rather than opened here;
    // getToplevelElements() is where they become the faces and edges the rest
    // of the analysis names them by.
    //
    // WHAT THIS ASKS OF THE PRODUCERS. Every step that writes a Shape has to
    // put the pieces in as children of it, and all of them do: an import
    // compounds what it brought in, a fuse hands back its result, a partition
    // compounds what it cut. A Shape that instead buries a piece inside another
    // shape would have that piece go unseen -- the boundary of what this can
    // know, and cheap to honour when writing a new step.
    std::vector<TopoDS_Shape> free_candidate;
    {
        std::vector<TopoDS_Shape> pending {shape.getShape()};
        while (!pending.empty()) {
            const TopoDS_Shape current = pending.back();
            pending.pop_back();
            if (current.IsNull()) {
                continue;
            }
            const TopAbs_ShapeEnum type = current.ShapeType();
            if (type != TopAbs_COMPOUND && type != TopAbs_COMPSOLID) {
                free_candidate.push_back(current);
                continue;
            }
            // Reversed, so that popping the stack hands the children back in
            // the order the step built them and the tree lists them that way.
            std::vector<TopoDS_Shape> children;
            for (TopoDS_Iterator it(current); it.More(); it.Next()) {
                children.push_back(it.Value());
            }
            pending.insert(pending.end(), children.rbegin(), children.rend());
        }
    }

    // A candidate can bridge candidates that were seen apart from each other, so
    // the components they were put in have to be joined when the bridge shows
    // up. Handing the bridge to the first component it touches would report two
    // components for geometry that shares topology and is therefore one.
    ComponentUnion candidate_union(free_candidate.size());
    Part::ShapeMapHasher hasher;
    TopExp_Explorer explorer;
    for (std::size_t i = 0; i < free_candidate.size(); ++i) {
        explorer.Init(free_candidate[i], TopAbs_VERTEX, TopAbs_SHAPE);
        for (; explorer.More(); explorer.Next()) {
            candidate_union.shareKey(hasher(explorer.Current()), i);
        }
    }

    for (std::size_t i = 0; i < free_candidate.size(); ++i) {
        auto component_idx = candidate_union.componentOf(i);
        if (component_idx >= m_components_cache.size()) {
            m_components_cache.emplace_back();
        }
        m_components_cache[component_idx].emplace_back(free_candidate[i]);
    }

    rebuildDimensionCache();
}

void FemGeometry::rebuildDimensionCache()
{
    FEM_PERF_SCOPE("geometry.dimensionCache");

    m_geometric_dimension.clear();
    m_entity_owners.clear();
    m_entities_of_toplevel.clear();

    auto shape = Shape.getShape();
    if (shape.isNull()) {
        return;
    }

    auto recordOwned = [this](const std::string& entity, const std::string& owner) {
        m_entity_owners[entity].push_back(owner);
        m_entities_of_toplevel[owner].push_back(entity);
    };

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
                        recordOwned("Face" + std::to_string(idx), name);
                    }
                }
                ex.Init(sub, TopAbs_EDGE);
                for (; ex.More(); ex.Next()) {
                    auto idx = shape.findShape(ex.Current());
                    if (idx > 0) {
                        recordOwned("Edge" + std::to_string(idx), name);
                    }
                }
                ex.Init(sub, TopAbs_VERTEX);
                for (; ex.More(); ex.Next()) {
                    auto idx = shape.findShape(ex.Current());
                    if (idx > 0) {
                        recordOwned("Vertex" + std::to_string(idx), name);
                    }
                }
            }
            else if (dim == 2) {
                TopExp_Explorer ex(sub, TopAbs_EDGE);
                for (; ex.More(); ex.Next()) {
                    auto idx = shape.findShape(ex.Current());
                    if (idx > 0) {
                        recordOwned("Edge" + std::to_string(idx), name);
                    }
                }
                ex.Init(sub, TopAbs_VERTEX);
                for (; ex.More(); ex.Next()) {
                    auto idx = shape.findShape(ex.Current());
                    if (idx > 0) {
                        recordOwned("Vertex" + std::to_string(idx), name);
                    }
                }
            }
            else if (dim == 1) {
                TopExp_Explorer ex(sub, TopAbs_VERTEX);
                for (; ex.More(); ex.Next()) {
                    auto idx = shape.findShape(ex.Current());
                    if (idx > 0) {
                        recordOwned("Vertex" + std::to_string(idx), name);
                    }
                }
            }
        }
    }

    // An embedded toplevel is one of its own owners. A shell fused into a solid
    // is a face of that solid and a model element in its own right at the same
    // time, and the loop above only ever hears the first of those: it records
    // what a toplevel owns, never that a toplevel is itself owned. Left at that,
    // the shell would answer to the solid alone, so the elements meshed on it
    // would read as the solid's skin, and the edges bounding it would be all
    // that the shell was ever seen to reach -- naming those edges 1D model
    // elements. A free toplevel is untouched and keeps the empty owner list
    // that is what says it is free.
    for (const auto& entry : m_geometric_dimension) {
        auto it = m_entity_owners.find(entry.first);
        if (it != m_entity_owners.end()) {
            it->second.push_back(entry.first);
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

std::size_t FemGeometry::componentCount() const
{
    return m_components_cache.size();
}

std::vector<std::string> FemGeometry::toplevelElements(componentIdType component) const
{
    return getToplevelElements(component);
}

std::vector<std::string> FemGeometry::entities(const std::string& toplevel) const
{
    auto it = m_entities_of_toplevel.find(toplevel);
    if (it == m_entities_of_toplevel.end()) {
        return {};
    }
    return it->second;
}

std::vector<std::string> FemGeometry::entityOwners(const std::string& entity) const
{
    return getEntityOwners(entity);
}

int FemGeometry::analysisDimension(const std::string& toplevel) const
{
    return getAnalysisDimension(toplevel);
}

int FemGeometry::entityDimensionMask(const std::string& entity) const
{
    return getEntityDimensionMask(entity);
}

std::size_t FemGeometry::topologyRevision() const
{
    return m_revision;
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
App::DocumentObjectExecReturn* Fem::FemGeometryPython::execute()
{
    // The proxy is what produces the Shape - an import, a partition, a group
    // passing on its last step - and the topology is derived from that Shape,
    // so it can only be finalised once the proxy has had its turn. Running both
    // inside one recompute is what leaves the geometry coherent at the point
    // every consumer looks at it.
    try {
        imp->execute();
    }
    catch (const Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    return Fem::FemGeometry::execute();
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
