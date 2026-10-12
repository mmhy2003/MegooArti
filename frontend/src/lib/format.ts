/** How a size, a time and a checksum are written for a person. No React here. */

const UNITS = ["B", "KiB", "MiB", "GiB", "TiB"] as const;

/** A size in binary units: `0 B`, `1.5 KiB`, `2.4 MiB`. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  // Whole bytes are whole. Above that, one decimal until the number has three digits.
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)} ${UNITS[unit]}`;
}

const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/** How long ago, in the UI's language: "3 days ago", "just now". */
export function relativeTime(moment: Date, now: Date): string {
  const seconds = Math.round((moment.getTime() - now.getTime()) / 1000);
  const format = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  for (const [unit, size] of STEPS) {
    if (Math.abs(seconds) >= size) return format.format(Math.trunc(seconds / size), unit);
  }
  return "just now";
}

/** The exact time, in the reader's own zone: "Oct 12, 2026, 10:15 AM". */
export function exactTime(moment: Date): string {
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(moment);
}

/**
 * The last second of a day (`2031-05-17`, as a date field gives it), where the person
 * is, as the API takes a moment. Null for what is no day: a date field lets a year of
 * five digits through, which no moment can be made of.
 */
export function endOfDay(day: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  const moment = new Date(`${day}T23:59:59`);
  return Number.isNaN(moment.getTime()) ? null : moment.toISOString();
}

export const CHECKSUMS = { 32: "md5", 40: "sha1", 64: "sha256", 128: "sha512" } as const;
export type ChecksumKind = (typeof CHECKSUMS)[keyof typeof CHECKSUMS];

/**
 * Which checksum a pasted text is, by its length, and the text as the API takes it.
 * Tools print them in either case, with spaces around, or with the name in front
 * (`sha256:9f86...`). Null if it is none.
 */
export function readChecksum(typed: string): { kind: ChecksumKind; value: string } | null {
  const value = typed
    .trim()
    .toLowerCase()
    .replace(/^(md5|sha1|sha256|sha512):/, "");
  if (!/^[0-9a-f]+$/.test(value)) return null;
  const kind = CHECKSUMS[value.length as keyof typeof CHECKSUMS];
  return kind ? { kind, value } : null;
}
