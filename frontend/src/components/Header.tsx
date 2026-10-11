import { useEffect, useRef, useState } from "react";
import type { Snapshot } from "../types";
import { Badge, fmtTime, readinessColor } from "../util";

export type Mode = "live" | "replay" | "livecheck";
export type View = "today" | "notifications" | "thresholds";

const TOOLS: { id: "replay" | "livecheck" | "thresholds"; label: string; hint: string }[] = [
  { id: "replay", label: "Replay a past storm", hint: "See what the system would have said during a real past event" },
  { id: "livecheck", label: "Try another location", hint: "Run a what-if check for an active alert anywhere in the US" },
  { id: "thresholds", label: "Thresholds & backtest", hint: "The weather limits behind each recommendation, and how they scored on past storms" },
];

export function Header({ snap, mode, setMode, view, setView, demo, theme, toggleTheme }: {
  snap: Snapshot | null; mode: Mode; setMode: (m: Mode) => void; view: View; setView: (v: View) => void;
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
  const tz = snap?.facility.timezone ?? "America/Chicago";

  return (
    <header className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button onClick={goToday} className="flex items-center gap-3 text-left" aria-label="Closure Call: go to today">
          {/* Logo by Casey (main), recolored to the blue/white theme */}
          <svg viewBox="0 0 40 40" className="h-9 w-9 shrink-0" aria-hidden="true" focusable="false">
            <circle cx="27" cy="12" r="6" fill="#93c5fd" />
            <path d="M27 2v2m0 16v2M17 12h2m16 0h2M20 5l1.5 1.5M33 18l1.5 1.5M34 5l-1.5 1.5" stroke="#93c5fd" strokeWidth="2" strokeLinecap="round" />
            <path d="M11 29a7 7 0 0 1-1-14 10 10 0 0 1 19-1 7.5 7.5 0 0 1 1 15Z" fill="#ffffff" stroke="#1d4ed8" strokeWidth="2" strokeLinejoin="round" />
            <path d="m14 33-1 3m8-3-1 3m8-3-1 3" stroke="#1d4ed8" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <span className="leading-tight">
            <span className="block text-base font-semibold">Closure Call</span>
            <span className="block text-xs text-muted">USDA Service Center, Ames, IA</span>
          </span>
        </button>

        <nav className="flex items-center gap-1 text-sm" aria-label="Main">
          <NavTab on={view === "today" && mode === "live"} onClick={goToday}>Today</NavTab>
          <NavTab on={view === "notifications"} onClick={() => setView("notifications")}
            dot={snap?.readiness ? readinessColor(snap.readiness.level) : undefined}
            title={snap?.readiness ? `Risk: Condition ${snap.readiness.level.toLowerCase()}` : undefined}>Notify staff</NavTab>
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
      {view === "today" && mode !== "live" && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-[var(--accent)] px-4 py-3 text-[var(--on-accent)]">
          <p className="font-semibold">
            {mode === "replay"
              ? `Viewing a past storm${snap?.mode === "replay" ? `: ${fmtTime(snap.as_of, tz)}` : ""}. This is not today's recommendation.`
              : `What-if check${snap?.mode === "livecheck" ? ` for ${snap.facility.name}` : ""}. This is not your facility's recommendation.`}
          </p>
          <button onClick={goToday} className="rounded-lg bg-[var(--surface-1)] px-3 py-1.5 text-sm font-semibold text-[var(--accent)]">Back to today</button>
        </div>
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
