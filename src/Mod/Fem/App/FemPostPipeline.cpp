/***************************************************************************
 *   Copyright (c) 2015 Stefan Tröger <stefantroeger@gmx.net>              *
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

#ifndef _PreComp_
#include <Python.h>
#include <vtkAppendFilter.h>
#include <vtkDataSetReader.h>
#include <vtkImageData.h>
#include <vtkRectilinearGrid.h>
#include <vtkStructuredGrid.h>
#include <vtkUnstructuredGrid.h>
#include <vtkXMLImageDataReader.h>
#include <vtkXMLPUnstructuredGridReader.h>
#include <vtkXMLPolyDataReader.h>
#include <vtkXMLRectilinearGridReader.h>
#include <vtkXMLStructuredGridReader.h>
#include <vtkXMLUnstructuredGridReader.h>
#include <vtkMultiBlockDataSet.h>
#include <vtkStreamingDemandDrivenPipeline.h>
#include <vtkPointData.h>
#include <vtkFloatArray.h>
#include <vtkStringArray.h>
#endif

#include <Base/Console.h>
#include <cmath>
#include <QString>

#include "FemMesh.h"
#include "FemMeshObject.h"
#include "FemPostFilter.h"
#include "FemPostPipeline.h"
#include "FemPostPipelinePy.h"
#include "FemVTKTools.h"


using namespace Fem;
using namespace App;


vtkStandardNewMacro(FemStepSourceAlgorithm);

FemStepSourceAlgorithm::FemStepSourceAlgorithm::FemStepSourceAlgorithm()
{
    // we are a source
    SetNumberOfInputPorts(0);
    SetNumberOfOutputPorts(1);
}


FemStepSourceAlgorithm::FemStepSourceAlgorithm::~FemStepSourceAlgorithm()
{
}

void FemStepSourceAlgorithm::setDataObject(vtkSmartPointer<vtkDataObject> data ) {
    m_data = data;
    Update();
}


std::vector<double> FemStepSourceAlgorithm::getStepValues()
{

    // check if we have step data
    if (!m_data || !m_data->IsA("vtkMultiBlockDataSet")) {
        return std::vector<double>();
    }

    // we have multiple steps! let's check the amount and times
    vtkSmartPointer<vtkMultiBlockDataSet> multiblock = vtkMultiBlockDataSet::SafeDownCast(m_data);

    unsigned long nblocks = multiblock->GetNumberOfBlocks();
    std::vector<double> tSteps(nblocks);

    for (unsigned long i=0; i<nblocks; i++) {

        vtkDataObject* block = multiblock->GetBlock(i);
        // check if the TimeValue field is available
        if (!block->GetFieldData()->HasArray("TimeValue")) {
            break;
        }

        //store the time value!
        vtkDataArray* TimeValue = block->GetFieldData()->GetArray("TimeValue");
        if (!TimeValue->IsA("vtkFloatArray") ||
            TimeValue->GetNumberOfTuples() < 1) {
            break;
        }

        tSteps[i] = vtkFloatArray::SafeDownCast(TimeValue)->GetValue(0);
    }

    if (tSteps.size() != nblocks) {
        // not every block had time data
        return std::vector<double>();
    }

    return tSteps;
}

int FemStepSourceAlgorithm::RequestInformation(vtkInformation*reqInfo, vtkInformationVector **inVector, vtkInformationVector* outVector)
{

    if (!this->Superclass::RequestInformation(reqInfo, inVector, outVector))
    {
        return 0;
    }


    std::stringstream strm;
    outVector->Print(strm);
    Base::Console().Message("Request data:\n%s\n", strm.str());

    std::vector<double> steps = getStepValues();

    if (steps.empty()) {
        Base::Console().Message("Not fuly setup with time values\n");
        return 1;
    }

    double tRange[2] = {steps.front(), steps.back()};
    double tSteps[steps.size()];
    std::copy(steps.begin(), steps.end(), tSteps);

    // finally set the time info!
    vtkInformation* info = outVector->GetInformationObject(0);
    info->Set(vtkStreamingDemandDrivenPipeline::TIME_RANGE(), tRange, 2);
    info->Set(vtkStreamingDemandDrivenPipeline::TIME_STEPS(), tSteps, steps.size());
    info->Set(CAN_HANDLE_PIECE_REQUEST(), 1);

    return 1;
}

int FemStepSourceAlgorithm::RequestData(vtkInformation* reqInfo, vtkInformationVector** inVector, vtkInformationVector* outVector)
{

    std::stringstream strstm;
    outVector->Print(strstm);
    Base::Console().Message("Request Data out Vector: %s\n", strstm.str());

    vtkInformation* outInfo = outVector->GetInformationObject(0);
    vtkUnstructuredGrid* output = vtkUnstructuredGrid::SafeDownCast(outInfo->Get(vtkDataObject::DATA_OBJECT()));

    if (!output || !m_data) {
        return 0;
    }

    if (!m_data->IsA("vtkMultiBlockDataSet")) {
        // no multi step data, return directly
        outInfo->Set(vtkDataObject::DATA_OBJECT(), m_data);
        return 1;
    }

    vtkSmartPointer<vtkMultiBlockDataSet> multiblock = vtkMultiBlockDataSet::SafeDownCast(m_data);
    // find the block asked for (lazy implementation)
    unsigned long idx = 0;
    if (outInfo->Has(vtkStreamingDemandDrivenPipeline::UPDATE_TIME_STEP()))
    {
        auto time = outInfo->Get(vtkStreamingDemandDrivenPipeline::UPDATE_TIME_STEP());
        auto steps = getStepValues();

        // we have float values, so be aware of roundign erros. lets subtract the searched time and then use the smalles value
        for(auto& step : steps)
            step = std::abs(step-time);

        auto it = std::min_element(std::begin(steps), std::end(steps));
        idx = std::distance(std::begin(steps), it);
    }

    auto block = multiblock->GetBlock(idx);
    output->ShallowCopy(block);
    return 1;
}



PROPERTY_SOURCE(Fem::FemPostPipeline, Fem::FemPostObject)
const char* FemPostPipeline::ModeEnums[] = {"Serial", "Parallel", nullptr};

FemPostPipeline::FemPostPipeline() : Fem::FemPostObject(), App::GroupExtension()
{
    GroupExtension::initExtension(this);

    ADD_PROPERTY_TYPE(Functions,
                      (nullptr),
                      "Pipeline",
                      App::Prop_Hidden,
                      "The function provider which groups all pipeline functions");
    ADD_PROPERTY_TYPE(Mode,
                      (long(0)),
                      "Pipeline",
                      App::Prop_None,
                      "Selects the pipeline data transition mode.\n"
                      "In serial, every filter gets the output of the previous one as input.\n"
                      "In parallel, every filter gets the pipeline source as input.\n");
    ADD_PROPERTY_TYPE(Step,
                      (long(0)),
                      "Pipeline",
                      App::Prop_None,
                      "The step used to calculate the data in the pipeline processing (read only, set via pipeline object).");

    Mode.setEnums(ModeEnums);

    // create our source algorithm
    m_source_algorithm = vtkSmartPointer<FemStepSourceAlgorithm>::New();
}

FemPostPipeline::~FemPostPipeline() = default;

short FemPostPipeline::mustExecute() const
{
    if (Mode.isTouched() ) {
        return 1;
    }

    return FemPostObject::mustExecute();
}

vtkDataSet* FemPostPipeline::getDataSet() {

    vtkDataObject* data = m_source_algorithm->GetOutputDataObject(0);
    if (!data) {
        return nullptr;
    }

    if (data->IsA("vtkDataSet")) {
        return vtkDataSet::SafeDownCast(data);
    }

    return nullptr;
}

bool FemPostPipeline::canRead(Base::FileInfo File)
{

    // from FemResult only unstructural mesh is supported in femvtktoools.cpp
    return File.hasExtension({"vtk", "vtp", "vts", "vtr", "vti", "vtu", "pvtu"});
}

void FemPostPipeline::read(Base::FileInfo File)
{

    // checking on the file
    if (!File.isReadable()) {
        throw Base::FileException("File to load not existing or not readable", File);
    }

    if (File.hasExtension("vtu")) {
        readXMLFile<vtkXMLUnstructuredGridReader>(File.filePath());
    }
    else if (File.hasExtension("pvtu")) {
        readXMLFile<vtkXMLPUnstructuredGridReader>(File.filePath());
    }
    else if (File.hasExtension("vtp")) {
        readXMLFile<vtkXMLPolyDataReader>(File.filePath());
    }
    else if (File.hasExtension("vts")) {
        readXMLFile<vtkXMLStructuredGridReader>(File.filePath());
    }
    else if (File.hasExtension("vtr")) {
        readXMLFile<vtkXMLRectilinearGridReader>(File.filePath());
    }
    else if (File.hasExtension("vti")) {
        readXMLFile<vtkXMLImageDataReader>(File.filePath());
    }
    else if (File.hasExtension("vtk")) {
        readXMLFile<vtkDataSetReader>(File.filePath());
    }
    else {
        throw Base::FileException("Unknown extension");
    }
}

void FemPostPipeline::scale(double s)
{
    Data.scale(s);
    onChanged(&Data);
}

void FemPostPipeline::onChanged(const Property* prop)
{
   /* onChanged handles the Pipeline setup: we connect the inputs and outputs
     * of our child filters correctly according to the new settings
     */


    // use the correct data as source
    if (prop == &Data) {
        m_source_algorithm->setDataObject(Data.getValue());

        // change the step enum to correct values
        std::string val;
        if (Step.hasEnums() && Step.getValue() >= 0) {
            val = Step.getValueAsString();
        }

        std::vector<double> steps = m_source_algorithm->getStepValues();
        std::vector<std::string> step_values;
        if (steps.empty()) {
            step_values.push_back("No steps available");
        }
        else {
            auto unit = getStepUnit();
            for (const double& step : steps) {
                auto quantity = Base::Quantity(step, unit);
                step_values.push_back(quantity.getUserString().toStdString());
            }
        }

        App::Enumeration empty;
        Step.setValue(empty);
        m_stepEnum.setEnums(step_values);
        Step.setValue(m_stepEnum);

        std::vector<std::string>::iterator it = std::find(step_values.begin(), step_values.end(), val);
        if (!val.empty() && it != step_values.end()) {
            Step.setValue(val.c_str());
        }

        Step.purgeTouched();
        recomputeChildren();
    }

    if (prop == &Step) {

        // update the algorithm for the visulization
        auto steps = getStepValues();
        if (!steps.empty() &&
            Step.getValue() < long(steps.size())) {

            double time = steps[Step.getValue()];
            m_source_algorithm->UpdateTimeStep(time);
        }

        // inform the downstream pipeline
        recomputeChildren();
    }


    // connect all filters correctly to the source
    if (prop == &Group || prop == &Mode) {

        // we check if all connections are right and add new ones if needed
        std::vector<App::DocumentObject*> objs = Group.getValues();

        if (objs.empty()) {
            return;
        }

        FemPostFilter* filter = NULL;
        std::vector<App::DocumentObject*>::iterator it = objs.begin();
        for (; it != objs.end(); ++it) {

            // prepare the filter: make all connections new
            FemPostFilter* nextFilter = static_cast<FemPostFilter*>(*it);
            nextFilter->getActiveFilterPipeline().source->RemoveAllInputConnections(0);

            // handle input modes
            if (Mode.getValue() == 0) {
                // serial: the next filter gets the previous output, the first one gets our input
                if (filter == NULL) {
                    nextFilter->getActiveFilterPipeline().source->SetInputConnection(m_source_algorithm->GetOutputPort(0));
                } else {
                    nextFilter->getActiveFilterPipeline().source->SetInputConnection(filter->getActiveFilterPipeline().target->GetOutputPort());
                }

            }
            else if (Mode.getValue() == 1) {
                // parallel: all filters get out input
                nextFilter->getActiveFilterPipeline().source->SetInputConnection(m_source_algorithm->GetOutputPort(0));
            }
            else {
                throw Base::ValueError("Unknown Mode set for Pipeline");
            }

            filter = nextFilter;
        };
    }

    FemPostObject::onChanged(prop);

}

void FemPostPipeline::filterChanged(FemPostFilter* filter)
{
    //we only need to update the following children if we are in serial mode
    if (Mode.getValue() == 0) {

        std::vector<App::DocumentObject*> objs = Group.getValues();

        if (objs.empty()) {
            return;
        }
        bool started = false;
        std::vector<App::DocumentObject*>::iterator it = objs.begin();
        for (; it != objs.end(); ++it) {

            if (started) {
                (*it)->touch();
            }

            if (*it == filter) {
                started = true;
            }
        }
    }
}

void FemPostPipeline::pipelineChanged(FemPostFilter* filter) {
    // one of our filters has changed its active pipeline. We need to reconnect it properly.
    // As we are cheap we just reconnect everything
    // TODO: Do more efficiently
    onChanged(&Group);
}

void FemPostPipeline::recomputeChildren()
{
    // get the step we use
    double step = 0;
    auto steps = getStepValues();
    if (!steps.empty() &&
         Step.getValue() < steps.size()) {

        step = steps[Step.getValue()];
    }

    for (const auto& obj : Group.getValues()) {
        obj->touch();

        if (obj->isDerivedFrom(FemPostFilter::getClassTypeId())) {
            static_cast<Fem::FemPostFilter*>(obj)->Step.setValue(step);
        }
    }
}

FemPostObject* FemPostPipeline::getLastPostObject()
{

    if (Group.getValues().empty()) {
        return this;
    }

    return static_cast<FemPostObject*>(Group.getValues().back());
}

bool FemPostPipeline::holdsPostObject(FemPostObject* obj)
{

    std::vector<App::DocumentObject*>::const_iterator it = Group.getValues().begin();
    for (; it != Group.getValues().end(); ++it) {

        if (*it == obj) {
            return true;
        }
    }
    return false;
}



bool FemPostPipeline::hasSteps()
{
    // lazy implementation
    return !m_source_algorithm->getStepValues().empty();
}

std::string FemPostPipeline::getStepType()
{
    vtkSmartPointer<vtkDataObject> data = Data.getValue();

    // check if we have step data
    if (!data || !data->IsA("vtkMultiBlockDataSet")) {
        return std::string("no steps");
    }

    // we have multiple steps! let's check the amount and times
    vtkSmartPointer<vtkMultiBlockDataSet> multiblock = vtkMultiBlockDataSet::SafeDownCast(data);
    if (!multiblock->GetFieldData()->HasArray("TimeInfo")) {
        return std::string("unknown");
    }

    vtkAbstractArray* TimeInfo = multiblock->GetFieldData()->GetAbstractArray("TimeInfo");
    if (!TimeInfo ||
        !TimeInfo->IsA("vtkStringArray") ||
         TimeInfo->GetNumberOfTuples() < 2) {

        return std::string("unknown");
    }

    return vtkStringArray::SafeDownCast(TimeInfo)->GetValue(0);
}

Base::Unit FemPostPipeline::getStepUnit()
{
    vtkSmartPointer<vtkDataObject> data = Data.getValue();

    // check if we have step data
    if (!data || !data->IsA("vtkMultiBlockDataSet")) {
        // units cannot be undefined, so use time
        return Base::Unit::TimeSpan;
    }

    // we have multiple steps! let's check the amount and times
    vtkSmartPointer<vtkMultiBlockDataSet> multiblock = vtkMultiBlockDataSet::SafeDownCast(data);
    if (!multiblock->GetFieldData()->HasArray("TimeInfo")) {
        // units cannot be undefined, so use time
        return Base::Unit::TimeSpan;
    }

    vtkAbstractArray* TimeInfo = multiblock->GetFieldData()->GetAbstractArray("TimeInfo");
    if (!TimeInfo->IsA("vtkStringArray") ||
         TimeInfo->GetNumberOfTuples() < 2) {

        // units cannot be undefined, so use time
        return Base::Unit::TimeSpan;
    }

    return Base::Unit(QString::fromStdString(vtkStringArray::SafeDownCast(TimeInfo)->GetValue(1)));
}

std::vector<double> FemPostPipeline::getStepValues()
{
    return m_source_algorithm->getStepValues();
}

unsigned int FemPostPipeline::getStepNumber()
{
    // lazy implementation
    return getStepValues().size();
}

void FemPostPipeline::load(FemResultObject* res)
{
    if (!res->Mesh.getValue()) {
        Base::Console().Log("Result mesh object is empty.\n");
        return;
    }
    if (!res->Mesh.getValue()->isDerivedFrom(Fem::FemMeshObject::getClassTypeId())) {
        Base::Console().Log("Result mesh object is not derived from Fem::FemMeshObject.\n");
        return;
    }

    // first copy the mesh over
    // ***************************
    const FemMesh& mesh = static_cast<FemMeshObject*>(res->Mesh.getValue())->FemMesh.getValue();
    vtkSmartPointer<vtkUnstructuredGrid> grid = vtkSmartPointer<vtkUnstructuredGrid>::New();
    FemVTKTools::exportVTKMesh(&mesh, grid);

    // Now copy the point data over
    // ***************************
    FemVTKTools::exportFreeCADResult(res, grid);

    Data.setValue(grid);
}

// set multiple result objects as steps for one pipeline
// Notes:
//      1. values vector must contain growing value, smalles first
void FemPostPipeline::load(std::vector<FemResultObject*> res, std::vector<double> values, Base::Unit unit, std::string step_type) {

    if (res.size() != values.size() ) {
        Base::Console().Error("Result values and step values have different length.\n");
        return;
    }

    auto multiblock = vtkSmartPointer<vtkMultiBlockDataSet>::New();
    for (ulong i=0; i<res.size(); i++) {

        if (!res[i]->Mesh.getValue()->isDerivedFrom(Fem::FemMeshObject::getClassTypeId())) {
            Base::Console().Error("Result mesh object is not derived from Fem::FemMeshObject.\n");
            return;
        }

        // first copy the mesh over
        const FemMesh& mesh = static_cast<FemMeshObject*>(res[i]->Mesh.getValue())->FemMesh.getValue();
        vtkSmartPointer<vtkUnstructuredGrid> grid = vtkSmartPointer<vtkUnstructuredGrid>::New();
        FemVTKTools::exportVTKMesh(&mesh, grid);

        // Now copy the point data over
        FemVTKTools::exportFreeCADResult(res[i], grid);

        // add time information
        vtkFloatArray* TimeValue = vtkFloatArray::New();
        TimeValue->SetNumberOfComponents(1);
        TimeValue->SetName("TimeValue");
        TimeValue->InsertNextValue(values[i]);
        grid->GetFieldData()->AddArray(TimeValue);

        multiblock->SetBlock(i, grid);
    }

    // setup the time information for the multiblock
    vtkStringArray* TimeInfo = vtkStringArray::New();
    TimeInfo->SetName("TimeInfo");
    TimeInfo->InsertNextValue(step_type);
    TimeInfo->InsertNextValue(unit.getString().toStdString());
    multiblock->GetFieldData()->AddArray(TimeInfo);

    Data.setValue(multiblock);
}

PyObject* FemPostPipeline::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        // ref counter is set to 1
        PythonObject = Py::Object(new FemPostPipelinePy(this), true);
    }
    return Py::new_reference_to(PythonObject);
}
