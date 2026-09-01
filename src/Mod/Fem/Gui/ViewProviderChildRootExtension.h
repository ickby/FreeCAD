/***************************************************************************
 *   Copyright (c) 2026 FreeCAD Project Association                        *
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

#include <Gui/ViewProviderExtensionPython.h>

#include <Mod/Fem/FemGlobal.h>

class SoGroup;

namespace Gui
{
class ViewProvider;
}

namespace FemGui
{

/**
 * Keeps a container from lighting up everything it holds.
 *
 * A container that draws nothing of its own still owns the selection root its
 * members hang under, so a click on it in the tree, or a double click to make
 * it the active one, paints every member as if all of them had been picked.
 * Said once on the root, the selection and the preselection of the container
 * as a whole pass without a colour, while a pick that names an element still
 * arrives at the member that draws it.
 */
void FemGuiExport paintNothingWhenSelected(Gui::ViewProvider* vp);

/**
 * Draws the members of a group under the group, so that hiding it hides them.
 *
 * A plain App::DocumentObjectGroup has no scene graph of its own; its members
 * are drawn at the top level of the document and the group hides them one by
 * one by writing their Visibility. That loses whatever each member was set to,
 * and it cannot express a group inside a group at all - the inner one would
 * have to be written through on every change of the outer.
 *
 * This gives the group a node to hang its members from, the same arrangement
 * Gui::ViewProviderGeoFeatureGroupExtension makes, minus the coordinate system
 * and the selection root that come with being a geo feature group. It exists
 * for a container that only wants the 3D nesting.
 *
 * Add it to the view object of a group, from Python or C++, and hiding the
 * group takes its members out of the view without touching them.
 */
class FemGuiExport ViewProviderChildRootExtension: public Gui::ViewProviderExtension
{
    EXTENSION_PROPERTY_HEADER_WITH_OVERRIDE(FemGui::ViewProviderChildRootExtension);

public:
    ViewProviderChildRootExtension();
    ~ViewProviderChildRootExtension() override;

    /// Puts the child root in the display mode switch of the view provider
    void initExtension(App::ExtensionContainer* obj) override;

    std::vector<App::DocumentObject*> extensionClaimChildren3D() const override;

    SoGroup* extensionGetChildRoot() const override;

    void extensionSetDisplayMode(const char* ModeName) override;
    std::vector<std::string> extensionGetDisplayModes() const override;

private:
    SoGroup* pcGroupChildren;
};

using ViewProviderChildRootExtensionPython
    = Gui::ViewProviderExtensionPythonT<FemGui::ViewProviderChildRootExtension>;

}  // namespace FemGui
