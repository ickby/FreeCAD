// SPDX-License-Identifier: LGPL-2.1-or-later

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


#include <Gui/Command.h>
#include <Gui/Selection/SelectionObject.h>
#include <Mod/Fem/App/FemConstraintHeatflux.h>
#include <Mod/Part/App/PartFeature.h>

#include "TaskFemConstraintHeatflux.h"
#include "ui_TaskFemConstraintHeatflux.h"


using namespace FemGui;
using namespace Gui;

/* TRANSLATOR FemGui::TaskFemConstraintHeatflux */

TaskFemConstraintHeatflux::TaskFemConstraintHeatflux(
    ViewProviderFemConstraintHeatflux* ConstraintView,
    QWidget* parent
)
    : TaskFemConstraint(ConstraintView, parent, "FEM_ConstraintHeatflux")
    , ui(new Ui_TaskFemConstraintHeatflux)
{
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    connect(
        ui->cb_constr_type,
        qOverload<int>(&QComboBox::activated),
        this,
        &TaskFemConstraintHeatflux::onConstrTypeChanged
    );
    connect(
        ui->qsb_heat_flux,
        qOverload<double>(&QuantitySpinBox::valueChanged),
        this,
        &TaskFemConstraintHeatflux::onHeatFluxChanged
    );
    connect(
        ui->qsb_ambienttemp_conv,
        qOverload<double>(&QuantitySpinBox::valueChanged),
        this,
        &TaskFemConstraintHeatflux::onAmbientTempChanged
    );
    connect(
        ui->qsb_film_coef,
        qOverload<double>(&QuantitySpinBox::valueChanged),
        this,
        &TaskFemConstraintHeatflux::onFilmCoefChanged
    );
    connect(
        ui->dsb_emissivity,
        qOverload<double>(&DoubleSpinBox::valueChanged),
        this,
        &TaskFemConstraintHeatflux::onEmissivityChanged
    );
    connect(
        ui->qsb_ambienttemp_rad,
        qOverload<double>(&QuantitySpinBox::valueChanged),
        this,
        &TaskFemConstraintHeatflux::onAmbientTempChanged
    );

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

    // Temporarily prevent unnecessary feature recomputes
    ui->qsb_ambienttemp_conv->blockSignals(true);
    // ui->if_facetemp->blockSignals(true);
    ui->qsb_film_coef->blockSignals(true);
    ui->dsb_emissivity->blockSignals(true);
    ui->qsb_ambienttemp_rad->blockSignals(true);
    ui->qsb_heat_flux->blockSignals(true);

    // Get the feature data
    auto pcConstraint = ConstraintView->getObject<Fem::ConstraintHeatflux>();

    // Fill data into dialog elements
    App::PropertyEnumeration* constrType = &pcConstraint->ConstraintType;
    QStringList qTypeList;
    for (auto item : constrType->getEnumVector()) {
        qTypeList << QString::fromUtf8(item.c_str());
    }
    ui->cb_constr_type->addItems(qTypeList);
    ui->cb_constr_type->setCurrentIndex(constrType->getValue());
    ui->sw_heatflux->setCurrentIndex(constrType->getValue());

    ui->qsb_ambienttemp_conv->setMinimum(0);
    ui->qsb_ambienttemp_conv->setMaximum(std::numeric_limits<float>::max());

    ui->qsb_film_coef->setMinimum(0);
    ui->qsb_film_coef->setMaximum(std::numeric_limits<float>::max());

    ui->dsb_emissivity->setMinimum(0);
    ui->dsb_emissivity->setMaximum(std::numeric_limits<float>::max());

    ui->qsb_ambienttemp_rad->setMinimum(0);
    ui->qsb_ambienttemp_rad->setMaximum(std::numeric_limits<float>::max());

    ui->qsb_ambienttemp_conv->setValue(pcConstraint->AmbientTemp.getQuantityValue());
    ui->qsb_film_coef->setValue(pcConstraint->FilmCoef.getQuantityValue());

    ui->qsb_ambienttemp_rad->setValue(pcConstraint->AmbientTemp.getQuantityValue());
    ui->dsb_emissivity->setValue(pcConstraint->Emissivity.getValue());

    ui->qsb_heat_flux->setValue(pcConstraint->DistributedHeatFlux.getQuantityValue());


    ui->qsb_ambienttemp_conv->blockSignals(false);
    // ui->if_facetemp->blockSignals(false);
    ui->qsb_film_coef->blockSignals(false);
    ui->dsb_emissivity->blockSignals(false);
    ui->qsb_ambienttemp_rad->blockSignals(false);
    ui->qsb_heat_flux->blockSignals(false);

    ui->qsb_film_coef->bind(pcConstraint->FilmCoef);
    ui->qsb_ambienttemp_conv->bind(pcConstraint->AmbientTemp);
    ui->qsb_ambienttemp_rad->bind(pcConstraint->AmbientTemp);
    ui->dsb_emissivity->bind(pcConstraint->Emissivity);
    ui->qsb_heat_flux->bind(pcConstraint->DistributedHeatFlux);
}

TaskFemConstraintHeatflux::~TaskFemConstraintHeatflux() = default;


void TaskFemConstraintHeatflux::onAmbientTempChanged(double val)
{
    Fem::ConstraintHeatflux* pcConstraint = ConstraintView->getObject<Fem::ConstraintHeatflux>();
    pcConstraint->AmbientTemp.setValue(val);
}

void TaskFemConstraintHeatflux::onFilmCoefChanged(double val)
{
    Fem::ConstraintHeatflux* pcConstraint = ConstraintView->getObject<Fem::ConstraintHeatflux>();
    pcConstraint->FilmCoef.setValue(val);
}

void TaskFemConstraintHeatflux::onEmissivityChanged(double val)
{
    Fem::ConstraintHeatflux* pcConstraint = ConstraintView->getObject<Fem::ConstraintHeatflux>();
    pcConstraint->Emissivity.setValue(val);
}

void TaskFemConstraintHeatflux::onHeatFluxChanged(double val)
{
    Fem::ConstraintHeatflux* pcConstraint = ConstraintView->getObject<Fem::ConstraintHeatflux>();
    pcConstraint->DistributedHeatFlux.setValue(val);
}

void TaskFemConstraintHeatflux::Conv()
{
    Fem::ConstraintHeatflux* pcConstraint = ConstraintView->getObject<Fem::ConstraintHeatflux>();
    std::string name = ConstraintView->getObject()->getNameInDocument();
    Gui::Command::doCommand(
        Gui::Command::Doc,
        "App.ActiveDocument.%s.ConstraintType = \"%s\"",
        name.c_str(),
        getConstraintType().c_str()
    );
    ui->qsb_ambienttemp_conv->setValue(pcConstraint->AmbientTemp.getQuantityValue());
    ui->qsb_film_coef->setValue(pcConstraint->FilmCoef.getQuantityValue());
    ui->sw_heatflux->setCurrentIndex(1);
}

void TaskFemConstraintHeatflux::Rad()
{
    Fem::ConstraintHeatflux* pcConstraint = ConstraintView->getObject<Fem::ConstraintHeatflux>();
    std::string name = ConstraintView->getObject()->getNameInDocument();
    Gui::Command::doCommand(
        Gui::Command::Doc,
        "App.ActiveDocument.%s.ConstraintType = \"%s\"",
        name.c_str(),
        getConstraintType().c_str()
    );
    ui->qsb_ambienttemp_rad->setValue(pcConstraint->AmbientTemp.getQuantityValue());
    ui->dsb_emissivity->setValue(pcConstraint->Emissivity.getValue());
    ui->sw_heatflux->setCurrentIndex(2);
}

void TaskFemConstraintHeatflux::Flux()
{
    Fem::ConstraintHeatflux* pcConstraint = ConstraintView->getObject<Fem::ConstraintHeatflux>();
    std::string name = ConstraintView->getObject()->getNameInDocument();
    Gui::Command::doCommand(
        Gui::Command::Doc,
        "App.ActiveDocument.%s.ConstraintType = \"%s\"",
        name.c_str(),
        getConstraintType().c_str()
    );
    ui->qsb_heat_flux->setValue(pcConstraint->DistributedHeatFlux.getQuantityValue());
    ui->sw_heatflux->setCurrentIndex(0);
}

void TaskFemConstraintHeatflux::onConstrTypeChanged(int item)
{
    auto obj = ConstraintView->getObject<Fem::ConstraintHeatflux>();
    obj->ConstraintType.setValue(item);
    const char* type = obj->ConstraintType.getValueAsString();
    if (strcmp(type, "Flux") == 0) {
        this->Flux();
    }
    else if (strcmp(type, "Convection") == 0) {
        this->Conv();
    }
    else if (strcmp(type, "Radiation") == 0) {
        this->Rad();
    }
}


std::string TaskFemConstraintHeatflux::getAmbientTemp() const
{
    std::string type = this->getConstraintType();
    if (type == "Convection") {
        return ui->qsb_ambienttemp_conv->value().getSafeUserString();
    }
    else if (type == "Convection") {
        return ui->qsb_ambienttemp_rad->value().getSafeUserString();
    }
    else {
        auto obj = ConstraintView->getObject<Fem::ConstraintHeatflux>();
        return obj->AmbientTemp.getQuantityValue().getSafeUserString();
    }
}

std::string TaskFemConstraintHeatflux::getFilmCoef() const
{
    return ui->qsb_film_coef->value().getSafeUserString();
}

std::string TaskFemConstraintHeatflux::getDFlux() const
{
    return ui->qsb_heat_flux->value().getSafeUserString();
}

double TaskFemConstraintHeatflux::getEmissivity() const
{
    return ui->dsb_emissivity->value();
}

std::string TaskFemConstraintHeatflux::getConstraintType() const
{
    return ui->cb_constr_type->currentText().toStdString();
}

void TaskFemConstraintHeatflux::changeEvent(QEvent* e)
{
    TaskBox::changeEvent(e);
    if (e->type() == QEvent::LanguageChange) {
        ui->qsb_ambienttemp_conv->blockSignals(true);
        ui->qsb_film_coef->blockSignals(true);
        ui->dsb_emissivity->blockSignals(true);
        ui->qsb_ambienttemp_rad->blockSignals(true);
        ui->qsb_heat_flux->blockSignals(true);

        ui->retranslateUi(proxy);

        ui->qsb_ambienttemp_conv->blockSignals(false);
        ui->qsb_film_coef->blockSignals(false);
        ui->dsb_emissivity->blockSignals(false);
        ui->qsb_ambienttemp_rad->blockSignals(false);
        ui->qsb_heat_flux->blockSignals(false);
    }
}


//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgFemConstraintHeatflux::TaskDlgFemConstraintHeatflux(
    ViewProviderFemConstraintHeatflux* ConstraintView
)
{
    this->ConstraintView = ConstraintView;
    assert(ConstraintView);
    this->parameter = new TaskFemConstraintHeatflux(ConstraintView);

    Content.push_back(parameter);
}

//==== calls from the TaskView ===============================================================

bool TaskDlgFemConstraintHeatflux::accept()
{
    std::string name = ConstraintView->getObject()->getNameInDocument();
    const TaskFemConstraintHeatflux* parameterHeatflux
        = static_cast<const TaskFemConstraintHeatflux*>(parameter);

    try {
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.AmbientTemp = \"%s\"",
            name.c_str(),
            parameterHeatflux->getAmbientTemp().c_str()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.FilmCoef = \"%s\"",
            name.c_str(),
            parameterHeatflux->getFilmCoef().c_str()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Emissivity = %f",
            name.c_str(),
            parameterHeatflux->getEmissivity()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.DistributedHeatFlux = \"%s\"",
            name.c_str(),
            parameterHeatflux->getDFlux().c_str()
        );
    }
    catch (const Base::Exception& e) {
        QMessageBox::warning(parameter, tr("Input Error"), QString::fromLatin1(e.what()));
        return false;
    }

    return TaskDlgFemConstraint::accept();
}

#include "moc_TaskFemConstraintHeatflux.cpp"
