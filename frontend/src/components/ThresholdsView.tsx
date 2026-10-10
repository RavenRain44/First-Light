import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Card, PostureBadge, fmtTime } from "../util";

export function ThresholdsView() {
  const [th, setTh] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.thresholds().then(setTh).catch((e) => setErr(e.message)); }, []);
  if (err) return <Card title="Thresholds"><p className="text-sm">{err}</p></Card>;
  if (!th) return <Card title="Thresholds"><div className="h-40 animate-pulse rounded bg-[var(--surface-2)]" /></Card>;
  const hazards = ["winter", "wind", "cold"];
  return (
    <div className="space-y-4">
      <Card title="Backtest: recommendation at 04:00 local on the impact day vs. what happened"
        right={<span className="text-xs text-muted">simulated by rules (backtest), not real USDA decisions</span>}>
        {th.backtest.length === 0 ? <p className="text-sm">No history built yet (python -m scripts.build_history).</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-edge text-left text-xs uppercase text-ink2">
                <th className="py-1">Event</th><th>04:00 recommendation</th><th>First non-normal</th><th>Severe impact observed?</th><th>Verdict</th>
              </tr></thead>
              <tbody>
                {th.backtest.map((b: any) => (
                  <tr key={b.event_id} className="border-b border-edge/50 align-top">
                    <td className="py-1.5 pr-2">{b.name}</td>
                    <td><PostureBadge p={b.at_0400_local.posture} size="sm" /> <span className="text-xs text-muted">{b.at_0400_local.confidence}</span></td>
                    <td className="text-xs tabnum">{b.first_non_normal ? `${fmtTime(b.first_non_normal.as_of, "America/Chicago")}` : "never"}</td>
                    <td>{b.outcome_severe ? <Badge tone="bad">yes</Badge> : <Badge>no</Badge>}</td>
                    <td className="text-xs">{b.verdict}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={`Threshold registry v${th.version}`} right={<span className="text-xs text-muted">sha256 {th.sha256.slice(0, 12)} · {th.unverified_count} of {th.rules.length} not yet verified</span>}>
        <p className="mb-3 text-sm text-ink2">Every cutoff the engine uses, with its anchor and source. Rules marked ⚠ are plausible but not verified against a primary source; they are flagged everywhere they appear.</p>
        {hazards.map((h) => (
          <div key={h} className="mb-4">
            <h3 className="mb-1 font-semibold capitalize">{h === "wind" ? "High wind / severe thunderstorm" : h === "winter" ? "Winter / ice" : "Extreme cold"}</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="border-b border-edge text-left text-xs uppercase text-ink2">
                  <th className="py-1">Rule</th><th>Test</th><th>Level</th><th>Anchor</th><th>Basis</th>
                </tr></thead>
                <tbody>
                  {th.rules.filter((r: any) => r.hazard === h).map((r: any) => (
                    <tr key={r.id} className="border-b border-edge/50 align-top">
                      <td className="py-1.5 pr-2 font-mono text-xs">{r.id}</td>
                      <td className="pr-2 text-xs">{r.metric === "alert_present" ? `NWS ${r.events.join(" / ")} in effect` : `${r.metric} ${r.operator} ${r.value} ${r.unit}`}</td>
                      <td className="pr-2 text-xs">{r.posture_effect}</td>
                      <td className="pr-2 text-xs">{r.anchor} <a className="underline" href={r.source_url} target="_blank" rel="noreferrer">source</a></td>
                      <td className="text-xs">{r.verified ? <Badge tone="good">✓ verified</Badge> : <Badge tone="warn">⚠ unverified</Badge>} <span className="text-muted">{r.basis}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </Card>

      <Card title="Posture timing and OPM mapping">
        <ul className="space-y-1 text-sm">
          {Object.entries(th.timing.posture_matrix).map(([k, v]) => <li key={k}><strong className="capitalize">{k}:</strong> {String(v)}</li>)}
          <li><strong>Combine:</strong> {th.timing.combine}</li>
          <li><strong>Windows:</strong> AM commute {th.timing.am_commute.join("–")}, PM commute {th.timing.pm_commute.join("–")}, morning core ends {th.timing.morning_core_end}, winter road recovery {th.timing.winter_road_recovery_hours} h</li>
        </ul>
        <table className="mt-3 w-full text-sm">
          <tbody>
            {Object.entries(th.postures).filter(([k]) => !k.startsWith("_")).map(([k, v]: any) => (
              <tr key={k} className="border-b border-edge/50"><td className="py-1.5 pr-2"><PostureBadge p={k as any} size="sm" /></td><td className="text-xs">{v.opm_label}</td><td className="text-xs text-muted">{v.opm_section}</td></tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-muted">Source: <a className="underline" href={th.postures._source} target="_blank" rel="noreferrer">{th.postures._source_title}</a></p>
      </Card>
    </div>
  );
}
