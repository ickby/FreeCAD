// SPDX-License-Identifier: LGPL-2.1-or-later

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

#include <CXX/Objects.hxx>
#include <QWidget>
#include <string>
#include <vector>

namespace App
{
class DocumentObject;
}

namespace FemGui
{

struct ReferenceSlotSpec
{
    std::string property = "References";
    std::string title;
    std::vector<std::string> types;
    int maxCount = 0;
    bool homogeneous = true;
    bool armed = false;
    bool promotionLatched = false;
    std::string role;
    std::string id;
    std::vector<std::string> objectKinds;
    bool allowEmptySub = false;
    std::string scope = "geometry";
};

/** Hide the Add/Remove/list chrome a .ui file still carries after the
 *  panel hosts the Python reference widget. */
void hideLegacyReferenceWidgets(QWidget* root);

/** QWidget host for femguiutils.selection_slots.from_slot_specs. */
class ReferenceSelectionWidget: public QWidget
{
    Q_OBJECT

public:
    ReferenceSelectionWidget(
        App::DocumentObject* obj,
        const std::vector<ReferenceSlotSpec>& specs,
        QWidget* parent = nullptr
    );
    ~ReferenceSelectionWidget() override;

    void finish();
    void setSlotVisible(const char* slotId, bool visible);

private:
    Py::Object m_panel;
};

}  // namespace FemGui
