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

#pragma once

#include <memory>

#include <CXX/Extensions.hxx>
#include <CXX/Objects.hxx>

#include "ClipPlaneHandle.h"

namespace FemGui
{

/**
 * Python wrapper owning one ClipPlaneHandle.
 *
 * The handle is torn down with the Python object, so a view panel row that
 * drops its reference also drops the dragger from the 3D view.
 */
class ClipPlaneHandlePy: public Py::PythonExtension<ClipPlaneHandlePy>
{
public:
    using BaseType = Py::PythonExtension<ClipPlaneHandlePy>;

    static void init_type();
    static Py::Object create(std::unique_ptr<ClipPlaneHandle> handle);

    explicit ClipPlaneHandlePy(std::unique_ptr<ClipPlaneHandle> handle);
    ~ClipPlaneHandlePy() override;

    Py::Object repr() override;

    Py::Object getName(const Py::Tuple&);
    Py::Object isActive(const Py::Tuple&);
    Py::Object setActive(const Py::Tuple&);
    Py::Object isWidgetVisible(const Py::Tuple&);
    Py::Object setWidgetVisible(const Py::Tuple&);
    Py::Object getOrigin(const Py::Tuple&);
    Py::Object getNormal(const Py::Tuple&);
    Py::Object setPlane(const Py::Tuple&);
    Py::Object getOffsetStep(const Py::Tuple&);
    Py::Object setOffsetStep(const Py::Tuple&);
    Py::Object getAngleStep(const Py::Tuple&);
    Py::Object setAngleStep(const Py::Tuple&);
    Py::Object refresh(const Py::Tuple&);
    Py::Object remove(const Py::Tuple&);

private:
    std::unique_ptr<ClipPlaneHandle> m_handle;
};

}  // namespace FemGui
