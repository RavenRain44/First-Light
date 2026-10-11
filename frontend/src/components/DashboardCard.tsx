import { useEffect, useId, useState } from "react";
import { api } from "../api";
import { ACTIONS, joinReasons, relevantMetrics, suggestionReasons, supportingRules } from "../dashboard";
import type { Snapshot, Timeseries } from "../types";
import { Badge, CooperBanner, PostureBadge, Skeleton, ago, fmtClock, fmtDayLong, fmtTime } from "../util";
import { PanelBoundary } from "./ErrorBoundary";
import { MetricChart } from "./MetricChart";

// One timeseries request per snapshot, shared by Relevant Metrics and the Forecast charts section.
const tsCache = new Map<string, Promise<Timeseries>>();
export function useTimeseries(snap: Snapshot, enabled: boolean): { data: Timeseries | null; error: string | null } {
  const id = snap.snapshot_id;
  const [state, setState] = useState<{ id: string; data: Timeseries | null; error: string | null } | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    if (!tsCache.has(id)) tsCache.set(id, api.timeseries(id).catch((e) => { tsCache.delete(id); throw e; }));
    tsCache.get(id)!.then((data) => alive && setState({ id, data, error: null }))
      .catch((e: Error) => alive && setState({ id, data: null, error: e.message }));
    return () => { alive = false; };
  }, [id, enabled]);
  return state?.id === id ? { data: state.data, error: state.error } : { data: null, error: null };
}

/** The top of Today: Cooper risk, the suggested action in one sentence, and the way to act on it.
 *  Nothing is recorded or sent from here; the button only opens Notify staff. */
export function SuggestedAction({ snap, busy, onRefresh, onRegenerate, onGoNotify }: {
  snap: Snapshot; busy: boolean; onRefresh?: () => void; onRegenerate?: () => void; onGoNotify: () => void;
}) {
  const id = useId();
  const tz = snap.facility.timezone;
  const r = snap.readiness;
  const pending = snap.ai_addon?.status === "pending";
  const provider = pending ? "Akamai brief in progress" : snap.model_id.startsWith("akamai:") ? "Powered by Akamai"
    : snap.model_id.startsWith("bedrock:") ? "AWS fallback" : snap.model_id === "deterministic-fallback" ? "Template suggestion" : "Archived AI brief";
  const unavailable = snap.sources.filter((s) => s.status === "unavailable");
  const people = snap.roster && !snap.roster.hypothetical ? snap.roster.expected_in_building : undefined;
  const canDecide = snap.mode !== "backtest" && !snap.facility.hypothetical;

  return (
    <article className="card overflow-hidden" aria-labelledby={`${id}-action`}>
      <CooperBanner r={r} />
      <section className="p-5 sm:p-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id={`${id}-action`} className="text-2xl font-semibold tracking-tight">Suggested Action</h2>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={snap.model_id.startsWith("bedrock:") ? "warn" : pending ? "neutral" : "info"}>{provider}</Badge>
            {onRegenerate && <button onClick={onRegenerate} disabled={pending} className="btn min-h-11 !px-2 !text-xs"
              title="Ask Akamai to rewrite the suggestion from the same recorded evidence. Use Check again for fresh weather.">
              <span aria-hidden className={pending ? "inline-block animate-spin" : ""}>↻</span> {pending ? "Updating…" : "Regenerate"}
            </button>}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="text-sm font-medium text-ink2">{fmtDayLong(snap.posture.decision_day)}</span>
          <PostureBadge p={snap.posture.posture} size="lg" />
          {r?.decide_by && (
            <span className={`text-lg font-semibold ${r.deadline_passed ? "text-[var(--danger)]" : ""}`}>
              {r.deadline_passed ? "Deadline passed: decide now" : `Decide by ${fmtClock(r.decide_by, tz)}`}
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-muted">OPM status: {snap.posture.opm_label}</p>

        <p key={`${snap.snapshot_id}-${snap.model_id}`} className="cc-fade mt-5 text-xl leading-relaxed sm:text-2xl" data-testid="suggested-action">
          {suggestionSentence(snap)}
        </p>

        {snap.posture.guidance.length > 0 && (
          <div role="alert" className="mt-4 rounded-xl border-l-4 border-[var(--danger)] bg-[var(--surface-2)] px-4 py-2.5 font-medium">
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
        {(snap.ai_addon?.status === "failed" || (snap.ai.validation && !snap.ai.validation.ok)) &&
          <p role="status" className="mt-3 text-xs text-ink2">Akamai's wording could not be verified. The suggestion uses the recorded rules and evidence.</p>}
        {snap.ai_addon?.regen_failed && <p role="status" className="mt-3 text-xs text-ink2">The new Akamai brief could not be verified. The previous brief is still shown.</p>}
        {unavailable.length > 0 && <p className="mt-3 text-sm text-ink2">Some data could not be loaded ({unavailable.map((s) => s.label).join(", ")}). Missing data does not mean conditions are safe.</p>}

        {canDecide ? (
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button onClick={onGoNotify} className="btn btn-primary min-h-11 px-5 text-base">Confirm decision &amp; notify staff <span aria-hidden>→</span></button>
            <span className="text-xs text-muted">You make the final decision. Nothing is sent until you approve the alerts.</span>
          </div>
        ) : (
          <p className="mt-6 text-sm text-ink2">{snap.facility.hypothetical ? "This is a what-if check" : "This is a replay of a past storm"}, so no decision is recorded and no one is alerted.</p>
        )}
      </section>
    </article>
  );
}

/** Charts of the evidence behind the suggestion. Only shown when a weather rule is triggered;
 *  on a calm day the charts stay in the collapsible Forecast charts section. */
export function RelevantMetrics({ snap }: { snap: Snapshot }) {
  const id = useId();
  const active = supportingRules(snap).length > 0;
  const { data, error } = useTimeseries(snap, active);
  if (!active) return null;
  const metrics = data ? relevantMetrics(snap, data) : [];
  return (
    <section className="card p-5 sm:p-8" aria-labelledby={`${id}-metrics`}>
      <h2 id={`${id}-metrics`} className="text-lg font-semibold">Relevant Metrics</h2>
      <p className="mt-1 text-sm text-ink2">Highlighted periods and points show the evidence behind the suggestion.</p>
      {error ? <p role="status" className="mt-4 rounded-lg bg-[var(--surface-2)] p-4 text-sm">Chart data could not be loaded. The suggestion and the decision steps are still available.</p>
        : !data ? <div className="mt-4 space-y-4" aria-label="Loading relevant metrics"><Skeleton className="h-60" /><Skeleton className="h-40" /></div>
        : <div className="mt-4 space-y-4">{metrics.map((metric, index) =>
          <PanelBoundary key={metric.id} name={metric.title}><MetricChart snap={snap} metric={metric} data={data} compact={index > 0} /></PanelBoundary>
        )}</div>}
    </section>
  );
}

/** "Due to <reasons>, <action>." The same sentence on Today and on Notify staff. */
export function suggestionSentence(snap: Snapshot) {
  return <>Due to {joinReasons(suggestionReasons(snap))}, <strong className="font-semibold">{ACTIONS[snap.posture.posture]}</strong>.</>;
}
