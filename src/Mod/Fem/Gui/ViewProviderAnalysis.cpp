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


#include <Inventor/nodes/SoGroup.h>
#include <Inventor/nodes/SoSeparator.h>
#include <QAction>
#include <QApplication>
#include <QMenu>
#include <QMessageBox>
#include <QTextStream>
#include <QTimer>


#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObjectGroup.h>
#include <App/MaterialObject.h>
#include <App/TextDocument.h>
#include <Base/Tools.h>
#include <Gui/ActionFunction.h>
#include <Gui/Application.h>
#include <Gui/Command.h>
#include <Gui/Control.h>
#include <Gui/Document.h>
#include <Gui/MainWindow.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Selection/SelectionObject.h>
#include <Gui/Workbench.h>
#include <Gui/WorkbenchManager.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemAnalysisImport.h>
#include <Mod/Fem/App/FemConstraint.h>
#include <Mod/Fem/App/FemMeshObject.h>
#include <Mod/Fem/App/FemResultObject.h>
#include <Mod/Fem/App/FemSetObject.h>
#include <Mod/Fem/App/FemSolverObject.h>
#ifdef FC_USE_VTK
# include <Mod/Fem/App/FemPostObject.h>
#endif

#include "TaskDlgAnalysis.h"
#include "ViewProviderAnalysis.h"
#include "ViewProviderChildRootExtension.h"
#include "AnalysisViewState.h"
#include "ClipPlaneHandle.h"


using namespace FemGui;

namespace
{
/// Looks an analysis view provider up by name, for work that is put off until the event loop
ViewProviderFemAnalysis* analysisViewProvider(const std::string& docName, const std::string& objName)
{
    auto* doc = App::GetApplication().getDocument(docName.c_str());
    auto* guiDoc = doc && Gui::Application::Instance ? Gui::Application::Instance->getDocument(doc)
                                                     : nullptr;
    if (!guiDoc) {
        return nullptr;
    }
    auto* obj = freecad_cast<Fem::FemAnalysis*>(doc->getObject(objName.c_str()));
    return obj ? freecad_cast<ViewProviderFemAnalysis*>(guiDoc->getViewProvider(obj)) : nullptr;
}
}  // namespace

ViewProviderFemHighlighter::ViewProviderFemHighlighter()
{
    annotate = new SoSeparator();
    annotate->ref();
}

ViewProviderFemHighlighter::~ViewProviderFemHighlighter()
{
    annotate->unref();
}

void ViewProviderFemHighlighter::attach(ViewProviderFemAnalysis* view)
{
    SoGroup* root = view->getRoot();
    root->addChild(annotate);
}

void ViewProviderFemHighlighter::highlightView(Gui::ViewProviderDocumentObject* view)
{
    annotate->removeAllChildren();

    if (view) {
        annotate->addChild(view->getRoot());
    }
}

void ViewProviderFemHighlighter::removeView(Gui::ViewProviderDocumentObject* view)
{
    if (view) {
        annotate->removeChild(view->getRoot());
    }
}

// ----------------------------------------------------------------------------

/* TRANSLATOR FemGui::ViewProviderFemAnalysis */

PROPERTY_SOURCE(FemGui::ViewProviderFemAnalysis, Gui::ViewProviderDocumentObjectGroup)


ViewProviderFemAnalysis::ViewProviderFemAnalysis()
{
    sPixmap = "FEM_Analysis";

    constexpr auto persistFlags = App::PropertyType(App::Prop_Output | App::Prop_Hidden);
    ADD_PROPERTY_TYPE(
        ViewHiddenElements,
        (std::vector<std::string>()),
        "ViewState",
        persistFlags,
        "Persisted hidden geometry/mesh element names"
    );
    ADD_PROPERTY_TYPE(
        ViewClipPlaneNames,
        (std::vector<std::string>()),
        "ViewState",
        persistFlags,
        "Persisted clip plane names"
    );
    ADD_PROPERTY_TYPE(
        ViewClipPlaneData,
        (std::vector<std::string>()),
        "ViewState",
        persistFlags,
        "Persisted clip plane data (origin + direction)"
    );
}

ViewProviderFemAnalysis::~ViewProviderFemAnalysis()
{
    viewStateConn.disconnect();
    // Before the view state goes, while the handles can still find it
    clipPlaneHandles.clear();

    if (auto* obj = freecad_cast<Fem::FemAnalysis*>(getObject())) {
        AnalysisViewState::destroyForAnalysis(obj);
    }
}

void ViewProviderFemAnalysis::attach(App::DocumentObject* obj)
{
    Gui::ViewProviderDocumentObjectGroup::attach(obj);
    extension.attach(this);

    childRoot = new SoGroup();
    childRoot->setName("FemAnalysisChildren");
    addDisplayMaskMode(childRoot, "Analysis");
    setDisplayMaskMode("Analysis");
    paintNothingWhenSelected(this);

    frontRoot = new SoSeparator();
    frontRoot->setName("FemAnalysisChildrenForeground");
    frontHidden = new SoSeparator();

    if (auto* analysis = freecad_cast<Fem::FemAnalysis*>(obj)) {
        // Ensure view state exists and is loaded from persisted properties
        AnalysisViewState::forAnalysis(analysis);
        connectViewState();
    }
}

void ViewProviderFemAnalysis::giveContainersAChildRoot()
{
    auto* analysis = freecad_cast<Fem::FemAnalysis*>(getObject());
    if (!analysis) {
        return;
    }
    for (auto* member : analysis->Group.getValues()) {
        // A FEM container brings its own scene graph. A plain group, which is
        // what the imports sit in, is given one here so that it can hold its
        // members rather than hide them one by one.
        if (!member || member->getTypeId() != App::DocumentObjectGroup::getClassTypeId()) {
            continue;
        }
        auto* vp = freecad_cast<Gui::ViewProviderDocumentObject*>(
            Gui::Application::Instance->getViewProvider(member)
        );
        if (!vp) {
            continue;
        }
        // Also for one that has been through this before: the style sits on the
        // scene graph, and the property that writes it as well is read back
        // after the extension has come in with a document.
        paintNothingWhenSelected(vp);

        const auto childRootType = ViewProviderChildRootExtension::getExtensionClassTypeId();
        if (vp->hasExtension(childRootType, true)) {
            continue;
        }
        // The Python flavour, because that is the one a document can read back:
        // the container only saves and restores extensions that are addable
        // from Python, and only deletes those again.
        (new ViewProviderChildRootExtensionPython())->initExtension(vp);
    }
}

void ViewProviderFemAnalysis::connectViewState()
{
    if (viewStateConn.connected()) {
        return;
    }
    auto* analysis = freecad_cast<Fem::FemAnalysis*>(getObject());
    auto* state = analysis ? AnalysisViewState::forAnalysis(analysis) : nullptr;
    if (!state) {
        return;
    }
    viewStateConn = state->connectChanged([this]() {
        syncClipPlaneHandles();
    });
}

void ViewProviderFemAnalysis::syncClipPlaneHandles()
{
    auto* analysis = freecad_cast<Fem::FemAnalysis*>(getObject());
    auto* state = analysis ? AnalysisViewState::find(analysis) : nullptr;
    if (!state || syncingClipPlanes) {
        return;
    }
    Base::StateLocker lock(syncingClipPlanes, true);

    const auto& planes = state->clipPlanes();

    // Gone planes first, so a handle is never built next to the one it replaces
    for (auto it = clipPlaneHandles.begin(); it != clipPlaneHandles.end();) {
        it = planes.count(it->first) > 0 ? std::next(it) : clipPlaneHandles.erase(it);
    }

    for (const auto& entry : planes) {
        auto found = clipPlaneHandles.find(entry.first);
        if (found == clipPlaneHandles.end()) {
            if (auto handle = ClipPlaneHandle::create(analysis, entry.first)) {
                clipPlaneHandles.emplace(entry.first, std::move(handle));
            }
            continue;
        }
        // Almost no change of the view state is about clipping, and re-fitting
        // a plane indicator means measuring the model, so only a plane that
        // somebody has actually moved or switched is handed back to its
        // handle. A handle that made the change already knows about it.
        auto known = syncedClipPlanes.find(entry.first);
        if (known == syncedClipPlanes.end() || known->second != entry.second) {
            found->second->refresh();
        }
    }

    syncedClipPlanes = planes;
}

ClipPlaneHandle* ViewProviderFemAnalysis::getClipPlaneHandle(const std::string& name) const
{
    auto it = clipPlaneHandles.find(name);
    return it != clipPlaneHandles.end() ? it->second.get() : nullptr;
}

void ViewProviderFemAnalysis::updateData(const App::Property* prop)
{
    auto* analysis = freecad_cast<Fem::FemAnalysis*>(getObject());
    if (analysis && prop == &analysis->Group) {
        // Before the caller rebuilds the 3D children off the back of this, so
        // that a container that just joined is one that can hold its own.
        giveContainersAChildRoot();

        if (!Visibility.getValue()) {
            // The caller refills our foreground once it is done, so we clear it again after.
            // Named rather than captured, see finishRestoring().
            const std::string docName = analysis->getDocument()->getName();
            const std::string objName = analysis->getNameInDocument();
            QTimer::singleShot(0, [docName, objName]() {
                if (auto* vp = analysisViewProvider(docName, objName)) {
                    vp->drawForeground(false);
                }
            });
        }
    }
    Gui::ViewProviderDocumentObjectGroup::updateData(prop);
}

void ViewProviderFemAnalysis::onChanged(const App::Property* prop)
{
    Gui::ViewProviderDocumentObjectGroup::onChanged(prop);

    if (prop == &SelectionStyle) {
        // Both styles the property offers are read off the members, since the
        // analysis has no shape and no box of its own to show. A document
        // written before this, or a hand on the property editor, says Shape.
        paintNothingWhenSelected(this);
    }
}

void ViewProviderFemAnalysis::finishRestoring()
{
    Gui::ViewProviderDocumentObjectGroup::finishRestoring();

    auto* analysis = freecad_cast<Fem::FemAnalysis*>(getObject());
    if (!analysis) {
        return;
    }
    // Documents written before the containers had one of their own
    giveContainersAChildRoot();

    if (auto* state = AnalysisViewState::forAnalysis(analysis)) {
        connectViewState();
        // Gives the restored planes their handles, through the change this
        // fires once the planes are read back.
        state->loadFromViewProvider(this);
    }

    // A plane indicator is sized against the model, and the objects it
    // measures are still being restored around us. Named rather than
    // captured, so a document that closes before this runs takes it with it.
    const std::string docName = analysis->getDocument()->getName();
    const std::string objName = analysis->getNameInDocument();
    QTimer::singleShot(0, [docName, objName]() {
        if (auto* vp = analysisViewProvider(docName, objName)) {
            vp->refreshClipPlaneHandles();
        }
    });
}

void ViewProviderFemAnalysis::refreshClipPlaneHandles()
{
    for (auto& entry : clipPlaneHandles) {
        entry.second->refresh();
    }
}

void ViewProviderFemAnalysis::highlightView(Gui::ViewProviderDocumentObject* view)
{
    extension.highlightView(view);
}

void ViewProviderFemAnalysis::removeView(Gui::ViewProviderDocumentObject* view)
{
    extension.removeView(view);
}

SoSeparator* ViewProviderFemAnalysis::getClipPlaneRoot()
{
    if (!clipPlaneRoot) {
        clipPlaneRoot = new SoSeparator();
        clipPlaneRoot->setName("FemClipPlanes");
        getRoot()->addChild(clipPlaneRoot);
    }
    return clipPlaneRoot;
}

bool ViewProviderFemAnalysis::doubleClicked()
{
    Gui::Command::assureWorkbench("FemWorkbench");
    Gui::Command::addModule(Gui::Command::Gui, "FemGui");
    Gui::Command::doCommand(
        Gui::Command::Gui,
        "FemGui.setActiveAnalysis(App.activeDocument().%s)",
        this->getObject()->getNameInDocument()
    );
    // After activation of the analysis the allowed FEM toolbar buttons should become active.
    // To achieve this we must clear the object selection to trigger the selection observer.
    Gui::Command::doCommand(Gui::Command::Gui, "Gui.Selection.clearSelection()");
    // indicate the activated analysis by selecting it
    // especially useful for files with 2 or more analyses but also
    // necessary for the workflow with new files to add a solver as next object
    std::vector<App::DocumentObject*> selVector {};
    selVector.push_back(this->getObject());
    auto* docName = this->getObject()->getDocument()->getName();
    Gui::Selection().setSelection(docName, selVector);
    return true;
}

std::vector<App::DocumentObject*> ViewProviderFemAnalysis::claimChildren() const
{
    return Gui::ViewProviderDocumentObjectGroup::claimChildren();
}

std::vector<App::DocumentObject*> ViewProviderFemAnalysis::claimChildren3D() const
{
    auto* analysis = freecad_cast<Fem::FemAnalysis*>(getObject());
    if (!analysis) {
        return {};
    }
    std::vector<App::DocumentObject*> children;
    for (auto* member : analysis->Group.getValues()) {
        if (member) {
            children.push_back(member);
        }
    }
    return children;
}

SoGroup* ViewProviderFemAnalysis::getChildRoot() const
{
    return childRoot;
}

SoSeparator* ViewProviderFemAnalysis::getFrontRoot() const
{
    return frontRoot;
}

void ViewProviderFemAnalysis::drawForeground(bool on)
{
    auto* from = on ? frontHidden.get() : frontRoot.get();
    auto* to = on ? frontRoot.get() : frontHidden.get();
    while (from->getNumChildren() > 0) {
        SoNode* node = from->getChild(0);
        from->removeChild(0);
        if (to->findChild(node) < 0) {
            to->addChild(node);
        }
    }
}

std::vector<std::string> ViewProviderFemAnalysis::getDisplayModes() const
{
    return {"Analysis"};
}

void ViewProviderFemAnalysis::hide()
{
    Gui::ViewProviderDocumentObjectGroup::hide();
    drawForeground(false);
}

void ViewProviderFemAnalysis::show()
{
    Gui::ViewProviderDocumentObjectGroup::show();
    drawForeground(true);
}

void ViewProviderFemAnalysis::setupContextMenu(QMenu* menu, QObject*, const char*)
{
    Gui::ActionFunction* func = new Gui::ActionFunction(menu);
    QAction* act = menu->addAction(tr("Activate Analysis"));
    func->trigger(act, [this]() { this->doubleClicked(); });
}

bool ViewProviderFemAnalysis::setEdit(int ModNum)
{
    if (ModNum == ViewProvider::Default) {
        // When double-clicking on the item for this pad the object
        // unsets and sets its edit mode without closing the task panel

        // Gui::TaskView::TaskDialog *dlg = Gui::Control().activeDialog();
        // TaskDlgAnalysis *anaDlg = qobject_cast<TaskDlgAnalysis *>(dlg);
        // if (padDlg && anaDlg->getPadView() != this)
        //     padDlg = 0; // another pad left open its task panel
        // if (dlg && !padDlg) {
        //     QMessageBox msgBox;
        //     msgBox.setText(QObject::tr("A dialog is already open in the task panel"));
        //     msgBox.setInformativeText(QObject::tr("Do you want to close this dialog?"));
        //     msgBox.setStandardButtons(QMessageBox::Yes | QMessageBox::No);
        //     msgBox.setDefaultButton(QMessageBox::Yes);
        //     int ret = msgBox.exec();
        //     if (ret == QMessageBox::Yes)
        //         Gui::Control().closeDialog();
        //     else
        //         return false;
        // }

        // start the edit dialog
        //        if (padDlg)
        //            Gui::Control().showDialog(padDlg);
        //        else

        // Fem::FemAnalysis* pcAna = this->getObject<Fem::FemAnalysis>();
        // Gui::Control().showDialog(new TaskDlgAnalysis(pcAna));
        // return true;
        return false;
    }
    else {
        return Gui::ViewProviderDocumentObjectGroup::setEdit(ModNum);
    }
}

void ViewProviderFemAnalysis::unsetEdit(int ModNum)
{
    if (ModNum == ViewProvider::Default) {
        // when pressing ESC make sure to close the dialog
        Gui::Control().closeDialog();
    }
    else {
        Gui::ViewProviderDocumentObjectGroup::unsetEdit(ModNum);
    }
}

bool ViewProviderFemAnalysis::canDragObjects() const
{
    return true;
}

bool ViewProviderFemAnalysis::canDragObject(App::DocumentObject* obj) const
{
    if (!obj) {
        return false;
    }

    // clang-format off: keep line breaks for readability
    if (obj->isDerivedFrom<Fem::FemMeshObject>()
        || obj->isDerivedFrom<Fem::FemSolverObject>()
        || obj->isDerivedFrom<Fem::FemResultObject>()
        || obj->isDerivedFrom<Fem::Constraint>()
        || obj->isDerivedFrom<Fem::FemSetObject>()
        || obj->isDerivedFrom<Fem::FemAnalysisImport>()
        || obj->isDerivedFrom<App::DocumentObjectGroup>()
        || obj->isDerivedFrom(Base::Type::fromName("Fem::FeaturePython"))
        || obj->isDerivedFrom<App::MaterialObject>()
        || obj->isDerivedFrom<App::TextDocument>()) {
        return true;
    }
    // clang-format on
#ifdef FC_USE_VTK
    else if (obj->isDerivedFrom<Fem::FemPostObject>()) {
        return true;
    }
#endif
    return false;
}

void ViewProviderFemAnalysis::dragObject(App::DocumentObject* obj)
{
    ViewProviderDocumentObjectGroup::dragObject(obj);
}

bool ViewProviderFemAnalysis::canDropObjects() const
{
    return true;
}

bool ViewProviderFemAnalysis::canDropObject(App::DocumentObject* obj) const
{
    return canDragObject(obj);
}

void ViewProviderFemAnalysis::dropObject(App::DocumentObject* obj)
{
    ViewProviderDocumentObjectGroup::dropObject(obj);
}

bool ViewProviderFemAnalysis::onDelete(const std::vector<std::string>&)
{
    // warn the user if the object has unselected children
    auto objs = claimChildren();
    return checkSelectedChildren(objs, this->getDocument(), "analysis");
}

bool ViewProviderFemAnalysis::checkSelectedChildren(
    const std::vector<App::DocumentObject*> objs,
    Gui::Document* docGui,
    std::string objectName
)
{
    // warn the user if the object has unselected children
    if (!objs.empty()) {
        // check if all children are in the selection
        bool found = false;
        auto selectionList = Gui::Selection().getSelectionEx(docGui->getDocument()->getName());
        for (auto child : objs) {
            found = false;
            for (Gui::SelectionObject selection : selectionList) {
                if (std::string(child->getNameInDocument()) == std::string(selection.getFeatName())) {
                    found = true;
                    break;
                }
            }
            if (!found) {
                break;
            }
        }
        if (found) {  // all children are selected too
            return true;
        }

        // generate dialog
        QString bodyMessage;
        QTextStream bodyMessageStream(&bodyMessage);
        bodyMessageStream << qApp->translate(
            "Std_Delete",
            ("The " + objectName
             + " is not empty, therefore the\nfollowing "
               "referencing objects might be lost:")
                .c_str()
        );
        bodyMessageStream << '\n';
        for (auto ObjIterator : objs) {
            bodyMessageStream << '\n' << QString::fromUtf8(ObjIterator->Label.getValue());
        }
        bodyMessageStream << "\n\n" << QObject::tr("Are you sure you want to continue?");
        // show and evaluate the dialog
        int DialogResult = QMessageBox::warning(
            Gui::getMainWindow(),
            qApp->translate("Std_Delete", "Object dependencies"),
            bodyMessage,
            QMessageBox::Yes,
            QMessageBox::No
        );
        if (DialogResult == QMessageBox::Yes) {
            return true;
        }
        else {
            return false;
        }
    }
    else {
        return true;
    }
}

bool ViewProviderFemAnalysis::canDelete(App::DocumentObject* obj) const
{
    // deletions of objects from a FemAnalysis don't necessarily destroy anything
    // thus we can pass this action
    // we can warn the user if necessary in the object's ViewProvider in the onDelete() function
    Q_UNUSED(obj)
    return true;
}

// Python feature -----------------------------------------------------------------------

namespace Gui
{
/// @cond DOXERR
PROPERTY_SOURCE_TEMPLATE(FemGui::ViewProviderFemAnalysisPython, FemGui::ViewProviderFemAnalysis)
/// @endcond

// explicit template instantiation
template class FemGuiExport ViewProviderFeaturePythonT<ViewProviderFemAnalysis>;
}  // namespace Gui
