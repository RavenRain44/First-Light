"""Compact multi-year reconstruction, durable builds and honest benchmark metrics.

ASOS-only baselines do not predict afternoon weather. Archive enrichment is a
separate reconstruction with estimated NBS availability, not verified forecast accuracy.
"""
from __future__ import annotations
import asyncio
import gzip
import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlmodel import select
from adapters.base import NormalizedInput, Point, SourceStatus, utc
from adapters.historical_asos import START, archive_dir, year_rows
from adapters.iem_obs import UNITS, _t, obs_series
from app import snapshots
from app.config import settings
from app.db import session
from app.facility import load_facility
from app.models import HistoricalArtifact, HistoricalBuild, HistoricalEvaluation
from engine import error_analysis
from engine.evaluate import assess, gather, json_ready
from engine.scoring import load_thresholds

OUTCOME_VERSION = 'AMW-local-disruption-v1'
TASKS = {}
_day_lock = asyncio.Lock()


def dumps(obj):
    return json.dumps(json_ready(obj), default=str, separators=(',', ':'), sort_keys=True)


def local_instant(day, clock='04:00'):
    try:
        d, t = date.fromisoformat(day), time.fromisoformat(clock)
        if t.second or t.microsecond or t.tzinfo:
            raise ValueError()
        naive = datetime.combine(d,t)
        tz = ZoneInfo(load_facility().timezone)
        choices = {naive.replace(tzinfo=tz,fold=f).astimezone(timezone.utc) for f in (0,1)
                   if naive.replace(tzinfo=tz,fold=f).astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == naive}
        if len(choices) != 1:
            raise HTTPException(422,'This local time is ambiguous or does not exist because of daylight saving; choose another time.')
        instant = choices.pop()
    except (ValueError, TypeError):
        raise HTTPException(422,'Enter a valid date and HH:MM local time.')
    if d < date.fromisoformat(START):
        raise HTTPException(422,f'Outside supported AMW archive range (starts {START}); completeness varies by date.')
    if d >= datetime.now(tz).date():
        raise HTTPException(422,'Future/current day: a complete historical outcome is not available yet.')
    return instant


def identity(as_of, reconstruction):
    rules = load_thresholds()
    config = hashlib.sha256(dumps(load_facility()).encode()).hexdigest()
    pipeline = 'v3' if reconstruction == 'archive' else 'v2'
    key = f'{as_of.isoformat()}|{rules.sha256}|{config}|{reconstruction}|{OUTCOME_VERSION}|{pipeline}'
    return 'bt-' + hashlib.sha256(key.encode()).hexdigest()[:32], rules, config


def lookup(id):
    with session() as s:
        row = s.get(HistoricalEvaluation,id)
        if not row or not row.artifact_sha: return None
        blob = s.get(HistoricalArtifact,row.artifact_sha)
        snap = json.loads(gzip.decompress(blob.payload)) if blob else None
    if snap:
        # Read-time enrichments are separate from the immutable compressed artifact.
        snap['integrity_ok'] = snapshots.content_hash(snap) == snap['content_sha256']
        snap['ai_addon'] = snapshots.interpretation(id)
        from engine import analogs
        snap['analogs_addon'] = analogs.find_analogs(snap['features'])
    return snap


def proxies(day=None, include_unconfirmed=False):
    path = Path(__file__).resolve().parents[1] / 'data' / 'historical_closures.json'
    records = json.loads(path.read_text())['records'] if path.exists() else []
    from app.decision_evidence import eligible
    return [r for r in records if (day is None or r['day'] == day) and (include_unconfirmed or eligible(r))]


def observation_inputs(rows, as_of, provenance):
    end = as_of - timedelta(minutes=15)
    past = [r for r in rows if as_of-timedelta(hours=12) <= _t(r['utc_valid']) <= end]
    series = obs_series(past)
    inputs = [NormalizedInput(id=f'obs.{m}',kind='series',role='observation',metric=m,unit=UNITS[m],
              series=[Point(t=t,v=round(v,2)) for t,v in pts], source='AMW archived routine/special METAR',
              source_url=provenance['url'], fetched_at=datetime.fromisoformat(provenance['fetched_at']),
              source_time=_t(past[-1]['utc_valid']) if past else None,
              note='Observation-based reconstruction; validity + assumed 15-minute latency, ingestion times not archived.')
              for m,pts in series.items() if pts]
    return inputs


def outcome(rows, day, tz):
    start = datetime.combine(date.fromisoformat(day),time(),ZoneInfo(tz)).astimezone(timezone.utc)
    end = (datetime.combine(date.fromisoformat(day)+timedelta(days=1),time(),ZoneInfo(tz))).astimezone(timezone.utc)
    selected = [r for r in rows if start <= _t(r['utc_valid']) < end]
    valid = [r for r in selected if r.get('tmpf') is not None and r.get('sknt') is not None and r.get('raw')]
    hours = {_t(r['utc_valid']).replace(minute=0,second=0,microsecond=0) for r in valid}
    needed = int((end-start).total_seconds()/3600)
    times = sorted([start] + [_t(r['utc_valid']) for r in valid] + [end])
    gap = max(((b-a).total_seconds()/3600 for a,b in zip(times,times[1:])),default=24)
    series = obs_series(selected)
    gust = max((v for _,v in series['peak_gust_mph']),default=None)
    fz = sum(v > 0 for _,v in series['freezing_precip'])
    snow = sum(v > 0 for _,v in series['snow_obs'])
    visibility = min((v for _,v in series['visibility_mi']),default=None)
    cold = min((v for _,v in series['apparent_temp_f']),default=None)
    # Independent impact definition, frozen independently of recommendation thresholds.
    disruptive = bool((gust is not None and gust >= 58) or fz >= 2 or
                      (snow >= 3 and visibility is not None and visibility <= .25) or
                      (cold is not None and cold <= -35))
    complete = len(hours) >= needed-2 and gap <= 3
    return {'method':OUTCOME_VERSION,'scope':'Local AMW station evidence only; corridor, snowfall totals, power outages and off-station damage unavailable.',
            'gradable':complete, 'disruptive':disruptive if complete else None,
            'reason':None if complete else 'Incomplete routine/special METAR coverage for independent daily outcome',
            'hours':len(hours),'expected_hours':needed,'largest_gap_hours':round(gap,2),
            'max_gust_mph':gust,'freezing_precip_hours':fz,'snow_hours':snow,'min_visibility_mi':visibility,'min_feels_like_f':cold}


async def compute(day, clock='04:00', reconstruction='observation', online=False, prefetched=None, force=False):
    as_of = local_instant(day,clock)
    id, rules, config_sha = identity(as_of,reconstruction)
    with session() as s:
        existing = s.get(HistoricalEvaluation,id)
        if existing and not force:
            meta = json.loads(existing.summary_json)
            meta['proxy_records'] = proxies(day)
            return {**meta,'snapshot':lookup(id) if meta.get('recommendation') else None}
    facility = load_facility()
    raw = prefetched or await year_rows(as_of.astimezone(ZoneInfo(facility.timezone)).year, online=online, retry=force and online)
    rows = raw['rows']
    # Jan 1 needs previous-year evening observations; Dec 31 outcome can cross UTC year.
    if day[5:] in ('01-01','12-31') and prefetched is None:
        other = int(day[:4]) + (-1 if day[5:]=='01-01' else 1)
        try: rows = sorted(rows + (await year_rows(other,online=online))['rows'],key=lambda r:r['utc_valid'])
        except Exception: pass  # explicit coverage labels below
    times = raw.get("_times") or [r["utc_valid"] for r in rows]
    begin = datetime.combine(date.fromisoformat(day),time(),ZoneInfo(facility.timezone)).astimezone(timezone.utc)-timedelta(hours=12)
    finish = begin+timedelta(hours=49)
    rows = rows[bisect_left(times,begin.isoformat()):bisect_right(times,finish.isoformat())]
    inputs = observation_inputs(rows,as_of,raw)
    statuses = [SourceStatus(adapter='iem_obs',label='AMW archived observations',status='ok' if inputs else 'empty',urls=[raw['url']], n_inputs=len(inputs))]
    kind = 'observation-based reconstruction'
    assumptions = ['Observation ingestion times unavailable: using validity + 15-minute lag.']
    if reconstruction == 'archive':
        from adapters.cache import historical_online
        token=historical_online.set(online)
        try: archive_inputs, statuses = await gather(facility,as_of,'backtest')
        finally: historical_online.reset(token)
        # Do not permit later source records. Ingest time uncertainty remains explicit.
        inputs += [i for i in archive_inputs if i.role != 'alert' and i.id not in {x.id for x in inputs} and i.source_time is not None and utc(i.source_time) <= as_of-(timedelta(minutes=15) if i.role=='observation' else timedelta()) and
                   (i.role != 'forecast' or utc(i.source_time)+timedelta(hours=2) <= as_of)]
        for item in inputs:
            if item.role == 'observation' and item.series:
                item.series = [p for p in item.series if utc(p.t) <= as_of-timedelta(minutes=15)]
        statuses = [s.model_copy(update={'status':'unavailable','n_inputs':0,'detail':'Final VTEC event records excluded: original expiration/update history not reconstructed.'}) if s.adapter=='iem_vtec' else s for s in statuses]
        if any(i.role == 'forecast' for i in inputs):
            kind = 'archived forecast reconstruction (estimated availability)'
        else:
            kind = 'observation-based reconstruction (archive enrichment; no forecast)'
        assumptions += ['NBS availability uses nominal run + 2-hour lag; exact publication times unavailable.',
                        'VTEC final event records can reflect later updates and are excluded from recommendation inputs.']
    missing = ['Archived corridor conditions, accumulation totals, facility outages and camera imagery may be unavailable.']
    if not any(i.role=='forecast' for i in inputs): missing.append('No archived forecast supplied; afternoon conditions cannot be predicted from morning observations alone.')
    if not any(i.kind=='alert' for i in inputs): missing.append('No alert inputs supplied; this is not proof no alerts existed.')
    assessment = assess(inputs,statuses,facility,as_of,'backtest',employees=[])
    snap = snapshots.build_snapshot_dict(facility,assessment,inputs,statuses,'backtest')
    from ai.agent import interpret
    from ai.prompts import PROMPT_VERSION
    from engine import analogs
    snap["analogs"] = analogs.find_analogs(snap["features"])
    snap['snapshot_id'] = id
    snap['ai'],snap['model_id'] = await interpret(snap,use_model=False)
    snap['prompt_version'] = PROMPT_VERSION
    if not any(i.kind == 'alert' for i in inputs):
        snap['ai']['uncertainty'] = 'Alert archive was not supplied. No displayed alerts does not establish that none existed. ' + snap['ai'].get('uncertainty','')
    snap['content_sha256'] = snapshots.content_hash(snap)
    complete_inputs = len({p.t.replace(minute=0,second=0,microsecond=0) for i in inputs if i.id=='obs.temp_f' for p in i.series or []}) >= 8
    status = 'partial' if inputs else 'unavailable'
    out = outcome(rows,day,facility.timezone)
    summary = {'id':id, 'day':day,'as_of':as_of.isoformat(),'reconstruction':kind,'requested_mode':reconstruction,
               'pipeline_version':'v3' if reconstruction=='archive' else 'v2',
               'status':status,'detail':'Partial historical reconstruction; consult source coverage.' if inputs else 'Archive contains no usable pre-evaluation observations or forecasts.',
               'rules_sha':rules.sha256,'rules_version':rules.version,'config_sha':config_sha,
               'recommendation':snap['posture']['posture'] if inputs else None,
               'decision_day':snap['posture']['decision_day'],
               'hazard':max(snap['hazards'],key=lambda h:snap['hazards'][h]['score']),
               'rule_margin_pct':error_analysis.day_margin(snap['rules']),
               'outcome':out,'selection_gradable':complete_inputs and bool(inputs),
               'missing':missing,'assumptions':assumptions,'provenance':{k:raw[k] for k in raw if k!='rows' and not k.startswith('_')},
               'source_coverage':[{ 'adapter':s.adapter, 'status':s.status, 'detail':s.detail} for s in statuses],
               'proxy_records':proxies(day)}
    snap['historical_context'] = summary
    payload = gzip.compress(dumps(snap).encode(),mtime=0)
    sha = hashlib.sha256(payload).hexdigest()
    with session() as s:
        # Immutable evaluations; retrying an unavailable/partial day creates a new attempt.
        prior = s.get(HistoricalEvaluation,id)
        if prior and force:
            id = id + '-' + uuid4().hex[:8]
            snap['snapshot_id']=id; summary['id']=id
            payload=gzip.compress(dumps(snap).encode(),mtime=0); sha=hashlib.sha256(payload).hexdigest()
        if not s.get(HistoricalArtifact,sha): s.add(HistoricalArtifact(sha256=sha,payload=payload)); s.commit()
        if not s.get(HistoricalEvaluation,id):
            s.add(HistoricalEvaluation(id=id,day=day,as_of=as_of.isoformat(),rules_sha=rules.sha256, config_sha=config_sha,
                  reconstruction=kind,status=status,summary_json=dumps(summary),artifact_sha=sha)); s.commit()
    return {**summary,'snapshot':snap if inputs else None}


_margins: dict[str,float|None] = {}


def rule_margin(row):
    """How close the day came to any threshold. Older summaries lack it; read it once from the immutable artifact."""
    if 'rule_margin_pct' in row: return row['rule_margin_pct']
    if row.get('id') is None: return None
    if row['id'] not in _margins:
        with session() as s:
            ev = s.get(HistoricalEvaluation,row['id'])
            blob = s.get(HistoricalArtifact,ev.artifact_sha) if ev and ev.artifact_sha else None
        _margins[row['id']] = error_analysis.day_margin(json.loads(gzip.decompress(blob.payload)).get('rules',[])) if blob else None
    return _margins[row['id']]


def binary_metrics(pairs):
    c=Counter((bool(pred),bool(actual)) for pred,actual in pairs)
    tp,tn,fp,fn=c[True,True],c[False,False],c[True,False],c[False,True]
    n=tp+tn+fp+fn
    recall=tp/(tp+fn) if tp+fn else None
    specificity=tn/(tn+fp) if tn+fp else None
    accuracy=(tp+tn)/n if n else None
    # Wilson interval for ordinary accuracy, not for balanced accuracy.
    interval=None
    if n:
        z=1.96; den=1+z*z/n; center=(accuracy+z*z/(2*n))/den
        radius=z*math.sqrt(accuracy*(1-accuracy)/n+z*z/(4*n*n))/den
        interval=[max(0,center-radius),min(1,center+radius)]
    return {'n':n,'correct':tp+tn,'accuracy':accuracy,'balanced_accuracy':(recall+specificity)/2 if recall is not None and specificity is not None else None,
            'precision':tp/(tp+fp) if tp+fp else None,'recall':recall,'specificity':specificity,
            'confusion':{'true_positive':tp,'true_negative':tn,'false_alarm':fp,'missed_disruption':fn},
            'accuracy_95pct_wilson':interval,'status':'not enough data' if n<30 or recall is None or specificity is None else 'descriptive estimate'}


def metrics(rows):
    weather=defaultdict(list); impact=defaultdict(list); breakdown=defaultdict(list); proxy=defaultdict(list); proxy_exact=defaultdict(list)
    excluded=Counter(); coverage=Counter(); proxy_days=set(); proxy_evidence={}; before=set(); disagreements={}; proxy_counts=defaultdict(set)
    for row in rows:
        kind=row['reconstruction']; coverage[kind]+=1
        # Earlier compact records predate this metadata. At 04:00 the deterministic
        # engine always targets today on workdays, and the next workday otherwise.
        target = row.get('decision_day')
        if target is None:
            from engine.posture import decision_day
            target = decision_day(datetime.fromisoformat(row['as_of']), load_facility()).isoformat()
        same_day = str(target) == row['day']
        if same_day and row.get('selection_gradable') and row['outcome']['gradable'] and row['recommendation']:
            pair=(row['recommendation']!='NORMAL',row['outcome']['disruptive'])
            impact[kind].append(pair)
            # Weather classification only; proxy closure records never enter these counts.
            weather[kind].append({'current_prediction':pair[0],'observed':pair[1],'margin':rule_margin(row)})
            for category in ('year:'+row['day'][:4],'hazard:'+row['hazard']): breakdown[kind+'|'+category].append(pair)
        else: excluded['Recommendation targets a different scheduled facility day' if not same_day else row['outcome'].get('reason') or 'Incomplete pre-evaluation input coverage']+=1
        for record in row.get('proxy_records',[]):
            if record.get('verification') not in ('official','reported') or record.get('cause')!='weather': continue
            status=record['status']
            if status not in ('NORMAL','CLOSED','DELAYED_ARRIVAL','EARLY_DISMISSAL','REMOTE_LEARNING','PARTIAL_CLOSURE'): continue
            if not same_day or not row['recommendation'] or not row.get('selection_gradable'): continue
            name=record['institution']; key=kind+'|'+name
            pair=(row['recommendation']!='NORMAL', status!='NORMAL')
            proxy[key].append(pair); proxy_days.add(row['day']); proxy_evidence[(name,row['day'])]=record
            proxy_counts[kind].add((name,row['day']))
            categories = [kind+'|'+category for category in ('type:'+record['institution_type'],'year:'+row['day'][:4],'hazard:'+row['hazard'])]
            for category in categories: proxy[category].append(pair)
            if status in ('NORMAL','CLOSED','DELAYED_ARRIVAL','EARLY_DISMISSAL'):
                proxy_exact[key].append(row['recommendation']==status)
                for category in categories: proxy_exact[category].append(row['recommendation']==status)
            announcement=record.get('announced_at') or record.get('announced_by')
            if announcement and datetime.fromisoformat(announcement)<=datetime.fromisoformat(row['as_of']): before.add((name,row['day']))
            disagreements.setdefault(row['day'],set()).add(status)
    return {'impact':{k:binary_metrics(v) for k,v in impact.items()},
            'error_analysis':{k:error_analysis.analyse(v) for k,v in weather.items()},'impact_breakdowns':{k:binary_metrics(v) for k,v in breakdown.items()},
            'proxy':{k:{**binary_metrics(v),'exact_status':{'n':len(proxy_exact[k]),'correct':sum(proxy_exact[k]),'accuracy':sum(proxy_exact[k])/len(proxy_exact[k]) if proxy_exact[k] else None}} for k,v in proxy.items()},
            'proxy_unique_days':len(proxy_days),'proxy_institution_days':len(proxy_evidence),
            'proxy_counts_by_reconstruction':{k:{'institution_days':len(v),'unique_days':len({day for _,day in v})} for k,v in proxy_counts.items()},
            'announcement_time_known':sum(bool(r.get('announced_at')) for r in proxy_evidence.values()),
            'announcement_time_unknown':sum(not r.get('announced_at') for r in proxy_evidence.values()),
            'announcement_before_evaluation':len(before),
            'institution_disagreements':{d:sorted(v) for d,v in disagreements.items() if len(v)>1},
            'coverage':dict(coverage),'excluded':dict(excluded),'n':len(rows),
            'range':{'start':min((r['day'] for r in rows),default=None),'end':max((r['day'] for r in rows),default=None)},
            'mapping':'NORMAL = no operational disruption; every other comparable posture = disruption. Remote learning/partial closures only support broad agreement, not exact status.',
            'limitations':['ASOS local disruption is not closure ground truth. No proxy notice means unknown, not open.',
                           'School calendars and policies differ from this synthetic workplace.',
                           'High ordinary accuracy can reflect many quiet days; use balanced accuracy and missed-impact counts.',
                           'Same-day institutions are correlated; unique-day counts are shown. Wilson intervals do not correct storm clustering.',
                           'Recommendations targeting another workday are excluded from same-day scores, including weekend searches.',
                           'Hazard breakdowns group by the recommendation engine’s highest-scoring hazard (ties use engine ordering).',
                           'No threshold tuning performed; these are descriptive evaluations, not a held-out validation claim.']}


def overview():
    id, rules, config=identity(datetime.now(timezone.utc),'observation')
    with session() as s:
        from sqlalchemy import text
        raw=s.exec(select(HistoricalEvaluation).where(HistoricalEvaluation.rules_sha==rules.sha256,HistoricalEvaluation.config_sha==config).order_by(text('rowid'))).all()
        jobs=[json.loads(j.state_json) for j in s.exec(select(HistoricalBuild)).all()]
    # One most recent attempt per time/type. Never pool different clock times.
    dedup={}
    for r in raw:
        summary=json.loads(r.summary_json)
        dedup[(r.as_of,summary['requested_mode'])]=summary
    rows=list(dedup.values()); groups=defaultdict(list)
    from app.risk_experiment import manifest_path
    cohort=json.loads(manifest_path().read_text()) if manifest_path().exists() else None
    cohort_ids={e['id'] for e in cohort['entries']} if cohort else None
    for r in rows:
        r['proxy_records'] = proxies(r['day'])
        clock=datetime.fromisoformat(r['as_of']).astimezone(ZoneInfo(load_facility().timezone)).strftime('%H:%M')
        # The fixed observation analysis cohort excludes ineligible/new attempts;
        # other clocks and forecast reconstruction remain explicitly separate.
        if cohort_ids is not None and clock=='04:00' and r['requested_mode']=='observation' and r['id'] not in cohort_ids:
            continue
        groups[clock].append(r)
    if cohort:
        retained={r.id:r for r in raw}
        frozen=[]
        with session() as s:
            for item in cohort['entries']:
                ev=retained.get(item['id']) or s.get(HistoricalEvaluation,item['id'])
                if not ev or hashlib.sha256(ev.summary_json.encode()).hexdigest()!=item['summary_sha']:
                    raise ValueError('Frozen analysis cohort evaluation unavailable or changed: '+item['id'])
                v=json.loads(ev.summary_json);v['proxy_records']=proxies(v['day']);frozen.append(v)
        groups['04:00']=[r for r in groups['04:00'] if r['requested_mode']!='observation']+frozen
    sources=list(archive_dir().glob('*.gz')) if archive_dir().exists() else []
    artifact_bytes=0
    with session() as s:
        from sqlalchemy import func
        artifact_bytes=s.exec(select(func.sum(func.length(HistoricalArtifact.payload)))).one() or 0
    from app.decision_evidence import describe
    decision_dataset = describe(proxies(include_unconfirmed=True))
    return {'analysis_cohort':{k:v for k,v in cohort.items() if k!='entries'} if cohort else None,'archive_evaluation_count':len(rows),'decision_dataset':decision_dataset,'supported_start':START,'supported_end':(datetime.now(ZoneInfo(load_facility().timezone)).date()-timedelta(days=1)).isoformat(),
            'default_start':'2020-01-01','default_time':'04:00','timezone':load_facility().timezone,
            'rules_sha':rules.sha256,'benchmark_sha':hashlib.sha256(dumps(proxies()).encode()).hexdigest(), 'metrics_by_time':{t:metrics(v) for t,v in groups.items()},
            'jobs':sorted(jobs,key=lambda j:j['created_at'],reverse=True), 'proxy_records':proxies(),
            'storage':{'evaluation_count':len(raw),'compressed_source_bytes':sum(p.stat().st_size for p in sources),
                       'compressed_evaluation_bytes':artifact_bytes,'mean_evaluation_bytes':artifact_bytes/max(1,len(raw)),
                       'db_bytes':settings.db_path.stat().st_size if settings.db_path.exists() else 0,
                       'source_years':sorted([p.stem.split('.')[0].split('-')[-1] for p in sources])},
            'latest_disruptive_days':sorted([r for r in rows if r['outcome'].get('disruptive')],key=lambda r:r['day'],reverse=True)[:100]}


def job_get(id):
    with session() as s:
        row=s.get(HistoricalBuild,id)
        return json.loads(row.state_json) if row else None


def job_save(state):
    with session() as s:
        row=s.get(HistoricalBuild,state['id']) or HistoricalBuild(id=state['id'],state_json='{}')
        row.state_json=dumps(state); s.add(row); s.commit()


def create_job(start,end,reconstruction='observation',online=False):
    local_instant(start); local_instant(end)
    if start>end: raise HTTPException(422,'Start must precede end')
    with session() as s:
        for row in s.exec(select(HistoricalBuild)).all():
            prior=json.loads(row.state_json)
            if prior['status'] in ('queued','running'):
                raise HTTPException(409,'A build is already active; cancel or resume it before starting another.')
    _,rules,config=identity(local_instant(start),reconstruction)
    state={'id':uuid4().hex,'start':start,'end':end,'mode':reconstruction,'online':online,'next_day':start,
           'rules_sha':rules.sha256,'config_sha':config,
           'status':'queued','processed':0,'failed':[],'created_at':datetime.now(timezone.utc).isoformat(),'seconds':0}
    job_save(state); return state


async def run_job(id):
    import time as timer
    state=job_get(id)
    if not state: return
    _,rules,config=identity(local_instant(state['start']),state['mode'])
    if state.get('rules_sha',rules.sha256)!=rules.sha256 or state.get('config_sha',config)!=config:
        state['status']='interrupted';job_save(state)
        raise HTTPException(409,'Rules or facility configuration changed. Start a new build; prior results are preserved.')
    state['status']='running'; job_save(state)
    year_data=None; year=None; t0=timer.monotonic(); elapsed=state['seconds']
    try:
        day=date.fromisoformat(state['next_day']); end=date.fromisoformat(state['end'])
        while day<=end:
            if job_get(id)['status']=='cancelled': return
            try:
                if year != day.year:
                    year_data=await year_rows(day.year,online=state['online']); year=day.year
                    # Keep adjacent years for boundary completeness without extra per-day downloads.
                    year_data={**year_data,'rows':list(year_data['rows'])}
                    for other in (day.year-1,day.year+1):
                        if other >= int(state['start'][:4])-1 and other <= datetime.now(timezone.utc).year:
                            try: year_data['rows'] += (await year_rows(other,online=state['online']))['rows']
                            except Exception: pass
                    year_data['rows'].sort(key=lambda r:r['utc_valid'])
                    year_data['_times']=[r['utc_valid'] for r in year_data['rows']]
                async with _day_lock:
                    await compute(day.isoformat(),reconstruction=state['mode'],online=state['online'],prefetched=year_data)
            except asyncio.CancelledError: raise
            except Exception as exc:
                state['failed'].append({'day':day.isoformat(),'reason':type(exc).__name__})
                if year != day.year:
                    # A failed year download should not hammer the source for each date.
                    last=min(end,date(day.year,12,31))
                    state['failed'][-1]['through']=last.isoformat(); day=last
            state['processed']+=1; day+=timedelta(days=1); state['next_day']=day.isoformat()
            state['seconds']=elapsed+timer.monotonic()-t0
            job_save(state)
            await asyncio.sleep(.01 if state['mode']=='observation' else .5)
        state['status']='completed_with_gaps' if state['failed'] else 'completed'; job_save(state)
    except asyncio.CancelledError:
        state['status']='interrupted'; state['seconds']=elapsed+timer.monotonic()-t0; job_save(state); raise
    finally: TASKS.pop(id,None)


def start_job(id):
    if id not in TASKS: TASKS[id]=asyncio.create_task(run_job(id))


def recover_jobs():
    with session() as s:
        states=[json.loads(r.state_json) for r in s.exec(select(HistoricalBuild)).all()]
    for state in states:
        if state['status'] in ('running','queued'):
            state['status']='interrupted'; job_save(state)
