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
