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

#pragma once

#include <Gui/DocumentObserver.h>
#include <Gui/Selection/Selection.h>
#include <Gui/TaskView/TaskDialog.h>
#include <Gui/TaskView/TaskView.h>
#include <Mod/Fem/FemGlobal.h>

#include "ViewProviderFemConstraint.h"
#include "ReferenceSelectionWidget.h"


namespace FemGui
{

class TaskFemConstraint: public Gui::TaskView::TaskBox, public Gui::SelectionObserver
{
    Q_OBJECT

public:
    explicit TaskFemConstraint(
        ViewProviderFemConstraint* ConstraintView,
        QWidget* parent = nullptr,
        const char* pixmapname = ""
    );
    ~TaskFemConstraint() override;

    const std::string getScale() const;

protected:
    void changeEvent(QEvent* e) override
    {
        TaskBox::changeEvent(e);
    }
    void onSelectionChanged(const Gui::SelectionChanges&) override
    {}
    void addReferenceSelection(const std::vector<ReferenceSlotSpec>& specs, QWidget* host = nullptr);

protected:
    QWidget* proxy;
    Gui::WeakPtrT<ViewProviderFemConstraint> ConstraintView;
    ReferenceSelectionWidget* m_references = nullptr;
};

/// simulation dialog for the TaskView
class TaskDlgFemConstraint: public Gui::TaskView::TaskDialog
{
    Q_OBJECT

public:
    /// is called the TaskView when the dialog is opened
    void open() override;
    bool accept() override;
    /// is called by the framework if the dialog is rejected (Cancel)
    bool reject() override;

    bool isAllowedAlterDocument() const override
    {
        return false;
    }

    /// returns for Close and Help button
    QDialogButtonBox::StandardButtons getStandardButtons() const override
    {
        return QDialogButtonBox::Ok | QDialogButtonBox::Cancel;
    }

    ViewProviderFemConstraint* getConstraintView() const
    {
        return ConstraintView;
    }

protected:
    ViewProviderFemConstraint* ConstraintView;
    TaskFemConstraint* parameter;
};

}  // namespace FemGui
