import type { Snapshot, Sufficiency } from "./types";

/** The recorded evidence sufficiency, or an explicit "not recorded" state for older snapshots (never sufficient). */
export function evidenceState(snap: Pick<Snapshot, "sufficiency" | "mode" | "as_of">): Sufficiency {
  return snap.sufficiency ?? {
    status: "not_recorded", headline: "Evidence sufficiency was not recorded for this snapshot",
    reasons: ["Saved before evidence sufficiency was tracked. It is not assumed to be sufficient."],
    missing_sources: [], stale_sources: [], checks: [], supports_all_clear: false, reason_required: true,
    hazard_evidence: [], forecast_coverage: null, mode: snap.mode, evaluated_as_of: snap.as_of, policy_version: null,
  };
}

/** True when a NORMAL suggestion must not be read as a supported all-clear. */
export const normalIsFallback = (snap: Pick<Snapshot, "sufficiency" | "mode" | "as_of" | "posture">) =>
  snap.posture.posture === "NORMAL" && !evidenceState(snap).supports_all_clear
  && !(evidenceState(snap).provisional && evidenceState(snap).status === "limited");

/** Prominent warning needed: the assessment cannot be relied on as it stands. */
export const evidenceWarning = (s: Sufficiency) => s.status === "insufficient" || s.status === "not_recorded";
