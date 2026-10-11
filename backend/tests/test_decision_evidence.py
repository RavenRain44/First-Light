from app.decision_evidence import eligible, describe
from app import historical

def test_default_dataset_excludes_uncertain_office_records():
    accepted = historical.proxies()
    assert {(r['day'],r['status']) for r in accepted} == {('2019-01-30','CLOSED'),('2019-01-31','DELAYED_ARRIVAL')}
    evidence = describe(historical.proxies(include_unconfirmed=True))
    assert evidence['institution_days']==2 and len(evidence['excluded_records'])==3
    assert evidence['confidence_probability'] is None

def test_weather_or_unsupported_number_is_not_decision_evidence():
    assert not eligible({'cause':'weather','verification':'official','status':'CLOSED','confidence':.99})
    r=historical.proxies()[0]
    assert not eligible({**r,'decision_evidence':{**r['decision_evidence'],'scope':'classes'}})
    assert not eligible({**r,'corroborating_source_url':None})

def test_ai_backtest_sample_excludes_unknown_decisions(monkeypatch):
    import json
    from contextlib import contextmanager
    from types import SimpleNamespace
    from scripts import backtest_ai
    rows = [SimpleNamespace(summary_json=json.dumps({'day':day,'requested_mode':'observation','recommendation':status})) for day,status in [('2019-01-30','CLOSED'),('2024-01-12','CLOSED'),('2024-06-03','NORMAL')]]
    @contextmanager
    def fake_session():
        yield SimpleNamespace(exec=lambda query: SimpleNamespace(all=lambda: rows))
    monkeypatch.setattr(backtest_ai,'session',fake_session)
    monkeypatch.setattr(backtest_ai.historical,'proxies',lambda:[{'day':'2019-01-30'}])
    result=backtest_ai.sample(100,'observation',7)
    assert [r['day'] for r in result]==['2019-01-30']
