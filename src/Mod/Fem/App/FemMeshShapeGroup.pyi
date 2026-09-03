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

    def getComponentCount(self) -> int:
        """Number of connected components of the result mesh."""
        ...

    def getToplevelElements(self, component: int, /) -> list:
        """Toplevel element names of a component (0-based index)."""
        ...

    def getEntities(self, toplevel: str, /) -> list:
        """Entity group names owned by a toplevel."""
        ...

    def getEntityOwners(self, entity: str, /) -> list:
        """Toplevel names that own an entity."""
        ...

    def getAnalysisDimension(self, toplevel: str, /) -> int:
        """Analysis dimension of a toplevel, or -1."""
        ...

    def getEntityDimensionMask(self, entity: str, /) -> int:
        """Dimension bitmask for an entity."""
        ...

    def getTopologyRevision(self) -> int:
        """Counter bumped when the result mesh is rebuilt."""
        ...

    def getGroupElementsByName(self, name: str, /) -> list:
        """
        Model element ids the named group or toplevel stands for.

        A catch-all toplevel has no SMESH group behind it, so looking the name
        up on the mesh alone would find nothing.
        """
        ...
