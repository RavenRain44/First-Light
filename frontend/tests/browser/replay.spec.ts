import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import type { NormalizedInput, ReplayEvent, ReplayPoint, Snapshot } from "../../src/types";

const dist = fileURLToPath(new URL("../../dist/", import.meta.url));
const history = fileURLToPath(new URL("../../../backend/fixtures/history/", import.meta.url));
const blizzardFixture = JSON.parse(await readFile(fileURLToPath(new URL("../../../backend/fixtures/blizzard_2022-12-22T18Z_chart.json", import.meta.url)), "utf8"));
const events: ReplayEvent[] = await Promise.all(["ice-2023-02-22", "derecho-2020-08-10", "blizzard-2022-12-22"].map(async (id) => {
  const data = JSON.parse(await readFile(`${history}${id}.json`, "utf8"));
  return { ...data.event, verification: data.verification, outcome: data.outcome, backtest: data.backtest, timeline: data.timeline };
}));
const controlFixture = JSON.parse(await readFile(`${history}normal-2024-07-18.json`, "utf8"));
const controlTimeline: ReplayPoint[] = Array.from({ length: 24 }, (_, h) => ({
  as_of: new Date(Date.parse(controlFixture.event.start) + h * 3600000).toISOString(),
  posture: "NORMAL", readiness: "YELLOW", coverage: "partial", unavailable_sources: ["Archived forecast", "Historical warnings"],
}));
events.push({ ...controlFixture.event, timeline: controlTimeline,
  verification: { checks: [{ product: "METAR coverage", ugc: "AMW", verified: true, events: [{ link: controlFixture.source.url }] }] },
  outcome: { summary: "24/24 hours covered at AMW; no reported freezing precipitation or snow; no defined station-level disruption." },
  backtest: { at_0400_local: { as_of: controlTimeline[4].as_of, posture: "NORMAL" }, verdict: "Quiet observed outcome; future conditions were unknown at 04:00.", label: "observations only; not a verified office decision" },
});

function snapshot(asOf: string, point: ReplayPoint, eventId: string | null): Snapshot {
  return {
    snapshot_id: `test-${eventId ?? "custom"}-${Date.parse(asOf)}`, as_of: asOf, created_at: asOf,
    mode: "replay", event_id: eventId, facility_id: "IA-AMES-SC", thresholds_version: "test", thresholds_sha256: "test",
    model_id: "deterministic-fallback", prompt_version: "test", content_sha256: "test", integrity_ok: true,
    facility: { id: "IA-AMES-SC", name: "Test facility", synthetic: true, state: "IA", timezone: "America/Chicago",
      lat: 42.0308, lon: -93.6319, hours: { open: "07:30", close: "16:30" }, corridors: [], accessibility_notes: [] },
    roster: { assigned: 270, expected_in_building: 270 }, inputs: [], alerts: [], sources: [], signals: {}, rules: [], hazards: {},
    posture: { posture: point.posture ?? "NORMAL", decision_day: asOf.slice(0, 10), opm_label: "Recorded test recommendation",
      opm_section: "test", contributing_hazards: [], reasons: [], guidance: [] },
    readiness: { level: point.readiness ?? "YELLOW", reasons: [], meaning: "Recorded test readiness", cooper: "test",
      decide_by: null, deadline_passed: false, recheck_minutes: 10, basis: "test" },
    confidence: { level: "medium", score: 0.5, factors: [] }, changes: [], watch_next_6h: [], analogs: [], features: {},
    ai: { headline: "Test brief", summary: "Recorded evidence for manager review.", rationale_paragraph: "Test rationale",
      what_would_change: [], watch_next_6h: [], alert_summaries: {}, analog_comparison: "No analogs" },
  };
}

type Weather = "pavement" | "snow" | "ice" | "freezing";

function withControl(report: Snapshot): Snapshot {
  const past = controlFixture.source.rows.filter((r: any) => Date.parse(r.utc_valid) >= Date.parse(report.as_of) - 12 * 3600000
    && Date.parse(r.utc_valid) <= Date.parse(report.as_of) - 15 * 60000);
  report.mode = "backtest";
  report.inputs = ["temp_f", "wind_speed_mph"].map((metric) => ({
    id: `obs.${metric}`, kind: "series", role: "observation", metric, unit: metric === "temp_f" ? "degF" : "mph", value: null,
    series: past.map((r: any) => ({ t: r.utc_valid, v: metric === "temp_f" ? r.tmpf : r.sknt * 1.150779 })), data: null,
    source: "AMW archived routine/special METAR", source_url: controlFixture.source.url,
    fetched_at: controlFixture.source.fetched_at, source_time: past.at(-1).utc_valid, note: "Assumed 15-minute availability lag",
  }));
  report.sufficiency = { status: "insufficient", headline: "Insufficient current data", reasons: ["Archived forecast and historical warnings unavailable"],
    missing_sources: ["Archived NBS forecast", "Historical warnings"], stale_sources: [], checks: [], supports_all_clear: false,
    reason_required: true, hazard_evidence: [], forecast_coverage: null,
    evaluated_as_of: report.as_of, mode: "backtest", mode_note: "Historical reconstruction, not current weather", policy_version: "test" };
  report.historical_context = { control: { kind: "normal-weather" }, status: "partial", reconstruction: "Retained observation-only normal-weather control",
    as_of: report.as_of, outcome: { gradable: true, disruptive: false }, detail: "Quiet local weather verified by a complete daily station record; forecasts and warnings unknown.",
    missing: ["Archived forecasts unavailable", "Historical warnings unavailable"], proxy_records: [], provenance: controlFixture.source };
  return report;
}

function withWeather(report: Snapshot, weather: Weather): Snapshot {
  const asOf = report.as_of, end = new Date(Date.parse(asOf) + 3 * 3600000).toISOString();
  const sourceTime = new Date(Date.parse(asOf) - 30 * 60000).toISOString();
  const pavement = weather === "pavement", freezing = weather === "freezing";
  const metric = pavement ? "rwis_ice_sensors" : freezing ? "obs_freezing_precip_hours_3h" : "alert_present";
  const label = pavement ? "RWIS sensors reporting ice" : freezing ? "Observed freezing precipitation"
    : weather === "snow" ? "Winter Storm Warning" : "Ice Storm Warning";
  const observed = pavement ? 1 : freezing ? 2 : label;
  const rule = { rule_id: `winter.${weather}`, hazard: "winter", metric, label, operator: ">=", threshold: 1,
    unit: pavement ? "sensors" : freezing ? "hours" : "alert", observed_value: observed, triggered: true, available: true,
    margin_abs: 0, margin_pct: 0, time_of_peak: sourceTime, window_start: sourceTime, window_end: end, input_ids: [],
    level: pavement ? 1 : 2, posture_effect: pavement ? "minor" : "significant", score: pavement ? 30 : 60,
    verified: false, basis: "policy", anchor: "Test evidence", source_url: "https://example.test/weather", time_window: "Test window", detail: null };
  const input = (metric: string, value: number, observation = false): NormalizedInput => ({
    id: `${observation ? "obs" : "fcst"}.${metric}`, kind: observation ? "scalar" : "series",
    metric, role: observation ? "observation" : "forecast", unit: metric.includes("temp") ? "degF" : "in", value: observation ? value : null,
    series: observation ? null : [{ t: asOf, v: value }], data: null, source: "Recorded test weather",
    source_url: "https://example.test/weather", source_time: sourceTime, fetched_at: asOf, note: null,
  });
  report.rules = [rule];
  report.inputs = [input("temp_f", 28), input("snow_in", weather === "snow" ? 6 : 0), input("ice_in", weather === "ice" ? 0.3 : 0)];
  if (pavement) report.inputs.push(input("pavement_temp_f", 28, true));
  if (pavement || freezing) report.signals = { [metric]: { value: observed, available: true, role: "observation", peak_time: sourceTime } };
  report.hazards = { winter: { hazard: "winter", label: "Winter / ice", score: rule.score, level: rule.level,
    level_name: rule.posture_effect, triggered_rule_ids: [rule.rule_id], controlling_rule_ids: [rule.rule_id],
    window_start: sourceTime, window_end: end, time_of_peak: sourceTime, posture: "DELAYED_ARRIVAL", posture_reason: "AM commute" } };
  report.posture = { ...report.posture, posture: "DELAYED_ARRIVAL", contributing_hazards: ["winter"] };
  report.readiness = { ...report.readiness!, level: "RED", decide_by: new Date(Date.parse(asOf) + 30 * 60000).toISOString(),
    reasons: [pavement ? "Delayed Arrival must be announced by Wed 04:30 CST" : `${label} is happening now`] };
  report.ai.suggested_reasons = [{ rule_id: rule.rule_id, text: pavement ? "RWIS sensors reporting ice of 1 sensors" : `${label} in effect` }];
  if (weather === "snow") report.alerts = [{ id: "test", event: label, headline: "Heavy snow expected, 6 to 8 inches.",
    description: null, instruction: null, severity: "Severe", certainty: "Likely", urgency: "Expected",
    onset: sourceTime, ends: end, expires: end, sent: sourceTime, areaDesc: "Test county" }];
  return report;
}

function withBackup(report: Snapshot): Snapshot {
  const issue = new Date(Date.parse(report.as_of) - 4 * 3600000).toISOString();
  report.mode = "backtest";
  report.inputs = ["temp_f", "wind_speed_mph"].map((metric) => ({
    id: `fcst.${metric}`, kind: "series", role: "forecast", metric, unit: metric === "temp_f" ? "degF" : "mph", value: null,
    series: Array.from({ length: 48 }, (_, h) => ({ t: new Date(Date.parse(report.as_of) + h * 3600000).toISOString(), v: metric === "temp_f" ? 65 : 8 })),
    data: { weather_fallback: true }, source: "Archived GFS MOS backup forecast (IEM)",
    source_url: "https://example.test/original-forecast", fetched_at: report.as_of, source_time: issue, note: "Original forecast, available before the selected time",
  }));
  report.posture = { ...report.posture, posture: "NORMAL", guidance: [], contributing_hazards: [] };
  report.readiness = { ...report.readiness!, level: "YELLOW", reasons: ["Backup forecast in use: verify missing evidence before deciding"], decide_by: null };
  report.sufficiency = { status: "limited", headline: "Provisional recommendation · backup forecast", provisional: true,
    forecast_sources: ["Archived GFS MOS backup forecast (IEM)"], reasons: ["Snow and ice amounts are unknown; verify local warnings."],
    missing_sources: ["Original warning history"], stale_sources: [], checks: [], supports_all_clear: false,
    reason_required: true, hazard_evidence: [], forecast_coverage: 1 };
  report.confidence = { level: "medium", score: 0.65, factors: [] };
  return report;
}

async function mockApp(page: Page, options: { pendingAi?: boolean; failFirstEvent?: boolean; holdReplay?: boolean; weather?: Weather; dateSearch?: boolean; blizzard?: boolean; backup?: boolean } = {}) {
  const loads: { event: string[]; replay: string[]; custom: string[]; ai: number } = { event: [], replay: [], custom: [], ai: 0 };
  const errors: string[] = [], unexpected: string[] = [];
  let failed = false;
  let releaseReplay = () => {};
  const replayGate = new Promise<void>((resolve) => { releaseReplay = resolve; });
  const saved = new Map<string, Snapshot>();
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const request = route.request(), url = new URL(request.url());
    try {
      if (!url.pathname.startsWith("/api/")) {
        const path = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
        const contentType = path.endsWith(".js") ? "text/javascript" : path.endsWith(".css") ? "text/css" : path.endsWith(".png") ? "image/png" : "text/html";
        return await route.fulfill({ contentType, body: await readFile(`${dist}${path}`) });
      }
      if (url.pathname === "/api/facilities") return await route.fulfill({ json: [snapshot("2026-10-11T10:00:00Z", { as_of: "2026-10-11T10:00:00Z", posture: "NORMAL", readiness: "WHITE" }, null).facility] });
      if (url.pathname === "/api/health") return await route.fulfill({ json: { demo_mode: true, inference: { enabled: false }, model_provider: "none" } });
      if (url.pathname === "/api/snapshot/latest") return await route.fulfill({ json: { ...snapshot("2026-10-11T10:00:00Z", { as_of: "2026-10-11T10:00:00Z", posture: "NORMAL", readiness: "WHITE" }, null), mode: "live" } });
      if (url.pathname === "/api/risk-tradeoffs") return await route.fulfill({ json: { errors: {} } });
      if (url.pathname === "/api/past-decisions") return await route.fulfill({ json: { decisions: [], reviewing: [] } });
      if (url.pathname === "/api/roads") return await route.fulfill({ json: { status: "not_applicable", corridors: [] } });
      if (url.pathname === "/api/timeseries") {
        const report = saved.get(url.searchParams.get("snapshot_id")!);
        if (options.blizzard && report?.snapshot_id === blizzardFixture.snapshot.snapshot_id) return await route.fulfill({ json: blizzardFixture.timeseries });
        const rows = new Map<string, Record<string, string | number | null>>();
        for (const input of report?.inputs ?? []) for (const point of input.series ?? []) {
          const row = rows.get(point.t) ?? { t: point.t };
          const key = `${input.role === "observation" ? "obs" : "fcst"}_${input.metric}`;
          row[key] = point.v;
          if (key === "fcst_snow_in" || key === "fcst_ice_in") row[key.replace("_in", "_cum")] = point.v;
          rows.set(point.t, row);
        }
        return await route.fulfill({ json: { rows: [...rows.values()], meta: {}, timezone: "America/Chicago" } });
      }
      if (url.pathname === "/api/backtesting") return await route.fulfill({ json: {
        jobs: [], proxy_records: [], latest_disruptive_days: [], supported_start: "1996-01-01", supported_end: "2026-10-10",
        storage: { source_years: [], compressed_source_bytes: 0, compressed_evaluation_bytes: 0, mean_evaluation_bytes: 0, db_bytes: 0 },
      } });
      if (url.pathname === "/api/history/events") return await route.fulfill({ json: events });
      const event = events.find((item) => url.pathname === `/api/history/events/${item.id}`);
      if (event) {
        loads.event.push(event.id);
        if (options.failFirstEvent && !failed) { failed = true; return await route.fulfill({ status: 503, json: { detail: "Archive temporarily unavailable" } }); }
        return await route.fulfill({ json: event });
      }
      const replayEvent = events.find((item) => url.pathname === `/api/history/events/${item.id}/replay`);
      if (replayEvent) {
        const asOf = url.searchParams.get("as_of")!;
        loads.replay.push(asOf);
        const point = replayEvent.timeline.find((item) => Date.parse(item.as_of) === Date.parse(asOf)) ?? replayEvent.timeline[4];
        const report = options.blizzard && Date.parse(asOf) === Date.parse(blizzardFixture.snapshot.as_of)
          ? structuredClone(blizzardFixture.snapshot) : snapshot(asOf, point, replayEvent.id);
        if (replayEvent.kind === "normal-control") withControl(report);
        if (options.backup) withBackup(report);
        if (options.weather) withWeather(report, options.weather);
        if (options.pendingAi) report.ai_addon = { status: "pending" };
        saved.set(report.snapshot_id, report);
        if (options.holdReplay) await replayGate;
        return await route.fulfill({ json: report });
      }
      if (url.pathname.endsWith("/interpretation")) {
        loads.ai++;
        const report = saved.get(decodeURIComponent(url.pathname.split("/")[3]))!;
        return await route.fulfill({ json: { status: "ok", model_id: "akamai:test", ai: report.ai } });
      }
      if (url.pathname === "/api/replay/timeline") {
        const asOf = url.searchParams.get("as_of")!;
        const timeline = Array.from({ length: 25 }, (_, i): ReplayPoint => ({
          as_of: new Date(Date.parse(asOf) + (i - 12) * 3600000).toISOString(), coverage: "complete",
          posture: i === 12 ? "EARLY_DISMISSAL" : "NORMAL", readiness: i === 12 ? "RED" : "YELLOW",
        }));
        return await route.fulfill({ json: { as_of: asOf, timezone: "America/Chicago", selected_index: 12, timeline } });
      }
      if (url.pathname === "/api/evaluate") {
        const asOf = request.postDataJSON().as_of;
        loads.custom.push(asOf);
        return await route.fulfill({ json: snapshot(asOf, { as_of: asOf, posture: "EARLY_DISMISSAL", readiness: "RED" }, null) });
      }
      unexpected.push(`${request.method()} ${url.pathname}`);
      return await route.fulfill({ status: 404, json: { detail: "Unexpected API request" } });
    } catch (error) {
      if (!/Target.*closed|cancelled|aborted|Invalid InterceptionId|already handled/.test(String(error))) throw error;
    }
  });
  await page.goto("http://replay.test/");
  await page.getByRole("button", { name: "More tools", exact: true }).click();
  await page.getByRole("menuitem", { name: "Replay a past storm" }).click();
  if (!options.dateSearch) await page.getByRole("button", { name: "Curated storm timeline", exact: true }).click();
  return { loads, errors, unexpected, releaseReplay };
}

const loading = (page: Page) => page.getByRole("status").filter({ hasText: /^Loading .*The report and timeline/ });

for (const width of [390, 1280]) test(`backup forecast remains provisional and identifies unknown ice at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  const app = await mockApp(page, { backup: true });
  await page.getByRole("combobox", { name: /^Event\b/ }).selectOption("normal-2024-07-18");
  const dashboard = page.getByTestId("cooper-dashboard");
  await expect(dashboard).toHaveAttribute("data-condition", "YELLOW");
  await expect(dashboard.getByRole("heading", { level: 2 })).toHaveText("Provisional forecast · verify before deciding");
  await expect(page.getByTestId("backup-source")).toContainText("Archived GFS MOS");
  await expect(page.getByTestId("evidence-notice")).toContainText("Snow and ice amounts are unknown");
  await expect(page.getByTestId("provisional-label")).toBeVisible();
  await expect(page.getByTestId("fallback-label")).toHaveCount(0);
  await expect(page.getByTestId("suggested-action")).toContainText("Based on a backup forecast");
  await expect(dashboard).toContainText("This is a replay of past weather");
  await page.getByTestId("forecast-charts").getByText("View forecast charts", { exact: true }).click();
  await expect(page.getByTestId("forecast-charts").locator('figure[data-metric="temp"]')).toBeVisible();
  await expect(page.getByTestId("forecast-charts").locator('figure[data-metric="wind"]')).toBeVisible();
  await expect(page.locator('figure[data-metric="ice"]')).toHaveCount(0);
  expect(app.errors).toEqual([]); expect(app.unexpected).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

for (const width of [390, 1280]) test(`the archived pre-Christmas blizzard shows its wind chill and older road point at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const app = await mockApp(page, { blizzard: true });
  await page.getByRole("combobox", { name: /^Event\b/ }).selectOption("blizzard-2022-12-22");
  await expect(page.getByTestId("replay-selected-time")).toContainText("Dec 22, 2022, 04:00 CST");
  const event = events.find((e) => e.id === "blizzard-2022-12-22")!;
  const index = event.timeline.findIndex((p) => Date.parse(p.as_of) === Date.parse(blizzardFixture.snapshot.as_of));
  await page.getByRole("group", { name: "Recommended posture by hour" }).getByRole("button").nth(index).click();
  await expect(page.getByTestId("replay-selected-time")).toContainText("Dec 22, 2022, 12:00 CST");
  const metrics = page.getByRole("region", { name: "Concerning weather data" });
  await expect(metrics.locator("figure")).toHaveCount(3);
  await expect(metrics).toContainText("0.00 in of additional snow");
  await expect(metrics.locator("figure").first()).toHaveAttribute("data-metric", "wind");
  const cold = metrics.locator('[data-metric="temp"]');
  await expect(cold.locator("figcaption")).toContainText("-37°F");
  await expect(cold).toContainText("Observed feels-like");
  await expect(cold).toContainText("Forecast feels-like");
  await expect(cold).toContainText(blizzardFixture.snapshot.rules.find((r: any) => r.rule_id === "cold.fcst_wind_chill_extreme").label);
  await expect(cold.locator(".recharts-line-curve").first()).toBeVisible();
  const roads = metrics.locator('[data-metric="roads"]');
  await expect(roads.locator("figcaption")).toContainText("Travel advisory");
  await expect(roads.locator("figcaption")).toContainText("07:37 CST");
  await expect(roads.locator(".recharts-reference-dot")).toBeVisible();
  await roads.getByRole("button", { name: "Show full timeline" }).click();
  await expect(roads.locator(".recharts-reference-dot")).toBeVisible();
  await expect(metrics.locator('[data-metric="snow"], [data-metric="ice"]')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(app.errors).toEqual([]); expect(app.unexpected).toEqual([]);
});

for (const dateSearch of [false, true]) test(`normal-weather control is available offline in ${dateSearch ? "date search" : "curated timeline"} with observed charts and no all-clear`, async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const app = await mockApp(page, { dateSearch });
  await page.getByRole("combobox", { name: dateSearch ? "Listed event" : /^Event\b/ }).selectOption(controlFixture.event.id);
  if (dateSearch) {
    await expect(page.getByLabel("Date", { exact: true })).toHaveValue("2024-07-18");
    await expect(page.getByRole("combobox", { name: "Reconstruction" })).toHaveValue("observation");
    await page.getByLabel("Time · America/Chicago").fill("04:17");
    await page.getByRole("button", { name: "View historical weather", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Retained observation-only" })).toContainText("No defined local disruption observed");
    expect(app.loads.replay).toEqual(["2024-07-18T09:17:00.000Z"]);
  } else {
    await expect(page.getByTestId("replay-selected-time")).toContainText("Jul 18, 2024, 04:00 CDT");
    await expect(page.getByText("24/24 hours covered at AMW", { exact: false })).toBeVisible();
    await expect(page.getByText("observations only; not a verified office decision", { exact: true })).toBeVisible();
  }
  const dashboard = page.getByTestId("cooper-dashboard");
  await expect(dashboard).toHaveAttribute("data-condition", "YELLOW");
  await expect(dashboard.getByRole("heading", { name: "Insufficient current data", exact: true })).toBeVisible();
  await expect(dashboard.getByTestId("suggested-action")).toContainText("Normal is only the fallback");
  await expect(dashboard).toContainText("no decision is recorded and no one is alerted");
  const metrics = page.getByRole("region", { name: "Observed weather for this control" });
  await expect(metrics.locator("figure").first()).toHaveAttribute("data-metric", "temp");
  await expect(metrics.locator("figure").nth(1)).toHaveAttribute("data-metric", "wind");
  await expect(metrics).toContainText("Observed wind (hourly report)");
  await expect(metrics.locator(".recharts-line-curve").first()).toBeVisible();
  await expect(metrics.locator('[data-metric="snow"], [data-metric="ice"]')).toHaveCount(0);
  expect(await page.evaluate(() => [...document.querySelectorAll("body *")]
    .filter((e) => e.getBoundingClientRect().width > 0 && e.getBoundingClientRect().right > innerWidth + 1)
    .map((e) => `${e.tagName}.${e.getAttribute("class")}: ${e.textContent?.slice(0, 70)}`).slice(-10))).toEqual([]);
  expect(app.loads.ai).toBe(0); expect(app.loads.custom).toEqual([]);
  expect(app.errors).toEqual([]); expect(app.unexpected).toEqual([]);
});

test("an untouched curated timeline settles once and stays stable across parent renders and AI completion", async ({ page }) => {
  const app = await mockApp(page, { pendingAi: true });
  await expect(page.getByTestId("replay-selected-time")).toContainText("Feb 22, 2023, 04:00 CST");
  await expect(page.getByTestId("cooper-dashboard")).toBeVisible();
  await expect(loading(page)).toHaveCount(0);
  await page.getByRole("button", { name: "Toggle dark mode" }).click();
  // Wait through the real AI polling interval, without using Evaluate to stop auto-selection.
  await expect(page.getByTestId("cooper-dashboard")).toContainText("Powered by Akamai", { timeout: 5000 });
  await page.waitForTimeout(500);
  expect(app.loads.event).toEqual(["ice-2023-02-22"]);
  expect(app.loads.replay).toEqual([events[0].backtest.at_0400_local.as_of]);
  expect(app.loads.ai).toBe(1);
  await expect(loading(page)).toHaveCount(0);
  expect(app.errors).toEqual([]); expect(app.unexpected).toEqual([]);
});

for (const [weather, primary, title] of [
  ["pavement", "rwis", "Decision due soon: delayed arrival"],
  ["snow", "snow", "Send communication immediately: Winter Storm Warning"],
  ["ice", "ice", "Send communication immediately: Ice Storm Warning"],
  ["freezing", "freezing", "Send communication immediately: Observed freezing precipitation"],
] as const) test(`${weather} events show the correct evidence graph and readiness explanation`, async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const app = await mockApp(page, { weather });
  const dashboard = page.getByTestId("cooper-dashboard");
  await expect(dashboard).toHaveAttribute("data-condition", "RED");
  await expect(dashboard.getByRole("heading", { name: title, exact: true })).toBeVisible();
  const metrics = page.getByRole("region", { name: "Concerning weather data" });
  await expect(metrics.locator("figure").first()).toHaveAttribute("data-metric", primary);
  await expect(metrics.locator("figure").nth(1)).toHaveAttribute("data-metric", "temp");
  if (weather === "pavement") {
    await expect(dashboard.getByTestId("readiness-urgency")).toContainText("weather hazard is rated minor");
    await expect(dashboard.getByTestId("suggested-action")).toContainText("1 nearby pavement sensor reporting an ice watch/warning condition");
    await expect(metrics).toContainText("not inches of ice or affected roads");
    await expect(metrics.locator('[data-metric="rwis"]')).toContainText("1 sensor");
  }
  if (weather !== "ice") await expect(metrics.locator('[data-metric="ice"]')).toHaveCount(0);
  if (weather !== "snow") await expect(metrics.locator('[data-metric="snow"]')).toHaveCount(0);
  await expect(metrics.locator(".recharts-reference-area").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(app.errors).toEqual([]); expect(app.unexpected).toEqual([]);
});

test("hour controls, playback, event switching, and exact-minute custom dates keep both ribbons in sync", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const app = await mockApp(page);
  const selected = page.getByTestId("replay-selected-time");
  await expect(selected).toContainText("04:00 CST");
  await page.getByRole("button", { name: "Next hour" }).click();
  await expect(selected).toContainText("05:00 CST");
  await page.getByRole("button", { name: "Previous hour" }).click();
  await expect(selected).toContainText("04:00 CST");
  await page.getByRole("button", { name: /Play/ }).click();
  await expect(selected).toContainText("05:00 CST");
  await page.getByRole("button", { name: /Pause/ }).click();
  const paused = app.loads.replay.length;
  await page.waitForTimeout(1600);
  expect(app.loads.replay).toHaveLength(paused);
  await page.getByRole("combobox", { name: /^Event\b/ }).selectOption("derecho-2020-08-10");
  await expect(selected).toContainText("Aug 10, 2020, 04:00 CDT");
  await page.getByLabel("Any moment (Central time)").fill("2020-08-10T11:17");
  await page.getByRole("button", { name: "Evaluate", exact: true }).click();
  await expect(selected).toContainText("Aug 10, 2020, 11:17 CDT");
  expect(app.loads.custom).toEqual(["2020-08-10T16:17:00.000Z"]);
  const posture = page.getByRole("group", { name: "Recommended posture by hour" });
  await expect(posture.locator("button")).toHaveCount(25);
  await expect(posture.locator('[aria-pressed="true"]')).toHaveAttribute("title", /Early dismissal/);
  await expect(page.getByRole("img", { name: "Readiness (Cooper color) by hour" }).locator('[data-selected="true"]')).toHaveAttribute("title", /Condition RED/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(loading(page)).toHaveCount(0);
  expect(app.errors).toEqual([]); expect(app.unexpected).toEqual([]);
});

test("initial failures remain stable until an explicit event retry", async ({ page }) => {
  const app = await mockApp(page, { failFirstEvent: true });
  await expect(page.getByRole("alert")).toContainText("Archive temporarily unavailable");
  await page.waitForTimeout(1500);
  expect(app.loads.event).toEqual(["ice-2023-02-22"]);
  expect(app.loads.replay).toHaveLength(0);
  await expect(loading(page)).toHaveCount(0);
  await page.getByRole("combobox", { name: /^Event\b/ }).selectOption("ice-2023-02-22");
  await expect(page.getByTestId("replay-selected-time")).toContainText("Feb 22, 2023");
  expect(app.loads.event).toHaveLength(2); expect(app.loads.replay).toHaveLength(1);
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(app.errors).toEqual([]); expect(app.unexpected).toEqual([]);
});

test("leaving curated replay cancels a pending report and ignores its late response", async ({ page }) => {
  const app = await mockApp(page, { holdReplay: true });
  try {
    await expect.poll(() => app.loads.replay.length).toBe(1);
    await page.getByRole("button", { name: "Date search & multi-year scores", exact: true }).click();
    app.releaseReplay();
    await page.waitForTimeout(300);
    await expect(page.getByTestId("replay-selected-time")).toHaveCount(0);
    await expect(page.getByTestId("cooper-dashboard")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "View historical weather", exact: true })).toBeEnabled();
    expect(app.loads.replay).toHaveLength(1);
    expect(app.errors).toEqual([]); expect(app.unexpected).toEqual([]);
  } finally { app.releaseReplay(); }
});

test("returning to live weather ignores an unfinished curated replay", async ({ page }) => {
  const app = await mockApp(page, { holdReplay: true });
  try {
    await expect.poll(() => app.loads.replay.length).toBe(1);
    await page.getByRole("button", { name: "Return to live", exact: true }).click();
    const dashboard = page.getByTestId("cooper-dashboard");
    await expect(dashboard).toHaveAttribute("data-condition", "WHITE");
    app.releaseReplay();
    await page.waitForTimeout(300);
    await expect(dashboard).toHaveAttribute("data-condition", "WHITE");
    await expect(dashboard).toContainText("Last updated");
    await expect(page.getByTestId("replay-selected-time")).toHaveCount(0);
    expect(app.loads.replay).toHaveLength(1);
    expect(app.errors).toEqual([]); expect(app.unexpected).toEqual([]);
  } finally { app.releaseReplay(); }
});


test("historical context stays explicit in dark mobile views and clears on return", async ({ page }) => {
  const app = await mockApp(page);
  const context = page.getByRole("complementary", {name:"Weather viewing context"});
  await expect(context).toContainText("HISTORICAL DATA");
  await expect(context).toContainText("America/Chicago");
  await expect(page.locator(".historical-workspace")).toHaveCount(1);
  await page.getByRole("button", {name:"Toggle dark mode"}).click();
  await page.setViewportSize({width:390,height:844});
  await expect(context.getByRole("button", {name:"Return to live"})).toBeVisible();
  await page.screenshot({path:test.info().outputPath("closure-call-historical-dark.png"),animations:"disabled"});
  await context.getByRole("button", {name:"Return to live"}).click();
  await expect(context).toContainText("DEMO · Cached weather");
  await expect(context).not.toContainText("HISTORICAL DATA");
  await expect(page.locator(".historical-workspace")).toHaveCount(0);
  expect(app.errors).toEqual([]);
});


test("Today clears saved decision evidence before live data arrives", async ({ page }) => {
  await mockApp(page);
  const old = {...snapshot("2020-08-10T16:00:00Z", {as_of:"2020-08-10T16:00:00Z",posture:"CLOSED",readiness:"RED"}, null), mode:"live"};
  await page.route(url => url.pathname === "/api/decisions", r => r.fulfill({json:[{id:99, facility_id:old.facility_id, snapshot_id:"saved-old", decision_posture:"CLOSED", decided_at:old.as_of, decided_by:"Test manager"}]}));
  await page.route(url => url.pathname === "/api/snapshot/saved-old", r => r.fulfill({json:{...old,snapshot_id:"saved-old"}}));
  await page.getByRole("button", {name:"Decision log",exact:true}).click();
  await page.getByRole("button", {name:"View saved weather & cameras"}).click();
  const context = page.getByRole("complementary", {name:"Weather viewing context"});
  await expect(context).toContainText("Saved decision #99");
  await expect(page.getByTestId("dashboard-metadata")).toContainText("Weather as of");
  await expect(page.getByTestId("dashboard-metadata")).not.toContainText("Last updated");
  await expect(page.getByTestId("cooper-dashboard")).toHaveAttribute("data-condition","RED");
  let release = () => {};
  const gate = new Promise<void>(resolve => {release=resolve;});
  await page.route(url => url.pathname === "/api/snapshot/latest", async route => {
    await gate;
    await route.fulfill({json:{...old,snapshot_id:"new-live",as_of:"2026-10-11T10:00:00Z",readiness:{...old.readiness,level:"WHITE"}}});
  });
  try {
    await page.getByRole("button", {name:"Today",exact:true}).click();
    await expect(page.getByTestId("cooper-dashboard")).toHaveCount(0);
    await expect(context).not.toContainText("2020");
    release();
    await expect(page.getByTestId("cooper-dashboard")).toHaveAttribute("data-condition","WHITE");
  } finally {release();}
});

test('notification groups support editing, selection, errors and simulated sends', async ({page}) => {
  const app=await mockApp(page);
  const names=['Onsite telework','Onsite leave','Essential','Remote'];
  const groups=names.map((title,i)=>({id:`g${i}`,title,kind:i===3?'awareness':'onsite',instruction:'Follow reporting instructions.',instruction_text:'Follow reporting instructions.',location_text:'Test facility',decision_text:'Closed.',sms_intro:'Closed',email_intro:'Closed',recipient_ids:[`r${i}`],test_contacts:[],scenario:'success',recipients:[{id:`r${i}`,name:`Synthetic person ${i}`,channels:['email'],due_at:'2026-10-12T12:30:00Z'}]}));
  const pack={id:1,facility_id:'IA-AMES-SC',decision_id:99,version:1,status:'draft',facility_name:'Test facility',timezone:'America/Chicago',decision_day:'2026-10-12',posture:'CLOSED',decided_by:'Test manager',draft_source:'Template',groups,excluded:[],messages:[]};
  await page.route(url=>url.pathname==='/api/decisions',r=>r.fulfill({json:[{id:99,facility_id:pack.facility_id,snapshot_id:'test',decision_posture:'CLOSED',decided_at:'2026-10-12T09:00:00Z',decided_by:'Test manager'}]}));
  await page.route(url=>url.pathname==='/api/notifications',r=>r.fulfill({json:{facility_id:pack.facility_id,contacts:[],packages:[pack]}}));
  await page.route(url=>url.pathname==='/api/notifications/delivery-setup',r=>r.fulfill({json:{email:false,sms:false}}));
  await page.route(url=>url.pathname==='/api/notifications/packages',r=>r.fulfill({json:pack}));
  let attempts=0;
  await page.route(url=>url.pathname==='/api/notifications/packages/1/review',async r=>{
    if(++attempts===1)return r.fulfill({status:409,json:{detail:'Draft changed; review again'}});
    const body=r.request().postDataJSON();
    expect(new URL(r.request().url()).searchParams.get('facility_id')).toBe(pack.facility_id);
    expect(body.facility_id).toBe(pack.facility_id);
    expect(body.approve_and_send).toBe(true);expect(body.groups).toHaveLength(4);
    expect(body.groups.every((g:any)=>g.decision_text==='Closed due to dangerous roads.')).toBe(true);
    expect(body.groups[3].recipient_ids).toEqual([]);
    await r.fulfill({json:{...pack,status:'dispatched',messages:[{status:'simulated_sent'}]}});
  });
  await page.getByRole('button',{name:'Decision log',exact:true}).click();
  await page.getByRole('button',{name:'Review decision & alerts'}).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  for(const name of names)await expect(page.getByLabel(`Instructions for ${name}`,{exact:true})).toBeVisible();
  await expect(page.locator('details').filter({has:page.locator('summary').filter({hasText:'Message preview'})})).toHaveAttribute('open','');
  await expect(page.locator('details').filter({has:page.locator('summary').filter({hasText:'Recipients ·'})})).not.toHaveAttribute('open','');
  await page.getByLabel('Shared decision',{exact:true}).fill('Closed due to dangerous roads.');
  await page.getByLabel('Select group Remote',{exact:true}).uncheck();
  await page.getByRole('button',{name:/3 · Approve and alert 3 people/}).click();
  await expect(page.getByRole('alert')).toContainText('Draft changed; review again');
  await page.getByRole('button',{name:/3 · Approve and alert 3 people/}).click();
  await expect(page.getByRole('status').filter({hasText:'Approved alerts sent in the simulator'})).toBeVisible();
  await expect(page.getByText('Delivered (simulated)',{exact:true})).toBeVisible();
  expect(app.errors).toEqual([]);
});
