export type Posture = "NORMAL" | "DELAYED_ARRIVAL" | "EARLY_DISMISSAL" | "TELEWORK" | "CLOSED";

export interface Point { t: string; v: number | null }

export interface NormalizedInput {
  id: string;
  kind: "series" | "scalar" | "alert" | "road" | "outlook" | "report";
  role: string;
  metric: string;
  unit: string | null;
  value: number | string | null;
  series: Point[] | null;
  data: Record<string, any> | null;
  source: string;
  source_url: string;
  fetched_at: string;
  source_time: string | null;
  note: string | null;
}

export interface SourceStatus {
  adapter: string;
  label: string;
  status: "ok" | "unavailable" | "not_applicable" | "empty";
  detail: string | null;
  fetched_at: string | null;
  source_time: string | null;
  urls: string[];
  n_inputs: number;
  elapsed_ms: number;
}

export interface Alert {
  id: string;
  event: string;
  severity: string | null;
  certainty: string | null;
  urgency: string | null;
  onset: string | null;
  ends: string | null;
  expires: string | null;
  sent: string | null;
  headline: string | null;
  description: string | null;
  instruction: string | null;
  areaDesc: string | null;
  web?: string | null;
  origin?: string;
  inferred_fields?: string[];
  archive_note?: string | null;
}

export interface RuleResult {
  rule_id: string;
  hazard: string;
  metric: string;
  label: string;
  operator: string;
  threshold: number;
  unit: string;
  observed_value: number | string | null;
  triggered: boolean;
  available: boolean;
  margin_abs: number | null;
  margin_pct: number | null;
  time_of_peak: string | null;
  window_start: string | null;
  window_end: string | null;
  input_ids: string[];
  level: number;
  posture_effect: string;
  score: number;
  verified: boolean;
  basis: string;
  anchor: string;
  source_url: string;
  time_window: string;
  detail: string | null;
}

export interface HazardResult {
  hazard: string;
  label: string;
  score: number;
  level: number;
  level_name: string;
  triggered_rule_ids: string[];
  controlling_rule_ids: string[];
  window_start: string | null;
  window_end: string | null;
  time_of_peak: string | null;
  posture: Posture;
  posture_reason: string;
}

export interface Factor { name: string; score: number; weight: number; explanation: string }

export interface Interpretation {
  headline: string;
  rationale_paragraph: string;
  what_would_change: string[];
  watch_next_6h: string[];
  alert_summaries: Record<string, string>;
  analog_comparison: string;
  validation?: { ok: boolean; attempts: number; problems: string[] };
}

export interface Analog {
  event_id: string;
  name: string;
  hazard: string;
  similarity_pct: number;
  matched_as_of: string;
  recommended_posture: Posture;
  outcome_summary: string;
  outcome: Record<string, any>;
  label: string;
}

export interface Facility {
  id: string;
  name: string;
  synthetic: boolean;
  lat: number;
  lon: number;
  state: string;
  timezone: string;
  hours: { open: string; close: string };
  building_type?: string;
  accessibility_notes: string[];
  corridors: { id: string; name: string; coordinates: number[][] }[];
  hypothetical?: boolean;
}

export interface Snapshot {
  snapshot_id: string;
  facility_id: string;
  as_of: string;
  created_at: string;
  mode: "live" | "replay" | "backtest" | "livecheck";
  event_id: string | null;
  thresholds_version: string;
  thresholds_sha256: string;
  model_id: string;
  prompt_version: string;
  content_sha256: string;
  integrity_ok: boolean | null;
  facility: Facility;
  roster: Record<string, any>;
  inputs: NormalizedInput[];
  alerts: Alert[];
  sources: SourceStatus[];
  signals: Record<string, any>;
  rules: RuleResult[];
  hazards: Record<string, HazardResult>;
  posture: {
    posture: Posture;
    opm_label: string;
    opm_section: string;
    decision_day: string;
    contributing_hazards: string[];
    reasons: string[];
    guidance: string[];
  };
  confidence: { level: "high" | "medium" | "low"; score: number; factors: Factor[] };
  changes: { text: string; kind: string; new_posture: Posture }[];
  readiness: Readiness | null;
  watch_next_6h: string[];
  analogs: Analog[];
  features: Record<string, number>;
  ai: Interpretation;
  livecheck?: { alert_id: string; event: string; place: string; label: string; assume_workday: boolean };
}

export type ReadinessLevel = "WHITE" | "YELLOW" | "ORANGE" | "RED";

export interface Readiness {
  level: ReadinessLevel;
  cooper: string;
  meaning: string;
  reasons: string[];
  decide_by: string | null;
  deadline_passed: boolean;
  recheck_minutes: number;
  basis: string;
}

export interface Decision {
  id: number;
  snapshot_id: string;
  decided_by: string;
  decision_posture: Posture;
  recommended_posture: Posture;
  agreed_with_recommendation: boolean;
  override_reason: string | null;
  notes: string | null;
  decided_at: string;
  label: string;
}

export interface CameraView { view: number; url: string; time: string; label: string }

export interface Camera {
  id: string;
  name: string;
  lat: number;
  lon: number;
  km: number;
  direction: string;
  corridor: string | null;
  corridor_name: string | null;
  updated: string;
  views: CameraView[];
}
