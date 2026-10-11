"""Historical cutoff, coverage, grading, durability and read-only boundaries."""
import asyncio
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlmodel import select
from adapters.base import NormalizedInput,Point,SourceStatus
from adapters.historical_asos import parse_csv
from app import db,historical as h,snapshots
from app.config import settings
from app.models import HistoricalArtifact,HistoricalEvaluation

@pytest.fixture
def env(tmp_path,monkeypatch):
    old=db._engine;engine=db.make_engine(f'sqlite:///{tmp_path}/history.db');db.set_engine(engine)
    monkeypatch.setattr(settings,'db_path',tmp_path/'history.db');monkeypatch.setattr(settings,'demo_mode',True)
    rows=[{'utc_valid':(datetime(2024,1,1,tzinfo=timezone.utc)+timedelta(hours=i)).isoformat(),'tmpf':20,'feel':10,'sknt':5,'gust':None,'vsby':10,'p01i':0,'raw':'METAR AMW AO2 SLP123','wxcodes':''} for i in range(96)]
    raw={'url':'https://example.org/archive','fetched_at':'2026-01-01T00:00:00+00:00','raw_sha256':'test','rows':rows}
    async def fetch(*args,**kwargs):return raw
    monkeypatch.setattr(h,'year_rows',fetch);monkeypatch.setattr(h,'proxies',lambda day=None:[])
    yield SimpleNamespace(rows=rows,raw=raw)
    db.set_engine(old);engine.dispose()

def test_csv_missing_values_and_weather():
    rows=parse_csv('station,valid,tmpf,feel,sknt,gust,vsby,p01i,metar\nAMW,2024-01-01 03:00,20,M,10,50,0.25,T,METAR FZRA AO2\n')
    assert rows[0]['feel'] is None and rows[0]['gust']==50 and 'FZRA' in rows[0]['wxcodes']

@pytest.mark.parametrize('day,clock',[('2024-03-10','02:30'),('2024-11-03','01:30'),('1990-01-01','04:00'),('2999-01-01','04:00'),('bad','04:00')])
def test_invalid_times(day,clock):
    with pytest.raises(HTTPException):h.local_instant(day,clock)

def test_exact_four_am_and_dst():
    assert h.local_instant('2024-01-02').isoformat()=='2024-01-02T10:00:00+00:00'
    assert h.local_instant('2024-07-02').isoformat()=='2024-07-02T09:00:00+00:00'

def test_cutoff_never_sees_future_observations(env):
    at=h.local_instant('2024-01-02');inputs=h.observation_inputs(env.rows,at,env.raw)
    assert all(i.source_time<=at-timedelta(minutes=15) for i in inputs)
    assert all(p.t<=at for i in inputs for p in i.series)
    baseline=[i.model_dump() for i in inputs];future={**env.rows[-1],'gust':200}
    assert [i.model_dump() for i in h.observation_inputs(env.rows+[future],at,env.raw)]==baseline

def test_outcomes_independent_and_missing(env):
    result=h.outcome(env.rows,'2024-01-02','America/Chicago')
    assert result['gradable'] and not result['disruptive']
    env.rows[40]['gust']=70
    assert h.outcome(env.rows,'2024-01-02','America/Chicago')['disruptive']
    missing=h.outcome(env.rows[:3],'2024-01-02','America/Chicago')
    assert not missing['gradable'] and missing['disruptive'] is None

def test_compact_dedup_and_chart_context(env):
    first=asyncio.run(h.compute('2024-01-02'));again=asyncio.run(h.compute('2024-01-02'))
    assert first['id']==again['id']
    with db.session() as s:
        assert len(s.exec(select(HistoricalEvaluation)).all())==1
        assert len(s.exec(select(HistoricalArtifact)).all())==1
    from app.routers.core import build_timeseries
    snap=snapshots.get(first['id']);chart=build_timeseries(snap)
    assert snap['as_of']==first['as_of']
    assert all(datetime.fromisoformat(p['t'])<=datetime.fromisoformat(first['as_of']) for p in chart['rows'])

def test_different_clocks_and_rule_versions(env,monkeypatch):
    first=asyncio.run(h.compute('2024-01-02'));later=asyncio.run(h.compute('2024-01-02','05:00'))
    original=h.load_thresholds
    def changed():
        value=original().model_copy(deep=True);value.sha256='new-rules';return value
    monkeypatch.setattr(h,'load_thresholds',changed)
    new=asyncio.run(h.compute('2024-01-02'))
    assert len({first['id'],later['id'],new['id']})==3
    assert snapshots.get(first['id'])['thresholds_sha256']!='new-rules'

def test_future_forecast_and_publication_lag(env,monkeypatch):
    at=h.local_instant('2024-01-02')
    def inp(id,issue):return NormalizedInput(id=id,kind='series',role='forecast',metric='wind_gust_mph',unit='mph',series=[Point(t=at+timedelta(hours=2),v=80)],source='test',source_url='https://example.org',fetched_at=at,source_time=issue)
    async def gather(*args):return [inp('future',at+timedelta(hours=1)),inp('late',at-timedelta(hours=1)),inp('fcst.wind_gust_mph',at-timedelta(hours=3))],[SourceStatus(adapter='test',label='test',status='ok')]
    monkeypatch.setattr(h,'gather',gather)
    result=asyncio.run(h.compute('2024-01-02',reconstruction='archive'));ids={i['id'] for i in result['snapshot']['inputs']}
    assert 'future' not in ids and 'late' not in ids and 'fcst.wind_gust_mph' in ids
    assert result['reconstruction'].startswith('archived forecast')

def test_revised_alerts_and_future_road_measurements_excluded(env,monkeypatch):
    at=h.local_instant('2024-01-02')
    alert=NormalizedInput(id='alert:final',kind='alert',role='alert',metric='nws_alert',value='Blizzard Warning',data={'ends':(at+timedelta(hours=12)).isoformat()},source='VTEC final archive',source_url='https://example.org',fetched_at=at,source_time=at-timedelta(days=1))
    road=NormalizedInput(id='obs.road',kind='series',role='observation',metric='temp_f',unit='degF',series=[Point(t=at-timedelta(hours=1),v=20),Point(t=at+timedelta(hours=1),v=90)],source='test',source_url='https://example.org',fetched_at=at,source_time=at-timedelta(hours=1))
    async def gather(*args):return [alert,road],[]
    monkeypatch.setattr(h,'gather',gather)
    result=asyncio.run(h.compute('2024-01-02',reconstruction='archive'))
    assert not result['snapshot']['alerts']
    assert all(p['t'] <= result['as_of'] for i in result['snapshot']['inputs'] if i['role']=='observation' for p in i.get('series') or [])


def test_archive_backup_can_support_prediction_when_observations_unavailable(env, monkeypatch):
    from adapters.cache import SourceUnavailable, historical_online
    async def missing(*args, **kwargs): raise SourceUnavailable('Observation archive not cached')
    monkeypatch.setattr(h, 'year_rows', missing)
    at = h.local_instant('2024-01-02')
    calls = []
    async def gather(facility, moment, mode):
        calls.append(historical_online.get())
        records = [NormalizedInput(id=f'fcst.{metric}', kind='series', role='forecast', metric=metric,
                   unit='degF' if metric=='temp_f' else 'mph',
                   series=[Point(t=at+timedelta(hours=j),v=value) for j in range(48)],
                   source='Archived GFS MOS backup', source_url='https://example.org/original-forecast',
                   fetched_at=at+timedelta(days=365), source_time=at-timedelta(hours=4),
                   data={'weather_fallback':True, 'limitations':['Snow and ice amounts unavailable.']})
                   for metric,value in [('temp_f',50),('wind_speed_mph',8)]]
        return records,[SourceStatus(adapter='iem_gfs',label='Archived GFS MOS',status='ok')]
    monkeypatch.setattr(h, 'gather', gather)
    result = asyncio.run(h.compute('2024-01-02', reconstruction='archive', online=False))
    assert calls == [False]
    assert result['pipeline_version'] == 'v4' and result['reconstruction'].startswith('archived secondary forecast')
    assert result['recommendation'] == 'NORMAL' and not result['outcome']['gradable']
    assert result['snapshot']['sufficiency']['provisional'] and not result['snapshot']['sufficiency']['supports_all_clear']
    assert not result['selection_gradable']  # No observations to independently grade a prediction.
    assert all(datetime.fromisoformat(i['source_time'])+timedelta(hours=2)<=at for i in result['snapshot']['inputs'])


def test_observation_baseline_does_not_silently_use_backup_forecasts(env, monkeypatch):
    from adapters.cache import SourceUnavailable
    async def missing(*args, **kwargs): raise SourceUnavailable('Observation archive unavailable')
    async def forbidden(*args, **kwargs): raise AssertionError('Observation-only baseline must remain separate')
    monkeypatch.setattr(h, 'year_rows', missing)
    monkeypatch.setattr(h, 'gather', forbidden)
    with pytest.raises(SourceUnavailable):
        asyncio.run(h.compute('2024-01-02', reconstruction='observation'))


def test_missing_evaluation_year_keeps_adjacent_observation_provenance(env, monkeypatch):
    from adapters.cache import SourceUnavailable
    rows = [{**env.rows[0], 'utc_valid':(datetime(2023,12,31,15,tzinfo=timezone.utc)+timedelta(hours=j)).isoformat()} for j in range(9)]
    adjacent = {**env.raw, 'rows':rows, 'url':'https://example.org/2023-observations'}
    async def fetch(year, **kwargs):
        if year == 2024: raise SourceUnavailable('2024 archive unavailable')
        return adjacent
    async def gather(*args): return [], []
    monkeypatch.setattr(h,'year_rows',fetch);monkeypatch.setattr(h,'gather',gather)
    value = asyncio.run(h.compute('2024-01-01',reconstruction='archive'))
    assert value['snapshot']['inputs'] and value['provenance']['url'] == adjacent['url']
    assert all(i['source_url'] == adjacent['url'] for i in value['snapshot']['inputs'])


def test_explicit_cloud_restore_can_precede_forecast_only_fallback(env, monkeypatch):
    from adapters.cache import SourceUnavailable
    async def missing(*args, **kwargs): raise SourceUnavailable('Restore this observation archive first')
    async def forbidden(*args, **kwargs): raise AssertionError('Cloud restoration must be tried before forecast-only fallback')
    monkeypatch.setattr(h,'year_rows',missing);monkeypatch.setattr(h,'gather',forbidden)
    with pytest.raises(SourceUnavailable):
        asyncio.run(h.compute('2024-01-02',reconstruction='archive',require_observations=True))

def test_recommendation_for_other_day_not_scored(env):
    value=asyncio.run(h.compute('2024-01-06'))
    assert value['decision_day']=='2024-01-08'
    result=h.metrics([value])
    assert result['impact']=={} and result['excluded']=={'Recommendation targets a different scheduled facility day':1}

def test_failed_year_is_not_requested_every_day(env,monkeypatch):
    calls=[]
    async def fail(year,**kwargs):
        calls.append(year)
        from adapters.cache import SourceUnavailable
        raise SourceUnavailable('not cached')
    monkeypatch.setattr(h,'year_rows',fail)
    state=h.create_job('2024-01-02','2024-01-05');asyncio.run(h.run_job(state['id']))
    value=h.job_get(state['id'])
    assert calls==[2024] and value['status']=='completed_with_gaps'
    assert value['failed'][0]['through']=='2024-01-05'

def test_cancelled_build_can_resume_without_duplicates(env,monkeypatch):
    original=h.compute
    async def cancel_after_first(*args,**kwargs):
        result=await original(*args,**kwargs)
        raise asyncio.CancelledError()
    state=h.create_job('2024-01-02','2024-01-03')
    monkeypatch.setattr(h,'compute',cancel_after_first)
    with pytest.raises(asyncio.CancelledError):asyncio.run(h.run_job(state['id']))
    assert h.job_get(state['id'])['status']=='interrupted'
    monkeypatch.setattr(h,'compute',original);asyncio.run(h.run_job(state['id']))
    with db.session() as s:assert len(s.exec(select(HistoricalEvaluation)).all())==2

def test_scores_and_single_class():
    m=h.binary_metrics([(True,True),(False,True),(True,False),(False,False)])
    assert m['n']==4 and m['correct']==2 and m['balanced_accuracy']==.5
    assert h.binary_metrics([(False,False)])['balanced_accuracy'] is None
    assert h.binary_metrics([])['accuracy'] is None

def test_proxy_mapping_and_denominators():
    rows=[{'day':'2024-01-02','as_of':'2024-01-02T10:00:00+00:00','reconstruction':'observation-based reconstruction','selection_gradable':True,'recommendation':'TELEWORK','hazard':'winter','outcome':{'gradable':True,'disruptive':True},'proxy_records':[]}]
    for name,status in [('school1','REMOTE_LEARNING'),('school2','CLOSED')]:rows[0]['proxy_records'].append({'institution':name,'institution_type':'school','day':'2024-01-02','status':status,'cause':'weather','verification':'official','announced_at':None})
    result=h.metrics(rows)
    assert result['proxy_unique_days']==1 and result['proxy_institution_days']==2
    assert result['proxy']['observation-based reconstruction|school1']['exact_status']['n']==0
    rows[0]['outcome']={'gradable':False,'disruptive':None,'reason':'missing'}
    assert h.metrics(rows)['excluded']=={'missing':1}

def test_durable_jobs_and_recovery(env):
    state=h.create_job('2024-01-02','2024-01-03');asyncio.run(h.run_job(state['id']))
    assert h.job_get(state['id'])['status']=='completed'
    asyncio.run(h.run_job(state['id']))
    with db.session() as s:assert len(s.exec(select(HistoricalEvaluation)).all())==2
    state['status']='running';h.job_save(state);h.recover_jobs()
    assert h.job_get(state['id'])['status']=='interrupted'

def test_search_cannot_record_or_send(env):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        result=client.post('/api/backtesting/search',json={'day':'2024-01-02'}).json()
        assert result['snapshot']['mode']=='backtest'
        response=client.post('/api/decisions',json={'snapshot_id':result['id'],'decided_by':'Test Manager','decision_posture':result['recommendation']})
        assert response.status_code==422

def test_historical_browsing_does_not_launch_ai_reviews(env,monkeypatch):
    from app.routers import past as router
    from fastapi.testclient import TestClient
    from app.main import app
    result=asyncio.run(h.compute('2024-01-02'))
    monkeypatch.setattr(router.past,'list_past',lambda *args:([{'decided_at':'2026-01-01T00:00:00+00:00'}],[42]))
    async def forbidden(*args):raise AssertionError('Automatic review must not run')
    monkeypatch.setattr(router.past,'review_due',forbidden)
    with TestClient(app) as client:
        value=client.get('/api/past-decisions',params={'snapshot_id':result['id']}).json()
        assert value=={'decisions':[],'reviewing':[]}

def test_proxy_records_not_counted_twice_between_reconstructions():
    record={'institution':'school','institution_type':'school','day':'2024-01-02','status':'CLOSED','cause':'weather','verification':'official','announced_at':None}
    row={'day':'2024-01-02','as_of':'2024-01-02T10:00:00+00:00','reconstruction':'observation-based reconstruction','selection_gradable':True,'recommendation':'CLOSED','hazard':'winter','outcome':{'gradable':True,'disruptive':True},'proxy_records':[record]}
    value=h.metrics([row,{**row,'reconstruction':'archived forecast reconstruction'}])
    assert value['proxy_institution_days']==1 and value['announcement_time_unknown']==1
    assert len(value['proxy_counts_by_reconstruction'])==2

def test_compact_ai_addon_is_explicit_and_preserves_original(env,monkeypatch):
    import time
    from ai import agent,fallback
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(settings,'model_provider','akamai')
    monkeypatch.setattr(settings,'akamai_api_key','dummy-test-key')
    monkeypatch.setattr(settings,'strands_fallback_enabled',False)
    calls=[]
    async def inference(provider,snap,feedback):
        calls.append(snap['snapshot_id'])
        return fallback.build(snap),{'provider':'akamai','model':'hackathon-chat','usage':None}
    monkeypatch.setattr(agent,'_run_agent',inference)
    result=asyncio.run(h.compute('2024-01-02'));sid=result['id'];original=result['snapshot']['content_sha256']
    with TestClient(app) as client:
        assert client.get(f'/api/snapshot/{sid}').json()['ai_addon']['status']=='none'
        assert calls==[]
        assert client.post(f'/api/snapshot/{sid}/interpretation').status_code==202
        for _ in range(100):
            value=client.get(f'/api/snapshot/{sid}').json()
            if value['ai_addon']['status']!='pending':break
            time.sleep(.01)
        assert value['ai_addon']['status']=='ok' and calls==[sid]
        assert value['integrity_ok'] and value['content_sha256']==original


def test_present_weather_ignores_remarks():
    """'LTG DSNT' and 'FZRANO' in remarks once read as snow and freezing rain (summer 'snow' days in the cohort)."""
    from adapters.historical_asos import present_weather
    assert present_weather('KAMW 202153Z AUTO 20010KT 10SM CLR 32/24 A2975 RMK AO2 LTG DSNT N AND NE SLP061') == ''
    assert present_weather('KAMW 010153Z AUTO 05012KT 10SM CLR 01/M02 A2990 RMK AO2 FZRANO TSNO PLE15') == ''
    assert present_weather('KAMW 110153Z AUTO 36015G20KT 6SM -SN BR OVC050 M01/M03 A3022 RMK AO2 SNB48') == '-SN BR'
    assert present_weather('KAMW 010153Z 27030G45KT 1/4SM +TSRA BLSN VCSH OVC008 10/08 A2990 RMK AO2') == '+TSRA BLSN VCSH'
    rows = parse_csv('station,valid,tmpf,feel,sknt,gust,vsby,p01i,metar\nAMW,2024-07-01 03:00,80,M,10,M,10,M,'
                     'KAMW 010300Z AUTO 20010KT 10SM CLR 27/20 A2975 RMK AO2 LTG DSNT\n')
    assert rows[0]['wxcodes'] == ''
