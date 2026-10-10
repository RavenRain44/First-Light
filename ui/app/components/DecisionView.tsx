import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, ChevronRight, Clipboard, Clock3, Database, GitCompareArrows, ShieldCheck, Sparkles } from 'lucide-react'
import { age, shortDate } from '../api'
import type { Facility, Posture, Recommendation } from '../types'

interface Props {
  facility?: Facility
  recommendation?: Recommendation
  busy: boolean
  onRefresh: () => void
  onDecide: (action: 'approved' | 'modified' | 'overridden', actor: string, reason?: string, posture?: Posture) => Promise<void>
}

const options: Posture[] = ['NORMAL', 'TELEWORK_OPTION', 'DELAYED_ARRIVAL', 'EARLY_DISMISSAL', 'CLOSED']

function deadlineText(value: string, now: number) {
  const seconds = Math.round((new Date(value).getTime() - now) / 1000)
  if (seconds <= 0) return 'Decision window is open now'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return `${hours ? `${hours}h ` : ''}${minutes}m remaining`
}

export default function DecisionView({ facility, recommendation, busy, onRefresh, onDecide }: Props) {
  const [dialog, setDialog] = useState<'approved' | 'modified' | 'overridden' | null>(null)
  const [actor, setActor] = useState('Morgan Manager')
  const [reason, setReason] = useState('')
  const [posture, setPosture] = useState<Posture>('NORMAL')
  const [copied, setCopied] = useState(false)
  const [clock, setClock] = useState(Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])
  useEffect(() => {
    if (recommendation) setPosture(recommendation.posture)
  }, [recommendation])
  const maxLevel = useMemo(() => Math.max(1, ...(recommendation?.thresholds_crossed.map((item) => item.level) || [1])), [recommendation])
  if (!facility || !recommendation) return <div className="loading-card">Loading decision context…</div>
  const rationale = recommendation.rationale_llm || recommendation.rationale_template

  async function submit() {
    if (!dialog) return
    await onDecide(dialog, actor, reason || undefined, dialog === 'approved' ? undefined : posture)
    setDialog(null)
    setReason('')
  }

  return (
    <section className="page">
      <div className="page-heading split-heading">
        <div>
          <p className="eyebrow">{facility.city}, {facility.state} · {facility.name}</p>
          <h1>Decision briefing</h1>
          <p>As of {shortDate(recommendation.as_of)} · engine {recommendation.engine_version} · registry {recommendation.registry_version}</p>
        </div>
        <button className="button secondary" onClick={onRefresh} disabled={busy}>Refresh this facility</button>
      </div>

      {recommendation.notices.map((notice) => <div className="notice" key={notice}><AlertTriangle size={18} />{notice}</div>)}

      <div className="decision-hero">
        <div className="posture-card">
          <div className="card-label">Engine recommendation</div>
          <div className={`posture posture-${recommendation.posture.toLowerCase()}`}>{recommendation.posture.replaceAll('_', ' ')}</div>
          {recommendation.delay_hours && <p>Delay: {recommendation.delay_hours} hour{recommendation.delay_hours > 1 ? 's' : ''}</p>}
          {recommendation.depart_by && <p>Depart by {shortDate(recommendation.depart_by)}</p>}
          {recommendation.shelter_now && <div className="shelter"><AlertTriangle size={18} /> SHELTER NOW overlay active</div>}
          <div className="deadline"><Clock3 size={17} /><span><strong>{deadlineText(recommendation.decision_deadline, clock)}</strong><small>Last useful decision moment · {shortDate(recommendation.decision_deadline)}</small></span></div>
        </div>
        <div className="confidence-card">
          <div className="confidence-ring"><span>{recommendation.confidence.level}</span><small>confidence</small></div>
          <div className="confidence-parts">
            {Object.entries(recommendation.confidence.components).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{String(value)}</strong></div>)}
          </div>
        </div>
      </div>

      <div className="two-column">
        <div className="card">
          <div className="card-heading"><GitCompareArrows size={18} /><div><h2>Thresholds crossed</h2><p>Observed values against cited policy boundaries.</p></div></div>
          {recommendation.thresholds_crossed.length === 0 ? <div className="empty">No quantitative thresholds crossed.</div> : recommendation.thresholds_crossed.map((item) => (
            <div className="threshold-row" key={item.id}>
              <div className="threshold-copy"><strong>{item.id.replaceAll('_', ' ')}</strong><span>{item.observed} observed · {item.margin}</span></div>
              <div className="threshold-track"><div style={{ width: `${Math.min(100, (item.level / maxLevel) * 100)}%` }} /><i style={{ left: `${Math.min(95, Math.max(10, (item.level / 4) * 100))}%` }} /></div>
              <span className="level-chip">L{item.level}</span>
            </div>
          ))}
        </div>
        <div className="card">
          <div className="card-heading"><ChevronRight size={18} /><div><h2>What would change this</h2><p>Smallest tested moves across a decision boundary.</p></div></div>
          <div className="counterfactual-list">
            {recommendation.what_would_change.map((item, index) => (
              <div className="counterfactual" key={`${item.if}-${index}`}><span>{index + 1}</span><div><p>If {item.if}</p><strong>Then {item.then.replaceAll('_', ' ')}</strong><small>{item.delta}</small></div></div>
            ))}
          </div>
        </div>
      </div>

      <div className="card rationale-card">
        <div className="card-heading"><Sparkles size={18} /><div><h2>Paste-ready rationale</h2><p>{recommendation.rationale_llm ? 'Akamai-hosted draft' : 'Deterministic template fallback'} · {recommendation.rationale_grounded ? 'grounding check passed' : 'fallback used'}</p></div><button className="icon-button" aria-label="Copy rationale" onClick={() => { navigator.clipboard.writeText(rationale); setCopied(true) }}><Clipboard size={17} />{copied && <span>Copied</span>}</button></div>
        <blockquote>{rationale}</blockquote>
      </div>

      <div className="card">
        <div className="card-heading"><Database size={18} /><div><h2>Evidence ledger</h2><p>Every claim links to a captured raw payload.</p></div></div>
        <div className="table-wrap"><table><thead><tr><th>Source</th><th>Issued</th><th>Fetched / age</th><th>Payload</th><th>Status</th></tr></thead><tbody>{recommendation.inputs.map((item) => <tr key={item.id}><td><a href={item.url} target="_blank" rel="noreferrer">{item.source}</a></td><td>{shortDate(item.issued_at)}</td><td>{shortDate(item.fetched_at)}<small>{age(item.fetched_at)}</small></td><td><code>{item.sha256.slice(0, 10)}…</code><small>{item.object_key}</small></td><td><span className={`status-pill ${item.stale ? 'warning' : 'ok'}`}>{item.stale ? 'cached' : 'current'}</span></td></tr>)}</tbody></table></div>
      </div>

      <div className="decision-bar">
        <div><ShieldCheck size={22} /><span><strong>The decision is still human.</strong><small>Nothing reaches employees until you approve.</small></span></div>
        <div className="action-row"><button className="button secondary" onClick={() => setDialog('modified')}>Modify</button><button className="button danger-ghost" onClick={() => setDialog('overridden')}>Override</button><button className="button primary" onClick={() => setDialog('approved')}><Check size={16} />Approve recommendation</button></div>
      </div>

      {dialog && <div className="dialog-backdrop" role="presentation" onMouseDown={() => setDialog(null)}><div className="dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><p className="eyebrow">Human action</p><h2>{dialog === 'approved' ? 'Approve recommendation' : dialog === 'modified' ? 'Modify posture' : 'Override engine'}</h2><label>Decision-maker<input value={actor} onChange={(event) => setActor(event.target.value)} /></label>{dialog !== 'approved' && <label>Selected posture<select value={posture} onChange={(event) => setPosture(event.target.value as Posture)}>{options.map((item) => <option key={item}>{item}</option>)}</select></label>}<label>{dialog === 'overridden' ? 'Reason (required)' : 'Decision note'}<textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Record the operational context behind this choice." /></label><div className="dialog-actions"><button className="button secondary" onClick={() => setDialog(null)}>Cancel</button><button className="button primary" disabled={!actor || (dialog === 'overridden' && !reason.trim())} onClick={submit}>Create signed record</button></div></div></div>}
    </section>
  )
}
