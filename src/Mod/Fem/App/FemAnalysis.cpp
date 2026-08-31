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


#include <cstring>

#include <App/DocumentObjectPy.h>
#include <App/FeaturePythonPyImp.h>
#include <Base/Uuid.h>

#include "FemAnalysis.h"


using namespace Fem;
using namespace App;

PROPERTY_SOURCE(Fem::FemAnalysis, App::DocumentObjectGroup)


FemAnalysis::FemAnalysis()
{
    Base::Uuid id;
    ADD_PROPERTY_TYPE(Uid, (id), 0, App::Prop_None, "UUID of the Analysis");
}

FemAnalysis::~FemAnalysis() = default;

App::DocumentObject* FemAnalysis::getSubObject(
    const char* subname,
    PyObject** pyObj,
    Base::Matrix4D* mat,
    bool transform,
    int depth
) const
{
    const char* dot = subname ? std::strchr(subname, '.') : nullptr;
    if (dot && subname[0] != '$') {
        if (auto* member = Group.findUsingMap(std::string(subname, dot))) {
            if (auto* deeper = member->getSubObject(dot + 1, pyObj, mat, true, depth + 1)) {
                return deeper;
            }
        }
    }
    return App::DocumentObjectGroup::getSubObject(subname, pyObj, mat, transform, depth);
}

void FemAnalysis::extensionOnChanged(const App::Property* prop)
{
    if (prop == &Visibility) {
        App::Extension::extensionOnChanged(prop);
        return;
    }
    App::GroupExtension::extensionOnChanged(prop);
}

void FemAnalysis::handleChangedPropertyName(
    Base::XMLReader& reader,
    const char* TypeName,
    const char* PropName
)
{
    Base::Type type = Base::Type::fromName(TypeName);
    if (Group.getClassTypeId() == type && strcmp(PropName, "Member") == 0) {
        Group.Restore(reader);
    }
    else {
        App::DocumentObjectGroup::handleChangedPropertyName(reader, TypeName, PropName);
    }
}


// Dummy class 'DocumentObject' in Fem namespace
PROPERTY_SOURCE_ABSTRACT(Fem::DocumentObject, App::DocumentObject)

// Python feature ---------------------------------------------------------

namespace App
{
/// @cond DOXERR
PROPERTY_SOURCE_TEMPLATE(Fem::FemAnalysisPython, Fem::FemAnalysis)
template<>
const char* Fem::FemAnalysisPython::getViewProviderName() const
{
    return "FemGui::ViewProviderFemAnalysisPython";
}

// template<> void Fem::FemAnalysisPython::Restore(Base::XMLReader& reader) {
//     FemAnalysis::Restore(reader);
// }
// template<> PyObject* Fem::FemAnalysisPython::getPyObject(void) {
//    if (PythonObject.is(Py::_None())) {
//        // ref counter is set to 1
//        PythonObject = Py::Object(new App::DocumentObjectPy(this),true);
//    }
//    return Py::new_reference_to(PythonObject);
//}
/// @endcond

// explicit template instantiation
template class FemExport FeaturePythonT<Fem::FemAnalysis>;
}  // namespace App

// ---------------------------------------------------------

namespace App
{
/// @cond DOXERR
PROPERTY_SOURCE_TEMPLATE(Fem::FeaturePython, Fem::DocumentObject)
template<>
const char* Fem::FeaturePython::getViewProviderName() const
{
    return "Gui::ViewProviderFeaturePython";
}
template<>
PyObject* Fem::FeaturePython::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        // ref counter is set to 1
        PythonObject = Py::Object(new App::FeaturePythonPyT<App::DocumentObjectPy>(this), true);
    }
    return Py::new_reference_to(PythonObject);
}
// explicit template instantiation
template class FemExport FeaturePythonT<Fem::DocumentObject>;
/// @endcond
}  // namespace App
