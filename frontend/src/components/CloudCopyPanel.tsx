import { useEffect, useState } from "react";
import { api, type StorageLinks, type StorageStatus } from "../api";
import type { Snapshot } from "../types";
import { Badge, Card, fmtTime } from "../util";

/** What's mirrored to Akamai Object Storage for this snapshot: the log, chart data and decision camera stills. */
export function CloudCopyPanel({ snap, refreshKey }: { snap: Snapshot; refreshKey: number }) {
  const [status, setStatus] = useState<StorageStatus | null>(null);
  const [links, setLinks] = useState<StorageLinks | null>(null);
  const tz = snap.facility.timezone;

  useEffect(() => {
    let live = true;
    // New decisions reach the bucket a few seconds after they're recorded, so look again shortly after.
    const load = () => api.storageStatus().then(async (s) => {
      if (!live) return;
      setStatus(s);
      if (s.enabled) { const l = await api.storageRecord(snap.snapshot_id); if (live) setLinks(l); }
    }).catch(() => live && setStatus(null));
    load();
    const t = window.setTimeout(load, 6000);
    return () => { live = false; window.clearTimeout(t); };
  }, [snap.snapshot_id, refreshKey]);

  if (!status) return null;
  if (!status.enabled) {
    return (
      <Card title="Cloud copy">
        <p className="text-sm text-ink2">Off. Records are kept in this server's database only. Set the <code>OBJ_*</code> values in <code>.env</code> to mirror logs, chart data and decision camera stills to Akamai Object Storage.</p>
      </Card>
    );
  }
  const sets = links?.camera_sets ?? [];
  return (
    <Card title="Cloud copy" right={<Badge tone={status.last_error ? "warn" : "info"}>{status.last_error ? "⚠ Sync retrying" : "Akamai Object Storage"}</Badge>}>
      <div className="space-y-3 text-sm">
        <p className="text-ink2">
          Mirrored to bucket <span className="font-medium">{status.bucket}</span>
          {status.last_sync && <> · last sync {fmtTime(status.last_sync, tz)}</>}
          {status.backup && <> · database backed up {fmtTime(status.backup, tz)}</>}
        </p>
        {status.last_error && <p className="text-xs text-muted">{status.last_error}. The app keeps working; the next sync catches up.</p>}
        {links?.error && <p className="text-xs text-muted">{links.error}</p>}
        <div className="flex flex-wrap gap-2">
          {links?.log_url ? <a className="btn" href={links.log_url} target="_blank" rel="noreferrer">Snapshot log (JSON)</a>
            : <span className="text-xs text-muted">This snapshot hasn't synced yet.</span>}
          {links?.graph_url && <a className="btn" href={links.graph_url} target="_blank" rel="noreferrer">Chart data (JSON)</a>}
        </div>
        {sets.map((s) => (
          <div key={s.decision_id} className="space-y-2">
            <p className="text-xs text-muted">Road cameras saved with decision #{s.decision_id}{s.captured_at && <> · {fmtTime(s.captured_at, tz)}</>}</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {s.images.map((i) => (
                <a key={i.key} href={i.url} target="_blank" rel="noreferrer" className="group block overflow-hidden rounded-lg border border-edge">
                  <img src={i.url} alt={`${i.camera}, ${i.view ?? ""}`} loading="lazy" className="aspect-video w-full object-cover transition-transform group-hover:scale-[1.03]" />
                  <span className="block truncate px-2 py-1 text-xs text-ink2">{i.camera}{i.time && <> · {fmtTime(i.time, tz)}</>}</span>
                </a>
              ))}
            </div>
          </div>
        ))}
        <p className="text-xs text-muted">Links are signed and expire after {Math.round((links?.expires_in ?? 3600) / 60)} minutes; the bucket itself stays private.</p>
      </div>
    </Card>
  );
}
