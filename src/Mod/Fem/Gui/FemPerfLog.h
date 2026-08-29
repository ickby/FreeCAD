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

#include <chrono>
#include <cstddef>
#include <map>
#include <string>
#include <vector>

#include <Mod/Fem/FemGlobal.h>

namespace FemGui
{

/**
 * Stopwatch for the stages of the FEM view pipeline.
 *
 * Drawing an analysis goes through a chain of VTK filters and ends in a scene
 * graph, and a report of what took how long is the only way to tell which of
 * the two an operation is waiting for. The stages mark themselves with
 * FEM_PERF_SCOPE() and the log adds up what they cost, so that a run of the
 * benchmark in femtest/perf answers the question by name rather than by guess.
 *
 * Off unless a measurement asked for it, and single threaded: the pipeline runs
 * on the GUI thread, and the log is not worth a lock that everything else would
 * pay for.
 */
class FemGuiExport PerfLog
{
public:
    struct Entry
    {
        std::string name;
        /** How often the stage ran. */
        std::size_t count {0};
        /** Seconds spent in the stage, including the stages nested in it. */
        double total {0.0};
        /** Seconds spent in the stage itself, with the nested ones taken out. */
        double self {0.0};
    };

    static PerfLog& instance();

    void setEnabled(bool on)
    {
        m_enabled = on;
    }
    bool isEnabled() const
    {
        return m_enabled;
    }

    void clear();
    /** What was measured, in the order the stages were first seen. */
    std::vector<Entry> report() const;

    void add(const char* name, double seconds, double nested);

private:
    bool m_enabled {false};
    std::vector<Entry> m_entries;
    std::map<std::string, std::size_t> m_index;
};

/** Times the block it lives in and books it under *name*. */
class FemGuiExport PerfScope
{
public:
    explicit PerfScope(const char* name);
    ~PerfScope();
    PerfScope(const PerfScope&) = delete;
    PerfScope& operator=(const PerfScope&) = delete;

private:
    const char* m_name {nullptr};
    PerfScope* m_parent {nullptr};
    std::chrono::steady_clock::time_point m_start;
    /** Seconds the stages nested in this one took. */
    double m_nested {0.0};
};

}  // namespace FemGui

#define FEM_PERF_CONCAT_(a, b) a##b
#define FEM_PERF_CONCAT(a, b) FEM_PERF_CONCAT_(a, b)
/** Book the enclosing block under *name* while the perf log is on. */
#define FEM_PERF_SCOPE(name) const FemGui::PerfScope FEM_PERF_CONCAT(femPerfScope, __LINE__)(name)
