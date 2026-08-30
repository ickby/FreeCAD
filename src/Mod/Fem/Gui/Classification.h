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
 * Concrete modes: Subelement, Toplevel, Material, CellType.
 * Instances are computed once per analysis and shared by geometry and mesh VPs.
 */
class FemGuiExport Classification
{
public:
    virtual ~Classification() = default;

    virtual std::vector<Category> categories() const = 0;
    virtual int categoryOfElement(const std::string& element) const = 0;
    virtual int categoryOfCell(vtkIdType cell) const = 0;

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
     */
    static std::unique_ptr<Classification> create(
        ColorMode mode,
        Fem::FemAnalysis* analysis,
        Fem::FemGeometry* geometry,
        vtkUnstructuredGrid* meshGrid = nullptr,
        const GridSource& gridSource = {}
    );
};

/** One colour per geometry entity (Face7, Solid3, ...). */
class FemGuiExport SubelementClassification: public Classification
{
public:
    SubelementClassification(
        Fem::FemAnalysis* analysis,
        Fem::FemGeometry* geometry,
        vtkUnstructuredGrid* meshGrid,
        const GridSource& gridSource = {}
    );

    std::vector<Category> categories() const override;
    int categoryOfElement(const std::string& element) const override;
    int categoryOfCell(vtkIdType cell) const override;

private:
    void build(
        Fem::FemAnalysis* analysis,
        Fem::FemGeometry* geometry,
        vtkUnstructuredGrid* meshGrid,
        const GridSource& gridSource
    );

    Fem::FemGeometry* m_geometry {nullptr};
    std::vector<Category> m_categories;
    std::map<std::string, int> m_keyToIndex;
    std::vector<int> m_cellCategory;  ///< per input-grid cell
};

/** One colour per toplevel element (owner of the entity). */
class FemGuiExport ToplevelClassification: public Classification
{
public:
    ToplevelClassification(
        Fem::FemAnalysis* analysis,
        Fem::FemGeometry* geometry,
        vtkUnstructuredGrid* meshGrid,
        const GridSource& gridSource = {}
    );

    std::vector<Category> categories() const override;
    int categoryOfElement(const std::string& element) const override;
    int categoryOfCell(vtkIdType cell) const override;

private:
    void build(
        Fem::FemAnalysis* analysis,
        Fem::FemGeometry* geometry,
        vtkUnstructuredGrid* meshGrid,
        const GridSource& gridSource
    );

    Fem::FemGeometry* m_geometry {nullptr};
    std::vector<Category> m_categories;
    std::map<std::string, int> m_keyToIndex;
    std::vector<int> m_cellCategory;
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

    MaterialClassification(Fem::FemAnalysis* analysis, Fem::FemGeometry* geometry,
                           vtkUnstructuredGrid* meshGrid, const GridSource& gridSource = {});

    std::vector<Category> categories() const override;
    int categoryOfElement(const std::string& element) const override;
    int categoryOfCell(vtkIdType cell) const override;

private:
    void build(Fem::FemAnalysis* analysis, Fem::FemGeometry* geometry,
               vtkUnstructuredGrid* meshGrid, const GridSource& gridSource);

    Fem::FemGeometry* m_geometry {nullptr};
    std::vector<Category> m_categories;
    std::map<std::string, int> m_keyToIndex;
    std::map<std::string, int> m_elementCategory;
    std::vector<int> m_cellCategory;
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

    std::vector<Category> categories() const override;
    int categoryOfElement(const std::string& element) const override;
    int categoryOfCell(vtkIdType cell) const override;

private:
    void build(
        vtkUnstructuredGrid* meshGrid,
        Fem::FemGeometry* geometry,
        const GridSource& gridSource
    );

    std::vector<Category> m_categories;
    std::map<std::string, int> m_keyToIndex;
    std::vector<int> m_cellCategory;
};

}  // namespace FemGui
