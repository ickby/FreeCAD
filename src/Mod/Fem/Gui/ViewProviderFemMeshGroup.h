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

#pragma once

#include <Gui/ViewProviderDocumentObjectGroup.h>
#include <Gui/ViewProviderFeaturePython.h>
#include <Mod/Fem/FemGlobal.h>

#include "AnalysisViewState.h"

namespace FemGui
{

/**
 * Thin view provider for FemMeshShapeGroup.
 *
 * Claims children and aggregates stage-aware visibility. Does not own scene
 * graph mesh content — per-object mesh VPs render via FemMeshRenderer.
 *
 * Mesh children should call FemMeshRenderer::applyVisibilityMask() with
 * AnalysisViewState filters and FemMeshRenderer::setClassification() with
 * AnalysisViewState::classification() (Stages 6–7).
 */
class FemGuiExport ViewProviderFemMeshGroup: public Gui::ViewProviderDocumentObjectGroup
{
    PROPERTY_HEADER_WITH_OVERRIDE(FemGui::ViewProviderFemMeshGroup);

public:
    ViewProviderFemMeshGroup();
    ~ViewProviderFemMeshGroup() override;

    void attach(App::DocumentObject* pcObject) override;
    void updateData(const App::Property*) override;
    void onChanged(const App::Property* prop) override;

    std::vector<std::string> getDisplayModes() const override;
    void setDisplayMode(const char* ModeName) override;

    /// Hide / show children according to AnalysisViewState active stage.
    void updateStageVisibility();

protected:
    Fem::FemAnalysis* findAnalysis() const;
    void connectViewState();
    void syncChildViewStates();

private:
    AnalysisViewState::Connection m_viewStateConn;
};

using ViewProviderFemMeshGroupPython = Gui::ViewProviderFeaturePythonT<ViewProviderFemMeshGroup>;

}  // namespace FemGui
