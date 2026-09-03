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
import Fem


# Nodes per edge of the synthetic tet lattice. 20 yields ~8k tets; 30 ~27k.
SIZES = (10, 20, 30)


class Measurement:
    """What one operation took, in total and per named stage."""

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


def _force_merge(group):
    """Touch the topology so the lazy merge runs if the cache is invalid."""
    return group.getComponentCount()


def _invalidate(group):
    """Drop the merge cache the way a child mesh change does."""
    group.Group = list(group.Group)


def run(sizes=SIZES):
    document = FreeCAD.newDocument("MeshMergeBench")
    try:
        results = []
        for n in sizes:
            mesh = _tet_lattice(n)
            group, child = _make_group(document, f"Mesh{n}", mesh)
            nodes = mesh.NodeCount
            volumes = mesh.VolumeCount

            # Cold merge: cache invalid, first topology read pays for everything.
            _invalidate(group)

            def cold():
                _force_merge(group)

            results.append(
                measure(
                    f"cold merge  [n={n}, nodes={nodes}, vols={volumes}]",
                    cold,
                    prepare=lambda: _invalidate(group),
                )
            )

            # Warm re-reads must not merge again.
            _force_merge(group)

            def reread():
                for _ in range(10):
                    _force_merge(group)

            results.append(
                measure(
                    f"10 topology reads, no change  [n={n}]",
                    reread,
                )
            )

            # Child mesh change invalidates and forces a re-merge.
            def remesh():
                child.FemMesh = _tet_lattice(n)
                document.recompute()
                _force_merge(group)

            results.append(
                measure(
                    f"re-merge after child change  [n={n}]",
                    remesh,
                )
            )

        print()
        print("=" * 72)
        print("FEM mesh merge benchmark")
        print("=" * 72)
        for m in results:
            for line in m.report():
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
