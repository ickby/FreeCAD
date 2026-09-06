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

#include <cstdint>
#include <vector>

#include <Mod/Fem/FemGlobal.h>

#include <vtkPolyData.h>
#include <vtkPointSet.h>
#include <vtkSmartPointer.h>

namespace FemGui
{

/**
 * The element edges of a boundary surface, as lines fit to hand to Coin.
 *
 * What a renderer wants drawn over a surface is the edges of the elements it
 * was made of, and neither of the obvious ways to get them is right.
 * vtkExtractEdges walks the surface with a point locator and merges as it goes,
 * which on a mesh of any size costs more than everything else the drawing does
 * put together. Reading the edges off a triangulated surface is worse than
 * slow: on curved elements the sides of the little triangles cut across the
 * face and are not element edges at all.
 *
 * So the boundary faces are walked once. No locator is needed, because the
 * point ids already say which points coincide; an edge is named by its two ends
 * and looked up in a flat table, so the one shared by two faces is drawn once;
 * and only the points the edges actually touch are carried out.
 *
 * Both renderers build their edges with this. What they want carried alongside
 * differs - the mesh view colours an edge by the cell it came from, the
 * post-processing view by the values at its points - so both are optional and
 * each asks for the one it uses.
 */
class FemGuiExport BoundaryEdgeBuilder
{
public:
    /**
     * Record the cell each edge came from, read from this cell array of the
     * surface and written to the same array name on the output.
     *
     * Empty for a caller that does not colour by cell. When set and the surface
     * does not carry the array, nothing is built: without it there is no
     * saying what an edge belongs to, and a guess would be a wrong colour.
     */
    void setOriginArray(const char* name)
    {
        m_originArray = name ? name : "";
    }

    /// Carry the point data of the surface onto the points that are kept.
    void setCopyPointData(bool on)
    {
        m_copyPointData = on;
    }

    /**
     * Build the edges of @a surface into @a out.
     *
     * @param curved whether the elements carry points between their corners.
     *        A curved face is asked for its edges, which is what knows where
     *        those points belong; a straight one has its sides read off the
     *        connectivity, which is a good deal cheaper.
     */
    void build(vtkPointSet* surface, bool curved, vtkPolyData* out);

private:
    std::string m_originArray;
    bool m_copyPointData {false};

    // Kept between builds so a redraw does not allocate them again.
    std::vector<vtkIdType> m_pointmap;
    std::vector<std::uint64_t> m_edgeseen;
};

}  // namespace FemGui
