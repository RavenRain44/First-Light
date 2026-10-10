import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Mail, MessageSquare, Phone, Radio, Send, Users } from 'lucide-react'
import { shortDate } from '../api'
import type { NotificationPackage, Recipient } from '../types'

interface Props {
  preview?: NotificationPackage
  approvedPackage?: NotificationPackage
  events: Array<{ recipient_id: string; channel: string; status: string; occurred_at: string; detail: string }>
  onSend: () => Promise<void>
  onAck: (employeeId: string) => Promise<void>
  onEscalate: () => Promise<void>
}

const channelIcons: Record<string, typeof Mail> = { email: Mail, sms: MessageSquare, voice: Phone, push: Radio }

export default function NotificationView({ preview, approvedPackage, events, onSend, onAck, onEscalate }: Props) {
  const packageToShow = approvedPackage || preview
  const [selectedId, setSelectedId] = useState<string>('')
  useEffect(() => {
    const first = packageToShow?.recipients.find((item) => item.included)
    if (first) setSelectedId(first.employee_id)
  }, [packageToShow])
  const selected = packageToShow?.recipients.find((item) => item.employee_id === selectedId)
  const counts = useMemo(() => ({
    included: packageToShow?.recipients.filter((item) => item.included).length || 0,
    excluded: packageToShow?.recipients.filter((item) => !item.included).length || 0,
    acknowledged: new Set(events.filter((item) => item.status === 'acknowledged').map((item) => item.recipient_id)).size,
  }), [packageToShow, events])
  if (!packageToShow) return <div className="loading-card">Resolving the synthetic roster…</div>

  return (
    <section className="page">
      <div className="page-heading split-heading"><div><p className="eyebrow">Human-approved package</p><h1>Notification routing</h1><p>Every person is accounted for—even when the right action is exclusion.</p></div>{approvedPackage ? <button className="button primary" onClick={onSend}><Send size={16} />Simulate send</button> : <div className="approval-needed">Approve a decision before send</div>}</div>
      <div className="stat-strip"><div><Users /><span><strong>{counts.included}</strong>included</span></div><div><Users /><span><strong>{counts.excluded}</strong>excluded with reason</span></div><div><CheckCircle2 /><span><strong>{counts.acknowledged}</strong>acknowledged</span></div><div><Radio /><span><strong>{packageToShow.urgency.replaceAll('_', ' ')}</strong>urgency</span></div></div>

      <div className="notification-layout">
        <div className="card roster-card">
          <div className="card-heading"><Users size={18} /><div><h2>Recipient resolution</h2><p>Rules applied in deterministic order.</p></div><span className={`status-pill ${packageToShow.checklist_valid ? 'ok' : 'warning'}`}>{packageToShow.checklist_valid ? 'content checks passed' : 'check failed'}</span></div>
          <div className="table-wrap"><table className="roster-table"><thead><tr><th>Person</th><th>Decision</th><th>Variant</th><th>Route / send time</th></tr></thead><tbody>{packageToShow.recipients.map((recipient) => <RecipientRow key={recipient.employee_id} recipient={recipient} selected={recipient.employee_id === selectedId} onSelect={() => setSelectedId(recipient.employee_id)} />)}</tbody></table></div>
        </div>
        <aside className="phone-column">
          <div className="phone-preview">
            <div className="phone-top"><i /><span>FirstLight simulator</span><i /></div>
            <div className="phone-body">
              <small>Messages · now</small>
              <div className="message-bubble">{selected?.message_sms || 'Select an included employee to preview the routed message.'}</div>
              {selected && <><div className="preview-meta"><strong>{selected.employee_name}</strong><span>{selected.variant.replaceAll('_', ' ')}</span></div><div className="channel-row">{selected.channels.map((channel) => { const Icon = channelIcons[channel] || Radio; return <span key={channel}><Icon size={14} />{channel}</span> })}</div></>}
            </div>
          </div>
          {selected && events.some((item) => item.recipient_id === selected.employee_id) && !events.some((item) => item.recipient_id === selected.employee_id && item.status === 'acknowledged') && <button className="button secondary wide" onClick={() => onAck(selected.employee_id)}>Simulate reply 1</button>}
          <div className="ack-list"><h3>Delivery & acknowledgments</h3>{events.length === 0 ? <p>No simulated delivery events yet.</p> : events.slice().reverse().slice(0, 10).map((event, index) => <div key={`${event.recipient_id}-${event.channel}-${index}`}><span className={`event-dot ${event.status}`} /><span><strong>{event.recipient_id}</strong><small>{event.channel} · {event.status} · {shortDate(event.occurred_at)}</small></span></div>)}{events.length > 0 && <button className="button secondary wide" onClick={onEscalate}>Run escalation check</button>}</div>
        </aside>
      </div>
    </section>
  )
}

function RecipientRow({ recipient, selected, onSelect }: { recipient: Recipient; selected: boolean; onSelect: () => void }) {
  return <tr className={`${recipient.included ? '' : 'excluded'} ${selected ? 'selected' : ''}`} onClick={recipient.included ? onSelect : undefined}><td><strong>{recipient.employee_name}</strong><small>{recipient.employee_id}</small></td><td><span className={`include-badge ${recipient.included ? 'yes' : 'no'}`}>{recipient.included ? 'Include' : 'Exclude'}</span><small>{recipient.reason}</small></td><td>{recipient.variant.replaceAll('_', ' ')}</td><td>{recipient.channels.join(' · ') || '—'}<small>{recipient.send_at ? shortDate(recipient.send_at) : 'No send'}</small></td></tr>
}
