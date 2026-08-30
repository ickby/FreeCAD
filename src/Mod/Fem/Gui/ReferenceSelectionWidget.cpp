/***************************************************************************
 *   Copyright (c) 2026 Stefan Tröger <stefantroeger@gmx.net>              *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#include "ReferenceSelectionWidget.h"

#include <App/DocumentObject.h>
#include <Base/Console.h>
#include <Base/Interpreter.h>
#include <Gui/PythonWrapper.h>

#include <QBoxLayout>
#include <QVBoxLayout>


using namespace FemGui;

namespace
{

Py::List toPyList(const std::vector<std::string>& values)
{
    Py::List list;
    for (const auto& value : values) {
        list.append(Py::String(value));
    }
    return list;
}

Py::Dict toPySpec(const ReferenceSlotSpec& spec)
{
    Py::Dict dict;
    dict.setItem("property", Py::String(spec.property));
    dict.setItem("title", Py::String(spec.title));
    dict.setItem("types", toPyList(spec.types));
    if (spec.maxCount > 0) {
        dict.setItem("max_count", Py::Long(spec.maxCount));
    }
    dict.setItem("homogeneous", Py::Boolean(spec.homogeneous));
    dict.setItem("armed", Py::Boolean(spec.armed));
    dict.setItem("promotion_latched", Py::Boolean(spec.promotionLatched));
    if (!spec.role.empty()) {
        dict.setItem("role", Py::String(spec.role));
    }
    if (!spec.id.empty()) {
        dict.setItem("id", Py::String(spec.id));
    }
    if (!spec.objectKinds.empty()) {
        dict.setItem("object_kinds", toPyList(spec.objectKinds));
    }
    dict.setItem("allow_empty_sub", Py::Boolean(spec.allowEmptySub));
    dict.setItem("scope", Py::String(spec.scope));
    return dict;
}

}  // namespace

void FemGui::hideLegacyReferenceWidgets(QWidget* root)
{
    if (!root) {
        return;
    }
    static const char* names[] = {
        "lbl_info",
        "lbl_info_2",
        "lbl_references",
        "btnAdd",
        "btnRemove",
        "btnAddSlave",
        "btnRemoveSlave",
        "btnAddMaster",
        "btnRemoveMaster",
        "buttonReference",
        "buttonDirection",
        "buttonLocation",
        "lineDirection",
        "lineLocation",
        "lw_references",
        "lw_referencesSlave",
        "lw_referencesMaster",
        "listReferences",
        "lw_Rect",
        nullptr
    };
    for (const char** name = names; *name; ++name) {
        if (auto* widget = root->findChild<QWidget*>(QLatin1String(*name))) {
            widget->hide();
        }
    }
}

ReferenceSelectionWidget::ReferenceSelectionWidget(
    App::DocumentObject* obj,
    const std::vector<ReferenceSlotSpec>& specs,
    QWidget* parent
)
    : QWidget(parent)
{
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);

    if (!obj) {
        return;
    }

    Base::PyGILStateLocker lock;
    try {
        Py::Module mod(PyImport_ImportModule("femguiutils.selection_slots"), true);
        if (mod.isNull()) {
            Base::Console().error("Unable to import femguiutils.selection_slots\n");
            return;
        }

        Py::List pySpecs;
        for (const auto& spec : specs) {
            pySpecs.append(toPySpec(spec));
        }

        Py::Callable method(mod.getAttr(std::string("from_slot_specs")));
        Py::Tuple args(2);
        args.setItem(0, Py::asObject(obj->getPyObject()));
        args.setItem(1, pySpecs);
        m_panel = method.apply(args);

        Gui::PythonWrapper wrap;
        if (wrap.loadCoreModule()) {
            if (auto* widget = qobject_cast<QWidget*>(wrap.toQObject(m_panel))) {
                layout->addWidget(widget);
            }
        }
    }
    catch (Py::Exception&) {
        Base::PyException e;
        e.reportException();
        Base::Console().error("Unable to import the FEM reference selection widget\n");
    }
}

ReferenceSelectionWidget::~ReferenceSelectionWidget()
{
    finish();
}

void ReferenceSelectionWidget::finish()
{
    Base::PyGILStateLocker lock;
    try {
        if (m_panel.isNull() || m_panel.isNone()) {
            return;
        }
        if (m_panel.hasAttr(std::string("finish_selection"))) {
            Py::Callable method(m_panel.getAttr(std::string("finish_selection")));
            method.apply(Py::Tuple());
        }
        m_panel = Py::None();
    }
    catch (Py::Exception&) {
        Base::PyException e;
        e.reportException();
    }
}

void ReferenceSelectionWidget::setSlotVisible(const char* slotId, bool visible)
{
    Base::PyGILStateLocker lock;
    try {
        if (m_panel.isNull() || m_panel.isNone() || !m_panel.hasAttr(std::string("set_slot_visible"))) {
            return;
        }
        Py::Callable method(m_panel.getAttr(std::string("set_slot_visible")));
        Py::Tuple args(2);
        args.setItem(0, Py::String(slotId));
        args.setItem(1, Py::Boolean(visible));
        method.apply(args);
    }
    catch (Py::Exception&) {
        Base::PyException e;
        e.reportException();
    }
}

#include "moc_ReferenceSelectionWidget.cpp"
