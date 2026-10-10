from datetime import UTC, datetime

from backend.app.models import DecisionRecord, DecisionRecordPayload, HumanAction
from backend.app.records.chain import build_record, verify_chain


def payload(identifier: str) -> DecisionRecordPayload:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return DecisionRecordPayload(
        id=identifier,
        facility_id="facility",
        created_at=now,
        observed_at=now,
        fetched_at=now,
        evidence_snapshot=[],
        engine_version="git:test",
        registry_version="sha256:test",
        recommendation={"posture": "NORMAL"},
        human_action=HumanAction.APPROVED,
        actor="Test Manager",
        decided_at=now,
        notification_package={"id": "package"},
    )


def test_chain_verifies_and_detects_tampering():
    first = build_record(payload("one"))
    second = build_record(payload("two"), first)
    assert verify_chain([first, second]).intact
    tampered = DecisionRecord.model_validate(
        {**second.model_dump(), "recommendation": {"posture": "CLOSED"}}
    )
    result = verify_chain([first, tampered])
    assert not result.intact
    assert result.broken_at == 2


def test_override_requires_reason():
    values = payload("override").model_dump()
    values["human_action"] = HumanAction.OVERRIDDEN
    try:
        DecisionRecordPayload.model_validate(values)
    except ValueError as exc:
        assert "reason" in str(exc)
    else:
        raise AssertionError("override without a reason was accepted")
