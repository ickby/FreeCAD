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
#include <TopoDS.hxx>
#include <sstream>


#include <App/DocumentObject.h>
#include <Gui/Command.h>
#include <Gui/Selection/SelectionObject.h>
#include <Gui/ViewProvider.h>
#include <Mod/Fem/App/FemConstraintPlaneRotation.h>
#include <Mod/Fem/App/FemTools.h>
#include <Mod/Part/App/PartFeature.h>

#include "TaskFemConstraintPlaneRotation.h"
#include "ui_TaskFemConstraintPlaneRotation.h"


using namespace FemGui;
using namespace Gui;

/* TRANSLATOR FemGui::TaskFemConstraintPlaneRotation */

TaskFemConstraintPlaneRotation::TaskFemConstraintPlaneRotation(
    ViewProviderFemConstraintPlaneRotation* ConstraintView,
    QWidget* parent
)
    : TaskFemConstraint(ConstraintView, parent, "FEM_ConstraintPlaneRotation")
    , ui(new Ui_TaskFemConstraintPlaneRotation)
{  // Note change "planerotation" in line above to new constraint name
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);


    this->groupLayout()->addWidget(proxy);
    {
        ReferenceSlotSpec spec;
        spec.property = "References";
        spec.title = tr("References").toStdString();
        spec.types = {"Face"};
        spec.maxCount = 1;
        spec.homogeneous = false;
        spec.armed = true;
        addReferenceSelection({spec}, proxy);
    }
}

TaskFemConstraintPlaneRotation::~TaskFemConstraintPlaneRotation() = default;


void TaskFemConstraintPlaneRotation::changeEvent(QEvent*)
{}

//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgFemConstraintPlaneRotation::TaskDlgFemConstraintPlaneRotation(
    ViewProviderFemConstraintPlaneRotation* ConstraintView
)
{
    this->ConstraintView = ConstraintView;
    assert(ConstraintView);
    this->parameter = new TaskFemConstraintPlaneRotation(ConstraintView);

    Content.push_back(parameter);
}

//==== calls from the TaskView ===============================================================

bool TaskDlgFemConstraintPlaneRotation::accept()
{
    return TaskDlgFemConstraint::accept();
}

#include "moc_TaskFemConstraintPlaneRotation.cpp"
