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
#include <set>


#include <App/DocumentObjectPy.h>
#include <Base/Tools.h>
#include <Base/VectorPy.h>
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

#ifdef FC_USE_VTK
# include <App/Application.h>
# include <App/Document.h>
# include <Base/Color.h>
# include <Gui/Application.h>
# include <Gui/ViewProvider.h>
# include <Mod/Fem/App/FemAnalysisImport.h>
# include <Mod/Fem/App/FemGeometry.h>

# include "ViewProviderFemAnalysisImport.h"
# include "ViewProviderFemGeometry.h"
#endif


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
            "geometryEditSubject",
            &Module::geometryEditSubject,
            "geometryEditSubject(obj) -- The geometry an open panel for obj is picked on: "
            "the input of a step that stores element references, the step itself for one "
            "that stores none, and None for anything that is no geometry."
        );
        add_varargs_method(
            "colorModes",
            &Module::colorModes,
            "colorModes([stage]) -- The colour modes the view state offers, in the order "
            "a chooser should list them. With a stage name ('Geometry', 'Mesh', ...) only "
            "the modes that say something about that stage."
        );
        add_varargs_method(
            "getAnalysisViewState",
            &Module::getAnalysisViewState,
            "getAnalysisViewState([AnalysisObject]) -- Runtime AnalysisViewState for the "
            "given or active analysis."
        );
        add_varargs_method(
            "addClipPlane",
            &Module::addClipPlane,
            "addClipPlane([AnalysisObject], [origin], [normal], [scope]) -- Add a clip plane "
            "to the given or active analysis and return it. Without a place it cuts the top "
            "off the model, with one it cuts through there, e.g. along a picked face."
        );
        add_varargs_method(
            "getClipPlane",
            &Module::getClipPlane,
            "getClipPlane(AnalysisObject, name) -- The clip plane of that name, or None. "
            "The 3D handle belongs to the analysis, so this is how to reach one rather "
            "than holding on to it."
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
#ifdef FC_USE_VTK
        add_varargs_method(
            "setPreselectPromotion",
            &Module::setPreselectPromotion,
            "setPreselectPromotion(bool) -- While true, hovering a face or edge of "
            "FEM geometry lights the solid that owns it."
        );
        add_varargs_method(
            "setElementHighlight",
            &Module::setElementHighlight,
            "setElementHighlight(obj, role, elements, [color]) -- Mark shape elements "
            "on a FemGeometry or FemAnalysisImport view."
        );
        add_varargs_method(
            "clearElementHighlight",
            &Module::clearElementHighlight,
            "clearElementHighlight(obj, role) -- Remove the marks of one role."
        );
#endif
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
    Py::Object geometryEditSubject(const Py::Tuple& args)
    {
        PyObject* object = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &object)) {
            throw Py::Exception();
        }
        auto* edited = static_cast<App::DocumentObjectPy*>(object)->getDocumentObjectPtr();
        auto* subject = editSubjectFor(edited);
        if (!subject) {
            return Py::None();
        }
        return Py::Object(subject->getPyObject(), true);
    }

    Py::Object colorModes(const Py::Tuple& args)
    {
        const char* stageName = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "|s", &stageName)) {
            throw Py::Exception();
        }

        // Without a stage every mode is listed: a chooser is filled once, before
        // there is an analysis to have a stage at all, and asks again per stage.
        Py::List names;
        for (ColorMode mode : allColorModes()) {
            if (stageName && !colorModeAppliesTo(mode, activeStageFromName(stageName))) {
                continue;
            }
            names.append(Py::String(colorModeName(mode)));
        }
        return names;
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
    Py::Object addClipPlane(const Py::Tuple& args)
    {
        PyObject* object = nullptr;
        PyObject* origin = nullptr;
        PyObject* normal = nullptr;
        const char* scope = "";
        if (!PyArg_ParseTuple(
                args.ptr(),
                "|O!O!O!s",
                &(App::DocumentObjectPy::Type),
                &object,
                &(Base::VectorPy::Type),
                &origin,
                &(Base::VectorPy::Type),
                &normal,
                &scope
            )) {
            throw Py::Exception();
        }
        if (static_cast<bool>(origin) != static_cast<bool>(normal)) {
            throw Py::Exception(
                Base::PyExc_FC_GeneralError,
                "A clip plane is placed by an origin and a normal together, or by neither"
            );
        }

        Fem::FemAnalysis* analysis = resolveAnalysis(object);
        if (!analysis) {
            return Py::None();
        }
        // The plane goes into the view state, and the analysis view provider
        // gives it its 3D handle from there.
        const std::string name = origin
            ? ClipPlaneHandle::addPlane(
                  analysis,
                  *static_cast<Base::VectorPy*>(origin)->getVectorPtr(),
                  *static_cast<Base::VectorPy*>(normal)->getVectorPtr(),
                  scope
              )
            : ClipPlaneHandle::addPlane(analysis);
        if (name.empty()) {
            return Py::None();
        }
        return ClipPlaneHandlePy::create(analysis, name);
    }
    Py::Object getClipPlane(const Py::Tuple& args)
    {
        PyObject* object = nullptr;
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O!s", &(App::DocumentObjectPy::Type), &object, &name)) {
            throw Py::Exception();
        }

        Fem::FemAnalysis* analysis = resolveAnalysis(object);
        auto* state = analysis ? AnalysisViewState::find(analysis) : nullptr;
        if (!state || state->clipPlanes().count(name) == 0) {
            return Py::None();
        }
        return ClipPlaneHandlePy::create(analysis, name);
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
#ifdef FC_USE_VTK
    Py::Object setPreselectPromotion(const Py::Tuple& args)
    {
        PyObject* pyOn = Py_True;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pyOn)) {
            throw Py::Exception();
        }
        const bool on = PyObject_IsTrue(pyOn) != 0;
        for (auto* document : App::GetApplication().getDocuments()) {
            for (auto* obj : document->getObjects()) {
                Gui::ViewProvider* view = Gui::Application::Instance->getViewProvider(obj);
                if (auto* geom = dynamic_cast<ViewProviderFemGeometry*>(view)) {
                    geom->setPreselectPromotion(on);
                }
                else if (auto* imported = dynamic_cast<ViewProviderFemAnalysisImport*>(view)) {
                    imported->setPreselectPromotion(on);
                }
            }
        }
        return Py::None();
    }
    static void parseHighlightElements(PyObject* pyElements, std::set<std::string>& elements)
    {
        if (!PySequence_Check(pyElements)) {
            throw Py::TypeError("elements must be a sequence of names");
        }
        const Py_ssize_t count = PySequence_Size(pyElements);
        for (Py_ssize_t i = 0; i < count; ++i) {
            Py::Object item(PySequence_GetItem(pyElements, i), true);
            if (!PyUnicode_Check(item.ptr())) {
                throw Py::TypeError("elements must be a sequence of names");
            }
            elements.insert(PyUnicode_AsUTF8(item.ptr()));
        }
    }
    static Base::Color parseHighlightColor(PyObject* pyColor)
    {
        auto color = ViewProviderFemGeometry::defaultElementHighlightColor();
        if (!pyColor || pyColor == Py_None) {
            return color;
        }
        if (!PySequence_Check(pyColor) || PySequence_Size(pyColor) != 3) {
            throw Py::TypeError("color must be an (r, g, b) sequence in 0..1");
        }
        float channel[3] {};
        for (int i = 0; i < 3; ++i) {
            Py::Object item(PySequence_GetItem(pyColor, i), true);
            channel[i] = static_cast<float>(PyFloat_AsDouble(item.ptr()));
        }
        return Base::Color(channel[0], channel[1], channel[2]);
    }
    Py::Object setElementHighlight(const Py::Tuple& args)
    {
        PyObject* pyObj = nullptr;
        const char* role = nullptr;
        PyObject* pyElements = nullptr;
        PyObject* pyColor = Py_None;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!sO|O",
                &(App::DocumentObjectPy::Type),
                &pyObj,
                &role,
                &pyElements,
                &pyColor
            )) {
            throw Py::Exception();
        }
        auto* obj = static_cast<App::DocumentObjectPy*>(pyObj)->getDocumentObjectPtr();
        std::set<std::string> elements;
        parseHighlightElements(pyElements, elements);
        const Base::Color color = parseHighlightColor(pyColor);
        Gui::ViewProvider* view = Gui::Application::Instance->getViewProvider(obj);
        if (auto* geom = dynamic_cast<ViewProviderFemGeometry*>(view)) {
            geom->setElementHighlight(role, elements, color);
        }
        else if (auto* imported = dynamic_cast<ViewProviderFemAnalysisImport*>(view)) {
            imported->setElementHighlight(role, elements, color);
        }
        return Py::None();
    }
    Py::Object clearElementHighlight(const Py::Tuple& args)
    {
        PyObject* pyObj = nullptr;
        const char* role = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O!s", &(App::DocumentObjectPy::Type), &pyObj, &role)) {
            throw Py::Exception();
        }
        auto* obj = static_cast<App::DocumentObjectPy*>(pyObj)->getDocumentObjectPtr();
        Gui::ViewProvider* view = Gui::Application::Instance->getViewProvider(obj);
        if (auto* geom = dynamic_cast<ViewProviderFemGeometry*>(view)) {
            geom->clearElementHighlight(role);
        }
        else if (auto* imported = dynamic_cast<ViewProviderFemAnalysisImport*>(view)) {
            imported->clearElementHighlight(role);
        }
        return Py::None();
    }
#endif
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
