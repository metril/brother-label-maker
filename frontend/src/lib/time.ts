// Pure time-formatting helpers for the Presets/History pages (task 2.13) --
// kept UI-framework-free per this app's own convention (see lib/tray.ts,
// lib/sequence.ts). Every timestamp involved is one of the backend's own
// ISO-8601 `_utcnow()` strings (db/database.py), always parseable by `new
// Date(iso)`.

const RELATIVE_UNITS: { unit: Intl.RelativeTimeFormatUnit; ms: number }[] = [
  { unit: "year", ms: 365 * 24 * 60 * 60 * 1000 },
  { unit: "month", ms: 30 * 24 * 60 * 60 * 1000 },
  { unit: "day", ms: 24 * 60 * 60 * 1000 },
  { unit: "hour", ms: 60 * 60 * 1000 },
  { unit: "minute", ms: 60 * 1000 },
];

const relativeTimeFormat = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "3h ago" / "in 2 minutes" -- the mono relative timestamp preset/history
 * rows show (design doc: "updated_at (relative, mono)" /
 * "created_at (relative + absolute on hover/title)"). `now` is an explicit
 * param (default `new Date()`) so a test can pin it instead of this
 * drifting with the real clock mid-run. Anything under a minute reads as
 * "just now" -- `Intl.RelativeTimeFormat` would otherwise print
 * "0 minutes ago", which looks like a rounding bug rather than "seconds
 * ago". */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const thenMs = new Date(iso).getTime();
  const diffMs = thenMs - now.getTime();
  const absMs = Math.abs(diffMs);

  if (absMs < 60_000) return "just now";

  for (const { unit, ms } of RELATIVE_UNITS) {
    if (absMs >= ms) {
      return relativeTimeFormat.format(Math.round(diffMs / ms), unit);
    }
  }
  return relativeTimeFormat.format(Math.round(diffMs / 60_000), "minute");
}

/** Absolute wall-clock rendering for a `title`/hover tooltip alongside the
 * relative form above -- locale-formatted, minute precision. */
export function formatAbsoluteTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
