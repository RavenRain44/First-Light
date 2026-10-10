import type { ReactNode } from "react";
import type { Posture } from "./types";

export const POSTURES: Posture[] = ["NORMAL", "DELAYED_ARRIVAL", "EARLY_DISMISSAL", "TELEWORK", "CLOSED"];

/** One posture -> one color everywhere. Always shown with its text label, never color alone. */
export const POSTURE_STYLE: Record<Posture, { label: string; color: string; icon: string; ink: string }> = {
  NORMAL: { label: "Normal", color: "var(--good)", icon: "✓", ink: "#ffffff" },
  DELAYED_ARRIVAL: { label: "Delayed arrival", color: "var(--warning)", icon: "◷", ink: "#0b0b0b" },
  EARLY_DISMISSAL: { label: "Early dismissal", color: "var(--serious)", icon: "↧", ink: "#0b0b0b" },
  TELEWORK: { label: "Telework / unscheduled leave", color: "var(--telework)", icon: "⌂", ink: "#ffffff" },
  CLOSED: { label: "Closed", color: "var(--critical)", icon: "✕", ink: "#ffffff" },
};

export function fmtTime(iso: string | null | undefined, tz: string, opts: { date?: boolean } = { date: true }): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const s = d.toLocaleString("en-US", {
    timeZone: tz,
    weekday: opts.date ? "short" : undefined,
    month: opts.date ? "short" : undefined,
    day: opts.date ? "numeric" : undefined,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZoneName: "short",
  });
  return s;
}

export function ago(iso: string | null | undefined, ref: Date = new Date()): string {
  if (!iso) return "unknown";
  const mins = Math.round((ref.getTime() - new Date(iso).getTime()) / 60000);
  if (Math.abs(mins) < 1) return "just now";
  if (Math.abs(mins) < 90) return `${mins} min ago`;
  const h = mins / 60;
  if (Math.abs(h) < 48) return `${h.toFixed(1)} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

export function fmtVal(v: number | string | null | undefined, unit?: string | null): string {
  if (v === null || v === undefined) return "n/a";
  if (typeof v === "string") return v;
  switch (unit) {
    case "in": return `${v.toFixed(2)} in`;
    case "mph": return `${v.toFixed(0)} mph`;
    case "degF": return `${v.toFixed(0)}°F`;
    case "%": return `${v.toFixed(0)}%`;
    case "rank": return RANK[v] ?? String(v);
    default:
      if (unit?.startsWith("SPC")) return SPC[v] ?? String(v);
      return `${Number.isInteger(v) ? v : v.toFixed(2)}${unit ? ` ${unit}` : ""}`;
  }
}

const RANK: Record<number, string> = { 0: "Normal", 1: "Wet/frost", 2: "Partially covered", 3: "Completely covered", 4: "Travel advisory", 5: "Not advised / closed" };
const SPC: Record<number, string> = { [-1]: "None", 0: "TSTM", 1: "MRGL", 2: "SLGT", 3: "ENH", 4: "MDT", 5: "HIGH" };

/** A value with a hover/focus tooltip naming its source and timestamps. */
export function Prov({ children, source, url, fetched, sourceTime, tz, note }: {
  children: ReactNode; source?: string | null; url?: string | null; fetched?: string | null;
  sourceTime?: string | null; tz: string; note?: string | null;
}) {
  return (
    <span className="relative group inline-block cursor-help border-b border-dotted border-[var(--text-muted)]" tabIndex={0}>
      {children}
      <span role="tooltip" className="pointer-events-none absolute left-0 top-full z-50 mt-1 hidden w-72 rounded-lg border border-edge bg-surface p-2 text-xs font-normal text-ink2 shadow-lg group-hover:block group-focus:block">
        <span className="block font-semibold text-ink">{source ?? "source unknown"}</span>
        {sourceTime && <span className="block">Source time: {fmtTime(sourceTime, tz)}</span>}
        {fetched && <span className="block">Fetched: {fmtTime(fetched, tz)}</span>}
        {note && <span className="block italic">{note}</span>}
        {url && <span className="block break-all text-muted">{url}</span>}
      </span>
    </span>
  );
}

export function Card({ title, right, children, className = "", id }: { title: ReactNode; right?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <section id={id} className={`card p-4 ${className}`}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink2">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: "neutral" | "warn" | "bad" | "good" | "info"; title?: string }) {
  const map = {
    neutral: "bg-[var(--surface-2)] text-ink2",
    warn: "bg-[var(--warning)] text-black",
    bad: "bg-[var(--critical)] text-white",
    good: "bg-[var(--good)] text-white",
    info: "bg-[var(--series-1)] text-white",
  };
  return <span title={title} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${map[tone]}`}>{children}</span>;
}

export function PostureBadge({ p, size = "md" }: { p: Posture; size?: "sm" | "md" | "lg" }) {
  const s = POSTURE_STYLE[p];
  const cls = size === "lg" ? "text-2xl px-4 py-2" : size === "sm" ? "text-xs px-2 py-0.5" : "text-sm px-3 py-1";
  return (
    <span className={`inline-flex items-center gap-2 rounded-lg font-bold ${cls}`} style={{ background: s.color, color: s.ink }}>
      <span aria-hidden>{s.icon}</span>{s.label}
    </span>
  );
}

export const CONF_TONE = { high: "good", medium: "warn", low: "bad" } as const;
