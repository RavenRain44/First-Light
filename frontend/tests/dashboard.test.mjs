import assert from "node:assert/strict";
import test from "node:test";
import { METRICS, crossesThreshold, metricEvidence, relevantMetrics, suggestionReasons } from "../src/dashboard.ts";

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

test("missing snow forecasts stay missing and unrelated wind does not fill a snow event", () => {
  const s = snap([rule("blizzard", "alert_present", { hazard: "winter", observed_value: "Blizzard Warning" })]);
  const d = data([{ t: at(8), fcst_ice_cum: 0, fcst_wind_gust_mph: 10 }]);
  assert.deepEqual(relevantMetrics(s, d).map((m) => m.id), ["snow"]);
  assert.equal(metricEvidence(s, METRICS.find((m) => m.id === "snow"), d).peak, null);
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

test('sustained wind rules highlight sustained wind rather than gusts', () => {
  const s=snap([rule('sustained','fcst_max_sustained_24h_mph',{threshold:40,observed_value:45})]);
  const result=metricEvidence(s,METRICS[0],data([{t:at(8),fcst_wind_speed_mph:45,fcst_wind_gust_mph:70}]));
  assert.deepEqual(result.keys,['fcst_wind_speed_mph']);
  assert.equal(result.rows[0].fcst_wind_speed_mph_focus,45);
  assert.equal(result.rows[0].fcst_wind_gust_mph_focus,null);
});
