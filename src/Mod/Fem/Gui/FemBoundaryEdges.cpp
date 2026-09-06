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
# include <algorithm>
# include <vtkCellArray.h>
# include <vtkCellData.h>
# include <vtkGenericCell.h>
# include <vtkIdList.h>
# include <vtkIntArray.h>
# include <vtkPointData.h>
# include <vtkPoints.h>
#endif

#include "FemBoundaryEdges.h"

using namespace FemGui;

namespace
{

/// One key per undirected point pair, naming an element edge by its two ends.
inline std::uint64_t edgeKey(vtkIdType a, vtkIdType b)
{
    const auto lo = static_cast<std::uint64_t>(std::min(a, b));
    const auto hi = static_cast<std::uint64_t>(std::max(a, b));
    return (lo << 32) | (hi & 0xFFFFFFFFULL);
}

}  // namespace

void BoundaryEdgeBuilder::build(vtkPointSet* surface, bool curved, vtkPolyData* out)
{
    out->Initialize();
    if (!surface) {
        out->Modified();
        return;
    }

    // Which cell of the mesh each face came from. Not vtkOriginalCellIds: the
    // surface filter numbers those by the intermediate faces it makes of a
    // quadratic cell, not by the cells it was given, so on a quadratic mesh
    // they name the wrong cells and run off the end of it. The baked array says
    // it outright and is carried through as ordinary cell data.
    vtkIntArray* origin = nullptr;
    if (!m_originArray.empty()) {
        origin = vtkIntArray::SafeDownCast(surface->GetCellData()->GetArray(m_originArray.c_str()));
        if (!origin) {
            out->Modified();
            return;
        }
    }

    // Points are numbered as they are met rather than looked up by position. A
    // locator exists to work out which points coincide, and here nothing does:
    // the ids say it already. What is drawn stays as small as the edges need,
    // instead of carrying the interior of the mesh to Coin.
    m_pointmap.assign(static_cast<std::size_t>(surface->GetNumberOfPoints()), -1);

    const vtkIdType numfaces = surface->GetNumberOfCells();
    const auto edgeguess = static_cast<std::size_t>(numfaces) * 4;

    auto points = vtkSmartPointer<vtkPoints>::New();
    if (auto* source = surface->GetPoints()) {
        points->SetDataType(source->GetDataType());
    }
    auto lines = vtkSmartPointer<vtkCellArray>::New();
    lines->AllocateEstimate(static_cast<vtkIdType>(edgeguess), 3);

    vtkSmartPointer<vtkIntArray> outcell;
    if (origin) {
        // Of everything the cells carry, only the cell each drawn one came from
        // is ever asked for again, by the colouring. Copying the rest through
        // costs more than the edges themselves, and here it is the id we
        // already walk by.
        outcell = vtkSmartPointer<vtkIntArray>::New();
        outcell->SetName(m_originArray.c_str());
        outcell->SetNumberOfComponents(1);
        outcell->Allocate(static_cast<vtkIdType>(edgeguess));
    }

    // A view that colours an edge by the values at its ends needs those values
    // to travel with the points it keeps, or the arrays and the points would no
    // longer be the same length and every colour would be somebody else's.
    vtkPointData* inPointData = surface->GetPointData();
    vtkPointData* outPointData = out->GetPointData();
    if (m_copyPointData && inPointData) {
        outPointData->CopyAllocate(inPointData);
    }

    // Neighbouring cells share edges, and an edge drawn twice is an edge drawn
    // twice as slowly. Its two ends name it, whichever cell reports it.
    //
    // The plainest hash set there is: a power-of-two table of keys, probed
    // linearly, empty where it is zero, which no edge can be since an edge
    // joins two different points. A general one spends more time following
    // pointers than this whole walk does enumerating the edges.
    std::size_t capacity = 16;
    while (capacity < edgeguess * 2 + 16) {
        capacity <<= 1;
    }
    m_edgeseen.assign(capacity, 0);
    const std::size_t mask = capacity - 1;
    auto unseen = [this, mask](std::uint64_t key) {
        std::size_t at = static_cast<std::size_t>((key * 0x9E3779B97F4A7C15ULL) >> 32) & mask;
        while (true) {
            std::uint64_t& slot = m_edgeseen[at];
            if (slot == 0) {
                slot = key;
                return true;
            }
            if (slot == key) {
                return false;
            }
            at = (at + 1) & mask;
        }
    };

    std::vector<vtkIdType> chain;
    std::vector<vtkIdType> mapped;

    const bool copyPoints = m_copyPointData && inPointData;
    auto pointOf = [&](vtkIdType id) {
        vtkIdType& at = m_pointmap[static_cast<std::size_t>(id)];
        if (at < 0) {
            double xyz[3];
            surface->GetPoint(id, xyz);
            at = points->InsertNextPoint(xyz);
            if (copyPoints) {
                outPointData->CopyData(inPointData, id, at);
            }
        }
        return at;
    };

    // The whole edge goes in as one line, curved ones included. Two lines
    // meeting at a midpoint leave it to chance whether the midpoint is drawn,
    // and OpenGL tends to decide that it is not; within one line there is no
    // such question.
    //
    // A 1D element is claimed without being drawn. It is not an element edge:
    // the surface filter hands it over as a line of its own, through the same
    // points, and that copy is the one coloured as the element it is. Claiming
    // it here is still what keeps a face lying along it from drawing a dark
    // edge over the top of it.
    auto emit = [&](int owner, bool draw = true) {
        // An edge that ends where it starts has no key of its own, zero being
        // the one the table reads as an empty slot, and nothing to draw either.
        if (chain.size() < 2 || chain.front() == chain.back()) {
            return;
        }
        if (!unseen(edgeKey(chain.front(), chain.back()))) {
            return;
        }
        if (!draw) {
            return;
        }
        mapped.clear();
        for (vtkIdType id : chain) {
            mapped.push_back(pointOf(id));
        }
        lines->InsertNextCell(static_cast<int>(mapped.size()), mapped.data());
        if (outcell) {
            outcell->InsertNextValue(owner);
        }
    };

    // VTK numbers a curved edge with its two ends first and the points between
    // them after, so walking one means going out to the middle and back.
    auto chainOf = [&chain](vtkIdList* ids) {
        chain.clear();
        const vtkIdType num = ids->GetNumberOfIds();
        if (num < 2) {
            return;
        }
        chain.push_back(ids->GetId(0));
        for (vtkIdType i = 2; i < num; ++i) {
            chain.push_back(ids->GetId(i));
        }
        chain.push_back(ids->GetId(1));
    };

    auto ownerOf = [origin](vtkIdType cell) {
        return origin ? origin->GetValue(cell) : 0;
    };

    if (curved) {
        // Asking each face for its edges, which is what knows where the points
        // between the corners belong. It reads a whole cell out to answer, and
        // is the reason the straight case does not go this way.
        auto cell = vtkSmartPointer<vtkGenericCell>::New();
        for (vtkIdType face = 0; face < numfaces; ++face) {
            surface->GetCell(face, cell);
            const int owner = ownerOf(face);
            const int numedges = cell->GetNumberOfEdges();

            // A point or a beam has no edges of its own to report; its own
            // points are where an element edge would run.
            if (numedges == 0) {
                chainOf(cell->GetPointIds());
                emit(owner, false);
                continue;
            }
            for (int e = 0; e < numedges; ++e) {
                chainOf(cell->GetEdge(e)->GetPointIds());
                emit(owner);
            }
        }
    }
    else {
        // Straight elements have nothing between their corners, so the sides of
        // a polygon can be read off the connectivity as it lies. The cell data
        // counts the vertices and the lines before the polygons.
        auto* poly = vtkPolyData::SafeDownCast(surface);
        if (!poly) {
            out->Modified();
            return;
        }
        const vtkIdType numverts = poly->GetNumberOfVerts();
        const vtkIdType numlines = poly->GetNumberOfLines();
        auto ids = vtkSmartPointer<vtkIdList>::New();

        // Claimed before the faces are walked, so that a beam always wins the
        // edge it shares with one. The grid is written in rising dimension, and
        // the filters keep that order, so the curved branch above meets them in
        // the same order for the same reason.
        auto* beams = poly->GetLines();
        for (vtkIdType at = 0; at < numlines; ++at) {
            beams->GetCellAtId(at, ids);
            chain.assign(ids->begin(), ids->end());
            emit(ownerOf(numverts + at), false);
        }

        auto* faces = poly->GetPolys();
        const vtkIdType numfacecells = faces->GetNumberOfCells();
        for (vtkIdType at = 0; at < numfacecells; ++at) {
            faces->GetCellAtId(at, ids);
            const vtkIdType corners = ids->GetNumberOfIds();
            const int owner = ownerOf(numverts + numlines + at);
            for (vtkIdType i = 0; i < corners; ++i) {
                chain.clear();
                chain.push_back(ids->GetId(i));
                chain.push_back(ids->GetId((i + 1) % corners));
                emit(owner);
            }
        }
    }

    out->SetPoints(points);
    out->SetLines(lines);
    if (outcell) {
        out->GetCellData()->AddArray(outcell);
    }
    out->Modified();
}
