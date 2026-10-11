import type { Snapshot } from "../types";
import { Card, ReadinessMeter } from "../util";

/** Scores, factors and record identifiers: kept for audit and admins, out of the manager's way. */
export function TechnicalSummary({ snap }: { snap: Snapshot }) {
  const tz = snap.facility.timezone;
  const r = snap.readiness;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="How urgent (readiness)">
        {r ? (
          <div className="space-y-2 text-sm">
            <ReadinessMeter r={r} tz={tz} />
            <p className="text-ink2">{r.meaning}</p>
            {!!r.reasons.length && <ul className="list-disc space-y-0.5 pl-5 text-ink2">{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>}
            <p className="text-xs text-muted">Re-checked every {r.recheck_minutes} min. Readiness sets urgency; the rules set the operating status.</p>
          </div>
        ) : <p className="text-sm text-ink2">Readiness was not recorded for this snapshot.</p>}
      </Card>
      <Card title={`Confidence: ${snap.confidence.level} (${snap.confidence.score.toFixed(2)})`}>
        <ul className="space-y-1.5 text-sm">
          {snap.confidence.factors.map((f) => (
            <li key={f.name}>
              <span className="font-medium">{f.name}</span> <span className="tabnum text-muted">{f.score.toFixed(2)} × {f.weight}</span>
              <span className="block text-xs text-ink2">{f.explanation}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-muted">
          Snapshot {snap.snapshot_id.slice(0, 12)} · content hash {snap.content_sha256.slice(0, 12)} {snap.integrity_ok ? "✓ verified" : ""}
          {" "}· model {snap.model_id} · {snap.prompt_version} · thresholds v{snap.thresholds_version}
        </p>
      </Card>
    </div>
  );
}
