import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Card, Skeleton } from "../util";

async function request(path: string, method = "GET", body?: unknown): Promise<any> {
  const r = await fetch(`/api/notifications${path}`, { method, headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await r.json();
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  return data;
}
const input = "min-w-0 max-w-full rounded-lg border border-edge bg-surface px-2 py-1";
const button = "btn";
const time = (t: string, tz: string) => new Intl.DateTimeFormat("en-US", { timeZone: tz, dateStyle: "medium", timeStyle: "short" }).format(new Date(t));

function Feedback({tone, title, text}: {tone: "success" | "warning" | "error"; title: string; text: string}) {
  // Blue/white theme: success = accent, warning = mid blue, errors keep the reserved warm --danger.
  const color = tone === "error" ? "var(--danger)" : tone === "warning" ? "var(--b3)" : "var(--accent)";
  return <div role={tone === "error" ? "alert" : "status"} className="cc-rise mt-3 rounded-xl border-l-4 bg-surface p-3 text-sm" style={{borderColor: color}}>
    <p className="font-semibold">{tone === "success" ? "✓ " : tone === "error" ? "✕ " : "! "}{title}</p>
    <p className="mt-1 whitespace-pre-wrap">{text}</p>
  </div>;
}

/** Counts of people and messages for the selected recipients of some groups. */
function tally(groups: any[]) {
  let people = 0, sms = 0, email = 0, now = 0, later = 0, access = 0;
  for (const g of groups) {
    for (const r of g.recipients) {
      if (!g.recipient_ids.includes(r.id)) continue;
      people += 1;
      if (r.channels.includes("sms")) sms += 1;
      if (r.channels.includes("email")) email += 1;
      if (g.kind === "awareness") later += 1; else now += 1;
      if (r.accessibility_followup) access += 1;
    }
  }
  return { people, sms, email, messages: sms + email, now, later, access };
}

function Stat({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-xl bg-[var(--surface-2)] px-4 py-3">
      <p className="text-xs font-medium uppercase tracking-[0.06em] text-muted">{label}</p>
      <p className="tabnum mt-0.5 text-2xl font-semibold">{value}</p>
      {hint && <p className="text-xs text-ink2">{hint}</p>}
    </div>
  );
}

function ChannelPills({ channels }: { channels: string[] }) {
  return <span className="inline-flex gap-1">{channels.map((c) => (
    <span key={c} className="rounded-full bg-[var(--tint)] px-1.5 py-0.5 text-[10px] font-semibold uppercase text-[var(--accent)]">{c}</span>
  ))}</span>;
}

/** Shared message, group-specific instructions, and one recipient list. */
function MessageComposer({ groups, p, update }: { groups: any[]; p: any; update: (id: string, patch: any) => void }) {
  const [q, setQ] = useState("");
  if (!groups.length) return <p className="text-sm">No recipient groups for this decision.</p>;
  const first = groups[0];
  const selected = groups.reduce((n,g)=>n + g.recipient_ids.length,0);
  const total = groups.reduce((n,g)=>n + g.recipients.length,0);
  const rows = groups.flatMap(g=>g.recipients.map((r:any)=>({...r, group:g}))).filter(r=>`${r.name} ${r.job_role ?? ''} ${r.division ?? ''} ${r.group.title}`.toLowerCase().includes(q.toLowerCase()));
  return <section className="card p-5 space-y-4">
    <details open>
      <summary className="cursor-pointer font-semibold">Message preview · edit directly</summary>
      <p className="mt-2 text-xs text-muted">{p.draft_source}. Location and decision are shared by everyone. Only personal instructions vary by group.</p>
      <div className="mt-4 space-y-4">
        <label className="grid gap-2 text-sm font-semibold">1 · Location<textarea className={`${input} font-normal`} rows={2} maxLength={300} value={first.location_text} onChange={e=>update(first.id,{location_text:e.target.value})} /></label>
        <label className="grid gap-2 text-sm font-semibold">2 · Decision<textarea className={`${input} font-normal`} rows={2} maxLength={1000} value={first.decision_text} onChange={e=>update(first.id,{decision_text:e.target.value})} /></label>
        <section className="rounded-xl border border-edge p-4">
          <h3 className="text-sm font-semibold">3 · Personal instructions</h3>
          <div className="mt-3 space-y-4">{groups.map(g=><label className="grid gap-2 text-sm" key={g.id}>
            <span className="flex flex-wrap justify-between gap-2"><strong>{g.title}</strong><span className="text-xs text-muted">{g.recipient_ids.length} people · {g.kind === 'awareness' ? 'at work start' : 'now'}</span></span>
            <textarea aria-label={`Instructions for ${g.title}`} className={input} rows={2} maxLength={1000} value={g.instruction_text} onChange={e=>update(g.id,{instruction_text:e.target.value})} />
            {g.instruction_text !== g.instruction && <span className="text-xs text-muted">Manager override · logged when saved</span>}
          </label>)}</div>
        </section>
      </div>
      <button className={`${button} mt-3`} onClick={()=>groups.forEach(g=>update(g.id,g.template))}>Use template text</button>
      <p className="mt-2 text-xs text-muted">Each recipient receives the shared location and decision followed by their group’s instructions. Edits require fresh approval.</p>
    </details>
    <details>
      <summary className="cursor-pointer font-semibold">Recipients · {selected} of {total} selected · all groups</summary>
      <div className="mt-3 flex flex-wrap justify-between gap-2">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selected === total} onChange={e=>groups.forEach(g=>update(g.id,{recipient_ids:e.target.checked ? g.recipients.map((r:any)=>r.id) : []}))} /> Select everyone</label>
        <input aria-label="Search all recipients" className={input} placeholder="Search name, role or group" value={q} onChange={e=>setQ(e.target.value)} />
      </div>
      <div className="mt-3 max-h-80 overflow-auto rounded-xl border border-edge">
        <table className="w-full text-left text-xs"><thead className="sticky top-0 bg-[var(--surface-2)]"><tr><th className="p-2">Include</th><th className="p-2">Name</th><th className="p-2">Group</th><th className="p-2">Channels</th><th className="p-2">Sends</th></tr></thead>
          <tbody>{rows.map(r=><tr key={`${r.group.id}:${r.id}`} className="border-t border-edge"><td className="p-2"><input aria-label={`Include ${r.name}`} type="checkbox" checked={r.group.recipient_ids.includes(r.id)} onChange={e=>update(r.group.id,{recipient_ids:e.target.checked ? [...r.group.recipient_ids,r.id] : r.group.recipient_ids.filter((id:string)=>id!==r.id)})} /></td><td className="p-2">{r.name}<span className="block text-muted">{r.job_role ?? ''}</span>{r.accessibility_followup && <span>Accessibility follow-up</span>}</td><td className="p-2">{r.group.title}</td><td className="p-2"><ChannelPills channels={r.channels} /></td><td className="p-2">{time(r.due_at,p.timezone)}</td></tr>)}{!rows.length && <tr><td colSpan={5} className="p-3">No matching recipients.</td></tr>}</tbody>
        </table>
      </div>
    </details>
  </section>;
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
    setP(pack); setGroups(pack.groups.map((g: any) => ({ ...g,
      location_text: g.location_text ?? `${pack.facility_name} · ${pack.decision_day} (${pack.timezone})`,
      decision_text: g.decision_text ?? `The manager recorded ${pack.posture.replaceAll('_',' ').toLowerCase()}: ${g.email_intro}`,
      instruction_text: g.instruction_text ?? g.instruction,
      template: g.template ?? {location_text: `${pack.facility_name} · ${pack.decision_day} (${pack.timezone})`, decision_text: `The manager recorded ${pack.posture.replaceAll('_',' ').toLowerCase()} following the weather assessment.`, instruction_text: g.instruction},
      recipient_ids: g.recipient_ids ?? g.recipients.map((r: any) => r.id) })));
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
  const edits = () => groups.map(g => ({id:g.id, location_text:g.location_text, decision_text:g.decision_text, instruction_text:g.instruction_text, sms_intro:g.sms_intro, email_intro:g.email_intro,
    recipient_ids:g.recipient_ids, test_contacts:g.test_contacts, schedule_override:g.schedule_override, scenario:g.scenario}));
  const update = (id: string, patch: any) => setGroups(cur => cur.map(g => g.id === id ? {...g, ...patch} : {...g, ...(patch.location_text !== undefined ? {location_text:patch.location_text} : {}), ...(patch.decision_text !== undefined ? {decision_text:patch.decision_text} : {})}));
  const t = tally(groups);
  const sent = p?.status === "dispatched";
  const selectedContacts = contacts.filter(c => testIds.includes(c.id));
  const testConfigured = selectedContacts.length > 0 && selectedContacts.every(c => ready[c.channel]);
  const excludedByReason: [string, number][] = Object.entries((p?.excluded ?? []).reduce((acc: Record<string, number>, r: any) => {
    acc[r.reason] = (acc[r.reason] ?? 0) + 1; return acc;
  }, {})).sort((a: any, b: any) => b[1] - a[1]) as [string, number][];
  const msgCount = (st: string[]) => (p?.messages ?? []).filter((m: any) => st.includes(m.status)).length;

  return <div className="mx-auto max-w-5xl space-y-5">
    <ol className="card flex flex-wrap gap-6 p-4 text-sm" aria-label="Alert workflow">
      <li className="flex items-center gap-2 text-ink">✓ 1. Decision</li>
      <li className={`flex items-center gap-2 ${!sent ? "font-semibold text-[var(--accent)]" : "text-ink"}`}>{sent ? "✓" : "→"} 2. Review alerts</li>
      <li className={`flex items-center gap-2 ${sent ? "font-semibold text-[var(--accent)]" : "text-muted"}`}>{sent ? "✓" : ""} 3. Send & done</li>
      <li className="ml-auto"><span className="rounded-full bg-[var(--tint)] px-2 py-0.5 text-xs font-semibold text-[var(--accent)]">SIMULATION · synthetic roster</span></li>
    </ol>
    {error && <Feedback tone="error" title="Action could not be completed" text={error} />}
    {notice && <Feedback tone={notice.tone} title={notice.tone === "success" ? "Action completed" : "Check delivery results"} text={notice.text} />}
    {busy && !p && <div className="space-y-4"><Skeleton className="h-40" /><Skeleton className="h-64" /></div>}
    {busy && p && <p role="status" className="cc-fade rounded-lg bg-[var(--tint)] px-3 py-2 text-sm text-[var(--accent)]">Working… Please wait before trying again.</p>}
    {!p && !busy && <Card title="Make a decision first"><p>Record the facility decision, then your alerts will appear here automatically.</p>{onBack && <button className={`${button} mt-3`} onClick={onBack}>Go to decision →</button>}</Card>}
    {p && <>
      <fieldset disabled={busy || sent}><MessageComposer groups={groups} p={p} update={update} /></fieldset>
      <Card title={sent ? "Alerts sent · you're done" : "2 · Review your alerts"}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <p className="text-xl font-semibold">{p.posture.replaceAll("_", " ")} · {p.decision_day}</p>
            <p className="text-sm text-ink2">{p.facility_name}</p>
          </div>
          <p className="text-xs text-muted">Decision #{p.decision_id} · {p.draft_source}</p>
        </div>
        {!sent ? (
          <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="People notified" value={t.people} hint={`${t.now} now · ${t.later} at work start`} />
            <Stat label="Text messages" value={t.sms} />
            <Stat label="Emails" value={t.email} />
            <Stat label="Total messages" value={t.messages} hint={t.access ? `${t.access} need accessibility follow-up` : undefined} />
          </div>
        ) : (
          <>
            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="Delivered (simulated)" value={msgCount(["simulated_sent"])} />
              <Stat label="Scheduled" value={msgCount(["scheduled", "queued", "delayed"])} hint="updates at work start" />
              <Stat label="Failed (simulated)" value={msgCount(["simulated_failed"])} />
              <Stat label="Total messages" value={(p.messages ?? []).length} />
            </div>
            <p className="mt-3 text-sm text-ink2">Immediate alerts were delivered in the simulator; later updates are scheduled. Nothing reached a real phone or mailbox.</p>
            <button className={`${button} mt-3`} disabled={busy} onClick={() => perform(async () => install(await request(`/packages/${p.id}/followup`, "POST", {version:p.version, actor})), "Follow-up draft created. Review your messages before sending.")}>Write a follow-up</button>
          </>
        )}
        {excludedByReason.length > 0 && (
          <details className="mt-4 text-sm">
            <summary className="cursor-pointer text-ink2"><strong className="tabnum">{p.excluded.length}</strong> people not notified</summary>
            <ul className="mt-2 grid gap-1 sm:grid-cols-2">
              {excludedByReason.map(([reason, n]) => (
                <li key={reason} className="flex items-center justify-between gap-2 rounded-lg bg-[var(--surface-2)] px-3 py-1.5 text-xs">
                  <span>{reason}</span><strong className="tabnum">{n}</strong>
                </li>
              ))}
            </ul>
          </details>
        )}
      </Card>
      {!sent && <label className="grid max-w-sm gap-1 text-sm">Your name<input className={input} value={actor} onChange={e => setActor(e.target.value)} /></label>}
      {!sent && <>
        <button className="btn btn-primary w-full !rounded-xl !py-4 !text-lg" disabled={busy || actor.trim().length<2 || !t.people} onClick={()=>perform(async()=>install(await request(`/packages/${p.id}/review`,"POST",{version:p.version,actor,groups:edits(),approve_and_send:true})), "Approved alerts sent in the simulator; later updates are scheduled. No real email or text was sent.")}>
          {busy ? "Working…" : `3 · Approve and alert ${t.people} people · ${t.messages} messages`}
        </button>
        <p className="text-center text-sm text-muted">Simulated delivery. Approves every reviewed group and sends them together in the simulator.</p>
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
    </>}
  </div>;
}
