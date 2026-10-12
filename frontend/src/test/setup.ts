import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { setCsrfToken } from "@/lib/api/client";
import { forgetPlaces } from "@/lib/places";

import { navigation } from "./navigation";

// The router is Next.js's own. Tests say where the visitor is and see where they are sent.
vi.mock("next/navigation", () => ({
  useRouter: () => navigation.router,
  usePathname: () => navigation.pathname,
  useSearchParams: () => new URLSearchParams(navigation.search),
}));

// Loading another page is the browser's doing. A test sees that it was asked for.
// And so is saying what is on the screen: jsdom lays nothing out. Here, what is inside
// something with the `hidden` attribute is not.
vi.mock("@/lib/browser", () => ({
  leaveTo: vi.fn(),
  isOnScreen: (element: Element) => element.closest("[hidden]") === null,
}));

// jsdom has no media queries: the system's mode is what a test says it is.
let systemIsDark = true;
export function setSystemMode(mode: "light" | "dark"): void {
  systemIsDark = mode === "dark";
}

beforeEach(() => {
  navigation.reset();
  setCsrfToken(null);
  forgetPlaces(); // each test is a page that was just loaded
  // A test of something that needs no page runs without one.
  if (typeof window === "undefined") return;
  systemIsDark = true;
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  window.matchMedia = (query: string) =>
    ({
      matches: query.includes("dark") ? systemIsDark : false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }) as unknown as MediaQueryList;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
