import { useState } from "react";
import type { Snapshot } from "../types";
import { Badge, Card, fmtTime, fmtVal } from "../util";

export function AIPanel({ snap, onRegenerate }: { snap: Snapshot; onRegenerate?: () => void }) {
  const [copied, setCopied] = useState(false);
  const ai = snap.ai;
  const overview = ai.summary?.match(/.*?[.!?](?=\s|$)/gs)?.slice(0, 2).join(" ").trim() || ai.summary;
  const template = snap.model_id === "deterministic-fallback";
  const addon = snap.ai_addon;
  const pending = addon?.status === "pending";
  const aws = snap.model_id.startsWith("bedrock:");
  const akamai = snap.model_id.startsWith("akamai:");
  const tz = snap.facility.timezone;
  const controlling = new Set(Object.values(snap.hazards)
    .filter((h) => snap.posture.contributing_hazards.includes(h.hazard)).flatMap((h) => h.controlling_rule_ids));
  const cited = ai.evidence_rule_ids ?? [];
  const rules = snap.rules.filter((r) => r.triggered)
    .sort((a, b) => Number(controlling.has(b.rule_id)) - Number(controlling.has(a.rule_id)) || b.level - a.level || b.score - a.score);
  const evidence = (cited.length ? cited.map((id) => rules.find((r) => r.rule_id === id)).filter((r) => r !== undefined) : rules).slice(0, 3);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(ai.rationale_paragraph);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard blocked */ }
  };
  return (
    <Card title="Evidence & explanation" right={<span className="flex flex-wrap items-center justify-end gap-2">{
      pending ? (
        <Badge tone="neutral" title="The template brief is shown now; the Akamai brief is being written in the background.">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--accent)]" /> Akamai brief in progress…
        </Badge>
      ) : (
        <Badge tone={template ? "neutral" : aws ? "warn" : "info"} title={`Model: ${snap.model_id} · ${snap.prompt_version}${addon?.created_at ? ` · added ${fmtTime(addon.created_at, snap.facility.timezone)}` : ""}`}>
          {template ? "Template brief" : aws ? "AWS fallback" : akamai ? `Powered by Akamai${addon?.seconds ? ` · +${Math.round(addon.seconds)} s` : ""}` : "Archived AI brief"}
        </Badge>
      )}
      {onRegenerate && (
        <button onClick={onRegenerate} disabled={pending} className="btn !px-2 !py-0.5 !text-xs"
          title="Ask Akamai to rewrite this brief now from the same recorded data. Use “Check again” on the status card to fetch fresh weather first.">
          <span aria-hidden className={`inline-block ${pending ? "animate-spin" : ""}`}>↻</span> {pending ? "Updating…" : "Regenerate"}
        </button>
      )}
    </span>}>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">In short</h3>
        <p key={`${snap.snapshot_id}-${snap.model_id}`} className="cc-fade mt-2 text-[15px] leading-relaxed">{overview || snap.posture.reasons.join(" ") || ai.headline}</p>
        {ai.uncertainty && <p className="mt-2 text-sm text-ink2"><span className="font-medium text-ink">What's uncertain: </span>{ai.uncertainty}</p>}
      </div>
      <div className="mt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Weather limits reached</h3>
        <ul className="mt-2 space-y-2">
          {evidence.map((r) => (
            <li key={r.rule_id} className="rounded-lg border border-edge p-3 text-sm">
              <p className="font-semibold">{r.label}</p>
              <p className="mt-1 text-ink2">{r.metric === "alert_present" ? `${r.observed_value} is in effect` : <>{fmtVal(r.observed_value, r.unit)} (limit {fmtVal(r.threshold, r.unit)})</>}</p>
              {(r.window_start || r.time_of_peak) && <p className="mt-1 text-xs text-muted">
                {r.window_start ? `When: ${fmtTime(r.window_start, tz)}${r.window_end ? ` – ${fmtTime(r.window_end, tz)}` : ""}` : `Worst at ${fmtTime(r.time_of_peak, tz)}`}
              </p>}
              <p className="mt-1 text-xs text-muted">
                {r.source_url.startsWith("https://") && <a href={r.source_url} target="_blank" rel="noreferrer" className="underline">Where this limit comes from</a>}
                {!r.verified && " · local policy limit"}
              </p>
            </li>
          ))}
        </ul>
        {!evidence.length && <p className="mt-2 text-sm text-ink2">No weather limit is reached for the work day.</p>}
      </div>
      {addon?.regen_failed && (
        <p role="status" className="mt-3 rounded-lg bg-[var(--surface-2)] p-3 text-xs text-ink2">The new Akamai brief could not be produced or verified; the previous brief is still shown.</p>
      )}
      {addon?.status === "failed" && (
        <p role="status" className="mt-3 rounded-lg bg-[var(--surface-2)] p-3 text-xs text-ink2">The Akamai brief could not be produced or verified, so the template brief stays. It uses the same recorded evidence; the rules recommendation is unchanged.</p>
      )}
      {template && ai.validation && !ai.validation.ok && (
        <p role="status" className="mt-3 rounded-lg bg-[var(--surface-2)] p-3 text-xs text-ink2">AI is unavailable or its brief could not be verified. This template uses the same recorded evidence; the rules recommendation is preserved.</p>
      )}
      {aws && <p className="mt-3 text-xs text-ink2">Akamai was unavailable or its output could not be verified. This brief was generated by the configured AWS fallback.</p>}
      <div className="mt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">What would change the recommendation</h3>
        <ul className="mt-2 space-y-1.5 text-sm">
          {(ai.what_would_change.length ? ai.what_would_change : ["Nothing nearby in the forecast would change it."]).map((w) => (
            <li key={w} className="flex gap-2"><span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--b3)]" />{w}</li>
          ))}
        </ul>
      </div>
      <div className="mt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Watch in the next 6 hours</h3>
        <ul className="mt-2 space-y-1.5 text-sm">
          {(ai.watch_next_6h.length ? ai.watch_next_6h : ["Monitor weather alerts and changes in source availability."]).map((w) => (
            <li key={w} className="flex gap-2"><span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent)]" />{w}</li>
          ))}
        </ul>
      </div>
      <details className="mt-4 border-t border-edge pt-3">
        <summary className="cursor-pointer text-sm font-semibold">Written rationale (to copy into your records)</summary>
        <div className="mt-3 rounded-xl bg-[var(--surface-2)] p-4">
          <button onClick={copy} className="btn mb-2 !px-2 !py-0.5 !text-xs">{copied ? "Copied ✓" : "Copy rationale"}</button>
          <p className="text-sm leading-relaxed">{ai.rationale_paragraph}</p>
        </div>
      </details>
    </Card>
  );
}
