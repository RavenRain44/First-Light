import assert from "node:assert/strict";
import test from "node:test";
import { parseReplayTime } from "../src/replay.ts";

const TZ = "America/Chicago";

test("custom replay preserves the selected minute in Central standard and daylight time", () => {
  assert.deepEqual(parseReplayTime("2023-02-22T05:17", TZ), { asOf: "2023-02-22T11:17:00.000Z", ambiguous: false });
  assert.deepEqual(parseReplayTime("2020-08-10T11:17", TZ), { asOf: "2020-08-10T16:17:00.000Z", ambiguous: false });
});

test("spring-forward uses the offset at the selected moment", () => {
  assert.equal(parseReplayTime("2025-03-09T01:30", TZ).asOf, "2025-03-09T07:30:00.000Z");
  assert.equal(parseReplayTime("2025-03-09T03:30", TZ).asOf, "2025-03-09T08:30:00.000Z");
  assert.throws(() => parseReplayTime("2025-03-09T02:30", TZ), /does not exist/);
});

test("fall-back resolves a unique post-transition time correctly and identifies the repeated hour", () => {
  assert.deepEqual(parseReplayTime("2025-11-02T01:30", TZ), { asOf: "2025-11-02T06:30:00.000Z", ambiguous: true });
  assert.deepEqual(parseReplayTime("2025-11-02T02:30", TZ), { asOf: "2025-11-02T08:30:00.000Z", ambiguous: false });
});

test("invalid and empty dates do not reach the replay API", () => {
  for (const wall of ["", "bad", "2025-02-29T05:00", "2025-09-31T05:00", "2025-01-01T24:00", "2025-01-01T12:60", "0000-01-01T00:00"]) {
    assert.throws(() => parseReplayTime(wall, TZ), /valid date and time/);
  }
  assert.equal(parseReplayTime("2024-02-29T05:00", TZ).asOf, "2024-02-29T11:00:00.000Z");
});

test("conversion supports facility timezones beyond Central, including fractional offsets", () => {
  assert.equal(parseReplayTime("2025-06-01T12:15", "Asia/Kolkata").asOf, "2025-06-01T06:45:00.000Z");
  assert.equal(parseReplayTime("2025-06-01T12:15", "UTC").asOf, "2025-06-01T12:15:00.000Z");
});
