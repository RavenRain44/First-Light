import type { Snapshot } from "../types";
import { evidenceState, evidenceWarning } from "../evidence";

/** "Insufficient current data" (or the limitations of a supported assessment), with what is missing and a recheck. */
export function EvidenceNotice({ snap, onRefresh, busy = false, compact = false }: {
  snap: Snapshot; onRefresh?: () => void; busy?: boolean; compact?: boolean;
}) {
  const s = evidenceState(snap);
  if (s.status === "sufficient") {
    return snap.mode === "live" && !s.mode_note?.startsWith("Demo") ? null
      : <p className="text-xs text-ink2" data-testid="evidence-mode">{s.mode_note}</p>;
  }
  const warn = evidenceWarning(s);
  const title = s.status === "not_recorded" ? "Evidence not recorded" : s.headline;
  const recheck = onRefresh && snap.mode === "live" && (
    <button onClick={onRefresh} disabled={busy} className="btn min-h-10 px-3 text-sm">{busy ? "Checking…" : "Check again for current data"}</button>
  );
  return (
    <section role={s.status === "insufficient" ? "alert" : "status"} data-testid="evidence-notice" data-status={s.status}
      className={`rounded-xl border-l-4 px-4 py-3 ${warn ? "border-[var(--danger)] bg-[var(--surface-2)]" : "border-[var(--outcome-mixed)] bg-[var(--surface-2)]"}`}>
      <p className={`${compact ? "text-base" : "text-lg"} font-semibold`}>{warn ? "⚠ " : ""}{title}</p>
      {s.provisional && <p className="mt-1 text-sm" data-testid="backup-source">Backup source: {s.forecast_sources?.join("; ") || "secondary forecast"}. This recommendation needs your review.</p>}
      {warn && s.status === "insufficient" && (
        <p className="mt-1 text-sm">The weather data needed to confirm conditions is missing or out of date. A "Normal" suggestion here is only the
          rules' fallback, not an all-clear. Missing data is not evidence that conditions are safe.</p>
      )}
      {s.hazard_evidence.length > 0 && (
        <p className="mt-1 text-sm">Known hazard evidence still applies: {s.hazard_evidence.join("; ")}.</p>
      )}
      {!compact && s.reasons.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-ink2">{s.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      )}
      {compact && (s.missing_sources.length > 0 || s.stale_sources.length > 0) && (
        <p className="mt-1 text-sm text-ink2">
          {s.missing_sources.length > 0 && <>Missing: {s.missing_sources.join(", ")}. </>}
          {s.stale_sources.length > 0 && <>Out of date: {s.stale_sources.join(", ")}.</>}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-3">
        {recheck}
        {s.mode_note && <span className="text-xs text-ink2">{s.mode_note}</span>}
        {(warn || s.reason_required) && <span className="text-xs text-ink2">{snap.mode === "backtest" ? "Review only; no decision is recorded." : "The manager makes the final decision. Recording a decision requires a reason."}</span>}
      </div>
    </section>
  );
}
