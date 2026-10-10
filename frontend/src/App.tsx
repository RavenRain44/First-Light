import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { AIPanel, WatchPanel } from "./components/AIPanel";
import { AlertsPanel } from "./components/AlertsPanel";
import { DecisionPanel } from "./components/DecisionPanel";
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
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState(false);
  const [theme, setTheme] = useState(initialTheme);
  const [recordKey, setRecordKey] = useState(0);
  const [view, setView] = useState<"dashboard" | "thresholds">("dashboard");

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
    if (mode === "live") run(() => api.latest());
    else setSnap((s) => (s && s.mode === "live" ? s : s));
  }, [mode, run]);

  // Keep the live view fresh. Cadence follows readiness (Red 10 min ... White 6 h), capped at 30 min
  // so a quiet dashboard still notices change; the backend only re-evaluates when its snapshot is stale.
  const recheck = Math.min(snap?.readiness?.recheck_minutes ?? 10, 30);
  useEffect(() => {
    if (mode !== "live") return;
    const t = setInterval(() => api.latest().then(setSnap).catch(() => {}), recheck * 60 * 1000);
    return () => clearInterval(t);
  }, [mode, recheck]);

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-3 sm:p-5">
      <Header snap={snap} mode={mode} setMode={setMode} busy={busy} demo={demo} theme={theme}
        onRefresh={() => run(() => api.evaluateLive())} toggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")} />

      <nav className="flex gap-5 border-b border-edge text-sm">
        {(["dashboard", "thresholds"] as const).map((v) => (
          <button key={v} onClick={() => setView(v)}
            className={`relative px-1 pb-1.5 ${view === v ? "font-semibold text-ink" : "text-ink2 hover:text-ink"}`}>
            {v === "dashboard" ? "Dashboard" : "Thresholds & backtest"}
            <span className={`absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-[var(--accent)] transition-transform duration-300 ${view === v ? "scale-x-100" : "scale-x-0"}`} />
          </button>
        ))}
      </nav>

      {view === "thresholds" ? <div className="cc-fade"><ThresholdsView /></div> : (
        <>
          {mode === "replay" && <ReplayPanel onSnapshot={setSnap} busy={busy} setBusy={setBusy} current={snap} />}
          {mode === "livecheck" && <LiveCheckPanel onSnapshot={setSnap} busy={busy} setBusy={setBusy} />}
          {err && <div role="alert" className="card border-l-4 border-l-[var(--danger)] p-3 text-sm">Could not load: {err}. The last good snapshot (if any) is still shown.</div>}
          {snap && (mode !== "livecheck" || snap.mode === "livecheck") && (mode !== "replay" || snap.mode !== "live") ? (
            <div className="cc-stagger space-y-4">
              <div className="grid items-start gap-4 lg:grid-cols-3">
                <div className="lg:col-span-2">
                  <PanelBoundary name="Interpretation"><AIPanel snap={snap} /></PanelBoundary>
                </div>
                {/* side column stays in view while the longer interpretation scrolls past */}
                <div className="space-y-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
                  <PanelBoundary name="Alerts"><AlertsPanel snap={snap} /></PanelBoundary>
                  <PanelBoundary name="Watch"><WatchPanel snap={snap} /></PanelBoundary>
                  <PanelBoundary name="Decision"><DecisionPanel key={snap.snapshot_id} snap={snap} onRecorded={() => setRecordKey((k) => k + 1)} /></PanelBoundary>
                </div>
              </div>
              <PanelBoundary name="Threat breakdown"><ThreatPanel snap={snap} /></PanelBoundary>
              <PanelBoundary name="Timeline"><TimelinePanel snap={snap} /></PanelBoundary>
              <PanelBoundary name="Roads"><RoadsPanel snap={snap} /></PanelBoundary>
              <PanelBoundary name="Analogs"><AnalogsPanel snap={snap} /></PanelBoundary>
              <div className="grid gap-4 lg:grid-cols-2">
                <PanelBoundary name="Decision record"><RecordTimeline snap={snap} refreshKey={recordKey} onOpen={(id) => run(() => api.snapshot(id))} /></PanelBoundary>
                <PanelBoundary name="Raw data"><RawDataDrawer snap={snap} /></PanelBoundary>
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
