import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { AIPanel, WatchPanel } from "./components/AIPanel";
import { AlertsPanel } from "./components/AlertsPanel";
import { DecisionPanel } from "./components/DecisionPanel";
import { NotificationsView } from "./components/NotificationsView";
import { PanelBoundary } from "./components/ErrorBoundary";
import { Header, type Mode } from "./components/Header";
import { AnalogsPanel, RecordTimeline } from "./components/HistoryPanel";
import { LiveCheckPanel } from "./components/LiveCheckPanel";
import { RawDataDrawer } from "./components/RawDataDrawer";
import { ReplayPanel } from "./components/ReplayPanel";
import { RoadsPanel } from "./components/RoadsPanel";
import { ThreatPanel } from "./components/ThreatPanel";
import { ThresholdsView } from "./components/ThresholdsView";
import { TimelinePanel } from "./components/TimelinePanel";
import type { Snapshot } from "./types";
import { Skeleton } from "./util";

function initialTheme(): string {
  try {
    const t = localStorage.getItem("cc-theme");
    if (t) return t;
  } catch { /* storage blocked */ }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  const [mode, setMode] = useState<Mode>("live");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  // Panels show the AI brief once its add-on record arrives; the snapshot itself is unchanged.
  const shown = useMemo(() => (snap && snap.ai_addon?.status === "ok" && snap.ai_addon.ai
    ? { ...snap, ai: snap.ai_addon.ai, model_id: snap.ai_addon.model_id ?? snap.model_id, prompt_version: snap.ai_addon.prompt_version ?? snap.prompt_version }
    : snap), [snap]);
  const pendingId = snap?.ai_addon?.status === "pending" ? snap.snapshot_id : null;
  useEffect(() => {
    if (!pendingId) return;
    let alive = true, tries = 0;
    const t = setInterval(async () => {
      tries += 1;
      try {
        const addon = await api.interpretation(pendingId);
        if (!alive) return;
        if (addon.status !== "pending" || tries > 60) {
          clearInterval(t);
          setSnap((s) => (s && s.snapshot_id === pendingId ? { ...s, ai_addon: addon.status === "pending" ? { status: "failed" } : addon } : s));
        }
      } catch { /* keep the template brief */ }
    }, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [pendingId]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState(false);
  const [theme, setTheme] = useState(initialTheme);
  const [recordKey, setRecordKey] = useState(0);
  const [view, setView] = useState<"dashboard" | "thresholds" | "notifications">("dashboard");
  const [savedDecisionId, setSavedDecisionId] = useState<number | null>(null);
  const [savedWeather, setSavedWeather] = useState(false);
  const savedWeatherRef = useRef(false);
  const [notificationDecision, setNotificationDecision] = useState<number | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("cc-theme", theme); } catch { /* ignore */ }
  }, [theme]);

  useEffect(() => { api.health().then((h) => setDemo(h.demo_mode)).catch(() => {}); }, []);

  const run = useCallback(async (fn: () => Promise<Snapshot>) => {
    setBusy(true); setErr(null);
    try { setSnap(await fn()); setRecordKey((k) => k + 1); }
    catch (e: any) { setErr(e.message ?? String(e)); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => {
    if (mode === "live" && !savedWeather) {
      api.latest().then(s => { if (!savedWeatherRef.current) setSnap(s); }).catch(e => setErr(e.message));
    }
    else setSnap((s) => (s && s.mode === "live" ? s : s));
  }, [mode, run, savedWeather]);

  // Keep the live view fresh. Cadence follows readiness (Red 10 min ... White 6 h), capped at 30 min
  // so a quiet dashboard still notices change; the backend only re-evaluates when its snapshot is stale.
  const recheck = Math.min(snap?.readiness?.recheck_minutes ?? 10, 30);
  useEffect(() => {
    if (mode !== "live" || savedWeather) return;
    const t = setInterval(() => api.latest().then(s => { if (!savedWeatherRef.current) setSnap(s); }).catch(() => {}), recheck * 60 * 1000);
    return () => clearInterval(t);
  }, [mode, recheck, savedWeather]);

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-3 sm:p-5">
      <Header snap={shown} mode={mode} setMode={setMode} busy={busy} demo={demo} theme={theme}
        onRefresh={() => { savedWeatherRef.current = false; setSavedWeather(false); run(() => api.evaluateLive()); }} toggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")} />

      {savedWeather && <div role="status" className="card p-3 text-sm">Saved weather snapshot · {snap?.snapshot_id}. Live updates are paused while reviewing this record. <button className="btn ml-2" onClick={()=>{savedWeatherRef.current = false; setSavedWeather(false);setMode('live');}}>Return to live weather</button></div>}
      <nav className="flex gap-5 border-b border-edge text-sm">
        {(["dashboard", "thresholds", "notifications"] as const).map((v) => (
          <button key={v} onClick={() => setView(v)}
            className={`relative px-1 pb-1.5 ${view === v ? "font-semibold text-ink" : "text-ink2 hover:text-ink"}`}>
            {v === "dashboard" ? "Dashboard" : v === "thresholds" ? "Thresholds & backtest" : "Notifications"}
            <span className={`absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-[var(--accent)] transition-transform duration-300 ${view === v ? "scale-x-100" : "scale-x-0"}`} />
          </button>
        ))}
      </nav>

      {view === "notifications" ? (
        <div className="cc-fade"><NotificationsView decisionId={notificationDecision} onBack={() => setView("dashboard")} onSnapshot={(id, decisionId)=>{setSavedDecisionId(decisionId);savedWeatherRef.current = true; setSavedWeather(true); setView("dashboard"); run(()=>api.snapshot(id));}} /></div>
      ) : view === "thresholds" ? <div className="cc-fade"><ThresholdsView /></div> : (
        <>
          {mode === "replay" && <ReplayPanel onSnapshot={setSnap} busy={busy} setBusy={setBusy} current={snap} />}
          {mode === "livecheck" && <LiveCheckPanel onSnapshot={setSnap} busy={busy} setBusy={setBusy} />}
          {err && <div role="alert" className="card border-l-4 border-l-[var(--danger)] p-3 text-sm">Could not load: {err}. The last good snapshot (if any) is still shown.</div>}
          {snap && (mode !== "livecheck" || snap.mode === "livecheck") && (mode !== "replay" || snap.mode !== "live") ? (
            <div className="cc-stagger space-y-4">
              {/* Both columns stretch to the same height: whichever side is shorter grows its last card,
                  so there is no blank gap and nothing scrolls inside a column. */}
              <div className="grid items-stretch gap-4 lg:grid-cols-3">
                <div className="lg:col-span-2 [&>section]:h-full">
                  <PanelBoundary name="Interpretation"><AIPanel snap={shown!} /></PanelBoundary>
                </div>
                <div className="flex flex-col gap-4 [&>section:last-child]:flex-1">
                  <PanelBoundary name="Alerts"><AlertsPanel snap={shown!} /></PanelBoundary>
                  <PanelBoundary name="Watch"><WatchPanel snap={shown!} /></PanelBoundary>
                  <PanelBoundary name="Decision"><DecisionPanel key={snap.snapshot_id} snap={shown!}
                    onRecorded={(id) => { setRecordKey((k) => k + 1); setNotificationDecision(id); }}
                    onNotify={(id) => { setNotificationDecision(id); setView("notifications"); window.scrollTo({ top: 0, behavior: "smooth" }); }} /></PanelBoundary>
                </div>
              </div>
              <PanelBoundary name="Threat breakdown"><ThreatPanel snap={shown!} /></PanelBoundary>
              <PanelBoundary name="Timeline"><TimelinePanel snap={shown!} /></PanelBoundary>
              <PanelBoundary name="Roads"><RoadsPanel snap={shown!} savedDecisionId={savedWeather ? savedDecisionId : null} historical={savedWeather} /></PanelBoundary>
              <PanelBoundary name="Analogs"><AnalogsPanel snap={shown!} /></PanelBoundary>
              <div className="grid gap-4 lg:grid-cols-2">
                <PanelBoundary name="Decision record"><RecordTimeline snap={shown!} refreshKey={recordKey} onOpen={(id) => run(() => api.snapshot(id))} /></PanelBoundary>
                <PanelBoundary name="Raw data"><RawDataDrawer snap={shown!} /></PanelBoundary>
              </div>
            </div>
          ) : !err && mode === "live" ? (
            <div className="space-y-4"><Skeleton className="h-48" /><Skeleton className="h-96" /></div>
          ) : null}
        </>
      )}
      <footer className="pb-6 text-center text-xs text-muted">
        Closure Call · Hack Midwest 2026 USDA AI Challenge · Facility and roster are synthetic; weather, alerts and roads are real (NWS, Iowa Environmental Mesonet, Iowa DOT). Times shown in facility local time.
      </footer>
    </div>
  );
}
