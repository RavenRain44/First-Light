/** Resolve a wall-clock date using offsets on both sides of a possible DST change. */
export function parseReplayTime(wall: string, timezone: string): { asOf: string; ambiguous: boolean } {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(wall);
  if (!match) throw new Error("Choose a valid date and time.");
  const [, y, m, d, h, min] = match.map(Number);
  const date = new Date(0);
  date.setUTCFullYear(y, m - 1, d);
  date.setUTCHours(h, min, 0, 0);
  if (y < 1 || date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d
    || date.getUTCHours() !== h || date.getUTCMinutes() !== min) throw new Error("Choose a valid date and time.");
  const guess = date.getTime();
  const formatter = new Intl.DateTimeFormat("en-US", { timeZone: timezone, hourCycle: "h23",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  const wallEpoch = (at: number) => {
    const p = Object.fromEntries(formatter.formatToParts(new Date(at)).map((x) => [x.type, x.value]));
    const seen = new Date(0);
    seen.setUTCFullYear(+p.year, +p.month - 1, +p.day);
    seen.setUTCHours(+p.hour, +p.minute, 0, 0);
    return seen.getTime();
  };
  const offsets = new Set([-36, -12, 0, 12, 36].map((hours) => {
    const probe = guess + hours * 3600000;
    return wallEpoch(probe) - probe;
  }));
  const candidates = [...offsets].map((offset) => guess - offset).filter((at) => wallEpoch(at) === guess).sort((a, b) => a - b);
  if (!candidates.length) throw new Error(`That local time does not exist in ${timezone} because the clocks move forward. Choose another time.`);
  // Fall's repeated hour uses its first occurrence, with an explicit note in the panel.
  return { asOf: new Date(candidates[0]).toISOString(), ambiguous: candidates.length > 1 };
}
