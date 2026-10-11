import type { Decision, ReplayEvent, ReplayTimeline, Snapshot, Timeseries } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...init });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export type StorageStatus = { enabled: boolean; bucket: string | null; endpoint: string | null; last_sync: string | null;
  last_error: string | null; uploaded: number; backup: string | null };
export type StorageLinks = { enabled: boolean; error?: string; expires_in?: number; log_url?: string | null; graph_url?: string | null;
  camera_sets?: { decision_id: number; captured_at?: string; images: { key: string; url: string; camera: string; view?: string; time?: string }[] }[] };

export const api = {
  health: () => req<{ demo_mode: boolean; model_provider: string; inference: { enabled: boolean } }>("/api/health"),
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
  cameraImage: (url: string) => url.startsWith("/api/cameras/saved-frame/") ? url : `/api/cameras/image?u=${encodeURIComponent(url)}`,
  thresholds: () => req<any>("/api/thresholds"),
  history: () => req<any[]>("/api/snapshots?limit=40"),
  decisions: () => req<Decision[]>("/api/decisions"),
  pastDecisions: (snapshotId?: string) => req<{ decisions: import("./types").PastDecision[]; reviewing: number[] }>(
    `/api/past-decisions${snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : ""}`),
  reviewDecision: (id: number, body: { reviewer: string; verdict: import("./types").Verdict; note?: string }) =>
    req<import("./types").DecisionReview>(`/api/decisions/${id}/review`, { method: "POST", body: JSON.stringify(body) }),
  aiReviewDecision: (id: number) => req<import("./types").DecisionReview>(`/api/decisions/${id}/ai-review`, { method: "POST" }),
  record: (id: string) => req<any>(`/api/record/${id}`),
  decide: (body: { snapshot_id: string; decided_by: string; decision_posture: string; override_reason?: string; notes?: string }) =>
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
