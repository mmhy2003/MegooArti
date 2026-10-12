/**
 * What a visitor is shown, decided from the session and the address alone. No React
 * and no requests here: the rules of the design's section 7, as functions.
 */
import type { SessionInfo } from "@/lib/api/types";

import { anyGrants, isValidPermission } from "./permissions";

export const HOME = "/";
export const SIGN_IN = "/login";
export const CHANGE_PASSWORD = "/account/password";
// What only a person who is signed in has.
const ACCOUNT_AREA = "/account";

export type Decision = { show: true } | { show: false; goTo: string };

/** Nobody is signed in, and the server lets such a visitor browse. */
export function isAnonymous(session: SessionInfo): boolean {
  return !session.authenticated && session.method !== null;
}

/** Whether to offer something that needs this permission. */
export function allows(session: SessionInfo, permission: string): boolean {
  if (!isValidPermission(permission)) return false;
  // Whatever roles the anonymous user holds, nobody administers anonymously.
  if (!session.authenticated && permission.startsWith("admin:")) return false;
  return anyGrants(session.permissions, permission);
}

/**
 * Where to go after signing in: the screen that was asked for, if it is one of ours.
 * Anything else, such as another site's address, is the home screen.
 */
export function returnPath(wanted: string | null | undefined): string {
  if (!wanted || !wanted.startsWith("/") || wanted.startsWith("//") || wanted.includes("\\")) {
    return HOME;
  }
  if (wanted === SIGN_IN || wanted.startsWith(`${SIGN_IN}?`)) return HOME;
  return wanted;
}

function signInFor(path: string): string {
  return path === HOME ? SIGN_IN : `${SIGN_IN}?next=${encodeURIComponent(path)}`;
}

/**
 * `path` is the address with its query. `next` is where the sign-in screen was asked
 * to return to.
 */
export function decide(session: SessionInfo, path: string, next: string | null = null): Decision {
  const pathname = path.split("?")[0] ?? path;
  if (pathname === SIGN_IN) {
    if (!session.authenticated) return { show: true };
    const onward = session.must_change_password ? CHANGE_PASSWORD : returnPath(next);
    return { show: false, goTo: onward };
  }
  if (session.authenticated) {
    if (session.must_change_password && pathname !== CHANGE_PASSWORD) {
      return { show: false, goTo: CHANGE_PASSWORD };
    }
    return { show: true };
  }
  const inAccount = pathname === ACCOUNT_AREA || pathname.startsWith(`${ACCOUNT_AREA}/`);
  if (isAnonymous(session) && !inAccount) return { show: true };
  return { show: false, goTo: signInFor(path) };
}
