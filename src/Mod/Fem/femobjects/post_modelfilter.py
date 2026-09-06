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

__title__ = "FreeCAD post model filter"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

## @package post_modelfilter
#  \ingroup FEM
#  \brief Post processing filter keeping the cells of chosen parts of the model

import FreeCAD

# check vtk version to potentially find missmatchs
from femguiutils.vtk_module_handling import vtk_module_handling

vtk_module_handling()

# IMPORTANT: Never import vtk directly. Often vtk is compiled with different QT
# version than FreeCAD, and "import vtk" crashes by importing qt components.
# Always import the filter and data modules only.
from vtkmodules.vtkCommonDataModel import vtkCompositeDataSet, vtkSelection, vtkSelectionNode
from vtkmodules.vtkFiltersExtraction import vtkExtractSelection

from . import base_fempythonobject

_PropHelper = base_fempythonobject._PropHelper

#: Per-cell index into the entity table, written by FemVTKTools::attributeResult.
ARRAY_ENTITY_IDS = "CellEntityIds"
#: Field data: the entity name of every index, in index order.
ARRAY_ENTITIES = "AttributionEntities"
#: Field data: entity name, component key, component label - three values per row.
ARRAY_COMPONENT = "AttributionComponent"
#: Field data: entity name, material key, material label - three values per row.
ARRAY_MATERIAL = "AttributionMaterial"

#: The id a cell carries when the attribution could say nothing about it.
UNATTRIBUTED_ID = -1

# The cells no entity speaks for are a choice like any other - they can be looked
# at, and they can be left out - so they need a name that can sit in Elements
# beside the entity names. Angle brackets never occur in a geometry element name
# nor in the dotted path leading to one, so nothing can collide with this.
UNATTRIBUTED = "<unattributed>"

#: The built-in identity pipeline every degenerate case falls back to.
PASSTHROUGH = "__passthrough__"

#: Our own pipeline, the one that actually extracts.
EXTRACTION = "model"

# What a result can be grouped by, in the order the combo box offers them.
#
# There is deliberately no mode that lists the entities flat. Every entity is
# already a row under the component it belongs to, so a flat list shows the same
# names with the grouping thrown away - which would only be worth something if
# the rows carried a colour of their own, and here they do not.
ATTRIBUTE_ARRAYS = {
    "Component": ARRAY_COMPONENT,
    "Material": ARRAY_MATERIAL,
}


def _first_dataset(data):
    """The data set of a result, reaching into a multi-frame set for its first block.

    Every block of a multi-frame result describes the same mesh and was
    attributed in the same pass, so one of them answers for all of them.
    """
    if data is None:
        return None
    if data.IsA("vtkDataSet"):
        return data
    if isinstance(data, vtkCompositeDataSet) or data.IsA("vtkCompositeDataSet"):
        iterator = data.NewIterator()
        iterator.InitTraversal()
        while not iterator.IsDoneWithTraversal():
            block = iterator.GetCurrentDataObject()
            if block is not None and block.IsA("vtkDataSet"):
                return block
            iterator.GoToNextItem()
    return None


class Attribution:
    """
    What a result says about itself, read off the tables stored on it.

    Built once from the input data and then only asked questions, because every
    part of the filter - the enumeration, the extraction and the panel tree -
    needs the same answers and none of them should read the raw arrays a second
    time. An instance whose ``entities`` is empty carries no attribution at all,
    which is the case a foreign result and a result from before this feature
    both land in.
    """

    def __init__(self, data=None):
        #: Entity name of every id, indexed by the id itself
        self.entities = []
        #: attribute name -> {entity name: (category key, category label)}
        self.categories = {}
        #: Number of cells carrying no entity at all
        self.unattributed_cells = 0
        #: The per-cell id array, kept so a selection can be built to match it
        self._ids = None

        dataset = _first_dataset(data)
        if dataset is None:
            return

        table = dataset.GetFieldData().GetAbstractArray(ARRAY_ENTITIES)
        ids = dataset.GetCellData().GetArray(ARRAY_ENTITY_IDS)
        if table is None or ids is None:
            return

        entities = [table.GetValue(i) for i in range(table.GetNumberOfValues())]

        # An id the table cannot answer for means the two were written by
        # different things, and nothing sensible can be done with either.
        for i in range(ids.GetNumberOfTuples()):
            value = int(ids.GetValue(i))
            if value == UNATTRIBUTED_ID:
                self.unattributed_cells += 1
            elif value < 0 or value >= len(entities):
                return

        self.entities = entities
        self._ids = ids

        for attribute, array_name in ATTRIBUTE_ARRAYS.items():
            side = dataset.GetFieldData().GetAbstractArray(array_name)
            if side is None:
                continue
            rows = {}
            for row in range(side.GetNumberOfValues() // 3):
                entity = side.GetValue(3 * row)
                rows[entity] = (side.GetValue(3 * row + 1), side.GetValue(3 * row + 2))
            self.categories[attribute] = rows

    def attributes(self):
        """The attributes this result can be grouped by, in a stable order."""
        return [name for name in ATTRIBUTE_ARRAYS if name in self.categories]

    def grouped(self, attribute):
        """(category key, category label) -> the entities in it, for *attribute*.

        Entities the attribute says nothing about are left out; they belong
        under the unattributed row, together with the cells no entity claims.
        """
        groups = {}
        for entity in self.entities:
            category = self.categories.get(attribute, {}).get(entity)
            if category is None:
                continue
            groups.setdefault(category, []).append(entity)
        return groups

    def uncategorised(self, attribute):
        """The entities *attribute* has no category for."""
        rows = self.categories.get(attribute, {})
        return [entity for entity in self.entities if entity not in rows]

    def new_id_array(self):
        """An empty array of the type the ids are stored in.

        A value selection compares array to array and refuses to compare an
        int32 array against a vtkIdType one, so the list is never built from a
        type picked here: it is built from the type the result happens to use.
        """
        return self._ids.NewInstance()

    def ids_of(self, entities):
        """The cell ids the named entities stand for, unknown names ignored."""
        wanted = set(entities)
        ids = [i for i, name in enumerate(self.entities) if name in wanted]
        if UNATTRIBUTED in wanted:
            ids.append(UNATTRIBUTED_ID)
        return ids

    def selectable(self, attribute):
        """Everything that can be checked for *attribute*, unattributed included."""
        names = list(self.entities)
        if self.unattributed_cells or self.uncategorised(attribute):
            names.append(UNATTRIBUTED)
        return names


class PostModelFilter(base_fempythonobject.BaseFemPythonObject):
    """
    A post processing filter that keeps only the cells of chosen model entities.

    An entity is chosen by name, and the attribute only decides what the names
    are grouped under while choosing them - the component a piece belongs to, or
    the material it was solved with.

    What it can offer is entirely a property of the result it is put on: a
    result carries the entity of every cell and the component and material of
    every entity, or it carries nothing at all and the filter is inert. There is
    no half way, and no case in which it shows an empty view - every degenerate
    one selects the built-in identity pipeline instead, so the filter is an
    exact no-op rather than an approximation of one.
    """

    Type = "Fem::PostFilterPython"

    def __init__(self, obj):
        super().__init__(obj)

        for prop in self._get_properties():
            prop.add_to_object(obj)

        self.__setupFilterPipeline(obj)

    def _get_properties(self):

        prop = [
            _PropHelper(
                type="App::PropertyEnumeration",
                name="Attribute",
                group="Model",
                doc="Which identity the model entities are grouped by",
                value=["Component"],
            ),
            _PropHelper(
                type="App::PropertyStringList",
                name="Elements",
                group="Model",
                doc="The model entities to keep, named the way the result names them",
                value=[],
            ),
        ]
        return prop

    def __setupFilterPipeline(self, obj):

        # A value selection, not a threshold: what is asked for is a set of ids
        # and a threshold can only express a range. The selection goes in as
        # plain data on the second port so the first one stays the single inlet
        # addFilterPipeline connects.
        self._extract = vtkExtractSelection()
        obj.addFilterPipeline(EXTRACTION, self._extract, self._extract)
        obj.setActiveFilterPipeline(PASSTHROUGH)

    def onDocumentRestored(self, obj):
        self.__setupFilterPipeline(obj)
        self._update(obj)

    def execute(self, obj):

        attribution = Attribution(obj.getInputData())

        # The attributes on offer are the ones this result actually carries. A
        # choice that is no longer available falls back to the first one rather
        # than being kept as a name nothing can answer.
        # A property enumeration cannot be empty, so a result that offers
        # nothing keeps the first name on the list with no table behind it. The
        # panel says so and the filter stays a no-op; see _selected_ids.
        available = attribution.attributes() or [next(iter(ATTRIBUTE_ARRAYS))]
        current = obj.Attribute
        obj.Attribute = available
        if current in available:
            obj.Attribute = current

        self._update(obj, attribution)

        # make sure parent class execute is called!
        return False

    def onChanged(self, obj, prop):

        # check if we are setup already
        if not hasattr(self, "_extract"):
            return

        if prop in ("Attribute", "Elements"):
            self._update(obj)

    def _update(self, obj, attribution=None):
        """Point the object at the pipeline the current choice calls for."""

        if attribution is None:
            attribution = Attribution(obj.getInputData())

        ids = self._selected_ids(obj, attribution)
        if ids is None:
            obj.setActiveFilterPipeline(PASSTHROUGH)
            return

        selection_list = attribution.new_id_array()
        # For a value selection it is the name of the list that says which array
        # the values are compared against.
        selection_list.SetName(ARRAY_ENTITY_IDS)
        for value in ids:
            selection_list.InsertNextValue(value)

        node = vtkSelectionNode()
        node.SetFieldType(vtkSelectionNode.CELL)
        node.SetContentType(vtkSelectionNode.VALUES)
        node.SetSelectionList(selection_list)

        selection = vtkSelection()
        selection.AddNode(node)

        self._extract.SetInputData(1, selection)
        obj.setActiveFilterPipeline(EXTRACTION)

    def _selected_ids(self, obj, attribution):
        """The ids to keep, or None when the filter has to be a no-op.

        Every case that cannot narrow anything down returns None, including the
        two that could technically be answered: everything checked is not a
        filter, and nothing checked would be an empty view that reads as
        breakage rather than as an answer.
        """

        if not attribution.entities:
            return None
        if obj.Attribute not in attribution.categories:
            return None

        selectable = attribution.selectable(obj.Attribute)
        checked = [name for name in obj.Elements if name in selectable]
        if not checked or len(checked) == len(selectable):
            return None

        return attribution.ids_of(checked)
