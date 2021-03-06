from crontab import CronTab
import datetime
from glob import glob
import netCDF4 as NET
import numpy as np
import os
from shutil import move
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import ObjectDeletedError
from django.http import JsonResponse
import jdcal
import time

#django imports
from django.contrib.auth.decorators import user_passes_test

#tethys imports
from tethys_dataset_services.engines import (GeoServerSpatialDatasetEngine, 
                                             CkanDatasetEngine)

#local imports
from functions import (check_shapefile_input_files,
                       rename_shapefile_input_files,
                       delete_old_watershed_prediction_files,
                       delete_old_watershed_files, 
                       delete_old_watershed_kml_files,
                       delete_old_watershed_geoserver_files,
                       purge_remove_geoserver_layer,
                       adhydro_find_most_current_file,
                       format_name,
                       get_cron_command,
                       get_reach_index, 
                       handle_uploaded_file, 
                       user_permission_test)

from model import (DataStore, Geoserver, MainSettings, SettingsSessionMaker,
                    Watershed, WatershedGroup)

@user_passes_test(user_permission_test)
def data_store_add(request):
    """
    Controller for adding a data store.
    """
    if request.is_ajax() and request.method == 'POST':
        #get/check information from AJAX request
        post_info = request.POST
        data_store_name = post_info.get('data_store_name')
        data_store_type_id = post_info.get('data_store_type_id')
        data_store_endpoint = post_info.get('data_store_endpoint')
        data_store_api_key = post_info.get('data_store_api_key')
        
        if not data_store_name or not data_store_type_id or \
            not data_store_endpoint or not data_store_api_key:
            return JsonResponse({ 'error': "Request missing data." })
            
        #initialize session
        session = SettingsSessionMaker()
        
        #check to see if duplicate exists
        num_similar_data_stores  = session.query(DataStore) \
            .filter(
                or_(
                    DataStore.name == data_store_name, 
                    DataStore.api_endpoint == data_store_endpoint
                )
            ) \
            .count()
        if(num_similar_data_stores > 0):
            return JsonResponse({ 'error': "A data store with the same name or api endpoint exists." })
            
        #check if data store info is valid
        try:
            dataset_engine = CkanDatasetEngine(endpoint=data_store_endpoint, 
                                               apikey=data_store_api_key)    
            result = dataset_engine.list_datasets()
            if not result or "success" not in result:
                return JsonResponse({ 'error': "Data Store Credentials Invalid"})
        except Exception, ex:
            return JsonResponse({ 'error': "%s" % ex })
        
            
        #add Data Store
        session.add(DataStore(data_store_name, data_store_type_id, data_store_endpoint, data_store_api_key))
        session.commit()
        session.close()
        
        return JsonResponse({ 'success': "Data Store Sucessfully Added!" })

    return JsonResponse({ 'error': "A problem with your request exists." })

@user_passes_test(user_permission_test)
def data_store_delete(request):
    """
    Controller for deleting a data store.
    """
    if request.is_ajax() and request.method == 'POST':
        #get/check information from AJAX request
        post_info = request.POST
        data_store_id = post_info.get('data_store_id')
    
        if int(data_store_id) != 1:
            try:
                #initialize session
                session = SettingsSessionMaker()
                #update data store
                data_store  = session.query(DataStore).get(data_store_id)
                session.delete(data_store)
                session.commit()
                session.close()
            except IntegrityError:
                return JsonResponse({ 'error': "This data store is connected with a watershed! Must remove connection to delete." })
            return JsonResponse({ 'success': "Data Store Sucessfully Deleted!" })
        return JsonResponse({ 'error': "Cannot change this data store." })
    return JsonResponse({ 'error': "A problem with your request exists." })

@user_passes_test(user_permission_test)
def data_store_update(request):
    """
    Controller for updating a data store.
    """
    if request.is_ajax() and request.method == 'POST':
        #get/check information from AJAX request
        post_info = request.POST
        data_store_id = post_info.get('data_store_id')
        data_store_name = post_info.get('data_store_name')
        data_store_api_endpoint = post_info.get('data_store_api_endpoint')
        data_store_api_key = post_info.get('data_store_api_key')
    
        if int(data_store_id) != 1:
            #initialize session
            session = SettingsSessionMaker()
            #check to see if duplicate exists
            num_similar_data_stores  = session.query(DataStore) \
                .filter(
                    or_(
                        DataStore.name == data_store_name, 
                        DataStore.api_endpoint == data_store_api_endpoint
                    )
                ) \
                .filter(DataStore.id != data_store_id) \
                .count()
            if(num_similar_data_stores > 0):
                session.close()
                return JsonResponse({ 'error': "A data store with the same name or api endpoint exists." })

            #check if data store info is valid
            try:
                dataset_engine = CkanDatasetEngine(endpoint=data_store_api_endpoint, 
                                                   apikey=data_store_api_key)    
                result = dataset_engine.list_datasets()
                if not result or "success" not in result:
                    return JsonResponse({ 'error': "Data store credentials invalid."})
            except Exception, ex:
                return JsonResponse({ 'error': "%s" % ex })
                
            #update data store
            data_store  = session.query(DataStore).get(data_store_id)
            data_store.name = data_store_name
            data_store.api_endpoint= data_store_api_endpoint    
            data_store.api_key = data_store_api_key
            session.commit()
            session.close()
            return JsonResponse({ 'success': "Data Store Sucessfully Updated!" })
        return JsonResponse({ 'error': "Cannot change this data store." })
    return JsonResponse({ 'error': "A problem with your request exists." })

@user_passes_test(user_permission_test)
def geoserver_add(request):
    """
    Controller for adding a geoserver.
    """
    if request.is_ajax() and request.method == 'POST':
        #get/check information from AJAX request
        post_info = request.POST
        geoserver_name = post_info.get('geoserver_name')
        geoserver_url = post_info.get('geoserver_url')
        geoserver_username = post_info.get('geoserver_username')
        geoserver_password = post_info.get('geoserver_password')
    
        #check data
        if not geoserver_name or not geoserver_url or not \
            geoserver_username or not geoserver_password:
            return JsonResponse({ 'error': "Missing input data." })
        #clean url
        geoserver_url = geoserver_url.strip()
        if geoserver_url.endswith('/'):
            geoserver_url = geoserver_url[:-1]
        #initialize session
        session = SettingsSessionMaker()
        
        #check to see if duplicate exists
        num_similar_geoservers  = session.query(Geoserver) \
            .filter(
                or_(
                    Geoserver.name == geoserver_name, 
                    Geoserver.url == geoserver_url
                )
            ) \
            .count()
        if(num_similar_geoservers > 0):
            session.close()
            return JsonResponse({ 'error': "A geoserver with the same name or url exists." })
        #check geoserver
        try:
            engine = GeoServerSpatialDatasetEngine(endpoint="%s/rest" % geoserver_url.strip(), 
                       username=geoserver_username.strip(),
                       password=geoserver_password.strip())
            resource_workspace = 'erfp'
            engine.create_workspace(workspace_id=resource_workspace, uri='tethys.ci-water.org')
        except Exception, ex:
            return JsonResponse({'error' : "GeoServer Error: %s" % ex})
  
        #add Data Store
        session.add(Geoserver(geoserver_name.strip(), geoserver_url.strip(),
                              geoserver_username.strip(), geoserver_password.strip()))
        session.commit()
        session.close()
        return JsonResponse({ 'success': "Geoserver Sucessfully Added!" })

    return JsonResponse({ 'error': "A problem with your request exists." })

@user_passes_test(user_permission_test)
def geoserver_delete(request):
    """
    Controller for deleting a geoserver.
    """
    if request.is_ajax() and request.method == 'POST':
        #get/check information from AJAX request
        post_info = request.POST
        geoserver_id = post_info.get('geoserver_id')
    
        if int(geoserver_id) != 1:
            #initialize session
            session = SettingsSessionMaker()
            try:
                #delete geoserver
                try:
                    geoserver = session.query(Geoserver).get(geoserver_id)
                except ObjectDeletedError:
                    session.close()
                    return JsonResponse({ 'error': "The geoserver to delete does not exist." })
                session.delete(geoserver)
                session.commit()
                session.close()
            except IntegrityError:
                session.close()
                return JsonResponse({ 'error': "This geoserver is connected with a watershed! Must remove connection to delete." })
            return JsonResponse({ 'success': "Geoserver sucessfully deleted!" })
        return JsonResponse({ 'error': "Cannot change this geoserver." })
    return JsonResponse({ 'error': "A problem with your request exists." })

@user_passes_test(user_permission_test)
def geoserver_update(request):
    """
    Controller for updating a geoserver.
    """
    if request.is_ajax() and request.method == 'POST':
        #get/check information from AJAX request
        post_info = request.POST
        geoserver_id = post_info.get('geoserver_id')
        geoserver_name = post_info.get('geoserver_name')
        geoserver_url = post_info.get('geoserver_url')
        geoserver_username = post_info.get('geoserver_username')
        geoserver_password = post_info.get('geoserver_password')
        #check data
        if not geoserver_id or not geoserver_name or not geoserver_url or not \
            geoserver_username or not geoserver_password:
            return JsonResponse({ 'error': "Missing input data." })
        #make sure id is id
        try:
            int(geoserver_id)
        except ValueError:
            return JsonResponse({'error' : 'Geoserver id is faulty.'})
        #clean url
        geoserver_url = geoserver_url.strip()
        if geoserver_url.endswith('/'):
            geoserver_url = geoserver_url[:-1]

        if int(geoserver_id) != 1:
            #initialize session
            session = SettingsSessionMaker()
            #check to see if duplicate exists
            num_similar_geoservers  = session.query(Geoserver) \
              .filter(
                  or_(Geoserver.name == geoserver_name,
                      Geoserver.url == geoserver_url)
                      ) \
              .filter(Geoserver.id != geoserver_id) \
              .count()
              
            if(num_similar_geoservers > 0):
                session.close()
                return JsonResponse({ 'error': "A geoserver with the same name or url exists." })
            #update geoserver
            try:
                geoserver = session.query(Geoserver).get(geoserver_id)
            except ObjectDeletedError:
                session.close()
                return JsonResponse({ 'error': "The geoserver to update does not exist." })
            
            #validate geoserver
            try:
                engine = GeoServerSpatialDatasetEngine(endpoint="%s/rest" % geoserver_url.strip(), 
                           username=geoserver_username.strip(),
                           password=geoserver_password.strip())
                resource_workspace = 'erfp'
                engine.create_workspace(workspace_id=resource_workspace, uri='tethys.ci-water.org')
            except Exception, ex:
                return JsonResponse({'error' : "GeoServer Error: %s" % ex})
                
            geoserver.name = geoserver_name.strip()
            geoserver.url = geoserver_url.strip()    
            geoserver.username = geoserver_username.strip()    
            geoserver.password = geoserver_password.strip()    
            session.commit()
            session.close()
            return JsonResponse({ 'success': "Geoserver sucessfully updated!" })
        return JsonResponse({ 'error': "Cannot change this geoserver." })
    return JsonResponse({ 'error': "A problem with your request exists." })
    
def adhydro_get_avaialable_dates(request):
    """""
    Finds a list of directories with valid data and returns dates in select2 format
    """""
    #TODO: UPDATE THIS
    if request.method == 'GET':
        #Query DB for path to rapid output
        session = SettingsSessionMaker()
        main_settings  = session.query(MainSettings).order_by(MainSettings.id).first()
        session.close()

        path_to_rapid_output = main_settings.adhydro_prediction_directory
        if not os.path.exists(path_to_rapid_output):
            return JsonResponse({'error' : 'Location of ADHydro RAPID output files faulty. Please check settings.'})

        #get/check information from AJAX request
        get_info = request.GET
        watershed_name = format_name(get_info['watershed_name']) if 'watershed_name' in get_info else None
        subbasin_name = format_name(get_info['subbasin_name']) if 'subbasin_name' in get_info else None
        if not watershed_name or not subbasin_name:
            return JsonResponse({'error' : 'AJAX request input faulty'})

        #find/check current output datasets
        path_to_watershed_files = os.path.join(path_to_rapid_output, watershed_name, subbasin_name)

        if not os.path.exists(path_to_watershed_files):
            return JsonResponse({'error' : 'ADHydro forecast for %s (%s) not found.' % (watershed_name, subbasin_name) })

        prediction_files = sorted([d for d in os.listdir(path_to_watershed_files) \
                                if not os.path.isdir(os.path.join(path_to_watershed_files, d))],
                                reverse=True)
        output_files = []
        directory_count = 0
        for prediction_file in prediction_files:
            date_string = prediction_file.split("_")[1]
#            date = datetime.datetime.strptime(date_string,"%Y%m%dT%H%MZ")
            date = 0
            path_to_file = os.path.join(path_to_watershed_files, prediction_file)
            if os.path.exists(path_to_file):
                output_files.append({
                    'id' : date_string,
                    'text' : str(date)
                })
                directory_count += 1
                #limit number of directories
                if(directory_count>64):
                    break
        if len(output_files)>0:
            return JsonResponse({
                        "success" : "File search complete!",
                        "output_files" : output_files,
                    })
        else:
            return JsonResponse({'error' : 'Recent ADHydro forecasts for %s (%s) not found.' % (watershed_name, subbasin_name)})

def adhydro_get_hydrograph(request):
    """""
    Returns ADHydro hydrograph
    """""
    #TODO: UPDATE
    if request.method == 'GET':
        #Query DB for path to rapid output
        session = SettingsSessionMaker()
        main_settings  = session.query(MainSettings).order_by(MainSettings.id).first()
        session.close()
        path_to_rapid_output = main_settings.adhydro_prediction_directory
        if not os.path.exists(path_to_rapid_output):
            return JsonResponse({'error' : 'Location of ADHydro RAPID output files faulty. Please check settings.'})

        #get information from GET request
        get_info = request.GET
        watershed_name = format_name(get_info['watershed_name']) if 'watershed_name' in get_info else None
        subbasin_name = format_name(get_info['subbasin_name']) if 'subbasin_name' in get_info else None
        reach_id = get_info.get('reach_id')
        date_string = get_info.get('date_string')
        if not reach_id or not watershed_name or not subbasin_name or not date_string:
            return JsonResponse({'error' : 'ADHydro AJAX request input faulty.'})
        #find/check current output datasets
        #20150405T2300Z
        path_to_output_files = os.path.join(path_to_rapid_output, watershed_name, subbasin_name)
        forecast_file = adhydro_find_most_current_file(path_to_output_files, date_string)
        if not forecast_file:
            return JsonResponse({'error' : 'ADHydro forecast for %s (%s) not found.' % (watershed_name, subbasin_name)})
        #get/check the index of the reach
        reach_index = get_reach_index(reach_id, forecast_file)
        if reach_index == None:
            return JsonResponse({'error' : 'ADHydro reach with id: %s not found.' % reach_id})

        #get information from dataset
        data_nc = NET.Dataset(forecast_file, mode="r")
        try:
            data_values = data_nc.variables['channelSurfacewaterDepth'][:,reach_index]
            jul_date = data_nc.variables['referenceDate'][0]
            ref_date = jdcal.jd2gcal(jul_date,0)
            ref_date_time = datetime.datetime(ref_date[0],ref_date[1],ref_date[2],int(ref_date[3]*24))
            ref_time_utc = time.mktime(ref_date_time.timetuple())
        except:
            data_nc.close()
            return JsonResponse({'error' : "Invalid ADHydro forecast file"})

        variables = data_nc.variables.keys()
        if 'currentTime' in variables:
            timeout = [(t+ref_time_utc)*1000 for t in data_nc.variables['currentTime'][:]]
        else:
            data_nc.close()
            return JsonResponse({'error' : "Invalid ADHydro forecast file"})
        data_nc.close()

        return JsonResponse({
                "success" : "ADHydro data analysis complete!",
                "adhydro" : zip(timeout, data_values.tolist()),
        })

@user_passes_test(user_permission_test)
def settings_update(request):
    """
    Controller for updating the settings.
    """
    if request.is_ajax() and request.method == 'POST':
        #get/check information from AJAX request
        post_info = request.POST
        base_layer_id = post_info.get('base_layer_id')
        api_key = post_info.get('api_key')
        adhydro_prediction_directory = post_info.get('adhydro_location')

        #update cron jobs
        try:
            cron_manager = CronTab(user=True)
            cron_manager.remove_all(comment="erfp-dataset-download")
            cron_command = get_cron_command()
            if cron_command:
                #create job to run every hour  
                cron_job = cron_manager.new(command=cron_command, 
                                            comment="erfp-dataset-download")
                cron_job.every(1).hours()
                print cron_job
            else:
               JsonResponse({ 'error': "Location of virtual environment not found. No changes made." }) 
       
            #writes content to crontab
            cron_manager.write_to_user(user=True)
        except Exception:
            return JsonResponse({ 'error': "CRON setup error." })

        #initialize session
        session = SettingsSessionMaker()
        #update main settings
        main_settings  = session.query(MainSettings).order_by(MainSettings.id).first()
        main_settings.base_layer_id = base_layer_id
        main_settings.adhydro_prediction_directory = adhydro_prediction_directory    
        main_settings.base_layer.api_key = api_key
        session.commit()
        session.close()

        return JsonResponse({ 'success': "Settings Sucessfully Updated!" })

@user_passes_test(user_permission_test)    
def watershed_add(request):
    """
    Controller for adding a watershed.
    """
    if request.is_ajax() and request.method == 'POST':
        post_info = request.POST
        #get/check information from AJAX request
        watershed_name = post_info.get('watershed_name')
        subbasin_name = post_info.get('subbasin_name')
        folder_name = format_name(watershed_name)
        file_name = format_name(subbasin_name)
        data_store_id = post_info.get('data_store_id')
        geoserver_id = post_info.get('geoserver_id')
        #REQUIRED TO HAVE drainage_line from one of these
        #layer names
        geoserver_drainage_line_layer = post_info.get('geoserver_drainage_line_layer')
        geoserver_catchment_layer = post_info.get('geoserver_catchment_layer')
        geoserver_gage_layer = post_info.get('geoserver_gage_layer')
        kml_drainage_line_layer = ""
        kml_catchment_layer = ""
        kml_gage_layer = ""
        #shape files
        drainage_line_shp_file = request.FILES.getlist('drainage_line_shp_file')
        catchment_shp_file = request.FILES.getlist('catchment_shp_file')
        gage_shp_file = request.FILES.getlist('gage_shp_file')
        #kml files
        drainage_line_kml_file = request.FILES.get('drainage_line_kml_file')
        catchment_kml_file = request.FILES.get('catchment_kml_file')
        gage_kml_file = request.FILES.get('gage_kml_file')
        
        geoserver_drainage_line_uploaded = False
        geoserver_catchment_uploaded = False
        geoserver_gage_uploaded = False
        
        #CHECK DATA
        #make sure information exists 
        if not watershed_name or not subbasin_name or not data_store_id \
            or not geoserver_id or not folder_name or not file_name:
            return JsonResponse({'error' : 'Request input missing data.'})
        #make sure ids are ids
        try:
            int(data_store_id)
            int(geoserver_id)
        except ValueError:
            return JsonResponse({'error' : 'One or more ids are faulty.'})
            
        #make sure information is correct
        adhydro_data_store_watershed_name = ""
        adhydro_data_store_subbasin_name = ""
        if(int(data_store_id)>1):
            #check ADHydro inputs
            adhydro_ready = False
            adhydro_data_store_watershed_name = format_name(post_info.get('adhydro_data_store_watershed_name'))
            adhydro_data_store_subbasin_name = format_name(post_info.get('adhydro_data_store_subbasin_name'))
            
            if not adhydro_data_store_watershed_name or not adhydro_data_store_subbasin_name:
                adhydro_data_store_watershed_name = ""
                adhydro_data_store_subbasin_name = ""
            else:
                adhydro_ready = True

            #need at least one to be OK to proceed
            if not adhydro_ready:
                    return JsonResponse({'error' : "Must have an ADHydro watershed/subbasin name to continue" })

            
        #initialize session
        session = SettingsSessionMaker()
        #make sure one layer exists
        if(int(geoserver_id)==1):
            if not drainage_line_kml_file:
                return JsonResponse({'error' : 'Missing drainage line KML file.'})
        else:
            #check shapefiles
            if not drainage_line_shp_file and not geoserver_drainage_line_layer:
                return JsonResponse({'error' : 'Missing geoserver drainage line.'})
            if drainage_line_shp_file:
                missing_extenstions = check_shapefile_input_files(drainage_line_shp_file)
                if missing_extenstions:
                    return JsonResponse({'error' : 'Missing geoserver drainage line files with extensions %s.' % \
                                        (", ".join(missing_extenstions)) })
            if catchment_shp_file:
                missing_extenstions = check_shapefile_input_files(catchment_shp_file)
                if missing_extenstions:
                    return JsonResponse({'error' : 'Missing geoserver catchment files with extensions %s.' % \
                                        (", ".join(missing_extenstions)) })
            if gage_shp_file:
                missing_extenstions = check_shapefile_input_files(gage_shp_file)
                if missing_extenstions:
                    return JsonResponse({'error' : 'Missing geoserver gage files with extensions %s.' % \
                                        (", ".join(missing_extenstions)) })
        #check to see if duplicate exists
        num_similar_watersheds  = session.query(Watershed) \
            .filter(Watershed.folder_name == folder_name) \
            .filter(Watershed.file_name == file_name) \
            .count()
        if(num_similar_watersheds > 0):
            session.close()
            return JsonResponse({ 'error': "A watershed with the same name exists." })

        #COMMIT
        #upload files if files present
        #LOCAL UPLOAD
        if(int(geoserver_id) == 1):
            if drainage_line_kml_file:
                kml_file_location = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                                 'public','kml',folder_name)
                kml_drainage_line_layer = "%s-drainage_line.kml" % file_name
                handle_uploaded_file(drainage_line_kml_file,
                                     kml_file_location, kml_drainage_line_layer)
                #upload catchment kml if exists
                if catchment_kml_file:
                    kml_catchment_layer = "%s-catchment.kml" % file_name
                    handle_uploaded_file(catchment_kml_file,kml_file_location, 
                                         kml_catchment_layer)
                #uploade gage kml if exists
                if gage_kml_file:
                    kml_gage_layer = "%s-gage.kml" % file_name
                    handle_uploaded_file(gage_kml_file,kml_file_location, 
                                         kml_gage_layer)
            else:
                session.close()
                return JsonResponse({ 'error': "Drainage line KML file missing." })

        #GEOSERVER UPLOAD
        elif drainage_line_shp_file:
            geoserver = session.query(Geoserver).get(geoserver_id)
            engine = GeoServerSpatialDatasetEngine(endpoint="%s/rest" % geoserver.url, 
                       username=geoserver.username,
                       password=geoserver.password)
            resource_workspace = 'erfp'
            engine.create_workspace(workspace_id=resource_workspace, uri='tethys.ci-water.org')
            #DRAINAGE LINE
            resource_name = "%s-%s-%s" % (folder_name, file_name, 'drainage_line')
            geoserver_drainage_line_layer = '{0}:{1}'.format(resource_workspace, resource_name)
            #create shapefile
            rename_shapefile_input_files(drainage_line_shp_file, resource_name)
            engine.create_shapefile_resource(geoserver_drainage_line_layer, 
                                             shapefile_upload=drainage_line_shp_file,
                                             overwrite=True)
            geoserver_drainage_line_uploaded = True

            #CATCHMENT
            if catchment_shp_file:
                #upload file
                resource_name = "%s-%s-%s" % (folder_name, file_name, 'catchment')
                geoserver_catchment_layer = '{0}:{1}'.format(resource_workspace, resource_name)
                # Do create shapefile
                rename_shapefile_input_files(catchment_shp_file, resource_name)
                engine.create_shapefile_resource(geoserver_catchment_layer, 
                                                 shapefile_upload=catchment_shp_file,
                                                 overwrite=True)
                geoserver_catchment_uploaded = True
                
            #GAGE
            if gage_shp_file:
                #upload file
                resource_name = "%s-%s-%s" % (folder_name, file_name, 'gage')
                geoserver_gage_layer = '{0}:{1}'.format(resource_workspace, resource_name)
                # Do create shapefile
                rename_shapefile_input_files(gage_shp_file, resource_name)
                engine.create_shapefile_resource(geoserver_gage_layer, 
                                                 shapefile_upload=gage_shp_file,
                                                 overwrite=True)
                geoserver_gage_uploaded = True
        
        #add watershed
        watershed = Watershed(watershed_name.strip(), 
                              subbasin_name.strip(), 
                              folder_name, 
                              file_name, 
                              data_store_id, 
                              adhydro_data_store_watershed_name,
                              adhydro_data_store_subbasin_name,
                              geoserver_id, 
                              geoserver_drainage_line_layer.strip(),
                              geoserver_catchment_layer.strip(),
                              geoserver_gage_layer.strip(),
                              geoserver_drainage_line_uploaded,
                              geoserver_catchment_uploaded,
                              geoserver_gage_uploaded,
                              kml_drainage_line_layer.strip(),
                              kml_catchment_layer.strip(),
                              kml_gage_layer.strip()
                              )
        session.add(watershed)
        session.commit()
        
        #get watershed_id
        watershed_id = watershed.id
        session.close()
        
        return JsonResponse({
                            'success': "Watershed Sucessfully Added!",
                            'watershed_id' : watershed_id,
                            'geoserver_drainage_line_layer': geoserver_drainage_line_layer,
                            'geoserver_catchment_layer': geoserver_catchment_layer,
                            'geoserver_gage_layer': geoserver_gage_layer,
                            'kml_drainage_line_layer': kml_drainage_line_layer,
                            'kml_catchment_layer': kml_catchment_layer,
                            'kml_gage_layer': kml_gage_layer,
                            })

    return JsonResponse({ 'error': "A problem with your request exists." })

@user_passes_test(user_permission_test)
def watershed_delete(request):
    """
    Controller for deleting a watershed.
    """
    if request.is_ajax() and request.method == 'POST':
        #get/check information from AJAX request
        post_info = request.POST
        watershed_id = post_info.get('watershed_id')
        #make sure ids are ids
        try:
            int(watershed_id)
        except TypeError, ValueError:
            return JsonResponse({'error' : 'Watershed id is faulty.'})    
        
        if watershed_id:
            #initialize session
            session = SettingsSessionMaker()
            #get watershed to delete
            try:
                watershed  = session.query(Watershed).get(watershed_id)
            except ObjectDeletedError:
                return JsonResponse({ 'error': "The watershed to delete does not exist." })
            main_settings  = session.query(MainSettings).order_by(MainSettings.id).first()
            print 'between third and fourth'
            #remove watershed geoserver, kml, local prediction files, RAPID Input Files
            print watershed
            print main_settings.adhydro_prediction_directory
            delete_old_watershed_files(watershed)
            print 'fouuuuuuuuuuuuuuuuuuurth'
            #delete watershed from database
            session.delete(watershed)
            session.commit()
            session.close()

            return JsonResponse({ 'success': "Watershed sucessfully deleted!" })
        return JsonResponse({ 'error': "Cannot delete this watershed." })
    return JsonResponse({ 'error': "A problem with your request exists." })
    
@user_passes_test(user_permission_test)
def watershed_update(request):
    """
    Controller for updating a watershed.
    """
    if request.is_ajax() and request.method == 'POST':
        post_info = request.POST
        #get/check information from AJAX request
        watershed_id = post_info.get('watershed_id')
        watershed_name = post_info.get('watershed_name')
        subbasin_name = post_info.get('subbasin_name')
        folder_name = format_name(watershed_name)
        file_name = format_name(subbasin_name)
        data_store_id = post_info.get('data_store_id')
        geoserver_id = post_info.get('geoserver_id')
        #REQUIRED TO HAVE drainage_line from one of these
        #layer names
        geoserver_drainage_line_layer = post_info.get('geoserver_drainage_line_layer')
        geoserver_catchment_layer = post_info.get('geoserver_catchment_layer')
        geoserver_gage_layer = post_info.get('geoserver_gage_layer')
        #shape files
        drainage_line_shp_file = request.FILES.getlist('drainage_line_shp_file')
        catchment_shp_file = request.FILES.getlist('catchment_shp_file')
        gage_shp_file = request.FILES.getlist('gage_shp_file')
        #kml files
        drainage_line_kml_file = request.FILES.get('drainage_line_kml_file')
        catchment_kml_file = request.FILES.get('catchment_kml_file')
        gage_kml_file = request.FILES.get('gage_kml_file')
        
        #CHECK INPUT
        #check if variables exist
        if not watershed_id or not watershed_name or not subbasin_name or not data_store_id \
            or not geoserver_id or not folder_name or not file_name:
            return JsonResponse({'error' : 'Request input missing data.'})
        #make sure ids are ids
        try:
            int(watershed_id)
            int(data_store_id)
            int(geoserver_id)
        except TypeError, ValueError:
            return JsonResponse({'error' : 'One or more ids are faulty.'})

        #initialize session
        session = SettingsSessionMaker()
        #check to see if duplicate exists
        num_similar_watersheds  = session.query(Watershed) \
            .filter(Watershed.folder_name == folder_name) \
            .filter(Watershed.file_name == file_name) \
            .filter(Watershed.id != watershed_id) \
            .count()
        if(num_similar_watersheds > 0):
            session.close()
            return JsonResponse({ 'error': "A watershed with the same name exists." })
        
        #get desired watershed
        try:
            watershed  = session.query(Watershed).get(watershed_id)
        except ObjectDeletedError:
            session.close()
            return JsonResponse({ 'error': "The watershed to update does not exist." })
            
        #make sure data store information is correct
        adhydro_data_store_watershed_name = ""
        adhydro_data_store_subbasin_name = ""
        if(int(data_store_id)>1):
            #check adhydro inputs
            adhydro_ready = False
            adhydro_data_store_watershed_name = format_name(post_info.get('adhydro_data_store_watershed_name'))
            adhydro_data_store_subbasin_name = format_name(post_info.get('adhydro_data_store_subbasin_name'))
            
            if not adhydro_data_store_watershed_name or not adhydro_data_store_subbasin_name:
                adhydro_data_store_watershed_name = ""
                adhydro_data_store_subbasin_name = ""
            else:
                adhydro_ready = True

            #need at least one to be OK to proceed
            if not adhydro_ready:
                return JsonResponse({'error' : "Must have an ADHydro watershed/subbasin name to continue" })

        #make sure one layer exists
        if(int(geoserver_id)==1):
            if not drainage_line_kml_file and not watershed.kml_drainage_line_layer:
                return JsonResponse({'error' : 'Missing drainage line KML file.'})
        else:
            if not drainage_line_shp_file and not geoserver_drainage_line_layer:
                return JsonResponse({'error' : 'Missing geoserver drainage line.'})
            #check shapefiles
            if drainage_line_shp_file:
                missing_extenstions = check_shapefile_input_files(drainage_line_shp_file)
                if missing_extenstions:
                    return JsonResponse({'error' : 'Missing geoserver drainage line files with extensions %s.' % \
                                        (", ".join(missing_extenstions)) })
            if catchment_shp_file:
                missing_extenstions = check_shapefile_input_files(catchment_shp_file)
                if missing_extenstions:
                    return JsonResponse({'error' : 'Missing geoserver catchment files with extensions %s.' % \
                                        (", ".join(missing_extenstions)) })
            if gage_shp_file:
                missing_extenstions = check_shapefile_input_files(gage_shp_file)
                if missing_extenstions:
                    return JsonResponse({'error' : 'Missing geoserver gage files with extensions %s.' % \
                                        (", ".join(missing_extenstions)) })
            
        #COMMIT    
        main_settings  = session.query(MainSettings).order_by(MainSettings.id).first()
        kml_drainage_line_layer = ""
        kml_catchment_layer = ""
        kml_gage_layer = ""
        #upload files to local server if ready
        if(int(geoserver_id) == 1):
            geoserver_drainage_line_uploaded = False
            geoserver_catchment_uploaded = False
            geoserver_gage_uploaded = False
            #remove old geoserver files
            delete_old_watershed_geoserver_files(watershed)
            #move/rename kml files
            old_kml_file_location = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                                 'public','kml',watershed.folder_name)
            new_kml_file_location = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                                 'public','kml',folder_name)
            kml_drainage_line_layer = "%s-drainage_line.kml" % file_name
            kml_catchment_layer = "%s-catchment.kml" % file_name
            kml_gage_layer = "%s-gage.kml" % file_name
            #add new directory if it does not exist                
            try:
                os.mkdir(new_kml_file_location)
            except OSError:
                pass

            #if the name of watershed or subbasin is changed, update file name/location
            if(folder_name != watershed.folder_name or file_name != watershed.file_name):
                if(watershed.geoserver_id == 1):
                    #move drainage line kml
                    if watershed.kml_drainage_line_layer:
                        try:
                            move(os.path.join(old_kml_file_location, watershed.kml_drainage_line_layer),
                                 os.path.join(new_kml_file_location, kml_drainage_line_layer))
                        except IOError:
                            pass
                    #move catchment kml
                    if watershed.kml_catchment_layer:
                        try:
                            move(os.path.join(old_kml_file_location, watershed.kml_catchment_layer),
                                 os.path.join(new_kml_file_location, kml_catchment_layer))
                        except IOError:
                            pass
                    #move gage kml
                    if watershed.kml_gage_layer:
                        try:
                            move(os.path.join(old_kml_file_location, watershed.kml_gage_layer),
                                 os.path.join(new_kml_file_location, kml_gage_layer))
                        except IOError:
                            pass
                    #remove old directory if exists
                    try:
                        os.rmdir(old_kml_file_location)
                    except OSError:
                        pass
            #upload new files if they exist
            if(drainage_line_kml_file):
                handle_uploaded_file(drainage_line_kml_file, new_kml_file_location, kml_drainage_line_layer)
            #other case already handled for drainage line
                
            if(catchment_kml_file):
                handle_uploaded_file(catchment_kml_file, new_kml_file_location, kml_catchment_layer)
            elif not watershed.kml_catchment_layer:
                kml_catchment_layer = ""
                
            if(gage_kml_file):
                handle_uploaded_file(gage_kml_file, new_kml_file_location, kml_gage_layer)
            elif not watershed.kml_gage_layer:
                kml_gage_layer = ""
        else:
            #if no drainage line name or shapefile upload, throw error
            if not geoserver_drainage_line_layer and not drainage_line_shp_file:
                session.close()
                return JsonResponse({ 'error': "Must have drainage line layer name or file." })

            #get desired geoserver
            try:
                geoserver  = session.query(Geoserver).get(geoserver_id)
            except ObjectDeletedError:
                session.close()
                return JsonResponse({ 'error': "The geoserver does not exist." })
            #attempt to get engine
            try:
                engine = GeoServerSpatialDatasetEngine(endpoint="%s/rest" % geoserver.url, 
                                                       username=geoserver.username,
                                                       password=geoserver.password)
            except Exception:
                session.close()
                return JsonResponse({ 'error': "The geoserver has errors." })
                

            geoserver_drainage_line_uploaded = watershed.geoserver_drainage_line_uploaded
            geoserver_catchment_uploaded = watershed.geoserver_catchment_uploaded
            geoserver_gage_uploaded = watershed.geoserver_gage_uploaded
            resource_workspace = 'erfp'
            engine.create_workspace(workspace_id=resource_workspace, uri='tethys.ci-water.org')
            
            #UPDATE DRAINAGE LINE
            if drainage_line_shp_file:
                #remove old geoserver layer if uploaded
                if watershed.geoserver_drainage_line_uploaded \
                    and (watershed.folder_name != folder_name
                    or watershed.file_name != file_name):
                    purge_remove_geoserver_layer(watershed.geoserver_drainage_line_layer, 
                                                 engine)
                resource_name = "%s-%s-%s" % (folder_name, file_name, 'drainage_line')
                geoserver_drainage_line_layer = '{0}:{1}'.format(resource_workspace, resource_name)
                # Do create shapefile
                rename_shapefile_input_files(drainage_line_shp_file, resource_name)
                engine.create_shapefile_resource(geoserver_drainage_line_layer, 
                                                 shapefile_upload=drainage_line_shp_file,
                                                 overwrite=True)
                geoserver_drainage_line_uploaded = True

            #UPDATE CATCHMENT
            #delete old layer from geoserver if removed
            geoserver_catchment_layer = "" if not geoserver_catchment_layer else geoserver_catchment_layer
            if not geoserver_catchment_layer and watershed.geoserver_catchment_layer:
                if watershed.geoserver_catchment_uploaded:
                    purge_remove_geoserver_layer(watershed.geoserver_catchment_layer,
                                                 engine)
                
            if catchment_shp_file:
                #remove old geoserver layer if uploaded
                if watershed.geoserver_catchment_uploaded \
                    and (watershed.folder_name != folder_name
                    or watershed.file_name != file_name):
                    purge_remove_geoserver_layer(watershed.geoserver_catchment_layer,
                                                 engine)
                resource_name = "%s-%s-%s" % (folder_name, file_name, 'catchment')
                geoserver_catchment_layer = '{0}:{1}'.format(resource_workspace, resource_name)
                # Do create shapefile
                rename_shapefile_input_files(catchment_shp_file, resource_name)
                engine.create_shapefile_resource(geoserver_catchment_layer, 
                                                 shapefile_upload=catchment_shp_file,
                                                 overwrite=True)
                geoserver_catchment_uploaded = True

            #UPDATE GAGE
            #delete old layer from geoserver if removed
            geoserver_gage_layer = "" if not geoserver_gage_layer else geoserver_gage_layer
            if not geoserver_gage_layer and watershed.geoserver_gage_layer:
                if watershed.geoserver_gage_uploaded:
                    purge_remove_geoserver_layer(watershed.geoserver_gage_layer, 
                                                 engine)

                    
            if gage_shp_file:
                #remove old geoserver layer if uploaded
                if watershed.geoserver_gage_uploaded \
                    and (watershed.folder_name != folder_name
                    or watershed.file_name != file_name):
                    purge_remove_geoserver_layer(watershed.geoserver_gage_layer,
                                                 engine)
                resource_name = "%s-%s-%s" % (folder_name, file_name, 'gage')
                geoserver_gage_layer = '{0}:{1}'.format(resource_workspace, resource_name)
                # Do create shapefile
                rename_shapefile_input_files(gage_shp_file, resource_name)
                engine.create_shapefile_resource(geoserver_gage_layer, 
                                                 shapefile_upload=gage_shp_file,
                                                 overwrite=True)
                geoserver_gage_uploaded = True
            
            #remove old kml files           
            delete_old_watershed_kml_files(watershed)

        if(adhydro_data_store_watershed_name != watershed.adhydro_data_store_watershed_name or 
           adhydro_data_store_subbasin_name != watershed.adhydro_data_store_subbasin_name):
            delete_old_watershed_prediction_files(watershed)

        #change watershed attributes
        watershed.watershed_name = watershed_name.strip()
        watershed.subbasin_name = subbasin_name.strip()
        watershed.folder_name = folder_name
        watershed.file_name = file_name
        watershed.data_store_id = data_store_id
        watershed.adhydro_data_store_watershed_name = adhydro_data_store_watershed_name
        watershed.adhydro_data_store_subbasin_name = adhydro_data_store_subbasin_name
        watershed.geoserver_drainage_line_layer = geoserver_drainage_line_layer.strip() if geoserver_drainage_line_layer else ""
        watershed.geoserver_catchment_layer = geoserver_catchment_layer.strip() if geoserver_catchment_layer else ""
        watershed.geoserver_gage_layer = geoserver_gage_layer.strip() if geoserver_gage_layer else ""
        watershed.geoserver_drainage_line_uploaded = geoserver_drainage_line_uploaded
        watershed.geoserver_catchment_uploaded = geoserver_catchment_uploaded
        watershed.geoserver_gage_uploaded = geoserver_gage_uploaded
        watershed.kml_drainage_line_layer = kml_drainage_line_layer.strip() if kml_drainage_line_layer else ""
        watershed.kml_catchment_layer = kml_catchment_layer.strip() if kml_catchment_layer else ""
        watershed.kml_gage_layer = kml_gage_layer.strip() if kml_gage_layer else ""
        
        #update database
        session.commit()
        session.close()
        
        return JsonResponse({ 'success': "Watershed sucessfully updated!", 
                              'geoserver_drainage_line_layer': geoserver_drainage_line_layer,
                              'geoserver_catchment_layer': geoserver_catchment_layer,
                              'geoserver_gage_layer': geoserver_gage_layer,
                              'kml_drainage_line_layer': kml_drainage_line_layer,
                              'kml_catchment_layer': kml_catchment_layer,
                              'kml_gage_layer': kml_gage_layer,
                              })

    return JsonResponse({ 'error': "A problem with your request exists." })

@user_passes_test(user_permission_test)
def watershed_group_add(request):
    """
    Controller for adding a watershed_group.
    """
    if request.is_ajax() and request.method == 'POST':
        #get/check information from AJAX request
        post_info = request.POST
        watershed_group_name = post_info.get('watershed_group_name')
        watershed_group_watershed_ids = post_info.getlist('watershed_group_watershed_ids[]')
        if not watershed_group_name or not watershed_group_watershed_ids:
            return JsonResponse({ 'error': 'AJAX request input faulty' })
        #initialize session
        session = SettingsSessionMaker()
        
        #check to see if duplicate exists
        num_similar_watershed_groups  = session.query(WatershedGroup) \
            .filter(WatershedGroup.name == watershed_group_name) \
            .count()
        if(num_similar_watershed_groups > 0):
            return JsonResponse({ 'error': "A watershed group with the same name." })
            
        #add Watershed Group
        group = WatershedGroup(watershed_group_name)

        #update watersheds
        watersheds  = session.query(Watershed) \
                .filter(Watershed.id.in_(watershed_group_watershed_ids)) \
                .all()
        for watershed in watersheds:
            group.watersheds.append(watershed)
        session.add(group)
        session.commit()
        session.close()

        return JsonResponse({ 'success': "Watershed group sucessfully added!" })

    return JsonResponse({ 'error': "A problem with your request exists." })
    
@user_passes_test(user_permission_test)
def watershed_group_delete(request):
    """
    Controller for deleting a watershed group.
    """
    if request.is_ajax() and request.method == 'POST':
        #get/check information from AJAX request
        post_info = request.POST
        watershed_group_id = post_info.get('watershed_group_id')
    
        
        if watershed_group_id:
            #initialize session
            session = SettingsSessionMaker()
            #get watershed group to delete
            watershed_group  = session.query(WatershedGroup).get(watershed_group_id)
            
            #delete watershed group from database
            session.delete(watershed_group)
            session.commit()
            session.close()

            return JsonResponse({ 'success': "Watershed group sucessfully deleted!" })
        return JsonResponse({ 'error': "Cannot delete this watershed group." })
    return JsonResponse({ 'error': "A problem with your request exists." })
    
@user_passes_test(user_permission_test)
def watershed_group_update(request):
    """
    Controller for updating a watershed_group.
    """
    if request.is_ajax() and request.method == 'POST':
        #get/check information from AJAX request
        post_info = request.POST
        watershed_group_id = post_info.get('watershed_group_id')
        watershed_group_name = post_info.get('watershed_group_name')
        watershed_group_watershed_ids = post_info.getlist('watershed_group_watershed_ids[]')
        if watershed_group_id and watershed_group_name and watershed_group_watershed_ids:
            #initialize session
            session = SettingsSessionMaker()
            #check to see if duplicate exists
            num_similar_watershed_groups  = session.query(WatershedGroup) \
                .filter(WatershedGroup.name == watershed_group_name) \
                .filter(WatershedGroup.id != watershed_group_id) \
                .count()
            if(num_similar_watershed_groups > 0):
                return JsonResponse({ 'error': "A watershed group with the same name exists." })

            #get watershed group
            watershed_group  = session.query(WatershedGroup).get(watershed_group_id)
            watershed_group.name = watershed_group_name
            #find new watersheds
            new_watersheds  = session.query(Watershed) \
                    .filter(Watershed.id.in_(watershed_group_watershed_ids)) \
                    .all()

            #remove old watersheds
            for watershed in watershed_group.watersheds:
                if watershed not in new_watersheds:
                    watershed_group.watersheds.remove(watershed)
                
            #add new watersheds        
            for watershed in new_watersheds:
                if watershed not in watershed_group.watersheds:
                    watershed_group.watersheds.append(watershed)
            
            session.commit()
            session.close()
            return JsonResponse({ 'success': "Watershed group successfully updated." })
        return JsonResponse({ 'error': "Data missing for this watershed group." })
    return JsonResponse({ 'error': "A problem with your request exists." })