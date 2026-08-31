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

#include <string>

#include <Base/Vector3D.h>
#include <Mod/Fem/FemGlobal.h>

namespace Fem
{
class FemGeometry;
}

namespace FemGui
{

/**
 * Where the element names on a mesh grid come from.
 *
 * A grid of a placed instance is meshed and named in the source analysis, so
 * its cells say "Solid1" where the importing analysis means "Import1.Solid1".
 * Without that path a category of the source is taken for a native one of the
 * same name, and every instance of one source ends up sharing its colours.
 */
struct FemGuiExport GridSource
{
    /// Path the elements of the grid are addressed under, "Import1." or empty
    std::string pathPrefix;
    /// Geometry the element names of the grid belong to, null for the analysis one
    Fem::FemGeometry* geometry {nullptr};
};

/** Clipping plane used by mesh and geometry view providers. */
struct FemGuiExport ClippingPlane
{
    Base::Vector3d Origin;
    Base::Vector3d Direction;
    /** Import path prefix, or empty to clip the whole analysis. */
    std::string Scope;
    /**
     * Whether the plane cuts anything at the moment.
     *
     * Being listed and cutting are two different things: a plane switched off
     * keeps its place in the list and its handle in the 3D view, so it can be
     * switched back on where it was left. Only the cutting ones are saved.
     */
    bool Active {true};

    bool operator==(const ClippingPlane& other) const
    {
        return Origin == other.Origin && Direction == other.Direction && Scope == other.Scope
            && Active == other.Active;
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
    Result,  ///< reserved for later post-processing unification
    NoStage  ///< neither geometry nor mesh drawn, the view left to the results
};

/** Colour mode is stage-scoped; valid values depend on ActiveStage. */
enum class ColorMode
{
    Subelement = 0,
    Component,
    Material,
    CellType
};

}  // namespace FemGui
