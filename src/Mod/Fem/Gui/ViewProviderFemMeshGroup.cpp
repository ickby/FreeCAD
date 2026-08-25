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

#include <cstring>

#include <App/Document.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/Document.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemMeshShapeGroup.h>

#include "ViewProviderFemMeshGroup.h"
#include "ViewProviderFemMeshShapePreprocess.h"


using namespace FemGui;

PROPERTY_SOURCE(FemGui::ViewProviderFemMeshGroup, Gui::ViewProviderDocumentObjectGroup)

ViewProviderFemMeshGroup::ViewProviderFemMeshGroup()
{
    sPixmap = "FEM_MeshGroup";
}

ViewProviderFemMeshGroup::~ViewProviderFemMeshGroup()
{
    m_viewStateConn.disconnect();
}

void ViewProviderFemMeshGroup::attach(App::DocumentObject* pcObject)
{
    // Thin: inherit group attach only — no mesh scene graph content.
    Gui::ViewProviderDocumentObjectGroup::attach(pcObject);
    connectViewState();
    updateStageVisibility();
}

std::vector<std::string> ViewProviderFemMeshGroup::getDisplayModes() const
{
    // No render modes; children own display.
    return {};
}

void ViewProviderFemMeshGroup::setDisplayMode(const char* ModeName)
{
    (void)ModeName;
}

void ViewProviderFemMeshGroup::updateData(const App::Property* prop)
{
    Gui::ViewProviderDocumentObjectGroup::updateData(prop);
    // Attach often runs before the group is added to an analysis, so reconnect
    // whenever data changes (e.g. after Analysis.addObject / Group updates).
    connectViewState();
    if (prop && prop->getName() && strcmp(prop->getName(), "Group") == 0) {
        updateStageVisibility();
        syncChildViewStates();
    }
}

void ViewProviderFemMeshGroup::onChanged(const App::Property* prop)
{
    Gui::ViewProviderDocumentObjectGroup::onChanged(prop);
    if (prop == &Visibility) {
        updateStageVisibility();
    }
}

Fem::FemAnalysis* ViewProviderFemMeshGroup::findAnalysis() const
{
    auto* obj = getObject();
    if (!obj) {
        return nullptr;
    }
    for (auto* parent : obj->getInList()) {
        if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(parent)) {
            return analysis;
        }
    }
    return nullptr;
}

void ViewProviderFemMeshGroup::connectViewState()
{
    auto* analysis = findAnalysis();
    if (!analysis) {
        return;
    }
    auto* state = AnalysisViewState::forAnalysis(analysis);
    if (!state) {
        return;
    }
    // Already bound to this analysis's state.
    if (m_viewStateConn.connected()) {
        return;
    }
    m_viewStateConn = state->connectChanged([this]() {
        updateStageVisibility();
        syncChildViewStates();
    });
    updateStageVisibility();
    syncChildViewStates();
}

void ViewProviderFemMeshGroup::syncChildViewStates()
{
    auto* obj = getObject();
    if (!obj) {
        return;
    }
    auto* doc = Gui::Application::Instance->getDocument(obj->getDocument());
    if (!doc) {
        return;
    }
    auto* group = Base::freecad_cast<Fem::FemMeshShapeGroup*>(obj);
    if (!group) {
        return;
    }
    for (auto* child : group->Group.getValues()) {
        if (!child) {
            continue;
        }
        auto* vp = Base::freecad_cast<ViewProviderFemMeshShapePreprocess*>(doc->getViewProvider(child));
        if (vp) {
            // Joining the group is what makes preprocessActive() true, and the
            // child gets no property change of its own for that.
            vp->syncRepresentation();
        }
    }
}

void ViewProviderFemMeshGroup::updateStageVisibility()
{
    auto* obj = getObject();
    if (!obj) {
        return;
    }

    bool meshStage = true;
    if (auto* analysis = findAnalysis()) {
        if (auto* state = AnalysisViewState::forAnalysis(analysis)) {
            meshStage = (state->activeStage() == ActiveStage::Mesh);
        }
    }

    // Never force children Visibility=false for Geometry stage. DocumentObjectGroup
    // can mirror “all children hidden” onto this group's Visibility, which then
    // permanently blocks Mesh stage (showMeshes stayed false until the user
    // manually unhid the group). Child preprocess VPs hide via display masks.
    if (!meshStage) {
        return;
    }

    if (!Visibility.getValue()) {
        Visibility.setValue(true);
    }

    auto* doc = Gui::Application::Instance->getDocument(obj->getDocument());
    if (!doc) {
        return;
    }

    auto* group = Base::freecad_cast<Fem::FemMeshShapeGroup*>(obj);
    if (!group) {
        return;
    }

    for (auto* child : group->Group.getValues()) {
        if (!child) {
            continue;
        }
        auto* vp = Base::freecad_cast<Gui::ViewProviderDocumentObject*>(doc->getViewProvider(child));
        if (vp && !vp->Visibility.getValue()) {
            vp->Visibility.setValue(true);
        }
    }
}

// Python feature ---------------------------------------------------------

namespace Gui
{

PROPERTY_SOURCE_TEMPLATE(FemGui::ViewProviderFemMeshGroupPython, FemGui::ViewProviderFemMeshGroup)

template class FemGuiExport ViewProviderFeaturePythonT<FemGui::ViewProviderFemMeshGroup>;

}  // namespace Gui
