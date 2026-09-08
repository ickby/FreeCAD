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

#include <cstring>
#include <set>
#include <string>

#include <SMESHDS_Mesh.hxx>
#include <SMESH_Mesh.hxx>

#include "FemAnalysis.h"
#include "FemAnalysisImport.h"
#include "FemGeometry.h"
#include "FemMesh.h"
#include "FemMeshShapeGroup.h"
#include "FemTools.h"

#include <App/ElementNamingUtils.h>
#include <Base/Parameter.h>
#include <Base/Tools.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/PartPyCXX.h>

PROPERTY_SOURCE(Fem::FemAnalysisImport, App::GeoFeature)

namespace
{

Fem::FemAnalysis* owningAnalysis(const App::DocumentObject* importObj)
{
    if (!importObj) {
        return nullptr;
    }
    std::set<const App::DocumentObject*> seen;
    std::vector<const App::DocumentObject*> pending = {importObj};
    while (!pending.empty()) {
        const App::DocumentObject* current = pending.back();
        pending.pop_back();
        for (auto* parent : current->getInList()) {
            if (!seen.insert(parent).second) {
                continue;
            }
            if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(parent)) {
                return analysis;
            }
            pending.push_back(parent);
        }
    }
    return nullptr;
}

Fem::FemMeshShapeGroup* meshGroupOf(const Fem::FemAnalysis* analysis)
{
    if (!analysis) {
        return nullptr;
    }
    for (auto* obj : analysis->Group.getValues()) {
        if (auto* meshGroup = Base::freecad_cast<Fem::FemMeshShapeGroup*>(obj)) {
            return meshGroup;
        }
    }
    return nullptr;
}

bool sourcePublishesMesh(const Fem::FemAnalysis* src)
{
    auto* meshGroup = meshGroupOf(src);
    if (!meshGroup) {
        return false;
    }
    if (const auto* smesh = meshGroup->getMergedMesh().getSMesh()) {
        if (const auto* meshDS = smesh->GetMeshDS()) {
            return meshDS->NbNodes() > 0;
        }
    }
    return false;
}

bool importsAnalysisRecursive(
    const Fem::FemAnalysis* start,
    const Fem::FemAnalysis* target,
    std::set<const Fem::FemAnalysis*>& visiting
)
{
    if (!start || !target) {
        return false;
    }
    if (start == target) {
        return true;
    }
    if (!visiting.insert(start).second) {
        return false;
    }
    for (auto* imp : Fem::Tools::analysisImports(start)) {
        if (auto* src = Base::freecad_cast<Fem::FemAnalysis*>(imp->Analysis.getValue())) {
            if (importsAnalysisRecursive(src, target, visiting)) {
                return true;
            }
        }
    }
    visiting.erase(start);
    return false;
}

}  // namespace

Fem::FemAnalysisImport::FemAnalysisImport()
{
    ADD_PROPERTY_TYPE(
        Analysis,
        (nullptr),
        "FEM Import",
        App::Prop_None,
        "Source analysis to import"
    );
    Analysis.setScope(App::LinkScope::Global);

    ADD_PROPERTY_TYPE(
        SuppressedComponents,
        (std::vector<long>()),
        "FEM Import",
        App::Prop_None,
        "1-based component indices from the source geometry to omit"
    );

    ADD_PROPERTY_TYPE(
        SuppressedMembers,
        (std::vector<std::string>()),
        "FEM Import",
        App::Prop_None,
        "Source analysis member names to omit"
    );

    ADD_PROPERTY_TYPE(
        SourceRevision,
        (0),
        "FEM Import",
        App::PropertyType(App::Prop_Output | App::Prop_Hidden | App::Prop_Transient),
        "Counter raised whenever this instance is recomputed"
    );

    ADD_PROPERTY_TYPE(
        SourceGeometryOutdated,
        (false),
        "FEM Import",
        App::PropertyType(App::Prop_Output | App::Prop_Hidden | App::Prop_Transient),
        "The geometry of the source analysis waits for an update"
    );

    ADD_PROPERTY_TYPE(
        SourceMeshMissing,
        (false),
        "FEM Import",
        App::PropertyType(App::Prop_Output | App::Prop_Hidden | App::Prop_Transient),
        "The source analysis publishes no mesh"
    );
}

Fem::FemAnalysisImport::~FemAnalysisImport() = default;

short Fem::FemAnalysisImport::mustExecute() const
{
    if (Analysis.isTouched() || SuppressedMembers.isTouched() || SuppressedComponents.isTouched()) {
        return 1;
    }
    // What the source analysis holds needs no asking after. The analysis keeps
    // its geometry, its mesh and its own instances in Group, so a change to any
    // of them travels up to it and on to us along the link, nested instances
    // included - which is more than reading the touched flag of the two
    // top-level ones ever caught.
    return App::GeoFeature::mustExecute();
}

App::DocumentObjectExecReturn* Fem::FemAnalysisImport::execute()
{
    // Raised before the checks below, so that a source that has gone away
    // reaches the view as well; what it draws is out of date either way.
    SourceRevision.setValue(SourceRevision.getValue() + 1);

    // Likewise before them: a source analysis without a mesh is precisely one
    // of the states worth marking, and the check for it returns further down.
    updateSourceMarkers();

    auto* src = Base::freecad_cast<Fem::FemAnalysis*>(Analysis.getValue());
    if (!src) {
        return new App::DocumentObjectExecReturn("Analysis import needs a source analysis", this);
    }

    if (src->getDocument() != getDocument()) {
        return new App::DocumentObjectExecReturn(
            "Cross-document analysis import is not supported yet",
            this
        );
    }

    if (auto* owner = owningAnalysis(this)) {
        if (src == owner) {
            return new App::DocumentObjectExecReturn("An analysis cannot import itself", this);
        }
        std::set<const Fem::FemAnalysis*> visiting;
        if (importsAnalysisRecursive(src, owner, visiting)) {
            return new App::DocumentObjectExecReturn("Analysis import would create a cycle", this);
        }
    }

    auto* srcGeom = Tools::getAnalysisGeometry(src);
    if (!srcGeom || srcGeom->Shape.getValue().IsNull()) {
        return new App::DocumentObjectExecReturn(
            "Source analysis has no geometry to import",
            this
        );
    }

    if (!meshGroupOf(src)) {
        return new App::DocumentObjectExecReturn(
            "Source analysis has no mesh to import",
            this
        );
    }

    return App::DocumentObject::StdReturn;
}

void Fem::FemAnalysisImport::onDocumentRestored()
{
    App::GeoFeature::onDocumentRestored();
    updateSourceMarkers();
}

void Fem::FemAnalysisImport::updateSourceMarkers()
{
    auto* src = Base::freecad_cast<Fem::FemAnalysis*>(Analysis.getValue());

    bool outdated = false;
    if (src) {
        if (auto* geometry = Tools::getAnalysisGeometry(src)) {
            outdated = geometry->Outdated.getValue();
        }
        // What the source imports in turn is part of what it shows, so a stale
        // geometry two analyses down still reaches the one on screen. No
        // recursion is needed to find it: the source recomputes before the
        // analysis importing it, so its own instances have already answered.
        if (!outdated) {
            for (auto* imp : Tools::analysisImports(src)) {
                if (imp->SourceGeometryOutdated.getValue()) {
                    outdated = true;
                    break;
                }
            }
        }
    }

    SourceGeometryOutdated.setValue(outdated);
    SourceMeshMissing.setValue(src && !sourcePublishesMesh(src));
}

Fem::FemGeometry* Fem::FemAnalysisImport::sourceGeometry() const
{
    auto* src = Base::freecad_cast<Fem::FemAnalysis*>(Analysis.getValue());
    return Tools::getAnalysisGeometry(src);
}

const Fem::FemMesh& Fem::FemAnalysisImport::sourceMesh() const
{
    auto* src = Base::freecad_cast<Fem::FemAnalysis*>(Analysis.getValue());
    if (auto* meshGroup = meshGroupOf(src)) {
        // The merge the source group last published. Nothing is forced here:
        // the source analysis recomputes before an import that depends on it.
        return meshGroup->getMergedMesh();
    }
    m_emptyMesh = FemMesh();
    return m_emptyMesh;
}

Fem::FemAnalysisImport* Fem::FemAnalysisImport::nestedImportByName(const char* name) const
{
    if (!name || !*name) {
        return nullptr;
    }
    auto* src = Base::freecad_cast<Fem::FemAnalysis*>(Analysis.getValue());
    if (!src) {
        return nullptr;
    }
    for (auto* imp : Tools::analysisImports(src)) {
        const char* impName = imp->getNameInDocument();
        if (impName && std::strcmp(impName, name) == 0) {
            return imp;
        }
    }
    return nullptr;
}

App::DocumentObject* Fem::FemAnalysisImport::getSubObject(
    const char* subname,
    PyObject** pyObj,
    Base::Matrix4D* pmat,
    bool transform,
    int depth
) const
{
    while (subname && *subname == '.') {
        ++subname;
    }

    if (!subname || !*subname) {
        return App::GeoFeature::getSubObject(subname, pyObj, pmat, transform, depth);
    }

    if (Data::isMappedElement(subname)) {
        return App::GeoFeature::getSubObject(subname, pyObj, pmat, transform, depth);
    }

    const char* dot = strchr(subname, '.');
    FemAnalysisImport* nested = nullptr;
    if (dot) {
        std::string nestedName(subname, dot - subname);
        nested = nestedImportByName(nestedName.c_str());
        if (!nested) {
            return App::GeoFeature::getSubObject(subname, pyObj, pmat, transform, depth);
        }
    }

    Base::Matrix4D _mat;
    auto& mat = pmat ? *pmat : _mat;
    if (transform) {
        mat *= Placement.getValue().toMatrix();
    }

    if (nested) {
        // The placement of a nested instance sits inside this one, so it always
        // applies; only the placement of this instance is what *transform* gates.
        return nested->getSubObject(dot + 1, pyObj, &mat, true, depth + 1);
    }

    auto* srcGeom = sourceGeometry();
    if (!srcGeom || srcGeom->Shape.getValue().IsNull()) {
        return nullptr;
    }

    if (!pyObj) {
        return const_cast<FemAnalysisImport*>(this);
    }

    Part::TopoShape ts = shapeFromSource(subname, mat);
    if (ts.isNull()) {
        return nullptr;
    }
    *pyObj = Py::new_reference_to(shape2pyshape(ts));
    return const_cast<FemAnalysisImport*>(this);
}

Part::TopoShape Fem::FemAnalysisImport::placedSubShape(const char* subname) const
{
    Base::Matrix4D mat;
    return subShapeInFrame(subname, mat);
}

Part::TopoShape
Fem::FemAnalysisImport::subShapeInFrame(const char* subname, Base::Matrix4D& mat) const
{
    while (subname && *subname == '.') {
        ++subname;
    }
    mat *= Placement.getValue().toMatrix();

    if (subname && *subname) {
        if (const char* dot = std::strchr(subname, '.')) {
            std::string nestedName(subname, dot - subname);
            auto* nested = nestedImportByName(nestedName.c_str());
            if (!nested) {
                return {};
            }
            return nested->subShapeInFrame(dot + 1, mat);
        }
    }

    return shapeFromSource(subname, mat);
}

Part::TopoShape
Fem::FemAnalysisImport::shapeFromSource(const char* subname, const Base::Matrix4D& mat) const
{
    auto* srcGeom = sourceGeometry();
    if (!srcGeom || srcGeom->Shape.getValue().IsNull()) {
        return {};
    }

    try {
        Part::TopoShape ts(srcGeom->Shape.getShape());
        bool doTransform = mat != ts.getTransform();
        if (doTransform) {
            ts.setShape(ts.getShape().Located(TopLoc_Location()), false);
        }
        if (subname && *subname) {
            ts = ts.getSubTopoShape(subname, true);
        }
        if (doTransform && !ts.isNull()) {
            static int sCopy = -1;
            if (sCopy < 0) {
                ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(
                    "User parameter:BaseApp/Preferences/Mod/Part/General"
                );
                sCopy = hGrp->GetBool("CopySubShape", false) ? 1 : 0;
            }
            ts.transformShape(mat, sCopy != 0, true);
        }
        return ts;
    }
    catch (Standard_Failure&) {
        return {};
    }
}
