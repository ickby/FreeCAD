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
#include <tuple>
#include <utility>
#include <vector>

#include <boost/signals2.hpp>

#include <Mod/Fem/FemGlobal.h>

#include "FemViewTypes.h"

class vtkUnstructuredGrid;

namespace Fem
{
class FemAnalysis;
class FemGeometry;
class FemMeshShapeGroup;
}

namespace Gui
{
class ViewProviderDocumentObject;
}

namespace FemGui
{

class ViewProviderFemAnalysis;
class Classification;
struct Category;

/**
 * Put @a vp on display mask @a mode without bringing a hidden object back.
 *
 * A mask switch writes the mode switch node itself, so an object the user hid
 * reappears the moment the stage changes the mask underneath it. Visibility is
 * what says whether an object is drawn at all and the mask only says what is
 * drawn when it is; this keeps the two in that order.
 */
FemGuiExport void setStageMask(Gui::ViewProviderDocumentObject& vp, const char* mode);

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

    /**
     * The stage on show, read off the geometry and mesh groups.
     *
     * Whether a group is drawn is its own Visibility and nothing else: the
     * user can hit space bar on it in the tree, and a stage kept alongside
     * could only ever disagree with what is on screen. Geometry wins when both
     * are shown, which is the state a document written before this reads back
     * as, and neither shown is a stage of its own that leaves the view to the
     * results. An analysis with no groups at all has nothing to read, and
     * keeps the last stage it was told.
     */
    ActiveStage activeStage() const;
    void setActiveStage(ActiveStage stage);

    /**
     * Told by a group view provider that the Visibility it owns has changed.
     *
     * @param owner the stage that group stands for. Showing it selects that
     *              stage and puts the other group away, which is what makes
     *              the space bar in the tree do what the stage buttons do.
     */
    void stageVisibilityChanged(ActiveStage owner);

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
        return colorMode(activeStage());
    }
    void setColorMode(ColorMode mode)
    {
        setColorMode(activeStage(), mode);
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

    /**
     * Every plane of the analysis, the switched off ones included.
     *
     * This is the list the user sees and the set the 3D handles are built
     * from. Anything that actually cuts geometry wants activeClipPlanes().
     */
    const std::map<std::string, ClippingPlane>& clipPlanes() const
    {
        return m_clipPlanes;
    }
    /** The planes that cut, which is what renderers care about. */
    std::map<std::string, ClippingPlane> activeClipPlanes() const;
    void setClipPlane(const std::string& name, const ClippingPlane& plane);
    void removeClipPlane(const std::string& name);
    /** Drop every plane at once, so the renderers recompute one time. */
    void clearClipPlanes();

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
    Fem::FemMeshShapeGroup* findMeshGroup() const;
    /// The stage the group visibilities spell out, see activeStage().
    ActiveStage readStage() const;
    /// Show the group the current stage belongs to and hide the other one.
    void applyStageToGroups();
    /// Cheap fingerprint of what the placed instances contribute, see classification().
    std::size_t importRevision() const;
    /// Analysis-wide key -> palette index for @a mode; see classification().
    const std::map<std::string, int>& paletteOrder(ColorMode mode, bool withMesh);
    /// Rebuild the palette-order map for @a mode from geometry, imports and mesh.
    void rebuildPaletteOrder(ColorMode mode, bool withMesh);
    /// Mirror the persistable subset onto the analysis view provider.
    void persist() const;
    /// Drop the cached classifications of one grid, in every colour mode.
    void forgetClassificationsOf(vtkUnstructuredGrid* meshGrid);

    Fem::FemAnalysis* m_analysis {nullptr};
    int m_batchDepth {0};
    bool m_pendingNotify {false};
    mutable bool m_pendingPersist {false};

    /// The stage as last read, kept for the groups an analysis does not build
    mutable ActiveStage m_stage {ActiveStage::Geometry};
    /// Set while the group visibilities are being written from m_stage
    bool m_writingStage {false};
    DimensionMode m_dimensionMode {DimensionMode::Highest};
    bool m_showConstruction {false};
    bool m_wireframe {false};
    bool m_overlay {true};
    std::map<ActiveStage, ColorMode> m_colorMode;

    std::set<std::string> m_hiddenElements;
    std::set<std::string> m_hiddenCellTypes;
    std::map<std::string, ClippingPlane> m_clipPlanes;
    std::map<std::string, int> m_underAchieved;

    /// One classification per (mode, stage, mesh grid); null grid serves
    /// grid-less callers. Stage is part of the key because Component means
    /// geometry components in the Geometry stage and mesh components in the
    /// Mesh stage, and the two must not share a cached classification.
    mutable std::map<
        std::tuple<ColorMode, ActiveStage, vtkUnstructuredGrid*>,
        std::unique_ptr<Classification>>
        m_classifications;
    /// Geometry revision the cached classifications were built from
    mutable std::size_t m_classificationRevision {0};
    /// Import fingerprint the cached classifications were built from
    mutable std::size_t m_classificationImportRevision {0};
    /// Mesh topology revision the cached classifications were built from
    mutable std::size_t m_classificationMeshRevision {0};
    /// Analysis-wide key -> palette index, per colour mode and with or without
    /// the mesh keys. The mesh keys are only ever appended behind the geometry
    /// ones, so a key the geometry names lands on the same colour in both, and
    /// the Geometry stage can be served without merging the mesh to find out.
    mutable std::map<std::pair<ColorMode, bool>, std::map<std::string, int>> m_paletteOrder;
    std::map<vtkUnstructuredGrid*, GridSource> m_meshGrids;

    boost::signals2::signal<void()> m_changed;

    static std::map<Fem::FemAnalysis*, std::unique_ptr<AnalysisViewState>> s_states;
};

}  // namespace FemGui
