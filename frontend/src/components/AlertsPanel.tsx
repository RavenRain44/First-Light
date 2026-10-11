import type { Snapshot } from "../types";
import { Badge, Card, Prov, fmtTime } from "../util";

const SEV_TONE: Record<string, "bad" | "warn" | "neutral" | "info"> = { Extreme: "bad", Severe: "bad", Moderate: "warn", Minor: "neutral" };

export function AlertsPanel({ snap }: { snap: Snapshot }) {
  const tz = snap.facility.timezone;
  const inputs = snap.inputs.filter((i) => i.kind === "alert");
  const none = snap.inputs.find((i) => i.id === "alert:none");
  const status = snap.sources.find((s) => s.adapter === "nws_alerts" || s.adapter === "iem_vtec");
  return (
    <Card title="Active NWS alerts" right={<span className="text-xs text-muted">{status?.label}</span>}>
      {status && status.status === "unavailable" && (
        <p className="rounded-md bg-[var(--surface-2)] p-2 text-sm">Alert source unavailable: {status.detail}. Confidence is reduced.</p>
      )}
      {inputs.length === 0 && snap.historical_context && <p className="text-sm text-muted">No alert inputs were supplied for this historical reconstruction. This does not establish that no alerts existed.</p>}
      {inputs.length === 0 && none && (
        <p className="text-sm text-ink2">
          <Prov tz={tz} source={none.source} url={none.source_url} fetched={none.fetched_at} note={none.note}>No active alerts</Prov> for this location.
        </p>
      )}
      <div className="space-y-3">
        {inputs.map((inp) => {
          const a = inp.data as any;
          const summary = snap.ai.alert_summaries?.[a.id];
          return (
            <article key={inp.id} className="cc-rise rounded-xl border border-edge p-3">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold">
                  <Prov tz={tz} source={inp.source} url={a.web ?? inp.source_url} fetched={inp.fetched_at} sourceTime={inp.source_time} note={inp.note}>{a.event}</Prov>
                </h3>
                {a.severity && <Badge tone={SEV_TONE[a.severity] ?? "neutral"}>{a.severity}</Badge>}
                {a.inferred_fields && <Badge tone="warn" title="The VTEC archive has no CAP fields; these are inferred from the warning/watch/advisory significance code.">inferred</Badge>}
              </div>
              <p className="mt-1 text-sm tabnum text-ink2">
                From {fmtTime(a.onset ?? a.effective, tz)} until {a.ends || a.expires ? fmtTime(a.ends ?? a.expires, tz) : "further notice"}
                {a.archive_note && <span className="italic"> ({a.archive_note})</span>}
              </p>
              {summary && <p className="mt-1 text-sm">{summary}</p>}
              {(a.headline || a.description || a.instruction) && (
                <details className="mt-2 text-sm">
                  <summary className="text-ink2">Full alert text</summary>
                  {a.headline && <p className="mt-1 font-medium">{a.headline}</p>}
                  <p className="mt-1 text-xs text-muted">Severity {a.severity ?? "?"} · certainty {a.certainty ?? "?"} · urgency {a.urgency ?? "?"}</p>
                  {a.description && <pre className="mt-1 whitespace-pre-wrap font-sans text-ink2">{a.description}</pre>}
                  {a.instruction && <pre className="mt-1 whitespace-pre-wrap font-sans">{a.instruction}</pre>}
                </details>
              )}
            </article>
          );
        })}
      </div>
    </Card>
  );
}
