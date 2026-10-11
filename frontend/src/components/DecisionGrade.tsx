import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, Skeleton } from "../util";

const field = "min-h-[44px] min-w-0 w-full rounded-lg border border-edge bg-surface px-3 py-2";
const words = (s: string) => s.replaceAll("_", " ");

export function DecisionGrade({ id, onBack }: { id: number; onBack: () => void }) {
  const [data, setData] = useState<any>(null);
  const [actor, setActor] = useState("");
  const [objective, setObjective] = useState("");
  const [verdict, setVerdict] = useState("insufficient_evidence");
  const [achievement, setAchievement] = useState("unknown");
  const [disputed, setDisputed] = useState(false);
  const [note, setNote] = useState("");
  const [refs, setRefs] = useState("");
  const [correction, setCorrection] = useState("");
  const [intentCorrection, setIntentCorrection] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const load = async () => {
    const d = await api.grade(id); setData(d);
    setObjective(d.intentions[0]?.objective ?? "");
    const r = d.reviews.find((r: any) => r.source === "manager");
    if (r) { setDisputed(r.evidence.observed_evidence_status === "disputed"); setVerdict(r.verdict); setAchievement(r.evidence.achievement ?? "unknown"); setNote(r.note ?? ""); setRefs((r.evidence.evidence_refs ?? []).join("\n")); }
  };
  useEffect(() => { load().catch(e => setError(e.message)); }, [id]);
  const run = async (action: () => Promise<any>, success: string) => {
    setBusy(true); setError(""); setMessage("");
    try { await action(); await load(); setMessage(success); setCorrection(""); setIntentCorrection(""); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const review = data?.reviews.find((r: any) => r.source === "manager");
  const assessment = data?.assessments[0];
  return <div className="space-y-4">
    <button className="btn" onClick={onBack}>← Back to decision log</button>
    <Card title={`Grade decision #${id}`}>
      {error && <p role="alert" className="my-2 text-[var(--danger)]">{error} <button className="btn" disabled={busy} onClick={() => run(load, "Record refreshed")}>Refresh record</button></p>}
      {message && <p role="status" className="my-2">{message}</p>}
      {!data && !error && <Skeleton className="h-40" />}
      {data && <div className="space-y-5 text-sm">
        <p><strong>{data.facility.name ?? data.facility.id}</strong> · {data.decision_day} · {data.timezone}</p>
        <p>Recorded {new Intl.DateTimeFormat("en-US", {timeZone: data.timezone, dateStyle:"medium",timeStyle:"short"}).format(new Date(data.decision.decided_at))} · Rule version {data.thresholds_version}</p>
        {data.demo_or_example && <p className="rounded border border-edge p-2">Demo/example: excluded from live accuracy statistics.</p>}
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded border border-edge p-3"><strong>Original recommendation: {words(data.decision.recommended_posture)}</strong><p>{data.recommended_reason.join(" ")}</p></div>
          <div className="rounded border border-edge p-3"><strong>Manager chose: {words(data.decision.decision_posture)}</strong><p>{data.decision.override_reason ?? data.decision.notes ?? "No reasoning recorded."}</p><p>{data.agreed ? "Agreed with recommendation" : "Overrode recommendation"} · agreement is not accuracy.</p></div>
        </div>
        <label className="flex flex-col gap-1">Your name / title<input className={field} value={actor} maxLength={120} onChange={e => setActor(e.target.value)} autoComplete="name" /></label>
        <section className="space-y-2 rounded border border-edge p-3" aria-label="Intended objective">
          <label className="flex flex-col gap-1">What did you want to happen?<textarea className={field} value={objective} onChange={e => setObjective(e.target.value)} maxLength={1000} /></label>
          <p className="text-muted">{data.intentions[0] ? `${data.intentions[0].retrospective ? "Retrospective annotation" : "Captured at decision time"} · ${data.intentions[0].created_at}` : "No objective recorded. Adding one now is labeled retrospective."}</p>
          {data.intentions.length > 0 && <label className="flex flex-col gap-1">Reason for correcting the objective<input className={field} value={intentCorrection} onChange={e => setIntentCorrection(e.target.value)} maxLength={1000} /></label>}
          <button className="btn" disabled={busy || actor.trim().length < 2 || objective.trim().length < 3 || (!!data.intentions.length && !intentCorrection.trim())}
            onClick={() => run(() => api.intention(id, {actor, objective, correction_reason:intentCorrection, expected_id:data.intentions[0]?.id ?? null}), "Objective saved; earlier annotations preserved")}>Save objective</button>
        </section>
        <section className="space-y-2 rounded border border-edge p-3" aria-label="Calculated assessment">
          <strong>Calculated weather assessment</strong>
          <p>{data.status === "pending" ? `Pending: the local day ends at ${new Date(data.period_end).toLocaleString("en-US", {timeZone:data.timezone})} (${data.timezone}).` : assessment?.outcome?.summary ?? "No independently observed outcome has been collected yet."}</p>
          {assessment && <><p>{assessment.eligible ? `${words(assessment.manager_weather_classification)} (manager) · ${words(assessment.recommendation_weather_classification)} (recommendation)` : assessment.exclusion_reason}</p><p>{assessment.comparison}</p><p>{assessment.action_assessment}</p>
            <p>Coverage: {assessment.outcome.coverage?.observed_hours ?? "unknown"}/{assessment.outcome.coverage?.expected_hours ?? "unknown"} hours · label {assessment.label_version}</p>
            {[assessment.outcome.lsr_source_url, ...(assessment.outcome.observation_source_urls ?? [])].filter(Boolean).map((url: string) => <a className="mr-3 underline" key={url} href={url} target="_blank" rel="noreferrer">Observed evidence</a>)}
          </>}
          <button className="btn" disabled={busy || data.status === "pending"} onClick={() => run(() => api.refreshGrade(id), "Observed weather assessment loaded; no AI inference requested")}>{busy ? "Working…" : "Calculate from observed weather"}</button>
          <p className="text-muted">Weather disruption is separate from whether closing was necessary or the manager's goal was achieved.</p>
        </section>
        <section className="space-y-2" aria-label="Manager review">
          <strong>Manager review · your judgment</strong>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1">How did the call fit the situation?<select className={field} value={verdict} onChange={e => setVerdict(e.target.value)}>{["good_call","too_lenient","too_strict","mixed","insufficient_evidence"].map(v => <option key={v} value={v}>{words(v)}</option>)}</select></label>
            <label className="flex flex-col gap-1">Was your objective achieved?<select className={field} value={achievement} onChange={e => setAchievement(e.target.value)}>{["achieved","partly_achieved","not_achieved","unknown"].map(v => <option key={v} value={v}>{words(v)}</option>)}</select></label>
          </div>
          <label className="flex min-h-[44px] items-center gap-2"><input type="checkbox" checked={disputed} onChange={e => setDisputed(e.target.checked)} />Observed weather evidence needs review (exclude from error statistics until resolved)</label>
          <label className="flex flex-col gap-1">What happened? (manager observations)<textarea className={field} value={note} maxLength={2000} onChange={e => setNote(e.target.value)} /></label>
          <label className="flex flex-col gap-1">Evidence URLs (one per line)<textarea className={field} value={refs} onChange={e => setRefs(e.target.value)} placeholder="https://…" /></label>
          {review && <label className="flex flex-col gap-1">Reason for correcting your review<input className={field} value={correction} maxLength={1000} onChange={e => setCorrection(e.target.value)} /></label>}
          <button className="btn btn-primary" disabled={busy || actor.trim().length < 2 || (!!review && !correction.trim())} onClick={() => run(() => api.saveGrade(id, {actor,verdict,achievement,observed_evidence_status:disputed ? "disputed":"not_disputed",note,evidence_refs:refs.split("\n").map(s => s.trim()).filter(Boolean),correction_reason:correction,expected_id:review?.id ?? null}), "Review saved; earlier versions preserved")}>Save manager grade</button>
          <p className="text-muted">Opinions and evidence links do not automatically become verified training labels.</p>
        </section>
        <details><summary className="cursor-pointer font-medium">Review and correction history</summary><div className="mt-2 space-y-2">
          {data.reviews.map((r: any) => <div key={r.id} className="rounded border border-edge p-2"><strong>{r.source === "ai" ? "AI interpretation (not a calculated grade)" : r.source === "manager" ? "Manager opinion" : "Template weather interpretation"} · {words(r.verdict)}</strong><p>{r.note}</p><p>{r.created_at} · {r.evidence.correction_reason || "Initial review"}</p></div>)}
          {data.intentions.map((r: any) => <p key={r.id}>Objective: {r.objective} · {r.created_at} · {r.correction_reason || "Initial objective"}</p>)}
          {data.assessments.map((r: any) => <p key={r.id}>Calculated assessment {r.id} · {r.created_at} · {r.status} · hash {r.hash.slice(0,12)}</p>)}
          {!data.reviews.length && <p>No reviews yet.</p>}
        </div></details>
      </div>}
    </Card>
  </div>;
}
