import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { parseReplayTime } from "../replay";
import type { ReplayEvent, ReplayPoint, Snapshot } from "../types";
import { Badge, Card, POSTURE_STYLE, PostureBadge, fmtTime, readinessColor } from "../util";

const TZ = "America/Chicago";
const MISSING = "repeating-linear-gradient(135deg, var(--border) 0 3px, var(--surface-1) 3px 6px)";
type Selection = { event: ReplayEvent | null; timeline: ReplayPoint[]; index: number; timezone: string; note?: string };
type LoadedSelection = { selection: Selection; snapshot: Snapshot };

export function LegacyReplayPanel({ onSnapshot, busy, setBusy, current }: {
  onSnapshot: (s: Snapshot) => void; busy: boolean; setBusy: (b: boolean) => void; current?: Snapshot | null;
}) {
  const [events, setEvents] = useState<ReplayEvent[] | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [playing, setPlaying] = useState(false);
  const [custom, setCustom] = useState("2023-02-22T05:00");
  const [err, setErr] = useState<string | null>(null);
  const [catalogErr, setCatalogErr] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const interacted = useRef(false);

  // The report, cursor and both ribbons commit together. Aborting plus checking
  // request identity also protects against responses already being decoded.
  const loadSelection = useCallback(async (load: (signal: AbortSignal) => Promise<LoadedSelection>, label: string) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setPending(label); setErr(null);
    try {
      const result = await load(controller.signal);
      if (request.current !== controller || controller.signal.aborted) return;
      const point = result.selection.timeline[result.selection.index];
      if (!point || new Date(point.as_of).getTime() !== new Date(result.snapshot.as_of).getTime()) {
        throw new Error("The report does not match the selected timeline hour.");
      }
      const timeline = result.selection.timeline.map((p, i) => i === result.selection.index && p.coverage !== "unavailable"
        ? { ...p, posture: result.snapshot.posture.posture, readiness: result.snapshot.readiness?.level ?? null } : p);
      setSelection({ ...result.selection, timeline });
      onSnapshot(result.snapshot);
    } catch (e) {
      if (request.current !== controller || controller.signal.aborted) return;
      controller.abort();
      setPlaying(false);
      setErr(`Could not load ${label}: ${e instanceof Error ? e.message : String(e)}. The report and timeline have not changed.`);
    } finally {
      if (request.current === controller) {
        request.current = null;
        setBusy(false); setPending(null);
      }
    }
  }, [onSnapshot, setBusy]);

  const loadEvent = useCallback((id: string, label = "event replay") => loadSelection(async (signal) => {
    const event = await api.event(id, signal);
    if (!event.timeline.length) throw new Error("This event has no recorded timeline. Choose a custom date instead.");
    const four = event.timeline.findIndex((t) => t.as_of === event.backtest?.at_0400_local?.as_of);
    const index = four >= 0 ? four : 0;
    const snapshot = await api.replay(id, event.timeline[index].as_of, signal);
    return { selection: { event, timeline: event.timeline, index, timezone: snapshot.facility?.timezone ?? TZ }, snapshot };
  }, label), [loadSelection]);

  // Catalog loading must not supersede a custom selection made while it loads.
  useEffect(() => {
    const controller = new AbortController();
    api.events(controller.signal).then((list) => {
      if (controller.signal.aborted) return;
      setEvents(list);
      if (list.length && !interacted.current) {
        const event = list.find((e) => e.id === "ice-2023-02-22") ?? list[0];
        void loadEvent(event.id, event.name);
      }
    }).catch((e) => { if (!controller.signal.aborted) setCatalogErr(e.message); });
    return () => controller.abort();
  }, [loadEvent]);

  useEffect(() => () => {
    request.current?.abort(); request.current = null;
    setBusy(false);
  }, [setBusy]);

  const loadPoint = useCallback((active: Selection, index: number) => loadSelection(async (signal) => {
    const asOf = active.timeline[index].as_of;
    const snapshot = active.event ? await api.replay(active.event.id, asOf, signal)
      : await api.evaluateReplay(asOf, undefined, signal);
    return { selection: { ...active, index }, snapshot };
  }, fmtTime(active.timeline[index].as_of, active.timezone)), [loadSelection]);

  useEffect(() => {
    if (!playing || !selection || pending) return;
    if (selection.index >= selection.timeline.length - 1) { setPlaying(false); return; }
    const timer = window.setTimeout(() => void loadPoint(selection, selection.index + 1), 1400);
    return () => clearTimeout(timer);
  }, [playing, selection, pending, loadPoint]);

  const tz = selection?.timezone ?? current?.facility?.timezone ?? TZ;
  const runCustom = () => {
    interacted.current = true; setPlaying(false);
    let parsed: ReturnType<typeof parseReplayTime>;
    try { parsed = parseReplayTime(custom, tz); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); return; }
    void loadSelection(async (signal) => {
      // Load the cheap timeline first; a failed timeline never starts an AI brief.
      const context = await api.replayTimeline(parsed.asOf, signal);
      if (signal.aborted) throw new DOMException("Replay cancelled", "AbortError");
      const snapshot = await api.evaluateReplay(parsed.asOf, undefined, signal);
      return { selection: { event: null, timeline: context.timeline, index: context.selected_index, timezone: context.timezone,
        note: parsed.ambiguous ? "This local hour occurs twice when clocks move back. Showing its first occurrence; step forward one hour to view the second." : undefined }, snapshot };
    }, `${custom.replace("T", " ")} (${tz})`);
  };
  const selectPoint = (index: number) => {
    interacted.current = true; setPlaying(false);
    if (selection) void loadPoint(selection, index);
  };
  const ev = selection?.event;
  const idx = selection?.index ?? 0;
  const timeline = selection?.timeline ?? [];
  const point = timeline[idx];
  const format = (iso: string) => new Date(iso).toLocaleString("en-US", { timeZone: tz,
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZoneName: "short" });
  const coverage = (p: ReplayPoint) => p.coverage === "unavailable" ? "; historical data unavailable"
    : p.coverage === "partial" ? `; incomplete evidence (${p.unavailable_sources?.join(", ") || "some sources unavailable"})` : "";

  return (
    <Card title="Replay a past event (only data available at that moment)" right={busy ? <span className="text-xs text-muted">loading…</span> : null}>
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-sm">Event
          <select value={ev?.id ?? ""} onChange={(e) => {
            if (!e.target.value) return;
            interacted.current = true; setPlaying(false); void loadEvent(e.target.value, events?.find((item) => item.id === e.target.value)?.name);
          }} className="rounded-md border border-edge bg-surface px-2 py-1">
            <option value="" disabled>{selection && !ev ? "Custom date" : "Choose an event"}</option>
            {events?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </label>
        <button onClick={() => setPlaying(!playing)} disabled={!selection || (!playing && !!pending) || idx >= timeline.length - 1} className="btn">{playing ? "❚❚ Pause" : "▶ Play"}</button>
        <button onClick={() => selectPoint(idx - 1)} disabled={!selection || idx === 0} className="btn" aria-label="Previous hour">◀ 1h</button>
        <button onClick={() => selectPoint(idx + 1)} disabled={!selection || idx >= timeline.length - 1} className="btn" aria-label="Next hour">1h ▶</button>
        {ev?.backtest?.at_0400_local && (
          <button onClick={() => selectPoint(Math.max(0, timeline.findIndex((x) => x.as_of === ev.backtest.at_0400_local.as_of)))}
            className="btn">Jump to 04:00 on impact day</button>
        )}
        <span className="ml-auto flex items-end gap-2 text-sm">
          <label className="grid gap-1">{tz === TZ ? "Any moment (Central time)" : `Any moment (${tz})`}
            <input type="datetime-local" value={custom} onChange={(e) => setCustom(e.target.value)} className="rounded-md border border-edge bg-surface px-2 py-1" />
          </label>
          <button onClick={runCustom} className="btn">Evaluate</button>
        </span>
      </div>
      <p className="mt-2 text-xs text-muted">Hourly colors use historical evidence and the rules engine. Only the selected report generates an AI brief; the manager makes the final decision.</p>
      {pending && <p role="status" className="mt-2 text-sm text-muted">Loading {pending}… The report and timeline will update together.</p>}
      {events?.length === 0 && <p className="mt-2 text-xs text-muted">No catalog events are available. You can still evaluate a custom date.</p>}
      {catalogErr && <p className="mt-2 text-xs text-muted">Event catalog unavailable: {catalogErr}. You can still evaluate a custom date.</p>}

      {selection && point && (
        <>
          <p className="mt-3 text-sm font-semibold" data-testid="replay-context">{ev ? ev.name : "Custom date replay · 12 hours before and after the requested time"}</p>
          <input type="range" min={0} max={timeline.length - 1} value={idx} onChange={(e) => selectPoint(+e.target.value)}
            className="mt-2 w-full" aria-label="Replay time" aria-valuetext={format(point.as_of)} />
          <div className="mt-1 flex h-5 w-full gap-px" role="group" aria-label="Recommended posture by hour">
            {timeline.map((x, i) => {
              const title = `${format(x.as_of)}: ${x.posture ? POSTURE_STYLE[x.posture].label : "Unavailable"}${coverage(x)}`;
              return <button key={x.as_of} title={title} aria-label={title} aria-pressed={i === idx}
                onClick={() => selectPoint(i)}
                className={`h-full flex-1 origin-bottom transition-transform duration-150 hover:scale-y-125 ${i === idx ? "outline outline-2 outline-[var(--text-primary)]" : ""}`}
                style={{ background: x.posture ? POSTURE_STYLE[x.posture].color : MISSING }} />;
            })}
          </div>
          <div className="mt-px flex h-2 w-full gap-px" role="img" aria-label="Readiness (Cooper color) by hour">
            {timeline.map((x, i) => (
              <span key={x.as_of} title={`${format(x.as_of)}: ${x.readiness ? `Condition ${x.readiness}` : "Unavailable"}${coverage(x)}`}
                data-selected={i === idx || undefined}
                className={`h-full flex-1 ${i === idx ? "outline outline-1 outline-[var(--text-primary)]" : ""}`}
                style={{ background: x.readiness ? readinessColor(x.readiness) : MISSING, boxShadow: x.readiness === "WHITE" ? "inset 0 0 0 1px var(--border)" : undefined }} />
            ))}
          </div>
          <div className="mt-0.5 flex flex-wrap gap-3 text-[10px] text-muted"><span>top row: recommended posture</span><span>bottom row: readiness (Cooper color)</span>{!ev && <span>striped cells: historical data unavailable</span>}</div>
          <div className="mt-1 flex flex-wrap justify-between gap-2 text-xs text-muted tabnum">
            <span>{format(timeline[0].as_of)}</span>
            <span className="font-semibold text-ink" data-testid="replay-selected-time">{format(point.as_of)}</span>
            <span>{format(timeline.at(-1)!.as_of)}</span>
          </div>
          {selection.note && <p className="mt-2 text-xs text-muted">{selection.note}</p>}
          {!ev && timeline.some((p) => p.coverage !== "complete") && <p className="mt-2 text-xs text-muted">Historical coverage varies by hour. Incomplete evidence is marked in each hour’s tooltip; missing evidence does not mean conditions are safe.</p>}
          {ev && <div className="mt-3 grid gap-3 text-sm md:grid-cols-3">
            <div>
              <p className="text-ink2">{ev.summary}</p>
              <p className="mt-1 text-xs">Verified in archive: {ev.verification.checks.map((c) => (
                <a key={c.product + c.ugc} href={c.events[0]?.link} target="_blank" rel="noreferrer" className="mr-2 underline">{c.product} {c.ugc} {c.verified ? "✓" : "✗"}</a>
              ))}</p>
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
          </div>}
        </>
      )}
      {err && <p role="alert" className="mt-2 text-sm text-[var(--danger)]">{err}</p>}
    </Card>
  );
}
