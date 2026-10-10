import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Card } from "../util";

async function request(path: string, method = "GET", body?: unknown): Promise<any> {
  const r = await fetch(`/api/notifications${path}`, { method, headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await r.json();
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  return data;
}
const input = "rounded-md border border-edge bg-surface px-2 py-1";
const button = "rounded-md border border-edge px-3 py-1.5 text-sm disabled:opacity-40";
const time = (t: string, tz: string) => new Intl.DateTimeFormat("en-US", { timeZone: tz, dateStyle: "medium", timeStyle: "short" }).format(new Date(t));

function Feedback({tone, title, text}: {tone: "success" | "warning" | "error"; title: string; text: string}) {
  const color = tone === "error" ? "var(--critical)" : tone === "warning" ? "var(--serious)" : "var(--series-1)";
  return <div role={tone === "error" ? "alert" : "status"} className="mt-3 rounded-lg border-l-4 bg-surface p-3 text-sm" style={{borderColor: color}}>
    <p className="font-semibold">{tone === "success" ? "✓ " : tone === "error" ? "✕ " : "! "}{title}</p>
    <p className="mt-1 whitespace-pre-wrap">{text}</p>
  </div>;
}

function GroupEditor({ group: g, pack: p, contacts, actor, run, onDirty }: any) {
  const [sms, setSms] = useState(g.sms_intro);
  const [email, setEmail] = useState(g.email_intro);
  const [schedule, setSchedule] = useState(g.schedule_override ?? "");
  const [scenario, setScenario] = useState(g.scenario);
  const [selected, setSelected] = useState<string[]>(g.test_contacts);
  const [employeeIds, setEmployeeIds] = useState<string[]>(g.recipient_ids ?? g.recipients.map((r: any) => r.id));
  const [recipient, setRecipient] = useState(g.recipients[0]?.name ?? "Recipient");
  const dirty = sms !== g.sms_intro || email !== g.email_intro || schedule !== (g.schedule_override ?? "") || scenario !== g.scenario || JSON.stringify(selected) !== JSON.stringify(g.test_contacts) || JSON.stringify(employeeIds) !== JSON.stringify(g.recipient_ids ?? g.recipients.map((r: any) => r.id));
  useEffect(() => { onDirty(g.id, dirty); return () => onDirty(g.id, false); }, [g.id, dirty, onDirty]);
  const editable = p.status === "draft";
  return <div className="card space-y-3 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{g.title} · {employeeIds.length} of {g.recipients.length} selected</h3><span className="text-sm">{g.approved && !dirty ? `Approved by ${g.approved_by}` : "Needs review"}</span></div>
    <p className="text-sm text-ink2">{g.instruction}</p>
    <p className="text-xs text-muted">Reporting instructions are fixed by the recorded decision. Edit the explanation below. Changes require fresh approval.</p>
    <div className="grid gap-3 md:grid-cols-2">
      <label className="grid gap-1 text-sm">SMS explanation<textarea className={input} rows={3} maxLength={120} value={sms} disabled={!editable} onChange={e => setSms(e.target.value)} /></label>
      <label className="grid gap-1 text-sm">Email explanation<textarea className={input} rows={3} maxLength={2000} value={email} disabled={!editable} onChange={e => setEmail(e.target.value)} /></label>
    </div>
    <div className="flex flex-wrap gap-3">
      <label className="grid gap-1 text-sm">Timing override (ISO time with offset; blank = recipient schedule)<input className={input} placeholder="2026-10-12T07:30:00-05:00" value={schedule} disabled={!editable} onChange={e => setSchedule(e.target.value)} /></label>
      <label className="grid gap-1 text-sm">Simulated provider outcome<select className={input} value={scenario} disabled={!editable} onChange={e => setScenario(e.target.value)}><option value="success">Success</option><option value="failure">Failure</option><option value="delay">Five-minute delay</option></select></label>
    </div>
    <details open><summary className="cursor-pointer text-sm">Choose recipients in this group</summary><label className="mt-2 block text-sm"><input type="checkbox" disabled={!editable} checked={employeeIds.length === g.recipients.length} onChange={e => setEmployeeIds(e.target.checked ? g.recipients.map((r: any) => r.id) : [])} /> Select all {g.recipients.length} group members</label><ul className="mt-2 space-y-2 text-sm">{g.recipients.map((r: any) => <li key={r.id}><label><input type="checkbox" disabled={!editable} checked={employeeIds.includes(r.id)} onChange={e => setEmployeeIds(e.target.checked ? [...employeeIds, r.id] : employeeIds.filter(id => id !== r.id))} /> <strong>{r.name}</strong></label> · {r.channels.join(" + ")} · {time(schedule || r.due_at, p.timezone)}<br />{r.reason}<br /><span className="text-xs text-muted">{r.schedule_source} · work start {r.work_start}{r.accessibility_followup ? " · manager accessibility follow-up needed" : ""}</span></li>)}</ul></details>
    <details><summary className="cursor-pointer text-sm">Add separate test contacts (simulation only)</summary><div className="mt-2 grid gap-2">{contacts.length === 0 && <p className="text-sm">No local test contacts configured.</p>}{contacts.map((c: any) => <label key={c.id} className="text-sm"><input type="checkbox" disabled={!editable} checked={selected.includes(c.id)} onChange={e => setSelected(e.target.checked ? [...selected, c.id] : selected.filter(x => x !== c.id))} /> {c.name} · {c.channel} · {c.address}</label>)}</div></details>
    <details><summary className="cursor-pointer text-sm">Personalized message previews</summary><select className={`${input} mt-2`} value={recipient} onChange={e => setRecipient(e.target.value)}>{g.recipients.map((r: any) => <option key={r.id}>{r.name}</option>)}</select><div className="mt-2 grid gap-3 md:grid-cols-2">{["sms", "email"].map(c => <div key={c}><h4 className="text-sm font-semibold">{c.toUpperCase()} · simulated{c === "sms" ? ` · ${(g.previews?.sms ?? "").length} characters` : ""}</h4><p className="whitespace-pre-wrap text-sm">{(g.previews?.[c] ?? "").replace("Recipient:", `${recipient}:`).replace(c === "sms" ? g.sms_intro : g.email_intro, c === "sms" ? sms : email)}</p></div>)}</div></details>
    {editable && <div className="flex gap-2"><button className={button} disabled={!actor.trim() || !dirty} onClick={() => run(() => request(`/packages/${p.id}/groups/${g.id}`, "PUT", { version: p.version, actor, sms_intro: sms, email_intro: email, schedule_override: schedule || null, scenario, test_contacts: selected, recipient_ids: employeeIds }))}>Save edits · clear approval</button><button className={button} disabled={!actor.trim() || dirty || g.approved} onClick={() => run(() => request(`/packages/${p.id}/groups/${g.id}/approve`, "POST", { version: p.version, actor }))}>Approve this group</button></div>}
  </div>;
}

function NotificationTools() {
  const [state, setState] = useState<any>(null);
  const [decisions, setDecisions] = useState<any[]>([]);
  const [decision, setDecision] = useState("");
  const [pid, setPid] = useState("");
  const [actor, setActor] = useState("");
  const [fallback, setFallback] = useState("");
  const [clock, setClock] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [audit, setAudit] = useState<any[] | null>(null);
  const [dirtyGroups, setDirtyGroups] = useState<Record<string, boolean>>({});
  const onDirty = useCallback((id: string, dirty: boolean) => setDirtyGroups(cur => ({ ...cur, [id]: dirty })), []);
  const [inbox, setInbox] = useState("");
  const refresh = async () => {
    const [data, ds] = await Promise.all([request(""), api.decisions()]);
    setState(data); setDecisions(ds);
    setActor(cur => cur || ds[0]?.decided_by || "");
    setPid(cur => cur || data.packages[0]?.id || "");
    setDecision(cur => cur || (ds[0]?.id ? String(ds[0].id) : ""));
  };
  useEffect(() => { refresh().catch(e => setError(e.message)); const id = window.setInterval(() => refresh().catch(e => setError(e.message)), 5000); return () => clearInterval(id); }, []);
  const run = async (fn: () => Promise<any>) => {
    setBusy(true); setError("");
    try { const result = await fn(); if (result?.id) setPid(result.id); await refresh(); setAudit(null); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };
  const p = state?.packages.find((x: any) => x.id === pid);
  const messages = state?.packages.flatMap((x: any) => x.messages.map((m: any) => ({ ...m, package: x }))) ?? [];
  return <div className="space-y-4">
    <Card title="Employee notifications" right={<span className="text-sm font-semibold">SIMULATION ONLY</span>}>
      <p className="text-sm text-ink2">Review group drafts, approve them, then send once. SMS and email stay inside this app; nothing reaches a phone or mailbox.</p>
      {error && <p role="alert" className="mt-2 text-sm text-[var(--critical)]">{error}</p>}
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-sm">Reviewing manager<input className={input} value={actor} placeholder="Name, title" onChange={e => setActor(e.target.value)} /></label>
        <label className="grid gap-1 text-sm">Recorded decision<select className={input} value={decision} onChange={e => setDecision(e.target.value)}><option value="">Select decision</option>{decisions.map(d => <option key={d.id} value={d.id}>#{d.id} · {d.decision_posture} · {d.decided_by}</option>)}</select></label>
        <label className="grid gap-1 text-sm">Awareness fallback start<input className={input} type="time" value={fallback} onChange={e => setFallback(e.target.value)} /></label>
        <button className={button} disabled={busy || !decision} onClick={() => run(() => request("/packages", "POST", { decision_id: Number(decision), fallback_start: fallback || null }))}>Create / open drafts</button>
      </div>
      <p className="mt-2 text-xs text-muted">Record a live or replay decision on the Dashboard first. Missing employee schedules fall back to facility opening time, unless overridden here. The synthetic roster represents the current assignment scenario.</p>
    </Card>
    <Card title="Simulation clock">
      <p className="text-sm">{state?.demo_clock ? "Demo clock" : "Real-time simulation clock"}: {state?.now ? time(state.now, p?.timezone ?? "America/Chicago") : "Loading…"}. Weather evaluation time is unchanged.</p>
      <div className="mt-2 flex flex-wrap gap-2"><input aria-label="Demo clock ISO timestamp" className={input} value={clock} placeholder="2026-10-12T04:00:00-05:00" onChange={e => setClock(e.target.value)} /><button className={button} disabled={busy || !actor.trim() || !clock} onClick={() => run(() => request("/clock", "PUT", { now: clock, actor }))}>Set / advance demo clock</button><button className={button} disabled={busy || !actor.trim() || !state} onClick={() => run(() => request("/clock", "PUT", { now: new Date(new Date(state.now).getTime() + 60 * 60 * 1000).toISOString(), actor }))}>Advance 1 hour</button><button className={button} disabled={busy || !actor.trim()} onClick={() => run(() => request("/clock", "PUT", { now: null, actor }))}>Reset to real time</button></div>
    </Card>
    {state?.packages.length > 0 && <label className="grid gap-1 text-sm">Notification package<select className={input} value={pid} onChange={e => { setPid(e.target.value); setAudit(null); }}>{state.packages.map((x: any) => <option key={x.id} value={x.id}>Decision #{x.decision_id} · {x.decision_day} · {x.posture} · {x.status}</option>)}</select></label>}
    {p && <>
      <Card title={`Decision #${p.decision_id} · ${p.posture}`}><p className="text-sm">{p.facility_name} · {p.decision_day} · {p.timezone} · {p.draft_source}</p><p className="text-xs text-muted">Snapshot {p.snapshot_id} · status {p.status}</p><p className="mt-2 text-sm">{p.messages.filter((m: any) => m.status === "simulated_sent").length} simulated deliveries · {p.messages.filter((m: any) => ["scheduled", "queued", "delayed"].includes(m.status)).length} pending · {p.messages.filter((m: any) => m.status === "simulated_failed").length} failed</p></Card>
      {p.status === "dispatched" && <Card title="This package has already been sent"><p className="text-sm">Sent messages are preserved. Create a follow-up draft to edit messages, choose several recipients in each group, review and send another update.</p><button className={`${button} mt-2`} disabled={busy || actor.trim().length < 2} onClick={() => run(() => request(`/packages/${p.id}/followup`, "POST", { version: p.version, actor }))}>Create editable follow-up draft</button></Card>}
      <fieldset disabled={busy} className="space-y-3">{p.groups.map((g: any) => <GroupEditor key={`${p.id}:${g.id}:${g.sms_intro}:${g.email_intro}:${g.approved}:${g.schedule_override}:${g.scenario}:${g.test_contacts.join(",")}:${(g.recipient_ids ?? []).join(",")}`} group={g} pack={p} contacts={state.contacts} actor={actor} run={run} onDirty={onDirty} />)}</fieldset>
      {p.groups.length === 0 && <Card title="No changed reporting instructions"><p className="text-sm">The team was already notified. To write another manager-reviewed update, create recipient groups below.</p><button className={`${button} mt-2`} disabled={busy || p.status !== "draft"} onClick={() => run(() => request("/packages", "POST", { decision_id: p.decision_id, include_unchanged: true }))}>Create groups for another update</button></Card>}
      <details className="card p-3"><summary className="cursor-pointer">Excluded employees ({p.excluded.length})</summary><ul className="mt-2 space-y-1 text-sm">{p.excluded.map((r: any) => <li key={r.id}>{r.name}: {r.reason}</li>)}</ul></details>
      <button className={`${button} bg-[var(--series-1)] text-white`} disabled={busy || actor.trim().length < 2 || p.status !== "draft" || !p.groups.length || Object.values(dirtyGroups).some(Boolean) || p.groups.some((g: any) => ((g.recipient_ids ?? g.recipients.map((r: any) => r.id)).length > 0 || g.test_contacts.length > 0) && !g.approved) || p.groups.every((g: any) => (g.recipient_ids ?? g.recipients).length === 0 && g.test_contacts.length === 0)} onClick={() => run(() => request(`/packages/${p.id}/send`, "POST", { version: p.version, actor }))}>Send approved immediate messages & schedule updates · simulated</button>
      <details className="card p-3"><summary className="cursor-pointer" onClick={() => request(`/packages/${p.id}/audit`).then(setAudit).catch(e => setError(e.message))}>Audit trail</summary>{audit?.map(a => <details key={a.id} className="mt-2 text-sm"><summary>{time(a.at, p.timezone)} · {a.actor} · {a.action}</summary><pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(JSON.parse(a.detail_json), null, 2)}</pre></details>)}</details>
    </>}
    <Card title="Simulated outbox"><div className="space-y-3">{messages.length === 0 && <p className="text-sm">No messages sent or scheduled.</p>}{messages.map((m: any) => <details key={m.id} className="border-b border-edge pb-2 text-sm"><summary className="cursor-pointer">{m.recipient_name} · {m.channel} · {m.status} (simulated) · {time(m.due_at, m.package.timezone)}</summary><p>Destination: {m.address}</p><p>{m.reason}</p><p className="mt-2 whitespace-pre-wrap">{m.body}</p><ul className="mt-2 text-xs">{m.attempts.map((a: any, i: number) => <li key={i}>{time(a.at, m.package.timezone)} · {a.detail}</li>)}</ul>{m.status === "simulated_failed" && m.package.status === "dispatched" && <button className={`${button} mt-2`} disabled={busy || actor.trim().length < 2} onClick={() => run(() => request(`/packages/${m.package.id}/messages/${encodeURIComponent(m.id)}/retry`, "POST", { version: m.package.version, actor }))}>Retry with simulated success</button>}</details>)}</div></Card>
    <Card title="Recipient inbox preview"><select aria-label="Recipient inbox" className={input} value={inbox} onChange={e => setInbox(e.target.value)}><option value="">Select recipient</option>{Array.from(new Set<string>(messages.map((m: any) => m.recipient_name))).map(n => <option key={n}>{n}</option>)}</select><div className="mt-3 space-y-3">{messages.filter((m: any) => m.recipient_name === inbox && m.status === "simulated_sent").map((m: any) => <div className="rounded-md border border-edge p-3" key={m.id}><p className="text-xs text-muted">{m.channel.toUpperCase()} · SIMULATED · Decision #{m.package.decision_id}</p><p className="whitespace-pre-wrap text-sm">{m.body}</p></div>)}</div><p className="mt-2 text-xs text-muted">Only successful simulated deliveries appear here. No acknowledgments are collected.</p></Card>
  </div>;
}


export function NotificationsView({ decisionId, onBack }: { decisionId?: number | null; onBack?: () => void }) {
  const [p, setP] = useState<any>(null);
  const [groups, setGroups] = useState<any[]>([]);
  const [contacts, setContacts] = useState<any[]>([]);
  const [ready, setReady] = useState<any>({email: false, sms: false});
  const [actor, setActor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{tone: "success" | "warning"; text: string} | null>(null);
  const [testGroup, setTestGroup] = useState("");
  const [testIds, setTestIds] = useState<string[]>([]);
  const [testResult, setTestResult] = useState<any>(null);
  const [smtpCheck, setSmtpCheck] = useState<any>(null);
  const requestId = useRef<string>(crypto.randomUUID());
  const install = (pack: any) => {
    setP(pack); setGroups(pack.groups.map((g: any) => ({ ...g, recipient_ids: g.recipient_ids ?? g.recipients.map((r: any) => r.id) })));
    setActor(pack.decided_by); setTestGroup(pack.groups[0]?.id ?? "");
  };
  const load = async () => {
    const [ds, data, setup] = await Promise.all([api.decisions(), request(""), request("/delivery-setup")]);
    const emails = data.contacts.filter((c: any) => c.channel === "email" || (c.channel === "sms" && c.gateway_address));
    setContacts(emails); setTestIds(emails.map((c: any) => c.id)); setReady(setup);
    const id = decisionId ?? ds[0]?.id;
    if (id) {
      let pack = await request("/packages", "POST", {decision_id: id});
      if (pack.status === "draft" && pack.groups.length === 0) pack = await request("/packages", "POST", {decision_id: id, include_unchanged: true});
      install(pack);
    }
  };
  useEffect(() => { setBusy(true); load().catch(e => setError(e.message)).finally(() => setBusy(false)); }, [decisionId]);
  const perform = async (fn: () => Promise<void>, confirmation?: string) => {
    setBusy(true); setError(""); setNotice(null);
    try { await fn(); if (confirmation) setNotice({tone:"success", text:confirmation}); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const edits = () => groups.map(g => ({id:g.id, sms_intro:g.sms_intro, email_intro:g.email_intro,
    recipient_ids:g.recipient_ids, test_contacts:g.test_contacts, schedule_override:g.schedule_override, scenario:g.scenario}));
  const update = (id: string, patch: any) => setGroups(cur => cur.map(g => g.id === id ? {...g, ...patch} : g));
  const selected = groups.reduce((sum, g) => sum + g.recipient_ids.length, 0);
  const immediate = groups.filter(g => g.kind !== "awareness").reduce((sum, g) => sum + g.recipient_ids.length, 0);
  const sent = p?.status === "dispatched";
  const selectedContacts = contacts.filter(c => testIds.includes(c.id));
  const testConfigured = selectedContacts.length > 0 && selectedContacts.every(c => ready[c.channel]);
  return <div className="mx-auto max-w-3xl space-y-5">
    <ol className="flex gap-3 rounded-xl border border-edge p-4 text-sm" aria-label="Alert workflow"><li>✓ 1. Decision</li><li className={!sent ? "font-bold" : ""}>{sent ? "✓" : "→"} 2. Review alerts</li><li className={sent ? "font-bold" : ""}>{sent ? "✓" : ""} 3. Send & done</li></ol>
    {error && <Feedback tone="error" title="Action could not be completed" text={error} />}
    {notice && <Feedback tone={notice.tone} title={notice.tone === "success" ? "Action completed" : "Check delivery results"} text={notice.text} />}
    {busy && <p role="status" className="text-sm text-ink2">Working… Please wait before trying again.</p>}
    {!p && <Card title="Make a decision first"><p>Record the facility decision, then your alerts will appear here automatically.</p>{onBack && <button className={`${button} mt-3`} onClick={onBack}>Go to decision →</button>}</Card>}
    {p && <>
      <Card title={sent ? "Alerts sent · you're done" : "2 · Review your alerts"}>
        <p className="text-lg font-semibold">{p.posture.replaceAll("_", " ")} · {p.decision_day}</p><p className="text-sm text-ink2">{p.facility_name}</p>
        {!sent && <p className="mt-3">{immediate} people alerted immediately · {selected - immediate} receive an update at work start.</p>}
        {sent && <><p className="mt-3">Immediate alerts have been simulated. Later updates are scheduled. No real message was sent by this demo action.</p><button className={`${button} mt-3`} disabled={busy} onClick={() => perform(async () => install(await request(`/packages/${p.id}/followup`, "POST", {version:p.version, actor})), "Follow-up draft created. Review your messages before sending.")}>Write a follow-up</button></>}
      </Card>
      {!sent && <>
        <label className="grid gap-1 text-sm">Your name<input className={input} value={actor} onChange={e => setActor(e.target.value)} /></label>
        {groups.map(g => <Card key={g.id} title={g.title} right={<span className="text-sm">{g.recipient_ids.length} people · {g.kind === "awareness" ? "at work start" : "now"}</span>}>
          <p className="text-sm">{g.instruction}</p>
          <label className="mt-3 grid gap-1 text-sm">Message explanation<textarea className={input} rows={2} value={g.email_intro} onChange={e => update(g.id, {email_intro:e.target.value, sms_intro:e.target.value.slice(0,120)})} /></label>
          <details className="mt-3 text-sm"><summary className="cursor-pointer">Change recipients or view message</summary>
            <label className="mt-2 block"><input type="checkbox" checked={g.recipient_ids.length === g.recipients.length} onChange={e => update(g.id,{recipient_ids:e.target.checked ? g.recipients.map((r:any)=>r.id) : []})} /> Select everyone in this group</label>
            {g.recipients.map((r:any)=><label className="mt-1 block" key={r.id}><input type="checkbox" checked={g.recipient_ids.includes(r.id)} onChange={e=>update(g.id,{recipient_ids:e.target.checked ? [...g.recipient_ids,r.id] : g.recipient_ids.filter((id:string)=>id!==r.id)})} /> {r.name} · {r.channels.join(" + ")}</label>)}
            <p className="mt-3 whitespace-pre-wrap rounded-lg border border-edge p-3">{p.facility_name} · {p.decision_day}: {p.posture.replaceAll("_"," ")}<br />{g.instruction}<br />{g.email_intro}<br />{p.next_update}</p>
          </details>
        </Card>)}
        <button className="w-full rounded-xl bg-[var(--series-1)] px-5 py-4 text-lg font-bold text-white disabled:opacity-40" disabled={busy || actor.trim().length<2 || !selected} onClick={()=>perform(async()=>install(await request(`/packages/${p.id}/review`,"POST",{version:p.version,actor,groups:edits(),approve_and_send:true})), "Approved alerts sent in the simulator; later updates are scheduled. No real email or text was sent.")}>{busy ? "Working…" : `3 · Approve and alert ${selected} people`}</button>
        <p className="text-center text-sm text-muted">Demo delivery. This button approves all reviewed groups and sends them together in the simulator.</p>
      </>}
      <details className="card p-4"><summary className="cursor-pointer font-semibold">Send real test emails / gateway texts</summary>
        <p className="mt-3 text-sm">The SMTP service sends reviewed test messages to the selected email contacts or configured SMS gateway addresses. Messages say TEST ONLY. Employee roster delivery remains simulated.</p>
        <div className="mt-3 rounded-lg border border-edge p-3 text-sm">Email: {ready.email ? "Configured" : "Not configured — add SMTP credentials"}<br />SMS gateway: {ready.sms ? "Configured" : "Add the gateway address supplied by your SMS gateway account"}</div>
        <button className={`${button} mt-3`} disabled={busy} onClick={()=>perform(async()=>{ setSmtpCheck(null); setSmtpCheck(await request('/delivery-setup/check', 'POST', {})); })}>Verify SMTP login · no message sent</button>
        {smtpCheck && <Feedback tone={smtpCheck.status === "authenticated" ? "success" : "error"} title={smtpCheck.status === "authenticated" ? "SMTP login verified" : "SMTP check failed"} text={smtpCheck.detail} />}
        <label className="mt-3 grid gap-1 text-sm">Test message group<select className={input} value={testGroup} onChange={e=>setTestGroup(e.target.value)}>{groups.map(g=><option key={g.id} value={g.id}>{g.title}</option>)}</select></label>
        <div className="mt-3 space-y-2">{contacts.map(c=><label className="block text-sm" key={c.id}><input type="checkbox" checked={testIds.includes(c.id)} onChange={e=>setTestIds(e.target.checked ? [...testIds,c.id] : testIds.filter(id=>id!==c.id))} /> {c.address} · {c.channel}{c.gateway_address ? ` via ${c.gateway_address}` : ""}</label>)}</div>
        <button className={`${button} mt-4`} disabled={busy || !testConfigured || !testGroup || actor.trim().length<2} onClick={()=>perform(async()=>{
          setTestResult(null);
          let pack=p;
          if (p.status==='draft') pack=await request(`/packages/${p.id}/review`,'POST',{version:p.version,actor,groups:edits(),approve_and_send:false});
          if (pack.status === "draft") pack=await request(`/packages/${p.id}/groups/${testGroup}/approve`,'POST',{version:pack.version,actor});
          setP(pack);
          const result=await request(`/packages/${p.id}/real-test`,'POST',{version:pack.version,actor,group_id:testGroup,contact_ids:testIds,request_id:requestId.current});
          setTestResult(result); requestId.current=crypto.randomUUID();
          const accepted = result.messages.filter((m:any)=>m.status === "provider_accepted").length;
          const failed = result.messages.filter((m:any)=>m.status === "provider_rejected").length;
          const unknown = result.messages.length - accepted - failed;
          setNotice({tone: failed || unknown ? "warning" : "success", text: `${accepted} accepted by SMTP · ${failed} rejected · ${unknown} unconfirmed. SMTP acceptance does not confirm inbox or phone delivery. ${unknown ? "Check provider logs before sending another test." : ""}`});
          try { await load(); } catch { setError("The test results are shown below, but refreshing the screen failed. Do not resend just to refresh; reload the page."); }
        })}>Approve and send real test to {testIds.length} contacts</button>
        {testResult?.messages.map((m:any)=><Feedback key={m.contact_id} tone={m.status === "provider_accepted" ? "success" : m.status === "provider_rejected" ? "error" : "warning"} title={`${m.address} · ${m.status === "provider_accepted" ? "Accepted by SMTP" : m.status === "provider_rejected" ? "Rejected" : "Delivery unconfirmed"}`} text={m.detail} />)}
        {!testConfigured && <p className="mt-2 text-sm text-muted">{!testIds.length ? "Select at least one test contact to send." : "Configure SMTP and the gateway for your selected channels before sending."}</p>}
        <details className="mt-4 text-sm"><summary className="cursor-pointer">One-time SMTP email setup</summary><p className="mt-2">Configure SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD and SMTP_FROM in your local .env, then restart the API. Use your sending account’s SMTP host and app password.</p><p className="mt-2">Full instructions: docs/notification-delivery-setup.md. Credentials stay local.</p><button className={`${button} mt-2`} onClick={()=>perform(async()=>setReady(await request('/delivery-setup')), 'Connection settings refreshed. Use Verify SMTP login to check authentication.')}>Check connection settings</button></details>
      </details>
      <details className="card p-4"><summary className="cursor-pointer">Delivery history & advanced tools</summary><div className="mt-4"><NotificationTools /></div></details>
    </>}
  </div>;
}
