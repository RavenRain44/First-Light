import { useState } from "react";
import type { Snapshot } from "../types";
import { Badge, Card, fmtTime, fmtVal, PostureBadge } from "../util";

export function AIPanel({ snap }: { snap: Snapshot }) {
  const [copied, setCopied] = useState(false);
  const ai = snap.ai;
  const overview = ai.summary?.match(/.*?[.!?](?=\s|$)/gs)?.slice(0, 2).join(" ").trim() || ai.summary;
  const template = snap.model_id === "deterministic-fallback";
  const aws = snap.model_id.startsWith("bedrock:");
  const akamai = snap.model_id.startsWith("akamai:");
  const tz = snap.facility.timezone;
  const weakest = [...snap.confidence.factors].sort((a, b) => a.score - b.score)[0];
  const controlling = new Set(Object.values(snap.hazards)
    .filter((h) => snap.posture.contributing_hazards.includes(h.hazard)).flatMap((h) => h.controlling_rule_ids));
  const cited = ai.evidence_rule_ids ?? [];
  const rules = snap.rules.filter((r) => r.triggered)
    .sort((a, b) => Number(controlling.has(b.rule_id)) - Number(controlling.has(a.rule_id)) || b.level - a.level || b.score - a.score);
  const evidence = (cited.length ? cited.map((id) => rules.find((r) => r.rule_id === id)).filter((r) => r !== undefined) : rules).slice(0, 3);
  const unavailable = snap.sources.filter((s) => s.status === "unavailable");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(ai.rationale_paragraph);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard blocked */ }
  };
  return (
    <Card title="Decision brief" right={
      <Badge tone={template ? "neutral" : aws ? "warn" : "info"} title={`Model: ${snap.model_id} · ${snap.prompt_version}`}>
        {template ? "Template brief" : aws ? "AWS fallback" : akamai ? "Powered by Akamai" : "Archived AI brief"}
      </Badge>
    }>
      <div className="rounded-xl bg-[var(--surface-2)] p-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Recommended operating status</p>
        <PostureBadge p={snap.posture.posture} size="lg" />
        <p className="mt-2 text-sm text-ink2">{snap.posture.opm_label}</p>
        <p className="mt-3 text-sm font-medium">The manager makes the final decision. This brief supports that decision.</p>
      </div>
      {snap.posture.guidance.length > 0 && (
        <div role="alert" className="mt-3 rounded-xl border-l-4 border-[var(--danger)] bg-[var(--surface-2)] px-3 py-2 text-sm font-medium">
          {snap.posture.guidance.map((g) => <p key={g}>⚠ {g}</p>)}
        </div>
      )}
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-edge p-3">
          <h3 className="text-xs font-semibold uppercase text-muted">Decision timing</h3>
          <p className="mt-1 text-sm font-semibold">
            {snap.readiness?.decide_by ? `Decide by ${fmtTime(snap.readiness.decide_by, tz)}` : `Operating day: ${snap.posture.decision_day}`}
          </p>
          <p className="mt-1 text-xs text-ink2">{snap.readiness?.deadline_passed ? "The decision deadline has passed; review and communicate the status now." : snap.readiness?.meaning ?? "Review the evidence before communicating the operating status."}</p>
          {!!snap.readiness?.reasons.length && (
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-xs text-ink2">{snap.readiness.reasons.map((x) => <li key={x}>{x}</li>)}</ul>
          )}
        </div>
        <div className="rounded-xl border border-edge p-3">
          <h3 className="text-xs font-semibold uppercase text-muted">Confidence & uncertainty</h3>
          <p className="mt-1 text-sm font-semibold capitalize">{snap.confidence.level} confidence</p>
          <p className="mt-1 text-xs text-ink2">{ai.uncertainty || weakest?.explanation || "Confidence factors are unavailable."}</p>
        </div>
      </div>
      <div className="mt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Why this is suggested</h3>
        <p key={snap.snapshot_id} className="cc-fade mt-2 text-[15px] leading-relaxed">{overview || snap.posture.reasons.join(" ") || ai.headline}</p>
        {snap.roster.expected_in_building !== undefined && (
          <p className="mt-2 text-xs text-muted">{snap.roster.expected_in_building} of {snap.roster.assigned} assigned employees expected on site. Brief as of {fmtTime(snap.as_of, tz)}.</p>
        )}
        {snap.roster.essential_in_building !== undefined && <p className="mt-1 text-xs text-muted">
          {snap.roster.essential_in_building} essential staff{snap.roster.accessibility_needs_in_building !== undefined && ` · ${snap.roster.accessibility_needs_in_building} with accessibility needs`}.
        </p>}
      </div>
      <div className="mt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Evidence to review</h3>
        <ul className="mt-2 space-y-2">
          {evidence.map((r) => (
            <li key={r.rule_id} className="rounded-lg border border-edge p-3 text-sm">
              <p className="font-semibold">{r.label}</p>
              <p className="mt-1 text-ink2">{fmtVal(r.observed_value, r.unit)}
                {r.metric !== "alert_present" && <> · Threshold: {r.operator} {fmtVal(r.threshold, r.unit)}</>}
              </p>
              {(r.window_start || r.time_of_peak) && <p className="mt-1 text-xs text-muted">
                {r.window_start ? `Window: ${fmtTime(r.window_start, tz)}${r.window_end ? ` – ${fmtTime(r.window_end, tz)}` : ""}` : `Peak: ${fmtTime(r.time_of_peak, tz)}`}
              </p>}
              <p className="mt-1 text-xs text-muted">
                {r.source_url.startsWith("https://") && <a href={r.source_url} target="_blank" rel="noreferrer" className="break-all underline">{r.anchor || "Source"}</a>}
                {" · "}{r.verified ? "Verified threshold" : "Policy threshold · source verification pending"}
              </p>
            </li>
          ))}
        </ul>
        {!evidence.length && <p className="mt-2 text-sm text-ink2">No operating-status threshold is crossed. Check uncertainty and missing sources before accepting normal operations.</p>}
        {unavailable.length > 0 && <p className="mt-2 text-sm text-ink2">Unavailable sources: {unavailable.map((s) => s.label).join(", ")}. Missing data does not establish safe conditions.</p>}
      </div>
      {template && ai.validation && !ai.validation.ok && (
        <p role="status" className="mt-3 rounded-lg bg-[var(--surface-2)] p-3 text-xs text-ink2">AI is unavailable or its brief could not be verified. This template uses the same recorded evidence; the rules recommendation is preserved.</p>
      )}
      {aws && <p className="mt-3 text-xs text-ink2">Akamai was unavailable or its output could not be verified. This brief was generated by the configured AWS fallback.</p>}
      <div className="mt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">What would change the recommendation</h3>
        <ul className="mt-2 space-y-1.5 text-sm">
          {(ai.what_would_change.length ? ai.what_would_change : ["No nearby threshold change identified."]).map((w) => (
            <li key={w} className="flex gap-2"><span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--b3)]" />{w}</li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted">Computed by re-running the rules. The manager can accept or override the recommendation in the decision panel.</p>
      </div>
      <details className="mt-4 border-t border-edge pt-3">
        <summary className="cursor-pointer text-sm font-semibold">Rationale for the decision record</summary>
        <div className="mt-3 rounded-xl bg-[var(--surface-2)] p-4">
          <button onClick={copy} className="btn mb-2 !px-2 !py-0.5 !text-xs">{copied ? "Copied ✓" : "Copy rationale"}</button>
          <p className="text-sm leading-relaxed">{ai.rationale_paragraph}</p>
        </div>
      </details>
      {snap.readiness && <p className="mt-3 text-xs text-muted">Re-check every {snap.readiness.recheck_minutes} min. Readiness sets urgency; deterministic rules recommend the operating status.</p>}
    </Card>
  );
}

export function WatchPanel({ snap }: { snap: Snapshot }) {
  return (
    <Card title="Watch in the next 6 hours">
      <ul className="space-y-2 text-sm">
        {(snap.ai.watch_next_6h.length ? snap.ai.watch_next_6h : ["Monitor weather alerts and changes in source availability."]).map((w) => (
          <li key={w} className="cc-rise flex gap-2"><span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent)]" />{w}</li>
        ))}
      </ul>
    </Card>
  );
}
