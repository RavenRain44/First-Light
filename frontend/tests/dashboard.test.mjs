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
