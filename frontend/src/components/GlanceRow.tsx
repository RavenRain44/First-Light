import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import type { Snapshot } from "../types";
import { latest, maxAhead } from "../util";

// One roads request per snapshot time, shared by the glance tile and the roads map.
const roadsCache = new Map<string, Promise<any>>();
export function useRoads(snap: Snapshot): { data: any; err: string | null } {
  const live = snap.mode === "live";
  const key = live ? `live:${snap.snapshot_id}` : snap.as_of;
  const [state, setState] = useState<{ key: string; data: any; err: string | null } | null>(null);
  useEffect(() => {
    if (snap.facility.hypothetical) return;
    let alive = true;
    if (!roadsCache.has(key)) roadsCache.set(key, api.roads(live ? undefined : snap.as_of).catch((e) => { roadsCache.delete(key); throw e; }));
    roadsCache.get(key)!.then((data) => alive && setState({ key, data, err: null }))
      .catch((e) => alive && setState({ key, data: null, err: String(e.message ?? e) }));
    return () => { alive = false; };
  }, [key, live, snap.as_of, snap.facility.hypothetical]);
  return state?.key === key ? { data: state.data, err: state.err } : { data: null, err: null };
}

/** Three plain-language tiles: weather right now, alerts, and commute roads. Each opens its section. */
export function GlanceRow({ snap, onOpen }: { snap: Snapshot; onOpen: (section: "charts" | "alerts" | "roads") => void }) {
  const temp = latest(snap, "obs.temp_f");
  const feels = latest(snap, "obs.apparent_temp_f");
  const wind = latest(snap, "obs.wind_speed_mph");
  const gust = latest(snap, "obs.wind_gust_mph") ?? latest(snap, "obs.peak_gust_mph");
  const rain = maxAhead(snap, "fcst.pop_pct", 12);
  const snow = maxAhead(snap, "fcst.snow_in", 24);
  const alerts = snap.inputs.filter((i) => i.kind === "alert").map((i) => (i.data as any)?.event as string).filter(Boolean);
  const roads = useRoads(snap);

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <Tile label="Weather now" onClick={() => onOpen("charts")} action="Forecast charts">
        {temp ? (
          <>
            <p className="text-2xl font-semibold tabnum">{Math.round(temp.v)}°F
              {feels && Math.abs(feels.v - temp.v) >= 5 && <span className="ml-2 text-base font-normal text-ink2">feels like {Math.round(feels.v)}°</span>}
            </p>
            <p className="text-sm text-ink2">
              Wind {wind ? `${Math.round(wind.v)} mph` : "n/a"}{gust && wind && gust.v > wind.v + 5 ? `, gusts ${Math.round(gust.v)}` : ""}
              {rain !== null && <> · {Math.round(rain)}% chance of precipitation in the next 12 h</>}
              {snow !== null && snow >= 0.5 && <> · {snow.toFixed(1)} in snow forecast</>}
            </p>
          </>
        ) : <p className="text-sm text-ink2">No current observation available.</p>}
      </Tile>

      <Tile label="Weather alerts" onClick={() => onOpen("alerts")} action={alerts.length ? "Read alerts" : "Details"} warn={alerts.length > 0}>
        {alerts.length ? (
          <>
            <p className="text-2xl font-semibold">{alerts.length} active</p>
            <p className="truncate text-sm text-ink2" title={alerts.join(", ")}>{[...new Set(alerts)].join(", ")}</p>
          </>
        ) : (
          <>
            <p className="text-2xl font-semibold">None</p>
            <p className="text-sm text-ink2">No National Weather Service alerts here.</p>
          </>
        )}
      </Tile>

      <Tile label="Commute roads" onClick={() => onOpen("roads")} action="Map & cameras">
        <RoadsSummary snap={snap} roads={roads} />
      </Tile>
    </div>
  );
}

function RoadsSummary({ snap, roads }: { snap: Snapshot; roads: { data: any; err: string | null } }) {
  if (snap.facility.hypothetical) return <p className="text-sm text-ink2">Road reports cover Iowa only.</p>;
  if (roads.err) return <p className="text-sm text-ink2">Road reports unavailable right now.</p>;
  if (!roads.data) return <div className="skeleton h-10" aria-hidden />;
  const reported = (roads.data.corridors ?? []).filter((c: any) => c.worst_rank !== null);
  if (!reported.length) return <><p className="text-2xl font-semibold">No reports</p><p className="text-sm text-ink2">Iowa DOT has no current reports for the commute routes.</p></>;
  const bad = reported.filter((c: any) => c.worst_rank > 0).sort((a: any, b: any) => b.worst_rank - a.worst_rank);
  if (!bad.length) return <><p className="text-2xl font-semibold">Normal</p><p className="text-sm text-ink2">All {reported.length} commute routes report normal conditions.</p></>;
  return (
    <>
      <p className="text-2xl font-semibold">{bad[0].worst_label}</p>
      <p className="truncate text-sm text-ink2" title={bad.map((c: any) => `${c.name}: ${c.worst_label}`).join("\n")}>
        On {bad[0].name}{bad.length > 1 ? ` and ${bad.length - 1} other route${bad.length > 2 ? "s" : ""}` : ""}
      </p>
    </>
  );
}

function Tile({ label, action, onClick, warn = false, children }: {
  label: string; action: string; onClick: () => void; warn?: boolean; children: ReactNode;
}) {
  return (
    <button onClick={onClick}
      className={`card flex min-h-[44px] flex-col gap-1 p-4 text-left hover:border-[var(--accent)] ${warn ? "border-l-4 border-l-[var(--danger)]" : ""}`}>
      <span className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">{label}</span>
      <span className="min-w-0">{children}</span>
      <span className="mt-auto pt-1 text-sm text-[var(--accent)]">{action} →</span>
    </button>
  );
}
