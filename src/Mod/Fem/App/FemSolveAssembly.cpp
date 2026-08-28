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

#include "FemSolveAssembly.h"

#include <algorithm>
#include <set>
#include <string>

#include "FemAnalysis.h"
#include "FemAnalysisImport.h"
#include "FemGeometry.h"
#include "FemMesh.h"
#include "FemMeshShapeGroup.h"
#include "FemTools.h"

#include <Base/Placement.h>

namespace
{

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

std::string joinPath(const std::string& prefix, const char* name)
{
    if (!name || !*name) {
        return prefix;
    }
    if (prefix.empty()) {
        return name;
    }
    return prefix + "." + name;
}

/**
 * Mesh group name for *groupName* of the instance at *path*.
 *
 * Flat, with the same underscore joining that femtools/importmembers.py uses
 * for inherited member names: a source group named after a source member has to
 * come out as the name the inherited member carries, or the group-data fast
 * path of meshtools.get_femmesh_groupdata_sets_by_name() would miss it and
 * every element set would have to be searched for geometrically.
 */
std::string flatGroupName(const std::string& path, const std::string& groupName)
{
    std::string flat = path;
    std::ranges::replace(flat, '.', '_');
    return flat.empty() ? groupName : flat + "_" + groupName;
}

std::set<std::string> suppressedElementNames(
    const Fem::FemGeometry* geom,
    const std::vector<long>& suppressed
)
{
    std::set<std::string> names;
    if (!geom) {
        return names;
    }
    for (long idx : suppressed) {
        if (idx < 1) {
            continue;
        }
        const auto elems = geom->getToplevelElements(static_cast<Fem::componentIdType>(idx - 1));
        names.insert(elems.begin(), elems.end());
    }
    return names;
}

bool allComponentsSuppressed(const Fem::FemGeometry* geom, const std::vector<long>& suppressed)
{
    if (!geom || suppressed.empty()) {
        return false;
    }
    const auto components = geom->getComponents();
    if (components.empty()) {
        return false;
    }
    std::set<long> supp(suppressed.begin(), suppressed.end());
    for (std::size_t i = 0; i < components.size(); ++i) {
        if (supp.find(static_cast<long>(i + 1)) == supp.end()) {
            return false;
        }
    }
    return true;
}

void appendImportTree(
    Fem::FemMesh& merged,
    std::vector<Part::TopoShape>& shapes,
    std::vector<std::string>& sources,
    std::map<std::string, std::map<int, int>>& nodeSources,
    const Fem::FemAnalysis* analysis,
    const std::string& pathPrefix,
    const Base::Placement& outerPlacement,
    std::vector<const Fem::FemAnalysisImport*>& chain
)
{
    for (auto* imp : Fem::Tools::analysisImports(analysis)) {
        if (std::ranges::find(chain, imp) != chain.end()) {
            continue;
        }
        const char* impName = imp->getNameInDocument();
        const std::string impPath = joinPath(pathPrefix, impName);
        const Base::Placement impPlacement = outerPlacement * imp->Placement.getValue();
        auto* srcGeom = imp->sourceGeometry();
        const auto suppressed = imp->SuppressedComponents.getValues();
        const bool skipImport = allComponentsSuppressed(srcGeom, suppressed);
        const std::set<std::string> suppressedNames = suppressedElementNames(srcGeom, suppressed);

        if (!skipImport && srcGeom) {
            if (!srcGeom->Shape.getValue().IsNull()) {
                Part::TopoShape piece = srcGeom->Shape.getShape();
                piece.setTransform(impPlacement.toMatrix());
                shapes.push_back(piece);
            }
        }

        if (!skipImport) {
            if (auto* srcGroup =
                    meshGroupOf(Base::freecad_cast<Fem::FemAnalysis*>(imp->Analysis.getValue()))) {
                const Fem::FemMesh& srcMesh = srcGroup->getMergedMesh();
                const Base::Matrix4D trsf = impPlacement.toMatrix();
                const std::string path = impPath;
                std::function<std::string(const std::string&)> renamer =
                    [path, suppressedNames](const std::string& groupName) -> std::string {
                        if (suppressedNames.contains(groupName)) {
                            return {};
                        }
                        return flatGroupName(path, groupName);
                    };
                merged.appendMeshData(
                    srcMesh,
                    path,
                    &sources,
                    &trsf,
                    &renamer,
                    &nodeSources[impPath]
                );
            }
        }

        if (auto* src = Base::freecad_cast<Fem::FemAnalysis*>(imp->Analysis.getValue())) {
            chain.push_back(imp);
            appendImportTree(
                merged,
                shapes,
                sources,
                nodeSources,
                src,
                impPath,
                impPlacement,
                chain
            );
            chain.pop_back();
        }
    }
}

}  // namespace

Fem::SolveAssemblyResult Fem::buildSolveAssembly(const FemAnalysis* analysis)
{
    SolveAssemblyResult result;
    if (!analysis) {
        return result;
    }

    std::vector<Part::TopoShape> shapes;
    if (auto* nativeGroup = meshGroupOf(analysis)) {
        result.mesh = nativeGroup->getMergedMesh();
        // cellSources holds paths, and the path of a native cell is empty: it
        // belongs to the analysis itself, not to one of the placed instances.
        // The group's own CellSources name the child mesh instead, which is a
        // different question and answered by the group.
        result.cellSources.assign(nativeGroup->CellSources.getSize(), std::string());
    }

    if (auto* geom = Tools::getAnalysisGeometry(analysis)) {
        if (!geom->Shape.getValue().IsNull()) {
            shapes.push_back(geom->Shape.getShape());
        }
    }

    std::vector<const Fem::FemAnalysisImport*> chain;
    appendImportTree(
        result.mesh,
        shapes,
        result.cellSources,
        result.nodeSources,
        analysis,
        {},
        Base::Placement(),
        chain
    );

    if (shapes.empty()) {
        result.shape = Part::TopoShape();
    }
    else if (shapes.size() == 1) {
        result.shape = shapes.front();
    }
    else {
        result.shape = Part::TopoShape().makeCompound(shapes);
    }

    return result;
}
