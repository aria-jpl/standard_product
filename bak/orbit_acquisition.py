#!/usr/bin/env python 
import os, sys, time, json, requests, logging
import re, traceback, argparse, copy, bisect
from hysds_commons.job_utils import resolve_hysds_job
from hysds.celery import app
import util
from util import ACQ

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

SLC_RE = re.compile(r'(?P<mission>S1\w)_IW_SLC__.*?' +
                    r'_(?P<start_year>\d{4})(?P<start_month>\d{2})(?P<start_day>\d{2})' +
                    r'T(?P<start_hour>\d{2})(?P<start_min>\d{2})(?P<start_sec>\d{2})' +
                    r'_(?P<end_year>\d{4})(?P<end_month>\d{2})(?P<end_day>\d{2})' +
                    r'T(?P<end_hour>\d{2})(?P<end_min>\d{2})(?P<end_sec>\d{2})_.*$')

BASE_PATH = os.path.dirname(__file__)

def query_es(query, es_index=None):
    """Query ES."""

    es_url = app.conf.GRQ_ES_URL
    rest_url = es_url[:-1] if es_url.endswith('/') else es_url
    url = "{}/_search?search_type=scan&scroll=60&size=100".format(rest_url)
    if es_index:
        url = "{}/{}/_search?search_type=scan&scroll=60&size=100".format(rest_url, es_index)
    #logger.info("url: {}".format(url))
    r = requests.post(url, data=json.dumps(query))
    r.raise_for_status()
    scan_result = r.json()
    #logger.info("scan_result: {}".format(json.dumps(scan_result, indent=2)))
    count = scan_result['hits']['total']
    scroll_id = scan_result['_scroll_id']
    hits = []
    while True:
        r = requests.post('%s/_search/scroll?scroll=60m' % rest_url, data=scroll_id)
        res = r.json()
        scroll_id = res['_scroll_id']
        if len(res['hits']['hits']) == 0: break
        hits.extend(res['hits']['hits'])
    return hits




def query_aois(starttime, endtime):
    """Query ES for active AOIs that intersect starttime and endtime."""

    es_index = "grq_*_area_of_interest"
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
					    "dataset_type": "area_of_interest"
                                        }
                                }
                            ]
                        }
                    },
        {
        "filtered": {
            "query": {

              "bool": {
                "must": [
                  {
                    "match": {
                      "dataset_type": "area_of_interest"
                      }
                  },
                  {
                    "range": {
                      "starttime": {
                        "lte": endtime
                      }
                    }
                  }
                ]
              }
            },
            "filter": {
              "missing": {
                "field": "endtime"
              }
            }
          }
        },
        {
        "filtered": {
            "query": {

              "bool": {
                "must": [
                  {
                    "match": {
                      "dataset_type": "area_of_interest"
                      }
                  },
                  {
                    "range": {
                      "endtime": {
                        "gte": starttime
                      }
                    }
                  }
                ]
              }
            },
            "filter": {
              "missing": {
                "field": "starttime"
              }
            }
          }
        }
          
      ]
    }
  },
        "partial_fields" : {
            "partial" : {
                "include" : [ "id", "starttime", "endtime", "location", 
                              "metadata.user_tags", "metadata.priority" ]
            }
        }
    }

    # filter inactive
    hits = [i['fields']['partial'][0] for i in query_es(query) 
            if 'inactive' not in i['fields']['partial'][0].get('metadata', {}).get('user_tags', [])]
    #logger.info("hits: {}".format(json.dumps(hits, indent=2)))
    #logger.info("aois: {}".format(json.dumps([i['id'] for i in hits])))
    return hits

def query_aois_new(starttime, endtime):
    """Query ES for active AOIs that intersect starttime and endtime."""

    es_index = "grq_*_area_of_interest"
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
					    "dataset_type": "area_of_interest"
                                        }
                                },
                                {
                                    "match": {
                                            "metadata.user_tags": "standard_product"
                                        }
                                }
                            ],
                 	    "must_not": {
                		"term": {
                    		    "metadata.user_tags": "inactive"
                		}
            		    }
			  
                        }
                    },
        {
        "filtered": {
            "query": {

              "bool": {
                "must": [
                  {
                    "match": {
                      "dataset_type": "area_of_interest"
                      }
                  },
                  {
                    "range": {
                      "starttime": {
                        "lte": endtime
                      }
                    }
                  },
                  {
                      "match": {
                          "metadata.user_tags": "standard_product"
                      }
                  }
                ],
       	    	"must_not": {
                    "term": {
                        "metadata.user_tags": "inactive"
                    }
                }
              }
            },
            "filter": {
              "missing": {
                "field": "endtime"
              }
            }
          }
        },
        {
        "filtered": {
            "query": {

              "bool": {
                "must": [
                  {
                    "match": {
                      "dataset_type": "area_of_interest"
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
                          "metadata.user_tags": "standard_product"
                      }
                  }
                ],
           	"must_not": {
                    "term": {
                        "metadata.user_tags": "inactive"
                    }
                }
              }
            },
            "filter": {
              "missing": {
                "field": "starttime"
              }
            }
          }
        }
          
      ]
    }
  },
        "partial_fields" : {
            "partial" : {
                "include" : [ "id", "starttime", "endtime", "location", 
                              "metadata.user_tags", "metadata.priority" ]
            }
        }
    }

    # filter inactive
    hits = [i['fields']['partial'][0] for i in query_es(query) 
            if 'inactive' not in i['fields']['partial'][0].get('metadata', {}).get('user_tags', [])]
    #logger.info("hits: {}".format(json.dumps(hits, indent=2)))
    #logger.info("aois: {}".format(json.dumps([i['id'] for i in hits])))
    return hits

def get_query(acq):
    query = {
    	"query": {
    	    "filtered": {
      		"filter": {
        	    "and": [
          		{
            		    "term": {
              			"system_version.raw": "v1.1"
            		    }
          		}, 
          		{
            		    "ids": {
              			"values": [acq['identifier']]
            		    }
          		}, 
          		{
            		    "geo_shape": {
              			"location": {
                		    "shape": acq['metadata']['location']
              			}
            		    }
          		}
        	    ]
      		}, 
      		"query": {
        	    "bool": {
          		"must": [
            		    {
              			"term": {
                		    "dataset.raw": "S1-IW_SLC"
              			}
            		    }
          		]
        	    }
      		}
    	    }
  	}, 
  	"partial_fields": {
    	    "partial": {
      		"exclude": "city"
    	    }
  	}
    }

    
    return query

def get_query(acq):
    query = {
    	"query": {
    	    "filtered": {
      		"filter": {
        	    "and": [
          		{
            		    "geo_shape": {
              			"location": {
                		    "shape": acq['metadata']['location']
              			}
            		    }
          		}
        	    ]
      		}, 
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
      		}
    	    }
  	}, 
  	"partial_fields": {
    	    "partial": {
      		"exclude": "city"
    	    }
  	}
    }

    
    return query

def get_query2(acq):
    query = {
    	"query": {
    	    "filtered": {
      		"filter": {
        	    "and": [
          		{
            		    "term": {
              			"system_version.raw": "v1.1"
            		    }
          		}, 
          		{
            		    "ids": {
              			"values": [acq['identifier']]
            		    }
          		}, 
          		{
            		    "geo_shape": {
              			"location": {
                		    "shape": acq['metadata']['location']
              			}
            		    }
          		}
        	    ]
      		}, 
      		"query": {
        	    "bool": {
          		"must": [
            		    {
              			"term": {
                		    "dataset.raw": "S1-IW_SLC"
              			}
            		    }
          		]
        	    }
      		}
    	    }
  	}, 
  	"partial_fields": {
    	    "partial": {
      		"exclude": "city"
    	    }
  	}
    }

    
    return query


def group_acqs_by_track(frames):
    grouped = {}
    acq_info = {}
    #print("frame length : %s" %len(frames))
    for acq in frames:
	acq_data = acq#['fields']['partial'][0]
	acq_id = acq['id']
        #print("acq_id : %s : %s" %(type(acq_id), acq_id))
	match = SLC_RE.search(acq_id)
        if not match:
	    logger.info("No Match : %s" %acq_id)
	    continue
	download_url = acq_data['metadata']['download_url'] 
	track = acq_data['metadata']['trackNumber']
	location = acq_data['metadata']['location']
	starttime = acq_data['starttime']
	endtime = acq_data['endtime']
        direction = acq_data['metadata']['direction']
        orbitnumber = acq_data['metadata']['orbitNumber']
        pv = acq_data['metadata']['processing_version']
	this_acq = ACQ(acq_id, download_url, track, location, starttime, endtime, direction, orbitnumber, pv)
        acq_info[acq_id] = this_acq
       
        #logger.info("Adding %s : %s : %s : %s" %(track, orbitnumber, pv, acq_id))
	#logger.info(grouped)
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


def get_dem_type(acq):
    dem_type = "SRTM+v3"
    if acq['city'] is not None and len(acq['city'])>0:
	if acq['city'][0]['country_name'] is not None and acq['city'][0]['country_name'].lower() == "united states":
	    dem_type="Ned1"
    return dem_type


def get_covered_acquisitions(aoi, acqs):
    
    for acq in acqs:
        grouped_matched = group_acqs_by_track(acqs)
        matched_ids = list(grouped_matched["acq_info"].keys())
    


    return acqs

def query_aoi_acquisitions(starttime, endtime, platform):
    """Query ES for active AOIs that intersect starttime and endtime and 
       find acquisitions that intersect the AOI polygon for the platform."""
    #aoi_acq = {}
    acq_info = {}
    es_index = "grq_*_*acquisition*"
    aois = query_aois(starttime, endtime)
    logger.info("No of AOIs : %s " %len(aois))
    for aoi in aois:
        logger.info("aoi: {}".format(aoi['id']))
        query = {
            "query": {
                "filtered": {
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
                                        "metadata.platform.raw": platform
                                    }
                                },
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
                                }
                            ]
                        }
                    },
                    "filter": {
                        "geo_shape": {  
                            "location": {
                                "shape": aoi['location']
                            }
                        }
                    }
                }
            },
            "partial_fields" : {
                "partial" : {
                    "include" : [ "id", "dataset_type", "dataset", "metadata", "city", "continent", "starttime", "endtime"]
                }
            }
        }
        logger.info(query)
        acqs = [i['fields']['partial'][0] for i in query_es(query, es_index)]
        logger.info("Found {} acqs for {}: {}".format(len(acqs), aoi['id'],
                    json.dumps([i['id'] for i in acqs], indent=2)))

        logger.info("ALL ACQ of AOI : \n%s" %acqs)

        acqs = get_covered_acquisitions(aoi, acqs)


        for acq in acqs:
            aoi_priority = aoi.get('metadata', {}).get('priority', 0)
            # ensure highest priority is assigned if multiple AOIs resolve the acquisition
            if acq['id'] in acq_info and acq_info[acq['id']].get('priority', 0) > aoi_priority:
                continue
            acq['aoi'] = aoi['id']
            acq['aoi_location'] =  aoi['location']
            acq['priority'] = aoi_priority
            acq_info[acq['id']] = acq
	#aoi_acq[aoi] = acq_info 
        logger.info("Acquistions to localize: {}".format(json.dumps(acq_info, indent=2)))
    return acq_info
    

def resolve_s1_slc(identifier, download_url, project):
    """Resolve S1 SLC using ASF datapool (ASF or NGAP). Fallback to ESA."""

    # determine best url and corresponding queue
    vertex_url = "https://datapool.asf.alaska.edu/SLC/SA/{}.zip".format(identifier)
    r = requests.head(vertex_url, allow_redirects=True)
    if r.status_code == 403:
        url = r.url
        queue = "{}-job_worker-small".format(project)
    elif r.status_code == 404:
        url = download_url
        queue = "factotum-job_worker-scihub_throttled"
    else:
        raise RuntimeError("Got status code {} from {}: {}".format(r.status_code, vertex_url, r.url))
    return url, queue


class DatasetExists(Exception):
    """Exception class for existing dataset."""
    pass

def get_temporal_baseline(ctx):
    temporalBaseline = 24
    if 'temporalBaseline' in ctx:
	temporalBaseline = int(ctx['temporalBaseline'])
    return temporalBaseline
   

def resolve_s1_slc(identifier, download_url, project):
    """Resolve S1 SLC using ASF datapool (ASF or NGAP). Fallback to ESA."""

    # determine best url and corresponding queue
    vertex_url = "https://datapool.asf.alaska.edu/SLC/SA/{}.zip".format(identifier)
    r = requests.head(vertex_url, allow_redirects=True)
    if r.status_code == 403:
        url = r.url
        queue = "{}-job_worker-small".format(project)
    elif r.status_code == 404:
        url = download_url
        queue = "factotum-job_worker-scihub_throttled"
    else:
        raise RuntimeError("Got status code {} from {}: {}".format(r.status_code, vertex_url, r.url))
    return url, queue


class DatasetExists(Exception):
    """Exception class for existing dataset."""
    pass

def get_temporal_baseline(ctx):
    temporalBaseline = 24
    if 'temporalBaseline' in ctx:
	temporalBaseline = int(ctx['temporalBaseline'])
    return temporalBaseline

def resolve_aoi_acqs(ctx_file):
    """Resolve best URL from acquisitions from AOIs."""

    # read in context
    with open(ctx_file) as f:
        ctx = json.load(f)

    #SFL = os.path.join(os.environ['HOME'], 'standard_product', 'aoi_acquisition_localizer_standard_product.sf.xml')
    # get acq_info
    acq_info = query_aoi_acquisitions(ctx['starttime'], ctx['endtime'], ctx['platform'])

    # build args
    #queue = ctx["recommended-queues"][0]
    queue = "system-jobs-queue"
    singlesceneOnly = True
    precise_orbit_only = True
    spyddder_extract_version= ctx['spyddder_extract_version']
    acquisition_localizer_version = ctx['acquisition_localizer_version']
    standard_product_localizer_version = ctx['standard_product_localizer_version']
    standard_product_ifg_version = 'standard-product'
    if 'standard_product_ifg_version' in ctx and ctx['standard_product_ifg_version'] is not None and ctx['standard_product_ifg_version'] !="":
	standard_product_ifg_version = ctx['standard_product_ifg_version']

    #standard_product_version= ctx['standard_product_version']
    project = ctx['project']
    logger.info("PROJECT : %s" %project)
    priority = ctx["job_priority"]
    job_type, job_version = ctx['job_specification']['id'].split(':') 
    acquisitions = []
    acquisition_array =[]

    for id in sorted(acq_info):
        acq = acq_info[id]
	aoi = acq['aoi']
        logging.info("\n\nPrinting AOI : %s, Acq : %s" %(aoi, id))
            #print(acq)

    	#job_type = "job-standard_product_localizer:{}".format(standard_product_localizer_version)
       
	    #return id, project, spyddder_extract_version, aoi, priority, queue


     	acq_data = {
            "acq_id" : id,
            "project" : project,
            #"identifier" : acq['metadata']['identifier'],
	    "spyddder_extract_version" : spyddder_extract_version,
	    "standard_product_ifg_version" : standard_product_ifg_version,
	    "acquisition_localizer_version" : acquisition_localizer_version,
	    "standard_product_localizer_version" : standard_product_localizer_version,
  	    #"job_type" : job_type, 
	    #"job_version" : job_version,
	    "job_priority" : ctx['job_priority']
		
        } 
        acquisition_array.append(acq_data)

    acquisitions.append(acquisition_array)

    logging.info("acquisition_array length : %s" %acquisition_array)
    #return acquisitions
    return acquisition_array

    '''
        logging.info("acq identifier : %s " %identifier)
	logging.info("acq city : %s " %acq['city'])
        logging.info("dem_type : %s" %dem_type)
	logging.info("query : %s" %query)
	logging.info("bbox : %s" %bbox)
        logging.info("ipf : %s" %ipf)
	
        acquisition_array.append([project, True, bbox, dataset, identifier, download_url, dataset_type, ipf, archive_filename, query, aoi, dem_type, spyddder_extract_version, standard_product_version, queue, job_priority, preReferencePairDirection, postReferencePairDirection, temporalBaseline, singlesceneOnly, precise_orbit_only])
        
        return project, True, bbox, dataset, identifier, download_url, dataset_type, ipf, archive_filename, query, aoi, dem_type, spyddder_extract_version, standard_product_version, queue, job_priority, preReferencePairDirection, postReferencePairDirection, temporalBaseline, singlesceneOnly, precise_orbit_only
        exit(0)
        #job = resolve_hysds_job(job_type, queue, priority=acq['priority'], params=params, job_name="%s-%s-%s" % (job_type, aoi, prod_name))

        #job_id = submit_hysds_job(job)

    '''

def main():
    """Run S1 create interferogram sciflo."""

    # read in _context.json
    context_file = os.path.abspath("_context.json")
    if not os.path.exists(context_file):
        raise RuntimeError
    
    resolve_aoi_acqs(context_file)

if __name__ == "__main__":
    sys.exit(main())
