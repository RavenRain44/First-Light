import { useId, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { metricDomain, metricEvidence, type MetricDefinition } from "../dashboard";
import type { Snapshot, Timeseries } from "../types";
import { fmtTime, fmtVal } from "../util";

export function MetricChart({ snap, metric, data, compact = false }: {
  snap: Snapshot; metric: MetricDefinition; data: Timeseries; compact?: boolean;
}) {
  const id = useId();
  const [full, setFull] = useState(false);
  const evidence = metricEvidence(snap, metric, data);
  const { rows, rule, context, window, highlighted, keys } = evidence;
  const tz = snap.facility.timezone;
  const asOf = new Date(snap.as_of).getTime();
  const available = metric.series.filter((s) => rows.some((row) => typeof row[s.key] === "number"));
  const seriesName = (s: MetricDefinition["series"][number]) => `${s.name}${data.meta[s.key]?.derived ? " (calculated)" : ""}${data.meta[s.key.replace("_cum", "_in")]?.provenance?.weather_fallback ? " (backup forecast)" : ""}`;
  const domain = metricDomain(snap, metric, evidence, full);
  const ticks = Array.from({ length: 5 }, (_, i) => domain[0] + (domain[1] - domain[0]) * i / 4);
  const visible = rows.filter((row) => row.ts >= domain[0] && row.ts <= domain[1]);
  const candidates = visible.flatMap((row) => keys.flatMap((key) => typeof row[key] === "number"
    ? [{ ts: row.ts, value: row[key] as number }] : []));
  const peak = candidates.sort((a, b) => metric.id === "temp" ? a.value - b.value : b.value - a.value)[0];
  const values = visible.flatMap((row) => available.flatMap((s) => typeof row[s.key] === "number" ? [row[s.key] as number] : []));
  const low = Math.min(0, ...values, rule?.threshold ?? 0);
  const high = Math.max(...values, rule?.threshold ?? 0, metric.unit === "in" ? 0.01 : 1);
  const pad = Math.max((high - low) * 0.12, metric.unit === "in" ? 0.02 : 1);
  const format = (value: number) => metric.unit === "sensors" ? `${value} sensor${value === 1 ? "" : "s"}`
    : fmtVal(value, metric.unit === "°F" ? "degF" : metric.unit);
  const tick = (value: number) => new Date(value).toLocaleString("en-US", { timeZone: tz, month: "short", day: "numeric", hour: "numeric", hour12: false });
  const label = rule?.triggered ? "Threshold crossed" : context ? "Hazard window" : "Weather context";
  return (
    <figure aria-labelledby={`${id}-title`} className="min-w-0 rounded-xl border border-edge p-3 sm:p-4" data-metric={metric.id}>
      <figcaption className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 id={`${id}-title`} className="text-base font-semibold">{metric.title} <span className="text-xs font-normal text-muted">({metric.unit})</span></h3>
          <p className="mt-0.5 text-xs text-ink2">{rule?.triggered ? "Evidence supporting the suggestion" : context ? "Context for the recorded alert or hazard" : "Supporting weather context"}</p>
        </div>
        {peak && <div className="text-right text-sm"><strong className="tabnum">{format(peak.value)}</strong>
          <p className="text-[11px] text-muted">{metric.signal ? "Recorded observation" : `${metric.id === "temp" ? "Lowest" : metric.id === "ice" || metric.id === "snow" ? "Total" : "Peak"} in chart`} · {fmtTime(new Date(peak.ts).toISOString(), tz, { date: false })}</p></div>}
      </figcaption>
      {!available.length ? (
        <p className="mt-3 rounded-lg bg-[var(--surface-2)] p-4 text-sm text-ink2">No measurements are available for this chart. The recommendation still uses the recorded alerts and evidence; missing data does not establish safe conditions.</p>
      ) : <>
        <div className={compact ? "mt-3 h-40" : "mt-3 h-60"}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={visible} margin={{ top: 12, right: 14, bottom: 0, left: 0 }} accessibilityLayer>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              {window && <ReferenceArea x1={window.start} x2={window.end} ifOverflow="hidden"
                fill="var(--data-focus-fill)" stroke="var(--data-focus)" strokeOpacity={0.4} strokeDasharray="3 3" />}
              <XAxis dataKey="ts" type="number" scale="time" domain={domain} ticks={ticks} tickFormatter={tick} minTickGap={65} interval="preserveStartEnd" allowDuplicatedCategory={false}
                stroke="var(--axis)" tick={{ fill: "var(--text-muted)", fontSize: 10 }} allowDataOverflow />
              <YAxis domain={metric.unit === "%" ? [0, 100] : [low < 0 ? low - pad : 0, high + pad]}
                allowDecimals={!["sensors", "hours", "rank"].includes(metric.unit)}
                width={38} tickCount={compact ? 3 : 5} tickFormatter={(v: number) => metric.unit === "in" ? v.toFixed(2) : String(Math.round(v))}
                stroke="var(--axis)" tick={{ fill: "var(--text-muted)", fontSize: 10 }} />
              {rule && <ReferenceLine y={rule.threshold} stroke="var(--data-focus)" strokeDasharray="5 4"
                label={{ value: `Threshold ${format(rule.threshold)}${rule.verified ? "" : " *"}`, position: rule.threshold < low + (high - low) / 3 ? "insideBottomRight" : "insideTopRight", fill: "var(--data-focus)", fontSize: 10 }} />}
              <ReferenceLine x={asOf} stroke="var(--text-muted)" strokeDasharray="3 3"
                label={{ value: "As of", position: "insideTopLeft", fill: "var(--text-muted)", fontSize: 10 }} />
              <Tooltip content={<MetricTooltip tz={tz} snap={snap} data={data} format={format} />} />
              {available.map((s) => <Line key={s.key} data={visible.filter((row) => row[s.key] !== undefined)} dataKey={s.key} name={seriesName(s)} stroke={s.color} strokeWidth={2}
                strokeDasharray={s.forecast ? "5 3" : undefined} dot={false} connectNulls={false} isAnimationActive={false} activeDot={{ r: 4 }} />)}
              {available.map((s) => <Line key={`${s.key}-focus`} data={visible.filter((row) => row[s.key] !== undefined)} dataKey={`${s.key}_focus`} stroke="var(--data-focus)" strokeWidth={3}
                dot={{ r: 2, fill: "var(--data-focus)", strokeWidth: 0 }} connectNulls={false} isAnimationActive={false} activeDot={false} tooltipType="none" />)}
              {peak && <ReferenceDot x={peak.ts} y={peak.value} r={5} fill="var(--data-focus)" stroke="var(--surface-1)" strokeWidth={2} ifOverflow="hidden" />}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-ink2">
          {available.map((s) => <span key={s.key} className="inline-flex items-center gap-1.5"><span aria-hidden className="inline-block w-5 border-t-2" style={{ borderColor: s.color, borderStyle: s.forecast ? "dashed" : "solid" }} />{seriesName(s)}</span>)}
          {(window || highlighted > 0) && <span className="inline-flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--data-focus)" }} />{label}</span>}
          {peak && <span className="inline-flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: "var(--data-focus)" }} />{metric.signal ? "Recorded observation" : metric.id === "temp" ? "Lowest point" : "Peak point"}</span>}
          <button className="ml-auto min-h-9 rounded-md px-2 text-xs font-medium text-[var(--accent)] underline underline-offset-2" onClick={() => setFull(!full)}>
            {full ? "Focus on relevant window" : "Show full timeline"}
          </button>
        </div>
        <div className="mt-2 rounded-lg bg-[var(--surface-2)] px-3 py-2 text-xs leading-relaxed text-ink2">
          {rule ? <><strong className="text-ink">{rule.triggered ? "Why highlighted: " : "Threshold to watch: "}</strong>
            {rule.label}: recorded {fmtVal(rule.observed_value, rule.unit)} against {rule.operator} {fmtVal(rule.threshold, rule.unit)}.
            {!rule.verified && " * This is a policy threshold; source verification is pending."}
            {!rule.triggered && " This threshold has not been crossed."}
            {!rule.triggered && context && <span className="mt-1 block">The suggestion is supported by {context.label}; this measurement is supporting context.</span>}
          </> : context ? <><strong className="text-ink">Why highlighted: </strong>{context.label}. The shaded period comes from the recorded hazard window; this chart does not establish that a numeric threshold was crossed.</>
            : <>These measurements provide context. No operating-status threshold is crossed for this metric.</>}
          {window && <span className="mt-1 block">Highlighted window: {fmtTime(new Date(window.start).toISOString(), tz)} – {fmtTime(new Date(window.end).toISOString(), tz)}.</span>}
          {metric.signal && <span className="mt-1 block">This is a recorded observation{peak ? ` reported at ${fmtTime(new Date(peak.ts).toISOString(), tz)}` : ""}, available by this evaluation, not a forecast of future conditions.</span>}
          {metric.id === "rwis" && <span className="mt-1 block">This counts nearby pavement sensor alerts, not inches of ice or affected roads. Verify conditions on staff commute routes before deciding.</span>}
          {metric.id === "roads" && <span className="mt-1 block">Road scale: 0 normal, 1 wet/frost, 2 partially covered, 3 completely covered, 4 travel advisory, 5 travel not advised/closed.</span>}
          {(rule ?? context)?.source_url.startsWith("https://") && <div className="mt-1"><a href={(rule ?? context)!.source_url} target="_blank" rel="noreferrer" className="inline-block underline underline-offset-2">View recorded evidence source</a></div>}
        </div>
      </>}
    </figure>
  );
}

function MetricTooltip({ active, payload, label, tz, snap, data, format }: {
  active?: boolean; payload?: { dataKey?: string | number; name?: string; value?: number; color?: string }[];
  label?: number | string; tz: string; snap: Snapshot; data: Timeseries; format: (v: number) => string;
}) {
  if (!active || !payload?.length || label === undefined) return null;
  return <div className="max-w-[240px] rounded-lg border border-edge bg-surface p-3 text-xs shadow-lg">
    <p className="mb-1 font-semibold">{fmtTime(new Date(Number(label)).toISOString(), tz)}</p>
    {payload.filter((p) => !String(p.dataKey).endsWith("_focus") && typeof p.value === "number").map((p) => {
      const key = String(p.dataKey).replace("_cum", "_in");
      const signal = key.startsWith("obs_") ? snap.signals[key.slice(4)] : undefined;
      const input = snap.inputs.find((input) => !input.id.startsWith("unused.") && (signal?.input_ids?.includes(input.id)
        || `${input.role === "observation" ? "obs" : "fcst"}_${input.metric}` === key));
      const meta = data.meta[key] ?? input;
      const provenance = data.meta[key]?.provenance ?? input?.data;
      const timeKey = new Date(Number(label)).toISOString().replace(".000Z", "Z");
      const pointSource = provenance?.secondary_point_sources?.[timeKey] ?? provenance?.point_sources?.[timeKey];
      const secondary = provenance?.secondary_times?.includes(timeKey) ? provenance.secondary_source : null;
      const origin = secondary ? { ...secondary, ...pointSource } : pointSource ? { ...meta, ...pointSource } : meta;
      return <div key={p.dataKey} className="mt-1"><p>{p.name}: <strong>{format(p.value!)}</strong></p>
        {origin && <><p className="text-muted">{origin.source} · {origin.source_time ? <>{key.startsWith("obs_") ? "observed" : "issued"} {fmtTime(origin.source_time, tz)}</>
          : <>issue time unavailable; retrieved {fmtTime(origin.fetched_at, tz)}</>}</p>{meta?.note && <p className="mt-1 text-muted">{meta.note}</p>}</>}</div>;
    })}
  </div>;
}
