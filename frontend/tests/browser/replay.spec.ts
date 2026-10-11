import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import type { ReplayEvent, ReplayPoint, Snapshot } from "../../src/types";

const dist = fileURLToPath(new URL("../../dist/", import.meta.url));
const history = fileURLToPath(new URL("../../../backend/fixtures/history/", import.meta.url));
const events: ReplayEvent[] = await Promise.all(["ice-2023-02-22", "derecho-2020-08-10"].map(async (id) => {
  const data = JSON.parse(await readFile(`${history}${id}.json`, "utf8"));
  return { ...data.event, verification: data.verification, outcome: data.outcome, backtest: data.backtest, timeline: data.timeline };
}));

function snapshot(asOf: string, point: ReplayPoint, eventId: string | null): Snapshot {
  return {
    snapshot_id: `test-${eventId ?? "custom"}-${asOf}`, as_of: asOf, created_at: asOf,
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

async function mockApp(page: Page, options: { pendingAi?: boolean; failFirstEvent?: boolean; holdReplay?: boolean } = {}) {
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
      if (url.pathname === "/api/health") return await route.fulfill({ json: { demo_mode: true, inference: { enabled: false }, model_provider: "none" } });
      if (url.pathname === "/api/snapshot/latest") return await route.fulfill({ json: { ...snapshot("2026-10-11T10:00:00Z", { as_of: "2026-10-11T10:00:00Z", posture: "NORMAL", readiness: "WHITE" }, null), mode: "live" } });
      if (url.pathname === "/api/risk-tradeoffs") return await route.fulfill({ json: { errors: {} } });
      if (url.pathname === "/api/past-decisions") return await route.fulfill({ json: { decisions: [], reviewing: [] } });
      if (url.pathname === "/api/roads") return await route.fulfill({ json: { status: "not_applicable", corridors: [] } });
      if (url.pathname === "/api/timeseries") return await route.fulfill({ json: { rows: [], meta: {}, timezone: "America/Chicago" } });
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
        const point = replayEvent.timeline.find((item) => Date.parse(item.as_of) === Date.parse(asOf))!;
        const report = snapshot(asOf, point, replayEvent.id);
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
  await page.getByRole("button", { name: "Curated storm timeline", exact: true }).click();
  return { loads, errors, unexpected, releaseReplay };
}

const loading = (page: Page) => page.getByRole("status").filter({ hasText: /^Loading .*The report and timeline/ });

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
