import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Snapshot } from "../types";
import { Badge, Card, ago, fmtTime } from "../util";

const SEV_TONE: Record<string, "bad" | "warn" | "neutral"> = { Extreme: "bad", Severe: "bad", Moderate: "warn" };

export function LiveCheckPanel({ onSnapshot, busy, setBusy }: { onSnapshot: (s: Snapshot) => void; busy: boolean; setBusy: (b: boolean) => void }) {
  const [list, setList] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [handledOnly, setHandledOnly] = useState(true);
  const [assumeWorkday, setAssumeWorkday] = useState(true);
  const [picked, setPicked] = useState<string | null>(null);
  const [result, setResult] = useState<Snapshot | null>(null);

  const load = () => { setErr(null); api.liveAlerts().then(setList).catch((e) => setErr(e.message)); };
  useEffect(load, []);

  const alerts = useMemo(() => (list?.alerts ?? []).filter((a: any) =>
    (!handledOnly || a.handled_hazard) && (`${a.event} ${a.areaDesc}`.toLowerCase().includes(q.toLowerCase()))), [list, q, handledOnly]);

  const run = async (id: string) => {
    setPicked(id); setBusy(true); setErr(null);
    try { const s = await api.liveEvaluate(id, assumeWorkday); setResult(s); onSnapshot(s); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Card title="Live Check: run the engine on a real active NWS alert anywhere in the US"
      right={list && <span className="text-xs text-muted">{list.count} land alerts · fetched {ago(list.fetched_at)} · <button className="underline" onClick={load}>refresh</button></span>}>
      <div role="note" className="mb-4 rounded-xl border border-dashed border-[var(--accent)] bg-[var(--tint)] p-3 text-sm">
        <strong>What-if, outside Iowa scope; NWS-only data, lower confidence.</strong> A hypothetical copy of the Ames facility is placed at the
        alert's location. Iowa-only sources (ASOS obs via IEM, Iowa DOT roads, RWIS) show as unavailable, which lowers confidence. Always live, even in demo mode.
      </div>
      <div className="mb-2 flex flex-wrap items-center gap-3 text-sm">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by event or area" className="rounded-md border border-edge bg-surface px-2 py-1" />
        <label className="flex items-center gap-1"><input type="checkbox" checked={handledOnly} onChange={(e) => setHandledOnly(e.target.checked)} /> winter / wind / cold only</label>
        <label className="flex items-center gap-1" title="Weekends and evenings otherwise push the decision to the next workday">
          <input type="checkbox" checked={assumeWorkday} onChange={(e) => setAssumeWorkday(e.target.checked)} /> treat today as a workday
        </label>
      </div>
      {err && <p className="mb-2 text-sm text-[var(--danger)]">{err}</p>}
      {!list && !err && <div className="h-40 animate-pulse rounded bg-[var(--surface-2)]" />}
      {list && (
        <div className="max-h-80 overflow-auto rounded-md border border-edge">
          {alerts.length === 0 && <p className="p-3 text-sm text-ink2">No matching active alerts right now.</p>}
          <ul>
            {alerts.map((a: any) => (
              <li key={a.id} className={`flex flex-wrap items-center justify-between gap-2 border-b border-edge px-3 py-2 text-sm ${picked === a.id ? "bg-[var(--surface-2)]" : ""}`}>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{a.event}</span>
                    <Badge tone={SEV_TONE[a.severity] ?? "neutral"}>{a.severity}</Badge>
                    <Badge>{a.certainty}</Badge>
                  </div>
                  <p className="truncate text-xs text-ink2" title={a.areaDesc}>{a.areaDesc}</p>
                  <p className="text-xs text-muted tabnum">{fmtTime(a.onset, "UTC")} → {fmtTime(a.ends ?? a.expires, "UTC")} · {a.senderName}</p>
                </div>
                <button onClick={() => run(a.id)} disabled={busy} className="btn btn-primary !py-1 !text-xs">
                  {busy && picked === a.id ? "Evaluating…" : "Evaluate here"}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {result?.livecheck && (
        <p className="mt-2 text-sm">Evaluated <strong>{result.livecheck.event}</strong> near <strong>{result.livecheck.place}</strong> ({result.facility.timezone}).
          Results below are for the hypothetical facility.</p>
      )}
    </Card>
  );
}
