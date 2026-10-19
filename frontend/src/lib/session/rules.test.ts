import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { ADMIN, NOBODY, VISITOR } from "@/test/render";

import { allows, decide, isAnonymous, returnPath } from "./rules";

const MUST_CHANGE: SessionInfo = { ...ADMIN, must_change_password: true };
const show = { show: true };
const goTo = (address: string) => ({ show: false, goTo: address });

describe("what a visitor is shown", () => {
  test("someone signed in sees the screen they asked for", () => {
    expect(decide(ADMIN, "/")).toEqual(show);
    expect(decide(ADMIN, "/account/password")).toEqual(show);
    expect(decide(ADMIN, "/browse/releases?path=com/acme")).toEqual(show);
  });

  test("someone signed in does not see the sign-in screen", () => {
    expect(decide(ADMIN, "/login")).toEqual(goTo("/"));
    expect(decide(ADMIN, "/login?next=%2Fsearch", "/search")).toEqual(goTo("/search"));
  });

  test("someone who must change their password sees only that", () => {
    expect(decide(MUST_CHANGE, "/")).toEqual(goTo("/account/password"));
    expect(decide(MUST_CHANGE, "/search?q=x")).toEqual(goTo("/account/password"));
    expect(decide(MUST_CHANGE, "/account/password")).toEqual(show);
    expect(decide(MUST_CHANGE, "/login", "/search")).toEqual(goTo("/account/password"));
  });

  test("nobody signed in, and no anonymous access: the sign-in screen, then back", () => {
    expect(decide(NOBODY, "/")).toEqual(goTo("/login"));
    expect(decide(NOBODY, "/search?q=commons lang")).toEqual(
      goTo("/login?next=%2Fsearch%3Fq%3Dcommons%20lang"),
    );
    expect(decide(NOBODY, "/login")).toEqual(show);
    expect(decide(NOBODY, "/login?next=%2Fsearch", "/search")).toEqual(show);
  });

  test("an application's consent page is answered by someone signed in, and is come back to", () => {
    expect(decide(NOBODY, "/connect?request=sealed")).toEqual(
      goTo("/login?next=%2Fconnect%3Frequest%3Dsealed"),
    );
    expect(decide(VISITOR, "/connect?request=sealed")).toEqual(
      goTo("/login?next=%2Fconnect%3Frequest%3Dsealed"),
    );
    expect(decide(ADMIN, "/connect?request=sealed")).toEqual(show);
    expect(decide(ADMIN, "/login", "/connect?request=sealed")).toEqual(
      goTo("/connect?request=sealed"),
    );
  });

  test("a visitor browses where anonymous access is on, and has no account", () => {
    expect(isAnonymous(VISITOR)).toBe(true);
    expect(isAnonymous(NOBODY)).toBe(false);
    expect(isAnonymous(ADMIN)).toBe(false);
    expect(decide(VISITOR, "/")).toEqual(show);
    expect(decide(VISITOR, "/login")).toEqual(show);
    expect(decide(VISITOR, "/account/password")).toEqual(goTo("/login?next=%2Faccount%2Fpassword"));
    expect(decide(VISITOR, "/account")).toEqual(goTo("/login?next=%2Faccount"));
    expect(decide(VISITOR, "/accounting")).toEqual(show); // not the account area
  });
});

describe("where to go after signing in", () => {
  test.each(["/", "/search", "/browse/releases?path=com/acme&x=1", "/account/password"])(
    "%s is one of our own screens",
    (wanted) => {
      expect(returnPath(wanted)).toBe(wanted);
    },
  );

  test.each([
    null,
    undefined,
    "",
    "search",
    "https://evil.example/",
    "//evil.example/",
    "/\\evil.example/",
    "\\\\evil.example",
    "javascript:alert(1)",
    "/login",
    "/login?next=%2Flogin",
    // A browser drops a tab and a line break from an address: these are `//evil.example`.
    "/\t/evil.example/",
    "/\n/evil.example/",
    "/\r/evil.example/",
    "\t//evil.example/",
    "/\u0000/evil.example",
    "/\u007f",
  ])("%j is not, and the home screen is used", (wanted) => {
    expect(returnPath(wanted)).toBe("/");
  });

  test("the address is given back as a browser would write it", () => {
    expect(returnPath("/search?q=commons lang#top")).toBe("/search?q=commons%20lang#top");
    expect(returnPath("/a/../search")).toBe("/search");
    expect(returnPath("/a/../login")).toBe("/"); // not the sign-in screen by another spelling
  });

  test("the gate goes nowhere else, whatever the sign-in screen was asked to return to", () => {
    for (const next of ["/\t/evil.example/", "//evil.example", "https://evil.example"]) {
      expect(decide(ADMIN, "/login", next)).toEqual(goTo("/"));
    }
  });
});

describe("what a caller is offered", () => {
  const editor: SessionInfo = { ...ADMIN, permissions: ["admin:users:read", "repository:maven"] };

  test("what their patterns grant", () => {
    expect(allows(ADMIN, "admin:settings:write")).toBe(true);
    expect(allows(editor, "admin:users:read")).toBe(true);
    expect(allows(editor, "admin:users:write")).toBe(false);
    expect(allows(editor, "repository:maven:releases:delete")).toBe(true);
    expect(allows(NOBODY, "admin:users:read")).toBe(false);
  });

  test("nothing of administration to a visitor, whatever the anonymous user holds", () => {
    const generous: SessionInfo = { ...VISITOR, permissions: ["*"] };

    expect(allows(generous, "admin:users:read")).toBe(false);
    expect(allows(generous, "repository:raw:files:browse")).toBe(true);
  });

  test("nothing for a permission that is not one", () => {
    expect(allows(ADMIN, "admin:*:read")).toBe(false);
    expect(allows(ADMIN, "")).toBe(false);
  });
});
