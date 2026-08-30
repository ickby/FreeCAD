// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2015 FreeCAD Developers                                 *
 *   Author: Przemo Firszt <przemo@firszt.eu>                              *
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
#include <Mod/Fem/App/FemConstraintPressure.h>
#include <Mod/Part/App/PartFeature.h>

#include "TaskFemConstraintPressure.h"
#include "ui_TaskFemConstraintPressure.h"


using namespace FemGui;
using namespace Gui;

/* TRANSLATOR FemGui::TaskFemConstraintPressure */

TaskFemConstraintPressure::TaskFemConstraintPressure(
    ViewProviderFemConstraintPressure* ConstraintView,
    QWidget* parent
)
    : TaskFemConstraint(ConstraintView, parent, "FEM_ConstraintPressure")
    , ui(new Ui_TaskFemConstraintPressure)
{  // Note change "pressure" in line above to new constraint name
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    this->groupLayout()->addWidget(proxy);
    {
        ReferenceSlotSpec spec;
        spec.property = "References";
        spec.title = tr("References").toStdString();
        spec.types = {"Edge", "Face"};
        spec.homogeneous = false;
        spec.armed = true;
        addReferenceSelection({spec}, proxy);
    }

    // Get the feature data
    Fem::ConstraintPressure* pcConstraint = ConstraintView->getObject<Fem::ConstraintPressure>();


    // Fill data into dialog elements
    ui->if_pressure->setUnit(pcConstraint->Pressure.getUnit());
    ui->if_pressure->setMinimum(0);
    ui->if_pressure->setMaximum(std::numeric_limits<float>::max());
    ui->if_pressure->setValue(pcConstraint->Pressure.getQuantityValue());
    ui->if_pressure->bind(pcConstraint->Pressure);

    bool reversed = pcConstraint->Reversed.getValue();
    ui->checkBoxReverse->setChecked(reversed);


    connect(ui->checkBoxReverse, &QCheckBox::toggled, this, &TaskFemConstraintPressure::onCheckReverse);
}

TaskFemConstraintPressure::~TaskFemConstraintPressure() = default;


void TaskFemConstraintPressure::onCheckReverse(const bool pressed)
{
    Fem::ConstraintPressure* pcConstraint = ConstraintView->getObject<Fem::ConstraintPressure>();
    pcConstraint->Reversed.setValue(pressed);
}


std::string TaskFemConstraintPressure::getPressure() const
{
    return ui->if_pressure->value().getSafeUserString();
}

bool TaskFemConstraintPressure::getReverse() const
{
    return ui->checkBoxReverse->isChecked();
}

void TaskFemConstraintPressure::changeEvent(QEvent*)
{}


//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgFemConstraintPressure::TaskDlgFemConstraintPressure(
    ViewProviderFemConstraintPressure* ConstraintView
)
{
    this->ConstraintView = ConstraintView;
    assert(ConstraintView);
    this->parameter = new TaskFemConstraintPressure(ConstraintView);

    Content.push_back(parameter);
}

//==== calls from the TaskView ===============================================================

bool TaskDlgFemConstraintPressure::accept()
{
    /* Note: */
    std::string name = ConstraintView->getObject()->getNameInDocument();
    const TaskFemConstraintPressure* parameterPressure
        = static_cast<const TaskFemConstraintPressure*>(parameter);

    try {
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Pressure = \"%s\"",
            name.c_str(),
            parameterPressure->getPressure().c_str()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Reversed = %s",
            name.c_str(),
            parameterPressure->getReverse() ? "True" : "False"
        );
    }
    catch (const Base::Exception& e) {
        QMessageBox::warning(parameter, tr("Input Error"), QString::fromLatin1(e.what()));
        return false;
    }
    /* */
    return TaskDlgFemConstraint::accept();
}

#include "moc_TaskFemConstraintPressure.cpp"
