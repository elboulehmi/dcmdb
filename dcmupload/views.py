# Create your views here.
from django.shortcuts import render_to_response
from django.http import HttpResponse, HttpRequest
from django.template import RequestContext
#ObjectDoesNotExist
from django.core.exceptions import ObjectDoesNotExist
#Force CSRF Cookie
from django.views.decorators.csrf import ensure_csrf_cookie
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from dcmupload.models import Study, Series, Image
from dcmupload.processdicom import processdicom

import json, simplejson
import random
import string
import re
import dicom
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
MEDIA_DIR = BASE_DIR + "/media"

dthandler = lambda obj: obj.isoformat() if isinstance(obj, datetime.datetime) else None

@ensure_csrf_cookie
def dcmupload(request):

	context = {}

	return render_to_response('dcmupload.html', context, context_instance = RequestContext(request))

@csrf_exempt
def blank(request):

	context = {}

	return render_to_response('blank.html', context, context_instance = RequestContext(request))

@csrf_exempt
def handle_upload(request):

     # used to generate random unique id
    import uuid

    # settings for the file upload
    #   you can define other parameters here
    #   and check validity late in the code
    options = {
        # the maximum file size (must be in bytes)
        "maxfilesize": 2 * 2 ** 20, # 2 Mb
        # the minimum file size (must be in bytes)
        "minfilesize": 1 * 2 ** 10, # 1 Kb
        # the file types which are going to be allowed for upload
        #   must be a mimetype
        "acceptedformats": (
            "application/dicom",
            "image/dicom",
            "image/x-dicom",
            "application/octet-stream",
            "application/x-rar-compressed",
            "application/zip",
        )
    }


    # POST request
    #   meaning user has triggered an upload action
    if request.method == 'POST':
        # figure out the path where files will be uploaded to
        temp_path = MEDIA_DIR

        # if 'f' query parameter is not specified
        # file is being uploaded
        if not ("f" in request.GET.keys()): # upload file

            # make sure some files have been uploaded
            if not request.FILES:
                return HttpResponseBadRequest('Must upload a file')

            # get the uploaded file
            file = request.FILES[u'files[]']

            # initialize the error
            # If error occurs, this will have the string error message so
            # uploader can display the appropriate message
            error = False

            # check against options for errors

            # file size
            if file.size > options["maxfilesize"]:
                error = "maxFileSize"
            if file.size < options["minfilesize"]:
                error = "minFileSize"
                # allowed file type
            if file.content_type not in options["acceptedformats"]:
                error = "acceptFileTypes"

            # the response data which will be returned to the uploader as json
            response_data = {
                "name": file.name,
                "size": file.size,
                "type": file.content_type
            }

            # if there was an error, add error message to response_data and return
            if error:
                # append error message
                response_data["error"] = error
                # generate json
                response_data = simplejson.dumps([response_data])
                # return response to uploader with error
                # so it can display error message
                return HttpResponse(response_data, mimetype='application/json')


            # make temporary dir if not exists already
            if not os.path.exists(temp_path):
                os.makedirs(temp_path)

            # get the absolute path of where the uploaded file will be saved
            # all add some random data to the filename in order to avoid conflicts
            # when user tries to upload two files with same filename
            file_name = str(uuid.uuid4()) + file.name

            if not file_name.endswith(".dcm"):
                file_name = file_name + '.dcm'

            filename = os.path.join(temp_path, file_name)

            # open the file handler with write binary mode
            destination = open(filename, "wb+")
            # save file data into the disk
            # use the chunk method in case the file is too big
            # in order not to clutter the system memory
            for chunk in file.chunks():
                destination.write(chunk)
                # close the file

            destination.close()

            # strip patient data
            anonymize(filename, filename)

            dcm = processdicom(filename = filename)

            #Save 
            args = {
                "dcm": dcm.getDCM(),
                "filename": file_name[:-4],
                "request": request,
            }

            new_series = add_dcm_record(**args)

            if not new_series['success']:
                #remove recently uploaded dcm file
                os.remove(filename)
                return HttpResponse(simplejson.dumps([{ 
                    "success": False, "msg": 
                    "DCM already found in database.", 
                    "name": file.name, 
                    "series_uid": new_series['series'].UID, 
                    "study_uid": new_series['study'].UID 
                }]), mimetype="application/json")

            #save image and thumbnail
            save_image = dcm.writeFiles(filename)
            
            if not save_image['success']:
                return HttpResponse(simplejson.dumps(save_image), mimetype="application/json")

            response_data['file_name'] = "/media/" + file_name[:-4]
            
            response_data['study_uid'] = new_series['study'].UID
            response_data['series_uid'] = new_series['series'].UID

            # allows to generate properly formatted and escaped url queries
            import urllib

            # generate the json data
            response_data = simplejson.dumps([response_data])
            # response type
            response_type = "application/json"

            # QUIRK HERE
            # in jQuey uploader, when it falls back to uploading using iFrames
            # the response content type has to be text/html
            # if json will be send, error will occur
            # if iframe is sending the request, it's headers are a little different compared
            # to the jQuery ajax request
            # they have different set of HTTP_ACCEPT values
            # so if the text/html is present, file was uploaded using jFrame because
            # that value is not in the set when uploaded by XHR
            if "text/html" in request.META["HTTP_ACCEPT"]:
                response_type = "text/html"

            # return the data to the uploading plugin
            return HttpResponse(response_data, mimetype=response_type)

#Creates a new record in our database for the DICOM file
#Right now we hard-coded a list of keys we are interested in
def add_dcm_record(**kwargs):

    #dcm, dcm_dir, filename, title, public, request, study

    modality = ""
    institution_name = ""
    manufacturer = ""
    physician_name = ""
    bits_allocated = ""
    bits_store = ""
    study_id = ""
    study_description = ""
    study_date = ""
    study_time = ""
    study_instance_uid = ""
    sop_clas_uid = ""
    instance_number = ""
    accession_number = ""
    series_instance_uid = ""
    series_number = ""
    series_date = ""
    image_type = ""

    dcm = kwargs['dcm']
    
    for tag in dcm.dir():

        if tag == "Modality":
            modality = dcm.Modality
        elif tag == "InstitutionName":
            institution_name = dcm.InstitutionName
            institution_name = institution_name.decode('utf-8')
        elif tag == "Manufacturer":
            manufacturer = dcm.Manufacturer
        elif tag == "BitsAllocated":
            bits_allocated = dcm.BitsAllocated
        elif tag == "BitsStored":
            bits_stored = dcm.BitsStored
        elif tag == "StudyID":
            study_id = dcm.StudyID
        elif tag == "StudyDescription":
            study_description = dcm.StudyDescription
            study_description = ""
            # study_description = study_description.decode('utf-8')
        elif tag == "StudyDate":
            study_date = dcm.StudyDate
            study_date = convert_date(study_date, "-")
        elif tag == "StudyTime":
            study_time = dcm.StudyTime
        elif tag == "StudyInstanceUID":
            # unique identifier for the study
            study_instance_uid = dcm.StudyInstanceUID
        elif tag == "SOPInstanceUID":
            sop_instance_uid = dcm.SOPInstanceUID
        elif tag == "SOPClassUID":
            sop_class_uid = dcm.SOPClassUID
        elif tag == "InstanceNumber":
            instance_number = dcm.InstanceNumber
        elif tag == "AccessionNumber":
            accession_number = dcm.AccessionNumber
        elif tag == "SeriesInstanceUID":
            # unique identifier for the series
            series_instance_uid = dcm.SeriesInstanceUID
        elif tag == "SeriesNumber":
            series_number = dcm.SeriesNumber
        elif tag == "SeriesDate":
            series_date = dcm.SeriesDate
            series_date = convert_date(series_date, "-").encode('utf-8')
        elif tag == "ImageType":
            image_type = dcm.ImageType
        elif tag == "Laterality":
            laterality = dcm.Laterality

    if series_date == "":
        series_date = "1990-01-01"

    try:
        study = Study.objects.get(UID = study_instance_uid)

    except (Study.DoesNotExist):

        study = Study.objects.create(
                UID = study_instance_uid,
                study_id = study_id,
                #study_date = study_date,
                #study_time = study_time,
                description = study_description,
                modality = modality,
                institution_name = institution_name,
                manufacturer = manufacturer,
                accession_number = accession_number
            )

        study.save()

    try:
        series = Series.objects.get(UID = series_instance_uid, instance_number = instance_number)

        return {
            "success": False,
            "series": series,
            "study": study
        }

    except (Series.DoesNotExist):

        series = Series.objects.create(
            dcm_study = study,
            UID = series_instance_uid,
            series_number = series_number,
            filename = kwargs['filename'],
            bits_allocated = bits_allocated,
            bits_stored = bits_stored,
            sop_instance_uid = sop_instance_uid,
            sop_class_uid = sop_class_uid,
            instance_number = instance_number,
            date = series_date
        )

        series.save()

        return {
            "success": True,
            "series": series,
            "study": study
        }

    #series = lambda: None
    #series.id = False
    #series.error = "Instance number already exists for this study "

    #return series

# Method that takes a date "20130513" and converts it to "2013-05-13" or whatever
# delimiter inputed
def convert_date(date, delim):

	year = date[:4]
	month = date[4:6]
	day = date[6:8]

	return delim.join([year, month, day])	

def id_generator(size = 6, chars = string.ascii_lowercase + string.digits):

	return ''.join(random.choice(chars) for x in range(size))

def anonymize(filename, output_filename, new_person_name="anonymous",
              new_patient_id="id", remove_curves=True, remove_private_tags=True):
    """Replace data element values to partly anonymize a DICOM file.
    Note: completely anonymizing a DICOM file is very complicated; there
    are many things this example code does not address. USE AT YOUR OWN RISK.
    """

    # Define call-back functions for the dataset.walk() function
    def PN_callback(ds, data_element):
        """Called from the dataset "walk" recursive function for all data elements."""
        if data_element.VR == "PN":
            data_element.value = new_person_name
    def curves_callback(ds, data_element):
        """Called from the dataset "walk" recursive function for all data elements."""
        if data_element.tag.group & 0xFF00 == 0x5000:
            del ds[data_element.tag]
    
    # Load the current dicom file to 'anonymize'
    dataset = dicom.read_file(filename)
    
    # Remove patient name and any other person names
    dataset.walk(PN_callback)
    
    # Change ID
    dataset.PatientID = new_patient_id
    
    # Remove data elements (should only do so if DICOM type 3 optional) 
    # Use general loop so easy to add more later
    # Could also have done: del ds.OtherPatientIDs, etc.
    for name in ['OtherPatientIDs', 'OtherPatientIDsSequence']:
        if name in dataset:
            delattr(dataset, name)

    # Same as above but for blanking data elements that are type 2.
    for name in ['PatientBirthDate']:
        if name in dataset:
            dataset.data_element(name).value = ''
    
    # Remove private tags if function argument says to do so. Same for curves
    if remove_private_tags:
        dataset.remove_private_tags()
    if remove_curves:
        dataset.walk(curves_callback)
        
    # write the 'anonymized' DICOM out under the new filename
    dataset.save_as(output_filename)