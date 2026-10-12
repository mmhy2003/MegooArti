/**
 * Where a screen last was, for as long as the page lives.
 *
 * A screen that changes under the keyboard (a folder is entered, and the list the link
 * was in is replaced) has to say where the keyboard goes. It cannot remember by itself
 * where it was: Next.js builds a screen anew when a part of its address changes. And a
 * screen shown for the first time since the page was loaded was nowhere before: a page
 * starts at its top.
 */
const last = new Map<string, string>();

/** Notes where a screen is now, and says whether it was somewhere else before. */
export function movedTo(screen: string, place: string): boolean {
  const was = last.get(screen);
  last.set(screen, place);
  return was !== undefined && was !== place;
}

/** For tests: no screen was anywhere before. */
export function forgetPlaces(): void {
  last.clear();
}
