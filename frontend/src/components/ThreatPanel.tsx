import { useState } from "react";
import type { RuleResult, Snapshot } from "../types";
import { AnimatedNumber, Badge, Card, PostureBadge, Prov, fmtTime, fmtVal } from "../util";

const LEVEL_TONE: Record<string, "neutral" | "warn" | "bad"> = { none: "neutral", minor: "warn", significant: "bad", extreme: "bad" };

export function ThreatPanel({ snap }: { snap: Snapshot }) {
  const [open, setOpen] = useState<string | null>(null);
  const tz = snap.facility.timezone;
  const inputsById = Object.fromEntries(snap.inputs.map((i) => [i.id, i]));
  return (
    <Card title="Hazard scores" right={<span className="text-xs text-muted">thresholds v{snap.thresholds_version} · {snap.thresholds_sha256.slice(0, 10)}</span>}>
      <div className="grid gap-6 lg:grid-cols-3 lg:gap-0 lg:divide-x lg:divide-[var(--border)]">
        {Object.values(snap.hazards).sort((a, b) => b.score - a.score).map((h) => {
          const rules = snap.rules.filter((r) => r.hazard === h.hazard);
          const trig = rules.filter((r) => r.triggered).sort((a, b) => b.level - a.level || b.score - a.score);
          const near = rules.filter((r) => !r.triggered && r.available && typeof r.observed_value === "number" && r.margin_pct !== null && r.margin_pct > -40);
          return (
            <div key={h.hazard} className="min-w-0 lg:px-5 lg:first:pl-0 lg:last:pr-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold">{h.label}</h3>
                  <Badge tone={LEVEL_TONE[h.level_name]}>{h.level_name}</Badge>
                  {h.level > 0 && <PostureBadge p={h.posture} size="sm" />}
                </div>
                <span className="tabnum text-sm font-semibold"><AnimatedNumber value={h.score} /><span className="font-normal text-muted">/100</span></span>
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-[var(--surface-2)]" role="meter" aria-valuenow={h.score} aria-valuemin={0} aria-valuemax={100} aria-label={`${h.label} score`}>
                <div className="cc-bar h-full rounded-full" style={{ width: `${Math.max(h.score, 2)}%`, background: h.level >= 3 ? "var(--b6)" : h.level === 2 ? "var(--b4)" : h.level === 1 ? "var(--b3)" : "var(--b2)" }} />
              </div>
              {h.level > 0 && (
                <p className="mt-1 text-xs text-ink2">
                  {h.posture_reason}. Peak {fmtTime(h.time_of_peak, tz)}.
                </p>
              )}
              <ul className="mt-2 space-y-1">
                {trig.map((r) => <RuleRow key={r.rule_id} r={r} tz={tz} open={open === r.rule_id} toggle={() => setOpen(open === r.rule_id ? null : r.rule_id)} inputsById={inputsById} />)}
                {near.map((r) => <RuleRow key={r.rule_id} r={r} tz={tz} open={open === r.rule_id} toggle={() => setOpen(open === r.rule_id ? null : r.rule_id)} inputsById={inputsById} />)}
                {!trig.length && !near.length && <li className="text-xs text-muted">No thresholds crossed or approached.</li>}
              </ul>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function RuleRow({ r, tz, open, toggle, inputsById }: { r: RuleResult; tz: string; open: boolean; toggle: () => void; inputsById: Record<string, any> }) {
  const first = inputsById[r.input_ids[0]];
  const isAlert = r.metric === "alert_present";
  return (
    <li className={`rounded-lg border ${r.triggered ? "border-edge" : "border-dashed border-edge opacity-75"}`}>
      <button onClick={toggle} aria-expanded={open} className="flex w-full flex-wrap items-center justify-between gap-2 px-2 py-1.5 text-left text-sm hover:bg-[var(--surface-2)]">
        <span className="flex items-center gap-2">
          <span aria-hidden className={`inline-block text-[10px] transition-transform duration-300 ${open ? "rotate-180" : ""}`}>{r.triggered ? "▲" : "△"}</span>
          <span className={r.triggered ? "font-medium" : ""}>{isAlert ? r.observed_value : r.label}</span>
          {!r.verified && <Badge tone="warn" title="Threshold value not verified against a primary source">⚠ unverified</Badge>}
          <Badge>{r.posture_effect}</Badge>
        </span>
        <span className="tabnum text-xs text-ink2">
          {isAlert ? (r.triggered ? "in effect" : "not in effect") : (
            <>
              {first ? <Prov tz={tz} source={first.source} url={first.source_url} fetched={first.fetched_at} sourceTime={first.source_time} note={first.note}>{fmtVal(r.observed_value, r.unit)}</Prov> : fmtVal(r.observed_value, r.unit)}
              {" "}{({">=": "≥", "<=": "≤"} as Record<string, string>)[r.operator] ?? r.operator} {fmtVal(r.threshold, r.unit)}
              {r.margin_abs !== null && <> · margin {r.margin_abs > 0 ? "+" : ""}{fmtVal(r.margin_abs, r.unit === "rank" || r.unit.startsWith("SPC") ? "" : r.unit)}{r.margin_pct !== null ? ` (${r.margin_pct > 0 ? "+" : ""}${r.margin_pct.toFixed(0)}%)` : ""}</>}
            </>
          )}
        </span>
      </button>
      <div className="cc-collapse" data-open={open} aria-hidden={!open}>
        <div><div className="space-y-1 border-t border-edge px-3 py-2 text-xs text-ink2">
          <p><span className="font-semibold text-ink">Anchor:</span> {r.anchor}</p>
          <p><span className="font-semibold text-ink">Source:</span> <a className="break-all underline" href={r.source_url} target="_blank" rel="noreferrer">{r.source_url}</a> · basis: {r.basis} · {r.verified ? "verified against source" : "NOT verified"}</p>
          <p><span className="font-semibold text-ink">Window:</span> {r.time_window}{r.window_start ? ` · exceeded ${fmtTime(r.window_start, tz)} → ${fmtTime(r.window_end, tz)}` : ""}</p>
          {r.detail && <p><span className="font-semibold text-ink">Detail:</span> {r.detail}</p>}
          <p><span className="font-semibold text-ink">Inputs:</span> {r.input_ids.join(", ") || "—"} · rule id <code>{r.rule_id}</code></p>
        </div></div>
      </div>
    </li>
  );
}
