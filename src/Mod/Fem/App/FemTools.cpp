// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2015 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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


#include <QStandardPaths>
#include <QStringList>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_BezierCurve.hxx>
#include <Geom_BezierSurface.hxx>
#include <Geom_Line.hxx>
#include <Precision.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Dir.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>
#include <gp_Vec.hxx>

#include <algorithm>
#include <array>
#include <set>

#include <App/Application.h>
#include <App/DocumentObjectGroup.h>
#include <App/GeoFeature.h>
#include <App/PropertyLinks.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/PropertyTopoShape.h>
#include <Mod/Part/App/Tools.h>

#include "FemAnalysis.h"
#include "FemAnalysisImport.h"
#include "FemGeometry.h"
#include "FemMeshShapeGroup.h"
#include "FemTools.h"


Base::Vector3d Fem::Tools::getDirectionFromShape(const TopoDS_Shape& shape)
{
    gp_XYZ dir(0, 0, 0);

    // "Direction must be a planar face or linear edge"
    //
    if (shape.ShapeType() == TopAbs_FACE) {
        if (isPlanar(TopoDS::Face(shape))) {
            dir = getDirection(TopoDS::Face(shape));
        }
    }
    else if (shape.ShapeType() == TopAbs_EDGE) {
        if (isLinear(TopoDS::Edge(shape))) {
            dir = getDirection(TopoDS::Edge(shape));
        }
    }

    Base::Vector3d the_direction(dir.X(), dir.Y(), dir.Z());
    return the_direction;
}

bool Fem::Tools::isPlanar(const TopoDS_Face& face)
{
    BRepAdaptor_Surface surface(face);
    if (surface.GetType() == GeomAbs_Plane) {
        return true;
    }
    else if (surface.GetType() == GeomAbs_BSplineSurface) {
        Handle(Geom_BSplineSurface) spline = surface.BSpline();
        try {
            TColgp_Array2OfPnt poles(1, spline->NbUPoles(), 1, spline->NbVPoles());
            spline->Poles(poles);

            // get the plane from three control points
            gp_Pnt p1 = poles(poles.LowerRow(), poles.LowerCol());
            gp_Pnt p2 = poles(poles.UpperRow(), poles.LowerCol());
            gp_Pnt p3 = poles(poles.LowerRow(), poles.UpperCol());
            gp_Vec vec1(p1, p2);
            gp_Vec vec2(p1, p3);
            gp_Vec vec3 = vec1.Crossed(vec2);
            gp_Pln plane(p1, gp_Dir(vec3));

            for (int i = poles.LowerRow(); i <= poles.UpperRow(); i++) {
                for (int j = poles.LowerCol(); j < poles.UpperCol(); j++) {
                    // are control points coplanar?
                    const gp_Pnt& pole = poles(i, j);
                    Standard_Real dist = plane.Distance(pole);
                    if (dist > Precision::Confusion()) {
                        return false;
                    }
                }
            }

            return true;
        }
        catch (Standard_Failure&) {
            return false;
        }
    }
    else if (surface.GetType() == GeomAbs_BezierSurface) {
        Handle(Geom_BezierSurface) bezier = surface.Bezier();
        try {
            TColgp_Array2OfPnt poles(1, bezier->NbUPoles(), 1, bezier->NbVPoles());
            bezier->Poles(poles);

            // get the plane from three control points
            gp_Pnt p1 = poles(poles.LowerRow(), poles.LowerCol());
            gp_Pnt p2 = poles(poles.UpperRow(), poles.LowerCol());
            gp_Pnt p3 = poles(poles.LowerRow(), poles.UpperCol());
            gp_Vec vec1(p1, p2);
            gp_Vec vec2(p1, p3);
            gp_Vec vec3 = vec1.Crossed(vec2);
            gp_Pln plane(p1, gp_Dir(vec3));

            for (int i = poles.LowerRow(); i <= poles.UpperRow(); i++) {
                for (int j = poles.LowerCol(); j < poles.UpperCol(); j++) {
                    // are control points coplanar?
                    const gp_Pnt& pole = poles(i, j);
                    Standard_Real dist = plane.Distance(pole);
                    if (dist > Precision::Confusion()) {
                        return false;
                    }
                }
            }

            return true;
        }
        catch (Standard_Failure&) {
            return false;
        }
    }

    return false;
}

gp_XYZ Fem::Tools::getDirection(const TopoDS_Face& face)
{
    gp_XYZ dir(0, 0, 0);

    BRepAdaptor_Surface surface(face);
    if (surface.GetType() == GeomAbs_Plane) {
        dir = surface.Plane().Axis().Direction().XYZ();
    }
    else if (surface.GetType() == GeomAbs_BSplineSurface) {
        Handle(Geom_BSplineSurface) spline = surface.BSpline();
        try {
            TColgp_Array2OfPnt poles(1, spline->NbUPoles(), 1, spline->NbVPoles());
            spline->Poles(poles);

            // get the plane from three control points
            gp_Pnt p1 = poles(poles.LowerRow(), poles.LowerCol());
            gp_Pnt p2 = poles(poles.UpperRow(), poles.LowerCol());
            gp_Pnt p3 = poles(poles.LowerRow(), poles.UpperCol());
            gp_Vec vec1(p1, p2);
            gp_Vec vec2(p1, p3);
            gp_Vec vec3 = vec1.Crossed(vec2);
            gp_Pln plane(p1, gp_Dir(vec3));
            dir = plane.Axis().Direction().XYZ();
        }
        catch (Standard_Failure&) {
        }
    }
    else if (surface.GetType() == GeomAbs_BezierSurface) {
        Handle(Geom_BezierSurface) bezier = surface.Bezier();
        try {
            TColgp_Array2OfPnt poles(1, bezier->NbUPoles(), 1, bezier->NbVPoles());
            bezier->Poles(poles);

            // get the plane from three control points
            gp_Pnt p1 = poles(poles.LowerRow(), poles.LowerCol());
            gp_Pnt p2 = poles(poles.UpperRow(), poles.LowerCol());
            gp_Pnt p3 = poles(poles.LowerRow(), poles.UpperCol());
            gp_Vec vec1(p1, p2);
            gp_Vec vec2(p1, p3);
            gp_Vec vec3 = vec1.Crossed(vec2);
            gp_Pln plane(p1, gp_Dir(vec3));
            dir = plane.Axis().Direction().XYZ();
        }
        catch (Standard_Failure&) {
        }
    }

    return dir;
}

bool Fem::Tools::isLinear(const TopoDS_Edge& edge)
{
    BRepAdaptor_Curve curve(edge);
    if (curve.GetType() == GeomAbs_Line) {
        return true;
    }
    else if (curve.GetType() == GeomAbs_BSplineCurve) {
        Handle(Geom_BSplineCurve) spline = curve.BSpline();
        try {
            gp_Pnt s1 = spline->Pole(1);
            gp_Pnt sn = spline->Pole(spline->NbPoles());
            gp_Vec vec(s1, sn);
            gp_Lin line(s1, gp_Dir(vec));

            for (int i = 2; i < spline->NbPoles(); i++) {
                // are control points collinear?
                Standard_Real dist = line.Distance(spline->Pole(i));
                if (dist > Precision::Confusion()) {
                    return false;
                }
            }

            return true;
        }
        catch (Standard_Failure&) {
            return false;
        }
    }
    else if (curve.GetType() == GeomAbs_BezierCurve) {
        Handle(Geom_BezierCurve) bezier = curve.Bezier();
        try {
            gp_Pnt s1 = bezier->Pole(1);
            gp_Pnt sn = bezier->Pole(bezier->NbPoles());
            gp_Vec vec(s1, sn);
            gp_Lin line(s1, gp_Dir(vec));

            for (int i = 2; i < bezier->NbPoles(); i++) {
                // are control points collinear?
                Standard_Real dist = line.Distance(bezier->Pole(i));
                if (dist > Precision::Confusion()) {
                    return false;
                }
            }

            return true;
        }
        catch (Standard_Failure&) {
            return false;
        }
    }

    return false;
}

gp_XYZ Fem::Tools::getDirection(const TopoDS_Edge& edge)
{
    gp_XYZ dir(0, 0, 0);

    BRepAdaptor_Curve curve(edge);
    if (curve.GetType() == GeomAbs_Line) {
        dir = curve.Line().Direction().XYZ();
    }
    else if (curve.GetType() == GeomAbs_BSplineCurve) {
        Handle(Geom_BSplineCurve) spline = curve.BSpline();
        try {
            gp_Pnt s1 = spline->Pole(1);
            gp_Pnt sn = spline->Pole(spline->NbPoles());
            gp_Vec vec(s1, sn);
            gp_Lin line(s1, gp_Dir(vec));
            dir = line.Direction().XYZ();
        }
        catch (Standard_Failure&) {
        }
    }
    else if (curve.GetType() == GeomAbs_BezierCurve) {
        Handle(Geom_BezierCurve) bezier = curve.Bezier();
        try {
            gp_Pnt s1 = bezier->Pole(1);
            gp_Pnt sn = bezier->Pole(bezier->NbPoles());
            gp_Vec vec(s1, sn);
            gp_Lin line(s1, gp_Dir(vec));
            dir = line.Direction().XYZ();
        }
        catch (Standard_Failure&) {
        }
    }

    return dir;
}

// function to determine 3rd-party binaries used by the FEM WB
std::string Fem::Tools::checkIfBinaryExists(
    std::string prefSection,
    std::string prefBinaryName,
    std::string binaryName
)
{
    // if "Search in known binary directories" is set in the preferences, we ignore custom path
    auto paramPath = "User parameter:BaseApp/Preferences/Mod/Fem/" + prefSection;
    auto knownDirectoriesString = "UseStandard" + prefSection + "Location";
    ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(paramPath.c_str());
    bool knownDirectories = hGrp->GetBool(knownDirectoriesString.c_str(), true);

    if (knownDirectories) {
        // first check the environment paths, normally determined by the PATH environment variable
        // On Windows, the executable extensions(".exe" etc.) should be automatically appended
        QString executablePath = QStandardPaths::findExecutable(
            QString::fromLatin1(binaryName.c_str())
        );
        if (!executablePath.isEmpty()) {
            return executablePath.toStdString();
        }
        // check the folder of the FreeCAD binary
        else {
            auto appBinaryPath = App::Application::getHomePath() + "bin/";
            QStringList pathCandidates = {QString::fromLatin1(appBinaryPath.c_str())};
            QString executablePath = QStandardPaths::findExecutable(
                QString::fromLatin1(binaryName.c_str()),
                pathCandidates
            );
            if (!executablePath.isEmpty()) {
                return executablePath.toStdString();
            }
        }
    }
    else {
        auto binaryPathString = prefBinaryName + "BinaryPath";
        // use binary path from settings, fall back to system path if not defined
        auto binaryPath = hGrp->GetASCII(binaryPathString.c_str(), binaryName.c_str());
        QString executablePath = QStandardPaths::findExecutable(
            QString::fromLatin1(binaryPath.c_str())
        );
        if (!executablePath.isEmpty()) {
            return executablePath.toStdString();
        }
    }
    return "";
}

Base::Placement
Fem::Tools::getSubShapeGlobalLocation(const App::GeoFeature* feat, const TopoDS_Shape& sh)
{
    Base::Matrix4D matrix = Part::TopoShape::convert(sh.Location().Transformation());
    Base::Placement shPla {matrix};
    Base::Placement featlPlaInv = feat->Placement.getValue().inverse();
    Base::Placement shGlobalPla = feat->globalPlacement() * featlPlaInv * shPla;

    return shGlobalPla;
}

void Fem::Tools::setSubShapeGlobalLocation(const App::GeoFeature* feat, TopoDS_Shape& sh)
{
    Base::Placement pla = getSubShapeGlobalLocation(feat, sh);
    sh.Location(Part::Tools::fromPlacement(pla));
}

const Part::TopoShape* Fem::Tools::getFeatureShape(const App::DocumentObject* obj)
{
    // An instance stores no shape of its own; the one it places is the shape
    // the source analysis builds. Callers ask for it to size a symbol or to
    // tell a shape carrier from one without a shape, and both answers are the
    // same whether the instance has moved the shape or not.
    if (auto* imp = Base::freecad_cast<FemAnalysisImport*>(obj)) {
        auto* geom = imp->sourceGeometry();
        return geom ? &geom->Shape.getShape() : nullptr;
    }

    auto* prop = dynamic_cast<const Part::PropertyPartShape*>(
        App::GeoFeature::getPropertyOfGeometry(obj)
    );

    return prop ? &prop->getShape() : nullptr;
}

TopoDS_Shape
Fem::Tools::getFeatureSubShape(const App::GeoFeature* feat, const char* subName, bool silent)
{
    TopoDS_Shape sh;

    // A reference on an instance is a dotted path through the instances it
    // nests, which only the instance itself can follow.
    if (auto* imp = Base::freecad_cast<FemAnalysisImport*>(feat)) {
        Part::TopoShape placed = imp->placedSubShape(subName);
        if (placed.isNull()) {
            return sh;
        }
        sh = placed.getShape();
        // The path put the instance chain into the shape, so all that is left
        // is whatever places the outermost instance in the document.
        const Base::Placement outer = imp->globalPlacement() * imp->Placement.getValue().inverse();
        sh.Move(Part::Tools::fromPlacement(outer));
        return sh;
    }

    const Part::TopoShape* toposhape = getFeatureShape(feat);
    if (!toposhape || toposhape->isNull()) {
        return sh;
    }

    sh = toposhape->getSubShape(subName, silent);
    if (sh.IsNull()) {
        return sh;
    }

    setSubShapeGlobalLocation(feat, sh);

    return sh;
}

Fem::FemGeometry* Fem::Tools::getAnalysisGeometry(const App::DocumentObject* member)
{
    if (!member) {
        return nullptr;
    }

    auto geometryOf = [](const Fem::FemAnalysis* analysis) -> Fem::FemGeometry* {
        for (auto* obj : analysis->Group.getValues()) {
            if (auto* geometry = Base::freecad_cast<Fem::FemGeometry*>(obj)) {
                return geometry;
            }
        }
        return nullptr;
    };

    if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(member)) {
        return geometryOf(analysis);
    }

    for (auto* parent : member->getInList()) {
        if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(parent)) {
            if (analysis->hasObject(member)) {
                return geometryOf(analysis);
            }
        }
    }

    return nullptr;
}

std::vector<Fem::FemAnalysisImport*> Fem::Tools::analysisImports(const Fem::FemAnalysis* analysis)
{
    std::vector<Fem::FemAnalysisImport*> out;
    if (!analysis) {
        return out;
    }

    auto add = [&out](App::DocumentObject* obj) {
        if (auto* imp = Base::freecad_cast<Fem::FemAnalysisImport*>(obj)) {
            if (std::ranges::find(out, imp) == out.end()) {
                out.push_back(imp);
            }
        }
    };

    for (auto* obj : analysis->Group.getValues()) {
        if (!obj) {
            continue;
        }
        add(obj);
        if (auto* group = Base::freecad_cast<App::DocumentObjectGroup*>(obj)) {
            for (auto* child : group->Group.getValues()) {
                add(child);
            }
        }
    }

    return out;
}

namespace
{

void collectImportedComponents(
    const Fem::FemAnalysis* analysis,
    const std::string& prefix,
    std::vector<const Fem::FemAnalysisImport*>& chain,
    std::vector<std::pair<std::string, std::vector<std::string>>>& out
)
{
    for (auto* imp : Fem::Tools::analysisImports(analysis)) {
        if (std::ranges::find(chain, imp) != chain.end()) {
            continue;
        }
        const char* name = imp->getNameInDocument();
        const std::string path = prefix.empty() ? std::string(name ? name : "Import")
                                                : prefix + "." + (name ? name : "Import");

        if (auto* geom = imp->sourceGeometry()) {
            const auto suppressedValues = imp->SuppressedComponents.getValues();
            const std::set<long> suppressed(suppressedValues.begin(), suppressedValues.end());
            Fem::componentIdType componentId = 0;
            for (auto& component : geom->getComponents()) {
                ++componentId;
                if (suppressed.contains(static_cast<long>(componentId))) {
                    continue;
                }
                std::vector<std::string> elements;
                for (const auto& element : geom->getToplevelElements(component)) {
                    elements.push_back(path + "." + element);
                }
                out.emplace_back(
                    path + ".Component" + std::to_string(componentId),
                    std::move(elements)
                );
            }
        }

        if (auto* src = Base::freecad_cast<Fem::FemAnalysis*>(imp->Analysis.getValue())) {
            chain.push_back(imp);
            collectImportedComponents(src, path, chain, out);
            chain.pop_back();
        }
    }
}

}  // namespace

std::vector<std::pair<std::string, std::vector<std::string>>> Fem::Tools::importedComponents(
    const Fem::FemAnalysis* analysis
)
{
    std::vector<std::pair<std::string, std::vector<std::string>>> out;
    std::vector<const Fem::FemAnalysisImport*> chain;
    collectImportedComponents(analysis, {}, chain, out);
    return out;
}

Fem::FemMeshShapeGroup* Fem::Tools::getAnalysisMeshGroup(const Fem::FemAnalysis* analysis)
{
    if (!analysis) {
        return nullptr;
    }
    for (auto* obj : analysis->Group.getValues()) {
        if (auto* mesh = Base::freecad_cast<Fem::FemMeshShapeGroup*>(obj)) {
            return mesh;
        }
    }
    return nullptr;
}

namespace
{

std::set<std::string> suppressedToplevelNames(const Fem::FemAnalysisImport* imp)
{
    std::set<std::string> hidden;
    auto* geom = imp->sourceGeometry();
    if (!geom) {
        return hidden;
    }
    const auto suppressedValues = imp->SuppressedComponents.getValues();
    const std::set<long> suppressed(suppressedValues.begin(), suppressedValues.end());
    Fem::componentIdType componentId = 0;
    for (auto& component : geom->getComponents()) {
        ++componentId;
        if (!suppressed.contains(static_cast<long>(componentId))) {
            continue;
        }
        for (const auto& name : geom->getToplevelElements(component)) {
            hidden.insert(name);
        }
    }
    return hidden;
}

void collectImportedMeshComponents(
    const Fem::FemAnalysis* analysis,
    const std::string& prefix,
    std::vector<const Fem::FemAnalysisImport*>& chain,
    std::vector<std::pair<std::string, std::vector<std::string>>>& out
)
{
    for (auto* imp : Fem::Tools::analysisImports(analysis)) {
        if (std::ranges::find(chain, imp) != chain.end()) {
            continue;
        }
        const char* name = imp->getNameInDocument();
        const std::string path = prefix.empty() ? std::string(name ? name : "Import")
                                                : prefix + "." + (name ? name : "Import");

        if (auto* src = Base::freecad_cast<Fem::FemAnalysis*>(imp->Analysis.getValue())) {
            if (auto* mesh = Fem::Tools::getAnalysisMeshGroup(src)) {
                const auto hidden = suppressedToplevelNames(imp);
                const auto n = mesh->componentCount();
                for (Fem::componentIdType i = 0; i < n; ++i) {
                    std::vector<std::string> elements;
                    for (const auto& element : mesh->toplevelElements(i)) {
                        if (hidden.contains(element)) {
                            continue;
                        }
                        elements.push_back(path + "." + element);
                    }
                    if (elements.empty()) {
                        continue;
                    }
                    out.emplace_back(
                        path + ".Component" + std::to_string(i + 1),
                        std::move(elements)
                    );
                }
            }
            chain.push_back(imp);
            collectImportedMeshComponents(src, path, chain, out);
            chain.pop_back();
        }
    }
}

}  // namespace

std::vector<std::pair<std::string, std::vector<std::string>>> Fem::Tools::importedMeshComponents(
    const Fem::FemAnalysis* analysis
)
{
    std::vector<std::pair<std::string, std::vector<std::string>>> out;
    std::vector<const Fem::FemAnalysisImport*> chain;
    collectImportedMeshComponents(analysis, {}, chain, out);
    return out;
}

std::vector<std::string> Fem::Tools::importedToplevelElements(const Fem::FemAnalysis* analysis)
{
    std::vector<std::string> out;
    for (const auto& [component, elements] : importedComponents(analysis)) {
        out.insert(out.end(), elements.begin(), elements.end());
    }
    return out;
}

bool Fem::Tools::isMemberSuppressed(
    const std::vector<const Fem::FemAnalysisImport*>& chain,
    const App::DocumentObject* member
)
{
    const char* name = member ? member->getNameInDocument() : nullptr;
    if (!name) {
        return false;
    }

    for (std::size_t i = 0; i < chain.size(); ++i) {
        const auto values = chain[i]->SuppressedMembers.getValues();
        if (values.empty()) {
            continue;
        }
        std::string path;
        for (std::size_t j = i + 1; j < chain.size(); ++j) {
            const char* nested = chain[j]->getNameInDocument();
            path += (nested ? nested : "Import");
            path += '.';
        }
        path += name;
        if (std::ranges::find(values, path) != values.end()) {
            return true;
        }
    }
    return false;
}

bool Fem::Tools::isInheritableMember(const App::DocumentObject* member)
{
    if (!member) {
        return false;
    }
    static const std::array<const char*, 7> excluded {
        "Fem::FemGeometry",
        "Fem::FemMeshObject",
        "Fem::FemMeshShapeGroup",
        "Fem::FemAnalysisImport",
        "Fem::FemSolverObject",
        "Fem::FemResultObject",
        "App::DocumentObjectGroup",
    };
    return std::ranges::none_of(excluded, [member](const char* type) {
        return member->isDerivedFrom(Base::Type::fromName(type));
    });
}

bool Fem::Tools::getCylinderParams(
    const TopoDS_Shape& sh,
    Base::Vector3d& base,
    Base::Vector3d& axis,
    double& height,
    double& radius
)
{
    if (sh.ShapeType() == TopAbs_FACE) {
        TopoDS_Face face = TopoDS::Face(sh);
        BRepAdaptor_Surface surface(face);
        if (!(surface.GetType() == GeomAbs_Cylinder)) {
            return false;
        }

        gp_Cylinder cyl = surface.Cylinder();
        gp_Pnt start = surface.Value(surface.FirstUParameter(), surface.FirstVParameter());
        gp_Pnt end = surface.Value(surface.FirstUParameter(), surface.LastVParameter());

        Handle(Geom_Curve) handle = new Geom_Line(cyl.Axis());
        GeomAPI_ProjectPointOnCurve proj(start, handle);
        gp_XYZ startProj = proj.NearestPoint().XYZ();
        proj.Perform(end);
        gp_XYZ endProj = proj.NearestPoint().XYZ();

        gp_XYZ ax(endProj - startProj);
        gp_XYZ center = (startProj + endProj) / 2.0;
        gp_Dir dir(ax);

        height = ax.Modulus();
        radius = cyl.Radius();
        base = Base::Vector3d(center.X(), center.Y(), center.Z());
        axis = Base::Vector3d(dir.X(), dir.Y(), dir.Z());
    }
    else if (sh.ShapeType() == TopAbs_EDGE) {
        TopoDS_Edge edge = TopoDS::Edge(sh);
        BRepAdaptor_Curve curve(edge);
        if (!(curve.GetType() == GeomAbs_Circle)) {
            return false;
        }
        gp_Circ circ = curve.Circle();
        gp_Ax1 ax = circ.Axis();
        gp_Dir dir = ax.Direction();
        gp_Pnt center = ax.Location();

        height = 0.0;
        radius = circ.Radius();
        base = Base::Vector3d(center.X(), center.Y(), center.Z());
        axis = Base::Vector3d(dir.X(), dir.Y(), dir.Z());
    }
    return true;
}
