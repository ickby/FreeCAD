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
Reference-picking widget: one or more slots, two presentations.

The UI follows fem-selection-slot-ui-mockup.canvas.tsx. max_count == 1 is a
read-only line edit; everything else is a list with an inline close glyph.
"""

__title__ = "FEM reference selection slots"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

from PySide import QtCore
from PySide import QtGui

import FreeCAD
import FreeCADGui

from femguiutils import selection_handoff
from femguiutils.selection_coordinator import SelectionCoordinator, alt_held
from femguiutils.selection_rules import (
    PICK_DIRECT,
    PROMOTION_LOCKED,
    PROMOTION_OFFERED,
    PROMOTION_UNAVAILABLE,
    Accept,
    NeedsChoice,
    ReferenceRule,
    display_name,
    element_exists,
    evaluate,
    pickable_phrase,
    placeholder_text,
    resolve_pick,
    shape_kind,
)
from femtools import femutils

CLOSE_GLYPH_WIDTH = 18
STALE_ROLE = QtCore.Qt.UserRole + 2
# A refusal is orange whatever the theme, because no palette role means
# "warning" — but one tone cannot serve both ends. The first is the mockup's
# t.category.orange, which needs a dark backdrop; the second is the same hue
# taken down far enough to read on a light one.
WARN_ON_DARK = QtGui.QColor("#d08326")
WARN_ON_LIGHT = QtGui.QColor("#9a5c0d")
SLOT_COLORS = (
    (0.20, 0.55, 0.95),
    (0.85, 0.15, 0.85),
    (0.00, 0.75, 0.95),
    (0.95, 0.55, 0.10),
)

# Passive focus return must not re-arm a slot the user just left via the toggle.
_ARM_FOCUS_REASONS = (
    QtCore.Qt.MouseFocusReason,
    QtCore.Qt.TabFocusReason,
    QtCore.Qt.BacktabFocusReason,
    QtCore.Qt.ShortcutFocusReason,
)


def _blend(front, back, weight):
    return QtGui.QColor(
        round(front.red() * weight + back.red() * (1 - weight)),
        round(front.green() * weight + back.green() * (1 - weight)),
        round(front.blue() * weight + back.blue() * (1 - weight)),
    )


def _luminance(color):
    """WCAG relative luminance, so 'legible' is measured rather than judged."""

    def channel(value):
        value /= 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def contrast(one, two):
    low, high = sorted((_luminance(one), _luminance(two)))
    return (high + 0.05) / (low + 0.05)


def warn_color(palette, on_base=False):
    """Whichever orange stands out against the backdrop this theme provides."""
    back = palette.color(QtGui.QPalette.Base if on_base else QtGui.QPalette.Window)
    return max(WARN_ON_DARK, WARN_ON_LIGHT, key=lambda tone: contrast(tone, back))


def muted_color(palette, on_base=False):
    """
    The mockup's t.text.tertiary: a dimmed version of the app's own text.

    Not QPalette.Mid, which is derived from the button colour rather than the
    text: it happens to read as grey on a light theme and sinks into a dark
    one. Fading the text towards what it sits on follows any stylesheet.
    """
    text = QtGui.QPalette.Text if on_base else QtGui.QPalette.WindowText
    back = QtGui.QPalette.Base if on_base else QtGui.QPalette.Window
    # 0.7 rather than a half: an even mix reads as muted on a dark theme but
    # drops under the 4.5 contrast ratio body text wants on a light one.
    return _blend(palette.color(text), palette.color(back), 0.7)


def hairline_color(palette):
    """The border of an idle slot: visible, but never louder than its text."""
    return _blend(
        palette.color(QtGui.QPalette.WindowText),
        palette.color(QtGui.QPalette.Window),
        0.3,
    )


def draw_close_glyph(painter, rect, color, fill=0.32):
    """The row's remove glyph, stroked rather than typed so no font is needed."""
    side = min(rect.width(), rect.height()) * fill
    center = QtCore.QRectF(rect).center()
    box = QtCore.QRectF(center.x() - side / 2, center.y() - side / 2, side, side)
    pen = QtGui.QPen(color, 1.3)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(pen)
    painter.drawLine(box.topLeft(), box.bottomRight())
    painter.drawLine(box.topRight(), box.bottomLeft())
    painter.restore()


def _stroked_pixmap(size, paint):
    """Paint into a 2x pixmap. QPainter maps the ratio, so paint() is in points."""
    pixmap = QtGui.QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    paint(painter, QtCore.QRect(0, 0, size, size))
    painter.end()
    return pixmap


def close_icon(color, size=14):
    """
    The same glyph as an icon, for the one-pick field's inline clear.

    Drawn larger than in a row: there the glyph sits in a column of its own
    and the size is the padding, here the pixmap is the whole button.
    """
    return QtGui.QIcon(
        _stroked_pixmap(
            size, lambda painter, rect: draw_close_glyph(painter, rect, color, fill=0.52)
        )
    )


def swatch_pixmap(color, size):
    """The slot's colour, as the rounded chip the 3D marks are drawn in."""

    def paint(painter, rect):
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(color)
        radius = size * 0.22
        painter.drawRoundedRect(QtCore.QRectF(rect), radius, radius)

    return _stroked_pixmap(size, paint)


def warn_pixmap(color, size=12):
    """
    The refusal marker, stroked in the same hue as the sentence beside it.

    A style's own warning icon is a raster whose colour no FEM code chooses,
    so it would be the one thing in the row that ignores the warning colour.
    """

    def paint(painter, rect):
        # Inset past half the pen, or the stroke spills onto the outer pixel
        # row and the icon looks cropped against whatever it sits on.
        box = QtCore.QRectF(rect).adjusted(1.1, 1.3, -1.1, -1.1)
        apex = QtCore.QPointF(box.center().x(), box.top())
        left = QtCore.QPointF(box.left(), box.bottom())
        right = QtCore.QPointF(box.right(), box.bottom())
        path = QtGui.QPainterPath(apex)
        path.lineTo(right)
        path.lineTo(left)
        path.closeSubpath()
        pen = QtGui.QPen(color, 1.1)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawPath(path)
        middle = box.center().x()
        painter.drawLine(
            QtCore.QPointF(middle, box.top() + box.height() * 0.40),
            QtCore.QPointF(middle, box.bottom() - box.height() * 0.34),
        )
        painter.drawLine(
            QtCore.QPointF(middle, box.bottom() - box.height() * 0.16),
            QtCore.QPointF(middle, box.bottom() - box.height() * 0.12),
        )

    return _stroked_pixmap(size, paint)


def _tr(text, **kwargs):
    translated = FreeCAD.Qt.translate("FEM", text)
    if kwargs:
        return translated.format(**kwargs)
    return translated


def header_button_side(widget):
    """
    Side of a square header button: the height of a text button beside it.

    Nothing here is a fixed pixel count. A text button is sized from the font
    by the style, so a header row measured off one keeps its proportions at
    any font size and under any style.
    """
    probe = QtGui.QToolButton(widget)
    # Parented so it is measured under the style and font it would live in,
    # but a child is shown along with its parent unless it is told not to be
    probe.hide()
    probe.setText(_tr("Clear"))
    side = probe.sizeHint().height()
    probe.setParent(None)
    probe.deleteLater()
    return side


def flatten_links(value):
    """PropertyLinkSubList / LinkSub / Link / LinkList -> [(obj, sub), ...]."""
    picks = []
    if not value:
        return picks
    if not isinstance(value, (list, tuple)):
        return [(value, "")]
    for item in value:
        if item is None:
            continue
        if not isinstance(item, (list, tuple)):
            picks.append((item, ""))
            continue
        obj = item[0]
        if obj is None:
            continue
        subs = item[1] if len(item) > 1 else ()
        if isinstance(subs, str):
            subs = (subs,) if subs else ()
        if not subs:
            picks.append((obj, ""))
        else:
            for sub in subs:
                picks.append((obj, sub or ""))
    return picks


def pack_links(picks):
    """[(obj, sub), ...] -> [(obj, (subs...)), ...] preserving object order."""
    order = []
    buckets = {}
    for obj, sub in picks:
        if obj not in buckets:
            order.append(obj)
            buckets[obj] = []
        if sub:
            buckets[obj].append(sub)
    packed = []
    for obj in order:
        subs = tuple(buckets[obj])
        packed.append((obj, subs) if subs else obj)
    return packed


class PropertyAdapter:
    """Read and write one property as a flat list of (obj, sub)."""

    def __init__(self, obj, prop, role=None):
        self.obj = obj
        self.prop = prop
        self.role = role  # None | "master" | "slave"
        self.group = None

    def read(self):
        if self.obj is None or not self.prop:
            return []
        value = getattr(self.obj, self.prop)
        picks = flatten_links(value)
        # Stored as [slave..., master]. A single leftover pick is the master,
        # matching the old Contact/Tie convention.
        if self.role == "master":
            return picks[-1:] if picks else []
        if self.role == "slave":
            return picks[:-1] if len(picks) > 1 else []
        return picks

    def write(self, picks):
        if self.obj is None or not self.prop:
            return
        typeid = ""
        try:
            typeid = self.obj.getTypeIdOfProperty(self.prop)
        except Exception:
            typeid = ""
        if self.role in ("master", "slave"):
            # Combine from the sibling slots' in-memory picks, not by
            # re-slicing the property: a lone slave pick must not be read
            # back as the master while the panel is still open.
            slaves, masters = [], []
            if self.group is not None:
                for slot in self.group.slots:
                    adapter = getattr(slot, "adapter", None)
                    if adapter is None or adapter.prop != self.prop:
                        continue
                    if adapter.role == "slave":
                        slaves.extend(slot.picks)
                    elif adapter.role == "master":
                        masters.extend(slot.picks)
            else:
                if self.role == "master":
                    masters = list(picks)
                else:
                    slaves = list(picks)
            self.obj.setPropertyStatus(self.prop, "-Immutable")
            setattr(self.obj, self.prop, list(slaves) + list(masters))
            return
        if "LinkSubList" in typeid:
            setattr(self.obj, self.prop, list(picks))
        elif "LinkList" in typeid:
            setattr(self.obj, self.prop, [obj for obj, _sub in picks])
        elif "LinkSub" in typeid:
            if not picks:
                setattr(self.obj, self.prop, None)
            else:
                obj = picks[0][0]
                subs = [sub for other, sub in picks if other == obj and sub]
                setattr(self.obj, self.prop, (obj, subs))
        else:
            setattr(self.obj, self.prop, picks[0][0] if picks else None)


class PickList(QtGui.QTreeWidget):
    """
    The pick list, with the pointer highlight taken off its rows.

    A lit row reads as a button, and next to a close glyph it reads as the
    delete button — clicking the label would then be expected to remove the
    pick. Only the glyph should answer the pointer, and QTreeView draws the
    row before any delegate gets a say, so the state is dropped here.
    """

    def drawRow(self, painter, option, index):
        option.state &= ~QtGui.QStyle.State_MouseOver
        super().drawRow(painter, option, index)


class CloseGlyphDelegate(QtGui.QStyledItemDelegate):
    """Paint the row text elided from the left, and a close glyph on the right."""

    clicked = QtCore.Signal(int)

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self._hovered = -1
        view.viewport().setMouseTracking(True)
        view.viewport().installEventFilter(self)

    @staticmethod
    def glyph_rect(rect):
        return rect.adjusted(rect.width() - CLOSE_GLYPH_WIDTH, 0, 0, 0)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.MouseMove:
            self.set_hovered(self._row_under(event.pos()))
        elif event.type() == QtCore.QEvent.Leave:
            self.set_hovered(-1)
        return super().eventFilter(watched, event)

    def _row_under(self, pos):
        index = self.view.indexAt(pos)
        if not index.isValid() or not index.data(QtCore.Qt.UserRole):
            return -1
        if not self.glyph_rect(self.view.visualRect(index)).contains(pos):
            return -1
        return index.row()

    def set_hovered(self, row):
        if row == self._hovered:
            return
        self._hovered = row
        self.view.viewport().update()

    def paint(self, painter, option, index):
        opt = QtGui.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if not index.data(QtCore.Qt.UserRole):
            super().paint(painter, option, index)
            return
        opt.state &= ~QtGui.QStyle.State_MouseOver
        opt.rect = option.rect.adjusted(0, 0, -CLOSE_GLYPH_WIDTH, 0)
        opt.textElideMode = QtCore.Qt.ElideLeft
        QtGui.QStyledItemDelegate.paint(self, painter, opt, index)

        glyph = self.glyph_rect(option.rect)
        hovered = index.row() == self._hovered
        ink = option.palette.color(QtGui.QPalette.Text)
        if hovered:
            side = min(glyph.width(), glyph.height()) - 2
            plate = QtCore.QRectF(0, 0, side, side)
            plate.moveCenter(QtCore.QRectF(glyph).center())
            painter.save()
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(_blend(ink, option.palette.color(QtGui.QPalette.Base), 0.2))
            painter.drawRoundedRect(plate, 3, 3)
            painter.restore()
        draw_close_glyph(painter, glyph, ink if hovered else muted_color(option.palette, True))

    def editorEvent(self, event, model, option, index):
        if event.type() == QtCore.QEvent.MouseButtonRelease and index.data(QtCore.Qt.UserRole):
            if self.glyph_rect(option.rect).contains(event.pos()):
                self.clicked.emit(index.row())
                return True
        return super().editorEvent(event, model, option, index)


class ReferenceSlot(QtGui.QFrame):
    """One input: a single-line field or a list, plus arm / solid / status."""

    armedChanged = QtCore.Signal(object, bool)
    picksChanged = QtCore.Signal(object)

    def __init__(self, slot_id, title, rule, adapter=None, color=None, parent=None):
        super().__init__(parent)
        self.slot_id = slot_id
        self.title = title
        self.rule = rule
        self.adapter = adapter
        self.color = color or SLOT_COLORS[0]
        self.picks = []
        self.promotion_latched = False
        self._armed = False
        self._refusing = False
        self._syncing_palette = False
        self._group = parent
        self.setObjectName("FemReferenceSlot")
        self.setFrameShape(QtGui.QFrame.StyledPanel)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self._build()
        if adapter is not None:
            self.picks = list(adapter.read())
        self._sync_palette()
        self._rebuild()

    def changeEvent(self, event):
        """Follow the app to another theme: every colour here is derived."""
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.PaletteChange:
            self._sync_palette()
        elif event.type() == QtCore.QEvent.FontChange and hasattr(self, "clear_btn"):
            self._sync_metrics()

    def _sync_metrics(self):
        """The header's square buttons stand as tall as the Clear beside them."""
        side = self.clear_btn.sizeHint().height()
        # The two are glyphs in a text button, and text keeps its own size
        # while the box around it grows. Scale it so they fill their button
        # about as much as Clear's word fills its own.
        glyph = QtGui.QFont(self.font())
        if glyph.pointSizeF() > 0:
            glyph.setPointSizeF(glyph.pointSizeF() * 1.3)
        else:
            glyph.setPixelSize(round(glyph.pixelSize() * 1.3))
        for button in (self.arm_btn, self.solid_btn):
            button.setFont(glyph)
            button.setFixedSize(side, side)
        chip = max(8, round(side * 0.45))
        self.swatch.setFixedSize(chip, chip)
        self.swatch.setPixmap(swatch_pixmap(QtGui.QColor.fromRgbF(*self.color), chip))

    def _sync_palette(self):
        # Setting a stylesheet re-resolves the palette, which lands back here.
        if self._syncing_palette or not hasattr(self, "count_label"):
            return
        self._syncing_palette = True
        try:
            self._apply_palette()
        finally:
            self._syncing_palette = False

    def _apply_palette(self):
        palette = self.palette()
        muted = muted_color(palette).name()
        warn = warn_color(palette).name()
        self.count_label.setStyleSheet(f"color: {muted};")
        self.status.setStyleSheet(f"color: {warn if self._refusing else muted};")
        self.status_icon.setPixmap(warn_pixmap(warn_color(palette)))
        if self.clear_action is not None:
            self.clear_action.setIcon(close_icon(muted_color(palette, on_base=True)))
        self._sync_frame()
        self._tint_stale_rows()

    def _tint_stale_rows(self):
        """A stale row's colour is a brush on the item, out of reach of a restyle."""
        if self.list is None:
            return
        brush = QtGui.QBrush(warn_color(self.palette(), on_base=True))
        for index in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(index)
            if item.data(0, STALE_ROLE):
                item.setForeground(0, brush)

    def _sync_frame(self):
        """Armed is a 2 px accent bar on the leading edge, and nothing else."""
        palette = self.palette()
        color = (
            palette.color(QtGui.QPalette.Highlight).name()
            if self._armed
            else hairline_color(palette).name()
        )
        self.setStyleSheet(
            f"QFrame#FemReferenceSlot {{ border: 1px solid {color};"
            f" border-left: 2px solid {color}; }}"
        )

    def _build(self):
        self.swatch = QtGui.QLabel()

        self.title_label = QtGui.QLabel(self.title)
        self.count_label = QtGui.QLabel("0")
        self.count_label.setVisible(self.rule.max_count != 1)

        self.solid_btn = QtGui.QToolButton()
        self.solid_btn.setCheckable(True)
        self.solid_btn.setAutoRaise(True)
        self.solid_btn.setToolTip(_tr("Take the solid behind the pick — or hold Alt"))
        self.solid_btn.setText("▣")
        self.solid_btn.toggled.connect(self._solid_toggled)
        if self.rule.promotion == PROMOTION_UNAVAILABLE:
            self.solid_btn.hide()
        elif self.rule.promotion == PROMOTION_LOCKED:
            self.solid_btn.setChecked(True)
            self.solid_btn.setEnabled(False)
            self.solid_btn.setToolTip(
                _tr("This feature takes solids, picked through their faces and edges")
            )

        self.arm_btn = QtGui.QToolButton()
        # Not "btnAdd": that is the name of the legacy button in the .ui files
        # the C++ panels still load, and those get hidden by name.
        self.arm_btn.setObjectName("FemReferenceArm")
        self.arm_btn.setCheckable(True)
        self.arm_btn.setAutoRaise(True)
        self.arm_btn.setToolTip(_tr("Click to pick in the 3D view"))
        self.arm_btn.setText("◎")
        self.arm_btn.clicked.connect(self._arm_clicked)

        self.clear_btn = QtGui.QToolButton()
        self.clear_btn.setAutoRaise(True)
        self.clear_btn.setText(_tr("Clear"))
        self.clear_btn.clicked.connect(self.clear)
        # A one-pick field carries its own inline clear button.
        self.clear_btn.setVisible(self.rule.max_count != 1)
        self._sync_metrics()

        header = QtGui.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.arm_btn)
        header.addWidget(self.solid_btn)
        header.addWidget(self.swatch)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.count_label)
        header.addWidget(self.clear_btn)

        self.status_icon = QtGui.QLabel()
        self.status_icon.setFixedSize(12, 12)
        self.status_icon.setPixmap(warn_pixmap(warn_color(self.palette())))
        self.status_icon.hide()
        self.status = QtGui.QLabel()
        self.status.setWordWrap(True)
        status_row = QtGui.QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(5)
        status_row.addWidget(self.status_icon, 0, QtCore.Qt.AlignTop)
        status_row.addWidget(self.status, 1)

        layout = QtGui.QVBoxLayout()
        layout.addLayout(header)

        if self.rule.max_count == 1:
            self.field = QtGui.QLineEdit()
            self.field.setReadOnly(True)
            # setClearButtonEnabled() draws the button but Qt disables it on a
            # read-only field, so the same glyph goes in as an action instead.
            self.field.setPlaceholderText(placeholder_text(self.rule))
            # The stock clear icon is a themed pixmap that a FreeCAD
            # stylesheet does not necessarily recolour, so it is the same
            # glyph the list rows draw, stroked in the palette's own text.
            self.clear_action = self.field.addAction(
                close_icon(muted_color(self.palette(), on_base=True)),
                QtGui.QLineEdit.TrailingPosition,
            )
            self.clear_action.setToolTip(_tr("Clear"))
            self.clear_action.triggered.connect(self.clear)
            self.list = None
            layout.addWidget(self.field)
        else:
            self.field = None
            self.clear_action = None
            self.list = PickList()
            self.list.setRootIsDecorated(False)
            self.list.setHeaderHidden(True)
            self.list.setUniformRowHeights(True)
            self.list.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
            self.list.setIndentation(0)
            self.delegate = CloseGlyphDelegate(self.list)
            self.delegate.clicked.connect(self._remove_row)
            self.list.setItemDelegate(self.delegate)
            # The same two actions serve the keys and the right-click menu, so
            # the menu can never drift from what the keys do.
            self.list.setContextMenuPolicy(QtCore.Qt.ActionsContextMenu)
            remove = QtGui.QAction(_tr("Remove"), self.list)
            remove.setShortcuts(
                [
                    QtGui.QKeySequence(QtCore.Qt.Key_Delete),
                    QtGui.QKeySequence(QtCore.Qt.Key_Backspace),
                ]
            )
            remove.setShortcutContext(QtCore.Qt.WidgetShortcut)
            remove.triggered.connect(self._remove_selected)
            self.list.addAction(remove)
            clear = QtGui.QAction(_tr("Clear list"), self.list)
            clear.triggered.connect(self.clear)
            self.list.addAction(clear)
            layout.addWidget(self.list)

        # The arm follows focus into the pick area, or the arm toggle. Arming
        # from the slot frame as well pre-checks the checkable arm button on
        # the same click and Qt toggles it off again immediately afterward.
        for child in (self.field, self.list):
            if child is not None:
                child.installEventFilter(self)

        layout.addLayout(status_row)
        self.setLayout(layout)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.FocusIn and event.reason() in _ARM_FOCUS_REASONS:
            self.arm()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self._remove_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def arm(self):
        if self._group is not None and hasattr(self._group, "arm"):
            self._group.arm(self.slot_id)
        else:
            self.set_armed(True)

    def set_rule(self, rule):
        """Replace the rule, e.g. when a panel changes the target kind."""
        self.rule = rule
        if self.rule.promotion == PROMOTION_UNAVAILABLE:
            self.solid_btn.hide()
            self.promotion_latched = False
        elif self.rule.promotion == PROMOTION_LOCKED:
            self.solid_btn.show()
            self.solid_btn.setChecked(True)
            self.solid_btn.setEnabled(False)
            self.promotion_latched = True
        else:
            self.solid_btn.show()
            self.solid_btn.setEnabled(True)
        self._rebuild()
        if self._group is not None:
            self._group.coordinator._refresh_preview()

    def set_armed(self, armed):
        self._armed = bool(armed)
        self.arm_btn.blockSignals(True)
        self.arm_btn.setChecked(self._armed)
        self.arm_btn.blockSignals(False)
        self.arm_btn.setToolTip(
            _tr("Picking — click to stop") if self._armed else _tr("Click to pick in the 3D view")
        )
        self._sync_frame()
        self.show_idle_status()

    def set_promotion_latched(self, on):
        if self.rule.promotion != PROMOTION_OFFERED:
            return
        self.promotion_latched = bool(on)
        self.solid_btn.blockSignals(True)
        self.solid_btn.setChecked(self.promotion_latched)
        self.solid_btn.blockSignals(False)
        self._sync_solid_visual()
        self.show_idle_status()
        if self._group is not None:
            self._group.coordinator._refresh_preview()

    def _solid_toggled(self, checked):
        self.set_promotion_latched(checked)

    def _arm_clicked(self):
        """Arm or disarm from the header toggle only — not from frame focus."""
        if self._group is not None and self._group.coordinator.armed_slot is self:
            self._group.coordinator.disarm()
        else:
            self.arm()

    def _sync_solid_visual(self):
        if self.rule.promotion == PROMOTION_UNAVAILABLE:
            return
        held = alt_held() and self._armed and self.rule.promotion == PROMOTION_OFFERED
        if self.rule.promotion == PROMOTION_LOCKED:
            self.solid_btn.setToolTip(
                _tr("This feature takes solids, picked through their faces and edges")
            )
        elif held:
            self.solid_btn.setToolTip(_tr("Alt held — taking the solid behind the pick"))
        elif self.promotion_latched:
            self.solid_btn.setToolTip(_tr("Taking the solid behind every pick — click to stop"))
        else:
            self.solid_btn.setToolTip(_tr("Take the solid behind the pick — or hold Alt"))
        # Holding Alt is invisible otherwise, and a dashed border says the
        # promotion lasts only as long as the key does — the latched state
        # keeps the button's own checked look.
        accent = self.palette().color(QtGui.QPalette.Highlight).name()
        self.solid_btn.setStyleSheet(
            f"QToolButton {{ border: 1px dashed {accent}; color: {accent}; }}" if held else ""
        )

    def show_idle_status(self):
        """
        Name what can be picked right now — and nothing else.

        An unarmed slot takes no picks, so it has nothing to say: the frame
        already shows which slot is armed.
        """
        mode = (
            self._group.coordinator.pick_mode_of(self) if self._group is not None else PICK_DIRECT
        )
        self._refusing = False
        self.status.setStyleSheet(f"color: {muted_color(self.palette()).name()};")
        self.status.setText(pickable_phrase(self.rule, mode, self.picks) if self._armed else "")
        self.status_icon.hide()
        self._sync_solid_visual()

    def set_status(self, text, refused=True):
        if not text:
            self.show_idle_status()
            return
        self._refusing = bool(refused)
        self.status.setStyleSheet(
            f"color: {warn_color(self.palette()).name()};"
            if refused
            else f"color: {muted_color(self.palette()).name()};"
        )
        self.status.setText(text)
        self.status_icon.setVisible(refused)

    def accept_picks(self, picks):
        if self.rule.max_count == 1:
            self.picks = list(picks[:1])
        else:
            for pick in picks:
                if pick not in self.picks:
                    if self.rule.max_count and len(self.picks) >= self.rule.max_count:
                        break
                    self.picks.append(pick)
        self._commit()

    def set_picks(self, picks):
        """Replace the whole list, as when a panel restores a stored value."""
        self.picks = list(picks)
        self._commit()

    def clear(self):
        self.picks = []
        self._commit()

    def _remove_row(self, row):
        if row < 0 or row >= self.list.topLevelItemCount():
            return
        item = self.list.topLevelItem(row)
        if not item.data(0, QtCore.Qt.UserRole):
            return
        index = item.data(0, QtCore.Qt.UserRole + 1)
        if isinstance(index, int) and 0 <= index < len(self.picks):
            del self.picks[index]
            self._commit()

    def _remove_selected(self):
        if self.list is None:
            self.clear()
            return
        rows = sorted(
            (self.list.indexOfTopLevelItem(item) for item in self.list.selectedItems()),
            reverse=True,
        )
        changed = False
        for row in rows:
            item = self.list.topLevelItem(row)
            index = item.data(0, QtCore.Qt.UserRole + 1) if item else None
            if isinstance(index, int) and 0 <= index < len(self.picks):
                del self.picks[index]
                changed = True
        if changed:
            self._commit()

    def _commit(self):
        if self.adapter is not None:
            self.adapter.write(self.picks)
        self._rebuild()
        self._update_marks()
        self.picksChanged.emit(self)

    def _rebuild(self):
        n = len(self.picks)
        if self.rule.max_count:
            self.count_label.setText(f"{n} of {self.rule.max_count}")
        else:
            self.count_label.setText(str(n))
        self.clear_btn.setEnabled(n > 0)
        if self.field is not None:
            self.field.blockSignals(True)
            if self.picks:
                self.field.setText(display_name(*self.picks[0]))
                # A QLineEdit cannot elide, so scroll to the tail instead: an
                # imported name is only useful from its element backwards.
                self.field.setCursorPosition(len(self.field.text()))
            else:
                self.field.clear()
                self.field.setPlaceholderText(placeholder_text(self.rule))
            self.field.blockSignals(False)
            self.clear_action.setVisible(bool(self.picks))
        if self.list is not None:
            self.list.clear()
            for index, (obj, sub) in enumerate(self.picks):
                item = QtGui.QTreeWidgetItem([display_name(obj, sub)])
                item.setData(0, QtCore.Qt.UserRole, True)
                item.setData(0, QtCore.Qt.UserRole + 1, index)
                if not element_exists(obj, sub):
                    item.setText(0, _tr("{name} — gone", name=display_name(obj, sub)))
                    item.setData(0, STALE_ROLE, True)
                    item.setToolTip(0, _tr("This element is gone from the shape."))
                self.list.addTopLevelItem(item)
            outstanding = self.rule.max_count - n if self.rule.max_count else (1 if n == 0 else 0)
            for _ in range(max(0, outstanding)):
                item = QtGui.QTreeWidgetItem([placeholder_text(self.rule)])
                item.setDisabled(True)
                font = item.font(0)
                font.setItalic(True)
                item.setFont(0, font)
                item.setData(0, QtCore.Qt.UserRole, False)
                self.list.addTopLevelItem(item)
            self._tint_stale_rows()
        self.show_idle_status()

    def _update_marks(self):
        if self._group is not None and getattr(self, "marks", True):
            self._group.update_marks(self)

    def mark_role(self):
        obj = self._group.obj if self._group is not None else None
        name = obj.Name if obj is not None else "slot"
        return f"selection:{name}:{self.slot_id}"


class ReferenceSelection(QtGui.QWidget):
    """
    Group of ReferenceSlots sharing one coordinator.

    The surface C++ calls: from_slot_specs(), finish_selection(), widget.
    """

    referencesUpdated = QtCore.Signal(object)

    def __init__(self, obj=None, parent=None, geometry=None, auto_install=True):
        super().__init__(parent)
        self.obj = obj
        self.widget = self
        self.slots = []
        self.coordinator = SelectionCoordinator(self)
        self._marks = {}
        self._geometry_override = geometry
        self.auto_install = auto_install
        # A backstop under the key events below: a window manager is free to
        # keep Alt to itself, and then the only way to notice is to ask.
        self._mod_timer = QtCore.QTimer(self)
        self._mod_timer.setInterval(80)
        self._mod_timer.timeout.connect(self._poll_modifier)
        self._last_alt = False
        self._filtering = False

        layout = QtGui.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

    @property
    def document(self):
        if self.obj is not None:
            return self.obj.Document
        return FreeCAD.ActiveDocument

    @property
    def geometry(self):
        if self._geometry_override is not None:
            return self._geometry_override
        if self.obj is not None:
            return femutils.get_reference_geometry(self.obj)
        try:
            import FemGui

            return femutils.get_reference_geometry(FemGui.getActiveAnalysis())
        except Exception:
            return None

    @property
    def references(self):
        """Flat picks of the first slot, matching GeometryElementsSelection."""
        return list(self.slots[0].picks) if self.slots else []

    @references.setter
    def references(self, picks):
        if self.slots:
            self.slots[0].picks = list(picks)
            self.slots[0]._commit()

    def has_equal_references_shape_types(self, ref_shty=""):
        """True if every stored pick is the same shape kind. Homogeneous slots keep this true."""
        kinds = {shape_kind(sub) for _obj, sub in self.references if shape_kind(sub)}
        return len(kinds) <= 1

    def add_slot(
        self,
        slot_id,
        title,
        rule,
        property=None,
        role=None,
        color=None,
        adapter=None,
        marks=True,
    ):
        if adapter is None and property:
            adapter = PropertyAdapter(self.obj, property, role=role)
        if adapter is not None:
            adapter.group = self
        color = color or SLOT_COLORS[len(self.slots) % len(SLOT_COLORS)]
        slot = ReferenceSlot(slot_id, title, rule, adapter=adapter, color=color, parent=self)
        slot.marks = marks
        slot.picksChanged.connect(self._slot_changed)
        self.slots.append(slot)
        self.layout().addWidget(slot)
        return slot

    def slot(self, slot_id):
        for item in self.slots:
            if item.slot_id == slot_id:
                return item
        return None

    def set_slot_visible(self, slot_id, visible):
        slot = self.slot(slot_id)
        if slot is not None:
            slot.setVisible(bool(visible))

    def arm(self, slot_id):
        target = slot_id if not isinstance(slot_id, str) else self.slot(slot_id)
        if target is None:
            return
        self.coordinator.arm(target)

    def begin_selection(self):
        """
        Start listening for picks, and arm a slot to receive them.

        Shown groups do this for themselves. A host that lays the slot
        widgets out itself, rather than showing the group, has to say when
        picking starts — without it the arm button lights up over nothing
        and no pick ever arrives.
        """
        self.coordinator.install()
        self._watch_modifier(True)
        if self.coordinator.armed_slot is None and self.slots:
            self.arm(self.slots[0].slot_id)

    def finish_selection(self):
        self.coordinator.remove()
        self._watch_modifier(False)
        self._clear_all_marks()

    def consume_current_selection(self):
        """Take the live 3D selection into the armed slot (partition Add)."""
        if self.coordinator.armed_slot is None and self.slots:
            self.arm(self.slots[0].slot_id)
        self.coordinator.addSelection("", "", "", None)

    def consume_handoff(self):
        """Prefill the armed slot from a create-command stash, then clear the selection."""
        picks = selection_handoff.take(self.obj) if self.obj is not None else []
        armed = self.coordinator.armed_slot
        if armed is None and self.slots:
            self.arm(self.slots[0].slot_id)
            armed = self.coordinator.armed_slot
        taken = 0
        skipped = 0
        if armed is not None and not armed.picks and picks:
            mode = self.coordinator.pick_mode_of(armed)
            for obj, sub in picks:
                obj, sub = resolve_pick(obj, sub)
                result = evaluate(
                    armed.rule,
                    mode,
                    obj,
                    sub,
                    armed.picks,
                    geometry=self.geometry,
                    document=self.document,
                )
                if isinstance(result, Accept):
                    armed.accept_picks(result.picks)
                    taken += 1
                else:
                    skipped += 1
            if skipped:
                armed.set_status(
                    _tr("{taken} of {total} picks taken.", taken=taken, total=taken + skipped)
                )
        try:
            FreeCADGui.Selection.clearSelection()
        except Exception:
            pass

    def update_marks(self, slot):
        role = slot.mark_role()
        self._apply_marks(role, slot.picks, slot.color)
        self._marks[role] = slot.picks

    def showEvent(self, event):
        super().showEvent(event)
        if self.auto_install:
            self.begin_selection()
        for slot in self.slots:
            slot._update_marks()

    def hideEvent(self, event):
        if self.auto_install:
            self.coordinator.remove()
            self._watch_modifier(False)
        super().hideEvent(event)

    def _watch_modifier(self, on):
        app = QtGui.QApplication.instance()
        if on == self._filtering or app is None:
            return
        self._filtering = on
        if on:
            app.installEventFilter(self)
            self._mod_timer.start()
        else:
            app.removeEventFilter(self)
            self._mod_timer.stop()

    def _poll_modifier(self):
        self._alt_changed(alt_held())

    def eventFilter(self, watched, event):
        """
        Alt straight off the keyboard, before anyone has to move the mouse.

        The polled state comes from the platform's idea of the modifiers,
        which on a good few of them is only as fresh as the last input event
        the application saw. Hovering a face and pressing Alt produces no
        such event, so the poll would read the old state until the pointer
        twitched. The key press itself is the event that was missing.
        """
        kind = event.type()
        if kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            if event.key() == QtCore.Qt.Key_Alt and not event.isAutoRepeat():
                self._alt_changed(kind == QtCore.QEvent.KeyPress)
        return super().eventFilter(watched, event)

    def _alt_changed(self, held):
        if held == self._last_alt:
            return
        self._last_alt = held
        armed = self.coordinator.armed_slot
        if armed is not None:
            armed._sync_solid_visual()
            armed.show_idle_status()
            self.coordinator._refresh_preview()

    def _slot_changed(self, slot):
        self.referencesUpdated.emit(self.references)

    def _apply_marks(self, role, picks, color):
        grouped = {}
        for obj, sub in picks:
            if obj is None:
                continue
            grouped.setdefault(obj, []).append(sub)
        previous = getattr(self, "_marked_objs", {}).get(role, [])
        for obj in previous:
            self._set_highlight(obj, role, [], color)
        for obj, elements in grouped.items():
            self._set_highlight(obj, role, [e for e in elements if e], color)
        if not hasattr(self, "_marked_objs"):
            self._marked_objs = {}
        self._marked_objs[role] = list(grouped)

    def _clear_all_marks(self):
        for role, objs in getattr(self, "_marked_objs", {}).items():
            for obj in objs:
                self._set_highlight(obj, role, [], None)
        self._marked_objs = {}

    def _set_highlight(self, obj, role, elements, color):
        try:
            import FemGui

            if hasattr(FemGui, "setElementHighlight"):
                FemGui.setElementHighlight(obj, role, list(elements), color)
                return
        except Exception:
            pass
        view = getattr(obj, "ViewObject", None)
        if view is not None and hasattr(view, "setElementHighlight"):
            view.setElementHighlight(role, list(elements), color)


def for_references(
    obj,
    types,
    *,
    homogeneous=True,
    title=None,
    empty_means_all=False,
    promotion_latched=False,
    max_count=None,
    property="References",
):
    """Single-slot group used by most Python task panels."""
    group = ReferenceSelection(obj)
    rule = ReferenceRule(types=tuple(types), homogeneous=homogeneous, max_count=max_count)
    slot = group.add_slot(
        "References",
        title or _tr("References"),
        rule,
        property=property,
    )
    if promotion_latched:
        slot.set_promotion_latched(True)
    group.arm("References")
    group.consume_handoff()
    if empty_means_all:
        slot.arm_btn.setToolTip(
            _tr(
                "Click and select geometric elements to add them to the list. "
                "If no geometry is added, all remaining ones are used."
            )
        )
    return group


def from_slot_specs(obj, specs, geometry=None):
    """
    Build a group from a list of dicts. The C++ host calls this.

    Each spec: property, title, types, max_count, homogeneous, armed,
    promotion_latched, role, object_kinds, allow_empty_sub, id, scope, marks.
    """
    group = ReferenceSelection(obj, geometry=geometry)
    armed = None
    for spec in specs:
        types = tuple(spec.get("types") or ())
        max_count = spec.get("max_count") or None
        rule = ReferenceRule(
            types=types,
            max_count=max_count,
            homogeneous=spec.get("homogeneous", True),
            scope=spec.get("scope") or "geometry",
            object_kinds=tuple(spec.get("object_kinds") or ()),
            allow_empty_sub=spec.get("allow_empty_sub", False),
        )
        slot = group.add_slot(
            spec.get("id") or spec.get("property") or f"slot{len(group.slots)}",
            spec.get("title") or spec.get("property") or "",
            rule,
            property=spec.get("property"),
            role=spec.get("role"),
            marks=spec.get("marks", True),
        )
        if spec.get("promotion_latched"):
            slot.set_promotion_latched(True)
        if spec.get("armed"):
            armed = slot.slot_id
    group.arm(armed or (group.slots[0].slot_id if group.slots else None))
    group.consume_handoff()
    return group
