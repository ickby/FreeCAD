// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2013 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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

#include <map>
#include <string>
#include <vector>

#include <App/DocumentObserver.h>
#include <CXX/Objects.hxx>
#include <Gui/Tree.h>

namespace Gui
{
class Document;
class ViewProviderDocumentObject;
}  // namespace Gui

namespace Fem
{
class FemAnalysis;
}

namespace FemGui
{

class ActiveAnalysisObserver: public App::DocumentObserver
{
public:
    static ActiveAnalysisObserver* instance();

    void setActiveObject(Fem::FemAnalysis*);
    Fem::FemAnalysis* getActiveObject() const;
    bool hasActiveObject() const;
    void highlightActiveObject(const Gui::HighlightMode&, bool);

    /**
     * Take up the analysis of the document that is open right now.
     *
     * Document activation is a signal, and a signal only reaches an observer
     * that already exists. The workbench is usually loaded with a document
     * already on screen, and that one was activated before there was anything
     * here to hear it, so it has to be asked about rather than waited for.
     */
    void syncToActiveDocument();

    /** Python subscribers receive slotActiveFemAnalysisUpdated(analysis_or_None). */
    void addPythonCallback(Py::Object obj);
    void removePythonCallback(Py::Object obj);

private:
    ActiveAnalysisObserver();
    ~ActiveAnalysisObserver() override;

    void slotDeletedDocument(const App::Document& Doc) override;
    void slotDeletedObject(const App::DocumentObject& Obj) override;

    /**
     * Follow the document the user is looking at.
     *
     * The active analysis is what commands act on and what the view panel
     * describes, and it was application-wide: switching document left both
     * pointing into a document that is no longer on screen, so the panel
     * described one model while the viewport showed another, and its rows went
     * on hiding elements of the document out of sight. The commands already
     * refused to act in that state, see FemCommands.active_analysis_in_active_doc.
     */
    void slotActivateDocument(const App::Document& Doc) override;

    /**
     * The analysis @a Doc should be working on, or null when it has none.
     *
     * The one the user last chose in that document if it is still there, and
     * otherwise its only analysis - one analysis is not a choice, so making it
     * the active one guesses nothing. With several and none chosen yet the
     * answer is none: picking one would silently decide where the user's next
     * object lands.
     */
    Fem::FemAnalysis* analysisForDocument(const App::Document& Doc) const;

    void emitCallbacks();

private:
    static ActiveAnalysisObserver* inst;
    Fem::FemAnalysis* activeObject {nullptr};
    Gui::ViewProviderDocumentObject* activeView {nullptr};
    Gui::Document* activeDocument {nullptr};

    std::vector<Py::Object> callbacks;
    /// Document name -> the analysis last active in it, so a return restores it
    std::map<std::string, std::string> lastPerDocument;
};

}  // namespace FemGui
