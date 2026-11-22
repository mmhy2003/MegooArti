/**
 * Whether the sidebar is open or a rail of icons, kept in the person's browser as the
 * mode is. No React here, so the page's head can use it: the hook is in use-sidebar.ts.
 * The choice is shown by `data-sidebar="rail"` on `<html>`, which the CSS reads, so
 * the script below can set it before anything is painted.
 */
export const SIDEBAR_STORAGE = "megooarti-sidebar";
export const RAIL = "rail";
export const SIDEBAR_ATTRIBUTE = "data-sidebar";
const CHANGED = "megooarti-sidebar-changed";

// What was chosen on this page, where the browser keeps nothing (storage is off, or
// full): the sidebar stays as it was put, if only until a reload.
let unkept: boolean | null = null;

/** Whether the sidebar is a rail. It is open unless it was collapsed. */
export function sidebarIsRail(): boolean {
  if (unkept !== null) return unkept;
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE) === RAIL;
  } catch {
    return false; // storage cannot be read: as if nothing had been chosen
  }
}

function show(rail: boolean): void {
  if (rail) document.documentElement.setAttribute(SIDEBAR_ATTRIBUTE, RAIL);
  else document.documentElement.removeAttribute(SIDEBAR_ATTRIBUTE);
}

export function setSidebarRail(rail: boolean): void {
  try {
    if (rail) window.localStorage.setItem(SIDEBAR_STORAGE, RAIL);
    else window.localStorage.removeItem(SIDEBAR_STORAGE);
    unkept = null;
  } catch {
    unkept = rail;
  }
  show(rail);
  // The same window is not told of its own writes to storage.
  window.dispatchEvent(new Event(CHANGED));
}

export function subscribe(changed: () => void): () => void {
  // Another tab: its choice changes this page's width too, which is the attribute's doing.
  const stored = () => {
    show(sidebarIsRail());
    changed();
  };
  window.addEventListener("storage", stored);
  window.addEventListener(CHANGED, changed); // this one
  return () => {
    window.removeEventListener("storage", stored);
    window.removeEventListener(CHANGED, changed);
  };
}

/**
 * Runs in the page's head before anything is painted, as THEME_SCRIPT does, so a rail
 * does not open and close again on load. A test holds it to the same decision as
 * sidebarIsRail.
 */
export const SIDEBAR_SCRIPT = `(function(){try{if(localStorage.getItem(${JSON.stringify(SIDEBAR_STORAGE)})===${JSON.stringify(RAIL)})document.documentElement.setAttribute(${JSON.stringify(SIDEBAR_ATTRIBUTE)},${JSON.stringify(RAIL)})}catch(e){}})()`;
