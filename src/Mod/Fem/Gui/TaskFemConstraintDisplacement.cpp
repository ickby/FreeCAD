// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2015, 2023 FreeCAD Developers                           *
 *   Authors: Michael Hindley <hindlemp@eskom.co.za>                       *
 *            Ruan Olwagen <olwager@eskom.co.za>                           *
 *            Oswald van Ginkel <vginkeo@eskom.co.za>                      *
 *            Uwe Stöhr <uwestoehr@lyx.org>                                *
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
#include <Mod/Fem/App/FemConstraintDisplacement.h>
#include <Mod/Part/App/PartFeature.h>

#include "TaskFemConstraintDisplacement.h"
#include "ui_TaskFemConstraintDisplacement.h"


using namespace FemGui;
using namespace Gui;

/* TRANSLATOR FemGui::TaskFemConstraintDisplacement */

TaskFemConstraintDisplacement::TaskFemConstraintDisplacement(
    ViewProviderFemConstraintDisplacement* ConstraintView,
    QWidget* parent
)
    : TaskFemConstraint(ConstraintView, parent, "FEM_ConstraintDisplacement")
    , ui(new Ui_TaskFemConstraintDisplacement)
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

    // setup ranges
    constexpr float max = std::numeric_limits<float>::max();
    ui->spinxDisplacement->setMinimum(-max);
    ui->spinxDisplacement->setMaximum(max);
    ui->spinyDisplacement->setMinimum(-max);
    ui->spinyDisplacement->setMaximum(max);
    ui->spinzDisplacement->setMinimum(-max);
    ui->spinzDisplacement->setMaximum(max);
    ui->spinxRotation->setMinimum(-max);
    ui->spinxRotation->setMaximum(max);
    ui->spinyRotation->setMinimum(-max);
    ui->spinyRotation->setMaximum(max);
    ui->spinzRotation->setMinimum(-max);
    ui->spinzRotation->setMaximum(max);

    // Get the feature data
    Fem::ConstraintDisplacement* pcConstraint
        = ConstraintView->getObject<Fem::ConstraintDisplacement>();
    Base::Quantity fStates[6] {};
    const char* sStates[3] {};
    bool bStates[10] {};
    fStates[0] = pcConstraint->xDisplacement.getQuantityValue();
    fStates[1] = pcConstraint->yDisplacement.getQuantityValue();
    fStates[2] = pcConstraint->zDisplacement.getQuantityValue();
    fStates[3] = pcConstraint->xRotation.getQuantityValue();
    fStates[4] = pcConstraint->yRotation.getQuantityValue();
    fStates[5] = pcConstraint->zRotation.getQuantityValue();
    sStates[0] = pcConstraint->xDisplacementFormula.getValue();
    sStates[1] = pcConstraint->yDisplacementFormula.getValue();
    sStates[2] = pcConstraint->zDisplacementFormula.getValue();
    bStates[0] = pcConstraint->xFree.getValue();
    bStates[1] = pcConstraint->yFree.getValue();
    bStates[2] = pcConstraint->zFree.getValue();
    bStates[3] = pcConstraint->rotxFree.getValue();
    bStates[4] = pcConstraint->rotyFree.getValue();
    bStates[5] = pcConstraint->rotzFree.getValue();
    bStates[6] = pcConstraint->hasXFormula.getValue();
    bStates[7] = pcConstraint->hasYFormula.getValue();
    bStates[8] = pcConstraint->hasZFormula.getValue();
    bStates[9] = pcConstraint->useFlowSurfaceForce.getValue();


    // Connect check box values displacements
    connect(ui->DisplacementXFormulaCB, &QCheckBox::toggled, this, &TaskFemConstraintDisplacement::formulaX);
    connect(ui->DisplacementYFormulaCB, &QCheckBox::toggled, this, &TaskFemConstraintDisplacement::formulaY);
    connect(ui->DisplacementZFormulaCB, &QCheckBox::toggled, this, &TaskFemConstraintDisplacement::formulaZ);
    connect(ui->FlowForceCB, &QCheckBox::toggled, this, &TaskFemConstraintDisplacement::flowForce);
    // Connect to check box values for rotations

    // Fill data into dialog elements
    ui->spinxDisplacement->setValue(fStates[0]);
    ui->spinyDisplacement->setValue(fStates[1]);
    ui->spinzDisplacement->setValue(fStates[2]);
    ui->spinxRotation->setValue(fStates[3]);
    ui->spinyRotation->setValue(fStates[4]);
    ui->spinzRotation->setValue(fStates[5]);
    ui->DisplacementXFormulaLE->setText(QString::fromUtf8(sStates[0]));
    ui->DisplacementYFormulaLE->setText(QString::fromUtf8(sStates[1]));
    ui->DisplacementZFormulaLE->setText(QString::fromUtf8(sStates[2]));
    ui->DisplacementXGB->setChecked(!bStates[0]);
    ui->DisplacementYGB->setChecked(!bStates[1]);
    ui->DisplacementZGB->setChecked(!bStates[2]);
    ui->RotationXGB->setChecked(!bStates[3]);
    ui->RotationYGB->setChecked(!bStates[4]);
    ui->RotationZGB->setChecked(!bStates[5]);
    ui->DisplacementXFormulaCB->setChecked(bStates[6]);
    ui->DisplacementYFormulaCB->setChecked(bStates[7]);
    ui->DisplacementZFormulaCB->setChecked(bStates[8]);
    ui->FlowForceCB->setChecked(bStates[9]);


    // Bind input fields to properties
    ui->spinxDisplacement->bind(pcConstraint->xDisplacement);
    ui->spinyDisplacement->bind(pcConstraint->yDisplacement);
    ui->spinzDisplacement->bind(pcConstraint->zDisplacement);
    ui->spinxRotation->bind(pcConstraint->xRotation);
    ui->spinyRotation->bind(pcConstraint->yRotation);
    ui->spinzRotation->bind(pcConstraint->zRotation);
}

TaskFemConstraintDisplacement::~TaskFemConstraintDisplacement() = default;


void TaskFemConstraintDisplacement::formulaX(bool state)
{
    ui->spinxDisplacement->setEnabled(!state);
    ui->DisplacementXFormulaLE->setEnabled(state);
}

void TaskFemConstraintDisplacement::formulaY(bool state)
{
    ui->spinyDisplacement->setEnabled(!state);
    ui->DisplacementYFormulaLE->setEnabled(state);
}

void TaskFemConstraintDisplacement::formulaZ(bool state)
{
    ui->spinzDisplacement->setEnabled(!state);
    ui->DisplacementZFormulaLE->setEnabled(state);
}

void TaskFemConstraintDisplacement::flowForce(bool state)
{
    if (state) {
        ui->DisplacementXGB->setChecked(!state);
        ui->DisplacementYGB->setChecked(!state);
        ui->DisplacementZGB->setChecked(!state);
        ui->RotationXGB->setChecked(!state);
        ui->RotationYGB->setChecked(!state);
        ui->RotationZGB->setChecked(!state);
    }
}

void TaskFemConstraintDisplacement::formulaRotx(bool state)
{
    ui->spinxRotation->setEnabled(!state);
}

void TaskFemConstraintDisplacement::formulaRoty(bool state)
{
    ui->spinyRotation->setEnabled(!state);
}

void TaskFemConstraintDisplacement::formulaRotz(bool state)
{
    ui->spinzRotation->setEnabled(!state);
}


std::string TaskFemConstraintDisplacement::get_spinxDisplacement() const
{
    return ui->spinxDisplacement->value().getSafeUserString();
}

std::string TaskFemConstraintDisplacement::get_spinyDisplacement() const
{
    return ui->spinyDisplacement->value().getSafeUserString();
}

std::string TaskFemConstraintDisplacement::get_spinzDisplacement() const
{
    return ui->spinzDisplacement->value().getSafeUserString();
}

std::string TaskFemConstraintDisplacement::get_spinxRotation() const
{
    return ui->spinxRotation->value().getSafeUserString();
}

std::string TaskFemConstraintDisplacement::get_spinyRotation() const
{
    return ui->spinyRotation->value().getSafeUserString();
}

std::string TaskFemConstraintDisplacement::get_spinzRotation() const
{
    return ui->spinzRotation->value().getSafeUserString();
}

std::string TaskFemConstraintDisplacement::get_xFormula() const
{
    return ui->DisplacementXFormulaLE->text().toStdString();
}

std::string TaskFemConstraintDisplacement::get_yFormula() const
{
    return ui->DisplacementYFormulaLE->text().toStdString();
}

std::string TaskFemConstraintDisplacement::get_zFormula() const
{
    return ui->DisplacementZFormulaLE->text().toStdString();
}

bool TaskFemConstraintDisplacement::get_dispxfree() const
{
    return !ui->DisplacementXGB->isChecked();
}

bool TaskFemConstraintDisplacement::get_hasDispXFormula() const
{
    return ui->DisplacementXFormulaCB->isChecked();
}

bool TaskFemConstraintDisplacement::get_dispyfree() const
{
    return !ui->DisplacementYGB->isChecked();
}

bool TaskFemConstraintDisplacement::get_hasDispYFormula() const
{
    return ui->DisplacementYFormulaCB->isChecked();
}

bool TaskFemConstraintDisplacement::get_dispzfree() const
{
    return !ui->DisplacementZGB->isChecked();
}

bool TaskFemConstraintDisplacement::get_hasDispZFormula() const
{
    return ui->DisplacementZFormulaCB->isChecked();
}

bool TaskFemConstraintDisplacement::get_rotxfree() const
{
    return !ui->RotationXGB->isChecked();
}

bool TaskFemConstraintDisplacement::get_rotyfree() const
{
    return !ui->RotationYGB->isChecked();
}

bool TaskFemConstraintDisplacement::get_rotzfree() const
{
    return !ui->RotationZGB->isChecked();
}

bool TaskFemConstraintDisplacement::get_useFlowSurfaceForce() const
{
    return ui->FlowForceCB->isChecked();
}

void TaskFemConstraintDisplacement::changeEvent(QEvent*)
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

TaskDlgFemConstraintDisplacement::TaskDlgFemConstraintDisplacement(
    ViewProviderFemConstraintDisplacement* ConstraintView
)
{
    this->ConstraintView = ConstraintView;
    assert(ConstraintView);
    this->parameter = new TaskFemConstraintDisplacement(ConstraintView);

    Content.push_back(parameter);
}

//==== calls from the TaskView ===============================================================

bool TaskDlgFemConstraintDisplacement::accept()
{
    std::string name = ConstraintView->getObject()->getNameInDocument();
    const TaskFemConstraintDisplacement* parameterDisplacement
        = static_cast<const TaskFemConstraintDisplacement*>(parameter);
    auto* constraint = static_cast<Fem::ConstraintDisplacement*>(ConstraintView->getObject());

    try {
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.xDisplacement = \"%s\"",
            name.c_str(),
            parameterDisplacement->get_spinxDisplacement().c_str()
        );
        // Formula fields are free-form user text and must never be interpolated into a
        // Python command; set the property directly to avoid code injection.
        constraint->xDisplacementFormula.setValue(parameterDisplacement->get_xFormula());
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.yDisplacement = \"%s\"",
            name.c_str(),
            parameterDisplacement->get_spinyDisplacement().c_str()
        );
        constraint->yDisplacementFormula.setValue(parameterDisplacement->get_yFormula());
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.zDisplacement = \"%s\"",
            name.c_str(),
            parameterDisplacement->get_spinzDisplacement().c_str()
        );
        constraint->zDisplacementFormula.setValue(parameterDisplacement->get_zFormula());
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.xRotation = \"%s\"",
            name.c_str(),
            parameterDisplacement->get_spinxRotation().c_str()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.yRotation = \"%s\"",
            name.c_str(),
            parameterDisplacement->get_spinyRotation().c_str()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.zRotation = \"%s\"",
            name.c_str(),
            parameterDisplacement->get_spinzRotation().c_str()
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.xFree = %s",
            name.c_str(),
            parameterDisplacement->get_dispxfree() ? "True" : "False"
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.hasXFormula = %s",
            name.c_str(),
            parameterDisplacement->get_hasDispXFormula() ? "True" : "False"
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.yFree = %s",
            name.c_str(),
            parameterDisplacement->get_dispyfree() ? "True" : "False"
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.hasYFormula = %s",
            name.c_str(),
            parameterDisplacement->get_hasDispYFormula() ? "True" : "False"
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.zFree = %s",
            name.c_str(),
            parameterDisplacement->get_dispzfree() ? "True" : "False"
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.hasZFormula = %s",
            name.c_str(),
            parameterDisplacement->get_hasDispZFormula() ? "True" : "False"
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.rotxFree = %s",
            name.c_str(),
            parameterDisplacement->get_rotxfree() ? "True" : "False"
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.rotyFree = %s",
            name.c_str(),
            parameterDisplacement->get_rotyfree() ? "True" : "False"
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.rotzFree = %s",
            name.c_str(),
            parameterDisplacement->get_rotzfree() ? "True" : "False"
        );
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.useFlowSurfaceForce = %s",
            name.c_str(),
            parameterDisplacement->get_useFlowSurfaceForce() ? "True" : "False"
        );
    }
    catch (const Base::Exception& e) {
        QMessageBox::warning(parameter, tr("Input Error"), QString::fromLatin1(e.what()));
        return false;
    }

    return TaskDlgFemConstraint::accept();
}

#include "moc_TaskFemConstraintDisplacement.cpp"
