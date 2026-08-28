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
#include <string>
#include <vector>

#include <App/DocumentObserver.h>
#include <Base/BoundBox.h>
#include <Base/Vector3D.h>
#include <Gui/ViewProvider.h>

#include <Mod/Fem/FemGlobal.h>

class SoCoordinate3;
class SoDragger;
class SoSeparator;
class SoSwitch;
class SoTransform;

namespace Gui
{
class SoTransformDragger;
class View3DInventorViewer;
}  // namespace Gui

namespace Fem
{
class FemAnalysis;
}

namespace FemGui
{

class AnalysisViewState;

/**
 * Interactive handle for one clip plane of an analysis.
 *
 * Owns the 3D part of a clip plane: the standard FreeCAD transform dragger
 * reduced to what a plane needs (one arrow, two rotations and one in-plane
 * slider) plus a plane indicator. The dragger keeps a constant size on screen,
 * while the indicator is model sized so it reads as part of the geometry.
 *
 * The arrow points into the part that gets cut away, hence opposite to the
 * plane normal handed to the view state.
 *
 * The handle survives deletion of its analysis: the scene graph nodes are
 * referenced, the analysis is held weakly and the view state is resolved on
 * every access, so a stale handle degrades to a no-op instead of touching
 * freed memory.
 */
class FemGuiExport ClipPlaneHandle
{
public:
    ~ClipPlaneHandle();

    ClipPlaneHandle(const ClipPlaneHandle&) = delete;
    ClipPlaneHandle& operator=(const ClipPlaneHandle&) = delete;

    /**
     * Build a handle for @a analysis.
     *
     * @param name Clip plane name. An empty name generates an unused one and
     *             starts clipping at the model center; an existing name adopts
     *             that plane, which is how planes restored from a saved
     *             document get their handle back.
     * @return nullptr if the analysis has no view provider to attach to.
     */
    static std::unique_ptr<ClipPlaneHandle> create(
        Fem::FemAnalysis* analysis,
        const std::string& name = {}
    );

    /** Clip plane name unused by both the view state and the live handles. */
    static std::string uniqueName(Fem::FemAnalysis* analysis);

    /**
     * Offset step of the arrow as configured by the user, 0 for automatic.
     *
     * Steps are nothing a user wants to set per plane, so they are preferences
     * that all clip planes of all analyses share.
     */
    static double offsetStep();

    /** Store the shared offset step and hand it to the live handles. */
    static void setOffsetStep(double step);

    /** Offset step this handle works with, the automatic one included. */
    double appliedOffsetStep() const;

    /** Rotation step of the two angle handles in degree. */
    static double angleStep();

    /** Store the shared rotation step and hand it to the live handles. */
    static void setAngleStep(double degree);

    const std::string& name() const
    {
        return m_name;
    }

    /** Whether the plane is applied to the view state. */
    bool isActive() const
    {
        return m_active;
    }
    void setActive(bool on);

    /** Whether dragger and plane indicator are drawn. */
    bool isWidgetVisible() const
    {
        return m_widgetVisible;
    }
    void setWidgetVisible(bool on);

    /**
     * What the plane cuts: the whole analysis for an empty scope, otherwise
     * the instance at that path and everything inside it.
     */
    const std::string& scope() const
    {
        return m_scope;
    }
    void setScope(const std::string& scope);

    Base::Vector3d origin() const;

    /** Plane normal, pointing at the half of the model that is kept. */
    Base::Vector3d normal() const;
    void setPlane(const Base::Vector3d& origin, const Base::Vector3d& normal);

    /**
     * Re-sync with the outside world: adopt the view state, re-fit the plane
     * indicator to the current model size and re-arm the viewport scaling.
     */
    void refresh();

    /** Drop the plane and detach from the scene; later calls are no-ops. */
    void remove();

private:
    ClipPlaneHandle(Fem::FemAnalysis* analysis, std::string name, SoSeparator* parent);

    void buildSceneGraph();
    void hideArrowLabel();
    void initializePlane();

    Fem::FemAnalysis* analysis() const;
    AnalysisViewState* viewState() const;
    Gui::View3DInventorViewer* viewer() const;

    void applyToViewState();
    void updateIndicatorSize();
    void updateOffsetStep();
    void updateAngleStep();
    void setUpViewportScale();
    Base::BoundBox3d modelBoundingBox() const;

    static void dragStartCB(void* data, SoDragger* dragger);
    static void dragFinishCB(void* data, SoDragger* dragger);

    App::DocumentObjectWeakPtrT m_analysis;
    std::string m_name;
    std::string m_scope;
    bool m_active {false};
    bool m_widgetVisible {true};
    bool m_removed {false};
    /// Half size of the plane indicator, the base of the automatic step
    double m_indicatorHalfSize {0.0};

    Gui::CoinPtr<SoSeparator> m_parent;
    Gui::CoinPtr<SoSwitch> m_switch;
    Gui::CoinPtr<Gui::SoTransformDragger> m_dragger;
    Gui::CoinPtr<SoTransform> m_indicatorTransform;
    Gui::CoinPtr<SoCoordinate3> m_indicatorCoords;

    /// Live handles, so generated names do not collide with inactive planes.
    static std::vector<ClipPlaneHandle*> s_handles;
};

}  // namespace FemGui
