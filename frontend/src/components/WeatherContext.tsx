import type { Snapshot } from "../types";
import { useFacility } from "../facility";
import type { Mode } from "./Header";
import { fmtTime } from "../util";

export function WeatherContext({ snap, mode, saved, decisionId, demo, error, onLive }: {
  snap: Snapshot | null; mode: Mode; saved: boolean; decisionId: number | null;
  demo: boolean; error: string | null; onLive: () => void;
}) {
  const facility = useFacility();
  const historical = saved || mode === "replay";
  const tz = snap?.facility.timezone ?? facility.timezone;
  const title = saved ? `HISTORICAL DATA · Saved decision${decisionId ? ` #${decisionId}` : ""}`
    : historical ? "HISTORICAL DATA · Weather replay" : mode === "livecheck" ? "WHAT-IF CHECK" : demo ? "DEMO · Cached weather" : "LIVE";
  return <aside aria-label="Weather viewing context" className={`card border-l-4 p-4 ${historical ? "border-l-amber-500" : "border-l-[var(--accent)]"}`}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p className="text-sm font-bold tracking-wide">{title}</p>
        <p className="mt-1 text-sm">{snap?.facility.name ?? facility.name} · {snap ? fmtTime(snap.as_of, tz, {date:true, year:true}) : "Loading weather…"} · {tz}</p>
      </div>
      {(historical || mode === "livecheck") && <button className="btn" onClick={onLive}>Return to live</button>}
    </div>
    <p className="mt-2 text-xs text-ink2">{saved ? "Recorded weather evidence. Live updates are paused; camera images are saved frames only."
      : historical ? "Past weather, not today's recommendation. Only archived evidence is shown; unavailable forecasts, alerts and cameras are not replaced with live feeds."
      : mode === "livecheck" ? "A hypothetical location, not your facility's operating decision."
      : demo ? "Saved fixtures are being used. This is not a live source feed."
      : "Live viewing mode. The timestamp identifies the evaluated weather; individual sources may be older or unavailable. Review evidence warnings before deciding."}</p>
    {snap?.historical_context && <p className="mt-2 text-xs text-ink2">{snap.historical_context.reconstruction || "Historical reconstruction"} · {snap.historical_context.status}</p>}
    {!historical && error && <p role="status" className="mt-2 text-sm font-semibold">Refresh unavailable. Any displayed weather is the last successfully loaded snapshot.</p>}
    {!historical && !!snap?.sufficiency?.stale_sources.length && <p className="mt-2 text-sm font-semibold">Stale sources: {snap.sufficiency.stale_sources.join(", ")}</p>}
  </aside>;
}
