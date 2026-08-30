// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2013 Jan Rheinländer                                    *
 *                                   <jrheinlaender@users.sourceforge.net> *
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


#include <QBoxLayout>
#include <QListWidget>
#include <QMessageBox>


#include <App/Document.h>
#include <App/DocumentObject.h>
#include <Base/Exception.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/Document.h>
#include <Gui/Selection/Selection.h>
#include <Mod/Fem/App/FemConstraint.h>

#include "TaskFemConstraint.h"


using namespace FemGui;
using namespace Gui;

/* TRANSLATOR FemGui::TaskFemConstraint */

TaskFemConstraint::TaskFemConstraint(
    ViewProviderFemConstraint* ConstraintView,
    QWidget* parent,
    const char* pixmapname
)
    : TaskBox(Gui::BitmapFactory().pixmap(pixmapname), tr("Analysis Feature Properties"), true, parent)
    , proxy(nullptr)
    , ConstraintView(ConstraintView)
{}

TaskFemConstraint::~TaskFemConstraint()
{
    if (m_references) {
        m_references->finish();
        m_references = nullptr;
    }
}

void TaskFemConstraint::addReferenceSelection(const std::vector<ReferenceSlotSpec>& specs, QWidget* host)
{
    if (ConstraintView.expired()) {
        return;
    }
    // Before the new widget becomes a child of the host, so that hiding by
    // name can only reach what the .ui file brought.
    if (host) {
        hideLegacyReferenceWidgets(host);
    }
    QWidget* parent = host ? host : this;
    m_references = new ReferenceSelectionWidget(ConstraintView->getObject(), specs, parent);
    if (host) {
        if (auto* layout = qobject_cast<QBoxLayout*>(host->layout())) {
            layout->insertWidget(0, m_references);
        }
        else {
            this->groupLayout()->addWidget(m_references);
        }
    }
    else {
        this->groupLayout()->addWidget(m_references);
    }
}

const std::string TaskFemConstraint::getScale() const
{
    Fem::Constraint* pcConstraint = ConstraintView->getObject<Fem::Constraint>();

    return std::to_string(pcConstraint->Scale.getValue());
}

//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

void TaskDlgFemConstraint::open()
{
    if (!ConstraintView->getDocument()->hasPendingCommand()) {
        const auto typeName = ConstraintView->getObject()->getTypeId().getName();
        ConstraintView->getDocument()->openCommand(std::string {typeName}.c_str());
        ConstraintView->setVisible(true);
    }
}

bool TaskDlgFemConstraint::accept()
{
    std::string name = ConstraintView->getObject()->getNameInDocument();

    try {
        // The slots write the property live, so accept() only has to check
        // that something was picked.
        auto* constraint = ConstraintView->getObject<Fem::Constraint>();
        if (!constraint || constraint->References.getValues().empty()) {
            QMessageBox::warning(
                parameter,
                tr("Input Error"),
                tr("You must specify at least one reference")
            );
            return false;
        }

        std::string scale = parameter->getScale();
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Scale = %s",
            name.c_str(),
            scale.c_str()
        );
        Gui::Command::doCommand(Gui::Command::Doc, "App.ActiveDocument.recompute()");
        if (!ConstraintView->getObject()->isValid()) {
            throw Base::RuntimeError(ConstraintView->getObject()->getStatusString());
        }
        Gui::Command::doCommand(Gui::Command::Gui, "Gui.activeDocument().resetEdit()");
        ConstraintView->getDocument()->commitCommand();
    }
    catch (const Base::Exception& e) {
        ConstraintView->getDocument()->abortCommand();
        QMessageBox::warning(parameter, tr("Input Error"), QString::fromLatin1(e.what()));
        return false;
    }

    return true;
}

bool TaskDlgFemConstraint::reject()
{
    ConstraintView->getDocument()->abortCommand();
    Gui::Command::doCommand(Gui::Command::Gui, "Gui.activeDocument().resetEdit()");
    Gui::Command::updateActive();

    return true;
}

#include "moc_TaskFemConstraint.cpp"
