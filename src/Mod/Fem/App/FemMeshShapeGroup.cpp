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
#include <vector>

#include <BRepBndLib.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <Bnd_Box.hxx>
#include <Precision.hxx>
#include <TopoDS_Shape.hxx>

#include <App/Document.h>
#include <App/FeaturePythonPyImp.h>
#include <App/GeoFeaturePy.h>
#include <Base/Console.h>
#include <Base/Tools.h>
#include <Mod/Part/App/TopoShape.h>

#include "FemGeometry.h"
#include "FemMesh.h"
#include "FemMeshShapeGroup.h"
#include "FemMeshShapeGroupPy.h"


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

/**
 * Writes a property without emitting a change.
 *
 * A property signals its container from aboutToSetValue()/hasSetValue(), which
 * touches the object and records an undo entry. Detaching the property from its
 * container for the duration of the write suppresses both, which is what a
 * derived cache needs.
 */
class SilentPropertyWrite
{
public:
    explicit SilentPropertyWrite(App::Property& prop)
        : m_prop(prop)
        , m_container(prop.getContainer())
    {
        m_prop.setContainer(nullptr);
    }
    ~SilentPropertyWrite()
    {
        m_prop.setContainer(m_container);
    }

    SilentPropertyWrite(const SilentPropertyWrite&) = delete;
    SilentPropertyWrite& operator=(const SilentPropertyWrite&) = delete;

private:
    App::Property& m_prop;
    App::PropertyContainer* m_container;
};

}  // namespace

PROPERTY_SOURCE_WITH_EXTENSIONS(Fem::FemMeshShapeGroup, Fem::FemMeshShapeBaseObject)

FemMeshShapeGroup::FemMeshShapeGroup()
{
    GroupExtension::initExtension(this);

    // Merged mesh is rebuilt on demand; children are what get persisted.
    FemMesh.setStatus(App::Property::Transient, true);

    ADD_PROPERTY_TYPE(
        CellSources,
        (),
        "FEM Mesh",
        App::PropertyType(App::Prop_Transient | App::Prop_Output | App::Prop_Hidden),
        "Child object name for each merged cell (elementId - 1)"
    );
}

FemMeshShapeGroup::~FemMeshShapeGroup() = default;

bool FemMeshShapeGroup::allowObject(App::DocumentObject* obj)
{
    return obj && obj->isDerivedFrom<FemMeshObject>();
}

short FemMeshShapeGroup::mustExecute() const
{
    if (Group.isTouched() || Shape.isTouched()) {
        return 1;
    }
    for (auto* obj : Group.getValues()) {
        if (obj && obj->isTouched()) {
            return 1;
        }
    }
    return FemMeshShapeBaseObject::mustExecute();
}

void FemMeshShapeGroup::invalidateMergedCache()
{
    if (m_merging) {
        return;
    }
    m_mergedValid = false;
}

void FemMeshShapeGroup::reconnectChildSignals()
{
    m_childConns.clear();
    for (auto* obj : Group.getValues()) {
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        m_childConns[obj] = obj->signalChanged.connect(
            [this](const App::DocumentObject& o, const App::Property& p) {
                this->slotChildChanged(o, p);
            }
        );
    }
}

void FemMeshShapeGroup::slotChildChanged(const App::DocumentObject& obj, const App::Property& prop)
{
    auto* meshObj = Base::freecad_cast<FemMeshObject*>(&obj);
    if (!meshObj) {
        return;
    }
    if (&prop == &meshObj->FemMesh || &prop == &meshObj->Placement) {
        invalidateMergedCache();
        return;
    }
    auto* shapeBase = Base::freecad_cast<FemMeshShapeBaseObject*>(&obj);
    if (shapeBase && &prop == &shapeBase->Components) {
        invalidateMergedCache();
    }
}

void FemMeshShapeGroup::onChanged(const App::Property* prop)
{
    if (prop == &Group || prop == &Shape) {
        invalidateMergedCache();
        if (prop == &Group) {
            reconnectChildSignals();
        }
    }
    FemMeshShapeBaseObject::onChanged(prop);
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
    std::map<int, App::DocumentObject*> owners;
    for (const auto& [idx, mesh] : collectComponentClaims().owner) {
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
    // Validation only — merge happens lazily in getMergedMesh().
    bool overlap = false;
    const std::string msg = validateComponents(&overlap);
    if (overlap) {
        return new App::DocumentObjectExecReturn(msg.c_str());
    }
    return StdReturn;
}

void FemMeshShapeGroup::ensureMergedMesh()
{
    if (m_merging || m_mergedValid) {
        return;
    }
    rebuildMergedMesh();
}

const ::Fem::FemMesh& FemMeshShapeGroup::getMergedMesh()
{
    ensureMergedMesh();
    return FemMesh.getValue();
}

void FemMeshShapeGroup::rebuildMergedMesh()
{
    m_merging = true;

    Fem::FemMesh merged;
    std::vector<std::string> sources;

    std::vector<FemMeshObject*> children;
    children.reserve(Group.getValues().size());
    for (auto* obj : Group.getValues()) {
        if (auto* meshObj = Base::freecad_cast<FemMeshObject*>(obj)) {
            children.push_back(meshObj);
        }
    }
    // Deterministic merge order so that CellSources and the merged element ids
    // do not depend on the order the children were added in.
    auto safeName = [](const FemMeshObject* obj) {
        const char* name = obj->getNameInDocument();
        return std::string_view(name ? name : "");
    };
    std::sort(
        children.begin(),
        children.end(),
        [&safeName](const FemMeshObject* a, const FemMeshObject* b) {
            return safeName(a) < safeName(b);
        }
    );

    for (auto* meshObj : children) {
        merged.appendMeshData(meshObj->FemMesh.getValue(), std::string(safeName(meshObj)), &sources);
    }

    // The merge is a cache fill derived from the children, not a user edit.
    // Reading .FemMesh must therefore neither mark the object touched (which
    // would mark the document modified) nor add an undo entry.
    {
        SilentPropertyWrite silentMesh(FemMesh);
        SilentPropertyWrite silentSources(CellSources);
        FemMesh.setValue(merged);
        CellSources.setValues(sources);
    }
    m_mergedValid = true;
    m_merging = false;
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
