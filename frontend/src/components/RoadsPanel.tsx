import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CircleMarker, GeoJSON, MapContainer, Marker, Polyline, TileLayer, Tooltip as LTooltip, useMap } from "react-leaflet";
import { api } from "../api";
import type { Camera, Snapshot } from "../types";
import { Card, Prov, Skeleton, fmtTime } from "../util";
import { CameraViewer } from "./CameraViewer";
import { useRoads } from "./GlanceRow";

// Ordinal road severity: one consistent scale, always shown with its text label.
export const RANK_COLOR: Record<number, string> = {
  // ordinal blue scale: pale = normal ... navy = not advised / closed (always labelled in the table/legend)
  0: "#bfdbfe", 1: "#93c5fd", 2: "#60a5fa", 3: "#2563eb", 4: "#1e3a8a", 5: "#0b1b2e",
};
const cssVar = (c: string) => c.startsWith("var(") ? getComputedStyle(document.documentElement).getPropertyValue(c.slice(4, -1)).trim() || "#888" : c;

const CAM_SVG = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/></svg>';
// Traffic cameras (live video) get a filled red dot; RWIS weather-station cameras are stills only.
const camIcon = (selected: boolean, video: boolean) => L.divIcon({
  className: "",
  html: `<span class="cc-cam${selected ? " cc-cam-on" : ""}${video ? " cc-cam-video" : ""}">${CAM_SVG}</span>`,
  iconSize: [26, 26],
  iconAnchor: [13, 13],
});

const CAMERA_REFRESH_MS = 5 * 60 * 1000;

export function RoadsPanel({ snap, savedDecisionId, historical = false }: { snap: Snapshot; savedDecisionId?: number | null; historical?: boolean }) {
  const { data, err } = useRoads(historical ? {...snap, mode:"replay"} : snap,historical);
  const [layers, setLayers] = useState({ roads: true, corridors: true, cameras: false });
  const [cams, setCams] = useState<{ status: string; detail: string | null; cameras: Camera[] } | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const live = snap.mode === "live" && !historical;

  // Cameras load only when the layer is on; they follow the replay clock and refresh while live.
  useEffect(() => {
    setCams(null);
    if (!layers.cameras || snap.facility.hypothetical) return;
    if (snap.historical_context) {setCams({status:"unavailable",detail:"Historical camera imagery unavailable for this date/time. Saved decision images and live feeds are not substituted.",cameras:[]});return;}
    let alive = true;
    const load = () => (historical ? (savedDecisionId ? api.decisionCameras(savedDecisionId) : Promise.resolve({status:"unavailable", detail:"No decision camera archive selected.", cameras:[]})) : api.cameras(live ? undefined : snap.as_of)).then((c) => { if (alive) setCams(c); })
      .catch((e) => alive && setCams({ status: "unavailable", detail: String(e.message ?? e), cameras: [] }));
    load();
    const t = live ? setInterval(load, CAMERA_REFRESH_MS) : undefined;
    return () => { alive = false; if (t) clearInterval(t); };
  }, [layers.cameras, live, snap.as_of, snap.facility.hypothetical, historical, savedDecisionId, snap.snapshot_id]);

  const visibleCams = useMemo(() => (cams?.cameras ?? []).filter((c) => !hidden.has(c.id)), [cams, hidden]);
  // Frame the traffic cameras and webcams around Ames; the far-off RWIS sites (~50+ km) stay on the map but would zoom it out too far.
  const fitCams = useMemo(() => {
    const near = visibleCams.filter((c) => c.kind !== "rwis");
    return near.length ? near : visibleCams;
  }, [visibleCams]);
  const selectedCam = visibleCams.find((c) => c.id === selected) ?? null;
  // A camera with no frame at the new replay hour simply disappears; close its viewer.
  useEffect(() => { if (selected && cams && !selectedCam) setSelected(null); }, [cams, selected, selectedCam]);
  const hide = useCallback((id: string) => { setHidden((h) => new Set(h).add(id)); setSelected(null); }, []);

  if (snap.facility.hypothetical) {
    return <Card title="Roads"><p className="text-sm text-ink2">Iowa DOT road conditions and cameras are Iowa-only. Unavailable for this what-if location, which lowers confidence.</p></Card>;
  }
  if (err) return <Card title="Roads"><p className="text-sm">Road data unavailable: {err}</p></Card>;
  if (!data) return <Card title="Roads"><Skeleton className="h-80" /></Card>;
  const tz = snap.facility.timezone;
  const center: [number, number] = [data.facility.lat - 0.12, data.facility.lon];
  const toggle = (k: keyof typeof layers) => {
    // Turning cameras off also closes the camera viewer.
    if (k === "cameras" && layers.cameras) setSelected(null);
    setLayers((l) => ({ ...l, [k]: !l[k] }));
  };

  return (
    <Card title="Roads: Iowa DOT conditions on commute corridors"
      right={<span className="text-xs text-muted">
        <Prov tz={tz} source={data.source} url={data.source_url} fetched={data.fetched_at}>as of {fmtTime(data.as_of, tz)}</Prov>
      </span>}>
      {data.status !== "ok" && <p className="mb-3 rounded-lg bg-[var(--surface-2)] px-3 py-2 text-sm text-ink2">{data.detail}</p>}
      <div className="grid gap-4 lg:grid-cols-5">
        <div className="h-96 lg:col-span-3 lg:h-auto lg:min-h-[24rem]">
          <MapContainer key={snap.snapshot_id} center={center} zoom={9} scrollWheelZoom={false} className="h-full w-full">
            <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            {layers.corridors && data.corridors.map((c: any) => (
              <Polyline key={c.id} positions={c.coordinates.map((p: number[]) => [p[1], p[0]])}
                pathOptions={{ color: "#3b82f6", weight: 14, opacity: 0.15 }}>
                <LTooltip sticky>{c.name}: {c.worst_label ?? "no report"} · {c.commuters_in_building} commuting today</LTooltip>
              </Polyline>
            ))}
            {layers.roads && data.geojson.features.length > 0 && (
              <GeoJSON key={`${snap.snapshot_id}-gj`} data={data.geojson}
                style={(f: any) => ({ color: cssVar(RANK_COLOR[f?.properties?.rank] ?? "#999"), weight: f?.properties?.corridors?.length ? 5 : 2.5, opacity: 0.95 })}
                onEachFeature={(f: any, layer: any) => layer.bindTooltip(
                  `${f.properties.label} (${f.properties.rank_label})<br/>reported ${fmtTime(f.properties.utc_valid?.replace("Z", ":00Z"), tz)}`, { sticky: true })} />
            )}
            {layers.cameras && visibleCams.map((c) => (
              <Marker key={c.id} position={[c.lat, c.lon]} icon={camIcon(c.id === selected, live && !!c.stream_url)} zIndexOffset={c.id === selected ? 1000 : 0}
                eventHandlers={{ click: () => setSelected(c.id) }} keyboard title={`${c.name} camera`}>
                <LTooltip direction="top" offset={[0, -12]}>
                  {c.name} · {live && c.stream_url ? "live video" : `${c.views.length} still view${c.views.length > 1 ? "s" : ""}`}
                </LTooltip>
              </Marker>
            ))}
            <AutoResize />
            <FitView center={center} points={layers.cameras ? fitCams.map((c) => [c.lat, c.lon] as [number, number]) : []} />
            <CircleMarker center={[data.facility.lat, data.facility.lon]} radius={8}
              pathOptions={{ color: cssVar("var(--surface-1)"), weight: 2, fillColor: cssVar("var(--text-primary)"), fillOpacity: 1 }}>
              <LTooltip permanent direction="right">Facility</LTooltip>
            </CircleMarker>
          </MapContainer>
        </div>

        <div className="flex min-w-0 flex-col gap-4 lg:col-span-2">
          {/* map layers */}
          <fieldset className="rounded-xl border border-edge p-3">
            <legend className="px-1 text-xs font-semibold uppercase tracking-[0.08em] text-muted">Map layers</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
              <LayerToggle on={layers.roads} onChange={() => toggle("roads")} label="Road conditions" />
              <LayerToggle on={layers.corridors} onChange={() => toggle("corridors")} label="Commute corridors" />
              <LayerToggle on={layers.cameras} onChange={() => toggle("cameras")}
                label={`DOT cameras${layers.cameras && cams ? ` (${visibleCams.length})` : ""}`} />
            </div>
            {layers.cameras && historical && cams?.status === "ok" && <p className="mt-2 text-xs text-muted">{cams.detail}</p>}
            {layers.cameras && cams && cams.status !== "ok" && (
              <p className="mt-2 text-xs text-muted">{cams.detail ?? "No camera images available for this time."}</p>
            )}
            {layers.cameras && cams?.status === "ok" && !selectedCam && (
              <p className="mt-2 text-xs text-muted">
                {historical ? "Click a camera to view its saved decision-time frames by angle." : "Click a camera on the map."}{live && visibleCams.some((c) => c.stream_url) && <> Cameras with a <span className="cc-cam-dot" aria-hidden /> stream live video; the others show stills.</>}
                {!live && " Replay shows weather-station and campus webcam stills archived at that time (traffic video is live only)."}
              </p>
            )}
          </fieldset>

          {selectedCam ? (
            <CameraViewer cam={selectedCam} tz={tz} live={live} onClose={() => setSelected(null)} onUnavailable={hide} />
          ) : (
            <div className="cc-fade">
              <table className="w-full text-sm">
                <thead><tr className="border-b border-edge text-left text-xs uppercase text-ink2">
                  <th className="py-1">Corridor</th><th>Worst condition</th><th className="text-right" title="Employees expected in the building today who commute on this corridor">In bldg</th>
                </tr></thead>
                <tbody>
                  {data.corridors.map((c: any) => (
                    <tr key={c.id} className="border-b border-edge/50">
                      <td className="py-1.5 pr-2">{c.name}</td>
                      <td>
                        {c.worst_rank !== null ? (
                          <span className="inline-flex items-center gap-1.5">
                            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: RANK_COLOR[c.worst_rank] }} />
                            <Prov tz={tz} source="Iowa DOT via IEM" url={data.source_url} sourceTime={c.worst_updated?.replace("Z", ":00Z")} fetched={data.fetched_at}>
                              {c.worst_label}
                            </Prov>
                          </span>
                        ) : <span className="text-muted">No report</span>}
                      </td>
                      <td className="text-right tabnum">{c.commuters_in_building}</td>
                    </tr>
                  ))}
                  <tr><td className="py-1.5 text-ink2">Local Ames streets (no DOT data)</td><td /><td className="text-right tabnum">{data.local_commuters_in_building}</td></tr>
                </tbody>
              </table>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                {Object.entries(data.rank_labels).map(([k, v]) => (
                  <span key={k} className="inline-flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: RANK_COLOR[+k] }} />{String(v)}</span>
                ))}
              </div>
              <p className="mt-2 text-xs text-muted">Segments are matched to corridors by geometry (within 2 km). Corridor lines are approximate; employee counts are synthetic.</p>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

function LayerToggle({ on, onChange, label }: { on: boolean; onChange: () => void; label: string }) {
  return (
    <span className="flex select-none items-center gap-2">
      <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={onChange}
        className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${on ? "bg-[var(--accent)]" : "bg-[var(--axis)]"}`}>
        <span className={`absolute left-0 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform duration-200 ${on ? "translate-x-[18px]" : "translate-x-0.5"}`} />
      </button>
      <span className="cursor-pointer" onClick={onChange}>{label}</span>
    </span>
  );
}

/** Glide out to fit the cameras when that layer turns on, and back to the facility view when it turns off. */
/** Leaflet must be told when its container changes size (e.g. the camera viewer makes the row taller). */
function AutoResize() {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    const ro = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [map]);
  return null;
}

function FitView({ center, points }: { center: [number, number]; points: [number, number][] }) {
  const map = useMap();
  const key = points.map((p) => p.join(",")).join(";");
  useEffect(() => {
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (points.length) {
      const b = L.latLngBounds([...points, center]);
      reduce ? map.fitBounds(b, { padding: [24, 24] }) : map.flyToBounds(b, { padding: [24, 24], duration: 0.8 });
    } else {
      reduce ? map.setView(center, 9) : map.flyTo(center, 9, { duration: 0.6 });
    }
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}
