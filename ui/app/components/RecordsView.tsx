import { useMemo, useState } from 'react'
import { CheckCircle2, Clock, Download, Fingerprint, ShieldCheck } from 'lucide-react'
import { shortDate } from '../api'
import type { DecisionRecord } from '../types'

interface Props {
  records: DecisionRecord[]
  verification: { intact: boolean; records_checked: number; message: string }
}

export default function RecordsView({ records, verification }: Props) {
  const [index, setIndex] = useState(Math.max(0, records.length - 1))
  const current = records[Math.min(index, Math.max(0, records.length - 1))]
  const evidenceCount = useMemo(() => current?.recommendation.inputs.length || 0, [current])
  return (
    <section className="page">
      <div className="page-heading split-heading"><div><p className="eyebrow">Append-only audit trail</p><h1>Decision record</h1><p>Reconstruct what the manager knew—not what became obvious later.</p></div><a className="button secondary" href="/api/records/export"><Download size={16} />Export JSONL</a></div>
      <div className={`integrity-banner ${verification.intact ? 'intact' : 'broken'}`}><ShieldCheck size={28} /><div><strong>{verification.intact ? 'Chain intact' : 'Integrity failure'}</strong><p>{verification.message}</p></div><span>{verification.records_checked} verified</span></div>
      {records.length === 0 ? <div className="empty-state"><Fingerprint size={42} /><h2>No signed decisions yet</h2><p>Approve a recommendation to create the genesis record. Previewing never writes to the chain.</p></div> : <>
        <div className="time-travel card"><div className="card-heading"><Clock size={18} /><div><h2>Time travel</h2><p>Slide to a record to see the exact immutable snapshot.</p></div></div><input type="range" min="0" max={records.length - 1} value={Math.min(index, records.length - 1)} onChange={(event) => setIndex(Number(event.target.value))} /><div className="time-labels"><span>Genesis</span><strong>{shortDate(current.created_at)}</strong><span>Latest</span></div></div>
        <div className="record-grid">
          <div className="card record-detail"><div className="record-sequence">#{current.sequence}</div><p className="eyebrow">{current.human_action}</p><h2>{current.recommendation.posture.replaceAll('_', ' ')}</h2><dl><div><dt>Decision-maker</dt><dd>{current.actor}</dd></div><div><dt>Created</dt><dd>{shortDate(current.created_at)}</dd></div><div><dt>Evidence inputs</dt><dd>{evidenceCount}</dd></div><div><dt>Engine</dt><dd>{current.recommendation.engine_version}</dd></div>{current.reason && <div><dt>Recorded reason</dt><dd>{current.reason}</dd></div>}</dl></div>
          <div className="card hash-card"><Fingerprint size={25} /><h2>Cryptographic link</h2><p>Each hash covers canonical record JSON plus the prior hash. Changing one byte breaks verification from that point forward.</p><label>Record hash<code>{current.hash}</code></label><label>Previous hash<code>{current.prev_hash}</code></label><div className="verified-line"><CheckCircle2 size={17} /> Recomputed and verified</div></div>
        </div>
        <div className="timeline">{records.map((record, recordIndex) => <button key={record.id} className={recordIndex === index ? 'active' : ''} onClick={() => setIndex(recordIndex)}><span>{record.sequence}</span><div><strong>{record.recommendation.posture.replaceAll('_', ' ')}</strong><small>{record.actor} · {shortDate(record.created_at)}</small></div></button>)}</div>
      </>}
    </section>
  )
}
