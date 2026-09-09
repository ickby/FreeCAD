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

#include <string>
#include <vector>

#include <Gui/ViewProviderFeaturePython.h>
#include <Mod/Fem/FemGlobal.h>

#include "FemPreprocessMeshViewHelper.h"
#include "ViewProviderFemMeshShape.h"

class SoSeparator;

namespace Fem
{
class FemAnalysis;
class FemGeometry;
class FemMeshShapeBaseObject;
}

namespace FemGui
{

/**
 * Per-object mesh view provider for the preprocessing workflow.
 *
 * Derives from the legacy ViewProviderFemMeshShapeBase so that objects which
 * are not part of the new workflow keep the full legacy behaviour and API
 * (node/element colouring, highlighted nodes, legacy display modes). This
 * matters because Gmsh and Netgen meshes share the App type and existing
 * documents and the result task panels rely on that API.
 *
 * When the object does participate in the new workflow -- it has Components
 * set on a FemGeometry, or it is a child of a FemMeshShapeGroup -- an extra
 * "Preprocess" display mask mode backed by a FemMeshRenderer is used instead.
 * That mode converts FemMesh to VTK, applies AnalysisViewState visibility and
 * classification, and maps Coin selection details to geometry entity names
 * (Face7, Edge3, ...).
 */
class FemGuiExport ViewProviderFemMeshShapePreprocess: public ViewProviderFemMeshShapeBase
{
    PROPERTY_HEADER_WITH_OVERRIDE(FemGui::ViewProviderFemMeshShapePreprocess);

public:
    ViewProviderFemMeshShapePreprocess();
    ~ViewProviderFemMeshShapePreprocess() override;

    void attach(App::DocumentObject* pcObject) override;
    void updateData(const App::Property* prop) override;
    void onChanged(const App::Property* prop) override;
    void finishRestoring() override;

    void setDisplayMode(const char* ModeName) override;
    std::vector<std::string> getDisplayModes() const override;

    std::string getElement(const SoDetail* detail) const override;
    SoDetail* getDetail(const char* subelement) const override;

    /**
     * True when the object takes part in the new preprocessing workflow, i.e.
     * it has Components pointing at a FemGeometry or lives inside a
     * FemMeshShapeGroup. Legacy objects answer false and behave exactly like
     * ViewProviderFemMeshShapeBase.
     */
    bool preprocessActive() const;

    /**
     * Build or drop the preprocess representation to match preprocessActive().
     *
     * preprocessActive() can turn true long after attach(), e.g. when the mesh
     * is assigned to a FemMeshShapeGroup or when a restored document resolves
     * its links. Until this runs, the legacy SMESH scene graph keeps rendering
     * and ignores the analysis view state, so anything that can change group or
     * analysis membership must call it.
     */
    void syncRepresentation();

protected:
    /**
     * The mesh of a preprocessing workflow is drawn by the renderer, so the
     * scene the base class builds from the mesh is not what is on screen and
     * making it would be a second of work for nobody. It is still what the old
     * display modes show, and the base class builds it on the way into one.
     */
    bool legacyRepresentationNeeded() const override;

    Fem::FemAnalysis* findAnalysis() const;
    Fem::FemGeometry* findGeometry() const;
    void updateMeshFromProperty();
    void updateStageVisibility();

    FemPreprocessMeshViewHelper m_preprocessMesh;
    /// Empty scene graph used to hide the object outside the mesh stage.
    SoSeparator* m_hidden {nullptr};
};

using ViewProviderFemMeshShapePreprocessPython
    = Gui::ViewProviderFeaturePythonT<ViewProviderFemMeshShapePreprocess>;

}  // namespace FemGui
