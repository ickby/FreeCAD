// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2013 Jan Rheinländer                                    *
 *                                   <jrheinlaender@users.sourceforge.net> *
 *   Copyright (c) 2024 Mario Passaglia <mpassaglia[at]cbc.uba.ar>         *
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

#include <Gui/ViewProviderGeometryObject.h>
#include <Gui/ViewProviderFeaturePython.h>
#include <Mod/Fem/FemGlobal.h>

#include <App/PropertyGeo.h>
#include <Base/Placement.h>
#include <Gui/ViewProviderSuppressibleExtension.h>


class QMenu;
class QObject;
class SbRotation;
class SoMultipleCopy;
class SoTransform;

namespace FemGui
{

class FemGuiExport ViewProviderFemConstraint: public Gui::ViewProviderGeometryObject,
                                              public Gui::ViewProviderSuppressibleExtension
{
    PROPERTY_HEADER_WITH_OVERRIDE(FemGui::ViewProviderFemConstraint);

public:
    /**
     * @brief An extra transform for the symbols of one reference each.
     *
     * @details
     *  Applied in the local frame of the symbol, before it is turned onto the
     *  surface normal and scaled, so a rotation here says which way round the
     *  symbol sits rather than where it goes. This is how a constraint whose
     *  references do not all mean the same thing tells them apart on screen,
     *  the way a tie draws its master the other way up from its slave.
     *
     *  One entry per reference, in the flat order of Fem::Constraint's
     *  References, the same order the solver writers use. Missing entries and
     *  an empty list mean no extra transform, so nothing has to be said about
     *  the references that are drawn as usual.
     *
     * @note
     *  The translation is in the units of the symbol file and is scaled along
     *  with the symbol, so it cannot express an offset of a fixed length.
     */
    App::PropertyPlacementList SymbolPlacements;

    /// Constructor
    ViewProviderFemConstraint();
    ~ViewProviderFemConstraint() override;

    void attach(App::DocumentObject*) override;
    void updateData(const App::Property* prop) override;
    std::vector<std::string> getDisplayModes() const override;
    void setDisplayMode(const char* ModeName) override;

    std::vector<App::DocumentObject*> claimChildren() const override;
    void setupContextMenu(QMenu*, QObject*, const char*) override;

    PyObject* getPyObject() override;

    /// Highlight the references that have been selected
    virtual void highlightReferences(const bool /* on */)
    {}

    SoSeparator* getSymbolSeparator() const;
    SoSeparator* getExtraSymbolSeparator() const;
    SoTransform* getExtraSymbolTransform() const;
    // Apply rotation on copies of the constraint symbol
    void setRotateSymbol(bool rotate);
    bool getRotateSymbol() const;

    /** Load constraint symbol from Open Inventor file
     * The file structure should be as follows:
     * A separator containing a separator with the symbol used in multiple
     * copies at points on the surface and an optional separator with a symbol
     * excluded from multiple copies.
     */
    void loadSymbol(const char* fileName);

    /** Build a symbol subtree with optional placement pre-transform. */
    SoSeparator* makeSymbolInstance(const Base::Placement& pre) const;

    static std::string gethideMeshShowPartStr();
    static std::string gethideMeshShowPartStr(const std::string showConstr);

protected:
    void onChanged(const App::Property* prop) override;
    bool setEdit(int ModNum) override;
    void unsetEdit(int ModNum) override;
    void handleChangedPropertyName(
        Base::XMLReader& reader,
        const char* typeName,
        const char* propName
    ) override;

    void updateSymbol();
    void fillSymbolMatrices(SoMultipleCopy* multCopy, const Base::Placement* pre = nullptr) const;
    virtual void transformSymbol(
        const Base::Vector3d& point,
        const Base::Vector3d& normal,
        SbMatrix& mat
    ) const;
    virtual void transformExtraSymbol() const;

    /**
     * @brief SymbolPlacements spread from references onto the single symbols.
     *
     * @details
     *  Empty when no symbol needs one, which spares the caller the whole
     *  question in the ordinary case. Otherwise it is as long as *count* and
     *  holds an identity wherever nothing was asked for.
     */
    std::vector<Base::Placement> symbolPlacementPerPoint(std::size_t count) const;

    /**
     * @brief Rotation that turns a symbol onto the other side of its surface.
     *
     * @details
     *  A symbol is modelled standing on the surface and reaching along its
     *  local Y, so a half turn about Z is what sinks it through to the other
     *  side. Meant for SymbolPlacements, and shared so that the constraints
     *  which reverse a surface all flip the same way.
     */
    static Base::Placement reversedSymbolPlacement();

private:
    bool rotateSymbol;

protected:
    SoSeparator* pShapeSep;
    SoSeparator* pSymbol;
    SoSeparator* pExtraSymbol;
    SoTransform* pExtraTrans;
    SoMultipleCopy* pMultCopy;
    const char* ivFile;

    static std::string resourceSymbolDir;
};


inline SoSeparator* ViewProviderFemConstraint::getSymbolSeparator() const
{
    return pSymbol;
}

inline SoSeparator* ViewProviderFemConstraint::getExtraSymbolSeparator() const
{
    return pExtraSymbol;
}

inline SoTransform* ViewProviderFemConstraint::getExtraSymbolTransform() const
{
    return pExtraTrans;
}

inline bool ViewProviderFemConstraint::getRotateSymbol() const
{
    return rotateSymbol;
}

using ViewProviderFemConstraintPython = Gui::ViewProviderFeaturePythonT<ViewProviderFemConstraint>;


}  // namespace FemGui
