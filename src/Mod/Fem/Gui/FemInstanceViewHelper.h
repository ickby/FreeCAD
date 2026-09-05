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

#include <functional>
#include <map>
#include <set>
#include <string>

#include <Base/Placement.h>
#include <Mod/Fem/FemGlobal.h>

#include "AnalysisViewState.h"
#include "FemViewTypes.h"

namespace Fem
{
class FemAnalysis;
class FemGeometry;
}  // namespace Fem

namespace Gui
{
class ViewProviderDocumentObject;
}

namespace FemGui
{

/**
 * What every helper that draws one instance under an analysis view state has,
 * whatever it is that the helper draws.
 *
 * An instance is a subtree of a view provider that renders part of an analysis:
 * the geometry of a placed import, or its mesh. Which of the two it is decides
 * everything about the drawing and nothing about the bookkeeping, and the
 * bookkeeping is what lives here. It is three things.
 *
 * The first is where the instance sits. An analysis names an element of a
 * placed import by a path ("Import2.Solid1") while the instance knows it by the
 * plain name its own source analysis gave it, and the shape is triangulated in
 * the frame of that source while the user places clip planes in the frame of
 * the importing one. So both the hidden-element set and the clip planes have to
 * be brought across, which is what localHiddenElements() and localClipPlanes()
 * are for.
 *
 * The second is the connection to the view state. A helper is built before the
 * object it draws is in an analysis, so the state it has to follow is only
 * reachable later and can be replaced afterwards. ensureViewStateConnection()
 * is therefore not "connect once": it rebinds whenever the state a helper
 * belongs to has changed or its connection was dropped, and applies the state
 * it finds straight away so that a helper arriving late does not draw as though
 * no colour mode, hidden element or clip plane were set. Every helper needs the
 * same rule, and having each write its own is how three slightly different
 * rules came to exist.
 *
 * The third is whether the helper switches the display mask of its host view
 * provider for the active stage, or whether the host does that itself because
 * it draws more than this one instance.
 */
class FemGuiExport FemInstanceViewHelper
{
public:
    using AnalysisFinder = std::function<Fem::FemAnalysis*()>;
    using GeometryFinder = std::function<Fem::FemGeometry*()>;

    FemInstanceViewHelper() = default;
    virtual ~FemInstanceViewHelper();

    FemInstanceViewHelper(const FemInstanceViewHelper&) = delete;
    FemInstanceViewHelper& operator=(const FemInstanceViewHelper&) = delete;

    /**
     * The view provider this instance draws under, and how to reach the
     * analysis and the geometry it belongs to.
     *
     * Finders rather than pointers: which analysis holds an object changes
     * over the life of the helper, and the host is the only one that knows how
     * to answer that for the kind of object it is.
     */
    void setHost(
        Gui::ViewProviderDocumentObject* viewProvider,
        AnalysisFinder findAnalysis,
        GeometryFinder findGeometry
    );

    /** Analysis-relative path prefix (e.g. "Import2.") for hidden/clip lookups. */
    void setPathPrefix(const std::string& prefix);
    /** Placement of this instance, used to bring clip planes into its frame. */
    void setLocalFrame(const Base::Placement& placement);
    /** When false the host view provider manages stage display masks itself. */
    void setManageStageVisibility(bool on);

    void connectViewState();
    void disconnectViewState();

    /** Redraw what the state of the analysis now says this instance looks like. */
    virtual void onViewStateChanged() = 0;

protected:
    /** Bind to the state of the analysis this instance is in, if it changed. */
    void ensureViewStateConnection();
    AnalysisViewState* viewState() const;

    /** The hidden elements of @a hidden that name this instance, named locally. */
    std::set<std::string> localHiddenElements(const std::set<std::string>& hidden) const;
    /** The planes of @a clips that cut this instance, in its own frame. */
    std::map<std::string, ClippingPlane> localClipPlanes(
        const std::map<std::string, ClippingPlane>& clips
    ) const;

    /// Called after a state was bound, before it is first applied.
    virtual void onViewStateBound()
    {}
    /// Called as @a state is let go of, so that anything given to it can be taken back.
    virtual void onViewStateUnbound(AnalysisViewState* state)
    {
        (void)state;
    }

    /// The state being followed, or null while this instance follows none.
    AnalysisViewState* boundViewState() const
    {
        return m_binding.state();
    }

    /// The state being followed, or the one this instance belongs to if not bound yet.
    AnalysisViewState* effectiveViewState() const
    {
        auto* bound = m_binding.state();
        return bound ? bound : viewState();
    }

    Gui::ViewProviderDocumentObject* m_viewProvider {nullptr};
    AnalysisFinder m_findAnalysis;
    GeometryFinder m_findGeometry;

    std::string m_pathPrefix;
    Base::Placement m_localFrame;
    bool m_manageStageVisibility {true};

    ViewStateBinding m_binding;
    bool m_viewStateCacheValid {false};
};

}  // namespace FemGui
