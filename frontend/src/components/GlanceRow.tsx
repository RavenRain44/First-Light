import { useEffect, useState, type ReactNode } from "react";
import { api, selectedApiGeneration } from "../api";
import type { Snapshot } from "../types";
import { latest, maxAhead } from "../util";

// One roads request per snapshot time, shared by the glance tile and the roads map.
const roadsCache = new Map<string, Promise<any>>();
export function useRoads(snap: Snapshot, frozen = false): { data: any; err: string | null } {
  const live = snap.mode === "live";
  const historicalContext = snap.historical_context ?? (frozen ? true : undefined);
  const key = `${selectedApiGeneration()}:${snap.facility_id}:${live ? `live:${snap.snapshot_id}` : snap.as_of}`;
  const [state, setState] = useState<{ key: string; data: any; err: string | null } | null>(null);
  useEffect(() => {
    if (snap.facility.hypothetical || historicalContext) return;
    let alive = true;
    if (!roadsCache.has(key)) roadsCache.set(key, api.roads(live ? undefined : snap.as_of).catch((e) => { roadsCache.delete(key); throw e; }));
    roadsCache.get(key)!.then((data) => alive && setState({ key, data, err: null }))
      .catch((e) => alive && setState({ key, data: null, err: String(e.message ?? e) }));
    return () => { alive = false; };
  }, [key, live, snap.as_of, snap.facility.hypothetical, historicalContext]);
  if (historicalContext) {
    const roads = snap.inputs.filter(i=>i.kind==='road');
    return {err:null,data:{as_of:snap.as_of,status:roads.length?'partial':'unavailable',detail:roads.length?'Historical corridor summaries saved in this reconstruction; statewide geometry unavailable.':'Road archive not supplied for this reconstruction. Current roads are not substituted.',source:'Saved historical corridor evidence',source_url:roads[0]?.source_url,fetched_at:roads[0]?.fetched_at,rank_labels:{0:'Seasonal / normal',1:'Wet or frost',2:'Partially covered',3:'Completely covered',4:'Travel advisory',5:'Travel not advised / closed'},geojson:{type:'FeatureCollection',features:[]},facility:snap.facility,corridors:snap.facility.corridors.map(c=>{const input=roads.find(i=>i.data?.corridor===c.id);return {...c,worst_rank:input?.value??null,worst_rank_label:input?.data?.rank_label??'No report',worst_label:input?.data?.label,worst_updated:input?.source_time,n_segments:input?.data?.n_segments??0,commuters_in_building:snap.roster?.commuters_by_corridor?.[c.id]??0,commuters_assigned:0};}),local_commuters_in_building:snap.roster?.commuters_by_corridor?.local??0}};
  }
  return state?.key === key ? { data: state.data, err: state.err } : { data: null, err: null };
}

/** Three plain-language tiles: weather right now, alerts, and commute roads. Each opens its section. */
export function GlanceRow({ snap, onOpen, historical = false }: { snap: Snapshot; historical?: boolean; onOpen: (section: "charts" | "alerts" | "roads") => void }) {
  const temp = latest(snap, "obs.temp_f");
  const feels = latest(snap, "obs.apparent_temp_f");
  const wind = latest(snap, "obs.wind_speed_mph");
  const gust = latest(snap, "obs.wind_gust_mph") ?? latest(snap, "obs.peak_gust_mph");
  const rain = maxAhead(snap, "fcst.pop_pct", 12);
  const snow = maxAhead(snap, "fcst.snow_in", 24);
  const alerts = snap.inputs.filter((i) => i.kind === "alert").map((i) => (i.data as any)?.event as string).filter(Boolean);
  const roads = useRoads(snap,historical);

  return (
    <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-3">
      <Tile label={snap.mode==='live'&&!historical?'Weather now':'Weather at evaluation'} onClick={() => onOpen("charts")} action="Forecast charts">
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
            <p className="text-2xl font-semibold">{snap.historical_context ? "Not supplied" : "None"}</p>
            <p className="text-sm text-ink2">{snap.historical_context ? "No alert inputs; historical alert coverage may be unavailable." : "No National Weather Service alerts here."}</p>
          </>
        )}
      </Tile>

      <Tile label="Commute roads" onClick={() => onOpen("roads")} action="Map & cameras">
        <RoadsSummary snap={historical?{...snap,mode:'replay'}:snap} roads={roads} />
      </Tile>
    </div>
  );
}

function RoadsSummary({ snap, roads }: { snap: Snapshot; roads: { data: any; err: string | null } }) {
  if (snap.facility.hypothetical) return <p className="text-sm text-ink2">Road coverage is not configured for this what-if location.</p>;
  if (roads.err) return <p className="text-sm text-ink2">Road reports unavailable right now.</p>;
  if (!roads.data) return <div className="skeleton h-10" aria-hidden />;
  if (["unavailable", "not_applicable"].includes(roads.data.status)) return <><p className="text-2xl font-semibold">Unavailable</p><p className="text-sm text-ink2">{roads.data.detail ?? "Road conditions could not be verified for this facility."}</p></>;
  const reported = (roads.data.corridors ?? []).filter((c: any) => c.worst_rank !== null);
  if (!reported.length) return <><p className="text-2xl font-semibold">No reports</p><p className="text-sm text-ink2">{snap.mode!=='live' ? 'Historical corridor reports unavailable for this context.' : 'No current DOT reports match the commute routes.'}</p></>;
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
      className={`card flex min-h-[44px] min-w-0 flex-col gap-1 p-4 text-left hover:border-[var(--accent)] ${warn ? "border-l-4 border-l-[var(--danger)]" : ""}`}>
      <span className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">{label}</span>
      <span className="min-w-0">{children}</span>
      <span className="mt-auto pt-1 text-sm text-[var(--accent)]">{action} →</span>
    </button>
  );
}
