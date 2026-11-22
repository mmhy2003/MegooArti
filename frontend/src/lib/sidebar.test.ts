import { describe, expect, test, vi } from "vitest";

import {
  setSidebarRail,
  SIDEBAR_SCRIPT,
  SIDEBAR_STORAGE,
  sidebarIsRail,
  subscribe,
} from "./sidebar";

const shown = () => document.documentElement.getAttribute("data-sidebar");

/** Runs the script as the page's head does: as it stands, before anything else. */
function runScript(): void {
  new Function(SIDEBAR_SCRIPT)();
}

function storageFails(): void {
  const denied = () => {
    throw new DOMException("denied", "SecurityError");
  };
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(denied);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(denied);
  vi.spyOn(Storage.prototype, "removeItem").mockImplementation(denied);
}

describe("the sidebar", () => {
  test("is open until it is collapsed", () => {
    expect(sidebarIsRail()).toBe(false);
  });

  test("is kept in this browser", () => {
    setSidebarRail(true);

    expect(window.localStorage.getItem(SIDEBAR_STORAGE)).toBe("rail");
    expect(sidebarIsRail()).toBe(true);
    expect(shown()).toBe("rail");

    setSidebarRail(false);

    expect(window.localStorage.getItem(SIDEBAR_STORAGE)).toBeNull();
    expect(sidebarIsRail()).toBe(false);
    expect(shown()).toBeNull();
  });

  test.each(["", "RAIL", "open", "true"])("is open when storage holds %j", (stored) => {
    window.localStorage.setItem(SIDEBAR_STORAGE, stored);

    expect(sidebarIsRail()).toBe(false);
  });

  test("lasts as long as the page when storage fails", () => {
    storageFails();

    expect(() => setSidebarRail(true)).not.toThrow();
    expect(sidebarIsRail()).toBe(true);
    expect(shown()).toBe("rail");

    vi.restoreAllMocks();
    setSidebarRail(false); // the choice that lasts for the page is not the next test's
  });

  test("tells whoever listens", () => {
    const changed = vi.fn();
    const stop = subscribe(changed);

    setSidebarRail(true);
    stop();

    expect(changed).toHaveBeenCalledTimes(1);
  });

  test("follows a choice made in another tab", () => {
    const changed = vi.fn();
    const stop = subscribe(changed);

    window.localStorage.setItem(SIDEBAR_STORAGE, "rail");
    window.dispatchEvent(new StorageEvent("storage"));
    stop();

    // The rail's width is the attribute's doing, so it must change with the choice.
    expect(shown()).toBe("rail");
    expect(changed).toHaveBeenCalledTimes(1);
  });
});

describe("the script in the page's head", () => {
  test.each(["rail", null, "x"])("agrees with the module for %j in storage", (stored) => {
    if (stored !== null) window.localStorage.setItem(SIDEBAR_STORAGE, stored);

    runScript();

    expect(shown() === "rail").toBe(sidebarIsRail());
  });

  test("leaves the page as it is when storage cannot be read", () => {
    storageFails();

    expect(runScript).not.toThrow();
    expect(shown()).toBeNull();
  });

  test("is one statement that a text cannot break out of", () => {
    expect(SIDEBAR_SCRIPT).not.toContain("</");
    expect(SIDEBAR_SCRIPT.startsWith("(function(){")).toBe(true);
  });
});
