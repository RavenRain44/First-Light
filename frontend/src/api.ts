import type { Decision, Snapshot } from "./types";

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

export const api = {
  health: () => req<{ demo_mode: boolean; model_provider: string }>("/api/health"),
  facility: () => req<any>("/api/facility"),
  latest: (maxAge?: number) => req<Snapshot>(`/api/snapshot/latest${maxAge !== undefined ? `?max_age_seconds=${maxAge}` : ""}`),
  snapshot: (id: string) => req<Snapshot>(`/api/snapshot/${id}`),
  regenerateBrief: (id: string) => req<import("./types").AiAddon>(`/api/snapshot/${id}/interpretation`, { method: "POST" }),
  interpretation: (id: string) => req<import("./types").AiAddon>(`/api/snapshot/${id}/interpretation`),
  evaluateLive: () => req<Snapshot>("/api/evaluate", { method: "POST", body: JSON.stringify({ mode: "live" }) }),
  evaluateReplay: (as_of: string, event_id?: string) =>
    req<Snapshot>("/api/evaluate", { method: "POST", body: JSON.stringify({ mode: "replay", as_of, event_id }) }),
  timeseries: (snapshot_id: string) => req<any>(`/api/timeseries?snapshot_id=${snapshot_id}`),
  roads: (as_of?: string) => req<any>(`/api/roads${as_of ? `?as_of=${encodeURIComponent(as_of)}` : ""}`),
  cameras: (as_of?: string) => req<{ status: string; detail: string | null; as_of: string; cameras: import("./types").Camera[]; note: string; source_url?: string; fetched_at?: string }>(
    `/api/cameras${as_of ? `?as_of=${encodeURIComponent(as_of)}` : ""}`),
  cameraImage: (url: string) => `/api/cameras/image?u=${encodeURIComponent(url)}`,
  thresholds: () => req<any>("/api/thresholds"),
  history: () => req<any[]>("/api/snapshots?limit=40"),
  decisions: () => req<Decision[]>("/api/decisions"),
  record: (id: string) => req<any>(`/api/record/${id}`),
  decide: (body: { snapshot_id: string; decided_by: string; decision_posture: string; override_reason?: string; notes?: string }) =>
    req<Decision>("/api/decisions", { method: "POST", body: JSON.stringify(body) }),
  events: () => req<any[]>("/api/history/events"),
  event: (id: string) => req<any>(`/api/history/events/${id}`),
  replay: (id: string, as_of: string) => req<Snapshot>(`/api/history/events/${id}/replay?as_of=${encodeURIComponent(as_of)}`),
  liveAlerts: () => req<any>("/api/live-check/alerts"),
  liveEvaluate: (alert_id: string, assume_workday: boolean) =>
    req<Snapshot>("/api/live-check/evaluate", { method: "POST", body: JSON.stringify({ alert_id, assume_workday }) }),
};
