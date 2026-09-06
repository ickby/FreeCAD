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

#include "PreCompiled.h"

#include <memory>
#include <optional>
#include <vector>

#include "FemPerfLog.h"

using namespace Fem;

namespace
{
/** The stage currently being timed, so a nested one can be booked to it. */
thread_local PerfScope* activeScope = nullptr;

/**
 * A stage opened by name rather than by a block going out of scope.
 *
 * The name has to outlive the PerfScope that points at it, and the scope has to
 * keep the address it was constructed with, which is why these are held one per
 * allocation rather than in a vector of values that would move underneath them.
 */
struct ScriptScope
{
    std::string name;
    std::optional<PerfScope> scope;
};

thread_local std::vector<std::unique_ptr<ScriptScope>> scriptScopes;
}  // namespace

PerfLog& PerfLog::instance()
{
    static PerfLog log;
    return log;
}

void PerfLog::clear()
{
    m_entries.clear();
    m_index.clear();
}

std::vector<PerfLog::Entry> PerfLog::report() const
{
    return m_entries;
}

void PerfLog::add(const char* name, double seconds, double nested)
{
    auto [it, inserted] = m_index.try_emplace(name, m_entries.size());
    if (inserted) {
        m_entries.push_back(Entry {name, 0, 0.0, 0.0});
    }
    Entry& entry = m_entries[it->second];
    entry.count += 1;
    entry.total += seconds;
    entry.self += seconds - nested;
}

PerfScope::PerfScope(const char* name)
{
    if (!PerfLog::instance().isEnabled()) {
        return;
    }
    m_name = name;
    m_parent = activeScope;
    m_start = std::chrono::steady_clock::now();
    activeScope = this;
}

PerfScope::~PerfScope()
{
    if (!m_name) {
        return;
    }
    const std::chrono::duration<double> elapsed = std::chrono::steady_clock::now() - m_start;
    activeScope = m_parent;
    if (m_parent) {
        m_parent->m_nested += elapsed.count();
    }
    PerfLog::instance().add(m_name, elapsed.count(), m_nested);
}

void Fem::perfBeginScope(const std::string& name)
{
    // Pushed even while the log is off, so that the matching end has something
    // to take off the stack and a measurement can be switched on mid-run
    // without the stack going out of step.
    auto opened = std::make_unique<ScriptScope>();
    opened->name = name;
    opened->scope.emplace(opened->name.c_str());
    scriptScopes.push_back(std::move(opened));
}

void Fem::perfEndScope()
{
    if (scriptScopes.empty()) {
        return;
    }
    // The PerfScope books the stage as it is destroyed, and the name it points
    // at has to still be there while that happens.
    scriptScopes.pop_back();
}
