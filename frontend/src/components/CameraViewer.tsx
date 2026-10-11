import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Camera } from "../types";
import { ago, fmtTime } from "../util";

// Traffic snapshots keep one URL that Iowa DOT overwrites every few minutes; re-ask this often.
const SNAPSHOT_REFRESH_MS = 60 * 1000;

/** Compact viewer for one Iowa DOT camera, shown in the panel beside the map. */
export function CameraViewer({ cam, tz, live, onClose, onUnavailable }: {
  cam: Camera; tz: string; live: boolean; onClose: () => void; onUnavailable: (id: string) => void;
}) {
  const [view, setView] = useState(cam.views[0]?.view ?? 0);
  const [failed, setFailed] = useState<Set<number>>(new Set());
  const [loaded, setLoaded] = useState(false);
  const [streamFailed, setStreamFailed] = useState(false);
  const [tick, setTick] = useState(0);

  // Keep the chosen view when the camera's frames update (replay step / live refresh), if it still exists.
  useEffect(() => {
    if (!cam.views.some((v) => v.view === view)) setView(cam.views[0]?.view ?? 0);
    setFailed(new Set());
  }, [cam]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setStreamFailed(false), [cam.id, cam.stream_url]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const streaming = live && !!cam.stream_url && !streamFailed;
  const refreshing = live && cam.kind === "traffic" && !streaming;
  useEffect(() => {
    if (!refreshing) return;
    const t = setInterval(() => setTick((n) => n + 1), SNAPSHOT_REFRESH_MS);
    return () => clearInterval(t);
  }, [refreshing]);

  const views = cam.views.filter((v) => !failed.has(v.view));
  const current = views.find((v) => v.view === view) ?? views[0];
  useEffect(() => setLoaded(false), [current?.url, streaming]);

  // Every view failed to load: hide this camera instead of showing a broken image.
  useEffect(() => {
    if (cam.views.length && views.length === 0) onUnavailable(cam.id);
  }, [views.length]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!current) return null;
  const still = api.cameraImage(current.url) + (refreshing ? `&t=${tick}` : "");
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

      {streaming ? (
        <div className="relative aspect-video overflow-hidden rounded-xl bg-black">
          {!loaded && <div className="skeleton absolute inset-0" />}
          <LiveVideo key={cam.stream_url} src={cam.stream_url!} poster={api.cameraImage(current.url)}
            label={`${cam.name}, live video`} onPlaying={() => setLoaded(true)} onFatal={() => setStreamFailed(true)} />
          <span className="absolute bottom-2 left-2 inline-flex items-center gap-1 rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] font-semibold text-white">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" aria-hidden />LIVE
          </span>
        </div>
      ) : (
        <a href={still} target="_blank" rel="noreferrer"
          className="relative block aspect-[4/3] overflow-hidden rounded-xl bg-[var(--surface-2)]" title="Open full size">
          {!loaded && <div className="skeleton absolute inset-0" />}
          <img key={current.url} src={still} alt={`${cam.name}, ${current.label}`}
            className={`h-full w-full object-cover transition-opacity duration-300 ${loaded ? "opacity-100" : "opacity-0"}`}
            onLoad={() => setLoaded(true)}
            onError={() => setFailed((f) => new Set(f).add(current.view))} />
          <span className="absolute bottom-2 left-2 rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] font-medium text-white">
            {cam.kind === "traffic" ? (live ? "Latest snapshot" : "Cached snapshot") : live ? `${ago(current.time)}` : fmtTime(current.time, tz)}
          </span>
        </a>
      )}

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
        {cam.kind === "traffic"
          ? streaming ? "Live video from Iowa DOT traffic camera." : "Snapshot from Iowa DOT traffic camera (live video unavailable)."
          : `Still image from ${cam.kind === "webcam" ? cam.source ?? "webcam via IEM" : "Iowa DOT weather-station camera via IEM"}, ${live ? "refreshed every few minutes" : "as archived at that time"}.`}
        {" "}For situational awareness; not used in the recommendation.
      </p>
    </div>
  );
}

/** HLS player: hls.js where needed (Chrome, Firefox), native playback on Safari/iOS. Torn down on unmount. */
function LiveVideo({ src, poster, label, onPlaying, onFatal }: {
  src: string; poster: string; label: string; onPlaying: () => void; onFatal: () => void;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    let hls: import("hls.js").default | null = null;
    let native = false;
    let cancelled = false;
    import("hls.js").then(({ default: Hls }) => {
      if (cancelled) return;
      if (Hls.isSupported()) {
        hls = new Hls({ liveDurationInfinity: true, lowLatencyMode: false });
        hls.on(Hls.Events.ERROR, (_e, d) => { if (d.fatal) { hls?.destroy(); hls = null; onFatal(); } });
        hls.loadSource(src);
        hls.attachMedia(video);
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        native = true;
        video.src = src;
      } else {
        onFatal();
      }
    }).catch(onFatal);
    return () => {
      cancelled = true;
      hls?.destroy();
      if (native) { video.removeAttribute("src"); video.load(); } // stop the native download
    };
  }, [src]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <video ref={ref} poster={poster} aria-label={label} muted autoPlay playsInline
      className="h-full w-full object-cover" onPlaying={onPlaying} onError={onFatal} />
  );
}
