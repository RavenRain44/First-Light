import type { Posture, RuleResult, Snapshot, Timeseries } from "./types";

export const ACTIONS: Record<Posture, string> = {
  NORMAL: "continue normal operations",
  DELAYED_ARRIVAL: "plan a delayed arrival",
  EARLY_DISMISSAL: "plan an early dismissal once departure is safe",
  TELEWORK: "offer unscheduled leave or telework under existing agreements",
  CLOSED: "close the facility for nonessential onsite operations",
};

export function supportingRules(snap: Snapshot): RuleResult[] {
  const controlling = new Set(Object.values(snap.hazards)
    .filter((h) => snap.posture.contributing_hazards.includes(h.hazard)).flatMap((h) => h.controlling_rule_ids));
  return snap.rules.filter((r) => r.triggered && r.available)
    .sort((a, b) => Number(controlling.has(b.rule_id)) - Number(controlling.has(a.rule_id)) || b.level - a.level || b.score - a.score);
}

export function suggestionReasons(snap: Snapshot): string[] {
  const rules = supportingRules(snap);
  if (snap.posture.posture === "NORMAL" && rules.length) {
    return ["the recorded hazard timing not requiring an operating-status change for the decision day"];
  }
  const valid = new Set(rules.map((r) => r.rule_id));
  const seen = new Set<string>();
  const phrases = (snap.ai.suggested_reasons ?? []).filter((r) => {
    if (!valid.has(r.rule_id) || seen.has(r.rule_id) || !r.text.trim()) return false;
    seen.add(r.rule_id);
    return true;
  }).slice(0, 3).map((r) => {
    // A sensor count is a pavement alert, not an amount of accumulated ice.
    const cited = rules.find((rule) => rule.rule_id === r.rule_id)!;
    return cited.metric === "rwis_ice_sensors" ? sensorReason(cited) : r.text.trim().replace(/[.!?]+$/, "");
  });
  if (phrases.length) return phrases;
  if (rules.length) return rules.slice(0, 3).map((r) => r.metric === "alert_present" ? `${r.observed_value} in effect`
    : r.metric === "rwis_ice_sensors" ? sensorReason(r) : r.label);
  return ["no operating-status threshold being crossed in the available data"];
}

function sensorReason(rule: RuleResult): string {
  const count = rule.observed_value;
  return `${count} nearby pavement sensor${count === 1 ? "" : "s"} reporting an ice watch/warning condition`;
}

export function joinReasons(reasons: string[]): string {
  return reasons.length < 3 ? reasons.join(" and ") : `${reasons.slice(0, -1).join(", ")}, and ${reasons.at(-1)}`;
}

export interface MetricDefinition {
  id: string;
  title: string;
  unit: string;
  hazard: string;
  contextHazards?: string[];
  /** A recorded observation aggregate, plotted once rather than as a forecast. */
  signal?: string;
  series: { key: string; name: string; color: string; forecast?: boolean }[];
}

export const METRICS: MetricDefinition[] = [
  { id: "wind", title: "Wind and gusts", unit: "mph", hazard: "wind", series: [
    { key: "obs_wind_speed_mph", name: "Observed wind (hourly report)", color: "var(--series-1)" },
    { key: "obs_peak_gust_mph", name: "Observed peak gust in hour", color: "var(--series-3)" },
    { key: "obs_wind_gust_mph", name: "Observed gust (archived)", color: "var(--series-3)" },
    { key: "fcst_wind_speed_mph", name: "Forecast wind", color: "var(--series-2)", forecast: true },
    { key: "fcst_wind_gust_mph", name: "Forecast gust", color: "var(--series-3)", forecast: true }] },
  { id: "ice", title: "Forecast ice accumulation", unit: "in", hazard: "winter", series: [
    { key: "fcst_ice_cum", name: "Forecast ice", color: "var(--series-2)", forecast: true }] },
  { id: "snow", title: "Forecast snowfall", unit: "in", hazard: "winter", series: [
    { key: "fcst_snow_cum", name: "Forecast snow", color: "var(--series-2)", forecast: true }] },
  { id: "temp", title: "Temperature & feels-like", unit: "°F", hazard: "cold", contextHazards: ["winter"], series: [
    { key: "obs_temp_f", name: "Observed temperature (hourly report)", color: "var(--series-1)" },
    { key: "obs_pavement_temp_f", name: "Observed pavement temperature (nearby minimum)", color: "var(--series-3)" },
    { key: "fcst_temp_f", name: "Forecast temperature", color: "var(--series-2)", forecast: true },
    { key: "fcst_apparent_temp_f", name: "Forecast feels-like", color: "var(--series-3)", forecast: true }] },
  { id: "pop", title: "Precipitation probability", unit: "%", hazard: "winter", contextHazards: ["wind"], series: [
    { key: "fcst_pop_pct", name: "Forecast probability", color: "var(--series-2)", forecast: true }] },
  { id: "rwis", title: "Pavement ice alerts", unit: "sensors", hazard: "winter", signal: "rwis_ice_sensors", series: [
    { key: "obs_rwis_ice_sensors", name: "Sensors reporting an ice watch/warning", color: "var(--series-1)" }] },
  { id: "freezing", title: "Observed freezing precipitation (last 3 hours)", unit: "hours", hazard: "winter", signal: "obs_freezing_precip_hours_3h", series: [
    { key: "obs_freezing_precip_hours_3h", name: "Hours reporting freezing rain, drizzle or ice pellets", color: "var(--series-1)" }] },
  { id: "observed-ice", title: "Measured ice accretion (last 3 hours)", unit: "in", hazard: "winter", signal: "obs_ice_accretion_3h_in", series: [
    { key: "obs_ice_accretion_3h_in", name: "Observed ice accretion", color: "var(--series-1)" }] },
  { id: "roads", title: "Commute road conditions", unit: "rank", hazard: "winter", signal: "road_worst_rank", series: [
    { key: "obs_road_worst_rank", name: "Worst reported commute-corridor condition", color: "var(--series-1)" }] },
];

export function metricForRule(rule: RuleResult): string | undefined {
  if (rule.metric.includes("gust")) return "wind";
  if (rule.metric.startsWith("fcst_ice")) return "ice";
  if (rule.metric.startsWith("fcst_snow")) return "snow";
  if (rule.metric === "rwis_ice_sensors") return "rwis";
  if (rule.metric === "obs_freezing_precip_hours_3h") return "freezing";
  if (rule.metric === "obs_ice_accretion_3h_in") return "observed-ice";
  if (rule.metric === "road_worst_rank") return "roads";
  if (rule.metric.includes("apparent")) return "temp";
  return undefined;
}

export function metricHasData(snap: Snapshot, metric: MetricDefinition, data: Timeseries): boolean {
  return metricRows(snap, metric, data).some((row) => metric.series.some((s) =>
    typeof row[s.key] === "number" && Number.isFinite(row[s.key])));
}

function winterMetrics(snap: Snapshot, rule: RuleResult, data: Timeseries): string[] {
  const event = String(rule.observed_value ?? "");
  // Named events are unambiguous; generic winter alerts need their actual text or measurements.
  if (/blizzard|snow/i.test(event)) return /\bice\b|freezing rain|freezing drizzle|sleet/i.test(event) ? ["snow", "ice"] : ["snow"];
  if (/ice storm|freezing rain|freezing drizzle/i.test(event)) return ["ice"];
  const text = [event, ...(snap.alerts ?? []).filter((a) => event.split(", ").includes(a.event))
    .flatMap((a) => [a.headline, a.description])].join(" ");
  const kinds = [/\bsnow\b|\bblizzard\b/i.test(text) ? "snow" : null,
    /\bice\b|icing|freezing rain|freezing drizzle|sleet/i.test(text) ? "ice" : null].filter((id): id is string => !!id);
  if (kinds.length) return kinds;
  const start = Math.floor(Date.parse(snap.as_of) / 3600e3) * 3600e3;
  const end = rule.window_end ? Date.parse(rule.window_end) : start + 48 * 3600e3;
  // A zero or missing accumulation does not identify the type of winter event.
  return ["snow", "ice"].filter((id) => data.rows.some((row) => Date.parse(row.t) >= start && Date.parse(row.t) < end
    && [row[`fcst_${id}_in`], row[`fcst_${id}_cum`]].some((v) => typeof v === "number" && v > 0))
    || supportingRules(snap).some((r) => metricForRule(r) === id));
}

function ruleMetrics(snap: Snapshot, rule: RuleResult, data: Timeseries): string[] {
  const direct = metricForRule(rule);
  if (direct) return [direct];
  if (rule.hazard === "winter") return rule.metric === "alert_present" ? winterMetrics(snap, rule, data) : [];
  return ({ wind: ["wind"], cold: ["temp"] } as Record<string, string[]>)[rule.hazard] ?? [];
}

export function relevantMetrics(snap: Snapshot, data: Timeseries): MetricDefinition[] {
  const ids: string[] = [];
  const add = (id: string | undefined) => { if (id && !ids.includes(id)) ids.push(id); };
  const supporting = supportingRules(snap);
  const hasData = (m: MetricDefinition) => metricHasData(snap, m, data);
  for (const r of supporting) for (const id of ruleMetrics(snap, r, data)) add(id);
  const closest = snap.rules.filter((r) => r.available && r.margin_pct !== null)
    .sort((a, b) => Math.abs(a.margin_pct!) - Math.abs(b.margin_pct!));
  const hazards = [...new Set(supporting.map((r) => r.hazard))];
  // Supporting context stays relevant to the active hazard, even when it has no numeric rule.
  const contextMetrics: Record<string, string[]> = { wind: ["pop", "temp"], winter: ["temp", "pop"], cold: ["wind"] };
  for (const hazard of hazards) for (const metricId of contextMetrics[hazard] ?? []) {
    const metric = METRICS.find((m) => m.id === metricId)!;
    if (hasData(metric)) add(metric.id);
  }
  // Do not pad an active event with unrelated hazards or an all-zero snow/ice forecast.
  if (hazards.length) {
    for (const hazard of hazards) if (!ids.length) add(contextMetrics[hazard]?.[0]);
    return ids.slice(0, 2).map((id) => METRICS.find((m) => m.id === id)!);
  }
  for (const r of closest) {
    const metric = METRICS.find((m) => m.id === metricForRule(r));
    if (metric && hasData(metric)) add(metric.id);
  }
  for (const m of METRICS) if (hasData(m)) add(m.id);
  // Two honest empty states if the sources contain no plottable measurements.
  for (const m of METRICS) add(m.id);
  return ids.slice(0, 2).map((id) => METRICS.find((m) => m.id === id)!);
}

export type ChartRow = Record<string, number | string | null> & { ts: number };

function metricRows(snap: Snapshot, metric: MetricDefinition, data: Timeseries): ChartRow[] {
  const byTime = new Map(data.rows.map((r) => [Date.parse(r.t), { ...r, ts: Date.parse(r.t) } as ChartRow]));
  const asOf = Date.parse(snap.as_of);
  const add = (ts: number, key: string, value: unknown) => {
    if (!Number.isFinite(ts) || ts < asOf - 12 * 3600e3 || ts > asOf || typeof value !== "number" || !Number.isFinite(value)) return;
    byTime.set(ts, { ...(byTime.get(ts) ?? { ts }), [key]: value });
  };
  for (const input of snap.inputs) {
    const key = `obs_${input.metric}`;
    if (input.kind === "scalar" && input.role === "observation" && input.source_time && metric.series.some((s) => s.key === key)) {
      add(Date.parse(input.source_time), key, input.value);
    }
  }
  if (metric.signal) {
    const signal = snap.signals[metric.signal];
    // Aggregates describe this evaluation; point measurements retain their recorded observation time.
    const rule = snap.rules.find((r) => r.metric === metric.signal && r.available);
    const ts = metric.id === "freezing" ? asOf : Date.parse(signal?.peak_time ?? rule?.time_of_peak ?? "");
    if (signal?.available !== false) add(ts, metric.series[0].key, signal?.value ?? rule?.observed_value);
  }
  return [...byTime.values()].filter((r) => Number.isFinite(r.ts));
}

function seriesForRule(r: RuleResult, snap: Snapshot, metric: MetricDefinition): string[] {
  const observedGust = r.input_ids?.includes("obs.peak_gust_mph") || snap.inputs.some((i) => i.id === "obs.peak_gust_mph")
    ? "obs_peak_gust_mph" : "obs_wind_gust_mph";
  if (r.metric === "max_gust_mph") return [snap.signals[r.metric]?.role === "observation" ? observedGust : "fcst_wind_gust_mph"];
  if (metric.signal) return metric.series.map((s) => s.key);
  if (metric.id === "wind") return [r.metric.startsWith("obs_") ? observedGust : "fcst_wind_gust_mph"];
  if (metric.id === "temp") return ["fcst_apparent_temp_f"];
  return metric.series.map((s) => s.key);
}

export function crossesThreshold(value: number, rule: Pick<RuleResult, "operator" | "threshold">): boolean {
  switch (rule.operator) {
    case ">=": return value >= rule.threshold;
    case ">": return value > rule.threshold;
    case "<=": return value <= rule.threshold;
    case "<": return value < rule.threshold;
    default: return false;
  }
}

export function metricEvidence(snap: Snapshot, metric: MetricDefinition, data: Timeseries) {
  let rows: ChartRow[] = metricRows(snap, metric, data);
  if (metric.id === "wind" && (snap.inputs.some((i) => i.id === "obs.peak_gust_mph") || rows.some((r) => r.obs_peak_gust_mph !== undefined))) {
    // New snapshots distinguish hourly METAR wind from the peak gust used by the rules.
    // Archived snapshots retain their original gust series and provenance.
    for (const row of rows) delete row.obs_wind_gust_mph;
  }
  const baseKeys = metric.series.map((s) => s.key.replace("_cum", "_in"));
  // Ignore timestamps belonging only to other metrics, but preserve explicit gaps in this source series.
  rows = rows.filter((row) => baseKeys.some((key) => row[key] !== undefined) || metric.series.some((s) => row[s.key] !== undefined));
  const byTime = new Map(rows.map((row) => [row.ts, row]));
  const asOf = new Date(snap.as_of).getTime();
  for (const input of snap.inputs) {
    const key = `${input.role === "observation" ? "obs" : "fcst"}_${input.metric}`;
    if (input.kind !== "series" || !baseKeys.includes(key)) continue;
    for (const point of input.series ?? []) {
      const ts = new Date(point.t).getTime();
      if (point.v !== null || ts < asOf - 12 * 3600e3 || ts > asOf + 48 * 3600e3 || !Number.isFinite(ts)) continue;
      byTime.set(ts, { ...(byTime.get(ts) ?? { ts }), [key]: null });
    }
  }
  rows = [...byTime.values()].sort((a, b) => a.ts - b.ts);
  const ranked = supportingRules(snap);
  const matching = snap.rules.filter((r) => r.available && metricForRule(r) === metric.id)
    .sort((a, b) => Number(b.triggered) - Number(a.triggered) ||
      (!a.triggered && !b.triggered ? Math.abs(a.margin_pct ?? Infinity) - Math.abs(b.margin_pct ?? Infinity) : 0) ||
      b.level - a.level || b.score - a.score);
  const rule = matching.find((r) => seriesForRule(r, snap, metric).some((key) => rows.some((row) => typeof row[key] === "number")));
  const context = ranked.find((r) => ruleMetrics(snap, r, data).includes(metric.id) || metric.contextHazards?.includes(r.hazard)
    || (metric.id === "pop" && (r.hazard === "winter" || r.hazard === "wind")));
  const driver = rule?.triggered ? rule : context;
  const window = driver?.window_start && driver.window_end ? {
    start: new Date(driver.window_start).getTime(), end: new Date(driver.window_end).getTime(),
  } : null;
  // Use the recorded accumulation window, especially the heaviest 12 h snow rule.
  if (rule && (metric.id === "ice" || metric.id === "snow")) {
    const start = rule.metric === "fcst_snow_12h_in" && rule.time_of_peak ? new Date(rule.time_of_peak).getTime()
      : Math.floor(new Date(snap.as_of).getTime() / 3600e3) * 3600e3;
    const end = rule.metric === "fcst_snow_12h_in" ? start + 12 * 3600e3
      : rule.window_end ? new Date(rule.window_end).getTime() : start + 24 * 3600e3;
    let total = 0;
    const raw = `fcst_${metric.id}_in`, key = `fcst_${metric.id}_cum`;
    rows = rows.map((row) => {
      const value = row[raw];
      if (row.ts < start || row.ts >= end || typeof value !== "number") return { ...row, [key]: null };
      total += value;
      return { ...row, [key]: Number(total.toFixed(3)) };
    });
  }
  const keys = rule?.triggered ? seriesForRule(rule, snap, metric) : metric.series.map((s) => s.key);
  const pointInWindow = (row: ChartRow) => !window || (row.ts >= window.start && row.ts < window.end);
  let highlighted = 0;
  rows = rows.map((row) => {
    const updates: Record<string, number | null> = {};
    for (const series of metric.series) {
      const value = row[series.key];
      const focus = typeof value === "number" && pointInWindow(row) && (rule?.triggered
        ? keys.includes(series.key) && crossesThreshold(value, rule) : !!context);
      updates[`${series.key}_focus`] = focus ? value as number : null;
      if (focus) highlighted++;
    }
    return { ...row, ...updates };
  });
  const candidates = rows.flatMap((row) => keys.flatMap((key) => typeof row[key] === "number"
    ? [{ ts: row.ts, value: row[key] as number, key }] : []));
  const peak = candidates.sort((a, b) => metric.id === "temp" ? a.value - b.value : b.value - a.value)[0] ?? null;
  return { rows, rule, context, window, peak, highlighted, keys };
}
