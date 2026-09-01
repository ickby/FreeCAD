# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2026 Stefan Tröger <stefantroeger@gmx.net>              *
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""
One global selection gate and one observer for every slot in a panel.

Gui.Selection only holds a single ActiveGate. This coordinator is that gate:
allow() delegates to the armed slot's rule, and the observer routes clicks
to the same slot. The arm never moves on its own.
"""

__title__ = "FEM reference selection coordinator"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

from PySide import QtCore
from PySide import QtGui

import FreeCAD
import FreeCADGui

from femguiutils.disambiguate_solid_selection import disambiguate_solid_selection
from femguiutils.selection_rules import (
    PICK_DIRECT,
    PICK_SOLID,
    PROMOTION_LOCKED,
    PROMOTION_UNAVAILABLE,
    Accept,
    NeedsChoice,
    Refuse,
    evaluate,
    leaf_name,
    resolve_pick,
    shape_kind,
)


def _tr(text, **kwargs):
    translated = FreeCAD.Qt.translate("FEM", text)
    if kwargs:
        return translated.format(**kwargs)
    return translated


def alt_held():
    return bool(QtGui.QApplication.queryKeyboardModifiers() & QtCore.Qt.AltModifier)


def set_preselect_promotion(on):
    """Ask every FEM geometry view in the active document to promote hover."""
    try:
        import FemGui

        if hasattr(FemGui, "setPreselectPromotion"):
            FemGui.setPreselectPromotion(bool(on))
            return
    except ImportError:
        pass
    doc = FreeCAD.ActiveDocument
    if doc is None:
        return
    for obj in doc.Objects:
        view = getattr(obj, "ViewObject", None)
        if view is not None and hasattr(view, "setPreselectPromotion"):
            view.setPreselectPromotion(bool(on))


REFUSAL_POLL_MS = 100
# SelectionChanges::MsgSource::Any. The Python default is Internal, which
# setPreselect takes as a reason to skip the gate entirely.
MSG_SOURCE_ANY = 0
# ResolveMode::NoResolve. Resolving hands out the last object of the way down
# and drops the way itself, and an element inside a placed analysis is only
# addressable with that way in front of it. resolve_pick() reads it instead.
NO_RESOLVE = 0


def pointer_is_blocked():
    """
    Whether the pointer is still showing the refusal that raised it.

    Nothing announces that the pointer left an element the gate turned away:
    setPreselect drops the preselection before it consults the gate, so a
    refused element never becomes one and no RmvPreselect ever follows. What
    does track it exactly is the cursor — Selection.cpp puts the forbidden
    shape on the viewer as it refuses, and SoFCUnifiedSelection takes it off
    again from the render pass once the pointer is somewhere harmless. Read
    that back and the sentence lasts precisely as long as the symbol does.
    """
    widget = QtGui.QApplication.widgetAt(QtGui.QCursor.pos())
    return widget is not None and widget.cursor().shape() == QtCore.Qt.ForbiddenCursor


class SelectionCoordinator:
    """
    Python SelectionGate + SelectionObserver owned by a ReferenceSelection.

    The observer spans the panel: installed on the group's showEvent, removed
    on hideEvent and finish_selection(). The gate spans an armed slot instead,
    because a gate with nothing to admit is a gate that only refuses.
    addSelectionGate replaces any existing gate; we cannot restore one,
    because the singleton deletes it.
    """

    def __init__(self, group):
        self.group = group
        self.notAllowedReason = ""
        self._installed = False
        self._gated = False
        self._armed = None
        self._promoting = False
        self._refused_slot = None
        self._sweep = QtCore.QTimer()
        self._sweep.setInterval(REFUSAL_POLL_MS)
        self._sweep.timeout.connect(self._sweep_refusal)

    @property
    def armed_slot(self):
        return self._armed

    def pick_mode_of(self, slot):
        if slot is None:
            return PICK_DIRECT
        promotion = slot.rule.promotion
        if promotion == PROMOTION_LOCKED:
            return PICK_SOLID
        if promotion == PROMOTION_UNAVAILABLE:
            return PICK_DIRECT
        if slot.promotion_latched or alt_held():
            return PICK_SOLID
        return PICK_DIRECT

    def arm(self, slot):
        if self._armed is slot:
            self._refresh_preview()
            return
        previous = self._armed
        self._armed = slot
        if previous is not None and previous is not slot:
            previous.set_armed(False)
        if slot is not None:
            slot.set_armed(True)
        self._sync_gate()
        self._refresh_preview()

    def disarm(self):
        if self._armed is not None:
            self._armed.set_armed(False)
        self._armed = None
        self._sync_gate()
        self._refresh_preview()

    def install(self):
        if self._installed:
            return
        FreeCADGui.Selection.addObserver(self, NO_RESOLVE)
        self._installed = True
        self._sync_gate()
        self._refresh_preview()

    def remove(self):
        if not self._installed:
            return
        self._release_gate()
        try:
            FreeCADGui.Selection.removeObserver(self)
        except Exception:
            pass
        self._installed = False
        self._promoting = False
        set_preselect_promotion(False)

    def _sync_gate(self):
        """
        The gate lives exactly as long as a slot is armed.

        Left standing while nothing is armed it refuses every pick, so the
        3D view goes dead for the rest of the panel — the arm toggle has to
        hand the view back, not just stop listening to it.
        """
        wanted = self._installed and self._armed is not None
        if wanted and not self._gated:
            FreeCADGui.Selection.addSelectionGate(self, NO_RESOLVE)
            self._gated = True
        elif not wanted and self._gated:
            self._release_gate()

    def _release_gate(self):
        if not self._gated:
            return
        try:
            FreeCADGui.Selection.removeSelectionGate()
        except Exception:
            pass
        self._gated = False
        self._forget_refusal()

    def allow(self, doc, obj, sub):
        slot = self._armed
        if slot is None:
            self.notAllowedReason = ""
            return False
        obj, sub = resolve_pick(obj, sub or "")
        result = self._evaluate(slot, obj, sub)
        if isinstance(result, (Accept, NeedsChoice)):
            self.notAllowedReason = ""
            self._forget_refusal()
            if isinstance(result, NeedsChoice):
                names = " and ".join(leaf_name(name) for _o, name in result.candidates)
                slot.set_status(
                    _tr(
                        "{leaf} bounds {names} — click to choose which.",
                        leaf=leaf_name(sub or ""),
                        names=names,
                    )
                )
            else:
                slot.show_idle_status()
            return True
        reason = result.reason if isinstance(result, Refuse) else _tr("Not allowed.")
        if getattr(result, "redirectable", True):
            other = self._other_slot_that_takes(obj, sub or "", except_slot=slot)
            if other is not None:
                reason = _tr(
                    "{leaf} belongs in {title} — click that field first.",
                    leaf=leaf_name(sub or "") or obj.Label,
                    title=other.title,
                )
        self.notAllowedReason = reason
        self._show_refusal(slot, reason)
        return False

    # -- how long a refusal stays up -----------------------------------------

    def _show_refusal(self, slot, reason):
        slot.set_status(reason)
        self._refused_slot = slot
        # The cursor is only put up once allow() has answered, so the first
        # look has to come later than this call.
        self._sweep.start()

    def _sweep_refusal(self):
        """Poll, alive only while a refusal is on screen, never past it."""
        if self._refused_slot is None or not pointer_is_blocked():
            self._forget_refusal(idle=True)

    def _forget_refusal(self, idle=False):
        slot, self._refused_slot = self._refused_slot, None
        self._sweep.stop()
        if idle and slot is not None:
            slot.show_idle_status()

    def getGatedTypes(self, all_types):
        slot = self._armed
        if slot is None:
            return set()
        allowed = slot.rule.gated_types
        return {name for name in all_types if name in allowed}

    def addSelection(self, doc_name, obj_name, sub, pos):
        slot = self._armed
        if slot is None:
            return
        resolved = []
        try:
            for sel in FreeCADGui.Selection.getSelectionEx("", NO_RESOLVE):
                for name in sel.SubElementNames or ("",):
                    resolved.append(resolve_pick(sel.Object, name))
        except Exception:
            resolved = []
        if not resolved and doc_name and obj_name:
            document = FreeCAD.getDocument(doc_name)
            obj = document.getObject(obj_name) if document else None
            obj, sub = resolve_pick(obj, sub or "")
            if obj is not None:
                resolved = [(obj, sub)]
        for obj, sub in resolved:
            result = self._evaluate(slot, obj, sub or "")
            if isinstance(result, NeedsChoice):
                chosen = self._choose_solid(result)
                if chosen is not None:
                    slot.accept_picks([chosen])
                break
            if isinstance(result, Accept):
                slot.accept_picks(result.picks)
        FreeCADGui.Selection.clearSelection()

    def removePreselection(self, *args):
        self._forget_refusal()
        if self._armed is not None:
            self._armed.show_idle_status()

    def setPreselection(self, *args):
        """A hover the gate let through ends whatever the last one refused."""
        self._forget_refusal()

    def _evaluate(self, slot, obj, sub):
        return evaluate(
            slot.rule,
            self.pick_mode_of(slot),
            obj,
            sub,
            slot.picks,
            geometry=self.group.geometry,
            document=self.group.document,
        )

    def _other_slot_that_takes(self, obj, sub, except_slot):
        obj, sub = resolve_pick(obj, sub)
        for slot in self.group.slots:
            if slot is except_slot:
                continue
            result = evaluate(
                slot.rule,
                self.pick_mode_of(slot),
                obj,
                sub,
                slot.picks,
                geometry=self.group.geometry,
                document=self.group.document,
            )
            if isinstance(result, (Accept, NeedsChoice)):
                return slot
        return None

    def _choose_solid(self, result):
        """Put the candidates up in the existing menu and return the chosen pick."""
        if not result.candidates:
            return None
        obj = result.candidates[0][0]
        indices = []
        prefix = ""
        for _obj, name in result.candidates:
            leaf = name.rsplit(".", 1)[-1]
            head = name.rpartition(".")[0]
            if head:
                prefix = head
            if shape_kind(leaf) != "Solid":
                indices = []
                break
            try:
                indices.append(int(leaf[len("Solid") :]) - 1)
            except ValueError:
                indices = []
                break
        # Only solids can be previewed by recolouring the part face by face.
        # Components and anything else get the plain list.
        chosen = (
            disambiguate_solid_selection(obj, indices)
            if indices
            else self._choose_from_list(result.candidates)
        )
        if not chosen:
            return None
        full = f"{prefix}.{chosen}" if prefix else chosen
        return (obj, full)

    @staticmethod
    def _choose_from_list(candidates):
        menu = QtGui.QMenu()
        label = menu.addAction(_tr("The pick belongs to several, choose one…"))
        label.setDisabled(True)
        for _obj, name in candidates:
            menu.addAction(leaf_name(name))
        action = menu.exec_(QtGui.QCursor.pos())
        return action.text() if action is not None else None

    def _refresh_preview(self):
        promoting = self._armed is not None and self.pick_mode_of(self._armed) == PICK_SOLID
        set_preselect_promotion(promoting)
        if promoting != self._promoting:
            self._promoting = promoting
            self._recheck_preselection()

    def _recheck_preselection(self):
        """
        Put the standing hover through the gate again under the new pick mode.

        setPreselect returns early on an element that is already preselected,
        before it ever reaches the gate. A hover the gate accepted therefore
        survives Alt going down: the highlight promotes to the whole solid and
        it goes on looking pickable, under an ordinary pointer, until the
        pointer crosses onto something else and the gate is finally asked.

        Clearing it first is what makes the second ask happen, and going back
        in through setPreselection rather than calling allow() directly is
        what puts the forbidden cursor up with the sentence — Selection.cpp
        raises the two together, and only for a source other than Internal,
        which is why the type argument is spelled out.
        """
        if self._armed is None:
            return
        obj, sub = self._standing_preselection()
        if obj is None:
            return
        FreeCADGui.Selection.clearPreselection()
        try:
            FreeCADGui.Selection.setPreselection(obj, sub, 0.0, 0.0, 0.0, MSG_SOURCE_ANY)
        except Exception:
            pass

    @staticmethod
    def _standing_preselection():
        try:
            standing = FreeCADGui.Selection.getPreselection()
            obj = getattr(standing, "Object", None)
            if obj is None:
                return None, ""
            names = getattr(standing, "SubElementNames", None) or ("",)
            return obj, names[0]
        except Exception:
            return None, ""
