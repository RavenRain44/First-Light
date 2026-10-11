import { evidenceState, evidenceWarning } from "./evidence.ts";
import { supportingRules } from "./dashboard.ts";
import type { NormalizedInput, ReadinessLevel, Snapshot } from "./types";

const HOUR = 3600000;
export interface ForecastValue {
  input?: NormalizedInput;
  min: number | null;
  max: number | null;
  hours: number;
}

/** The current forecast hour plus the next 23 hours; missing values never become zero. */
export function forecastOverview(snap: Snapshot) {
  const start = Math.floor(new Date(snap.as_of).getTime() / HOUR) * HOUR;
  const end = start + 24 * HOUR;
  const metric = (id: string): ForecastValue => {
    const input = snap.inputs.find((i) => i.id === `fcst.${id}` && i.kind === "series");
    const points = (input?.series ?? []).filter((p) => new Date(p.t).getTime() >= start && new Date(p.t).getTime() < end
      && typeof p.v === "number" && Number.isFinite(p.v)
      && (!id.endsWith("_pct") || (p.v >= 0 && p.v <= 100)) && (!id.includes("wind") || p.v >= 0));
    const values = points.map((p) => p.v as number);
    return { input, min: values.length ? Math.min(...values) : null, max: values.length ? Math.max(...values) : null,
      hours: new Set(points.map((p) => Math.floor(new Date(p.t).getTime() / HOUR))).size };
  };
  return { start: new Date(start).toISOString(), end: new Date(end).toISOString(),
    temperature: metric("temp_f"), feelsLike: metric("apparent_temp_f"), wind: metric("wind_speed_mph"),
    gust: metric("wind_gust_mph"), precipitation: metric("pop_pct"), sky: metric("sky_cover_pct") };
}

export function weatherHeading(snap: Snapshot): string {
  const f = forecastOverview(snap);
  const cold = (f.feelsLike.min ?? f.temperature.min) !== null && (f.feelsLike.min ?? f.temperature.min)! <= 32;
  const windy = (f.wind.max ?? 0) >= 20 || (f.gust.max ?? 0) >= 30;
  if (cold && windy) return "Cold, windy weather expected";
  if (cold) return "Cold weather expected";
  if (windy) return "Windy weather expected";
  // A clear/cloudy headline needs coverage of the whole stated forecast window.
  if ((f.precipitation.max ?? 0) >= 50) return "A chance of precipitation";
  if (f.sky.hours === 24 && f.sky.max !== null && f.sky.max <= 5) return "Clear skies forecast";
  if (f.sky.hours === 24 && f.sky.min !== null && f.sky.min >= 75) return "Cloudy weather expected";
  if (f.sky.max !== null && f.sky.max > 25) return "Clouds in the forecast";
  if ([f.temperature, f.wind, f.gust, f.precipitation].every((m) => m.max === null)) return "Forecast data unavailable";
  return "Your local forecast";
}

export function readinessLevel(snap: Snapshot): ReadinessLevel | null {
  const level = snap.readiness?.level;
  return level && ["WHITE", "YELLOW", "ORANGE", "RED"].includes(level) ? level : null;
}

/** The event comes from the rules that justify readiness, rather than any unrelated alert. */
export function readinessEvent(snap: Snapshot): string | null {
  const rules = supportingRules(snap);
  const reason = snap.readiness?.reasons.join(" ").toLowerCase() ?? "";
  const alerts = rules.filter((r) => r.metric === "alert_present" && typeof r.observed_value === "string");
  const matched = alerts.find((r) => String(r.observed_value).split(", ").some((event) => reason.includes(event.toLowerCase())));
  if (matched) return String(matched.observed_value);
  const numeric = rules.find((r) => reason.includes(r.label.toLowerCase()));
  if (numeric) return numeric.label;
  if (snap.posture.guidance.length && alerts.length) return String(alerts[0].observed_value);
  // A deadline can be urgent even without an active weather event.
  if (reason.includes("announced by") || reason.includes("deadline")) return null;
  if (alerts.length) return String(alerts[0].observed_value);
  return rules[0]?.label ?? null;
}

export function cooperPresentation(snap: Snapshot) {
  const level = readinessLevel(snap);
  const event = readinessEvent(snap);
  const urgent = level === "ORANGE" || level === "RED";
  // A quiet forecast heading would read as an all-clear, so insufficient evidence names itself instead.
  const quiet = level !== "RED" && level !== "ORANGE";
  const reasons = snap.readiness?.reasons ?? [];
  const deadlineOnly = level === "RED" && !snap.posture.guidance.length && reasons.length > 0
    && reasons.every((r) => /announced by|deadline/i.test(r));
  const posture = snap.posture.posture.toLowerCase().replaceAll("_", " ");
  const title = deadlineOnly ? `${snap.readiness?.deadline_passed ? "Decision overdue" : "Decision due soon"}: ${posture}`
    : level === "RED" ? `Send communication immediately${event ? `: ${event}` : ""}`
    : level === "ORANGE" ? "Start taking precautions"
    : quiet && evidenceWarning(evidenceState(snap)) && snap.sufficiency ? "Insufficient current data"
    : quiet && evidenceState(snap).provisional ? "Provisional forecast · verify before deciding"
    : level ? weatherHeading(snap) : "Readiness not recorded";
  const action = level === "RED" ? "Draft urgent decision" : level === "ORANGE" ? "Draft decision"
    : level === "YELLOW" ? "Review decision" : level === null ? "Review decision" : null;
  const contributing = Object.values(snap.hazards).filter((h) => snap.posture.contributing_hazards.includes(h.hazard));
  const severity = contributing.length ? Math.max(...contributing.map((h) => h.level)) : null;
  const urgencyExplanation = deadlineOnly
    ? `Red reflects the announcement deadline${severity === null ? "." : `; the contributing weather hazard is rated ${["none", "minor", "significant", "extreme"][severity] ?? "unknown"}.`} Review the evidence before choosing an operating status.`
    : null;
  const watch = level === "YELLOW" ? watchMessage(snap, event, title) : null;
  return { level, title, event, urgent, action, watch, deadlineOnly, urgencyExplanation, reasons: reasons.slice(0, 3) };
}

function watchMessage(snap: Snapshot, event: string | null, title: string): string {
  if (evidenceState(snap).provisional) return "A backup forecast is in use. Verify local warnings and the missing measurements before choosing an operating status.";
  const reasons = snap.readiness?.reasons.join(" ") ?? "";
  if (/insufficient|incomplete|stale/i.test(reasons)) return "Verify the latest local warnings and forecast before deciding; some evidence is incomplete or stale.";
  if (snap.confidence.level === "low") return "Confidence is low. Verify the latest local warnings and forecast before deciding.";
  // The hazard responsible for readiness takes priority over background weather.
  const concern = event ?? reasons;
  if (/tornado|severe thunderstorm|convective/i.test(concern)) return "Watch for new tornado or severe thunderstorm warnings; be ready to shelter before staff travel or leave the building.";
  if (/ice|snow|winter|freezing/i.test(concern)) return "Watch for ice or snow affecting commute routes; recheck road reports before staff travel.";
  const cold = "Watch for falling feels-like temperatures before staff travel or work outdoors.";
  const wind = "Watch for strengthening gusts and changing travel conditions before the commute.";
  if (/cold|apparent|chill/i.test(concern)) return cold;
  if (/wind|gust/i.test(concern)) return wind;
  if (event) return `Watch for changes to ${event}; recheck its timing before the commute.`;
  if (/cold/i.test(title)) return cold;
  if (/wind/i.test(title)) return wind;
  if (/cloud/i.test(title)) return "Watch for changes in cloud cover and precipitation forecasts before the commute.";
  if (/precipitation/i.test(title)) return "Watch for changing precipitation forecasts; check road conditions before staff travel.";
  return "Watch for changes in the forecast and local alerts before the next commute.";
}
