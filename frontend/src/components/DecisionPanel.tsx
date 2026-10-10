import { useState } from "react";
import { api } from "../api";
import type { Posture, Snapshot } from "../types";
import { Card, POSTURES, POSTURE_STYLE, PostureBadge } from "../util";

export function DecisionPanel({ snap, onRecorded, onNotify }: {
  snap: Snapshot; onRecorded: (id: number) => void; onNotify: (id: number) => void;
}) {
  const [by, setBy] = useState("");
  const [posture, setPosture] = useState<Posture>(snap.posture.posture);
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [recordedId, setRecordedId] = useState<number | null>(null);
  const override = posture !== snap.posture.posture;
  if (snap.mode === "backtest" || snap.facility.hypothetical) {
    return <Card title="Record decision"><p className="text-sm text-ink2">Decisions are recorded only against live or replay snapshots of the real facility profile.</p></Card>;
  }
  const submit = async () => {
    setBusy(true); setMsg(null);
    try {
      const recorded = await api.decide({ snapshot_id: snap.snapshot_id, decided_by: by, decision_posture: posture, override_reason: override ? reason : undefined, notes: notes || undefined });
      setMsg("Decision recorded against this snapshot. It cannot be edited; record a new decision to correct it.");
      setReason(""); setNotes("");
      setRecordedId(recorded.id);
      onRecorded(recorded.id);
    } catch (e: any) {
      setMsg(`Not recorded: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Record decision">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">Recommendation: <PostureBadge p={snap.posture.posture} size="sm" /></div>
      <div className="grid gap-2 text-sm">
        <label className="grid gap-1">Decided by
          <input value={by} onChange={(e) => setBy(e.target.value)} placeholder="Name, title" className="rounded-md border border-edge bg-surface px-2 py-1" />
        </label>
        <fieldset className="grid gap-1">
          <legend className="mb-1">Decision</legend>
          <div className="flex flex-wrap gap-2">
            {POSTURES.map((p) => (
              <label key={p} className={`flex cursor-pointer items-center gap-1 rounded-md border px-2 py-1 ${posture === p ? "border-2" : "border-edge"}`} style={posture === p ? { borderColor: POSTURE_STYLE[p].color } : undefined}>
                <input type="radio" name="posture" value={p} checked={posture === p} onChange={() => setPosture(p)} />
                {POSTURE_STYLE[p].label}{p === snap.posture.posture && <span className="text-xs text-muted"> (rec.)</span>}
              </label>
            ))}
          </div>
        </fieldset>
        {override && (
          <label className="grid gap-1">Override reason (required)
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className="rounded-md border border-edge bg-surface px-2 py-1"
              placeholder="e.g. Story County EM reports untreated rural roads; staff on US-69 can't get in" />
          </label>
        )}
        <label className="grid gap-1">Notes (optional)
          <input value={notes} onChange={(e) => setNotes(e.target.value)} className="rounded-md border border-edge bg-surface px-2 py-1" />
        </label>
        <button onClick={submit} disabled={busy || by.trim().length < 2 || (override && !reason.trim())}
          className="btn btn-primary mt-1">
          {override ? "Record override" : "Accept recommendation"}
        </button>
        {msg && <p className="cc-rise rounded-lg bg-[var(--tint)] px-2 py-1.5 text-xs">{msg}</p>}
        {recordedId !== null && (
          <button onClick={() => onNotify(recordedId)} className="btn btn-primary cc-rise">Send notifications →</button>
        )}
        <p className="text-xs text-muted">Snapshot {snap.snapshot_id.slice(0, 12)} · content hash {snap.content_sha256.slice(0, 12)} {snap.integrity_ok ? "✓ verified" : ""}</p>
      </div>
    </Card>
  );
}
