# SPDX-License-Identifier: LGPL-2.1-or-later

from typing import Final

from Base.Metadata import export
from App.GeoFeature import GeoFeature


@export(
    Twin="FemGeometry",
    TwinPointer="FemGeometry",
    Include="Mod/Fem/App/FemGeometry.h",
    Namespace="Fem",
    FatherInclude="App/GeoFeaturePy.h",
)
class FemGeometry(GeoFeature):
    """
    FemGeometry analysis geometry container

    Author: Stefan Tröger <stefantroeger@gmx.net>
    License: LGPL-2.1-or-later
    """

    def getComponents(self) -> list:
        """
        Returns the components available in shape. A component is a set of
        subshapes that are topologically connected.
        """
        ...

    def getComponentCount(self) -> int:
        """
        Returns the number of components available in the shape.
        """
        ...

    def getToplevelElements(self, component: int, /) -> list:
        """
        Returns the toplevel elements of a given component (0-based index).
        """
        ...

    def getGeometricDimension(self, toplevel: str, /) -> int:
        """
        Geometric dimension of a toplevel element (solid=3 .. vertex=0), or -1.
        """
        ...

    def getAnalysisDimension(self, toplevel: str, /) -> int:
        """
        Analysis dimension: DimensionOverride if set, else geometric dimension.
        """
        ...
