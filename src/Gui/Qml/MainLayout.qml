/***************************************************************************
 *   Copyright (c) 2014 StefanTroeger <stefantroeger@gmx.net>              *
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

import QtQuick 1.1
import FreeCADLib 1.0

Rectangle {
    id:root
    property int currentIndex: 0
    anchors.fill: parent

    MDIArea {
        id: viewManager
        objectName: "mdiarea"
        nav: tabnav
        anchors.fill: parent
    }
 
    InterfaceArea {
        id: interfaceArea
        objectName: "Area"
        anchors.fill:parent
        
        InterfaceItem {
            id: navigator
            title: "Navigator"  
            objectName: "Navigator"

            area: parent
            height: titleBarHeight + 23
            minWidth:  tabnav.tabwidth
            minHeight: 20
            fixedHeight: true
            
            MDINavigator {
                id: tabnav
                tabwidth: 140    
                mdiArea: viewManager
                anchors.fill: parent
            }
        }
    }    
}
