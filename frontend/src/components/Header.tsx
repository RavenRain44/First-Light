import { useEffect, useRef, useState } from "react";
import type { Facility, Snapshot } from "../types";
import { facilityLabel } from "../facility";
import { Badge, readinessColor } from "../util";

export type Mode = "live" | "replay" | "livecheck";
export type View = "today" | "notifications" | "decisions" | "thresholds";

const TOOLS: { id: "replay" | "thresholds"; label: string; hint: string }[] = [
  { id: "replay", label: "Replay a past storm", hint: "See what the system would have said during a real past event" },
  { id: "thresholds", label: "Thresholds & backtest", hint: "The weather limits behind each recommendation, and how they scored on past storms" },
];

export function Header({ snap, mode, setMode, view, setView, demo, theme, toggleTheme, facility, facilities, onFacilityChange }: {
  snap: Snapshot | null; mode: Mode; setMode: (m: Mode) => void; view: View; setView: (v: View) => void;
  facility: Facility; facilities: Facility[]; onFacilityChange: (id: string) => void;
  demo: boolean; theme: string; toggleTheme: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !menuRef.current?.contains(e.target as Node)) setMenu(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", close); };
  }, [menu]);

  const openTool = (id: (typeof TOOLS)[number]["id"]) => {
    setMenu(false);
    if (id === "thresholds") setView("thresholds");
    else { setView("today"); setMode(id); }
  };
  const goToday = () => { setMode("live"); setView("today"); };

  return (
    <header className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-3">
        <button onClick={goToday} className="flex items-center gap-3 text-left" aria-label="Closure Call: go to today">
          <img src="/closure-call-mark.svg" alt="" width="40" height="40" className="h-10 w-10 shrink-0" />
          <span className="leading-tight">
            <span className="block text-base font-semibold">Closure Call</span>
            <span className="block text-xs text-muted">{facility.name}</span>
          </span>
        </button>
        <label className="grid gap-1 text-xs text-muted">
          <span>Facility</span>
          <select aria-label="Facility" value={facility.id} onChange={e => onFacilityChange(e.target.value)}
            className="min-h-[44px] max-w-full rounded-lg border border-edge bg-surface px-3 text-sm font-semibold text-ink">
            {facilities.map(f => <option key={f.id} value={f.id}>{facilityLabel(f)}</option>)}
          </select>
        </label>
        </div>

        <nav className="flex items-center gap-1 text-sm" aria-label="Main">
          <NavTab on={view === "today" && mode === "live"} onClick={goToday}>Today</NavTab>
          <NavTab on={view === "notifications"} onClick={() => setView("notifications")}
            dot={snap?.readiness ? readinessColor(snap.readiness.level) : undefined}
            title={snap?.readiness ? `Risk: Condition ${snap.readiness.level.toLowerCase()}` : undefined}>Notify staff</NavTab>
          <NavTab on={view === "decisions"} onClick={() => setView("decisions")}>Decision log</NavTab>
          <div ref={menuRef} className="relative">
            <button onClick={() => setMenu((m) => !m)} aria-haspopup="menu" aria-expanded={menu}
              className={`rounded-lg px-3 py-2 ${mode !== "live" || view === "thresholds" ? "font-semibold text-[var(--accent)]" : "text-ink2 hover:text-ink"}`}>
              More tools <span aria-hidden className="text-xs">▾</span>
            </button>
            {menu && (
              <div role="menu" className="cc-rise absolute right-0 z-[1000] mt-1 w-72 rounded-xl border border-edge bg-surface p-1 shadow-lg">
                {TOOLS.map((t) => (
                  <button key={t.id} role="menuitem" onClick={() => openTool(t.id)}
                    className="block w-full rounded-lg px-3 py-2 text-left hover:bg-[var(--surface-2)]">
                    <span className="block font-medium">{t.label}</span>
                    <span className="block text-xs text-muted">{t.hint}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <button onClick={toggleTheme} className="btn ml-1" aria-label="Toggle dark mode">{theme === "dark" ? "☀" : "☾"}</button>
        </nav>
      </div>

      {demo && (
        <p className="text-xs text-muted"><Badge tone="warn" title="DEMO_MODE=true: sources served from cached fixtures">Demo mode</Badge> Weather and roads come from saved data, not live feeds.</p>
      )}

    </header>
  );
}

function NavTab({ on, onClick, children, dot, title }: { on: boolean; onClick: () => void; children: string; dot?: string; title?: string }) {
  return (
    <button onClick={onClick} aria-current={on ? "page" : undefined} title={title}
      className={`flex items-center gap-2 rounded-lg px-3 py-2 ${on ? "bg-[var(--tint)] font-semibold text-[var(--accent)]" : "text-ink2 hover:text-ink"}`}>
      {dot && <span aria-hidden className="h-2.5 w-2.5 rounded-full border border-black/20" style={{ background: dot }} />}
      {children}
    </button>
  );
}
