import type { Decision, Facility, ReplayEvent, ReplayTimeline, Snapshot, Timeseries } from "./types";

export const DEFAULT_FACILITY_ID = "IA-AMES-SC";
let facilityId = DEFAULT_FACILITY_ID;
let generation = 0;
let scope = new AbortController();

/** Capture the facility for every request, and cancel all outgoing work when it changes. */
export function selectApiFacility(id: string) {
  if (id === facilityId) return;
  scope.abort();
  scope = new AbortController();
  facilityId = id;
  generation += 1;
}
export const selectedApiFacility = () => facilityId;
export const selectedApiGeneration = () => generation;
export function facilityPath(path: string, id = facilityId): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}facility_id=${encodeURIComponent(id)}`;
}

export async function scopedRequest<T>(path: string, init?: RequestInit, scoped = true): Promise<T> {
  const version = generation, selected = facilityId;
  const controller = new AbortController();
  const signals = scoped ? [scope.signal, init?.signal] : [init?.signal];
  const abort = () => controller.abort();
  for (const signal of signals) {
    if (signal?.aborted) controller.abort();
    else signal?.addEventListener("abort", abort, { once: true });
  }
  let body = init?.body;
  if (scoped && typeof body === "string") {
    try { const data = JSON.parse(body); if (data && !Array.isArray(data) && typeof data === "object") body = JSON.stringify({ ...data, facility_id: selected }); }
    catch { /* Non-JSON bodies retain their original encoding. */ }
  }
  try {
    const r = await fetch(scoped ? facilityPath(path, selected) : path, {
      headers: { "content-type": "application/json" }, ...init, body, signal: controller.signal,
    });
    if (!r.ok) {
      let detail = `${r.status} ${r.statusText}`;
      try { const j = await r.json(); detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j); }
      catch { /* not JSON */ }
      throw new Error(detail);
    }
    const data = await r.json() as T;
    if (controller.signal.aborted || (scoped && version !== generation)) throw new DOMException("Facility request cancelled", "AbortError");
    const responseFacility = data && typeof data === "object" ? (data as any).facility_id ?? (data as any).facility?.id : undefined;
    const whatIf = data as any;
    const requestPath = path.split("?")[0];
    const selectedHypothetical = ((requestPath === "/api/live-check/evaluate"
      && whatIf?.livecheck?.base_facility_id === selected) ||
      (requestPath.startsWith("/api/snapshot/") && requestPath !== "/api/snapshot/latest"))
      && whatIf?.mode === "livecheck" && whatIf?.facility?.hypothetical === true
      && whatIf?.facility?.provider_settings?.origin_facility_id === selected;
    if (scoped && responseFacility && responseFacility !== selected && !selectedHypothetical) throw new Error("The response belongs to a different facility. Reload this view.");
    return data;
  } finally {
    for (const signal of signals) signal?.removeEventListener("abort", abort);
  }
}
const req = scopedRequest;

export type StorageStatus = { enabled: boolean; bucket: string | null; endpoint: string | null; last_sync: string | null;
  last_error: string | null; uploaded: number; backup: string | null };
export type StorageLinks = { enabled: boolean; error?: string; expires_in?: number; log_url?: string | null; graph_url?: string | null;
  camera_sets?: { decision_id: number; captured_at?: string; images: { key: string; url: string; camera: string; view?: string; time?: string }[] }[] };

export const api = {
  grade: (id: number) => req<any>(`/api/decisions/${id}/grade`),
  saveGrade: (id: number, body: any) => req<any>(`/api/decisions/${id}/grade`, {method:"POST", body:JSON.stringify(body)}),
  intention: (id: number, body: any) => req<any>(`/api/decisions/${id}/intention`, {method:"POST", body:JSON.stringify(body)}),
  refreshGrade: (id: number) => req<any>(`/api/decisions/${id}/grade/refresh`, {method:"POST"}),
  feedback: (fp = 1, fn = 5) => req<any>(`/api/feedback/statistics?false_alarm_cost=${fp}&missed_disruption_cost=${fn}`),
  feedbackCatalog: () => req<any>("/api/feedback/catalog"),
  feedbackAnalysis: () => req<any>("/api/feedback/analysis"),
  analyzeFeedback: (body: any) => req<any>("/api/feedback/analyze", {method:"POST",body:JSON.stringify(body)}),
  policies: () => req<any>("/api/policies"),
  proposePolicy: (body: any) => req<any>("/api/policies", {method:"POST",body:JSON.stringify(body)}),
  policyAction: (id: string, action: string, body: any, token = "") => req<any>(`/api/policies/${id}/${action}`, {
    method:"POST",headers:{"Content-Type":"application/json", "X-Threshold-Admin-Token":token},body:JSON.stringify(body)}),
  facilities: () => req<Facility[]>("/api/facilities", undefined, false),
  backtesting: () => req<any>("/api/backtesting"),
  searchHistory: (body: any) => req<any>("/api/backtesting/search", {method:"POST",body:JSON.stringify(body)}),
  startHistoryBuild: (body: any) => req<any>("/api/backtesting/build", {method:"POST",body:JSON.stringify(body)}),
  resumeHistoryBuild: (id: string) => req<any>(`/api/backtesting/jobs/${id}/resume`, {method:"POST"}),
  cancelHistoryBuild: (id: string) => req<any>(`/api/backtesting/jobs/${id}/cancel`, {method:"POST"}),
  health: () => req<{ demo_mode: boolean; model_provider: string; inference: { enabled: boolean } }>("/api/health", undefined, false),
  facility: () => req<any>("/api/facility"),
  latest: (maxAge?: number) => req<Snapshot>(`/api/snapshot/latest${maxAge !== undefined ? `?max_age_seconds=${maxAge}` : ""}`),
  snapshot: (id: string) => req<Snapshot>(`/api/snapshot/${id}`),
  regenerateBrief: (id: string) => req<import("./types").AiAddon>(`/api/snapshot/${id}/interpretation`, { method: "POST" }),
  interpretation: (id: string) => req<import("./types").AiAddon>(`/api/snapshot/${id}/interpretation`),
  evaluateLive: () => req<Snapshot>("/api/evaluate", { method: "POST", body: JSON.stringify({ mode: "live" }) }),
  evaluateReplay: (as_of: string, event_id?: string, signal?: AbortSignal) =>
    req<Snapshot>("/api/evaluate", { method: "POST", body: JSON.stringify({ mode: "replay", as_of, event_id }), signal }),
  timeseries: (snapshot_id: string, signal?: AbortSignal) => req<Timeseries>(`/api/timeseries?snapshot_id=${snapshot_id}`, { signal }),
  roads: (as_of?: string) => req<any>(`/api/roads${as_of ? `?as_of=${encodeURIComponent(as_of)}` : ""}`),
  cameras: (as_of?: string) => req<{ status: string; detail: string | null; as_of: string; cameras: import("./types").Camera[]; note: string; source_url?: string; fetched_at?: string }>(
    `/api/cameras${as_of ? `?as_of=${encodeURIComponent(as_of)}` : ""}`),
  decisionCameras: (id: number) => req<any>(`/api/cameras/decision/${id}`),
  cameraImage: (url: string) => url.startsWith("/api/cameras/saved-frame/") ? facilityPath(url) : facilityPath(`/api/cameras/image?u=${encodeURIComponent(url)}`),
  thresholds: () => req<any>("/api/thresholds"),
  history: () => req<any[]>("/api/snapshots?limit=40"),
  decisions: () => req<Decision[]>("/api/decisions"),
  riskTradeoffs: (snapshotId?: string) => req<import("./tradeoffs").RiskTradeoffs>(
    `/api/risk-tradeoffs${snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : ""}`),
  pastDecisions: (snapshotId?: string) => req<{ decisions: import("./types").PastDecision[]; reviewing: number[] }>(
    `/api/past-decisions${snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : ""}`),
  reviewDecision: (id: number, body: { reviewer: string; verdict: import("./types").Verdict; note?: string }) =>
    req<import("./types").DecisionReview>(`/api/decisions/${id}/review`, { method: "POST", body: JSON.stringify(body) }),
  aiReviewDecision: (id: number) => req<import("./types").DecisionReview>(`/api/decisions/${id}/ai-review`, { method: "POST" }),
  record: (id: string) => req<any>(`/api/record/${id}`),
  decide: (body: { snapshot_id: string; decided_by: string; decision_posture: string; override_reason?: string; notes?: string; intended_objective?: string }) =>
    req<Decision>("/api/decisions", { method: "POST", body: JSON.stringify(body) }),
  events: (signal?: AbortSignal) => req<ReplayEvent[]>("/api/history/events", { signal }),
  event: (id: string, signal?: AbortSignal) => req<ReplayEvent>(`/api/history/events/${id}`, { signal }),
  replay: (id: string, as_of: string, signal?: AbortSignal) => req<Snapshot>(`/api/history/events/${id}/replay?as_of=${encodeURIComponent(as_of)}`, { signal }),
  replayTimeline: (as_of: string, signal?: AbortSignal) => req<ReplayTimeline>(`/api/replay/timeline?as_of=${encodeURIComponent(as_of)}`, { signal }),
  storageStatus: () => req<StorageStatus>("/api/storage/status"),
  storageRecord: (id: string) => req<StorageLinks>(`/api/storage/record/${id}`),
  liveAlerts: () => req<any>("/api/live-check/alerts"),
  liveEvaluate: (alert_id: string, assume_workday: boolean) =>
    req<Snapshot>("/api/live-check/evaluate", { method: "POST", body: JSON.stringify({ alert_id, assume_workday }) }),
};
