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

#include <App/GeoFeature.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <Base/Placement.h>
#include <Mod/Fem/FemGlobal.h>
#include <Mod/Fem/App/FemMesh.h>
#include <Mod/Part/App/TopoShape.h>

namespace Fem
{

class FemAnalysis;
class FemGeometry;

/**
 * One placed instance of another analysis imported into the current analysis.
 *
 * Geometry and mesh are read from the source analysis; Placement positions the
 * instance. Element references use dotted paths (Import2.Face3) through nested
 * imports.
 */
class FemExport FemAnalysisImport: public App::GeoFeature
{
    PROPERTY_HEADER_WITH_OVERRIDE(Fem::FemAnalysisImport);

public:
    FemAnalysisImport();
    ~FemAnalysisImport() override;

    App::PropertyLink Analysis;

    /** 1-based component indices from the source geometry to omit. */
    App::PropertyIntegerList SuppressedComponents;

    /** Member names from the source analysis to omit when resolving imports. */
    App::PropertyStringList SuppressedMembers;

    const char* getViewProviderName() const override
    {
        return "FemGui::ViewProviderFemAnalysisImport";
    }

    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;

    /** Geometry of the linked source analysis, or nullptr. */
    FemGeometry* sourceGeometry() const;

    /** Merged mesh from the source analysis (read-only). */
    const FemMesh& sourceMesh() const;

    App::DocumentObject* getSubObject(
        const char* subname,
        PyObject** pyObj = nullptr,
        Base::Matrix4D* mat = nullptr,
        bool transform = true,
        int depth = 0
    ) const override;

    /**
     * Shape of *subname* in the frame of the analysis this instance sits in.
     *
     * The dotted path is followed through nested instances and every placement
     * along the way is applied, so the result stands where the instance draws
     * it. Null when the path names nothing.
     */
    Part::TopoShape placedSubShape(const char* subname) const;

private:
    FemAnalysisImport* nestedImportByName(const char* name) const;
    Part::TopoShape subShapeInFrame(const char* subname, Base::Matrix4D& mat) const;
    Part::TopoShape shapeFromSource(const char* subname, const Base::Matrix4D& mat) const;

    mutable FemMesh m_emptyMesh;
};

}  // namespace Fem
