# ***************************************************************************
# *   Copyright (c) 2026 Stefan Tröger <stefantroeger@gmx.net>              *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

"""
What the FEM view spends its time on when an analysis of placed instances is
switched between its stages, has parts of it hidden, or is cut by a clip plane.

The model is an assembly of nested imports of about the size that starts to
feel slow: two placed legs, each of which places a block of its own, four
meshed instances of some seventeen thousand nodes each. Every operation is
performed the way the view panel performs it, and the stages of the pipeline
that C++ marked with FEM_PERF_SCOPE report what they took, so that the answer
names a stage rather than an operation.

Hand it to FreeCAD, which runs everything and quits when it is done. The
report goes to the terminal, so the GUI need not be looked at::

    ./bin/FreeCAD Mod/Fem/femtest/perf/view_pipeline.py

Or call it from the Python console of a running FreeCAD, which leaves the
model behind to look at::

    from femtest.perf import view_pipeline
    view_pipeline.run()

``run`` takes ``nodes_per_axis`` above all: lowering it makes a quick run,
raising it says how a stage scales.
"""

__title__ = "FEM view pipeline benchmark"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import time

import FreeCAD
import Fem
import ObjectsFem
import Part

# Nodes along an edge of one box. Each analysis is two boxes and the assembly
# draws four analyses, so 42 makes 4 * 2 * 42**3 = 592704 nodes, about the size
# at which the view starts to feel slow.
NODES_PER_AXIS = 42

BOX_SIZE = 10.0

# Two solids per analysis, so that hiding a component is not the same as
# hiding everything and the tree has all three depths to offer.
BOXES_PER_ANALYSIS = 2


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------


def boxes(count=BOXES_PER_ANALYSIS):
    """The origins of the boxes one analysis is made of, side by side."""
    return [FreeCAD.Vector(index * 2 * BOX_SIZE, 0, 0) for index in range(count)]


def _append_box(mesh, origin, nodes_per_axis, solid_index, face_index):
    """
    A hexahedral mesh of one box, grouped the way a mesher would group it.

    The groups matter as much as the elements: it is the element names that
    the view resolves a cell to when it hides, colours or picks it, and a mesh
    without them would take a shortcut through most of the pipeline.
    """
    n = nodes_per_axis
    step = BOX_SIZE / (n - 1)
    base = mesh.NodeCount

    def node_id(i, j, k):
        return base + i * n * n + j * n + k + 1

    for i in range(n):
        for j in range(n):
            for k in range(n):
                mesh.addNode(
                    origin.x + i * step,
                    origin.y + j * step,
                    origin.z + k * step,
                    node_id(i, j, k),
                )

    volumes = []
    for i in range(n - 1):
        for j in range(n - 1):
            for k in range(n - 1):
                volumes.append(
                    mesh.addVolume(
                        [
                            node_id(i, j, k),
                            node_id(i + 1, j, k),
                            node_id(i + 1, j + 1, k),
                            node_id(i, j + 1, k),
                            node_id(i, j, k + 1),
                            node_id(i + 1, j, k + 1),
                            node_id(i + 1, j + 1, k + 1),
                            node_id(i, j + 1, k + 1),
                        ]
                    )
                )
    group = mesh.addGroup(f"Solid{solid_index}", "Volume")
    mesh.addGroupElements(group, volumes)

    # The quads on the six sides, so that every face element of the box owns
    # part of the mesh and can be hidden or coloured on its own. Their order
    # follows the faces of Part.makeBox: x, then y, then z, near side first.
    last = n - 1
    sides = [
        [(0, j, k) for j in range(last) for k in range(last)],
        [(last, j, k) for j in range(last) for k in range(last)],
        [(i, 0, k) for i in range(last) for k in range(last)],
        [(i, last, k) for i in range(last) for k in range(last)],
        [(i, j, 0) for i in range(last) for j in range(last)],
        [(i, j, last) for i in range(last) for j in range(last)],
    ]
    corners = [
        lambda i, j, k: [(i, j, k), (i, j + 1, k), (i, j + 1, k + 1), (i, j, k + 1)],
        lambda i, j, k: [(i, j, k), (i, j + 1, k), (i, j + 1, k + 1), (i, j, k + 1)],
        lambda i, j, k: [(i, j, k), (i + 1, j, k), (i + 1, j, k + 1), (i, j, k + 1)],
        lambda i, j, k: [(i, j, k), (i + 1, j, k), (i + 1, j, k + 1), (i, j, k + 1)],
        lambda i, j, k: [(i, j, k), (i + 1, j, k), (i + 1, j + 1, k), (i, j + 1, k)],
        lambda i, j, k: [(i, j, k), (i + 1, j, k), (i + 1, j + 1, k), (i, j + 1, k)],
    ]
    for offset, (cells, quad_of) in enumerate(zip(sides, corners)):
        faces = [mesh.addFace([node_id(*c) for c in quad_of(*cell)]) for cell in cells]
        group = mesh.addGroup(f"Face{face_index + offset}", "Face")
        mesh.addGroupElements(group, faces)


def structured_mesh(origins, nodes_per_axis):
    """A hexahedral mesh of several boxes, grouped by solid and by face."""
    mesh = Fem.FemMesh()
    for index, origin in enumerate(origins):
        _append_box(mesh, origin, nodes_per_axis, index + 1, index * 6 + 1)
    return mesh


def _meshed_analysis(document, name, nodes_per_axis):
    """An analysis of a few boxes, meshed."""
    analysis = ObjectsFem.makeAnalysis(document, name)
    geometry = ObjectsFem.makeGeometryGroup(document, name + "Geometry")
    analysis.addObject(geometry)

    origins = boxes()
    source = document.addObject("Part::Feature", name + "Part")
    source.Shape = Part.makeCompound(
        [Part.makeBox(BOX_SIZE, BOX_SIZE, BOX_SIZE, origin) for origin in origins]
    )
    step = ObjectsFem.makeGeometryImport(document)
    step.Import = [source]
    geometry.Group = [step]

    group = ObjectsFem.makeMeshShapeGroup(document, geometry=geometry, analysis=analysis)
    mesh_obj = document.addObject("Fem::FemMeshObject", name + "Mesh")
    mesh_obj.FemMesh = structured_mesh(origins, nodes_per_axis)
    group.addObject(mesh_obj)
    document.recompute()
    return analysis


def build_model(document, nodes_per_axis=NODES_PER_AXIS):
    """
    The assembly the benchmark measures: an analysis that places two legs,
    each of which places a block of its own.

    Returns the assembly analysis.
    """
    from femtools import importtools

    block = _meshed_analysis(document, "Block", nodes_per_axis)
    leg = _meshed_analysis(document, "Leg", nodes_per_axis)

    nested = ObjectsFem.makeAnalysisImport(document, "Block1")
    nested.Analysis = block
    nested.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 2 * BOX_SIZE), FreeCAD.Rotation())
    importtools.wire_import(leg, nested)
    document.recompute()

    # No geometry of its own: an assembly that only places others is the case
    # the imports were built for.
    assembly = ObjectsFem.makeAnalysis(document, "Assembly")
    for index in range(2):
        placed = ObjectsFem.makeAnalysisImport(document, f"Leg{index + 1}")
        placed.Analysis = leg
        placed.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0, index * 2 * BOX_SIZE, 0), FreeCAD.Rotation()
        )
        importtools.wire_import(assembly, placed)
    document.recompute()
    return assembly


def model_size(assembly):
    """Nodes and cells of everything the assembly draws, instances counted each."""
    from femtools import importmembers

    nodes = 0
    cells = 0

    def walk(analysis):
        nonlocal nodes, cells
        for member in analysis.Group:
            if member.isDerivedFrom("Fem::FemMeshShapeGroup"):
                mesh = member.FemMesh
                nodes += mesh.NodeCount
                cells += mesh.VolumeCount + mesh.FaceCount
        for placed in importmembers.collect_imports(analysis):
            if placed.Analysis:
                walk(placed.Analysis)

    walk(assembly)
    return nodes, cells


# ---------------------------------------------------------------------------
# measuring
# ---------------------------------------------------------------------------


class Measurement:
    """What one operation took, in total and per pipeline stage."""

    def __init__(self, label, wall, stages):
        self.label = label
        self.wall = wall
        self.stages = stages

    def report(self):
        lines = [f"{self.label}: {self.wall * 1000:8.1f} ms"]
        if not self.stages:
            lines.append("    (nothing marked ran - the operation was a no-op)")
            return lines
        lines.append(
            "    {:<48} {:>6} {:>10} {:>10} {:>7}".format(
                "stage", "calls", "total ms", "self ms", "% wall"
            )
        )
        for name, calls, total, own in sorted(self.stages, key=lambda row: -row[3]):
            # Below a millisecond a stage says nothing about why an operation
            # feels slow, and there are enough of them to bury the ones that do.
            if own * 1000 < 1.0:
                continue
            lines.append(
                "    {:<48} {:>6} {:>10.1f} {:>10.1f} {:>6.1f}%".format(
                    name, calls, total * 1000, own * 1000, own / self.wall * 100
                )
            )
        accounted = sum(row[3] for row in self.stages)
        lines.append(
            "    {:<48} {:>6} {:>10} {:>10.1f} {:>6.1f}%".format(
                "(not marked: Python, Qt, Coin, document)",
                "",
                "",
                (self.wall - accounted) * 1000,
                (self.wall - accounted) / self.wall * 100,
            )
        )
        return lines


def measure(label, action, prepare=None):
    """
    Run *action* with the pipeline stages timed, and say what they took.

    The action runs once beforehand without the clock, because the helpers
    remember the view state they last drew and a first run does work a second
    one is spared. *prepare* puts the state back to where the action starts,
    both before the warm-up and before the run that counts.
    """
    import FemGui

    if prepare:
        prepare()
    action()
    if prepare:
        prepare()

    FemGui.perfReset()
    FemGui.perfEnable(True)
    start = time.perf_counter()
    try:
        action()
    finally:
        wall = time.perf_counter() - start
        FemGui.perfEnable(False)
    return Measurement(label, wall, FemGui.perfReport())


# ---------------------------------------------------------------------------
# the operations
# ---------------------------------------------------------------------------


def _panel(assembly):
    """The live view panel, set up on the assembly the way the workbench does."""
    import FreeCADGui
    import FemGui
    from PySide import QtGui
    from femguiutils import view_panel

    view_panel.setup_visualization_panel()
    dock = FreeCADGui.getMainWindow().findChild(QtGui.QDockWidget, "FEMView")
    if dock is None:
        raise RuntimeError("the view panel did not come up")

    # After the panel, so that it hears about the analysis the way it does when
    # a user activates one.
    FemGui.setActiveAnalysis(assembly)

    widget = dock.widget()
    return widget._explorer, widget._settings


def _node_for(model, element, parent=None):
    """The tree row that stands for an element name, or None."""
    from femguiutils.view_panel import QModelIndex

    if parent is None:
        parent = QModelIndex()
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        node = model.get_item(index)
        if node.element == element:
            return index
        found = _node_for(model, element, index)
        if found is not None:
            return found
    return None


def _named_node(model, name, parent=None):
    """The tree row with a display name, which is how imports and components show."""
    from femguiutils.view_panel import QModelIndex

    if parent is None:
        parent = QModelIndex()
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        node = model.get_item(index)
        if node.name == name:
            return index
        found = _named_node(model, name, parent=index)
        if found is not None:
            return found
    return None


def _toggle(model, index):
    """Uncheck and check a row, which is how the panel hides and shows."""
    from femguiutils.view_panel import Qt

    # The checkbox lives in the third column, and the model only listens there.
    check = index.sibling(index.row(), 2)
    model.setData(check, Qt.Unchecked, Qt.CheckStateRole)
    model.setData(check, Qt.Checked, Qt.CheckStateRole)


def run(nodes_per_axis=NODES_PER_AXIS, document=None, keep=True):
    """
    Build the assembly, run the three operations that feel slow, and print
    what each of their stages took.

    Returns the measurements, so that a caller can compare two runs.
    """
    import FreeCADGui
    import FemGui

    if not hasattr(FreeCADGui, "getMainWindow") or FreeCADGui.getMainWindow() is None:
        raise RuntimeError("the view pipeline only runs with a GUI")

    owns_document = document is None
    if owns_document:
        document = FreeCAD.newDocument("FemViewPipelineBenchmark")

    start = time.perf_counter()
    assembly = build_model(document, nodes_per_axis)
    build_seconds = time.perf_counter() - start

    explorer, _ = _panel(assembly)
    model = explorer._model
    state = FemGui.getAnalysisViewState(assembly)

    nodes, cells = model_size(assembly)
    print()
    print("=" * 96)
    print(f"FEM view pipeline, {nodes} nodes and {cells} cells over the placed instances")
    print(f"built in {build_seconds:.1f} s")
    print("=" * 96)

    measurements = []

    def add(measurement):
        measurements.append(measurement)
        for line in measurement.report():
            print(line)
        print()

    def colour_everywhere(mode):
        # The colour mode belongs to a stage, so setting it for both is the
        # only way to switch stages without also switching mode.
        for stage in ("Geometry", "Mesh"):
            state.setActiveStage(stage)
            state.setColorMode(mode)
        state.setActiveStage("Geometry")

    # 1. Switching stages, per colour mode, and changing colour mode without
    #    leaving a stage. The two together separate what a stage switch costs
    #    from what a colour mode costs.
    for mode in ("Material", "Subelement"):
        colour_everywhere(mode)
        add(
            measure(
                f"stage Geometry -> Mesh  [{mode} in both]",
                lambda: state.setActiveStage("Mesh"),
                lambda: state.setActiveStage("Geometry"),
            )
        )
        add(
            measure(
                f"stage Mesh -> Geometry  [{mode} in both]",
                lambda: state.setActiveStage("Geometry"),
                lambda: state.setActiveStage("Mesh"),
            )
        )

    # The stages carry a colour mode each, so a switch between stages that
    # disagree also changes the mode, which is a different path.
    colour_everywhere("Subelement")
    state.setActiveStage("Mesh")
    state.setColorMode("Material")
    state.setActiveStage("Geometry")
    add(
        measure(
            "stage Geometry -> Mesh  [Subelement, then Material]",
            lambda: state.setActiveStage("Mesh"),
            lambda: state.setActiveStage("Geometry"),
        )
    )

    colour_everywhere("Subelement")
    for stage in ("Geometry", "Mesh"):
        state.setActiveStage(stage)
        add(
            measure(
                f"colour mode Subelement -> Material  [{stage}]",
                lambda: state.setColorMode("Material"),
                lambda: state.setColorMode("Subelement"),
            )
        )
    colour_everywhere("Subelement")

    # 2. Hiding and showing, at the three depths the tree offers. A row without
    #    an element of its own hides every element below it, so this also says
    #    what the depth of a row costs.
    for stage in ("Geometry", "Mesh"):
        state.setActiveStage(stage)
        leg = _named_node(model, "Leg1")
        targets = [
            ("one element (a solid of a placed leg)", _node_for(model, "Leg1.Solid1")),
            (
                "one component of a placed leg",
                _named_node(model, "Component1", leg) if leg is not None else None,
            ),
            ("a whole import (one leg with its block)", leg),
        ]
        for what, index in targets:
            if index is None:
                print(f"hide/show {what} [{stage}]: no such row in the tree")
                continue
            add(measure(f"hide/show {what}  [{stage}]", lambda i=index: _toggle(model, i)))

    # 3. Clipping. Moving the plane is what the handle does while dragged, and
    #    the release is the same call with the drag over.
    here = FreeCAD.Vector(BOX_SIZE, BOX_SIZE / 2, BOX_SIZE / 2)
    there = here + FreeCAD.Vector(1, 0, 0)
    direction = FreeCAD.Vector(1, 0, 0)

    def clip_at(where):
        state.setClipPlane("Bench", where, direction)

    for stage in ("Geometry", "Mesh"):
        state.setActiveStage(stage)
        add(
            measure(
                f"clip plane appears  [{stage}]",
                lambda: clip_at(here),
                lambda: state.removeClipPlane("Bench"),
            )
        )
        add(
            measure(
                f"clip plane moves  [{stage}]",
                lambda: clip_at(there),
                lambda: clip_at(here),
            )
        )
        add(
            measure(
                f"clip plane goes  [{stage}]",
                lambda: state.removeClipPlane("Bench"),
                lambda: clip_at(here),
            )
        )

    print("=" * 96)
    print("summary")
    for measurement in measurements:
        print(f"    {measurement.wall * 1000:8.1f} ms  {measurement.label}")
    print("=" * 96)

    if owns_document and not keep:
        FreeCAD.closeDocument(document.Name)
    return measurements


def main():
    """Run the benchmark in a GUI that quits when it is done.

    Meant for ``FreeCAD path/to/view_pipeline.py``, so the main window has to go
    away by itself. Documents are closed first, otherwise the unsaved changes
    dialog waits for an answer that never comes.
    """
    import sys

    import FreeCADGui

    try:
        run(keep=False)
    finally:
        sys.stdout.flush()
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)
        FreeCADGui.getMainWindow().close()


# A script handed to FreeCAD is imported as a top-level module named after the
# file, so __name__ is never "__main__" and the usual guard would never fire.
# Belonging to a package is what tells the two apart: only the import from
# femtest.perf, which wants to call run() itself, has one.
if not __package__:
    main()
