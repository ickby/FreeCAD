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
#include <string>
#include <vector>

#include <App/GroupExtension.h>

#include "FemMeshShapeObject.h"


namespace Fem
{

/**
 * Mesh container for the preprocessing workflow.
 *
 * Holds per-object mesh children (never listed in analysis.Group). execute()
 * validates component assignment only; the merged FemMesh is built lazily by
 * getMergedMesh() and kept transient.
 */
class FemExport FemMeshShapeGroup: public FemMeshShapeBaseObject, public App::GroupExtension
{
    PROPERTY_HEADER_WITH_EXTENSIONS(Fem::FemMeshShapeGroup);

public:
    FemMeshShapeGroup();
    ~FemMeshShapeGroup() override;

    /**
     * Per-cell provenance after a merge: child object Name for each element,
     * indexed as elementId - 1. Transient / not persisted.
     */
    App::PropertyStringList CellSources;

    const char* getViewProviderName() const override
    {
        return "FemGui::ViewProviderFemMeshGroup";
    }

    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;

    bool allowObject(App::DocumentObject* obj) override;

    /**
     * Build or return the cached merged mesh. Children are merged sorted by
     * Name. Fills the transient FemMesh property and CellSources.
     */
    const ::Fem::FemMesh& getMergedMesh();

    /** Ensure FemMesh holds a current merge (used by PropertyFemMesh lazy access). */
    void ensureMergedMesh();

    void invalidateMergedCache();

protected:
    void onChanged(const App::Property* prop) override;

private:
    void reconnectChildSignals();
    void slotChildChanged(const App::DocumentObject& obj, const App::Property& prop);
    std::string validateComponents(bool* hasOverlap = nullptr) const;
    void rebuildMergedMesh();

    bool m_mergedValid {false};
    bool m_merging {false};
    std::map<const App::DocumentObject*, fastsignals::scoped_connection> m_childConns;
};

using FemMeshShapeGroupPython = App::FeaturePythonT<FemMeshShapeGroup>;

}  // namespace Fem
