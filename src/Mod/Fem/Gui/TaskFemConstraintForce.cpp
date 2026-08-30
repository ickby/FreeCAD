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


#include <QAction>
#include <QMessageBox>
#include <TopoDS.hxx>
#include <limits>
#include <sstream>


#include <App/DocumentObject.h>
#include <App/Datums.h>
#include <Gui/Command.h>
#include <Gui/Selection/SelectionObject.h>
#include <Gui/ViewProvider.h>
#include <Mod/Fem/App/FemConstraintForce.h>
#include <Mod/Fem/App/FemTools.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/DatumFeature.h>

#include "TaskFemConstraintForce.h"
#include "ui_TaskFemConstraintForce.h"


using namespace FemGui;
using namespace Gui;

/* TRANSLATOR FemGui::TaskFemConstraintForce */

TaskFemConstraintForce::TaskFemConstraintForce(
    ViewProviderFemConstraintForce* ConstraintView,
    QWidget* parent
)
    : TaskFemConstraint(ConstraintView, parent, "FEM_ConstraintForce")
    , ui(new Ui_TaskFemConstraintForce)
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    this->groupLayout()->addWidget(proxy);
    {
        ReferenceSlotSpec spec;
        spec.property = "References";
        spec.title = tr("References").toStdString();
        spec.types = {"Vertex", "Edge", "Face"};
        spec.homogeneous = false;
        spec.armed = true;
        ReferenceSlotSpec direction;
        direction.property = "Direction";
        direction.title = tr("Direction").toStdString();
        direction.types = {"Edge", "Face"};
        direction.maxCount = 1;
        direction.homogeneous = false;
        direction.id = "Direction";
        addReferenceSelection({spec, direction}, proxy);
    }

    // Get the feature data
    Fem::ConstraintForce* pcConstraint = ConstraintView->getObject<Fem::ConstraintForce>();
    auto force = pcConstraint->Force.getQuantityValue();

    // Fill data into dialog elements
    ui->spinForce->setUnit(pcConstraint->Force.getUnit());
    ui->spinForce->setMinimum(0);
    ui->spinForce->setMaximum(std::numeric_limits<float>::max());
    ui->spinForce->setValue(force);
    ui->checkReverse->setChecked(pcConstraint->Reversed.getValue());

    connect(ui->checkReverse, &QCheckBox::toggled, this, &TaskFemConstraintForce::onCheckReverse);

    ui->spinForce->bind(pcConstraint->Force);
}


void TaskFemConstraintForce::onCheckReverse(const bool pressed)
{
    Fem::ConstraintForce* pcConstraint = ConstraintView->getObject<Fem::ConstraintForce>();
    pcConstraint->Reversed.setValue(pressed);
}

const std::string TaskFemConstraintForce::getForce() const
{
    return ui->spinForce->value().getSafeUserString();
}


bool TaskFemConstraintForce::getReverse() const
{
    return ui->checkReverse->isChecked();
}

TaskFemConstraintForce::~TaskFemConstraintForce() = default;

void TaskFemConstraintForce::changeEvent(QEvent* e)
{
    TaskBox::changeEvent(e);
    if (e->type() == QEvent::LanguageChange) {
        ui->spinForce->blockSignals(true);
        ui->retranslateUi(proxy);
        ui->spinForce->blockSignals(false);
    }
}


//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgFemConstraintForce::TaskDlgFemConstraintForce(ViewProviderFemConstraintForce* ConstraintView)
{
    this->ConstraintView = ConstraintView;
    assert(ConstraintView);
    this->parameter = new TaskFemConstraintForce(ConstraintView);

    Content.push_back(parameter);
}

//==== calls from the TaskView ===============================================================

bool TaskDlgFemConstraintForce::accept()
{
    std::string name = ConstraintView->getObject()->getNameInDocument();
    const TaskFemConstraintForce* parameterForce = static_cast<const TaskFemConstraintForce*>(
        parameter
    );

    try {
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Force = \"%s\"",
            name.c_str(),
            parameterForce->getForce().c_str()
        );

        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Reversed = %s",
            name.c_str(),
            parameterForce->getReverse() ? "True" : "False"
        );
    }
    catch (const Base::Exception& e) {
        QMessageBox::warning(parameter, tr("Input Error"), QString::fromLatin1(e.what()));
        return false;
    }

    return TaskDlgFemConstraint::accept();
}

#include "moc_TaskFemConstraintForce.cpp"
