// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2013 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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


#include <algorithm>

#include <Base/Console.h>
#include <Base/Interpreter.h>
#include <Gui/Application.h>
#include <Gui/Document.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Mod/Fem/App/FemAnalysis.h>

#include "ActiveAnalysisObserver.h"
#include "AnalysisViewState.h"


using namespace FemGui;

ActiveAnalysisObserver* ActiveAnalysisObserver::inst = nullptr;

ActiveAnalysisObserver* ActiveAnalysisObserver::instance()
{
    if (!inst) {
        inst = new ActiveAnalysisObserver();
    }
    return inst;
}

ActiveAnalysisObserver::ActiveAnalysisObserver() = default;

ActiveAnalysisObserver::~ActiveAnalysisObserver() = default;

void ActiveAnalysisObserver::setActiveObject(Fem::FemAnalysis* fem)
{
    if (fem) {
        activeObject = fem;
        App::Document* doc = fem->getDocument();
        activeDocument = Gui::Application::Instance->getDocument(doc);
        activeView = static_cast<Gui::ViewProviderDocumentObject*>(
            activeDocument->getViewProvider(activeObject)
        );
        attachDocument(doc);
        // Ensure view state exists for the newly active analysis
        AnalysisViewState::forAnalysis(fem);
    }
    else {
        activeObject = nullptr;
        activeView = nullptr;
    }
    emitCallbacks();
}

Fem::FemAnalysis* ActiveAnalysisObserver::getActiveObject() const
{
    return activeObject;
}

bool ActiveAnalysisObserver::hasActiveObject() const
{
    return activeObject != nullptr;
}

void ActiveAnalysisObserver::highlightActiveObject(const Gui::HighlightMode& mode, bool on)
{
    if (activeDocument && activeView) {
        activeDocument->signalHighlightObject(*activeView, mode, on, 0, 0);
    }
}

void ActiveAnalysisObserver::slotDeletedDocument(const App::Document& Doc)
{
    App::Document* d = getDocument();
    if (d == &Doc) {
        if (activeObject) {
            AnalysisViewState::destroyForAnalysis(activeObject);
        }
        activeObject = nullptr;
        activeDocument = nullptr;
        activeView = nullptr;
        detachDocument();
        emitCallbacks();
    }
}

void ActiveAnalysisObserver::slotDeletedObject(const App::DocumentObject& Obj)
{
    if (activeObject == &Obj) {
        AnalysisViewState::destroyForAnalysis(activeObject);
        activeObject = nullptr;
        activeView = nullptr;
        emitCallbacks();
    }
}

void ActiveAnalysisObserver::addPythonCallback(Py::Object obj)
{
    callbacks.push_back(obj);
}

void ActiveAnalysisObserver::removePythonCallback(Py::Object obj)
{
    callbacks.erase(std::remove(callbacks.begin(), callbacks.end(), obj), callbacks.end());
}

void ActiveAnalysisObserver::emitCallbacks()
{
    Base::PyGILStateLocker lock;
    try {
        std::string slot = "slotActiveFemAnalysisUpdated";
        Py::Tuple args(1);
        if (activeObject) {
            args.setItem(0, Py::asObject(activeObject->getPyObject()));
        }
        else {
            args.setItem(0, Py::None());
        }
        for (auto& obj : callbacks) {
            Py::Object callable;
            if (PyObject_HasAttrString(obj.ptr(), slot.c_str())) {
                callable = obj.getAttr(slot);
            }
            else if (obj.isCallable()) {
                callable = obj;
            }
            else {
                continue;
            }
            Base::pyCall(callable.ptr(), args.ptr());
        }
    }
    catch (Py::Exception&) {
        Base::PyException e;
        e.reportException();
    }
}
