import type { ReactNode } from "react";
import type { Snapshot } from "../types";
import { Badge, PostureBadge, ReadinessMeter, ago, fmtTime } from "../util";

export type Mode = "live" | "replay" | "livecheck";

const MODES: { id: Mode; label: string }[] = [
  { id: "live", label: "Live" }, { id: "replay", label: "Replay" }, { id: "livecheck", label: "Live Check" },
];

export function Header({ snap, mode, setMode, onRefresh, busy, demo, theme, toggleTheme, showSummary = true }: {
  snap: Snapshot | null; mode: Mode; setMode: (m: Mode) => void; onRefresh: () => void; busy: boolean;
  demo: boolean; theme: string; toggleTheme: () => void;
  showSummary?: boolean;
}) {
  const tz = snap?.facility.timezone ?? "America/Chicago";
  const ok = snap?.sources.filter((s) => s.status === "ok" || s.status === "empty").length ?? 0;
  const total = snap?.sources.length ?? 0;
  const na = snap?.sources.filter((s) => s.status === "not_applicable").length ?? 0;
  const newest = snap?.sources.map((s) => s.fetched_at).filter(Boolean).sort().at(-1) ?? null;
  const roster = snap?.roster;

  return (
    <header className="space-y-3">
      {/* top bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <img src="/logo.png" alt="" className="app-logo h-10 w-auto shrink-0" />
          <div className="leading-tight">
            <h1 className="text-base font-semibold">Closure Call</h1>
            <p className="text-xs text-muted">USDA Service Center (synthetic), Ames, IA · real weather</p>
          </div>
          {demo && <Badge tone="warn" title="DEMO_MODE=true: sources served from cached fixtures">Demo mode · cached data</Badge>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div role="tablist" aria-label="Mode" className="flex rounded-xl bg-[var(--surface-2)] p-1 text-sm">
            {MODES.map((m) => (
              <button key={m.id} role="tab" aria-selected={mode === m.id} onClick={() => setMode(m.id)}
                className={`rounded-lg px-3 py-1 transition-colors ${mode === m.id ? "bg-[var(--surface-1)] font-semibold text-[var(--accent)] shadow-sm" : "text-ink2 hover:text-ink"}`}>
                {m.label}
              </button>
            ))}
          </div>
          {mode === "live" && <button onClick={onRefresh} disabled={busy} className="btn">{busy ? "Evaluating…" : "Re-evaluate"}</button>}
          <button onClick={toggleTheme} className="btn" aria-label="Toggle dark mode">{theme === "dark" ? "☀" : "☾"}</button>
        </div>
      </div>

      {/* decision strip */}
      {showSummary && <section className="card p-5" aria-label="Current recommendation">
        {!snap ? <div className="h-24 animate-pulse rounded-xl bg-[var(--surface-2)]" /> : (
          <>
            {snap.facility.hypothetical && (
              <p className="mb-3 text-sm font-medium text-[var(--accent)]">{snap.facility.name} (what-if)</p>
            )}
            <div className="grid gap-5 md:grid-cols-[1.4fr_1fr_1.2fr] md:items-center">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">Recommended for {fmtDay(snap.posture.decision_day)}</p>
                <div className="mt-2"><PostureBadge p={snap.posture.posture} size="lg" /></div>
                <p className="mt-2 text-sm text-ink2">OPM: {snap.posture.opm_label}</p>
              </div>
              <div className="md:border-l md:border-edge md:pl-5">
                {snap.readiness ? <ReadinessMeter r={snap.readiness} tz={tz} /> : <span className="text-sm text-muted">Readiness not recorded for this snapshot</span>}
              </div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm md:border-l md:border-edge md:pl-5">
                <Fact label="As of"><span className="tabnum">{fmtTime(snap.as_of, tz)}</span></Fact>
                <Fact label="Confidence">
                  <span title={snap.confidence.factors.map((f) => `${f.name}: ${f.score} - ${f.explanation}`).join("\n")} className="cursor-help">
                    <span className="capitalize">{snap.confidence.level}</span> <span className="tabnum text-muted">{snap.confidence.score.toFixed(2)}</span>
                  </span>
                </Fact>
                <Fact label="Sources">
                  <span title={snap.sources.map((s) => `${s.label}: ${s.status}${s.detail ? ` (${s.detail})` : ""}`).join("\n")} className="cursor-help tabnum">
                    {ok}/{total}{na ? ` · ${na} n/a` : ""} <span className="text-muted">· {ago(newest)}</span>
                  </span>
                </Fact>
                {roster && !roster.hypothetical ? (
                  <Fact label={roster.day ? `In building ${fmtDay(roster.day)}` : "In building today"}>
                    <span className="tabnum" title={`Assigned ${roster.assigned}; detailed in ${roster.detailed_in}; detailed out ${roster.detailed_out}; on travel ${roster.on_travel}; teleworking ${roster.teleworking_today}; on leave ${roster.on_leave ?? 0}; not scheduled ${roster.not_scheduled ?? 0}. Synthetic roster.`}>
                      {roster.expected_in_building} of {roster.assigned}
                    </span>
                    <span className="block text-xs font-normal text-muted">
                      {[roster.detailed_in && `+${roster.detailed_in} in`, roster.detailed_out && `${roster.detailed_out} detailed out`,
                        roster.on_travel && `${roster.on_travel} travel`, roster.teleworking_today && `${roster.teleworking_today} telework`,
                        roster.on_leave && `${roster.on_leave} leave`, roster.not_scheduled && `${roster.not_scheduled} off`]
                        .filter(Boolean).join(" · ") || "everyone on site"}
                    </span>
                  </Fact>
                ) : <Fact label="Mode">{snap.mode}</Fact>}
              </dl>
            </div>
            {(snap.mode === "replay" || snap.mode === "backtest") && (
              <p className="mt-4 rounded-lg bg-[var(--tint)] px-3 py-1.5 text-xs text-[var(--accent)]">Replay: only data that was available at this moment is used.</p>
            )}
          </>
        )}
      </section>}
    </header>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-medium">{children}</dd>
    </div>
  );
}

function fmtDay(d: string) {
  const [y, m, day] = d.split("-").map(Number);
  return new Date(y, m - 1, day).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}
