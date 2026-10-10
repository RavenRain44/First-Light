import type { Snapshot } from "../types";
import { Badge, CONF_TONE, PostureBadge, ReadinessMeter, ago, fmtTime } from "../util";

export type Mode = "live" | "replay" | "livecheck";

export function Header({ snap, mode, setMode, onRefresh, busy, demo, theme, toggleTheme }: {
  snap: Snapshot | null; mode: Mode; setMode: (m: Mode) => void; onRefresh: () => void; busy: boolean;
  demo: boolean; theme: string; toggleTheme: () => void;
}) {
  const tz = snap?.facility.timezone ?? "America/Chicago";
  const ok = snap?.sources.filter((s) => s.status === "ok" || s.status === "empty").length ?? 0;
  const total = snap?.sources.length ?? 0;
  const na = snap?.sources.filter((s) => s.status === "not_applicable").length ?? 0;
  const newest = snap?.sources.map((s) => s.fetched_at).filter(Boolean).sort().at(-1) ?? null;
  const roster = snap?.roster;
  return (
    <header className="card p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-bold">Closure Call</h1>
            <span className="text-sm text-ink2">Weather decision support</span>
            {demo && <Badge tone="warn" title="DEMO_MODE=true: sources served from cached fixtures">Demo mode (cached data)</Badge>}
          </div>
          <label className="mt-2 flex items-center gap-2 text-sm">
            <span className="text-ink2">Facility</span>
            <select className="rounded-md border border-edge bg-surface px-2 py-1" value={snap?.facility.id ?? "IA-AMES-SC"} disabled>
              <option value="IA-AMES-SC">USDA Service Center (synthetic), Ames, IA</option>
            </select>
          </label>
          {snap?.facility.hypothetical && <p className="mt-1 text-sm font-semibold text-[var(--serious)]">{snap.facility.name}</p>}
          <p className="mt-1 text-xs text-muted">Synthetic facility and roster for demonstration. Weather data is real.</p>
        </div>

        <div className="flex flex-col items-start gap-2 sm:items-end">
          {snap ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs uppercase tracking-wide text-ink2">Recommended for {fmtDay(snap.posture.decision_day)}</span>
              </div>
              <PostureBadge p={snap.posture.posture} size="lg" />
              <div className="max-w-md text-right text-xs text-ink2">OPM: {snap.posture.opm_label}</div>
              {snap.readiness && <ReadinessMeter r={snap.readiness} tz={tz} />}
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={CONF_TONE[snap.confidence.level]} title={snap.confidence.factors.map((f) => `${f.name}: ${f.score} - ${f.explanation}`).join("\n")}>
                  Confidence: {snap.confidence.level} ({snap.confidence.score.toFixed(2)})
                </Badge>
                <Badge tone="neutral" title={snap.sources.map((s) => `${s.label}: ${s.status}${s.detail ? ` (${s.detail})` : ""}`).join("\n")}>
                  Sources {ok}/{total}{na ? ` (${na} n/a here)` : ""} · newest fetch {ago(newest)}
                </Badge>
              </div>
            </>
          ) : (
            <div className="h-24 w-64 animate-pulse rounded-lg bg-[var(--surface-2)]" />
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-edge pt-3">
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <span>As of <strong className="tabnum">{snap ? fmtTime(snap.as_of, tz) : "—"}</strong></span>
          {snap?.mode === "replay" || snap?.mode === "backtest" ? <Badge tone="info">Replay: data available at that moment only</Badge> : null}
          {roster && !roster.hypothetical && (
            <span title={`Assigned ${roster.assigned}; detailed in ${roster.detailed_in}; detailed out ${roster.detailed_out}; on travel ${roster.on_travel}; teleworking ${roster.teleworking_today}`}>
              Expected in building today: <strong className="tabnum">{roster.expected_in_building} of {roster.assigned}</strong> assigned
              <span className="text-ink2"> (+{roster.detailed_in} detailed in, {roster.detailed_out} out, {roster.on_travel} travel, {roster.teleworking_today} telework)</span>
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div role="tablist" aria-label="Mode" className="flex rounded-lg border border-edge p-0.5 text-sm">
            {(["live", "replay", "livecheck"] as Mode[]).map((m) => (
              <button key={m} role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
                className={`rounded-md px-3 py-1 ${mode === m ? "bg-[var(--series-1)] text-white" : "text-ink2 hover:bg-[var(--surface-2)]"}`}>
                {m === "live" ? "Live" : m === "replay" ? "Replay" : "Live Check"}
              </button>
            ))}
          </div>
          {mode === "live" && (
            <button onClick={onRefresh} disabled={busy} className="rounded-lg border border-edge px-3 py-1 text-sm hover:bg-[var(--surface-2)] disabled:opacity-50">
              {busy ? "Evaluating…" : "Re-evaluate now"}
            </button>
          )}
          <button onClick={toggleTheme} className="rounded-lg border border-edge px-2 py-1 text-sm" aria-label="Toggle dark mode">
            {theme === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
        </div>
      </div>
    </header>
  );
}

function fmtDay(d: string) {
  const [y, m, day] = d.split("-").map(Number);
  return new Date(y, m - 1, day).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}
