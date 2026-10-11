import { useEffect, useState } from "react";
import { api } from "../api";
import type { Decision } from "../types";
import { Card, Skeleton } from "../util";
import { NotificationsView } from "./NotificationsView";

export function DecisionLogView({ timezone, onSnapshot }: {
  timezone: string; onSnapshot: (id: string, decisionId: number) => void;
}) {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError("");
    api.decisions().then(rows => {
      if (active) setDecisions([...rows].sort((a, b) => b.decided_at.localeCompare(a.decided_at)));
    }).catch(e => { if (active) setError(e.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [refresh]);
  if (selected !== null) return <div className="space-y-4">
    <button className="btn" onClick={() => setSelected(null)}>← Back to decision log</button>
    <NotificationsView key={selected} decisionId={selected} onBack={() => setSelected(null)} />
  </div>;
  return <Card title="Decision log">
    <p className="text-sm text-muted">Review recorded decisions and the weather saved when each decision was made.</p>
    {loading && <Skeleton className="mt-3 h-40" />}
    {error && <div role="alert" className="mt-3 text-sm">Could not load decisions: {error} <button className="btn" onClick={() => setRefresh(n => n + 1)}>Retry</button></div>}
    {!loading && !error && decisions.length === 0 && <p className="mt-3 text-sm">No decisions recorded yet. Record your first decision in Notify staff.</p>}
    <ul className="mt-3 space-y-3">{decisions.map(d => <li key={d.id} className="rounded-lg border border-edge p-3 text-sm">
      <strong>Decision #{d.id} · {d.decision_posture.replaceAll("_", " ")}</strong>
      <p className="mt-1 text-ink2">{d.decided_by} · {new Intl.DateTimeFormat("en-US", {timeZone: timezone, dateStyle: "medium", timeStyle: "short"}).format(new Date(d.decided_at))} · {timezone}</p>
      <p className="mt-1">{d.override_reason || d.notes || "Manager confirmed the assessment."}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn" onClick={() => setSelected(d.id)}>Review decision & alerts</button>
        <button className="btn" onClick={() => onSnapshot(d.snapshot_id, d.id)}>View saved weather & cameras</button>
      </div>
    </li>)}</ul>
  </Card>;
}
