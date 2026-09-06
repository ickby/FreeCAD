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

#include <set>
#include <string>
#include <vector>

#include <App/PropertyStandard.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Gui/ViewProviderFeaturePython.h>

#include <Base/Color.h>
#include <Mod/Part/App/TopoShape.h>

#include "AnalysisViewState.h"
#include "FemGeometryViewHelper.h"
#include "FemViewTypes.h"

class SoSeparator;
class SoSwitch;

namespace PartGui
{
class SoPreviewShape;
}

namespace FemGui
{

/**
 * View provider for Fem::FemGeometry.
 *
 * Draws nothing itself. A FemGeometryViewHelper renders the shape, here as an
 * instance with no path prefix and the identity frame - what a placed import
 * is a generalisation of - so the geometry of an analysis and the geometry of
 * an import placed in one are drawn by the same code.
 *
 * What is left here is what only a view provider can do: the display masks,
 * the Python object, the picking hooks the framework calls, and the chain of
 * build steps, which is about the geometry's history rather than its picture.
 */
class FemGuiExport ViewProviderFemGeometry: public Gui::ViewProviderDocumentObject
{
    PROPERTY_HEADER_WITH_OVERRIDE(FemGui::ViewProviderFemGeometry);

public:
    ViewProviderFemGeometry();
    ~ViewProviderFemGeometry() override;

    /// Convenience API: forwards to the active analysis AnalysisViewState.
    void setClippingPlane(const std::string& name, const ClippingPlane& plane);
    void removeClippingPlane(const std::string& name);

    void attach(App::DocumentObject* pcObject) override;
    void setDisplayMode(const char* ModeName) override;
    std::vector<std::string> getDisplayModes() const override;

    void updateData(const App::Property* prop) override;
    void onChanged(const App::Property* prop) override;
    void finishRestoring() override;

    QIcon mergeColorfulOverlayIcons(const QIcon& orig) const override;

    /**
     * The geometry group this object is a build step of, or nullptr.
     *
     * Steps of a chain have no visual of their own: the group owns the result
     * shape and is the only object that renders it.
     */
    Fem::FemGeometry* chainOwner() const;
    bool isChainStep() const
    {
        return chainOwner() != nullptr;
    }
    /** Mark this step as the one the group takes its result from. */
    void setChainResult(bool result);

    /**
     * While a chain step is edited, show its own shape for picking instead of
     * staying hidden. Hides the geometry group for the duration.
     */
    void setChainPreview(bool on);
    /** True while this shape stands in for the chain result, see setChainPreview(). */
    bool isChainPreview() const
    {
        return m_chainPreview;
    }
    void setChainRenderSuppressed(bool on);
    bool isChainRenderSuppressed() const
    {
        return m_suppressChainRender;
    }
    ViewProviderFemGeometry* groupViewProvider(Fem::FemGeometry* group) const;
    const char* suppressedMaskMode() const;

    std::string getElement(const SoDetail*) const override;
    SoDetail* getDetail(const char*) const override;
    void onSelectionChanged(const Gui::SelectionChanges&) override;

    /** Rebuild 3D selection/preselection highlight from Gui::Selection. */
    void syncSelectionHighlight();

    /**
     * While true, hovering a Face/Edge/Vertex lights the solid(s) that own it.
     *
     * Used while a promoting reference slot is armed. The solid becomes the
     * preselected element, so the existing volume-preselect path colours every
     * face of it. Ambiguous faces light every owner.
     */
    void setPreselectPromotion(bool on);
    bool isPreselectPromotion() const
    {
        return m_geometry.isPreselectPromotion();
    }

    /**
     * Mark shape elements in a colour of their own, independent of what is
     * selected.
     *
     * For panels that hold references to geometry -- partition targets,
     * constraint references -- so the user can see what is already picked while
     * still selecting freely. Marking is not selecting: it survives a
     * Gui::Selection change and does not answer to one.
     *
     * Elements may name toplevels (Solid2) or sub-elements (Face7, Edge3,
     * Vertex1). A toplevel marks its faces and only those: a solid reads from
     * its faces, and colouring its edges and vertices as well would swamp the
     * ones marked in their own right. A role separates consumers, so two open
     * panels do not overwrite each other and each clears only its own marks.
     * Where roles overlap, the one set last wins.
     */
    void setElementHighlight(
        const std::string& role,
        const std::set<std::string>& elements,
        const Base::Color& color
    );
    void clearElementHighlight(const std::string& role);
    /** Elements currently marked by that role. */
    std::set<std::string> elementHighlight(const std::string& role) const;
    /** Colour marking this element, or nullptr if it carries no mark. */
    const Base::Color* elementHighlightColor(const std::string& element) const;
    /** Colour used to mark elements when the caller names none. */
    static Base::Color defaultElementHighlightColor();

    /**
     * Show a temporary cutting-tool shape over this geometry.
     *
     * Used while a partition (or similar) panel is open. The overlay is
     * unpickable and semi-transparent so it does not stand between the user
     * and the geometry being edited. An empty shape clears the preview.
     */
    void setToolPreview(
        const Part::TopoShape& shape,
        const Base::Color& color,
        float transparency
    );
    void clearToolPreview();
    /** Colour used when the caller names none for the tool preview. */
    static Base::Color defaultToolPreviewColor();

    PyObject* getPyObject() override;

protected:
    /** Map a Selection message onto a shape element of this geometry, or empty. */
    std::string elementFromSelection(
        const char* docName,
        const char* objName,
        const char* subName
    ) const;

    /**
     * The analysis this geometry is drawn under, or null.
     *
     * Preferring the analysis that owns it in the tree over the active one:
     * relying on ActiveAnalysisObserver alone misses the case where the view
     * provider attaches before the analysis is marked active.
     */
    Fem::FemAnalysis* owningAnalysis() const;

    /// Hand the current shape to the helper, which is what redraws it.
    void pushShapeToHelper();

    void ensureViewStateConnection();
    void onViewStateChanged();
    AnalysisViewState* viewState() const;

    /** Apply the chain role of this object: build step or result owner. */
    void applyChainRole();
    /** Refresh the roles of the steps below this group. */
    void refreshChainSteps();

    /// Everything this object draws.
    FemGeometryViewHelper m_geometry;

    // coin display nodes owned here rather than by the helper: the masks the
    // stage switches between, and the tool preview, which is an affordance of
    // an open panel rather than a picture of the geometry.
    SoSeparator* m_separator {nullptr};
    SoSeparator* m_hidden {nullptr};

    // Cutting-tool preview while a chain-step panel is open (e.g. partition).
    // Switched out while no tool is set: an empty preview still holds a point
    // at the origin, and a bounding box drawn around that reaches back to it.
    SoSwitch* m_toolPreviewSwitch {nullptr};
    PartGui::SoPreviewShape* m_toolPreview {nullptr};

    ViewStateBinding m_viewStateBinding;

    // Chain role: a step renders nothing, the result step carries a tree badge
    bool m_isChainStep {false};
    bool m_isChainResult {false};
    bool m_chainPreview {false};
    bool m_suppressChainRender {false};
    std::string m_previewSuppressedGroup;
    // Chain members of the last refresh, to hand their visual back when they go
    std::set<std::string> m_chainMembers;
};

using ViewProviderFemGeometryPython = Gui::ViewProviderFeaturePythonT<ViewProviderFemGeometry>;

}  // namespace FemGui
