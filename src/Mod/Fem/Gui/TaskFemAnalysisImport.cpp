/***************************************************************************
 *   Copyright (c) 2026 Stefan Tröger <stefantroeger@gmx.net>              *
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

#include <algorithm>
#include <functional>
#include <set>
#include <string>
#include <vector>

#include <QDialogButtonBox>
#include <QListWidgetItem>
#include <QPushButton>

#include <Base/Placement.h>
#include <Gui/BitmapFactory.h>
#include <Mod/Fem/App/FemAnalysis.h>
#include <Mod/Fem/App/FemAnalysisImport.h>
#include <Mod/Fem/App/FemGeometry.h>
#include <Mod/Fem/App/FemTools.h>

#include "TaskFemAnalysisImport.h"
#include "ViewProviderFemAnalysisImport.h"
#include "ui_TaskFemAnalysisImport.h"

using namespace FemGui;

namespace
{

/** Holds a flag for as long as it lives, then puts back what it found. */
class FlagGuard
{
public:
    explicit FlagGuard(bool& flag)
        : m_flag(flag)
        , m_previous(flag)
    {
        m_flag = true;
    }
    ~FlagGuard()
    {
        m_flag = m_previous;
    }
    FlagGuard(const FlagGuard&) = delete;
    FlagGuard& operator=(const FlagGuard&) = delete;

private:
    bool& m_flag;
    bool m_previous;
};

}  // namespace

TaskFemAnalysisImport::TaskFemAnalysisImport(
    ViewProviderFemAnalysisImport* view,
    QWidget* parent
)
    : Gui::TaskView::TaskBox(
        Gui::BitmapFactory().pixmap("FEM_AnalysisImport"),
        tr("Analysis import"),
        true,
        parent
    )
    , m_view(view)
    , ui(new Ui_TaskFemAnalysisImport)
{
    // Setting a field up makes it report a value, and an empty field reports
    // zero. Read back as an edit that would put the instance at the origin
    // before it has said where it stands.
    const FlagGuard guard(m_updating);

    auto* proxy = new QWidget(this);
    ui->setupUi(proxy);
    layout()->addWidget(proxy);

    for (auto* box : {ui->PosX, ui->PosY, ui->PosZ}) {
        box->setProperty("unit", QByteArray("mm"));
    }
    for (auto* box : {ui->RotX, ui->RotY, ui->RotZ}) {
        box->setProperty("unit", QByteArray("deg"));
    }
    applyStepsToFields();
    for (auto* box : {ui->PosX, ui->PosY, ui->PosZ, ui->RotX, ui->RotY, ui->RotZ}) {
        connect(box, qOverload<double>(&Gui::QuantitySpinBox::valueChanged), this, [this]() {
            onPlacementChanged();
        });
    }

    ui->PositionStep->setProperty("unit", QByteArray("mm"));
    ui->PositionStep->setProperty("rawValue", ViewProviderFemAnalysisImport::translationStep());
    ui->AngleStep->setProperty("unit", QByteArray("deg"));
    ui->AngleStep->setProperty("rawValue", ViewProviderFemAnalysisImport::angleStep());
    for (auto* box : {ui->PositionStep, ui->AngleStep}) {
        connect(box, qOverload<double>(&Gui::QuantitySpinBox::valueChanged), this, [this]() {
            onDraggerStepChanged();
        });
    }

    connect(
        ui->listComponents,
        &QListWidget::itemChanged,
        this,
        &TaskFemAnalysisImport::onComponentChanged
    );
    connect(ui->listMembers, &QListWidget::itemChanged, this, &TaskFemAnalysisImport::onMemberChanged);
    connect(
        ui->checkDragger,
        &QCheckBox::toggled,
        this,
        &TaskFemAnalysisImport::onDraggerToggled
    );
    ui->checkDragger->setToolTip(
        tr("Place the instance by dragging it in the 3D view instead of typing values")
    );
    // Placing the instance is what the panel is opened for, so the dragger is
    // there from the start. Set after the connection, which is what carries it
    // to the view provider.
    ui->checkDragger->setChecked(true);

    updatePlacementFields();
    populateComponents();
    populateMembers();

    if (m_view) {
        // The placement written by the dragger has to reach the fields, and the
        // signal for it is delivered to the view provider.
        m_placementConn = fastsignals::scoped_connection(
            m_view->signalPlacementChanged.connect([this]() {
                updatePlacementFields();
            })
        );
    }
}

TaskFemAnalysisImport::~TaskFemAnalysisImport()
{
    // A dragger left behind would keep sitting on the model with nothing to
    // switch it off.
    if (m_view) {
        m_view->setDraggerVisible(false);
    }
}

void TaskFemAnalysisImport::applyStepsToFields()
{
    // Typing a placement and dragging it walk in the same steps, so that a
    // model laid out by hand and one laid out in the view end up on one grid.
    const double position = ViewProviderFemAnalysisImport::translationStep();
    const double angle = ViewProviderFemAnalysisImport::angleStep();
    for (auto* box : {ui->PosX, ui->PosY, ui->PosZ}) {
        box->setProperty("singleStep", position);
    }
    for (auto* box : {ui->RotX, ui->RotY, ui->RotZ}) {
        box->setProperty("singleStep", angle);
    }
}

void TaskFemAnalysisImport::updatePlacementFields()
{
    auto* importObj = m_view ? m_view->getObject<Fem::FemAnalysisImport>() : nullptr;
    if (!importObj) {
        return;
    }
    const FlagGuard guard(m_updating);
    // While the instance is being dragged it is drawn ahead of what is written
    // for it, and the fields say where it is, not where it was let go last.
    const Base::Placement pla = m_view->shownPlacement();
    const Base::Vector3d pos = pla.getPosition();
    double yaw = 0.0;
    double pitch = 0.0;
    double roll = 0.0;
    pla.getRotation().getYawPitchRoll(yaw, pitch, roll);

    ui->PosX->setProperty("rawValue", pos.x);
    ui->PosY->setProperty("rawValue", pos.y);
    ui->PosZ->setProperty("rawValue", pos.z);
    ui->RotX->setProperty("rawValue", roll);
    ui->RotY->setProperty("rawValue", pitch);
    ui->RotZ->setProperty("rawValue", yaw);
}

void TaskFemAnalysisImport::applyPlacementLive()
{
    auto* importObj = m_view ? m_view->getObject<Fem::FemAnalysisImport>() : nullptr;
    if (!importObj) {
        return;
    }
    Base::Placement pla = importObj->Placement.getValue();
    pla.setPosition(Base::Vector3d(
        ui->PosX->property("rawValue").toDouble(),
        ui->PosY->property("rawValue").toDouble(),
        ui->PosZ->property("rawValue").toDouble()
    ));
    Base::Rotation rot = pla.getRotation();
    rot.setYawPitchRoll(
        ui->RotZ->property("rawValue").toDouble(),
        ui->RotY->property("rawValue").toDouble(),
        ui->RotX->property("rawValue").toDouble()
    );
    pla.setRotation(rot);
    importObj->Placement.setValue(pla);
}

void TaskFemAnalysisImport::onPlacementChanged()
{
    if (m_updating) {
        return;
    }
    applyPlacementLive();
}

void TaskFemAnalysisImport::onDraggerToggled(bool on)
{
    if (m_view) {
        m_view->setDraggerVisible(on);
    }
}

void TaskFemAnalysisImport::onDraggerStepChanged()
{
    if (m_updating) {
        return;
    }
    ViewProviderFemAnalysisImport::setTranslationStep(
        ui->PositionStep->property("rawValue").toDouble()
    );
    ViewProviderFemAnalysisImport::setAngleStep(ui->AngleStep->property("rawValue").toDouble());
    applyStepsToFields();
    if (m_view) {
        m_view->updateDraggerSteps();
    }
}

void TaskFemAnalysisImport::populateComponents()
{
    // Filling a list emits itemChanged, which must not be read back as a user
    // switching things off.
    const FlagGuard guard(m_updating);
    ui->listComponents->clear();
    auto* importObj = m_view ? m_view->getObject<Fem::FemAnalysisImport>() : nullptr;
    if (!importObj) {
        return;
    }
    auto* geom = importObj->sourceGeometry();
    if (!geom) {
        return;
    }

    const std::set<long> suppressed(
        importObj->SuppressedComponents.getValues().begin(),
        importObj->SuppressedComponents.getValues().end()
    );

    const auto components = geom->getComponents();
    for (std::size_t i = 0; i < components.size(); ++i) {
        auto* item = new QListWidgetItem(tr("Component%1").arg(static_cast<int>(i + 1)));
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setData(Qt::UserRole, static_cast<qlonglong>(i + 1));
        item->setCheckState(suppressed.count(static_cast<long>(i + 1)) ? Qt::Unchecked : Qt::Checked);
        ui->listComponents->addItem(item);
    }
}

void TaskFemAnalysisImport::populateMembers()
{
    const FlagGuard guard(m_updating);
    ui->listMembers->clear();
    auto* importObj = m_view ? m_view->getObject<Fem::FemAnalysisImport>() : nullptr;
    auto* src =
        importObj ? Base::freecad_cast<Fem::FemAnalysis*>(importObj->Analysis.getValue()) : nullptr;
    if (!src) {
        return;
    }

    const std::set<std::string> suppressed(
        importObj->SuppressedMembers.getValues().begin(),
        importObj->SuppressedMembers.getValues().end()
    );

    // A member of a nested instance is addressed by the path to it, so that
    // suppressing it here leaves the analysis it actually lives in alone.
    std::function<void(Fem::FemAnalysis*, const std::string&, std::vector<const Fem::FemAnalysis*>&)>
        addMembers = [&](Fem::FemAnalysis* analysis,
                         const std::string& prefix,
                         std::vector<const Fem::FemAnalysis*>& seen) {
            if (!analysis || std::ranges::find(seen, analysis) != seen.end()) {
                return;
            }
            seen.push_back(analysis);

            for (auto* member : analysis->Group.getValues()) {
                if (!member || !Fem::Tools::isInheritableMember(member)) {
                    continue;
                }
                const std::string path = prefix + member->getNameInDocument();
                const QString label = prefix.empty()
                    ? QString::fromUtf8(member->Label.getValue())
                    : tr("%1 (%2)")
                          .arg(QString::fromUtf8(member->Label.getValue()))
                          .arg(QString::fromStdString(prefix.substr(0, prefix.size() - 1)));
                auto* item = new QListWidgetItem(label);
                item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
                item->setData(Qt::UserRole, QString::fromStdString(path));
                item->setCheckState(suppressed.count(path) ? Qt::Unchecked : Qt::Checked);
                ui->listMembers->addItem(item);
            }

            for (auto* nested : Fem::Tools::analysisImports(analysis)) {
                addMembers(
                    Base::freecad_cast<Fem::FemAnalysis*>(nested->Analysis.getValue()),
                    prefix + nested->getNameInDocument() + ".",
                    seen
                );
            }
            seen.pop_back();
        };

    std::vector<const Fem::FemAnalysis*> seen;
    addMembers(src, {}, seen);
}

void TaskFemAnalysisImport::onComponentChanged(QListWidgetItem* item)
{
    if (m_updating || !item) {
        return;
    }
    auto* importObj = m_view ? m_view->getObject<Fem::FemAnalysisImport>() : nullptr;
    if (!importObj) {
        return;
    }

    std::vector<long> suppressed;
    for (int row = 0; row < ui->listComponents->count(); ++row) {
        auto* rowItem = ui->listComponents->item(row);
        if (rowItem->checkState() == Qt::Unchecked) {
            suppressed.push_back(rowItem->data(Qt::UserRole).toLongLong());
        }
    }
    importObj->SuppressedComponents.setValues(suppressed);
}

void TaskFemAnalysisImport::onMemberChanged(QListWidgetItem* item)
{
    if (m_updating || !item) {
        return;
    }
    auto* importObj = m_view ? m_view->getObject<Fem::FemAnalysisImport>() : nullptr;
    if (!importObj) {
        return;
    }

    std::vector<std::string> suppressed;
    for (int row = 0; row < ui->listMembers->count(); ++row) {
        auto* rowItem = ui->listMembers->item(row);
        if (rowItem->checkState() == Qt::Unchecked) {
            suppressed.push_back(rowItem->data(Qt::UserRole).toString().toStdString());
        }
    }
    importObj->SuppressedMembers.setValues(suppressed);
}

void TaskFemAnalysisImport::accept() {}

void TaskFemAnalysisImport::reject() {}

TaskDlgFemAnalysisImport::TaskDlgFemAnalysisImport(ViewProviderFemAnalysisImport* view)
{
    m_task = new TaskFemAnalysisImport(view);
    Content.push_back(m_task);
}

void TaskDlgFemAnalysisImport::modifyStandardButtons(QDialogButtonBox* box)
{
    box->button(QDialogButtonBox::Close)->setText(tr("Close"));
}

bool TaskDlgFemAnalysisImport::accept()
{
    m_task->accept();
    return true;
}

bool TaskDlgFemAnalysisImport::reject()
{
    m_task->reject();
    return true;
}
