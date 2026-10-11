import assert from "node:assert/strict";
import test from "node:test";
import { evidenceState, evidenceWarning, normalIsFallback } from "../src/evidence.ts";

const base = { mode: "live", as_of: "2026-01-13T09:00:00Z", posture: { posture: "NORMAL" } };
const insufficient = { status: "insufficient", headline: "Insufficient current data", reasons: ["No usable forecast"], missing_sources: ["NWS gridded forecast"],
  stale_sources: [], checks: [], supports_all_clear: false, reason_required: true, hazard_evidence: [], forecast_coverage: null };

test("older snapshots without the field are 'not recorded', never sufficient", () => {
  const s = evidenceState({ ...base, sufficiency: undefined });
  assert.equal(s.status, "not_recorded");
  assert.equal(s.supports_all_clear, false);
  assert.equal(s.reason_required, true);
  assert.equal(evidenceWarning(s), true);
  assert.equal(normalIsFallback({ ...base, sufficiency: null }), true);
});

test("insufficient evidence makes NORMAL a fallback, not an all-clear", () => {
  assert.equal(normalIsFallback({ ...base, sufficiency: insufficient }), true);
  assert.equal(normalIsFallback({ ...base, posture: { posture: "CLOSED" }, sufficiency: insufficient }), false);
});

test("a supported NORMAL is an all-clear", () => {
  const ok = { ...insufficient, status: "sufficient", supports_all_clear: true, reason_required: false, reasons: [] };
  assert.equal(normalIsFallback({ ...base, sufficiency: ok }), false);
  assert.equal(evidenceWarning(ok), false);
});

test("a usable backup supports a provisional NORMAL while an incomplete backup remains insufficient", () => {
  const backup = { ...insufficient, provisional: true, status: "limited", forecast_sources: ["Archived GFS MOS"], reason_required: true };
  assert.equal(normalIsFallback({ ...base, sufficiency: backup }), false);
  assert.equal(evidenceState({ ...base, sufficiency: backup }).supports_all_clear, false);
  assert.equal(normalIsFallback({ ...base, sufficiency: { ...backup, status: "insufficient" } }), true);
});
