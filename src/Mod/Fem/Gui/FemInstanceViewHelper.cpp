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
#include <utility>
#endif

#include "FemInstanceViewHelper.h"

using namespace FemGui;

namespace
{

std::string stripTrailingDot(std::string path)
{
    if (!path.empty() && path.back() == '.') {
        path.pop_back();
    }
    return path;
}

/// Whether @a plane is cutting at all, and cutting the instance at @a pathPrefix.
bool clipApplies(const ClippingPlane& plane, const std::string& pathPrefix)
{
    if (!plane.Active) {
        return false;
    }
    if (plane.Scope.empty()) {
        return true;
    }
    const std::string scope = stripTrailingDot(pathPrefix);
    if (scope.empty()) {
        return false;
    }
    return scope == plane.Scope || scope.starts_with(plane.Scope + ".");
}

}  // namespace

// A derived helper that has something to hand back calls disconnectViewState()
// from its own destructor, where its override still exists to be called; what is
// left for this one is the connection, which the binding drops itself.
FemInstanceViewHelper::~FemInstanceViewHelper() = default;

void FemInstanceViewHelper::setHost(
    Gui::ViewProviderDocumentObject* viewProvider,
    AnalysisFinder findAnalysis,
    GeometryFinder findGeometry
)
{
    m_viewProvider = viewProvider;
    m_findAnalysis = std::move(findAnalysis);
    m_findGeometry = std::move(findGeometry);
}

void FemInstanceViewHelper::setPathPrefix(const std::string& prefix)
{
    m_pathPrefix = prefix;
}

void FemInstanceViewHelper::setLocalFrame(const Base::Placement& placement)
{
    m_localFrame = placement;
    m_viewStateCacheValid = false;
}

void FemInstanceViewHelper::setManageStageVisibility(bool on)
{
    m_manageStageVisibility = on;
}

AnalysisViewState* FemInstanceViewHelper::viewState() const
{
    if (!m_findAnalysis) {
        return nullptr;
    }
    auto* analysis = m_findAnalysis();
    if (!analysis) {
        return nullptr;
    }
    return AnalysisViewState::forAnalysis(analysis);
}

void FemInstanceViewHelper::onViewStateChanged()
{
    if (m_renderingEnabled) {
        applyViewStateChange();
    }
}

void FemInstanceViewHelper::setRenderingEnabled(bool on)
{
    if (on == m_renderingEnabled) {
        return;
    }
    m_renderingEnabled = on;
    if (on) {
        // Every change made while it slept was ignored, so nothing that was
        // worked out before it can be trusted now.
        m_viewStateCacheValid = false;
        onViewStateChanged();
    }
}

void FemInstanceViewHelper::connectViewState()
{
    ensureViewStateConnection();
}

void FemInstanceViewHelper::disconnectViewState()
{
    if (auto* state = m_binding.release()) {
        onViewStateUnbound(state);
    }
    m_viewStateCacheValid = false;
}

void FemInstanceViewHelper::ensureViewStateConnection()
{
    auto* state = viewState();
    if (m_binding.isBoundTo(state)) {
        return;
    }
    disconnectViewState();
    if (state) {
        m_binding.bind(state, [this]() { onViewStateChanged(); });
        onViewStateBound();
        // Apply it straight away: a helper that arrives after the stage was
        // chosen would otherwise draw as though nothing had been chosen at all.
        onViewStateChanged();
    }
}

std::set<std::string> FemInstanceViewHelper::localHiddenElements(
    const std::set<std::string>& hidden
) const
{
    std::set<std::string> local;
    if (m_pathPrefix.empty()) {
        for (const auto& name : hidden) {
            if (name.find('.') == std::string::npos) {
                local.insert(name);
            }
        }
        return local;
    }
    for (const auto& name : hidden) {
        if (name.starts_with(m_pathPrefix)) {
            local.insert(name.substr(m_pathPrefix.size()));
        }
    }
    return local;
}

std::map<std::string, ClippingPlane> FemInstanceViewHelper::localClipPlanes(
    const std::map<std::string, ClippingPlane>& clips
) const
{
    std::map<std::string, ClippingPlane> local;
    const Base::Placement toLocal = m_localFrame.inverse();
    for (const auto& entry : clips) {
        if (!clipApplies(entry.second, m_pathPrefix)) {
            continue;
        }
        // What this instance draws is placed in the frame of its source
        // analysis while a plane is placed in the frame of the importing one,
        // so the plane has to come back through the instance placement to cut
        // where the user put it.
        ClippingPlane plane = entry.second;
        toLocal.multVec(entry.second.Origin, plane.Origin);
        plane.Direction = toLocal.getRotation().multVec(entry.second.Direction);
        local.emplace(entry.first, plane);
    }
    return local;
}
