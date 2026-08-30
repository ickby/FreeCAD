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


#include <BRepAdaptor_Surface.hxx>
#include <QAction>
#include <QMessageBox>
#include <TopoDS.hxx>
#include <limits>
#include <sstream>


#include <App/Document.h>
#include <Gui/Command.h>
#include <Gui/Selection/Selection.h>

#include <Mod/Fem/App/FemConstraintBearing.h>
#include <Mod/Fem/App/FemTools.h>
#include <Mod/Part/App/PartFeature.h>

#include "TaskFemConstraintBearing.h"
#include "ui_TaskFemConstraintBearing.h"


using namespace FemGui;
using namespace Gui;

/* TRANSLATOR FemGui::TaskFemConstraintBearing */

TaskFemConstraintBearing::TaskFemConstraintBearing(
    ViewProviderFemConstraint* ConstraintView,
    QWidget* parent,
    const char* pixmapname
)
    : TaskFemConstraint(ConstraintView, parent, pixmapname)
    , ui(new Ui_TaskFemConstraintBearing)
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
        spec.types = {"Face"};
        spec.homogeneous = false;
        spec.armed = true;
        ReferenceSlotSpec location;
        location.property = "Location";
        location.title = tr("Location").toStdString();
        location.types = {"Face", "Edge"};
        location.maxCount = 1;
        location.homogeneous = false;
        location.id = "Location";
        ReferenceSlotSpec direction;
        direction.property = "Direction";
        direction.title = tr("Direction").toStdString();
        direction.types = {"Face", "Edge"};
        direction.maxCount = 1;
        direction.homogeneous = false;
        direction.id = "Direction";
        addReferenceSelection({spec, location, direction}, proxy);
        m_references->setSlotVisible("Direction", false);
    }

    // setup ranges
    constexpr float max = std::numeric_limits<float>::max();
    ui->spinDiameter->setMinimum(-max);
    ui->spinDiameter->setMaximum(max);
    ui->spinOtherDiameter->setMinimum(-max);
    ui->spinOtherDiameter->setMaximum(max);
    ui->spinCenterDistance->setMinimum(-max);
    ui->spinCenterDistance->setMaximum(max);
    ui->spinForce->setMinimum(-max);
    ui->spinForce->setMaximum(max);
    ui->spinTensionForce->setMinimum(-max);
    ui->spinTensionForce->setMaximum(max);
    ui->spinDistance->setMinimum(-max);
    ui->spinDistance->setMaximum(max);

    // Get the feature data
    Fem::ConstraintBearing* pcConstraint = ConstraintView->getObject<Fem::ConstraintBearing>();
    double distance = pcConstraint->Dist.getValue();

    // Fill data into dialog elements
    ui->spinDistance->setValue(distance);
    ui->checkAxial->setChecked(pcConstraint->AxialFree.getValue());

    connect(
        ui->spinDistance,
        qOverload<double>(&QDoubleSpinBox::valueChanged),
        this,
        &TaskFemConstraintBearing::onDistanceChanged
    );
    connect(ui->checkAxial, &QCheckBox::toggled, this, &TaskFemConstraintBearing::onCheckAxial);

    // Hide unwanted ui elements
    ui->labelDiameter->setVisible(false);
    ui->spinDiameter->setVisible(false);
    ui->labelOtherDiameter->setVisible(false);
    ui->spinOtherDiameter->setVisible(false);
    ui->labelCenterDistance->setVisible(false);
    ui->spinCenterDistance->setVisible(false);
    ui->checkIsDriven->setVisible(false);
    ui->labelForce->setVisible(false);
    ui->spinForce->setVisible(false);
    ui->labelTensionForce->setVisible(false);
    ui->spinTensionForce->setVisible(false);
    ui->labelForceAngle->setVisible(false);
    ui->spinForceAngle->setVisible(false);
    ui->checkReversed->setVisible(false);
}


void TaskFemConstraintBearing::onDistanceChanged(double l)
{
    Fem::ConstraintBearing* pcConstraint = ConstraintView->getObject<Fem::ConstraintBearing>();
    pcConstraint->Dist.setValue(l);
}


void TaskFemConstraintBearing::onCheckAxial(const bool pressed)
{
    Fem::ConstraintBearing* pcConstraint = ConstraintView->getObject<Fem::ConstraintBearing>();
    pcConstraint->AxialFree.setValue(pressed);
}

double TaskFemConstraintBearing::getDistance() const
{
    return ui->spinDistance->value();
}


bool TaskFemConstraintBearing::getAxial() const
{
    return ui->checkAxial->isChecked();
}

TaskFemConstraintBearing::~TaskFemConstraintBearing() = default;

void TaskFemConstraintBearing::changeEvent(QEvent* e)
{
    TaskBox::changeEvent(e);
    if (e->type() == QEvent::LanguageChange) {
        ui->spinDistance->blockSignals(true);
        ui->retranslateUi(proxy);
        ui->spinDistance->blockSignals(false);
    }
}

//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgFemConstraintBearing::TaskDlgFemConstraintBearing(
    ViewProviderFemConstraintBearing* ConstraintView
)
{
    this->ConstraintView = ConstraintView;
    assert(ConstraintView);
    this->parameter = new TaskFemConstraintBearing(ConstraintView);

    Content.push_back(parameter);
}

//==== calls from the TaskView ===============================================================

bool TaskDlgFemConstraintBearing::accept()
{
    std::string name = ConstraintView->getObject()->getNameInDocument();
    const TaskFemConstraintBearing* parameterBearing = static_cast<const TaskFemConstraintBearing*>(
        parameter
    );

    try {
        // Gui::Command::openCommand(QT_TRANSLATE_NOOP("Command", "FEM force constraint changed"));
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Dist = %f",
            name.c_str(),
            parameterBearing->getDistance()
        );

        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.AxialFree = %s",
            name.c_str(),
            parameterBearing->getAxial() ? "True" : "False"
        );
    }
    catch (const Base::Exception& e) {
        QMessageBox::warning(parameter, tr("Input Error"), QString::fromLatin1(e.what()));
        return false;
    }

    return TaskDlgFemConstraint::accept();
}

#include "moc_TaskFemConstraintBearing.cpp"
