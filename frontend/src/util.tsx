import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { Posture, Readiness, ReadinessLevel, Snapshot } from "./types";

export const POSTURES: Posture[] = ["NORMAL", "DELAYED_ARRIVAL", "EARLY_DISMISSAL", "TELEWORK", "CLOSED"];

/** One posture -> one color everywhere. Always shown with its text label, never color alone. */
// Light -> deep blue as severity rises; the icon and word carry the meaning, the shade reinforces it.
export const POSTURE_STYLE: Record<Posture, { label: string; color: string; icon: string; ink: string }> = {
  NORMAL: { label: "Normal", color: "var(--b1)", icon: "✓", ink: "var(--b1-ink)" },
  DELAYED_ARRIVAL: { label: "Delayed arrival", color: "var(--b2)", icon: "◷", ink: "var(--b2-ink)" },
  EARLY_DISMISSAL: { label: "Early dismissal", color: "var(--b4)", icon: "↧", ink: "var(--b4-ink)" },
  TELEWORK: { label: "Telework / unscheduled leave", color: "var(--b5)", icon: "⌂", ink: "var(--surface-1)" },
  CLOSED: { label: "Closed", color: "var(--b6)", icon: "✕", ink: "var(--surface-1)" },
};

export function fmtTime(iso: string | null | undefined, tz: string, opts: { date?: boolean; year?: boolean } = { date: true }): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const s = d.toLocaleString("en-US", {
    timeZone: tz,
    weekday: opts.date ? "short" : undefined,
    month: opts.date ? "short" : undefined,
    day: opts.date ? "numeric" : undefined,
    year: opts.year ? "numeric" : undefined,
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

/** Inside a <Section>, panels drop their own card frame so there is one box, not a box in a box. */
const InSection = createContext<{ title: boolean } | null>(null);

export function Card({ title, right, children, className = "", id }: { title: ReactNode; right?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  const inSection = useContext(InSection);
  if (inSection) {
    return (
      <div id={id} className={className}>
        {(inSection.title || right) && (
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            {inSection.title ? <h3 className="text-sm font-semibold">{title}</h3> : <span />}
            {right}
          </div>
        )}
        {children}
      </div>
    );
  }
  return (
    <section id={id} className={`card p-5 ${className}`}>
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: "neutral" | "warn" | "bad" | "good" | "info"; title?: string }) {
  // All-blue tones: neutral (gray-blue), good (tint), warn (soft blue + the caller's ⚠ text), bad (deep), info (accent).
  const map = {
    neutral: "bg-[var(--surface-2)] text-ink2",
    warn: "bg-[var(--tint-strong)] text-ink ring-1 ring-inset ring-[var(--b3)]",
    bad: "bg-[var(--b5)] text-[var(--surface-1)]",
    good: "bg-[var(--tint)] text-[var(--accent)]",
    info: "bg-[var(--accent)] text-[var(--on-accent)]",
  };
  return <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${map[tone]}`}>{children}</span>;
}

export function PostureBadge({ p, size = "md" }: { p: Posture; size?: "sm" | "md" | "lg" }) {
  const s = POSTURE_STYLE[p];
  const cls = size === "lg" ? "text-2xl px-4 py-2 rounded-xl" : size === "sm" ? "text-xs px-2 py-0.5 rounded-md" : "text-sm px-3 py-1 rounded-lg";
  return (
    <span key={p} className={`inline-flex items-center gap-2 whitespace-nowrap font-semibold ${size === "lg" ? "cc-pop" : ""} ${cls}`} style={{ background: s.color, color: s.ink }}>
      <span aria-hidden>{s.icon}</span>{s.label}
    </span>
  );
}

export const CONF_TONE = { high: "good", medium: "warn", low: "bad" } as const;

/** Readiness (adapted Cooper Color Code). Drawn as a 4-step meter, never as a pill, so it is not
 *  mistaken for the posture badge, and always labelled "Condition <color>". */
export const READINESS: { level: ReadinessLevel; label: string; color: string }[] = [
  { level: "WHITE", label: "White", color: "var(--cooper-white)" },
  { level: "YELLOW", label: "Yellow", color: "var(--cooper-yellow)" },
  { level: "ORANGE", label: "Orange", color: "var(--cooper-orange)" },
  { level: "RED", label: "Red", color: "var(--cooper-red)" },
];

export function ReadinessMeter({ r, tz, compact = false }: { r: Readiness; tz: string; compact?: boolean }) {
  const idx = Math.max(0, READINESS.findIndex((x) => x.level === r.level));
  const tip = [r.cooper, r.meaning, ...r.reasons, `(${r.basis})`].join("\n");
  return (
    <div className="flex flex-col gap-1" title={tip}>
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">Readiness</span>
        <div className="flex" role="meter" aria-valuemin={0} aria-valuemax={3} aria-valuenow={idx} aria-label={`Readiness: Condition ${READINESS[idx].label}`}>
          {READINESS.map((x, i) => (
            <span key={x.level} className={`h-3.5 w-6 border border-edge transition-opacity duration-500 first:rounded-l-full last:rounded-r-full ${i === idx ? `ring-2 ring-inset ring-[var(--text-primary)] ${x.level === "RED" ? "cc-pulse" : ""}` : "opacity-30"}`}
              style={{ background: x.color }} />
          ))}
        </div>
        <span className="text-sm font-semibold">Condition {READINESS[idx].label}</span>
      </div>
      {!compact && r.decide_by && (
        <span className={`text-xs ${r.deadline_passed ? "font-semibold text-[var(--danger)]" : "text-ink2"}`}>
          {r.deadline_passed ? "Announcement deadline passed: " : "Decide and announce by "}{fmtTime(r.decide_by, tz)}
        </span>
      )}
    </div>
  );
}

export function readinessColor(level: string | null | undefined): string {
  return READINESS.find((x) => x.level === level)?.color ?? "transparent";
}

/** Number that eases to its new value (used for scores and confidence). */
export function AnimatedNumber({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    const start = performance.now();
    const a = from.current;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce || a === value) { setShown(value); from.current = value; return; }
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / 600);
      const e = 1 - Math.pow(1 - k, 3);
      setShown(a + (value - a) * e);
      if (k < 1) raf = requestAnimationFrame(step); else from.current = value;
    };
    raf = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(raf); from.current = value; };
  }, [value]);
  return <>{shown.toFixed(decimals)}</>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

/** A collapsed-by-default card: a one-line title and summary that opens to the full panel.
 *  Content mounts on first open (so charts and maps only load when wanted) and stays mounted. */
export function Section({ id, title, summary, open, onToggle, children, innerTitles = false }: {
  id: string; title: string; summary?: ReactNode; open: boolean; onToggle: () => void; children: ReactNode;
  /** Show the titles of the panels inside (for sections that hold several panels). */
  innerTitles?: boolean;
}) {
  const [mounted, setMounted] = useState(open);
  useEffect(() => { if (open) setMounted(true); }, [open]);
  return (
    <section id={`section-${id}`} className="card scroll-mt-4">
      <button type="button" onClick={onToggle} aria-expanded={open} aria-controls={`section-${id}-body`}
        className="flex w-full items-center gap-3 rounded-[14px] px-5 py-4 text-left hover:bg-[var(--surface-2)]">
        <span aria-hidden className={`text-muted transition-transform duration-300 ${open ? "rotate-90" : ""}`}>▸</span>
        <span className="min-w-0 flex-1">
          <span className="block font-semibold">{title}</span>
          {summary && <span className="block truncate text-sm text-ink2">{summary}</span>}
        </span>
        <span className="shrink-0 text-sm text-[var(--accent)]">{open ? "Hide" : "Show"}</span>
      </button>
      <div id={`section-${id}-body`} className="cc-collapse" data-open={open} aria-hidden={!open}>
        <div className="overflow-hidden">
          {mounted && (
            <div className="space-y-6 border-t border-edge px-5 py-5">
              <InSection.Provider value={{ title: innerTitles }}>{children}</InSection.Provider>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

/** Newest non-null value of a series input (e.g. "obs.temp_f"), with its time. */
export function latest(snap: Snapshot, id: string): { v: number; t: string } | null {
  const pts = snap.inputs.find((i) => i.id === id)?.series ?? [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    if (typeof p.v === "number" && new Date(p.t).getTime() <= new Date(snap.as_of).getTime() + 60e3) return { v: p.v, t: p.t };
  }
  return null;
}

/** Largest forecast value of a series input in the next ``hours`` after the snapshot time. */
export function maxAhead(snap: Snapshot, id: string, hours: number): number | null {
  const from = new Date(snap.as_of).getTime(), to = from + hours * 3600e3;
  const vals = (snap.inputs.find((i) => i.id === id)?.series ?? [])
    .filter((p) => typeof p.v === "number" && new Date(p.t).getTime() >= from - 3600e3 && new Date(p.t).getTime() <= to)
    .map((p) => p.v as number);
  return vals.length ? Math.max(...vals) : null;
}

/** "3:00 PM" or "Mon 3:00 PM" in the facility's time zone. */
export function fmtClock(iso: string | null | undefined, tz: string, withDay = false): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", { timeZone: tz, weekday: withDay ? "short" : undefined, hour: "numeric", minute: "2-digit" });
}

/** "Monday, Oct 12" from a YYYY-MM-DD day. */
export function fmtDayLong(d: string): string {
  const [y, m, day] = d.split("-").map(Number);
  return new Date(y, m - 1, day).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
}

/** Text color that stays readable on each Cooper color, in both themes. */
const COOPER_INK: Record<ReadinessLevel, string> = { WHITE: "#1f2937", YELLOW: "#1f2937", ORANGE: "#1f2937", RED: "#ffffff" };
const COOPER_RISK: Record<ReadinessLevel, string> = {
  WHITE: "Low risk", YELLOW: "Be aware", ORANGE: "Get ready to act", RED: "Act now",
};

/** Risk shown with Col. Jeff Cooper's color code (White, Yellow, Orange, Red), always with its words. */
export function CooperBanner({ r, className = "" }: { r: Readiness | null | undefined; className?: string }) {
  if (!r) return null;
  const x = READINESS.find((c) => c.level === r.level) ?? READINESS[0];
  return (
    <div className={`flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 sm:px-7 ${className}`}
      style={{ background: x.color, color: COOPER_INK[x.level] }} role="status" aria-label={`Risk: Condition ${x.label}`}>
      <span className="text-lg font-bold uppercase tracking-wide">Condition {x.label}</span>
      <span className="font-semibold">{COOPER_RISK[x.level]}</span>
      <span className="min-w-0 flex-1 text-sm opacity-90">{r.meaning}</span>
      <span className="flex shrink-0 gap-1" aria-hidden>
        {READINESS.map((c) => (
          <span key={c.level} className={`h-3 w-6 rounded-full border border-black/20 ${c.level === x.level ? "ring-2 ring-black/60" : "opacity-50"}`} style={{ background: c.color }} />
        ))}
      </span>
    </div>
  );
}

/** Small Cooper color swatch with its words, for lists (urgency at the time of a past decision). */
export function CooperChip({ level }: { level: ReadinessLevel | null | undefined }) {
  const x = READINESS.find((c) => c.level === level);
  if (!x) return <span className="text-xs text-muted">Urgency not recorded</span>;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-edge px-2 py-0.5 text-xs font-semibold"
      title={`Urgency then: Condition ${x.label} (${COOPER_RISK[x.level]})`}>
      <span aria-hidden className="h-3 w-3 rounded-sm border border-black/20" style={{ background: x.color }} />
      {x.label}
    </span>
  );
}
