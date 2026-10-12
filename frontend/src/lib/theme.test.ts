import { describe, expect, test, vi } from "vitest";

import { setSystemMode } from "@/test/setup";

import {
  isChoice,
  resolve,
  STORAGE_KEY,
  storeChoice,
  storedChoice,
  THEME_SCRIPT,
  type ThemeChoice,
} from "./theme";

const shown = () => document.documentElement.getAttribute("data-theme");

/** Runs the script as the page's head does: as it stands, before anything else. */
function runScript(): void {
  new Function(THEME_SCRIPT)();
}

describe("the mode that is shown", () => {
  test.each([
    ["light", true, "light"],
    ["light", false, "light"],
    ["dark", true, "dark"],
    ["dark", false, "dark"],
    ["system", true, "dark"],
    ["system", false, "light"],
  ] as const)("for the choice %s on a system that is dark=%s is %s", (choice, dark, mode) => {
    expect(resolve(choice, dark)).toBe(mode);
  });
});

describe("the choice", () => {
  test("is as the system, until one is made", () => {
    expect(storedChoice()).toBe("system");
  });

  test("is kept in this browser", () => {
    storeChoice("light");

    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");
    expect(storedChoice()).toBe("light");
  });

  test.each(["", "blue", "DARK", '{"mode":"dark"}'])(
    "is as the system when storage holds %j",
    (stored) => {
      window.localStorage.setItem(STORAGE_KEY, stored);

      expect(storedChoice()).toBe("system");
      expect(isChoice(stored)).toBe(false);
    },
  );
});

describe("the script in the page's head", () => {
  const CASES: [ThemeChoice | null, "light" | "dark", string][] = [
    [null, "dark", "dark"],
    [null, "light", "light"],
    ["system", "dark", "dark"],
    ["system", "light", "light"],
    ["light", "dark", "light"],
    ["dark", "light", "dark"],
  ];

  test.each(CASES)("with the choice %s on a %s system shows %s", (choice, system, mode) => {
    if (choice !== null) window.localStorage.setItem(STORAGE_KEY, choice);
    setSystemMode(system);

    runScript();

    expect(shown()).toBe(mode);
    // The same decision as the code that runs later, or the mode would change under the reader.
    expect(resolve(storedChoice(), system === "dark")).toBe(mode);
  });

  test("leaves the page as it is when storage cannot be read", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });

    setSystemMode("light");

    expect(runScript).not.toThrow();
    // Nothing was chosen that can be read, so the system decides: not the markup's dark.
    expect(shown()).toBe("light");
    expect(storedChoice()).toBe("system");
    expect(() => storeChoice("dark")).not.toThrow();
  });

  test("is one statement that a text cannot break out of", () => {
    expect(THEME_SCRIPT).not.toContain("</");
    expect(THEME_SCRIPT.startsWith("(function(){")).toBe(true);
  });
});
