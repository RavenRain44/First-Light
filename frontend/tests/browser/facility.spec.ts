import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import type { Facility, RuleResult, Snapshot } from "../../src/types";

const dist = fileURLToPath(new URL("../../dist/", import.meta.url));
const facilities: Facility[] = [
  { id: "IA-AMES-SC", city: "Ames", name: "Synthetic Ames facility", state: "IA", timezone: "America/Chicago", synthetic: true,
    lat: 42.03, lon: -93.63, asos_station: "AMW", hours: { open: "07:30", close: "16:30" }, corridors: [], accessibility_notes: [] },
  { id: "NC-WILMINGTON-SC", city: "Wilmington", name: "Synthetic Wilmington facility", state: "NC", timezone: "America/New_York", synthetic: true,
    lat: 34.2257, lon: -77.875, asos_station: "ILM", hours: { open: "07:30", close: "16:30" }, corridors: [], accessibility_notes: [] },
];
function snapshot(facility: Facility, asOf = "2026-10-11T10:00:00Z", mode: "live" | "replay" = "live"): Snapshot {
  return { facility, facility_id: facility.id, snapshot_id: `${facility.id}-${asOf}`, as_of: asOf, created_at: asOf,
    mode, event_id: null, thresholds_version: "test", thresholds_sha256: "test", model_id: "template", prompt_version: "test",
    content_sha256: "test", integrity_ok: true, roster: { assigned: 270, expected_in_building: facility.state === "NC" ? 321 : 270 },
    inputs: [], alerts: [], sources: [], signals: {}, rules: [], hazards: {},
    posture: { posture: "NORMAL", decision_day: "2026-10-11", opm_label: "Normal", opm_section: "test", contributing_hazards: [], reasons: [], guidance: [] },
    confidence: { level: "medium", score: .5, factors: [] }, changes: [], readiness: { level: "WHITE", cooper: "test", meaning: "test", reasons: [],
      decide_by: null, deadline_passed: false, recheck_minutes: 10, basis: "test" }, watch_next_6h: [], analogs: [], features: {},
    ai: { headline: "Test brief", rationale_paragraph: "Test rationale", what_would_change: [], watch_next_6h: [], alert_summaries: {}, analog_comparison: "None" },
  };
}
function coastalSnapshot(facility: Facility): Snapshot {
  const report = snapshot(facility);
  const rule: RuleResult = { rule_id: "tropical.hurricane_warning", hazard: "tropical", metric: "alert_present", observed_value: "Hurricane Warning",
    label: "Hurricane Warning", triggered: true, available: true, level: 3, score: 100, input_ids: ["nws.alert.hurricane"],
    window_start: report.as_of, window_end: "2026-10-13T10:00:00Z", time_of_peak: report.as_of, threshold: 1, operator: ">=", unit: "flag",
    source_url: "https://www.weather.gov/ilm/", margin_abs: 0, margin_pct: 0, posture_effect: "extreme", verified: true,
    basis: "policy", anchor: "NWS warning", time_window: "Next 48 h", detail: null };
  report.rules = [rule]; report.posture = { ...report.posture, posture: "CLOSED", contributing_hazards: ["tropical"] };
  report.readiness = { ...report.readiness!, level: "RED", reasons: ["Hurricane Warning in effect"] };
  report.hazards = { tropical: { hazard: "tropical", label: "Tropical / hurricane", level: 3, level_name: "extreme", score: 100,
    triggered_rule_ids: [rule.rule_id], controlling_rule_ids: [rule.rule_id], window_start: rule.window_start, window_end: rule.window_end,
    time_of_peak: report.as_of, posture: "CLOSED", posture_reason: "Local Hurricane Warning" } };
  report.alerts = [{ id: "nws.alert.hurricane", event: "Hurricane Warning", severity: "Severe", certainty: "Likely", urgency: "Expected",
    sent: "2026-10-11T09:00:00Z", onset: report.as_of, ends: rule.window_end, expires: rule.window_end, headline: "Hurricane Warning for Wilmington",
    description: "Damaging winds and heavy rainfall expected.", instruction: "Follow local emergency management instructions.", areaDesc: "Wilmington" }];
  report.inputs = ["wind_gust_mph", "rain_in"].map(metric => ({ id: `fcst.${metric}`, metric, kind: "series", role: "forecast",
    value: null, unit: metric === "rain_in" ? "in" : "mph", series: [0, 1, 2].map(h => ({ t: new Date(Date.parse(report.as_of) + h * 3600000).toISOString(),
      v: metric === "rain_in" ? 1.2 : 65 + h })), data: null, source: "NWS Wilmington", source_url: "https://www.weather.gov/ilm/",
    fetched_at: report.as_of, source_time: "2026-10-11T09:00:00Z", note: null }));
  return report;
}

async function setup(page: Page, options: { delayAmes?: boolean; coastal?: boolean } = {}) {
  let releaseAmes: (() => void) | undefined;
  let sawAmes = false;
  const calls: { path: string; facility: string | null; body?: any }[] = [];
  await page.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) {
      const path = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
      try { return await route.fulfill({ contentType: path.endsWith(".js") ? "application/javascript" : path.endsWith(".css") ? "text/css" : path.endsWith(".png") ? "image/png" : "text/html", body: await readFile(`${dist}${path}`) }); }
      catch { return await route.abort(); }
    }
    const id = url.searchParams.get("facility_id"), facility = facilities.find(f => f.id === id) ?? facilities[0];
    const body = request.method() === "POST" ? request.postDataJSON() : undefined;
    calls.push({ path: url.pathname, facility: id, body });
    try {
      if (url.pathname === "/api/facilities") return await route.fulfill({ json: facilities });
      if (url.pathname === "/api/health") return await route.fulfill({ json: { demo_mode: true, inference: { enabled: false }, model_provider: "none" } });
      if (url.pathname === "/api/snapshot/latest") {
        if (options.delayAmes && facility.state === "IA" && !sawAmes) { sawAmes = true; await new Promise<void>(resolve => { releaseAmes = resolve; }); }
        return await route.fulfill({ json: options.coastal && facility.state === "NC" ? coastalSnapshot(facility) : snapshot(facility) });
      }
      if (url.pathname === "/api/risk-tradeoffs") return await route.fulfill({ json: { errors: {} } });
      if (url.pathname === "/api/past-decisions") return await route.fulfill({ json: { decisions: [], reviewing: [] } });
      if (url.pathname === "/api/snapshots") return await route.fulfill({ json: [] });
      if (url.pathname === "/api/roads") return await route.fulfill({ json: { status: "unavailable", corridors: [] } });
      if (url.pathname === "/api/timeseries") return await route.fulfill({ json: options.coastal && facility.state === "NC" ? {
        rows: [0, 1, 2].map(h => ({ t: new Date(Date.parse("2026-10-11T10:00:00Z") + h * 3600000).toISOString(), fcst_wind_gust_mph: 65 + h,
          fcst_rain_in: 1.2, fcst_water_level_ft_WLON7: 6.2 + h * .1 })), timezone: facility.timezone,
        meta: { fcst_water_level_ft_WLON7: { source: "NOAA NWPS", unit: "ft", station_id: "WLON7", station_name: "Cape Fear River at Wilmington",
          source_time: "2026-10-11T09:00:00Z", fetched_at: "2026-10-11T10:00:00Z", input_ids: ["water.WLON7.forecast"], datum: "MLLW",
          provenance: { datum: "MLLW", flood_stage_ft: 5.5 }, source_url: "https://api.water.noaa.gov/nwps/v1/gauges/wlon7/stageflow" } }
      } : { rows: [], meta: {}, timezone: facility.timezone } });
      if (url.pathname === "/api/history/events") return await route.fulfill({ json: [] });
      if (url.pathname === "/api/backtesting") return await route.fulfill({ json: { jobs: [], supported_start: "1942-06-01", supported_end: "2026-10-10", latest_disruptive_days: [], decision_dataset: { unique_days: [] } } });
      if (url.pathname === "/api/replay/timeline") {
        const asOf = url.searchParams.get("as_of")!;
        return await route.fulfill({ json: { as_of: asOf, timezone: facility.timezone, selected_index: 1,
          timeline: [-1, 0, 1].map(h => ({ as_of: new Date(Date.parse(asOf) + h * 3600000).toISOString(), posture: "NORMAL", readiness: "YELLOW" })) } });
      }
      if (url.pathname === "/api/evaluate") return await route.fulfill({ json: snapshot(facility, body.as_of, body.mode) });
      return await route.fulfill({ status: 404, json: { detail: "Unexpected request" } });
    } catch { /* A facility switch can abort a deliberately delayed route. */ }
  });
  await page.goto("http://closure-call.test/");
  return { calls, release: () => releaseAmes?.(), sawAmes: () => sawAmes };
}

test("switching facilities discards delayed Ames responses and persists Wilmington", async ({ page }) => {
  const mock = await setup(page, { delayAmes: true });
  await expect.poll(mock.sawAmes).toBe(true);
  await page.getByRole("combobox", { name: "Facility", exact: true }).selectOption("NC-WILMINGTON-SC");
  await expect(page.getByText("321", { exact: true })).toBeVisible();
  mock.release();
  await expect(page.getByText("270", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Facility", exact: true })).toHaveValue("NC-WILMINGTON-SC");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("cc-facility"))).toBe("NC-WILMINGTON-SC");
  for (const call of mock.calls.filter(c => !["/api/health", "/api/facilities"].includes(c.path))) expect(call.facility).toBeTruthy();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Facility", exact: true })).toHaveValue("NC-WILMINGTON-SC");
  await expect(page.getByText("321", { exact: true })).toBeVisible();
});

test("Wilmington custom replay uses Eastern time and a switch stops playback and resets replay state", async ({ page }) => {
  const mock = await setup(page);
  await page.getByRole("combobox", { name: "Facility", exact: true }).selectOption("NC-WILMINGTON-SC");
  await page.getByRole("button", { name: "More tools", exact: true }).click();
  await page.getByRole("menuitem", { name: /Replay a past storm/ }).click();
  await expect(page.getByText("Time · America/New_York", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Curated storm timeline" }).click();
  await page.getByLabel("Any moment (Eastern time)").fill("2025-06-01T04:00");
  await page.getByRole("button", { name: "Evaluate", exact: true }).click();
  await expect(page.getByTestId("replay-context")).toContainText("Custom date replay");
  const evaluated = mock.calls.find(c => c.path === "/api/evaluate");
  expect(Date.parse(evaluated?.body.as_of)).toBe(Date.parse("2025-06-01T08:00:00Z"));
  expect(evaluated?.body.facility_id).toBe("NC-WILMINGTON-SC");
  await page.getByRole("button", { name: "▶ Play", exact: true }).click();
  await page.getByRole("combobox", { name: "Facility", exact: true }).selectOption("IA-AMES-SC");
  await expect(page.getByTestId("replay-context")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Today", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("270", { exact: true })).toBeVisible();
});

test("only actual decision edits prompt before changing facilities", async ({ page }) => {
  await setup(page);
  await expect(page.getByText("270", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Notify staff", exact: true }).click();
  const reason = page.getByRole("textbox", { name: /What is this manual decision based on/ });
  await expect(reason).toBeVisible();
  await reason.fill("A local bridge closure affects the staff commute.");
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("combobox", { name: "Facility", exact: true }).selectOption("NC-WILMINGTON-SC");
  await expect(page.getByRole("combobox", { name: "Facility", exact: true })).toHaveValue("IA-AMES-SC");
  await reason.fill("");
  let dialogs = 0;
  page.on("dialog", dialog => { dialogs += 1; void dialog.dismiss(); });
  await page.getByRole("combobox", { name: "Facility", exact: true }).selectOption("NC-WILMINGTON-SC");
  await expect(page.getByText("321", { exact: true })).toBeVisible();
  expect(dialogs).toBe(0);
});


test("Wilmington hurricane evidence shows wind, rain, and local water levels without zero winter charts", async ({ page }) => {
  await setup(page, { coastal: true });
  await page.getByRole("combobox", { name: "Facility", exact: true }).selectOption("NC-WILMINGTON-SC");
  const metrics = page.getByRole("region", { name: "Concerning weather data" });
  await expect(metrics.locator('figure[data-metric="wind"]')).toBeVisible();
  await expect(metrics.locator('figure[data-metric="rain"]')).toBeVisible();
  await expect(metrics.locator('figure[data-metric^="water-"]')).toBeVisible();
  await expect(metrics).toContainText("Cape Fear River at Wilmington");
  await expect(metrics).toContainText("MLLW");
  await expect(metrics.locator('figure[data-metric="snow"], figure[data-metric="ice"]')).toHaveCount(0);
  await expect(page.getByTestId("dashboard-metadata")).toContainText("EDT");
  await expect(page.getByTestId("cooper-dashboard")).toContainText("Hurricane Warning");
});
