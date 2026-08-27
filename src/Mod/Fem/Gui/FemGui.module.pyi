# SPDX-License-Identifier: LGPL-2.1-or-later

"""Typed public signatures for the ``FemGui`` module-level helpers.

This source-adjacent stub file carries the active-analysis selector and the
GUI editor helpers exposed directly by the Fem GUI module.
"""

from __future__ import annotations

from typing import overload

from FreeCAD import DocumentObject

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

def createClipPlane(
    analysis: DocumentObject | None = None, name: str | None = None, /
) -> object | None:
    """Return an interactive clip plane handle for the given or active analysis.

    A new plane starts clipping at the center of the model. Passing the name of
    an existing clip plane adopts that plane instead of adding a new one.
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
