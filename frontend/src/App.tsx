import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { AIPanel } from "./components/AIPanel";
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

  // Keep the live view fresh: re-check every 5 minutes (backend re-evaluates when its snapshot is stale).
  useEffect(() => {
    if (mode !== "live") return;
    const t = setInterval(() => api.latest().then(setSnap).catch(() => {}), 5 * 60 * 1000);
    return () => clearInterval(t);
  }, [mode]);

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-3 sm:p-5">
      <Header snap={snap} mode={mode} setMode={setMode} busy={busy} demo={demo} theme={theme}
        onRefresh={() => run(() => api.evaluateLive())} toggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")} />

      <nav className="flex gap-2 text-sm">
        <button onClick={() => setView("dashboard")} className={`rounded-md px-3 py-1 ${view === "dashboard" ? "bg-[var(--surface-2)] font-semibold" : "text-ink2"}`}>Dashboard</button>
        <button onClick={() => setView("thresholds")} className={`rounded-md px-3 py-1 ${view === "thresholds" ? "bg-[var(--surface-2)] font-semibold" : "text-ink2"}`}>Thresholds & backtest</button>
      </nav>

      {view === "thresholds" ? <ThresholdsView /> : (
        <>
          {mode === "replay" && <ReplayPanel onSnapshot={setSnap} busy={busy} setBusy={setBusy} current={snap} />}
          {mode === "livecheck" && <LiveCheckPanel onSnapshot={setSnap} busy={busy} setBusy={setBusy} />}
          {err && <div role="alert" className="card border-[var(--critical)] p-3 text-sm">Could not load: {err}. The last good snapshot (if any) is still shown.</div>}
          {snap && (mode !== "livecheck" || snap.mode === "livecheck") && (mode !== "replay" || snap.mode !== "live") ? (
            <>
              <div className="grid gap-4 lg:grid-cols-3">
                <div className="space-y-4 lg:col-span-2">
                  <PanelBoundary name="Interpretation"><AIPanel snap={snap} /></PanelBoundary>
                  <PanelBoundary name="Threat breakdown"><ThreatPanel snap={snap} /></PanelBoundary>
                </div>
                <div className="space-y-4">
                  <PanelBoundary name="Alerts"><AlertsPanel snap={snap} /></PanelBoundary>
                  <PanelBoundary name="Decision"><DecisionPanel key={snap.snapshot_id} snap={snap} onRecorded={() => setRecordKey((k) => k + 1)} /></PanelBoundary>
                </div>
              </div>
              <PanelBoundary name="Timeline"><TimelinePanel snap={snap} /></PanelBoundary>
              <PanelBoundary name="Roads"><RoadsPanel snap={snap} /></PanelBoundary>
              <PanelBoundary name="Analogs"><AnalogsPanel snap={snap} /></PanelBoundary>
              <div className="grid gap-4 lg:grid-cols-2">
                <PanelBoundary name="Decision record"><RecordTimeline snap={snap} refreshKey={recordKey} onOpen={(id) => run(() => api.snapshot(id))} /></PanelBoundary>
                <PanelBoundary name="Raw data"><RawDataDrawer snap={snap} /></PanelBoundary>
              </div>
            </>
          ) : !err && mode === "live" ? (
            <div className="card h-64 animate-pulse" />
          ) : null}
        </>
      )}
      <footer className="pb-6 text-center text-xs text-muted">
        Closure Call · Hack Midwest 2026 USDA AI Challenge · Facility and roster are synthetic; weather, alerts and roads are real (NWS, Iowa Environmental Mesonet, Iowa DOT). Times shown in facility local time.
      </footer>
    </div>
  );
}
