import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Snapshot } from "../types";
import { Badge, Card, POSTURE_STYLE, PostureBadge, fmtTime, readinessColor } from "../util";

const TZ = "America/Chicago";

export function ReplayPanel({ onSnapshot, busy, setBusy, current }: {
  onSnapshot: (s: Snapshot) => void; busy: boolean; setBusy: (b: boolean) => void; current?: Snapshot | null;
}) {
  const [events, setEvents] = useState<any[] | null>(null);
  const [eventId, setEventId] = useState<string>("");
  const [ev, setEv] = useState<any>(null);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [custom, setCustom] = useState("2023-02-22T05:00");
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api.events().then((e) => {
      setEvents(e);
      if (e.length) setEventId((cur) => cur || (e.find((x) => x.id === "ice-2023-02-22") ?? e[0]).id);
    }).catch((e) => setErr(e.message));
  }, []);

  useEffect(() => {
    if (!eventId) return;
    api.event(eventId).then((d) => {
      setEv(d);
      const four = d.timeline.findIndex((t: any) => t.as_of === d.backtest?.at_0400_local?.as_of);
      setIdx(four >= 0 ? four : 0);
    }).catch((e) => setErr(e.message));
  }, [eventId]);

  useEffect(() => {
    if (!ev || !ev.timeline[idx]) return;
    let cancelled = false;
    setBusy(true); setErr(null);
    api.replay(ev.id, ev.timeline[idx].as_of)
      .then((s) => { if (!cancelled) onSnapshot(s); })
      .catch((e) => !cancelled && setErr(e.message))
      .finally(() => !cancelled && setBusy(false));
    return () => { cancelled = true; };
  }, [ev, idx]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!playing || !ev) return;
    timer.current = window.setTimeout(() => setIdx((i) => (i + 1 < ev.timeline.length ? i + 1 : (setPlaying(false), i))), 1400);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [playing, idx, ev]);

  const runCustom = async () => {
    setBusy(true); setErr(null);
    try { onSnapshot(await api.evaluateReplay(zonedToUtc(custom, TZ).toISOString())); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  if (events && events.length === 0) {
    return <Card title="Replay"><p className="text-sm">No historical events in the database. Run <code>python -m scripts.build_history</code> in backend/ (works offline with DEMO_MODE=true once the cache exists).</p></Card>;
  }
  const t = ev?.timeline[idx];
  return (
    <Card title="Replay a past event (only data available at that moment)" right={busy ? <span className="text-xs text-muted">loading…</span> : null}>
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-sm">Event
          <select value={eventId} onChange={(e) => { setPlaying(false); setEventId(e.target.value); }} className="rounded-md border border-edge bg-surface px-2 py-1">
            {events?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </label>
        <button onClick={() => setPlaying(!playing)} disabled={!ev} className="btn">{playing ? "❚❚ Pause" : "▶ Play"}</button>
        <button onClick={() => setIdx((i) => Math.max(0, i - 1))} disabled={!ev} className="btn" aria-label="Previous hour">◀ 1h</button>
        <button onClick={() => setIdx((i) => Math.min((ev?.timeline.length ?? 1) - 1, i + 1))} disabled={!ev} className="btn" aria-label="Next hour">1h ▶</button>
        {ev?.backtest?.at_0400_local && (
          <button onClick={() => setIdx(Math.max(0, ev.timeline.findIndex((x: any) => x.as_of === ev.backtest.at_0400_local.as_of)))}
            className="btn">Jump to 04:00 on impact day</button>
        )}
        <span className="ml-auto flex items-end gap-2 text-sm">
          <label className="grid gap-1">Any moment (Central time)
            <input type="datetime-local" value={custom} onChange={(e) => setCustom(e.target.value)} className="rounded-md border border-edge bg-surface px-2 py-1" />
          </label>
          <button onClick={runCustom} disabled={busy} className="btn">Evaluate</button>
        </span>
      </div>

      {ev && (
        <>
          <input type="range" min={0} max={ev.timeline.length - 1} value={idx} onChange={(e) => { setPlaying(false); setIdx(+e.target.value); }}
            className="mt-4 w-full" aria-label="Replay time" />
          {/* posture ribbon: one cell per replayed hour */}
          <div className="mt-1 flex h-5 w-full gap-px" role="img" aria-label="Recommended posture by hour">
            {ev.timeline.map((x: any, i: number) => (
              <button key={x.as_of} title={`${fmtTime(x.as_of, TZ)}: ${POSTURE_STYLE[x.posture as keyof typeof POSTURE_STYLE].label}`}
                onClick={() => { setPlaying(false); setIdx(i); }}
                className={`h-full flex-1 ${i === idx ? "outline outline-2 outline-[var(--text-primary)]" : ""}`}
                style={{ background: POSTURE_STYLE[x.posture as keyof typeof POSTURE_STYLE].color }} />
            ))}
          </div>
          <div className="mt-px flex h-2 w-full gap-px" role="img" aria-label="Readiness (Cooper color) by hour">
            {ev.timeline.map((x: any, i: number) => (
              <span key={x.as_of} title={`${fmtTime(x.as_of, TZ)}: Condition ${x.readiness ?? "n/a"}`}
                className={`h-full flex-1 ${i === idx ? "outline outline-1 outline-[var(--text-primary)]" : ""}`}
                style={{ background: readinessColor(x.readiness), boxShadow: x.readiness === "WHITE" ? "inset 0 0 0 1px var(--border)" : undefined }} />
            ))}
          </div>
          <div className="mt-0.5 flex gap-3 text-[10px] text-muted"><span>top row: recommended posture</span><span>bottom row: readiness (Cooper color)</span></div>
          <div className="mt-1 flex justify-between text-xs text-muted tabnum">
            <span>{fmtTime(ev.timeline[0].as_of, TZ)}</span>
            <span className="font-semibold text-ink">{t ? fmtTime(t.as_of, TZ) : ""}</span>
            <span>{fmtTime(ev.timeline.at(-1).as_of, TZ)}</span>
          </div>
          <div className="mt-3 grid gap-3 text-sm md:grid-cols-3">
            <div>
              <p className="text-ink2">{ev.summary}</p>
              <p className="mt-1 text-xs">
                Verified in archive: {ev.verification.checks.map((c: any) => (
                  <a key={c.product + c.ugc} href={c.events[0]?.link} target="_blank" rel="noreferrer" className="mr-2 underline">{c.product} {c.ugc} {c.verified ? "✓" : "✗"}</a>
                ))}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase text-ink2">What actually happened</p>
              <p>{ev.outcome.summary}</p>
              {ev.outcome.amw_obs_note && <p className="text-xs italic text-muted">{ev.outcome.amw_obs_note}</p>}
            </div>
            <div>
              <p className="text-xs font-semibold uppercase text-ink2">Backtest at 04:00 on impact day</p>
              <div className="mt-1 flex flex-wrap items-center gap-2"><PostureBadge p={ev.backtest.at_0400_local.posture} size="sm" /><Badge>{ev.backtest.verdict}</Badge></div>
              <p className="mt-1 text-xs text-muted">{ev.backtest.label}</p>
            </div>
          </div>
        </>
      )}
      {current && current.mode !== "live" && current.event_id === null && <p className="mt-2 text-xs text-muted">Showing a free-form replay at {fmtTime(current.as_of, TZ)}.</p>}
      {err && <p className="mt-2 text-sm text-[var(--danger)]">{err}</p>}
    </Card>
  );
}

/** "2023-02-22T05:00" as wall-clock time in `tz` -> the UTC instant. */
function zonedToUtc(wall: string, tz: string): Date {
  const [d, t] = wall.split("T");
  const [y, m, day] = d.split("-").map(Number);
  const [hh, mm] = t.split(":").map(Number);
  const guess = Date.UTC(y, m - 1, day, hh, mm);
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
    .formatToParts(new Date(guess)).map((p) => [p.type, p.value]));
  const seen = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute);
  return new Date(guess - (seen - guess));
}
