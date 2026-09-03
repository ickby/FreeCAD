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

"""Benchmark the mesh merge and topology classification.

Console-runnable via FreeCADCmd. Unlike the view-pipeline benchmark this needs
no GUI: Fem.perfEnable talks to the same PerfLog singleton the merge scopes
write into.

Run as:
    ./bin/FreeCADCmd Mod/Fem/femtest/perf/mesh_merge.py
or interactively:
    from femtest.perf import mesh_merge; mesh_merge.run()
"""

__title__ = "FEM mesh merge benchmark"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import time

import FreeCAD
import Part

import Fem
import ObjectsFem


# Nodes per edge of the synthetic tet lattice. 20 yields ~8k tets; 30 ~27k.
SIZES = (10, 20, 30)

# Solids in the geometry chain the topology section classifies.
GEOMETRY_SOLIDS = 8

# The scopes worth counting rather than timing. A merge that is meant to happen
# once has to happen exactly once: twice is a caller doing the work of the
# recompute behind its back, and the timings alone would not say so.
COUNTED_STAGES = (
    ("merge", "merge"),
    ("merge.placement", "placement"),
    ("merge.topology", "topology"),
    ("merge.classifyDimensions", "classify"),
    ("merge.catchAllGroups", "catchAll"),
    ("geometry.components", "geometry"),
)


class Measurement:
    """What one operation took, in total and per named stage."""

    def __init__(self, label, wall, stages):
        self.label = label
        self.wall = wall
        self.stages = stages

    def calls(self, stage):
        """How often a named scope was entered, 0 if it never was."""
        for name, calls, _total, _own in self.stages:
            if name == stage:
                return calls
        return 0

    def report(self):
        lines = [f"{self.label}: {self.wall * 1000:8.1f} ms"]
        if not self.stages:
            lines.append("    (nothing marked ran - the operation was a no-op)")
            return lines
        lines.append(
            "    {:<40} {:>6} {:>10} {:>10} {:>7}".format(
                "stage", "calls", "total ms", "self ms", "% wall"
            )
        )
        for name, calls, total, own in sorted(self.stages, key=lambda row: -row[3]):
            if own * 1000 < 0.05 and calls == 0:
                continue
            lines.append(
                "    {:<40} {:>6} {:>10.2f} {:>10.2f} {:>6.1f}%".format(
                    name,
                    calls,
                    total * 1000,
                    own * 1000,
                    own / self.wall * 100 if self.wall else 0.0,
                )
            )
        accounted = sum(row[3] for row in self.stages)
        lines.append(
            "    {:<40} {:>6} {:>10} {:>10.2f} {:>6.1f}%".format(
                "(not marked)",
                "",
                "",
                (self.wall - accounted) * 1000,
                (self.wall - accounted) / self.wall * 100 if self.wall else 0.0,
            )
        )
        return lines


def measure(label, action, prepare=None):
    """
    Run *action* with the merge stages timed.

    *prepare* puts the state back before both the warm-up and the timed run,
    so a cold merge stays cold and a re-merge after a child change starts from
    the same place each time.
    """
    if prepare:
        prepare()
    action()
    if prepare:
        prepare()

    Fem.perfReset()
    Fem.perfEnable(True)
    start = time.perf_counter()
    try:
        action()
    finally:
        wall = time.perf_counter() - start
        Fem.perfEnable(False)
    return Measurement(label, wall, Fem.perfReport())


def call_table(results):
    """One row per action, one column per counted scope."""
    width = max(len(m.label) for m in results)
    header = "{:<{w}}".format("action", w=width)
    for _stage, title in COUNTED_STAGES:
        header += "{:>11}".format(title)
    lines = [header, "-" * len(header)]
    for m in results:
        row = "{:<{w}}".format(m.label, w=width)
        for stage, _title in COUNTED_STAGES:
            row += "{:>11}".format(m.calls(stage))
        lines.append(row)
    return lines


def _tet_lattice(n):
    """
    Regular lattice of n^3 corner-sharing tets. Node count is (n+1)^3; volume
    count is n^3. Large enough that the merge and topology scopes show up.
    """
    mesh = Fem.FemMesh()
    # Node ids are 1-based and dense, which is what ComponentUnion's keyRange
    # path expects when the topology joins by node.
    for iz in range(n + 1):
        for iy in range(n + 1):
            for ix in range(n + 1):
                nid = 1 + ix + iy * (n + 1) + iz * (n + 1) * (n + 1)
                mesh.addNode(float(ix), float(iy), float(iz), nid)
    for iz in range(n):
        for iy in range(n):
            for ix in range(n):
                # Four corners of the unit cube starting at (ix, iy, iz).
                a = 1 + ix + iy * (n + 1) + iz * (n + 1) * (n + 1)
                b = a + 1
                c = a + (n + 1)
                d = a + (n + 1) * (n + 1)
                mesh.addVolume([a, b, c, d])
    return mesh


def _make_group(document, name, mesh):
    group = document.addObject("Fem::FemMeshShapeGroup", name)
    child = document.addObject("Fem::FemMeshObject", name + "Child")
    child.FemMesh = mesh
    group.Group = [child]
    document.recompute()
    return group, child


def _read_output(group):
    """
    A pure read of what the last recompute published.

    Nothing here may show a merge stage: the merge is an output of execute(),
    and a reader that triggered one would be doing the work of a recompute
    behind the back of the document.
    """
    group.getComponentCount()
    return group.FemMesh.NodeCount


def _request_rebuild(group):
    """Ask for a full rebuild the way a membership change does, without doing it."""
    group.Group = list(group.Group)


def _geometry_chain(document, name):
    """
    A group over one import step, which is the shortest real chain.

    Both objects are geometries of their own and each classifies the shape it
    publishes, so a changed input costs one geometry.components per step. That
    is the number to watch: it must not grow with what else happens to the
    chain.
    """
    group = ObjectsFem.makeGeometryGroup(document, name)
    step = ObjectsFem.makeGeometryImport(document, name + "Import")
    sources = []
    for i in range(GEOMETRY_SOLIDS):
        box = document.addObject("Part::Box", f"{name}Box{i}")
        box.Placement = FreeCAD.Placement(FreeCAD.Vector(i * 20.0, 0.0, 0.0), FreeCAD.Rotation())
        sources.append(box)
    step.Import = sources
    group.Group = [step]
    document.recompute()
    return group, step, sources


def _geometry_measurements(document):
    """What a geometry chain classifies, and how often."""
    results = []
    group, step, sources = _geometry_chain(document, "Geom")
    solids = len(group.Shape.Solids)

    def read_topology():
        for _ in range(10):
            group.getComponentCount()
            for c in range(group.getComponentCount()):
                group.getToplevelElements(c)

    results.append(
        measure(
            f"10 geometry topology reads, no change  [solids={solids}]",
            read_topology,
        )
    )

    labelled = [0]

    def irrelevant_property():
        labelled[0] += 1
        step.Label = f"Import {labelled[0]}"
        document.recompute()

    results.append(
        measure(
            f"recompute after irrelevant property on a step  [solids={solids}]",
            irrelevant_property,
        )
    )

    lengths = [10.0]

    def changed_input():
        lengths[0] += 1.0
        sources[0].Length = lengths[0]
        document.recompute()

    results.append(
        measure(
            f"recompute after a changed input shape  [solids={solids}]",
            changed_input,
        )
    )
    return results


def run(sizes=SIZES):
    document = FreeCAD.newDocument("MeshMergeBench")
    try:
        results = []
        for n in sizes:
            mesh = _tet_lattice(n)
            group, child = _make_group(document, f"Mesh{n}", mesh)
            nodes = mesh.NodeCount
            volumes = mesh.VolumeCount

            # Cold merge: the request is placed by prepare(), and the recompute
            # is the only thing that pays for it.
            results.append(
                measure(
                    f"cold merge  [n={n}, nodes={nodes}, vols={volumes}]",
                    document.recompute,
                    prepare=lambda: _request_rebuild(group),
                )
            )

            def reread():
                for _ in range(10):
                    _read_output(group)

            results.append(
                measure(
                    f"10 output reads, no change  [n={n}]",
                    reread,
                )
            )

            # A recompute with nothing requested must merge nothing. Touching the
            # child stands for the mesher settings, Components and labels that
            # reach the group through the Group link and say nothing about the
            # mesh it holds.
            def idle_recompute():
                child.touch()
                document.recompute()

            results.append(
                measure(
                    f"recompute after irrelevant child change  [n={n}]",
                    idle_recompute,
                )
            )

            # One mesh assignment, one full merge.
            def remesh():
                child.FemMesh = _tet_lattice(n)
                document.recompute()

            results.append(
                measure(
                    f"re-merge after child mesh change  [n={n}]",
                    remesh,
                )
            )

            # A move lays the coordinates down again and keeps the
            # classification, so merge.placement runs and the topology scopes
            # of the full path do not.
            moved = [0.0]

            def move():
                moved[0] += 1.0
                child.Placement = FreeCAD.Placement(
                    FreeCAD.Vector(moved[0], 0.0, 0.0), FreeCAD.Rotation()
                )
                document.recompute()

            results.append(
                measure(
                    f"re-merge after child placement change  [n={n}]",
                    move,
                )
            )

        results.extend(_geometry_measurements(document))

        print()
        print("=" * 72)
        print("FEM mesh merge and topology benchmark")
        print("=" * 72)
        for m in results:
            for line in m.report():
                print(line)
            print()

        print("=" * 72)
        print("Stage call counts")
        print("=" * 72)
        for line in call_table(results):
            print(line)
        print()
        return results
    finally:
        FreeCAD.closeDocument(document.Name)


# A script handed to FreeCADCmd is imported as a top-level module named after
# the file, so __name__ is never "__main__" and the usual guard would never
# fire. Belonging to a package is what tells the two apart: only the import
# from femtest.perf, which wants to call run() itself, has one.
if not __package__:
    run()
