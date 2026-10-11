from copy import deepcopy
from app.routers.core import build_timeseries
from app.facility import load_facility
from engine.features import wind_chill_f


def test_archived_feels_like_curve_reproduces_recorded_calculation():
    snap={'as_of':'2022-12-22T10:00:00+00:00','snapshot_id':'archive','facility':load_facility().model_dump(mode='json'),
          'signals':{'fcst_min_apparent_24h_f':{'available':True,'input_ids':['fcst.temp_f','fcst.wind_speed_mph'],'detail':'calculated wind chill'}},
          'inputs':[{'kind':'series','role':'forecast','metric':metric,'series':[{'t':'2022-12-22T11:00:00+00:00','v':value}],
                     'source':'Archived forecast','source_time':'2022-12-22T09:00:00+00:00'} for metric,value in [('temp_f',0),('wind_speed_mph',20)]]}
    before=deepcopy(snap)
    data=build_timeseries(snap)
    assert data['rows'][0]['fcst_apparent_temp_f']==round(wind_chill_f(0,20),1)
    assert 'recorded forecast' in data['meta']['fcst_apparent_temp_f']['source']
    assert snap==before
    snap['inputs'].append({'kind':'series','role':'forecast','metric':'apparent_temp_f','series':[{'t':'2022-12-22T11:00:00+00:00','v':-33}], 'source':'Archived explicit feels-like'})
    assert build_timeseries(snap)['rows'][0]['fcst_apparent_temp_f']==-33


def test_archived_threshold_lines_use_recorded_values_not_current_config():
    snap={'as_of':'2022-12-22T10:00:00+00:00','snapshot_id':'archive','facility':load_facility().model_dump(mode='json'),'inputs':[],
          'rules':[{'rule_id':'wind.fcst_gust_warning','threshold':77,'label':'Recorded gust limit','unit':'mph','verified':False,'posture_effect':'significant'}]}
    assert build_timeseries(snap)['threshold_lines'][0]['value']==77
