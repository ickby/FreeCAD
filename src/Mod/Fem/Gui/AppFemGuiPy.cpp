// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2008 Werner Mayer <werner.wm.mayer@gmx.de>              *
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

#include <QFileInfo>


#include <App/DocumentObjectPy.h>
#include <Base/Tools.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Document.h>
#include <Gui/EditorView.h>
#include <Gui/MainWindow.h>
#include <Gui/PythonEditor.h>
#include <Gui/TextEdit.h>
#include <Mod/Fem/App/FemAnalysis.h>

#include "AbaqusHighlighter.h"
#include "ActiveAnalysisObserver.h"
#include "AnalysisViewState.h"
#include "AnalysisViewStatePy.h"
#include "ClipPlaneHandle.h"
#include "ClipPlaneHandlePy.h"
#include "FemPerfLog.h"


namespace FemGui
{
class Module: public Py::ExtensionModule<Module>
{
public:
    Module()
        : Py::ExtensionModule<Module>("FemGui")
    {
        AnalysisViewStatePy::init_type();
        ClipPlaneHandlePy::init_type();

        add_varargs_method(
            "setActiveAnalysis",
            &Module::setActiveAnalysis,
            "setActiveAnalysis(AnalysisObject) -- Set the Analysis object in work."
        );
        add_varargs_method(
            "getActiveAnalysis",
            &Module::getActiveAnalysis,
            "getActiveAnalysis() -- Returns the Analysis object in work."
        );
        add_varargs_method(
            "addActiveAnalysisObserver",
            &Module::addActiveAnalysisObserver,
            "addActiveAnalysisObserver(object) -- Register for active-analysis updates "
            "(slotActiveFemAnalysisUpdated)."
        );
        add_varargs_method(
            "removeActiveAnalysisObserver",
            &Module::removeActiveAnalysisObserver,
            "removeActiveAnalysisObserver(object) -- Remove a previously registered observer."
        );
        add_varargs_method(
            "getAnalysisViewState",
            &Module::getAnalysisViewState,
            "getAnalysisViewState([AnalysisObject]) -- Runtime AnalysisViewState for the "
            "given or active analysis."
        );
        add_varargs_method(
            "createClipPlane",
            &Module::createClipPlane,
            "createClipPlane([AnalysisObject], [name]) -- Interactive clip plane handle for "
            "the given or active analysis. A new plane starts clipping at the model center, "
            "an existing name adopts that plane."
        );
        add_varargs_method(
            "perfEnable",
            &Module::perfEnable,
            "perfEnable(bool) -- Switch the timing of the view pipeline stages on or off. "
            "Off costs nothing, so leave it off outside a measurement."
        );
        add_varargs_method(
            "perfReset",
            &Module::perfReset,
            "perfReset() -- Forget what has been timed so far."
        );
        add_varargs_method(
            "perfReport",
            &Module::perfReport,
            "perfReport() -- What the view pipeline spent, as a list of "
            "(name, count, total_seconds, self_seconds) in the order the stages were first "
            "seen. total counts the stages nested in one, self does not."
        );
        add_varargs_method(
            "open",
            &Module::open,
            "open(string) -- Opens an Abaqus file in a text editor."
        );
        add_varargs_method(
            "insert",
            &Module::open,
            "insert(string,string) -- Opens an Abaqus file in a text editor."
        );
        initialize("This module is the FemGui module.");  // register with Python
    }

private:
    Py::Object invoke_method_varargs(void* method_def, const Py::Tuple& args) override
    {
        try {
            return Py::ExtensionModule<Module>::invoke_method_varargs(method_def, args);
        }
        catch (const Base::Exception& e) {
            throw Py::RuntimeError(e.what());
        }
        catch (const std::exception& e) {
            throw Py::RuntimeError(e.what());
        }
    }
    Py::Object setActiveAnalysis(const Py::Tuple& args)
    {
        if (FemGui::ActiveAnalysisObserver::instance()->hasActiveObject()) {
            FemGui::ActiveAnalysisObserver::instance()->highlightActiveObject(
                Gui::HighlightMode::Blue,
                false
            );
            FemGui::ActiveAnalysisObserver::instance()->setActiveObject(nullptr);
        }

        PyObject* object = nullptr;
        if (PyArg_ParseTuple(args.ptr(), "|O!", &(App::DocumentObjectPy::Type), &object) && object) {
            App::DocumentObject* obj
                = static_cast<App::DocumentObjectPy*>(object)->getDocumentObjectPtr();
            if (!obj || !obj->isDerivedFrom<Fem::FemAnalysis>()) {
                throw Py::Exception(
                    Base::PyExc_FC_GeneralError,
                    "Active Analysis object have to be of type Fem::FemAnalysis!"
                );
            }

            // get the gui document of the Analysis Item
            FemGui::ActiveAnalysisObserver::instance()->setActiveObject(
                static_cast<Fem::FemAnalysis*>(obj)
            );
            FemGui::ActiveAnalysisObserver::instance()->highlightActiveObject(
                Gui::HighlightMode::UserDefined,
                true
            );
        }

        return Py::None();
    }
    Py::Object getActiveAnalysis(const Py::Tuple& args)
    {
        if (!PyArg_ParseTuple(args.ptr(), "")) {
            throw Py::Exception();
        }
        if (FemGui::ActiveAnalysisObserver::instance()->hasActiveObject()) {
            return Py::asObject(
                FemGui::ActiveAnalysisObserver::instance()->getActiveObject()->getPyObject()
            );
        }
        return Py::None();
    }
    Py::Object addActiveAnalysisObserver(const Py::Tuple& args)
    {
        PyObject* object = nullptr;
        if (PyArg_ParseTuple(args.ptr(), "O", &object) && object) {
            FemGui::ActiveAnalysisObserver::instance()->addPythonCallback(Py::Object(object));
        }
        return Py::None();
    }
    Py::Object removeActiveAnalysisObserver(const Py::Tuple& args)
    {
        PyObject* object = nullptr;
        if (PyArg_ParseTuple(args.ptr(), "O", &object) && object) {
            FemGui::ActiveAnalysisObserver::instance()->removePythonCallback(Py::Object(object));
        }
        return Py::None();
    }
    /// The given analysis or, without argument, the active one.
    static Fem::FemAnalysis* resolveAnalysis(PyObject* object)
    {
        if (object) {
            App::DocumentObject* obj
                = static_cast<App::DocumentObjectPy*>(object)->getDocumentObjectPtr();
            auto* analysis = Base::freecad_cast<Fem::FemAnalysis*>(obj);
            if (!analysis) {
                throw Py::Exception(
                    Base::PyExc_FC_GeneralError,
                    "Object must be of type Fem::FemAnalysis"
                );
            }
            return analysis;
        }
        if (FemGui::ActiveAnalysisObserver::instance()->hasActiveObject()) {
            return FemGui::ActiveAnalysisObserver::instance()->getActiveObject();
        }
        return nullptr;
    }
    Py::Object getAnalysisViewState(const Py::Tuple& args)
    {
        PyObject* object = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "|O!", &(App::DocumentObjectPy::Type), &object)) {
            throw Py::Exception();
        }

        Fem::FemAnalysis* analysis = resolveAnalysis(object);
        if (!analysis) {
            return Py::None();
        }
        auto* state = AnalysisViewState::forAnalysis(analysis);
        if (!state) {
            return Py::None();
        }
        return AnalysisViewStatePy::create(state);
    }
    Py::Object createClipPlane(const Py::Tuple& args)
    {
        PyObject* object = nullptr;
        char* name = nullptr;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "|O!s",
                &(App::DocumentObjectPy::Type),
                &object,
                &name
            )) {
            throw Py::Exception();
        }

        Fem::FemAnalysis* analysis = resolveAnalysis(object);
        if (!analysis) {
            return Py::None();
        }
        auto handle = ClipPlaneHandle::create(analysis, name ? std::string(name) : std::string());
        if (!handle) {
            throw Py::Exception(
                Base::PyExc_FC_GeneralError,
                "Analysis has no view provider to attach a clip plane to"
            );
        }
        return ClipPlaneHandlePy::create(std::move(handle));
    }
    Py::Object perfEnable(const Py::Tuple& args)
    {
        PyObject* on = Py_True;
        if (!PyArg_ParseTuple(args.ptr(), "|O", &on)) {
            throw Py::Exception();
        }
        PerfLog::instance().setEnabled(PyObject_IsTrue(on) == 1);
        return Py::None();
    }
    Py::Object perfReset(const Py::Tuple& args)
    {
        if (!PyArg_ParseTuple(args.ptr(), "")) {
            throw Py::Exception();
        }
        PerfLog::instance().clear();
        return Py::None();
    }
    Py::Object perfReport(const Py::Tuple& args)
    {
        if (!PyArg_ParseTuple(args.ptr(), "")) {
            throw Py::Exception();
        }
        Py::List result;
        for (const auto& entry : PerfLog::instance().report()) {
            Py::Tuple row(4);
            row.setItem(0, Py::String(entry.name));
            row.setItem(1, Py::Long(static_cast<long>(entry.count)));
            row.setItem(2, Py::Float(entry.total));
            row.setItem(3, Py::Float(entry.self));
            result.append(row);
        }
        return result;
    }
    Py::Object open(const Py::Tuple& args)
    {
        char* Name;
        const char* DocName;
        if (!PyArg_ParseTuple(args.ptr(), "et|s", "utf-8", &Name, &DocName)) {
            throw Py::Exception();
        }

        std::string EncodedName = std::string(Name);
        PyMem_Free(Name);

        QString fileName = QString::fromUtf8(EncodedName.c_str());
        QFileInfo fi;
        fi.setFile(fileName);
        QString ext = fi.completeSuffix().toLower();
        QList<Gui::EditorView*> views = Gui::getMainWindow()->findChildren<Gui::EditorView*>();
        for (auto view : views) {
            if (view->fileName() == fileName) {
                view->setFocus();
                return Py::None();
            }
        }

        Gui::TextEditor* editor = new Gui::TextEditor();
        editor->setWindowIcon(Gui::BitmapFactory().pixmap(":/icons/fem-solver-inp-editor.svg"));
        Gui::EditorView* edit = new Gui::EditorView(editor, Gui::getMainWindow());
        if (ext == QLatin1String("inp")) {
            editor->setSyntaxHighlighter(new FemGui::AbaqusHighlighter(editor));
        }
        else if (ext == QLatin1String("py")) {
            editor->setSyntaxHighlighter(new Gui::PythonSyntaxHighlighter(editor));
        }
        edit->setDisplayName(Gui::EditorView::FileName);
        edit->open(fileName);
        edit->resize(400, 300);
        Gui::getMainWindow()->addWindow(edit);

        QFont font = editor->font();
        font.setFamily(QStringLiteral("Arial"));

        return Py::None();
    }
};

PyObject* initModule()
{
    return Base::Interpreter().addModule(new Module);
}

}  // namespace FemGui
