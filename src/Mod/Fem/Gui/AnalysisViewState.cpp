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
# include <sstream>
#endif

#include "AnalysisViewState.h"
#include "Classification.h"
#include "ViewProviderAnalysis.h"

#include <Base/Console.h>
#include <Base/Interpreter.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/Document.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemGeometry.h>

using namespace FemGui;

std::map<Fem::FemAnalysis*, std::unique_ptr<AnalysisViewState>> AnalysisViewState::s_states;

AnalysisViewState::AnalysisViewState(Fem::FemAnalysis* analysis)
    : m_analysis(analysis)
{
    m_colorMode[ActiveStage::Geometry] = ColorMode::Subelement;
    m_colorMode[ActiveStage::Mesh] = ColorMode::Subelement;
    m_colorMode[ActiveStage::Result] = ColorMode::Subelement;
}

AnalysisViewState::~AnalysisViewState() = default;

AnalysisViewState* AnalysisViewState::forAnalysis(Fem::FemAnalysis* analysis)
{
    if (!analysis) {
        return nullptr;
    }
    auto it = s_states.find(analysis);
    if (it != s_states.end()) {
        return it->second.get();
    }
    auto state = std::make_unique<AnalysisViewState>(analysis);
    auto* raw = state.get();

    // Restore persisted subset from the view provider if available
    if (Gui::Application::Instance) {
        auto* guiDoc = Gui::Application::Instance->getDocument(analysis->getDocument());
        if (guiDoc) {
            auto* vp = freecad_cast<ViewProviderFemAnalysis*>(guiDoc->getViewProvider(analysis));
            if (vp) {
                raw->loadFromViewProvider(vp);
            }
        }
    }

    s_states.emplace(analysis, std::move(state));
    return raw;
}

AnalysisViewState* AnalysisViewState::find(Fem::FemAnalysis* analysis)
{
    if (!analysis) {
        return nullptr;
    }
    auto it = s_states.find(analysis);
    return it != s_states.end() ? it->second.get() : nullptr;
}

void AnalysisViewState::destroyForAnalysis(Fem::FemAnalysis* analysis)
{
    s_states.erase(analysis);
}

bool AnalysisViewState::isAlive(const AnalysisViewState* state)
{
    if (!state) {
        return false;
    }
    for (const auto& entry : s_states) {
        if (entry.second.get() == state) {
            return true;
        }
    }
    return false;
}

void AnalysisViewState::beginUpdate()
{
    ++m_batchDepth;
}

void AnalysisViewState::endUpdate()
{
    if (m_batchDepth > 0) {
        --m_batchDepth;
    }
    if (m_batchDepth == 0 && m_pendingNotify) {
        m_pendingNotify = false;
        m_changed();
    }
}

void AnalysisViewState::notifyChanged()
{
    if (m_batchDepth > 0) {
        m_pendingNotify = true;
        return;
    }
    m_changed();
}

AnalysisViewState::Connection AnalysisViewState::connectChanged(Slot slot)
{
    return m_changed.connect(std::move(slot));
}

void AnalysisViewState::setActiveStage(ActiveStage stage)
{
    if (m_stage == stage) {
        return;
    }
    m_stage = stage;
    invalidateClassification();
    notifyChanged();
}

void AnalysisViewState::setDimensionMode(DimensionMode mode)
{
    if (m_dimensionMode == mode) {
        return;
    }
    m_dimensionMode = mode;
    notifyChanged();
}

void AnalysisViewState::setWireframe(bool on)
{
    if (m_wireframe == on) {
        return;
    }
    m_wireframe = on;
    notifyChanged();
}

void AnalysisViewState::setOverlay(bool on)
{
    if (m_overlay == on) {
        return;
    }
    m_overlay = on;
    notifyChanged();
}

ColorMode AnalysisViewState::colorMode(ActiveStage stage) const
{
    auto it = m_colorMode.find(stage);
    if (it == m_colorMode.end()) {
        return ColorMode::Subelement;
    }
    return it->second;
}

void AnalysisViewState::setColorMode(ActiveStage stage, ColorMode mode)
{
    // Restrict CellType to mesh stage
    if (mode == ColorMode::CellType && stage != ActiveStage::Mesh) {
        mode = ColorMode::Subelement;
    }
    if (colorMode(stage) == mode) {
        return;
    }
    m_colorMode[stage] = mode;
    if (stage == m_stage) {
        invalidateClassification();
    }
    notifyChanged();
}

void AnalysisViewState::setElementHidden(const std::string& element, bool hidden)
{
    bool changed = false;
    if (hidden) {
        changed = m_hiddenElements.insert(element).second;
    }
    else {
        changed = m_hiddenElements.erase(element) > 0;
    }
    if (changed) {
        persist();
        notifyChanged();
    }
}

void AnalysisViewState::setHiddenElements(const std::set<std::string>& elements)
{
    if (m_hiddenElements == elements) {
        return;
    }
    m_hiddenElements = elements;
    persist();
    notifyChanged();
}

bool AnalysisViewState::isElementHidden(const std::string& element) const
{
    return m_hiddenElements.count(element) > 0;
}

void AnalysisViewState::setCellTypeHidden(const std::string& cellType, bool hidden)
{
    bool changed = false;
    if (hidden) {
        changed = m_hiddenCellTypes.insert(cellType).second;
    }
    else {
        changed = m_hiddenCellTypes.erase(cellType) > 0;
    }
    if (changed) {
        notifyChanged();
    }
}

bool AnalysisViewState::isCellTypeHidden(const std::string& cellType) const
{
    return m_hiddenCellTypes.count(cellType) > 0;
}

void AnalysisViewState::setClipPlane(const std::string& name, const ClippingPlane& plane)
{
    // A degenerate normal reaches VTK as a zero length plane normal, which
    // clips everything or nothing depending on the filter.
    ClippingPlane clip = plane;
    if (clip.Direction.Length() < 1e-9) {
        Base::Console().warning(
            "FEM view state: clip plane '%s' ignored, its normal is degenerate\n",
            name.c_str()
        );
        return;
    }
    clip.Direction.Normalize();

    auto it = m_clipPlanes.find(name);
    if (it != m_clipPlanes.end() && it->second == clip) {
        return;
    }
    m_clipPlanes[name] = clip;
    persist();
    notifyChanged();
}

void AnalysisViewState::removeClipPlane(const std::string& name)
{
    if (m_clipPlanes.erase(name) > 0) {
        persist();
        notifyChanged();
    }
}

void AnalysisViewState::invalidateClassification()
{
    m_classifications.clear();
}

void AnalysisViewState::setUnderAchievedElements(std::set<std::string> elements)
{
    m_underAchieved = std::move(elements);
}

Fem::FemGeometry* AnalysisViewState::findGeometry() const
{
    if (!m_analysis) {
        return nullptr;
    }
    for (auto* obj : m_analysis->Group.getValues()) {
        if (auto* geo = Base::freecad_cast<Fem::FemGeometry*>(obj)) {
            return geo;
        }
    }
    return nullptr;
}

const Classification* AnalysisViewState::classification(vtkUnstructuredGrid* meshGrid)
{
    const ColorMode mode = colorMode();
    if (m_classificationMode != mode) {
        m_classifications.clear();
        m_classificationMode = mode;
    }

    auto& entry = m_classifications[meshGrid];
    if (!entry) {
        entry = Classification::create(mode, m_analysis, findGeometry(), meshGrid);
    }
    return entry.get();
}

void AnalysisViewState::registerMeshGrid(vtkUnstructuredGrid* meshGrid)
{
    if (meshGrid) {
        m_meshGrids.insert(meshGrid);
        // Force a fresh classification so entity→toplevel mapping uses current geometry.
        m_classifications.erase(meshGrid);
    }
}

void AnalysisViewState::unregisterMeshGrid(vtkUnstructuredGrid* meshGrid)
{
    m_meshGrids.erase(meshGrid);
    m_classifications.erase(meshGrid);
}

std::vector<Category> AnalysisViewState::categories() const
{
    auto* self = const_cast<AnalysisViewState*>(this);

    std::vector<Category> result;
    std::set<std::string> seen;
    auto collect = [&result, &seen](const Classification* cls) {
        if (!cls) {
            return;
        }
        for (const auto& cat : cls->categories()) {
            if (seen.insert(cat.key).second) {
                result.push_back(cat);
            }
        }
    };

    // Geometry derived categories first so their order stays stable, then
    // whatever the individual meshes add on top.
    collect(self->classification(nullptr));
    for (auto* grid : m_meshGrids) {
        collect(self->classification(grid));
    }
    return result;
}

namespace
{
std::string encodeClipPlane(const ClippingPlane& p)
{
    std::ostringstream os;
    os << p.Origin.x << ' ' << p.Origin.y << ' ' << p.Origin.z << ' ' << p.Direction.x << ' '
       << p.Direction.y << ' ' << p.Direction.z;
    return os.str();
}

bool decodeClipPlane(const std::string& s, ClippingPlane& p)
{
    std::istringstream is(s);
    return static_cast<bool>(
        is >> p.Origin.x >> p.Origin.y >> p.Origin.z >> p.Direction.x >> p.Direction.y
           >> p.Direction.z
    );
}
}  // namespace

void AnalysisViewState::loadFromViewProvider(ViewProviderFemAnalysis* vp)
{
    if (!vp) {
        return;
    }

    beginUpdate();
    m_hiddenElements.clear();
    for (const auto& e : vp->ViewHiddenElements.getValues()) {
        m_hiddenElements.insert(e);
    }

    m_clipPlanes.clear();
    const auto& names = vp->ViewClipPlaneNames.getValues();
    const auto& data = vp->ViewClipPlaneData.getValues();
    const size_t n = std::min(names.size(), data.size());
    for (size_t i = 0; i < n; ++i) {
        ClippingPlane plane;
        if (decodeClipPlane(data[i], plane)) {
            m_clipPlanes[names[i]] = plane;
        }
    }
    // Restored state has to reach the renderers, so announce it like any other
    // change. endUpdate() collapses this into a single notification.
    notifyChanged();
    endUpdate();
}

void AnalysisViewState::persist() const
{
    if (!m_analysis || !Gui::Application::Instance) {
        return;
    }
    auto* guiDoc = Gui::Application::Instance->getDocument(m_analysis->getDocument());
    if (!guiDoc) {
        return;
    }
    saveToViewProvider(freecad_cast<ViewProviderFemAnalysis*>(guiDoc->getViewProvider(m_analysis)));
}

void AnalysisViewState::saveToViewProvider(ViewProviderFemAnalysis* vp) const
{
    if (!vp) {
        return;
    }

    // These live on the view provider, so they are saved with the document and
    // never trigger a recompute of the analysis.
    std::vector<std::string> hidden(m_hiddenElements.begin(), m_hiddenElements.end());
    vp->ViewHiddenElements.setValues(hidden);

    std::vector<std::string> names;
    std::vector<std::string> data;
    names.reserve(m_clipPlanes.size());
    data.reserve(m_clipPlanes.size());
    for (const auto& entry : m_clipPlanes) {
        names.push_back(entry.first);
        data.push_back(encodeClipPlane(entry.second));
    }
    vp->ViewClipPlaneNames.setValues(names);
    vp->ViewClipPlaneData.setValues(data);
}
