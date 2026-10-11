import pytest
from fastapi import BackgroundTasks, HTTPException
from app.config import settings
from app.routers import core

@pytest.mark.parametrize('mode', ['replay', 'backtest', 'livecheck'])
def test_non_live_context_cannot_record_production_decision(monkeypatch, mode):
    monkeypatch.setattr(settings, 'demo_mode', False)
    monkeypatch.setattr(core.snapshots, 'get', lambda sid: {'mode': mode})
    with pytest.raises(HTTPException) as error:
        core.record_decision(core.DecisionIn(snapshot_id='historical', decided_by='Manager', decision_posture='CLOSED'), BackgroundTasks())
    assert error.value.status_code == 422
