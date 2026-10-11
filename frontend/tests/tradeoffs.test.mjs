import assert from "node:assert/strict";
import test from "node:test";
import { bestSetting, rateText, scenarioLoss } from "../src/tradeoffs.ts";

const point = (offset_pct, false_alarm, missed_disruption) => ({ offset_pct, current_thresholds: offset_pct === 0, confusion: { true_positive: 0, true_negative: 0, false_alarm, missed_disruption } });
const SWEEP = [point(-50, 143, 154), point(-25, 8, 159), point(0, 0, 160), point(25, 0, 181)];

test("scenario loss is false alarms x cost plus misses x cost", () => {
  assert.equal(scenarioLoss(SWEEP[1].confusion, 2, 7), 8 * 2 + 159 * 7);
});

test("costlier misses move the best setting toward easier thresholds", () => {
  assert.equal(bestSetting(SWEEP, 1, 1).offset_pct, 0);
  assert.equal(bestSetting(SWEEP, 1, 20).offset_pct, -25);
  assert.equal(bestSetting(SWEEP, 1, 1000).offset_pct, -50);
});

test("ties prefer today's thresholds", () => {
  assert.equal(bestSetting([point(-25, 0, 10), point(0, 0, 10)], 1, 1).offset_pct, 0);
});

test("rates show their denominator and say when data is missing", () => {
  assert.match(rateText({ count: 0, n: 3951, denominator: "non-disruptive days", rate: 0, ci95: [0, 0.001], status: "descriptive estimate", reason: null }), /0 of 3,951 non-disruptive days \(0\.0%, 95% range 0\.0%–0\.1%\)/);
  assert.equal(rateText({ count: 0, n: 0, denominator: "disruptive days", rate: null, ci95: null, status: "not enough data", reason: "No disruptive days in this sample." }), "No disruptive days in this sample.");
});
