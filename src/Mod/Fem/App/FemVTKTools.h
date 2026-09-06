// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2015 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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

#include <vtkDataSet.h>
#include <vtkSmartPointer.h>
#include <vtkUnstructuredGrid.h>

#include <App/DocumentObject.h>

#include "FemMeshObject.h"

#include <string>
#include <vector>


namespace Fem
{
class FemAnalysis;

// utility class to import/export read/write vtk mesh and result
class FemExport FemVTKTools
{
public:
    // extract data from vtkUnstructuredGrid instance and fill a FreeCAD FEM mesh object with that
    // data
    static void importVTKMesh(vtkSmartPointer<vtkDataSet> grid, FemMesh* mesh, float scale = 1.0);

    // uses the content of the cell array and convert it into FemMeshGroup. Ever unique entry in the
    // cell array becomes a group, and  this group contains all elements with the entry. If the cell
    // array is a Integer array the value becomes the groupID, if it is a string array the value
    // becomes the group name. Other cell types are not supported.
    static void importVTKCellGroup(vtkSmartPointer<vtkDataSet> grid, FemMesh* mesh, std::string arrayname);

    // extract data from FreCAD FEM mesh and fill a vtkUnstructuredGrid instance with that data. Set
    // `highest` to false to export all elements levels. When true, uses per-entity highest
    // filtering (volumes of solids plus free faces/edges), not a global dimension fallback.
    //
    // Cells are grouped by element type, so their order does not follow the SMESH
    // element ids. Pass `cellElementIds` to receive the SMESH element id of every
    // written cell; that mapping is required by exportVTKCellGroup.
    static void exportVTKMesh(
        const FemMesh* mesh,
        vtkSmartPointer<vtkUnstructuredGrid> grid,
        bool highest = true,
        float scale = 1.0,
        std::vector<int>* cellElementIds = nullptr
    );

    // Build a VTK cell array from FemMesh groups and attach it to the grid.
    // If index_map is empty, write group names as strings. Otherwise write the
    // mapped integer id for each group; groups not present in index_map are
    // skipped (sentinel -1), so refinement/analysis groups are not mis-attributed.
    //
    // `cellElementIds` must be the mapping returned by exportVTKMesh for this grid.
    // Group elements that are not part of the grid (filtered out by `highest`) are
    // ignored.
    static void exportVTKCellGroup(
        FemMesh* mesh,
        vtkSmartPointer<vtkDataSet> grid,
        std::string arrayname,
        std::map<std::string, int> index_map,
        const std::vector<int>& cellElementIds
    );

    // extract data from vtkUnstructuredGrid object and fill a FreeCAD FEM result object with that
    // data (needed by readResult)
    static void importFreeCADResult(vtkSmartPointer<vtkDataSet> dataset, App::DocumentObject* result);

    // extract data from a FreeCAD FEM result object and fill a vtkUnstructuredGrid object with that
    // data (needed by writeResult)
    static void exportFreeCADResult(const App::DocumentObject* result, vtkSmartPointer<vtkDataSet> grid);

    // FemMesh read from vtkUnstructuredGrid data file
    static FemMesh* readVTKMesh(const char* filename, FemMesh* mesh, const char* group_array = nullptr);

    // FemMesh write to vtkUnstructuredGrid data file
    static void writeVTKMesh(const char* Filename, const FemMesh* mesh, bool highest = true);
    static void writeVTKMeshWithGroups(
        std::string Filename,
        FemMesh* mesh,
        std::string group_array,
        std::map<std::string, int> index_map,
        bool highest = true
    );

    // FemResult (activeObject or created if res= NULL) read from vtkUnstructuredGrid dataset file
    static App::DocumentObject* readResult(const char* Filename, App::DocumentObject* res = nullptr);

    // write FemResult (activeObject if res= NULL) to vtkUnstructuredGrid dataset file
    static void writeResult(const char* filename, const App::DocumentObject* res = nullptr);

    static void frdToVTK(const char* filename, bool binary = true);

    static void addArrayFromFunction(
        vtkSmartPointer<vtkDataObject>& data,
        const std::map<std::string, std::string>& functions
    );

    /// Per-cell index into the entity table, -1 where nothing could be said.
    /// The same array name the mesh grids use, so a filter that reads one
    /// reads the other.
    static constexpr const char* ArrayEntityIds = "CellEntityIds";
    /// Field data: the entity name of every index, in index order.
    static constexpr const char* ArrayAttributionEntities = "AttributionEntities";
    /// Field data: entity name, component key, component label - three values
    /// per row. Component and material are functions of the entity name, not
    /// of the cell, so they are side tables rather than per-cell arrays.
    static constexpr const char* ArrayAttributionComponent = "AttributionComponent";
    /// Field data: entity name, material key, material label - three per row.
    static constexpr const char* ArrayAttributionMaterial = "AttributionMaterial";

    /**
     * Write onto a result what the analysis it came out of was made of.
     *
     * A result outlives the mesh and the geometry it was computed from: both
     * are routinely replaced, and a reloaded document may hold neither. So the
     * answer is resolved once, here, and stored on the grid itself, where
     * PropertyPostDataObject serialises it along with the rest of the data.
     * What is stored is the conclusion - which entity, which component, which
     * material - never the objects it was drawn from.
     *
     * The material is the one the analysis was solved with. Reassigning a
     * material afterwards says nothing about a result that already exists, so
     * nothing re-runs this; the caller does, once, and only where it knows the
     * result is the one it just computed.
     *
     * @param data      a grid, or the multi-block set a multi-frame result is.
     *                  Every block describes the same mesh, so all of them are
     *                  attributed alike.
     * @param mesh      the mesh that was solved, groups and all.
     * @param cellSources import path of every cell of @a mesh, indexed as
     *                  elementId - 1, as SolveAssemblyResult reports it. Empty
     *                  entries are cells the analysis meshed itself. May be
     *                  shorter than the mesh, which reads as all-native.
     * @param analysis  the analysis the components and materials are read from.
     */
    static void attributeResult(
        vtkSmartPointer<vtkDataObject> data,
        FemMesh& mesh,
        const std::vector<std::string>& cellSources,
        const FemAnalysis* analysis
    );
};
}  // namespace Fem
