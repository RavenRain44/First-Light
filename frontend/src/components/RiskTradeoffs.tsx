import { useEffect, useState } from "react";
import { useFacility } from "../facility";
import { api } from "../api";
import { bestSetting, pct, RATIOS, rateText, scenarioLoss, settingLabel, type ActionScenario, type ErrorAnalysis, type Exposure, type RiskTradeoffs as Data } from "../tradeoffs";

const EXPOSURE: Record<Exposure, { label: string; color: string }> = {
  lower: { label: "Lower", color: "var(--outcome-good)" },
  moderate: { label: "Moderate", color: "var(--outcome-mixed)" },
  elevated: { label: "Elevated", color: "var(--outcome-bad)" },
  unknown: { label: "Unknown", color: "var(--text-muted)" },
};
const COSTS_KEY = "cc-assumed-costs";

export function useRiskTradeoffs(snapshotId: string | undefined) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setData(null); setError("");
    api.riskTradeoffs(snapshotId).then((d) => active && setData(d)).catch((e) => active && setError(e.message));
    return () => { active = false; };
  }, [snapshotId]);
  return { data, error };
}

/** The reconstruction with the most graded days (the 30-year observation baseline when built). */
export const mainAnalysis = (d: Data | null): [string, ErrorAnalysis] | null =>
  Object.entries(d?.errors ?? {}).sort((a, b) => b[1].weather.n - a[1].weather.n)[0] ?? null;

export function riskSummary(d: Data | null) {
  const main = mainAnalysis(d);
  if (!main) return d ? "Not enough data yet: build the multi-year history under More tools" : "Loading…";
  const k = main[1].weather.confusion;
  return `${d!.range?.start?.slice(0, 4)}–${d!.range?.end?.slice(0, 4)}: ${k.false_alarm.toLocaleString()} false alarms in ${(k.false_alarm + k.true_negative).toLocaleString()} quiet days · ${k.missed_disruption.toLocaleString()} missed disruptions in ${(k.missed_disruption + k.true_positive).toLocaleString()} disruptive days`;
}

export function RiskTradeoffs({ data, error }: { data: Data | null; error: string }) {
  if (error) return <p role="alert" className="text-sm">{error}</p>;
  if (!data) return <p className="text-sm text-muted">Loading…</p>;
  const main = mainAnalysis(data);
  return (
    <div className="space-y-6 text-sm">
      {main ? <WeatherErrors kind={main[0]} a={main[1]} data={data} /> :
        <p>Not enough data yet. Build the multi-year history (More tools → Thresholds & backtest) to see how often the weather warnings were wrong.</p>}
      {data.experiment && <ChronologicalExperiment report={data.experiment} />}
      {data.actions && <ActionRisks a={data.actions} />}
    </div>
  );
}

function WeatherErrors({ kind, a, data }: { kind: string; a: ErrorAnalysis; data: Data }) {
  const facility = useFacility();
  const w = a.weather;
  const zeroFa = w.confusion.false_alarm === 0 && w.false_positive_rate.ci95;
  return (
    <section>
      <p className="mb-3">Missed hazardous conditions can expose staff to injury, unsafe commuting or stranding. Unnecessary restrictions can delay services and unfinished work. Income effects and task recoverability depend on employment arrangements; neither injury nor financial loss is measured here. Essential staff may still travel during closure.</p>
      <h3 className="font-semibold">How often the weather warnings were wrong</h3>
      <p className="mt-1 text-xs text-muted">
        {w.n.toLocaleString()} weekdays, {data.range?.start} to {data.range?.end}, checked at {data.evaluation_time} against what the {facility.asos_station ?? "local"} airport
        station recorded that day ({kind}). {a.label}
      </p>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-edge p-3">
          <dt className="font-semibold">False alarms <span className="font-normal text-muted">(warned, but the day stayed calm)</span></dt>
          <dd className="mt-1">{rateText(w.false_positive_rate)}</dd>
        </div>
        <div className="rounded-lg border border-edge p-3">
          <dt className="font-semibold">Missed disruptions <span className="font-normal text-muted">(no warning, but the weather was disruptive)</span></dt>
          <dd className="mt-1">{rateText(w.false_negative_rate)}</dd>
        </div>
      </dl>
      <p className="mt-2 text-xs text-muted">
        Of the warnings that were issued, {rateText(w.false_alarm_share_of_warnings)} were false alarms. This uses a different denominator from the false-alarm rate above.
      </p>
      {zeroFa && <p className="mt-2">{a.zero_errors_note} The data are consistent with a false-alarm rate as high as {pct(w.false_positive_rate.ci95![1], 2)}.</p>}
      <p className="mt-2 text-xs text-muted">
        A missed disruption is missed <em>weather</em>, not proof that staying open was unsafe. A false alarm is an unnecessary weather warning under this benchmark, not proof that closing would have been wrong.
      </p>
      <Tradeoff a={a} />
    </section>
  );
}

function Tradeoff({ a }: { a: ErrorAnalysis }) {
  const facility = useFacility();
  const costsKey = `${COSTS_KEY}:${facility.id}`;
  const [costs, setCosts] = useState<{ fa: number; miss: number }>(() => {
    try { return JSON.parse(localStorage.getItem(costsKey) || "") ?? { fa: 1, miss: 5 }; } catch { return { fa: 1, miss: 5 }; }
  });
  const update = (k: "fa" | "miss", v: string) => {
    const n = Math.max(0, Number(v) || 0);
    const next = { ...costs, [k]: n };
    setCosts(next); localStorage.setItem(costsKey, JSON.stringify(next));
  };
  const best = bestSetting(a.sweep, costs.fa, costs.miss);
  const current = a.weather.confusion;
  return (
    <>
      {a.tradeoff && <p className="mt-3"><strong>Trade-off:</strong> {a.tradeoff}</p>}
      <details className="mt-3">
        <summary className="cursor-pointer font-semibold">What if the thresholds were different?</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-muted"><tr><th className="py-1 pr-3">Threshold setting</th><th className="pr-3">Caught</th><th className="pr-3">Missed</th><th className="pr-3">False alarms</th><th className="pr-3">Missed rate</th><th>False-alarm rate</th></tr></thead>
            <tbody>
              {[...a.sweep].sort((x, y) => x.offset_pct - y.offset_pct).map((p) => (
                <tr key={p.offset_pct} className={p.current_thresholds ? "font-semibold" : ""}>
                  <td className="py-1 pr-3">{settingLabel(p.offset_pct)}</td>
                  <td className="pr-3">{p.confusion.true_positive}</td><td className="pr-3">{p.confusion.missed_disruption}</td>
                  <td className="pr-3">{p.confusion.false_alarm}</td><td className="pr-3">{pct(p.false_negative_rate.rate)}</td><td>{pct(p.false_positive_rate.rate)}</td>
                </tr>
              ))}
              <tr className="border-t border-edge"><td className="py-1 pr-3">Current rules, including timing (what was actually suggested)</td>
                <td className="pr-3">{current.true_positive}</td><td className="pr-3">{current.missed_disruption}</td><td className="pr-3">{current.false_alarm}</td>
                <td className="pr-3">{pct(a.weather.false_negative_rate.rate)}</td><td>{pct(a.weather.false_positive_rate.rate)}</td></tr>
            </tbody>
          </table>
          <p className="mt-1 text-xs text-muted">Each setting classifies stored signed rule margins at a different cutoff; it does not rerun the full operating engine or change scientific hazard definitions. Rows are descriptive results on past days, not a tuned or validated threshold.</p>
        </div>
      </details>
      <details className="mt-3">
        <summary className="cursor-pointer font-semibold">Weigh false alarms against missed disruptions</summary>
        <p className="mt-2 rounded-md border border-edge px-2 py-1 text-xs"><strong>Assumed costs: illustrative only, not measured.</strong> Enter how much worse a missed disruption is than a false alarm for your site. The numbers have no units.</p>
        <div className="mt-2 flex flex-wrap gap-4">
          <label>Cost of one false alarm <input type="number" min={0} step="any" value={costs.fa} onChange={(e) => update("fa", e.target.value)} className="ml-1 w-20 rounded border border-edge bg-surface p-1" /></label>
          <label>Cost of one missed disruption <input type="number" min={0} step="any" value={costs.miss} onChange={(e) => update("miss", e.target.value)} className="ml-1 w-20 rounded border border-edge bg-surface p-1" /></label>
        </div>
        <p className="mt-2">
          Expected scenario loss with today's thresholds: <strong>{scenarioLoss(a.sweep.find((p) => p.current_thresholds)!.confusion, costs.fa, costs.miss).toLocaleString()}</strong>
          {" "}(false alarms × {costs.fa} + misses × {costs.miss}). Lowest: <strong>{best ? `${best.loss.toLocaleString()} (${settingLabel(best.offset_pct).toLowerCase()})` : "—"}</strong>.
        </p>
        <h4 className="mt-3 font-semibold">Sensitivity: the best setting under different assumed cost ratios</h4>
        <table className="mt-1 w-full text-left text-xs">
          <thead className="text-muted"><tr><th className="py-1 pr-3">A miss costs</th><th className="pr-3">Lowest-loss setting</th><th className="pr-3">Its loss</th><th>Current rules' loss</th></tr></thead>
          <tbody>{a.sensitivity.rows.map((r) => (
            <tr key={r.ratio}><td className="py-1 pr-3">{r.ratio}× a false alarm</td><td className="pr-3">{settingLabel(r.best_offset_pct)}</td>
              <td className="pr-3">{r.best_loss.toLocaleString()}</td><td>{r.current_rules_loss?.toLocaleString() ?? "—"}</td></tr>
          ))}</tbody>
        </table>
        <p className="mt-1 text-xs text-muted">{a.sensitivity.label} Ratios shown: {RATIOS.join(", ")} to 1. These are weather-classification costs only, separate from the cost of any operating action.</p>
      </details>
    </>
  );
}

function ActionRisks({ a }: { a: import("../tradeoffs").ActionRisk }) {
  return (
    <section>
      <h3 className="font-semibold">Risk of each option for {a.decision_day} <span className="ml-1 rounded border border-edge px-1.5 py-0.5 text-xs font-normal">experimental</span></h3>
      <p className="mt-1 rounded-md border border-dashed border-edge px-2 py-1 text-xs">
        Experimental assessment. It is separate from your recorded decision and does not change the suggestion or notify anyone. The decision stays yours.
      </p>
      {a.hazards.length > 0 && <p className="mt-2 text-xs">{a.hazards.map((h) => `${h.hazard} (${h.level_name})${h.timing_known ? `: ${h.overlaps.map((o) => o.replace("_", " ")).join(", ") || "outside work and commute hours"}` : ": timing unknown"}`).join(" · ")}</p>}
      <ul className="mt-3 grid gap-3 sm:grid-cols-2">{a.scenarios.map((s) => <ActionCard key={s.action} s={s} />)}</ul>
      <details className="mt-3">
        <summary className="cursor-pointer font-semibold">Missing information ({a.missing_inputs.length})</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">{a.missing_inputs.map((m) => <li key={m}>{m}</li>)}</ul>
      </details>
      <p className="mt-2 text-xs text-muted">{a.quantitative_note} Staff: {a.staff.expected_in_building} expected on site, {a.staff.essential} essential, {a.staff.telework_eligible} can telework, {a.staff.no_remote_option} have no remote option.</p>
    </section>
  );
}

function ActionCard({ s }: { s: ActionScenario }) {
  const e = EXPOSURE[s.weather_exposure];
  return (
    <li className="rounded-lg border border-edge p-3">
      <div className="flex items-center justify-between gap-2">
        <strong>{s.label}</strong>
        <span className="inline-flex items-center gap-1.5 rounded-md border border-edge px-2 py-0.5 text-xs font-semibold" title="Weather exposure for people travelling">
          <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: e.color }} />Weather exposure: {e.label}
        </span>
      </div>
      <p className="mt-1 text-xs text-muted">{s.who_travels} ({s.people_travelling} people).</p>
      {s.risks_if_conditions_worsen.length > 0 && <><p className="mt-2 text-xs font-semibold">If conditions are bad</p>
        <ul className="list-disc pl-5 text-xs">{s.risks_if_conditions_worsen.map((r) => <li key={r}>{r}</li>)}</ul></>}
      <p className="mt-2 text-xs font-semibold">Cost of choosing this</p>
      <ul className="list-disc pl-5 text-xs">{s.costs_of_acting.map((r) => <li key={r}>{r}</li>)}</ul>
    </li>
  );
}

function ChronologicalExperiment({report:r}:{report:any}) {
  const [ratio,setRatio]=useState('10');
  const s=r.scenarios.find((v:any)=>String(v.ratio)===ratio)??r.scenarios[0];
  return <section className="border-t border-edge pt-4"><h3 className="font-semibold">Chronological safety / operational-loss comparison</h3><p className="mt-2">Fixed cohort: {r.cohort_n.toLocaleString()} days at the facility’s 04:00 local evaluation. Training {r.splits.training.baseline.n.toLocaleString()}, validation {r.splits.validation.baseline.n.toLocaleString()}, final test {r.splits.test.baseline.n.toLocaleString()}; {r.boundary_excluded_days.length} boundary days purged.</p><p className="text-xs text-muted">{r.method} Threshold selected on validation only; production recommendations stay unchanged. Test disruption sample: {r.test_positive_count} days; {r.test_disruption_sample_status}.</p><label className="mt-3 block">Assumed missed-disruption cost relative to a false alarm <select className="ml-2 rounded border border-edge bg-surface p-1" value={ratio} onChange={e=>setRatio(e.target.value)}>{r.scenarios.map((v:any)=><option key={v.ratio} value={String(v.ratio)}>{v.ratio}:1</option>)}</select></label><p className="mt-2">Selected rule-margin offset: {s.selected_offset_pct}%. Final-test recall {pct(s.test.recall)} versus {pct(s.baseline_test.recall)} with existing rules; balanced accuracy {pct(s.test.balanced_accuracy)} versus {pct(s.baseline_test.balanced_accuracy)}.</p><p>Additional disruptions caught: {s.additional_disruptions_caught}. Additional false alarms: {s.additional_false_alarms}. Misses: {s.test.confusion.missed_disruption} versus {s.baseline_test.confusion.missed_disruption}. Assumed test loss: {s.test_loss} versus {s.baseline_test_loss}.</p><details className="mt-2"><summary>Method, provenance & limitations</summary><p>Manifest {r.cohort_version} · SHA {r.cohort_sha}. Missing values remain unavailable, not zero. No model fitting, injury probabilities or financial losses.</p>{r.limitations.map((x:string)=><p className="mt-1 text-xs" key={x}>{x}</p>)}<p>Future performance needs prospective out-of-sample evaluation. Current test dates were inspected in earlier baseline analyses.</p></details></section>;
}
