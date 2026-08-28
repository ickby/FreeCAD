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

#pragma once

#include <QObject>
#include <memory>

class QListWidgetItem;

#include <Gui/TaskView/TaskDialog.h>
#include <Gui/TaskView/TaskView.h>
#include <Mod/Fem/FemGlobal.h>
#include <fastsignals/signal.h>

class Ui_TaskFemAnalysisImport;

namespace FemGui
{

class ViewProviderFemAnalysisImport;

class FemGuiExport TaskFemAnalysisImport: public Gui::TaskView::TaskBox
{
    Q_OBJECT

public:
    explicit TaskFemAnalysisImport(ViewProviderFemAnalysisImport* view, QWidget* parent = nullptr);
    ~TaskFemAnalysisImport() override;

    void accept();
    void reject();

private Q_SLOTS:
    void onPlacementChanged();
    void onDraggerToggled(bool on);
    void onDraggerStepChanged();
    void onComponentChanged(QListWidgetItem* item);
    void onMemberChanged(QListWidgetItem* item);

private:
    void updatePlacementFields();
    /** Let the placement fields walk in the configured drag steps. */
    void applyStepsToFields();
    void populateComponents();
    void populateMembers();
    void applyPlacementLive();

    ViewProviderFemAnalysisImport* m_view {nullptr};
    std::unique_ptr<Ui_TaskFemAnalysisImport> ui;
    fastsignals::scoped_connection m_placementConn;
    bool m_updating {false};
};

class FemGuiExport TaskDlgFemAnalysisImport: public Gui::TaskView::TaskDialog
{
    Q_OBJECT

public:
    explicit TaskDlgFemAnalysisImport(ViewProviderFemAnalysisImport* view);
    ~TaskDlgFemAnalysisImport() override = default;

    QDialogButtonBox::StandardButtons getStandardButtons() const override
    {
        return QDialogButtonBox::Close;
    }
    bool isAllowedAlterDocument() const override
    {
        return true;
    }

    void modifyStandardButtons(QDialogButtonBox* box) override;

public Q_SLOTS:
    bool accept() override;
    bool reject() override;

private:
    TaskFemAnalysisImport* m_task {nullptr};
};

}  // namespace FemGui
