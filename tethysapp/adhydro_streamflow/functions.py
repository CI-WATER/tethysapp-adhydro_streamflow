import datetime
from glob import glob
import netCDF4 as NET
import numpy as np
import os
import re
from shutil import rmtree
from sqlalchemy import and_
#tethys imports
from tethys_dataset_services.engines import GeoServerSpatialDatasetEngine
#local import
from model import SettingsSessionMaker, MainSettings, Watershed
#from sfpt_dataset_manager.dataset_manager import CKANDatasetManager

def check_shapefile_input_files(shp_files):
    """
    #make sure required files for shapefiles are included
    """
    required_extentsions = ['.shp', '.shx', '.prj','.dbf']
    accepted_extensions = []
    for shp_file in shp_files:
        file_name, file_extension = os.path.splitext(shp_file.name)
        for required_extentsion in required_extentsions: 
            if file_extension == required_extentsion:
                accepted_extensions.append(required_extentsion)
                required_extentsions.remove(required_extentsion)
    return required_extentsions

def rename_shapefile_input_files(shp_files, new_file_name):
    """
    #make sure required files for shapefiles are included
    """
    for shp_file in shp_files:
        file_name, file_extension = os.path.splitext(shp_file.name)
        shp_file.name = "%s%s" % (new_file_name, file_extension)
    
def delete_old_watershed_prediction_files(watershed):
    """
    Removes old watershed prediction files from system if no other watershed has them
    """
    def delete_prediciton_files(main_folder_name, sub_folder_name, local_prediction_files_location):
        """
        Removes predicitons from folder and folder if not empty
        """
        prediciton_folder = os.path.join(local_prediction_files_location, 
                                         main_folder_name,
                                         sub_folder_name)
        #remove watersheds subbsasins folders/files
        if main_folder_name and sub_folder_name and \
        local_prediction_files_location and os.path.exists(prediciton_folder):
            
            #remove all prediction files from watershed/subbasin
            try:
                rmtree(prediciton_folder)
            except OSError:
                pass
            
            #remove watershed folder if no other subbasins exist
            try:
                os.rmdir(os.path.join(local_prediction_files_location, 
                                      main_folder_name))
            except OSError:
                pass
        
    #initialize session
    session = SettingsSessionMaker()
    main_settings  = session.query(MainSettings).order_by(MainSettings.id).first()
    
    #Make sure that you don't delete if another watershed is using the
    #same predictions
    num_adhydro_watersheds_with_forecast  = session.query(Watershed) \
        .filter(
            and_(
                Watershed.adhydro_data_store_watershed_name == watershed.adhydro_data_store_watershed_name, 
                Watershed.adhydro_data_store_subbasin_name == watershed.adhydro_data_store_subbasin_name
            )
        ) \
        .filter(Watershed.id != watershed.id) \
        .count()
    if num_adhydro_watersheds_with_forecast <= 0:
        delete_prediciton_files(watershed.adhydro_data_store_watershed_name, 
                                watershed.adhydro_data_store_subbasin_name, 
                                main_settings.adhydro_prediction_directory)
    
    session.close()
              

def delete_old_watershed_kml_files(watershed):
    """
    Removes old watershed kml files from system
    """
    old_kml_file_location = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                         'public','kml',watershed.folder_name)
    #remove old kml files on local server
    #drainange line
    try:
        if watershed.kml_drainage_line_layer:
            os.remove(os.path.join(old_kml_file_location, 
                                   watershed.kml_drainage_line_layer))
    except OSError:
        pass
    #catchment
    try:
        if watershed.kml_catchment_layer:
            os.remove(os.path.join(old_kml_file_location, 
                                   watershed.kml_catchment_layer))
    except OSError:
        pass
    #gage
    try:
        if watershed.kml_gage_layer:
            os.remove(os.path.join(old_kml_file_location, 
                                   watershed.kml_gage_layer))
    except OSError:
        pass
    #folder
    try:
        os.rmdir(old_kml_file_location)
    except OSError:
        pass

def purge_remove_geoserver_layer(layer_id, engine):
    """
    completely remove geoserver layer
    """
    engine.delete_layer(layer_id, purge=True, recurse=True)
    engine.delete_resource(layer_id, purge=True, recurse=True)
    engine.delete_store(layer_id, purge=True, recurse=True)

def delete_old_watershed_geoserver_files(watershed):
    """
    Removes old watershed geoserver files from system
    """
    engine = GeoServerSpatialDatasetEngine(endpoint="%s/rest" % watershed.geoserver.url, 
                           username=watershed.geoserver.username,
                           password=watershed.geoserver.password)

    if watershed.geoserver_drainage_line_uploaded:
        purge_remove_geoserver_layer(watershed.geoserver_drainage_line_layer, 
                                     engine)
    if watershed.geoserver_catchment_uploaded:
        purge_remove_geoserver_layer(watershed.geoserver_catchment_layer,
                                     engine)
    if watershed.geoserver_gage_uploaded:
        purge_remove_geoserver_layer(watershed.geoserver_gage_layer, engine) 

def delete_old_watershed_files(watershed):
    """
    Removes old watershed files from system
    """
    #remove old kml files
    print 'delete kml'
    delete_old_watershed_kml_files(watershed)
    #remove old geoserver files
    print 'delete geoserver'
    delete_old_watershed_geoserver_files(watershed)
    #remove old ADHydro prediction files
    print 'delete watershed'
    delete_old_watershed_prediction_files(watershed)

def adhydro_find_most_current_file(path_to_watershed_files, date_string):
    """""
    Finds the current output from downscaled ADHydro forecasts
    """""
    if(date_string=="most_recent"):
        if not os.path.exists(path_to_watershed_files):
            return None
        prediction_files = sorted(glob(os.path.join(path_to_watershed_files,"*.nc")),
                                  reverse=True)
    else:
        #RapidResult_20150405T2300Z_CF.nc
        prediction_files = ["RapidResult_%s_CF.nc" % date_string]
    for prediction_file in prediction_files:
        try:
            path_to_file = os.path.join(path_to_watershed_files, prediction_file)
            if os.path.exists(path_to_file):
                return path_to_file
        except Exception as ex:
            print ex
            pass
    #there are no files found
    return None

def format_name(string):
    """
    Formats watershed name for code
    """
    if string:
        formatted_string = string.strip().replace(" ", "_").lower()
        formatted_string = re.sub(r'[^a-zA-Z0-9_-]', '', formatted_string)
        while formatted_string.startswith("-") or formatted_string.startswith("_"):
            formatted_string = formatted_string[1:]
    else:
        formatted_string = ""
    return formatted_string

def format_watershed_title(watershed, subbasin):
    """
    Formats title for watershed in navigation
    """
    max_length = 30
    watershed = watershed.strip()
    subbasin = subbasin.strip()
    watershed_length = len(watershed)
    if(watershed_length>max_length):
        return watershed[:max_length-1].strip() + "..."
    max_length -= watershed_length
    subbasin_length = len(subbasin)
    if(subbasin_length>max_length):
        return (watershed + " (" + subbasin[:max_length-3].strip() + " ...)")
    return (watershed + " (" + subbasin + ")")

def get_cron_command():
    """
    Gets cron command for downloading datasets
    """
    #/usr/lib/tethys/src/tethys_apps/tethysapp/erfp_tool/cron/load_datasets.py
    local_directory = os.path.dirname(os.path.abspath(__file__))
    delimiter = ""
    if "/" in local_directory:
        delimiter = "/"
    elif "\\" in local_directory:
        delimiter = "\\"
    virtual_env_path = ""
    if delimiter and local_directory:
        virtual_env_path = delimiter.join(local_directory.split(delimiter)[:-4])
        command = '%s %s' % (os.path.join(virtual_env_path,'bin','python'), 
                              os.path.join(local_directory, 'load_datasets.py'))
        return command
    else:
        return None

def get_reach_index(reach_id, prediction_file):
    """
    Gets the index of the reach from the COMID 
    """
    data_nc = NET.Dataset(prediction_file, mode="r")
#    com_ids = len(data_nc.variables['channelSurfacewaterDepth'][0])-1
    data_nc.close()
    try:
        reach_index = reach_id
#        reach_index = np.where(com_ids==int(reach_id))[0][0]
    except Exception as ex:
        print ex
        reach_index = None
        pass
    return reach_index                

def get_subbasin_list(file_path):
    """
    Gets a list of subbasins in the watershed
    """
    subbasin_list = []
    drainage_line_kmls = glob(os.path.join(file_path, '*drainage_line.kml'))
    for drainage_line_kml in drainage_line_kmls:
        subbasin_name = "-".join(os.path.basename(drainage_line_kml).split("-")[:-1])
        if subbasin_name not in subbasin_list:
            subbasin_list.append(subbasin_name)
    catchment_kmls = glob(os.path.join(file_path, '*catchment.kml'))
    for catchment_kml in catchment_kmls:
        subbasin_name = "-".join(os.path.basename(catchment_kml).split("-")[:-1])
        if subbasin_name not in subbasin_list:
            subbasin_list.append(subbasin_name)
    subbasin_list.sort()
    return subbasin_list
   
def handle_uploaded_file(f, file_path, file_name):
    """
    Uploads file to specified path
    """
    #remove old file if exists
    try:
        os.remove(os.path.join(file_path, file_name))
    except OSError:
        pass
    #make directory
    if not os.path.exists(file_path):
        os.mkdir(file_path)
    #upload file    
    with open(os.path.join(file_path,file_name), 'wb+') as destination:
        for chunk in f.chunks():
            destination.write(chunk)

def user_permission_test(user):
    """
    User needs to be superuser or staff
    """
    return user.is_superuser or user.is_staff