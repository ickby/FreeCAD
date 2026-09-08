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

    /**
     * Bumped on every recompute of this instance.
     *
     * Nothing stored here says what the instance draws: geometry and mesh are
     * read from the source analysis, so a change over there leaves this object
     * looking untouched and the view provider with nothing to follow. The
     * dependency graph does reach us, through the link to the source analysis,
     * and this is how that arrival is passed on. Output, so that saying it
     * does not ask for another recompute, and transient, because a restored
     * document builds its render tree anyway.
     */
    App::PropertyInteger SourceRevision;

    /**
     * The geometry of the source analysis is behind the model it was built
     * from, and so is everything this instance shows of it.
     *
     * Geometry and mesh are read from the source and nothing is kept here, so
     * an instance is only ever as current as the analysis it points at. The
     * mark the source raised for itself is therefore carried on to the analysis
     * that imports it, which is where a user standing in front of an instance
     * can see that what it draws is out of date - and read there by the update
     * command, because updating the source is the only thing that repairs it.
     *
     * A source that imports further analyses answers for them too: its own
     * instances have already been asked by the time this is written, the
     * dependency graph running a source before the analysis that imports it.
     */
    App::PropertyBool SourceGeometryOutdated;

    /**
     * The source analysis publishes no mesh.
     *
     * Either nobody has set a mesher up over there, which no update can repair,
     * or its geometry was updated and took the mesh with it, which a remesh of
     * the source does repair. Both leave this instance drawing a geometry with
     * nothing to compute on, so both are worth saying; telling them apart is
     * left to the command, which can see whether the source has meshers at all.
     */
    App::PropertyBool SourceMeshMissing;

    const char* getViewProviderName() const override
    {
        return "FemGui::ViewProviderFemAnalysisImport";
    }

    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;

    /**
     * Both markers are derived from the source analysis on every execute, so a
     * document that has just been restored has to be asked once as well - the
     * alternative is a tree that looks healthy until something recomputes.
     */
    void onDocumentRestored() override;

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
    /// Read the state of the source analysis into the two markers.
    void updateSourceMarkers();

    FemAnalysisImport* nestedImportByName(const char* name) const;
    Part::TopoShape subShapeInFrame(const char* subname, Base::Matrix4D& mat) const;
    Part::TopoShape shapeFromSource(const char* subname, const Base::Matrix4D& mat) const;

    mutable FemMesh m_emptyMesh;
};

}  // namespace Fem
