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

#include <Mod/Fem/App/FemMeshShapeGroup.h>

// inclusion of the generated files
#include "FemMeshShapeGroupPy.h"
#include "FemMeshShapeGroupPy.cpp"

using namespace Fem;

std::string FemMeshShapeGroupPy::representation() const
{
    return {"<FemMeshShapeGroup object>"};
}

PyObject* FemMeshShapeGroupPy::getComponentOwners(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }

    Py::Dict owners;
    for (const auto& [index, mesh] : this->getFemMeshShapeGroupPtr()->getComponentOwners()) {
        if (!mesh) {
            continue;
        }
        owners.setItem(Py::Int(index), Py::asObject(mesh->getPyObject()));
    }
    return Py::new_reference_to(owners);
}

PyObject* FemMeshShapeGroupPy::getComponentCount(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    return Py::new_reference_to(
        Py::Int(static_cast<long>(this->getFemMeshShapeGroupPtr()->componentCount()))
    );
}

PyObject* FemMeshShapeGroupPy::getToplevelElements(PyObject* args)
{
    int idx = 0;
    if (!PyArg_ParseTuple(args, "i", &idx)) {
        return nullptr;
    }
    Py::List names;
    for (const auto& name :
         this->getFemMeshShapeGroupPtr()->toplevelElements(static_cast<unsigned int>(idx))) {
        names.append(Py::String(name));
    }
    return Py::new_reference_to(names);
}

PyObject* FemMeshShapeGroupPy::getEntities(PyObject* args)
{
    const char* name = nullptr;
    if (!PyArg_ParseTuple(args, "s", &name)) {
        return nullptr;
    }
    Py::List entities;
    for (const auto& entity : this->getFemMeshShapeGroupPtr()->entities(name)) {
        entities.append(Py::String(entity));
    }
    return Py::new_reference_to(entities);
}

PyObject* FemMeshShapeGroupPy::getEntityOwners(PyObject* args)
{
    const char* name = nullptr;
    if (!PyArg_ParseTuple(args, "s", &name)) {
        return nullptr;
    }
    Py::List owners;
    for (const auto& owner : this->getFemMeshShapeGroupPtr()->entityOwners(name)) {
        owners.append(Py::String(owner));
    }
    return Py::new_reference_to(owners);
}

PyObject* FemMeshShapeGroupPy::getAnalysisDimension(PyObject* args)
{
    const char* name = nullptr;
    if (!PyArg_ParseTuple(args, "s", &name)) {
        return nullptr;
    }
    return Py::new_reference_to(
        Py::Int(this->getFemMeshShapeGroupPtr()->analysisDimension(name))
    );
}

PyObject* FemMeshShapeGroupPy::getEntityDimensionMask(PyObject* args)
{
    const char* name = nullptr;
    if (!PyArg_ParseTuple(args, "s", &name)) {
        return nullptr;
    }
    return Py::new_reference_to(
        Py::Int(this->getFemMeshShapeGroupPtr()->entityDimensionMask(name))
    );
}

PyObject* FemMeshShapeGroupPy::getMergeRevision(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    return Py::new_reference_to(
        Py::Int(static_cast<long>(this->getFemMeshShapeGroupPtr()->mergeRevision()))
    );
}

PyObject* FemMeshShapeGroupPy::getTopologyRevision(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    return Py::new_reference_to(
        Py::Int(static_cast<long>(this->getFemMeshShapeGroupPtr()->topologyRevision()))
    );
}

PyObject* FemMeshShapeGroupPy::getGroupElementsByName(PyObject* args)
{
    const char* name = nullptr;
    if (!PyArg_ParseTuple(args, "s", &name)) {
        return nullptr;
    }
    Py::List ids;
    for (int eid : this->getFemMeshShapeGroupPtr()->groupElementsByName(name)) {
        ids.append(Py::Int(eid));
    }
    return Py::new_reference_to(ids);
}

PyObject* FemMeshShapeGroupPy::getCustomAttributes(const char* /*attr*/) const
{
    return nullptr;
}

int FemMeshShapeGroupPy::setCustomAttributes(const char* /*attr*/, PyObject* /*obj*/)
{
    return 0;
}
