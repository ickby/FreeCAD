// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 Stefan Tröger <stefantroeger@gmx.net>              *
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#include "PreCompiled.h"

#include <App/DocumentObject.h>
#include <App/MeasureManager.h>
#include <Base/Console.h>

#include "FemAnalysisImport.h"
#include "FemGeometry.h"
#include "Measure.h"

using namespace Fem;

namespace
{

/**
 * Whether the measurement tools can get a shape out of what a selection names.
 *
 * The measurement facility dispatches on the module an object's type belongs
 * to, which for everything in here is the single name "Fem" - the mesh, the
 * analysis, every constraint and the geometry alike. So the handler registered
 * under that name is asked about all of them, and has to sort out which of them
 * actually carry geometry. The two that do are the analysis geometry itself and
 * an imported instance of another analysis, which answers for the geometry it
 * draws.
 *
 * The rest are not merely unmeasurable, they are asked about constantly: the
 * type callback runs on every pick while the measurement dialog is open. Left
 * to Part's callback, each of those picks reaches its shape lookup, fails, and
 * writes a line to the report view. Answering them here keeps that quiet, and
 * says in one place what FEM offers the measurement tools.
 *
 * The question has to be asked of what the subname ends on, not of the object
 * it starts at. A selection is stored as a top-level object and a path down to
 * the element, and an analysis geometry is reached through the analysis holding
 * it - so the object handed here is Fem::FemAnalysis for every pick in a real
 * document, and asking it whether it carries a shape answers no for faces and
 * edges alike. Resolving first is also what the facility itself does to choose
 * the module, so the two agree on what is being measured.
 */
bool carriesShape(App::DocumentObject* obj, const char* subName)
{
    if (!obj) {
        return false;
    }

    auto* resolved = obj->getSubObject(subName ? subName : "");
    return resolved
        && (resolved->isDerivedFrom<Fem::FemGeometry>()
            || resolved->isDerivedFrom<Fem::FemAnalysisImport>());
}

}  // namespace

/**
 * Let the measurement tools work on analysis geometry, through Part's callbacks.
 *
 * Nothing about measuring a face or an edge of the analysis geometry differs
 * from measuring one of a Part shape, and none of Part's measurement code
 * requires a Part::Feature: it resolves what it was handed through
 * Part::Feature::getTopoShape(), which asks the object itself for the sub-shape
 * named by the selection. FemGeometry answers that, so Part's callbacks work on
 * it unchanged and are taken over here rather than reimplemented - the same way
 * PartDesign, Sketcher and Surface take them over.
 *
 * This covers the element classification only. What each kind of measurement
 * then does with the shape is registered separately, from the lists that
 * Part::MeasureClient publishes and the Measure module reads when it loads;
 * "Fem" is named in those lists beside the other modules that borrow Part's
 * handlers. Both registrations are needed for a measurement to appear.
 *
 * Part has to have been loaded before this runs, which the module entry point
 * guarantees; without it there is nothing to borrow and FEM simply stays
 * unmeasurable rather than registering a handler that would crash on use.
 */
void Fem::Measure::initialize()
{
    const App::MeasureHandler& part = App::MeasureManager::getMeasureHandler("Part");
    if (!part.typeCb) {
        Base::Console().log("FEM: no Part measurement handler to build on, FEM geometry will not "
                            "be measurable\n");
        return;
    }

    App::MeasureManager::addMeasureHandler(
        "Fem",
        [typeCb = part.typeCb](App::DocumentObject* obj, const char* subName) {
            if (!carriesShape(obj, subName)) {
                return App::MeasureElementType::INVALID;
            }
            return typeCb(obj, subName);
        }
    );
}
