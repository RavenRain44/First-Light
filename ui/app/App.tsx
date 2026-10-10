import { useCallback, useEffect, useState } from 'react'
import { BellRing, Bot, ClipboardCheck, CloudSun, Database, Gauge, Menu, RadioTower, X } from 'lucide-react'
import type { FeatureCollection } from 'geojson'
import { api, post } from './api'
import AnalystPanel from './components/AnalystPanel'
import DecisionView from './components/DecisionView'
import NotificationView from './components/NotificationView'
import RecordsView from './components/RecordsView'
import SituationBoard from './components/SituationBoard'
import ThresholdsView from './components/ThresholdsView'
import type { DecisionRecord, Facility, NotificationPackage, Posture, Recommendation, Threshold } from './types'

type Tab = 'situation' | 'decision' | 'notifications' | 'records' | 'thresholds' | 'analyst'

const nav: Array<{ id: Tab; label: string; icon: typeof CloudSun }> = [
  { id: 'situation', label: 'Situation', icon: CloudSun },
  { id: 'decision', label: 'Decision', icon: ClipboardCheck },
  { id: 'notifications', label: 'Notify', icon: BellRing },
  { id: 'records', label: 'Record', icon: Database },
  { id: 'thresholds', label: 'Thresholds', icon: Gauge },
  { id: 'analyst', label: 'Analyst', icon: Bot },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('situation')
  const [mobileNav, setMobileNav] = useState(false)
  const [facilities, setFacilities] = useState<Facility[]>([])
  const [selectedId, setSelectedId] = useState('ia-des-moines')
  const [recommendation, setRecommendation] = useState<Recommendation>()
  const [preview, setPreview] = useState<NotificationPackage>()
  const [approvedPackage, setApprovedPackage] = useState<NotificationPackage>()
  const [events, setEvents] = useState<Array<{ recipient_id: string; channel: string; status: string; occurred_at: string; detail: string }>>([])
  const [records, setRecords] = useState<DecisionRecord[]>([])
  const [verification, setVerification] = useState({ intact: true, records_checked: 0, message: 'Chain intact across 0 records.' })
  const [thresholds, setThresholds] = useState<{ version: string; thresholds: Threshold[] }>({ version: '', thresholds: [] })
  const [alerts, setAlerts] = useState<FeatureCollection | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')

  const selected = facilities.find((item) => item.id === selectedId)

  const loadCore = useCallback(async () => {
    try {
      const [facilityData, thresholdData, recordData, chainData] = await Promise.all([
        api<Facility[]>('/facilities'),
        api<{ version: string; thresholds: Threshold[] }>('/thresholds'),
        api<DecisionRecord[]>('/records'),
        api<typeof verification>('/records/verify'),
      ])
      setFacilities(facilityData)
      setThresholds(thresholdData)
      setRecords(recordData)
      setVerification(chainData)
    } catch (caught) { setError((caught as Error).message) }
  }, [])

  const loadFacility = useCallback(async (facilityId: string) => {
    setError('')
    try {
      const [result, notification] = await Promise.all([
        api<Recommendation>(`/facilities/${facilityId}/recommendation`),
        api<NotificationPackage>(`/facilities/${facilityId}/notifications/preview`),
      ])
      setRecommendation(result)
      setPreview(notification)
    } catch (caught) { setError((caught as Error).message) }
  }, [])

  useEffect(() => {
    void loadCore()
    api<FeatureCollection>('/alerts/active').then(setAlerts).catch((caught) => setError((caught as Error).message))
  }, [loadCore])

  useEffect(() => {
    setApprovedPackage(undefined)
    setEvents([])
    void loadFacility(selectedId)
  }, [selectedId, loadFacility])

  async function refreshLive() {
    setBusy(true); setError('')
    try {
      const result = await post<Recommendation>(`/facilities/${selectedId}/refresh`, {})
      setRecommendation(result)
      const notification = await api<NotificationPackage>(`/facilities/${selectedId}/notifications/preview`)
      setPreview(notification)
      await loadCore()
      setToast('Live NWS and NWPS evidence refreshed')
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }

  async function teleport() {
    setBusy(true); setError('')
    try {
      const result = await post<{ facility: Facility; recommendation: Recommendation }>('/demo/teleport', {})
      await loadCore()
      setSelectedId(result.facility.id)
      setRecommendation(result.recommendation)
      setTab('decision')
      setToast('Facility cloned into a current NWS alert')
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }

  async function decide(action: 'approved' | 'modified' | 'overridden', actor: string, reason?: string, posture?: Posture) {
    setBusy(true); setError('')
    try {
      const result = await post<{ record: DecisionRecord; notification_package: NotificationPackage }>(`/facilities/${selectedId}/decision`, { action, actor, reason, posture })
      setApprovedPackage(result.notification_package)
      setRecords((items) => [...items, result.record])
      const chain = await api<typeof verification>('/records/verify')
      setVerification(chain)
      setTab('notifications')
      setToast(`Decision ${action}; notification package unlocked`)
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }

  async function simulateSend() {
    if (!approvedPackage) return
    setBusy(true)
    try {
      const result = await post<{ events: typeof events }>(`/notifications/${approvedPackage.id}/send`, { simulate: true })
      setEvents(result.events)
      setToast(`${result.events.length} simulated channel deliveries captured`)
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }

  async function acknowledge(employeeId: string) {
    if (!approvedPackage) return
    try {
      await post(`/notifications/${approvedPackage.id}/ack`, { employee_id: employeeId, reply: '1' })
      setEvents(await api(`/notifications/${approvedPackage.id}/events`))
    } catch (caught) { setError((caught as Error).message) }
  }

  async function escalate() {
    if (!approvedPackage) return
    try {
      await post(`/notifications/${approvedPackage.id}/escalate?after_minutes=0`, {})
      setEvents(await api(`/notifications/${approvedPackage.id}/events`))
      setToast('Unacknowledged recipients escalated in the simulator')
    } catch (caught) { setError((caught as Error).message) }
  }

  function chooseTab(next: Tab) { setTab(next); setMobileNav(false) }

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="mobile-menu" onClick={() => setMobileNav((value) => !value)}>{mobileNav ? <X /> : <Menu />}</button>
        <button className="brand" onClick={() => chooseTab('situation')}><span className="brand-mark"><i /><i /><i /></span><span><strong>FirstLight</strong><small>Storm decision support</small></span></button>
        <nav className={mobileNav ? 'open' : ''}>{nav.map((item) => { const Icon = item.icon; return <button key={item.id} className={tab === item.id ? 'active' : ''} onClick={() => chooseTab(item.id)}><Icon size={17} />{item.label}</button> })}</nav>
        <div className="system-state"><span /><RadioTower size={15} /> Decision support online</div>
      </header>
      <div className="context-bar"><span className={`mode mode-${recommendation?.data_mode || 'loading'}`}>{recommendation?.data_mode || 'loading'} evidence</span><strong>{selected?.city || 'Loading facility'}{selected ? `, ${selected.state}` : ''}</strong><span>{recommendation?.inputs.length || 0} traceable inputs</span><span>{recommendation?.confidence.level || '—'} confidence</span></div>
      {error && <div className="global-error"><strong>Visible failure:</strong> {error}<button onClick={() => setError('')}>Dismiss</button></div>}
      {toast && <button className="toast" onClick={() => setToast('')}>{toast}<X size={14} /></button>}
      <main>
        {tab === 'situation' && <SituationBoard facilities={facilities} selectedId={selectedId} alerts={alerts} liveError={error} busy={busy} onSelect={setSelectedId} onRefresh={refreshLive} onTeleport={teleport} />}
        {tab === 'decision' && <DecisionView facility={selected} recommendation={recommendation} busy={busy} onRefresh={refreshLive} onDecide={decide} />}
        {tab === 'notifications' && <NotificationView preview={preview} approvedPackage={approvedPackage} events={events} onSend={simulateSend} onAck={acknowledge} onEscalate={escalate} />}
        {tab === 'records' && <RecordsView records={records} verification={verification} />}
        {tab === 'thresholds' && <ThresholdsView version={thresholds.version} thresholds={thresholds.thresholds} />}
        {tab === 'analyst' && <AnalystPanel facilityId={selectedId} />}
      </main>
      <footer className="site-footer"><span>FirstLight · Human decides, system prepares</span><strong>Prototype for HackMidwest. Not an official USDA or OPM system.</strong><span>Simulator only · Synthetic people</span></footer>
    </div>
  )
}
