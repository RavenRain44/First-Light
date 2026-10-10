import { useEffect, useMemo, useState } from 'react'
import { ExternalLink, Scale, ShieldAlert } from 'lucide-react'
import { api } from '../api'
import type { Threshold } from '../types'

interface Props { version: string; thresholds: Threshold[] }

export default function ThresholdsView({ version, thresholds }: Props) {
  const metrics = useMemo(() => [...new Set(thresholds.filter((item) => typeof item.value === 'number').map((item) => item.metric))], [thresholds])
  const [metric, setMetric] = useState('ice_accumulation_in')
  const [points, setPoints] = useState<Array<{ value: number; level: number }>>([])
  useEffect(() => { api<{ points: Array<{ value: number; level: number }> }>(`/thresholds/sensitivity?metric=${metric}`).then((value) => setPoints(value.points)).catch(() => setPoints([])) }, [metric])
  return (
    <section className="page">
      <div className="page-heading"><p className="eyebrow">Defensibility registry · {version}</p><h1>Thresholds with receipts</h1><p>Definitions are sourced. Operational assumptions are plainly marked for USDA safety or continuity sign-off.</p></div>
      <div className="notice warning"><ShieldAlert size={18} /><strong>{thresholds.filter((item) => item.requires_signoff).length} policy assumptions require sign-off.</strong> These are prototype hypotheses, not official USDA policy.</div>
      <div className="card sensitivity-card"><div className="card-heading"><Scale size={18} /><div><h2>Sensitivity sweep</h2><p>See exactly where the engine’s severity level changes.</p></div><select value={metric} onChange={(event) => setMetric(event.target.value)}>{metrics.map((item) => <option key={item}>{item}</option>)}</select></div><div className="sensitivity-chart">{points.map((point) => <div key={point.value} title={`${point.value}: level ${point.level}`}><i style={{ height: `${Math.max(4, point.level * 22)}%` }} /><small>{point.value}</small></div>)}</div></div>
      <div className="threshold-grid">{thresholds.map((item) => <article className="threshold-card" id={item.id} key={item.id}><div><span className={`source-tag ${item.source_type}`}>{item.source_type.replaceAll('_', ' ')}</span>{item.requires_signoff && <span className="signoff-tag">sign-off required</span>}</div><h2>{item.id.replaceAll('_', ' ')}</h2><div className="trigger"><strong>{item.value}</strong><span>{item.unit}<small>level {item.level}{item.posture_floor ? ` · floor ${item.posture_floor.replaceAll('_', ' ')}` : ''}</small></span></div><p>{item.quote_or_summary}</p><a href={item.source_url} target="_blank" rel="noreferrer">Primary source <ExternalLink size={13} /></a><footer>Retrieved {item.retrieved_at} · {item.verified_by}</footer></article>)}</div>
    </section>
  )
}
