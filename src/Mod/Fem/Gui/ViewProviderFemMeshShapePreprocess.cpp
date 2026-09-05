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
# include <cstring>
# include <Inventor/nodes/SoSeparator.h>
#endif

#include "ViewProviderFemMeshShapePreprocess.h"

#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemGeometry.h>
#include <Mod/Fem/App/FemMeshObject.h>
#include <Mod/Fem/App/FemMeshShapeGroup.h>
#include <Mod/Fem/App/FemMeshShapeObject.h>

using namespace FemGui;

PROPERTY_SOURCE(FemGui::ViewProviderFemMeshShapePreprocess, FemGui::ViewProviderFemMeshShapeBase)

ViewProviderFemMeshShapePreprocess::ViewProviderFemMeshShapePreprocess()
{
    m_hidden = new SoSeparator();
    m_hidden->ref();
}

ViewProviderFemMeshShapePreprocess::~ViewProviderFemMeshShapePreprocess()
{
    m_preprocessMesh.disconnectViewState();
    m_hidden->unref();
}

bool ViewProviderFemMeshShapePreprocess::preprocessActive() const
{
    auto* obj = getObject();
    if (!obj) {
        return false;
    }
    if (auto* shapeBase = Base::freecad_cast<Fem::FemMeshShapeBaseObject*>(obj)) {
        if (Base::freecad_cast<Fem::FemGeometry*>(shapeBase->Components.getValue())) {
            return true;
        }
    }
    for (auto* parent : obj->getInList()) {
        if (Base::freecad_cast<Fem::FemMeshShapeGroup*>(parent)) {
            return true;
        }
    }
    return false;
}

void ViewProviderFemMeshShapePreprocess::attach(App::DocumentObject* pcObject)
{
    ViewProviderFemMeshShapeBase::attach(pcObject);
    m_preprocessMesh.setHost(
        this,
        [this]() { return findAnalysis(); },
        [this]() { return findGeometry(); }
    );
    syncRepresentation();
}

void ViewProviderFemMeshShapePreprocess::setDisplayMode(const char* ModeName)
{
    if (ModeName && strcmp(ModeName, ViewMode::Preprocess) == 0) {
        if (m_preprocessMesh.hasDisplayModes()) {
            setStageMask(*this, ViewMode::Preprocess);
        }
        return;
    }
    ViewProviderFemMeshShapeBase::setDisplayMode(ModeName);
}

std::vector<std::string> ViewProviderFemMeshShapePreprocess::getDisplayModes() const
{
    auto modes = ViewProviderFemMeshShapeBase::getDisplayModes();
    if (preprocessActive()) {
        modes.emplace_back(ViewMode::Preprocess);
    }
    return modes;
}

void ViewProviderFemMeshShapePreprocess::updateData(const App::Property* prop)
{
    // The legacy representation is always kept up to date so that switching
    // back out of the new workflow, and the legacy postprocessing API, keep
    // working without a rebuild.
    ViewProviderFemMeshShapeBase::updateData(prop);
    if (!prop) {
        return;
    }
    auto* meshObj = Base::freecad_cast<Fem::FemMeshObject*>(getObject());
    if (!meshObj) {
        return;
    }
    if (prop == &meshObj->FemMesh) {
        m_preprocessMesh.invalidateMesh();
        syncRepresentation();
        return;
    }
    auto* shapeBase = Base::freecad_cast<Fem::FemMeshShapeBaseObject*>(getObject());
    if (shapeBase && prop == &shapeBase->Components) {
        syncRepresentation();
    }
}

void ViewProviderFemMeshShapePreprocess::syncRepresentation()
{
    if (!preprocessActive()) {
        m_preprocessMesh.disconnectViewState();
        return;
    }

    m_preprocessMesh.ensureDisplayModes(m_hidden);
    m_preprocessMesh.connectViewState();
    if (!m_preprocessMesh.isBuilt()) {
        updateMeshFromProperty();
    }
    updateStageVisibility();
}

void ViewProviderFemMeshShapePreprocess::onChanged(const App::Property* prop)
{
    ViewProviderFemMeshShapeBase::onChanged(prop);
    if (prop == &Visibility && preprocessActive()) {
        // Visibility is also the first signal a freshly grouped mesh gets, so the
        // representation may still be the legacy one at this point.
        syncRepresentation();
    }
}

void ViewProviderFemMeshShapePreprocess::finishRestoring()
{
    ViewProviderFemMeshShapeBase::finishRestoring();
    // GuiDocument.xml is restored before FemMesh.unv, and the property change
    // that carries the mesh data does not reach view providers while the
    // document is restoring. Whatever was built earlier came from an empty
    // property, so discard it and rebuild from the now complete object.
    m_preprocessMesh.invalidateMesh();
    syncRepresentation();
}

Fem::FemAnalysis* ViewProviderFemMeshShapePreprocess::findAnalysis() const
{
    auto* obj = getObject();
    if (!obj) {
        return nullptr;
    }
    for (auto* parent : obj->getInList()) {
        if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(parent)) {
            return analysis;
        }
        if (auto* group = Base::freecad_cast<Fem::FemMeshShapeGroup*>(parent)) {
            for (auto* grand : group->getInList()) {
                if (auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(grand)) {
                    return analysis;
                }
            }
        }
    }
    return nullptr;
}

Fem::FemGeometry* ViewProviderFemMeshShapePreprocess::findGeometry() const
{
    if (auto* shapeBase = Base::freecad_cast<Fem::FemMeshShapeBaseObject*>(getObject())) {
        if (auto* geo = Base::freecad_cast<Fem::FemGeometry*>(shapeBase->Components.getValue())) {
            return geo;
        }
    }
    auto* analysis = findAnalysis();
    if (!analysis) {
        return nullptr;
    }
    for (auto* obj : analysis->Group.getValues()) {
        if (auto* geo = Base::freecad_cast<Fem::FemGeometry*>(obj)) {
            return geo;
        }
    }
    return nullptr;
}

void ViewProviderFemMeshShapePreprocess::updateMeshFromProperty()
{
    auto* meshObj = Base::freecad_cast<Fem::FemMeshObject*>(getObject());
    if (!meshObj) {
        return;
    }

    m_preprocessMesh.updateFromFemMesh(meshObj->FemMesh.getValue());
}

void ViewProviderFemMeshShapePreprocess::updateStageVisibility()
{
    if (!preprocessActive()) {
        return;
    }
    m_preprocessMesh.syncStageVisibility();
}

// References are picked on the geometry, and the mesh drawn over it is there to
// be looked at. Naming a subelement of it would let a pick that only meant to
// show the mesh reach into the analysis, and the base implementation names the
// elements of a scene graph this mode does not draw. So neither: the mesh
// answers for itself as a whole and nothing below it.
std::string ViewProviderFemMeshShapePreprocess::getElement(const SoDetail* detail) const
{
    if (!preprocessActive()) {
        return ViewProviderFemMeshShapeBase::getElement(detail);
    }
    return {};
}

SoDetail* ViewProviderFemMeshShapePreprocess::getDetail(const char* subelement) const
{
    if (!preprocessActive()) {
        return ViewProviderFemMeshShapeBase::getDetail(subelement);
    }
    return nullptr;
}

// Python feature ---------------------------------------------------------

namespace Gui
{

PROPERTY_SOURCE_TEMPLATE(
    FemGui::ViewProviderFemMeshShapePreprocessPython,
    FemGui::ViewProviderFemMeshShapePreprocess
)

template class FemGuiExport ViewProviderFeaturePythonT<FemGui::ViewProviderFemMeshShapePreprocess>;

}  // namespace Gui
