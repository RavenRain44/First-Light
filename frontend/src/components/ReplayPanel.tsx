import { useEffect, useRef, useState } from "react";
import { LegacyReplayPanel } from "./LegacyReplayPanel";
import { api } from "../api";
import type { Snapshot } from "../types";
import { Card, fmtTime } from "../util";
import { BacktestingPanel } from "./BacktestingPanel";
import { facilityLabel, useFacility } from "../facility";
import { parseReplayTime } from "../replay";

function HistoricalReplayPanel({ onSnapshot, busy, setBusy }: {
  onSnapshot: (s: Snapshot | null) => void; busy: boolean; setBusy: (b: boolean) => void; current?: Snapshot | null;
}) {
  const facility = useFacility();
  const timezone = facility.timezone;
  const [events,setEvents]=useState<any[]>([]);
  const [coverage,setCoverage]=useState<any>(null);
  const [day,setDay]=useState(facility.state === 'NC' ? '2018-09-14' : '2023-02-22');
  const [clock,setClock]=useState('04:00');
  const [eventId,setEventId]=useState('');
  const [mode,setMode]=useState('archive');
  const [online,setOnline]=useState(false);
  const [cloudCache,setCloudCache]=useState(false);
  const [result,setResult]=useState<any>(null);
  const [err,setErr]=useState('');
  const generation=useRef(0);
  const active=useRef(true);
  useEffect(()=>{active.current=true;onSnapshot(null);api.events().then(e=>active.current&&setEvents(e)).catch(e=>active.current&&setErr(e.message));api.backtesting().then(d=>active.current&&setCoverage(d)).catch(e=>active.current&&setErr(e.message));return()=>{active.current=false;generation.current++;};},[]);
  const invalidate=()=>{generation.current++;setResult(null);setErr('');onSnapshot(null);setBusy(false);};
  const search=async(selectedDay=day, selectedTime=clock, retry=false)=>{
    const version=++generation.current;setBusy(true);setErr('');setResult(null);onSnapshot(null);
    try{
      const chosen=events.find(e=>e.id===eventId);
      let data;
      if(chosen?.kind==='normal-control' && mode==='observation'){
        const snapshot=await api.replay(chosen.id,parseReplayTime(`${selectedDay}T${selectedTime}`,timezone).asOf);
        data={...snapshot.historical_context,snapshot};
      }else{
        data=await api.searchHistory({day:selectedDay,time:selectedTime,mode,online,retry,cloud_cache:cloudCache});
      }
      if(!active.current||version!==generation.current)return;
      setResult(data);onSnapshot(data.snapshot ?? null);
    }catch(e:any){if(active.current&&version===generation.current)setErr(e.message);}
    finally{if(active.current&&version===generation.current)setBusy(false);}
  };
  return <div className="space-y-4"><Card title={`Historical weather · ${facilityLabel(facility)}`}>
    <p className="text-sm text-muted">Choose an event or search any day. All weather displays below follow the selected evaluation time. No decisions are recorded and no notifications are sent.</p>
    <div className="mt-4 flex flex-wrap items-end gap-3">
      <label className="grid min-w-0 max-w-full gap-1 text-sm">Listed event<select value={eventId} onChange={e=>{invalidate();setEventId(e.target.value);const chosen=events.find(v=>v.id===e.target.value);if(chosen){setDay(chosen.impact_day);setClock('04:00');if(chosen.kind==='normal-control')setMode('observation');}else if(e.target.value.startsWith('day:')){setDay(e.target.value.slice(4));setClock('04:00');}}} className="min-w-0 max-w-full rounded-lg border border-edge bg-surface p-2"><option value="">Choose an event</option>{events.map(e=><option key={e.id} value={e.id}>{e.name}</option>)}{coverage?.latest_disruptive_days?.filter((d:any)=>coverage.decision_dataset?.unique_days?.includes(d.day)).filter((d:any,i:number,all:any[])=>!events.some(e=>e.impact_day===d.day)&&all.findIndex(x=>x.day===d.day)===i).map((d:any)=><option key={d.id} value={`day:${d.day}`}>{facility.asos_station ?? 'Local station'} observed disruption · {d.day}</option>)}{coverage?.decision_dataset?.unique_days.filter((d:string)=>!events.some(e=>e.impact_day===d)&&!coverage.latest_disruptive_days?.some((e:any)=>e.day===d)).map((d:string)=><option key={d} value={`day:${d}`}>Confirmed office decision · {d}</option>)}</select></label>
      <label className="grid gap-1 text-sm">Date<input type="date" value={day} onInput={e=>{const value=e.currentTarget.value;invalidate();setDay(value);setEventId('');}} className="rounded-lg border border-edge bg-surface p-2" /></label>
      <label className="grid gap-1 text-sm">Time · {timezone}<input type="time" value={clock} onInput={e=>{const value=e.currentTarget.value;invalidate();setClock(value);}} className="rounded-lg border border-edge bg-surface p-2" /></label>
      <button className="btn btn-primary" disabled={busy||!day||!clock} onClick={()=>search()}>{busy?'Loading historical evidence…':'View historical weather'}</button>
    </div>
    <div className="mt-3 flex flex-wrap gap-3 text-sm"><label>Reconstruction <select className="rounded border border-edge bg-surface p-1" value={mode} onChange={e=>{invalidate();setMode(e.target.value);}}><option value="archive">Archived forecasts where available</option><option value="observation">Observation-only baseline</option></select></label><label><input type="checkbox" checked={online} onChange={e=>setOnline(e.target.checked)} /> Download missing public archives</label><label><input type="checkbox" checked={cloudCache} onChange={e=>setCloudCache(e.target.checked)} /> Load missing years from Akamai dataset</label></div>
    <p className="mt-2 text-xs text-muted">Normal-weather controls verify station observations. Curated storms and documented office decisions are labeled separately. Arbitrary date search still accesses the weather archive. Evidence is high-confidence, not a calibrated 95% probability.</p><p className="mt-2 text-xs text-muted">Supported search: {coverage?.supported_start ?? 'provider-dependent'} through {coverage?.supported_end ?? 'latest complete day'}. Coverage varies; absent records are not normal weather.</p>
    {err&&<p role="alert" className="mt-3 rounded-lg border border-edge p-3">{err}</p>}
    {result&&<div role="status" className="mt-4 rounded-lg border border-edge p-3 text-sm">
      <strong>{result.status==='unavailable'?'Historical data unavailable':result.reconstruction} · {day} {clock} {timezone}</strong><p>{result.detail}</p>
      {result.as_of&&<p>Exact evaluation: {fmtTime(result.as_of,timezone)}</p>}
      {result.snapshot&&<p>Recommendation applies to: {result.snapshot.posture.decision_day}{result.snapshot.posture.decision_day!==day?' (next scheduled facility day; excluded from same-day scores)':''}.</p>}
      {result.outcome&&<p>Independent daily outcome: {result.outcome.gradable?(result.outcome.disruptive?'Local disruptive conditions observed':'No defined local disruption observed'):'Ungradable — '+result.outcome.reason}.</p>}
      <button className="btn mt-2" disabled={busy} onClick={()=>search(day,clock,true)}>Rebuild this result</button>
      <details className="mt-2"><summary className="cursor-pointer">Coverage, sources & local closure evidence</summary><ul>{[...(result.missing??[]),...(result.assumptions??[])].map((s:string)=><li key={s}>{s}</li>)}</ul>{result.source_coverage?.map((s:any)=><p key={s.adapter}>{s.adapter}: {s.status} {s.detail}</p>)}{result.provenance&&<a href={result.provenance.url} className="underline" target="_blank" rel="noreferrer">{facility.asos_station ?? 'Station'} source archive</a>}<ul>{result.proxy_records?.map((r:any,i:number)=><li key={i}>{r.institution}: {r.status} · <a className="underline" href={r.source_url} target="_blank" rel="noreferrer">Evidence</a></li>)}</ul>{!result.proxy_records?.length&&<p>No documented local operating decision for this date; operating status is unknown.</p>}</details>
    </div>}
  </Card><details><summary className="cursor-pointer text-sm font-semibold">Multi-year scores & build progress</summary><div className="mt-3"><BacktestingPanel key={result?.id??clock} evaluationTime={clock} /></div></details></div>;
}

export function ReplayPanel(props: {onSnapshot: (s: Snapshot | null) => void; busy: boolean; setBusy: (b: boolean) => void; current?: Snapshot | null}) {
  const [timeline, setTimeline] = useState(false);
  return <div><div className="mb-3 flex gap-2"><button className="btn" disabled={!timeline} onClick={() => {props.onSnapshot(null); props.setBusy(false); setTimeline(false);}}>Date search & multi-year scores</button><button className="btn" disabled={timeline} onClick={() => {props.onSnapshot(null); props.setBusy(false); setTimeline(true);}}>Curated storm timeline</button></div>{timeline ? <LegacyReplayPanel {...props} /> : <HistoricalReplayPanel {...props} />}</div>;
}
