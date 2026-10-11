// Errors & risk trade-offs: types and the assumed-cost math (same formula as backend engine/error_analysis.py).

export type Rate = { count: number; n: number; denominator: string; rate: number | null; ci95: [number, number] | null; status: string; reason: string | null };
export type Confusion = { true_positive: number; true_negative: number; false_alarm: number; missed_disruption: number };
export type Rates = { n: number; confusion: Confusion; false_positive_rate: Rate; false_negative_rate: Rate; false_alarm_share_of_warnings: Rate };
export type SweepPoint = Rates & { offset_pct: number; current_thresholds: boolean };
export type ErrorAnalysis = {
  weather: Rates; sweep: SweepPoint[]; tradeoff: string | null; label: string; zero_errors_note: string;
  sensitivity: { assumed: true; label: string; rows: { ratio: number; best_offset_pct: number; best_loss: number; current_rules_loss: number | null }[] };
};
export type Exposure = "lower" | "moderate" | "elevated" | "unknown";
export type ActionScenario = { action: string; label: string; weather_exposure: Exposure; people_travelling: number; who_travels: string; costs_of_acting: string[]; risks_if_conditions_worsen: string[] };
export type ActionRisk = {
  experimental: true; quantitative: false; label: string; quantitative_note: string; decision_day: string;
  hazards: { hazard: string; level: number; level_name: string; overlaps: string[]; timing_known: boolean }[];
  staff: { expected_in_building: number; essential: number; telework_eligible: number; no_remote_option: number };
  missing_inputs: string[]; scenarios: ActionScenario[];
};
export type RiskTradeoffs = { errors: Record<string, ErrorAnalysis>; range: { start: string | null; end: string | null } | null; evaluation_time: string; actions: ActionRisk | null };

export const RATIOS = [1, 2, 5, 10, 20, 50];

/** Expected scenario loss: false alarms x assumed false-alarm cost + misses x assumed missed-disruption cost. */
export const scenarioLoss = (c: Confusion, falseAlarmCost: number, missCost: number) =>
  c.false_alarm * falseAlarmCost + c.missed_disruption * missCost;

/** Lowest-loss threshold setting; ties go to the setting closest to today's thresholds. */
export function bestSetting(points: SweepPoint[], falseAlarmCost: number, missCost: number) {
  let best: { offset_pct: number; loss: number } | null = null;
  for (const p of points) {
    const loss = scenarioLoss(p.confusion, falseAlarmCost, missCost);
    if (!best || loss < best.loss || (loss === best.loss && Math.abs(p.offset_pct) < Math.abs(best.offset_pct))) best = { offset_pct: p.offset_pct, loss };
  }
  return best;
}

export const settingLabel = (offset: number) =>
  offset === 0 ? "Thresholds as set today" : offset < 0 ? `${-offset}% easier to trigger` : `${offset}% harder to trigger`;

export const pct = (v: number | null | undefined, digits = 1) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);

/** "160 of 349 disruptive days (45.8%, 95% range 40.7–51.1%)", or the not-enough-data reason. */
export function rateText(r: Rate) {
  if (r.rate == null) return r.reason ?? "Not enough data";
  const range = r.ci95 ? `, 95% range ${pct(r.ci95[0])}–${pct(r.ci95[1])}` : "";
  return `${r.count.toLocaleString()} of ${r.n.toLocaleString()} ${r.denominator} (${pct(r.rate)}${range})${r.status === "not enough data" ? ". Not enough data to rely on" : ""}`;
}
