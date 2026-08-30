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

#include <functional>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

#include <boost/signals2.hpp>

#include <Mod/Fem/FemGlobal.h>

#include "FemViewTypes.h"

class vtkUnstructuredGrid;

namespace Fem
{
class FemAnalysis;
class FemGeometry;
}

namespace FemGui
{

class ViewProviderFemAnalysis;
class Classification;
struct Category;

/**
 * Runtime view state for one analysis. Not model state — mutations never
 * recompute document objects. Persistable subset (hidden elements, clip
 * planes) is mirrored onto ViewProviderFemAnalysis as Prop_Output|Prop_Hidden
 * so reloads restore it without dirtying the document or entering undo.
 */
class FemGuiExport AnalysisViewState
{
public:
    using Connection = boost::signals2::connection;
    using Slot = std::function<void()>;

    explicit AnalysisViewState(Fem::FemAnalysis* analysis);
    ~AnalysisViewState();

    Fem::FemAnalysis* analysis() const
    {
        return m_analysis;
    }

    void beginUpdate();
    void endUpdate();

    ActiveStage activeStage() const
    {
        return m_stage;
    }
    void setActiveStage(ActiveStage stage);

    DimensionMode dimensionMode() const
    {
        return m_dimensionMode;
    }
    void setDimensionMode(DimensionMode mode);

    /**
     * Whether the elements the mesher built the mesh from are in scope.
     *
     * A mesh holds more than the analysis solves: the skin triangles of a
     * volume, the edges those triangles were grown from. Off, which is the
     * default, the dimension mode selects among the analysis elements only,
     * and asking for a dimension the analysis does not have shows nothing.
     * On, it selects among every element in the mesh.
     */
    bool showConstruction() const
    {
        return m_showConstruction;
    }
    void setShowConstruction(bool on);

    bool wireframe() const
    {
        return m_wireframe;
    }
    void setWireframe(bool on);

    /**
     * Ghost overlay of the parts that the display filter removes. Renderers
     * only draw it when something is actually missing from the view, i.e. in
     * wireframe mode or with hidden elements / clip planes present.
     */
    bool overlay() const
    {
        return m_overlay;
    }
    void setOverlay(bool on);

    ColorMode colorMode(ActiveStage stage) const;
    void setColorMode(ActiveStage stage, ColorMode mode);
    ColorMode colorMode() const
    {
        return colorMode(m_stage);
    }
    void setColorMode(ColorMode mode)
    {
        setColorMode(m_stage, mode);
    }

    const std::set<std::string>& hiddenElements() const
    {
        return m_hiddenElements;
    }
    void setElementHidden(const std::string& element, bool hidden);
    void setHiddenElements(const std::set<std::string>& elements);
    bool isElementHidden(const std::string& element) const;

    const std::set<std::string>& hiddenCellTypes() const
    {
        return m_hiddenCellTypes;
    }
    void setCellTypeHidden(const std::string& cellType, bool hidden);
    bool isCellTypeHidden(const std::string& cellType) const;

    const std::map<std::string, ClippingPlane>& clipPlanes() const
    {
        return m_clipPlanes;
    }
    void setClipPlane(const std::string& name, const ClippingPlane& plane);
    void removeClipPlane(const std::string& name);

    /**
     * Classification for the active stage colour mode.
     *
     * Cached per mesh grid and colour mode, because CellType categories and
     * cell lookups are derived from the grid: several mesh view providers ask
     * for their own grid and must not be handed a classification built for
     * another mesh. Category colours stay stable across grids so the same
     * material or cell type looks the same on every mesh.
     *
     * @param meshGrid Optional VTK mesh for CellType / cell lookups.
     */
    const Classification* classification(vtkUnstructuredGrid* meshGrid = nullptr);

    /**
     * Mesh view providers announce their grid here so that consumers without a
     * grid of their own -- the view panel tree -- can still see mesh derived
     * categories such as the cell types present in the analysis.
     *
     * @param source Where the element names of the grid come from; an instance
     *               has to say so or its elements pass for native ones.
     */
    void registerMeshGrid(vtkUnstructuredGrid* meshGrid, const GridSource& source = {});
    void unregisterMeshGrid(vtkUnstructuredGrid* meshGrid);

    /**
     * Categories of the active colour mode across the whole analysis, i.e. the
     * union over all registered mesh grids. Colours are derived from the
     * category key, so they match what each individual mesh renders.
     */
    std::vector<Category> categories() const;

    /**
     * Toplevel elements where achieved mesh dim < declared analysis dim,
     * mapped to the dimension the mesh did reach.
     */
    const std::map<std::string, int>& underAchievedElements() const
    {
        return m_underAchieved;
    }
    void setUnderAchievedElements(std::map<std::string, int> elements);

    Connection connectChanged(Slot slot);

    static AnalysisViewState* forAnalysis(Fem::FemAnalysis* analysis);
    /**
     * State of @a analysis without creating one.
     *
     * For callers that may run while an analysis is being torn down, where
     * forAnalysis() would resurrect a state for a dying object.
     */
    static AnalysisViewState* find(Fem::FemAnalysis* analysis);
    static void destroyForAnalysis(Fem::FemAnalysis* analysis);
    /** True while @a state is still owned by the forAnalysis registry. */
    static bool isAlive(const AnalysisViewState* state);

    void loadFromViewProvider(ViewProviderFemAnalysis* vp);
    void saveToViewProvider(ViewProviderFemAnalysis* vp) const;

private:
    void notifyChanged();
    Fem::FemGeometry* findGeometry() const;
    /// Cheap fingerprint of what the placed instances contribute, see classification().
    std::size_t importRevision() const;
    /// Mirror the persistable subset onto the analysis view provider.
    void persist() const;
    /// Drop the cached classifications of one grid, in every colour mode.
    void forgetClassificationsOf(vtkUnstructuredGrid* meshGrid);

    Fem::FemAnalysis* m_analysis {nullptr};
    int m_batchDepth {0};
    bool m_pendingNotify {false};
    mutable bool m_pendingPersist {false};

    ActiveStage m_stage {ActiveStage::Geometry};
    DimensionMode m_dimensionMode {DimensionMode::Highest};
    bool m_showConstruction {false};
    bool m_wireframe {false};
    bool m_overlay {true};
    std::map<ActiveStage, ColorMode> m_colorMode;

    std::set<std::string> m_hiddenElements;
    std::set<std::string> m_hiddenCellTypes;
    std::map<std::string, ClippingPlane> m_clipPlanes;
    std::map<std::string, int> m_underAchieved;

    /// One classification per mesh grid; the null key serves grid-less callers.
    // Keyed by colour mode as well as by grid, because the mode belongs to the
    // stage and a switch of stage swings it back and forth. Dropping the other
    // mode's work on every switch would mean rebuilding it on the way back.
    mutable std::map<std::pair<ColorMode, vtkUnstructuredGrid*>, std::unique_ptr<Classification>>
        m_classifications;
    /// Geometry revision the cached classifications were built from
    mutable std::size_t m_classificationRevision {0};
    /// Import fingerprint the cached classifications were built from
    mutable std::size_t m_classificationImportRevision {0};
    std::map<vtkUnstructuredGrid*, GridSource> m_meshGrids;

    boost::signals2::signal<void()> m_changed;

    static std::map<Fem::FemAnalysis*, std::unique_ptr<AnalysisViewState>> s_states;
};

}  // namespace FemGui
