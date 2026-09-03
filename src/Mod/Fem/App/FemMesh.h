// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2009 Jürgen Riegel <juergen.riegel@web.de>              *
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
#include <list>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

#include <SMDSAbs_ElementType.hxx>
#include <SMESH_Version.h>

#include <App/ComplexGeoData.h>
#include <Base/Matrix.h>
#include <Base/Quantity.h>
#include <Mod/Fem/FemGlobal.h>


class SMESH_Gen;
class SMESH_Mesh;
class SMESH_Hypothesis;
class TopoDS_Shape;
class TopoDS_Face;
class TopoDS_Edge;
class TopoDS_Vertex;
class TopoDS_Solid;

namespace Fem
{

class FemGeometry;

enum class ABAQUS_VolumeVariant
{
    Standard,
    Reduced,
    Incompatible,
    Modified,
    Fluid
};
enum class ABAQUS_FaceVariant
{
    Shell,
    Shell_Reduced,
    Membrane,
    Membrane_Reduced,
    Stress,
    Stress_Reduced,
    Strain,
    Strain_Reduced,
    Axisymmetric,
    Axisymmetric_Reduced
};
enum class ABAQUS_EdgeVariant
{
    Beam,
    Beam_Reduced,
    Truss,
    Network
};

using SMESH_HypothesisPtr = std::shared_ptr<SMESH_Hypothesis>;

/** The representation of a FemMesh
 */
class FemExport FemMesh: public Data::ComplexGeoData
{
    TYPESYSTEM_HEADER_WITH_OVERRIDE();

public:
    FemMesh();
    FemMesh(const FemMesh&);

    /**
     * Takes the mesh over instead of building it again.
     *
     * A copy re-adds every node and every element one at a time, which on a
     * mesh of any size costs about as much as whatever produced it. A mesh that
     * has been moved from owns nothing and is only good for destruction or for
     * being assigned to again.
     */
    FemMesh(FemMesh&&) noexcept;
    ~FemMesh() override;

    FemMesh& operator=(const FemMesh&);
    FemMesh& operator=(FemMesh&&) noexcept;
    const SMESH_Mesh* getSMesh() const;
    SMESH_Mesh* getSMesh();
    static SMESH_Gen* getGenerator();
    void addHypothesis(const TopoDS_Shape& aSubShape, SMESH_HypothesisPtr hyp);
    void setStandardHypotheses();
    template<typename T>
    SMESH_HypothesisPtr createHypothesis(int hypId);

    void compute();

    // from base class
    unsigned int getMemSize() const override;
    void Save(Base::Writer& /*writer*/) const override;
    void Restore(Base::XMLReader& /*reader*/) override;
    void SaveDocFile(Base::Writer& writer) const override;
    void RestoreDocFile(Base::Reader& reader) override;

    /** @name Subelement management */
    //@{
    /** Sub type list
     *  List of different subelement types
     *  it is NOT a list of the subelements itself
     */
    std::vector<const char*> getElementTypes() const override;
    unsigned long countSubElements(const char* Type) const override;
    /// get the subelement by type and number
    Data::Segment* getSubElement(const char* Type, unsigned long) const override;
    /** Get points from object with given accuracy */
    void getPoints(
        std::vector<Base::Vector3d>& Points,
        std::vector<Base::Vector3d>& Normals,
        double Accuracy,
        uint16_t flags = 0
    ) const override;
    //@}

    /** @name search and retrieval */
    //@{
    /// retrieving by region growing
    std::set<long> getSurfaceNodes(long ElemId, short FaceId, float Angle = 360) const;
    /// retrieving by solid
    std::set<int> getNodesBySolid(const TopoDS_Solid& solid) const;
    /// retrieving by face
    std::set<int> getNodesByFace(const TopoDS_Face& face) const;
    /// retrieving by edge
    std::set<int> getNodesByEdge(const TopoDS_Edge& edge) const;
    /// retrieving by vertex
    std::set<int> getNodesByVertex(const TopoDS_Vertex& vertex) const;
    /// retrieving node IDs by element ID
    std::list<int> getElementNodes(int id) const;
    /// retrieving elements IDs by node ID
    std::list<int> getNodeElements(int id, SMDSAbs_ElementType type = SMDSAbs_All) const;
    /// retrieving face IDs number by face
    std::list<int> getFacesByFace(const TopoDS_Face& face) const;
    /// retrieving edge IDs number by edge
    std::list<int> getEdgesByEdge(const TopoDS_Edge& edge) const;
    /// retrieving volume IDs and face IDs number by face
    std::list<std::pair<int, int>> getVolumesByFace(const TopoDS_Face& face) const;
    /// retrieving volume IDs and CalculiX face number by face
    std::map<int, int> getccxVolumesByFace(const TopoDS_Face& face) const;
    /// retrieving IDs of edges not belonging to any face (and thus not belonging to any volume too)
    std::set<int> getEdgesOnly() const;
    /// retrieving IDs of faces not belonging to any volume
    std::set<int> getFacesOnly() const;

    /**
     * Element IDs kept by the per-entity "highest" export filter (elemParam=1 / highest=true).
     *
     * With FemGeometry and Solid/Face/Edge/Vertex entity groups: keep cell e when
     * getEntityDimensionMask(entity(e)) has bit celldim(e) set (same rule as Stage 6 dimmask).
     * Without geometry: if entity groups exist, keep cells at the max cell dimension of their
     * entity group, dropping Face/Edge/Vertex cells that are topologically owned by higher
     * elements (free-face / free-edge rule). If no entity groups: volumes + getFacesOnly +
     * getEdgesOnly (+ free 0D when nothing else).
     */
    std::set<int> getHighestElements(const FemGeometry* geometry = nullptr) const;
    //@}

    /** @name Placement control */
    //@{
    /// set the transformation
    void setTransform(const Base::Matrix4D& rclTrf) override;
    /// get the transformation
    Base::Matrix4D getTransform() const override;
    /// Bound box from the shape
    Base::BoundBox3d getBoundBox() const override;
    /// get the volume (when there are volume elements)
    Base::Quantity getVolume() const;
    //@}

    /** @name Modification */
    //@{
    /// Applies a transformation on the real geometric data type
    void transformGeometry(const Base::Matrix4D& rclMat) override;
    /**
     * Removes elements and the nodes they leave behind.
     *
     * Groups lose the removed elements, groups that end up empty are dropped.
     * Ids of the remaining elements and nodes are kept. Returns the number of
     * removed elements.
     */
    int removeElements(const std::vector<int>& ids);
    //@}

    /** @name Group management */
    //@{
    /// Adds group to mesh
    int addGroup(const std::string, const std::string, const int = -1);
    /// Adds elements to group (int due to int used by raw SMESH functions)
    void addGroupElements(int, const std::set<int>&);
    /// Remove group (Name due to similarity to SMESH basis functions)
    bool removeGroup(int);
    /// Rename group
    void renameGroup(int id, const std::string& name);
    //@}


    struct FemMeshInfo
    {
        int numFaces;
        int numNode;
        int numTria;
        int numQuad;
        int numPoly;
        int numVolu;
        int numTetr;
        int numHexa;
        int numPyrd;
        int numPris;
        int numHedr;
    };

    ///
    struct FemMeshInfo getInfo() const;

    /// import from files
    void read(const char* FileName);
    // import vtk file, and interprets the vtk_group_cell_array
    // as group indicator. A group will be created for each unique entry in
    // the cell data array, the name is the entry. Int and String array are
    // supported. String array creates groups names according to the string,
    // int array leads to groups with the string version of the integer as name.
    void readVTKWithGroups(const char* FileName, const char* vtk_group_cell_array);

    void write(const char* FileName) const;
    void writeABAQUS(
        const std::string& Filename,
        int elemParam,
        bool groupParam,
        ABAQUS_VolumeVariant volVariant = ABAQUS_VolumeVariant::Standard,
        ABAQUS_FaceVariant faceVariant = ABAQUS_FaceVariant::Shell,
        ABAQUS_EdgeVariant edgeVariant = ABAQUS_EdgeVariant::Beam,
        const std::set<int>* elementIds = nullptr
    ) const;
    void writeVTK(const std::string& FileName, bool highest = true) const;
    // write vtk file, and writes the groups into the provided cell array.
    // If name_to_id is empty the created cell data array is a vtkStringArray,
    // and the group name is used as entry for each element. If the map is provided
    // a vtkIntArray is created and the mapped int is used as entry.
    // The following limitations apply:
    //        1. Only element/cell groups are supported, no node groups and no mixed groups
    //        2. Elements can only be in a single group, groups can not overlap
    //        3. Element IDs in the mesh need to be continuous and start with ID 1
    void writeVTKWithGroups(
        const std::string& FileName,
        const std::string& vtk_group_cell_array,
        std::map<std::string, int> name_to_id,
        bool highest = true
    );
    void writeZ88(const std::string& FileName) const;

    /**
     * Append another mesh's nodes, elements and groups into this mesh.
     * Child placement is applied to node coordinates (group frame stays identity).
     * Groups with the same name and type are unioned, not duplicated.
     * New nodes/elements get contiguous IDs assigned by SMESH.
     * If sourceName and cellSources are set, each new element appends sourceName
     * to cellSources (provenance).
     */
    void appendMeshData(
        const FemMesh& mesh,
        const std::string& sourceName = {},
        std::vector<std::string>* cellSources = nullptr
    );

    /**
     * Append with an explicit node transform and optional mesh-group renamer.
     * When transformOverride is null, mesh.getTransform() is used.
     * When groupRenamer is set, SMESH group names are mapped before merge; a
     * group whose mapped name is empty is dropped.
     * When nodeIdMap is set, it receives source node ID -> appended node ID,
     * which is the only way back from a merged node to where it came from.
     * When cellSourceIds is set, it receives the source element ID of every
     * appended cell, in the order the cells were appended. It is the only way to
     * carry per-element data of the source over to the merged mesh, because an
     * element which SMESH refuses would otherwise shift everything behind it.
     * When appendedNodeIds is set, it receives the merged node ID of every
     * source node, in the order the nodes were appended. That order is what
     * lets a later pass find the merged node a source node became without
     * carrying a map per child.
     */
    void appendMeshData(
        const FemMesh& mesh,
        const std::string& sourceName,
        std::vector<std::string>* cellSources,
        const Base::Matrix4D* transformOverride,
        const std::function<std::string(const std::string&)>* groupRenamer,
        std::map<int, int>* nodeIdMap = nullptr,
        std::vector<int>* cellSourceIds = nullptr,
        std::vector<int>* appendedNodeIds = nullptr
    );

private:
    void copyMeshData(const FemMesh&);
    void readNastran(const std::string& Filename);
    void readNastran95(const std::string& Filename);
    void readZ88(const std::string& Filename);
    void readAbaqus(const std::string& Filename);

private:
    /// positioning matrix
    Base::Matrix4D _Mtrx;
    SMESH_Mesh* myMesh;
#if SMESH_VERSION_MAJOR < 9
    const int myStudyId;
#endif

    std::list<SMESH_HypothesisPtr> hypoth;
    static SMESH_Gen* _mesh_gen;
};


template<typename T>
inline SMESH_HypothesisPtr FemMesh::createHypothesis(int hypId)
{
    SMESH_Gen* myGen = getGenerator();
#if SMESH_VERSION_MAJOR >= 9
    SMESH_HypothesisPtr hypo(new T(hypId, myGen));
#else
    // use own StudyContextStruct
    SMESH_HypothesisPtr hypo(new T(hypId, myStudyId, myGen));
#endif
    return hypo;
}

}  // namespace Fem
