from __future__ import division
from past.utils import old_div
import os, sys, re, requests, json, logging, traceback, argparse, copy, bisect
import util
#from hysds.celery import app
import os, sys, re, requests, json, logging, traceback, argparse, copy, bisect
import hashlib
from itertools import product, chain
from datetime import datetime, timedelta
import numpy as np
from osgeo import ogr, osr
from pprint import pformat
from collections import OrderedDict
from shapely.geometry import Polygon
from util import ACQ

#import isce
#from UrlUtils import UrlUtils as UU

BASE_PATH = os.path.dirname(__file__)
GRQ_ES_URL = "http://100.64.134.208:9200/"
covth = 0.98
MIN_MAX = 2


'''
class ACQ:
    def __init__(self, acq_id, download_url, tracknumber, location, starttime, endtime, direction, orbitnumber, pv ):
	self.acq_id=acq_id,
	self.download_url = download_url
	self.tracknumber = tracknumber
        self.location= location
	self.starttime = starttime
	self.endtime = endtime
	self.pv = pv
	self.direction = direction
        self.orbitnumber = orbitnumber
        #print("%s, %s, %s, %s, %s, %s, %s, %s, %s" %(acq_id, download_url, tracknumber, location, starttime, endtime, direction, orbitnumber, pv))
'''



# set logger and custom filter to handle being run from sciflo
log_format = "[%(asctime)s: %(levelname)s/%(funcName)s] %(message)s"
logging.basicConfig(format=log_format, level=logging.INFO)

class LogFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, 'id'): record.id = '--'
        return True

logger = logging.getLogger('enumerate_acquisations')
logger.setLevel(logging.INFO)
logger.addFilter(LogFilter())

RESORB_RE = re.compile(r'_RESORB_')

SLC_RE = re.compile(r'(?P<mission>S1\w)_IW_SLC__.*?' +
                    r'_(?P<start_year>\d{4})(?P<start_month>\d{2})(?P<start_day>\d{2})' +
                    r'T(?P<start_hour>\d{2})(?P<start_min>\d{2})(?P<start_sec>\d{2})' +
                    r'_(?P<end_year>\d{4})(?P<end_month>\d{2})(?P<end_day>\d{2})' +
                    r'T(?P<end_hour>\d{2})(?P<end_min>\d{2})(?P<end_sec>\d{2})_.*$')

IFG_ID_TMPL = "S1-IFG_R{}_M{:d}S{:d}_TN{:03d}_{:%Y%m%dT%H%M%S}-{:%Y%m%dT%H%M%S}_s{}-{}-{}"
RSP_ID_TMPL = "S1-SLCP_R{}_M{:d}S{:d}_TN{:03d}_{:%Y%m%dT%H%M%S}-{:%Y%m%dT%H%M%S}_s{}-{}-{}"



def run_acq_query(query):
    es_url = GRQ_ES_URL
    
    es_index = "grq_*_*acquisition*"

    if es_url.endswith('/'):
        search_url = '%s%s/_search' % (es_url, es_index)
    else:
        search_url = '%s/%s/_search' % (es_url, es_index)
    r = requests.post(search_url, data=json.dumps(query))

    if r.status_code != 200:
        logger.info("Failed to query %s:\n%s" % (es_url, r.text))
        logger.info("query: %s" % json.dumps(query, indent=2))
        logger.info("returned: %s" % r.text)
        r.raise_for_status()

    result = r.json()
    #print(result['hits']['total'])
    return result['hits']['hits']

def get_overlapping_slaves_query(master):
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
				{ "term": { "trackNumber": master.tracknumber }},
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
			        { "term": { "trackNumber": master.tracknumber }}
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
    logger.info("Reference GeoJSON: %s" % ref_geom.ExportToJson())

    # get union geometry of all matched scenes
    matched_geoms = []
    matched_union = None
    matched_geoms_tr = []
    matched_union_tr = None
    ids = sorted(matched_footprints.keys())
    #ids.sort()
    #logger.info("ids: %s" % len(ids))
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
    logger.info("Matched union GeoJSON: %s" % json.dumps(matched_union_geojson))
    
    # check matched_union disjointness
    if len(matched_union_geojson['coordinates']) > 1:
        logger.info("Matched union is a disjoint geometry.")
        return True
            
    # check that intersection of reference and stitched scenes passes coverage threshold
    ref_int = ref_geom.Intersection(matched_union)
    ref_int_tr = ref_geom_tr.Intersection(matched_union_tr)
    ref_int_tr_area = ref_int_tr.GetArea() # in square meters
    logger.info("Reference intersection GeoJSON: %s" % ref_int.ExportToJson())
    logger.info("area (m^2) for intersection: %s" % ref_int_tr_area)
    cov = old_div(ref_int_tr_area,ref_geom_tr_area)
    logger.info("coverage: %s" % cov)
    if cov < covth:
        logger.info("Matched union doesn't cover at least %s%% of the reference footprint." % (covth*100.))
        return True
   
    return False


def is_overlap(geojson1, geojson2):
    '''returns True if there is any overlap between the two geojsons. The geojsons
    are just a list of coordinate tuples'''
    p3=0
    p1=Polygon(geojson1[0])
    p2=Polygon(geojson2[0])
    if p1.intersects(p2):
        p3 = old_div(p1.intersection(p2).area,p1.area)
    return p1.intersects(p2), p3


def is_within(geojson1, geojson2):
    '''returns True if there is any overlap between the two geojsons. The geojsons
    are just a list of coordinate tuples'''
    p1=Polygon(geojson1[0])
    p2=Polygon(geojson2[0])
    return p1.within(p2)


def find_overlap_match(master_acq, slave_acqs):
    #logger.info("\n\nmaster info : %s : %s : %s :%s" %(master_acq.tracknumber, master_acq.orbitnumber, master_acq.pv, master_acq.acq_id))
    #logger.info("slave info : ")
    master_loc = master_acq.location["coordinates"]

    #logger.info("\n\nmaster_loc : %s" %master_loc)
    overlapped_matches = {}
    for slave in slave_acqs:
        slave_loc = slave.location["coordinates"]
        #logger.info("\n\nslave_loc : %s" %slave_loc)
        is_over, overlap = is_overlap(master_loc, slave_loc)
        logger.info("is_overlap : %s" %is_over)
        logger.info("overlap area : %s" %overlap)
        if is_over:
            overlapped_matches[slave.acq_id] = slave.location
            logger.info("Overlapped slave : %s" %slave.acq_id)

    return overlapped_matches

def get_union_geometry(acq_dict):
    """Return polygon of union of acquisition footprints."""

    # geometries are in lat/lon projection
    #src_srs = osr.SpatialReference()
    #src_srs.SetWellKnownGeogCS("WGS84")
    #src_srs.ImportFromEPSG(4326)

    # get union geometry of all scenes
    geoms = []
    union = None
    #logger.info(acq_dict)
    ids = sorted(acq_dict.keys())
    for id in ids:
        geom = ogr.CreateGeometryFromJson(json.dumps(acq_dict[id]))
        geoms.append(geom)
        union = geom if union is None else union.Union(geom)
    union_geojson =  json.loads(union.ExportToJson())
    return union_geojson

def group_acqs_by_orbitnumber(frames):
    grouped = {}
    acq_info = {}
    #print("frame length : %s" %len(frames))
    for acq in frames:
        acq_data = acq['fields']['partial'][0]
        acq_id = acq['_id']
        #print("acq_id : %s : %s" %(type(acq_id), acq_id))
        match = SLC_RE.search(acq_id)
        if not match:
            logger.info("No Match : %s" %acq_id)
            continue
        download_url = acq_data['metadata']['download_url'] 
        track = acq_data['metadata']['trackNumber']
        location = acq_data['location']
        starttime = acq_data['starttime']
        endtime = acq_data['endtime']
        direction = acq_data['metadata']['direction']
        orbitnumber = acq_data['metadata']['orbitNumber']
        pv = acq_data['metadata']['processing_version']
        slave_acq = ACQ(acq_id, download_url, track, location, starttime, endtime, direction, orbitnumber, pv)
        acq_info[acq_id] = slave_acq
       
        #logger.info("Adding %s : %s : %s : %s" %(track, orbitnumber, pv, acq_id))
	#logger.info(grouped)
        bisect.insort(grouped.setdefault(track, {}).setdefault(orbitnumber, {}).setdefault(pv, []), acq_id)
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


def group_frames_by_track_date(frames):
    """Classify frames by track and date."""

    hits = {}
    grouped = {}
    dates = {}
    footprints = {}
    metadata = {}
    for h in frames: 
        if h['_id'] in hits: continue
        fields = h['fields']['partial'][0]
        #print("h['_id'] : %s" %h['_id'])

        # get product url; prefer S3
        prod_url = fields['urls'][0]
        if len(fields['urls']) > 1:
            for u in fields['urls']:
                if u.startswith('s3://'):
                    prod_url = u
                    break
        #print("prod_url : %s" %prod_url)
        hits[h['_id']] = "%s/%s" % (prod_url, fields['metadata']['archive_filename'])
        match = SLC_RE.search(h['_id'])
        #print("match : %s" %match)
        if not match:
            raise RuntimeError("Failed to recognize SLC ID %s." % h['_id'])
        day_dt = datetime(int(match.group('start_year')),
                          int(match.group('start_month')),
                          int(match.group('start_day')),
                          0, 0, 0)
        #print("day_dt : %s " %day_dt)

        bisect.insort(grouped.setdefault(fields['metadata']['trackNumber'], {}) \
                             .setdefault(day_dt, []), h['_id'])
        slc_start_dt = datetime(int(match.group('start_year')),
                                int(match.group('start_month')),
                                int(match.group('start_day')),
                                int(match.group('start_hour')),
                                int(match.group('start_min')),
                                int(match.group('start_sec')))
        #print("slc_start_dt : %s" %slc_start_dt)

        slc_end_dt = datetime(int(match.group('end_year')),
                              int(match.group('end_month')),
                              int(match.group('end_day')),
                              int(match.group('end_hour')),
                              int(match.group('end_min')),
                              int(match.group('end_sec')))

	#print("slc_end_dt : %s" %slc_end_dt)
        dates[h['_id']] = [ slc_start_dt, slc_end_dt ]
        footprints[h['_id']] = fields['location']
        metadata[h['_id']] = fields['metadata']
	#break
    #print("grouped : %s" %grouped)
    logger.info("grouped keys : %s" %list(grouped.keys()))
    return {
        "hits": hits,
        "grouped": grouped,
        "dates": dates,
        "footprints": footprints,
        "metadata": metadata,
    }


def switch_references(candidate_pair_list, master_acq, slaves):
    logger.info("swithch reference initial  candidate_pair_list: %s" %candidate_pair_list)
    for slave in slaves:
        query = get_overlapping_masters_query(master_acq, slave)
        candidate_pair_list = find_candidate_pair(candidate_pair_list, slave, query, False, master_acq)
        logger.info("swithch reference returning  candidate_pair_list: %s" %candidate_pair_list)
        return candidate_pair_list


def find_candidate_pair(candidate_pair_list, ref_acq, query, switch, must_acq=None):
    logger.info("find_candidate_pair candidate_pair_list: %s" %candidate_pair_list)
    
    if len(candidate_pair_list)>=MIN_MAX:
        logger.info("returning as Min_MAX satisfied")
        return candidate_pair_list
    
    matched_acqs = process_query(query)
    #for acq in matched_acqs:
	#logger.info(acq["_id"])
    #exit(0)

    grouped_matched = group_acqs_by_orbitnumber(matched_acqs)
    matched_ids = list(grouped_matched["acq_info"].keys())
    
    if must_acq is not None:
        logger.info(grouped_matched["grouped"])
        if must_acq.acq_id not in matched_ids:
            logger.info("ERROR : master acq : %s not in matched acq list of the slave : "%must_acq.acq_id)
        else:
            logger.info("ERROR : master acq : %s in matched acq list of the slave : "%must_acq.acq_id)
	
    
    logger.info(list(grouped_matched["acq_info"].keys()))
    #logger.info(type(grouped_matched["acq_info"]))
    #logger.info(grouped_matched["grouped"])
    slc_count = 0
    pv_count = 0
    orbit_count =0
    track_count = 0
    for track in grouped_matched["grouped"]:
        track_count = track_count+1
        logger.info("\n\n\nTRACK : %s" %track)
        for orbitnumber in sorted( grouped_matched["grouped"][track], reverse=True):
            orbit_count= orbit_count+1
            logger.info("SortedOrbitNumber : %s" %orbitnumber)
            for pv in grouped_matched["grouped"][track][orbitnumber]:
                logger.info("\tpv : %s" %pv)
                pv_count = pv_count +1
                matched_acq_ids=grouped_matched["grouped"][track][orbitnumber][pv]
                matched_acqs = []
                for acq in matched_acq_ids:
                    slc_count=slc_count+1
                    logger.info("]\t\tTypeCheck %s : %s" %(type(acq), type(acq[0])))
                    if acq.strip() in list(grouped_matched["acq_info"].keys()):
                        acq_info =grouped_matched["acq_info"][acq.strip()]
                        matched_acqs.append(acq_info) 
                    else:
                        logger.info("Key does not exists : %s" %acq.strip())   
                overlapped_matches = find_overlap_match(ref_acq, matched_acqs)
                if len(overlapped_matches)>0:
                    logger.info("Overlapped Acq exists for track: %s orbit_number: %s process version: %s. Now checking coverage." %(track, orbitnumber, pv))
                    union_loc = get_union_geometry(overlapped_matches)
                    logger.info("union loc : %s" %union_loc)
                    is_ref_truncated = ref_truncated(ref_acq, overlapped_matches, covth=.99)
                    is_covered = is_within(ref_acq.location["coordinates"], union_loc["coordinates"])
                    is_overlapped, overlap = is_overlap(ref_acq.location["coordinates"], union_loc["coordinates"])
                    logger.info("is_ref_truncated : %s" %is_ref_truncated)
                    logger.info("is_within : %s" %is_covered)
                    logger.info("is_overlapped : %s, overlap : %s" %(is_overlapped, overlap))
                    matched_acqs=[]
                    matched_acqs2=[]
                    for acq_id in list(overlapped_matches.keys()):
                        matched_acqs2.append(acq_id[0])
                        matched_acqs.append(grouped_matched["acq_info"][acq_id[0]])
        	    #logger.info("overlap area : %s" %overlap)
                    if is_overlapped and overlap>=0.95: # and overlap >=covth:
                        logger.info("MATCHED we have found a match :" )
                        if switch:
                            master_acqs=[ref_acq.acq_id[0]]
                            slave_acqs=matched_acqs2
                        else:
                            master_acqs=matched_acqs2
                            slave_acqs=[ref_acq.acq_id[0]]
                        logger.info("find_candidate_pair, before adding to  candidate_pair_list: %s" %candidate_pair_list)
                        logger.info("\n\n\nmaster urls : %s" %master_acqs)
                        logger.info("slave urls : %s" %slave_acqs)
                        candidate_pair_list.append({"master_acqs" : master_acqs, "slave_acqs" : slave_acqs})
                        logger.info("find_candidate_pair, after adding to  candidate_pair_list: %s" %candidate_pair_list)
                        logger.info("find_candidate_pair, after adding to  candidate_pair_list: %s" %len(candidate_pair_list))
                        if len(candidate_pair_list)>=MIN_MAX:
                            logger.info("returning as Min_MAX satisfied")
                            return candidate_pair_list
                        #return {"master_acqs" : master_acqs, "slave_acqs" : slave_acqs}
                    else:
                        logger.info("we have NOT found a match. So switching slaves...")
                        if switch:
                            candidate_pair_list = switch_references(candidate_pair_list, ref_acq, matched_acqs)
			    
                            if len(candidate_pair_list)>=MIN_MAX:
                                return candidate_pair_list
			    

                else:
                    logger.info("No Overlapped Acq for track: %s orbit_number: %s process version: %s" %(track, orbitnumber, pv))
    return candidate_pair_list

def process_query(query):

    rest_url = GRQ_ES_URL
    #dav_url =  "https://aria-dav.jpl.nasa.gov"
    #version = "v1.1"
    grq_index_prefix = "grq"

    logger.info("query: {}".format(json.dumps(query, indent=2)))

    if rest_url.endswith('/'):
        rest_url = rest_url[:-1]

    # get index name and url
    url = "{}/{}/_search?search_type=scan&scroll=60&size=100".format(rest_url, grq_index_prefix)
    logger.info("url: {}".format(url))
    r = requests.post(url, data=json.dumps(query))
    r.raise_for_status()
    scan_result = r.json()
    count = scan_result['hits']['total']
    print("count : %s" %count)
    scroll_id = scan_result['_scroll_id']
    ref_hits = []
    while True:
        r = requests.post('%s/_search/scroll?scroll=60m' % rest_url, data=scroll_id)
        res = r.json()
        scroll_id = res['_scroll_id']
        if len(res['hits']['hits']) == 0: break
        ref_hits.extend(res['hits']['hits'])

    return ref_hits

def enumerate_acquisations_array(acq_array):

    enumerate_dict={}
    projects = []
    spyddder_extract_versions = []
    acquisition_localizer_versions = []
    standard_product_localizer_versions = []
    standard_product_ifg_versions=[]
    aois = []
    job_priorities = []
    queues = []
    master_acquisitions= []
    slave_acquisitions = []

   

    logger.info("\n\n\nenumerate_acquisations_array Length : %s" %len(acq_array))
    logger.info(acq_array)
    for acq_data in acq_array:
        logger.info("%s : %s" %(type(acq_data), acq_data))
        logger.info("\n\n Processing Acquisition : %s for project : %s" %(acq_data['acq_id'], acq_data['project']))
        candidate_pair_list =  enumerate_acquisations_standard_product(acq_data['acq_id'])
        if len(candidate_pair_list)>=MIN_MAX:
            for candidate in candidate_pair_list:
                #logger.info("candidate slave_acqs is of type : %s of length : %s" %(type(candidate["slave_acqs"]), len(candidate["slave_acqs"])))
                #logger.info("candidate master_acqs is of type : %s of length : %s" %(type(candidate["master_acqs"]), len(candidate["master_acqs"])))
                projects.append(acq_data['project'])
                spyddder_extract_versions.append(acq_data['spyddder_extract_version'])
                acquisition_localizer_versions.append(acq_data['acquisition_localizer_version'])
                standard_product_localizer_versions.append(acq_data['standard_product_localizer_version'])
                standard_product_ifg_versions.append(acq_data['standard_product_ifg_version'])
                job_priorities.append(acq_data['job_priority'])
                master_acquisitions.append(candidate["master_acqs"])
                slave_acquisitions.append(candidate["slave_acqs"])

	    
    return master_acquisitions, slave_acquisitions, projects, spyddder_extract_versions, acquisition_localizer_versions, standard_product_localizer_versions, standard_product_ifg_versions,  job_priorities


    
def enumerate_acquisations_standard_product(acq_id):
    
    candidate_pair_list = []   

    # First lets find information about the acquisation
    acq = util.get_complete_grq_data(acq_id)[0]
    #print(acq)
    acq_data = acq['_source']
    #print(acq_data['metadata']['download_url'])
    #print(acq_data['starttime'])
    master_acq = ACQ(acq['_id'], acq_data['metadata']['download_url'], acq_data['metadata']['trackNumber'], acq_data['location'], acq_data['starttime'], acq_data['endtime'], acq_data['metadata']['direction'], acq_data['metadata']['orbitNumber'], acq_data['metadata']['processing_version'])
    master_scene = {
     'id': acq['_id'],
     'track': acq_data['metadata']['trackNumber'],
     'date': acq_data['starttime'],
     'location': acq_data['location'],
     'pre_matches': None,
     'post_matches': None 

    }
    #Now lets find all the acqusations that has same location but from previous date 
    ref_hits = []
    query = get_overlapping_slaves_query(master_acq)

    candidate_pair_list = find_candidate_pair(candidate_pair_list, master_acq, query, True)
    logger.info("enumerate_acquisations_standard_product before returning candidate_pair_list: %s" %candidate_pair_list)
    #logger.info("\n\nFinal Result: length : %s" %len(candidate_pair_list))
    #logger.info(candidate_pair_list)
    return candidate_pair_list



if __name__ == "__main__":
    acq_id = "acquisition-S1A_IW_SLC__1SDV_20180807T135955_20180807T140022_023141_02837E_DA79"
    enumerate_acquisatio1ns_standard_product(acq_id)
