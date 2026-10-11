import type { Snapshot } from "../types";
import { CooperBanner, PostureBadge, ago, fmtClock, fmtDayLong, fmtTime } from "../util";

/** The one card everyone reads: the risk (Cooper color), what is suggested, by when, and why.
 *  It only informs; deciding and alerting staff happen on the Notify staff page. */
export function StatusCard({ snap, busy, onRefresh }: { snap: Snapshot; busy: boolean; onRefresh?: () => void }) {
  const tz = snap.facility.timezone;
  const r = snap.readiness;
  const unavailable = snap.sources.filter((s) => s.status === "unavailable");
  const people = snap.roster && !snap.roster.hypothetical ? snap.roster.expected_in_building : undefined;

  return (
    <section className="card overflow-hidden" aria-label="Today's suggestion">
      <CooperBanner r={r} />
      <div className="p-5 sm:p-7">
        <p className="text-sm font-medium text-ink2">Suggested for {fmtDayLong(snap.posture.decision_day)}</p>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          <PostureBadge p={snap.posture.posture} size="lg" />
          {r?.decide_by && (
            <span className={`text-lg font-semibold ${r.deadline_passed ? "text-[var(--danger)]" : ""}`}>
              {r.deadline_passed ? "Deadline passed: decide now" : `Decide by ${fmtClock(r.decide_by, tz)}`}
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-muted">OPM status: {snap.posture.opm_label}</p>

        <p key={`${snap.snapshot_id}-${snap.model_id}`} className="cc-fade mt-4 max-w-3xl text-lg leading-relaxed">{plainWhy(snap)}</p>

        {snap.posture.guidance.length > 0 && (
          <div role="alert" className="mt-3 rounded-xl border-l-4 border-[var(--danger)] bg-[var(--surface-2)] px-4 py-2.5 font-medium">
            {snap.posture.guidance.map((g) => <p key={g}>⚠ {g}</p>)}
          </div>
        )}

        <ul className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-sm text-ink2">
          <li><span className="font-semibold capitalize text-ink">{snap.confidence.level}</span> confidence</li>
          {people !== undefined && <li><span className="font-semibold text-ink">{people}</span> people expected in the building</li>}
          <li>
            {snap.mode === "live" ? <>Updated {ago(snap.as_of)}</> : <>As of {fmtTime(snap.as_of, tz)}</>}
            {onRefresh && <> · <button onClick={onRefresh} disabled={busy} className="text-[var(--accent)] underline-offset-2 hover:underline disabled:opacity-50">{busy ? "Checking…" : "Check again"}</button></>}
          </li>
        </ul>
        {snap.confidence.level === "low" && (
          <p className="mt-2 text-sm text-ink2">Confidence is low: {[...snap.confidence.factors].sort((a, b) => a.score - b.score)[0]?.explanation}</p>
        )}
        {unavailable.length > 0 && (
          <p className="mt-2 text-sm text-ink2">Some data could not be loaded ({unavailable.map((s) => s.label).join(", ")}). Missing data does not mean conditions are safe.</p>
        )}
        <p className="mt-4 text-xs text-muted">This is a suggestion; you make the final decision. When you are ready, confirm it and alert staff on the Notify staff page.</p>
      </div>
    </section>
  );
}

/** The first sentence of the brief that says something the status badge doesn't. */
export function plainWhy(snap: Snapshot): string {
  // A sentence ends at . ! or ? followed by a capitalised word or the end, so "(incl. 1 h)" stays whole.
  const sentences = (snap.ai.summary ?? "").split(/(?<=[.!?])\s+(?=[A-Z])/).map((x) => x.trim()).filter(Boolean);
  const restates = (x: string) => /^\S.*\b(is|are) recommended\.?$/i.test(x) || x === snap.ai.headline;
  const quiet = !snap.rules.some((r) => r.triggered) && !snap.posture.guidance.length;
  // Rule summaries end in engine shorthand ("... -> CLOSED"); the badge already says that.
  const tidy = (x: string) => x.replace(/\s*->\s*[A-Z_]+\.?$/, ".");
  const first = sentences.find((x) => !restates(x) && !/no hazard thresholds? (were |are )?crossed/i.test(x));
  if (first) return tidy(first);
  if (quiet) return "No weather threats are expected for the work day.";
  return tidy(snap.posture.reasons[0] ?? snap.ai.headline);
}
