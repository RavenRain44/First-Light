import { useEffect, useState } from "react";
import { facilityLabel, useFacility } from "../facility";
import { api } from "../api";
import { Card } from "../util";
const pct = (v: number | null | undefined) => v == null ? "Not enough data" : `${(v * 100).toFixed(1)}%`;

export function BacktestingPanel({evaluationTime='04:00'}: {evaluationTime?: string}) {
  const facility = useFacility();
  const station = facility.asos_station ?? "local station";
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [start, setStart] = useState(facility.state === "NC" ? "2018-01-01" : "2020-01-01");
  const [end, setEnd] = useState("");
  const [mode, setMode] = useState("observation");
  const [online, setOnline] = useState(false);
  const refresh = () => api.backtesting().then(d => {setData(d); setEnd(cur => cur || d.supported_end);}).catch(e => setError(e.message));
  useEffect(() => { let active=true; api.backtesting().then(d => {if(active){setData(d);setEnd(d.supported_end);}}).catch(e => active && setError(e.message)); return () => {active=false;}; }, []);
  const running=data?.jobs?.some((j:any)=>['queued','running'].includes(j.status));
  useEffect(() => { if(!running) return; const t=window.setInterval(refresh,5000); return ()=>clearInterval(t); }, [running]);
  const action=async(fn:()=>Promise<any>)=>{setBusy(true);setError("");try {await fn();await refresh();}catch(e:any){setError(e.message);}finally{setBusy(false);}};
  const scores=data?.metrics_by_time?.[evaluationTime];
  return <Card title={`Multi-year backtesting · ${facilityLabel(facility)} · ${evaluationTime} ${facility.timezone}`}>
    <p className="text-sm text-muted">Scores compare recommendations with independent {station} weather observations and separately with documented local operating decisions. This synthetic facility has no verified closure history.</p>
    {error && <p role="alert" className="mt-3 text-sm">{error}</p>}
    {!data ? <p className="mt-3">Loading coverage…</p> : <>
      <p className="mt-3 text-sm">{evaluationTime==='04:00' && data.analysis_cohort ? `${data.analysis_cohort.n.toLocaleString()} days in the fixed observation analysis cohort · ${data.archive_evaluation_count.toLocaleString()} stored evaluations across reconstruction types` : `${scores?.n ?? 0} daily evaluations under current rules`} · {scores?.range?.start ?? 'not built'} through {scores?.range?.end ?? 'not built'}. Search range: {data.supported_start}–{data.supported_end}; availability varies.</p>
      <p className="mt-3 text-sm">Decision dataset: {data.decision_dataset?.institution_days ?? 0} confirmed office records across {data.decision_dataset?.unique_days?.length ?? 0} dates. Unknown office decisions are excluded from closure scoring. Weather-impact scores below remain a separate weather-only benchmark.</p><details className="mt-2"><summary>Decision evidence filter & exclusions</summary><p>{data.decision_dataset?.label}</p>{data.decision_dataset?.excluded_records?.map((r:any)=><p key={r.institution+r.day}>{r.day} · {r.institution}: {r.reason}</p>)}</details><div className="mt-4 space-y-3">{Object.entries(scores?.impact ?? {}).map(([kind,m]:[string,any])=><section key={kind} className="rounded-lg border border-edge p-3 text-sm">
        <h3 className="font-semibold">Observed-impact alignment · {kind}</h3>
        <p>Balanced accuracy: <strong>{pct(m.balanced_accuracy)}</strong> · Ordinary accuracy: {pct(m.accuracy)} ({m.correct}/{m.n})</p>
        <p>Precision {pct(m.precision)} · Recall {pct(m.recall)} · False alarms {m.confusion.false_alarm} · Missed disruptions {m.confusion.missed_disruption}</p>
        <p>False-alarm rate {pct(m.specificity == null ? null : 1 - m.specificity)} of {m.confusion.false_alarm + m.confusion.true_negative} non-disruptive days · Missed-disruption rate {pct(m.recall == null ? null : 1 - m.recall)} of {m.confusion.missed_disruption + m.confusion.true_positive} disruptive days. Trade-offs and assumed costs: Today → Errors & risk trade-offs.</p>
        <p className="text-xs text-muted">{m.status}; local station weather labels, not actual closure accuracy. Missing outcome days excluded.</p>
        <details className="mt-2"><summary className="cursor-pointer">Confusion matrix & uncertainty</summary><p>True disruptions detected: {m.confusion.true_positive}; normal days correctly identified: {m.confusion.true_negative}.</p><p>95% Wilson interval for ordinary accuracy: {m.accuracy_95pct_wilson ? m.accuracy_95pct_wilson.map(pct).join('–') : 'Unavailable'}. Storm clustering is not corrected.</p></details>
      </section>)}</div>
      {!Object.keys(scores?.impact ?? {}).length && <p className="mt-3 text-sm">Not enough data for an impact alignment score. Build historical coverage below.</p>}
      <details className="mt-4"><summary className="cursor-pointer font-semibold">Local closure agreement & source evidence</summary>
        <p className="mt-2 text-sm">{scores?.proxy_institution_days ?? 0} scored institution-days across {scores?.proxy_unique_days ?? 0} unique days. Closure-only evidence cannot establish false-alarm rate or balanced accuracy.</p>
        <p className="text-sm">Announcement timestamp known: {scores?.announcement_time_known??0}; unknown: {scores?.announcement_time_unknown??0}; documented by evaluation time: {scores?.announcement_before_evaluation??0} (includes dated reporting bounds).</p>
        {Object.entries(scores?.proxy ?? {}).map(([name,m]:[string,any])=><section key={name} className="mt-2 rounded border border-edge p-2 text-sm"><p>{name}: broad agreement {pct(m.accuracy)} ({m.correct}/{m.n}); exact-status agreement {pct(m.exact_status.accuracy)} ({m.exact_status.correct}/{m.exact_status.n}).</p><p>{m.status} · Balanced {pct(m.balanced_accuracy)} · Precision {pct(m.precision)} · Recall {pct(m.recall)} · False alarms {m.confusion.false_alarm} · Misses {m.confusion.missed_disruption} · True disruptions {m.confusion.true_positive} · Normal days {m.confusion.true_negative}.</p><p>95% ordinary accuracy interval: {m.accuracy_95pct_wilson?.map(pct).join('–')??'Unavailable'}.</p></section>)}
        {Object.entries(scores?.institution_disagreements??{}).map(([day,statuses])=><p key={day} className="text-sm">Different institutional statuses on {day}: {(statuses as string[]).join(', ')}.</p>)}
        <ul className="mt-3 space-y-2 text-sm">{(data.proxy_records ?? []).map((r:any,i:number)=><li key={i}><strong>{r.day} · {r.institution} · {r.status}</strong><p>{r.evidence}</p><a href={r.source_url} target="_blank" rel="noreferrer" className="underline">{r.verification} source</a><p>{r.note}</p>{r.corroborating_source_url&&<a href={r.corroborating_source_url} target="_blank" rel="noreferrer" className="underline">Corroborating dated source</a>}<p className="text-xs text-muted">Announcement time: {r.announced_at ?? 'unknown'}{r.announced_by ? `; documented by ${r.announced_by} (upper bound only)` : ''}.</p></li>)}</ul>
      </details>
      <details className="mt-4"><summary className="cursor-pointer font-semibold">Coverage, exclusions & scoring definitions</summary><div className="mt-2 space-y-2 text-sm">
        <p>{scores?.mapping}</p><p>Outcome v1: daily {station} gust ≥58 mph, ≥2 freezing-precipitation hours, ≥3 snow hours with visibility ≤¼ mile, or feels-like ≤−35°F. Requires all but two daily observation hours and no gap over three hours. Off-station damage and corridor conditions are not represented.</p>
        <p>Observation reconstructions use only the preceding 12 hours, with a 15-minute validity lag; afternoon weather is not known. Forecast reconstruction estimates publication as run time + two hours and retains archive limitations.</p>
        {scores?.limitations?.map((s:string)=><p key={s}>{s}</p>)}
        <p>Excluded: {Object.entries(scores?.excluded ?? {}).map(([reason,n])=>`${n}: ${reason}`).join('; ') || 'None built yet'}</p>
        <details><summary>Results by year and hazard</summary>{Object.entries(scores?.impact_breakdowns ?? {}).map(([key,m]:[string,any])=><p key={key}>{key}: balanced {pct(m.balanced_accuracy)}, {m.correct}/{m.n} ordinary agreement.</p>)}</details>
        <p>Stored source years: {(data.storage?.source_years ?? []).join(', ') || 'none'} · compressed sources {((data.storage?.compressed_source_bytes ?? 0)/1048576).toFixed(2)} MiB · evaluations {((data.storage?.compressed_evaluation_bytes ?? 0)/1048576).toFixed(2)} MiB ({Math.round((data.storage?.mean_evaluation_bytes ?? 0))} bytes/result) · SQLite {((data.storage?.db_bytes ?? 0)/1048576).toFixed(2)} MiB (includes decisions and camera archives).</p>
      </div></details>
      <details className="mt-4"><summary className="cursor-pointer font-semibold">Akamai dataset storage</summary><p className="mt-2 text-sm">Publish the frozen cohort, yearly source archives and reports to a private bucket using <code>npm run dataset:cloud -- publish</code>. Restore on another server with <code>npm run dataset:cloud -- restore --full</code>; cache one year with <code>npm run dataset:cloud -- restore --year 2024</code>. Set OBJ_* in the ignored backend .env first. Existing local files are preserved when they differ. Dataset uploads exclude operational database backups, credentials and contacts.</p></details>
      <details className="mt-4"><summary className="cursor-pointer font-semibold">Build / resume historical coverage</summary><div className="mt-3 flex flex-wrap gap-3 text-sm">
        <label>From <input type="date" min={data.supported_start} max={data.supported_end} value={start} onChange={e=>setStart(e.target.value)} className="rounded border border-edge bg-surface p-1" /></label>
        <label>Through <input type="date" min={start} max={data.supported_end} value={end} onChange={e=>setEnd(e.target.value)} className="rounded border border-edge bg-surface p-1" /></label>
        <label>Sources <select value={mode} onChange={e=>setMode(e.target.value)} className="rounded border border-edge bg-surface p-1"><option value="observation">Efficient observation baseline</option><option value="archive">Forecast/alert archive enrichment (slower)</option></select></label>
        <label><input type="checkbox" checked={online} onChange={e=>setOnline(e.target.checked)} /> Download missing public archives</label>
        <button className="btn" disabled={busy || running || !end} onClick={()=>action(()=>api.startHistoryBuild({start,end,mode,online}))}>Build coverage</button>
      </div><p className="mt-2 text-xs text-muted">Bulk builds evaluate 04:00 {facility.timezone}. Other evaluation times are built on demand through date/time search. No paid AI calls. Daily results are compressed and resumable. Observation baseline cannot predict later weather; forecast enrichment takes more archive requests.</p>
      <ul className="mt-3 space-y-2 text-sm">{(data.jobs ?? []).slice(0,10).map((j:any)=><li key={j.id} className="rounded-lg border border-edge p-3">{j.start}–{j.end} · {j.mode} · <strong>{j.status}</strong> · processed {j.processed} · next {j.next_day} · {Math.round(j.seconds)}s
        {['interrupted','cancelled','queued'].includes(j.status) && <button className="btn ml-2" disabled={busy} onClick={()=>action(()=>api.resumeHistoryBuild(j.id))}>Resume</button>}
        {['running','queued'].includes(j.status) && <button className="btn ml-2" disabled={busy} onClick={()=>action(()=>api.cancelHistoryBuild(j.id))}>Cancel</button>}
        {j.failed.length>0 && <details><summary>Failed ranges · {j.failed.length}</summary>{j.failed.map((f:any,i:number)=><p key={i}>{f.day}{f.through ? `–${f.through}` : ''}: {f.reason}. Start a build of this range to retry.</p>)}</details>}
      </li>)}</ul></details>
    </>}
  </Card>;
}
