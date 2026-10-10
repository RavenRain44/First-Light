import { useEffect, useState } from "react";
import { api } from "../api";
import type { Snapshot } from "../types";
import { Badge, Card, PostureBadge, Skeleton, fmtTime, readinessColor } from "../util";

export function AnalogsPanel({ snap }: { snap: Snapshot }) {
  const tz = snap.facility.timezone;
  const [nEvents, setNEvents] = useState<number | null>(null);
  useEffect(() => { api.events().then((e) => setNEvents(e.length)).catch(() => setNEvents(null)); }, []);
  const quiet = Object.values(snap.hazards).every((h) => h.level === 0) && snap.alerts.length === 0;
  return (
    <Card title="Similar past events" right={<span className="text-xs text-muted">nearest neighbors on the snapshot feature vector</span>}>
      {snap.analogs.length === 0 ? (
        nEvents === 0 ? (
          <p className="text-sm text-ink2">No backtested history in this database yet. Run <code>npm run build:history</code> (works offline in about 20 s from the committed cache).</p>
        ) : (
          <p className="text-sm text-ink2">
            {quiet
              ? `No active alerts or hazards right now, so comparing to past storms isn't meaningful (a calm day resembles every storm's calm hours).`
              : "No past event is similar enough to show."}
            {nEvents ? ` ${nEvents} past events are loaded; try Replay to see analogs during a storm.` : ""}
          </p>
        )
      ) : (
        <div className="grid gap-3 md:grid-cols-3">
          {snap.analogs.map((a) => (
            <article key={a.event_id} className="cc-rise rounded-xl border border-edge p-4 text-sm transition-colors hover:border-[var(--b3)]">
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-semibold">{a.name}</h3>
                <span className="tabnum text-lg font-bold">{a.similarity_pct.toFixed(0)}%</span>
              </div>
              <p className="text-xs text-muted">closest hour: {fmtTime(a.matched_as_of, tz)}</p>
              <div className="mt-2 flex flex-wrap items-center gap-1 text-xs">Rules recommended <PostureBadge p={a.recommended_posture} size="sm" /></div>
              <Badge tone="neutral">{a.label}</Badge>
              <p className="mt-2 text-xs"><span className="font-semibold">What happened:</span> {a.outcome_summary}</p>
            </article>
          ))}
        </div>
      )}
      {snap.ai.analog_comparison && <p className="mt-3 text-sm"><span className="font-semibold">Comparison: </span>{snap.ai.analog_comparison}</p>}
    </Card>
  );
}

export function RecordTimeline({ snap, refreshKey, onOpen }: { snap: Snapshot; refreshKey: number; onOpen: (id: string) => void }) {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => { api.history().then(setRows).catch(() => setRows([])); }, [refreshKey, snap.snapshot_id]);
  const tz = snap.facility.timezone;
  return (
    <Card title="Decision record (this facility)" right={<span className="text-xs text-muted">immutable snapshots + human decisions</span>}>
      {!rows ? <Skeleton className="h-24" /> : rows.length === 0 ? (
        <p className="text-sm text-ink2">No snapshots yet.</p>
      ) : (
        <ol className="max-h-96 space-y-2 overflow-auto pr-1">
          {rows.map((r) => (
            <li key={r.snapshot_id} className={`rounded-md border p-2 text-sm ${r.snapshot_id === snap.snapshot_id ? "border-[var(--accent)] bg-[var(--tint)]" : "border-edge"}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <button className="text-left underline-offset-2 hover:underline" onClick={() => onOpen(r.snapshot_id)}>
                  <span className="tabnum">{fmtTime(r.as_of, tz)}</span> <Badge>{r.mode}</Badge>
                </button>
                <PostureBadge p={r.posture} size="sm" />
              </div>
              <p className="flex flex-wrap items-center gap-1 text-xs text-muted">
                {r.readiness && <><span className="inline-block h-2.5 w-2.5 rounded-sm border border-edge" style={{ background: readinessColor(r.readiness) }} />Condition {r.readiness.toLowerCase()} ·</>}
                confidence {r.confidence} · {r.model_id} · created {fmtTime(r.created_at, tz)}
              </p>
              {r.decisions.map((d: any) => (
                <div key={d.id} className="mt-1 rounded bg-[var(--surface-2)] p-1.5 text-xs">
                  <span className="font-semibold">{d.decided_by}</span> decided <strong>{d.decision_posture.replace("_", " ")}</strong>{" "}
                  {d.agreed_with_recommendation ? <Badge tone="good">agreed</Badge> : <Badge tone="warn">override</Badge>}{" "}
                  <span className="text-muted">{fmtTime(d.decided_at, tz)} · real (recorded in this system)</span>
                  {d.override_reason && <p className="mt-0.5 italic">Reason: {d.override_reason}</p>}
                </div>
              ))}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
