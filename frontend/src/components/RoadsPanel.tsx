import "leaflet/dist/leaflet.css";
import { useEffect, useState } from "react";
import { CircleMarker, GeoJSON, MapContainer, Polyline, TileLayer, Tooltip as LTooltip } from "react-leaflet";
import { api } from "../api";
import type { Snapshot } from "../types";
import { Card, Prov, fmtTime } from "../util";

// Ordinal road severity: one consistent scale, always shown with its text label.
export const RANK_COLOR: Record<number, string> = {
  0: "var(--good)", 1: "#7a9cc6", 2: "var(--warning)", 3: "var(--serious)", 4: "var(--critical)", 5: "#6b0f1a",
};
const cssVar = (c: string) => c.startsWith("var(") ? getComputedStyle(document.documentElement).getPropertyValue(c.slice(4, -1)).trim() || "#888" : c;

export function RoadsPanel({ snap }: { snap: Snapshot }) {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const live = snap.mode === "live";
  useEffect(() => {
    if (snap.facility.hypothetical) return;
    setErr(null);
    api.roads(live ? undefined : snap.as_of).then(setData).catch((e) => setErr(String(e.message ?? e)));
  }, [snap.snapshot_id, live, snap.as_of, snap.facility.hypothetical]);

  if (snap.facility.hypothetical) {
    return <Card title="Roads"><p className="text-sm text-ink2">Iowa DOT road conditions are Iowa-only. Unavailable for this what-if location, which lowers confidence.</p></Card>;
  }
  if (err) return <Card title="Roads"><p className="text-sm">Road data unavailable: {err}</p></Card>;
  if (!data) return <Card title="Roads"><div className="h-72 animate-pulse rounded bg-[var(--surface-2)]" /></Card>;
  const tz = snap.facility.timezone;
  const center: [number, number] = [data.facility.lat - 0.12, data.facility.lon];

  return (
    <Card title="Roads: Iowa DOT conditions on commute corridors"
      right={<span className="text-xs text-muted">
        <Prov tz={tz} source={data.source} url={data.source_url} fetched={data.fetched_at}>as of {fmtTime(data.as_of, tz)}</Prov>
      </span>}>
      {data.status !== "ok" && <p className="mb-2 rounded-md bg-[var(--surface-2)] p-2 text-sm">{data.detail}</p>}
      <div className="grid gap-4 lg:grid-cols-5">
        <div className="h-80 lg:col-span-3">
          <MapContainer key={snap.snapshot_id} center={center} zoom={9} scrollWheelZoom={false} className="h-full w-full">
            <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            {data.corridors.map((c: any) => (
              <Polyline key={c.id} positions={c.coordinates.map((p: number[]) => [p[1], p[0]])}
                pathOptions={{ color: cssVar("var(--series-1)"), weight: 12, opacity: 0.25 }}>
                <LTooltip sticky>{c.name}: {c.worst_label ?? "no report"} · {c.commuters_in_building} commuting today</LTooltip>
              </Polyline>
            ))}
            {data.geojson.features.length > 0 && (
              <GeoJSON key={`${snap.snapshot_id}-gj`} data={data.geojson}
                style={(f: any) => ({ color: cssVar(RANK_COLOR[f?.properties?.rank] ?? "#999"), weight: f?.properties?.corridors?.length ? 5 : 2.5, opacity: 0.95 })}
                onEachFeature={(f: any, layer: any) => layer.bindTooltip(
                  `${f.properties.label} (${f.properties.rank_label})<br/>reported ${fmtTime(f.properties.utc_valid?.replace("Z", ":00Z"), tz)}`, { sticky: true })} />
            )}
            <CircleMarker center={[data.facility.lat, data.facility.lon]} radius={8}
              pathOptions={{ color: cssVar("var(--surface-1)"), weight: 2, fillColor: cssVar("var(--text-primary)"), fillOpacity: 1 }}>
              <LTooltip permanent direction="right">Facility</LTooltip>
            </CircleMarker>
          </MapContainer>
        </div>
        <div className="lg:col-span-2">
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
      </div>
    </Card>
  );
}
