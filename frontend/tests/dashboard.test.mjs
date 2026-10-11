import assert from "node:assert/strict";
import test from "node:test";
import { METRICS, crossesThreshold, metricDefinitions, metricDomain, metricEvidence, relevantMetrics, suggestionReasons } from "../src/dashboard.ts";
import { readFileSync } from "node:fs";

const asOf = "2026-01-13T06:00:00Z";
const at = (hour) => `2026-01-13T${String(hour).padStart(2, "0")}:00:00Z`;
const rule = (id, metric, extra = {}) => ({ rule_id: id, metric, hazard: "wind", label: id,
  threshold: 58, operator: ">=", triggered: true, available: true, level: 2, score: 70,
  window_start: at(7), window_end: at(10), time_of_peak: at(8), margin_pct: 10, ...extra });
const snap = (rules, extra = {}) => ({ as_of: asOf, rules, inputs: [], signals: {},
  ai: {}, posture: { contributing_hazards: ["wind"] }, hazards: { wind: { hazard: "wind", controlling_rule_ids: [rules[0]?.rule_id] } }, ...extra });
const data = (rows) => ({ rows });

test("controlling evidence chooses the primary metric; charts do not duplicate the same measurement", () => {
  const s = snap([rule("wind", "fcst_max_gust_24h_mph"), rule("wind-other", "max_gust_mph"),
    rule("ice", "fcst_ice_24h_in", { hazard: "winter", level: 1 })]);
  assert.deepEqual(relevantMetrics(s, data([])).map((m) => m.id), ["wind", "ice"]);
});

test("an alert selects the matching hazard context without inventing a numeric threshold", () => {
  const s = snap([rule("storm", "alert_present")]);
  const d = data([{ t: at(8), fcst_wind_gust_mph: 20 }]);
  const result = metricEvidence(s, METRICS[0], d);
  assert.equal(result.rule, undefined);
  assert.equal(result.context.rule_id, "storm");
  assert.equal(result.rows[0].fcst_wind_gust_mph_focus, 20);
});

test("secondary metrics provide active-hazard context instead of unrelated winter measurements during a storm", () => {
  const s = snap([rule("storm", "alert_present"), rule("ice", "fcst_ice_24h_in", { hazard: "winter", triggered: false, margin_pct: -100 })]);
  const d = data([{ t: at(8), fcst_wind_gust_mph: 20, fcst_ice_cum: 0, fcst_pop_pct: 70 }]);
  assert.deepEqual(relevantMetrics(s, d).map((m) => m.id), ["wind", "pop"]);
  const context = metricEvidence(s, METRICS.find((m) => m.id === "pop"), d);
  assert.equal(context.rule, undefined);
  assert.equal(context.context.rule_id, "storm");
  assert.equal(context.rows[0].fcst_pop_pct_focus, 70);
});

test("a snow warning chooses snowfall rather than ice as its primary graph", () => {
  const s = snap([rule("snow-warning", "alert_present", { hazard: "winter", observed_value: "Winter Storm Warning for heavy snow" })]);
  const d = data([{ t: at(8), fcst_snow_cum: 6, fcst_temp_f: 10 }]);
  assert.deepEqual(relevantMetrics(s, d).map((m) => m.id), ["snow", "temp"]);
});

test("generic winter warnings use matching alert descriptions and do not borrow unrelated alerts", () => {
  const rules = [rule("winter-warning", "alert_present", { hazard: "winter", observed_value: "Winter Storm Warning" })];
  const s = snap(rules, { alerts: [
    { event: "Winter Storm Warning", headline: "Heavy snow expected. Total snow accumulation 6 to 8 inches." },
    { event: "Ice Storm Watch", headline: "Freezing rain possible next week." },
  ] });
  const d = data([{ t: at(8), fcst_snow_cum: 6, fcst_ice_cum: 0, fcst_temp_f: 20 }]);
  assert.deepEqual(relevantMetrics(s, d).map((m) => m.id), ["snow", "temp"]);
  assert.equal(metricEvidence(s, METRICS.find((m) => m.id === "ice"), d).context, undefined);
  s.alerts[0].headline = "Freezing rain expected. Ice accumulations around a quarter inch.";
  assert.deepEqual(relevantMetrics(s, d).map((m) => m.id), ["ice", "temp"]);
});

test("snowstorms, ice storms and mixed precipitation select their own measurements", () => {
  const d = data([{ t: at(8), fcst_snow_cum: 6, fcst_ice_cum: 0.25, fcst_temp_f: 20 }]);
  for (const [event, expected] of [["Blizzard Warning", ["snow", "temp"]], ["Ice Storm Warning", ["ice", "temp"]],
    ["Winter Storm Warning for snow and freezing rain", ["snow", "ice"]]]) {
    const s = snap([rule("winter-warning", "alert_present", { hazard: "winter", observed_value: event })]);
    assert.deepEqual(relevantMetrics(s, d).map((m) => m.id), expected);
  }
});

test("a generic winter advisory does not identify a precipitation type from a zero forecast", () => {
  const s = snap([rule("advisory", "alert_present", { hazard: "winter", observed_value: "Winter Weather Advisory" })]);
  const d = data([{ t: at(8), fcst_snow_cum: 0, fcst_ice_cum: 0, fcst_temp_f: 20, fcst_pop_pct: 50 }]);
  assert.deepEqual(relevantMetrics(s, d).map((m) => m.id), ["temp", "pop"]);
  d.rows[0].fcst_snow_cum = 3;
  assert.deepEqual(relevantMetrics(s, d).map((m) => m.id), ["snow", "temp"]);
});

test("one icy pavement sensor shows its observed count and temperature, not zero forecast ice or snow", () => {
  const s = snap([rule("rwis", "rwis_ice_sensors", { hazard: "winter", observed_value: 1, threshold: 1,
    unit: "sensors", level: 1, time_of_peak: at(5), window_start: at(5), window_end: at(9) })], {
    signals: { rwis_ice_sensors: { value: 1, available: true, peak_time: at(5) } },
    inputs: [{ kind: "scalar", role: "observation", metric: "pavement_temp_f", source_time: at(5), value: 28 }],
    ai: { suggested_reasons: [{ rule_id: "rwis", text: "RWIS sensors reporting ice of 1 sensors" }] },
  });
  const d = data([{ t: at(8), fcst_ice_cum: 0, fcst_snow_cum: 0 }]);
  assert.deepEqual(relevantMetrics(s, d).map((m) => m.id), ["rwis", "temp"]);
  assert.deepEqual(suggestionReasons(s), ["1 nearby pavement sensor reporting an ice watch/warning condition"]);
  const evidence = metricEvidence(s, METRICS.find((m) => m.id === "rwis"), d);
  assert.equal(evidence.rows.length, 1);
  assert.equal(evidence.rows[0].ts, Date.parse(at(5)));
  assert.equal(evidence.rows[0].obs_rwis_ice_sensors_focus, 1);
  assert.equal(evidence.rule.rule_id, "rwis");
  assert.equal(evidence.peak.value, 1);
  const temp = metricEvidence(s, METRICS.find((m) => m.id === "temp"), d);
  assert.equal(temp.peak.value, 28);
});

test("freezing precipitation, measured ice and covered roads retain their observed source and units", () => {
  for (const [metricId, signalId, value, unit] of [["freezing", "obs_freezing_precip_hours_3h", 2, "hours"],
    ["observed-ice", "obs_ice_accretion_3h_in", 0.02, "in"], ["roads", "road_worst_rank", 3, "rank"]]) {
    const s = snap([rule("observed", signalId, { hazard: "winter", observed_value: value, threshold: value,
      unit, time_of_peak: at(5), window_start: at(5), window_end: at(9) })], {
      signals: { [signalId]: { value, available: true, peak_time: at(5) } },
    });
    const d = data([{ t: at(8), fcst_ice_cum: 0, fcst_snow_cum: 0, fcst_temp_f: 20 }]);
    const metrics = relevantMetrics(s, d);
    assert.deepEqual(metrics.map((m) => m.id), [metricId, "temp"]);
    assert.equal(metrics[0].unit, unit);
    const evidence = metricEvidence(s, metrics[0], d);
    assert.equal(evidence.peak.value, value);
    assert.equal(evidence.rows.length, 1);
    assert.equal(evidence.rows[0].ts, Date.parse(metricId === "freezing" ? asOf : at(5)));
    assert.equal(evidence.highlighted, 1);
  }
});

test("missing snow forecasts stay missing while blizzards use their available wind context", () => {
  const s = snap([rule("blizzard", "alert_present", { hazard: "winter", observed_value: "Blizzard Warning" })]);
  const d = data([{ t: at(8), fcst_ice_cum: 0, fcst_wind_gust_mph: 10 }]);
  assert.deepEqual(relevantMetrics(s, d).map((m) => m.id), ["wind"]);
  assert.equal(metricEvidence(s, METRICS.find((m) => m.id === "snow"), d).peak, null);
});

test("the pre-Christmas blizzard shows wind, dangerous cold and a timestamped travel advisory after new snow ends", () => {
  const { snapshot: s, timeseries: d } = JSON.parse(readFileSync(new URL("../../backend/fixtures/blizzard_2022-12-22T18Z_chart.json", import.meta.url)));
  assert.equal(s.signals.fcst_snow_24h_in.value, 0);
  assert.deepEqual(relevantMetrics(s, d).map((m) => m.id), ["wind", "temp", "roads"]);
  const cold = metricEvidence(s, METRICS.find((m) => m.id === "temp"), d);
  assert.equal(cold.rule.rule_id, "cold.fcst_wind_chill_extreme");
  assert.equal(cold.peak.value, s.signals.fcst_min_apparent_24h_f.value);
  assert.ok(cold.highlighted > 0);
  assert.ok(cold.rows.some((r) => r.obs_apparent_temp_f < -35));
  const roadMetric = METRICS.find((m) => m.id === "roads");
  const roads = metricEvidence(s, roadMetric, d);
  assert.equal(roads.peak.value, 4);
  assert.equal(roads.peak.ts, Date.parse("2022-12-22T13:37:00Z"));
  assert.equal(roads.highlighted, 1);
  const domain = metricDomain(s, roadMetric, roads);
  assert.ok(domain[0] < roads.peak.ts && roads.peak.ts < domain[1]);
  assert.equal(roads.rows.length, 1); // one report, never a fabricated road trend
});

test("a road report before the commute window stays visible without being moved to evaluation time", () => {
  const s = snap([rule("roads", "road_worst_rank", { hazard: "winter", observed_value: 4, threshold: 4,
    time_of_peak: at(1), window_start: at(5), window_end: at(9) })], {
    signals: { road_worst_rank: { available: true, value: 4, peak_time: at(1) } },
  });
  const metric = METRICS.find((m) => m.id === "roads"), d = data([]);
  const evidence = metricEvidence(s, metric, d);
  assert.equal(evidence.peak.ts, Date.parse(at(1)));
  assert.equal(evidence.highlighted, 1);
  assert.ok(metricDomain(s, metric, evidence)[0] < evidence.peak.ts);
  assert.deepEqual(metricDomain(s, metric, evidence, true), [Date.parse(asOf) - 12 * 3600e3, Date.parse(asOf) + 48 * 3600e3]);
});

test("only the recorded threshold, series and hazard window are highlighted", () => {
  const s = snap([rule("wind", "fcst_max_gust_24h_mph")]);
  const result = metricEvidence(s, METRICS[0], data([
    { t: at(6), fcst_wind_gust_mph: 80 }, { t: at(7), fcst_wind_gust_mph: 40 },
    { t: at(8), fcst_wind_gust_mph: 70, obs_wind_gust_mph: 90 }, { t: at(10), fcst_wind_gust_mph: 80 },
  ]));
  assert.deepEqual(result.rows.map((r) => r.fcst_wind_gust_mph_focus), [null, null, 70, null]);
  assert.equal(result.rows[2].obs_wind_gust_mph_focus, null);
  assert.equal(result.highlighted, 1);
});

test("an untriggered chart shows the nearest applicable threshold to watch", () => {
  const s = snap([
    rule("extreme", "fcst_max_gust_24h_mph", { triggered: false, threshold: 80, level: 3, margin_pct: -50 }),
    rule("nearby", "fcst_max_gust_24h_mph", { triggered: false, threshold: 58, level: 2, margin_pct: -31 }),
  ]);
  const result = metricEvidence(s, METRICS[0], data([{ t: at(8), fcst_wind_gust_mph: 40 }]));
  assert.equal(result.rule.rule_id, "nearby");
  assert.equal(result.highlighted, 0);
});

test("combined destructive gust evidence highlights observations when they controlled the rule", () => {
  const s = snap([rule("wind", "max_gust_mph")], { signals: { max_gust_mph: { role: "observation" } } });
  const result = metricEvidence(s, METRICS[0], data([{ t: at(8), obs_wind_gust_mph: 90, fcst_wind_gust_mph: 80 }]));
  assert.equal(result.rows[0].obs_wind_gust_mph_focus, 90);
  assert.equal(result.rows[0].fcst_wind_gust_mph_focus, null);
});

test("corrected hourly weather uses the peak gust for threshold evidence and preserves reported wind", () => {
  const s = snap([rule("wind", "max_gust_mph", { input_ids: ["obs.peak_gust_mph"] })], {
    signals: { max_gust_mph: { role: "observation" } },
    inputs: [{ id: "obs.peak_gust_mph", kind: "series", role: "observation", metric: "peak_gust_mph", series: [] }],
  });
  const result = metricEvidence(s, METRICS[0], data([{ t: at(8), obs_wind_speed_mph: 20,
    obs_wind_gust_mph: 35, obs_peak_gust_mph: 90, fcst_wind_gust_mph: 40 }]));
  assert.equal(result.rows[0].obs_peak_gust_mph_focus, 90);
  assert.equal(result.rows[0].obs_wind_speed_mph, 20);
  assert.equal(result.rows[0].obs_wind_speed_mph_focus, null);
  assert.equal(result.rows[0].obs_wind_gust_mph, undefined);
  assert.equal(result.peak.value, 90);
});

test("cold thresholds highlight lows instead of highs", () => {
  const s = snap([rule("cold", "fcst_min_apparent_24h_f", { hazard: "cold", operator: "<=", threshold: -20 })]);
  const result = metricEvidence(s, METRICS.find((m) => m.id === "temp"), data([
    { t: at(7), fcst_apparent_temp_f: -10 }, { t: at(8), fcst_apparent_temp_f: -25 },
  ]));
  assert.equal(result.peak.value, -25);
  assert.deepEqual(result.rows.map((r) => r.fcst_apparent_temp_f_focus), [null, -25]);
});

test("heaviest 12 h snow uses its recorded starting hour, not the whole forecast total", () => {
  const s = snap([rule("snow", "fcst_snow_12h_in", { hazard: "winter", threshold: 5, time_of_peak: at(8), window_start: at(8), window_end: at(20) })]);
  const result = metricEvidence(s, METRICS.find((m) => m.id === "snow"), data([
    { t: at(7), fcst_snow_in: 9, fcst_snow_cum: 9 }, { t: at(8), fcst_snow_in: 3, fcst_snow_cum: 12 },
    { t: at(9), fcst_snow_in: 3, fcst_snow_cum: 15 }, { t: at(20), fcst_snow_in: 9, fcst_snow_cum: 24 },
  ]));
  assert.deepEqual(result.rows.map((r) => r.fcst_snow_cum), [null, 3, 6, null]);
  assert.equal(result.peak.value, 6);
});

test("missing measurements stay missing; timestamps from other metrics do not create false gaps", () => {
  const s = snap([rule("wind", "fcst_max_gust_24h_mph")], { inputs: [{ kind: "series", role: "forecast", metric: "wind_gust_mph",
    series: [{ t: at(8), v: null }] }] });
  const result = metricEvidence(s, METRICS[0], data([
    { t: at(7), fcst_wind_gust_mph: 70 }, { t: "2026-01-13T07:15:00Z", obs_temp_f: 20 },
    { t: at(9), fcst_wind_gust_mph: 75 },
  ]));
  assert.equal(result.rows.length, 3);
  assert.equal(result.rows[1].fcst_wind_gust_mph, null);
  assert.equal(result.rows[1].fcst_wind_gust_mph_focus, null);
});

test("quiet and missing-data snapshots get honest context instead of fabricated supporting evidence", () => {
  const s = snap([]);
  assert.deepEqual(suggestionReasons(s), ["no operating-status threshold being crossed in the available data"]);
  assert.equal(relevantMetrics(s, data([])).length, 2);
  const result = metricEvidence(s, METRICS[0], data([]));
  assert.equal(result.peak, null);
  assert.equal(result.highlighted, 0);
});

test("normal operations with triggered hazards explain the timing instead of claiming no thresholds crossed", () => {
  const s = snap([rule("overnight", "fcst_max_gust_24h_mph")], { posture: { posture: "NORMAL", contributing_hazards: ["wind"] } });
  assert.deepEqual(suggestionReasons(s), ["the recorded hazard timing not requiring an operating-status change for the decision day"]);
});

test("old briefs use rule reasons, while new reason phrases require a valid distinct citation", () => {
  const rules = [rule("wind", "fcst_max_gust_24h_mph"), rule("ice", "fcst_ice_24h_in")];
  assert.deepEqual(suggestionReasons(snap(rules)), ["wind", "ice"]);
  const s = snap(rules, { ai: { suggested_reasons: [
    { rule_id: "wind", text: "strong forecast gusts." }, { rule_id: "missing", text: "invented evidence" },
    { rule_id: "wind", text: "duplicate" },
  ] } });
  assert.deepEqual(suggestionReasons(s), ["strong forecast gusts"]);
});

test("strict versus inclusive threshold comparisons are preserved", () => {
  assert.equal(crossesThreshold(58, { operator: ">", threshold: 58 }), false);
  assert.equal(crossesThreshold(58, { operator: ">=", threshold: 58 }), true);
  assert.equal(crossesThreshold(-20, { operator: "<", threshold: -20 }), false);
  assert.equal(crossesThreshold(-20, { operator: "<=", threshold: -20 }), true);
});

test("a Wilmington hurricane leads with local wind and rainfall instead of unrelated zero winter charts", () => {
  const s = snap([rule("hurricane", "alert_present", { hazard: "tropical", observed_value: "Hurricane Warning" })], {
    facility: { state: "NC" }, posture: { contributing_hazards: ["tropical"] },
  });
  const d = data([{ t: at(8), fcst_wind_gust_mph: 65, fcst_rain_in: 1.2, fcst_snow_cum: 0, fcst_ice_cum: 0 }]);
  assert.deepEqual(relevantMetrics(s, d).map((m) => m.id), ["wind", "rain"]);
  const rain = metricEvidence(s, METRICS.find((m) => m.id === "rain"), d);
  assert.equal(rain.context.rule_id, "hurricane");
  assert.equal(rain.peak.value, 1.2);
  assert.equal(rain.highlighted, 1);
  const wind = metricEvidence(s, METRICS[0], d);
  assert.equal(metricDomain(s, METRICS[0], wind, true)[1], Date.parse(asOf) + 72 * 3600e3);
});

test("alert-only coastal replay does not create blank or unrelated numerical charts", () => {
  const s = snap([rule("surge", "alert_present", { hazard: "coastal", observed_value: "Storm Surge Warning" })]);
  assert.deepEqual(relevantMetrics(s, data([{ t: at(8), fcst_snow_cum: 0, fcst_temp_f: 80 }])), []);
});

test("a DriveNC commute closure shows access evidence without implying a flood or adding a rainfall chart", () => {
  const s = snap([rule("access.commute_road_closed", "road_worst_rank", { hazard: "access", observed_value: 5, threshold: 5,
    time_of_peak: at(5), window_start: at(5), window_end: at(9) })], {
    facility: { state: "NC" }, signals: { road_worst_rank: { available: true, value: 5, peak_time: at(5) } },
  });
  const d = data([{ t: at(8), fcst_rain_in: 0.1, fcst_snow_cum: 0 }]);
  const metrics = relevantMetrics(s, d);
  assert.deepEqual(metrics.map((m) => m.id), ["roads"]);
  const evidence = metricEvidence(s, metrics[0], d);
  assert.equal(evidence.rule.hazard, "access");
  assert.equal(evidence.peak.value, 5);
});

test("rain accumulation uses the winning 24-hour window and preserves original forecast gaps", () => {
  const offset = (hours) => new Date(Date.parse(asOf) + hours * 3600e3).toISOString();
  const s = snap([rule("rain", "fcst_rain_24h_in", { hazard: "flood", threshold: 3, time_of_peak: offset(2),
    window_start: offset(2), window_end: offset(26) })], {
    facility: { state: "NC" }, inputs: [{ kind: "series", role: "forecast", metric: "qpf_in", series: [{ t: offset(3), v: null }] }],
  });
  const d = data([{ t: offset(1), fcst_rain_in: 50 }, { t: offset(2), fcst_rain_in: 1 },
    { t: offset(4), fcst_rain_in: 2 }, { t: offset(26), fcst_rain_in: 50 }]);
  const rain = metricEvidence(s, METRICS.find((m) => m.id === "rain"), d);
  assert.deepEqual(rain.rows.map((row) => row.fcst_rain_cum), [null, 1, null, 3, null]);
  assert.equal(rain.peak.value, 3);
  assert.equal(rain.rows[3].fcst_rain_cum_focus, 3);
});

test("Wilmington winter charts use the recorded heaviest day within the coastal planning horizon", () => {
  const offset = (hours) => new Date(Date.parse(asOf) + hours * 3600e3).toISOString();
  for (const [metric, amount] of [["snow", 6], ["ice", 0.3]]) {
    const s = snap([rule(metric, `fcst_${metric}_24h_in`, { hazard: "winter", threshold: amount,
      time_of_peak: offset(30), window_start: offset(30), window_end: offset(54) })], { facility: { state: "NC" } });
    const d = data([{ t: offset(1), [`fcst_${metric}_in`]: 20, [`fcst_${metric}_cum`]: 20 },
      { t: offset(30), [`fcst_${metric}_in`]: amount / 2, [`fcst_${metric}_cum`]: 20 + amount / 2 },
      { t: offset(40), [`fcst_${metric}_in`]: amount / 2, [`fcst_${metric}_cum`]: 20 + amount },
      { t: offset(54), [`fcst_${metric}_in`]: 20, [`fcst_${metric}_cum`]: 40 + amount }]);
    const evidence = metricEvidence(s, METRICS.find((m) => m.id === metric), d);
    assert.deepEqual(evidence.rows.map((row) => row[`fcst_${metric}_cum`]), [null, amount / 2, amount, null]);
    assert.equal(evidence.peak.value, amount);
    assert.equal(evidence.rows[2][`fcst_${metric}_cum_focus`], amount);
  }
});

const waterMeta = (id, extra = {}) => ({ source: "NOAA NWPS", unit: "ft", station_id: "WLON7", station_name: "Cape Fear River at Wilmington",
  source_time: at(3), input_ids: [id], provenance: { datum: "MLLW", flood_stage_ft: 5.5 }, ...extra });

test("water charts compare the matched gauge and datum and highlight only the controlling observed source", () => {
  const s = snap([rule("gauge", "water_above_flood_stage_ft", { hazard: "coastal", threshold: 0, unit: "ft", observed_value: 0.5,
    input_ids: ["water.WLON7.observed"], window_start: at(4), window_end: at(10) })]);
  const d = { rows: [{ t: at(5), obs_water_level_ft_WLON7: 6 }, { t: at(8), fcst_water_level_ft_WLON7: 10 }],
    meta: { obs_water_level_ft_WLON7: waterMeta("water.WLON7.observed"), fcst_water_level_ft_WLON7: waterMeta("water.WLON7.forecast") } };
  const [metric] = relevantMetrics(s, d);
  assert.equal(metric.waterLevel.stationId, "WLON7");
  assert.equal(metric.waterLevel.datum, "MLLW");
  assert.equal(metric.waterLevel.floodStage, 5.5);
  const evidence = metricEvidence(s, metric, d);
  assert.equal(evidence.rule.threshold, 5.5);
  assert.equal(evidence.rule.observed_value, 6);
  assert.equal(evidence.rows[0].obs_water_level_ft_WLON7_focus, 6);
  assert.equal(evidence.rows[1].fcst_water_level_ft_WLON7_focus, null);
  assert.equal(evidence.peak.value, 6);
});

test("water observations after evaluation, forecasts issued later, and incompatible gauge units are excluded", () => {
  const s = snap([rule("surge", "alert_present", { hazard: "coastal" })]);
  const d = { rows: [{ t: at(5), obs_water_level_ft_WLON7: 4 }, { t: at(8), obs_water_level_ft_WLON7: 20, fcst_water_level_ft_WLON7: 20 }],
    meta: { obs_water_level_ft_WLON7: waterMeta("water.WLON7.observed"),
      fcst_water_level_ft_WLON7: waterMeta("water.WLON7.forecast", { source_time: at(7) }),
      obs_water_level_ft_OTHER: waterMeta("water.OTHER.observed", { station_id: "OTHER", unit: "m" }) } };
  const metrics = relevantMetrics(s, d);
  assert.equal(metrics.length, 1);
  assert.equal(metrics[0].series.length, 1);
  assert.equal(metricEvidence(s, metrics[0], d).peak.value, 4);
});

test("different gauge datums and providers never share a chart or a numerical flood-stage comparison", () => {
  const s = snap([]);
  const d = { rows: [], meta: { obs_water_level_ft_WLON7: waterMeta("water.WLON7.observed"),
    fcst_water_level_ft_WLON7: waterMeta("water.WLON7.forecast", { provenance: { datum: "NAVD88", flood_stage_ft: 9 } }),
    obs_water_level_ft_WLON7_OTHER: waterMeta("water.WLON7.observed2", { source: "Other source" }),
    obs_water_level_ft_UNKNOWN: waterMeta("water.WLON7.unknown", { provenance: { datum: null, flood_stage_ft: 5.5 } }) } };
  const metrics = metricDefinitions(s, d).filter((m) => m.waterLevel);
  assert.equal(metrics.length, 4);
  assert.ok(metrics.every((m) => m.series.length === 1));
  assert.equal(metrics.at(-1).waterLevel.floodStage, null);
});
