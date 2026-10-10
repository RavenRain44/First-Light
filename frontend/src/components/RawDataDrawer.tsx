import type { Snapshot } from "../types";
import { Badge, Card, fmtTime } from "../util";

const STATUS_TONE = { ok: "good", empty: "neutral", unavailable: "bad", not_applicable: "neutral" } as const;

export function RawDataDrawer({ snap }: { snap: Snapshot }) {
  const tz = snap.facility.timezone;
  const bySource: Record<string, typeof snap.inputs> = {};
  for (const i of snap.inputs) (bySource[i.source] ??= []).push(i);
  return (
    <Card title="Raw data & sources">
      <ul className="mb-3 grid gap-1 text-sm md:grid-cols-2">
        {snap.sources.map((s) => (
          <li key={s.adapter} className="flex flex-wrap items-center gap-2">
            <Badge tone={STATUS_TONE[s.status]}>{s.status}</Badge>
            <span>{s.label}</span>
            {s.detail && <span className="text-xs text-muted">({s.detail})</span>}
            {s.fetched_at && <span className="text-xs text-muted">fetched {fmtTime(s.fetched_at, tz)}</span>}
          </li>
        ))}
      </ul>
      <details>
        <summary className="text-sm font-medium">Every normalized input in this snapshot ({snap.inputs.length}), grouped by source</summary>
        <div className="mt-2 space-y-2">
          {Object.entries(bySource).map(([src, items]) => (
            <details key={src} className="rounded-md border border-edge p-2">
              <summary className="text-sm">{src} <span className="text-xs text-muted">· {items.length} inputs · fetched {fmtTime(items[0].fetched_at, tz)}</span></summary>
              <p className="mt-1 break-all text-xs text-muted">{items[0].source_url}</p>
              <pre className="mt-1 max-h-80 overflow-auto rounded bg-[var(--surface-2)] p-2 text-xs">{JSON.stringify(items, null, 1)}</pre>
            </details>
          ))}
        </div>
      </details>
      <details className="mt-2">
        <summary className="text-sm font-medium">Snapshot metadata</summary>
        <pre className="mt-1 max-h-60 overflow-auto rounded bg-[var(--surface-2)] p-2 text-xs">{JSON.stringify({
          snapshot_id: snap.snapshot_id, mode: snap.mode, as_of: snap.as_of, created_at: snap.created_at,
          thresholds_version: snap.thresholds_version, thresholds_sha256: snap.thresholds_sha256,
          model_id: snap.model_id, prompt_version: snap.prompt_version, content_sha256: snap.content_sha256,
          integrity_ok: snap.integrity_ok, confidence: snap.confidence,
        }, null, 1)}</pre>
      </details>
    </Card>
  );
}
