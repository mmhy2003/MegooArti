/**
 * Whether a caller's permission patterns grant a permission, matched as the backend
 * matches them (`megooarti.security.permissions`). The UI uses this to hide what a
 * caller could not use. It is a courtesy: the API decides.
 */

const SEGMENT = /^[A-Za-z0-9_.-]+$/;

/** A permission that could not shift segments: every part is a plain word. */
export function isValidPermission(permission: string): boolean {
  return permission.split(":").every((part) => SEGMENT.test(part));
}

/** A pattern grants what it is a prefix of, with `*` for any one segment. */
export function grants(pattern: string, permission: string): boolean {
  const granted = pattern.split(":");
  const required = permission.split(":");
  if (granted.length > required.length) return false;
  return granted.every((have, index) => have === "*" || have === required[index]);
}

export function anyGrants(patterns: readonly string[], permission: string): boolean {
  return patterns.some((pattern) => grants(pattern, permission));
}
