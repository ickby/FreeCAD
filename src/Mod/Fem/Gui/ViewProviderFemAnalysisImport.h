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

#include <memory>
#include <set>
#include <string>
#include <vector>

#include <App/PropertyStandard.h>
#include <Base/Color.h>
#include <Base/Placement.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Mod/Fem/FemGlobal.h>
#include <fastsignals/signal.h>

#include "AnalysisViewState.h"
#include "FemGeometryViewHelper.h"
#include "FemPreprocessMeshViewHelper.h"

class SoDragger;
class SoSeparator;
class SoTransform;

namespace Gui
{
class SoTransformDragger;
class View3DInventorViewer;
}

namespace Fem
{
class FemAnalysis;
class FemAnalysisImport;
class FemGeometry;
class FemMesh;
}

namespace FemGui
{

class ViewProviderFemConstraint;

/**
 * View provider for a placed analysis import instance.
 *
 * Renders the source geometry and mesh through dedicated helpers, recursively
 * including nested imports from the source analysis. Inherited constraint
 * symbols stay visible outside the geometry/mesh stage switch.
 */
class FemGuiExport ViewProviderFemAnalysisImport: public Gui::ViewProviderDocumentObject
{
    PROPERTY_HEADER_WITH_OVERRIDE(FemGui::ViewProviderFemAnalysisImport);

public:
    ViewProviderFemAnalysisImport();
    ~ViewProviderFemAnalysisImport() override;

    App::PropertyBool ShowInheritedConstraints;

    /** The instance placement changed, e.g. because the dragger was moved. */
    fastsignals::signal<void()> signalPlacementChanged;

    void attach(App::DocumentObject*) override;
    std::vector<std::string> getDisplayModes() const override;
    void setDisplayMode(const char* mode) override;
    void updateData(const App::Property* prop) override;
    void onChanged(const App::Property* prop) override;
    void finishRestoring() override;

    bool setEdit(int ModNum) override;
    void unsetEdit(int ModNum) override;
    void setEditViewer(Gui::View3DInventorViewer* viewer, int ModNum) override;
    void unsetEditViewer(Gui::View3DInventorViewer* viewer) override;
    bool doubleClicked() override;

    /**
     * Name an element from a detail alone.
     *
     * Without a path there is nothing to say which instance the indices of the
     * detail belong to, so this answers for the first one that can read them.
     * getElementPicked() is what a pick goes through.
     */
    std::string getElement(const SoDetail*) const override;
    SoDetail* getDetail(const char*) const override;

    /**
     * Name the element a pick landed on, read off the instance it went through.
     *
     * A detail is nothing but indices into the arrays of the node that made it,
     * and every instance of one source analysis has the same arrays. Only the
     * path the pick came down says which instance those indices belong to.
     */
    bool getElementPicked(const SoPickedPoint* point, std::string& subname) const override;
    /**
     * Path down to the instance @a subname belongs to, and its detail.
     *
     * The caller applies its selection and highlight actions to everything
     * below the end of this path. Left at the mode switch, that is every
     * instance the view provider draws, each of which would light the part of
     * the index the detail carries - a different face in every one of them.
     */
    bool getDetailPath(const char* subname, SoFullPath* path, bool append, SoDetail*& det) const override;

    /**
     * Re-read the selection and hand it to the render tree.
     *
     * A solid has no part of its own to highlight, so the helpers light its
     * faces themselves and need to be told when the selection moves.
     */
    void syncSelectionHighlight();

    /**
     * While true, hovering a Face/Edge/Vertex of this instance lights the
     * solid(s) that own it. See ViewProviderFemGeometry::setPreselectPromotion.
     */
    void setPreselectPromotion(bool on);

    /** Mark referenced elements, named as a reference on this import names them. */
    void setElementHighlight(
        const std::string& role,
        const std::set<std::string>& elements,
        const Base::Color& color
    );
    void clearElementHighlight(const std::string& role);

    /**
     * Show a dragger that writes the instance placement.
     *
     * The task panel puts one up as it opens and offers a switch for it,
     * because a dragger sitting on the model is in the way of anything else
     * picked there.
     */
    void setDraggerVisible(bool on);
    bool isDraggerVisible() const
    {
        return m_dragger != nullptr;
    }

    /**
     * Where the instance is drawn.
     *
     * That is where it is being dragged to while a drag is going on, which is
     * only written to the instance once the drag is over.
     */
    Base::Placement shownPlacement() const;

    /** Distance in millimetres the dragger snaps a translation to. */
    static double translationStep();
    static void setTranslationStep(double step);
    /** Angle in degree the dragger snaps a rotation to. */
    static double angleStep();
    static void setAngleStep(double degree);
    /** Hand the configured steps to the dragger that is up, if any. */
    void updateDraggerSteps();

private:
    struct ImportRenderNode;

    void rebuildRenderTree();
    void clearRenderTree();
    ImportRenderNode* buildRenderNode(
        Fem::FemAnalysisImport* importObj,
        const Base::Placement& outer,
        const std::string& pathPrefix,
        const std::string& selectionPrefix,
        std::vector<const Fem::FemAnalysisImport*>& chain
    );
    /** The instance @a path runs through, or null if it misses their geometry. */
    const ImportRenderNode* pickedNode(const SoPath* path) const;
    /**
     * The instance @a subelement belongs to.
     *
     * @a branch is filled with the nodes leading to it from the geometry root,
     * the geometry branch of every instance on the way and the separator of
     * the one that owns the element.
     */
    const ImportRenderNode* elementOwner(const char* subelement, std::vector<SoNode*>& branch) const;
    void rebuildInheritedSymbols();
    void clearInheritedSymbols();
    void addInheritedSymbols(
        Fem::FemAnalysisImport* importObj,
        const Base::Placement& outer,
        std::vector<const Fem::FemAnalysisImport*>& chain
    );
    void connectSource();
    void connectViewState();
    void connectNodeViewState(ImportRenderNode& node);
    void syncStageVisibility();
    void onViewStateChanged();
    /**
     * Put the render tree where the instances stand.
     *
     * With a placement given, the root instance is drawn there instead of where
     * it is written: a drag is shown while it happens, and only committed once
     * it is over.
     */
    void updatePlacements(const Base::Placement* rootPlacement = nullptr);
    void updateNodePlacement(
        ImportRenderNode& node,
        const Base::Placement& outer,
        const Base::Placement* own = nullptr
    );
    /** True when *obj* is part of what any analysis in the import tree renders. */
    bool sourceProvides(const App::DocumentObject* obj) const;

    Fem::FemAnalysis* findAnalysis() const;
    static std::vector<unsigned char> buildComponentSubsetMask(
        const Fem::FemMesh& mesh,
        Fem::FemGeometry* geom,
        const std::vector<long>& suppressedComponents
    );

    void syncDraggerToPlacement();
    /**
     * Let the dragger follow the camera of *viewer*, the active view by default.
     *
     * Without a camera to read its size against, the dragger draws itself far
     * too small to see.
     */
    void setUpDraggerScale(Gui::View3DInventorViewer* viewer = nullptr);
    /**
     * Where the dragger has been dragged to.
     *
     * The dragger snaps to its increments and counts them; its own translation
     * and rotation fields are single precision echoes of that, so the counts
     * are what land the instance exactly on the step grid.
     */
    Base::Placement draggedPlacement() const;
    static void dragStartCB(void* data, SoDragger* dragger);
    static void dragMotionCB(void* data, SoDragger* dragger);
    static void dragFinishCB(void* data, SoDragger* dragger);

    Gui::SoTransformDragger* m_dragger {nullptr};
    /** Where the instance stood when the current drag started. */
    Base::Placement m_dragOrigin;
    bool m_dragging {false};
    SoSeparator* pInheritedSymbols {nullptr};
    /** Placement of this instance, above the symbols inherited through it. */
    SoTransform* m_symbolTransform {nullptr};
    SoSeparator* m_geometryRoot {nullptr};
    SoSeparator* m_meshRoot {nullptr};
    SoSeparator* m_hidden {nullptr};
    std::vector<std::unique_ptr<ImportRenderNode>> m_renderNodes;
    std::vector<fastsignals::connection> m_connections;
    fastsignals::scoped_connection m_treeConn;
    AnalysisViewState::Connection m_viewStateConn;
    AnalysisViewState* m_boundViewState {nullptr};
};

}  // namespace FemGui
