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
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

"""
What the post-processing view spends its time on when a result is drawn, hidden,
and narrowed to part of the model by the Model filter.

The point of the run is a comparison. The same document carries the same mesh
twice over: once as the analysis the preprocessing view draws, where hiding a
component has already been made fast, and once as a result in a post-processing
pipeline, where it has not. Both hides are measured here, on one model in one
run, so the two numbers can be read against each other rather than against a
memory of an earlier run on another machine.

Every stage the post-processing path marked with FEM_PERF_SCOPE reports what it
took and how often it ran, which is what separates "the filter is slow" from
"the filter is fine and the drawing after it is not".

Hand it to FreeCAD, which runs everything and quits when it is done::

    ./bin/FreeCAD Mod/Fem/femtest/perf/post_pipeline.py

Or call it from the Python console of a running FreeCAD, which leaves the model
behind to look at::

    from femtest.perf import post_pipeline
    post_pipeline.run()

``run`` takes ``nodes_per_axis`` above all: lowering it makes a quick run,
raising it says how a stage scales.
"""

__title__ = "FEM post-processing pipeline benchmark"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import time

import FreeCAD
import ObjectsFem

# Absolute, not relative: FreeCAD imports a script handed to it as a top-level
# module with no package, and a relative import would fail there. The path is
# importable either way, so this form serves both.
from femtest.perf import view_pipeline
from femtest.perf.view_pipeline import measure

# The same default the preprocessing benchmark uses, so the mesh numbers of the
# two runs can be laid side by side.
NODES_PER_AXIS = view_pipeline.NODES_PER_AXIS


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------


def build_result(document, assembly):
    """
    A pipeline holding a result of the assembly's solve mesh, attributed.

    No solver is run. What is under test is what the view does with a result,
    not how the result was arrived at, and the mesh the solver would have been
    handed is the mesh the result has to be built on for the attribution to
    match it cell for cell.
    """
    from femtools import membertools

    solve_mesh = membertools.get_mesh_to_solve(assembly)

    holder = document.addObject("Fem::FemMeshObject", "ResultMesh")
    holder.FemMesh = solve_mesh.FemMesh
    document.recompute()

    result = ObjectsFem.makeResultMechanical(document, "Result")
    result.Mesh = holder
    numbers = list(holder.FemMesh.Nodes.keys())
    result.NodeNumbers = numbers
    # A field with a real range, because colouring walks every point of it and
    # a constant would still be walked but would not be a fair colour bar.
    result.DisplacementVectors = [
        FreeCAD.Vector(0.0, 0.0, (index % 100) * 0.01) for index in range(len(numbers))
    ]
    assembly.addObject(result)
    document.recompute()

    pipeline = document.addObject("Fem::FemPostPipeline", "Pipeline")
    pipeline.load(result)
    assembly.addObject(pipeline)
    document.recompute()

    pipeline.attribute(solve_mesh, assembly)
    document.recompute()

    return pipeline


def add_material(document, assembly):
    """One material over everything, so Material is a grouping the filter offers."""
    material = ObjectsFem.makeMaterialSolid(document, "Steel")
    card = material.Material
    card["Name"] = "CalculiX-Steel"
    material.Material = card
    assembly.addObject(material)
    document.recompute()
    return material


def show_as_surface(view_object):
    """Draw the surface, which is what the workbench puts a result up as.

    A post object added straight to the document comes up in Outline, and an
    outline is a box: no field to colour by, and a handful of lines where the
    surface has half a million polygons. Measuring that would be measuring
    nothing anyone looks at, so the benchmark sets the mode the workbench sets
    in ObjectsFem.makePostVtkResult.
    """
    view_object.DisplayMode = "Surface"


def use_field(view_object):
    """Colour by the first real field, the way a user looking at a result does.

    Left on "None" the view paints one flat colour and never walks the points,
    which is a quarter of the drawing skipped and not what anyone is looking at
    a result for.
    """
    fields = view_object.getEnumerationsOfProperty("Field")
    for name in fields:
        if name != "None":
            view_object.Field = name
            return name
    return None


def post_size(pipeline):
    """Points and cells the pipeline draws."""
    data = pipeline.Data
    if data is None:
        return 0, 0
    if hasattr(data, "GetNumberOfBlocks"):
        block = data.GetBlock(0)
        return block.GetNumberOfPoints(), block.GetNumberOfCells()
    return data.GetNumberOfPoints(), data.GetNumberOfCells()


# ---------------------------------------------------------------------------
# naming the Python half
# ---------------------------------------------------------------------------


def instrument():
    """
    Put the filter's own Python steps on the same clock as the C++ stages.

    The filter decides in Python what the VTK pipeline then runs, so a report
    that only timed C++ would book the deciding as unaccounted time and point at
    the wrong half. The marks go on from here rather than living in the filter,
    because a measurement is not something the filter should carry around.

    Idempotent, so a second run in the same session does not wrap twice.
    """
    import FemGui
    from femobjects import post_modelfilter

    def wrap(owner, method, stage):
        original = getattr(owner, method)
        if getattr(original, "_perf_wrapped", False):
            return

        def timed(*args, **kwargs):
            FemGui.perfBegin(stage)
            try:
                return original(*args, **kwargs)
            finally:
                FemGui.perfEnd()

        timed._perf_wrapped = True
        setattr(owner, method, timed)

    wrap(post_modelfilter.Attribution, "__init__", "post.python.readTables")
    wrap(post_modelfilter.PostModelFilter, "execute", "post.python.execute")
    wrap(post_modelfilter.PostModelFilter, "onChanged", "post.python.onChanged")
    wrap(post_modelfilter.PostModelFilter, "_update", "post.python.update")
    wrap(post_modelfilter.PostModelFilter, "_selected_ids", "post.python.selectIds")


# ---------------------------------------------------------------------------
# the operations
# ---------------------------------------------------------------------------


def components_of(filter_obj):
    """Component key -> the entities under it, as the filter sees them."""
    from femobjects import post_modelfilter

    attribution = post_modelfilter.Attribution(filter_obj.getInputData())
    groups = {}
    for (key, _label), entities in attribution.grouped("Component").items():
        groups[key] = entities
    return groups


def everything_but(groups, hidden):
    """The entities to check so that *hidden* is the one component left out."""
    keep = []
    for key, entities in groups.items():
        if key != hidden:
            keep.extend(entities)
    return keep


def run(nodes_per_axis=NODES_PER_AXIS, document=None, keep=True):
    """
    Build the model, draw a result of it, and time the operations that feel
    slow, against the preprocessing hide that has already been made fast.

    Returns the measurements, so that a caller can compare two runs.
    """
    import FreeCADGui
    import FemGui

    if not hasattr(FreeCADGui, "getMainWindow") or FreeCADGui.getMainWindow() is None:
        raise RuntimeError("the post-processing pipeline only runs with a GUI")

    owns_document = document is None
    if owns_document:
        document = FreeCAD.newDocument("FemPostPipelineBenchmark")

    start = time.perf_counter()
    assembly = view_pipeline.build_model(document, nodes_per_axis)
    add_material(document, assembly)
    pipeline = build_result(document, assembly)
    filter_obj = ObjectsFem.makePostFilterModel(document, pipeline)
    document.recompute()
    instrument()
    show_as_surface(pipeline.ViewObject)
    show_as_surface(filter_obj.ViewObject)
    document.recompute()
    field = use_field(pipeline.ViewObject)
    use_field(filter_obj.ViewObject)
    build_seconds = time.perf_counter() - start

    explorer, _ = view_pipeline._panel(assembly)
    model = explorer._model

    mesh_nodes, mesh_cells = view_pipeline.model_size(assembly)
    points, cells = post_size(pipeline)
    groups = components_of(filter_obj)

    print()
    print("=" * 96)
    print("FEM post-processing pipeline")
    print(f"  analysis drawn by the preprocessing view: {mesh_nodes} nodes, {mesh_cells} cells")
    print(f"  result drawn by the pipeline:             {points} points, {cells} cells")
    print(f"  components the Model filter offers:       {sorted(groups)}")
    print(f"  coloured by:                              {field}")
    print(f"  built in {build_seconds:.1f} s")
    print("=" * 96)

    measurements = []

    def add(measurement):
        measurements.append(measurement)
        for line in measurement.report():
            print(line)
        print()

    def recompute():
        document.recompute()

    def set_elements(names):
        filter_obj.Elements = names
        recompute()

    # ---- the post-processing side -------------------------------------
    #
    # The filter and the pipeline are drawn one at a time. Two visible post
    # objects both answer a data change, and the measurement would then hold
    # two redraws of the same thing.
    filter_obj.ViewObject.Visibility = False
    pipeline.ViewObject.Visibility = True

    add(
        measure(
            "pipeline hide",
            lambda: setattr(pipeline.ViewObject, "Visibility", False),
            lambda: setattr(pipeline.ViewObject, "Visibility", True),
        )
    )
    add(
        measure(
            "pipeline show",
            lambda: setattr(pipeline.ViewObject, "Visibility", True),
            lambda: setattr(pipeline.ViewObject, "Visibility", False),
        )
    )

    pipeline.ViewObject.Visibility = False
    filter_obj.ViewObject.Visibility = True
    set_elements([])

    hidden = sorted(groups)[0] if groups else None
    if hidden is None:
        print("no components to hide - the result carries no attribution")
    else:
        keep_names = everything_but(groups, hidden)
        add(
            measure(
                f"Model filter: hide component {hidden}",
                lambda: set_elements(keep_names),
                lambda: set_elements([]),
            )
        )
        add(
            measure(
                f"Model filter: show component {hidden} again",
                lambda: set_elements([]),
                lambda: set_elements(keep_names),
            )
        )
        add(
            measure(
                "Model filter: hide a second component on top",
                lambda: set_elements(everything_but(groups, sorted(groups)[-1])),
                lambda: set_elements(keep_names),
            )
        )

    if "Material" in filter_obj.getEnumerationsOfProperty("Attribute"):
        add(
            measure(
                "Model filter: group by Material instead",
                lambda: setattr(filter_obj, "Attribute", "Material"),
                lambda: setattr(filter_obj, "Attribute", "Component"),
            )
        )

    # ---- the preprocessing side, for scale ----------------------------
    #
    # The same mesh, hidden the way the view panel hides it. This is the
    # number the post-processing ones are meant to be read against.
    filter_obj.ViewObject.Visibility = False
    pipeline.ViewObject.Visibility = False
    state = FemGui.getAnalysisViewState(assembly)
    for stage in ("Geometry", "Mesh"):
        state.setActiveStage(stage)
        leg = view_pipeline._named_node(model, "Leg1")
        index = view_pipeline._named_node(model, "Component1", leg) if leg else None
        if index is None:
            print(f"mesh hide/show one component [{stage}]: no such row in the tree")
            continue
        add(
            measure(
                f"mesh hide/show one component  [{stage}]",
                lambda i=index: view_pipeline._toggle(model, i),
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
    """Run the benchmark in a GUI that quits when it is done."""
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
# Belonging to a package is what tells the two apart.
if not __package__:
    main()
