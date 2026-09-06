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

namespace App
{
class DocumentObject;
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
 * Start following what the user edits, so the view state can open a scope for it.
 *
 * Called once when the workbench module loads. Every task panel is reached
 * through the same edit-mode signals, so nothing else in the workbench has to
 * know about edit scopes at all.
 */
FemGuiExport void observeEditScopes();

/**
 * The geometry an open panel for @a edited is picked on, or null when @a edited
 * is no geometry at all.
 *
 * A build step that stores element references stores them against the geometry
 * it was handed, not against the one it produces - a partition names the faces
 * of its input - so that input is what has to be on show for the panel to be
 * usable, and what the view panel has to list. A step that stores no such
 * references produces geometry rather than altering it, and there the answer is
 * the step itself: what a geometry import is edited for is what it imports.
 *
 * Told apart by the element property, the same way intentFor() tells a panel
 * that will ask for a pick from one that will not. Answering it here rather
 * than in each setEdit() is what stopped the import from having no answer at
 * all, which is how it came to rely on the group happening to draw the same
 * shape.
 */
FemGuiExport App::DocumentObject* editSubjectFor(App::DocumentObject* edited);

/**
 * The colour modes, in the order a chooser should offer them.
 *
 * Which modes there are, what each is called, and which of them mean anything
 * in a given stage are three things the view state decides and everything else
 * - the Python wrapper, the view panel's combo box - has to be told. They were
 * spelled out again in each of those places, so adding a mode meant finding
 * every list that had to grow, and forgetting one left a mode that could be
 * chosen but not honoured.
 */
FemGuiExport const std::vector<ColorMode>& allColorModes();

/**
 * Whether @a mode says anything about what @a stage draws.
 *
 * CellType names the kinds of element a mesh is built from, so it has nothing
 * to say about a stage that is not showing the mesh. setColorMode() enforces
 * this; a chooser asks so that it can grey the entry out rather than let the
 * user pick something that springs back.
 */
FemGuiExport bool colorModeAppliesTo(ColorMode mode, ActiveStage stage);

/// The name @a mode goes by in Python and in the view panel.
FemGuiExport const char* colorModeName(ColorMode mode);
/// The mode @a name stands for, Subelement for anything unrecognised.
FemGuiExport ColorMode colorModeFromName(const std::string& name);

/// The name @a stage goes by in Python and in the view panel.
FemGuiExport const char* activeStageName(ActiveStage stage);
/// The stage @a name stands for, Geometry for anything unrecognised.
FemGuiExport ActiveStage activeStageFromName(const std::string& name);

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
     * Open an edit scope for @a edited.
     *
     * A task panel is about one object, and what the view has to show while it
     * is open follows from what the panel asks for rather than from whatever
     * the panel's command happened to switch on the way in. The scope puts the
     * view where @a intent needs it, remembers what it changed, and endEdit()
     * puts it back. Nothing here is persisted: an edit is not a state the
     * document comes back in.
     *
     * Only one scope is open at a time, which is all FreeCAD's edit mode
     * allows. A second call closes the first and warns.
     */
    void beginEdit(App::DocumentObject* edited, EditIntent intent);

    /**
     * Close the scope of @a edited and put back what it changed.
     *
     * A stage the user chose while the panel was open is theirs and stays;
     * only a stage still standing as this scope left it is restored. Closing a
     * scope that is not open, which an unsetEdit for an object that never
     * opened one does, is a no-op.
     */
    void endEdit(App::DocumentObject* edited);

    /// The object whose panel is open, or null when none is.
    App::DocumentObject* editedObject() const
    {
        return m_editedObject;
    }

    /// What the open edit scope asked the view for; None when none is open.
    EditIntent editIntent() const
    {
        return m_editIntent;
    }

    /**
     * The geometry on show for the open panel, or null when none is open.
     *
     * The one answer to "which geometry is the user looking at and picking on
     * right now", read by the geometry view providers to know which of them
     * draws, by the group to know that it has to step aside, and by the view
     * panel to know whose elements to list. See editSubjectFor().
     */
    App::DocumentObject* editSubject() const
    {
        return m_editSubject;
    }

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

    /**
     * Tell the followers that the geometry chain has been rebuilt.
     *
     * What a build step is, which of them the group takes its result from, and
     * which of them is drawn all follow from the membership of the chain, and
     * every geometry view provider works its own answer out. It only has to be
     * told that the answers may have changed, which the group is the only one
     * to hear: the members get no property change of their own for joining or
     * leaving. Named rather than notifying outright, so the caller says what
     * happened instead of what should be done about it.
     */
    void chainChanged();

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

    /// Object whose task panel is open, null when none is. Never persisted.
    App::DocumentObject* m_editedObject {nullptr};
    App::DocumentObject* m_editSubject {nullptr};
    EditIntent m_editIntent {EditIntent::None};
    /// Stage to go back to when the scope closes
    ActiveStage m_editStageBefore {ActiveStage::Geometry};
    /// Stage the scope put the view in, to tell a restore from a user choice
    ActiveStage m_editStageApplied {ActiveStage::NoStage};
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

/**
 * One follower's connection to the view state of the analysis it belongs to.
 *
 * Following a state is never done once. A view provider or a render helper is
 * built before the object it draws is in an analysis, so the state it has to
 * follow is only reachable later; and the object can be moved to another
 * analysis afterwards, which makes the state it was following the wrong one.
 * Every follower therefore has to ask again whether the state it holds is
 * still the state it wants, and rebind when it is not.
 *
 * Written out by hand at each place that needed it, that rule came out
 * differently every time - some rebound on a changed state, some only ever
 * connected once and kept following an analysis the object had left, some
 * would not reconnect a connection that had been dropped. This holds the rule
 * once. isBoundTo() answers "is there anything to do", bind() does it, and
 * release() gives the state back one last time so that a follower with
 * something to hand in can do so before the state is let go of.
 */
class FemGuiExport ViewStateBinding
{
public:
    ViewStateBinding() = default;
    ~ViewStateBinding();

    ViewStateBinding(const ViewStateBinding&) = delete;
    ViewStateBinding& operator=(const ViewStateBinding&) = delete;

    /// Whether @a state is already being followed, connection and all.
    bool isBoundTo(const AnalysisViewState* state) const;

    /// Follow @a state, calling @a onChanged whenever it changes. Replaces any binding.
    void bind(AnalysisViewState* state, AnalysisViewState::Slot onChanged);

    /**
     * Stop being called about changes and give the state back, or null when
     * none was bound.
     *
     * The state is returned rather than dropped silently because a follower
     * that registered something with it - a mesh grid, say - has to take that
     * back, and this is its last chance to name what it is taking it back from.
     */
    AnalysisViewState* release();

    /**
     * The state being followed, or null once it is gone.
     *
     * Gated on the connection rather than handing the pointer back plainly: a
     * state is destroyed with the analysis it belongs to, and destroying it
     * takes its signal with it, so a dropped connection is exactly how a
     * follower finds out. Handing the raw pointer out instead let a geometry
     * object that outlived its analysis read from freed memory.
     */
    AnalysisViewState* state() const
    {
        return m_conn.connected() ? m_state : nullptr;
    }

    explicit operator bool() const
    {
        return state() != nullptr;
    }

private:
    AnalysisViewState* m_state {nullptr};
    AnalysisViewState::Connection m_conn;
};

}  // namespace FemGui
