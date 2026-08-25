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

#include <Base/Vector3D.h>
#include <Mod/Fem/FemGlobal.h>

namespace FemGui
{

/** Clipping plane used by mesh and geometry view providers. */
struct FemGuiExport ClippingPlane
{
    Base::Vector3d Origin;
    Base::Vector3d Direction;

    bool operator==(const ClippingPlane& other) const
    {
        return Origin == other.Origin && Direction == other.Direction;
    }
    bool operator!=(const ClippingPlane& other) const
    {
        return !(*this == other);
    }
};

/** Display dimension mode for mesh rendering. */
enum class DimensionMode
{
    Highest = 0,
    Volume,
    Surface,
    Curve,
    Point
};

/** Preprocessing / result stage shown in the FEM View panel. */
enum class ActiveStage
{
    Geometry = 0,
    Mesh,
    Result  ///< reserved for later post-processing unification
};

/** Colour mode is stage-scoped; valid values depend on ActiveStage. */
enum class ColorMode
{
    Subelement = 0,
    Toplevel,
    Material,
    CellType
};

}  // namespace FemGui
