// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2008 Jürgen Riegel <juergen.riegel@web.de>              *
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

#include <functional>

#include "FemMesh.h"
#include <App/PropertyGeo.h>
#include <Base/BoundBox.h>

namespace Fem
{


/** The part shape property class.
 * @author Werner Mayer
 */
class FemExport PropertyFemMesh: public App::PropertyComplexGeoData
{
    TYPESYSTEM_HEADER_WITH_OVERRIDE();

public:
    PropertyFemMesh();
    ~PropertyFemMesh() override;

    /** @name Getter/setter */
    //@{
    void setValuePtr(FemMesh* mesh);
    /// set the FemMesh shape
    void setValue(const FemMesh&);

    /**
     * Set the FemMesh shape by taking the mesh over.
     *
     * The copying overload builds the whole mesh again, which for a value the
     * caller made and is about to drop is the merge paid for twice.
     */
    void setValue(FemMesh&&);

    /**
     * Change the mesh where it lies, under the usual notification.
     *
     * For an edit that leaves the structure of the mesh alone -- moving nodes
     * that are already there -- and so has nothing to rebuild. The mesh keeps
     * its identity, so anything holding on to it from getComplexData() still
     * points at the right object.
     */
    void modifyValue(const std::function<void(FemMesh&)>& editor);

    /// does nothing, for add property macro
    void setValue()
    {}
    /// get the FemMesh shape
    const FemMesh& getValue() const;
    const Data::ComplexGeoData* getComplexData() const override;
    //@}


    /** @name Getting basic geometric entities */
    //@{
    /** Returns the bounding box around the underlying mesh kernel */
    Base::BoundBox3d getBoundingBox() const override;
    /// Set the placement of the geometry
    void setTransform(const Base::Matrix4D& rclTrf) override;
    /// Get the placement of the geometry
    Base::Matrix4D getTransform() const override;
    void transformGeometry(const Base::Matrix4D& rclMat) override;
    //@}

    /** @name Python interface */
    //@{
    PyObject* getPyObject() override;
    void setPyObject(PyObject* value) override;
    //@}

    /** @name Save/restore */
    //@{
    void Save(Base::Writer& writer) const override;
    void Restore(Base::XMLReader& reader) override;
    void SaveDocFile(Base::Writer& writer) const override;
    void RestoreDocFile(Base::Reader& reader) override;

    App::Property* Copy() const override;
    void Paste(const App::Property& from) override;
    unsigned int getMemSize() const override;
    const char* getEditorName() const override
    {
        return "FemGui::PropertyFemMeshItem";
    }
    //@}

private:
    Base::Reference<FemMesh> _FemMesh;
};


}  // namespace Fem
