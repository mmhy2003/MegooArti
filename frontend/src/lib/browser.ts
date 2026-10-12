/** What only the browser itself can do. Kept apart so that a test can stand in for it. */

/** Go to an address by loading it afresh: everything this page held in memory is gone. */
export function leaveTo(path: string): void {
  window.location.assign(path);
}

/**
 * Whether an element is on the screen: not one that is hidden at this width, or inside
 * a part that is closed. Only a browser that lays the page out can say.
 */
export function isOnScreen(element: Element): boolean {
  return element.getClientRects().length > 0;
}
