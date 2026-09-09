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
What it costs to bring a mesh an external mesher made into the document and
onto the screen.

A mesher of any size runs outside FreeCAD and hands back a file. Reading that
file is the part of the wait that has a name, and it is not the part that takes
the time: the mesh then has to go into a property, be merged by the group that
holds the mesher, be turned into a VTK grid, be classified, be filtered into a
surface and finally be written into Coin before anything is on screen and the
application answers again. This benchmark walks that whole way with half a
million volume elements, which is the size at which the wait stops being a
pause and becomes an interruption, and says what each step of it took.

The model is the one the workflow builds: an analysis over a geometry of one
solid, a mesh group on that geometry, and a single Gmsh mesher in the group -
the case where nothing is shared and no second mesher can be blamed for the
time. The file is the one Gmsh actually writes on a VTK build, a legacy .vtk
carrying a CellEntityIds cell array, and it is read back through the same call
gmshtools makes, so the groups arrive as numeric tags and are renamed the same
way afterwards.

Building half a million elements in Python takes minutes, so the file is
written once into the user cache and every later run reads it from there.

The stages come from two sides at once. C++ marks its own with FEM_PERF_SCOPE -
the merge, the grid build, the classification, the render and the Coin write
are all marked already - and the four steps of the load itself are marked from
here with FemGui.perfBegin, onto the same stack, so that the report reads as one
nesting rather than two.

Hand it to FreeCAD, which runs everything and quits when it is done. The report
goes to the terminal, so the GUI need not be looked at::

    ./bin/FreeCAD Mod/Fem/femtest/perf/mesh_load.py

Or call it from the Python console of a running FreeCAD, which leaves the model
behind to look at::

    from femtest.perf import mesh_load
    mesh_load.run()

``run`` takes ``cells_per_axis``: it is the edge of the lattice, so the element
count is its cube. Lowering it makes a quick run, raising it says how a stage
scales.
"""

__title__ = "FEM mesh load benchmark"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import os
import time

import FreeCAD
import Part

import Fem
import ObjectsFem


# Elements along an edge of the lattice. 80 is 512000 hexahedra, the half
# million the benchmark is about; the 38400 quads of the six sides come on top
# of them, because a mesher names the surface of what it meshed and the view
# resolves a cell through those names.
CELLS_PER_AXIS = 80

# A smaller run to read the big one against. A stage that costs the same on ten
# times fewer elements is not the stage that makes the big load slow.
SMALL_CELLS_PER_AXIS = 30

BOX_SIZE = 10.0

# The array Gmsh writes its physical tags into, and the one gmshtools reads them
# back through. A VTK file can only carry a number per cell, so this is how a
# group survives the trip through the file at all.
CELL_GROUP_ARRAY = "CellEntityIds"

# The elements of one box, in the order the lattice groups them. The position in
# this list is the tag the group is written under, which is all the file can
# hold; the names only exist in FreeCAD, and the load maps one onto the other in
# both directions - once when the fixture is written, once when it is read.
ELEMENT_NAMES = ["Solid1"] + [f"Face{index}" for index in range(1, 7)]


def tag_of_name():
    """Element name to the tag it is written under."""
    return {name: tag for tag, name in enumerate(ELEMENT_NAMES, start=1)}


def name_of_tag():
    """
    Tag to element name.

    Reading a VTK group back gives it the tag as its name, spelled out, because
    that is all the file said. This turns it back into the element it stands
    for, which is what the merge and the view address the mesh by.
    """
    return {str(tag): name for name, tag in tag_of_name().items()}


# ---------------------------------------------------------------------------
# the mesh file
# ---------------------------------------------------------------------------


def fixture_path(cells_per_axis):
    """Where the mesh file of a given size lives once it has been written."""
    folder = os.path.join(FreeCAD.getUserCachePath(), "FemPerf")
    return os.path.join(folder, f"mesh_load_{cells_per_axis}.vtk")


def write_fixture(cells_per_axis, path=None):
    """
    Write the mesh file the benchmark loads, and say where it is.

    Does nothing when the file is already there: it takes minutes to build and
    nothing about it changes between runs.
    """
    from femtest.perf import view_pipeline

    path = path or fixture_path(cells_per_axis)
    if os.path.exists(path):
        return path

    os.makedirs(os.path.dirname(path), exist_ok=True)
    print(f"building the mesh file {path} - this happens once and takes a while")

    start = time.perf_counter()
    # The same lattice the view benchmark draws, one box of it: a hexahedral
    # mesh grouped by the solid and by each of the six faces, which is the
    # grouping a mesher hands back and the one the view needs to resolve a cell
    # to an element name.
    mesh = view_pipeline.structured_mesh([FreeCAD.Vector(0, 0, 0)], cells_per_axis + 1)
    built = time.perf_counter() - start

    start = time.perf_counter()
    # highest=False keeps the surface elements: they are what carries the face
    # groups, and without them the file would not be the file a mesher writes.
    mesh.write(
        file_name=path,
        highest=False,
        vtk_cell_group_array=CELL_GROUP_ARRAY,
        vtk_group_id_map=tag_of_name(),
    )
    written = time.perf_counter() - start

    print(
        f"    {mesh.NodeCount} nodes, {mesh.VolumeCount} volumes, {mesh.FaceCount} faces"
        f" - built in {built:.1f} s, written in {written:.1f} s"
        f" ({os.path.getsize(path) / 1e6:.0f} MB)"
    )
    return path


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------


def build_model(document, name="Load"):
    """
    An analysis of one solid with one mesher in its mesh group, meshing nothing
    yet.

    Built the way the workbench builds it: the geometry is an import step over a
    Part feature, the mesh group is made on that geometry, and the mesher goes
    into the group and is given the components no other mesher claims. Returns
    the analysis and the mesher.
    """
    from femmesh import meshcomponents

    analysis = ObjectsFem.makeAnalysis(document, name)
    geometry = ObjectsFem.makeGeometryGroup(document, name + "Geometry")
    analysis.addObject(geometry)

    source = document.addObject("Part::Feature", name + "Part")
    source.Shape = Part.makeBox(BOX_SIZE, BOX_SIZE, BOX_SIZE)
    step = ObjectsFem.makeGeometryImport(document)
    step.Import = [source]
    geometry.Group = [step]
    document.recompute()

    group = ObjectsFem.makeMeshShapeGroup(document, geometry=geometry, analysis=analysis)
    mesher = ObjectsFem.makeMeshGmsh(document, name + "Mesh")
    group.addObject(mesher)
    meshcomponents.assign_unclaimed(mesher)
    document.recompute()
    return analysis, mesher


def show_analysis(analysis):
    """Make an analysis the one on screen, with the mesh stage active."""
    import FemGui

    FemGui.setActiveAnalysis(analysis)
    # The mesh is what is being loaded, so it is the stage the user is looking
    # at; on the geometry stage the mesh would be built and then not drawn, and
    # the benchmark would measure half of the wait.
    FemGui.getAnalysisViewState(analysis).setActiveStage("Mesh")


def open_panel(analysis):
    """
    The view panel, brought up on the analysis the way the workbench does.

    It is part of what a load pays for - the tree it holds is rebuilt when the
    mesh arrives - so a measurement taken without it would be a measurement of
    something the user never does.
    """
    import FreeCADGui
    from PySide import QtGui
    from femguiutils import view_panel

    view_panel.setup_visualization_panel()
    dock = FreeCADGui.getMainWindow().findChild(QtGui.QDockWidget, "FEMView")
    if dock is None:
        raise RuntimeError("the view panel did not come up")

    # After the panel, so that it hears about the analysis the way it does when
    # a user activates one.
    show_analysis(analysis)
    return dock


# ---------------------------------------------------------------------------
# the load
# ---------------------------------------------------------------------------


def rename_groups(mesh, names):
    """
    Turn the numeric tags the file carries back into element names.

    The same step gmshtools takes after reading, and for the same reason: a
    group still called "3" belongs to nothing the analysis knows.
    """
    for index in mesh.Groups:
        name = names.get(mesh.getGroupName(index))
        if name:
            mesh.renameGroup(index, name)


def load(document, mesher, path, names, view=None):
    """
    Everything between the mesher finishing and the user having the application
    back: read the file, hand the mesh over, recompute, draw.

    Each of the four is opened as a stage of its own, so that the marks C++ set
    inside them nest where they belong. Recomputing and drawing are separate
    because they answer different questions - what the merge costs and what the
    view costs - even though the user waits for the sum of all four.

    Returns the mesh that was read, so a caller can say how big it was.
    """
    import FemGui
    import FreeCADGui

    FemGui.perfBegin("load.read")
    mesh = Fem.FemMesh()
    mesh.read(file_name=path, vtk_cell_group_array=CELL_GROUP_ARRAY)
    rename_groups(mesh, names)
    FemGui.perfEnd()

    # Assigning the property is what tells the view providers, so the grid
    # build, the classification and the Coin write all happen inside this one
    # statement rather than at the recompute below.
    FemGui.perfBegin("load.assign")
    mesher.FemMesh = mesh
    FemGui.perfEnd()

    FemGui.perfBegin("load.recompute")
    document.recompute()
    FemGui.perfEnd()

    # Coin has the scene by now but has not drawn it, and the user is still
    # waiting at that point. The redraw is the first frame; updateGui comes
    # first because whatever Qt has queued - the panel tree above all - is part
    # of the same wait.
    FemGui.perfBegin("load.draw")
    FreeCADGui.updateGui()
    if view is not None:
        view.redraw()
    FemGui.perfEnd()

    return mesh


# ---------------------------------------------------------------------------
# measuring
# ---------------------------------------------------------------------------


class Measurement:
    """What one load took, in total and per stage."""

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
            "    {:<44} {:>6} {:>10} {:>10} {:>7}".format(
                "stage", "calls", "total ms", "self ms", "% wall"
            )
        )
        for name, calls, total, own in sorted(self.stages, key=lambda row: -row[3]):
            # Below a millisecond a stage says nothing about why a load feels
            # slow, and there are enough of them to bury the ones that do. The
            # four steps of the load are the exception: they are what the wall
            # time is divided into, and one of them costing nothing itself is
            # the answer to a question rather than noise, so they always show.
            if own * 1000 < 1.0 and not name.startswith("load."):
                continue
            lines.append(
                "    {:<44} {:>6} {:>10.1f} {:>10.1f} {:>6.1f}%".format(
                    name, calls, total * 1000, own * 1000, own / self.wall * 100
                )
            )
        accounted = sum(row[3] for row in self.stages)
        lines.append(
            "    {:<44} {:>6} {:>10} {:>10.1f} {:>6.1f}%".format(
                "(not marked: Python, Qt, Coin, document)",
                "",
                "",
                (self.wall - accounted) * 1000,
                (self.wall - accounted) / self.wall * 100,
            )
        )
        return lines


def measure(label, action):
    """
    Run *action* once with the stages timed, and say what they took.

    Unlike the other benchmarks there is no warm-up run: a load is the first
    thing that ever happens to a mesh, and running it twice would measure a
    document that already holds what is being loaded. What a repeat would have
    said is asked for separately instead, as a load of its own.
    """
    import FemGui

    FemGui.perfReset()
    FemGui.perfEnable(True)
    start = time.perf_counter()
    try:
        action()
    finally:
        wall = time.perf_counter() - start
        FemGui.perfEnable(False)
    return Measurement(label, wall, FemGui.perfReport())


def active_view():
    """The 3D view to force a frame out of, or None when there is none."""
    import FreeCADGui

    document = FreeCADGui.ActiveDocument
    if document is None:
        return None
    view = document.ActiveView
    return view if hasattr(view, "redraw") else None


def run(cells_per_axis=CELLS_PER_AXIS, small_cells_per_axis=SMALL_CELLS_PER_AXIS, keep=True):
    """
    Load a mesh file of half a million elements into a mesher of a mesh group,
    and report what the wait was spent on.

    Three loads are timed. The small one comes first, to pay the one-off costs -
    the VTK pipeline, the Python view providers, the panel - that would
    otherwise be charged to the big one, and to be the number the big one is
    read against. Then the big load into a mesher that holds nothing, which is
    the case a user meets when a mesh run finishes. Then the same file again
    into the same mesher, which is what re-meshing costs and says how much of
    the first load was setup that only ever happens once.

    Returns the measurements, so that a caller can compare two runs.
    """
    import FreeCADGui

    if not hasattr(FreeCADGui, "getMainWindow") or FreeCADGui.getMainWindow() is None:
        raise RuntimeError("the mesh load only runs with a GUI")

    small_path = write_fixture(small_cells_per_axis)
    path = write_fixture(cells_per_axis)
    names = name_of_tag()

    document = FreeCAD.newDocument("FemMeshLoadBenchmark")
    measurements = []

    print()
    print("=" * 100)
    print("FEM mesh load: from the file an external mesher wrote to a drawn mesh")
    print("=" * 100)

    def timed_load(label, mesher, mesh_path, view):
        loaded = []
        measurement = measure(
            label, lambda: loaded.append(load(document, mesher, mesh_path, names, view))
        )
        mesh = loaded[0]
        measurements.append(measurement)
        print(
            f"    [{mesh.NodeCount} nodes, {mesh.VolumeCount} volumes, {mesh.FaceCount} faces]"
        )
        for line in measurement.report():
            print(line)
        print()

    warm_analysis, warm_mesher = build_model(document, "Warm")
    open_panel(warm_analysis)
    view = active_view()
    timed_load(
        f"load {small_cells_per_axis ** 3} elements  [warm-up, small]",
        warm_mesher,
        small_path,
        view,
    )

    # A model of its own, so that the big load goes into a mesher that has never
    # held a mesh - which is what a finished mesh run is - rather than replacing
    # one.
    analysis, mesher = build_model(document, "Load")
    show_analysis(analysis)
    timed_load(
        f"load {cells_per_axis ** 3} elements  [cold, into an empty mesher]",
        mesher,
        path,
        view,
    )
    timed_load(
        f"load {cells_per_axis ** 3} elements  [again, replacing the mesh]",
        mesher,
        path,
        view,
    )

    print("=" * 100)
    print("summary")
    for measurement in measurements:
        print(f"    {measurement.wall:8.2f} s  {measurement.label}")
    print("=" * 100)

    if not keep:
        FreeCAD.closeDocument(document.Name)
    return measurements


def main():
    """
    Run the benchmark in a GUI that quits when it is done.

    Meant for ``FreeCAD path/to/mesh_load.py``, so the main window has to go away
    by itself. Documents are closed first, otherwise the unsaved changes dialog
    waits for an answer that never comes.
    """
    import sys

    import FreeCADGui

    try:
        run(keep=False)
    finally:
        sys.stdout.flush()
        FreeCADGui.Control.closeDialog()
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)
        FreeCADGui.getMainWindow().close()


# A script handed to FreeCAD is imported as a top-level module named after the
# file, so __name__ is never "__main__" and the usual guard would never fire.
# Belonging to a package is what tells the two apart: only the import from
# femtest.perf, which wants to call run() itself, has one.
if not __package__:
    main()
