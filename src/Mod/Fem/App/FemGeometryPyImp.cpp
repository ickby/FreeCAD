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

#ifndef _PreComp_
#endif

#include <Mod/Part/App/PartPyCXX.h>
#include <Mod/Fem/App/FemGeometry.h>

// inclusion of the generated files
#include "FemGeometryPy.h"
#include "FemGeometryPy.cpp"

using namespace Fem;

std::string FemGeometryPy::representation() const
{
    return {"<FemGeometry object>"};
}

PyObject* FemGeometryPy::getComponents(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }

    auto components = this->getFemGeometryPtr()->getComponents();
    Py::List pyComponents;
    for (auto& component : components) {
        Py::List pyComponent;
        for (auto& subshape : component) {
            pyComponent.append(shape2pyshape(subshape));
        }
        pyComponents.append(pyComponent);
    }
    return Py::new_reference_to(pyComponents);
}

PyObject* FemGeometryPy::getComponentCount(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }

    auto components = this->getFemGeometryPtr()->getComponents();
    return Py::new_reference_to(Py::Int(static_cast<long>(components.size())));
}

PyObject* FemGeometryPy::getToplevelElements(PyObject* args)
{
    int idx;
    if (!PyArg_ParseTuple(args, "i", &idx)) {
        return nullptr;
    }

    auto elements = this->getFemGeometryPtr()->getToplevelElements(static_cast<unsigned int>(idx));
    Py::List pyToplevel;
    for (auto& element : elements) {
        pyToplevel.append(Py::String(element));
    }
    return Py::new_reference_to(pyToplevel);
}

PyObject* FemGeometryPy::getGeometricDimension(PyObject* args)
{
    const char* name = nullptr;
    if (!PyArg_ParseTuple(args, "s", &name)) {
        return nullptr;
    }
    return Py::new_reference_to(
        Py::Int(this->getFemGeometryPtr()->getGeometricDimension(name))
    );
}

PyObject* FemGeometryPy::getAnalysisDimension(PyObject* args)
{
    const char* name = nullptr;
    if (!PyArg_ParseTuple(args, "s", &name)) {
        return nullptr;
    }
    return Py::new_reference_to(
        Py::Int(this->getFemGeometryPtr()->getAnalysisDimension(name))
    );
}

PyObject* FemGeometryPy::getEntityOwners(PyObject* args)
{
    const char* name = nullptr;
    if (!PyArg_ParseTuple(args, "s", &name)) {
        return nullptr;
    }
    Py::List owners;
    for (const auto& owner : this->getFemGeometryPtr()->getEntityOwners(name)) {
        owners.append(Py::String(owner));
    }
    return Py::new_reference_to(owners);
}

PyObject* FemGeometryPy::getEntities(PyObject* args)
{
    const char* name = nullptr;
    if (!PyArg_ParseTuple(args, "s", &name)) {
        return nullptr;
    }
    Py::List entities;
    for (const auto& entity : this->getFemGeometryPtr()->entities(name)) {
        entities.append(Py::String(entity));
    }
    return Py::new_reference_to(entities);
}

PyObject* FemGeometryPy::getEntityDimensionMask(PyObject* args)
{
    const char* name = nullptr;
    if (!PyArg_ParseTuple(args, "s", &name)) {
        return nullptr;
    }
    return Py::new_reference_to(
        Py::Int(this->getFemGeometryPtr()->getEntityDimensionMask(name))
    );
}

PyObject* FemGeometryPy::getTopologyRevision(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    return Py::new_reference_to(
        Py::Int(static_cast<long>(this->getFemGeometryPtr()->topologyRevision()))
    );
}

PyObject* FemGeometryPy::getCustomAttributes(const char* /*attr*/) const
{
    return nullptr;
}

int FemGeometryPy::setCustomAttributes(const char* /*attr*/, PyObject* /*obj*/)
{
    return 0;
}
