"""Frozen observation cohort and chronological, read-only margin-risk experiment.

No thresholds, labels, decisions, artifacts or notifications are modified.
"""
from __future__ import annotations
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlmodel import select
from app.config import settings
from app.db import session
from app.models import HistoricalEvaluation
from engine import error_analysis as e

VERSION = 'ames-7470-v1'
RATIOS = (1, 5, 10, 20, 50)

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def cohort_version(facility_id=None):
    from app.facility import load_facility
    site = load_facility(facility_id)
    return VERSION if site.id == 'IA-AMES-SC' else f'{site.id.lower()}-observations-v1'

def manifest_path(facility_id=None): return settings.db_path.parent/'cohorts'/f'{cohort_version(facility_id)}.json'
def report_path(facility_id=None): return settings.db_path.parent/'analysis'/f'{cohort_version(facility_id)}-risk.json'

def freeze(facility_id=None):
    from app import historical as h
    facility=h.load_facility(facility_id)
    path=manifest_path() if facility.id=="IA-AMES-SC" else manifest_path(facility.id)
    if path.exists(): return json.loads(path.read_text())
    _,rules,config=h.identity(h.local_instant('2020-01-02',facility_id=facility.id),'observation',facility.id)
    with session() as s:
        from sqlalchemy import text
        rows=s.exec(select(HistoricalEvaluation).where(HistoricalEvaluation.rules_sha==rules.sha256,HistoricalEvaluation.config_sha==config).order_by(text('rowid'))).all()
    latest={}
    for r in rows:
        v=json.loads(r.summary_json)
        if v['requested_mode']=='observation' and datetime.fromisoformat(v['as_of']).astimezone(ZoneInfo(facility.timezone)).strftime('%H:%M')=='04:00': latest[v['day']]=(r,v)
    entries=[];excluded={}
    for day,(r,v) in sorted(latest.items()):
        target=v.get('decision_day')
        if target is None:
            from engine.posture import decision_day
            target=decision_day(datetime.fromisoformat(v['as_of']),facility).isoformat()
        reason=('different decision day' if str(target)!=day else 'incomplete outcome' if not v['outcome']['gradable'] or not v['outcome'].get('outcome_sufficient',True) else 'incomplete inputs' if not v.get('selection_gradable') or not v.get('recommendation') else None)
        if reason: excluded[reason]=excluded.get(reason,0)+1;continue
        entries.append({'id':r.id,'day':day,'artifact_sha':r.artifact_sha,'summary_sha':hashlib.sha256(r.summary_json.encode()).hexdigest()})
    if facility.id == 'IA-AMES-SC' and (len(entries)!=7470 or len({r['day'] for r in entries})!=7470):
        raise ValueError(f'Expected exactly 7470 unique eligible dates; found {len(entries)}. Cohort not silently changed.')
    if not entries:
        raise ValueError('No independent gradable observation evaluations for this facility; build a site-specific cohort first.')
    m={'version':cohort_version(facility.id),'facility_id':facility.id,'station':facility.asos_station,'created_at':datetime.now(timezone.utc).isoformat(),'n':len(entries),'evaluation_time':f'04:00 {facility.timezone}','rules_sha':rules.sha256,'config_sha':config,'excluded':excluded,'entries':entries,'cohort_sha':digest(entries)}
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f: json.dump(m,f,indent=2)
    return m

def load_rows(manifest):
    from app import historical as h
    if manifest['cohort_sha']!=digest(manifest['entries']): raise ValueError('Cohort manifest integrity mismatch')
    out=[]
    with session() as s:
        for item in manifest['entries']:
            r=s.get(HistoricalEvaluation,item['id'])
            if not r or r.artifact_sha!=item['artifact_sha'] or hashlib.sha256(r.summary_json.encode()).hexdigest()!=item['summary_sha']: raise ValueError('Retained cohort evaluation changed or unavailable: '+item['id'])
            v=json.loads(r.summary_json)
            out.append({'id':r.id,'day':v['day'],'current_prediction':v['recommendation']!='NORMAL','observed':v['outcome']['disruptive'],'margin':h.rule_margin(v),'hazard':v['hazard']})
    return out

def partition(rows):
    """Two calendar-day purge on each side; purge disruptive episodes crossing a split."""
    boundaries=[date(2019,1,1),date(2023,1,1)]
    drop={r['day'] for r in rows if any(abs((date.fromisoformat(r['day'])-b).days)<=2 for b in boundaries)}
    episodes=[];run=[]
    for r in rows:
        if r['observed']:
            if run and (date.fromisoformat(r['day'])-date.fromisoformat(run[-1]['day'])).days>1: episodes.append(run);run=[]
            run.append(r)
        elif run: episodes.append(run);run=[]
    if run: episodes.append(run)
    for run in episodes:
        if any(run[0]['day']<b.isoformat()<=run[-1]['day'] for b in boundaries): drop.update(r['day'] for r in run)
    splits={'training':[],'validation':[],'test':[]}
    for r in rows:
        if r['day'] in drop: continue
        splits['training' if r['day']<'2019-01-01' else 'validation' if r['day']<'2023-01-01' else 'test'].append(r)
    return splits,sorted(drop)

def score(rows,offset=None):
    from app.historical import binary_metrics
    pairs=[(r['current_prediction'] if offset is None else r['margin'] is not None and r['margin']>=offset,r['observed']) for r in rows]
    return {**binary_metrics(pairs),'errors':e.rates(pairs), 'range':{'start':rows[0]['day'] if rows else None,'end':rows[-1]['day'] if rows else None}}

def evaluate(rows,ratios=RATIOS):
    splits,purged=partition(rows)
    if not splits['validation'] or len({r['observed'] for r in splits['validation']})<2: raise ValueError('Validation lacks both weather classes; cannot choose a threshold')
    candidates={name:[{'offset_pct':o,**score(part,o)} for o in e.OFFSETS] for name,part in splits.items()}
    scenarios=[]
    for ratio in ratios:
        if not math.isfinite(ratio) or ratio<=0: raise ValueError('Miss-to-false-alarm cost ratios must be positive')
        # This is the only selection step. Test labels never choose the threshold.
        best=min(candidates['validation'],key=lambda p:(e.loss(p,1,ratio),abs(p['offset_pct'])))
        o=best['offset_pct'];test=score(splits['test'],o);base=score(splits['test'])
        scenarios.append({'ratio':ratio,'selected_offset_pct':o,'validation':best,'test':test,'baseline_test':base,
                          'test_loss':e.loss(test,1,ratio),'baseline_test_loss':e.loss(base,1,ratio),
                          'additional_disruptions_caught':test['confusion']['true_positive']-base['confusion']['true_positive'],
                          'additional_false_alarms':test['confusion']['false_alarm']-base['confusion']['false_alarm']})
    return {'method':'Retrospective rule-margin classification sensitivity, not trained AI and not a full operating-engine rerun.',
            'splits':{name:{'baseline':score(part),'candidate_results':candidates[name],'always_normal':score([{**r,'current_prediction':False} for r in part])} for name,part in splits.items()},
            'boundary_excluded_days':purged,'scenarios':scenarios,
            'limitations':['Input observations stop 15 minutes before 04:00; weather later in the day is not a prediction feature.',
                           'No production threshold changes or hazard-definition changes. Margin offset is not a probability.',
                           'Final-test dates were previously inspected for baseline backtesting; this retrospective holdout is not pristine prospective validation.',
                           'Wilson intervals do not correct correlated storm days; annual/hazard breakdowns are descriptive.',
                           'Costs are assumed unitless weights, not injury probabilities, dollars or proven cancellation costs.',
                           'No labeled injury, crash, office-operation or financial outcomes are available for this weather cohort.'],
            'test_positive_count':sum(r['observed'] for r in splits['test']),
            'test_disruption_sample_status':'not enough data for a reliable disruption-recall estimate' if sum(r['observed'] for r in splits['test'])<30 else 'descriptive estimate',
            'breakdowns':{str(x['ratio']):{category:score([r for r in splits['test'] if (r['day'][:4] if category.startswith('year:') else r['hazard'])==category.split(':',1)[1]],x['selected_offset_pct']) for category in sorted({'year:'+r['day'][:4] for r in splits['test']}|{'hazard:'+r['hazard'] for r in splits['test']})} for x in scenarios}}

def run(ratios=RATIOS,facility_id=None):
    m=freeze(facility_id);rows=load_rows(m);report=evaluate(rows,ratios)
    report.update({'cohort_version':m['version'],'facility_id':m.get('facility_id','IA-AMES-SC'),'cohort_sha':m['cohort_sha'],'cohort_n':m['n'],'created_at':datetime.now(timezone.utc).isoformat(),'manifest_path':str(manifest_path(facility_id)),'full_cohort_baseline':score(rows)})
    p=report_path(facility_id);p.parent.mkdir(parents=True,exist_ok=True)
    # Reports are versioned by content; latest is only a read-only UI pointer.
    immutable=p.with_name(p.stem+'-'+digest(report)[:12]+'.json');immutable.write_text(json.dumps(report,indent=2));p.write_text(json.dumps(report,indent=2))
    return report

def saved_report(facility_id=None):
    p=report_path(facility_id)
    return json.loads(p.read_text()) if p.exists() else None
