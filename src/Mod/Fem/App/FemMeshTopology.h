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

#include "FemTopology.h"

namespace Fem
{

class FemMesh;
struct DimensionClassification;

/**
 * Derived mesh-side analysis topology.
 *
 * Components come from union-find over model elements joined by shared nodes.
 * Toplevels are named SMESH groups (or definitional catch-alls). Catch-alls are
 * derived on every build and never read back from the mesh, even though the
 * container writes them onto the merged mesh afterwards. Catch-all names use
 * the form ComponentN_Volume / _Surface / _Curve / _Point so they never match
 * isEntityGroupName().
 */
struct FemExport MeshTopology
{
    std::vector<std::vector<int>> componentElements;  ///< model element IDs per component
    std::vector<std::vector<std::string>> componentToplevels;
    std::map<std::string, std::vector<std::string>> entitiesOfToplevel;
    std::map<std::string, std::vector<std::string>> ownersOfEntity;
    std::map<std::string, int> dimensionOfToplevel;
    std::map<std::string, int> dimensionMaskOfEntity;
    std::map<std::string, int> componentOfGroup;  ///< group name -> 0-based component

    /// Model elements of each toplevel, catch-alls included. A catch-all has no
    /// SMESH group behind it, so this is the only place its elements are named.
    std::map<std::string, std::vector<int>> elementsOfToplevel;

    std::size_t componentCount() const
    {
        return componentElements.size();
    }
};

/**
 * Build mesh topology from a classified mesh.
 *
 * Classification is by dimension alone, never by the shape of a group name: a
 * group at the dimension of a component it touches is a toplevel of it, one
 * below that names part of one. An imported deck that happens to carry a group
 * called "Solid1" is therefore read the same way as any other named group, and
 * no origin has to be consulted to keep it from posing as a geometry entity.
 *
 * @param mesh           Mesh whose SMESH groups and elements are read.
 * @param classification Result of classifyDimensions (must use model elements).
 */
FemExport MeshTopology buildMeshTopology(
    const FemMesh& mesh,
    const DimensionClassification& classification
);

/**
 * True when name is a definitional catch-all (ComponentN_Volume etc.).
 */
FemExport bool isCatchAllGroupName(const std::string& name);

/**
 * Suffix for a catch-all of the given dimension: Volume/Surface/Curve/Point.
 */
FemExport const char* catchAllSuffix(int dimension);

}  // namespace Fem
