import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { AIPanel } from "./components/AIPanel";
import { AlertsPanel } from "./components/AlertsPanel";
import { RelevantMetrics, SuggestedAction, useTimeseries } from "./components/DashboardCard";
import { DecisionLogView } from "./components/DecisionLogView";
import { NotificationsView } from "./components/NotificationsView";
import { PanelBoundary } from "./components/ErrorBoundary";
import { GlanceRow } from "./components/GlanceRow";
import { Header, type Mode, type View } from "./components/Header";
import { DecisionStep } from "./components/DecisionStep";
import { AnalogsPanel, RecordTimeline } from "./components/HistoryPanel";
import { LiveCheckPanel } from "./components/LiveCheckPanel";
import { ReplayPanel } from "./components/ReplayPanel";
import { RoadsPanel } from "./components/RoadsPanel";
import { PastDecisions, pastSummary, usePastDecisions } from "./components/PastDecisions";
import { RawDataDrawer } from "./components/RawDataDrawer";
import { TechnicalSummary } from "./components/TechnicalDetails";
import { CloudCopyPanel } from "./components/CloudCopyPanel";
import { ThreatPanel } from "./components/ThreatPanel";
import { ThresholdsView } from "./components/ThresholdsView";
import { TimelinePanel } from "./components/TimelinePanel";
import type { Snapshot } from "./types";
import { Section, Skeleton } from "./util";

type SectionId = "why" | "past" | "alerts" | "charts" | "roads" | "analogs" | "technical";

function initialTheme(): string {
  try {
    const t = localStorage.getItem("cc-theme");
    if (t) return t;
  } catch { /* storage blocked */ }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  const [mode, setMode] = useState<Mode>("live");
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const [snap, setSnap] = useState<Snapshot | null>(null);
  // Panels show the AI brief once its add-on record arrives; the snapshot itself is unchanged.
  const shown = useMemo(() => {
    // Show the newest finished AI brief; while a regeneration runs, keep showing the previous one.
    const a = snap?.ai_addon?.status === "ok" ? snap.ai_addon
      : snap?.ai_addon?.status === "pending" && snap.ai_addon.previous?.status === "ok" ? snap.ai_addon.previous : null;
    return snap && a?.ai
      ? { ...snap, analogs: snap.analogs_addon ?? snap.analogs, ai: a.ai, model_id: a.model_id ?? snap.model_id, prompt_version: a.prompt_version ?? snap.prompt_version }
      : snap && snap.analogs_addon ? {...snap, analogs: snap.analogs_addon} : snap;
  }, [snap]);
  const [aiEnabled, setAiEnabled] = useState(false);
  const regenerate = useCallback(async () => {
    if (!snap) return;
    const id = snap.snapshot_id, prev = snap.ai_addon ?? undefined;
    setSnap((s) => (s && s.snapshot_id === id ? { ...s, ai_addon: { status: "pending", previous: prev } } : s));
    try { await api.regenerateBrief(id); }
    catch { setSnap((s) => (s && s.snapshot_id === id ? { ...s, ai_addon: prev ?? { status: "failed" } } : s)); }
  }, [snap]);
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
          setSnap((s) => {
            if (!s || s.snapshot_id !== pendingId) return s;
            // A failed regeneration keeps the previous good brief on screen.
            const prev = s.ai_addon?.previous;
            const next = addon.status === "pending" ? { status: "failed" as const } : addon;
            return { ...s, ai_addon: next.status === "failed" && prev?.status === "ok" ? { ...prev, regen_failed: true } : next };
          });
        }
      } catch { /* keep the template brief */ }
    }, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [pendingId]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const requestVersion = useRef(0);
  const [demo, setDemo] = useState(false);
  const [theme, setTheme] = useState(initialTheme);
  const [recordKey, setRecordKey] = useState(0);
  const [view, setView] = useState<View>("today");
  const [savedWeather, setSavedWeather] = useState(false);
  const savedWeatherRef = useRef(false);
  const [savedDecisionId, setSavedDecisionId] = useState<number | null>(null);
  const [notificationDecision, setNotificationDecision] = useState<number | null>(null);
  const [open, setOpen] = useState<Set<SectionId>>(new Set());
  const toggle = (id: SectionId) => setOpen((o) => { const n = new Set(o); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const openSection = (id: SectionId) => {
    setOpen((o) => new Set(o).add(id));
    requestAnimationFrame(() => document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("cc-theme", theme); } catch { /* ignore */ }
  }, [theme]);

  useEffect(() => {
    api.health().then((h: any) => {
      setDemo(h.demo_mode);
      setAiEnabled(!!h.inference?.enabled);
    }).catch(() => {});
  }, []);

  const run = useCallback(async (fn: () => Promise<Snapshot>) => {
    const version = ++requestVersion.current;
    setBusy(true); setErr(null);
    try { const data = await fn(); if (version === requestVersion.current) {setSnap(data); setRecordKey((k) => k + 1);} }
    catch (e: any) { if(version === requestVersion.current) setErr(e.message ?? String(e)); }
    finally { if(version === requestVersion.current) {requestVersion.current++;setBusy(false);} }
  }, []);

  useEffect(() => {
    if (mode === "live" && !savedWeather) {
      let active=true;
      const version=requestVersion.current;
      api.latest().then(s=>{if(active && version===requestVersion.current && !savedWeatherRef.current) setSnap(s);}).catch(e=>active&&version===requestVersion.current&&setErr(e.message));
      return ()=>{active=false;};
    }
    else if (!savedWeather) setSnap(null);
  }, [mode, run, savedWeather]);

  // Keep the live view fresh. Cadence follows readiness (Red 10 min ... White 6 h), capped at 30 min
  // so a quiet dashboard still notices change; the backend only re-evaluates when its snapshot is stale.
  const recheck = Math.min(snap?.readiness?.recheck_minutes ?? 10, 30);
  // Paused on Notify staff so the snapshot can't change under a decision being confirmed or alerts being reviewed.
  useEffect(() => {
    if (mode !== "live" || view === "notifications" || savedWeather) return;
    let active=true;
    const t = setInterval(() => {const version=requestVersion.current;api.latest().then(s=>{if (active && version===requestVersion.current && !savedWeatherRef.current) setSnap(s);}).catch(() => {});}, recheck * 60 * 1000);
    return () => {active=false;clearInterval(t);};
  }, [mode, recheck, view, savedWeather]);

  const alertCount = shown?.inputs.filter((i) => i.kind === "alert").length ?? 0;
  // Past decisions compare against the weather being viewed (live, replay or a saved snapshot).
  const past = usePastDecisions(shown && shown.mode !== "livecheck" && !shown.facility.hypothetical ? shown : null);
  const viewDecisionWeather = (snapshotId: string, decisionId: number | null) => {
    setSnap(null); setErr(null); setMode('live');
    setSavedDecisionId(decisionId); savedWeatherRef.current = true; setSavedWeather(true); setView("today");
    run(() => api.snapshot(snapshotId)); window.scrollTo({ top: 0, behavior: "smooth" });
  };
  // Active alerts are the one detail section worth opening without being asked.
  useEffect(() => { if (alertCount) setOpen((o) => new Set(o).add("alerts")); }, [shown?.snapshot_id, alertCount]);
  const ready = snap && (mode !== "livecheck" || snap.mode === "livecheck") && (mode !== "replay" || snap.mode !== "live");
  const changeMode = (next: Mode) => {
    const changed = next !== mode || savedWeatherRef.current;
    if (changed) {requestVersion.current++;setBusy(false);}
    savedWeatherRef.current=false;setSavedWeather(false);setSavedDecisionId(null);setErr(null);
    if (next !== mode) setSnap(null);
    else if (next === 'live' && !snap && !changed) run(()=>api.latest());
    setMode(next);
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-3 sm:p-5">
      <Header snap={shown} mode={mode} setMode={changeMode} view={view} setView={(next)=>{if(next==='notifications'&&(mode!=='live'||savedWeather)){changeMode('live');setNotificationDecision(null);}setView(next);}} demo={demo} theme={theme}
        toggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")} />

      {savedWeather && <div role="status" className="card p-3 text-sm">Saved weather snapshot · {snap?.snapshot_id}. Live updates are paused while reviewing this record. <button className="btn ml-2" onClick={()=>{requestVersion.current++;setBusy(false);setSnap(null);savedWeatherRef.current=false;setSavedWeather(false);setMode('live');}}>Return to live weather</button></div>}
      {view === "notifications" ? (
        <div className="cc-fade space-y-5">
          {err && <div role="alert" className="card p-3 text-sm">Could not load the app: {err}. <button className="btn ml-2" onClick={()=>run(()=>api.latest())}>Retry</button></div>}
          {shown ? <PanelBoundary name="Decision"><DecisionStep snap={shown} onDecided={(id) => { setNotificationDecision(id); if (id) setRecordKey((k) => k + 1); }} /></PanelBoundary>
            : <Skeleton className="h-48" />}
          {notificationDecision !== null && <NotificationsView key={notificationDecision} decisionId={notificationDecision} onBack={() => setView("today")} />}
        </div>
      ) : view === "decisions" ? <DecisionLogView timezone={shown?.facility.timezone ?? "America/Chicago"} onSnapshot={viewDecisionWeather} /> : view === "thresholds" ? <div className="cc-fade"><ThresholdsView /></div> : (
        <>
          {mode === "replay" && <ReplayPanel onSnapshot={(s)=>{requestVersion.current++;savedWeatherRef.current=false;setSavedWeather(false);setSavedDecisionId(null);setSnap(s);}} busy={busy} setBusy={setBusy} current={snap} />}
          {mode === "livecheck" && <LiveCheckPanel onSnapshot={(s)=>{if(modeRef.current==='livecheck')setSnap(s);}} busy={busy} setBusy={setBusy} />}
          {err && <div role="alert" className="card border-l-4 border-l-[var(--danger)] p-3 text-sm">Could not load: {err}. The last good snapshot (if any) is still shown.</div>}
          {ready && shown ? (
            <div className="cc-stagger space-y-4">
              <PanelBoundary name="Suggested action"><SuggestedAction snap={shown} busy={busy} readOnly={savedWeather}
                onRefresh={mode === "live" && !savedWeather ? () => {savedWeatherRef.current=false;setSavedWeather(false);run(() => api.evaluateLive());} : undefined}
                onRegenerate={aiEnabled ? regenerate : undefined}
                onGoNotify={() => { setView("notifications"); window.scrollTo({ top: 0, behavior: "smooth" }); }} /></PanelBoundary>
              <PanelBoundary name="Relevant metrics"><RelevantMetrics snap={shown} /></PanelBoundary>
              <PanelBoundary name="At a glance"><GlanceRow snap={shown} historical={savedWeather} onOpen={openSection} /></PanelBoundary>

              <h2 className="px-1 pt-2 text-xs font-semibold uppercase tracking-[0.08em] text-muted">More detail, if you want it</h2>
              <Section id="why" title="Why this recommendation" open={open.has("why")} onToggle={() => toggle("why")}
                summary="The weather behind it, what would change it, and what to watch">
                <PanelBoundary name="Interpretation"><AIPanel snap={shown} onRegenerate={aiEnabled ? regenerate : undefined} /></PanelBoundary>
              </Section>
              {!shown.facility.hypothetical && (
                <Section id="past" title="Past decisions" open={open.has("past")} onToggle={() => toggle("past")} summary={pastSummary(past.rows)}>
                  <PanelBoundary name="Past decisions"><PastDecisions past={past} onViewWeather={viewDecisionWeather} /></PanelBoundary>
                </Section>
              )}
              <Section id="alerts" title="Weather alerts" open={open.has("alerts")} onToggle={() => toggle("alerts")}
                summary={alertCount ? `${alertCount} active: ${[...new Set(shown.inputs.filter((i) => i.kind === "alert").map((i) => (i.data as any)?.event))].join(", ")}` : shown.historical_context ? "Historical alert inputs unavailable" : "No active National Weather Service alerts"}>
                <PanelBoundary name="Alerts"><AlertsPanel snap={shown} /></PanelBoundary>
              </Section>
              <Section id="charts" title="Forecast charts" open={open.has("charts")} onToggle={() => toggle("charts")}
                summary={shown.historical_context?.requested_mode === "observation" ? "Archived observations before the selected time; forecast not supplied" : "Temperature, wind, ice, snow and precipitation: past 12 hours and next 48"}>
                <PanelBoundary name="Timeline"><AllCharts snap={shown} /></PanelBoundary>
              </Section>
              <Section id="roads" title="Roads map & cameras" open={open.has("roads")} onToggle={() => toggle("roads")}
                summary={mode === "live" && !savedWeather ? "Iowa DOT road conditions on commute routes, with live traffic cameras" : "Historical corridor evidence; camera images only where archived"}>
                <PanelBoundary name="Roads"><RoadsPanel snap={shown} historical={savedWeather} savedDecisionId={savedWeather ? savedDecisionId : null} /></PanelBoundary>
              </Section>
              {shown.analogs.length > 0 && (
                <Section id="analogs" title="Similar past storms" open={open.has("analogs")} onToggle={() => toggle("analogs")}
                  summary={`Closest: ${shown.analogs[0].name} (${shown.analogs[0].similarity_pct.toFixed(0)}% similar)`}>
                  <PanelBoundary name="Analogs"><AnalogsPanel snap={shown} /></PanelBoundary>
                </Section>
              )}
              <Section id="technical" title="Technical details & decision record" innerTitles open={open.has("technical")} onToggle={() => toggle("technical")}
                summary="Hazard scores, confidence factors, past decisions, cloud copy and raw data sources">
                <PanelBoundary name="Technical summary"><TechnicalSummary snap={shown} /></PanelBoundary>
                <PanelBoundary name="Threat breakdown"><ThreatPanel snap={shown} /></PanelBoundary>
                <PanelBoundary name="Decision record"><RecordTimeline snap={shown} refreshKey={recordKey} onOpen={(id) => viewDecisionWeather(id,null)} /></PanelBoundary>
                <PanelBoundary name="Cloud copy"><CloudCopyPanel snap={shown} refreshKey={recordKey} /></PanelBoundary>
                <PanelBoundary name="Raw data"><RawDataDrawer snap={shown} /></PanelBoundary>
              </Section>
            </div>
          ) : !err && mode === "live" ? (
            <div className="space-y-4"><Skeleton className="h-64" /><Skeleton className="h-28" /></div>
          ) : null}
        </>
      )}
      <footer className="pb-6 text-center text-xs text-muted">
        Closure Call · Hack Midwest 2026 USDA AI Challenge · Facility and roster are synthetic; weather, alerts and roads are real (NWS, Iowa Environmental Mesonet, Iowa DOT). Times shown in facility local time.
      </footer>
    </div>
  );
}

/** All weather charts; the timeseries is fetched only once this section is opened (and shared). */
function AllCharts({ snap }: { snap: Snapshot }) {
  const { data, error } = useTimeseries(snap, true);
  if (error) return <p className="text-sm text-ink2">Chart data could not be loaded: {error}</p>;
  return data ? <TimelinePanel snap={snap} data={data} /> : <Skeleton className="h-60" />;
}
