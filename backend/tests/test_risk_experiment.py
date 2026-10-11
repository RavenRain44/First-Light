from datetime import date,timedelta
import json
import pytest
from app import risk_experiment as x

def row(day, observed=False, margin=-50):
    return {'id':day,'day':day,'current_prediction':margin is not None and margin>=0,'observed':observed,'margin':margin,'hazard':'cold'}

def sample():
    return [row('2018-01-02',True,5),row('2018-01-03'),row('2020-01-02',True,-50),row('2020-01-03',False,-100),row('2024-01-02',True,-60),row('2024-01-03',False,-100)]

def test_test_outcomes_do_not_select_threshold():
    a=x.evaluate(sample(),[10]);rows=sample();rows[-1]['observed']=True
    b=x.evaluate(rows,[10])
    assert a['scenarios'][0]['selected_offset_pct']==b['scenarios'][0]['selected_offset_pct']
    assert a['scenarios'][0]['test']['confusion']!=b['scenarios'][0]['test']['confusion']

def test_boundary_purge_and_storm_episodes():
    rows=[row((date(2018,12,27)+timedelta(days=i)).isoformat(),True) for i in range(11)]
    groups,purged=x.partition(rows)
    assert len(purged)==11 and not any(groups.values())

def test_unknown_margin_is_not_zero():
    assert x.score([row('2020-01-01',True,None)],-75)['confusion']['missed_disruption']==1

def test_validation_needs_both_classes_and_positive_costs():
    with pytest.raises(ValueError):x.evaluate([row('2020-01-01')])
    with pytest.raises(ValueError):x.evaluate(sample(),[0])

def test_manifest_integrity_rejected_before_read():
    with pytest.raises(ValueError,match='integrity'):x.load_rows({'cohort_sha':'bad','entries':[]})

def test_existing_manifest_never_reselected(tmp_path,monkeypatch):
    monkeypatch.setattr(x,'manifest_path',lambda:tmp_path/'manifest.json')
    m={'entries':[{'id':'original'}],'version':'frozen'}
    (tmp_path/'manifest.json').write_text(json.dumps(m))
    assert x.freeze()==m

def test_overview_keeps_original_cohort_after_new_attempt(tmp_path,monkeypatch):
    import hashlib
    from app import db,historical as h
    from app.config import settings
    from app.models import HistoricalEvaluation
    monkeypatch.setattr(settings,'db_path',tmp_path/'test.db')
    old=db._engine;engine=db.make_engine(f'sqlite:///{tmp_path / "test.db"}');db.set_engine(engine)
    try:
        _,rules,config=h.identity(h.local_instant('2024-01-02'),'observation')
        v={'id':'original','day':'2024-01-02','as_of':'2024-01-02T10:00:00+00:00','requested_mode':'observation','reconstruction':'observation-based reconstruction','decision_day':'2024-01-02','selection_gradable':True,'recommendation':'NORMAL','hazard':'cold','outcome':{'gradable':True,'disruptive':False},'rule_margin_pct':0}
        original=json.dumps(v)
        with db.session() as s:
            for id,text in [('original',original),('new-attempt',json.dumps({**v,'id':'new-attempt','recommendation':'CLOSED'}))]:
                s.add(HistoricalEvaluation(id=id,day=v['day'],as_of=v['as_of'],rules_sha=rules.sha256,config_sha=config,reconstruction=v['reconstruction'],status='partial',summary_json=text));s.commit()
        p=x.manifest_path();p.parent.mkdir(parents=True)
        p.write_text(json.dumps({'n':1,'entries':[{'id':'original','day':v['day'],'summary_sha':hashlib.sha256(original.encode()).hexdigest()}]}))
        result=h.overview()['metrics_by_time']['04:00']['impact'][v['reconstruction']]
        assert result['n']==1 and result['confusion']['true_negative']==1 and result['confusion']['false_alarm']==0
    finally:
        db.set_engine(old);engine.dispose()
