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

#include <Base/VectorPy.h>
#include <Mod/Fem/Gui/ViewProviderFemGeometry.h>

// clang-format off
// inclusion of the generated files (generated out of ViewProviderFemGeometry.pyi)
#include "ViewProviderFemGeometryPy.h"
#include "ViewProviderFemGeometryPy.cpp"
// clang-format on

using namespace FemGui;

std::string ViewProviderFemGeometryPy::representation() const
{
    return {"<ViewProviderFemGeometry object>"};
}

PyObject* ViewProviderFemGeometryPy::setClippingPlane(PyObject* args)
{
    char* name;
    PyObject* pyorigin;
    PyObject* pydirection;
    if (!PyArg_ParseTuple(
            args,
            "sO!O!",
            &name,
            &(Base::VectorPy::Type),
            &pyorigin,
            &(Base::VectorPy::Type),
            &pydirection
        )) {
        return nullptr;
    }

    Base::Vector3d origin = static_cast<Base::VectorPy*>(pyorigin)->value();
    Base::Vector3d direction = static_cast<Base::VectorPy*>(pydirection)->value();

    ClippingPlane cplane;
    cplane.Origin = origin;
    cplane.Direction = direction;
    this->getViewProviderFemGeometryPtr()->setClippingPlane(name, cplane);

    Py_Return;
}

PyObject* ViewProviderFemGeometryPy::removeClippingPlane(PyObject* args)
{
    char* name;
    if (!PyArg_ParseTuple(args, "s", &name)) {
        return nullptr;
    }

    this->getViewProviderFemGeometryPtr()->removeClippingPlane(name);
    Py_Return;
}

PyObject* ViewProviderFemGeometryPy::syncSelectionHighlight(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    this->getViewProviderFemGeometryPtr()->syncSelectionHighlight();
    Py_Return;
}

PyObject* ViewProviderFemGeometryPy::setChainPreview(PyObject* args)
{
    PyObject* pyOn = nullptr;
    if (!PyArg_ParseTuple(args, "O!", &PyBool_Type, &pyOn)) {
        return nullptr;
    }
    this->getViewProviderFemGeometryPtr()->setChainPreview(PyObject_IsTrue(pyOn) != 0);
    Py_Return;
}

PyObject* ViewProviderFemGeometryPy::isChainPreview(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    if (this->getViewProviderFemGeometryPtr()->isChainPreview()) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

PyObject* ViewProviderFemGeometryPy::isChainRenderSuppressed(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    if (this->getViewProviderFemGeometryPtr()->isChainRenderSuppressed()) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

PyObject* ViewProviderFemGeometryPy::setElementHighlight(PyObject* args)
{
    char* role = nullptr;
    PyObject* pyElements = nullptr;
    PyObject* pyColor = nullptr;
    if (!PyArg_ParseTuple(args, "sO|O", &role, &pyElements, &pyColor)) {
        return nullptr;
    }

    Py_ssize_t count = PySequence_Check(pyElements) ? PySequence_Size(pyElements) : -1;
    if (count < 0) {
        PyErr_SetString(PyExc_TypeError, "elements must be a sequence of element names");
        return nullptr;
    }

    std::set<std::string> elements;
    for (Py_ssize_t i = 0; i < count; i++) {
        Py::Object item(PySequence_GetItem(pyElements, i), true);
        if (!PyUnicode_Check(item.ptr())) {
            PyErr_SetString(PyExc_TypeError, "elements must be a sequence of element names");
            return nullptr;
        }
        elements.insert(PyUnicode_AsUTF8(item.ptr()));
    }

    auto color = FemGui::ViewProviderFemGeometry::defaultElementHighlightColor();
    if (pyColor && pyColor != Py_None) {
        if (!PySequence_Check(pyColor) || PySequence_Size(pyColor) != 3) {
            PyErr_SetString(PyExc_TypeError, "color must be an (r, g, b) sequence in 0..1");
            return nullptr;
        }
        float channel[3] {};
        for (Py_ssize_t i = 0; i < 3; i++) {
            Py::Object item(PySequence_GetItem(pyColor, i), true);
            const double value = PyFloat_AsDouble(item.ptr());
            if (PyErr_Occurred()) {
                return nullptr;
            }
            channel[i] = static_cast<float>(value);
        }
        color = Base::Color(channel[0], channel[1], channel[2]);
    }

    this->getViewProviderFemGeometryPtr()->setElementHighlight(role, elements, color);
    Py_Return;
}

PyObject* ViewProviderFemGeometryPy::clearElementHighlight(PyObject* args)
{
    char* role = nullptr;
    if (!PyArg_ParseTuple(args, "s", &role)) {
        return nullptr;
    }

    this->getViewProviderFemGeometryPtr()->clearElementHighlight(role);
    Py_Return;
}

PyObject* ViewProviderFemGeometryPy::getElementHighlight(PyObject* args)
{
    char* role = nullptr;
    if (!PyArg_ParseTuple(args, "s", &role)) {
        return nullptr;
    }

    Py::List elements;
    for (const auto& element : this->getViewProviderFemGeometryPtr()->elementHighlight(role)) {
        elements.append(Py::String(element));
    }
    return Py::new_reference_to(elements);
}

PyObject* ViewProviderFemGeometryPy::getCustomAttributes(const char* /*attr*/) const
{
    return nullptr;
}

int ViewProviderFemGeometryPy::setCustomAttributes(const char* /*attr*/, PyObject* /*obj*/)
{
    return 0;
}
