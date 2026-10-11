import { useEffect, useState } from "react";
import { api } from "../api";
import type { PastDecision, Snapshot, Verdict } from "../types";
import { Badge, CooperChip, POSTURE_STYLE, PostureBadge, Skeleton, fmtDayLong } from "../util";

const NAME_KEY = "cc-decided-by";
const savedName = () => { try { return localStorage.getItem(NAME_KEY) ?? ""; } catch { return ""; } };

export const VERDICT: Record<Verdict, { label: string; color: string }> = {
  good_call: { label: "Good call", color: "var(--outcome-good)" },
  mixed: { label: "Mixed", color: "var(--outcome-mixed)" },
  too_lenient: { label: "Too lenient", color: "var(--outcome-bad)" },
  too_strict: { label: "Too strict", color: "var(--outcome-bad)" },
};
const VERDICT_HELP: Record<Verdict, string> = {
  good_call: "Good call", too_lenient: "Should have been stricter", too_strict: "Should have been less strict", mixed: "Mixed",
};

export interface PastState { rows: PastDecision[] | null; error: string | null; reviewing: number[]; refresh: () => void }

/** One request per snapshot, shared by the section summary and the list (App owns it). */
export function usePastDecisions(snap: Snapshot | null): PastState {
  const [n, setN] = useState(0);
  const [state, setState] = useState<{ key: string; rows: PastDecision[] | null; error: string | null; reviewing: number[] }>({ key: "", rows: null, error: null, reviewing: [] });
  const key = snap ? `${snap.snapshot_id}:${n}` : "";
  useEffect(() => {
    if (!snap) return;
    let alive = true;
    api.pastDecisions(snap.snapshot_id).then((r) => alive && setState({ key, rows: r.decisions, error: null, reviewing: r.reviewing }))
      .catch((e) => alive && setState({ key, rows: null, error: String(e.message ?? e), reviewing: [] }));
    return () => { alive = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  // Automatic AI reviews run in the background; look again shortly so they appear.
  const reviewing = state.key === key ? state.reviewing : [];
  useEffect(() => {
    if (!reviewing.length) return;
    const t = setTimeout(() => setN((x) => x + 1), 6000);
    return () => clearTimeout(t);
  }, [reviewing.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const refresh = () => setN((x) => x + 1);
  // Keep showing the previous list while a refresh loads, so open rows don't collapse.
  return state.key === key || state.key.startsWith(`${snap?.snapshot_id}:`) ? { rows: state.rows, error: state.error, reviewing, refresh } : { rows: null, error: null, reviewing: [], refresh };
}

export function pastSummary(rows: PastDecision[] | null): string {
  if (!rows) return "What was decided before in similar weather, and how it went";
  if (!rows.length) return "No past decisions recorded yet";
  const top = rows[0];
  const how = top.review ? VERDICT[top.review.verdict].label.toLowerCase() : "not reviewed yet";
  return `${rows.length} past decision${rows.length > 1 ? "s" : ""} · closest: ${fmtDayLong(top.decision_day)}, ${POSTURE_STYLE[top.decision_posture].label}, ${how}`;
}

/** Past decisions at this facility, most similar weather first (with a small bias toward recent ones). */
export function PastDecisions({ past, onViewWeather }: { past: PastState; onViewWeather: (snapshotId: string, decisionId: number) => void }) {
  const { rows, error, reviewing, refresh } = past;
  const [showAll, setShowAll] = useState(false);
  const [open, setOpen] = useState<number | null>(null);

  if (error) return <p className="text-sm text-ink2">Past decisions could not be loaded: {error}</p>;
  if (!rows) return <div className="space-y-2"><Skeleton className="h-14" /><Skeleton className="h-14" /></div>;
  if (!rows.length) return <p className="text-sm text-ink2">No past decisions are recorded for this facility yet. Each decision you confirm on Notify staff is saved here with the weather at the time.</p>;
  const list = showAll ? rows : rows.slice(0, 8);

  return (
    <div>
      <p className="mb-3 text-sm text-ink2">Sorted by how similar the weather was to now, with a slight preference for recent decisions.
        Each shows the urgency at the time, what was decided, and how it went.</p>
      <div className="mb-2 hidden grid-cols-[7.5rem_5.5rem_minmax(0,1fr)_minmax(0,1fr)_4rem] gap-3 px-3 text-xs font-semibold uppercase tracking-[0.06em] text-muted md:grid">
        <span>Date</span><span>Urgency</span><span>What was decided</span><span>How it went</span><span className="text-right">Similar</span>
      </div>
      <ul className="space-y-2">
        {list.map((r) => (
          <Row key={r.decision_id} r={r} open={open === r.decision_id} toggle={() => setOpen(open === r.decision_id ? null : r.decision_id)}
            pendingAuto={reviewing.includes(r.decision_id)} onChanged={refresh}
            onViewWeather={() => onViewWeather(r.snapshot_id, r.decision_id)} />
        ))}
      </ul>
      {rows.length > 8 && (
        <button onClick={() => setShowAll((s) => !s)} className="mt-3 text-sm text-[var(--accent)] hover:underline">
          {showAll ? "Show fewer" : `Show all ${rows.length}`}
        </button>
      )}
    </div>
  );
}

function Outcome({ r, pendingAuto }: { r: PastDecision; pendingAuto: boolean }) {
  const v = r.review;
  if (!v) {
    const due = new Date(r.review_due_at);
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5 text-xs text-ink2">
        <span aria-hidden className="h-3 w-3 rounded-full border-2 border-[var(--axis)]" />
        Not reviewed yet{pendingAuto ? " · AI reviewing…" : ` · AI review ${due.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`}
      </span>
    );
  }
  const s = VERDICT[v.verdict];
  const by = v.source === "manager" ? "manager" : v.source === "ai" ? `AI · ${Math.round((v.confidence ?? 0) * 100)}% sure`
    : `weather check · ${Math.round((v.confidence ?? 0) * 100)}% sure`;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-xs">
      <span className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-semibold text-white" style={{ background: s.color }}>
        <span aria-hidden>●</span>{s.label}
      </span>
      <span className="text-muted">{by}</span>
    </span>
  );
}

function Row({ r, open, toggle, pendingAuto, onChanged, onViewWeather }: {
  r: PastDecision; open: boolean; toggle: () => void; pendingAuto: boolean; onChanged: () => void; onViewWeather: () => void;
}) {
  const [reviewing, setReviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const askAi = async () => {
    setBusy(true); setErr(null);
    try { await api.aiReviewDecision(r.decision_id); onChanged(); }
    catch (e: any) { setErr(String(e.message ?? e)); }
    finally { setBusy(false); }
  };
  return (
    <li className="rounded-xl border border-edge">
      <button onClick={toggle} aria-expanded={open}
        className="grid w-full grid-cols-2 items-center gap-x-3 gap-y-2 rounded-xl px-3 py-2.5 text-left hover:bg-[var(--surface-2)] md:grid-cols-[7.5rem_5.5rem_minmax(0,1fr)_minmax(0,1fr)_4rem]">
        <span className="text-sm font-medium">
          {new Date(r.decision_day + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
          {r.example && <span className="ml-1.5 align-middle"><Badge>example</Badge></span>}
        </span>
        <span><CooperChip level={r.readiness_level} /></span>
        <span className="flex min-w-0 flex-wrap items-center gap-1.5">
          <PostureBadge p={r.decision_posture} size="sm" />
          <span className="text-xs text-muted">{r.followed_suggestion ? "followed the suggestion" : `changed from ${POSTURE_STYLE[r.recommended_posture].label}`}</span>
        </span>
        <Outcome r={r} pendingAuto={pendingAuto} />
        <span className="text-right text-sm tabnum text-ink2 md:block">{Math.round(r.similarity_pct)}%</span>
      </button>

      <div className="cc-collapse" data-open={open} aria-hidden={!open}>
        <div className="overflow-hidden">
          {open && (
            <div className="space-y-3 border-t border-edge px-4 py-3 text-sm">
              {r.headline && <p className="text-ink2"><span className="font-medium text-ink">The weather then: </span>{r.headline}</p>}
              <p className="text-ink2">
                Decided by <span className="font-medium text-ink">{r.decided_by}</span>
                {r.override_reason && <> · reason for changing: <span className="italic">{r.override_reason}</span></>}
              </p>
              {r.review && (
                <div className="rounded-lg bg-[var(--surface-2)] px-3 py-2">
                  <p><span className="font-medium">{VERDICT_HELP[r.review.verdict]}</span>
                    <span className="text-muted"> · {r.review.source === "manager" ? `reviewed by ${r.review.reviewer}` : r.review.source === "ai" ? "AI review" : "automatic weather check (AI unavailable)"}</span></p>
                  {r.review.note && <p className="mt-1 text-ink2">{r.review.note}</p>}
                  {r.review.observed && <p className="mt-1 text-xs text-muted">What happened: {r.review.observed}</p>}
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <button onClick={() => setReviewing((x) => !x)} className="btn min-h-[40px]">{r.review?.source === "manager" ? "Change the review" : "Review this decision"}</button>
                {r.review?.source !== "manager" && (
                  <button onClick={askAi} disabled={busy || !r.day_over} className="btn min-h-[40px]"
                    title={r.day_over ? "Compare the decision with what the weather actually did" : "The decision day has not finished yet"}>
                    {busy ? "Reviewing…" : r.review ? "Ask AI to review again" : "Ask AI to review now"}
                  </button>
                )}
                <button onClick={onViewWeather} className="btn min-h-[40px]">View weather at decision time</button>
              </div>
              {!r.day_over && !r.review && <p className="text-xs text-muted">This decision's day hasn't finished, so it can't be judged yet.</p>}
              {err && <p role="alert" className="text-sm text-[var(--danger)]">{err}</p>}
              {reviewing && <ReviewForm decisionId={r.decision_id} onDone={() => { setReviewing(false); onChanged(); }} />}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

function ReviewForm({ decisionId, onDone }: { decisionId: number; onDone: () => void }) {
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [note, setNote] = useState("");
  const [by, setBy] = useState(savedName);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    if (!verdict) return;
    setBusy(true); setErr(null);
    try {
      await api.reviewDecision(decisionId, { reviewer: by.trim(), verdict, note: note.trim() || undefined });
      try { localStorage.setItem(NAME_KEY, by.trim()); } catch { /* storage blocked */ }
      onDone();
    } catch (e: any) { setErr(`Not saved: ${e.message ?? e}`); }
    finally { setBusy(false); }
  };
  return (
    <div className="cc-rise space-y-3 rounded-xl border border-edge p-3">
      <fieldset>
        <legend className="mb-2 font-medium">How did this decision go?</legend>
        <div className="flex flex-wrap gap-2">
          {(Object.keys(VERDICT) as Verdict[]).map((v) => (
            <label key={v} className={`flex min-h-[40px] cursor-pointer items-center gap-2 rounded-lg border px-3 ${verdict === v ? "border-2" : "border-edge"}`}
              style={verdict === v ? { borderColor: VERDICT[v].color } : undefined}>
              <input type="radio" name={`verdict-${decisionId}`} checked={verdict === v} onChange={() => setVerdict(v)} />
              <span aria-hidden style={{ color: VERDICT[v].color }}>●</span>{VERDICT_HELP[v]}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="flex flex-col gap-1">
        <span className="font-medium">What happened? (optional)</span>
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} className="rounded-lg border border-edge bg-surface px-3 py-2"
          placeholder="e.g. The lot stayed icy until noon; two staff slipped on the ramp" />
      </label>
      <label className="flex max-w-sm flex-col gap-1">
        <span className="font-medium">Your name</span>
        <input value={by} onChange={(e) => setBy(e.target.value)} className="min-h-[40px] rounded-lg border border-edge bg-surface px-3" />
      </label>
      <button onClick={submit} disabled={busy || !verdict || by.trim().length < 2} className="btn btn-primary min-h-[40px]">{busy ? "Saving…" : "Save review"}</button>
      <p className="text-xs text-muted">Reviews are kept permanently. A manager's review replaces the AI's.</p>
      {err && <p role="alert" className="text-sm text-[var(--danger)]">{err}</p>}
    </div>
  );
}
