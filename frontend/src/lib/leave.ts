/**
 * Leave this site for another address: an application's, after its consent page. A
 * module of its own, so that a test can see where the browser was sent.
 */
export function leaveFor(address: string): void {
  window.location.assign(address);
}
