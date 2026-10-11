"""Checksummed original coastal station archives; never supplies revised flood/surge records.

This intentionally partial event library uses issued GFS forecasts and past METARs.
Unavailable warning histories and coastal impacts are disclosed, not fabricated.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from fastapi import HTTPException
from adapters.base import NormalizedInput, Point, SourceStatus, iso_z, utc
from app import historical, snapshots
from app.facility import load_facility
from engine.evaluate import assess
from engine.normalize import KT_TO_MPH
from engine.scoring import load_thresholds

FACILITY_ID='NC-WILMINGTON-SC'
CONTROL_ID='nc-normal-2024-10-16'
FIXTURE=Path(__file__).resolve().parents[1]/'fixtures/history/wilmington-originals.json'
LIMITATIONS=[
    'Original NHC/local warning update history is not supplied; no displayed warnings does not establish none existed.',
    'GFS MOS provides sustained wind, temperature and rain probability; gust forecasts, quantitative rainfall, snow/ice amounts and surge forecasts remain unknown.',
    'Historical corridor closures, cameras, evacuation orders and facility operating decisions are not supplied.',
    'Station observations cannot establish coastal flooding, storm surge, river flooding or safe access to this facility.',
]

def digest(rows):
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()

@lru_cache(maxsize=1)
def fixtures():
    data=json.loads(FIXTURE.read_text())
    if data.get('facility_id')!=FACILITY_ID:raise ValueError('Coastal fixture facility mismatch')
    for event in data['events']:
        for source in event['observations']:
            if source.get('station')!='ILM' or digest(source['rows'])!=source['rows_sha256']:
                raise ValueError('Coastal observation source checksum/station mismatch')
        for source in event['forecasts']:
            if digest(source['data'])!=source['rows_sha256']:
                raise ValueError('Coastal forecast source checksum mismatch')
            for row in source['data']:
                if row.get('station')!='KILM' or row.get('model')!='GFS':
                    raise ValueError('Coastal forecast station/model mismatch')
    return {event['event']['id']:event for event in data['events']}

def fixture(event_id):
    if event_id not in fixtures():raise HTTPException(404,'Event not found for this facility')
    return fixtures()[event_id]

def forecast_inputs(data,as_of):
    eligible=[]
    for source in data['forecasts']:
        if not source['data']:continue
        times={utc(datetime.fromisoformat(r['runtime_utc'])) for r in source['data']}
        if len(times)!=1:raise ValueError('Mixed coastal forecast runs')
        runtime=times.pop()
        if runtime+timedelta(hours=2)<=as_of and as_of-runtime<=timedelta(hours=12):
            eligible.append((runtime,source))
    runs=sorted(eligible,key=lambda p:p[0],reverse=True)[:2]
    values={m:{} for m in ('temp_f','wind_speed_mph','pop_pct')}
    for runtime,source in reversed(runs):
        for row in source['data']:
            valid=utc(datetime.fromisoformat(row['ftime_utc']))
            for field,metric,scale,offsets in [('tmp','temp_f',1,(-1,0,1)),('wsp','wind_speed_mph',KT_TO_MPH,(-1,0,1)),('p06','pop_pct',1,range(-6,0))]:
                value=row.get(field)
                if value is None or value>=999 or (field!='tmp' and value<0):continue
                for h in offsets:
                    when=valid+timedelta(hours=h)
                    if as_of-timedelta(hours=1)<=when<=as_of+timedelta(hours=72):
                        values[metric][when]=(round(value*scale,4),runtime,source)
    out=[]
    for metric,points in values.items():
        if not points:continue
        runtime=max(p[1] for p in points.values());source=next(p[2] for p in points.values() if p[1]==runtime)
        out.append(NormalizedInput(id=f'fcst.{metric}',kind='series',role='forecast',metric=metric,
                   unit={'temp_f':'degF','wind_speed_mph':'mph','pop_pct':'%'}[metric],
                   series=[Point(t=t,v=p[0]) for t,p in sorted(points.items())],
                   source='Original archived KILM GFS MOS (IEM)',source_time=runtime,source_url=source['url'],
                   fetched_at=datetime.fromisoformat(source['fetched_at']),
                   data={'weather_fallback':True,'point_sources':{iso_z(t):{'source_time':iso_z(p[1]),'source_url':p[2]['url']} for t,p in points.items()},'limitations':LIMITATIONS[:2]},
                   note='Original forecast run plus estimated 2-hour publication lag; categorical QPF/snow fields are excluded.'))
    return out

def evaluation(event_id,as_of):
    as_of=utc(as_of);data=fixture(event_id);spec=data['event']
    if not utc(datetime.fromisoformat(spec['start']))<=as_of<=utc(datetime.fromisoformat(spec['end'])):
        raise HTTPException(422,'Choose a time inside this archived event, or use historical date search')
    facility=load_facility(FACILITY_ID)
    inputs=[]
    for source in data['observations']:
        inputs+=historical.observation_inputs(source['rows'],as_of,source)
    # Local-day source slices may produce duplicate metric ids. Merge their past points
    # while keeping the latest actual observation timestamp and provenance.
    merged={}
    for item in inputs:
        if item.id in merged:
            previous=merged[item.id]
            item.series=sorted(previous.series+item.series,key=lambda p:p.t)
            if previous.source_time>item.source_time:
                item.source_time=previous.source_time
                item.source_url=previous.source_url
        merged[item.id]=item
    inputs=list(merged.values())+forecast_inputs(data,as_of)
    statuses=[SourceStatus(adapter='iem_obs',label='ILM archived observations',status='ok' if merged else 'empty',
                           urls=[s['url'] for s in data['observations']],n_inputs=len(merged)),
              SourceStatus(adapter='iem_gfs',label='Original archived GFS MOS backup',status='ok' if any(i.role=='forecast' for i in inputs) else 'empty',
                           urls=[s['url'] for s in data['forecasts']],n_inputs=sum(i.role=='forecast' for i in inputs))]
    for adapter,label,detail in [('iem_mos','Archived NBM forecast','Not retained for this event; original GFS MOS is a limited backup.'),
                                 ('iem_vtec','Original warning updates',LIMITATIONS[0]),
                                 ('ncdot_roads','Historical DriveNC corridor conditions',LIMITATIONS[2]),
                                 ('nwps_water','Historical coastal water levels',LIMITATIONS[3]),
                                 ('nws_hurricane_local','Original hurricane/surge advisories',LIMITATIONS[0])]:
        statuses.append(SourceStatus(adapter=adapter,label=label,status='unavailable',detail=detail))
    return facility,inputs,statuses,assess(inputs,statuses,facility,as_of,'backtest',employees=[])

def observed(event_id):
    data=fixture(event_id)
    rows=sorted((r for source in data['observations'] for r in source['rows']),key=lambda r:r['utc_valid'])
    out=historical.outcome(rows,data['event']['impact_day'],'America/New_York','ILM')
    out.update({'outcome_sufficient':False,'coastal_impacts':'unknown','summary':f"ILM station outcome: {out['hours']}/{out['expected_hours']} hours covered; maximum reported gust {out['max_gust_mph']} mph. Coastal flooding, surge, roads and office decisions remain unknown."})
    return out

@lru_cache(maxsize=16)
def _event(event_id,rules_sha):
    data=fixture(event_id);spec=data['event'];out=observed(event_id)
    if event_id==CONTROL_ID and (not out['gradable'] or out['disruptive']):
        raise ValueError('Coastal normal control requires complete independently quiet station observations')
    timeline=[];at=datetime.fromisoformat(spec['start']);end=datetime.fromisoformat(spec['end'])
    while at<=end:
        _,inputs,statuses,a=evaluation(event_id,at)
        timeline.append({'as_of':at.isoformat(),'posture':a.posture.posture,'readiness':a.readiness.level,'confidence':a.confidence.level,
                         'coverage':'partial','unavailable_sources':[s.label for s in statuses if s.status=='unavailable'],
                         'label':'partial original-source reconstruction; simulated by rules'})
        at+=timedelta(hours=1)
    four=historical.local_instant(spec['impact_day'],facility_id=FACILITY_ID)
    selected=min(timeline,key=lambda p:abs(datetime.fromisoformat(p['as_of'])-four))
    return {**spec,'timezone':'America/New_York','partial':True,'timeline':timeline,'verification':{'ok':True,'checks':[{'ugc':'ILM','product':'Original station source checksums','verified':True,
             'source_url':data['observations'][0]['url'],'events':[{'link':s['url']} for s in data['observations']]}]},
            'outcome':out,'backtest':{'at_0400_local':selected,'verdict':'Partial station replay; coastal outcomes and actual office decisions cannot be graded.','label':'original forecasts and past observations; no complete coastal outcome'},
            'missing':LIMITATIONS}

def event(event_id):
    return _event(event_id,load_thresholds(facility=load_facility(FACILITY_ID)).sha256)

def events():return [event(event_id) for event_id in fixtures()]

def replay(event_id,as_of,use_ai=False):
    facility,inputs,statuses,result=evaluation(event_id,as_of)
    snap=snapshots.build_snapshot_dict(facility,result,inputs,statuses,'replay',event_id)
    from ai.fallback import build
    from ai.prompts import PROMPT_VERSION
    snap['ai']=build(snap,[]).model_dump(mode='json')
    snap['model_id'],snap['prompt_version']='deterministic-fallback',PROMPT_VERSION
    snap['snapshot_id']='nc-replay-'+snapshots.content_hash(snap)[:32]
    snap=snapshots.get(snap['snapshot_id']) or snapshots.store(snap)
    if use_ai:
        # Background enrichment captures its argument by reference. Give it a separate
        # dictionary before adding the hindsight outcome context to the displayed report.
        enriched=snapshots.ensure_interpretation(dict(snap))
        snap['ai_addon']=enriched.get('ai_addon')
    snap['historical_context']={'facility_id':FACILITY_ID,'id':snap['snapshot_id'],'day':fixture(event_id)['event']['impact_day'],
             'as_of':snap['as_of'],'status':'partial','reconstruction':'Original archived coastal station reconstruction',
             'detail':'Original GFS forecasts and observations only; coastal warning, surge and flood evidence is incomplete.',
             'outcome':observed(event_id),'missing':LIMITATIONS,
             'assumptions':['METAR validity + assumed 15-minute observation availability lag.','GFS nominal run + assumed 2-hour publication lag.','Full-day station outcomes are hindsight grading context only.'],
             'source_coverage':[s.model_dump(mode='json') for s in statuses], 'proxy_records':[]}
    return snap
