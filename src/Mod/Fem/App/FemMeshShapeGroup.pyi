# SPDX-License-Identifier: LGPL-2.1-or-later

from Base.Metadata import export
from App.GeoFeature import GeoFeature


@export(
    Twin="FemMeshShapeGroup",
    TwinPointer="FemMeshShapeGroup",
    Include="Mod/Fem/App/FemMeshShapeGroup.h",
    Namespace="Fem",
    FatherInclude="App/GeoFeaturePy.h",
)
class FemMeshShapeGroup(GeoFeature):
    """
    FemMeshShapeGroup container of the per component meshes of one analysis

    Author: Stefan Tröger <stefantroeger@gmx.net>
    License: LGPL-2.1-or-later
    """

    def getComponentOwners(self) -> dict:
        """
        Returns the mesh object meshing each component of the geometry, as a
        dict keyed by the 1-based component index. A mesh object with an empty
        Components sub-list owns every component. Components nobody meshes are
        missing from the dict.
        """
        ...
