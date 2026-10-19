import { Boxes, Users } from "lucide-react";
import type { Route } from "next";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { ADMIN, NOBODY, VISITOR } from "@/test/render";

import { isCurrent, NAVIGATION, visible, type NavArea, type NavItem } from "./navigation";

// A navigation as plan 10 will have it: items with and without a permission.
const item = (key: string, href: string, permission?: string) =>
  ({ key, href: href as Route, icon: Users, permission }) as unknown as NavItem;

const AREAS: NavArea[] = [
  { key: "browse", items: [item("repositories", "/"), item("search", "/search")] },
  {
    key: "administration",
    items: [
      item("users", "/admin/users", "admin:users:read"),
      item("roles", "/admin/roles", "admin:roles:read"),
      item("settings", "/admin/settings", "admin:settings:read"),
    ],
  },
];

const shown = (session: SessionInfo) =>
  visible(AREAS, session).map((area) => [area.key, area.items.map((entry) => entry.key)]);

describe("the navigation a caller is shown (UI-2)", () => {
  test("an administrator sees everything, browsing before administration", () => {
    expect(shown(ADMIN)).toEqual([
      ["browse", ["repositories", "search"]],
      ["administration", ["users", "roles", "settings"]],
    ]);
  });

  test("an item is hidden from a caller who lacks its permission", () => {
    const helpdesk: SessionInfo = { ...ADMIN, permissions: ["admin:users"] };

    expect(shown(helpdesk)).toEqual([
      ["browse", ["repositories", "search"]],
      ["administration", ["users"]],
    ]);
  });

  test("an area with nothing left in it is not shown", () => {
    const developer: SessionInfo = { ...ADMIN, permissions: ["repository:*:*:read"] };

    expect(shown(developer)).toEqual([["browse", ["repositories", "search"]]]);
    expect(shown(NOBODY)).toEqual([["browse", ["repositories", "search"]]]);
  });

  test("a visitor sees no administration, whatever the anonymous user holds", () => {
    expect(shown({ ...VISITOR, permissions: ["*"] })).toEqual([
      ["browse", ["repositories", "search"]],
    ]);
  });

  test("nothing is changed in the navigation it is given", () => {
    visible(AREAS, NOBODY);

    expect(AREAS[1]?.items).toHaveLength(3);
  });
});

describe("the navigation as it is", () => {
  test("has the browsing area first, and every item an address of the UI", () => {
    expect(NAVIGATION.map((area) => area.key)).toEqual(["browse", "administration"]);
    for (const entry of NAVIGATION.flatMap((area) => area.items)) {
      expect(entry.href.startsWith("/")).toBe(true);
    }
    expect(NAVIGATION[0]?.items[0]).toMatchObject({ key: "repositories", href: "/", icon: Boxes });
  });

  test("shows each part of the administration to whoever may read it (UI-2)", () => {
    const administration = (session: SessionInfo) =>
      visible(NAVIGATION, session)
        .filter((area) => area.key === "administration")
        .flatMap((area) => area.items.map((entry) => [entry.key, entry.href]));

    expect(administration(ADMIN)).toEqual([
      ["users", "/admin/users"],
      ["roles", "/admin/roles"],
      ["anonymousAccess", "/admin/anonymous-access"],
      ["authentication", "/admin/authentication"],
      ["manageRepositories", "/admin/repositories"],
      ["blobStores", "/admin/blob-stores"],
      ["system", "/admin/system"],
    ]);
    // How people sign in is security's, not a setting's (spec 4.3).
    expect(administration({ ...ADMIN, permissions: ["admin:security:read"] })).toEqual([
      ["authentication", "/admin/authentication"],
    ]);
    expect(administration({ ...ADMIN, permissions: ["admin:roles:read"] })).toEqual([
      ["roles", "/admin/roles"],
    ]);
    // Anonymous access and the system page are both settings.
    expect(administration({ ...ADMIN, permissions: ["admin:settings"] })).toEqual([
      ["anonymousAccess", "/admin/anonymous-access"],
      ["system", "/admin/system"],
    ]);
    expect(administration({ ...ADMIN, permissions: ["admin:repositories:read"] })).toEqual([
      ["manageRepositories", "/admin/repositories"],
    ]);
    expect(administration({ ...ADMIN, permissions: ["admin:blobstores:*"] })).toEqual([
      ["blobStores", "/admin/blob-stores"],
    ]);
    expect(administration({ ...ADMIN, permissions: ["repository:*:*:*"] })).toEqual([]);
    // Whatever the anonymous user holds, nobody administers without signing in.
    expect(administration({ ...VISITOR, permissions: ["*"] })).toEqual([]);
  });

  test("marks an administration item for everything under it", () => {
    const current = (pathname: string) =>
      NAVIGATION.flatMap((area) => area.items)
        .filter((entry) => isCurrent(entry, pathname))
        .map((entry) => entry.key);

    expect(current("/admin/users")).toEqual(["users"]);
    expect(current("/admin/users/new")).toEqual(["users"]);
    expect(current("/admin/roles/deployers")).toEqual(["roles"]);
    expect(current("/admin/anonymous-access")).toEqual(["anonymousAccess"]);
    // The settings of a repository are among those that are managed, not those that are browsed.
    expect(current("/admin/repositories/releases")).toEqual(["manageRepositories"]);
    expect(current("/admin/repositories/~new")).toEqual(["manageRepositories"]);
    expect(current("/admin/blob-stores")).toEqual(["blobStores"]);
    expect(current("/admin/system")).toEqual(["system"]);
    expect(current("/account/tokens")).toEqual([]);
  });

  test("leads to the repositories, to search and to upload", () => {
    const [browse] = visible(NAVIGATION, ADMIN);

    expect(browse?.items.map((entry) => [entry.key, entry.href])).toEqual([
      ["repositories", "/"],
      ["search", "/search"],
      ["upload", "/upload"],
    ]);
  });

  test("offers an upload only to whoever could upload somewhere (UI-2)", () => {
    const offered = (permissions: string[]) =>
      visible(NAVIGATION, { ...ADMIN, permissions })
        .flatMap((area) => area.items)
        .map((entry) => entry.key);

    expect(offered(["repository:maven:releases:add"])).toContain("upload");
    expect(offered(["repository:*:*:edit"])).toContain("upload");
    expect(offered(["repository:*:*:browse", "repository:*:*:read"])).toEqual([
      "repositories",
      "search",
    ]);
    expect(offered(["repository:maven:releases:delete"])).not.toContain("upload");
    expect(visible(NAVIGATION, VISITOR).flatMap((area) => area.items)).toHaveLength(2);
    expect(visible(NAVIGATION, NOBODY).flatMap((area) => area.items)).toHaveLength(2);
  });

  test("marks the repositories while one is browsed, and a component of one is shown", () => {
    const current = (pathname: string) =>
      NAVIGATION.flatMap((area) => area.items)
        .filter((entry) => isCurrent(entry, pathname))
        .map((entry) => entry.key);

    expect(current("/")).toEqual(["repositories"]);
    expect(current("/browse/releases/com/acme")).toEqual(["repositories"]);
    expect(current("/components/releases/0190-c0")).toEqual(["repositories"]);
    expect(current("/search")).toEqual(["search"]);
    expect(current("/upload/releases")).toEqual(["upload"]);
    expect(current("/browser")).toEqual([]); // an address that only begins the same
    expect(current("/account/password")).toEqual([]);
  });
});

describe("where the visitor is", () => {
  test("the home item is current at home only", () => {
    const home = item("repositories", "/");

    expect(isCurrent(home, "/")).toBe(true);
    expect(isCurrent(home, "/search")).toBe(false);
  });

  test("any other item is current at its address and under it", () => {
    const users = item("users", "/admin/users");

    expect(isCurrent(users, "/admin/users")).toBe(true);
    expect(isCurrent(users, "/admin/users/42")).toBe(true);
    expect(isCurrent(users, "/admin/users-and-more")).toBe(false);
    expect(isCurrent(users, "/admin")).toBe(false);
  });
});
