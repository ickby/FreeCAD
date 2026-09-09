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
Notifications in the task panel: a state worth acting on, and the way to act.

An analysis passes through states its owner has to be told about - a geometry
that fell behind the model, a mesh thrown away by an update, a stage nobody has
set up yet - and each of them has an obvious next step. FreeCAD's task panel is
where work waiting to be done belongs, so that is where they are said, one
panel per state, inside a task watcher that is simply not there while it has
nothing to say.

The pieces are small on purpose. A notification is a condition, a sentence and
a list of actions; a watcher is a title, an icon and a list of notifications.
A state worth reporting later is an entry in a list, not another widget.
"""

__title__ = "FreeCAD FEM task panel notifications"
__author__ = "Stefan Tröger"
__url__ = "https://www.freecad.org"

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtGui


class _FlowLayout(QtGui.QLayout):
    """
    A row of buttons that wraps instead of shrinking or being cut off.

    The task panel is docked and the user decides how wide it is. A plain
    QHBoxLayout answers a width it cannot fit by clipping - the last button
    disappears off the edge with no sign that it was ever there - so the
    buttons are laid out by hand: as many as fit on a line, then a new line.
    Rows are right-aligned, which keeps the last and most likely action in the
    same corner however many lines it takes.
    """

    def __init__(self, spacing=6):
        super().__init__()
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    # -- the QLayout contract ----------------------------------------------

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return QtCore.Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._lay_out(QtCore.QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._lay_out(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    # -- the placement ------------------------------------------------------

    def _lay_out(self, rect, apply):
        spacing = self.spacing()
        rows = []
        row, row_width = [], 0
        for item in self._items:
            if not item.widget() or item.widget().isVisibleTo(item.widget().parentWidget()):
                hint = item.sizeHint()
                extra = hint.width() + (spacing if row else 0)
                if row and row_width + extra > rect.width():
                    rows.append((row, row_width))
                    row, row_width = [], 0
                    extra = hint.width()
                row.append((item, hint))
                row_width += extra
        if row:
            rows.append((row, row_width))

        y = rect.y()
        for placed, width in rows:
            height = max(hint.height() for _, hint in placed)
            if apply:
                x = rect.x() + rect.width() - width
                for item, hint in placed:
                    item.setGeometry(QtCore.QRect(x, y, hint.width(), height))
                    x += hint.width() + spacing
            y += height + spacing
        return max(0, y - rect.y() - spacing)


class _ActivityBar(QtGui.QWidget):
    """
    A bar that says work is happening, painted here rather than by the style.

    Qt's own indeterminate QProgressBar leaves its animation to the style, and
    this application runs with UI effects switched off: the bar then sits
    perfectly still, which says the opposite of what it is there for - at any
    size, as the styles were asked. Painting it costs a timer and a dozen
    lines, and the colours come from the palette like everything else in the
    panel, so it follows the user's theme.

    Indeterminate on purpose. Neither a mesher nor a solver reports how far
    along it is, and a bar that filled up would be inventing it.
    """

    def __init__(self, width=64, height=6, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self.phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.advance)

    def advance(self):
        """One frame on. Public so that it can be stepped without a clock."""
        self.phase = (self.phase + 0.022) % 1.0
        self.update()

    # Running only while it can be seen: a panel that is hidden, or a whole
    # task view that is, has no business spending frames.
    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)

        radius = self.height() / 2.0
        palette = self.palette()
        painter.setBrush(palette.color(QtGui.QPalette.ColorRole.Mid))
        painter.drawRoundedRect(QtCore.QRectF(self.rect()), radius, radius)

        # A chunk a third as wide, entering at the left and leaving at the
        # right; the same thing Qt's own busy bar does when it is allowed to.
        span = self.width() / 3.0
        left = self.phase * (self.width() + span) - span
        painter.setBrush(palette.color(QtGui.QPalette.ColorRole.Highlight))
        painter.drawRoundedRect(
            QtCore.QRectF(left, 0.0, span, float(self.height())), radius, radius
        )


def _dim(widget):
    """
    Step a widget's text back, in the theme's own ink.

    The palette's disabled colour rather than one of ours: it is the shade this
    theme already uses for text that is there to be glanced at, and it follows
    the user's theme like everything else in the panel.
    """
    palette = widget.palette()
    palette.setColor(
        QtGui.QPalette.ColorRole.WindowText,
        palette.color(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.WindowText),
    )
    widget.setPalette(palette)
    return widget


def _wrapping_label(text):
    """
    A label that gives way when the dock is narrowed.

    Word wrap alone is not enough: a label keeps a minimum width off its
    longest word and its size hint, and a layout that cannot go below that
    passes the overflow on to whoever is holding it - here, the task panel,
    which answers by cutting the sentence off at the edge. Saying the height
    follows from the width, and that any width will do, is what turns an
    overflow into another line.
    """
    label = QtGui.QLabel(text)
    label.setWordWrap(True)
    label.setMinimumWidth(1)
    policy = QtGui.QSizePolicy(QtGui.QSizePolicy.Policy.Ignored, QtGui.QSizePolicy.Policy.Minimum)
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    return label


class Action:
    """
    One button in a notification panel, and the thing it does.

    Two kinds, indistinguishable on screen. Given a *command*, the button is
    bound to it: the icon, the tooltip and - unless *text* overrides it, which
    is worth doing only where the menu wording is too long for a docked panel -
    the label all come from the command, and so does whether it can be pressed
    at all. Nothing about the button is written twice, and it greys itself out
    exactly when the command cannot help.

    Given *run* instead, the button calls that function with the analysis it is
    shown for. That is for work no command offers, and there is no reason to
    invent a command for the sake of a button: meshing a whole analysis is a
    function and has never been a command. Such an action may say when it is
    available through *enabled*, and carry an icon by name like any other.

    The difference exists for whoever registers a notification. A user reading
    one cannot tell, and should not be able to.
    """

    def __init__(self, command=None, text=None, icon=None, run=None, enabled=None):
        if command is None and run is None:
            raise ValueError("an action needs a command to run or a function to call")
        if command is not None and run is not None:
            raise ValueError("an action runs a command or a function, not both")
        if run is not None and not text:
            raise ValueError("an action without a command has to bring its own label")

        self.command = command
        self._text = text
        self._icon = icon
        self._run = run
        self._enabled = enabled

    # -- what the button shows ---------------------------------------------

    def text(self):
        if self._text:
            return self._text
        info = self._command_info()
        # The ampersand marks the menu accelerator and has no place on a button
        # that is not in a menu.
        return info["menuText"].replace("&", "") if info else ""

    def tooltip(self):
        if self.command is not None:
            info = self._command_info()
            return info["toolTip"] if info else ""
        return ""

    def icon(self):
        name = self._icon
        if name is None and self.command is not None:
            info = self._command_info()
            name = info["pixmap"] if info else None
        if not name:
            return None
        # Through the same factory the toolbar uses, so the button wears the
        # icon rather than a second rendering of the same drawing.
        return FreeCADGui.getIcon(name)

    # -- what the button does ----------------------------------------------

    def is_enabled(self, analysis):
        if self.command is not None:
            command = FreeCADGui.Command.get(self.command)
            return command is not None and command.isActive()
        return True if self._enabled is None else bool(self._enabled(analysis))

    def trigger(self, analysis):
        if self.command is not None:
            FreeCADGui.runCommand(self.command)
        else:
            self._run(analysis)

    def _command_info(self):
        command = FreeCADGui.Command.get(self.command)
        return command.getInfo() if command is not None else None


class Notification:
    """
    A state worth reporting, in the words the user needs and no more.

    *condition* is asked about the analysis on screen and decides whether the
    panel is there at all. *message* says what is true rather than what to
    press; *aside* is the consequence of pressing, for the cases where it is
    not obvious - that updating a geometry costs the mesh, say.

    Either text may be a function of the analysis instead of a string, for the
    states that have something to count: which mesher is running, how many are
    left, which ones failed.

    *actions* may be a list, or a function of the context for the states whose
    choices are not known when the watcher is built - which of the document's
    analyses to activate, say. The panel rebuilds its buttons when the list
    changes and leaves them alone when it does not.

    A state that is *work in progress* rather than a fact says so through
    *busy*, and the panel then shows an activity bar beside its buttons.
    *status* is the short line that goes with it - an elapsed time, a step
    name - kept apart from the message because it changes every second while
    the message does not. Nothing here knows about meshing: a solver reporting
    a run of its own needs the same two things and can say so the same way.
    """

    def __init__(
        self, key, icon, message, condition, aside=None, actions=(), busy=None, status=None
    ):
        self.key = key
        self.icon = icon
        self.message = message
        self.aside = aside
        self.actions = actions if callable(actions) else list(actions)
        self._condition = condition
        self._busy = busy
        self._status = status

    def applies(self, analysis):
        try:
            return bool(self._condition(analysis))
        except (AttributeError, ReferenceError, RuntimeError):
            # A document closing under us is not a reason to break the panel.
            return False

    def message_for(self, analysis):
        return self.message(analysis) if callable(self.message) else self.message

    def aside_for(self, analysis):
        return self.aside(analysis) if callable(self.aside) else self.aside

    def actions_for(self, context):
        return list(self.actions(context)) if callable(self.actions) else self.actions

    def is_busy(self, analysis):
        return bool(self._busy(analysis)) if callable(self._busy) else bool(self._busy)

    def status_for(self, analysis):
        return self._status(analysis) if callable(self._status) else (self._status or "")


class NotificationPanel(QtGui.QWidget):
    """
    One notification drawn: icon, message, consequence, and a row of buttons.

    Ordinary widgets in the application's palette, with no stylesheet of its
    own - the panel has to look like the rest of FreeCAD on whatever theme the
    user runs, and the only colour in it is the state icon. The buttons sit in
    a row of their own below the message rather than beside it: the task panel
    is docked and often narrow, and a button row that shares the line with the
    text squeezes the text first.
    """

    def __init__(self, notification, parent=None):
        super().__init__(parent)
        self.notification = notification
        self.busy = False
        self._analysis = None

        self.separator = QtGui.QFrame()
        self.separator.setFrameShape(QtGui.QFrame.Shape.HLine)
        self.separator.setFrameShadow(QtGui.QFrame.Shadow.Sunken)

        icon = FreeCADGui.getIcon(notification.icon)
        self.icon_label = QtGui.QLabel()
        if icon is not None:
            self.icon_label.setPixmap(icon.pixmap(16, 16))
        self.icon_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft
        )

        self.message = _wrapping_label("")

        self.aside = None
        if notification.aside:
            self.aside = _dim(_wrapping_label(""))

        self.activity = _ActivityBar()
        self.activity.hide()

        self.status = QtGui.QLabel()
        _dim(self.status)
        self.status.hide()

        self.buttons = []
        self.button_row = _FlowLayout(spacing=6)
        self._button_labels = None
        if not callable(notification.actions):
            self._set_buttons(notification.actions)

        # The activity bar and its clock sit on the same line as the buttons,
        # at the other end of it: work in progress on the left, what to do
        # about it on the right.
        action_row = QtGui.QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        action_row.addWidget(self.activity, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        action_row.addWidget(self.status, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        action_row.addLayout(self.button_row, 1)

        text_column = QtGui.QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(9)
        text_column.addWidget(self.message)
        if self.aside is not None:
            text_column.addWidget(self.aside)
        text_column.addLayout(action_row)

        body = QtGui.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        body.addWidget(self.icon_label, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        body.addLayout(text_column, 1)

        layout = QtGui.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        layout.addWidget(self.separator)
        layout.addLayout(body)
        self.setLayout(layout)

    def refresh(self, context, first_visible):
        """
        Show or hide, and say which. *first_visible* drops the rule on top.

        The context is whatever the watcher works on - an analysis for most of
        them, the document for the one that reports there being no analysis at
        all. Nothing is assumed about it here, not even that it exists: a
        notification that only makes sense for an analysis says so in its own
        condition, and the states worth reporting when there is none would
        otherwise be the ones that could never be shown.
        """
        analysis = context
        self._analysis = context
        applies = self.notification.applies(context)
        self.setVisible(applies)
        if not applies:
            return False

        actions = self.notification.actions_for(context)
        if self._button_labels != [action.text() for action in actions]:
            self._set_buttons(actions)

        self.separator.setVisible(not first_visible)
        # Re-read every time: a state that counts something - which mesher is
        # running, which ones failed - says something different on every pass.
        self.message.setText(self.notification.message_for(analysis))
        if self.aside is not None:
            self.aside.setText(self.notification.aside_for(analysis) or "")
        self.busy = self.notification.is_busy(analysis)
        self.activity.setVisible(self.busy)
        self.update_status(analysis)
        for action, button in self.buttons:
            button.setEnabled(action.is_enabled(analysis))
        return True

    def _set_buttons(self, actions):
        """
        Put this list of actions in the row, replacing whatever was there.

        Rebuilding rather than editing in place: an action carries its own
        label, icon and function, and matching those onto existing buttons one
        by one would be more work than making them again for a row that is
        never more than a handful wide.
        """
        for _action, button in self.buttons:
            self.button_row.removeWidget(button)
            button.setParent(None)
            button.deleteLater()
        self.buttons = []

        for action in actions:
            button = QtGui.QPushButton(action.text())
            icon = action.icon()
            if icon is not None:
                button.setIcon(icon)
            tooltip = action.tooltip()
            if tooltip:
                button.setToolTip(tooltip)
            button.clicked.connect(lambda checked=False, a=action: self._run(a))
            button.setSizePolicy(QtGui.QSizePolicy.Policy.Fixed, QtGui.QSizePolicy.Policy.Fixed)
            self.button_row.addWidget(button)
            self.buttons.append((action, button))

        # Last is rightmost, which is where the platform puts the one the user
        # most likely wants - but only where an author put it there. A computed
        # list is a set of equals, and marking whichever came last as the
        # default would recommend an analysis for no reason but its position.
        if self.buttons and not callable(self.notification.actions):
            self.buttons[-1][1].setDefault(True)
        self._button_labels = [action.text() for action in actions]

    def update_status(self, analysis):
        """
        The line that changes while nothing else does.

        Kept apart from refresh() so that a clock can tick once a second
        without every condition in the panel being asked again.
        """
        text = self.notification.status_for(analysis) if analysis is not None else ""
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _run(self, action):
        if self._analysis is not None:
            action.trigger(self._analysis)


class NotificationWidget(QtGui.QWidget):
    """
    The panels of one watcher, stacked in the order they were declared.

    Declaration order and nothing else: sorting by what happens to be showing
    would move a panel under the user's cursor between one recompute and the
    next.
    """

    def __init__(self, notifications, parent=None):
        super().__init__(parent)
        self.panels = [NotificationPanel(n) for n in notifications]
        self._analysis = None

        # Only while something is actually running, and only the status line:
        # a clock that ticks is the cheapest way to say that a process is still
        # alive, and re-asking every condition once a second to do it would be
        # the most expensive.
        self._clock = QtCore.QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick)

        layout = QtGui.QVBoxLayout()
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(9)
        for panel in self.panels:
            layout.addWidget(panel)
        self.setLayout(layout)
        self.setMinimumWidth(1)
        self.setSizePolicy(QtGui.QSizePolicy.Policy.Ignored, QtGui.QSizePolicy.Policy.Minimum)

    def refresh(self, analysis):
        """Bring every panel up to date; answer whether any of them is showing."""
        self._analysis = analysis
        shown = 0
        busy = False
        for panel in self.panels:
            if panel.refresh(analysis, first_visible=(shown == 0)):
                shown += 1
                busy = busy or panel.busy

        if busy and not self._clock.isActive():
            self._clock.start()
        elif not busy and self._clock.isActive():
            self._clock.stop()

        return shown > 0

    def _tick(self):
        for panel in self.panels:
            if panel.busy and not panel.isHidden():
                panel.update_status(self._analysis)


class NotificationWatcher:
    """
    A task watcher that is there only while it has something to say.

    The attributes are read by FreeCAD when the watcher is installed - title
    and icon head the box, *widgets* go inside it - so they are plain data. The
    whole box goes when every panel in it is hidden: an empty frame with a
    title in it is worse than nothing, because it teaches the user to ignore
    the place where the real thing will appear.
    """

    def __init__(self, title, icon, notifications, analysis_of):
        self.title = title
        self.icon = icon
        self.widget = NotificationWidget(notifications)
        self.widgets = [self.widget]
        self._analysis_of = analysis_of

    def shouldShow(self):
        return self.refresh()

    def refresh(self):
        """
        Bring the panels up to date and take the box with them.

        FreeCAD asks shouldShow() when the selection changes, when a task
        dialog closes and when the panel is shown - not when a document
        recomputes, which is exactly when these states appear and go. So the
        box is hidden here as well, the same widget the task view would hide
        and in the same way, and the two never disagree: whichever of them
        looks last, it reads the same conditions.
        """
        shown = self.widget.refresh(self._analysis_of())
        box = self._box()
        if box is not None and box.isVisible() != shown:
            box.setVisible(shown)
            # A box coming or going changes what the panel around it has room
            # for. Qt would get there on its own eventually; doing it now is
            # what keeps the panel from showing the previous state's layout
            # until something else happens to disturb it.
            parent = box.parentWidget()
            if parent is not None and parent.layout() is not None:
                parent.layout().activate()
        return shown

    def _box(self):
        """The task box FreeCAD built around our widget, once it has been put in one."""
        widget = self.widget.parentWidget()
        while widget is not None:
            if "TaskBox" in widget.metaObject().className():
                return widget
            widget = widget.parentWidget()
        return None
