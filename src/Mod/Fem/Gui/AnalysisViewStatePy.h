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

#include <CXX/Extensions.hxx>
#include <CXX/Objects.hxx>
#include <vector>

#include "AnalysisViewState.h"

namespace FemGui
{

/**
 * Thin Python wrapper around AnalysisViewState.
 * Lifetime follows the C++ state (keyed by FemAnalysis*).
 */
class AnalysisViewStatePy: public Py::PythonExtension<AnalysisViewStatePy>
{
public:
    using BaseType = Py::PythonExtension<AnalysisViewStatePy>;

    static void init_type();
    static Py::Object create(AnalysisViewState* state);

    explicit AnalysisViewStatePy(AnalysisViewState* state);
    ~AnalysisViewStatePy() override;

    Py::Object repr() override;

    Py::Object getActiveStage(const Py::Tuple&);
    Py::Object setActiveStage(const Py::Tuple&);
    Py::Object getDimensionMode(const Py::Tuple&);
    Py::Object setDimensionMode(const Py::Tuple&);
    Py::Object getWireframe(const Py::Tuple&);
    Py::Object setWireframe(const Py::Tuple&);
    Py::Object getOverlay(const Py::Tuple&);
    Py::Object setOverlay(const Py::Tuple&);
    Py::Object getColorMode(const Py::Tuple&);
    Py::Object setColorMode(const Py::Tuple&);

    Py::Object isElementHidden(const Py::Tuple&);
    Py::Object setElementHidden(const Py::Tuple&);
    Py::Object getHiddenElements(const Py::Tuple&);
    Py::Object setHiddenElements(const Py::Tuple&);

    Py::Object isCellTypeHidden(const Py::Tuple&);
    Py::Object setCellTypeHidden(const Py::Tuple&);
    Py::Object getHiddenCellTypes(const Py::Tuple&);

    Py::Object setClipPlane(const Py::Tuple&);
    Py::Object removeClipPlane(const Py::Tuple&);
    Py::Object getClipPlanes(const Py::Tuple&);

    Py::Object getCategories(const Py::Tuple&);
    Py::Object categoryOfElement(const Py::Tuple&);
    Py::Object getUnderAchievedElements(const Py::Tuple&);

    Py::Object beginUpdate(const Py::Tuple&);
    Py::Object endUpdate(const Py::Tuple&);

    Py::Object connectChanged(const Py::Tuple&);
    Py::Object disconnectChanged(const Py::Tuple&);

    AnalysisViewState* getViewStatePtr() const
    {
        return m_state;
    }

private:
    void emitPythonCallbacks();

    AnalysisViewState* m_state {nullptr};
    AnalysisViewState::Connection m_changedConn;
    std::vector<Py::Object> m_pyCallbacks;
};

}  // namespace FemGui
