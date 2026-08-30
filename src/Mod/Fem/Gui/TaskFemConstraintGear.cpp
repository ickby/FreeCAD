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

#include <limits>

#include <QMessageBox>
#include <TopoDS.hxx>

#include <App/Document.h>
#include <Gui/Command.h>
#include <Gui/Selection/Selection.h>
#include <Gui/ViewProvider.h>
#include <Mod/Fem/App/FemConstraintGear.h>
#include <Mod/Fem/App/FemTools.h>
#include <Mod/Part/App/PartFeature.h>

#include "TaskFemConstraintGear.h"
#include "ui_TaskFemConstraintBearing.h"


using namespace FemGui;
using namespace Gui;

/* TRANSLATOR FemGui::TaskFemConstraintGear */

TaskFemConstraintGear::TaskFemConstraintGear(
    ViewProviderFemConstraint* ConstraintView,
    QWidget* parent,
    const char* pixmapname
)
    : TaskFemConstraintBearing(ConstraintView, parent, pixmapname)
{
    if (m_references) {
        m_references->setSlotVisible("Direction", true);
    }
    connect(
        ui->spinDiameter,
        qOverload<double>(&QDoubleSpinBox::valueChanged),
        this,
        &TaskFemConstraintGear::onDiameterChanged
    );
    connect(
        ui->spinForce,
        qOverload<double>(&QDoubleSpinBox::valueChanged),
        this,
        &TaskFemConstraintGear::onForceChanged
    );
    connect(
        ui->spinForceAngle,
        qOverload<double>(&QDoubleSpinBox::valueChanged),
        this,
        &TaskFemConstraintGear::onForceAngleChanged
    );
    connect(ui->checkReversed, &QCheckBox::toggled, this, &TaskFemConstraintGear::onCheckReversed);

    // Temporarily prevent unnecessary feature recomputes
    ui->spinDiameter->blockSignals(true);
    ui->spinForce->blockSignals(true);
    ui->spinForceAngle->blockSignals(true);
    ui->checkReversed->blockSignals(true);

    // Get the feature data
    Fem::ConstraintGear* pcConstraint = ConstraintView->getObject<Fem::ConstraintGear>();
    double dia = pcConstraint->Diameter.getValue();
    double force = pcConstraint->Force.getValue();
    double angle = pcConstraint->ForceAngle.getValue();
    bool reversed = pcConstraint->Reversed.getValue();

    // Fill data into dialog elements
    ui->spinDiameter->setMinimum(0);
    ui->spinDiameter->setMaximum(std::numeric_limits<float>::max());
    ui->spinDiameter->setValue(dia);
    ui->spinForce->setMinimum(0);
    ui->spinForce->setMaximum(std::numeric_limits<float>::max());
    ui->spinForce->setValue(force);
    ui->spinForceAngle->setMinimum(-360);
    ui->spinForceAngle->setMaximum(360);
    ui->spinForceAngle->setValue(angle);
    ui->checkReversed->setChecked(reversed);

    // Adjust ui
    ui->labelDiameter->setVisible(true);
    ui->spinDiameter->setVisible(true);
    ui->labelForce->setVisible(true);
    ui->spinForce->setVisible(true);
    ui->labelForceAngle->setVisible(true);
    ui->spinForceAngle->setVisible(true);
    ui->checkReversed->setVisible(true);
    ui->checkAxial->setVisible(false);

    ui->spinDiameter->blockSignals(false);
    ui->spinForce->blockSignals(false);
    ui->spinForceAngle->blockSignals(false);
    ui->checkReversed->blockSignals(false);
}


void TaskFemConstraintGear::onDiameterChanged(double l)
{
    Fem::ConstraintGear* pcConstraint = ConstraintView->getObject<Fem::ConstraintGear>();
    pcConstraint->Diameter.setValue(l);
}

void TaskFemConstraintGear::onForceChanged(double f)
{
    Fem::ConstraintGear* pcConstraint = ConstraintView->getObject<Fem::ConstraintGear>();
    pcConstraint->Force.setValue(f);
}

void TaskFemConstraintGear::onForceAngleChanged(double a)
{
    Fem::ConstraintGear* pcConstraint = ConstraintView->getObject<Fem::ConstraintGear>();
    pcConstraint->ForceAngle.setValue(a);
}


void TaskFemConstraintGear::onCheckReversed(const bool pressed)
{
    Fem::ConstraintGear* pcConstraint = ConstraintView->getObject<Fem::ConstraintGear>();
    pcConstraint->Reversed.setValue(pressed);
}

double TaskFemConstraintGear::getForce() const
{
    return ui->spinForce->value();
}

double TaskFemConstraintGear::getForceAngle() const
{
    return ui->spinForceAngle->value();
}


bool TaskFemConstraintGear::getReverse() const
{
    return ui->checkReversed->isChecked();
}

double TaskFemConstraintGear::getDiameter() const
{
    return ui->spinDiameter->value();
}

void TaskFemConstraintGear::changeEvent(QEvent* e)
{
    TaskBox::changeEvent(e);
    if (e->type() == QEvent::LanguageChange) {
        ui->spinDiameter->blockSignals(true);
        ui->spinForce->blockSignals(true);
        ui->spinForceAngle->blockSignals(true);
        ui->checkReversed->blockSignals(true);
        ui->retranslateUi(proxy);
        ui->spinDiameter->blockSignals(false);
        ui->spinForce->blockSignals(false);
        ui->spinForceAngle->blockSignals(true);
        ui->checkReversed->blockSignals(false);
    }
}

//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgFemConstraintGear::TaskDlgFemConstraintGear(ViewProviderFemConstraintGear* ConstraintView)
{
    this->ConstraintView = ConstraintView;
    assert(ConstraintView);
    this->parameter = new TaskFemConstraintGear(ConstraintView, nullptr, "FEM_ConstraintGear");

    Content.push_back(parameter);
}

//==== calls from the TaskView ===============================================================

bool TaskDlgFemConstraintGear::accept()
{
    std::string name = ConstraintView->getObject()->getNameInDocument();
    const TaskFemConstraintGear* parameterGear = static_cast<const TaskFemConstraintGear*>(parameter);

    try {
        // Gui::Command::openCommand(QT_TRANSLATE_NOOP("Command", "FEM force constraint changed"));

        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Reversed = %s",
            name.c_str(),
            parameterGear->getReverse() ? "True" : "False"
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Diameter = %f",
            name.c_str(),
            parameterGear->getDiameter()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Force = %f",
            name.c_str(),
            parameterGear->getForce()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.ForceAngle = %f",
            name.c_str(),
            parameterGear->getForceAngle()
        );
    }
    catch (const Base::Exception& e) {
        QMessageBox::warning(parameter, tr("Input Error"), QString::fromLatin1(e.what()));
        return false;
    }

    return TaskDlgFemConstraintBearing::accept();
}

#include "moc_TaskFemConstraintGear.cpp"
