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


#include <QAction>
#include <QMessageBox>
#include <limits>
#include <sstream>


#include <App/Document.h>
#include <Gui/Command.h>
#include <Gui/QuantitySpinBox.h>
#include <Gui/Selection/SelectionObject.h>
#include <Mod/Fem/App/FemConstraintTemperature.h>
#include <Mod/Part/App/PartFeature.h>

#include "TaskFemConstraintTemperature.h"
#include "ui_TaskFemConstraintTemperature.h"


using namespace FemGui;
using namespace Gui;

/* TRANSLATOR FemGui::TaskFemConstraintTemperature */

TaskFemConstraintTemperature::TaskFemConstraintTemperature(
    ViewProviderFemConstraintTemperature* ConstraintView,
    QWidget* parent
)
    : TaskFemConstraint(ConstraintView, parent, "FEM_ConstraintTemperature")
    , ui(new Ui_TaskFemConstraintTemperature)
{
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
        addReferenceSelection({spec}, proxy);
    }

    // Get the feature data
    Fem::ConstraintTemperature* pcConstraint = ConstraintView->getObject<Fem::ConstraintTemperature>();


    // Fill data into dialog elements
    ui->qsb_temperature->setMinimum(0);
    ui->qsb_temperature->setMaximum(std::numeric_limits<float>::max());
    ui->qsb_cflux->setMinimum(-std::numeric_limits<float>::max());
    ui->qsb_cflux->setMaximum(std::numeric_limits<float>::max());

    App::PropertyEnumeration* constrType = &pcConstraint->ConstraintType;
    QStringList qTypeList;
    for (auto item : constrType->getEnumVector()) {
        qTypeList << QString::fromUtf8(item.c_str());
    }

    ui->cb_constr_type->addItems(qTypeList);
    ui->cb_constr_type->setCurrentIndex(constrType->getValue());
    onConstrTypeChanged(constrType->getValue());

    ui->qsb_temperature->setValue(pcConstraint->Temperature.getQuantityValue());
    ui->qsb_temperature->bind(pcConstraint->Temperature);
    ui->qsb_temperature->setUnit(pcConstraint->Temperature.getUnit());

    ui->qsb_cflux->setValue(pcConstraint->ConcentratedHeatFlux.getQuantityValue());
    ui->qsb_cflux->bind(pcConstraint->ConcentratedHeatFlux);
    ui->qsb_cflux->setUnit(pcConstraint->ConcentratedHeatFlux.getUnit());


    connect(
        ui->cb_constr_type,
        qOverload<int>(&QComboBox::activated),
        this,
        &TaskFemConstraintTemperature::onConstrTypeChanged
    );
    connect(
        ui->qsb_temperature,
        qOverload<double>(&Gui::QuantitySpinBox::valueChanged),
        this,
        &TaskFemConstraintTemperature::onTempChanged
    );
    connect(
        ui->qsb_cflux,
        qOverload<double>(&Gui::QuantitySpinBox::valueChanged),
        this,
        &TaskFemConstraintTemperature::onCFluxChanged
    );
}

TaskFemConstraintTemperature::~TaskFemConstraintTemperature() = default;


void TaskFemConstraintTemperature::onTempChanged(double)
{
    std::string name = ConstraintView->getObject()->getNameInDocument();
    Gui::Command::doCommand(
        Gui::Command::Doc,
        "App.ActiveDocument.%s.Temperature = \"%s\"",
        name.c_str(),
        get_temperature().c_str()
    );
}

void TaskFemConstraintTemperature::onCFluxChanged(double)
{
    std::string name = ConstraintView->getObject()->getNameInDocument();
    Gui::Command::doCommand(
        Gui::Command::Doc,
        "App.ActiveDocument.%s.ConcentratedHeatFlux = \"%s\"",
        name.c_str(),
        get_cflux().c_str()
    );
}

void TaskFemConstraintTemperature::onConstrTypeChanged(int item)
{
    auto obj = ConstraintView->getObject<Fem::ConstraintTemperature>();
    obj->ConstraintType.setValue(item);
    const char* type = obj->ConstraintType.getValueAsString();
    if (strcmp(type, "Temperature") == 0) {
        ui->qsb_temperature->setVisible(true);
        ui->qsb_cflux->setVisible(false);
        ui->lbl_temperature->setVisible(true);
        ui->lbl_cflux->setVisible(false);
    }
    else if (strcmp(type, "Flux") == 0) {
        ui->qsb_cflux->setVisible(true);
        ui->qsb_temperature->setVisible(false);
        ui->lbl_cflux->setVisible(true);
        ui->lbl_temperature->setVisible(false);
    }
}


std::string TaskFemConstraintTemperature::get_temperature() const
{
    return ui->qsb_temperature->value().getSafeUserString();
}

std::string TaskFemConstraintTemperature::get_cflux() const
{
    return ui->qsb_cflux->value().getSafeUserString();
}

std::string TaskFemConstraintTemperature::get_constraint_type() const
{
    return ui->cb_constr_type->currentText().toStdString();
}

void TaskFemConstraintTemperature::changeEvent(QEvent*)
{
    //    TaskBox::changeEvent(e);
    //    if (e->type() == QEvent::LanguageChange) {
    //        ui->if_pressure->blockSignals(true);
    //        ui->retranslateUi(proxy);
    //        ui->if_pressure->blockSignals(false);
    //    }
}


//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgFemConstraintTemperature::TaskDlgFemConstraintTemperature(
    ViewProviderFemConstraintTemperature* ConstraintView
)
{
    this->ConstraintView = ConstraintView;
    assert(ConstraintView);
    this->parameter = new TaskFemConstraintTemperature(ConstraintView);

    Content.push_back(parameter);
}

//==== calls from the TaskView ===============================================================

bool TaskDlgFemConstraintTemperature::accept()
{
    std::string name = ConstraintView->getObject()->getNameInDocument();
    const TaskFemConstraintTemperature* parameterTemperature
        = static_cast<const TaskFemConstraintTemperature*>(parameter);

    auto type = parameterTemperature->get_constraint_type();

    try {
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.ConstraintType = \"%s\"",
            name.c_str(),
            parameterTemperature->get_constraint_type().c_str()
        );
        if (type == "Temperature") {
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "App.ActiveDocument.%s.Temperature = \"%s\"",
                name.c_str(),
                parameterTemperature->get_temperature().c_str()
            );
        }
        else if (type == "Flux") {
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "App.ActiveDocument.%s.ConcentratedHeatFlux = \"%s\"",
                name.c_str(),
                parameterTemperature->get_cflux().c_str()
            );
        }
    }
    catch (const Base::Exception& e) {
        QMessageBox::warning(parameter, tr("Input Error"), QString::fromLatin1(e.what()));
        return false;
    }

    return TaskDlgFemConstraint::accept();
}

#include "moc_TaskFemConstraintTemperature.cpp"
