import { vi } from "vitest";

/** Where the visitor is, as a test sets it, and where the UI then sent them. */
export const navigation = {
  pathname: "/",
  search: "",
  router: { push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn() },
  /** Put the visitor at an address: `at("/login?next=%2Fsearch")`. */
  at(address: string): void {
    const [pathname, search = ""] = address.split("?");
    this.pathname = pathname ?? "/";
    this.search = search;
  },
  reset(): void {
    this.pathname = "/";
    this.search = "";
    for (const spy of Object.values(this.router)) spy.mockReset();
  },
};
