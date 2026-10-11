import { useEffect, useId, useRef, useState } from "react";
import { api } from "../api";
import { ACTIONS, joinReasons, relevantMetrics, suggestionReasons } from "../dashboard";
import type { Snapshot, Timeseries } from "../types";
import { Badge, Skeleton, fmtTime } from "../util";
import { AIPanel, WatchPanel } from "./AIPanel";
import { AlertsPanel } from "./AlertsPanel";
import { DecisionPanel } from "./DecisionPanel";
import { PanelBoundary } from "./ErrorBoundary";
import { AnalogsPanel, RecordTimeline } from "./HistoryPanel";
import { MetricChart } from "./MetricChart";
import { RawDataDrawer } from "./RawDataDrawer";
import { RoadsPanel } from "./RoadsPanel";
import { ThreatPanel } from "./ThreatPanel";
import { TimelinePanel } from "./TimelinePanel";

export function DashboardCard({ snap, recordKey, onRecorded, onNotify, onOpenRecord, onRegenerate, historical = false, savedDecisionId }: {
  snap: Snapshot; recordKey: number; onRecorded: (id: number) => void; onNotify: (id: number) => void;
  historical?: boolean; savedDecisionId?: number | null;
  onOpenRecord: (id: string) => void;
  onRegenerate?: () => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [visited, setVisited] = useState(false);
  const [focusDecision, setFocusDecision] = useState(false);
  const decisionRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<Timeseries | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError(null);
    api.timeseries(snap.snapshot_id, controller.signal).then(setData)
      .catch((e: Error) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [snap.snapshot_id]);
  useEffect(() => {
    if (!open || !focusDecision) return;
    const frame = requestAnimationFrame(() => {
      const target = decisionRef.current;
      target?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start" });
      (target?.querySelector("input") as HTMLInputElement | null)?.focus({ preventScroll: true });
      setFocusDecision(false);
    });
    return () => cancelAnimationFrame(frame);
  }, [open, focusDecision]);
  const showDecision = () => { setVisited(true); setOpen(true); setFocusDecision(true); };
  const pending = snap.ai_addon?.status === "pending";
  const provider = pending ? "Akamai brief in progress" : snap.model_id.startsWith("akamai:") ? "Powered by Akamai"
    : snap.model_id.startsWith("bedrock:") ? "AWS fallback" : snap.model_id === "deterministic-fallback" ? "Template suggestion" : "Archived AI brief";
  const tz = snap.facility.timezone;
  const unavailable = snap.sources.filter((s) => s.status === "unavailable");
  const metrics = data ? relevantMetrics(snap, data) : [];
  return (
    <article className="card overflow-hidden" aria-labelledby={`${id}-action`}>
      <section className="p-5 sm:p-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id={`${id}-action`} className="text-2xl font-semibold tracking-tight underline decoration-[var(--accent)] decoration-2 underline-offset-8">Suggested Action</h2>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={snap.model_id.startsWith("bedrock:") ? "warn" : pending ? "neutral" : "info"}>{provider}</Badge>
            {onRegenerate && <button onClick={onRegenerate} disabled={pending} className="btn min-h-11 !px-2 !text-xs"
              title="Ask Akamai to rewrite the suggestion from the same recorded evidence. Re-evaluate for fresh weather.">
              <span aria-hidden>↻</span> {pending ? "Updating…" : "Regenerate"}
            </button>}
          </div>
        </div>
        <p className="mt-6 text-xl leading-relaxed sm:text-2xl" data-testid="suggested-action">
          Due to {joinReasons(suggestionReasons(snap))}, <strong className="font-semibold">{ACTIONS[snap.posture.posture]}</strong>.
        </p>
        <p className="mt-3 text-sm text-ink2">The manager makes the final decision. Approval is required before operating instructions are communicated.</p>
        {snap.posture.guidance.length > 0 && <div role="alert" className="mt-4 rounded-lg border-l-4 border-[var(--danger)] bg-[var(--surface-2)] px-3 py-2 text-sm font-medium">
          {snap.posture.guidance.map((guidance) => <p key={guidance}>{guidance}</p>)}
        </div>}
        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-ink2">
          <span className="capitalize">{snap.confidence.level} confidence</span>
          <span>As of {fmtTime(snap.as_of, tz)}</span>
          {snap.readiness?.decide_by && <span className={snap.readiness.deadline_passed ? "font-semibold text-[var(--danger)]" : "font-medium"}>
            {snap.readiness.deadline_passed ? "Decision deadline passed: " : "Decide by "}{fmtTime(snap.readiness.decide_by, tz)}
          </span>}
          {snap.roster.expected_in_building !== undefined && <span>{snap.roster.expected_in_building} people expected on site</span>}
        </div>
        {(snap.ai_addon?.status === "failed" || (snap.ai.validation && !snap.ai.validation.ok)) &&
          <p role="status" className="mt-3 text-xs text-ink2">Akamai's wording could not be verified. The suggestion uses the recorded rules and evidence.</p>}
        {snap.ai_addon?.regen_failed && <p role="status" className="mt-3 text-xs text-ink2">The new Akamai brief could not be verified. The previous brief is still shown.</p>}
        {unavailable.length > 0 && <p className="mt-3 text-xs text-ink2">Unavailable: {unavailable.map((s) => s.label).join(", ")}. Missing data does not establish safe conditions.</p>}
        <button onClick={showDecision} className="btn btn-primary mt-5 min-h-11">Review and record decision <span aria-hidden>→</span></button>
      </section>
      <hr className="border-edge" />
      <section className="p-5 sm:p-8" aria-labelledby={`${id}-metrics`}>
        <h2 id={`${id}-metrics`} className="text-lg font-semibold">Relevant Metrics</h2>
        <p className="mt-1 text-sm text-ink2">Highlighted periods and points show the evidence behind the suggestion.</p>
        {error ? <p role="status" className="mt-4 rounded-lg bg-[var(--surface-2)] p-4 text-sm">Chart data could not be loaded. The recorded suggestion and manager review remain available.</p>
          : !data ? <div className="mt-4 space-y-4" aria-label="Loading relevant metrics"><Skeleton className="h-60" /><Skeleton className="h-40" /></div>
          : <div className="mt-4 space-y-4">{metrics.map((metric, index) =>
            <PanelBoundary key={metric.id} name={metric.title}><MetricChart snap={snap} metric={metric} data={data} compact={index > 0} /></PanelBoundary>
          )}</div>}
      </section>
      <hr className="border-edge" />
      <section>
        <button id={`${id}-toggle`} aria-expanded={open} aria-controls={`${id}-details`}
          onClick={() => { setVisited(true); setOpen(!open); }}
          className="flex min-h-16 w-full items-center gap-3 bg-[var(--surface-2)] px-5 py-4 text-left hover:bg-[var(--tint)] sm:px-8">
          <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className={`h-5 w-5 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}>
            <path d="m5 7 5 5 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span><span className="block font-semibold">More information</span><span className="block text-xs text-muted">Manager decision, supporting evidence, sources & history</span></span>
        </button>
        <div id={`${id}-details`} role="region" aria-labelledby={`${id}-toggle`} hidden={!open}>
          {visited && <div className="space-y-4 p-4 sm:p-6">
            <div ref={decisionRef} className="scroll-mt-4">
              <PanelBoundary name="Manager decision"><DecisionPanel key={snap.snapshot_id} snap={snap} onRecorded={onRecorded} onNotify={onNotify} /></PanelBoundary>
            </div>
            <PanelBoundary name="Explanation"><AIPanel snap={snap} onRegenerate={onRegenerate} /></PanelBoundary>
            <PanelBoundary name="Alerts"><AlertsPanel snap={snap} /></PanelBoundary>
            <PanelBoundary name="Watch"><WatchPanel snap={snap} /></PanelBoundary>
            <PanelBoundary name="Threat breakdown"><ThreatPanel snap={snap} /></PanelBoundary>
            <PanelBoundary name="All weather metrics"><TimelinePanel snap={snap} data={data} /></PanelBoundary>
            <PanelBoundary name="Roads and cameras"><RoadsPanel snap={snap} historical={historical} savedDecisionId={savedDecisionId} /></PanelBoundary>
            <PanelBoundary name="Analogs"><AnalogsPanel snap={snap} /></PanelBoundary>
            <PanelBoundary name="Decision record"><RecordTimeline snap={snap} refreshKey={recordKey} onOpen={onOpenRecord} /></PanelBoundary>
            <PanelBoundary name="Raw data"><RawDataDrawer snap={snap} /></PanelBoundary>
          </div>}
        </div>
      </section>
    </article>
  );
}
