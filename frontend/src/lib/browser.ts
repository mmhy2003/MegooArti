/** What only the browser itself can do. Kept apart so that a test can stand in for it. */

/** Go to an address by loading it afresh: everything this page held in memory is gone. */
export function leaveTo(path: string): void {
  window.location.assign(path);
}
