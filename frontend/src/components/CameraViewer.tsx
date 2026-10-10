import { useEffect, useState } from "react";
import { api } from "../api";
import type { Camera } from "../types";
import { ago, fmtTime } from "../util";

/** Compact viewer for one Iowa DOT camera, shown in the panel beside the map. */
export function CameraViewer({ cam, tz, live, onClose, onUnavailable }: {
  cam: Camera; tz: string; live: boolean; onClose: () => void; onUnavailable: (id: string) => void;
}) {
  const [view, setView] = useState(cam.views[0]?.view ?? 0);
  const [failed, setFailed] = useState<Set<number>>(new Set());
  const [loaded, setLoaded] = useState(false);

  // Keep the chosen view when the camera's frames update (replay step / live refresh), if it still exists.
  useEffect(() => {
    if (!cam.views.some((v) => v.view === view)) setView(cam.views[0]?.view ?? 0);
    setFailed(new Set());
  }, [cam]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const views = cam.views.filter((v) => !failed.has(v.view));
  const current = views.find((v) => v.view === view) ?? views[0];
  useEffect(() => setLoaded(false), [current?.url]);

  // Every view failed to load: hide this camera instead of showing a broken image.
  useEffect(() => {
    if (cam.views.length && views.length === 0) onUnavailable(cam.id);
  }, [views.length]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!current) return null;
  return (
    <div className="cc-rise flex flex-col gap-2" role="region" aria-label={`Camera ${cam.name}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate font-semibold" title={cam.name}>{cam.name}</h3>
          <p className="text-xs text-muted">
            {cam.km.toFixed(0)} km {cam.direction} of facility{cam.corridor_name ? ` · on ${cam.corridor_name}` : ""}
          </p>
        </div>
        <button onClick={onClose} className="btn !px-2 !py-0.5" aria-label="Close camera (Esc)">✕</button>
      </div>

      <a href={api.cameraImage(current.url)} target="_blank" rel="noreferrer"
        className="relative block aspect-[4/3] overflow-hidden rounded-xl bg-[var(--surface-2)]" title="Open full size">
        {!loaded && <div className="skeleton absolute inset-0" />}
        <img key={current.url} src={api.cameraImage(current.url)} alt={`${cam.name}, ${current.label}`}
          className={`h-full w-full object-cover transition-opacity duration-300 ${loaded ? "opacity-100" : "opacity-0"}`}
          onLoad={() => setLoaded(true)}
          onError={() => setFailed((f) => new Set(f).add(current.view))} />
        <span className="absolute bottom-2 left-2 rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] font-medium text-white">
          {live ? `${ago(current.time)}` : fmtTime(current.time, tz)}
        </span>
      </a>

      {views.length > 1 && (
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Camera views">
          {views.map((v) => (
            <button key={v.view} role="tab" aria-selected={v.view === current.view} onClick={() => setView(v.view)}
              className={`rounded-lg px-2 py-0.5 text-xs ${v.view === current.view ? "bg-[var(--accent)] text-[var(--on-accent)]" : "bg-[var(--surface-2)] text-ink2 hover:text-ink"}`}>
              {v.label}
            </button>
          ))}
        </div>
      )}
      <p className="text-[11px] text-muted">
        Still image from Iowa DOT via IEM, {live ? "refreshed every few minutes" : "as archived at that time"}. For situational awareness; not used in the recommendation.
      </p>
    </div>
  );
}
