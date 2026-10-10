from __future__ import annotations

import hashlib
import json

from backend.app.models import ChainVerification, DecisionRecord, DecisionRecordPayload

GENESIS_HASH = "0" * 64


def canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def calculate_hash(payload: DecisionRecordPayload, prev_hash: str) -> str:
    material = canonical_json(payload.model_dump(mode="json")) + prev_hash
    return hashlib.sha256(material.encode()).hexdigest()


def build_record(
    payload: DecisionRecordPayload,
    previous: DecisionRecord | None = None,
) -> DecisionRecord:
    prev_hash = previous.hash if previous else GENESIS_HASH
    sequence = previous.sequence + 1 if previous else 1
    return DecisionRecord(
        **payload.model_dump(),
        sequence=sequence,
        prev_hash=prev_hash,
        hash=calculate_hash(payload, prev_hash),
    )


def verify_chain(records: list[DecisionRecord]) -> ChainVerification:
    prev_hash = GENESIS_HASH
    for expected_sequence, record in enumerate(records, start=1):
        payload = DecisionRecordPayload.model_validate(
            record.model_dump(exclude={"sequence", "prev_hash", "hash"})
        )
        if record.sequence != expected_sequence or record.prev_hash != prev_hash:
            return ChainVerification(
                intact=False,
                records_checked=expected_sequence - 1,
                broken_at=expected_sequence,
                message="Sequence or previous hash mismatch.",
            )
        if calculate_hash(payload, prev_hash) != record.hash:
            return ChainVerification(
                intact=False,
                records_checked=expected_sequence - 1,
                broken_at=expected_sequence,
                message="Record content hash mismatch; possible tampering detected.",
            )
        prev_hash = record.hash
    return ChainVerification(
        intact=True,
        records_checked=len(records),
        message=f"Chain intact across {len(records)} record(s).",
    )
