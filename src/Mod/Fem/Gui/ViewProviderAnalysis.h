// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2013 Jürgen Riegel <FreeCAD@juergen-riegel.net>         *
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

#include <map>
#include <memory>
#include <string>

#include <Gui/ViewProviderDocumentObjectGroup.h>
#include <Gui/ViewProviderFeaturePython.h>
#include <App/PropertyStandard.h>
#include <Mod/Fem/FemGlobal.h>
#include <QCoreApplication>

#include "AnalysisViewState.h"

namespace FemGui
{

class ClipPlaneHandle;

class ViewProviderFemAnalysis;
class ViewProviderFemHighlighter
{
public:
    /// Constructor
    ViewProviderFemHighlighter();
    ~ViewProviderFemHighlighter();

    void attach(ViewProviderFemAnalysis*);
    void highlightView(Gui::ViewProviderDocumentObject*);
    void removeView(Gui::ViewProviderDocumentObject*);

private:
    SoSeparator* annotate;
};

class FemGuiExport ViewProviderFemAnalysis: public Gui::ViewProviderDocumentObjectGroup
{
    Q_DECLARE_TR_FUNCTIONS(FemGui::ViewProviderFemAnalysis)
    PROPERTY_HEADER_WITH_OVERRIDE(FemGui::ViewProviderFemAnalysis);

public:
    /// constructor
    ViewProviderFemAnalysis();

    /// destructor
    ~ViewProviderFemAnalysis() override;

    /**
     * Persistable AnalysisViewState subset. Prop_Output|Prop_Hidden so writes
     * do not touch the document or appear in the property editor.
     */
    App::PropertyStringList ViewHiddenElements;
    App::PropertyStringList ViewClipPlaneNames;
    App::PropertyStringList ViewClipPlaneData;

    void attach(App::DocumentObject*) override;
    void updateData(const App::Property*) override;
    /**
     * attach() runs before the persisted properties are read back, so the view
     * state has to pick them up once restoring is complete.
     */
    void finishRestoring() override;
    bool doubleClicked() override;

    std::vector<App::DocumentObject*> claimChildren() const override;
    /**
     * Everything the analysis holds hangs under it in 3D.
     *
     * Which makes hiding the analysis hide the analysis, geometry, meshes,
     * constraint symbols and placed instances alike, instead of leaving a
     * document with two analyses in it drawing both on top of each other.
     * Only the direct members are claimed; what sits in a container below is
     * that container's to draw, see giveContainersAChildRoot().
     */
    std::vector<App::DocumentObject*> claimChildren3D() const override;
    SoGroup* getChildRoot() const override;
    /*!
     * A foreground of our own, so that what a member draws over the scene still reaches the
     * viewer once we have taken the member out of it. The post processing color bar lives
     * there.
     */
    SoSeparator* getFrontRoot() const override;

    /// handling when object is deleted
    bool onDelete(const std::vector<std::string>&) override;
    /// warning on deletion when there are children
    static bool checkSelectedChildren(
        const std::vector<App::DocumentObject*> objs,
        Gui::Document* docGui,
        std::string objectName
    );
    /// asks the view provider if the given object can be deleted
    bool canDelete(App::DocumentObject* obj) const override;

    void setupContextMenu(QMenu*, QObject*, const char*) override;

    /// list of all possible display modes
    std::vector<std::string> getDisplayModes() const override;
    /// shows solid in the tree
    bool isShow() const override
    {
        return Visibility.getValue();
    }
    /// Hide the object in the view
    void hide() override;
    /// Show the object in the view
    void show() override;

    void highlightView(Gui::ViewProviderDocumentObject*);

    void removeView(Gui::ViewProviderDocumentObject*);

    /**
     * Scene graph parent for the clip plane handles, created on first use.
     *
     * The handles live next to the display mode switch so they stay visible
     * and interactive independent of the analysis display mode.
     */
    SoSeparator* getClipPlaneRoot();

    /**
     * The 3D handle of clip plane @a name, or null if there is no such plane.
     *
     * Handles belong to the analysis, not to whoever put the plane there, so
     * a caller that wants to drive one looks it up rather than holding it.
     */
    ClipPlaneHandle* getClipPlaneHandle(const std::string& name) const;

    /** Re-fit every handle to the model, after it changed size or appeared. */
    void refreshClipPlaneHandles();

    /** @name Drag and drop */
    //@{
    /// Returns true if the view provider generally supports dragging objects
    bool canDragObjects() const override;
    /// Check whether the object can be removed from the view provider by drag and drop
    bool canDragObject(App::DocumentObject*) const override;
    /// Starts to drag the object
    void dragObject(App::DocumentObject*) override;
    /// Returns true if the view provider generally accepts dropping of objects
    bool canDropObjects() const override;
    /// Check whether the object can be dropped to the view provider by drag and drop
    bool canDropObject(App::DocumentObject*) const override;
    /// If the dropped object type is accepted the object will be added as child
    void dropObject(App::DocumentObject*) override;
    //@}

protected:
    bool setEdit(int ModNum) override;
    void unsetEdit(int ModNum) override;

private:
    /**
     * Give every clip plane of the view state a handle, and no other.
     *
     * The planes are the truth and the handles follow them, which is what
     * lets a toolbar command add a plane without knowing that draggers or
     * view panels exist.
     */
    void syncClipPlaneHandles();
    void connectViewState();

    /**
     * Let the plain containers of this analysis draw their own members.
     *
     * The imports live in an App::DocumentObjectGroup, which has no scene
     * graph and so would hide its members by writing each of them. Adding
     * ViewProviderChildRootExtension gives it a node to hang them from, and
     * hiding the container then simply takes them out of the view.
     */
    void giveContainersAChildRoot();

    ViewProviderFemHighlighter extension;
    Gui::CoinPtr<SoSeparator> clipPlaneRoot;
    Gui::CoinPtr<SoGroup> childRoot;
    Gui::CoinPtr<SoSeparator> frontRoot;
    /// The foreground sits next to the scene, so we take it away by hand while hidden
    Gui::CoinPtr<SoSeparator> frontHidden;
    void drawForeground(bool on);

    std::map<std::string, std::unique_ptr<ClipPlaneHandle>> clipPlaneHandles;
    /// The planes as of the last sync, to tell a real change from a passing one
    std::map<std::string, ClippingPlane> syncedClipPlanes;
    AnalysisViewState::Connection viewStateConn;
    /// Guards against a sync that is set off by the syncing itself
    bool syncingClipPlanes {false};
};

using ViewProviderFemAnalysisPython = Gui::ViewProviderFeaturePythonT<ViewProviderFemAnalysis>;

}  // namespace FemGui
