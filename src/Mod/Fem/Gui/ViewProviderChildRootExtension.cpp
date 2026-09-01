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

#include "PreCompiled.h"

#ifndef _PreComp_
# include <Inventor/nodes/SoGroup.h>
#endif

#include <App/DocumentObject.h>
#include <App/GroupExtension.h>
#include <Gui/Selection/SoFCUnifiedSelection.h>
#include <Gui/ViewProviderDocumentObject.h>

#include "ViewProviderChildRootExtension.h"


using namespace FemGui;

namespace
{
/// Display mask mode the child root is registered under
constexpr const char* CHILD_ROOT_MODE = "Group";
}  // namespace

void FemGui::paintNothingWhenSelected(Gui::ViewProvider* vp)
{
    auto* root = vp ? vp->getRoot() : nullptr;
    if (root && root->isOfType(Gui::SoFCSelectionRoot::getClassTypeId())) {
        static_cast<Gui::SoFCSelectionRoot*>(root)->selectionStyle = Gui::SoFCSelectionRoot::None;
    }
}

// ----------------------------------------------------------------------------

EXTENSION_PROPERTY_SOURCE(FemGui::ViewProviderChildRootExtension, Gui::ViewProviderExtension)

ViewProviderChildRootExtension::ViewProviderChildRootExtension()
{
    initExtensionType(ViewProviderChildRootExtension::getExtensionClassTypeId());

    pcGroupChildren = new SoGroup();
    pcGroupChildren->ref();
    pcGroupChildren->setName("FemGroupChildren");
}

ViewProviderChildRootExtension::~ViewProviderChildRootExtension()
{
    pcGroupChildren->unref();
    pcGroupChildren = nullptr;
}

std::vector<App::DocumentObject*> ViewProviderChildRootExtension::extensionClaimChildren3D() const
{
    auto* obj = getExtendedViewProvider()->getObject();
    auto* group = obj ? obj->getExtensionByType<App::GroupExtension>(true) : nullptr;
    if (!group) {
        return {};
    }
    return group->Group.getValues();
}

void ViewProviderChildRootExtension::initExtension(App::ExtensionContainer* obj)
{
    Gui::ViewProviderExtension::initExtension(obj);

    // Rather than extensionAttach, which the view provider has long been
    // through by the time one of these is added, whether that was from Python,
    // from C++ or by a document being read back.
    auto* vp = getExtendedViewProvider();
    vp->addDisplayMaskMode(pcGroupChildren, CHILD_ROOT_MODE);
    vp->setDisplayMaskMode(CHILD_ROOT_MODE);
    paintNothingWhenSelected(vp);
    if (!vp->Visibility.getValue()) {
        // Picking a mask mode draws the object whatever it was set to, and a
        // document that saved the group hidden picks one on the way in.
        vp->Gui::ViewProvider::hide();
    }
}

SoGroup* ViewProviderChildRootExtension::extensionGetChildRoot() const
{
    return pcGroupChildren;
}

void ViewProviderChildRootExtension::extensionSetDisplayMode(const char* ModeName)
{
    if (strcmp(CHILD_ROOT_MODE, ModeName) == 0) {
        getExtendedViewProvider()->setDisplayMaskMode(CHILD_ROOT_MODE);
    }

    Gui::ViewProviderExtension::extensionSetDisplayMode(ModeName);
}

std::vector<std::string> ViewProviderChildRootExtension::extensionGetDisplayModes() const
{
    std::vector<std::string> modes = Gui::ViewProviderExtension::extensionGetDisplayModes();
    modes.emplace_back(CHILD_ROOT_MODE);
    return modes;
}

namespace Gui
{
EXTENSION_PROPERTY_SOURCE_TEMPLATE(
    FemGui::ViewProviderChildRootExtensionPython,
    FemGui::ViewProviderChildRootExtension
)

// explicit template instantiation
template class FemGuiExport ViewProviderExtensionPythonT<FemGui::ViewProviderChildRootExtension>;
}  // namespace Gui
