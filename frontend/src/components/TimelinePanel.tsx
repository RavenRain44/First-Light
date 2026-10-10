import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api";
import type { Snapshot } from "../types";
import { Card, fmtTime } from "../util";

type Row = Record<string, number | string> & { ts: number };

interface SeriesDef { key: string; name: string; color: string; dash?: string }
interface ChartDef { id: string; title: string; unit: string; series: SeriesDef[]; lineChart: string; minMax?: number; lines?: "always" | "near" }

const CHARTS: ChartDef[] = [
  { id: "wind", title: "Wind gust", unit: "mph", lineChart: "wind", minMax: 60, lines: "always",
    series: [{ key: "obs_wind_gust_mph", name: "Observed gust", color: "var(--series-1)" },
             { key: "fcst_wind_gust_mph", name: "Forecast gust", color: "var(--series-2)" }] },
  { id: "temp", title: "Temperature / feels-like", unit: "°F", lineChart: "temp", lines: "near",
    series: [{ key: "obs_temp_f", name: "Observed temp", color: "var(--series-1)" },
             { key: "fcst_temp_f", name: "Forecast temp", color: "var(--series-2)" },
             { key: "fcst_apparent_temp_f", name: "Forecast feels-like", color: "var(--series-2)", dash: "4 3" }] },
  { id: "ice", title: "Forecast ice accumulation (running total)", unit: "in", lineChart: "ice_cum", minMax: 0.3, lines: "always",
    series: [{ key: "fcst_ice_cum", name: "Forecast ice (cumulative)", color: "var(--series-2)" }] },
  { id: "snow", title: "Forecast snowfall (running total)", unit: "in", lineChart: "snow_cum", minMax: 7, lines: "always",
    series: [{ key: "fcst_snow_cum", name: "Forecast snow (cumulative)", color: "var(--series-2)" }] },
  { id: "pop", title: "Precipitation probability", unit: "%", lineChart: "pop", minMax: 100,
    series: [{ key: "fcst_pop_pct", name: "Forecast PoP", color: "var(--series-2)" }] },
];

export function TimelinePanel({ snap }: { snap: Snapshot }) {
  const [ts, setTs] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setErr(null);
    api.timeseries(snap.snapshot_id).then(setTs).catch((e) => setErr(String(e.message ?? e)));
  }, [snap.snapshot_id]);

  const tz = snap.facility.timezone;
  const rows: Row[] = useMemo(() => (ts?.rows ?? []).map((r: any) => ({ ...r, ts: new Date(r.t).getTime() })), [ts]);
  const asOf = new Date(snap.as_of).getTime();
  if (err) return <Card title="Conditions timeline"><p className="text-sm">Could not load chart data: {err}</p></Card>;
  if (!ts) return <Card title="Conditions timeline"><div className="h-64 animate-pulse rounded bg-[var(--surface-2)]" /></Card>;
  const domain: [number, number] = [asOf - 12 * 3600e3, asOf + 48 * 3600e3];
  const tick = (v: number) => new Date(v).toLocaleString("en-US", { timeZone: tz, weekday: "short", hour: "2-digit", hour12: false });

  return (
    <Card title="Conditions timeline" right={<span className="text-xs text-muted">past 12 h observed (IEM ASOS) · next 48 h forecast · shaded: commute windows (blue), facility hours (gray)</span>}>
      <div className="grid gap-4 lg:grid-cols-2">
        {CHARTS.map((c) => {
          const present = c.series.filter((s) => rows.some((r) => typeof r[s.key] === "number"));
          if (!present.length) {
            return (
              <div key={c.id} className="rounded-lg border border-dashed border-edge p-3 text-sm text-ink2">
                <h3 className="font-semibold text-ink">{c.title}</h3>
                No data for this series from the available sources.
              </div>
            );
          }
          const vals = rows.flatMap((r) => present.map((s) => r[s.key])).filter((v): v is number => typeof v === "number");
          const dataMax = Math.max(...vals);
          const dataMin = Math.min(...vals);
          const lines = (ts.threshold_lines as any[]).filter((l) => l.chart === c.lineChart)
            .filter((l) => c.lines === "always" || (l.value >= dataMin - 15 && l.value <= dataMax + 15));
          const yMax = Math.max(dataMax, c.minMax ?? dataMax, ...lines.map((l) => l.value)) * 1.08;
          const yMin = Math.min(c.id === "temp" ? dataMin - 5 : 0, ...lines.map((l) => l.value));
          return (
            <figure key={c.id} className="min-w-0">
              <figcaption className="mb-1 flex items-baseline justify-between text-sm">
                <span className="font-semibold">{c.title} <span className="font-normal text-muted">({c.unit})</span></span>
              </figcaption>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={rows} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
                    <CartesianGrid stroke="var(--grid)" vertical={false} />
                    {(ts.windows as any[]).map((w, i) => (
                      <ReferenceArea key={i} x1={new Date(w.start).getTime()} x2={new Date(w.end).getTime()} ifOverflow="hidden"
                        fill={w.kind === "hours" ? "var(--shade-hours)" : "var(--shade-commute)"} strokeOpacity={0} />
                    ))}
                    <XAxis dataKey="ts" type="number" domain={domain} scale="time" tickFormatter={tick} stroke="var(--axis)"
                      tick={{ fill: "var(--text-muted)", fontSize: 11 }} minTickGap={40} allowDataOverflow />
                    <YAxis domain={[Math.floor(yMin), c.unit === "in" ? +yMax.toFixed(2) : Math.ceil(yMax)]} stroke="var(--axis)"
                      tick={{ fill: "var(--text-muted)", fontSize: 11 }} width={44} allowDataOverflow />
                    {lines.map((l) => (
                      <ReferenceLine key={l.rule_id} y={l.value} stroke="var(--text-secondary)" strokeDasharray="6 4" strokeWidth={1}
                        label={{ value: `${l.value}${l.verified ? "" : " ⚠"}`, position: "insideTopRight", fill: "var(--text-secondary)", fontSize: 10 }} />
                    ))}
                    <ReferenceLine x={asOf} stroke="var(--text-primary)" strokeWidth={1.5}
                      label={{ value: "as of", position: "insideTopLeft", fill: "var(--text-primary)", fontSize: 10 }} />
                    <Tooltip content={<ProvTooltip tz={tz} meta={ts.meta} unit={c.unit} />} />
                    {present.length > 1 && <Legend wrapperStyle={{ fontSize: 12, color: "var(--text-secondary)" }} />}
                    {present.map((s) => (
                      <Line key={s.key} dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={2} strokeDasharray={s.dash}
                        dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface-1)" }} connectNulls isAnimationActive={false} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </figure>
          );
        })}
      </div>
      <details className="mt-3 text-xs text-ink2">
        <summary>Threshold lines on these charts</summary>
        <ul className="mt-1 list-disc pl-5">
          {(ts.threshold_lines as any[]).map((l) => <li key={l.rule_id}>{l.label} → {l.level}{l.verified ? "" : " (⚠ unverified)"}</li>)}
        </ul>
      </details>
    </Card>
  );
}

function ProvTooltip({ active, payload, label, tz, meta, unit }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="max-w-xs rounded-lg border border-edge bg-surface p-2 text-xs shadow-lg">
      <div className="mb-1 font-semibold">{fmtTime(new Date(label).toISOString(), tz)}</div>
      {payload.map((p: any) => {
        const baseKey = String(p.dataKey).replace("_cum", "_in");
        const m = meta?.[baseKey];
        return (
          <div key={p.dataKey} className="mb-1">
            <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: p.color }} />
            <span className="text-ink">{p.name}: <strong className="tabnum">{typeof p.value === "number" ? p.value.toFixed(unit === "in" ? 2 : 0) : p.value} {unit}</strong></span>
            {m && <div className="pl-3 text-muted">{m.source} · issued {fmtTime(m.source_time, tz)} · fetched {fmtTime(m.fetched_at, tz)}</div>}
          </div>
        );
      })}
    </div>
  );
}
