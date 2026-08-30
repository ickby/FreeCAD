// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2015 FreeCAD Developers                                 *
 *   Authors: Michael Hindley <hindlemp@eskom.co.za>                       *
 *            Ruan Olwagen <olwager@eskom.co.za>                           *
 *            Oswald van Ginkel <vginkeo@eskom.co.za>                      *
 *            Ofentse Kgoa <kgoaot@eskom.co.za>                            *
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


#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <QListWidgetItem>
#include <QMessageBox>
#include <TopoDS.hxx>
#include <limits>
#include <sstream>


#include <App/Document.h>
#include <Gui/Command.h>
#include <Gui/Selection/SelectionObject.h>
#include <Mod/Fem/App/FemConstraintTransform.h>
#include <Mod/Part/App/PartFeature.h>

#include "TaskFemConstraintTransform.h"
#include "ui_TaskFemConstraintTransform.h"


using namespace FemGui;
using namespace Gui;

/* TRANSLATOR FemGui::TaskFemConstraintTransform */

TaskFemConstraintTransform::TaskFemConstraintTransform(
    ViewProviderFemConstraintTransform* ConstraintView,
    QWidget* parent
)
    : TaskFemConstraint(ConstraintView, parent, "FEM_ConstraintTransform")
    , ui(new Ui_TaskFemConstraintTransform)
{
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    // The transformable-surface list is informational, but clicking a row
    // still shows that surface in the 3D view.
    connect(
        ui->lw_displobj_rect,
        &QListWidget::currentItemChanged,
        this,
        &TaskFemConstraintTransform::selectDisplacedSurface
    );
    connect(
        ui->lw_displobj_rect,
        &QListWidget::itemClicked,
        this,
        &TaskFemConstraintTransform::selectDisplacedSurface
    );

    this->groupLayout()->addWidget(proxy);
    {
        ReferenceSlotSpec spec;
        spec.property = "References";
        spec.title = tr("References").toStdString();
        spec.types = {"Edge", "Face"};
        spec.maxCount = 1;
        spec.homogeneous = false;
        spec.armed = true;
        addReferenceSelection({spec}, proxy);
    }

    connect(ui->rb_rect, &QRadioButton::clicked, this, &TaskFemConstraintTransform::Rect);
    connect(ui->rb_cylin, &QRadioButton::clicked, this, &TaskFemConstraintTransform::Cyl);

    connect(
        ui->spb_rot_axis_x,
        qOverload<double>(&DoubleSpinBox::valueChanged),
        this,
        &TaskFemConstraintTransform::xAxisChanged
    );
    connect(
        ui->spb_rot_axis_y,
        qOverload<double>(&DoubleSpinBox::valueChanged),
        this,
        &TaskFemConstraintTransform::yAxisChanged
    );
    connect(
        ui->spb_rot_axis_z,
        qOverload<double>(&DoubleSpinBox::valueChanged),
        this,
        &TaskFemConstraintTransform::zAxisChanged
    );
    connect(
        ui->qsb_rot_angle,
        qOverload<double>(&QuantitySpinBox::valueChanged),
        this,
        &TaskFemConstraintTransform::angleChanged
    );

    // Get the feature data
    Fem::ConstraintTransform* pcConstraint = ConstraintView->getObject<Fem::ConstraintTransform>();

    std::vector<App::DocumentObject*> Objects = pcConstraint->References.getValues();
    std::vector<std::string> SubElements = pcConstraint->References.getSubValues();

    // Fill data into dialog elements
    Base::Vector3d axis;
    double angle;
    pcConstraint->Rotation.getValue().getValue(axis, angle);
    ui->spb_rot_axis_x->setValue(axis.x);
    ui->spb_rot_axis_y->setValue(axis.y);
    ui->spb_rot_axis_z->setValue(axis.z);
    Base::Quantity rotAngle(angle, "rad");
    ui->qsb_rot_angle->setValue(rotAngle.getValueAs(Base::Quantity::Degree));

    ui->spb_rot_axis_x->bind(
        App::ObjectIdentifier::parse(pcConstraint, std::string("Rotation.Axis.x"))
    );
    ui->spb_rot_axis_y->bind(
        App::ObjectIdentifier::parse(pcConstraint, std::string("Rotation.Axis.y"))
    );
    ui->spb_rot_axis_z->bind(
        App::ObjectIdentifier::parse(pcConstraint, std::string("Rotation.Axis.z"))
    );
    ui->qsb_rot_angle->bind(App::ObjectIdentifier::parse(pcConstraint, std::string("Rotation.Angle")));

    float max = std::numeric_limits<float>::max();
    ui->spb_rot_axis_x->setMinimum(-max);
    ui->spb_rot_axis_x->setMaximum(max);
    ui->spb_rot_axis_y->setMinimum(-max);
    ui->spb_rot_axis_y->setMaximum(max);
    ui->spb_rot_axis_z->setMinimum(-max);
    ui->spb_rot_axis_z->setMaximum(max);
    ui->qsb_rot_angle->setMinimum(-max);
    ui->qsb_rot_angle->setMaximum(max);

    std::string transform_type = pcConstraint->TransformType.getValueAsString();
    if (transform_type == "Rectangular") {
        ui->sw_transform->setCurrentIndex(0);
        ui->rb_rect->setChecked(true);
        ui->rb_cylin->setChecked(false);
    }
    else if (transform_type == "Cylindrical") {
        ui->sw_transform->setCurrentIndex(1);
        ui->rb_rect->setChecked(false);
        ui->rb_cylin->setChecked(true);
    }

    // Transformable surfaces
    Gui::Command::doCommand(
        Gui::Command::Doc,
        TaskFemConstraintTransform::getSurfaceReferences(
            (ConstraintView->getObject<Fem::Constraint>())->getNameInDocument()
        )
            .c_str()
    );
    std::vector<App::DocumentObject*> ObjDispl = pcConstraint->RefDispl.getValues();
    std::vector<std::string> SubElemDispl = pcConstraint->RefDispl.getSubValues();

    for (std::size_t i = 0; i < ObjDispl.size(); i++) {
        ui->lw_displobj_rect->addItem(makeSurfaceText(ObjDispl[i], SubElemDispl[i]));
        ui->lw_displobj_cylin->addItem(makeSurfaceText(ObjDispl[i], SubElemDispl[i]));
    }

    std::vector<App::DocumentObject*> nDispl = pcConstraint->NameDispl.getValues();
    for (auto i : nDispl) {
        ui->lw_dis_rect->addItem(makeText(i));
        ui->lw_dis_cylin->addItem(makeText(i));
    }

    int p = 0;
    for (std::size_t i = 0; i < ObjDispl.size(); i++) {
        for (std::size_t j = 0; j < Objects.size(); j++) {
            if (ObjDispl[i] == Objects[j] && SubElemDispl[i] == SubElements[j]) {
                p++;
            }
        }
    }
    if ((p == 0) && (!Objects.empty())) {
        QMessageBox::warning(
            this,
            tr("Analysis feature update error"),
            tr("The transformable faces have changed. Add only the "
               "transformable faces and remove non-transformable faces!")
        );
        return;
    }
}

TaskFemConstraintTransform::~TaskFemConstraintTransform() = default;

const QString TaskFemConstraintTransform::makeText(const App::DocumentObject* obj) const
{
    return QString::fromUtf8((std::string(obj->getNameInDocument())).c_str());
}

QString TaskFemConstraintTransform::makeSurfaceText(
    const App::DocumentObject* obj,
    const std::string& subName
)
{
    return QString::fromUtf8((std::string(obj->getNameInDocument()) + ":" + subName).c_str());
}

void TaskFemConstraintTransform::selectDisplacedSurface(QListWidgetItem* item)
{
    if (!item || ConstraintView.expired()) {
        return;
    }
    const QStringList parts = item->text().split(QLatin1Char(':'));
    const std::string document = ConstraintView->getObject()->getDocument()->getName();
    const std::string object = parts.value(0).toStdString();
    const std::string element = parts.value(1).toStdString();
    Gui::Selection().clearSelection();
    Gui::Selection().addSelection(document.c_str(), object.c_str(), element.c_str());
}


void TaskFemConstraintTransform::xAxisChanged(double x)
{
    (void)x;
    Base::Rotation rot = getRotation();
    Fem::ConstraintTransform* pcConstraint = ConstraintView->getObject<Fem::ConstraintTransform>();
    pcConstraint->Rotation.setValue(rot);
}

void TaskFemConstraintTransform::yAxisChanged(double y)
{
    (void)y;
    Base::Rotation rot = getRotation();
    Fem::ConstraintTransform* pcConstraint = ConstraintView->getObject<Fem::ConstraintTransform>();
    pcConstraint->Rotation.setValue(rot);
}

void TaskFemConstraintTransform::zAxisChanged(double z)
{
    (void)z;
    Base::Rotation rot = getRotation();
    Fem::ConstraintTransform* pcConstraint = ConstraintView->getObject<Fem::ConstraintTransform>();
    pcConstraint->Rotation.setValue(rot);
}

void TaskFemConstraintTransform::angleChanged(double a)
{
    (void)a;
    Base::Rotation rot = getRotation();
    Fem::ConstraintTransform* pcConstraint = ConstraintView->getObject<Fem::ConstraintTransform>();
    pcConstraint->Rotation.setValue(rot);
}

void TaskFemConstraintTransform::Rect()
{
    ui->sw_transform->setCurrentIndex(0);
    std::string name = ConstraintView->getObject()->getNameInDocument();
    Gui::Command::doCommand(
        Gui::Command::Doc,
        "App.ActiveDocument.%s.TransformType = %s",
        name.c_str(),
        get_transform_type().c_str()
    );
    Fem::ConstraintTransform* pcConstraint = ConstraintView->getObject<Fem::ConstraintTransform>();
    if (!pcConstraint->References.getValues().empty()) {
        pcConstraint->References.setValues({}, {});
    }
}

void TaskFemConstraintTransform::Cyl()
{
    ui->sw_transform->setCurrentIndex(1);
    std::string name = ConstraintView->getObject()->getNameInDocument();
    Gui::Command::doCommand(
        Gui::Command::Doc,
        "App.ActiveDocument.%s.TransformType = %s",
        name.c_str(),
        get_transform_type().c_str()
    );
    Fem::ConstraintTransform* pcConstraint = ConstraintView->getObject<Fem::ConstraintTransform>();
    if (!pcConstraint->References.getValues().empty()) {
        pcConstraint->References.setValues({}, {});
    }
}


Base::Rotation TaskFemConstraintTransform::getRotation() const
{
    double x = ui->spb_rot_axis_x->value();
    double y = ui->spb_rot_axis_y->value();
    double z = ui->spb_rot_axis_z->value();
    double angle = ui->qsb_rot_angle->value().getValueAs(Base::Quantity::Radian);

    return Base::Rotation(Base::Vector3d(x, y, z), angle);
}


std::string TaskFemConstraintTransform::getSurfaceReferences(std::string showConstr = "")
// https://forum.freecad.org/viewtopic.php?f=18&t=43650
{
    return "\n\
doc = FreeCAD.ActiveDocument\n\
for obj in doc.Objects:\n\
        if obj.isDerivedFrom(\"Fem::FemAnalysis\"):\n\
                if doc."
        + showConstr + " in obj.Group:\n\
                        analysis = obj\n\
A = []\n\
i = 0\n\
ss = []\n\
for member in analysis.Group:\n\
        if ((member.isDerivedFrom(\"Fem::ConstraintDisplacement\")) or (member.isDerivedFrom(\"Fem::ConstraintForce\"))) and len(member.References) > 0:\n\
                m = member.References\n\
                A.append(m)\n\
                if i >0:\n\
                        p = p + m[0][1]\n\
                        x = (A[0][0][0],p)\n\
                        for t in range(len(m[0][1])):\n\
                                ss.append(member)\n\
                else:\n\
                        p = A[i][0][1]\n\
                        x = (A[0][0][0],p)\n\
                        for t in range(len(m[0][1])):\n\
                                ss.append(member)\n\
                i = i+1\n\
if i>0:\n\
        doc."
        + showConstr + ".RefDispl = [x]\n\
        doc."
        + showConstr + ".NameDispl = ss\n\
else:\n\
        doc."
        + showConstr + ".RefDispl = None\n\
        doc."
        + showConstr + ".NameDispl = []\n";
}

std::string TaskFemConstraintTransform::get_transform_type() const
{
    std::string transform;
    if (ui->rb_rect->isChecked()) {
        transform = "\"Rectangular\"";
    }
    else if (ui->rb_cylin->isChecked()) {
        transform = "\"Cylindrical\"";
    }
    return transform;
}

void TaskFemConstraintTransform::changeEvent(QEvent*)
{}

//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgFemConstraintTransform::TaskDlgFemConstraintTransform(
    ViewProviderFemConstraintTransform* ConstraintView
)
{
    this->ConstraintView = ConstraintView;
    assert(ConstraintView);
    this->parameter = new TaskFemConstraintTransform(ConstraintView);

    Content.push_back(parameter);
}

//==== calls from the TaskView ===============================================================

bool TaskDlgFemConstraintTransform::accept()
{
    /* Note: */
    std::string name = ConstraintView->getObject()->getNameInDocument();
    const TaskFemConstraintTransform* parameters = static_cast<const TaskFemConstraintTransform*>(
        parameter
    );

    try {
        Base::Rotation rot = parameters->getRotation();
        Base::Vector3d axis;
        double angle;
        rot.getValue(axis, angle);
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.Rotation = App.Rotation(App.Vector(%f,% f, %f), Radian=%f)",
            name.c_str(),
            axis.x,
            axis.y,
            axis.z,
            angle
        );

        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.ActiveDocument.%s.TransformType = %s",
            name.c_str(),
            parameters->get_transform_type().c_str()
        );
    }
    catch (const Base::Exception& e) {
        QMessageBox::warning(parameter, tr("Input Error"), QString::fromLatin1(e.what()));
        return false;
    }
    /* */
    return TaskDlgFemConstraint::accept();
}

#include "moc_TaskFemConstraintTransform.cpp"
