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

#include <algorithm>

#include <Base/Console.h>
#include <Base/Interpreter.h>
#include <Base/VectorPy.h>
#include <App/DocumentObjectPy.h>
#include <Mod/Fem/App/FemAnalysis.h>

#include "AnalysisViewStatePy.h"
#include "Classification.h"

using namespace FemGui;

namespace
{

const char* stageToString(ActiveStage stage)
{
    switch (stage) {
        case ActiveStage::Geometry:
            return "Geometry";
        case ActiveStage::Mesh:
            return "Mesh";
        case ActiveStage::Result:
            return "Result";
    }
    return "Geometry";
}

ActiveStage stageFromString(const std::string& s)
{
    if (s == "Mesh") {
        return ActiveStage::Mesh;
    }
    if (s == "Result") {
        return ActiveStage::Result;
    }
    return ActiveStage::Geometry;
}

const char* dimensionToString(DimensionMode mode)
{
    switch (mode) {
        case DimensionMode::Highest:
            return "Highest";
        case DimensionMode::Volume:
            return "Volume";
        case DimensionMode::Surface:
            return "Surface";
        case DimensionMode::Curve:
            return "Curve";
        case DimensionMode::Point:
            return "Point";
    }
    return "Highest";
}

DimensionMode dimensionFromString(const std::string& s)
{
    if (s == "Volume" || s == "3D") {
        return DimensionMode::Volume;
    }
    if (s == "Surface" || s == "2D") {
        return DimensionMode::Surface;
    }
    if (s == "Curve" || s == "1D") {
        return DimensionMode::Curve;
    }
    if (s == "Point" || s == "0D") {
        return DimensionMode::Point;
    }
    return DimensionMode::Highest;
}

const char* colorModeToString(ColorMode mode)
{
    switch (mode) {
        case ColorMode::Subelement:
            return "Subelement";
        case ColorMode::Toplevel:
            return "Toplevel";
        case ColorMode::Material:
            return "Material";
        case ColorMode::CellType:
            return "CellType";
    }
    return "Subelement";
}

ColorMode colorModeFromString(const std::string& s)
{
    if (s == "Toplevel") {
        return ColorMode::Toplevel;
    }
    if (s == "Material") {
        return ColorMode::Material;
    }
    if (s == "CellType") {
        return ColorMode::CellType;
    }
    return ColorMode::Subelement;
}

}  // namespace

void AnalysisViewStatePy::init_type()
{
    behaviors().name("AnalysisViewState");
    behaviors().doc("Runtime view state for one FEM analysis");
    behaviors().supportRepr();

    add_varargs_method("getActiveStage", &AnalysisViewStatePy::getActiveStage, "getActiveStage()");
    add_varargs_method("setActiveStage", &AnalysisViewStatePy::setActiveStage, "setActiveStage(str)");
    add_varargs_method(
        "getDimensionMode",
        &AnalysisViewStatePy::getDimensionMode,
        "getDimensionMode()"
    );
    add_varargs_method(
        "setDimensionMode",
        &AnalysisViewStatePy::setDimensionMode,
        "setDimensionMode(str)"
    );
    add_varargs_method("getWireframe", &AnalysisViewStatePy::getWireframe, "getWireframe()");
    add_varargs_method("setWireframe", &AnalysisViewStatePy::setWireframe, "setWireframe(bool)");
    add_varargs_method("getOverlay", &AnalysisViewStatePy::getOverlay, "getOverlay()");
    add_varargs_method("setOverlay", &AnalysisViewStatePy::setOverlay, "setOverlay(bool)");
    add_varargs_method("getColorMode", &AnalysisViewStatePy::getColorMode, "getColorMode()");
    add_varargs_method("setColorMode", &AnalysisViewStatePy::setColorMode, "setColorMode(str)");

    add_varargs_method(
        "isElementHidden",
        &AnalysisViewStatePy::isElementHidden,
        "isElementHidden(str)"
    );
    add_varargs_method(
        "setElementHidden",
        &AnalysisViewStatePy::setElementHidden,
        "setElementHidden(str, bool)"
    );
    add_varargs_method(
        "getHiddenElements",
        &AnalysisViewStatePy::getHiddenElements,
        "getHiddenElements()"
    );
    add_varargs_method(
        "setHiddenElements",
        &AnalysisViewStatePy::setHiddenElements,
        "setHiddenElements(list)"
    );

    add_varargs_method(
        "isCellTypeHidden",
        &AnalysisViewStatePy::isCellTypeHidden,
        "isCellTypeHidden(str)"
    );
    add_varargs_method(
        "setCellTypeHidden",
        &AnalysisViewStatePy::setCellTypeHidden,
        "setCellTypeHidden(str, bool)"
    );
    add_varargs_method(
        "getHiddenCellTypes",
        &AnalysisViewStatePy::getHiddenCellTypes,
        "getHiddenCellTypes()"
    );

    add_varargs_method(
        "setClipPlane",
        &AnalysisViewStatePy::setClipPlane,
        "setClipPlane(name, origin, direction)"
    );
    add_varargs_method(
        "removeClipPlane",
        &AnalysisViewStatePy::removeClipPlane,
        "removeClipPlane(name)"
    );
    add_varargs_method("getClipPlanes", &AnalysisViewStatePy::getClipPlanes, "getClipPlanes()");

    add_varargs_method("getCategories", &AnalysisViewStatePy::getCategories, "getCategories()");
    add_varargs_method(
        "categoryOfElement",
        &AnalysisViewStatePy::categoryOfElement,
        "categoryOfElement(str)"
    );
    add_varargs_method(
        "getUnderAchievedElements",
        &AnalysisViewStatePy::getUnderAchievedElements,
        "getUnderAchievedElements()"
    );

    add_varargs_method("beginUpdate", &AnalysisViewStatePy::beginUpdate, "beginUpdate()");
    add_varargs_method("endUpdate", &AnalysisViewStatePy::endUpdate, "endUpdate()");
    add_varargs_method(
        "connectChanged",
        &AnalysisViewStatePy::connectChanged,
        "connectChanged(callable)"
    );
    add_varargs_method(
        "disconnectChanged",
        &AnalysisViewStatePy::disconnectChanged,
        "disconnectChanged(callable)"
    );

    // Without this the methods registered above are not reachable from Python.
    behaviors().supportGetattr();
    behaviors().readyType();
}

Py::Object AnalysisViewStatePy::create(AnalysisViewState* state)
{
    return Py::asObject(new AnalysisViewStatePy(state));
}

AnalysisViewStatePy::AnalysisViewStatePy(AnalysisViewState* state)
    : m_state(state)
{}

AnalysisViewStatePy::~AnalysisViewStatePy()
{
    m_changedConn.disconnect();
    m_pyCallbacks.clear();
}

AnalysisViewState* AnalysisViewStatePy::state() const
{
    return AnalysisViewState::isAlive(m_state) ? m_state : nullptr;
}

Py::Object AnalysisViewStatePy::repr()
{
    std::ostringstream s;
    s << "<AnalysisViewState at " << m_state << ">";
    return Py::String(s.str());
}

void AnalysisViewStatePy::emitPythonCallbacks()
{
    Base::PyGILStateLocker lock;
    try {
        Py::Tuple args;
        for (auto& cb : m_pyCallbacks) {
            if (cb.isCallable()) {
                Base::pyCall(cb.ptr(), args.ptr());
            }
        }
    }
    catch (Py::Exception&) {
        Base::PyException e;
        e.reportException();
    }
}

Py::Object AnalysisViewStatePy::getActiveStage(const Py::Tuple& args)
{
    if (args.size() != 0) {
        throw Py::TypeError("getActiveStage() takes no arguments");
    }
    if (!state()) {
        return Py::None();
    }
    return Py::String(stageToString(state()->activeStage()));
}

Py::Object AnalysisViewStatePy::setActiveStage(const Py::Tuple& args)
{
    char* name = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "s", &name)) {
        throw Py::Exception();
    }
    if (state()) {
        state()->setActiveStage(stageFromString(name));
    }
    return Py::None();
}

Py::Object AnalysisViewStatePy::getDimensionMode(const Py::Tuple& args)
{
    (void)args;
    if (!state()) {
        return Py::None();
    }
    return Py::String(dimensionToString(state()->dimensionMode()));
}

Py::Object AnalysisViewStatePy::setDimensionMode(const Py::Tuple& args)
{
    char* name = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "s", &name)) {
        throw Py::Exception();
    }
    if (state()) {
        state()->setDimensionMode(dimensionFromString(name));
    }
    return Py::None();
}

Py::Object AnalysisViewStatePy::getWireframe(const Py::Tuple& args)
{
    (void)args;
    if (!state()) {
        return Py::Boolean(false);
    }
    return Py::Boolean(state()->wireframe());
}

Py::Object AnalysisViewStatePy::setWireframe(const Py::Tuple& args)
{
    PyObject* value = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "O!", &PyBool_Type, &value)) {
        // also accept int
        PyErr_Clear();
        int ival = 0;
        if (!PyArg_ParseTuple(args.ptr(), "i", &ival)) {
            throw Py::Exception();
        }
        if (state()) {
            state()->setWireframe(ival != 0);
        }
        return Py::None();
    }
    if (state()) {
        state()->setWireframe(PyObject_IsTrue(value) != 0);
    }
    return Py::None();
}

Py::Object AnalysisViewStatePy::getOverlay(const Py::Tuple& args)
{
    (void)args;
    if (!state()) {
        return Py::Boolean(false);
    }
    return Py::Boolean(state()->overlay());
}

Py::Object AnalysisViewStatePy::setOverlay(const Py::Tuple& args)
{
    PyObject* value = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "O!", &PyBool_Type, &value)) {
        // also accept int
        PyErr_Clear();
        int ival = 0;
        if (!PyArg_ParseTuple(args.ptr(), "i", &ival)) {
            throw Py::Exception();
        }
        if (state()) {
            state()->setOverlay(ival != 0);
        }
        return Py::None();
    }
    if (state()) {
        state()->setOverlay(PyObject_IsTrue(value) != 0);
    }
    return Py::None();
}

Py::Object AnalysisViewStatePy::getColorMode(const Py::Tuple& args)
{
    (void)args;
    if (!state()) {
        return Py::None();
    }
    return Py::String(colorModeToString(state()->colorMode()));
}

Py::Object AnalysisViewStatePy::setColorMode(const Py::Tuple& args)
{
    char* name = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "s", &name)) {
        throw Py::Exception();
    }
    if (state()) {
        state()->setColorMode(colorModeFromString(name));
    }
    return Py::None();
}

Py::Object AnalysisViewStatePy::isElementHidden(const Py::Tuple& args)
{
    char* name = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "s", &name)) {
        throw Py::Exception();
    }
    if (!state()) {
        return Py::Boolean(false);
    }
    return Py::Boolean(state()->isElementHidden(name));
}

Py::Object AnalysisViewStatePy::setElementHidden(const Py::Tuple& args)
{
    char* name = nullptr;
    PyObject* hidden = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "sO", &name, &hidden)) {
        throw Py::Exception();
    }
    if (state()) {
        state()->setElementHidden(name, PyObject_IsTrue(hidden) != 0);
    }
    return Py::None();
}

Py::Object AnalysisViewStatePy::getHiddenElements(const Py::Tuple& args)
{
    (void)args;
    Py::List list;
    if (state()) {
        for (const auto& e : state()->hiddenElements()) {
            list.append(Py::String(e));
        }
    }
    return list;
}

Py::Object AnalysisViewStatePy::setHiddenElements(const Py::Tuple& args)
{
    PyObject* seq = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "O", &seq)) {
        throw Py::Exception();
    }
    if (!state()) {
        return Py::None();
    }
    std::set<std::string> elements;
    Py::Sequence sequence(seq);
    for (Py::Sequence::size_type i = 0; i < sequence.size(); ++i) {
        elements.insert(Py::Object(sequence[i]).as_string());
    }
    state()->setHiddenElements(elements);
    return Py::None();
}

Py::Object AnalysisViewStatePy::isCellTypeHidden(const Py::Tuple& args)
{
    char* name = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "s", &name)) {
        throw Py::Exception();
    }
    if (!state()) {
        return Py::Boolean(false);
    }
    return Py::Boolean(state()->isCellTypeHidden(name));
}

Py::Object AnalysisViewStatePy::setCellTypeHidden(const Py::Tuple& args)
{
    char* name = nullptr;
    PyObject* hidden = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "sO", &name, &hidden)) {
        throw Py::Exception();
    }
    if (state()) {
        state()->setCellTypeHidden(name, PyObject_IsTrue(hidden) != 0);
    }
    return Py::None();
}

Py::Object AnalysisViewStatePy::getHiddenCellTypes(const Py::Tuple& args)
{
    (void)args;
    Py::List list;
    if (state()) {
        for (const auto& e : state()->hiddenCellTypes()) {
            list.append(Py::String(e));
        }
    }
    return list;
}

Py::Object AnalysisViewStatePy::setClipPlane(const Py::Tuple& args)
{
    char* name = nullptr;
    PyObject* origin = nullptr;
    PyObject* direction = nullptr;
    if (!PyArg_ParseTuple(
            args.ptr(),
            "sO!O!",
            &name,
            &(Base::VectorPy::Type),
            &origin,
            &(Base::VectorPy::Type),
            &direction
        )) {
        throw Py::Exception();
    }
    if (state()) {
        ClippingPlane plane;
        plane.Origin = *static_cast<Base::VectorPy*>(origin)->getVectorPtr();
        plane.Direction = *static_cast<Base::VectorPy*>(direction)->getVectorPtr();
        state()->setClipPlane(name, plane);
    }
    return Py::None();
}

Py::Object AnalysisViewStatePy::removeClipPlane(const Py::Tuple& args)
{
    char* name = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "s", &name)) {
        throw Py::Exception();
    }
    if (state()) {
        state()->removeClipPlane(name);
    }
    return Py::None();
}

Py::Object AnalysisViewStatePy::getClipPlanes(const Py::Tuple& args)
{
    (void)args;
    Py::Dict dict;
    if (state()) {
        for (const auto& entry : state()->clipPlanes()) {
            Py::Tuple pair(2);
            pair.setItem(0, Py::asObject(new Base::VectorPy(entry.second.Origin)));
            pair.setItem(1, Py::asObject(new Base::VectorPy(entry.second.Direction)));
            dict.setItem(entry.first, pair);
        }
    }
    return dict;
}

Py::Object AnalysisViewStatePy::getCategories(const Py::Tuple& args)
{
    (void)args;
    Py::List list;
    if (!state()) {
        return list;
    }
    for (const auto& cat : state()->categories()) {
        Py::Dict d;
        d.setItem("key", Py::String(cat.key));
        d.setItem("label", Py::String(cat.label));
        Py::Tuple color(4);
        color.setItem(0, Py::Float(cat.color.r));
        color.setItem(1, Py::Float(cat.color.g));
        color.setItem(2, Py::Float(cat.color.b));
        color.setItem(3, Py::Float(cat.color.a));
        d.setItem("color", color);
        list.append(d);
    }
    return list;
}

Py::Object AnalysisViewStatePy::categoryOfElement(const Py::Tuple& args)
{
    char* name = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "s", &name)) {
        throw Py::Exception();
    }
    if (!state()) {
        return Py::Long(-1);
    }
    const Classification* cls = state()->classification();
    if (!cls) {
        return Py::Long(-1);
    }
    return Py::Long(cls->categoryOfElement(name));
}

Py::Object AnalysisViewStatePy::getUnderAchievedElements(const Py::Tuple& args)
{
    (void)args;
    Py::List list;
    if (state()) {
        for (const auto& e : state()->underAchievedElements()) {
            list.append(Py::String(e));
        }
    }
    return list;
}

Py::Object AnalysisViewStatePy::beginUpdate(const Py::Tuple& args)
{
    (void)args;
    if (state()) {
        state()->beginUpdate();
    }
    return Py::None();
}

Py::Object AnalysisViewStatePy::endUpdate(const Py::Tuple& args)
{
    (void)args;
    if (state()) {
        state()->endUpdate();
    }
    return Py::None();
}

Py::Object AnalysisViewStatePy::connectChanged(const Py::Tuple& args)
{
    PyObject* callable = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "O", &callable) || !callable) {
        throw Py::Exception();
    }
    if (!PyCallable_Check(callable)) {
        throw Py::TypeError("connectChanged expects a callable");
    }
    m_pyCallbacks.emplace_back(callable);
    if (!m_changedConn.connected()) {
        if (auto* live = state()) {
            m_changedConn = live->connectChanged([this]() { emitPythonCallbacks(); });
        }
    }
    return Py::None();
}

Py::Object AnalysisViewStatePy::disconnectChanged(const Py::Tuple& args)
{
    PyObject* callable = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "O", &callable) || !callable) {
        throw Py::Exception();
    }
    Py::Object obj(callable);
    m_pyCallbacks.erase(
        std::remove(m_pyCallbacks.begin(), m_pyCallbacks.end(), obj),
        m_pyCallbacks.end()
    );
    if (m_pyCallbacks.empty()) {
        m_changedConn.disconnect();
    }
    return Py::None();
}
