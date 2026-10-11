import assert from "node:assert/strict";
import test from "node:test";
import { cooperPresentation, forecastOverview, readinessEvent, weatherHeading } from "../src/cooper.ts";

const asOf = "2026-01-13T06:30:00Z";
const at = (h) => new Date(Date.parse("2026-01-13T06:00:00Z") + h * 3600000).toISOString();
const input = (metric, value, hours = 24) => ({ id: `fcst.${metric}`, kind: "series", role: metric === "sky_cover_pct" ? "context" : "forecast",
  metric, source: "Recorded forecast", source_time: at(-3), series: Array.from({ length: hours }, (_, h) => ({ t: at(h), v: value })) });
const rule = (label, extra = {}) => ({ rule_id: label, label, hazard: "wind", metric: "alert_present", observed_value: label,
  triggered: true, available: true, level: 2, score: 70, ...extra });
const snap = (level, extra = {}) => ({ as_of: asOf, inputs: [input("temp_f", 65), input("wind_speed_mph", 8), input("pop_pct", 0)],
  readiness: { level, reasons: [] }, posture: { posture: "NORMAL", contributing_hazards: [], guidance: [] },
  confidence: { level: "high" }, hazards: {}, rules: [], ...extra });

test("each Cooper condition has the requested next step, independently of the suggested posture", () => {
  for (const [level, action] of [["WHITE", null], ["YELLOW", "Review decision"], ["ORANGE", "Draft decision"], ["RED", "Draft urgent decision"]]) {
    const s = snap(level);
    const p = cooperPresentation(s);
    assert.equal(p.level, level);
    assert.equal(p.action, action);
    assert.equal(p.urgent, ["ORANGE", "RED"].includes(level));
    assert.equal(s.posture.posture, "NORMAL");
  }
  assert.equal(cooperPresentation(snap("ORANGE")).title, "Start taking precautions");
  assert.equal(cooperPresentation(snap("RED")).title, "Send communication immediately");
});

test("White reflects actual skies and needs a complete clear forecast", () => {
  assert.equal(weatherHeading(snap("WHITE")), "Your local forecast");
  assert.equal(weatherHeading(snap("WHITE", { inputs: [input("sky_cover_pct", 0)] })), "Clear skies forecast");
  assert.equal(weatherHeading(snap("WHITE", { inputs: [input("sky_cover_pct", 90)] })), "Cloudy weather expected");
  assert.notEqual(weatherHeading(snap("WHITE", { inputs: [input("sky_cover_pct", 0, 23)] })), "Clear skies forecast");
  assert.notEqual(weatherHeading(snap("WHITE", { inputs: [input("sky_cover_pct", 0), input("pop_pct", 70)] })), "Clear skies forecast");
});

test("headlines describe cold and wind without changing recorded color rules", () => {
  const s = snap("WHITE", { inputs: [input("temp_f", 40), input("apparent_temp_f", 25), input("wind_gust_mph", 35)] });
  assert.equal(weatherHeading(s), "Cold, windy weather expected");
  assert.equal(cooperPresentation(s).level, "WHITE");
  assert.equal(weatherHeading(snap("YELLOW", { inputs: [input("temp_f", 25)] })), "Cold weather expected");
  assert.equal(weatherHeading(snap("YELLOW", { inputs: [input("wind_speed_mph", 25)] })), "Windy weather expected");
});

test("forecast summaries use the replay time, preserve zero, and exclude out-of-window extremes", () => {
  const temperature = input("temp_f", 40);
  temperature.series.push({ t: at(-1), v: -80 }, { t: at(24), v: 140 });
  const f = forecastOverview(snap("WHITE", { inputs: [temperature, input("pop_pct", 0)] }));
  assert.equal(f.temperature.min, 40);
  assert.equal(f.temperature.max, 40);
  assert.equal(f.temperature.hours, 24);
  assert.equal(f.precipitation.max, 0);
  assert.equal(f.start, at(0));
  assert.equal(f.end, at(24));
});

test("missing and invalid measurements never become reassuring zeroes", () => {
  const s = snap("YELLOW", { inputs: [input("pop_pct", null), input("wind_speed_mph", -10), input("sky_cover_pct", 110), input("temp_f", NaN)] });
  const f = forecastOverview(s);
  assert.equal(f.precipitation.max, null);
  assert.equal(f.wind.max, null);
  assert.equal(f.sky.max, null);
  assert.equal(f.temperature.max, null);
  assert.equal(weatherHeading(s), "Forecast data unavailable");
  const missingHour = input("sky_cover_pct", 0);
  missingHour.series[10].v = null;
  missingHour.series.push({ t: at(0), v: 0 });
  assert.notEqual(weatherHeading(snap("WHITE", { inputs: [missingHour] })), "Clear skies forecast");
});

test("Yellow gives weather-specific watch guidance and prioritizes incomplete evidence", () => {
  for (const [reason, phrase] of [["Wind gusts approaching threshold", "strengthening gusts"],
    ["Wind chill approaching threshold", "falling feels-like"], ["Winter Storm Watch issued", "commute routes"]]) {
    const s = snap("YELLOW", { readiness: { level: "YELLOW", reasons: [reason] } });
    assert.ok(cooperPresentation(s).watch.includes(phrase));
  }
  const s = snap("YELLOW", { confidence: { level: "low" }, rules: [rule("High Wind Advisory")] });
  assert.match(cooperPresentation(s).watch, /Confidence is low/);
});

test("Red names the event responsible for urgency rather than an unrelated watch", () => {
  const s = snap("RED", { readiness: { level: "RED", reasons: ["Tornado Warning is happening now"] },
    rules: [rule("Winter Storm Watch", { hazard: "winter", level: 1 }), rule("Tornado Warning", { level: 3 })] });
  assert.equal(readinessEvent(s), "Tornado Warning");
  assert.equal(cooperPresentation(s).title, "Send communication immediately: Tornado Warning");
});

test("an active watch takes priority over unrelated cold or windy background weather", () => {
  const inputs = [input("temp_f", 25), input("wind_gust_mph", 35)];
  for (const [event, phrase] of [["Winter Storm Watch", "ice or snow"], ["Tornado Watch", "be ready to shelter"]]) {
    const s = snap("YELLOW", { inputs, readiness: { level: "YELLOW", reasons: [`${event} issued`] },
      rules: [rule(event, { level: 1 })] });
    assert.ok(cooperPresentation(s).watch.includes(phrase));
  }
});

test("numeric urgency has a recorded label while deadline-only urgency invents no event", () => {
  const s = snap("RED", { readiness: { level: "RED", reasons: ["Destructive gusts is happening now"] },
    rules: [rule("Destructive gusts", { metric: "max_gust_mph", observed_value: 90 })] });
  assert.equal(readinessEvent(s), "Destructive gusts");
  const deadline = snap("RED", { readiness: { level: "RED", reasons: ["Telework must be announced by Tue 04:30 CST"] } });
  assert.equal(readinessEvent(deadline), null);
  assert.equal(cooperPresentation(deadline).title, "Send communication immediately");
});

test("old snapshots without readiness remain explicitly unknown with their forecast available", () => {
  const s = snap(null, { readiness: null });
  const p = cooperPresentation(s);
  assert.equal(p.level, null);
  assert.equal(p.title, "Readiness not recorded");
  assert.equal(p.action, "Review decision");
  assert.equal(forecastOverview(s).temperature.max, 65);
  assert.equal(cooperPresentation(snap("UNKNOWN")).level, null);
});
