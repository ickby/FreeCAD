/***************************************************************************
 *   Copyright (c) 2015 FreeCAD Developers                                 *
 *   Authors: Michael Hindley <hindlemp@eskom.co.za>                       *
 *            Ruan Olwagen <olwager@eskom.co.za>                           *
 *            Oswald van Ginkel <vginkeo@eskom.co.za>                      *
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

#include <limits>
#include <sstream>

#include <QMessageBox>

#include "Mod/Fem/App/FemConstraintContact.h"
#include <Gui/Command.h>
#include <Gui/Selection/SelectionObject.h>
#include <Mod/Part/App/PartFeature.h>

#include "TaskFemConstraintContact.h"
#include "ui_TaskFemConstraintContact.h"


using namespace FemGui;
using namespace Gui;

/* TRANSLATOR FemGui::TaskFemConstraintContact */

TaskFemConstraintContact::TaskFemConstraintContact(
    ViewProviderFemConstraintContact* ConstraintView,
    QWidget* parent
)
    : TaskFemConstraint(ConstraintView, parent, "FEM_ConstraintContact")
    , ui(new Ui_TaskFemConstraintContact)
{
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    this->groupLayout()->addWidget(proxy);
    {
        ReferenceSlotSpec spec;
        spec.property = "References";
        spec.title = tr("Slave").toStdString();
        spec.types = {"Edge", "Face"};
        spec.maxCount = 1;
        spec.homogeneous = false;
        spec.armed = true;
        spec.role = "slave";
        spec.id = "Slave";
        ReferenceSlotSpec master;
        master.property = "References";
        master.title = tr("Master").toStdString();
        master.types = {"Edge", "Face"};
        master.maxCount = 1;
        master.homogeneous = false;
        master.role = "master";
        master.id = "Master";
        addReferenceSelection({spec, master}, proxy);
    }

    /* Note: */
    // Get the feature data
    Fem::ConstraintContact* pcConstraint = ConstraintView->getObject<Fem::ConstraintContact>();

    bool friction = pcConstraint->Friction.getValue();
    auto revMaster = pcConstraint->ReversedMaster.getValues();
    auto revSlave = pcConstraint->ReversedSlave.getValues();

    // Fill data into dialog elements
    ui->spbSlope->setUnit(pcConstraint->Slope.getUnit());
    ui->spbSlope->setMinimum(0);
    ui->spbSlope->setMaximum(std::numeric_limits<float>::max());
    ui->spbSlope->setValue(pcConstraint->Slope.getQuantityValue());
    ui->spbSlope->bind(pcConstraint->Slope);

    ui->spbAdjust->setUnit(pcConstraint->Adjust.getUnit());
    ui->spbAdjust->setMinimum(0);
    ui->spbAdjust->setMaximum(std::numeric_limits<float>::max());
    ui->spbAdjust->setValue(pcConstraint->Adjust.getQuantityValue());
    ui->spbAdjust->bind(pcConstraint->Adjust);

    ui->ckbFriction->setChecked(friction);

    ui->ckbRevMaster->setChecked(revMaster.empty() ? false : revMaster.at(0));
    ui->ckbRevSlave->setChecked(revSlave.empty() ? false : revSlave.at(0));

    ui->spbFrictionCoeff->setMinimum(0);
    ui->spbFrictionCoeff->setMaximum(std::numeric_limits<float>::max());
    ui->spbFrictionCoeff->setValue(pcConstraint->FrictionCoefficient.getValue());
    ui->spbFrictionCoeff->setEnabled(friction);
    ui->spbFrictionCoeff->bind(pcConstraint->FrictionCoefficient);

    ui->spbStickSlope->setUnit(pcConstraint->StickSlope.getUnit());
    ui->spbStickSlope->setMinimum(0);
    ui->spbStickSlope->setMaximum(std::numeric_limits<float>::max());
    ui->spbStickSlope->setValue(pcConstraint->StickSlope.getQuantityValue());
    ui->spbStickSlope->setEnabled(friction);
    ui->spbStickSlope->bind(pcConstraint->StickSlope);
    /* */

    connect(ui->ckbFriction, &QCheckBox::toggled, this, &TaskFemConstraintContact::onFrictionChanged);
}

TaskFemConstraintContact::~TaskFemConstraintContact() = default;


void TaskFemConstraintContact::onFrictionChanged(bool state)
{
    ui->spbFrictionCoeff->setEnabled(state);
    ui->spbStickSlope->setEnabled(state);
}


const std::string TaskFemConstraintContact::getSlope() const
{
    return ui->spbSlope->value().getSafeUserString();
}

const std::string TaskFemConstraintContact::getAdjust() const
{
    return ui->spbAdjust->value().getSafeUserString();
}

bool TaskFemConstraintContact::getFriction() const
{
    return ui->ckbFriction->isChecked();
}

double TaskFemConstraintContact::getFrictionCoeff() const
{
    return ui->spbFrictionCoeff->value();
}

const std::string TaskFemConstraintContact::getStickSlope() const
{
    return ui->spbStickSlope->value().getSafeUserString();
}

const std::vector<bool> TaskFemConstraintContact::getRevMaster() const
{
    auto* constraint = ConstraintView->getObject<Fem::ConstraintContact>();
    const std::size_t n = constraint ? constraint->References.getValues().size() : 0;
    const std::size_t count = n > 0 ? 1 : 0;
    return std::vector<bool>(count, ui->ckbRevMaster->isChecked());
}

const std::vector<bool> TaskFemConstraintContact::getRevSlave() const
{
    auto* constraint = ConstraintView->getObject<Fem::ConstraintContact>();
    const std::size_t n = constraint ? constraint->References.getValues().size() : 0;
    const std::size_t count = n >= 2 ? n - 1 : 0;
    return std::vector<bool>(count, ui->ckbRevSlave->isChecked());
}


void TaskFemConstraintContact::changeEvent(QEvent*)
{}

//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgFemConstraintContact::TaskDlgFemConstraintContact(
    ViewProviderFemConstraintContact* ConstraintView
)
{
    this->ConstraintView = ConstraintView;
    assert(ConstraintView);
    this->parameter = new TaskFemConstraintContact(ConstraintView);

    Content.push_back(parameter);
}

//==== calls from the TaskView ===============================================================

bool TaskDlgFemConstraintContact::accept()
{
    /* Note: */
    std::string name = ConstraintView->getObject()->getNameInDocument();
    const TaskFemConstraintContact* parameterContact = static_cast<const TaskFemConstraintContact*>(
        parameter
    );

    try {
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Slope = \"%s\"",
            name.c_str(),
            parameterContact->getSlope().c_str()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Adjust = \"%s\"",
            name.c_str(),
            parameterContact->getAdjust().c_str()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Friction = %s",
            name.c_str(),
            parameterContact->getFriction() ? "True" : "False"
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.FrictionCoefficient = %f",
            name.c_str(),
            parameterContact->getFrictionCoeff()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.StickSlope = \"%s\"",
            name.c_str(),
            parameterContact->getStickSlope().c_str()
        );

        auto rev_master = parameterContact->getRevMaster();
        std::string rev_master_str {""};
        for (bool b : rev_master) {
            rev_master_str.append(b ? "True," : "False,");
        }
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.ReversedMaster = [%s]",
            name.c_str(),
            rev_master_str.c_str()
        );

        auto rev_slave = parameterContact->getRevSlave();
        std::string rev_slave_str {""};
        for (bool b : rev_slave) {
            rev_slave_str.append(b ? "True," : "False,");
        }
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.ReversedSlave = [%s]",
            name.c_str(),
            rev_slave_str.c_str()
        );
    }
    catch (const Base::Exception& e) {
        QMessageBox::warning(parameter, tr("Input Error"), QString::fromLatin1(e.what()));
        return false;
    }
    /* */
    return TaskDlgFemConstraint::accept();
}

#include "moc_TaskFemConstraintContact.cpp"
