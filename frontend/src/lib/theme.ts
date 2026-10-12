/** The mode: what a person chose, and what is shown. No React here, so it can be tested alone. */

export type ThemeChoice = "light" | "dark" | "system";
export type Mode = "light" | "dark";

export const CHOICES: readonly ThemeChoice[] = ["light", "dark", "system"];
export const STORAGE_KEY = "megooarti-theme";
export const DARK_QUERY = "(prefers-color-scheme: dark)";

export function isChoice(value: unknown): value is ThemeChoice {
  return value === "light" || value === "dark" || value === "system";
}

/** The mode to show for a choice. */
export function resolve(choice: ThemeChoice, systemIsDark: boolean): Mode {
  if (choice === "system") return systemIsDark ? "dark" : "light";
  return choice;
}

/** What was chosen in this browser, or "system" if nothing was, or storage cannot be read. */
export function storedChoice(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isChoice(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

export function storeChoice(choice: ThemeChoice): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // Storage is off or full. The choice then lasts as long as the page.
  }
}

export function applyMode(mode: Mode): void {
  document.documentElement.setAttribute("data-theme", mode);
}

/**
 * Runs in the page's head, before anything is painted, so the wrong mode is never
 * shown (UI-10). It is the same decision as `resolve(storedChoice(), ...)`, written
 * out because it runs before any module is loaded. A test holds the two together.
 * Only reading storage may fail (a browser can forbid it): the system is then asked.
 */
export const THEME_SCRIPT = `(function(){var c=null;try{c=localStorage.getItem(${JSON.stringify(
  STORAGE_KEY,
)})}catch(e){}var d=c==="dark"||(c!=="light"&&matchMedia(${JSON.stringify(
  DARK_QUERY,
)}).matches);document.documentElement.setAttribute("data-theme",d?"dark":"light")})()`;
