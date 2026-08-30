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

#include <Base/Placement.h>
#include <Base/Vector3D.h>
#include <Mod/Fem/FemGlobal.h>
#include <gp_XYZ.hxx>
#include <TopoDS_Shape.hxx>

#include <string>
#include <utility>
#include <vector>

class TopoDS_Edge;
class TopoDS_Face;

namespace App
{

class DocumentObject;
class GeoFeature;

}

namespace Part
{

class Feature;
class TopoShape;

}

namespace Fem
{

class FemAnalysis;
class FemAnalysisImport;
class FemGeometry;

class FemExport Tools
{
public:
    /*!
     Get the direction of the shape. If the shape is a planar face
     then get its normal direction. If it's 'linear' then get its
     direction vector.
     @see isLinear
     @see isPlanar
     */
    static Base::Vector3d getDirectionFromShape(const TopoDS_Shape&);
    /*!
     Checks whether the curve of the edge is 'linear' which is the case
     for a line or a spline or Bezier curve with collinear control points.
     */
    static bool isLinear(const TopoDS_Edge&);
    /*!
     Checks whether the surface of the face is planar.
     */
    static bool isPlanar(const TopoDS_Face&);
    /*!
     It is assumed that the edge is 'linear'.
     The direction vector of the line is returned.
     @see isLinear
     */
    static gp_XYZ getDirection(const TopoDS_Edge&);
    /*!
     It is assumed that the face is 'planar'.
     The normal vector of the plane is returned.
     @see isPlanar
     */
    static gp_XYZ getDirection(const TopoDS_Face&);
    /*!
     function to determine 3rd-party binaries used by the FEM WB
     The result is either the full path if available or just the binary
     name if it was found in a system path
     */
    static std::string checkIfBinaryExists(
        std::string prefSection,
        std::string prefBinaryPath,
        std::string prefBinaryName
    );

    /*!
     Subshape placement is not necessarily the same as the
     feature placement
    */
    static Base::Placement
    getSubShapeGlobalLocation(const App::GeoFeature* feat, const TopoDS_Shape& sh);
    static void setSubShapeGlobalLocation(const App::GeoFeature* feat, TopoDS_Shape& sh);
    /*!
     Get the shape of a feature that carries one, be it a part or the geometry an
     analysis builds. Null when the object carries no part shape.
    */
    static const Part::TopoShape* getFeatureShape(const App::DocumentObject* obj);
    /*!
     Get subshape from a feature that carries a shape. The subShape is returned
     with global location
    */
    static TopoDS_Shape
    getFeatureSubShape(const App::GeoFeature* feat, const char* subName, bool silent);
    /*!
     The geometry the members of an analysis reference. Pass any member of the
     analysis. Null when the analysis builds no geometry, which is the case for
     documents whose members reference part features directly.
    */
    static Fem::FemGeometry* getAnalysisGeometry(const App::DocumentObject* member);
    /*!
     The analysis imports of an analysis, in no particular order.

     An import sits either directly in the analysis or in a group inside it;
     both count, and each import is listed once. Only the analysis itself is
     looked at, so imports of an imported analysis are not included.
    */
    static std::vector<Fem::FemAnalysisImport*> analysisImports(const Fem::FemAnalysis* analysis);
    /*!
     Toplevel elements the imports of *analysis* contribute, as dotted paths.

     Recursive, so an imported analysis that places instances of its own is
     covered as well, under the path leading to them. A suppressed component is
     left out: it is not part of the analysis, so nothing may name it.
    */
    static std::vector<std::string> importedToplevelElements(const Fem::FemAnalysis* analysis);
    /*!
     The same elements as importedToplevelElements(), each under the component
     it belongs to.

     Both are dotted paths read from the analysis: "Import1.Component2" names
     the component, "Import1.Face7" an element of it. Colouring per component
     needs the grouping that the flat list throws away.
    */
    static std::vector<std::pair<std::string, std::vector<std::string>>> importedComponents(
        const Fem::FemAnalysis* analysis
    );
    /*!
     Whether *member* is switched off for the instance chain leading to it.

     *chain* lists the imports from the outermost inwards, the innermost one
     being the instance *member* belongs to. An instance names a member of a
     nested instance by the path to it, so switching a member off in one
     instance leaves the other instances of the same analysis alone.
    */
    static bool isMemberSuppressed(
        const std::vector<const Fem::FemAnalysisImport*>& chain,
        const App::DocumentObject* member
    );
    /*!
     Whether *member* of an imported analysis can be inherited at all.

     Everything an analysis holds is inheritable but the parts that describe
     the analysis itself rather than a condition on it: its geometry, its mesh,
     the imports it places and the solvers and results it drives.
    */
    static bool isInheritableMember(const App::DocumentObject* member);
    /*!
     Get cylinder parameters. Base is located at the center of the cylinder
    */
    static bool getCylinderParams(
        const TopoDS_Shape& sh,
        Base::Vector3d& base,
        Base::Vector3d& axis,
        double& height,
        double& radius
    );
};

}  // namespace Fem
