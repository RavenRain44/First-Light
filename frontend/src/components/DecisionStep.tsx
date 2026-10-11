import { useEffect, useState } from "react";
import { api } from "../api";
import type { Posture, Snapshot } from "../types";
import { CooperBanner, POSTURES, POSTURE_STYLE, PostureBadge, fmtClock, fmtDayLong, fmtTime } from "../util";
import { suggestionSentence } from "./DashboardCard";

const NAME_KEY = "cc-decided-by";
const savedName = () => { try { return localStorage.getItem(NAME_KEY) ?? ""; } catch { return ""; } };

interface Recorded { id: number; decided_by: string; decision_posture: Posture; decided_at: string; agreed_with_recommendation: boolean }

/** Step 1 on the Notify staff page: see the risk and suggestion, then confirm (or change) the decision.
 *  Confirming records it; nothing is sent until the alerts below are reviewed and approved. */
export function DecisionStep({ snap, onDecided }: { snap: Snapshot; onDecided: (id: number | null) => void }) {
  const tz = snap.facility.timezone;
  const r = snap.readiness;
  const rec = snap.posture.posture;
  const canDecide = snap.mode !== "backtest" && !snap.facility.hypothetical;
  const [done, setDone] = useState<Recorded | null>(null);
  const [checked, setChecked] = useState(false);
  const [editing, setEditing] = useState(false);

  // Was this suggestion already decided (e.g. earlier today, before a page reload)?
  useEffect(() => {
    let alive = true;
    setChecked(false); setDone(null); setEditing(false);
    api.history().then((rows) => {
      if (!alive) return;
      const ds: Recorded[] = rows.find((x: any) => x.snapshot_id === snap.snapshot_id)?.decisions ?? [];
      const last = [...ds].sort((a, b) => b.decided_at.localeCompare(a.decided_at))[0] ?? null;
      setDone(last); onDecided(last?.id ?? null);
    }).catch(() => onDecided(null)).finally(() => alive && setChecked(true));
    return () => { alive = false; };
  }, [snap.snapshot_id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className="card overflow-hidden" aria-label="Step 1: confirm the decision">
      <CooperBanner r={r} />
      <div className="p-5 sm:p-7">
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">Step 1 · Confirm the decision</p>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="text-sm text-ink2">Suggested for {fmtDayLong(snap.posture.decision_day)}:</span>
          <PostureBadge p={rec} />
          {r?.decide_by && (
            <span className={`font-semibold ${r.deadline_passed ? "text-[var(--danger)]" : ""}`}>
              {r.deadline_passed ? "Deadline passed: decide now" : `Decide by ${fmtClock(r.decide_by, tz)}`}
            </span>
          )}
        </div>
        <p className="mt-2 max-w-3xl text-ink2">{suggestionSentence(snap)}</p>

        {!canDecide ? (
          <p className="mt-5 rounded-lg bg-[var(--surface-2)] px-3 py-2 text-sm">
            {snap.facility.hypothetical ? "This is a what-if check, so no decision is recorded and no one is alerted."
              : "This is a replay of a past storm, so no decision is recorded and no one is alerted."} Go back to Today to decide for your facility.
          </p>
        ) : !checked ? (
          <div className="skeleton mt-5 h-12" aria-hidden />
        ) : done && !editing ? (
          <div className="cc-rise mt-5 flex flex-wrap items-center gap-3 rounded-xl bg-[var(--tint)] px-4 py-3">
            <span className="font-semibold">✓ Decided:</span>
            <PostureBadge p={done.decision_posture} size="sm" />
            <span className="text-sm text-ink2">by {done.decided_by} at {fmtTime(done.decided_at, tz)}{done.agreed_with_recommendation ? "" : " (changed from the suggestion)"}</span>
            <button onClick={() => setEditing(true)} className="ml-auto text-sm text-[var(--accent)] hover:underline">Record a different decision</button>
          </div>
        ) : (
          <DecideForm snap={snap} onCancel={done ? () => setEditing(false) : undefined}
            onRecorded={(d) => { setDone(d); setEditing(false); onDecided(d.id); }} />
        )}
      </div>
    </section>
  );
}

function DecideForm({ snap, onRecorded, onCancel }: { snap: Snapshot; onRecorded: (d: Recorded) => void; onCancel?: () => void }) {
  const rec = snap.posture.posture;
  const [by, setBy] = useState(savedName);
  const [posture, setPosture] = useState<Posture>(rec);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const override = posture !== rec;
  const ok = by.trim().length >= 2 && (!override || reason.trim().length > 0);

  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const d = await api.decide({ snapshot_id: snap.snapshot_id, decided_by: by.trim(), decision_posture: posture,
        override_reason: override ? reason.trim() : undefined });
      try { localStorage.setItem(NAME_KEY, by.trim()); } catch { /* storage blocked */ }
      onRecorded({ id: d.id, decided_by: by.trim(), decision_posture: posture, decided_at: new Date().toISOString(), agreed_with_recommendation: !override });
    } catch (e: any) {
      setErr(`Not recorded: ${e.message ?? e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-5 space-y-4">
      <fieldset>
        <legend className="mb-2 text-sm font-medium">Operating status</legend>
        <div className="flex flex-wrap gap-2">
          {POSTURES.map((p) => (
            <label key={p} className={`flex min-h-[44px] cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm ${posture === p ? "border-2" : "border-edge"}`}
              style={posture === p ? { borderColor: POSTURE_STYLE[p].color } : undefined}>
              <input type="radio" name="decision-posture" value={p} checked={posture === p} onChange={() => setPosture(p)} />
              {POSTURE_STYLE[p].label}{p === rec && <span className="text-xs text-muted">(suggested)</span>}
            </label>
          ))}
        </div>
      </fieldset>
      {override && (
        <label className="flex max-w-2xl flex-col gap-1 text-sm">
          <span className="font-medium">Why are you choosing differently? (required)</span>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className="rounded-lg border border-edge bg-surface px-3 py-2"
            placeholder="e.g. County roads north of town are untreated; staff on US 69 can't get in" />
        </label>
      )}
      <label className="flex max-w-sm flex-col gap-1 text-sm">
        <span className="font-medium">Your name and title</span>
        <input value={by} onChange={(e) => setBy(e.target.value)} placeholder="e.g. Pat Lee, Facility Manager" autoComplete="name"
          className="min-h-[44px] rounded-lg border border-edge bg-surface px-3" />
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={submit} disabled={busy || !ok} className="btn btn-primary min-h-[44px] px-5 text-base">
          {busy ? "Recording…" : `Confirm “${POSTURE_STYLE[posture].label}”`}
        </button>
        {onCancel && <button onClick={onCancel} className="btn min-h-[44px] px-4">Cancel</button>}
        <span className="text-xs text-muted">Confirming does not alert anyone. You review and send the alerts in step 2.</span>
      </div>
      {err && <p role="alert" className="text-sm text-[var(--danger)]">{err}</p>}
    </div>
  );
}
