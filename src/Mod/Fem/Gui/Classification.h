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
#include <memory>
#include <string>
#include <vector>

#include <Base/Color.h>
#include <Mod/Fem/FemGlobal.h>

#include "FemViewTypes.h"

#include <vtkSmartPointer.h>
#include <vtkType.h>
#include <vtkUnstructuredGrid.h>

namespace Fem
{
class AnalysisTopology;
class FemGeometry;
class FemAnalysis;
}

namespace App
{
class DocumentObject;
}

namespace FemGui
{

/** One colour category shared by the view-panel tree and mesh/geometry colouring. */
struct FemGuiExport Category
{
    std::string key;    ///< Stable identity (material Name, VTKCellType, element name, ...)
    std::string label;  ///< Display label
    Base::Color color;
    /// Cells the mesher built the mesh from rather than ones the analysis
    /// solves on. Only CellType tells the two apart; the label stays the same
    /// for both, the tree groups by this.
    bool construction {false};
    /// Cells in the category, where counting them is the classification's to
    /// do; the tree counts its own children for the geometry-keyed modes.
    int count {0};
};

/**
 * Abstraction driving smart colouring and the grouped view-panel tree.
 *
 * Concrete modes: Subelement, Component, Material, CellType.
 * Instances are computed once per analysis and shared by geometry and mesh VPs.
 */
class FemGuiExport Classification
{
public:
    virtual ~Classification() = default;

    /**
     * The categories this classification sorts into, in palette order.
     *
     * Every mode builds the same three tables - the categories, the key each
     * one is known by, and the category each cell of the grid fell into - and
     * differs only in how it fills them and how it answers for a geometry
     * element. So the tables and the two answers that read them straight off
     * live here, and a mode is its build() and its categoryOfElement().
     */
    std::vector<Category> categories() const;

    /// The category of @a cell, or 0 when the cell is not one of this grid's.
    int categoryOfCell(vtkIdType cell) const;

    virtual int categoryOfElement(const std::string& element) const = 0;

    /**
     * Colour of the n-th category, wrapping the live palette.
     *
     * Categories are sorted by key before they are numbered, so the same set
     * of names always lands on the same colours, and the first twelve names
     * take the twelve most distinct entries. A later FEM setting can replace
     * the palette without anything in a document having to change.
     */
    static Base::Color colorForIndex(int index);

    /**
     * The washed-out twin of a category colour, for the construction elements.
     *
     * Skin triangles and shell triangles are the same VTK type, so the two
     * keep the one hue their type was given and it is the tone that tells them
     * apart: scaffolding reads as the pale one without a legend to consult.
     */
    static Base::Color constructionColor(const Base::Color& color);

    /**
     * Build the classification for the active colour mode.
     * @param meshGrid Optional; required for CellType (and cell lookups for mesh modes).
     * @param gridSource Where the element names of @a meshGrid come from.
     * @param meshTopology The mesh group, when the Mesh stage is colouring by
     *                     its partition rather than the geometry's. Null in
     *                     every other stage, and it is the null that says so.
     * @param paletteOrder Analysis-wide key -> palette index, so geometry and
     *                     mesh classifications of the same mode agree on colour.
     */
    static std::unique_ptr<Classification> create(
        ColorMode mode,
        Fem::FemAnalysis* analysis,
        Fem::FemGeometry* geometry,
        vtkUnstructuredGrid* meshGrid = nullptr,
        const GridSource& gridSource = {},
        const Fem::AnalysisTopology* meshTopology = nullptr,
        const std::map<std::string, int>* paletteOrder = nullptr
    );

protected:
    /// @a geometry is what element names are resolved against; null for mesh-only modes.
    explicit Classification(Fem::FemGeometry* geometry = nullptr)
        : m_geometry(geometry)
    {}

    Fem::FemGeometry* m_geometry {nullptr};
    std::vector<Category> m_categories;
    /// Category key -> its index in m_categories
    std::map<std::string, int> m_keyToIndex;
    /// Category of each cell of the input grid
    std::vector<int> m_cellCategory;
};

/** One colour per geometry entity (Face7, Solid3, ...). */
class FemGuiExport SubelementClassification: public Classification
{
public:
    SubelementClassification(
        Fem::FemAnalysis* analysis,
        Fem::FemGeometry* geometry,
        vtkUnstructuredGrid* meshGrid,
        const GridSource& gridSource = {},
        const Fem::AnalysisTopology* meshTopology = nullptr,
        const std::map<std::string, int>* paletteOrder = nullptr
    );

    int categoryOfElement(const std::string& element) const override;

private:
    void build(
        Fem::FemAnalysis* analysis,
        Fem::FemGeometry* geometry,
        vtkUnstructuredGrid* meshGrid,
        const GridSource& gridSource,
        const Fem::AnalysisTopology* meshTopology,
        const std::map<std::string, int>* paletteOrder
    );
};

/**
 * One colour per component, shared by everything the component is made of.
 *
 * A component is the piece of geometry (or mesh connectivity) that hangs
 * together, and it is the unit the user assembles an analysis from, so its
 * faces and edges are the one thing that must not be told apart here: a shell
 * of forty faces is one colour, and the next component is the next colour.
 *
 * In the Mesh stage the components come from the mesh topology. Where that
 * partition differs from the geometry (a mesher fusing touching parts), each
 * mesh component inherits the colour of the geometry component it shares the
 * most toplevels with, so as many elements as possible keep the colour they
 * had in the Geometry stage.
 */
class FemGuiExport ComponentClassification: public Classification
{
public:
    ComponentClassification(
        Fem::FemAnalysis* analysis,
        Fem::FemGeometry* geometry,
        vtkUnstructuredGrid* meshGrid,
        const GridSource& gridSource = {},
        const Fem::AnalysisTopology* meshTopology = nullptr,
        const std::map<std::string, int>* paletteOrder = nullptr
    );

    int categoryOfElement(const std::string& element) const override;

private:
    void build(
        Fem::FemAnalysis* analysis,
        Fem::FemGeometry* geometry,
        vtkUnstructuredGrid* meshGrid,
        const GridSource& gridSource,
        const Fem::AnalysisTopology* meshTopology,
        const std::map<std::string, int>* paletteOrder
    );

    /// Toplevel element path -> the component it sits in
    std::map<std::string, int> m_elementCategory;
};

/**
 * Material assignment inverted from material References.
 * Empty References = default material for unassigned shapes.
 * Remaining unassigned (no empty-ref material) = "no material".
 */
class FemGuiExport MaterialClassification: public Classification
{
public:
    static constexpr const char* NoMaterialKey = "__no_material__";

    MaterialClassification(
        Fem::FemAnalysis* analysis,
        Fem::FemGeometry* geometry,
        vtkUnstructuredGrid* meshGrid,
        const GridSource& gridSource = {},
        const std::map<std::string, int>* paletteOrder = nullptr
    );

    int categoryOfElement(const std::string& element) const override;

private:
    void build(
        Fem::FemAnalysis* analysis,
        Fem::FemGeometry* geometry,
        vtkUnstructuredGrid* meshGrid,
        const GridSource& gridSource,
        const std::map<std::string, int>* paletteOrder
    );

    std::map<std::string, int> m_elementCategory;
};

/**
 * Categories from the baked celltype array on the input grid, each VTK type
 * split into the cells the analysis solves on and the cells the mesher built
 * them from. A type that is only ever scaffolding therefore shows up once, a
 * type that is both (tria3 skinning a solid, tria3 being a shell) twice.
 */
class FemGuiExport CellTypeClassification: public Classification
{
public:
    CellTypeClassification(
        vtkUnstructuredGrid* meshGrid,
        Fem::FemGeometry* geometry,
        const GridSource& gridSource = {}
    );

    int categoryOfElement(const std::string& element) const override;

private:
    void build(
        vtkUnstructuredGrid* meshGrid,
        Fem::FemGeometry* geometry,
        const GridSource& gridSource
    );
};

}  // namespace FemGui
