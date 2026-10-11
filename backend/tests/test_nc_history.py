"""Facility isolation and original-as-of coastal replay coverage boundaries."""
import asyncio
import copy
from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient
from app import db,historical,nc_replay,replay_timeline,risk_experiment,dataset_cloud
from app.config import settings
from app.facility import load_facility
from app.main import app
from adapters.base import utc
from adapters.historical_asos import parse_csv,source_url
import pytest

SITE=nc_replay.FACILITY_ID

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    old=db._engine;engine=db.make_engine(f'sqlite:///{tmp_path}/nc.db');db.set_engine(engine)
    monkeypatch.setattr(settings,'db_path',tmp_path/'nc.db')
    monkeypatch.setattr(settings,'demo_mode',True)
    monkeypatch.setattr(settings,'obj_bucket','')
    monkeypatch.setattr(settings,'model_provider','none')
    monkeypatch.setattr(settings,'strands_fallback_enabled',False)
    yield
    db.set_engine(old);engine.dispose()


def test_station_sources_and_cache_identity_are_distinct():
    assert 'station=ILM' in source_url(2024,'ILM','NC_ASOS')
    assert 'network=NC_ASOS' in source_url(2024,'ILM','NC_ASOS')
    text='station,valid,tmpf,feel,sknt,gust,vsby,p01i,metar\nAMW,2024-01-02 00:00,20,20,4,M,10,0,KAMW CLR\nILM,2024-01-02 00:00,70,70,4,M,10,0,KILM CLR\n'
    assert parse_csv(text,'ILM')[0]['tmpf']==70
    at=datetime(2024,1,2,10,tzinfo=timezone.utc)
    assert historical.identity(at,'archive')[0]!=historical.identity(at,'archive',SITE)[0]
    assert risk_experiment.manifest_path(SITE)!=risk_experiment.manifest_path()
    assert dataset_cloud.dataset_version(SITE)!=dataset_cloud.dataset_version()


def test_ames_archive_identity_preserves_existing_config_but_tracks_real_changes(monkeypatch):
    at = datetime(2024, 1, 2, 10, tzinfo=timezone.utc)
    # Config digest used before the facility schema gained coastal defaults.
    original = 'd03e8bf3d73beed3c530ac499c708619d2971bef9351dbf89f543eeacd70890e'
    assert historical.identity(at, 'observation')[2] == original
    changed = load_facility().model_copy(update={'provider_settings': {'forecast': 'new-source'}})
    monkeypatch.setattr(historical, 'load_facility', lambda _: changed)
    assert historical.identity(at, 'observation')[2] != original


def test_four_am_respects_each_facility_timezone():
    assert historical.local_instant('2024-01-02',facility_id=SITE).hour==9
    assert historical.local_instant('2024-01-02').hour==10
    assert historical.local_instant('2024-07-02',facility_id=SITE).hour==8


def test_original_forecast_publication_and_observation_gates():
    at=datetime(2018,9,14,8,tzinfo=timezone.utc)
    _,inputs,_,_=nc_replay.evaluation('nc-florence-2018-09-14',at)
    assert any(i.role=='forecast' for i in inputs)
    for item in inputs:
        if item.role=='forecast':
            assert item.source_time+timedelta(hours=2)<=at
            for origin in item.data['point_sources'].values():
                assert utc(datetime.fromisoformat(origin['source_time']))+timedelta(hours=2)<=at
        else:
            assert item.source_time<=at-timedelta(minutes=15)
            assert all(p.t<=at-timedelta(minutes=15) for p in item.series)
    metrics={i.metric for i in inputs if i.role=='forecast'}
    assert not metrics&{'qpf_in','snow_in','ice_in','wind_gust_mph','water_level_ft'}


def test_later_forecast_and_observation_changes_cannot_change_past_evaluation(monkeypatch):
    event_id='nc-florence-2018-09-14';at=datetime(2018,9,14,8,tzinfo=timezone.utc)
    baseline=nc_replay.evaluation(event_id,at)[1]
    fixture=copy.deepcopy(nc_replay.fixture(event_id))
    for source in fixture['observations']:
        for row in source['rows']:
            if utc(datetime.fromisoformat(row['utc_valid']))>at-timedelta(minutes=15):row['gust']=250
    for source in fixture['forecasts']:
        for row in source['data']:
            if utc(datetime.fromisoformat(row['runtime_utc']))+timedelta(hours=2)>at:row['wsp']=250
    monkeypatch.setattr(nc_replay,'fixture',lambda _:fixture)
    after=nc_replay.evaluation(event_id,at)[1]
    assert [i.model_dump() for i in after]==[i.model_dump() for i in baseline]


def test_control_verifies_station_weather_without_claiming_coastal_safety():
    event=nc_replay.event(nc_replay.CONTROL_ID)
    assert event['outcome']['gradable'] and not event['outcome']['disruptive']
    assert event['outcome']['hours']==24
    assert event['outcome']['coastal_impacts']=='unknown'
    assert event['outcome']['outcome_sufficient'] is False
    assert event['partial'] is True
    assert event['backtest']['at_0400_local']['posture']=='NORMAL'
    assert event['backtest']['at_0400_local']['readiness']!='RED'


def test_catalog_replay_and_date_search_work_offline_without_current_feeds(isolated,monkeypatch):
    async def forbidden(*args,**kwargs):raise AssertionError('Retained replay must never call current/live weather')
    monkeypatch.setattr(historical,'gather',forbidden)
    monkeypatch.setattr(replay_timeline,'gather',forbidden)
    with TestClient(app) as client:
        events=client.get('/api/history/events',params={'facility_id':SITE}).json()
        assert len(events)==4 and all(e['facility_id']==SITE for e in events)
        assert not any(e['id'].startswith('ice-') for e in events)
        query={'facility_id':SITE,'as_of':'2018-09-14T08:00:00Z'}
        replay=client.get('/api/history/events/nc-florence-2018-09-14/replay',params=query)
        assert replay.status_code==200
        snap=replay.json()
        assert snap['facility']['id']==SITE and snap['mode']=='replay'
        assert snap['historical_context']['outcome']['outcome_sufficient'] is False
        timeline=client.get('/api/replay/timeline',params=query).json()
        assert timeline['timezone']=='America/New_York' and len(timeline['timeline'])==25
        search=client.post('/api/backtesting/search',json={'facility_id':SITE,'day':'2018-09-14','time':'04:00','mode':'archive'})
        assert search.status_code==200 and search.json()['snapshot']['facility']['id']==SITE
        assert client.get('/api/history/events/normal-2024-07-18',params={'facility_id':SITE}).status_code==404
        assert client.get('/api/history/events/nc-florence-2018-09-14').status_code==404
        assert client.get('/api/history/events',params={'facility_id':'unknown'}).status_code==422


def test_station_only_nc_outcomes_are_excluded_from_coastal_accuracy():
    row={'id':'nc-test','day':'2024-10-16','as_of':'2024-10-16T08:00:00+00:00','decision_day':'2024-10-16','reconstruction':'archive',
         'recommendation':'NORMAL','selection_gradable':True,'hazard':'wind','rule_margin_pct':-50,
         'outcome':{'gradable':True,'disruptive':False,'outcome_sufficient':False},'proxy_records':[]}
    metrics=historical.metrics([row],SITE)
    assert metrics['excluded']=={'Coastal impacts are not independently covered by station observations':1}


def test_builds_and_benchmarks_are_facility_scoped(isolated):
    ames=historical.create_job('2024-01-02','2024-01-02')
    coastal=historical.create_job('2024-01-02','2024-01-02',facility_id=SITE)
    assert historical.overview()['jobs'][0]['id']==ames['id']
    nc=historical.overview(SITE)
    assert nc['jobs'][0]['id']==coastal['id'] and nc['proxy_records']==[]
    assert nc['analysis_cohort'] is None and nc['storage']['source_station']=='ILM'
    assert nc['supported_start']=='1942-06-01'


def test_repeated_selected_report_reuses_snapshot_and_one_mocked_akamai_brief(isolated,monkeypatch):
    from ai import agent,fallback
    from app import snapshots
    from app.models import Snapshot
    from sqlmodel import select
    import time
    monkeypatch.setattr(settings,'model_provider','akamai')
    monkeypatch.setattr(settings,'akamai_api_key','dummy-test-key')
    calls=[]
    async def mock_inference(provider,snap,feedback):
        calls.append(snap['snapshot_id'])
        assert not snap.get('historical_context'), 'Hindsight outcomes must not enter the brief context'
        return fallback.build(snap),{'provider':'akamai','model':'hackathon-chat','usage':None}
    monkeypatch.setattr(agent,'_run_agent',mock_inference)
    with TestClient(app) as client:
        path='/api/history/events/nc-florence-2018-09-14/replay'
        params={'facility_id':SITE,'as_of':'2018-09-14T08:00:00Z'}
        first=client.get(path,params=params).json()
        for _ in range(20):
            if snapshots.interpretation(first['snapshot_id'])['status']!='pending':break
            time.sleep(.01)
        second=client.get(path,params=params).json()
        assert first['snapshot_id']==second['snapshot_id']
        assert calls==[first['snapshot_id']]
        assert second['ai_addon']['status']=='ok'
        with db.session() as session:
            assert len(session.exec(select(Snapshot).where(Snapshot.facility_id==SITE)).all())==1


@pytest.mark.parametrize('request_flags',[{'online':True},{'force':True},{'require_observations':True}])
def test_explicit_archive_requests_do_not_silently_reuse_partial_coastal_fixture(isolated,monkeypatch,request_flags):
    calls=[]
    source=nc_replay.fixture('nc-florence-2018-09-14')['observations'][1]
    async def year(year,**kwargs):
        calls.append(('year',year,kwargs))
        assert kwargs['station']=='ILM' and kwargs['network']=='NC_ASOS'
        return source
    async def gather(*args):
        calls.append(('gather',args[1]))
        return [],[]
    def forbidden(*args,**kwargs):raise AssertionError('Explicit rebuild/enrichment must not reuse curated fixture')
    monkeypatch.setattr(historical,'year_rows',year)
    monkeypatch.setattr(historical,'gather',gather)
    monkeypatch.setattr(nc_replay,'replay',forbidden)
    result=asyncio.run(historical.compute('2018-09-14',reconstruction='archive',facility_id=SITE,**request_flags))
    assert result['id'].startswith('bt-')
    assert [c[0] for c in calls]==['year','gather']


@pytest.mark.parametrize('endpoint,payload',[
    ('/api/backtesting/search',{'day':'2024-01-02'}),
    ('/api/backtesting/build',{'start':'2024-01-02','end':'2024-01-02'}),
])
def test_backtesting_rejects_conflicting_facilities_before_work(isolated,monkeypatch,endpoint,payload):
    def forbidden(*args,**kwargs):raise AssertionError('Conflicting site request must not launch work')
    monkeypatch.setattr(historical,'compute',forbidden)
    monkeypatch.setattr(historical,'create_job',forbidden)
    with TestClient(app) as client:
        response=client.post(endpoint,params={'facility_id':'IA-AMES-SC'},json={**payload,'facility_id':SITE})
        assert response.status_code==422
        assert response.json()['detail']=='Facility identifiers disagree'


def test_explicit_cloud_restore_uses_restored_year_evidence_instead_of_partial_fixture(isolated,monkeypatch):
    from adapters.cache import SourceUnavailable
    restored=[];downloads=[]
    source=nc_replay.fixture('nc-florence-2018-09-14')['observations'][1]
    async def year(year,**kwargs):
        downloads.append(year)
        if not restored:raise SourceUnavailable('Station year archive not cached')
        return source
    async def gather(*args):return [],[]
    def restore(**kwargs):
        assert kwargs=={'year':'2018','facility_id':SITE}
        restored.append(True)
    def forbidden(*args,**kwargs):raise AssertionError('Cloud restoration must use restored year sources')
    monkeypatch.setattr(historical,'year_rows',year)
    monkeypatch.setattr(historical,'gather',gather)
    monkeypatch.setattr(dataset_cloud,'restore',restore)
    monkeypatch.setattr(nc_replay,'replay',forbidden)
    with TestClient(app) as client:
        response=client.post('/api/backtesting/search',json={'facility_id':SITE,'day':'2018-09-14','mode':'archive','cloud_cache':True})
        assert response.status_code==200 and response.json()['id'].startswith('bt-')
        assert downloads==[2018,2018] and restored==[True]


def test_cached_forecast_only_result_is_enriched_as_a_new_immutable_observation_attempt(isolated,monkeypatch):
    from adapters.cache import SourceUnavailable
    from adapters.base import SourceStatus
    day='2024-10-16';at=historical.local_instant(day,facility_id=SITE)
    data=nc_replay.fixture(nc_replay.CONTROL_ID)
    forecasts=nc_replay.forecast_inputs(data,at)
    restored=[];year_calls=[]
    raw={**data['observations'][1],'rows':sorted((r for source in data['observations'] for r in source['rows']),key=lambda r:r['utc_valid'])}
    async def year(year,**kwargs):
        year_calls.append(year)
        if not restored:raise SourceUnavailable('Station archive missing')
        return raw
    async def gather(*args):
        return forecasts,[SourceStatus(adapter='iem_obs',label='Station archive',status='unavailable')]
    def restore(**kwargs):restored.append(kwargs)
    monkeypatch.setattr(historical,'year_rows',year)
    monkeypatch.setattr(historical,'gather',gather)
    monkeypatch.setattr(dataset_cloud,'restore',restore)
    first=asyncio.run(historical.compute(day,reconstruction='archive',online=True,facility_id=SITE))
    assert not first['outcome']['gradable']
    assert not any(i['role']=='observation' for i in first['snapshot']['inputs'])
    first_hash=first['snapshot']['content_sha256']
    with TestClient(app) as client:
        response=client.post('/api/backtesting/search',json={'facility_id':SITE,'day':day,'mode':'archive','cloud_cache':True})
    assert response.status_code==200
    enriched=response.json()
    assert restored==[{'year':'2024','facility_id':SITE}]
    assert enriched['id'].startswith(first['id']+'-')
    assert enriched['outcome']['gradable']
    assert any(i['role']=='observation' for i in enriched['snapshot']['inputs'])
    retained=historical.lookup(enriched['id'])
    assert retained['snapshot_id']==enriched['snapshot']['snapshot_id']
    assert retained['content_sha256']==enriched['snapshot']['content_sha256']
    assert retained['inputs']==enriched['snapshot']['inputs']
    assert historical.lookup(first['id'])['content_sha256']==first_hash


def test_cached_complete_station_archive_satisfies_required_observation_check(isolated,monkeypatch):
    day='2024-10-16';data=nc_replay.fixture(nc_replay.CONTROL_ID)
    raw={**data['observations'][1],'rows':sorted((r for source in data['observations'] for r in source['rows']),key=lambda r:r['utc_valid'])}
    async def year(*args,**kwargs):return raw
    async def gather(*args):return [],[]
    monkeypatch.setattr(historical,'year_rows',year)
    monkeypatch.setattr(historical,'gather',gather)
    first=asyncio.run(historical.compute(day,reconstruction='archive',online=True,facility_id=SITE))
    assert first['outcome']['gradable']
    async def forbidden(*args,**kwargs):raise AssertionError('Proven cached station coverage remains reusable')
    monkeypatch.setattr(historical,'year_rows',forbidden)
    monkeypatch.setattr(historical,'gather',forbidden)
    second=asyncio.run(historical.compute(day,reconstruction='archive',require_observations=True,facility_id=SITE))
    assert second['id']==first['id']
