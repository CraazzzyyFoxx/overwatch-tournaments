/**
 * Wall-clock ⇄ UTC conversion for the workspace timezone (`workspace.timezone`,
 * an IANA name). Storage and the API stay UTC; admin schedule forms display and
 * parse `datetime-local` strings ("YYYY-MM-DDTHH:mm") in the workspace zone.
 * Pure `Intl` — no timezone library.
 */

export const DEFAULT_WORKSPACE_TIMEZONE = "Europe/Moscow";

const formatterCache = new Map<string, Intl.DateTimeFormat>();

function getFormatter(timeZone: string): Intl.DateTimeFormat {
  let formatter = formatterCache.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23"
    });
    formatterCache.set(timeZone, formatter);
  }
  return formatter;
}

type WallClock = Record<"year" | "month" | "day" | "hour" | "minute" | "second", string>;

function wallClockParts(date: Date, timeZone: string): WallClock {
  const parts = {} as WallClock;
  for (const part of getFormatter(timeZone).formatToParts(date)) {
    if (part.type !== "literal") parts[part.type as keyof WallClock] = part.value;
  }
  return parts;
}

/** Milliseconds the zone's wall clock is ahead of UTC at instant `ts` (minute precision). */
function zoneOffsetMs(ts: number, timeZone: string): number {
  const p = wallClockParts(new Date(ts), timeZone);
  const wallAsUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
  return wallAsUtc - Math.floor(ts / 1000) * 1000;
}

/** UTC instant → "YYYY-MM-DDTHH:mm" wall clock in `timeZone` (datetime-local format). */
export function utcToZonedInput(value: Date | string | null | undefined, timeZone: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const p = wallClockParts(date, timeZone);
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

/** "YYYY-MM-DDTHH:mm" wall clock in `timeZone` → UTC ISO string (null when blank/invalid). */
export function zonedInputToUtc(input: string, timeZone: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(input ?? "");
  if (!match) return null;
  const [, year, month, day, hour, minute] = match;
  const wallAsUtc = Date.UTC(+year, +month - 1, +day, +hour, +minute);
  // Two passes converge across DST boundaries (a no-op for fixed-offset zones like MSK).
  let ts = wallAsUtc - zoneOffsetMs(wallAsUtc, timeZone);
  ts = wallAsUtc - zoneOffsetMs(ts, timeZone);
  return new Date(ts).toISOString();
}

/** "UTC+3" / "UTC-5:30" label for the zone's offset at `at` (defaults to now). */
export function getUtcOffsetLabel(timeZone: string, at: Date = new Date()): string {
  const offsetMinutes = Math.round(zoneOffsetMs(at.getTime(), timeZone) / 60_000);
  const sign = offsetMinutes < 0 ? "-" : "+";
  const abs = Math.abs(offsetMinutes);
  const hours = Math.floor(abs / 60);
  const minutes = abs % 60;
  return `UTC${sign}${hours}${minutes ? `:${String(minutes).padStart(2, "0")}` : ""}`;
}
