"""Seed clearly labelled example manager decisions on the historical storms, for Past decisions.

Run from backend/:  python -m scripts.seed_example_decisions     (idempotent; needs build_history first)

For each event in the history library this evaluates a replay snapshot at 04:00 local on the impact
day (only data available then; works offline from the committed cache), records an "Example manager"
decision on it tagged DecisionContext(example=True), and adds a review: some written as a manager
would, some graded from what the storm actually did. One is left unreviewed so the automatic AI
review can be seen. Examples are always shown with an "example" tag in the app.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

from sqlmodel import select

from adapters import cache
from app import past_decisions, snapshots
from app.db import session
from app.facility import load_facility
from app.models import Decision, DecisionContext, HistoryEvent, Snapshot

WHO = "Example manager"
# event -> (decision: None = follow the suggestion, override reason, review: None = weather check, "skip" = leave unreviewed)
EXAMPLES: dict[str, tuple[str | None, str | None, tuple[str, str] | str | None]] = {
    "derecho-2020-08-10": (None, None, None),
    "wind-2021-12-15": (None, None, ("good_call", "Released staff early afternoon, before the gust front. No one was on the road at the peak.")),
    "blizzard-2022-12-22": (None, None, None),
    "ice-2023-02-22": (None, None, ("good_call", "Closing was right: the ramp and parking lot stayed glazed until noon.")),
    "snow-2024-01-09": ("DELAYED_ARRIVAL", "Plows were expected to clear US 30 by 9 AM.",
                        ("too_lenient", "Roads stayed completely covered and several staff could not get in. Telework would have been better.")),
    "advisory-2025-02-05": ("NORMAL", "Advisory only; the city treated roads overnight.", None),
    "blizzard-2025-03-05": (None, None, "skip"),
}


async def main() -> None:
    f = load_facility()
    with session() as s:
        events = {e.id: e for e in s.exec(select(HistoryEvent)).all()}
        seeded = {snap_event for snap_event, in s.exec(
            select(Snapshot.event_id).join(Decision, Decision.snapshot_id == Snapshot.snapshot_id)
            .join(DecisionContext, DecisionContext.decision_id == Decision.id).where(DecisionContext.example == True)).all()}  # noqa: E712
    if not events:
        raise SystemExit("No history events; run `npm run build:history` first.")
    for event_id, (choice, reason, review) in EXAMPLES.items():
        e = events.get(event_id)
        if not e or event_id in seeded:
            print(f"{event_id}: {'already seeded' if e else 'not in history library'}")
            continue
        as_of = datetime.fromisoformat(json.loads(e.backtest_json)["at_0400_local"]["as_of"])
        snap = await snapshots.evaluate(f, as_of, "replay", event_id=event_id, use_ai=False)
        rec = snap["posture"]["posture"]
        chose = choice or rec
        with session() as s:
            d = Decision(snapshot_id=snap["snapshot_id"], facility_id=f.id, decided_by=WHO, decision_posture=chose,
                         recommended_posture=rec, agreed_with_recommendation=chose == rec,
                         override_reason=reason if chose != rec else None, decided_at=as_of)
            s.add(d); s.commit(); s.refresh(d)
            s.add(DecisionContext(decision_id=d.id, example=True)); s.commit()
            did = d.id
        if isinstance(review, tuple):
            past_decisions.add_manager_review(did, WHO, review[0], review[1], now=as_of)
            how = f"manager: {review[0]}"
        elif review is None:
            r = await past_decisions.run_review(did)
            how = f"{r['source']}: {r['verdict']} ({r['confidence']})"
        else:
            how = "left unreviewed (automatic AI review)"
        print(f"{event_id}: suggested {rec}, chose {chose}; {how}")
    await cache.aclose()


if __name__ == "__main__":
    asyncio.run(main())
