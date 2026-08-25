/***************************************************************************
 *   Copyright (c) 2013 Jürgen Riegel <FreeCAD@juergen-riegel.net>         *
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

#include <App/PropertyLinks.h>

#include "FemMeshObject.h"


namespace Fem
{

class FemExport FemMeshShapeBaseObject: public FemMeshObject
{
    PROPERTY_HEADER_WITH_OVERRIDE(Fem::FemMeshShapeBaseObject);

public:
    /// Constructor
    FemMeshShapeBaseObject();
    ~FemMeshShapeBaseObject() override;

    /** Legacy geometry link (Part feature). Kept as PropertyLink for document compatibility. */
    App::PropertyLink Shape;

    /**
     * New-style component assignment onto FemGeometry using ComponentN subnames.
     * Coexists with Shape; new workflow uses Components, legacy keeps Shape.
     */
    App::PropertyLinkSub Components;

    /// returns the type name of the ViewProvider
    const char* getViewProviderName() const override
    {
#ifdef FC_USE_VTK
        return "FemGui::ViewProviderFemMeshShapePreprocess";
#else
        return "FemGui::ViewProviderFemMeshShapeBase";
#endif
    }
};


class FemExport FemMeshShapeObject: public FemMeshShapeBaseObject
{
    PROPERTY_HEADER_WITH_OVERRIDE(Fem::FemMeshShapeObject);

public:
    /// Constructor
    FemMeshShapeObject();
    ~FemMeshShapeObject() override;

    /// returns the type name of the ViewProvider
    const char* getViewProviderName() const override
    {
        return "FemGui::ViewProviderFemMeshShape";
    }
    App::DocumentObjectExecReturn* execute() override;

    // virtual short mustExecute(void) const;
    // virtual PyObject *getPyObject(void);

protected:
    /// get called by the container when a property has changed
    // virtual void onChanged (const App::Property* prop);
};

using FemMeshShapeBaseObjectPython = App::FeaturePythonT<FemMeshShapeBaseObject>;

}  // namespace Fem
