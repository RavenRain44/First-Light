import { useEffect, useState } from "react";
import { api } from "../api";
import { Card } from "../util";

const field = "min-h-[44px] min-w-0 w-full rounded-lg border border-edge bg-surface px-3 py-2";
const pct = (v: number | null | undefined) => v == null ? "Not enough data" : `${(v * 100).toFixed(1)}%`;
const interval = (v: number[] | null) => v ? v.map(pct).join("–") : "Not enough data";

function Metrics({ title, data }: { title: string; data: any }) {
  return <section className="rounded-lg border border-edge p-3" aria-label={title}>
    <strong>{title} · {data.n} eligible days</strong><p className="text-muted">{data.status}</p>
    <dl className="my-2 grid grid-cols-2 gap-2">
      {["accuracy","balanced_accuracy","precision","recall","specificity"].map(k => <div key={k}><dt>{k.replaceAll("_"," ")}</dt><dd className="font-semibold">{pct(data[k])}</dd></div>)}
      <div><dt>Assumed weighted loss</dt><dd>{data.weighted_loss}</dd></div>
    </dl>
    <p>TP {data.confusion.true_positive} · TN {data.confusion.true_negative} · FP {data.confusion.false_alarm} · FN {data.confusion.missed_disruption}</p>
    <p>Type I (false alarm): {pct(data.false_positive_rate.rate)} · {data.false_positive_rate.count}/{data.false_positive_rate.n} quiet days</p>
    <p>Type II (miss): {pct(data.false_negative_rate.rate)} · {data.false_negative_rate.count}/{data.false_negative_rate.n} disruptive days</p>
    <p>Accuracy interval: {interval(data.accuracy_95pct_wilson)} (95% Wilson)</p>
    <p>Type I interval: {interval(data.false_positive_rate.ci95)} · {data.false_positive_rate.status}</p>
    <p>Type II interval: {interval(data.false_negative_rate.ci95)} · {data.false_negative_rate.status}</p>
    <p>False alarms / warnings issued: {pct(data.false_alarm_share_of_warnings.rate)} · {data.false_alarm_share_of_warnings.count}/{data.false_alarm_share_of_warnings.n}</p>
  </section>;
}

export function DecisionFeedback() {
  const [stats,setStats] = useState<any>(null);
  const [catalog,setCatalog] = useState<any>(null);
  const [analysis,setAnalysis] = useState<any>(null);
  const [policies,setPolicies] = useState<any>(null);
  const [actor,setActor] = useState("");
  const [token,setToken] = useState("");
  const [fp,setFp] = useState(1);
  const [fn,setFn] = useState(5);
  const [path,setPath] = useState("");
  const [value,setValue] = useState("");
  const [rationale,setRationale] = useState("");
  const [cohort,setCohort] = useState("forecast");
  const [minRecall,setMinRecall] = useState("");
  const [maxFp,setMaxFp] = useState("");
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [message,setMessage] = useState("");
  const validCosts = Number.isFinite(fp) && fp > 0 && fp <= 1000 && Number.isFinite(fn) && fn > 0 && fn <= 1000;
  const load = async () => {
    const [s,c,a,p] = await Promise.all([api.feedback(fp,fn),api.feedbackCatalog(),api.feedbackAnalysis(),api.policies()]);
    setStats(s); setCatalog(c); setAnalysis(a); setPolicies(p);
  };
  useEffect(() => { load().catch(e => setError(e.message)); }, []);
  const pending = policies?.proposals.some((p: any) => p.status === "evaluating");
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => api.policies().then(setPolicies).catch(e => setError(e.message)),2000);
    return () => clearInterval(timer);
  }, [pending]);
  const run = async (action: () => Promise<any>, success: string) => {
    setBusy(true); setError(""); setMessage("");
    try { await action(); await load(); setMessage(success); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const param = policies?.parameters.find((p: any) => p.path === path);
  return <Card title="Decision feedback & error analysis">
    <div className="space-y-4 break-words text-sm">
      <p>Compare the manager's call with the original recommendation using independent completed-day weather evidence. Manager agreement and goal achievement remain separate.</p>
      {error && <p role="alert" className="text-[var(--danger)]">{error}</p>}
      {message && <p role="status">{message}</p>}
      <button className="btn" disabled={busy || !validCosts} onClick={() => run(load,"Statistics refreshed")}>Refresh statistics</button>
      {stats && <>
        <p><strong>{stats.label}</strong> · updated {new Date(stats.updated_at).toLocaleString()} · {stats.range.start ?? "No eligible dates"}{stats.range.end && ` to ${stats.range.end}`}</p>
        <p>First decision per facility/local day · {stats.eligible_count} eligible · {stats.excluded_count} excluded · cohort {stats.cohort_sha.slice(0,12)}</p>
        <div className="grid gap-3 lg:grid-cols-2"><Metrics title="Manager decisions" data={stats.manager} /><Metrics title="Original recommendations" data={stats.recommendation} /></div>
        {stats.historical_benchmarks?.frozen_baseline?.metrics && <details><summary className="cursor-pointer font-medium">Historical benchmarks (separate datasets)</summary>
          <p>{stats.historical_benchmarks.frozen_baseline.status}</p><div className="mt-2 grid gap-3 lg:grid-cols-2"><Metrics title="Frozen observation baseline" data={stats.historical_benchmarks.frozen_baseline.metrics} /><Metrics title="Retained forecast benchmark" data={stats.historical_benchmarks.forecast_dataset.metrics} /></div>
          <p>{stats.historical_benchmarks.limitation}</p><p>These are preserved recorded predictions. A new candidate must be rerun against the same inputs to measure improvement.</p>
        </details>}
        <p>Agreement: {pct(stats.agreement.rate)} ({stats.agreement.count}/{stats.agreement.n}) · verified operating-action accuracy: {stats.confirmed_operating_decisions.status}.</p>
        <p>Goal achievement (manager opinions): {Object.entries(stats.objective_achievement_opinions ?? {}).map(([k,v]) => `${k.replaceAll("_"," ")}: ${v}`).join("; ") || "No reviews yet"}.</p>
        <p className="rounded border border-edge p-3">Type II misses may expose workers to hazardous travel; Type I false alarms may cause task delays and lost income. This dataset measures neither injury nor financial losses. Zero false alarms is not the objective.</p>
        <details><summary className="cursor-pointer">Definitions, exclusions and breakdowns</summary><div className="space-y-2 pt-2">
          {Object.entries(stats.manager.definitions).map(([k,v]) => <p key={k}>{k.replaceAll("_"," ")}: {String(v)}</p>)}
          {Object.entries(stats.excluded).map(([k,v]) => <p key={k}>Excluded: {k} · {String(v)}</p>)}
          <p>Rule versions: {Object.entries(stats.rule_versions).map(([k,v]) => `${k}: ${v}`).join("; ") || "None eligible"}</p>
          {Object.entries(stats.years).map(([k,v]: [string,any]) => <p key={k}>{k}: {v.manager.n} days · manager recall {pct(v.manager.recall)} · recommendation recall {pct(v.recommendation.recall)}</p>)}
          {Object.entries(stats.hazards).map(([k,v]: [string,any]) => <p key={k}>{k}: {v.manager.n} days · manager recall {pct(v.manager.recall)} · recommendation recall {pct(v.recommendation.recall)}</p>)}
          {stats.limitations.map((s: string) => <p key={s}>{s}</p>)}
          <p>The frozen 7,470-day observation baseline, retained forecast cohort and hourly validation stay separate. Proxy closures are not USDA operating truth.</p>
        </div></details>
      </>}
      {catalog && <p>Private operational dataset: {catalog.dataset.id} · cloud {catalog.cloud.enabled ? catalog.cloud.last_error ? "retrying after sync error" : `enabled; last sync ${catalog.cloud.last_sync ?? "pending"}` : "not configured; retained locally"}. These reviews are not published to GitHub.</p>}
      <details><summary className="cursor-pointer font-semibold">Akamai explanation & policy proposals</summary><div className="space-y-4 pt-3">
        <label className="flex flex-col gap-1">Manager name / title<input className={field} value={actor} onChange={e => setActor(e.target.value)} maxLength={120} /></label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1">Assumed false-alarm cost<input className={field} type="number" min="0.01" max="1000" step="0.1" value={fp} onChange={e => setFp(Number(e.target.value))} /></label>
          <label className="flex flex-col gap-1">Assumed missed-disruption cost<input className={field} type="number" min="0.01" max="1000" step="0.1" value={fn} onChange={e => setFn(Number(e.target.value))} /></label>
        </div>
        <p className="text-muted">Hypothetical unitless weights. Weighted loss = false alarms × first weight + misses × second weight. Apply with Refresh statistics.</p>
        <button className="btn" disabled={busy || !validCosts || actor.trim().length < 2} onClick={() => run(() => api.analyzeFeedback({actor,false_alarm_cost:fp,missed_disruption_cost:fn}),"Analysis available; no policy has been activated")}>{busy ? "Working…" : "Ask Akamai to explain errors"}</button>
        {analysis && <div className="rounded border border-edge p-3"><strong>{analysis.source === "akamai" ? "Akamai interpretation" : "Template explanation"} · {analysis.status}</strong><p>{analysis.explanation}</p><p className="text-muted">Calculated statistics remain authoritative. {analysis.metric_id !== stats?.id && "This analysis refers to an earlier statistics version."}</p>
          {analysis.proposals?.map((s: any, i: number) => <div key={i} className="mt-3"><p>Hypothesis: {s.path} → {s.value}. {s.rationale}</p><button className="btn" disabled={busy} onClick={() => {setPath(s.path); setValue(String(s.value)); setRationale(s.rationale);}}>Use suggestion in proposal</button></div>)}
        </div>}
        {policies && <>
          <p>Effective policy: {policies.current_version} · {policies.current_sha.slice(0,12)}. Analyze → propose → backtest → approve → activate. Official definitions cannot be edited.</p>
          <label className="flex flex-col gap-1">Policy parameter<select className={field} value={path} onChange={e => {setPath(e.target.value);setValue("");}}><option value="">Choose a bounded parameter</option>{policies.parameters.map((p: any) => <option key={p.path} value={p.path}>{p.category}: {p.path} (current {p.current})</option>)}</select></label>
          {param && <label className="flex flex-col gap-1">Candidate value ({param.min}–{param.max} {param.unit})<input className={field} type="number" min={param.min} max={param.max} step="any" value={value} onChange={e => setValue(e.target.value)} /></label>}
          <label className="flex flex-col gap-1">Why test this change?<textarea className={field} value={rationale} onChange={e => setRationale(e.target.value)} maxLength={1000} /></label>
          <label className="flex flex-col gap-1">Evaluation cohort<select className={field} value={cohort} onChange={e => setCohort(e.target.value)}><option value="forecast">Retained 04:00 forecast decisions</option><option value="baseline">Frozen 7,470-day observation benchmark</option></select></label>
          <div className="grid gap-3 sm:grid-cols-2"><label className="flex flex-col gap-1">Minimum recall (optional, 0–1)<input className={field} type="number" min="0" max="1" step=".01" value={minRecall} onChange={e => setMinRecall(e.target.value)} /></label><label className="flex flex-col gap-1">Maximum Type I rate (optional, 0–1)<input className={field} type="number" min="0" max="1" step=".01" value={maxFp} onChange={e => setMaxFp(e.target.value)} /></label></div>
          <button className="btn" disabled={busy || !validCosts || !param || value === "" || !Number.isFinite(Number(value)) || actor.trim().length < 2 || rationale.trim().length < 10} onClick={() => run(() => api.proposePolicy({actor,category:param.category,changes:[{path,value:Number(value)}],rationale,cohort,analysis_id:analysis?.source === "akamai" && analysis.proposals.some((s: any) => s.path === path && s.value === Number(value) && s.rationale === rationale) ? analysis.id : null,false_alarm_cost:fp,missed_disruption_cost:fn,minimum_recall:minRecall === "" ? null:Number(minRecall),maximum_false_alarm:maxFp === "" ? null:Number(maxFp)}),"Proposal saved; current policy unchanged")}>Save candidate proposal</button>
          <label className="flex flex-col gap-1">Manager authorization token (approve / activate / roll back)<input className={field} type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} /></label>
          <p className="text-muted">{policies.admin_configured ? "Authorization is verified by the server. The token is held only in this view's memory." : "Activation disabled: configure THRESHOLD_ADMIN_TOKEN in the server's ignored .env."} Readiness and confidence brackets require their own independent validation labels; weather accuracy alone cannot approve them.</p>
          {policies.proposals.map((p: any) => { const latest = p.events.at(-1); const report = [...p.events].reverse().find((e: any) => e.report)?.report; return <section key={p.id} className="space-y-2 rounded border border-edge p-3" aria-label={`Policy proposal ${p.id}`}>
            <strong>{p.category} proposal · {p.status}</strong><p>{p.changes.map((c: any) => `${c.path} → ${c.value}`).join("; ")}</p><p>{p.rationale}</p><p>{latest.reason ?? report?.reason}</p>
            {report && <><p>{report.cohort_n} retained days · cohort {report.cohort_sha.slice(0,12)} · {report.purged_days.length} dates purged</p>{Object.entries(report.scores).map(([key,v]: [string,any]) => <p key={key}>{key}: loss {v.incumbent.weighted_loss} → {v.candidate.weighted_loss}; recall {pct(v.incumbent.recall)} → {pct(v.candidate.recall)}; Type I {pct(v.incumbent.false_positive_rate.rate)} → {pct(v.candidate.false_positive_rate.rate)}; n={v.candidate.n}</p>)}<p>Validation: {report.additional_disruptions_caught} additional disruptions caught; {report.additional_false_alarms} additional false alarms. Historical test scores are retrospective.</p></>}
            {(["proposed","validated","approved","active"].includes(p.status)) && <button className="btn" disabled={busy || actor.trim().length < 2 || (p.status !== "proposed" && (!token || !policies.admin_configured))} onClick={() => {const action = p.status === "proposed" ? "evaluate" : p.status === "validated" ? "approve" : p.status === "approved" ? "activate" : "rollback"; run(() => api.policyAction(p.id,action,{actor,version:p.version},token),`${action} action recorded`);}}>{p.status === "proposed" ? "Run full-engine backtest" : p.status === "validated" ? "Approve validated candidate" : p.status === "approved" ? "Activate approved policy" : "Roll back active policy"}</button>}
            <details><summary>Audit trail & limitations</summary>{p.events.map((e: any) => <p key={e.id}>{e.at} · {e.actor} · {e.status}</p>)}{report?.limitations.map((s: string) => <p key={s}>{s}</p>)}</details>
          </section>;})}
        </>}
      </div></details>
    </div>
  </Card>;
}
