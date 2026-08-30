// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2022 FreeCAD Developers                                 *
 *   Author: Ajinkya Dahale <dahale.a.p@gmail.com>                         *
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


#include <App/Document.h>
#include <Gui/Application.h>
#include "Mod/Fem/App/FemConstraint.h"
#include <Mod/Fem/App/FemAnalysisImport.h>
#include <Mod/Fem/App/FemGeometry.h>
#include <Mod/Fem/App/FemTools.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/Gui/ReferenceHighlighter.h>
#include <Mod/Part/Gui/ViewProvider.h>

#include "ViewProviderFemAnalysisImport.h"
#include "ViewProviderFemConstraintOnBoundary.h"
#include "ViewProviderFemGeometry.h"


using namespace FemGui;

PROPERTY_SOURCE(FemGui::ViewProviderFemConstraintOnBoundary, FemGui::ViewProviderFemConstraint)

ViewProviderFemConstraintOnBoundary::ViewProviderFemConstraintOnBoundary() = default;

ViewProviderFemConstraintOnBoundary::~ViewProviderFemConstraintOnBoundary() = default;

void ViewProviderFemConstraintOnBoundary::markGeometryReferences(const bool on)
{
    App::DocumentObject* constraint = getObject();
    const std::string role = std::string("constraint:") + constraint->getNameInDocument();

    std::map<const App::DocumentObject*, std::set<std::string>> marked;
    if (on) {
        for (const auto& subSet : getObject<Fem::Constraint>()->References.getSubListValues()) {
            if (Base::freecad_cast<Fem::FemGeometry*>(subSet.first)) {
                marked[subSet.first].insert(subSet.second.begin(), subSet.second.end());
            }
            else if (auto* imp = Base::freecad_cast<Fem::FemAnalysisImport*>(subSet.first)) {
                for (const auto& sub : subSet.second) {
                    marked[imp].insert(sub);
                }
            }
        }
    }

    // Reach every geometry, not only the referenced ones, so that marks left on
    // a geometry the references have moved away from go as well.
    const auto geometries = constraint->getDocument()->getObjectsOfType(
        Fem::FemGeometry::getClassTypeId()
    );
    for (auto* geometry : geometries) {
        auto* vp = dynamic_cast<ViewProviderFemGeometry*>(
            Gui::Application::Instance->getViewProvider(geometry)
        );
        if (!vp) {
            continue;
        }

        auto elements = marked.find(geometry);
        if (elements == marked.end()) {
            vp->clearElementHighlight(role);
        }
        else {
            vp->setElementHighlight(
                role,
                elements->second,
                ViewProviderFemGeometry::defaultElementHighlightColor()
            );
        }
    }

    // An element of an imported analysis is referenced on the import, which
    // draws it itself, so the mark has to go there rather than to a geometry.
    const auto imports = constraint->getDocument()->getObjectsOfType(
        Fem::FemAnalysisImport::getClassTypeId()
    );
    for (auto* importObj : imports) {
        auto* vp = dynamic_cast<ViewProviderFemAnalysisImport*>(
            Gui::Application::Instance->getViewProvider(importObj)
        );
        if (!vp) {
            continue;
        }

        auto elements = marked.find(importObj);
        if (elements == marked.end()) {
            vp->clearElementHighlight(role);
        }
        else {
            vp->setElementHighlight(
                role,
                elements->second,
                ViewProviderFemGeometry::defaultElementHighlightColor()
            );
        }
    }
}

void ViewProviderFemConstraintOnBoundary::highlightReferences(const bool on)
{
    Fem::Constraint* pcConstraint = this->getObject<Fem::Constraint>();
    const auto& subSets = pcConstraint->References.getSubListValues();

    markGeometryReferences(on);

    for (auto& subSet : subSets) {
        Part::Feature* base = dynamic_cast<Part::Feature*>(subSet.first);
        if (!base) {
            continue;
        }
        PartGui::ViewProviderPart* vp = dynamic_cast<PartGui::ViewProviderPart*>(
            Gui::Application::Instance->getViewProvider(base)
        );
        if (!vp) {
            continue;
        }

        // if somehow the subnames are empty, clear any existing colors
        if (on && !subSet.second.empty()) {
            // identify the type of subelements
            // TODO: Assumed here the subelements are of the same type.
            // It is a requirement but we should keep safeguards.
            if (subSet.second[0].find("Vertex") != std::string::npos) {
                // make sure original colors are remembered
                if (originalPointColors[base].empty()) {
                    originalPointColors[base] = vp->PointColorArray.getValues();
                }
                std::vector<Base::Color> colors = originalPointColors[base];

                // go through the subelements with constraint and recolor them
                // TODO: Replace `ShapeAppearance` with anything more appropriate
                PartGui::ReferenceHighlighter highlighter(
                    base->Shape.getValue(),
                    colors.empty() ? ShapeAppearance.getDiffuseColor() : colors[0]
                );
                highlighter.getVertexColors(subSet.second, colors);
                vp->PointColorArray.setValues(colors);
            }
            else if (subSet.second[0].find("Edge") != std::string::npos) {
                // make sure original colors are remembered
                if (originalLineColors[base].empty()) {
                    originalLineColors[base] = vp->LineColorArray.getValues();
                }
                std::vector<Base::Color> colors = originalLineColors[base];

                // go through the subelements with constraint and recolor them
                // TODO: Replace `ShapeAppearance` with anything more appropriate
                PartGui::ReferenceHighlighter highlighter(
                    base->Shape.getValue(),
                    colors.empty() ? ShapeAppearance.getDiffuseColor() : colors[0]
                );
                highlighter.getEdgeColors(subSet.second, colors);
                vp->LineColorArray.setValues(colors);
            }
            else if (subSet.second[0].find("Face") != std::string::npos) {
                // make sure original colors are remembered
                if (originalFaceColors[base].empty()) {
                    originalFaceColors[base] = vp->ShapeAppearance.getDiffuseColors();
                }
                std::vector<Base::Color> colors = originalFaceColors[base];

                // go through the subelements with constraint and recolor them
                // TODO: Replace shape DiffuseColor with anything more appropriate
                PartGui::ReferenceHighlighter highlighter(
                    base->Shape.getValue(),
                    colors.empty() ? ShapeAppearance.getDiffuseColor() : colors[0]
                );
                highlighter.getFaceColors(subSet.second, colors);
                vp->ShapeAppearance.setDiffuseColors(colors);
            }
        }
        else {
            if (!originalPointColors[base].empty()) {
                vp->PointColorArray.setValues(originalPointColors[base]);
                originalPointColors[base].clear();
            }
            else if (!originalLineColors[base].empty()) {
                vp->LineColorArray.setValues(originalLineColors[base]);
                originalLineColors[base].clear();
            }
            else if (!originalFaceColors[base].empty()) {
                vp->ShapeAppearance.setDiffuseColors(originalFaceColors[base]);
                originalFaceColors[base].clear();
            }
        }
    }

    if (subSets.empty()) {
        // there is nothing selected but previous selection may have highlighting
        // reset that highlighting here
        for (auto& ogPair : originalPointColors) {
            if (ogPair.second.empty()) {
                continue;
            }
            PartGui::ViewProviderPart* vp = dynamic_cast<PartGui::ViewProviderPart*>(
                Gui::Application::Instance->getViewProvider(ogPair.first)
            );
            if (!vp) {
                continue;
            }

            vp->PointColorArray.setValues(ogPair.second);
            ogPair.second.clear();
        }

        for (auto& ogPair : originalLineColors) {
            if (ogPair.second.empty()) {
                continue;
            }
            PartGui::ViewProviderPart* vp = dynamic_cast<PartGui::ViewProviderPart*>(
                Gui::Application::Instance->getViewProvider(ogPair.first)
            );
            if (!vp) {
                continue;
            }

            vp->LineColorArray.setValues(ogPair.second);
            ogPair.second.clear();
        }

        for (auto& ogPair : originalFaceColors) {
            if (ogPair.second.empty()) {
                continue;
            }
            PartGui::ViewProviderPart* vp = dynamic_cast<PartGui::ViewProviderPart*>(
                Gui::Application::Instance->getViewProvider(ogPair.first)
            );
            if (!vp) {
                continue;
            }

            vp->ShapeAppearance.setDiffuseColors(ogPair.second);
            ogPair.second.clear();
        }
    }
}
