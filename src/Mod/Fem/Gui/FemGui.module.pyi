# SPDX-License-Identifier: LGPL-2.1-or-later

"""Typed public signatures for the ``FemGui`` module-level helpers.

This source-adjacent stub file carries the active-analysis selector and the
GUI editor helpers exposed directly by the Fem GUI module.
"""

from __future__ import annotations

from typing import overload

from FreeCAD import DocumentObject, Vector

@overload
def setActiveAnalysis() -> None:
    """Clear the currently active FEM analysis object."""
    ...

@overload
def setActiveAnalysis(obj: DocumentObject, /) -> None:
    """Set the active FEM analysis object."""
    ...

def getActiveAnalysis() -> DocumentObject | None:
    """Return the active FEM analysis object, if one is currently set."""
    ...

def addActiveAnalysisObserver(obj: object, /) -> None:
    """Register an object for active-analysis change notifications."""
    ...

def removeActiveAnalysisObserver(obj: object, /) -> None:
    """Remove a previously registered active-analysis observer."""
    ...

def getAnalysisViewState(analysis: DocumentObject | None = None, /) -> object | None:
    """Return the runtime AnalysisViewState for the given or active analysis."""
    ...

def addClipPlane(
    analysis: DocumentObject | None = None,
    origin: Vector | None = None,
    normal: Vector | None = None,
    scope: str = "",
    /,
) -> object | None:
    """Add a clip plane to the given or active analysis and return it.

    Without a place the plane cuts the top off the model. With one it cuts
    through there, which is how a picked face becomes a clip plane. The normal
    points at the half that is kept.
    """
    ...

def getClipPlane(analysis: DocumentObject, name: str, /) -> object | None:
    """Return the clip plane of that name, or None if the analysis has no such plane.

    The 3D handle belongs to the analysis and comes and goes with the plane, so
    it is looked up when needed rather than held on to.
    """
    ...

@overload
def open(name: str, /) -> None:
    """Open one Abaqus or Python input file in the FEM editor."""
    ...

@overload
def open(name: str, doc_name: str, /) -> None:
    """Open one Abaqus or Python input file in the FEM editor."""
    ...

@overload
def insert(name: str, /) -> None:
    """Open one Abaqus or Python input file in the FEM editor."""
    ...

@overload
def insert(name: str, doc_name: str, /) -> None:
    """Open one Abaqus or Python input file in the FEM editor."""
    ...
