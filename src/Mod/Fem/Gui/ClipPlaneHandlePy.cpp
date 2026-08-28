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

#include <sstream>

#include <Base/VectorPy.h>

#include "ClipPlaneHandlePy.h"

using namespace FemGui;

void ClipPlaneHandlePy::init_type()
{
    behaviors().name("ClipPlaneHandle");
    behaviors().doc("Interactive clip plane of one FEM analysis");
    behaviors().supportRepr();

    add_varargs_method("getName", &ClipPlaneHandlePy::getName, "getName()");
    add_varargs_method("isActive", &ClipPlaneHandlePy::isActive, "isActive()");
    add_varargs_method("setActive", &ClipPlaneHandlePy::setActive, "setActive(bool)");
    add_varargs_method("isWidgetVisible", &ClipPlaneHandlePy::isWidgetVisible, "isWidgetVisible()");
    add_varargs_method("setWidgetVisible", &ClipPlaneHandlePy::setWidgetVisible, "setWidgetVisible(bool)");
    add_varargs_method(
        "getScope",
        &ClipPlaneHandlePy::getScope,
        "getScope() -- path of the instance the plane cuts, empty for all of them"
    );
    add_varargs_method(
        "setScope",
        &ClipPlaneHandlePy::setScope,
        "setScope(str) -- restrict the plane to the instance at that path and "
        "everything inside it. An empty path cuts the whole analysis."
    );
    add_varargs_method("getOrigin", &ClipPlaneHandlePy::getOrigin, "getOrigin()");
    add_varargs_method("getNormal", &ClipPlaneHandlePy::getNormal, "getNormal()");
    add_varargs_method("setPlane", &ClipPlaneHandlePy::setPlane, "setPlane(Vector origin, Vector normal)");
    add_varargs_method(
        "getOffsetStep",
        &ClipPlaneHandlePy::getOffsetStep,
        "getOffsetStep() -- offset step of the arrow, automatic one included"
    );
    add_varargs_method(
        "setOffsetStep",
        &ClipPlaneHandlePy::setOffsetStep,
        "setOffsetStep(float) -- offset step, shared by all clip planes and "
        "stored in the preferences. 0 restores the automatic step."
    );
    add_varargs_method(
        "getAngleStep",
        &ClipPlaneHandlePy::getAngleStep,
        "getAngleStep() -- rotation step of the angle handles in degree"
    );
    add_varargs_method(
        "setAngleStep",
        &ClipPlaneHandlePy::setAngleStep,
        "setAngleStep(float) -- rotation step in degree, shared by all clip "
        "planes and stored in the preferences"
    );
    add_varargs_method(
        "refresh",
        &ClipPlaneHandlePy::refresh,
        "refresh() -- re-fit the plane indicator and adopt the view state"
    );
    add_varargs_method(
        "remove",
        &ClipPlaneHandlePy::remove,
        "remove() -- drop the plane and its 3D widget"
    );

    // Without this the methods registered above are not reachable from Python.
    behaviors().supportGetattr();
    behaviors().readyType();
}

Py::Object ClipPlaneHandlePy::create(std::unique_ptr<ClipPlaneHandle> handle)
{
    return Py::asObject(new ClipPlaneHandlePy(std::move(handle)));
}

ClipPlaneHandlePy::ClipPlaneHandlePy(std::unique_ptr<ClipPlaneHandle> handle)
    : m_handle(std::move(handle))
{}

ClipPlaneHandlePy::~ClipPlaneHandlePy() = default;

Py::Object ClipPlaneHandlePy::repr()
{
    std::ostringstream s;
    s << "<ClipPlaneHandle " << (m_handle ? m_handle->name() : std::string("removed")) << ">";
    return Py::String(s.str());
}

Py::Object ClipPlaneHandlePy::getName(const Py::Tuple& args)
{
    (void)args;
    return Py::String(m_handle ? m_handle->name() : std::string());
}

Py::Object ClipPlaneHandlePy::isActive(const Py::Tuple& args)
{
    (void)args;
    return Py::Boolean(m_handle && m_handle->isActive());
}

Py::Object ClipPlaneHandlePy::setActive(const Py::Tuple& args)
{
    PyObject* value = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "O", &value)) {
        throw Py::Exception();
    }
    if (m_handle) {
        m_handle->setActive(PyObject_IsTrue(value) != 0);
    }
    return Py::None();
}

Py::Object ClipPlaneHandlePy::isWidgetVisible(const Py::Tuple& args)
{
    (void)args;
    return Py::Boolean(m_handle && m_handle->isWidgetVisible());
}

Py::Object ClipPlaneHandlePy::setWidgetVisible(const Py::Tuple& args)
{
    PyObject* value = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "O", &value)) {
        throw Py::Exception();
    }
    if (m_handle) {
        m_handle->setWidgetVisible(PyObject_IsTrue(value) != 0);
    }
    return Py::None();
}

Py::Object ClipPlaneHandlePy::getScope(const Py::Tuple& args)
{
    (void)args;
    return Py::String(m_handle ? m_handle->scope() : std::string());
}

Py::Object ClipPlaneHandlePy::setScope(const Py::Tuple& args)
{
    const char* scope = nullptr;
    if (!PyArg_ParseTuple(args.ptr(), "s", &scope)) {
        throw Py::Exception();
    }
    if (m_handle) {
        m_handle->setScope(scope ? scope : "");
    }
    return Py::None();
}

Py::Object ClipPlaneHandlePy::getOrigin(const Py::Tuple& args)
{
    (void)args;
    Base::Vector3d origin = m_handle ? m_handle->origin() : Base::Vector3d();
    return Py::asObject(new Base::VectorPy(origin));
}

Py::Object ClipPlaneHandlePy::getNormal(const Py::Tuple& args)
{
    (void)args;
    Base::Vector3d normal = m_handle ? m_handle->normal() : Base::Vector3d(0, 0, 1);
    return Py::asObject(new Base::VectorPy(normal));
}

Py::Object ClipPlaneHandlePy::setPlane(const Py::Tuple& args)
{
    PyObject* origin = nullptr;
    PyObject* normal = nullptr;
    if (!PyArg_ParseTuple(
            args.ptr(),
            "O!O!",
            &(Base::VectorPy::Type),
            &origin,
            &(Base::VectorPy::Type),
            &normal
        )) {
        throw Py::Exception();
    }
    if (m_handle) {
        m_handle->setPlane(
            *static_cast<Base::VectorPy*>(origin)->getVectorPtr(),
            *static_cast<Base::VectorPy*>(normal)->getVectorPtr()
        );
    }
    return Py::None();
}

Py::Object ClipPlaneHandlePy::getOffsetStep(const Py::Tuple& args)
{
    (void)args;
    return Py::Float(m_handle ? m_handle->appliedOffsetStep() : ClipPlaneHandle::offsetStep());
}

Py::Object ClipPlaneHandlePy::setOffsetStep(const Py::Tuple& args)
{
    double step = 0.0;
    if (!PyArg_ParseTuple(args.ptr(), "d", &step)) {
        throw Py::Exception();
    }
    // Shared by every plane, so this reaches past the handle it is called on
    ClipPlaneHandle::setOffsetStep(step);
    return Py::None();
}

Py::Object ClipPlaneHandlePy::getAngleStep(const Py::Tuple& args)
{
    (void)args;
    return Py::Float(ClipPlaneHandle::angleStep());
}

Py::Object ClipPlaneHandlePy::setAngleStep(const Py::Tuple& args)
{
    double degree = 0.0;
    if (!PyArg_ParseTuple(args.ptr(), "d", &degree)) {
        throw Py::Exception();
    }
    ClipPlaneHandle::setAngleStep(degree);
    return Py::None();
}

Py::Object ClipPlaneHandlePy::refresh(const Py::Tuple& args)
{
    (void)args;
    if (m_handle) {
        m_handle->refresh();
    }
    return Py::None();
}

Py::Object ClipPlaneHandlePy::remove(const Py::Tuple& args)
{
    (void)args;
    m_handle.reset();
    return Py::None();
}
