import { EvidenceNotice } from "./EvidenceNotice";
import { evidenceState, normalIsFallback } from "../evidence";
import { useEffect, useId, useState, type ReactNode } from "react";
import { api } from "../api";
import { ACTIONS, METRICS, joinReasons, relevantMetrics, suggestionReasons, supportingRules } from "../dashboard";
import { cooperPresentation, forecastOverview, type ForecastValue } from "../cooper";
import type { Snapshot, Timeseries } from "../types";
import { Badge, PostureBadge, READINESS, Skeleton, ago, fmtDayLong, fmtTime } from "../util";
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

/** The top of Today: Cooper condition, grounded weather, and the manager's next step.
 *  Nothing is recorded or sent from here; the button only opens Notify staff. */
export function SuggestedAction({ snap, busy, onRefresh, onRegenerate, onGoNotify, readOnly = false }: {
  snap: Snapshot; busy: boolean; onRefresh?: () => void; onRegenerate?: () => void; onGoNotify: () => void; readOnly?: boolean;
}) {
  const id = useId();
  const tz = snap.facility.timezone;
  const r = snap.readiness;
  const presentation = cooperPresentation(snap);
  const condition = READINESS.find((c) => c.level === presentation.level);
  const pending = snap.ai_addon?.status === "pending";
  const provider = pending ? "AI brief in progress" : snap.model_id.startsWith("akamai:") ? "Powered by Akamai"
    : snap.model_id.startsWith("strands:") ? "Strands fallback" : snap.model_id === "deterministic-fallback" ? "Template suggestion" : "Archived AI brief";
  const unavailable = snap.sources.filter((s) => s.status === "unavailable");
  const people = snap.roster && !snap.roster.hypothetical ? snap.roster.expected_in_building : undefined;
  const canDecide = !readOnly && snap.mode !== "backtest" && !snap.facility.hypothetical;
  const evidence = evidenceState(snap);

  return (
    <article className="card min-w-0 overflow-hidden" aria-labelledby={`${id}-action`} data-testid="cooper-dashboard" data-condition={presentation.level ?? "UNKNOWN"}>
      <header className="px-5 py-5 sm:px-8 sm:py-6" aria-live="polite" aria-atomic="true"
        style={{ background: condition?.color ?? "var(--surface-2)", color: presentation.level === "RED" ? "#fff" : condition ? "#1f2937" : "var(--text-primary)" }}>
        <p className="text-xs font-semibold uppercase tracking-wider">{condition ? `Condition ${condition.label}` : "Condition unavailable"} · Colonel Cooper readiness</p>
        <h2 id={`${id}-action`} className="mt-2 text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">{presentation.title}</h2>
        {presentation.urgencyExplanation && <p className="mt-2 text-sm" data-testid="readiness-urgency">{presentation.urgencyExplanation}</p>}
        {presentation.level === "WHITE" && <p className="mt-2 text-sm">Keep routine monitoring; review again when the forecast changes.</p>}
        {snap.historical_context && <p className="mt-2 text-sm">Historical rating uses supplied inputs only; missing forecasts and alerts remain unknown.</p>}
      </header>
      <section className="p-5 sm:p-8">
        {!evidence.supports_all_clear || evidence.status !== "sufficient" || snap.mode !== "live"
          ? <div className="mb-5"><EvidenceNotice snap={snap} onRefresh={onRefresh} busy={busy} /></div> : null}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-4 text-sm sm:grid-cols-4" data-testid="dashboard-metadata">
          <div><dt className="text-xs text-muted">Confidence</dt><dd className="mt-1 font-semibold capitalize">{snap.confidence.level}</dd></div>
          <div><dt className="text-xs text-muted">People expected</dt><dd className="mt-1 font-semibold">{people ?? "Unavailable"}</dd></div>
          <div><dt className="text-xs text-muted">Decision date</dt><dd className="mt-1 font-medium">{fmtDayLong(snap.posture.decision_day)}, {snap.posture.decision_day.slice(0, 4)}</dd></div>
          <div><dt className="text-xs text-muted">{snap.mode === "live" ? "Last updated" : "Weather as of"}</dt>
            <dd className="mt-1 font-medium"><time dateTime={snap.as_of}>{fmtTime(snap.as_of, tz, { date: true, year: true })}</time>
              {snap.mode === "live" && <span className="block text-xs font-normal text-ink2">{ago(snap.as_of)}</span>}
              {onRefresh && <button onClick={onRefresh} disabled={busy} className="mt-1 block min-h-9 text-[var(--accent)] underline underline-offset-2 disabled:opacity-50">{busy ? "Checking…" : "Check again"}</button>}
            </dd>
          </div>
        </dl>
        <hr className="my-5 border-edge" />
        {/* Immediate safety instructions precede operating-status advice. */}
        {snap.posture.guidance.length > 0 && (
          <div role="alert" className="mb-5 rounded-xl border-l-4 border-[var(--danger)] bg-[var(--surface-2)] px-4 py-3 font-medium">
            {snap.posture.guidance.map((g) => <p key={g}>⚠ {g}</p>)}
          </div>
        )}
        {r?.decide_by && <p className={`mb-4 rounded-lg bg-[var(--surface-2)] px-4 py-3 text-base font-semibold ${r.deadline_passed ? "text-[var(--danger)]" : ""}`}>
          {r.deadline_passed ? "Deadline passed — decide now. Announce-by time: " : "Decide and announce by "}{fmtTime(r.decide_by, tz, { date: true, year: true })}
        </p>}
        {presentation.watch && <p className="mb-4 text-lg font-medium leading-relaxed" data-testid="weather-watch">{presentation.watch}</p>}
        {presentation.level === null && <p className="mb-4 text-sm text-ink2">This saved snapshot has no Cooper condition. Review the recorded weather and recommendation before deciding.</p>}
        {presentation.urgent && <>
          <h3 className="text-sm font-semibold underline underline-offset-4">Suggested Action</h3>
          <p key={`${snap.snapshot_id}-${snap.model_id}`} className="cc-fade mt-2 text-xl leading-relaxed sm:text-2xl" data-testid="suggested-action">{suggestionSentence(snap)}</p>
        </>}
        {presentation.reasons.length > 0 && presentation.level !== "WHITE" && <div className="mt-4 text-sm text-ink2">
          <p className="font-semibold text-ink">Why this condition</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">{presentation.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </div>}
        {!presentation.urgent && normalIsFallback(snap) && (
          <p className="mb-2 text-lg font-medium leading-relaxed" data-testid="suggested-action">{suggestionSentence(snap)}</p>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-2 text-sm"><span className="text-ink2">Suggested operating status:</span><PostureBadge p={snap.posture.posture} />
          {normalIsFallback(snap) && <span className="font-semibold text-[var(--danger)]" data-testid="fallback-label">Fallback only, not confirmed by current data</span>}</div>
        <p className="mt-1 text-xs text-muted">OPM status: {snap.posture.opm_label}</p>

        {presentation.action && canDecide && (
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button onClick={onGoNotify} className="btn btn-primary min-h-11 px-5 text-base">{presentation.action} <span aria-hidden>→</span></button>
            <p className="text-xs text-ink2">{snap.mode === "replay" ? "Practice decision for this replay. " : ""}You make the final decision. Nothing is sent until you approve the alerts.</p>
          </div>
        )}
        {!canDecide && <p className="mt-5 text-sm text-ink2">{snap.facility.hypothetical ? "This is a what-if check" : readOnly ? "This is a saved weather review" : "This is a replay of past weather"}, so no decision is recorded and no one is alerted.</p>}
        {(presentation.level === "WHITE" || presentation.level === "YELLOW" || presentation.level === null) && <ForecastSummary key={snap.snapshot_id} snap={snap} />}

        {(snap.ai_addon?.status === "failed" || (snap.ai.validation && !snap.ai.validation.ok)) &&
          <p role="status" className="mt-3 text-xs text-ink2">AI wording could not be verified. The suggestion uses the recorded rules and evidence.</p>}
        {snap.ai_addon?.regen_failed && <p role="status" className="mt-3 text-xs text-ink2">The new AI brief could not be verified. The previous brief is still shown.</p>}
        {unavailable.length > 0 && <p className="mt-3 text-sm text-ink2">Some data could not be loaded ({unavailable.map((s) => s.label).join(", ")}). Missing data does not mean conditions are safe.</p>}

        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-edge pt-4">
          <Badge tone={snap.model_id.startsWith("strands:") ? "warn" : pending ? "neutral" : "info"}>{provider}</Badge>
          {onRegenerate && <button onClick={onRegenerate} disabled={pending} className="btn min-h-11 !px-2 !text-xs"
            title="Rewrite the brief using the same recorded evidence. Use Check again for fresh weather.">
            <span aria-hidden className={pending ? "inline-block animate-spin" : ""}>↻</span> {pending ? "Updating…" : "Regenerate brief"}
          </button>}
        </div>
      </section>
    </article>
  );
}

function ForecastSummary({ snap }: { snap: Snapshot }) {
  const [open, setOpen] = useState(false);
  const { data, error } = useTimeseries(snap, open);
  const f = forecastOverview(snap);
  const tz = snap.facility.timezone;
  const range = (value: ForecastValue, unit: string) => value.min === null || value.max === null ? "Unavailable"
    : value.min === value.max ? `${Math.round(value.min)}${unit}` : `${Math.round(value.min)}–${Math.round(value.max)}${unit}`;
  const metrics = data ? METRICS.filter((m) => m.series.some((s) => data.rows.some((row) => typeof row[s.key] === "number"))
    && (!["ice", "snow"].includes(m.id) || data.rows.some((row) => new Date(row.t).getTime() >= new Date(f.start).getTime()
      && new Date(row.t).getTime() < new Date(f.end).getTime() && Number(row[`fcst_${m.id}_in`]) > 0))) : [];
  const sources = [f.temperature, f.feelsLike, f.wind, f.gust, f.precipitation, f.sky].filter((v) => v.input && v.hours > 0);
  return <section className="mt-5 border-t border-edge pt-5" aria-label="24-hour forecast">
    <h3 className="text-base font-semibold">24-hour forecast</h3>
    <p className="mt-1 text-xs text-ink2">{fmtTime(f.start, tz)} – {fmtTime(f.end, tz)}. Forecast values for this recorded weather time.</p>
    <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
      <ForecastStat label="Temperature" value={f.temperature} text={range(f.temperature, "°F")}>
        {f.feelsLike.min !== null && <p>Feels-like low {Math.round(f.feelsLike.min)}°F{f.feelsLike.hours < 24 ? ` (${f.feelsLike.hours}/24 hours available)` : ""}</p>}
      </ForecastStat>
      <ForecastStat label="Wind" value={f.wind} text={f.wind.max === null ? "Unavailable" : `Up to ${Math.round(f.wind.max)} mph`}>
        <p>{f.gust.max === null ? "Gust forecast unavailable" : `Gusts up to ${Math.round(f.gust.max)} mph${f.gust.hours < 24 ? ` (${f.gust.hours}/24 hours available)` : ""}`}</p>
      </ForecastStat>
      <ForecastStat label="Precipitation chance" value={f.precipitation} text={f.precipitation.max === null ? "Unavailable" : `Up to ${Math.round(f.precipitation.max)}%`} />
    </dl>
    {f.sky.max !== null && <p className="mt-3 text-xs text-ink2">Sky cover: {range(f.sky, "%")}{f.sky.hours < 24 ? ` (${f.sky.hours}/24 hours available)` : ""}.</p>}
    {sources.length > 0 && <details className="mt-2 text-xs text-ink2">
      <summary className="min-h-9 cursor-pointer py-2 underline underline-offset-2">Forecast sources and issue times</summary>
      <ul className="space-y-2 py-2">{sources.map(({ input }) => <li key={input!.id} className="break-words">
        {input!.metric.replace(/_/g, " ")}: {input!.source} · issued {fmtTime(input!.source_time, tz, { date: true, year: true })}
        {input!.source_url.startsWith("https://") && <> · <a href={input!.source_url} target="_blank" rel="noreferrer" className="underline">View source</a></>}
      </li>)}</ul>
    </details>}
    <details className="group mt-3 rounded-xl border border-edge" onToggle={(e) => setOpen(e.currentTarget.open)} data-testid="forecast-charts">
      <summary className="flex min-h-12 cursor-pointer list-none items-center gap-3 px-4 py-3 text-sm font-semibold [&::-webkit-details-marker]:hidden">
        <svg aria-hidden="true" className="h-4 w-4 shrink-0 transition-transform group-open:rotate-180" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 9 6 6 6-6" /></svg>
        View forecast charts
      </summary>
      {open && <div className="space-y-3 border-t border-edge p-3">
        {error ? <p role="status" className="p-3 text-sm text-ink2">Forecast charts could not be loaded. The recorded forecast summary is still available.</p>
          : !data ? <Skeleton className="h-40" />
          : !metrics.length ? <p className="p-3 text-sm text-ink2">No chart measurements are available for this snapshot.</p>
          : metrics.map((metric) => <PanelBoundary key={metric.id} name={metric.title}><MetricChart snap={snap} metric={metric} data={data} compact /></PanelBoundary>)}
      </div>}
    </details>
  </section>;
}

function ForecastStat({ label, value, text, children }: {
  label: string; value: ForecastValue; text: string; children?: ReactNode;
}) {
  return <div className="min-w-0 rounded-lg bg-[var(--surface-2)] p-3">
    <dt className="text-xs text-ink2">{label}</dt><dd className="mt-1 text-lg font-semibold tabnum">{text}</dd>
    <dd className="mt-1 text-xs text-ink2">{children}{value.hours > 0 && value.hours < 24 && <p>{value.hours}/24 forecast hours available</p>}</dd>
  </div>;
}

/** Elevated conditions put their evidence up front, even when the suggested posture is NORMAL. */
export function RelevantMetrics({ snap }: { snap: Snapshot }) {
  const id = useId();
  const presentation = cooperPresentation(snap);
  const active = presentation.urgent || (presentation.level === null && supportingRules(snap).length > 0);
  const { data, error } = useTimeseries(snap, active);
  if (!active) return null;
  const metrics = data ? relevantMetrics(snap, data) : [];
  return (
    <section className="card p-5 sm:p-8" aria-labelledby={`${id}-metrics`}>
      <h2 id={`${id}-metrics`} className="text-lg font-semibold">Concerning weather data</h2>
      <p className="mt-1 text-sm text-ink2">Highlighted periods and points show the evidence behind the suggestion.</p>
      {error ? <p role="status" className="mt-4 rounded-lg bg-[var(--surface-2)] p-4 text-sm">Chart data could not be loaded. The suggestion and the decision steps are still available.</p>
        : !data ? <div className="mt-4 space-y-4" aria-label="Loading relevant metrics"><Skeleton className="h-60" /><Skeleton className="h-40" /></div>
        : <div className="mt-4 space-y-4">{metrics.map((metric, index) =>
          <PanelBoundary key={metric.id} name={metric.title}><MetricChart snap={snap} metric={metric} data={data} compact={index > 0} /></PanelBoundary>
        )}</div>}
    </section>
  );
}

/** "Due to <reasons>, <action>." The same sentence on Today and on Notify staff. Never an all-clear
 *  when the evidence is insufficient: NORMAL is then only the rules' fallback. */
export function suggestionSentence(snap: Snapshot) {
  if (normalIsFallback(snap)) {
    return <>Current data is insufficient to confirm conditions. <strong className="font-semibold">Normal is only the fallback</strong>: recheck for current data, or record a manual decision with your reason.</>;
  }
  return <>Due to {joinReasons(suggestionReasons(snap))}, <strong className="font-semibold">{ACTIONS[snap.posture.posture]}</strong>.</>;
}
