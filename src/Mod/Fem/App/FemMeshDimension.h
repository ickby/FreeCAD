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

#include <map>
#include <set>
#include <string>
#include <vector>

#include <Mod/Fem/FemGlobal.h>

namespace Fem
{

class FemMesh;
class FemGeometry;

/**
 * Per-cell and per-entity dimension classification for mixed-mesh export.
 *
 * cellDimension[i] is the analysis dimension of element (i+1), or -1 when the
 * element is not part of the model (internal skin / dropped by the filter).
 *
 * entityDimension maps SolidN / FaceN / EdgeN / VertexN group names to the
 * dimension of the structure that entity belongs to. It answers whether a
 * reference to the entity names model elements itself (entity dimension equals
 * the reference dimension) or only the boundary of higher-dimensional elements:
 * Face7 of a solid-meshed component answers 3 even though its group holds
 * triangles. Entities without mesh elements are absent from the map.
 */
struct FemExport DimensionClassification
{
    std::vector<int> cellDimension;
    std::map<std::string, int> entityDimension;

    /** Element IDs kept by the highest-element filter (cellDimension >= 0). */
    std::set<int> modelElementIds() const;
};

/**
 * Classify mesh elements by the layered rule:
 * provenance-scoped achieved dimension, then geometry-declared dimension,
 * then mesh topology.
 *
 * @param mesh         Mesh to classify.
 * @param cellSources  Per-element provenance (index = elementId - 1); empty if none.
 * @param geometry     Optional FemGeometry for entity ownership and overrides.
 */
FemExport DimensionClassification classifyDimensions(
    const FemMesh& mesh,
    const std::vector<std::string>& cellSources,
    const FemGeometry* geometry
);

/**
 * Effective analysis dimension of an owner: min(declared, achieved) when both
 * are known, else whichever is known. Shared by export classification and the
 * visibility mask so the display and the solver see the same rule.
 *
 * @param declared  FemGeometry::getAnalysisDimension result (-1 if unknown).
 * @param achieved  Max cell dimension observed for the owner (-1 if none).
 */
FemExport int effectiveAnalysisDimension(int declared, int achieved);

/**
 * True when name matches SolidN / FaceN / EdgeN / VertexN.
 */
FemExport bool isEntityGroupName(const char* name);

/**
 * Geometric dimension of an SMDS element type: volume=3 .. 0D=0, else -1.
 */
FemExport int smeshElementDimension(int smdsAbsType);

}  // namespace Fem
