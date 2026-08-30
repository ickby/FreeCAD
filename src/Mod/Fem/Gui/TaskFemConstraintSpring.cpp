// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2021 FreeCAD Developers                                 *
 *   Author: Preslav Aleksandrov <preslav.aleksandrov@protonmail>          *
 *   Based on Force constraint by Jan Rheinländer                          *
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


#include <QAction>
#include <QMessageBox>
#include <limits>
#include <sstream>


#include <Gui/Command.h>
#include <Gui/Selection/SelectionObject.h>
#include <Mod/Fem/App/FemConstraintSpring.h>
#include <Mod/Part/App/PartFeature.h>

#include "TaskFemConstraintSpring.h"
#include "ui_TaskFemConstraintSpring.h"


using namespace FemGui;
using namespace Gui;

/* TRANSLATOR FemGui::TaskFemConstraintSpring */

TaskFemConstraintSpring::TaskFemConstraintSpring(
    ViewProviderFemConstraintSpring* ConstraintView,
    QWidget* parent
)
    : TaskFemConstraint(ConstraintView, parent, "FEM_ConstraintSpring")
    , ui(new Ui_TaskFemConstraintSpring)
{
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);


    this->groupLayout()->addWidget(proxy);
    {
        ReferenceSlotSpec spec;
        spec.property = "References";
        spec.title = tr("References").toStdString();
        spec.types = {"Face"};
        spec.homogeneous = false;
        spec.armed = true;
        addReferenceSelection({spec}, proxy);
    }

    /* Note: */
    // Get the feature data
    Fem::ConstraintSpring* pcConstraint = ConstraintView->getObject<Fem::ConstraintSpring>();


    // Fill data into dialog elements
    ui->qsb_norm->setUnit(pcConstraint->NormalStiffness.getUnit());
    ui->qsb_norm->setMaximum(std::numeric_limits<float>::max());
    ui->qsb_norm->setValue(pcConstraint->NormalStiffness.getQuantityValue());

    ui->qsb_tan->setUnit(pcConstraint->TangentialStiffness.getUnit());
    ui->qsb_tan->setMaximum(std::numeric_limits<float>::max());
    ui->qsb_tan->setValue(pcConstraint->TangentialStiffness.getQuantityValue());

    ui->cb_elmer_stiffness->clear();
    auto stiffnesses = pcConstraint->ElmerStiffness.getEnumVector();
    QStringList stiffnessesList;
    for (auto item : stiffnesses) {
        stiffnessesList << QLatin1String(item.c_str());
    }
    ui->cb_elmer_stiffness->addItems(stiffnessesList);
    ui->cb_elmer_stiffness->setCurrentIndex(pcConstraint->ElmerStiffness.getValue());


    ui->qsb_norm->bind(pcConstraint->NormalStiffness);
    ui->qsb_tan->bind(pcConstraint->TangentialStiffness);
}

TaskFemConstraintSpring::~TaskFemConstraintSpring() = default;


std::string TaskFemConstraintSpring::getNormalStiffness() const
{
    return ui->qsb_norm->value().getSafeUserString();
}

std::string TaskFemConstraintSpring::getTangentialStiffness() const
{
    return ui->qsb_tan->value().getSafeUserString();
}

std::string TaskFemConstraintSpring::getElmerStiffness() const
{
    return ui->cb_elmer_stiffness->currentText().toStdString();
}

void TaskFemConstraintSpring::changeEvent(QEvent*)
{}


//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgFemConstraintSpring::TaskDlgFemConstraintSpring(ViewProviderFemConstraintSpring* ConstraintView)
{
    this->ConstraintView = ConstraintView;
    assert(ConstraintView);
    this->parameter = new TaskFemConstraintSpring(ConstraintView);

    Content.push_back(parameter);
}

//==== calls from the TaskView ===============================================================

bool TaskDlgFemConstraintSpring::accept()
{
    /* Note: */
    std::string name = ConstraintView->getObject()->getNameInDocument();
    const TaskFemConstraintSpring* parameterStiffness = static_cast<const TaskFemConstraintSpring*>(
        parameter
    );
    // const TaskFemConstraintSpring* parameterTan = static_cast<const
    // TaskFemConstraintSpring>(parameter);

    try {
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.NormalStiffness = \"%s\"",
            name.c_str(),
            parameterStiffness->getNormalStiffness().c_str()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.TangentialStiffness = \"%s\"",
            name.c_str(),
            parameterStiffness->getTangentialStiffness().c_str()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.ElmerStiffness = '%s'",
            name.c_str(),
            parameterStiffness->getElmerStiffness().c_str()
        );
    }
    catch (const Base::Exception& e) {
        QMessageBox::warning(parameter, tr("Input Error"), QString::fromLatin1(e.what()));
        return false;
    }
    /* */
    return TaskDlgFemConstraint::accept();
}

#include "moc_TaskFemConstraintSpring.cpp"
