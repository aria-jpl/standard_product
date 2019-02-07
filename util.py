#!/usr/bin/env python 
import os, sys, time, json, requests, logging
import re, traceback, argparse, copy, bisect
from xml.etree import ElementTree
#from hysds_commons.job_utils import resolve_hysds_job
#from hysds.celery import app
from UrlUtils import UrlUtils
from shapely.geometry import Polygon
from shapely.ops import cascaded_union
import datetime
import dateutil.parser
from datetime import datetime, timedelta
#import groundTrack
from osgeo import ogr, osr
import elasticsearch
import lightweight_water_mask
from dateutil import parser
import pytz

#logger = logging.getLogger(os.path.splitext(os.path.basename(__file__))[0])
#logger.setLevel(logging.INFO)
#logger.addFilter(LogFilter())
log_format = "[%(asctime)s: %(levelname)s/%(funcName)s] %(message)s"
logging.basicConfig(format=log_format, level=logging.INFO)

class LogFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, 'id'): record.id = '--'
        return True

logger = logging.getLogger('util')
logger.setLevel(logging.INFO)
logger.addFilter(LogFilter())

DATE_RE = re.compile(r'(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})T(?P<hour>\d{2}):(?P<min>\d{2}):(?P<sec>\d{2}).*$')

SLC_RE = re.compile(r'(?P<mission>S1\w)_IW_SLC__.*?' +
                    r'_(?P<start_year>\d{4})(?P<start_month>\d{2})(?P<start_day>\d{2})' +
                    r'T(?P<start_hour>\d{2})(?P<start_min>\d{2})(?P<start_sec>\d{2})' +
                    r'_(?P<end_year>\d{4})(?P<end_month>\d{2})(?P<end_day>\d{2})' +
                    r'T(?P<end_hour>\d{2})(?P<end_min>\d{2})(?P<end_sec>\d{2})_.*$')

# acquisition-S1A_IW_SLC__1SSV_20160203T004751_20160203T004818_009775_00E4B2_A0B8
ACQ_RE = re.compile(r'(?P<mission>acquisition-S1\w)_IW_SLC__.*?' +
                    r'_(?P<start_year>\d{4})(?P<start_month>\d{2})(?P<start_day>\d{2})' +
                    r'T(?P<start_hour>\d{2})(?P<start_min>\d{2})(?P<start_sec>\d{2})' +
                    r'_(?P<end_year>\d{4})(?P<end_month>\d{2})(?P<end_day>\d{2})' +
                    r'T(?P<end_hour>\d{2})(?P<end_min>\d{2})(?P<end_sec>\d{2})_.*$')



#acquisition-Sentinel-1B_20161003T020729.245_35_IW-esa_scihub
ACQ_RE_v2_0= re.compile(r'(?P<mission>acquisition-Sentinel-1\w)_' +
                    r'(?P<start_year>\d{4})(?P<start_month>\d{2})(?P<start_day>\d{2})' +
                    r'T(?P<start_hour>\d{2})(?P<start_min>\d{2})(?P<start_sec>\d{2}).*$')

IFG_ID_TMPL = "S1-IFG_R{}_M{:d}S{:d}_TN{:03d}_{:%Y%m%dT%H%M%S}-{:%Y%m%dT%H%M%S}_s123-{}-{}-standard_product"
RSP_ID_TMPL = "S1-SLCP_R{}_M{:d}S{:d}_TN{:03d}_{:%Y%m%dT%H%M%S}-{:%Y%m%dT%H%M%S}_s{}-{}-{}"

BASE_PATH = os.path.dirname(__file__)
MISSION = 'S1A'



class ACQ:
    def __init__(self, acq_id, download_url, tracknumber, location, starttime, endtime, direction, orbitnumber, identifier, pv, platform = None  ):
        self.acq_id=acq_id,
        self.download_url = download_url
        self.tracknumber = tracknumber
        self.location= location
        self.starttime = starttime
        self.endtime = endtime
        self.pv = pv
        self.direction = direction
        self.orbitnumber = orbitnumber
        self.identifier = identifier
        self.platform = platform
        self.covers_only_water = lightweight_water_mask.covers_only_water(location)
        self.covers_only_land = lightweight_water_mask.covers_only_land(location)
        
        #print("%s, %s, %s, %s, %s, %s, %s, %s, %s, %s" %(acq_id, download_url, tracknumber, location, starttime, endtime, direction, orbitnumber, identifier, pv))



# set logger
log_format = "[%(asctime)s: %(levelname)s/%(name)s/%(funcName)s] %(message)s"
logging.basicConfig(format=log_format, level=logging.INFO)

class LogFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, 'id'): record.id = '--'
        return True

logger = logging.getLogger(os.path.splitext(os.path.basename(__file__))[0])
logger.setLevel(logging.INFO)
logger.addFilter(LogFilter())


BASE_PATH = os.path.dirname(__file__)
MOZART_ES_ENDPOINT = "MOZART"
GRQ_ES_ENDPOINT = "GRQ"

def print_acq(acq):
    print("%s, %s, %s, %s, %s, %s, %s, %s, %s, %s" %(acq.acq_id, acq.download_url, acq.tracknumber, acq.location, acq.starttime, acq.endtime, acq.direction, acq.orbitnumber, acq.identifier, acq.pv))

def group_acqs_by_orbit_number_from_metadata(frames):
    return group_acqs_by_orbit_number(create_acqs_from_metadata(frames))

def group_acqs_by_track_date_from_metadata(frames):
    return group_acqs_by_track_date(create_acqs_from_metadata(frames))

def group_acqs_by_track_date(acqs):
    print("\ngroup_acqs_by_track_date")
    grouped = {}
    acqs_info = {}
    for acq in acqs:
        acqs_info[acq.acq_id] = acq
        match = SLC_RE.search(acq.identifier)
        
        if not match:
            raise RuntimeError("Failed to recognize SLC ID %s." % h['_id'])
        print("group_acqs_by_track_date : Year : %s Month : %s Day : %s" %(int(match.group('start_year')), int(match.group('start_month')), int(match.group('start_day'))))

        day_dt = datetime(int(match.group('start_year')),
                          int(match.group('start_month')),
                          int(match.group('start_day')),
                          0, 0, 0)
        print("day_dt : %s " %day_dt)
        #bisect.insort(grouped.setdefault(fields['metadata']['track_number'], {}).setdefault(day_dt, []), h['_id'])
        bisect.insort(grouped.setdefault(acq.tracknumber, {}).setdefault(day_dt, []), acq.acq_id)
    return {"grouped": grouped, "acq_info" : acqs_info}

def group_acqs_by_orbit_number(acqs):
    #print(acqs)
    grouped = {}
    acqs_info = {}
    for acq in acqs:
        acqs_info[acq.acq_id] = acq
        print("acq_id : %s track_number : %s orbit_number : %s acq_pv : %s" %(acq.acq_id, acq.tracknumber, acq.orbitnumber, acq.pv))
        bisect.insort(grouped.setdefault(acq.tracknumber, {}).setdefault(acq.orbitnumber, {}).setdefault(acq.pv, []), acq.acq_id)
        '''
        if track in grouped.keys():
            if orbitnumber in grouped[track].keys():
                if pv in grouped[track][orbitnumber].keys():
                    grouped[track][orbitnumber][pv] = grouped[track][orbitnumber][pv].append(slave_acq)
                else:
                    slave_acqs = [slave_acq]
                    slave_pv = {}
                
                    grouped[track][orbitnumber] = 
        '''
    return {"grouped": grouped, "acq_info" : acqs_info}



def update_acq_pv(acq_id, pv):
    pass


def import_file_by_osks(url):
    osaka.main.get(url)



def get_area(coords):
    '''get area of enclosed coordinates- determines clockwise or counterclockwise order'''
    print("get_area : coords : %s" %coords)
    n = len(coords) # of corners
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        #print("i : %s j: %s, coords[i][1] : %s coords[j][0] : %s coords[j][1] : %s coords[i][0] : %s"  %(i, j, coords[i][1], coords[j][0], coords[j][1], coords[i][0]))
        area += coords[i][1] * coords[j][0]
        area -= coords[j][1] * coords[i][0]
    #area = abs(area) / 2.0
    return area / 2

def get_env_box(env):

    #print("get_env_box env " %env)
    bbox = [
        [ env[3], env[0] ],
        [ env[3], env[1] ],
        [ env[2], env[1] ],
        [ env[2], env[0] ],
    ]
    print("get_env_box box : %s" %bbox)
    return bbox

def isTrackSelected(acqs_land, total_land):
    selected = False
    sum_of_acq_land = 0

    for acq_land in acqs_land:
        sum_of_acq_land+= acq_land

    delta = abs(sum_of_acq_land - total_land)
    if delta/total_land<.01:
        selected = True

    return selected

def get_ipf_count(acqs):
    pv_list = []
    for acq in acqs:
        if acq.pv:
            pv_list.append(acq.pv)
        else:
            pv = get_processing_version(acq.identifier)
            if pv:
                update_acq_pv(acq.acq_id, acq.pv)
                pv_list.append(pv)

    return len(list(set(pv_list)))

def get_ipf_count_by_acq_id(acq_ids, acq_info):
    acqs = []
    for acq_id in acq_ids:
        acq = acq_info[acq_id]
        acqs.append(acq)
    return get_ipf_count(acqs)


def get_union_data_from_acqs(acqs):
    starttimes = []
    endtimes = []
    polygons = []
    track = None
    direction = None
    orbitnumber = None
    pv_list = []

    for acq in acqs:
        if acq.pv:
            pv_list.append(acq.pv)
        else:
            pv = get_processing_version(acq.identifier)
            if pv:
                update_acq_pv(acq.acq_id, pv)
                pv_list.append(pv)

        starttimes.append(get_time(acq.starttime))
        endtimes.append(get_time(acq.endtime)) 
        polygons.append(acq.location)
        track = acq.tracknumber
        direction = acq.direction
        orbitnumber =acq.orbitnumber
    starttime = sorted(starttimes)[0]
    endtime = sorted(endtimes, reverse=True)[0]
    location = get_union_geometry(polygons)
    ipf_count = len(list(set(pv_list)))

    return ipf_count, starttime.strftime("%Y-%m-%d %H:%M:%S"), endtime.strftime("%Y-%m-%d %H:%M:%S"), location, track, direction, orbitnumber 


def create_acq_obj_from_metadata(acq):
    #create ACQ(acq_id, download_url, tracknumber, location, starttime, endtime, direction, orbitnumber, identifier, pv)
    #print("ACQ = %s\n" %acq)
    acq_data = acq #acq['fields']['partial'][0]
    missing_pcv_list = list()
    acq_id = acq['id']
    print("logger level : %s" %logger.level)
    print("Creating Acquisition Obj for acq_id : %s : %s" %(type(acq_id), acq_id))
    '''
    match = SLC_RE.search(acq_id)
    if not match:
        print("SLC_RE : %s" %SLC_RE)
        print("Error : No Match : %s" %acq_id)
        return None
    print("SLC_MATCHED")
    '''

    download_url = acq_data['metadata']['download_url']
    track = acq_data['metadata']['track_number']
    location = acq_data['metadata']['location']
    starttime = acq_data['starttime']
    endtime = acq_data['endtime']
    direction = acq_data['metadata']['direction']
    orbitnumber = acq_data['metadata']['orbitNumber']
    platform = acq_data['metadata']['platform']
    identifier = acq_data['metadata']['identifier']
    pv = None
    if "processing_version" in  acq_data['metadata']:
        pv = acq_data['metadata']['processing_version']
        print("pv found in metadata : %s" %pv)
    else:
        missing_pcv_list.append(acq_id)
        print("pv NOT in metadata,so calling ASF")
        pv = get_processing_version(identifier)
        #print("ASF returned pv : %s" %pv)
        #update_acq_pv(acq_id, pv) 
    return ACQ(acq_id, download_url, track, location, starttime, endtime, direction, orbitnumber, identifier, pv, platform)


def create_acqs_from_metadata(frames):
    acqs = []
    #print("frame length : %s" %len(frames))
    for acq in frames:
        print("create_acqs_from_metadata : %s" %acq['id'])
        acq_obj = create_acq_obj_from_metadata(acq)
        if acq_obj:
            acqs.append(acq_obj)
    return acqs

def get_result_dict():
    result = {}
    result['aoi'] = None
    result['track'] = None
    result['dt']  = None
    result['acq_union_land_area'] = None
    result['acq_union_aoi_intersection'] = None
    result['ACQ_POEORB_AOI_Intersection'] = None   
    result['ACQ_Union_POEORB_Land'] = None
    result['Track_POEORB_Land'] = None
    result['Track_AOI_Intersection'] = None
    result['res'] = None
    result['WATER_MASK_PASSED'] = None
    result['matched'] = None
    result['BL_PASSED'] = None
    result['master_ipf_count'] = None
    result['slave_ipf_count'] = None
    result['candidate_pairs'] = None

    return result

def dataset_exists(id, index_suffix):
    """Query for existence of dataset by ID."""

    # es_url and es_index
    uu = UrlUtils()
    es_url = uu.rest_url
    es_index = "grq_*_{}".format(index_suffix.lower())
    
    # query
    query = {
        "query":{
            "bool":{
                "must":[
                    { "term":{ "_id": id } },
                ]
            }
        },
        "fields": [],
    }

    if es_url.endswith('/'):
        search_url = '%s%s/_search' % (es_url, es_index)
    else:
        search_url = '%s/%s/_search' % (es_url, es_index)
    r = requests.post(search_url, data=json.dumps(query))
    if r.status_code == 200:
        result = r.json()
        total = result['hits']['total']
    else:
        print("Failed to query %s:\n%s" % (es_url, r.text))
        print("query: %s" % json.dumps(query, indent=2))
        print("returned: %s" % r.text)
        if r.status_code == 404: total = 0
        else: r.raise_for_status()
    return False if total == 0 else True

def get_dataset(id, index_suffix):
    """Query for existence of dataset by ID."""

    # es_url and es_index
    uu = UrlUtils()
    es_url = uu.rest_url
    es_index = "grq_*_{}".format(index_suffix.lower())
    #es_index = "grq"

    # query
    query = {
        "query":{
            "bool":{
                "must":[
                    { "term":{ "_id": id } }
                ]
            }
        },
        "fields": []
    }

    print(query)

    if es_url.endswith('/'):
        search_url = '%s%s/_search' % (es_url, es_index)
    else:
        search_url = '%s/%s/_search' % (es_url, es_index)
    r = requests.post(search_url, data=json.dumps(query))

    if r.status_code != 200:
        print("Failed to query %s:\n%s" % (es_url, r.text))
        print("query: %s" % json.dumps(query, indent=2))
        print("returned: %s" % r.text)
        r.raise_for_status()

    result = r.json()
    print(result['hits']['total'])
    return result

def get_dataset(id):
    """Query for existence of dataset by ID."""

    # es_url and es_index
    uu = UrlUtils()
    es_url = uu.rest_url
    #es_index = "grq_*_{}".format(index_suffix.lower())
    es_index = "grq"

    # query
    query = {
        "query":{
            "bool":{
                "must":[
                    { "term":{ "_id": id } }
                ]
            }
        },
        "fields": []
    }

    print(query)

    if es_url.endswith('/'):
        search_url = '%s%s/_search' % (es_url, es_index)
    else:
        search_url = '%s/%s/_search' % (es_url, es_index)
    r = requests.post(search_url, data=json.dumps(query))

    if r.status_code != 200:
        print("Failed to query %s:\n%s" % (es_url, r.text))
        print("query: %s" % json.dumps(query, indent=2))
        print("returned: %s" % r.text)
        r.raise_for_status()

    result = r.json()
    print(result['hits']['total'])
    return result


def query_es(query, es_index=None):
    """Query ES."""
    uu = UrlUtils()
    es_url = uu.rest_url
    rest_url = es_url[:-1] if es_url.endswith('/') else es_url
    url = "{}/_search?search_type=scan&scroll=60&size=100".format(rest_url)
    if es_index:
        url = "{}/{}/_search?search_type=scan&scroll=60&size=100".format(rest_url, es_index)
    #print("url: {}".format(url))
    r = requests.post(url, data=json.dumps(query))
    r.raise_for_status()
    scan_result = r.json()
    #print("scan_result: {}".format(json.dumps(scan_result, indent=2)))
    count = scan_result['hits']['total']
    if '_scroll_id' not in scan_result:
        print("_scroll_id not found in scan_result. Returning empty array for the query :\n%s" %query)
        return []

    scroll_id = scan_result['_scroll_id']
    hits = []
    while True:
        r = requests.post('%s/_search/scroll?scroll=60m' % rest_url, data=scroll_id)
        res = r.json()
        scroll_id = res['_scroll_id']
        if len(res['hits']['hits']) == 0: break
        hits.extend(res['hits']['hits'])
    return hits


def query_es2(query, es_index=None):
    """Query ES."""
    print(query)
    uu = UrlUtils()
    es_url = uu.rest_url
    rest_url = es_url[:-1] if es_url.endswith('/') else es_url
    url = "{}/_search?search_type=scan&scroll=60&size=100".format(rest_url)
    if es_index:
        url = "{}/{}/_search?search_type=scan&scroll=60&size=100".format(rest_url, es_index)
    #print("url: {}".format(url))
    r = requests.post(url, data=json.dumps(query))
    r.raise_for_status()
    scan_result = r.json()
    #print("scan_result: {}".format(json.dumps(scan_result, indent=2)))
    count = scan_result['hits']['total']
    if count == 0:
        return []

    if '_scroll_id' not in scan_result:
        print("_scroll_id not found in scan_result. Returning empty array for the query :\n%s" %query)
        return []

    scroll_id = scan_result['_scroll_id']
    hits = []
    while True:
        r = requests.post('%s/_search/scroll?scroll=60m' % rest_url, data=scroll_id)
        res = r.json()
        scroll_id = res['_scroll_id']
        if len(res['hits']['hits']) == 0: break
        hits.extend(res['hits']['hits'])
    return hits

def print_groups(grouped_matched):
    for track in grouped_matched["grouped"]:
        print("\nTrack : %s" %track)
        for day_dt in sorted(grouped_matched["grouped"][track], reverse=True):
            print("\tDate : %s" %day_dt)
            for acq in grouped_matched["grouped"][track][day_dt][pv]:
                print("\t\t%s" %(acq[0]))


def get_complete_grq_data(id):
    uu = UrlUtils()
    es_url = uu.rest_url
    es_index = "grq"
    query = {
      "query": {
        "bool": {
          "must": [
            {
              "term": {
                "_id": id
              }
            }
          ]
        }
      }
    }


    print(query)

    if es_url.endswith('/'):
        search_url = '%s%s/_search' % (es_url, es_index)
    else:
        search_url = '%s/%s/_search' % (es_url, es_index)
    r = requests.post(search_url, data=json.dumps(query))

    if r.status_code != 200:
        err_str = "Failed to query %s:\n%s" % (es_url, r.text)
        err_str += "\nreturned: %s" % r.text
        print(err_str)
        print("query: %s" % json.dumps(query, indent=2))
        #r.raise_for_status()
        raise RuntimeError(err_str)
    '''
    if r.status_code != 200:
        print("Failed to query %s:\n%s" % (es_url, r.text))
        print("query: %s" % json.dumps(query, indent=2))
        print("returned: %s" % r.text)
        r.raise_for_status()
    '''

    result = r.json()
    print(result['hits']['total'])
    return result['hits']['hits']

def get_partial_grq_data(id):
    uu = UrlUtils()
    es_url = uu.rest_url
    es_index = "grq"

    query = {
        "query": {
            "term": {
                "_id": id,
            },
        },
        "partial_fields" : {
            "partial" : {
                "exclude" : "city",
            }
        }
    }

    print(query)

    if es_url.endswith('/'):
        search_url = '%s%s/_search' % (es_url, es_index)
    else:
        search_url = '%s/%s/_search' % (es_url, es_index)
    r = requests.post(search_url, data=json.dumps(query))

    if r.status_code != 200:
        err_str = "Failed to query %s:\n%s" % (es_url, r.text)
        err_str += "\nreturned: %s" % r.text
        print(err_str)
        print("query: %s" % json.dumps(query, indent=2))
        #r.raise_for_status()
        raise RuntimeError(err_str)

    '''
    if r.status_code != 200:
        print("Failed to query %s:\n%s" % (es_url, r.text))
        print("query: %s" % json.dumps(query, indent=2))
        print("returned: %s" % r.text)
        r.raise_for_status()
    '''

    result = r.json()
    print(result['hits']['total'])
    return result['hits']['hits'][0]

def get_acquisition_data(id):
    uu = UrlUtils()
    es_url = uu.rest_url
    es_index = "grq_*_*acquisition*"
    query = {
      "query": {
        "bool": {
          "must": [
            {
              "term": {
                "_id": id
              }
            }
          ]
        }
      },
      "partial_fields": {
        "partial": {
          "include": [
            "id",
            "dataset_type",
            "dataset",
            "metadata",
            "city",
            "continent"
          ]
        }
      }
    }


    print(query)

    if es_url.endswith('/'):
        search_url = '%s%s/_search' % (es_url, es_index)
    else:
        search_url = '%s/%s/_search' % (es_url, es_index)
    r = requests.post(search_url, data=json.dumps(query))


    if r.status_code != 200:
        err_str = "Failed to query %s:\n%s" % (es_url, r.text)
        err_str += "\nreturned: %s" % r.text
        print(err_str)
        print("query: %s" % json.dumps(query, indent=2))
        #r.raise_for_status()
        raise RuntimeError(err_str)
    '''
    if r.status_code != 200:
        print("Failed to query %s:\n%s" % (es_url, r.text))
        print("query: %s" % json.dumps(query, indent=2))
        print("returned: %s" % r.text)
        r.raise_for_status()
    '''
    result = r.json()
    print(result['hits']['total'])
    return result['hits']['hits']


def group_acqs_by_track(frames):
    grouped = {}
    acq_info = {}
    #print("frame length : %s" %len(frames))
    for acq in frames:
        #print("ACQ : %s" %acq)
        acq_data = acq # acq['fields']['partial'][0]
        acq_id = acq['id']
        #print("acq_id : %s : %s" %(type(acq_id), acq_id))
        '''
        match = SLC_RE.search(acq_id)
        if not match:
            print("No Match : %s" %acq_id)
            continue
        '''
        download_url = acq_data['metadata']['download_url']
        track = acq_data['metadata']['track_number']
        location = acq_data['metadata']['location']
        starttime = acq_data['starttime']
        endtime = acq_data['endtime']
        direction = acq_data['metadata']['direction']
        orbitnumber = acq_data['metadata']['orbitNumber']
        identifier = acq['metadata']['identifier']
        platform = acq_data['metadata']['platform']

        pv = None
        if "processing_version" in  acq_data['metadata']:
            pv = acq_data['metadata']['processing_version']
        this_acq = ACQ(acq_id, download_url, track, location, starttime, endtime, direction, orbitnumber, identifier, pv, platform)
        acq_info[acq_id] = this_acq

        #print("Adding %s : %s : %s : %s" %(track, orbitnumber, pv, acq_id))
        #print(grouped)
        bisect.insort(grouped.setdefault(track, []), acq_id)
        '''
        if track in grouped.keys():
            if orbitnumber in grouped[track].keys():
                if pv in grouped[track][orbitnumber].keys():
                    grouped[track][orbitnumber][pv] = grouped[track][orbitnumber][pv].append(slave_acq)
                else:
                    slave_acqs = [slave_acq]
                    slave_pv = {}
                
                    grouped[track][orbitnumber] = 
        '''
    return {"grouped": grouped, "acq_info" : acq_info}


def getUpdatedTime(s, m):
    #date = dateutil.parser.parse(s, ignoretz=True)
    new_date = s + timedelta(minutes = m)
    return new_date

def getUpdatedTimeStr(s, m):
    date = dateutil.parser.parse(s, ignoretz=True)
    new_date = date + timedelta(minutes = m)
    return new_date

def is_overlap(geojson1, geojson2):
    '''returns True if there is any overlap between the two geojsons. The geojsons
    are just a list of coordinate tuples'''
    p3=0
    p1=Polygon(geojson1[0])
    p2=Polygon(geojson2[0])
    if p1.intersects(p2):
        p3 = p1.intersection(p2).area/p1.area
    return p1.intersects(p2), p3

def find_overlap_within_aoi(loc1, loc2, aoi_loc):
    '''returns True if there is any overlap between the two geojsons. The geojsons
    are just a list of coordinate tuples'''
    print("find_overlap_within_aoi : %s\n%s\n%s" %(loc1, loc2, aoi_loc))
    geojson1 = get_intersection(loc1, aoi_loc)
    geojson2 = get_intersection(loc1, aoi_loc)
    p3=0
    print("find_overlap_within_aoi : geojson1 : %s\n geojson2 : %s" %(geojson1, geojson2))
    if type(geojson1) is tuple:
        geojson1 = geojson1[0]
    if type(geojson2) is tuple:
        geojson2 = geojson2[0]

    p1=Polygon(geojson1["coordinates"][0])
    p2=Polygon(geojson2["coordinates"][0])
    if p1.intersects(p2):
        p3 = p1.intersection(p2).area/p1.area
    return p1.intersects(p2), p3



def is_within(geojson1, geojson2):
    '''returns True if there is any overlap between the two geojsons. The geojsons
    are just a list of coordinate tuples'''
    p1=Polygon(geojson1[0])
    p2=Polygon(geojson2[0])
    return p1.within(p2)


def find_overlap_match(master_acq, slave_acqs):
    #print("\n\nmaster info : %s : %s : %s :%s" %(master_acq.tracknumber, master_acq.orbitnumber, master_acq.pv, master_acq.acq_id))
    #print("slave info : ")
    master_loc = master_acq.location["coordinates"]

    #print("\n\nmaster_loc : %s" %master_loc)
    overlapped_matches = {}
    for slave in slave_acqs:
        print("SLAVE : %s" %slave.location)
        slave_loc = slave.location["coordinates"]
        #print("\n\nslave_loc : %s" %slave_loc)
        is_over, overlap = is_overlap(master_loc, slave_loc)
        print("is_overlap : %s" %is_over)
        print("overlap area : %s" %overlap)
        if is_over:
            overlapped_matches[slave.acq_id] = slave
            print("Overlapped slave : %s" %slave.acq_id)

    return overlapped_matches

def ref_truncated(ref_scene, matched_footprints, covth=.99):
    """Return True if reference scene will be truncated."""

    # geometries are in lat/lon projection
    src_srs = osr.SpatialReference()
    src_srs.SetWellKnownGeogCS("WGS84")
    #src_srs.ImportFromEPSG(4326)

    # use projection with unit as meters
    tgt_srs = osr.SpatialReference()
    tgt_srs.ImportFromEPSG(3857)

    # create transformer
    transform = osr.CoordinateTransformation(src_srs, tgt_srs)
    
    # get polygon to fill if specified
    ref_geom = ogr.CreateGeometryFromJson(json.dumps(ref_scene.location))
    ref_geom_tr = ogr.CreateGeometryFromJson(json.dumps(ref_scene.location))
    ref_geom_tr.Transform(transform)
    ref_geom_tr_area = ref_geom_tr.GetArea() # in square meters
    print("Reference GeoJSON: %s" % ref_geom.ExportToJson())

    # get union geometry of all matched scenes
    matched_geoms = []
    matched_union = None
    matched_geoms_tr = []
    matched_union_tr = None
    ids = sorted(matched_footprints.keys())
    #ids.sort()
    #print("ids: %s" % len(ids))
    for id in ids:
        geom = ogr.CreateGeometryFromJson(json.dumps(matched_footprints[id]))
        geom_tr = ogr.CreateGeometryFromJson(json.dumps(matched_footprints[id]))
        geom_tr.Transform(transform)
        matched_geoms.append(geom)
        matched_geoms_tr.append(geom_tr)
        if matched_union is None:
            matched_union = geom
            matched_union_tr = geom_tr
        else:
            matched_union = matched_union.Union(geom)
            matched_union_tr = matched_union_tr.Union(geom_tr)
    matched_union_geojson =  json.loads(matched_union.ExportToJson())
    print("Matched union GeoJSON: %s" % json.dumps(matched_union_geojson))
    
    # check matched_union disjointness
    if len(matched_union_geojson['coordinates']) > 1:
        print("Matched union is a disjoint geometry.")
        return True
            
    # check that intersection of reference and stitched scenes passes coverage threshold
    ref_int = ref_geom.Intersection(matched_union)
    ref_int_tr = ref_geom_tr.Intersection(matched_union_tr)
    ref_int_tr_area = ref_int_tr.GetArea() # in square meters
    print("Reference intersection GeoJSON: %s" % ref_int.ExportToJson())
    print("area (m^2) for intersection: %s" % ref_int_tr_area)
    cov = ref_int_tr_area/ref_geom_tr_area
    print("coverage: %s" % cov)
    if cov < covth:
        print("Matched union doesn't cover at least %s%% of the reference footprint." % (covth*100.))
        return True
   
    return False
def get_union_geojson_acqs(acqs):
    geoms = []
    union = None
    for acq in acqs:
        geom = ogr.CreateGeometryFromJson(json.dumps(acq.location))
        geoms.append(geom)
        union = geom if union is None else union.Union(geom)
    union_geojson =  json.loads(union.ExportToJson())
    return union_geojson
    
def get_union_geometry(geojsons):
    """Return polygon of union of acquisition footprints."""

    # geometries are in lat/lon projection
    #src_srs = osr.SpatialReference()
    #src_srs.SetWellKnownGeogCS("WGS84")
    #src_srs.ImportFromEPSG(4326)

    # get union geometry of all scenes
    geoms = []
    union = None
    for geojson in geojsons:
        geom = ogr.CreateGeometryFromJson(json.dumps(geojson))
        geoms.append(geom)
        union = geom if union is None else union.Union(geom)
    union_geojson =  json.loads(union.ExportToJson())
    return union_geojson

def get_acq_orbit_polygon(starttime, endtime, orbit_dir):
    pass
    
def get_intersection(js1, js2):
    intersection = None
    try:
        print("intersection between :\n %s\nAND\n%s\n\n" %(js1, js2))
        poly1 = ogr.CreateGeometryFromJson(json.dumps(js1, indent=2, sort_keys=True))
        print("\n\npoly1 : %s\n\n" %poly1)


        poly2 = ogr.CreateGeometryFromJson(json.dumps(js2, indent=2, sort_keys=True))
        print("\n\npoly2 : %s\n\n" %poly2)
    
        intersection = poly1.Intersection(poly2)
    except Exception as err:
        err_value = "Error intersecting two polygon : %s" %str(err)
        print(err_value)
        raise RuntimeError(err_value)

    return True, json.loads(intersection.ExportToJson()), intersection.GetEnvelope()

def get_combined_polygon():
    pass

def get_time(t):

    logger.info("get_time(t) : %s" %t)
    t = parser.parse(t).strftime('%Y-%m-%dT%H:%M:%S')
    t1 = datetime.strptime(t, '%Y-%m-%dT%H:%M:%S')
    logger.info("returning : %s" %t1)
    return t1


def get_processing_version(slc):
    pv = get_processing_version_from_scihub(slc)
    if not pv:
        pv = get_processing_version_from_asf(slc)
    return pv

def get_processing_version_from_scihub(slc):

    ipf_string = None

    return ipf_string

def get_processing_version_from_asf(slc):

    ipf = None

    try:
        # query the asf search api to find the download url for the .iso.xml file
        request_string = 'https://api.daac.asf.alaska.edu/services/search/param?platform=SA,SB&processingLevel=METADATA_SLC&granule_list=%s&output=json' %slc
        response = requests.get(request_string)

        response.raise_for_status()
        results = json.loads(response.text)

        # download the .iso.xml file, assumes earthdata login credentials are in your .netrc file
        response = requests.get(results[0][0]['downloadUrl'])
        response.raise_for_status()

        # parse the xml file to extract the ipf version string
        root = ElementTree.fromstring(response.text.encode('utf-8'))
        ns = {'gmd': 'http://www.isotc211.org/2005/gmd', 'gmi': 'http://www.isotc211.org/2005/gmi', 'gco': 'http://www.isotc211.org/2005/gco'}
        ipf_string = root.find('gmd:composedOf/gmd:DS_DataSet/gmd:has/gmi:MI_Metadata/gmd:dataQualityInfo/gmd:DQ_DataQuality/gmd:lineage/gmd:LI_Lineage/gmd:processStep/gmd:LI_ProcessStep/gmd:description/gco:CharacterString', ns).text

        if ipf_string:
            ipf = ipf_string.split('version')[1].split(')')[0].strip()
    except Exception as err:
        print("get_processing_version_from_asf : %s" %str(err))
 
        
    return ipf

def print_acquisitions(aoi_id, acqs):
    print("PRINT_ACQS")
    for acq in acqs:
        #aoi_id = acq_data['aoi_id']
        print("aoi : %s track: %s orbitnumber : %s pv: %s acq_id : %s" %(aoi_id, acq.tracknumber, acq.orbitnumber, acq.pv, acq.acq_id))
    print("\n")

def update_doc(body=None, index=None, doc_type=None, doc_id=None):
    uu = UrlUtils()
    es_url = uu.rest_url
    ES = elasticsearch.Elasticsearch(es_url)
    ES.update(index= index, doc_type= doc_type, id=doc_id,
              body=body)


def get_track(info):
    """Get track number."""

    tracks = {}
    for id in info:
        print(id)
        h = info[id]
        fields = h["_source"]
        track = fields['metadata']['track_number']
        print(track)
        tracks.setdefault(track, []).append(id)
    if len(tracks) != 1:
        print(tracks)
        
        raise RuntimeError("Failed to find SLCs for only 1 track : %s" %tracks)
    return track

def get_bool_param(ctx, param):
    """Return bool param from context."""

    if param in ctx and isinstance(ctx[param], bool): return ctx[param]
    return True if ctx.get(param, 'true').strip().lower() == 'true' else False

def get_metadata(id, rest_url, url):
    """Get SLC metadata."""

    # query hits
    query = {
        "query": {
            "term": {
                "_id": id
            }
        }
    }
    print("query: {}".format(json.dumps(query, indent=2)))
    r = requests.post(url, data=json.dumps(query))
    r.raise_for_status()
    scan_result = r.json()
    
    count = scan_result['hits']['total']
    if count == 0:
        return []

    if '_scroll_id' not in scan_result:
        print("_scroll_id not found in scan_result. Returning empty array for the query :\n%s" %query)
        return []

    scroll_id = scan_result['_scroll_id']
    hits = []
    while True:
        r = requests.post('%s/_search/scroll?scroll=60m' % rest_url, data=scroll_id)
        res = r.json()
        scroll_id = res['_scroll_id']
        if len(res['hits']['hits']) == 0: break
        hits.extend(res['hits']['hits'])
    if len(hits) == 0:
        raise RuntimeError("Failed to find {}.".format(id))
    return hits[0]

def get_dem_type(info):
    """Get dem type."""

    dem_type = "SRTM+v3"

    dems = {}
    for id in info:
        dem_type = "SRTM+v3"
        h = info[id]
        fields = h["_source"]
        try:
            if 'city' in fields:
                if fields['city'][0]['country_name'] is not None and fields['city'][0]['country_name'].lower() == "united states":
                    dem_type="Ned1"
                dems.setdefault(dem_type, []).append(id)
        except:
            dem_type = "SRTM+v3"

    if len(dems) != 1:
        print("There are more than one type of dem, so selecting SRTM+v3")
        dem_type = "SRTM+v3"
    return dem_type
'''
def get_overlapping_slaves_query(master):
    return get_overlapping_slaves_query(master.starttime, master.endtime, master.location, master.tracknumber, master.direction, master.orbitnumber)
'''
    
def get_overlapping_slaves_query(starttime, location, track, direction, platform, master_orbitnumber, acquisition_version):
    query = {
      "partial_fields": {
        "partial": {
          "exclude": "city"
        }
      },
      "query": {
        "filtered": {
          "filter": {
            "geo_shape": {
              "location": {
                "shape": location
              }
            }
          },
          "query": {
            "bool": {
              "must": [
                {
                  "term": {
                    "dataset_type.raw": "acquisition"
                  }
                },
                {
                 "term": {
                    "metadata.platformname.raw": "Sentinel-1"
                  }
                },
                {
                  "term": {
                    "track_number": track
                  }
                },
                {
                  "term": {
                    "version.raw": acquisition_version
                  }
                },
                {
                  "term": {
                    "direction": direction
                  }
                },
                {
                  "range": {
                    "endtime": {
                      "lt": starttime
                    }
                  }
                }  
              ],
              "must_not": {
                "term": {
                  "orbitNumber": master_orbitnumber
                }
              }
            }
          }
        }
      }
    }



    return query

def get_overlapping_masters_query(master, slave):
    query = {
            "query": {
                "filtered": {
                    "query": {
                        "bool": {
                            "must": [
                                {
                                    "term": {
                                        "dataset.raw": "acquisition-S1-IW_SLC"
                                    }
				
                                }
                            ]
                        }
                    },
                    "filter": {
 			"bool": {
			    "must": [
				{
                                "geo_shape": {
                                    "location": {
                                      "shape": master.location
                                    }
                                }},
				{ "term": { "direction": master.direction }},
	                        { "term": { "orbitNumber": master.orbitnumber }},
			        { "term": { "track_number": master.tracknumber }}
			    ]
			}
                    }
                }
            },
            "partial_fields" : {
                "partial" : {
                        "exclude": "city"
                }
            }
        }    

    return query

def get_overlapping_slaves_query_orbit(master, orbitnumber):
    query = {
            "query": {
                "filtered": {
                    "query": {
                        "bool": {
                            "must": [
                                {
                                    "term": {
                                        "dataset.raw": "acquisition-S1-IW_SLC"
                                    }
				
                                }
                            ]
                        }
                    },
                    "filter": {
 			"bool": {
			    "must": [
				{
                                "geo_shape": {
                                    "location": {
                                      "shape": master.location
                                    }
                                }},
				{	
                                "range" : {
                                    "endtime" : {
                                        "lte" : master.starttime
                
                                    }
                                }},
				{ "term": { "track_number": master.tracknumber }},
                                { "term": { "orbitNumber": orbitnumber }},
				{ "term": { "direction": master.direction }}
			    ],
			"must_not": { "term": { "orbitNumber": master.orbitnumber }}
			}
                    }
                }
            },
            "partial_fields" : {
                "partial" : {
                        "exclude": "city"
                }
            }
        }    

    return query

def create_dataset_json(id, version, met_file, ds_file):
    """Write dataset json."""


    # get metadata
    with open(met_file) as f:
        md = json.load(f)

    ds = {
        'creation_timestamp': "%sZ" % datetime.utcnow().isoformat(),
        'version': version,
        'label': id
    }

    coordinates = None

    try:
        '''
        if 'bbox' in md:
            print("create_dataset_json : met['bbox']: %s" %md['bbox'])
            coordinates = [
                    [
                      [ md['bbox'][0][1], md['bbox'][0][0] ],
                      [ md['bbox'][3][1], md['bbox'][3][0] ],
                      [ md['bbox'][2][1], md['bbox'][2][0] ],
                      [ md['bbox'][1][1], md['bbox'][1][0] ],
                      [ md['bbox'][0][1], md['bbox'][0][0] ]
                    ]
                  ]
        else:
            coordinates = md['union_geojson']['coordinates']
        '''

        coordinates = md['union_geojson']['coordinates']
        cord_area = get_area(coordinates[0])
        if not cord_area>0:
            print("creating dataset json. coordinates are not clockwise, reversing it")
            coordinates = [coordinates[0][::-1]]
            print(coordinates)
            cord_area = get_area(coordinates[0])
            if not cord_area>0:
                print("creating dataset json. coordinates are STILL NOT  clockwise")
        else:
            print("creating dataset json. coordinates are already clockwise")

        ds['location'] =  {'type': 'Polygon', 'coordinates': coordinates}

    except Exception as err:
        logger.warn(str(err))
        logger.warn("Traceback: {}".format(traceback.format_exc()))


    ds['starttime'] = md['starttime']
    ds['endtime'] = md['endtime']

    # write out dataset json
    with open(ds_file, 'w') as f:
        json.dump(ds, f, indent=2)

def get_orbit_date(s):
    date = dateutil.parser.parse(s, ignoretz=True)
    date = date.replace(minute=0, hour=12, second=0)
    return date.isoformat()

def get_isoformat_date(s):
    date = dateutil.parser.parse(s, ignoretz=True)
    return date.isoformat()


def get_orbit_file(orbit_dt, platform):
    print("get_orbit_file : %s : %s" %(orbit_dt, platform))
    hits = query_orbit_file(orbit_dt, orbit_dt, platform)
    #print("get_orbit_file : hits : \n%s\n" %hits)
    print("get_orbit_file returns %s result " %len(hits))
    #return hits


    for hit in hits:
        metadata = hit["metadata"]
        
        id = hit['id']
        orbit_platform = metadata["platform"]
        print(orbit_platform)
        if orbit_platform == platform:
            if "urls" in hit:
                urls = hit["urls"]
                url = urls[0]
                if len(urls)>1:
                    for u in urls:
                        if u.startswith('http://') or u.startswith('https://'):
                            url = u
                            break
            else:
                url = metadata["context"]["localize_urls"][0]["url"]

            if url.startswith('s3://'):
                url = metadata["context"]["localize_urls"][0]["url"]
            
            orbit_url = "%s/%s" % (url, hit['metadata']['archive_filename'])
            return True, id, orbit_url,  hit['metadata']['archive_filename']
    return False, None, None, None


def query_orbit_file(starttime, endtime, platform):
    """Query ES for active AOIs that intersect starttime and endtime."""
    print("query_orbit_file: %s, %s, %s" %(starttime, endtime, platform))
    es_index = "grq_*_s1-aux_poeorb"
    query = {
      "query": {
          "bool": {
              "should": [
                {
                  "bool": {
                    "must": [
                  {
                    "range": {
                      "starttime": {
                        "lte": endtime
                      }
                    }
                  },
                  {
                    "range": {
                      "endtime": {
                        "gte": starttime
                      }
                    }
                  },
                  {
                    "match": {
                      "metadata.dataset": "S1-AUX_POEORB"
                    }
                  },
                  {
                    "match": {
                      "metadata.platform": platform
                    }
                  },
                  {
                    "match": {
                      "_type": "S1-AUX_POEORB"
                    }
                  }
                ]  
              }
            }
          ]
        }
      },
      "partial_fields": {
        "partial": {
          "include": [
            "id",
            "starttime",
            "endtime",
            "metadata.platform",
            "metadata.archive_filename",
            "metadata.context.localize_urls",
            "urls"
          ]
        }
      }
    }

    print(query)
    #return query_es(query)


    # filter inactive
    hits = [i['fields']['partial'][0] for i in query_es(query)]
    #print("hits: {}".format(json.dumps(hits, indent=2)))
    #print("aois: {}".format(json.dumps([i['id'] for i in hits])))
    return hits


def get_dates_mission_from_id(id, scene_type):
    """Return day date, slc start date and slc end date."""
    match = None
    if scene_type.upper().startswith("ACQ"):
        match = ACQ_RE.search(id)
    elif scene_type.upper().startswith("SLC"):
        match = SLC_RE.search(id)

    if not match:
        raise RuntimeError("Failed to recognize SLC ID %s." % id)

    day_dt = datetime(int(match.group('start_year')),
                      int(match.group('start_month')),
                      int(match.group('start_day')),
                      0, 0, 0)
    start_dt = datetime(int(match.group('start_year')),
                            int(match.group('start_month')),
                            int(match.group('start_day')),
                            int(match.group('start_hour')),
                            int(match.group('start_min')),
                            int(match.group('start_sec')))
    end_dt = datetime(int(match.group('end_year')),
                          int(match.group('end_month')),
                          int(match.group('end_day')),
                          int(match.group('end_hour')),
                          int(match.group('end_min')),
                          int(match.group('end_sec')))
    mission = match.group('mission')
    return day_dt, start_dt, end_dt, mission

def get_dates_mission_from_metadata(starttime, endtime, platform):
    match_s = DATE_RE.search(starttime)
    if not match_s:
        raise RuntimeError("Failed to recognize starttime %s." % starttime)

    mission = None
    if platform.strip()=='Sentinel-1B':
        mission = 'S1B'
    elif platform.strip()=='Sentinel-1A':
        mission = 'S1A'
    else:
        raise RuntimeError("Unrecognisable Platform : %s" %platform)


    day_dt = datetime(int(match_s.group('year')), int(match_s.group('month')), int(match_s.group('day')),0, 0, 0)
    start_dt = datetime(int(match_s.group('year')),
                            int(match_s.group('month')),
                            int(match_s.group('day')),
                            int(match_s.group('hour')),
                            int(match_s.group('min')),
                            int(match_s.group('sec')))
    match_e = DATE_RE.search(endtime)
    if not match_s:
        raise RuntimeError("Failed to recognize starttime %s." % starttime)
    end_dt = datetime(int(match_e.group('year')),
                            int(match_e.group('month')),
                            int(match_e.group('day')),
                            int(match_e.group('hour')),
                            int(match_e.group('min')),
                            int(match_e.group('sec')))

    return day_dt, start_dt, end_dt, mission


def get_date_from_metadata(mds):
    day_dts = {}
    mission = None 

    for id in mds:
        print(id)
        h = mds[id]
        fields = h["_source"]
        day_dt, start_dt, end_dt, mission = get_dates_mission_from_metadata(fields['starttime'], fields['endtime'], fields['metadata']['platform'])
        print("day_dt : %s, start_dt : %s, end_dt : %s, mission : %s" %(day_dt, start_dt, end_dt, mission))
        day_dts.setdefault(day_dt, []).extend([start_dt, end_dt])
    if len(day_dts) > 1:
        raise RuntimeError("Found data for more than 1 day.")
    all_dts = day_dts[day_dt]
    print("all_dts : %s" %all_dts)

    return day_dt, all_dts, mission

def get_scene_dates_from_metadata(master_mds, slave_mds):
    master_day_dt, master_all_dts, m_mission = get_date_from_metadata(master_mds)
    slave_day_dt, slave_all_dts, s_mission = get_date_from_metadata(slave_mds)
    print("master_day_dt : %s, master_all_dts : %s, m_mission %s: " %(master_day_dt, master_all_dts, m_mission))
    print("slave_day_dt : %s, slave_all_dts : %s, m_mission %s: " %(slave_day_dt, slave_all_dts, m_mission))
    master_all_dts.sort()
    slave_all_dts.sort()
    print("master_day_dt : %s, master_all_dts : %s, m_mission %s: " %(master_day_dt, master_all_dts, m_mission))
    print("slave_day_dt : %s, slave_all_dts : %s, m_mission %s: " %(slave_day_dt, slave_all_dts, m_mission))

    if master_day_dt < slave_day_dt: return master_all_dts[0], slave_all_dts[-1]
    else: return master_all_dts[-1], slave_all_dts[0]

def get_date_from_ids(ids, scene_type):
    '''
    ids : list of acquistion or slc ids
    scene_type : acq or slc
    '''
    mission = None
    
    day_dts = {}
    for id in ids:
        day_dt, start_dt, end_dt, mission = get_dates_mission_from_id(id, scene_type)
        print("day_dt : %s, start_dt : %s, end_dt : %s, mission : %s" %(day_dt, start_dt, end_dt, mission))
        day_dts.setdefault(day_dt, []).extend([start_dt, end_dt])
    if len(day_dts) > 1:
        raise RuntimeError("Found ACQ/SLCs for more than 1 day : %s" %ids)
    all_dts = day_dts[day_dt]
    print("all_dts : %s" %all_dts)
    return day_dt, all_dts, mission


def get_scene_dates_from_ids(master_ids, slave_ids, scene_type):
    '''
    ids : list of acquistion or slc ids
    scene_type : acq or slc
    '''

    master_day_dt, master_all_dts, m_mission = get_date_from_ids(master_ids, scene_type)
    slave_day_dt, slave_all_dts, s_mission = get_date_from_ids(slave_ids, scene_type)
    print("master_day_dt : %s, master_all_dts : %s, m_mission %s: " %(master_day_dt, master_all_dts, m_mission))
    print("slave_day_dt : %s, slave_all_dts : %s, m_mission %s: " %(slave_day_dt, slave_all_dts, m_mission))
    master_all_dts.sort()
    slave_all_dts.sort()

    if master_day_dt < slave_day_dt: return master_all_dts[0], slave_all_dts[-1]
    else: return master_all_dts[-1], slave_all_dts[0]



def get_urls(info):
    """Return list of SLC URLs with preference for S3 URLs."""

    urls = []
    for id in info:
        h = info[id]
        fields = h['_source']
        prod_url = fields['urls'][0]
        if len(fields['urls']) > 1:
            for u in fields['urls']:
                if u.startswith('s3://'):
                    prod_url = u
                    break
        urls.append("%s/%s" % (prod_url, fields['metadata']['archive_filename']))
    return urls


