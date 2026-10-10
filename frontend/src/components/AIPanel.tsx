import { useState } from "react";
import type { Snapshot } from "../types";
import { Badge, Card } from "../util";

export function AIPanel({ snap }: { snap: Snapshot }) {
  const [copied, setCopied] = useState(false);
  const ai = snap.ai;
  const fallback = snap.model_id === "deterministic-fallback";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(ai.rationale_paragraph);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard blocked */ }
  };
  return (
    <Card title="Interpretation" right={
      <span className="flex items-center gap-2 text-xs text-muted">
        <Badge tone={fallback ? "neutral" : "info"} title={`model: ${snap.model_id} · prompt ${snap.prompt_version}`}>
          {fallback ? "Template (no model)" : `AI: ${snap.model_id}`}
        </Badge>
      </span>
    }>
      <p className="text-lg font-semibold">{ai.headline}</p>
      {snap.posture.guidance.length > 0 && (
        <div role="alert" className="mt-3 rounded-xl border-l-4 border-[var(--danger)] bg-[var(--surface-2)] px-3 py-2 text-sm font-medium">
          {snap.posture.guidance.map((g) => <p key={g}>⚠ {g}</p>)}
        </div>
      )}
      {snap.readiness && (
        <div className="mt-4 border-l-2 border-edge pl-3">
          <p className="text-sm"><span className="font-semibold">Condition {snap.readiness.level.charAt(0) + snap.readiness.level.slice(1).toLowerCase()}:</span> {snap.readiness.meaning}</p>
          <ul className="mt-1 list-disc pl-5 text-xs text-ink2">{snap.readiness.reasons.map((x) => <li key={x}>{x}</li>)}</ul>
          <p className="mt-1 text-xs text-muted">Re-check every {snap.readiness.recheck_minutes} min at this level. Adapted from Jeff Cooper's Color Code (a policy aid, not a federal standard); it sets urgency, never the posture.</p>
        </div>
      )}
      <div className="mt-4 rounded-xl bg-[var(--surface-2)] p-4">
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase text-ink2">Paste-ready rationale</span>
          <button onClick={copy} className="btn !px-2 !py-0.5 !text-xs">{copied ? "Copied ✓" : "Copy"}</button>
        </div>
        <p className="text-[15px] leading-relaxed">{ai.rationale_paragraph}</p>
      </div>
      {ai.validation && !ai.validation.ok && (
        <p className="mt-2 text-xs text-muted">Model output failed number validation ({ai.validation.problems.join("; ")}); showing the deterministic template.</p>
      )}
      <div className="mt-5 grid gap-5 md:grid-cols-2">
        <div>
          <h3 className="text-xs font-semibold uppercase text-ink2">What would change this</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {(ai.what_would_change.length ? ai.what_would_change : ["Nothing within reach of a threshold."]).map((w) => <li key={w}>{w}</li>)}
          </ul>
          <p className="mt-1 text-xs text-muted">Computed by re-running the rules with each input moved past its threshold.</p>
        </div>
        <div>
          <h3 className="text-xs font-semibold uppercase text-ink2">Watch in the next 6 hours</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {ai.watch_next_6h.map((w) => <li key={w}>{w}</li>)}
          </ul>
        </div>
      </div>
      <p className="mt-3 text-xs text-muted">The recommendation is computed by deterministic rules. The model only explains it; the manager decides.</p>
    </Card>
  );
}
