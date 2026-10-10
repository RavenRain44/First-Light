export type Posture = 'NORMAL' | 'TELEWORK_OPTION' | 'DELAYED_ARRIVAL' | 'EARLY_DISMISSAL' | 'CLOSED'

export interface Facility {
  id: string
  name: string
  city: string
  state: string
  lat: number
  lon: number
  tz: string
  region: string
  is_teleported: boolean
  recommendation: {
    posture: Posture
    confidence: { level: string; components: Record<string, string | number> }
    as_of: string
    data_mode: string
    active_alerts: number
  }
}

export interface Recommendation {
  facility_id: string
  as_of: string
  engine_version: string
  registry_version: string
  posture: Posture
  delay_hours?: number
  depart_by?: string
  shelter_now: boolean
  decision_deadline: string
  inputs: Array<{
    id: string
    source: string
    url: string
    issued_at: string
    fetched_at: string
    sha256: string
    object_key: string
    fields_used: Record<string, unknown>
    stale: boolean
  }>
  thresholds_crossed: Array<{
    id: string
    hazard: string
    observed: number | string
    limit: number | string
    margin: string
    level: number
    rationale_ref: string
  }>
  confidence: { level: string; components: Record<string, string | number> }
  what_would_change: Array<{ if: string; then: Posture; direction: string; delta: string }>
  rationale_template: string
  rationale_llm?: string
  rationale_grounded: boolean
  severity_timeline: Array<{ at: string; level: number; hazards: Record<string, number> }>
  data_mode: string
  notices: string[]
}

export interface Recipient {
  employee_id: string
  employee_name: string
  included: boolean
  reason: string
  variant: string
  channels: string[]
  send_at?: string
  message_sms?: string
  message_email_subject?: string
  message_email_body?: string
}

export interface NotificationPackage {
  id: string
  facility_id: string
  posture: Posture
  urgency: string
  checklist_valid: boolean
  validation_errors: string[]
  recipients: Recipient[]
}

export interface DecisionRecord {
  id: string
  sequence: number
  created_at: string
  hash: string
  prev_hash: string
  actor: string
  human_action: string
  reason?: string
  recommendation: Recommendation
  notification_package: NotificationPackage
}

export interface Threshold {
  id: string
  hazard: string
  metric: string
  value: number | string
  unit: string
  level: number
  posture_floor?: Posture
  source_type: string
  source_url: string
  quote_or_summary: string
  retrieved_at: string
  verified_by: string
  notes: string
  requires_signoff: boolean
}
