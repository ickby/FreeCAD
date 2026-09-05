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
    : m_childRoot(new SoGroup())
{
    sPixmap = "FEM_MeshGroup";
    m_childRoot->ref();
}

ViewProviderFemMeshGroup::~ViewProviderFemMeshGroup()
{
    m_viewStateBinding.release();
    m_childRoot->unref();
}

void ViewProviderFemMeshGroup::attach(App::DocumentObject* pcObject)
{
    Gui::ViewProviderDocumentObjectGroup::attach(pcObject);
    addDisplayMaskMode(m_childRoot, "Group");
    setDisplayMaskMode("Group");
    connectViewState();
}

std::vector<std::string> ViewProviderFemMeshGroup::getDisplayModes() const
{
    return {"Group"};
}

SoGroup* ViewProviderFemMeshGroup::getChildRoot() const
{
    return m_childRoot;
}

std::vector<App::DocumentObject*> ViewProviderFemMeshGroup::claimChildren3D() const
{
    if (auto* group = Base::freecad_cast<Fem::FemMeshShapeGroup*>(getObject())) {
        return group->Group.getValues();
    }
    return {};
}

void ViewProviderFemMeshGroup::updateData(const App::Property* prop)
{
    Gui::ViewProviderDocumentObjectGroup::updateData(prop);
    connectViewState();
    if (!prop || !prop->getName()) {
        return;
    }
    if (strcmp(prop->getName(), "Group") == 0) {
        syncChildViewStates();
    }
}

void ViewProviderFemMeshGroup::onChanged(const App::Property* prop)
{
    Gui::ViewProviderDocumentObjectGroup::onChanged(prop);
    if (prop == &Visibility) {
        // Showing the meshes is what the mesh stage is, so the stage has to be
        // read again whenever this changes, including when the user hits space
        // bar on the group in the tree.
        if (auto* analysis = findAnalysis()) {
            if (auto* state = AnalysisViewState::find(analysis)) {
                state->stageVisibilityChanged(ActiveStage::Mesh);
            }
        }
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
    auto* state = analysis ? AnalysisViewState::forAnalysis(analysis) : nullptr;
    if (m_viewStateBinding.isBoundTo(state)) {
        return;
    }
    m_viewStateBinding.bind(state, [this]() { syncChildViewStates(); });
    if (state) {
        syncChildViewStates();
    }
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
            vp->syncRepresentation();
        }
    }
}

namespace Gui
{

PROPERTY_SOURCE_TEMPLATE(FemGui::ViewProviderFemMeshGroupPython, FemGui::ViewProviderFemMeshGroup)

template class FemGuiExport ViewProviderFeaturePythonT<FemGui::ViewProviderFemMeshGroup>;

}  // namespace Gui
