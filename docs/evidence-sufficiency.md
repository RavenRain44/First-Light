# Evidence sufficiency ("Insufficient current data")

Every assessment carries a deterministic `sufficiency` result (`backend/engine/sufficiency.py`,
policy `evidence-sufficiency-v1`), separate from the operating posture, confidence and Cooper readiness.
It answers one question: is there enough usable, current weather evidence to support the assessment?
Missing evidence never chooses a posture. The rules' NORMAL is a fallback, and when evidence is
insufficient the app does not present it as an all-clear.

## Policy

| Evidence | Role | Usable when |
|---|---|---|
| Forecast (live: NWS gridded; replay/backtest: archived NBS) | **Core** | Issued ≤ 12 h before the evaluation time (never after it); covers ≥ 80 % of the decision window (evaluation time → end of the decision day's PM commute; 3-hourly archive values count); live only: retrieved ≤ 3 h before the evaluation time |
| Alert feed (live: NWS; replay: IEM VTEC) | Supporting | Feed responded. "Checked: none in effect" is recorded separately from "unavailable", and never establishes safety by itself |
| Observations (AMW ASOS) | Supporting | Latest observation ≤ 2 h before the evaluation time |
| Iowa DOT roads, RWIS, SPC outlook | Optional | Never required. Road reporting is seasonal and Iowa-only; "not applicable" or empty never blocks an assessment |

- **sufficient**: core forecast plus both kinds of supporting evidence.
- **limited**: core forecast with a supporting gap, or no core forecast but credible positive hazard
  evidence (a hazard at minor or worse whose rule inputs are themselves current). The hazard recommendation
  stands, because missing sources can hide a worse hazard but never a milder one.
- **insufficient**: no usable core forecast and no credible hazard evidence.
- **not_recorded**: snapshots saved before this existed. These are never treated as sufficient.

Stale cache: the HTTP cache keeps each response's original retrieval time, including when a failed retry
falls back to an old copy, so retrying cannot make old evidence look fresh.

Modes: evidence is judged against the snapshot's own evaluation time. In replay and backtest that is the
replayed moment, and archive retrieval dates are ignored. These results are labelled as historical. Demo
mode is labelled as cached live weather.

## Behaviour

- **Dashboard and Notify staff**: an "Insufficient current data" notice (with what is missing or stale, and
  **Check again for current data**). The Cooper heading reads "Insufficient current data" instead of a quiet
  forecast heading. A NORMAL badge is marked "Fallback only, not confirmed by current data", and the
  suggestion sentence replaces "continue normal operations".
- **Readiness**: at least Condition Yellow, with "recheck before relying on a normal day". The posture is
  never changed.
- **Briefs**: the template brief says the data is insufficient and that NORMAL is only the fallback. The AI
  receives the computed state, and its brief is rejected (falling back to the template) unless it says data is
  insufficient or missing and makes no safe or clear claim. The AI never decides adequacy.
- **Decisions** (`POST /api/decisions`): when `reason_required` (insufficient or not recorded), a non-blank
  `override_reason` is required for any posture, including the fallback. The decision is stored with
  `agreed_with_recommendation=false`, and `DecisionContext.evidence_status` / `decision_basis =
  "manual_insufficient_evidence"`. Both are returned by `GET /api/decisions` and `/api/record/{id}`.
- **Storage**: stored in the snapshot (`sufficiency_json`, `sufficiency_status`) and in its content hash. Older
  snapshots without it keep their original hash (`LATER_FIELDS`) and read back as `sufficiency: null`.
