# Account and Security Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person manages their own account in the web UI (API tokens, password, preferences), and an administrator manages people: users, roles written as rows of permissions, and anonymous access.

**Architecture:** Each screen is a client component that asks the security API of plan 2 through TanStack Query, as the screens of plan 10a ask the content API. A permission pattern is taken apart into a row of a form and put together again by one module with no React in it; what the lists of a row cannot say stays a pattern typed by hand, so that nothing a role holds is lost. A token's secret and a password that is passed on live in component state only. Preferences are kept in the browser, as the mode is. No backend change.

**Tech Stack:** Next.js 16.4 (App Router), React 19.3, TypeScript 5.9, Tailwind CSS 4.3, Radix primitives, TanStack Query 5, `next-intl` 4, Vitest 5 with Testing Library and axe, Playwright with `@axe-core/playwright`. No new dependency.

**Spec:** [docs/superpowers/specs/2026-10-12-frontend-design.md](../specs/2026-10-12-frontend-design.md), section 12.3 (decisions A1 to A13 and the table of addresses), with S3, S9 and S11 of section 12.1 and B11 of 12.2. Business requirements: [docs/BRD.md](../../BRD.md) SEC-1 to SEC-9, UI-1 to UI-6. Task 6 amends the spec where this plan settles something it left open (A14 to A20).

**Read first:** `frontend/AGENTS.md`. The API these screens call is in `backend/src/megooarti/security/api/` (`me.py`, `users.py`, `roles.py`) and `backend/src/megooarti/system/settings_api.py`; its shapes are in `frontend/src/lib/api/schema.d.ts`.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| A14 | In a wide window the navigation is a row of its own in the header, under the wordmark and the search box, and wraps where it does not fit. | With the administration's items beside the browsing ones, the navigation ran under the search box, which took the clicks meant for "Roles". |
| A15 | Whether an element is on the screen is asked of the browser in `lib/browser.ts`, which the tests replace. | A12 needs it, and the test environment lays nothing out. |
| A16 | The rows of a role keep to themselves once shown: a pattern typed by hand stays a typed row, though it becomes one the lists could say. | The field would otherwise turn into lists under the hands that are typing in it. |
| A17 | A row that is added gets the keyboard. Where what had the keyboard goes (a row removed, a token revoked, the panel of a token or user just made), the keyboard is put at what is nearest: the button that adds, the list of tokens, the form's first field. | B11 of plan 10a. |
| A18 | A new user's password is shown once more after the user is made, with a button that copies it. A password set for an existing user stays in its field. | The administrator has to pass it on. |
| A19 | What a visitor may do is the patterns of the anonymous user's roles and of the roles they contain, and of those only what concerns repositories. | The server allows a request without credentials nothing else. |
| A20 | The request that makes a token is forgotten by the store as soon as its answer is handed over (`gcTime: 0`). | A5: the secret is kept nowhere. |
| A21 | The texts of every screen of this plan are added to `messages/en.json` in Task 2, with the shell's own changes. | One file, typed as a whole; the user menu's "Change password" goes when "Account" comes. |

## Global Constraints

- **A colour is written in `src/styles/tokens.css` and nowhere else.**
- **Text a person reads or hears is in `messages/en.json`.** ESLint refuses it in markup and in a property that is read out; a unit test fails on a text that is missing.
- **What comes from the API is text.** A name goes into an address through `lib/paths.ts`.
- **A secret is kept nowhere:** not in what was fetched, not in an address, not in the browser's storage, not in a log.
- **What a caller may not do is not offered** (UI-2); the server is still what decides. A form whose data may be read and not changed is shown without the button that saves.
- **When a screen changes under the keyboard, the keyboard is put at what changed** (B11). A field that is wrong gets the keyboard (section 11a).
- **Status is never colour alone. Every control has a name, and everything works by keyboard.**
- **Formatting:** Prettier, 100 columns, LF line endings. ESLint and `tsc` are clean after every task.
- **This plan adds no dependency, no migration, no backend code and no setting.** The one backend file it touches is a test.

**Working directories:** run `pnpm` commands in `frontend/`, `uv` and `pytest` commands in `backend/`, and `git` commands in the repository root. Backend tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **A role that this UI did not write:** a pattern shorter or longer than a row, an action or an area this UI does not know, a repository that is gone, a format with no repository, text that is no pattern; opened and saved, it must come back as it was (Tasks 1, 2, 4 and 6).
2. **A secret on its way through the page:** a token's secret and a generated password, in what was fetched, in the address, in storage, after the panel is closed; a password field the browser might fill or offer to remember (Tasks 1, 2, 3, 4 and 6).
3. **A caller who may read and not change, or neither:** each screen with read-only permissions; users without the right to see roles or tokens; the anonymous user's roles without the right to see users; a visitor at the preferences page and at the rest of the account (Tasks 1, 2, 3 and 4).
4. **What the server protects:** one's own account, a built-in user or role, the `admin` role, the last administrator, a role that would contain itself, a name that is taken; a user or role deleted while its page is open (Task 4).
5. **Where the keyboard is afterwards:** a row added or removed, a token revoked, a panel closed, a form refused, the `/` key turned off, and the key in a window too narrow to show the search box (Tasks 2, 3, 4 and 6).

---

### Task 1: Patterns, passwords, preferences and the requests of the screens

**Files:**
- Create: `frontend/src/lib/patterns.ts`, `passwords.ts`, `preferences.ts`, `refusals.ts`, `security.ts` (all in `frontend/src/lib/`)
- Modify: `frontend/src/lib/api/types.ts`, `frontend/src/lib/browser.ts`, `frontend/src/lib/paths.ts`, `frontend/src/lib/session/rules.ts`
- Test: `frontend/src/lib/account.test.ts`
- Test (modify): `frontend/src/test/setup.ts`

**Interfaces:**
- Consumes: `api`, `ApiError`, `isApiError` of `lib/api/client.ts`; `SESSION_KEY` of `lib/session/session.ts`; the generated `schema.d.ts`.
- Produces:
  - `lib/patterns.ts`: `ANY`, `REPOSITORY_ACTIONS`, `ADMIN_AREAS`, `ADMIN_ACTIONS`, `READ_ONLY`, `isValidPattern(pattern)`, `Row` (`{ kind: "repository"; format; name; action } | { kind: "admin"; area; action } | { kind: "all" } | { kind: "typed"; text }`), `RowKind`, `toPattern(row)`, `fromPattern(pattern)`, `startOf(kind)`.
  - `lib/passwords.ts`: `ALPHABET`, `GENERATED_LENGTH`, `generatePassword(length?)`.
  - `lib/preferences.ts`: `SEARCH_KEY_STORAGE`, `searchKeyIsOn()`, `setSearchKey(on)`, `useSearchKey() -> [on, set]`.
  - `lib/refusals.ts`: `refusalsOf(error, fields) -> { at: Record<field, message>; elsewhere: boolean }`, `NOTHING_REFUSED`.
  - `lib/browser.ts`: `isOnScreen(element)`; in tests it is true unless the element is inside something with the `hidden` attribute.
  - `lib/paths.ts`: `ACCOUNT_TOKENS`, `PREFERENCES`, `USERS`, `NEW_USER`, `ROLES`, `NEW_ROLE`, `ANONYMOUS_ACCESS`, `pageHref(list, page)`, `pageOf(search)`, `userHref(id)`, `roleHref(name)`, `parseUser(pathname) -> { id } | null`, `parseRole(pathname) -> { name } | null`.
  - `lib/session/rules.ts`: `decide` shows `/account/preferences` to a visitor.
  - `lib/api/types.ts`: `TokenInfo`, `TokenCreated`, `TokenCreate`, `UserOut`, `UserCreate`, `UserUpdate`, `PasswordReset`, `RoleOut`, `RoleCreate`, `RoleContent`, `SettingsOut`.
  - `lib/security.ts`: `AT_ONCE`, `useMyTokens(page)`, `useCreateToken()`, `useRevokeToken()`, `useUsers(page)`, `useUser(id | null)`, `useAnonymousUser(enabled)`, `useCreateUser()`, `useUpdateUser(id)`, `useResetPassword(id)`, `useDeleteUser()`, `useUserTokens(id, enabled)`, `useRevokeUserToken(id)`, `useRoles(page)`, `useEveryRole(enabled?)`, `useRole(name | null)`, `useCreateRole()`, `useUpdateRole(name)`, `useDeleteRole()`, `useSettings()`, `useSetAnonymousAccess()`. A change to a user or a role invalidates the session (A10).

- [ ] **Step 1: Write the failing tests**

Change `frontend/src/test/setup.ts`:

```diff
@@ -16,7 +16,12 @@ vi.mock("next/navigation", () => ({
 }));
 
 // Loading another page is the browser's doing. A test sees that it was asked for.
-vi.mock("@/lib/browser", () => ({ leaveTo: vi.fn() }));
+// And so is saying what is on the screen: jsdom lays nothing out. Here, what is inside
+// something with the `hidden` attribute is not.
+vi.mock("@/lib/browser", () => ({
+  leaveTo: vi.fn(),
+  isOnScreen: (element: Element) => element.closest("[hidden]") === null,
+}));
 
 // jsdom has no media queries: the system's mode is what a test says it is.
 let systemIsDark = true;
```

Create `frontend/src/lib/account.test.ts`:

```ts
import type { Route } from "next";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import { ALPHABET, generatePassword } from "@/lib/passwords";
import { pageHref, pageOf, parseRole, parseUser, roleHref, userHref, USERS } from "@/lib/paths";
import {
  fromPattern,
  isValidPattern,
  READ_ONLY,
  startOf,
  toPattern,
  type Row,
} from "@/lib/patterns";
import { SEARCH_KEY_STORAGE, searchKeyIsOn, setSearchKey } from "@/lib/preferences";
import { refusalsOf } from "@/lib/refusals";
import { grants } from "@/lib/session/permissions";
import { decide } from "@/lib/session/rules";
import { ADMIN, NOBODY, VISITOR } from "@/test/render";

describe("a permission pattern", () => {
  // As the backend takes them (megooarti.security.permissions.is_valid_pattern).
  test.each([
    ["*", true],
    ["admin:users:*", true],
    ["repository:maven:my.repo-1_x:read", true],
    ["repository:*:*:read", true],
    ["", false],
    ["admin::read", false],
    ["admin:us ers", false],
    ["admin:**", false],
    ["admin:use*", false],
    ["é", false],
  ])("%s is one: %s", (pattern, expected) => {
    expect(isValidPattern(pattern)).toBe(expected);
  });

  test.each<[string, Row]>([
    ["*", { kind: "all" }],
    [
      "repository:maven:releases:read",
      { kind: "repository", format: "maven", name: "releases", action: "read" },
    ],
    ["repository:*:*:browse", { kind: "repository", format: "*", name: "*", action: "browse" }],
    ["repository:npm:*:*", { kind: "repository", format: "npm", name: "*", action: "*" }],
    ["admin:users:write", { kind: "admin", area: "users", action: "write" }],
    ["admin:*:read", { kind: "admin", area: "*", action: "read" }],
    ["admin:*:*", { kind: "admin", area: "*", action: "*" }],
  ])("%s is taken apart into a row, and the row makes it again", (pattern, row) => {
    expect(fromPattern(pattern)).toEqual(row);
    expect(toPattern(row)).toBe(pattern);
  });

  // Each grants something, and is kept as it was written: nothing a role holds is
  // rewritten by opening it (A3).
  test.each([
    "repository:maven", // shorter: everything in every Maven repository
    "repository",
    "admin",
    "admin:users",
    "repository:maven:releases:publish", // an action this UI does not know
    "admin:audit:read", // an area this UI does not know
    "admin:users:read:more",
    "*:users:read",
    "metrics:read",
  ])("%s is of no shape a row has, and stays as it was typed", (pattern) => {
    expect(fromPattern(pattern)).toEqual({ kind: "typed", text: pattern });
    expect(toPattern(fromPattern(pattern))).toBe(pattern);
  });

  test("what is no pattern at all is a typed row too, to be put right", () => {
    expect(fromPattern("not a pattern")).toEqual({ kind: "typed", text: "not a pattern" });
    expect(toPattern({ kind: "typed", text: "  admin:users  " })).toBe("admin:users");
  });

  test("a row starts as the widest of its shape that only reads", () => {
    expect(toPattern(startOf("repository"))).toBe("repository:*:*:read");
    expect(toPattern(startOf("admin"))).toBe("admin:*:read");
    expect(toPattern(startOf("all"))).toBe("*");
    expect(toPattern(startOf("typed"))).toBe("");
  });

  test("a token that may only read can browse and download, and nothing else", () => {
    const may = (permission: string) => READ_ONLY.some((pattern) => grants(pattern, permission));

    expect(may("repository:maven:releases:browse")).toBe(true);
    expect(may("repository:npm:own:read")).toBe(true);
    expect(may("repository:maven:releases:add")).toBe(false);
    expect(may("repository:maven:releases:delete")).toBe(false);
    expect(may("admin:users:read")).toBe(false);
  });
});

describe("a generated password", () => {
  afterEach(() => vi.restoreAllMocks());

  test("is twenty characters that are not mistaken for each other", () => {
    const password = generatePassword();

    expect(password).toHaveLength(20);
    expect(Array.from(password).every((character) => ALPHABET.includes(character))).toBe(true);
    for (const confusing of "0O1lI") expect(ALPHABET).not.toContain(confusing);
    expect(generatePassword(32)).toHaveLength(32);
  });

  test("is another one each time, from the browser's own randomness", () => {
    const random = vi.spyOn(crypto, "getRandomValues");

    const made = new Set(Array.from({ length: 50 }, () => generatePassword()));

    expect(made.size).toBe(50);
    expect(random).toHaveBeenCalled();
  });

  test("favours no letter: a byte that would is drawn again", () => {
    // 228 is the first byte past the last whole run of the alphabet (4 x 57): taken, it
    // would make the first letters likelier than the last.
    expect(ALPHABET).toHaveLength(57);
    const bytes = [228, 255, 0, 56, 57, 227];
    vi.spyOn(crypto, "getRandomValues").mockImplementation((array) => {
      (array as Uint8Array).set(
        Array.from({ length: (array as Uint8Array).length }, () => bytes.shift() ?? 1),
      );
      return array;
    });

    expect(generatePassword(4)).toBe(`${ALPHABET[0]}${ALPHABET[56]}${ALPHABET[0]}${ALPHABET[56]}`);
  });
});

describe("the search key", () => {
  test("is on until it is turned off, and is kept in the browser", () => {
    expect(searchKeyIsOn()).toBe(true);

    setSearchKey(false);
    expect(searchKeyIsOn()).toBe(false);
    expect(window.localStorage.getItem(SEARCH_KEY_STORAGE)).toBe("off");

    setSearchKey(true);
    expect(searchKeyIsOn()).toBe(true);
    expect(window.localStorage.getItem(SEARCH_KEY_STORAGE)).toBeNull();
  });

  test("is on where storage cannot be read, and turning it off there breaks nothing", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });

    expect(() => setSearchKey(false)).not.toThrow();
    expect(searchKeyIsOn()).toBe(true);
    vi.restoreAllMocks();
  });

  test("tells the page when it changes", () => {
    const told = vi.fn();
    window.addEventListener("megooarti-preferences", told);

    setSearchKey(false);

    expect(told).toHaveBeenCalledOnce();
    window.removeEventListener("megooarti-preferences", told);
  });
});

describe("what the API refused of a form", () => {
  const refusal = (details: { field: string; message: string }[]) =>
    new ApiError(422, "validation_error", "The request is not valid.", details, null);

  test("is put at the form's own field, whatever the server calls the place", () => {
    const refused = refusalsOf(
      refusal([
        { field: "body.name", message: "Too long." },
        { field: "password", message: "Too short." },
        { field: "body.permissions.2", message: "Not a pattern." },
      ]),
      ["name", "password", "permissions"],
    );

    expect(refused).toEqual({
      at: { name: "Too long.", password: "Too short.", permissions: "Not a pattern." },
      elsewhere: false,
    });
  });

  test("says the first thing wrong with a field, and not the rest", () => {
    const refused = refusalsOf(
      refusal([
        { field: "body.permissions.0", message: "First." },
        { field: "body.permissions.3", message: "Second." },
      ]),
      ["permissions"],
    );

    expect(refused.at).toEqual({ permissions: "First." });
  });

  test("is said whole when it is about nothing the form has", () => {
    expect(refusalsOf(refusal([{ field: "body.colour", message: "?" }]), ["name"])).toEqual({
      at: {},
      elsewhere: true,
    });
    // A field whose name only begins the same is another field.
    expect(refusalsOf(refusal([{ field: "body.names", message: "?" }]), ["name"]).elsewhere).toBe(
      true,
    );
    expect(refusalsOf(refusal([]), ["name"]).elsewhere).toBe(true);
  });

  test("a failure of another kind is said whole, and no failure is nothing", () => {
    const conflict = new ApiError(409, "conflict", "A user named alice already exists.", [], null);

    expect(refusalsOf(conflict, ["username"])).toEqual({ at: {}, elsewhere: true });
    expect(refusalsOf(new Error("?"), ["username"]).elsewhere).toBe(true);
    expect(refusalsOf(null, ["username"])).toEqual({ at: {}, elsewhere: false });
  });
});

describe("the addresses of the account and security screens", () => {
  test("a user is addressed by its id, a role by its name, each as one segment", () => {
    expect(userHref("0190-aa")).toBe("/admin/users/0190-aa");
    expect(roleHref("deployers")).toBe("/admin/roles/deployers");
    expect(roleHref("odd/name?#")).toBe("/admin/roles/odd%2Fname%3F%23");

    expect(parseUser("/admin/users/0190-aa")).toEqual({ id: "0190-aa" });
    expect(parseRole("/admin/roles/odd%2Fname%3F%23")).toEqual({ name: "odd/name?#" });
  });

  test("an address that names none is not read as one", () => {
    expect(parseUser("/admin/users")).toBeNull();
    expect(parseUser("/admin/users/a/b")).toBeNull();
    expect(parseRole("/admin/roles/")).toBeNull();
    expect(parseRole("/admin/rolesx/a")).toBeNull();
    expect(parseRole("/admin/roles/%E0%A4%A")).toBeNull();
  });

  test("the first page of a list has no number in its address", () => {
    expect(pageHref(USERS, 1)).toBe("/admin/users");
    expect(pageHref(USERS, 3)).toBe("/admin/users?page=3");
    expect(pageHref("/account/tokens" as Route, 2)).toBe("/account/tokens?page=2");
  });

  test.each([
    ["", 1],
    ["page=1", 1],
    ["page=7", 7],
    ["page=0", 1],
    ["page=-2", 1],
    ["page=2x", 1],
    ["page=1.5", 1],
    ["page=99999999999999999999", 1],
  ])("the page of ?%s is %i", (query, page) => {
    expect(pageOf(new URLSearchParams(query))).toBe(page);
  });
});

describe("the preferences page", () => {
  test("is a visitor's too, though the rest of the account is not", () => {
    expect(decide(VISITOR, "/account/preferences")).toEqual({ show: true });
    expect(decide(VISITOR, "/account/tokens")).toEqual({
      show: false,
      goTo: "/login?next=%2Faccount%2Ftokens",
    });
    expect(decide(VISITOR, "/account/preferences-and-more").show).toBe(false);
    expect(decide(ADMIN, "/account/preferences")).toEqual({ show: true });
  });

  test("is not shown where nobody may be without signing in", () => {
    expect(decide(NOBODY, "/account/preferences")).toEqual({
      show: false,
      goTo: "/login?next=%2Faccount%2Fpreferences",
    });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 1 file fails and none of its tests runs: `Failed to resolve import` of one of the modules this task creates, from `src/lib/account.test.ts`. The other 524 tests pass.

- [ ] **Step 3: Implement**

Change `frontend/src/lib/api/types.ts`:

```diff
@@ -17,6 +17,19 @@ export type UsageView = Schemas["UsageView"];
 export type SearchResult = Schemas["Result"];
 export type Uploaded = Schemas["Uploaded"];
 export type FolderDeleted = Schemas["FolderDeleted"];
+/** An API token as it is listed: never its secret. */
+export type TokenInfo = Schemas["TokenInfo"];
+/** A token that was just made, with its secret, which is given this once. */
+export type TokenCreated = Schemas["TokenCreated"];
+export type TokenCreate = Schemas["TokenCreate"];
+export type UserOut = Schemas["UserOut"];
+export type UserCreate = Schemas["UserCreate"];
+export type UserUpdate = Schemas["UserUpdate"];
+export type PasswordReset = Schemas["PasswordReset"];
+export type RoleOut = Schemas["RoleOut"];
+export type RoleCreate = Schemas["RoleCreate"];
+export type RoleContent = Schemas["RoleContent"];
+export type SettingsOut = Schemas["SettingsOut"];
 
 /** A page of a list, as every list endpoint answers. */
 export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
```

Create `frontend/src/lib/patterns.ts`:

```ts
/**
 * Permission patterns, as the rows of a form and back. No React here.
 *
 * A pattern is words joined by `:`, with `*` for any one word; a pattern shorter than
 * what is asked grants everything under it (`megooarti.security.permissions`). A row is
 * a pattern of one of the shapes the API uses, taken apart so that it can be chosen
 * from lists. A pattern of any other shape is a row typed by hand, and is kept as it is.
 */

export const ANY = "*";
/** What can be done to a repository's content. */
export const REPOSITORY_ACTIONS = ["browse", "read", "add", "edit", "delete"] as const;
/** The areas of administration the API has. */
export const ADMIN_AREAS = [
  "users",
  "roles",
  "tokens",
  "settings",
  "blobstores",
  "repositories",
] as const;
export const ADMIN_ACTIONS = ["read", "write"] as const;
/** What a token that may only read is limited to. */
export const READ_ONLY = ["repository:*:*:browse", "repository:*:*:read"] as const;

const WORD = /^[A-Za-z0-9_.-]+$/;

/** Whether the server would take it as a pattern. */
export function isValidPattern(pattern: string): boolean {
  return pattern.split(":").every((part) => part === ANY || WORD.test(part));
}

export type Row =
  | { kind: "repository"; format: string; name: string; action: string }
  | { kind: "admin"; area: string; action: string }
  | { kind: "all" }
  | { kind: "typed"; text: string };

export type RowKind = Row["kind"];

const known = (values: readonly string[], value: string | undefined) =>
  value === ANY || (value !== undefined && values.includes(value));

/** The pattern a row stands for. A typed row is what was typed, without space around it. */
export function toPattern(row: Row): string {
  switch (row.kind) {
    case "repository":
      return `repository:${row.format}:${row.name}:${row.action}`;
    case "admin":
      return `admin:${row.area}:${row.action}`;
    case "all":
      return ANY;
    case "typed":
      return row.text.trim();
  }
}

/**
 * The row for a pattern. Only a pattern that a row would write is taken apart: any
 * other, though it may grant the same (`repository:maven` for `repository:maven:*:*`),
 * stays as it was written.
 */
export function fromPattern(pattern: string): Row {
  if (pattern === ANY) return { kind: "all" };
  const typed: Row = { kind: "typed", text: pattern };
  if (!isValidPattern(pattern)) return typed;
  const [about, second, third, fourth, ...more] = pattern.split(":");
  if (more.length > 0 || second === undefined || third === undefined) return typed;
  if (about === "repository" && fourth !== undefined && known(REPOSITORY_ACTIONS, fourth)) {
    return { kind: "repository", format: second, name: third, action: fourth };
  }
  if (
    about === "admin" &&
    fourth === undefined &&
    known(ADMIN_AREAS, second) &&
    known(ADMIN_ACTIONS, third)
  ) {
    return { kind: "admin", area: second, action: third };
  }
  return typed;
}

/** A row of a kind, as it starts: the widest of its shape that only reads. */
export function startOf(kind: RowKind): Row {
  switch (kind) {
    case "repository":
      return { kind, format: ANY, name: ANY, action: "read" };
    case "admin":
      return { kind, area: ANY, action: "read" };
    case "all":
      return { kind };
    case "typed":
      return { kind, text: "" };
  }
}
```

Create `frontend/src/lib/passwords.ts`:

```ts
/** A password an administrator gives to someone, who then chooses their own. No React here. */

// Letters and digits that are not taken for one another when read aloud or copied by
// hand: no 0 and O, no 1, l and I.
export const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
export const GENERATED_LENGTH = 20;

/**
 * A password of `length` characters, each as likely as any other, from the browser's
 * own source of randomness. A byte that would favour the first letters of the alphabet
 * is thrown away and drawn again.
 */
export function generatePassword(length: number = GENERATED_LENGTH): string {
  const fair = 256 - (256 % ALPHABET.length);
  const drawn: string[] = [];
  while (drawn.length < length) {
    for (const byte of crypto.getRandomValues(new Uint8Array(length))) {
      if (byte < fair && drawn.length < length) drawn.push(ALPHABET[byte % ALPHABET.length] ?? "");
    }
  }
  return drawn.join("");
}
```

Create `frontend/src/lib/preferences.ts`:

```ts
"use client";

/**
 * What a person prefers of this UI besides the mode, kept in their browser as the mode
 * is. So far there is one: whether `/` goes to the search box. A shortcut that is one
 * character must be one that can be turned off (WCAG 2.1.4): it gets in the way of
 * whoever dictates, or whose keyboard sends keys they did not mean.
 */
import { useCallback, useSyncExternalStore } from "react";

export const SEARCH_KEY_STORAGE = "megooarti-search-key";
const OFF = "off";
const CHANGED = "megooarti-preferences";

/** Whether `/` goes to the search box. It does unless it was turned off. */
export function searchKeyIsOn(): boolean {
  try {
    return window.localStorage.getItem(SEARCH_KEY_STORAGE) !== OFF;
  } catch {
    return true; // storage cannot be read: as if nothing had been chosen
  }
}

export function setSearchKey(on: boolean): void {
  try {
    if (on) window.localStorage.removeItem(SEARCH_KEY_STORAGE);
    else window.localStorage.setItem(SEARCH_KEY_STORAGE, OFF);
  } catch {
    // Storage is off or full. Nothing can be kept then.
  }
  // The same window is not told of its own writes to storage.
  window.dispatchEvent(new Event(CHANGED));
}

function subscribe(changed: () => void): () => void {
  window.addEventListener("storage", changed); // another tab
  window.addEventListener(CHANGED, changed); // this one
  return () => {
    window.removeEventListener("storage", changed);
    window.removeEventListener(CHANGED, changed);
  };
}

/** Whether `/` goes to the search box, and a way to say so. On the server it is on. */
export function useSearchKey(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, searchKeyIsOn, () => true);
  return [on, useCallback((next: boolean) => setSearchKey(next), [])];
}
```

Create `frontend/src/lib/refusals.ts`:

```ts
/**
 * What the API refused of a form, by the field it refused it at. No React here.
 *
 * A refusal of what was sent has the code `validation_error` and says, for each thing
 * that is wrong, where: `body.name` for the name in the body, `body.permissions.2` for
 * the third permission, or a plain `password` where the check is the server's own.
 */
import { isApiError } from "@/lib/api/client";

export type Refusals = {
  /** What is wrong, by the form's own name for the field. */
  at: Record<string, string>;
  /**
   * Whether something was refused that no field of the form can show: a failure of
   * another kind, or a detail about something the form does not have. It is then said
   * whole, where the form's button is.
   */
  elsewhere: boolean;
};

export const NOTHING_REFUSED: Refusals = { at: {}, elsewhere: false };

/** `fields` are the names the form has places for. A place takes what is under it too. */
export function refusalsOf(error: unknown, fields: readonly string[]): Refusals {
  if (error === null || error === undefined) return NOTHING_REFUSED;
  if (!isApiError(error) || error.code !== "validation_error" || error.details.length === 0) {
    return { at: {}, elsewhere: true };
  }
  const refused: Refusals = { at: {}, elsewhere: false };
  for (const detail of error.details) {
    const where = (detail.field ?? "").replace(/^body\./, "");
    const field = fields.find((name) => where === name || where.startsWith(`${name}.`));
    if (field === undefined) refused.elsewhere = true;
    // The first thing wrong with a field is the one that is said.
    else refused.at[field] ??= detail.message;
  }
  return refused;
}
```

Change `frontend/src/lib/browser.ts`:

```diff
@@ -4,3 +4,11 @@
 export function leaveTo(path: string): void {
   window.location.assign(path);
 }
+
+/**
+ * Whether an element is on the screen: not one that is hidden at this width, or inside
+ * a part that is closed. Only a browser that lays the page out can say.
+ */
+export function isOnScreen(element: Element): boolean {
+  return element.getClientRects().length > 0;
+}
```

Change `frontend/src/lib/paths.ts`:

```diff
@@ -12,6 +12,13 @@ const BROWSE = "/browse";
 const COMPONENTS = "/components";
 const UPLOAD = "/upload";
 const SEARCH = "/search";
+export const ACCOUNT_TOKENS = "/account/tokens" as Route;
+export const PREFERENCES = "/account/preferences" as Route;
+export const USERS = "/admin/users" as Route;
+export const NEW_USER = "/admin/users/new" as Route;
+export const ROLES = "/admin/roles" as Route;
+export const NEW_ROLE = "/admin/roles/new" as Route;
+export const ANONYMOUS_ACCESS = "/admin/anonymous-access" as Route;
 
 const segments = (path: string) => path.split("/").filter((segment) => segment !== "");
 const encoded = (path: string) => segments(path).map(encodeURIComponent).join("/");
@@ -50,6 +57,25 @@ export function searchHref(wanted: Record<string, string | undefined>): Route {
   return withQuery(SEARCH, wanted);
 }
 
+/** A page of a list that has numbered pages. The first has no number in its address. */
+export function pageHref(list: Route, page: number): Route {
+  return withQuery(list, { page: page > 1 ? String(page) : undefined });
+}
+
+/** The page an address asks for: a whole number from 1, or 1 for anything else. */
+export function pageOf(search: { get(name: string): string | null }): number {
+  const asked = search.get("page") ?? "";
+  return /^[1-9][0-9]{0,8}$/.test(asked) ? Number(asked) : 1;
+}
+
+export function userHref(id: string): Route {
+  return `${USERS}/${encodeURIComponent(id)}` as Route;
+}
+
+export function roleHref(name: string): Route {
+  return `${ROLES}/${encodeURIComponent(name)}` as Route;
+}
+
 /**
  * An address the API gave, if a link may lead to it: one of `http` or `https`. A file's
  * download address is built from the installation's base URL, which is a setting, and
@@ -104,3 +130,21 @@ export function parseUpload(pathname: string): { repository: string } | null {
   const [repository] = found ?? [];
   return found?.length === 1 && repository ? { repository } : null;
 }
+
+/** The one thing an address under a list names: a user's id, a role's name. Null if none. */
+function one(pathname: string, list: string): string | null {
+  const found = after(pathname, list);
+  const [name] = found ?? [];
+  return found?.length === 1 && name ? name : null;
+}
+
+/** The id of the user an address is about. `new` is the form for one that is not there yet. */
+export function parseUser(pathname: string): { id: string } | null {
+  const id = one(pathname, USERS);
+  return id === null ? null : { id };
+}
+
+export function parseRole(pathname: string): { name: string } | null {
+  const name = one(pathname, ROLES);
+  return name === null ? null : { name };
+}
```

Change `frontend/src/lib/session/rules.ts`:

```diff
@@ -11,6 +11,8 @@ export const SIGN_IN = "/login";
 export const CHANGE_PASSWORD = "/account/password";
 // What only a person who is signed in has.
 const ACCOUNT_AREA = "/account";
+// But for this: what is kept in the browser is as much a visitor's as anybody's.
+const PREFERENCES = "/account/preferences";
 
 export type Decision = { show: true } | { show: false; goTo: string };
 
@@ -90,6 +92,6 @@ export function decide(session: SessionInfo, path: string, next: string | null =
     return { show: true };
   }
   const inAccount = pathname === ACCOUNT_AREA || pathname.startsWith(`${ACCOUNT_AREA}/`);
-  if (isAnonymous(session) && !inAccount) return { show: true };
+  if (isAnonymous(session) && (!inAccount || pathname === PREFERENCES)) return { show: true };
   return { show: false, goTo: signInFor(path) };
 }
```

Create `frontend/src/lib/security.ts`:

```ts
"use client";

/**
 * Who may do what, asked of the API: a person's own tokens, and what an administrator
 * keeps (users, roles, anonymous access). The requests of the account and security
 * screens.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  Page,
  PasswordReset,
  RoleContent,
  RoleCreate,
  RoleOut,
  SettingsOut,
  TokenCreate,
  TokenCreated,
  TokenInfo,
  UserCreate,
  UserOut,
  UserUpdate,
} from "@/lib/api/types";
import { SESSION_KEY } from "@/lib/session/session";

// As many of a list as one page shows (A13).
export const AT_ONCE = 50;
// As many roles as one request may ask for: the choices of a form.
const EVERY = 200;

const TOKENS = "tokens";
const USERS = "users";
const ROLES = "roles";
const SETTINGS = "settings";

const paged = (page: number) => ({ limit: AT_ONCE, offset: (page - 1) * AT_ONCE });
const user = (id: string) => `/users/${encodeURIComponent(id)}`;
const role = (name: string) => `/roles/${encodeURIComponent(name)}`;

/**
 * After a user or a role changed, what the person who changed it may do can have
 * changed with it (their own roles, or a role they hold): the session is asked again.
 */
function afterSecurityChange(client: QueryClient): Promise<void> {
  void client.invalidateQueries({ queryKey: SESSION_KEY });
  void client.invalidateQueries({ queryKey: [ROLES] });
  return client.invalidateQueries({ queryKey: [USERS] });
}

// --- One's own tokens --------------------------------------------------------------------

export function useMyTokens(page: number) {
  return useQuery({
    queryKey: [TOKENS, "mine", page],
    queryFn: () => api.get<Page<TokenInfo>>("/me/tokens", { query: paged(page) }),
  });
}

/**
 * Creates a token. Its secret is in the answer and nowhere else: the answer is given
 * to whoever called, and is not kept among what was fetched.
 */
export function useCreateToken() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: TokenCreate) => api.post<TokenCreated>("/me/tokens", wanted),
    gcTime: 0,
    onSuccess: () => client.invalidateQueries({ queryKey: [TOKENS, "mine"] }),
  });
}

export function useRevokeToken() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/me/tokens/${encodeURIComponent(id)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: [TOKENS, "mine"] }),
  });
}

// --- Users ----------------------------------------------------------------------------------

export function useUsers(page: number) {
  return useQuery({
    queryKey: [USERS, "list", page],
    queryFn: () => api.get<Page<UserOut>>("/users", { query: paged(page) }),
  });
}

export function useUser(id: string | null) {
  return useQuery({
    queryKey: [USERS, "one", id],
    queryFn: () => api.get<UserOut>(user(id ?? "")),
    enabled: id !== null,
  });
}

/**
 * The built-in user a request without credentials acts as, or null if it is not among
 * the users that one request brings.
 */
export function useAnonymousUser(enabled: boolean) {
  return useQuery({
    queryKey: [USERS, "anonymous"],
    queryFn: async () => {
      const users = await api.get<Page<UserOut>>("/users", { query: { limit: EVERY } });
      return users.items.find((one) => one.builtin && one.username === "anonymous") ?? null;
    },
    enabled,
  });
}

export function useCreateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: UserCreate) => api.post<UserOut>("/users", wanted),
    onSuccess: () => afterSecurityChange(client),
  });
}

export function useUpdateUser(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: UserUpdate) => api.patch<UserOut>(user(id), changes),
    onSuccess: () => afterSecurityChange(client),
  });
}

export function useResetPassword(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: PasswordReset) => api.put<void>(`${user(id)}/password`, wanted),
    gcTime: 0, // what was sent is a password
    onSuccess: () => afterSecurityChange(client),
  });
}

export function useDeleteUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(user(id)),
    onSuccess: (_, id) => {
      client.removeQueries({ queryKey: [USERS, "one", id] });
      client.removeQueries({ queryKey: [TOKENS, "of", id] });
      return afterSecurityChange(client);
    },
  });
}

export function useUserTokens(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [TOKENS, "of", id],
    queryFn: () => api.get<Page<TokenInfo>>(`${user(id)}/tokens`, { query: { limit: EVERY } }),
    enabled,
  });
}

export function useRevokeUserToken(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (token: string) =>
      api.delete<void>(`${user(id)}/tokens/${encodeURIComponent(token)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: [TOKENS, "of", id] }),
  });
}

// --- Roles ----------------------------------------------------------------------------------

export function useRoles(page: number) {
  return useQuery({
    queryKey: [ROLES, "list", page],
    queryFn: () => api.get<Page<RoleOut>>("/roles", { query: paged(page) }),
  });
}

/** The roles there are, for a form to choose from. `enabled` is false for who may not read them. */
export function useEveryRole(enabled = true) {
  return useQuery({
    queryKey: [ROLES, "every"],
    queryFn: () => api.get<Page<RoleOut>>("/roles", { query: { limit: EVERY } }),
    enabled,
  });
}

export function useRole(name: string | null) {
  return useQuery({
    queryKey: [ROLES, "one", name],
    queryFn: () => api.get<RoleOut>(role(name ?? "")),
    enabled: name !== null,
  });
}

export function useCreateRole() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: RoleCreate) => api.post<RoleOut>("/roles", wanted),
    onSuccess: () => afterSecurityChange(client),
  });
}

export function useUpdateRole(name: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (content: RoleContent) => api.put<RoleOut>(role(name), content),
    onSuccess: () => afterSecurityChange(client),
  });
}

export function useDeleteRole() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.delete<void>(role(name)),
    onSuccess: (_, name) => {
      client.removeQueries({ queryKey: [ROLES, "one", name] });
      return afterSecurityChange(client);
    },
  });
}

// --- Settings -------------------------------------------------------------------------------

export function useSettings() {
  return useQuery({
    queryKey: [SETTINGS],
    queryFn: () => api.get<SettingsOut>("/settings"),
  });
}

export function useSetAnonymousAccess() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      api.put<SettingsOut>("/settings/anonymous-access", { enabled }),
    onSuccess: (settings) => client.setQueryData([SETTINGS], settings),
  });
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 576 passed in 20 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): patterns, passwords, preferences and the requests of the security screens"
```

---

### Task 2: The components, the texts, and the shell

**Files:**
- Create: `frontend/src/components/permission-rows.tsx`, `token-list.tsx`, `new-password-field.tsx`, `account-nav.tsx` (all in `frontend/src/components/`)
- Modify: `frontend/src/components/ui/inputs.tsx`, `frontend/messages/en.json`
- Modify: `frontend/src/lib/navigation.ts`, `frontend/src/components/app-shell.tsx`, `user-menu.tsx`, `theme-switch.tsx`, `search-box.tsx`
- Test: `frontend/src/components/security.test.tsx`
- Test (modify): `frontend/src/components/shell.test.tsx`, `frontend/src/lib/navigation.test.ts`, `frontend/src/screens/search.test.tsx`

**Interfaces:**
- Consumes: everything Task 1 produces; `ConfirmDialog`, `CopyButton`, `TextField`, `SelectField`, `Table`, `StatusTag`, `Time`, `Button` of plans 9 and 10a.
- Produces:
  - `ChoiceGroup({ legend, options: { value, label, hint? }[], value, onChange, disabled? })` and `CheckList({ legend, options, value: string[], onChange, disabled?, empty? })` in `ui/inputs.tsx`.
  - `PermissionRows({ legend, initial: string[], onChange(patterns), repositories: { name, format }[], checked? })`: it starts from `initial` and keeps its own rows; `PermissionList({ patterns, empty })`; `patternsAreValid(patterns)`; `usePatternWords() -> (pattern) => string | null`; `Held`.
  - `TokenList({ caption, tokens, empty, onRevoke? })`: `onRevoke(token)` returns a promise.
  - `NewPasswordField({ label, hint?, value, onChange, error? })`.
  - `AccountNav()`: the three pages of the account, or nothing for a visitor.
  - `NAVIGATION`'s administration area: `users`, `roles`, `anonymousAccess`. `ThemeSwitch({ bare? })` with "More preferences". The user menu's "Account". `SearchBox` follows the preference and takes `/` only when it is on the screen.
  - `messages/en.json`: the groups `accountArea`, `preferences`, `newPassword`, `permissions`, `tokens`, `users`, `roles`, `anonymous`; `nav.items.users`, `roles`, `anonymousAccess`; `theme.more`; `account.account` (in place of `account.changePassword`); `searchBox.placeholderPlain`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/security.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, test, vi } from "vitest";

import type { TokenInfo } from "@/lib/api/types";
import { ALPHABET } from "@/lib/passwords";
import { failure, mockApi } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi, VISITOR } from "@/test/render";

import { AccountNav } from "./account-nav";
import { NewPasswordField } from "./new-password-field";
import { PermissionList, PermissionRows, patternsAreValid } from "./permission-rows";
import { TokenList } from "./token-list";
import { CheckList, ChoiceGroup } from "./ui/inputs";

const REPOSITORIES = [
  { name: "releases", format: "maven" },
  { name: "snapshots", format: "maven" },
  { name: "npm-own", format: "npm" },
];

/** The rows, and the patterns they were last said to stand for. */
function Rows({ initial, checked = false }: { initial: string[]; checked?: boolean }) {
  const [patterns, setPatterns] = useState(initial);
  return (
    <>
      <PermissionRows
        legend="Permissions"
        initial={initial}
        onChange={setPatterns}
        repositories={REPOSITORIES}
        checked={checked}
      />
      <output aria-label="Patterns">{JSON.stringify(patterns)}</output>
    </>
  );
}
const patterns = () => JSON.parse(screen.getByLabelText("Patterns").textContent ?? "[]");
const row = (number: number) => screen.getByRole("group", { name: `Permission ${number}` });
const options = (select: HTMLElement) =>
  within(select)
    .getAllByRole("option")
    .map((option) => option.textContent);

describe("permissions as rows (A2)", () => {
  test("each pattern is a row, taken apart, with what it grants in words", async () => {
    renderUi(<Rows initial={["repository:maven:releases:read", "admin:users:write", "*"]} />);

    expect(within(row(1)).getByLabelText("About")).toHaveValue("repository");
    expect(within(row(1)).getByLabelText("Format")).toHaveValue("maven");
    expect(within(row(1)).getByLabelText("Repository")).toHaveValue("releases");
    expect(within(row(1)).getByLabelText("Action")).toHaveValue("read");
    expect(row(1)).toHaveTextContent("repository:maven:releases:read");
    expect(row(1)).toHaveTextContent("Read in the maven repository releases.");

    expect(within(row(2)).getByLabelText("Area")).toHaveValue("users");
    expect(row(2)).toHaveTextContent("Change the users.");
    expect(within(row(3)).getByLabelText("About")).toHaveValue("all");
    expect(row(3)).toHaveTextContent(
      "Everything: every repository, and all of the administration.",
    );
    await expectAccessible();
  });

  test("choosing from the lists makes the pattern", async () => {
    const user = userEvent.setup();
    renderUi(<Rows initial={["repository:*:*:read"]} />);

    await user.selectOptions(within(row(1)).getByLabelText("Format"), "maven");
    expect(options(within(row(1)).getByLabelText("Repository"))).toEqual([
      "Any",
      "releases",
      "snapshots",
    ]);
    await user.selectOptions(within(row(1)).getByLabelText("Repository"), "snapshots");
    await user.selectOptions(within(row(1)).getByLabelText("Action"), "delete");

    expect(patterns()).toEqual(["repository:maven:snapshots:delete"]);
    expect(row(1)).toHaveTextContent("Delete in the maven repository snapshots.");

    // A repository of one format is not one of another: the choice of it is undone.
    await user.selectOptions(within(row(1)).getByLabelText("Format"), "npm");
    expect(patterns()).toEqual(["repository:npm:*:delete"]);
    expect(row(1)).toHaveTextContent("Delete in every npm repository.");
  });

  test("offers every format, whether or not a repository of it exists", () => {
    renderUi(<Rows initial={["repository:*:*:read"]} />);

    expect(options(within(row(1)).getByLabelText("Format"))).toEqual([
      "Any",
      "docker",
      "maven",
      "npm",
      "pypi",
      "raw",
    ]);
  });

  test("changing what a row is about starts it afresh", async () => {
    const user = userEvent.setup();
    renderUi(<Rows initial={["repository:maven:releases:delete"]} />);

    await user.selectOptions(within(row(1)).getByLabelText("About"), "admin");
    expect(patterns()).toEqual(["admin:*:read"]);
    expect(row(1)).toHaveTextContent("See everything an administrator keeps.");

    await user.selectOptions(within(row(1)).getByLabelText("Area"), "blobstores");
    await user.selectOptions(within(row(1)).getByLabelText("Action"), "*");
    expect(patterns()).toEqual(["admin:blobstores:*"]);
    expect(row(1)).toHaveTextContent("See and change the blob stores.");

    await user.selectOptions(within(row(1)).getByLabelText("About"), "all");
    expect(patterns()).toEqual(["*"]);
  });

  test("what the lists cannot say is typed, and stays as it was typed (A3)", async () => {
    const user = userEvent.setup();
    renderUi(<Rows initial={["repository:maven", "admin:audit:read"]} />);

    expect(within(row(1)).getByLabelText("About")).toHaveValue("typed");
    expect(within(row(1)).getByLabelText("Pattern")).toHaveValue("repository:maven");
    expect(row(1)).toHaveTextContent("Whatever this pattern matches.");
    expect(patterns()).toEqual(["repository:maven", "admin:audit:read"]);

    // Typing a pattern that a row could say does not turn the field into lists under
    // the hands that are typing it.
    const typed = within(row(2)).getByLabelText("Pattern");
    await user.clear(typed);
    await user.type(typed, "repository:npm:*:read");
    expect(within(row(2)).getByLabelText("Pattern")).toHaveFocus();
    expect(patterns()[1]).toBe("repository:npm:*:read");
  });

  test("a repository or a format that is not among the choices is still what the row holds", () => {
    renderUi(<Rows initial={["repository:helm:gone-repo:read"]} />);

    expect(within(row(1)).getByLabelText("Format")).toHaveValue("helm");
    expect(within(row(1)).getByLabelText("Repository")).toHaveValue("gone-repo");
    expect(patterns()).toEqual(["repository:helm:gone-repo:read"]);
  });

  test("what is typed and is no pattern is said to be wrong, where it is", async () => {
    const user = userEvent.setup();
    renderUi(<Rows initial={[]} />);
    expect(screen.getByText("No permission yet.")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Add a permission" }));
    await user.selectOptions(within(row(1)).getByLabelText("About"), "typed");
    await user.type(within(row(1)).getByLabelText("Pattern"), "admin::read");

    const field = within(row(1)).getByLabelText("Pattern");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(expect.stringContaining("words joined by a colon"));
    expect(patternsAreValid(patterns())).toBe(false);
    await expectAccessible();
  });

  test("a row left empty is wrong only once saving was tried", () => {
    const { unmount } = renderUi(<Rows initial={[""]} />);
    expect(within(row(1)).getByLabelText("Pattern")).not.toHaveAttribute("aria-invalid");
    expect(patternsAreValid([""])).toBe(false);
    unmount();

    renderUi(<Rows initial={[""]} checked />);
    expect(within(row(1)).getByLabelText("Pattern")).toHaveAttribute("aria-invalid", "true");
  });

  test("a row that is added has the keyboard, and one that is removed leaves it at the button that adds", async () => {
    const user = userEvent.setup();
    renderUi(<Rows initial={["*"]} />);

    await user.click(screen.getByRole("button", { name: "Add a permission" }));
    expect(patterns()).toEqual(["*", "repository:*:*:read"]);
    expect(within(row(2)).getByLabelText("About")).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Remove permission 1" }));
    expect(patterns()).toEqual(["repository:*:*:read"]);
    expect(screen.getByRole("button", { name: "Add a permission" })).toHaveFocus();
    expect(screen.queryByRole("group", { name: "Permission 2" })).toBeNull();
  });

  test("as a list, for whoever may only read them", async () => {
    const { unmount } = renderUi(
      <PermissionList patterns={["repository:*:*:browse", "<img src=x>"]} empty="None." />,
    );

    expect(screen.getByText("Browse in every repository.")).toBeVisible();
    expect(screen.getByText("<img src=x>")).toBeVisible(); // as text, whatever it is
    expect(screen.queryByRole("img")).toBeNull();
    await expectAccessible();
    unmount();

    renderUi(<PermissionList patterns={[]} empty="None." />);
    expect(screen.getByText("None.")).toBeVisible();
  });
});

describe("a password set for someone else (A6)", () => {
  function Field() {
    const [value, setValue] = useState("");
    return (
      <NewPasswordField label="Password" hint="At least 8." value={value} onChange={setValue} />
    );
  }

  test("is hidden as it is typed, and shown when asked", async () => {
    const user = userEvent.setup();
    renderUi(<Field />);
    const field = screen.getByLabelText("Password");

    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("autocomplete", "new-password");
    await user.type(field, "typed-by-hand");
    await user.click(screen.getByRole("button", { name: "Show it" }));

    expect(field).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Show it" })).toHaveAttribute("aria-pressed", "true");
    await expectAccessible();
  });

  test("can be generated: then it is shown, and can be copied to pass on", async () => {
    const user = userEvent.setup();
    renderUi(<Field />);
    expect(screen.queryByRole("button", { name: "Copy Password" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Generate one" }));
    const made = (screen.getByLabelText("Password") as HTMLInputElement).value;

    expect(made).toHaveLength(20);
    expect(Array.from(made).every((character) => ALPHABET.includes(character))).toBe(true);
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Copy Password" }));
    expect(await navigator.clipboard.readText()).toBe(made);
  });
});

describe("one of a few, and any of a list", () => {
  test("one of a few is the browser's own radio buttons, each with what it means", async () => {
    const user = userEvent.setup();
    const chosen = vi.fn();
    renderUi(
      <ChoiceGroup
        legend="State"
        value="active"
        onChange={chosen}
        options={[
          { value: "active", label: "Active", hint: "Can sign in." },
          { value: "disabled", label: "Disabled" },
        ]}
      />,
    );
    const group = screen.getByRole("group", { name: "State" });

    expect(within(group).getByRole("radio", { name: "Active" })).toBeChecked();
    expect(within(group).getByRole("radio", { name: "Active" })).toHaveAccessibleDescription(
      "Can sign in.",
    );
    await user.click(within(group).getByRole("radio", { name: "Disabled" }));
    expect(chosen).toHaveBeenCalledWith("disabled");
    await expectAccessible();
  });

  test("any of a list is ticks, and says so when there is nothing to tick", async () => {
    const user = userEvent.setup();
    function Roles() {
      const [held, setHeld] = useState(["admin"]);
      return (
        <CheckList
          legend="Roles"
          value={held}
          onChange={setHeld}
          options={[
            { value: "admin", label: "admin" },
            { value: "deployers", label: "deployers", hint: "May deploy." },
          ]}
        />
      );
    }
    const { unmount } = renderUi(<Roles />);
    const group = screen.getByRole("group", { name: "Roles" });

    await user.click(within(group).getByRole("checkbox", { name: "deployers" }));
    await user.click(within(group).getByRole("checkbox", { name: "admin" }));

    expect(within(group).getByRole("checkbox", { name: "deployers" })).toBeChecked();
    expect(within(group).getByRole("checkbox", { name: "admin" })).not.toBeChecked();
    await expectAccessible();
    unmount();

    renderUi(
      <CheckList legend="Roles" value={[]} onChange={() => {}} options={[]} empty="No role." />,
    );
    expect(screen.getByText("No role.")).toBeVisible();
  });
});

describe("a list of API tokens", () => {
  const token = (name: string, more: Partial<TokenInfo> = {}): TokenInfo => ({
    id: `id-of-${name}`,
    name,
    display_prefix: "mga_Uw7S",
    scopes: null,
    expires_at: null,
    created_at: "2026-10-01T08:00:00Z",
    last_used_at: null,
    ...more,
  });
  const TOKENS = [
    token("ci build", { scopes: ["repository:maven:releases:read"] }),
    token("old", { expires_at: "2020-01-01T00:00:00Z" }),
    token("laptop", { expires_at: "2099-01-01T00:00:00Z" }),
  ];

  test("says of each how it begins, what it may do and when it ends, and never its secret", async () => {
    renderUi(<TokenList caption="Your tokens" tokens={TOKENS} empty="None." onRevoke={vi.fn()} />);
    const rows = within(screen.getByRole("table", { name: "Your tokens" })).getAllByRole("row");

    expect(rows[1]).toHaveTextContent("ci build");
    expect(rows[1]).toHaveTextContent("mga_Uw7S…");
    expect(rows[1]).toHaveTextContent("repository:maven:releases:read");
    expect(rows[1]).toHaveTextContent("Never");
    expect(rows[2]).toHaveTextContent("Everything its owner may");
    expect(rows[2]).toHaveTextContent("Expired");
    expect(rows[3]).not.toHaveTextContent("Expired");
    await expectAccessible();
  });

  test("revokes after asking, and leaves the keyboard at the list", async () => {
    const user = userEvent.setup();
    const revoke = vi.fn().mockResolvedValue(undefined);
    // As a screen has it: once a token is revoked it is no longer among those listed.
    function Listed() {
      const [tokens, setTokens] = useState(TOKENS);
      return (
        <TokenList
          caption="Your tokens"
          tokens={tokens}
          empty="None."
          onRevoke={async (token) => {
            await revoke(token);
            setTokens((held) => held.filter((one) => one.id !== token.id));
          }}
        />
      );
    }
    renderUi(<Listed />);

    await user.click(screen.getByRole("button", { name: "Revoke ci build" }));
    const dialog = screen.getByRole("alertdialog", { name: "Revoke the token ci build?" });
    expect(revoke).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Revoke" }));

    expect(revoke).toHaveBeenCalledWith(TOKENS[0]);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(screen.queryByRole("button", { name: "Revoke ci build" })).toBeNull();
    // The button that was pressed went with its row.
    await waitFor(() => expect(screen.getByRole("group", { name: "Your tokens" })).toHaveFocus());
  });

  test("says why when a token could not be revoked", async () => {
    const user = userEvent.setup();
    mockApi({ "DELETE /me/tokens/x": failure(404, "not_found", "No such token.") });
    const revoke = vi.fn(async () => {
      await fetch("/api/v1/me/tokens/x", { method: "DELETE" });
      throw new Error("refused");
    });
    renderUi(<TokenList caption="Your tokens" tokens={TOKENS} empty="None." onRevoke={revoke} />);

    await user.click(screen.getByRole("button", { name: "Revoke old" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Revoke" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong.");
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  test("offers no revoking to whoever may only look, and says so when there is none", () => {
    const { unmount } = renderUi(
      <TokenList caption="Tokens of alice" tokens={TOKENS} empty="None." />,
    );
    expect(screen.queryByRole("button", { name: /Revoke/ })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Revoke" })).toBeNull();
    unmount();

    renderUi(<TokenList caption="Tokens of alice" tokens={[]} empty="This user has no token." />);
    expect(screen.getByText("This user has no token.")).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("the pages of an account (A1)", () => {
  test("are links to each other, with the present one marked", async () => {
    navigation.at("/account/tokens");
    renderUi(<AccountNav />, { session: ADMIN });
    const links = within(screen.getByRole("navigation", { name: "Account" })).getAllByRole("link");

    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["API tokens", "/account/tokens"],
      ["Password", "/account/password"],
      ["Preferences", "/account/preferences"],
    ]);
    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual(["page", null, null]);
    await expectAccessible();
  });

  test("are not listed for a visitor, who has no account", () => {
    navigation.at("/account/preferences");
    renderUi(<AccountNav />, { session: VISITOR });

    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
```

Change `frontend/src/components/shell.test.tsx`:

```diff
@@ -49,7 +49,8 @@ describe("the shell", () => {
 
   test("leads to the repositories, to search and to upload", () => {
     navigation.at("/browse/releases/com");
-    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
+    const uploader: SessionInfo = { ...ADMIN, permissions: ["repository:*:*:*"] };
+    renderUi(<AppShell session={uploader}>Content</AppShell>, { session: uploader });
     const [wide] = screen.getAllByRole("navigation", { name: "Main" });
     const links = within(wide as HTMLElement).getAllByRole("link");
 
@@ -62,6 +63,34 @@ describe("the shell", () => {
     expect(links.map((link) => link.getAttribute("aria-current"))).toEqual(["page", null, null]);
   });
 
+  test("leads an administrator to the users, the roles and anonymous access", () => {
+    navigation.at("/admin/users/0190-aa");
+    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
+    const [wide] = screen.getAllByRole("navigation", { name: "Main" });
+    const links = within(wide as HTMLElement)
+      .getAllByRole("link")
+      .slice(3);
+
+    expect(within(wide as HTMLElement).getByText("Administration")).toBeVisible();
+    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
+      ["Users", "/admin/users"],
+      ["Roles", "/admin/roles"],
+      ["Anonymous access", "/admin/anonymous-access"],
+    ]);
+    // One user's page is among the users.
+    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual(["page", null, null]);
+  });
+
+  test("has the navigation in a row of its own, which wraps where it does not fit", () => {
+    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
+    const [wide] = screen.getAllByRole("navigation", { name: "Main" });
+
+    // Not beside the search box, where an administrator's items ran under it.
+    expect(wide?.querySelector('[role="search"]')).toBeNull();
+    expect(wide?.closest("header > div")).toBeNull();
+    expect(within(wide as HTMLElement).getAllByRole("list")[0]).toHaveClass("lg:flex-wrap");
+  });
+
   test("has the search box in its header, and in the navigation of a narrow window", async () => {
     const user = userEvent.setup();
     renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
@@ -80,10 +109,11 @@ describe("the shell", () => {
   });
 
   test("shows no area that has nothing in it", () => {
-    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
+    renderUi(<AppShell session={VISITOR}>Content</AppShell>, { session: VISITOR });
 
-    // Plan 9 has no administration screen yet, so the area is not there to be empty.
+    // A visitor administers nothing, so the area is not there to be empty.
     expect(screen.queryByText("Administration")).toBeNull();
+    expect(screen.getAllByText("Browse")[0]).toBeVisible();
   });
 
   test("opens its navigation from a button where the window is narrow (UI-3)", async () => {
@@ -125,7 +155,7 @@ describe("the shell", () => {
 });
 
 describe("the user menu", () => {
-  test("says who is signed in, and leads to changing the password", async () => {
+  test("says who is signed in, and leads to their account", async () => {
     const user = userEvent.setup();
     renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
 
@@ -136,9 +166,9 @@ describe("the user menu", () => {
     expect(menu).toHaveTextContent("admin");
     await expectAccessible();
 
-    await user.click(within(menu).getByRole("menuitem", { name: "Change password" }));
+    await user.click(within(menu).getByRole("menuitem", { name: "Account" }));
 
-    expect(navigation.router.push).toHaveBeenCalledWith("/account/password");
+    expect(navigation.router.push).toHaveBeenCalledWith("/account/tokens");
   });
 
   test("signs out, forgets what was fetched for that person, and starts afresh at home", async () => {
@@ -207,7 +237,7 @@ describe("the user menu", () => {
     expect(screen.queryByRole("button", { name: /Account of/ })).toBeNull();
   });
 
-  test("offers no change of password to whoever is already made to change it", async () => {
+  test("offers no way to the account to whoever must choose a password first", async () => {
     const user = userEvent.setup();
     const pending: SessionInfo = { ...ADMIN, must_change_password: true };
     renderUi(
@@ -219,8 +249,25 @@ describe("the user menu", () => {
 
     await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));
 
-    expect(screen.queryByRole("menuitem", { name: "Change password" })).toBeNull();
+    expect(screen.queryByRole("menuitem", { name: "Account" })).toBeNull();
     expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeVisible();
+    // Nor to the preferences, from the mode menu: no other screen can be reached.
+    await user.keyboard("{Escape}");
+    await user.click(screen.getByRole("button", { name: /^Mode:/ }));
+    expect(screen.getByRole("menuitemradio", { name: "Dark" })).toBeVisible();
+    expect(screen.queryByRole("menuitem", { name: "More preferences" })).toBeNull();
+  });
+});
+
+describe("the mode menu", () => {
+  test("leads to the other preferences, for a visitor as for anybody (A11)", async () => {
+    const user = userEvent.setup();
+    renderUi(<AppShell session={VISITOR}>Content</AppShell>, { session: VISITOR });
+
+    await user.click(screen.getByRole("button", { name: /^Mode:/ }));
+    await user.click(screen.getByRole("menuitem", { name: "More preferences" }));
+
+    expect(navigation.router.push).toHaveBeenCalledWith("/account/preferences");
   });
 });
 
```

Change `frontend/src/lib/navigation.test.ts`:

```diff
@@ -72,6 +72,41 @@ describe("the navigation as it is", () => {
     expect(NAVIGATION[0]?.items[0]).toMatchObject({ key: "repositories", href: "/", icon: Boxes });
   });
 
+  test("shows each part of the administration to whoever may read it (UI-2)", () => {
+    const administration = (session: SessionInfo) =>
+      visible(NAVIGATION, session)
+        .filter((area) => area.key === "administration")
+        .flatMap((area) => area.items.map((entry) => [entry.key, entry.href]));
+
+    expect(administration(ADMIN)).toEqual([
+      ["users", "/admin/users"],
+      ["roles", "/admin/roles"],
+      ["anonymousAccess", "/admin/anonymous-access"],
+    ]);
+    expect(administration({ ...ADMIN, permissions: ["admin:roles:read"] })).toEqual([
+      ["roles", "/admin/roles"],
+    ]);
+    expect(administration({ ...ADMIN, permissions: ["admin:settings"] })).toEqual([
+      ["anonymousAccess", "/admin/anonymous-access"],
+    ]);
+    expect(administration({ ...ADMIN, permissions: ["repository:*:*:*"] })).toEqual([]);
+    // Whatever the anonymous user holds, nobody administers without signing in.
+    expect(administration({ ...VISITOR, permissions: ["*"] })).toEqual([]);
+  });
+
+  test("marks an administration item for everything under it", () => {
+    const current = (pathname: string) =>
+      NAVIGATION.flatMap((area) => area.items)
+        .filter((entry) => isCurrent(entry, pathname))
+        .map((entry) => entry.key);
+
+    expect(current("/admin/users")).toEqual(["users"]);
+    expect(current("/admin/users/new")).toEqual(["users"]);
+    expect(current("/admin/roles/deployers")).toEqual(["roles"]);
+    expect(current("/admin/anonymous-access")).toEqual(["anonymousAccess"]);
+    expect(current("/account/tokens")).toEqual([]);
+  });
+
   test("leads to the repositories, to search and to upload", () => {
     const [browse] = visible(NAVIGATION, ADMIN);
 
```

Change `frontend/src/screens/search.test.tsx`:

```diff
@@ -249,6 +249,25 @@ describe("the search box of every screen", () => {
     expect(screen.getByLabelText("Elsewhere")).toHaveValue("a/b");
   });
 
+  test("does not take the key when it is not on the screen to go to (A12)", () => {
+    // As in a narrow window, where the box is in a navigation that is closed.
+    renderUi(
+      <div hidden>
+        <SearchBox />
+      </div>,
+    );
+
+    // `fireEvent` says whether the key was left to do what it does anyway.
+    expect(fireEvent.keyDown(document.body, { key: "/" })).toBe(true);
+  });
+
+  test("takes the key when it is", () => {
+    renderUi(<SearchBox />);
+
+    expect(fireEvent.keyDown(document.body, { key: "/" })).toBe(false);
+    expect(screen.getByRole("searchbox", { name: "Search components" })).toHaveFocus();
+  });
+
   test("leaves the browser's own shortcuts alone", () => {
     renderUi(<SearchBox />);
 
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 7 tests fail and 1 file does not load. In `shell.test.tsx`: "leads an administrator to the users, the roles and anonymous access", "has the navigation in a row of its own, which wraps where it does not fit", "says who is signed in, and leads to their account" and "leads to the other preferences, for a visitor as for anybody (A11)". In `navigation.test.ts`: "shows each part of the administration to whoever may read it (UI-2)" and "marks an administration item for everything under it". In `search.test.tsx`: "does not take the key when it is not on the screen to go to (A12)". `security.test.tsx` fails with `Failed to resolve import` of one of the components this task creates.

- [ ] **Step 3: Implement**

Change `frontend/messages/en.json`:

```diff
@@ -17,7 +17,10 @@
     "items": {
       "repositories": "Repositories",
       "search": "Search",
-      "upload": "Upload"
+      "upload": "Upload",
+      "users": "Users",
+      "roles": "Roles",
+      "anonymousAccess": "Anonymous access"
     }
   },
   "theme": {
@@ -25,15 +28,16 @@
     "current": "Mode: {choice}",
     "light": "Light",
     "dark": "Dark",
-    "system": "As the system"
+    "system": "As the system",
+    "more": "More preferences"
   },
   "account": {
     "menu": "Account of {name}",
     "signedInAs": "Signed in as",
-    "changePassword": "Change password",
     "signOut": "Sign out",
     "signOutFailed": "You are still signed in",
-    "signIn": "Sign in"
+    "signIn": "Sign in",
+    "account": "Account"
   },
   "signIn": {
     "title": "Sign in",
@@ -135,7 +139,8 @@
   },
   "searchBox": {
     "label": "Search components",
-    "placeholder": "Search  ( / )"
+    "placeholder": "Search  ( / )",
+    "placeholderPlain": "Search"
   },
   "browse": {
     "kind": "{format} repository, {type}",
@@ -307,5 +312,295 @@
     "notHosted": "Only a hosted repository takes an upload. A proxy holds what its remote has, and a group holds nothing of its own.",
     "notDocker": "An image is pushed with a container client, not uploaded.",
     "notAllowed": "You do not have permission to add to this repository."
+  },
+  "accountArea": {
+    "label": "Account",
+    "pages": {
+      "tokens": "API tokens",
+      "password": "Password",
+      "preferences": "Preferences"
+    }
+  },
+  "preferences": {
+    "title": "Preferences",
+    "intro": "How this UI behaves for you. They are kept in this browser, and take effect as you choose them.",
+    "keys": "Keyboard",
+    "searchKey": "Go to the search box with the / key",
+    "searchKeyHint": "From anywhere that is not a place to type. Turn it off if the key gets in your way, as it can when you dictate."
+  },
+  "newPassword": {
+    "generate": "Generate one",
+    "show": "Show it"
+  },
+  "permissions": {
+    "none": "No permission yet.",
+    "row": "Permission {number}",
+    "about": "About",
+    "kinds": {
+      "repository": "A repository",
+      "admin": "Administration",
+      "all": "Everything",
+      "typed": "Typed by hand"
+    },
+    "any": "Any",
+    "format": "Format",
+    "repository": "Repository",
+    "action": "Action",
+    "area": "Area",
+    "pattern": "Pattern",
+    "actions": {
+      "browse": "Browse",
+      "read": "Read",
+      "add": "Add",
+      "edit": "Edit",
+      "delete": "Delete",
+      "write": "Write"
+    },
+    "areas": {
+      "users": "Users",
+      "roles": "Roles",
+      "tokens": "API tokens",
+      "settings": "Settings",
+      "blobstores": "Blob stores",
+      "repositories": "Repositories"
+    },
+    "add": "Add a permission",
+    "remove": "Remove permission {number}",
+    "notAPattern": "A pattern is words joined by a colon, with * for any one word: repository:maven:*:read.",
+    "grants": {
+      "all": "Everything: every repository, and all of the administration.",
+      "repository": "{action} in {where}.",
+      "doing": {
+        "any": "Everything",
+        "browse": "Browse",
+        "read": "Read",
+        "add": "Add",
+        "edit": "Edit",
+        "delete": "Delete"
+      },
+      "everyRepository": "every repository",
+      "everyOfFormat": "every {format} repository",
+      "everyNamed": "every repository named {name}",
+      "oneRepository": "the {format} repository {name}",
+      "admin": "{action} {area}.",
+      "administering": {
+        "any": "See and change",
+        "read": "See",
+        "write": "Change"
+      },
+      "areas": {
+        "any": "everything an administrator keeps",
+        "users": "the users",
+        "roles": "the roles",
+        "tokens": "everybody's API tokens",
+        "settings": "the settings",
+        "blobstores": "the blob stores",
+        "repositories": "the repositories"
+      },
+      "other": "Whatever this pattern matches."
+    }
+  },
+  "tokens": {
+    "title": "API tokens",
+    "intro": "A token signs in for you where a password should not be: in a build, a script, a package client's settings.",
+    "createTitle": "Create a token",
+    "listTitle": "Your tokens",
+    "none": "You have no token.",
+    "fields": {
+      "name": "Name",
+      "lasts": "Lasts",
+      "day": "Until the end of",
+      "limit": "What it may do",
+      "custom": "Its permissions"
+    },
+    "hints": {
+      "name": "What it is for: you will know it by this name."
+    },
+    "lasts": {
+      "never": "Until it is revoked",
+      "30": "30 days",
+      "90": "90 days",
+      "365": "A year",
+      "date": "Until a day I choose"
+    },
+    "limits": {
+      "everything": "Everything I may do",
+      "read": "Only read",
+      "custom": "Only what I choose"
+    },
+    "limitHints": {
+      "everything": "It can do what you can, now and as your roles change.",
+      "read": "Browse and download from the repositories you may read. Nothing else.",
+      "custom": "Whatever you choose here, it never does more than you may do yourself."
+    },
+    "nameNeeded": "Give it a name.",
+    "dayNeeded": "Choose the day.",
+    "customNeeded": "Add at least one permission, or choose another limit.",
+    "create": "Create token",
+    "madeTitle": "The token {name} is made",
+    "madeOnce": "This is the only time it is shown. Copy it now: it cannot be shown again, only replaced.",
+    "theToken": "the token",
+    "madeUse": "Use it as a bearer token, or as the password with your user name (or the name __token__) where a client asks for one.",
+    "madeDone": "I have copied it",
+    "columns": {
+      "name": "Name",
+      "begins": "Begins with",
+      "mayDo": "May do",
+      "expires": "Expires",
+      "lastUsed": "Last used",
+      "created": "Created",
+      "actions": "Revoke"
+    },
+    "begins": "{prefix}…",
+    "everything": "Everything its owner may",
+    "never": "Never",
+    "expired": "Expired",
+    "revoke": "Revoke",
+    "revokeNamed": "Revoke {name}",
+    "revokeTitle": "Revoke the token {name}?",
+    "revokeBody": "Whatever uses it is refused from then on. It cannot be brought back, only replaced by a new one.",
+    "revoked": "Revoked the token {name}."
+  },
+  "users": {
+    "title": "Users",
+    "newTitle": "New user",
+    "oneTitle": "User",
+    "intro": "Who can sign in, and what roles they hold.",
+    "path": "Path",
+    "new": "New user",
+    "columns": {
+      "username": "User name",
+      "displayName": "Name",
+      "roles": "Roles",
+      "state": "State",
+      "lastSignIn": "Last sign-in"
+    },
+    "active": "Active",
+    "disabled": "Disabled",
+    "builtin": "Built in",
+    "mustChange": "Must change password",
+    "details": "Who they are",
+    "fields": {
+      "username": "User name",
+      "displayName": "Name",
+      "email": "Email",
+      "password": "Password",
+      "newPassword": "New password",
+      "mustChange": "Must choose a new password at the next sign-in",
+      "roles": "Roles",
+      "state": "State"
+    },
+    "hints": {
+      "username": "Letters, digits and . _ @ - , up to 64. It cannot be changed later.",
+      "email": "Optional.",
+      "password": "At least {min} characters. Type one, or have one made.",
+      "newPassword": "At least {min} characters. Their sessions end when it is set.",
+      "mustChange": "They sign in with this one once, and then choose their own.",
+      "active": "Can sign in.",
+      "disabled": "Cannot sign in, and their tokens are refused. Nothing of theirs is deleted."
+    },
+    "facts": {
+      "created": "Created",
+      "lastSignIn": "Last sign-in"
+    },
+    "usernameRule": "A user name is 1 to 64 letters, digits or . _ @ -",
+    "displayNameNeeded": "Give their name.",
+    "emailRule": "This is not an email address.",
+    "passwordRule": "The password must be at least {min} characters long.",
+    "noRoles": "There is no role to give.",
+    "noRolesHeld": "None",
+    "rolesNotReadable": "You may not see the roles, so none can be given here.",
+    "create": "Create user",
+    "createdTitle": "The user {username} is created",
+    "createdMustChange": "Pass this password on to them. They sign in with it once, and then choose their own.",
+    "createdKeeps": "Pass this password on to them. It stays their password until they change it.",
+    "thePassword": "the password",
+    "createdOnce": "It is not shown again once you leave this page.",
+    "open": "Open {username}",
+    "another": "Create another",
+    "save": "Save",
+    "saved": "Saved {username}.",
+    "builtinNote": "This user is built in. It can be changed, and not deleted.",
+    "selfState": "This is your own account: you cannot disable it.",
+    "passwordTitle": "Set a new password",
+    "setPassword": "Set password",
+    "passwordSet": "The password of {username} is set",
+    "passwordSetOnce": "Pass it on to them. It is not shown again once you leave this page.",
+    "tokensTitle": "API tokens",
+    "tokensOf": "API tokens of {username}",
+    "noTokens": "This user has no token.",
+    "tokenRevoked": "Revoked the token {name} of {username}.",
+    "deleteTitle": "Delete this user",
+    "deleteIntro": "Their tokens and sessions go with them. What they stored stays.",
+    "delete": "Delete user",
+    "deleteAsk": "Delete the user {username}?",
+    "deleteBody": "They can no longer sign in, and every token of theirs is refused. This cannot be undone.",
+    "deleted": "Deleted the user {username}.",
+    "selfDelete": "This is your own account: you cannot delete it.",
+    "builtinDelete": "A built-in user cannot be deleted. It can be disabled."
+  },
+  "roles": {
+    "title": "Roles",
+    "newTitle": "New role",
+    "oneTitle": "Role",
+    "intro": "What a user may do is what their roles grant.",
+    "path": "Path",
+    "new": "New role",
+    "columns": {
+      "name": "Name",
+      "description": "Description",
+      "permissions": "Permissions",
+      "contains": "Contains"
+    },
+    "builtin": "Built in",
+    "fields": {
+      "name": "Name",
+      "description": "Description",
+      "permissions": "Permissions",
+      "contains": "Roles it contains"
+    },
+    "hints": {
+      "name": "Letters, digits and . _ - , up to 64. It cannot be changed later."
+    },
+    "nameRule": "A role's name is 1 to 64 letters, digits or . _ -",
+    "noOtherRoles": "There is no other role.",
+    "noPermissions": "It grants nothing of its own.",
+    "containsNone": "None",
+    "create": "Create role",
+    "created": "Created the role {name}.",
+    "save": "Save",
+    "saved": "Saved the role {name}.",
+    "adminFixed": "This is the role that makes an administrator. It grants everything, and cannot be changed.",
+    "builtinNote": "This role is built in. It can be changed, and not deleted.",
+    "deleteTitle": "Delete this role",
+    "deleteIntro": "Users who hold it, and roles that contain it, lose what it grants.",
+    "delete": "Delete role",
+    "deleteAsk": "Delete the role {name}?",
+    "deleteBody": "Everyone who holds it loses what it grants, at once. This cannot be undone.",
+    "deleted": "Deleted the role {name}."
+  },
+  "anonymous": {
+    "title": "Anonymous access",
+    "intro": "Whether someone who is not signed in may use this server at all.",
+    "state": "Anonymous access is",
+    "on": "On",
+    "off": "Off",
+    "turnOn": "Turn on",
+    "turnOff": "Turn off",
+    "onMeans": "Anyone who can reach this server may do what is listed below, without signing in.",
+    "offMeans": "Nothing is given without signing in. Package clients need credentials.",
+    "ask": "Turn anonymous access on?",
+    "askBody": "Anyone who can reach this server will then be able to do what the anonymous user may do, without signing in. Look at what that is before you go on.",
+    "turnedOn": "Anonymous access is on.",
+    "turnedOff": "Anonymous access is off.",
+    "allowedTitle": "What a visitor may do",
+    "notReadable": "You may not see users and roles, so what a visitor may do cannot be shown here.",
+    "userNotFound": "The anonymous user was not found among the first users.",
+    "toUsers": "Look for it among the users",
+    "rolesIntro": "A visitor acts as the built-in user anonymous, with the roles it holds.",
+    "toUser": "Change its roles",
+    "noRoles": "It holds no role.",
+    "grantsNothing": "Its roles grant nothing in any repository.",
+    "onlyRepositories": "Whatever its roles say, a visitor is never allowed anything but what concerns repositories."
   }
 }
```

Change `frontend/src/components/ui/inputs.tsx`:

```diff
@@ -195,3 +195,109 @@ export function FilePicker({
     </div>
   );
 }
+
+export type Option = Choice & { hint?: string };
+
+const GROUP = "flex min-w-0 flex-col gap-2 border-0 p-0";
+const LEGEND = "label-caps mb-1 p-0 text-fg-muted";
+
+function OptionText({ id, option }: { id: string; option: Option }) {
+  return (
+    <div className="min-w-0">
+      <label htmlFor={id} className="break-words text-fg">
+        {option.label}
+      </label>
+      {option.hint ? (
+        <p id={`${id}-hint`} className="text-sm text-fg-subtle">
+          {option.hint}
+        </p>
+      ) : null}
+    </div>
+  );
+}
+
+/** One of a few, all in view, each with what it means: the browser's own radio buttons. */
+export function ChoiceGroup({
+  legend,
+  options,
+  value,
+  onChange,
+  disabled = false,
+  className,
+}: {
+  legend: string;
+  options: Option[];
+  value: string;
+  onChange: (value: string) => void;
+  disabled?: boolean;
+  className?: string;
+}) {
+  const id = useId();
+  return (
+    <fieldset className={cn(GROUP, className)} disabled={disabled}>
+      <legend className={LEGEND}>{legend}</legend>
+      {options.map((option, index) => (
+        <div key={option.value} className="flex items-start gap-3">
+          <input
+            id={`${id}-${index}`}
+            type="radio"
+            name={id}
+            value={option.value}
+            checked={option.value === value}
+            aria-describedby={option.hint ? `${id}-${index}-hint` : undefined}
+            onChange={() => onChange(option.value)}
+            className="mt-1 size-4 shrink-0 accent-primary"
+          />
+          <OptionText id={`${id}-${index}`} option={option} />
+        </div>
+      ))}
+    </fieldset>
+  );
+}
+
+/** Any number of a list, each ticked or not: the roles of a user, the roles in a role. */
+export function CheckList({
+  legend,
+  options,
+  value,
+  onChange,
+  disabled = false,
+  empty,
+  className,
+}: {
+  legend: string;
+  options: Option[];
+  value: string[];
+  onChange: (value: string[]) => void;
+  disabled?: boolean;
+  /** What to say when there is nothing to tick. */
+  empty?: string;
+  className?: string;
+}) {
+  const id = useId();
+  return (
+    <fieldset className={cn(GROUP, className)} disabled={disabled}>
+      <legend className={LEGEND}>{legend}</legend>
+      {options.length === 0 && empty ? <p className="text-sm text-fg-subtle">{empty}</p> : null}
+      {options.map((option, index) => (
+        <div key={option.value} className="flex items-start gap-3">
+          <input
+            id={`${id}-${index}`}
+            type="checkbox"
+            checked={value.includes(option.value)}
+            aria-describedby={option.hint ? `${id}-${index}-hint` : undefined}
+            onChange={(event) =>
+              onChange(
+                event.target.checked
+                  ? [...value, option.value]
+                  : value.filter((held) => held !== option.value),
+              )
+            }
+            className="mt-1 size-4 shrink-0 accent-primary"
+          />
+          <OptionText id={`${id}-${index}`} option={option} />
+        </div>
+      ))}
+    </fieldset>
+  );
+}
```

Create `frontend/src/components/permission-rows.tsx`:

```tsx
"use client";

import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { SelectField, type Choice } from "@/components/ui/inputs";
import {
  ADMIN_ACTIONS,
  ADMIN_AREAS,
  ANY,
  fromPattern,
  isValidPattern,
  REPOSITORY_ACTIONS,
  startOf,
  toPattern,
  type Row,
  type RowKind,
} from "@/lib/patterns";

const KINDS: readonly RowKind[] = ["repository", "admin", "all", "typed"];
// The formats there are, whether or not a repository of each exists yet.
const FORMATS = ["raw", "maven", "npm", "pypi", "docker"];

/** A repository, as far as a permission is concerned: what it is called and its format. */
export type Held = { name: string; format: string };

/** Whether patterns can be saved as they are: each is one, and none is empty. */
export function patternsAreValid(patterns: string[]): boolean {
  return patterns.every((pattern) => pattern !== "" && isValidPattern(pattern));
}

/** What a pattern grants, in words. Null for what is not a pattern. */
export function usePatternWords(): (pattern: string) => string | null {
  const t = useTranslations("permissions");
  return (pattern) => {
    if (pattern === "" || !isValidPattern(pattern)) return null;
    const row = fromPattern(pattern);
    switch (row.kind) {
      case "all":
        return t("grants.all");
      case "repository": {
        const { format, name } = row;
        const where =
          format === ANY && name === ANY
            ? t("grants.everyRepository")
            : name === ANY
              ? t("grants.everyOfFormat", { format })
              : format === ANY
                ? t("grants.everyNamed", { name })
                : t("grants.oneRepository", { format, name });
        const action = row.action === ANY ? "any" : (row.action as "read");
        return t("grants.repository", { action: t(`grants.doing.${action}`), where });
      }
      case "admin": {
        const action = row.action === ANY ? "any" : (row.action as "read");
        const area = row.area === ANY ? "any" : (row.area as "users");
        return t("grants.admin", {
          action: t(`grants.administering.${action}`),
          area: t(`grants.areas.${area}`),
        });
      }
      case "typed":
        return t("grants.other");
    }
  };
}

/** Patterns as they stand, for whoever may read them and not change them. */
export function PermissionList({ patterns, empty }: { patterns: string[]; empty: string }) {
  const words = usePatternWords();
  if (patterns.length === 0) return <p className="text-sm text-fg-subtle">{empty}</p>;
  return (
    <ul className="flex flex-col gap-2">
      {patterns.map((pattern) => (
        <li key={pattern} className="rounded-sm border border-line bg-field px-3 py-2">
          <code className="font-mono text-sm break-all text-fg">{pattern}</code>
          <p className="text-sm text-fg-muted">{words(pattern)}</p>
        </li>
      ))}
    </ul>
  );
}

type Kept = { id: number; row: Row };

/**
 * Permissions as rows (A2). A row says what it is about, and the lists that follow
 * make its pattern, which is shown beside it with what it grants. Anything the lists
 * cannot say is typed by hand: nothing a role holds is lost by opening it here.
 *
 * It starts from `initial` and then keeps its own rows: `onChange` is told the
 * patterns as they stand, some of which may not be patterns yet.
 */
export function PermissionRows({
  legend,
  initial,
  onChange,
  repositories,
  checked = false,
}: {
  legend: string;
  initial: string[];
  onChange: (patterns: string[]) => void;
  repositories: Held[];
  /** Saving was tried: a row that is still empty is now said to be wrong. */
  checked?: boolean;
}) {
  const t = useTranslations("permissions");
  const words = usePatternWords();
  const next = useRef(initial.length);
  const [rows, setRows] = useState<Kept[]>(() =>
    initial.map((pattern, id) => ({ id, row: fromPattern(pattern) })),
  );
  const list = useRef<HTMLOListElement>(null);
  const adder = useRef<HTMLDivElement>(null);
  // The row to give the keyboard to once it is on the screen: the one just added.
  const [added, setAdded] = useState<number | null>(null);
  useEffect(() => {
    if (added === null) return;
    list.current?.querySelector<HTMLElement>(`[data-row="${added}"] select`)?.focus();
  }, [added]);

  function change(to: Kept[]) {
    setRows(to);
    onChange(to.map((kept) => toPattern(kept.row)));
  }
  const set = (id: number, row: Row) =>
    change(rows.map((kept) => (kept.id === id ? { id, row } : kept)));

  const any: Choice = { value: ANY, label: t("any") };
  const listed = (values: readonly string[], held: string, label: (value: string) => string) => [
    any,
    // What a row holds is always one of its choices, though it be a repository that is
    // gone or a format this list does not know.
    ...(held !== ANY && !values.includes(held) ? [held, ...values] : values).map((value) => ({
      value,
      label: label(value),
    })),
  ];
  const plain = (value: string) => value;
  const formats = Array.from(
    new Set([...FORMATS, ...repositories.map((held) => held.format)]),
  ).sort();

  return (
    <fieldset className="flex min-w-0 flex-col gap-3 border-0 p-0">
      <legend className="label-caps mb-1 p-0 text-fg-muted">{legend}</legend>
      {rows.length === 0 ? <p className="text-sm text-fg-subtle">{t("none")}</p> : null}
      <ol ref={list} className="flex flex-col gap-3">
        {rows.map(({ id, row }, index) => {
          const number = index + 1;
          const pattern = toPattern(row);
          const said = words(pattern);
          const wrong =
            row.kind === "typed" && said === null && (pattern !== "" || checked)
              ? t("notAPattern")
              : null;
          return (
            <li key={id} data-row={id}>
              <fieldset className="flex min-w-0 flex-col gap-3 rounded-sm border border-line p-3">
                <legend className="sr-only">{t("row", { number })}</legend>
                <div className="flex flex-wrap items-end gap-3">
                  <SelectField
                    label={t("about")}
                    value={row.kind}
                    onChange={(event) => set(id, startOf(event.target.value as RowKind))}
                    choices={KINDS.map((kind) => ({ value: kind, label: t(`kinds.${kind}`) }))}
                  />
                  {row.kind === "repository" ? (
                    <>
                      <SelectField
                        label={t("format")}
                        value={row.format}
                        onChange={(event) =>
                          // A repository of one format is not one of another.
                          set(id, { ...row, format: event.target.value, name: ANY })
                        }
                        choices={listed(formats, row.format, plain)}
                      />
                      <SelectField
                        label={t("repository")}
                        value={row.name}
                        onChange={(event) => set(id, { ...row, name: event.target.value })}
                        choices={listed(
                          repositories
                            .filter((held) => row.format === ANY || held.format === row.format)
                            .map((held) => held.name),
                          row.name,
                          plain,
                        )}
                      />
                      <SelectField
                        label={t("action")}
                        value={row.action}
                        onChange={(event) => set(id, { ...row, action: event.target.value })}
                        choices={listed(REPOSITORY_ACTIONS, row.action, (action) =>
                          t(`actions.${action as "read"}`),
                        )}
                      />
                    </>
                  ) : null}
                  {row.kind === "admin" ? (
                    <>
                      <SelectField
                        label={t("area")}
                        value={row.area}
                        onChange={(event) => set(id, { ...row, area: event.target.value })}
                        choices={listed(ADMIN_AREAS, row.area, (area) =>
                          t(`areas.${area as "users"}`),
                        )}
                      />
                      <SelectField
                        label={t("action")}
                        value={row.action}
                        onChange={(event) => set(id, { ...row, action: event.target.value })}
                        choices={listed(ADMIN_ACTIONS, row.action, (action) =>
                          t(`actions.${action as "read"}`),
                        )}
                      />
                    </>
                  ) : null}
                  {row.kind === "typed" ? (
                    <TextField
                      className="min-w-48 flex-1"
                      label={t("pattern")}
                      spellCheck={false}
                      autoComplete="off"
                      value={row.text}
                      error={wrong}
                      onChange={(event) => set(id, { kind: "typed", text: event.target.value })}
                    />
                  ) : null}
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ml-auto"
                    aria-label={t("remove", { number })}
                    onClick={() => {
                      change(rows.filter((kept) => kept.id !== id));
                      // This button goes with its row: the keyboard goes to the one that adds.
                      adder.current?.querySelector("button")?.focus();
                    }}
                  >
                    <X aria-hidden="true" className="size-4" />
                  </Button>
                </div>
                {said === null ? null : (
                  <p className="text-sm text-fg-muted">
                    <code className="mr-2 font-mono break-all text-fg">{pattern}</code>
                    {said}
                  </p>
                )}
              </fieldset>
            </li>
          );
        })}
      </ol>
      <div ref={adder}>
        <Button
          size="sm"
          onClick={() => {
            const id = next.current++;
            change([...rows, { id, row: startOf("repository") }]);
            setAdded(id);
          }}
        >
          <Plus aria-hidden="true" className="size-4" />
          {t("add")}
        </Button>
      </div>
    </fieldset>
  );
}
```

Create `frontend/src/components/token-list.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Time } from "@/components/ui/details";
import { ErrorState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import type { TokenInfo } from "@/lib/api/types";

/**
 * API tokens as a table: a person's own, or a user's as an administrator sees them.
 * A token is known by its name and by how its secret begins; the secret itself is
 * never here. `onRevoke` returns when the token is gone, or throws.
 */
export function TokenList({
  caption,
  tokens,
  onRevoke,
  empty,
}: {
  caption: string;
  tokens: TokenInfo[];
  /** Without it, the tokens can be seen and not revoked. */
  onRevoke?: (token: TokenInfo) => Promise<unknown>;
  /** What to say when there is none. */
  empty: string;
}) {
  const t = useTranslations("tokens");
  const [asked, setAsked] = useState<TokenInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const table = useRef<HTMLDivElement>(null);
  // Read when a token is drawn: one that ran out while the page was open is caught by
  // the next look at the list.
  const [now] = useState(() => Date.now());

  // The button that was pressed goes with its row, and the dialog gives the keyboard
  // back to that button: once the dialog is closed, the keyboard is put at the list.
  const revoked = useRef(false);
  useEffect(() => {
    if (asked !== null || !revoked.current) return;
    revoked.current = false;
    table.current?.focus();
  }, [asked]);

  async function revoke(token: TokenInfo) {
    setBusy(true);
    setFailure(null);
    try {
      await onRevoke?.(token);
      revoked.current = true;
      setAsked(null);
    } catch (error) {
      setAsked(null);
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    // Named, and able to take the keyboard: after a token is revoked the button that
    // was pressed is gone, and the keyboard is put here, whether or not a token is left.
    <div ref={table} tabIndex={-1} role="group" aria-label={caption} className="outline-none">
      {tokens.length === 0 ? <p className="p-6 text-fg-muted">{empty}</p> : null}
      <Table caption={caption} hidden={tokens.length === 0}>
        <thead>
          <tr>
            <Th>{t("columns.name")}</Th>
            <Th>{t("columns.begins")}</Th>
            <Th>{t("columns.mayDo")}</Th>
            <Th>{t("columns.expires")}</Th>
            <Th>{t("columns.lastUsed")}</Th>
            <Th>{t("columns.created")}</Th>
            {onRevoke ? <Th className="text-right">{t("columns.actions")}</Th> : null}
          </tr>
        </thead>
        <tbody>
          {tokens.map((token) => {
            const expired =
              token.expires_at !== null && new Date(token.expires_at).getTime() <= now;
            return (
              <tr key={token.id} className="hover:bg-raised">
                <Td className="font-medium break-all">{token.name}</Td>
                <Td className="font-mono whitespace-nowrap text-fg-muted">
                  {t("begins", { prefix: token.display_prefix })}
                </Td>
                <Td>
                  {token.scopes === null ? (
                    t("everything")
                  ) : (
                    <ul className="flex flex-col gap-0.5">
                      {token.scopes.map((scope) => (
                        <li key={scope} className="font-mono text-xs break-all">
                          {scope}
                        </li>
                      ))}
                    </ul>
                  )}
                </Td>
                <Td className="whitespace-nowrap text-fg-muted">
                  {token.expires_at === null ? (
                    t("never")
                  ) : expired ? (
                    <StatusTag tone="warning">{t("expired")}</StatusTag>
                  ) : (
                    <Time value={token.expires_at} />
                  )}
                </Td>
                <Td className="whitespace-nowrap text-fg-muted">
                  <Time value={token.last_used_at} />
                </Td>
                <Td className="whitespace-nowrap text-fg-muted">
                  <Time value={token.created_at} />
                </Td>
                {onRevoke ? (
                  <Td className="text-right">
                    <Button
                      size="sm"
                      aria-label={t("revokeNamed", { name: token.name })}
                      onClick={() => setAsked(token)}
                    >
                      {t("revoke")}
                    </Button>
                  </Td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </Table>
      {failure ? <ErrorState error={failure} className="m-4" /> : null}
      <ConfirmDialog
        open={asked !== null}
        onOpenChange={(open) => {
          if (!open) setAsked(null);
        }}
        title={t("revokeTitle", { name: asked?.name ?? "" })}
        confirmLabel={t("revoke")}
        busy={busy}
        onConfirm={() => {
          if (asked) void revoke(asked);
        }}
      >
        {t("revokeBody")}
      </ConfirmDialog>
    </div>
  );
}
```

Create `frontend/src/components/new-password-field.tsx`:

```tsx
"use client";

import { Dices, Eye, EyeOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { TextField } from "@/components/ui/field";
import { generatePassword } from "@/lib/passwords";

/**
 * A password an administrator sets for someone else (A6): typed, or generated. A
 * generated one is shown, since it has to be told to its owner, and can be copied.
 * The browser is told it is a new password, so that it offers neither to fill in the
 * administrator's own nor to remember this one as theirs.
 */
export function NewPasswordField({
  label,
  hint,
  value,
  onChange,
  error,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | null;
}) {
  const t = useTranslations("newPassword");
  const [shown, setShown] = useState(false);
  const Icon = shown ? EyeOff : Eye;
  return (
    <div className="flex flex-col gap-2">
      <TextField
        label={label}
        hint={hint}
        type={shown ? "text" : "password"}
        autoComplete="new-password"
        spellCheck={false}
        value={value}
        error={error}
        onChange={(event) => onChange(event.target.value)}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          onClick={() => {
            onChange(generatePassword());
            setShown(true);
          }}
        >
          <Dices aria-hidden="true" className="size-4" />
          {t("generate")}
        </Button>
        <Button size="sm" variant="ghost" aria-pressed={shown} onClick={() => setShown(!shown)}>
          <Icon aria-hidden="true" className="size-4" />
          {t("show")}
        </Button>
        {value ? <CopyButton text={value} what={label} /> : null}
      </div>
    </div>
  );
}
```

Create `frontend/src/components/account-nav.tsx`:

```tsx
"use client";

import { KeyRound, SlidersHorizontal, Ticket, type LucideIcon } from "lucide-react";
import type { Route } from "next";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";

import { AppLink } from "@/components/ui/link";
import { cn } from "@/lib/cn";
import { ACCOUNT_TOKENS, PREFERENCES } from "@/lib/paths";
import { CHANGE_PASSWORD } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

type Page = { key: "tokens" | "password" | "preferences"; href: Route; icon: LucideIcon };

const PAGES: Page[] = [
  { key: "tokens", href: ACCOUNT_TOKENS, icon: Ticket },
  { key: "password", href: CHANGE_PASSWORD as Route, icon: KeyRound },
  { key: "preferences", href: PREFERENCES, icon: SlidersHorizontal },
];

/**
 * The pages of a person's own account (A1), each a link, with the present one marked.
 * A visitor has no account, and of these pages only the preferences, which are kept in
 * the browser: there is then nothing to choose between, and no list.
 */
export function AccountNav() {
  const t = useTranslations("accountArea");
  const pathname = usePathname();
  const session = useSession();
  if (!session.data?.authenticated) return null;
  return (
    <nav aria-label={t("label")} className="mb-6">
      <ul className="flex flex-wrap gap-2">
        {PAGES.map(({ key, href, icon: Icon }) => {
          const current = pathname === href;
          return (
            <li key={key}>
              <AppLink
                href={href}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "label-caps inline-flex min-h-10 items-center gap-2 rounded-sm border px-3",
                  current
                    ? "border-neon-cyan text-ink-cyan"
                    : "border-line-strong text-fg-muted hover:border-neon-cyan hover:text-fg",
                )}
              >
                <Icon aria-hidden="true" className="size-4" />
                {t(`pages.${key}`)}
              </AppLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
```

Change `frontend/src/lib/navigation.ts`:

```diff
@@ -2,14 +2,15 @@
  * The navigation, as data. A screen is put into the navigation by adding an item here,
  * with the permission its API needs: the item is then shown only to those who hold it.
  */
-import { Boxes, Search, Upload, type LucideIcon } from "lucide-react";
+import { Boxes, Search, ShieldCheck, Unlock, Upload, Users, type LucideIcon } from "lucide-react";
 import type { Route } from "next";
 
 import type { SessionInfo } from "@/lib/api/types";
+import { ANONYMOUS_ACCESS, ROLES, USERS } from "@/lib/paths";
 import { allows, allowsSome } from "@/lib/session/rules";
 
 export type AreaKey = "browse" | "administration";
-export type ItemKey = "repositories" | "search" | "upload";
+export type ItemKey = "repositories" | "search" | "upload" | "users" | "roles" | "anonymousAccess";
 
 export type NavItem = {
   /** Its name is the message `nav.items.<key>`. */
@@ -49,7 +50,19 @@ export const NAVIGATION: readonly NavArea[] = [
       },
     ],
   },
-  { key: "administration", items: [] },
+  {
+    key: "administration",
+    items: [
+      { key: "users", href: USERS, icon: Users, permission: "admin:users:read" },
+      { key: "roles", href: ROLES, icon: ShieldCheck, permission: "admin:roles:read" },
+      {
+        key: "anonymousAccess",
+        href: ANONYMOUS_ACCESS,
+        icon: Unlock,
+        permission: "admin:settings:read",
+      },
+    ],
+  },
 ];
 
 /** The areas and items to show this caller. An area with nothing in it is left out. */
```

Change `frontend/src/components/app-shell.tsx`:

```diff
@@ -30,11 +30,11 @@ function Navigation({ areas, onNavigate }: { areas: NavArea[]; onNavigate?: () =
   const t = useTranslations("nav");
   const pathname = usePathname();
   return (
-    <ul className="flex flex-col gap-4 lg:flex-row lg:items-center lg:gap-6">
+    <ul className="flex flex-col gap-4 lg:flex-row lg:flex-wrap lg:items-center lg:gap-x-8 lg:gap-y-1">
       {areas.map((area) => (
         <li key={area.key} className="flex flex-col gap-1 lg:flex-row lg:items-center lg:gap-2">
           <span className="label-caps text-fg-subtle">{t(`areas.${area.key}`)}</span>
-          <ul className="flex flex-col gap-1 lg:flex-row">
+          <ul className="flex flex-col gap-1 lg:flex-row lg:flex-wrap">
             {area.items.map((item) => {
               const current = isCurrent(item, pathname);
               return (
@@ -66,6 +66,10 @@ function Navigation({ areas, onNavigate }: { areas: NavArea[]; onNavigate?: () =
 /**
  * What every screen is inside: the header with the navigation, and the content. With
  * `bare`, there is no navigation: for whoever must change their password first.
+ *
+ * In a wide window the navigation is a row of its own under the wordmark: an
+ * administrator has more items than fit beside the search box, and the row wraps
+ * where they do not fit in one.
  */
 export function AppShell({
   session,
@@ -88,18 +92,13 @@ export function AppShell({
         {t("skipToContent")}
       </a>
       <header className="relative border-b border-line-strong bg-panel">
-        <div className="mx-auto flex min-h-16 max-w-7xl items-center gap-4 px-4 lg:gap-8">
+        <div className="mx-auto flex min-h-16 max-w-7xl items-center gap-4 px-4">
           <AppLink href="/" className="shrink-0 rounded-sm">
             <Wordmark />
           </AppLink>
-          {areas.length > 0 ? (
-            <nav aria-label={t("mainNavigation")} className="hidden min-w-0 flex-1 lg:block">
-              <Navigation areas={areas} />
-            </nav>
-          ) : null}
           <div className="ml-auto flex items-center gap-2">
-            {bare ? null : <SearchBox className="hidden w-56 md:block xl:w-72" />}
-            <ThemeSwitch />
+            {bare ? null : <SearchBox className="hidden w-56 md:block lg:w-80" />}
+            <ThemeSwitch bare={bare} />
             <UserMenu session={session} />
             {areas.length > 0 ? (
               <button
@@ -119,6 +118,13 @@ export function AppShell({
             ) : null}
           </div>
         </div>
+        {areas.length > 0 ? (
+          <nav aria-label={t("mainNavigation")} className="hidden border-t border-line lg:block">
+            <div className="mx-auto max-w-7xl px-4 py-1.5">
+              <Navigation areas={areas} />
+            </div>
+          </nav>
+        ) : null}
         {areas.length > 0 ? (
           <nav
             id="narrow-navigation"
```

Change `frontend/src/components/user-menu.tsx`:

```diff
@@ -1,6 +1,6 @@
 "use client";
 
-import { KeyRound, LogIn, LogOut, UserRound } from "lucide-react";
+import { LogIn, LogOut, UserCog, UserRound } from "lucide-react";
 import { useTranslations } from "next-intl";
 import { useRouter } from "next/navigation";
 
@@ -17,7 +17,8 @@ import {
 } from "@/components/ui/menu";
 import type { SessionInfo } from "@/lib/api/types";
 import { useErrorText } from "@/lib/errors";
-import { CHANGE_PASSWORD, SIGN_IN } from "@/lib/session/rules";
+import { ACCOUNT_TOKENS } from "@/lib/paths";
+import { SIGN_IN } from "@/lib/session/rules";
 import { useSignOut } from "@/lib/session/session";
 
 /** Who is signed in, and what they can do about it. For a visitor, the way to sign in. */
@@ -68,9 +69,9 @@ export function UserMenu({ session }: { session: SessionInfo }) {
           <p className="px-3 pb-2 font-mono text-sm break-all text-fg">{session.user.username}</p>
           <MenuSeparator />
           {session.must_change_password ? null : (
-            <MenuItem onSelect={() => router.push(CHANGE_PASSWORD)}>
-              <KeyRound aria-hidden="true" className="size-4" />
-              {t("changePassword")}
+            <MenuItem onSelect={() => router.push(ACCOUNT_TOKENS)}>
+              <UserCog aria-hidden="true" className="size-4" />
+              {t("account")}
             </MenuItem>
           )}
           <MenuItem disabled={signOut.isPending} onSelect={() => signOut.mutate()}>
```

Change `frontend/src/components/theme-switch.tsx`:

```diff
@@ -1,24 +1,33 @@
 "use client";
 
-import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
+import { Monitor, Moon, SlidersHorizontal, Sun, type LucideIcon } from "lucide-react";
 import { useTranslations } from "next-intl";
+import { useRouter } from "next/navigation";
 
 import { useTheme } from "@/components/theme-provider";
 import {
   Menu,
   MenuContent,
+  MenuItem,
   MenuLabel,
   MenuRadioGroup,
   MenuRadioItem,
+  MenuSeparator,
   MenuTrigger,
 } from "@/components/ui/menu";
+import { PREFERENCES } from "@/lib/paths";
 import { CHOICES, isChoice, type ThemeChoice } from "@/lib/theme";
 
 const ICONS: Record<ThemeChoice, LucideIcon> = { light: Sun, dark: Moon, system: Monitor };
 
-/** Light, dark, or as the system says (UI-10). */
-export function ThemeSwitch() {
+/**
+ * Light, dark, or as the system says (UI-10). It also leads to the other preferences
+ * (A11): it is in the header for everybody, a visitor too, and so is the one way there
+ * that everybody has. `bare` leaves that out, where no other screen can be reached.
+ */
+export function ThemeSwitch({ bare = false }: { bare?: boolean }) {
   const t = useTranslations("theme");
+  const router = useRouter();
   const { choice, choose } = useTheme();
   const Current = ICONS[choice];
   return (
@@ -47,6 +56,15 @@ export function ThemeSwitch() {
             );
           })}
         </MenuRadioGroup>
+        {bare ? null : (
+          <>
+            <MenuSeparator />
+            <MenuItem onSelect={() => router.push(PREFERENCES)}>
+              <SlidersHorizontal aria-hidden="true" className="size-4" />
+              {t("more")}
+            </MenuItem>
+          </>
+        )}
       </MenuContent>
     </Menu>
   );
```

Change `frontend/src/components/search-box.tsx`:

```diff
@@ -5,8 +5,10 @@ import { useTranslations } from "next-intl";
 import { useRouter } from "next/navigation";
 import { useEffect, useRef, useState, type FormEvent } from "react";
 
+import { isOnScreen } from "@/lib/browser";
 import { cn } from "@/lib/cn";
 import { searchHref } from "@/lib/paths";
+import { useSearchKey } from "@/lib/preferences";
 
 const KEY = "/";
 
@@ -18,24 +20,29 @@ function isTyping(target: EventTarget | null): boolean {
 
 /**
  * Search, on every screen: finding a package is what most visitors come for. `/` takes
- * the keyboard here from anywhere that is not itself a place to type.
+ * the keyboard here from anywhere that is not itself a place to type, unless the
+ * person has turned that off (A11), and only when this box is on the screen (A12): a
+ * key that is taken and leads nowhere is a key that is lost.
  */
 export function SearchBox({ className }: { className?: string }) {
   const t = useTranslations("searchBox");
   const router = useRouter();
   const input = useRef<HTMLInputElement>(null);
   const [text, setText] = useState("");
+  const [keyIsOn] = useSearchKey();
 
   useEffect(() => {
+    if (!keyIsOn) return;
     function onKey(event: KeyboardEvent) {
       if (event.key !== KEY || event.ctrlKey || event.metaKey || event.altKey) return;
-      if (isTyping(event.target)) return;
+      const box = input.current;
+      if (isTyping(event.target) || box === null || !isOnScreen(box)) return;
       event.preventDefault();
-      input.current?.focus();
+      box.focus();
     }
     window.addEventListener("keydown", onKey);
     return () => window.removeEventListener("keydown", onKey);
-  }, []);
+  }, [keyIsOn]);
 
   function submit(event: FormEvent) {
     event.preventDefault();
@@ -58,8 +65,8 @@ export function SearchBox({ className }: { className?: string }) {
         type="search"
         name="q"
         aria-label={t("label")}
-        aria-keyshortcuts={KEY}
-        placeholder={t("placeholder")}
+        aria-keyshortcuts={keyIsOn ? KEY : undefined}
+        placeholder={keyIsOn ? t("placeholder") : t("placeholderPlain")}
         value={text}
         onChange={(event) => setText(event.target.value)}
         className="min-h-10 w-full rounded-sm border border-line-strong bg-field py-2 pr-3 pl-9 text-sm text-fg placeholder:text-fg-subtle hover:border-neon-cyan focus:shadow-glow-sm"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 603 passed in 21 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): permission rows, the account in the shell, and the navigation's own row"
```

---

### Task 3: The account: API tokens and preferences

**Files:**
- Create: `frontend/src/screens/tokens.tsx`, `frontend/src/screens/preferences.tsx`
- Modify: `frontend/src/screens/change-password.tsx`
- Test: `frontend/src/screens/account.test.tsx`

**Interfaces:**
- Consumes: `useMyTokens`, `useCreateToken`, `useRevokeToken`, `AT_ONCE`; `PermissionRows`, `TokenList`, `AccountNav`, `ChoiceGroup`; `useSearchKey`; `useTheme`; `refusalsOf`; `pageOf`, `pageHref`; `useRepositories` of plan 10a.
- Produces: `TokensScreen()` at `/account/tokens` (with `?page=`), `PreferencesScreen()` at `/account/preferences`. `ChangePasswordScreen` shows the account's pages unless the change is forced.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/screens/account.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import { SearchBox } from "@/components/search-box";
import type { SessionInfo } from "@/lib/api/types";
import { SEARCH_KEY_STORAGE } from "@/lib/preferences";
import { STORAGE_KEY } from "@/lib/theme";
import { failure, mockApi, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi, VISITOR } from "@/test/render";

import { ChangePasswordScreen } from "./change-password";
import { PreferencesScreen } from "./preferences";
import { TokensScreen } from "./tokens";

const SECRET = "mga_Uw7SaBb3NAxy_RJ9arOrPGIK0LuZuSXGygzK9TKvMf4";
const token = (name: string, more: Record<string, unknown> = {}) => ({
  id: `id-of-${name}`,
  name,
  display_prefix: "mga_Uw7S",
  scopes: null,
  expires_at: null,
  created_at: "2026-10-01T08:00:00Z",
  last_used_at: null,
  ...more,
});
const page = (items: unknown[], total = items.length) => ({ items, total, limit: 50, offset: 0 });
const DAY = 24 * 3600 * 1000;

function tokens(more: Routes = {}, address = "/account/tokens") {
  const api = mockApi({
    "GET /me/tokens": { json: page([token("laptop")]) },
    "GET /content": {
      json: page([{ name: "releases", format: "maven", type: "hosted", online: true, url: "" }]),
    },
    "POST /me/tokens": (call) => ({
      status: 201,
      json: { ...token((call.body as { name: string }).name), token: SECRET },
    }),
    ...more,
  });
  navigation.at(address);
  return { ...renderUi(<TokensScreen />, { session: ADMIN }), ...api };
}

const create = () => screen.getByRole("button", { name: "Create token" });
const sent = (calls: { method: string; body: unknown }[]) =>
  calls.find((call) => call.method === "POST")?.body as {
    name: string;
    expires_at: string | null;
    scopes: string[] | null;
  };

describe("one's API tokens (A4)", () => {
  test("are listed, as one of the pages of the account", async () => {
    const { calls } = tokens();

    const table = await screen.findByRole("table", { name: "Your tokens" });

    expect(screen.getByRole("heading", { level: 1, name: "API tokens" })).toBeVisible();
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("laptop");
    expect(calls.map((call) => call.path)).toContain("/me/tokens?limit=50&offset=0");
    expect(
      within(screen.getByRole("navigation", { name: "Account" })).getByRole("link", {
        name: "API tokens",
      }),
    ).toHaveAttribute("aria-current", "page");
    await expectAccessible();
  });

  test("say so when there is none, and what went wrong when they cannot be shown", async () => {
    const first = tokens({ "GET /me/tokens": { json: page([]) } });
    expect(await screen.findByText("You have no token.")).toBeVisible();
    first.unmount();

    tokens({ "GET /me/tokens": failure(403, "forbidden", "No.") });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You do not have permission to do this.",
    );
  });

  test("come a page at a time when there are many", async () => {
    const { calls } = tokens(
      { "GET /me/tokens": { json: page([token("t-51")], 120) } },
      "/account/tokens?page=2",
    );

    const pages = await screen.findByRole("navigation", { name: "Pages" });

    expect(calls.map((call) => call.path)).toContain("/me/tokens?limit=50&offset=50");
    expect(pages).toHaveTextContent("Page 2 of 3");
    expect(within(pages).getByRole("link", { name: "Previous" })).toHaveAttribute(
      "href",
      "/account/tokens",
    );
    expect(within(pages).getByRole("link", { name: "Next" })).toHaveAttribute(
      "href",
      "/account/tokens?page=3",
    );
  });

  test("a new one lasts ninety days and does what its owner may, unless told otherwise", async () => {
    const user = userEvent.setup();
    const { calls } = tokens();
    await screen.findByRole("table", { name: "Your tokens" });

    await user.type(screen.getByLabelText("Name"), "  ci build ");
    await user.click(create());

    await screen.findByRole("region", { name: "The token ci build is made" });
    const wanted = sent(calls);
    expect(wanted.name).toBe("ci build");
    expect(wanted.scopes).toBeNull();
    const lasts = new Date(wanted.expires_at ?? "").getTime() - Date.now();
    expect(lasts).toBeGreaterThan(89.9 * DAY);
    expect(lasts).toBeLessThan(90.1 * DAY);
  });

  test("can last until it is revoked, or until a day that is chosen", async () => {
    const user = userEvent.setup();
    const first = tokens();
    await user.type(await screen.findByLabelText("Name"), "forever");
    await user.selectOptions(screen.getByLabelText("Lasts"), "never");
    await user.click(create());
    await screen.findByRole("region", { name: "The token forever is made" });
    expect(sent(first.calls).expires_at).toBeNull();
    first.unmount();

    const second = tokens();
    await user.type(await screen.findByLabelText("Name"), "until");
    await user.selectOptions(screen.getByLabelText("Lasts"), "date");
    await user.click(create());
    // A day is needed, and is asked for where it is missing.
    expect(screen.getByLabelText("Until the end of")).toHaveAccessibleDescription(
      "Choose the day.",
    );
    expect(screen.getByLabelText("Until the end of")).toHaveFocus();
    expect(second.calls.some((call) => call.method === "POST")).toBe(false);

    await user.type(screen.getByLabelText("Until the end of"), "2031-05-17");
    await user.click(create());
    await screen.findByRole("region", { name: "The token until is made" });
    // The end of that day, where the person is.
    expect(sent(second.calls).expires_at).toBe(new Date("2031-05-17T23:59:59").toISOString());
  });

  test("can be limited to reading, or to what is chosen row by row", async () => {
    const user = userEvent.setup();
    const first = tokens();
    await user.type(await screen.findByLabelText("Name"), "reader");
    await user.click(screen.getByRole("radio", { name: "Only read" }));
    await user.click(create());
    await screen.findByRole("region", { name: "The token reader is made" });
    expect(sent(first.calls).scopes).toEqual(["repository:*:*:browse", "repository:*:*:read"]);
    first.unmount();

    const second = tokens();
    await user.type(await screen.findByLabelText("Name"), "deploy");
    await user.click(screen.getByRole("radio", { name: "Only what I choose" }));
    await user.click(create());
    // Nothing chosen is not a limit: it would be a token that may do nothing.
    expect(await screen.findByRole("alert")).toHaveTextContent("Add at least one permission");
    expect(second.calls.some((call) => call.method === "POST")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Add a permission" }));
    await user.selectOptions(screen.getByLabelText("Format"), "maven");
    await user.selectOptions(screen.getByLabelText("Repository"), "releases");
    await user.selectOptions(screen.getByLabelText("Action"), "add");
    await user.click(create());
    await screen.findByRole("region", { name: "The token deploy is made" });
    expect(sent(second.calls).scopes).toEqual(["repository:maven:releases:add"]);
  });

  test("needs a name, and a name no other token of one's own has", async () => {
    const user = userEvent.setup();
    const { calls } = tokens({
      "POST /me/tokens": failure(409, "conflict", "A token named laptop already exists."),
    });
    await screen.findByRole("table", { name: "Your tokens" });

    await user.click(create());
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription("Give it a name.");
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(calls.some((call) => call.method === "POST")).toBe(false);

    await user.type(screen.getByLabelText("Name"), "laptop");
    await user.click(create());

    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
        "A token named laptop already exists.",
      ),
    );
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(screen.queryByRole("region", { name: /is made/ })).toBeNull();
  });

  test("says what the server refused at the field it is about, or whole", async () => {
    const user = userEvent.setup();
    const first = tokens({
      "POST /me/tokens": failure(422, "validation_error", "The request is not valid.", [
        { field: "body.expires_at", message: "The expiry must be in the future." },
      ]),
    });
    await user.type(await screen.findByLabelText("Name"), "past");
    await user.selectOptions(screen.getByLabelText("Lasts"), "date");
    await user.type(screen.getByLabelText("Until the end of"), "2001-01-01");
    await user.click(create());
    await waitFor(() =>
      expect(screen.getByLabelText("Until the end of")).toHaveAccessibleDescription(
        "The expiry must be in the future.",
      ),
    );
    first.unmount();

    tokens({ "POST /me/tokens": failure(500, "internal_error", "Oops.") });
    await user.type(await screen.findByLabelText("Name"), "x");
    await user.click(create());
    expect(await screen.findByRole("alert")).toHaveTextContent("The server met a fault.");
  });
});

describe("the secret of a new token (A5)", () => {
  test("is shown once, where the keyboard and a screen reader are taken, and can be copied", async () => {
    const user = userEvent.setup();
    tokens();
    await user.type(await screen.findByLabelText("Name"), "ci build");
    await user.click(create());

    const made = await screen.findByRole("region", { name: "The token ci build is made" });

    expect(within(made).getByText(SECRET)).toBeVisible();
    expect(within(made).getByRole("heading", { name: "The token ci build is made" })).toHaveFocus();
    expect(made).toHaveTextContent("This is the only time it is shown.");
    expect(screen.queryByRole("button", { name: "Create token" })).toBeNull(); // one thing at a time
    await user.click(within(made).getByRole("button", { name: "Copy the token" }));
    expect(await navigator.clipboard.readText()).toBe(SECRET);
    await expectAccessible();
  });

  test("is kept nowhere: not in what was fetched, not in the address, not in the browser", async () => {
    const user = userEvent.setup();
    const { client } = tokens();
    await user.type(await screen.findByLabelText("Name"), "ci build");
    await user.click(create());
    await screen.findByRole("region", { name: "The token ci build is made" });

    const held = () =>
      JSON.stringify([
        client
          .getQueryCache()
          .getAll()
          .map((query) => query.state.data),
        client
          .getMutationCache()
          .getAll()
          .map((mutation) => mutation.state.data),
        Object.entries(window.localStorage),
        Object.entries(window.sessionStorage),
        navigation.router.push.mock.calls,
        navigation.router.replace.mock.calls,
      ]);
    await waitFor(() => expect(held()).not.toContain(SECRET));

    await user.click(screen.getByRole("button", { name: "I have copied it" }));

    expect(document.body).not.toHaveTextContent(SECRET);
    expect(held()).not.toContain(SECRET);
    // The panel that had the keyboard is gone: it is at the tokens, where the new one is.
    expect(screen.getByRole("heading", { name: "Your tokens" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Create token" })).toBeVisible();
  });
});

describe("revoking a token of one's own", () => {
  test("asks first, then says it is revoked", async () => {
    const user = userEvent.setup();
    const { calls } = tokens({ "DELETE /me/tokens/id-of-laptop": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Revoke laptop" }));
    const dialog = screen.getByRole("alertdialog", { name: "Revoke the token laptop?" });
    expect(dialog).toHaveTextContent("Whatever uses it is refused from then on.");
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
    await user.click(within(dialog).getByRole("button", { name: "Revoke" }));

    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Notifications" })).toHaveTextContent(
        "Revoked the token laptop.",
      ),
    );
    expect(calls.filter((call) => call.method === "DELETE")).toHaveLength(1);
  });

  test("says why when it could not be", async () => {
    const user = userEvent.setup();
    tokens({ "DELETE /me/tokens/id-of-laptop": failure(404, "not_found", "No such token.") });

    await user.click(await screen.findByRole("button", { name: "Revoke laptop" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Revoke" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("This was not found.");
  });
});

describe("preferences (A11)", () => {
  function preferences(session: SessionInfo = ADMIN) {
    navigation.at("/account/preferences");
    return renderUi(
      <>
        <SearchBox />
        <PreferencesScreen />
      </>,
      { session },
    );
  }

  test("are the mode and the search key, taking effect as they are chosen", async () => {
    const user = userEvent.setup();
    preferences();

    expect(screen.getByRole("heading", { level: 1, name: "Preferences" })).toBeVisible();
    expect(screen.getByRole("radio", { name: "As the system" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "Light" }));

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");
    await expectAccessible();
  });

  test("turning the search key off frees the key, there and then", async () => {
    const user = userEvent.setup();
    preferences();
    const box = screen.getByRole("searchbox", { name: "Search components" });
    const key = screen.getByRole("checkbox", { name: "Go to the search box with the / key" });
    expect(key).toBeChecked();
    expect(box).toHaveAttribute("aria-keyshortcuts", "/");

    await user.click(key);

    expect(window.localStorage.getItem(SEARCH_KEY_STORAGE)).toBe("off");
    expect(box).not.toHaveAttribute("aria-keyshortcuts");
    expect(box).toHaveAttribute("placeholder", "Search"); // it no longer says there is a key
    await user.click(screen.getByRole("heading", { level: 1 }));
    await user.keyboard("/");
    expect(box).not.toHaveFocus();

    await user.click(key);
    await user.click(screen.getByRole("heading", { level: 1 }));
    await user.keyboard("/");
    expect(box).toHaveFocus();
  });

  test("start from what was chosen before in this browser", () => {
    window.localStorage.setItem(SEARCH_KEY_STORAGE, "off");
    preferences();

    expect(
      screen.getByRole("checkbox", { name: "Go to the search box with the / key" }),
    ).not.toBeChecked();
  });

  test("are a visitor's too, who has no other page of an account", () => {
    preferences(VISITOR);

    expect(screen.getByRole("heading", { level: 1, name: "Preferences" })).toBeVisible();
    expect(screen.queryByRole("navigation", { name: "Account" })).toBeNull();
  });
});

describe("the password page", () => {
  test("is one of the pages of the account", () => {
    navigation.at("/account/password");
    renderUi(<ChangePasswordScreen />, { session: ADMIN });

    expect(
      within(screen.getByRole("navigation", { name: "Account" })).getByRole("link", {
        name: "Password",
      }),
    ).toHaveAttribute("aria-current", "page");
  });

  test("leads nowhere else for whoever must choose a password first", () => {
    navigation.at("/account/password");
    renderUi(<ChangePasswordScreen />, { session: { ...ADMIN, must_change_password: true } });

    expect(screen.queryByRole("navigation", { name: "Account" })).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 1 file does not load: `Failed to resolve import "./preferences"` or `"./tokens"` from `src/screens/account.test.tsx`. The other 603 tests pass.

- [ ] **Step 3: Implement**

Create `frontend/src/screens/tokens.tsx`:

```tsx
"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { AccountNav } from "@/components/account-nav";
import { PermissionRows, patternsAreValid } from "@/components/permission-rows";
import { TokenList } from "@/components/token-list";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { Pager } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { ChoiceGroup, SelectField } from "@/components/ui/inputs";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { isApiError } from "@/lib/api/client";
import type { TokenCreated } from "@/lib/api/types";
import { useRepositories } from "@/lib/content";
import { ACCOUNT_TOKENS, pageHref, pageOf } from "@/lib/paths";
import { READ_ONLY } from "@/lib/patterns";
import { refusalsOf } from "@/lib/refusals";
import { AT_ONCE, useCreateToken, useMyTokens, useRevokeToken } from "@/lib/security";

const DAY = 24 * 3600 * 1000;
// How long a token lasts: never, a number of days, or until a day that is chosen.
const LASTS = ["never", "30", "90", "365", "date"] as const;
type Lasts = (typeof LASTS)[number];
const LIMITS = ["everything", "read", "custom"] as const;
type Limit = (typeof LIMITS)[number];

/** The moment a token ends, as the API takes it, or null for one that does not. */
function expiryOf(lasts: Lasts, day: string): string | null {
  if (lasts === "never") return null;
  // Until the end of the day that was chosen, where the person is.
  if (lasts === "date") return new Date(`${day}T23:59:59`).toISOString();
  return new Date(Date.now() + Number(lasts) * DAY).toISOString();
}

/**
 * A token that was just made (A5). Its secret is here and nowhere else, and only
 * until this is closed or the page is left.
 */
function Made({ token, onDone }: { token: TokenCreated; onDone: () => void }) {
  const t = useTranslations("tokens");
  const heading = useRef<HTMLHeadingElement>(null);
  // The form that made it is gone: the keyboard, and a screen reader, come here.
  useEffect(() => heading.current?.focus(), []);
  return (
    <Panel role="region" aria-labelledby="made-token" className="mb-6 border-ok p-6">
      <h2
        id="made-token"
        ref={heading}
        tabIndex={-1}
        className="mb-2 text-lg font-semibold text-fg outline-none"
      >
        {t("madeTitle", { name: token.name })}
      </h2>
      <Alert tone="warning" className="mb-4">
        {t("madeOnce")}
      </Alert>
      <div className="flex items-start gap-2 rounded-sm border border-line bg-field p-3">
        <code className="min-w-0 flex-1 font-mono text-sm break-all text-fg">{token.token}</code>
        <CopyButton text={token.token} what={t("theToken")} className="-my-1" />
      </div>
      <p className="mt-3 text-sm text-fg-muted">{t("madeUse")}</p>
      <Button className="mt-4" onClick={onDone}>
        {t("madeDone")}
      </Button>
    </Panel>
  );
}

function Create({ onCreated }: { onCreated: (token: TokenCreated) => void }) {
  const t = useTranslations("tokens");
  const create = useCreateToken();
  const repositories = useRepositories();
  const [name, setName] = useState("");
  const [lasts, setLasts] = useState<Lasts>("90");
  const [day, setDay] = useState("");
  const [limit, setLimit] = useState<Limit>("everything");
  const [custom, setCustom] = useState<string[]>([]);
  const [checked, setChecked] = useState(false);
  const form = useRef<HTMLFormElement>(null);

  const refused = refusalsOf(create.error, ["name", "expires_at", "scopes"]);
  // A name that another of one's tokens has: said at the name.
  const taken =
    isApiError(create.error) && create.error.code === "conflict" ? create.error.message : null;
  const problems = {
    name: !checked ? undefined : name.trim() === "" ? t("nameNeeded") : (taken ?? refused.at.name),
    day:
      checked && lasts === "date" && day === ""
        ? t("dayNeeded")
        : lasts === "date"
          ? refused.at.expires_at
          : undefined,
    custom:
      checked && limit === "custom" && custom.length === 0 ? t("customNeeded") : refused.at.scopes,
  };

  // The keyboard goes to the first field that is wrong, where it is read with why.
  useEffect(() => {
    if (checked) form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [checked, create.error]);

  function submit(event: FormEvent) {
    event.preventDefault();
    setChecked(true);
    create.reset();
    const scopes = limit === "everything" ? null : limit === "read" ? [...READ_ONLY] : custom;
    if (name.trim() === "" || (lasts === "date" && day === "")) return;
    if (scopes !== null && (scopes.length === 0 || !patternsAreValid(scopes))) return;
    create.mutate(
      { name: name.trim(), expires_at: expiryOf(lasts, day), scopes },
      { onSuccess: onCreated },
    );
  }

  return (
    <Panel className="mb-6 p-6">
      <h2 className="mb-4 text-lg font-semibold text-fg uppercase">{t("createTitle")}</h2>
      <form ref={form} onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label={t("fields.name")}
            hint={t("hints.name")}
            required
            maxLength={100}
            value={name}
            error={problems.name}
            onChange={(event) => setName(event.target.value)}
          />
          <div className="flex flex-col gap-3">
            <SelectField
              label={t("fields.lasts")}
              value={lasts}
              onChange={(event) => setLasts(event.target.value as Lasts)}
              choices={LASTS.map((value) => ({ value, label: t(`lasts.${value}`) }))}
            />
            {lasts === "date" ? (
              <TextField
                label={t("fields.day")}
                type="date"
                required
                value={day}
                error={problems.day}
                onChange={(event) => setDay(event.target.value)}
              />
            ) : null}
          </div>
        </div>
        <ChoiceGroup
          legend={t("fields.limit")}
          value={limit}
          onChange={(value) => setLimit(value as Limit)}
          options={LIMITS.map((value) => ({
            value,
            label: t(`limits.${value}`),
            hint: t(`limitHints.${value}`),
          }))}
        />
        {limit === "custom" ? (
          <>
            <PermissionRows
              legend={t("fields.custom")}
              initial={custom}
              onChange={setCustom}
              repositories={repositories.data?.items ?? []}
              checked={checked}
            />
            {problems.custom ? <Alert tone="danger">{problems.custom}</Alert> : null}
          </>
        ) : null}
        {create.isError && taken === null && refused.elsewhere ? (
          <ErrorState error={create.error} />
        ) : null}
        <div>
          <Button type="submit" variant="primary" busy={create.isPending}>
            <Plus aria-hidden="true" className="size-4" />
            {t("create")}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

/** A person's own API tokens (A4, A5): those there are, a new one, and revoking one. */
export function TokensScreen() {
  const t = useTranslations("tokens");
  const notify = useNotify();
  const page = pageOf(useSearchParams());
  const tokens = useMyTokens(page);
  const revoke = useRevokeToken();
  const [made, setMade] = useState<TokenCreated | null>(null);
  const listed = useRef<HTMLHeadingElement>(null);

  return (
    <div className="mx-auto max-w-5xl">
      <AccountNav />
      <PageHeader title={t("title")} intro={t("intro")} />
      {made ? (
        <Made
          token={made}
          onDone={() => {
            // The panel that had the keyboard goes: it is put at the tokens, where the
            // new one now is.
            listed.current?.focus();
            setMade(null);
          }}
        />
      ) : (
        <Create onCreated={setMade} />
      )}
      <Panel>
        <h2
          ref={listed}
          tabIndex={-1}
          className="px-4 pt-4 text-lg font-semibold text-fg uppercase outline-none"
        >
          {t("listTitle")}
        </h2>
        {tokens.isError ? (
          <ErrorState error={tokens.error} onRetry={() => void tokens.refetch()} className="m-4" />
        ) : !tokens.data ? (
          <LoadingState />
        ) : (
          <>
            <TokenList
              caption={t("listTitle")}
              tokens={tokens.data.items}
              empty={t("none")}
              onRevoke={async (token) => {
                await revoke.mutateAsync(token.id);
                notify(t("revoked", { name: token.name }));
              }}
            />
            <Pager
              page={page}
              pages={Math.ceil(tokens.data.total / AT_ONCE)}
              hrefFor={(target) => pageHref(ACCOUNT_TOKENS, target)}
            />
          </>
        )}
      </Panel>
    </div>
  );
}
```

Create `frontend/src/screens/preferences.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";

import { AccountNav } from "@/components/account-nav";
import { useTheme } from "@/components/theme-provider";
import { CheckboxField, ChoiceGroup } from "@/components/ui/inputs";
import { PageHeader, Panel } from "@/components/ui/panel";
import { useSearchKey } from "@/lib/preferences";
import { CHOICES, isChoice } from "@/lib/theme";

/**
 * How this UI behaves for the person in front of it (A11): the mode, and whether `/`
 * goes to the search box. Both are kept in the browser and take effect as they are
 * chosen, so there is nothing to save, and a visitor has them as much as anybody.
 */
export function PreferencesScreen() {
  const t = useTranslations("preferences");
  const mode = useTranslations("theme");
  const { choice, choose } = useTheme();
  const [searchKey, setSearchKey] = useSearchKey();
  return (
    <div className="mx-auto max-w-2xl">
      <AccountNav />
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel className="flex flex-col gap-8 p-6">
        <ChoiceGroup
          legend={mode("label")}
          value={choice}
          onChange={(value) => {
            if (isChoice(value)) choose(value);
          }}
          options={CHOICES.map((value) => ({ value, label: mode(value) }))}
        />
        <fieldset className="flex min-w-0 flex-col gap-2 border-0 p-0">
          <legend className="label-caps mb-1 p-0 text-fg-muted">{t("keys")}</legend>
          <CheckboxField
            label={t("searchKey")}
            hint={t("searchKeyHint")}
            checked={searchKey}
            onChange={(event) => setSearchKey(event.target.checked)}
          />
        </fieldset>
      </Panel>
    </div>
  );
}
```

Change `frontend/src/screens/change-password.tsx`:

```diff
@@ -4,6 +4,7 @@ import { useTranslations } from "next-intl";
 import { useRouter } from "next/navigation";
 import { useEffect, useRef, useState, type FormEvent } from "react";
 
+import { AccountNav } from "@/components/account-nav";
 import { Alert } from "@/components/ui/alert";
 import { Button } from "@/components/ui/button";
 import { TextField } from "@/components/ui/field";
@@ -83,6 +84,8 @@ export function ChangePasswordScreen() {
   const unexplained = change.isError && fromServer(change.error) === null;
   return (
     <div className="mx-auto max-w-lg">
+      {/* Whoever must choose a password first can go nowhere else, and is shown no way there. */}
+      {forced ? null : <AccountNav />}
       <PageHeader title={forced ? t("mustChangeTitle") : t("title")} />
       {forced ? (
         <Alert tone="warning" className="mb-6">
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 621 passed in 22 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): one's own API tokens and preferences"
```

---

### Task 4: Users, roles and anonymous access

**Files:**
- Create: `frontend/src/screens/users.tsx`, `user.tsx`, `roles.tsx`, `anonymous-access.tsx` (all in `frontend/src/screens/`)
- Test: `frontend/src/screens/security.test.tsx`

**Interfaces:**
- Consumes: the hooks of `lib/security.ts`; `PermissionRows`, `PermissionList`, `patternsAreValid`, `TokenList`, `NewPasswordField`, `CheckList`, `ChoiceGroup`; `refusalsOf`; `parseUser`, `parseRole`, `userHref`, `roleHref`, `pageOf`, `pageHref`; `allows`; `ConfirmDialog` with `mustType`; `useNotify`; `NothingHere`.
- Produces: `UsersScreen()` at `/admin/users`; `NewUserScreen()` at `/admin/users/new` and `UserScreen()` at `/admin/users/<id>`, both in `user.tsx`; `RolesScreen()` at `/admin/roles`, `NewRoleScreen()` at `/admin/roles/new` and `RoleScreen()` at `/admin/roles/<name>`, all in `roles.tsx`; `AnonymousAccessScreen()` at `/admin/anonymous-access`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/screens/security.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { AnonymousAccessScreen } from "./anonymous-access";
import { NewRoleScreen, RoleScreen, RolesScreen } from "./roles";
import { NewUserScreen, UserScreen } from "./user";
import { UsersScreen } from "./users";

const page = (items: unknown[], total = items.length) => ({ items, total, limit: 50, offset: 0 });
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });

const person = (username: string, more: Record<string, unknown> = {}) => ({
  id: `id-of-${username}`,
  username,
  display_name: `${username[0]?.toUpperCase()}${username.slice(1)} Example`,
  email: null,
  status: "active",
  must_change_password: false,
  builtin: false,
  roles: [],
  created_at: "2026-10-01T08:00:00Z",
  last_login_at: null,
  ...more,
});
const ALICE = person("alice", { roles: ["deployers"], email: "alice@example.com" });
const ANONYMOUS = person("anonymous", { builtin: true, roles: ["anonymous"] });
// The session's own user, as the users API has it.
const SELF = person("admin", { id: ADMIN.user?.id, builtin: true, roles: ["admin"] });

const role = (name: string, more: Record<string, unknown> = {}) => ({
  name,
  description: "",
  builtin: false,
  permissions: [],
  roles: [],
  ...more,
});
const ROLES = [
  role("admin", { builtin: true, description: "Full access to everything.", permissions: ["*"] }),
  role("anonymous", {
    builtin: true,
    description: "What requests without credentials may do.",
    permissions: ["repository:*:*:browse", "repository:*:*:read"],
  }),
  role("deployers", {
    description: "May deploy releases",
    permissions: ["repository:maven:releases:add", "admin:audit:read"],
    roles: ["anonymous"],
  }),
];
const DEPLOYERS = ROLES[2];
const REPOSITORIES = page([
  { name: "releases", format: "maven", type: "hosted", online: true, url: "" },
]);

const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });

describe("the users (A13)", () => {
  function users(more: Routes = {}, session = ADMIN, address = "/admin/users") {
    const api = mockApi({ "GET /users": { json: page([SELF, ALICE, ANONYMOUS]) }, ...more });
    navigation.at(address);
    return { ...renderUi(<UsersScreen />, { session }), ...api };
  }

  test("are listed with their roles and whether they can sign in", async () => {
    const { calls } = users({
      "GET /users": {
        json: page([
          SELF,
          person("bob", { status: "disabled", must_change_password: true }),
          ALICE,
        ]),
      },
    });

    const table = await screen.findByRole("table", { name: "Users" });
    const rows = within(table).getAllByRole("row").slice(1);

    expect(calls[0]?.path).toBe("/users?limit=50&offset=0");
    expect(within(rows[2] as HTMLElement).getByRole("link", { name: "alice" })).toHaveAttribute(
      "href",
      "/admin/users/id-of-alice",
    );
    expect(rows[2]).toHaveTextContent("Alice Example");
    expect(rows[2]).toHaveTextContent("deployers");
    expect(rows[2]).toHaveTextContent("Active");
    expect(rows[0]).toHaveTextContent("Built in");
    expect(rows[1]).toHaveTextContent("Disabled");
    expect(rows[1]).toHaveTextContent("Must change password");
    expect(screen.getByRole("link", { name: "New user" })).toHaveAttribute(
      "href",
      "/admin/users/new",
    );
    await expectAccessible();
  });

  test("offer no new user to whoever may only read them", async () => {
    users({}, holding("admin:users:read"));

    await screen.findByRole("table", { name: "Users" });

    expect(screen.queryByRole("link", { name: "New user" })).toBeNull();
  });

  test("come a page at a time, and say so when they may not be seen", async () => {
    const first = users(
      { "GET /users": { json: page([ALICE], 101) } },
      ADMIN,
      "/admin/users?page=3",
    );
    const pages = await screen.findByRole("navigation", { name: "Pages" });
    expect(first.calls[0]?.path).toBe("/users?limit=50&offset=100");
    expect(pages).toHaveTextContent("Page 3 of 3");
    expect(within(pages).getByRole("link", { name: "Previous" })).toHaveAttribute(
      "href",
      "/admin/users?page=2",
    );
    first.unmount();

    users({ "GET /users": failure(403, "forbidden", "No.") });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You do not have permission to do this.",
    );
  });
});

describe("a new user (A6)", () => {
  function fresh(more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      "GET /roles": { json: page(ROLES) },
      "POST /users": (call) => ({
        status: 201,
        json: person((call.body as { username: string }).username, {
          must_change_password: (call.body as { must_change_password: boolean })
            .must_change_password,
        }),
      }),
      "GET /auth/session": { json: session },
      ...more,
    });
    navigation.at("/admin/users/new");
    return { ...renderUi(<NewUserScreen />, { session }), ...api };
  }
  const submit = () => screen.getByRole("button", { name: "Create user" });

  test("is made with a name, a password to start with, and roles", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.type(screen.getByLabelText("User name"), "carol");
    await user.type(screen.getByLabelText("Name"), " Carol Example ");
    await user.type(screen.getByLabelText("Password"), "typed-by-hand");
    await user.click(await screen.findByRole("checkbox", { name: "deployers" }));
    await user.click(submit());

    await screen.findByRole("region", { name: "The user carol is created" });
    expect(of(calls, "POST")[0]?.body).toEqual({
      username: "carol",
      display_name: "Carol Example",
      email: null,
      password: "typed-by-hand",
      must_change_password: true,
      roles: ["deployers"],
    });
    await expectAccessible();
  });

  test("says the password to pass on once more, where the keyboard is taken", async () => {
    const user = userEvent.setup();
    fresh();
    await user.type(screen.getByLabelText("User name"), "carol");
    await user.type(screen.getByLabelText("Name"), "Carol");
    await user.click(screen.getByRole("button", { name: "Generate one" }));
    const generated = (screen.getByLabelText("Password") as HTMLInputElement).value;
    await user.click(submit());

    const created = await screen.findByRole("region", { name: "The user carol is created" });

    expect(within(created).getByRole("heading")).toHaveFocus();
    expect(within(created).getByText(generated)).toBeVisible();
    expect(created).toHaveTextContent("They sign in with it once, and then choose their own.");
    expect(created).toHaveTextContent("It is not shown again once you leave this page.");
    await user.click(within(created).getByRole("button", { name: "Copy the password" }));
    expect(await navigator.clipboard.readText()).toBe(generated);
    expect(within(created).getByRole("link", { name: "Open carol" })).toHaveAttribute(
      "href",
      "/admin/users/id-of-carol",
    );

    // Another one: the form is empty again, and has the keyboard.
    await user.click(within(created).getByRole("button", { name: "Create another" }));
    expect(screen.getByLabelText("User name")).toHaveValue("");
    expect(screen.getByLabelText("User name")).toHaveFocus();
    expect(document.body).not.toHaveTextContent(generated);
  });

  test("says what is wrong with what was typed, at the first field it is wrong at", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.type(screen.getByLabelText("User name"), "has space");
    await user.type(screen.getByLabelText("Email"), "not-an-address");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(submit());

    expect(screen.getByLabelText("User name")).toHaveAccessibleDescription(
      "A user name is 1 to 64 letters, digits or . _ @ -",
    );
    expect(screen.getByLabelText("User name")).toHaveFocus();
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription("Give their name.");
    expect(screen.getByLabelText("Email")).toHaveAccessibleDescription(
      "This is not an email address.",
    );
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
      "The password must be at least 8 characters long.",
    );
    expect(of(calls, "POST")).toHaveLength(0);
  });

  test("says that a name is taken at the name, and anything else the server refuses where it belongs", async () => {
    const user = userEvent.setup();
    const fill = async () => {
      await user.type(screen.getByLabelText("User name"), "alice");
      await user.type(screen.getByLabelText("Name"), "Alice");
      await user.type(screen.getByLabelText("Password"), "long-enough");
      await user.click(submit());
    };
    const first = fresh({
      "POST /users": failure(409, "conflict", "A user named alice already exists."),
    });
    await fill();
    await waitFor(() =>
      expect(screen.getByLabelText("User name")).toHaveAccessibleDescription(
        "A user named alice already exists.",
      ),
    );
    expect(screen.getByLabelText("User name")).toHaveFocus();
    first.unmount();

    const second = fresh({
      "POST /users": failure(422, "validation_error", "The request is not valid.", [
        { field: "password", message: "The password must not be the user name." },
      ]),
    });
    await fill();
    await waitFor(() =>
      expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
        "The password must not be the user name.",
      ),
    );
    second.unmount();

    fresh({ "POST /users": failure(500, "internal_error", "Oops.") });
    await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent("The server met a fault.");
  });

  test("gives no role where the roles may not be seen, and says so", async () => {
    const user = userEvent.setup();
    const { calls } = fresh({}, holding("admin:users:read", "admin:users:write"));

    expect(screen.getByText("You may not see the roles, so none can be given here.")).toBeVisible();
    await user.type(screen.getByLabelText("User name"), "dave");
    await user.type(screen.getByLabelText("Name"), "Dave");
    await user.type(screen.getByLabelText("Password"), "long-enough");
    await user.click(submit());

    await screen.findByRole("region", { name: "The user dave is created" });
    expect(calls.some((call) => call.path.startsWith("/roles"))).toBe(false);
    expect((of(calls, "POST")[0]?.body as { roles: string[] }).roles).toEqual([]);
  });
});

describe("one user", () => {
  function one(who = ALICE, more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      [`GET /users/${who.id}`]: { json: who },
      [`GET /users/${who.id}/tokens`]: {
        json: page([
          {
            id: "t1",
            name: "ci build",
            display_prefix: "mga_Uw7S",
            scopes: null,
            expires_at: null,
            created_at: "2026-10-01T08:00:00Z",
            last_used_at: null,
          },
        ]),
      },
      "GET /roles": { json: page(ROLES) },
      "GET /users": { json: page([SELF, ALICE]) },
      "GET /auth/session": { json: session },
      ...more,
    });
    navigation.at(`/admin/users/${who.id}`);
    return { ...renderUi(<UserScreen />, { session }), ...api };
  }

  test("is who they are, what they hold, and whether they can sign in", async () => {
    one();

    expect(await screen.findByRole("heading", { level: 1, name: "alice" })).toBeVisible();
    expect(screen.getByLabelText("Name")).toHaveValue("Alice Example");
    expect(screen.getByLabelText("Email")).toHaveValue("alice@example.com");
    expect(await screen.findByRole("checkbox", { name: "deployers" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "admin" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Active" })).toBeChecked();
    expect(
      within(screen.getByRole("navigation", { name: "Path" })).getAllByRole("link")[0],
    ).toHaveAttribute("href", "/admin/users");
    await expectAccessible();
  });

  test("is saved with what was changed, and the session is asked again (A10)", async () => {
    const user = userEvent.setup();
    const { calls } = one(ALICE, { "PATCH /users/id-of-alice": { json: ALICE } });
    await screen.findByRole("checkbox", { name: "deployers" });

    await user.clear(screen.getByLabelText("Email"));
    await user.click(screen.getByRole("checkbox", { name: "admin" }));
    await user.click(screen.getByRole("radio", { name: "Disabled" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Saved alice."));
    expect(of(calls, "PATCH")[0]?.body).toEqual({
      display_name: "Alice Example",
      email: null,
      roles: ["deployers", "admin"],
      status: "disabled",
    });
    // What the person who saved may do can have changed with it.
    await waitFor(() => expect(calls.some((call) => call.path === "/auth/session")).toBe(true));
    expect(screen.getByRole("button", { name: "Save" })).toHaveFocus();
  });

  test("says what the server will not have, as it says it", async () => {
    const user = userEvent.setup();
    one(ALICE, {
      "PATCH /users/id-of-alice": failure(
        409,
        "last_administrator",
        "This would leave nobody who can sign in with full access.",
      ),
    });
    await screen.findByRole("checkbox", { name: "deployers" });

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This would leave nobody who can sign in with full access.",
    );
  });

  test("one's own account cannot be disabled or deleted here, and the screen says so (A7)", async () => {
    const user = userEvent.setup();
    const { calls } = one(SELF, { [`PATCH /users/${SELF.id}`]: { json: SELF } });
    await screen.findByRole("checkbox", { name: "admin" });

    expect(screen.queryByRole("radio", { name: "Disabled" })).toBeNull();
    expect(screen.getByText("This is your own account: you cannot disable it.")).toBeVisible();
    expect(screen.getByText("This is your own account: you cannot delete it.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Delete user" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(of(calls, "PATCH")).toHaveLength(1));
    expect(of(calls, "PATCH")[0]?.body).not.toHaveProperty("status");
  });

  test("a built-in user is not deleted, and the anonymous one has no password", async () => {
    one(ANONYMOUS);

    await screen.findByRole("heading", { level: 1, name: "anonymous" });

    expect(
      screen.getByText("This user is built in. It can be changed, and not deleted."),
    ).toBeVisible();
    expect(
      screen.getByText("A built-in user cannot be deleted. It can be disabled."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Delete user" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Set a new password" })).toBeNull();
    expect(screen.getByRole("radio", { name: "Disabled" })).toBeVisible();
  });

  test("is shown, and not changed, by whoever may only read users", async () => {
    const { calls } = one(ALICE, {}, holding("admin:users:read"));

    await screen.findByRole("heading", { level: 1, name: "alice" });

    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.getByText("deployers")).toBeVisible(); // held, as text: roles may not be read
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Set a new password" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Delete this user" })).toBeNull();
    // Nor their tokens, which is a permission of its own.
    expect(screen.queryByRole("heading", { name: "API tokens" })).toBeNull();
    expect(calls.some((call) => call.path.includes("/tokens"))).toBe(false);
    expect(calls.some((call) => call.path.startsWith("/roles"))).toBe(false);
  });

  test("is given a new password, typed or generated, which is to be passed on", async () => {
    const user = userEvent.setup();
    const { calls } = one(ALICE, { "PUT /users/id-of-alice/password": { status: 204 } });
    await screen.findByRole("heading", { name: "Set a new password" });

    await user.type(screen.getByLabelText("New password"), "short");
    await user.click(screen.getByRole("button", { name: "Set password" }));
    expect(screen.getByLabelText("New password")).toHaveAccessibleDescription(
      "The password must be at least 8 characters long.",
    );
    expect(screen.getByLabelText("New password")).toHaveFocus();
    expect(of(calls, "PUT")).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Generate one" }));
    const generated = (screen.getByLabelText("New password") as HTMLInputElement).value;
    await user.click(
      screen.getByRole("checkbox", { name: "Must choose a new password at the next sign-in" }),
    );
    await user.click(screen.getByRole("button", { name: "Set password" }));

    expect(await screen.findByText("The password of alice is set")).toBeVisible();
    expect(of(calls, "PUT")[0]?.body).toEqual({
      password: generated,
      must_change_password: false,
    });
    // Still there to be copied: it is not shown again once the page is left.
    expect(screen.getByLabelText("New password")).toHaveValue(generated);
  });

  test("has their tokens listed, and revoked by whoever may", async () => {
    const user = userEvent.setup();
    const first = one(ALICE, { "DELETE /users/id-of-alice/tokens/t1": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Revoke ci build" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Revoke" }),
    );

    await waitFor(() =>
      expect(notices()).toHaveTextContent("Revoked the token ci build of alice."),
    );
    expect(of(first.calls, "DELETE")[0]?.path).toBe("/users/id-of-alice/tokens/t1");
    first.unmount();

    one(ALICE, {}, holding("admin:users:read", "admin:tokens:read"));
    expect(await screen.findByRole("table", { name: "API tokens of alice" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Revoke ci build" })).toBeNull();
  });

  test("is deleted only by whoever types their name, and is then not asked for again (A8)", async () => {
    const user = userEvent.setup();
    const { calls } = one(ALICE, { "DELETE /users/id-of-alice": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Delete user" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete the user alice?" });
    const confirm = within(dialog).getByRole("button", { name: "Delete user" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Type alice to go on"), "alice");
    await user.click(confirm);

    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/admin/users"));
    expect(notices()).toHaveTextContent("Deleted the user alice.");
    await new Promise((resolve) => setTimeout(resolve, 50));
    const since = calls.slice(calls.findIndex((call) => call.method === "DELETE") + 1);
    expect(since.filter((call) => call.path.startsWith("/users/id-of-alice"))).toEqual([]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("says why when the user could not be deleted, or is not there", async () => {
    const user = userEvent.setup();
    const first = one(ALICE, {
      "DELETE /users/id-of-alice": failure(409, "last_administrator", "Nobody would be left."),
    });
    await user.click(await screen.findByRole("button", { name: "Delete user" }));
    const dialog = screen.getByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Type alice to go on"), "alice");
    await user.click(within(dialog).getByRole("button", { name: "Delete user" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nobody would be left.");
    expect(navigation.router.replace).not.toHaveBeenCalled();
    first.unmount();

    one(ALICE, { "GET /users/id-of-alice": failure(404, "not_found", "No such user.") });
    expect(await screen.findByRole("alert")).toHaveTextContent("This was not found.");
  });
});

describe("the roles", () => {
  function roles(session = ADMIN) {
    const api = mockApi({ "GET /roles": { json: page(ROLES) } });
    navigation.at("/admin/roles");
    return { ...renderUi(<RolesScreen />, { session }), ...api };
  }

  test("are listed with what they hold", async () => {
    const { calls } = roles();

    const table = await screen.findByRole("table", { name: "Roles" });
    const rows = within(table).getAllByRole("row").slice(1);

    expect(calls[0]?.path).toBe("/roles?limit=50&offset=0");
    expect(within(rows[2] as HTMLElement).getByRole("link", { name: "deployers" })).toHaveAttribute(
      "href",
      "/admin/roles/deployers",
    );
    expect(rows[2]).toHaveTextContent("May deploy releases");
    expect(rows[2]).toHaveTextContent("repository:maven:releases:add");
    expect(rows[2]).toHaveTextContent("anonymous");
    expect(rows[0]).toHaveTextContent("Built in");
    expect(screen.getByRole("link", { name: "New role" })).toHaveAttribute(
      "href",
      "/admin/roles/new",
    );
    await expectAccessible();
  });

  test("offer no new role to whoever may only read them", async () => {
    roles(holding("admin:roles:read"));

    await screen.findByRole("table", { name: "Roles" });

    expect(screen.queryByRole("link", { name: "New role" })).toBeNull();
  });
});

describe("a role", () => {
  const SAVED = { ...DEPLOYERS };
  function existing(which = DEPLOYERS, more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      [`GET /roles/${which?.name}`]: { json: which },
      "GET /roles": { json: page(ROLES) },
      "GET /content": { json: REPOSITORIES },
      "GET /users": { json: page([SELF]) },
      "GET /auth/session": { json: session },
      ...more,
    });
    navigation.at(`/admin/roles/${which?.name}`);
    return { ...renderUi(<RoleScreen />, { session }), ...api };
  }
  function fresh(more: Routes = {}) {
    const api = mockApi({
      "GET /roles": { json: page(ROLES) },
      "GET /content": { json: REPOSITORIES },
      "GET /users": { json: page([SELF]) },
      "GET /auth/session": { json: ADMIN },
      "POST /roles": (call) => ({ status: 201, json: role((call.body as { name: string }).name) }),
      ...more,
    });
    navigation.at("/admin/roles/new");
    return { ...renderUi(<NewRoleScreen />, { session: ADMIN }), ...api };
  }

  test("is made with a name, permissions as rows, and the roles it contains", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.type(screen.getByLabelText("Name"), "readers");
    await user.type(screen.getByLabelText("Description"), "May read everything");
    await user.click(screen.getByRole("button", { name: "Add a permission" }));
    await user.click(await screen.findByRole("checkbox", { name: "anonymous" }));
    await user.click(screen.getByRole("button", { name: "Create role" }));

    await waitFor(() =>
      expect(navigation.router.push).toHaveBeenCalledWith("/admin/roles/readers"),
    );
    expect(of(calls, "POST")[0]?.body).toEqual({
      name: "readers",
      description: "May read everything",
      permissions: ["repository:*:*:read"],
      roles: ["anonymous"],
    });
    expect(notices()).toHaveTextContent("Created the role readers.");
  });

  test("needs a name of the kind a role has, and one no other role has", async () => {
    const user = userEvent.setup();
    const { calls } = fresh({
      "POST /roles": failure(409, "conflict", "A role named deployers already exists."),
    });

    await user.type(screen.getByLabelText("Name"), "has space");
    await user.click(screen.getByRole("button", { name: "Create role" }));
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
      "A role's name is 1 to 64 letters, digits or . _ -",
    );
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(of(calls, "POST")).toHaveLength(0);

    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "deployers");
    await user.click(screen.getByRole("button", { name: "Create role" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
        "A role named deployers already exists.",
      ),
    );
    expect(navigation.router.push).not.toHaveBeenCalled();
  });

  test("opens with what it holds, and loses nothing by being saved as it is (A3)", async () => {
    const user = userEvent.setup();
    const { calls } = existing(DEPLOYERS, { "PUT /roles/deployers": { json: SAVED } });

    expect(await screen.findByRole("heading", { level: 1, name: "deployers" })).toBeVisible();
    const first = screen.getByRole("group", { name: "Permission 1" });
    expect(within(first).getByLabelText("Repository")).toHaveValue("releases");
    // A permission this UI has no lists for is there as it was typed.
    expect(
      within(screen.getByRole("group", { name: "Permission 2" })).getByLabelText("Pattern"),
    ).toHaveValue("admin:audit:read");
    // A role does not contain itself, so it is not offered itself.
    expect(await screen.findByRole("checkbox", { name: "anonymous" })).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "deployers" })).toBeNull();
    await expectAccessible();

    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Saved the role deployers."));
    expect(of(calls, "PUT")[0]?.body).toEqual({
      description: "May deploy releases",
      permissions: ["repository:maven:releases:add", "admin:audit:read"],
      roles: ["anonymous"],
    });
    await waitFor(() => expect(calls.some((call) => call.path === "/auth/session")).toBe(true));
  });

  test("is not saved while a permission is no pattern: the keyboard goes to it", async () => {
    const user = userEvent.setup();
    const { calls } = existing(DEPLOYERS, { "PUT /roles/deployers": { json: SAVED } });
    await screen.findByRole("group", { name: "Permission 2" });

    const typed = within(screen.getByRole("group", { name: "Permission 2" })).getByLabelText(
      "Pattern",
    );
    await user.clear(typed);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(typed).toHaveAttribute("aria-invalid", "true");
    expect(typed).toHaveFocus();
    expect(of(calls, "PUT")).toHaveLength(0);
  });

  test("says what the server will not have: a role that would contain itself", async () => {
    const user = userEvent.setup();
    existing(DEPLOYERS, {
      "PUT /roles/deployers": failure(
        409,
        "role_cycle",
        "A role cannot contain itself, directly or indirectly.",
      ),
    });
    await screen.findByRole("group", { name: "Permission 1" });

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A role cannot contain itself, directly or indirectly.",
    );
  });

  test("the role that makes an administrator is shown, and changed by nobody (A7)", async () => {
    existing(ROLES[0]);

    expect(await screen.findByRole("heading", { level: 1, name: "admin" })).toBeVisible();
    expect(screen.getByText(/It grants everything, and cannot be changed/)).toBeVisible();
    expect(
      screen.getByText("Everything: every repository, and all of the administration."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add a permission" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete role" })).toBeNull();
  });

  test("another built-in role is changed, and not deleted", async () => {
    existing(ROLES[1]);

    expect(await screen.findByRole("button", { name: "Save" })).toBeVisible();
    expect(
      screen.getByText("This role is built in. It can be changed, and not deleted."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Delete role" })).toBeNull();
  });

  test("is shown, and not changed, by whoever may only read roles", async () => {
    existing(DEPLOYERS, {}, holding("admin:roles:read"));

    await screen.findByRole("heading", { level: 1, name: "deployers" });

    expect(screen.getByText("repository:maven:releases:add")).toBeVisible();
    expect(screen.getByText("Add in the maven repository releases.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete role" })).toBeNull();
  });

  test("is deleted after asking, and is then not asked for again (A8)", async () => {
    const user = userEvent.setup();
    const { calls } = existing(DEPLOYERS, { "DELETE /roles/deployers": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Delete role" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete the role deployers?" });
    expect(dialog).toHaveTextContent("Everyone who holds it loses what it grants, at once.");
    await user.click(within(dialog).getByRole("button", { name: "Delete role" }));

    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/admin/roles"));
    expect(notices()).toHaveTextContent("Deleted the role deployers.");
    await new Promise((resolve) => setTimeout(resolve, 50));
    const since = calls.slice(calls.findIndex((call) => call.method === "DELETE") + 1);
    expect(since.filter((call) => call.path === "/roles/deployers")).toEqual([]);
  });
});

describe("anonymous access (A9)", () => {
  function anonymous(enabled: boolean, more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      "GET /settings": { json: { base_url: null, anonymous_access: { enabled } } },
      "PUT /settings/anonymous-access": (call) => ({
        json: { base_url: null, anonymous_access: call.body },
      }),
      "GET /users": { json: page([SELF, ALICE, { ...ANONYMOUS, roles: ["deployers"] }]) },
      "GET /roles": { json: page(ROLES) },
      ...more,
    });
    navigation.at("/admin/anonymous-access");
    return { ...renderUi(<AnonymousAccessScreen />, { session }), ...api };
  }

  test("is off until it is turned on, which asks first and says what it means", async () => {
    const user = userEvent.setup();
    const { calls } = anonymous(false);

    expect(await screen.findByText("Off")).toBeVisible();
    expect(screen.getByText(/Nothing is given without signing in/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Turn on" }));
    const dialog = screen.getByRole("alertdialog", { name: "Turn anonymous access on?" });
    expect(dialog).toHaveTextContent("Anyone who can reach this server");
    expect(of(calls, "PUT")).toHaveLength(0);
    await expectAccessible();
    await user.click(within(dialog).getByRole("button", { name: "Turn on" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Anonymous access is on."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ enabled: true });
    expect(screen.getByText("On")).toBeVisible();
    expect(screen.getByRole("button", { name: "Turn off" })).toBeVisible();
  });

  test("is turned off at once", async () => {
    const user = userEvent.setup();
    const { calls } = anonymous(true);

    await user.click(await screen.findByRole("button", { name: "Turn off" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Anonymous access is off."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ enabled: false });
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  test("shows what a visitor may do: the anonymous user's roles, and those they contain", async () => {
    anonymous(true);

    expect(await screen.findByRole("link", { name: "deployers" })).toHaveAttribute(
      "href",
      "/admin/roles/deployers",
    );
    expect(screen.getByRole("link", { name: "Change its roles" })).toHaveAttribute(
      "href",
      "/admin/users/id-of-anonymous",
    );
    // Of deployers itself, and of the role anonymous that it contains.
    expect(screen.getByText("repository:maven:releases:add")).toBeVisible();
    expect(screen.getByText("Browse in every repository.")).toBeVisible();
    expect(screen.getByText("Read in every repository.")).toBeVisible();
    // Not what a visitor is never allowed, whatever the roles say.
    expect(screen.queryByText("admin:audit:read")).toBeNull();
    await expectAccessible();
  });

  test("offers no switch to whoever may only read the settings, and says what it cannot show", async () => {
    const { calls } = anonymous(false, {}, holding("admin:settings:read"));

    expect(await screen.findByText("Off")).toBeVisible();

    expect(screen.queryByRole("button", { name: "Turn on" })).toBeNull();
    expect(screen.getByText(/You may not see users and roles/)).toBeVisible();
    expect(calls.map((call) => call.path)).toEqual(["/settings"]);
  });

  test("says why when it could not be changed", async () => {
    const user = userEvent.setup();
    anonymous(true, { "PUT /settings/anonymous-access": failure(403, "forbidden", "No.") });

    await user.click(await screen.findByRole("button", { name: "Turn off" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You do not have permission to do this.",
    );
    expect(screen.getByText("On")).toBeVisible();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 1 file does not load: `Failed to resolve import` of one of the four screens, from `src/screens/security.test.tsx`. The other 621 tests pass.

- [ ] **Step 3: Implement**

Create `frontend/src/screens/users.tsx`:

```tsx
"use client";

import { UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";

import { StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Pager, Time } from "@/components/ui/details";
import { AppLink } from "@/components/ui/link";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { NEW_USER, pageHref, pageOf, userHref, USERS } from "@/lib/paths";
import { AT_ONCE, useUsers } from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

/** The users there are (A13): who they are, what roles they hold, and whether they can sign in. */
export function UsersScreen() {
  const t = useTranslations("users");
  const session = useSession();
  const page = pageOf(useSearchParams());
  const users = useUsers(page);
  const mayWrite = session.data !== undefined && allows(session.data, "admin:users:write");

  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")}>
        {mayWrite ? (
          <Button asChild variant="primary" size="sm">
            <AppLink href={NEW_USER}>
              <UserPlus aria-hidden="true" className="size-4" />
              {t("new")}
            </AppLink>
          </Button>
        ) : null}
      </PageHeader>
      {users.isError ? (
        <ErrorState error={users.error} onRetry={() => void users.refetch()} />
      ) : !users.data ? (
        <Panel>
          <LoadingState />
        </Panel>
      ) : (
        <Panel>
          <Table caption={t("title")}>
            <thead>
              <tr>
                <Th>{t("columns.username")}</Th>
                <Th>{t("columns.displayName")}</Th>
                <Th>{t("columns.roles")}</Th>
                <Th>{t("columns.state")}</Th>
                <Th>{t("columns.lastSignIn")}</Th>
              </tr>
            </thead>
            <tbody>
              {users.data.items.map((user) => (
                <tr key={user.id} className="hover:bg-raised">
                  <Td>
                    <AppLink
                      href={userHref(user.id)}
                      className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
                    >
                      {user.username}
                    </AppLink>
                  </Td>
                  <Td className="break-words">{user.display_name}</Td>
                  <Td className="font-mono text-xs break-all">{user.roles.join(", ")}</Td>
                  <Td>
                    <div className="flex flex-wrap gap-1.5">
                      <StatusTag tone={user.status === "active" ? "success" : "warning"}>
                        {user.status === "active" ? t("active") : t("disabled")}
                      </StatusTag>
                      {user.builtin ? <StatusTag tone="info">{t("builtin")}</StatusTag> : null}
                      {user.must_change_password ? (
                        <StatusTag tone="info">{t("mustChange")}</StatusTag>
                      ) : null}
                    </div>
                  </Td>
                  <Td className="whitespace-nowrap text-fg-muted">
                    <Time value={user.last_login_at} />
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <Pager
            page={page}
            pages={Math.ceil(users.data.total / AT_ONCE)}
            hrefFor={(target) => pageHref(USERS, target)}
          />
        </Panel>
      )}
    </>
  );
}
```

Create `frontend/src/screens/user.tsx`:

```tsx
"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { NewPasswordField } from "@/components/new-password-field";
import { TokenList } from "@/components/token-list";
import { Alert } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { CopyButton } from "@/components/ui/copy-button";
import { Fact, Facts, Time } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { CheckboxField, CheckList, ChoiceGroup } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { isApiError } from "@/lib/api/client";
import type { UserOut } from "@/lib/api/types";
import { NEW_USER, parseUser, userHref, USERS } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import {
  useCreateUser,
  useDeleteUser,
  useEveryRole,
  useResetPassword,
  useRevokeUserToken,
  useUpdateUser,
  useUser,
  useUserTokens,
} from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

// The server's rules, said before the request is made. The server still decides.
const USERNAME = /^[A-Za-z0-9._@-]{1,64}$/;
const EMAIL = /^[^@\s]+@[^@\s]+$/;
const MIN_PASSWORD = 8;
const ANONYMOUS = "anonymous";

const H2 = "mb-4 text-lg font-semibold text-fg uppercase";

/** The keyboard goes to the first field that is wrong, whenever what is wrong changes. */
function useFocusOnWrong(changed: unknown) {
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [changed]);
  return form;
}

/** The roles a user can be given, as ticks. Without the right to read roles: those they hold. */
function useRoleOptions(held: string[]) {
  const session = useSession();
  const mayRead = session.data !== undefined && allows(session.data, "admin:roles:read");
  const roles = useEveryRole(mayRead);
  const names = roles.data?.items.map((role) => role.name) ?? [];
  // A role that is held is one of the choices, though it be beyond what was fetched.
  const all = Array.from(new Set([...names, ...held])).sort();
  const described = new Map(roles.data?.items.map((role) => [role.name, role.description]));
  return {
    known: mayRead ? roles.data !== undefined : true,
    canChoose: mayRead,
    options: all.map((name) => ({
      value: name,
      label: name,
      hint: described.get(name) || undefined,
    })),
  };
}

// ============================== a new user ================================================

/** A user that was just made, with the password to pass on, which is not shown again. */
function Created({
  user,
  password,
  onAnother,
}: {
  user: UserOut;
  password: string;
  onAnother: () => void;
}) {
  const t = useTranslations("users");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  return (
    <Panel role="region" aria-labelledby="created-user" className="border-ok p-6">
      <h2
        id="created-user"
        ref={heading}
        tabIndex={-1}
        className="mb-2 text-lg font-semibold text-fg outline-none"
      >
        {t("createdTitle", { username: user.username })}
      </h2>
      <p className="mb-3 text-fg-muted">
        {user.must_change_password ? t("createdMustChange") : t("createdKeeps")}
      </p>
      <div className="flex items-start gap-2 rounded-sm border border-line bg-field p-3">
        <code className="min-w-0 flex-1 font-mono text-sm break-all text-fg">{password}</code>
        <CopyButton text={password} what={t("thePassword")} className="-my-1" />
      </div>
      <p className="mt-3 text-sm text-fg-muted">{t("createdOnce")}</p>
      <div className="mt-4 flex flex-wrap gap-3">
        <Button asChild variant="primary">
          <AppLink href={userHref(user.id)}>{t("open", { username: user.username })}</AppLink>
        </Button>
        <Button onClick={onAnother}>{t("another")}</Button>
      </div>
    </Panel>
  );
}

function NewUserForm({
  onCreated,
  again,
}: {
  onCreated: (user: UserOut, password: string) => void;
  /** It follows a user that was just made: the keyboard starts at its first field. */
  again: boolean;
}) {
  const t = useTranslations("users");
  const create = useCreateUser();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mustChange, setMustChange] = useState(true);
  const [roles, setRoles] = useState<string[]>([]);
  const [checked, setChecked] = useState(false);
  const choices = useRoleOptions(roles);

  const refused = refusalsOf(create.error, [
    "username",
    "display_name",
    "email",
    "password",
    "roles",
  ]);
  // A name another user has: said at the name.
  const taken =
    isApiError(create.error) && create.error.code === "conflict" ? create.error.message : null;
  const own = {
    username: USERNAME.test(username) ? undefined : t("usernameRule"),
    displayName: displayName.trim() === "" ? t("displayNameNeeded") : undefined,
    email: email.trim() === "" || EMAIL.test(email.trim()) ? undefined : t("emailRule"),
    password: password.length < MIN_PASSWORD ? t("passwordRule", { min: MIN_PASSWORD }) : undefined,
  };
  const problems = checked
    ? {
        username: own.username ?? taken ?? refused.at.username,
        displayName: own.displayName ?? refused.at.display_name,
        email: own.email ?? refused.at.email,
        password: own.password ?? refused.at.password,
      }
    : {};
  const form = useFocusOnWrong(`${checked}${String(create.error)}`);
  useEffect(() => {
    // The panel that said a user was made had the keyboard, and is gone.
    if (again) form.current?.querySelector("input")?.focus();
  }, [again, form]);

  function submit(event: FormEvent) {
    event.preventDefault();
    setChecked(true);
    create.reset();
    if (Object.values(own).some(Boolean)) return;
    create.mutate(
      {
        username,
        display_name: displayName.trim(),
        email: email.trim() || null,
        password,
        must_change_password: mustChange,
        roles,
      },
      { onSuccess: (user) => onCreated(user, password) },
    );
  }

  return (
    <Panel className="p-6">
      <form ref={form} onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label={t("fields.username")}
            hint={t("hints.username")}
            required
            spellCheck={false}
            autoComplete="off"
            value={username}
            error={problems.username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <TextField
            label={t("fields.displayName")}
            required
            autoComplete="off"
            value={displayName}
            error={problems.displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </div>
        <TextField
          label={t("fields.email")}
          hint={t("hints.email")}
          type="email"
          autoComplete="off"
          value={email}
          error={problems.email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <NewPasswordField
          label={t("fields.password")}
          hint={t("hints.password", { min: MIN_PASSWORD })}
          value={password}
          error={problems.password}
          onChange={setPassword}
        />
        <CheckboxField
          label={t("fields.mustChange")}
          hint={t("hints.mustChange")}
          checked={mustChange}
          onChange={(event) => setMustChange(event.target.checked)}
        />
        {choices.canChoose ? (
          <CheckList
            legend={t("fields.roles")}
            options={choices.options}
            value={roles}
            onChange={setRoles}
            empty={t("noRoles")}
          />
        ) : (
          <p className="text-sm text-fg-subtle">{t("rolesNotReadable")}</p>
        )}
        {refused.at.roles ? <Alert tone="danger">{refused.at.roles}</Alert> : null}
        {create.isError && taken === null && refused.elsewhere ? (
          <ErrorState error={create.error} />
        ) : null}
        <div>
          <Button type="submit" variant="primary" busy={create.isPending}>
            {t("create")}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

/** A new user (A6): who they are, the password they start with, and their roles. */
export function NewUserScreen() {
  const t = useTranslations("users");
  const [created, setCreated] = useState<{ user: UserOut; password: string } | null>(null);
  const [again, setAgain] = useState(false);
  return (
    <div className="mx-auto max-w-3xl">
      <Breadcrumbs
        label={t("path")}
        crumbs={[
          { name: t("title"), href: USERS },
          { name: t("newTitle"), href: NEW_USER },
        ]}
      />
      <PageHeader title={t("newTitle")} />
      {created ? (
        <Created
          user={created.user}
          password={created.password}
          onAnother={() => {
            setAgain(true);
            setCreated(null);
          }}
        />
      ) : (
        <NewUserForm again={again} onCreated={(user, password) => setCreated({ user, password })} />
      )}
    </div>
  );
}

// ============================== one user ===================================================

function Details({
  user,
  mayWrite,
  isSelf,
}: {
  user: UserOut;
  mayWrite: boolean;
  isSelf: boolean;
}) {
  const t = useTranslations("users");
  const notify = useNotify();
  const update = useUpdateUser(user.id);
  const [displayName, setDisplayName] = useState(user.display_name);
  const [email, setEmail] = useState(user.email ?? "");
  const [roles, setRoles] = useState(user.roles);
  const [status, setStatus] = useState(user.status);
  const [checked, setChecked] = useState(false);
  const choices = useRoleOptions(user.roles);

  const refused = refusalsOf(update.error, ["display_name", "email", "roles", "status"]);
  const own = {
    displayName: displayName.trim() === "" ? t("displayNameNeeded") : undefined,
    email: email.trim() === "" || EMAIL.test(email.trim()) ? undefined : t("emailRule"),
  };
  const problems = checked
    ? {
        displayName: own.displayName ?? refused.at.display_name,
        email: own.email ?? refused.at.email,
      }
    : {};
  const form = useFocusOnWrong(`${checked}${String(update.error)}`);

  function submit(event: FormEvent) {
    event.preventDefault();
    setChecked(true);
    update.reset();
    if (Object.values(own).some(Boolean)) return;
    update.mutate(
      {
        display_name: displayName.trim(),
        email: email.trim() || null,
        // What could not be chosen is not sent, and so is not changed.
        ...(choices.canChoose ? { roles } : {}),
        ...(isSelf ? {} : { status: status as "active" | "disabled" }),
      },
      { onSuccess: () => notify(t("saved", { username: user.username })) },
    );
  }

  return (
    <Panel className="p-6">
      <h2 className={H2}>{t("details")}</h2>
      <Facts className="mb-5">
        <Fact name={t("fields.username")} copy={user.username} mono>
          {user.username}
        </Fact>
        <Fact name={t("facts.created")}>
          <Time value={user.created_at} />
        </Fact>
        <Fact name={t("facts.lastSignIn")}>
          <Time value={user.last_login_at} />
        </Fact>
      </Facts>
      <form ref={form} onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <fieldset disabled={!mayWrite} className="flex min-w-0 flex-col gap-5 border-0 p-0">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label={t("fields.displayName")}
              required
              autoComplete="off"
              value={displayName}
              error={problems.displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
            <TextField
              label={t("fields.email")}
              type="email"
              autoComplete="off"
              value={email}
              error={problems.email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          {choices.canChoose ? (
            <CheckList
              legend={t("fields.roles")}
              options={choices.options}
              value={roles}
              onChange={setRoles}
              empty={t("noRoles")}
            />
          ) : (
            <Facts>
              <Fact name={t("fields.roles")} mono>
                {user.roles.join(", ") || t("noRolesHeld")}
              </Fact>
            </Facts>
          )}
          {refused.at.roles ? <Alert tone="danger">{refused.at.roles}</Alert> : null}
          {isSelf ? (
            <p className="text-sm text-fg-subtle">{t("selfState")}</p>
          ) : (
            <ChoiceGroup
              legend={t("fields.state")}
              value={status}
              onChange={setStatus}
              options={[
                { value: "active", label: t("active"), hint: t("hints.active") },
                { value: "disabled", label: t("disabled"), hint: t("hints.disabled") },
              ]}
            />
          )}
        </fieldset>
        {update.isError && refused.elsewhere ? <ErrorState error={update.error} /> : null}
        {mayWrite ? (
          <div>
            <Button type="submit" variant="primary" busy={update.isPending}>
              {t("save")}
            </Button>
          </div>
        ) : null}
      </form>
    </Panel>
  );
}

function Password({ user }: { user: UserOut }) {
  const t = useTranslations("users");
  const reset = useResetPassword(user.id);
  const [password, setPassword] = useState("");
  const [mustChange, setMustChange] = useState(true);
  const [checked, setChecked] = useState(false);
  const refused = refusalsOf(reset.error, ["password"]);
  const short = password.length < MIN_PASSWORD ? t("passwordRule", { min: MIN_PASSWORD }) : null;
  const problem = checked ? (short ?? refused.at.password) : undefined;
  const form = useFocusOnWrong(`${checked}${String(reset.error)}`);

  function submit(event: FormEvent) {
    event.preventDefault();
    setChecked(true);
    reset.reset();
    if (short) return;
    reset.mutate({ password, must_change_password: mustChange });
  }

  return (
    <Panel className="p-6">
      <h2 className={H2}>{t("passwordTitle")}</h2>
      <form ref={form} onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <NewPasswordField
          label={t("fields.newPassword")}
          hint={t("hints.newPassword", { min: MIN_PASSWORD })}
          value={password}
          error={problem}
          onChange={(value) => {
            setPassword(value);
            reset.reset(); // what was set is not what is in the field any more
          }}
        />
        <CheckboxField
          label={t("fields.mustChange")}
          hint={t("hints.mustChange")}
          checked={mustChange}
          onChange={(event) => setMustChange(event.target.checked)}
        />
        {reset.isError && refused.elsewhere ? <ErrorState error={reset.error} /> : null}
        {reset.isSuccess ? (
          <Alert tone="success" title={t("passwordSet", { username: user.username })}>
            {t("passwordSetOnce")}
          </Alert>
        ) : null}
        <div>
          <Button type="submit" busy={reset.isPending}>
            {t("setPassword")}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

function Tokens({ user, mayRevoke }: { user: UserOut; mayRevoke: boolean }) {
  const t = useTranslations("users");
  const notify = useNotify();
  const tokens = useUserTokens(user.id, true);
  const revoke = useRevokeUserToken(user.id);
  return (
    <Panel>
      <h2 className="px-6 pt-6 text-lg font-semibold text-fg uppercase">{t("tokensTitle")}</h2>
      {tokens.isError ? (
        <ErrorState error={tokens.error} onRetry={() => void tokens.refetch()} className="m-6" />
      ) : !tokens.data ? (
        <LoadingState />
      ) : (
        <TokenList
          caption={t("tokensOf", { username: user.username })}
          tokens={tokens.data.items}
          empty={t("noTokens")}
          onRevoke={
            mayRevoke
              ? async (token) => {
                  await revoke.mutateAsync(token.id);
                  notify(t("tokenRevoked", { name: token.name, username: user.username }));
                }
              : undefined
          }
        />
      )}
    </Panel>
  );
}

function Delete({
  user,
  remove,
}: {
  user: UserOut;
  /** The screen's own: once it has succeeded, the screen stops asking for the user. */
  remove: ReturnType<typeof useDeleteUser>;
}) {
  const t = useTranslations("users");
  const router = useRouter();
  const notify = useNotify();
  const [asking, setAsking] = useState(false);
  return (
    <Panel className="p-6">
      <h2 className={H2}>{t("deleteTitle")}</h2>
      <p className="mb-4 text-fg-muted">{t("deleteIntro")}</p>
      {remove.isError ? <ErrorState error={remove.error} className="mb-4" /> : null}
      <Button
        variant="danger"
        onClick={() => {
          remove.reset();
          setAsking(true);
        }}
      >
        <Trash2 aria-hidden="true" className="size-4" />
        {t("delete")}
      </Button>
      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        title={t("deleteAsk", { username: user.username })}
        confirmLabel={t("delete")}
        mustType={user.username}
        busy={remove.isPending}
        onConfirm={() =>
          remove.mutate(user.id, {
            onSuccess: () => {
              notify(t("deleted", { username: user.username }));
              router.replace(USERS);
            },
            onSettled: () => setAsking(false),
          })
        }
      >
        {t("deleteBody")}
      </ConfirmDialog>
    </Panel>
  );
}

/** One user: who they are and what they hold, a new password, their tokens, and deleting them (A7, A8). */
export function UserScreen() {
  const t = useTranslations("users");
  const session = useSession();
  const where = parseUser(usePathname());
  const remove = useDeleteUser();
  // Once deleted, the user is not asked for again: the answer would be that there is
  // none, shown for the moment before the screen returns to the list.
  const user = useUser(remove.isSuccess ? null : (where?.id ?? null));

  if (where === null) return <NothingHere />;
  if (user.isError) return <ErrorState error={user.error} onRetry={() => void user.refetch()} />;
  if (!user.data || !session.data) return <LoadingState />;

  const found = user.data;
  const may = (permission: string) => allows(session.data, permission);
  const mayWrite = may("admin:users:write");
  const isSelf = session.data.user?.id === found.id;
  const isAnonymous = found.builtin && found.username === ANONYMOUS;
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Breadcrumbs
          label={t("path")}
          crumbs={[
            { name: t("title"), href: USERS },
            { name: found.username, href: userHref(found.id) },
          ]}
        />
        <PageHeader named title={found.username} intro={found.display_name} />
        {found.builtin ? <Alert tone="info">{t("builtinNote")}</Alert> : null}
      </div>
      <Details user={found} mayWrite={mayWrite} isSelf={isSelf} />
      {mayWrite && !isAnonymous ? <Password user={found} /> : null}
      {may("admin:tokens:read") ? (
        <Tokens user={found} mayRevoke={may("admin:tokens:write")} />
      ) : null}
      {mayWrite ? (
        isSelf || found.builtin ? (
          <Panel className="p-6">
            <h2 className={H2}>{t("deleteTitle")}</h2>
            <p className="text-fg-muted">{isSelf ? t("selfDelete") : t("builtinDelete")}</p>
          </Panel>
        ) : (
          <Delete user={found} remove={remove} />
        )
      ) : null}
    </div>
  );
}
```

Create `frontend/src/screens/roles.tsx`:

```tsx
"use client";

import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { PermissionList, PermissionRows, patternsAreValid } from "@/components/permission-rows";
import { Alert, StatusTag } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Pager } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { CheckList } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { isApiError } from "@/lib/api/client";
import type { RoleOut } from "@/lib/api/types";
import { useRepositories } from "@/lib/content";
import { NEW_ROLE, pageHref, pageOf, parseRole, roleHref, ROLES } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import {
  AT_ONCE,
  useCreateRole,
  useDeleteRole,
  useEveryRole,
  useRole,
  useRoles,
  useUpdateRole,
} from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

// The server's rule for a role's name, said before the request is made.
const NAME = /^[A-Za-z0-9_.-]{1,64}$/;
const ADMIN = "admin";
const H2 = "mb-4 text-lg font-semibold text-fg uppercase";

function useMayWrite(): boolean {
  const session = useSession();
  return session.data !== undefined && allows(session.data, "admin:roles:write");
}

/** The roles there are (A13): what each is called, and what it holds. */
export function RolesScreen() {
  const t = useTranslations("roles");
  const page = pageOf(useSearchParams());
  const roles = useRoles(page);
  const mayWrite = useMayWrite();

  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")}>
        {mayWrite ? (
          <Button asChild variant="primary" size="sm">
            <AppLink href={NEW_ROLE}>
              <Plus aria-hidden="true" className="size-4" />
              {t("new")}
            </AppLink>
          </Button>
        ) : null}
      </PageHeader>
      {roles.isError ? (
        <ErrorState error={roles.error} onRetry={() => void roles.refetch()} />
      ) : !roles.data ? (
        <Panel>
          <LoadingState />
        </Panel>
      ) : (
        <Panel>
          <Table caption={t("title")}>
            <thead>
              <tr>
                <Th>{t("columns.name")}</Th>
                <Th>{t("columns.description")}</Th>
                <Th>{t("columns.permissions")}</Th>
                <Th>{t("columns.contains")}</Th>
              </tr>
            </thead>
            <tbody>
              {roles.data.items.map((role) => (
                <tr key={role.name} className="hover:bg-raised">
                  <Td>
                    <div className="flex flex-wrap items-center gap-2">
                      <AppLink
                        href={roleHref(role.name)}
                        className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
                      >
                        {role.name}
                      </AppLink>
                      {role.builtin ? <StatusTag tone="info">{t("builtin")}</StatusTag> : null}
                    </div>
                  </Td>
                  <Td className="break-words text-fg-muted">{role.description}</Td>
                  <Td className="font-mono text-xs break-all">{role.permissions.join(", ")}</Td>
                  <Td className="font-mono text-xs break-all">{role.roles.join(", ")}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <Pager
            page={page}
            pages={Math.ceil(roles.data.total / AT_ONCE)}
            hrefFor={(target) => pageHref(ROLES, target)}
          />
        </Panel>
      )}
    </>
  );
}

type Content = { name: string; description: string; permissions: string[]; roles: string[] };

/**
 * The form of a role, new or not: its description, its permissions as rows (A2), and
 * the roles it contains. `onSave` is given what the form holds once it can be sent.
 */
function RoleForm({
  role,
  saving,
  error,
  onSave,
  saveLabel,
}: {
  /** The role as it is, or null for one that is not there yet, which also has a name. */
  role: RoleOut | null;
  saving: boolean;
  error: unknown;
  onSave: (content: Content) => void;
  saveLabel: string;
}) {
  const t = useTranslations("roles");
  const repositories = useRepositories();
  const others = useEveryRole();
  const [name, setName] = useState("");
  const [description, setDescription] = useState(role?.description ?? "");
  const [permissions, setPermissions] = useState(role?.permissions ?? []);
  const [contained, setContained] = useState(role?.roles ?? []);
  const [checked, setChecked] = useState(false);
  const form = useRef<HTMLFormElement>(null);

  const refused = refusalsOf(error, ["name", "description", "permissions", "roles"]);
  // A name another role has: said at the name.
  const taken = isApiError(error) && error.code === "conflict" ? error.message : null;
  const ownName = role === null && !NAME.test(name) ? t("nameRule") : undefined;
  const nameProblem = checked ? (ownName ?? taken ?? refused.at.name) : undefined;

  // The keyboard goes to the first field that is wrong, where it is read with why.
  useEffect(() => {
    if (checked) form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [checked, error]);

  function submit(event: FormEvent) {
    event.preventDefault();
    setChecked(true);
    if (ownName || !patternsAreValid(permissions)) return;
    onSave({ name, description: description.trim(), permissions, roles: contained });
  }

  // A role does not contain itself, and what it contains is one of the choices though
  // it be beyond what was fetched.
  const names = Array.from(
    new Set([...(others.data?.items.map((other) => other.name) ?? []), ...contained]),
  )
    .filter((other) => other !== role?.name)
    .sort();
  const described = new Map(others.data?.items.map((other) => [other.name, other.description]));
  return (
    <form ref={form} onSubmit={submit} className="flex flex-col gap-6" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        {role === null ? (
          <TextField
            label={t("fields.name")}
            hint={t("hints.name")}
            required
            spellCheck={false}
            autoComplete="off"
            value={name}
            error={nameProblem}
            onChange={(event) => setName(event.target.value)}
          />
        ) : null}
        <TextField
          label={t("fields.description")}
          maxLength={255}
          value={description}
          error={checked ? refused.at.description : undefined}
          onChange={(event) => setDescription(event.target.value)}
        />
      </div>
      <PermissionRows
        legend={t("fields.permissions")}
        initial={permissions}
        onChange={setPermissions}
        repositories={repositories.data?.items ?? []}
        checked={checked}
      />
      {refused.at.permissions ? <Alert tone="danger">{refused.at.permissions}</Alert> : null}
      <CheckList
        legend={t("fields.contains")}
        options={names.map((other) => ({
          value: other,
          label: other,
          hint: described.get(other) || undefined,
        }))}
        value={contained}
        onChange={setContained}
        empty={t("noOtherRoles")}
      />
      {refused.at.roles ? <Alert tone="danger">{refused.at.roles}</Alert> : null}
      {error && taken === null && refused.elsewhere ? <ErrorState error={error} /> : null}
      <div>
        <Button type="submit" variant="primary" busy={saving}>
          {saveLabel}
        </Button>
      </div>
    </form>
  );
}

/** A new role. */
export function NewRoleScreen() {
  const t = useTranslations("roles");
  const router = useRouter();
  const notify = useNotify();
  const create = useCreateRole();
  return (
    <div className="mx-auto max-w-4xl">
      <Breadcrumbs
        label={t("path")}
        crumbs={[
          { name: t("title"), href: ROLES },
          { name: t("newTitle"), href: NEW_ROLE },
        ]}
      />
      <PageHeader title={t("newTitle")} />
      <Panel className="p-6">
        <RoleForm
          role={null}
          saving={create.isPending}
          error={create.error}
          saveLabel={t("create")}
          onSave={(content) =>
            create.mutate(content, {
              onSuccess: (role) => {
                notify(t("created", { name: role.name }));
                router.push(roleHref(role.name));
              },
            })
          }
        />
      </Panel>
    </div>
  );
}

function Edit({ role }: { role: RoleOut }) {
  const t = useTranslations("roles");
  const notify = useNotify();
  const update = useUpdateRole(role.name);
  return (
    <Panel className="p-6">
      <RoleForm
        role={role}
        saving={update.isPending}
        error={update.error}
        saveLabel={t("save")}
        onSave={({ description, permissions, roles }) =>
          update.mutate(
            { description, permissions, roles },
            { onSuccess: () => notify(t("saved", { name: role.name })) },
          )
        }
      />
    </Panel>
  );
}

/** A role as it is, for whoever may not change it, and for the one role nobody may. */
function Shown({ role }: { role: RoleOut }) {
  const t = useTranslations("roles");
  return (
    <Panel className="flex flex-col gap-6 p-6">
      <Facts>
        <Fact name={t("fields.description")}>{role.description}</Fact>
        <Fact name={t("fields.contains")} mono>
          {role.roles.join(", ") || t("containsNone")}
        </Fact>
      </Facts>
      <div>
        <h2 className={H2}>{t("fields.permissions")}</h2>
        <PermissionList patterns={role.permissions} empty={t("noPermissions")} />
      </div>
    </Panel>
  );
}

/** One role: what it grants and contains, and deleting it (A7, A8). */
export function RoleScreen() {
  const t = useTranslations("roles");
  const router = useRouter();
  const notify = useNotify();
  const where = parseRole(usePathname());
  const mayWrite = useMayWrite();
  const remove = useDeleteRole();
  // Once deleted, the role is not asked for again: there is none to answer with.
  const role = useRole(remove.isSuccess ? null : (where?.name ?? null));
  const [asking, setAsking] = useState(false);

  if (where === null) return <NothingHere />;
  if (role.isError) return <ErrorState error={role.error} onRetry={() => void role.refetch()} />;
  if (!role.data) return <LoadingState />;

  const found = role.data;
  // The server lets nobody change the role that makes an administrator.
  const fixed = found.builtin && found.name === ADMIN;
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Breadcrumbs
          label={t("path")}
          crumbs={[
            { name: t("title"), href: ROLES },
            { name: found.name, href: roleHref(found.name) },
          ]}
        />
        <PageHeader named title={found.name} />
        {fixed ? (
          <Alert tone="info">{t("adminFixed")}</Alert>
        ) : found.builtin ? (
          <Alert tone="info">{t("builtinNote")}</Alert>
        ) : null}
      </div>
      {mayWrite && !fixed ? <Edit role={found} /> : <Shown role={found} />}
      {mayWrite && !found.builtin ? (
        <Panel className="p-6">
          <h2 className={H2}>{t("deleteTitle")}</h2>
          <p className="mb-4 text-fg-muted">{t("deleteIntro")}</p>
          {remove.isError ? <ErrorState error={remove.error} className="mb-4" /> : null}
          <Button
            variant="danger"
            onClick={() => {
              remove.reset();
              setAsking(true);
            }}
          >
            <Trash2 aria-hidden="true" className="size-4" />
            {t("delete")}
          </Button>
          <ConfirmDialog
            open={asking}
            onOpenChange={setAsking}
            title={t("deleteAsk", { name: found.name })}
            confirmLabel={t("delete")}
            busy={remove.isPending}
            onConfirm={() =>
              remove.mutate(found.name, {
                onSuccess: () => {
                  notify(t("deleted", { name: found.name }));
                  router.replace(ROLES);
                },
                onSettled: () => setAsking(false),
              })
            }
          >
            {t("deleteBody")}
          </ConfirmDialog>
        </Panel>
      ) : null}
    </div>
  );
}
```

Create `frontend/src/screens/anonymous-access.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { PermissionList } from "@/components/permission-rows";
import { StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import type { RoleOut } from "@/lib/api/types";
import { roleHref, userHref, USERS } from "@/lib/paths";
import { useAnonymousUser, useEveryRole, useSetAnonymousAccess, useSettings } from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

const H2 = "mb-3 text-lg font-semibold text-fg uppercase";

/**
 * Every pattern the roles of these names grant, with those of the roles they contain.
 * Only what concerns repositories: whatever its roles say, a request without
 * credentials is allowed nothing else.
 */
function patternsOf(held: string[], roles: RoleOut[]): string[] {
  const byName = new Map(roles.map((role) => [role.name, role]));
  const seen = new Set<string>();
  const patterns = new Set<string>();
  const visit = (name: string) => {
    if (seen.has(name)) return;
    seen.add(name);
    const role = byName.get(name);
    role?.permissions.forEach((pattern) => patterns.add(pattern));
    role?.roles.forEach(visit);
  };
  held.forEach(visit);
  return Array.from(patterns)
    .filter((pattern) => ["*", "repository"].includes(pattern.split(":")[0] ?? ""))
    .sort();
}

/** What a visitor may do, as far as this caller may see it: the anonymous user and its roles. */
function Allowed() {
  const t = useTranslations("anonymous");
  const session = useSession();
  const may = (permission: string) =>
    session.data !== undefined && allows(session.data, permission);
  const readable = may("admin:users:read") && may("admin:roles:read");
  const user = useAnonymousUser(readable);
  const roles = useEveryRole(readable);

  if (!readable) return <p className="text-fg-muted">{t("notReadable")}</p>;
  const failed = user.isError ? user : roles.isError ? roles : null;
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  if (user.data === undefined || !roles.data) return <LoadingState className="p-4" />;
  if (user.data === null) {
    return (
      <p className="flex flex-wrap gap-x-2 text-fg-muted">
        <span>{t("userNotFound")}</span>
        <AppLink href={USERS} className="text-ink-cyan underline-offset-4 hover:underline">
          {t("toUsers")}
        </AppLink>
      </p>
    );
  }
  const held = user.data.roles;
  return (
    <div className="flex flex-col gap-4">
      <p className="flex flex-wrap gap-x-2 text-fg-muted">
        <span>{t("rolesIntro")}</span>
        <AppLink
          href={userHref(user.data.id)}
          className="text-ink-cyan underline-offset-4 hover:underline"
        >
          {t("toUser")}
        </AppLink>
      </p>
      {held.length === 0 ? (
        <p className="text-fg">{t("noRoles")}</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {held.map((name) => (
            <li key={name}>
              <AppLink
                href={roleHref(name)}
                className="rounded-sm border border-line-strong px-2 py-1 font-mono text-sm text-ink-cyan hover:border-neon-cyan"
              >
                {name}
              </AppLink>
            </li>
          ))}
        </ul>
      )}
      <PermissionList patterns={patternsOf(held, roles.data.items)} empty={t("grantsNothing")} />
      <p className="text-sm text-fg-subtle">{t("onlyRepositories")}</p>
    </div>
  );
}

/**
 * Whether someone who is not signed in may use the server at all (A9). It is the one
 * setting that makes content public, so turning it on asks first.
 */
export function AnonymousAccessScreen() {
  const t = useTranslations("anonymous");
  const session = useSession();
  const notify = useNotify();
  const settings = useSettings();
  const change = useSetAnonymousAccess();
  const [asking, setAsking] = useState(false);

  if (settings.isError) {
    return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;
  }
  if (!settings.data) return <LoadingState />;

  const on = settings.data.anonymous_access.enabled;
  const mayWrite = session.data !== undefined && allows(session.data, "admin:settings:write");
  const set = (enabled: boolean) =>
    change.mutate(enabled, {
      onSuccess: () => notify(enabled ? t("turnedOn") : t("turnedOff")),
      onSettled: () => setAsking(false),
    });

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="text-fg">{t("state")}</span>
            <StatusTag tone={on ? "warning" : "success"}>{on ? t("on") : t("off")}</StatusTag>
          </div>
          {mayWrite ? (
            <Button
              variant={on ? "primary" : "secondary"}
              busy={change.isPending && !asking}
              onClick={() => (on ? set(false) : setAsking(true))}
            >
              {on ? t("turnOff") : t("turnOn")}
            </Button>
          ) : null}
        </div>
        <p className="mt-3 text-fg-muted">{on ? t("onMeans") : t("offMeans")}</p>
        {change.isError ? <ErrorState error={change.error} className="mt-4" /> : null}
      </Panel>
      <Panel className="p-6">
        <h2 className={H2}>{t("allowedTitle")}</h2>
        <Allowed />
      </Panel>
      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        title={t("ask")}
        confirmLabel={t("turnOn")}
        busy={change.isPending}
        onConfirm={() => set(true)}
      >
        {t("askBody")}
      </ConfirmDialog>
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 655 passed in 23 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): users, roles and anonymous access"
```

---

### Task 5: The routes

**Files:**
- Create: `page.tsx` in each of `account/tokens`, `account/preferences`, `admin/users`, `admin/users/new`, `admin/users/[id]`, `admin/roles`, `admin/roles/new`, `admin/roles/[name]` and `admin/anonymous-access`, under `frontend/src/app/(shell)/`
- Test (modify): `frontend/src/app/titles.test.ts`

**Interfaces:**
- Consumes: the screens of Tasks 3 and 4.
- Produces: the nine addresses, each with a title.

- [ ] **Step 1: Write the failing test**

Change `frontend/src/app/titles.test.ts`:

```diff
@@ -1,6 +1,15 @@
 import { expect, test } from "vitest";
 
 import { metadata as password } from "./(shell)/account/password/page";
+import { metadata as preferences } from "./(shell)/account/preferences/page";
+import { metadata as tokens } from "./(shell)/account/tokens/page";
+import { metadata as anonymousAccess } from "./(shell)/admin/anonymous-access/page";
+import { metadata as role } from "./(shell)/admin/roles/[name]/page";
+import { metadata as newRole } from "./(shell)/admin/roles/new/page";
+import { metadata as roles } from "./(shell)/admin/roles/page";
+import { metadata as user } from "./(shell)/admin/users/[id]/page";
+import { metadata as newUser } from "./(shell)/admin/users/new/page";
+import { metadata as users } from "./(shell)/admin/users/page";
 import { generateMetadata as browse } from "./(shell)/browse/[repository]/[[...path]]/page";
 import { generateMetadata as component } from "./(shell)/components/[repository]/[id]/page";
 import { metadata as home } from "./(shell)/page";
@@ -31,6 +40,13 @@ test("each screen has a title of its own", () => {
   ]);
 });
 
+test("the screens of the account and of the administration have titles of their own", () => {
+  expect([tokens.title, preferences.title]).toEqual(["API tokens", "Preferences"]);
+  expect([users.title, newUser.title, user.title]).toEqual(["Users", "New user", "User"]);
+  expect([roles.title, newRole.title, role.title]).toEqual(["Roles", "New role", "Role"]);
+  expect(anonymousAccess.title).toBe("Anonymous access");
+});
+
 test("a screen about one repository is titled by it, as the address names it", async () => {
   const at = (repository: string) => ({ params: Promise.resolve({ repository }) });
 
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm test`
Expected: 1 file does not load: `Failed to resolve import` of one of the new routes, from `src/app/titles.test.ts`. The other tests pass.

- [ ] **Step 3: Implement**

Create `frontend/src/app/(shell)/account/tokens/page.tsx`:

```tsx
import type { Metadata } from "next";

import { TokensScreen } from "@/screens/tokens";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.tokens.title };

export default function Page() {
  return <TokensScreen />;
}
```

Create `frontend/src/app/(shell)/account/preferences/page.tsx`:

```tsx
import type { Metadata } from "next";

import { PreferencesScreen } from "@/screens/preferences";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.preferences.title };

export default function Page() {
  return <PreferencesScreen />;
}
```

Create `frontend/src/app/(shell)/admin/users/page.tsx`:

```tsx
import type { Metadata } from "next";

import { UsersScreen } from "@/screens/users";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.users.title };

export default function Page() {
  return <UsersScreen />;
}
```

Create `frontend/src/app/(shell)/admin/users/new/page.tsx`:

```tsx
import type { Metadata } from "next";

import { NewUserScreen } from "@/screens/user";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.users.newTitle };

export default function Page() {
  return <NewUserScreen />;
}
```

Create `frontend/src/app/(shell)/admin/users/[id]/page.tsx`:

```tsx
import type { Metadata } from "next";

import { UserScreen } from "@/screens/user";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.users.oneTitle };

export default function Page() {
  return <UserScreen />;
}
```

Create `frontend/src/app/(shell)/admin/roles/page.tsx`:

```tsx
import type { Metadata } from "next";

import { RolesScreen } from "@/screens/roles";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.roles.title };

export default function Page() {
  return <RolesScreen />;
}
```

Create `frontend/src/app/(shell)/admin/roles/new/page.tsx`:

```tsx
import type { Metadata } from "next";

import { NewRoleScreen } from "@/screens/roles";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.roles.newTitle };

export default function Page() {
  return <NewRoleScreen />;
}
```

Create `frontend/src/app/(shell)/admin/roles/[name]/page.tsx`:

```tsx
import type { Metadata } from "next";

import { RoleScreen } from "@/screens/roles";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.roles.oneTitle };

export default function Page() {
  return <RoleScreen />;
}
```

Create `frontend/src/app/(shell)/admin/anonymous-access/page.tsx`:

```tsx
import type { Metadata } from "next";

import { AnonymousAccessScreen } from "@/screens/anonymous-access";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.anonymous.title };

export default function Page() {
  return <AnonymousAccessScreen />;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 656 passed in 23 files.

Run: `pnpm lint && pnpm typecheck`
Expected: no finding.

Run: `pnpm build`
Expected: `Compiled successfully`, and the nine routes in the list, each rendered for its request (`ƒ`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): the routes of the account and security screens"
```

---

### Task 6: The screens in a real browser, and the documents

**Files:**
- Modify: `frontend/e2e/ui.spec.ts`, `backend/tests/test_ui_client.py`
- Modify: `README.md`, `docs/superpowers/specs/2026-10-12-frontend-design.md`

**Interfaces:**
- Consumes: the whole stack of `docker-compose.yml`, started by the `stack` fixture of `backend/tests/conftest.py`.
- Produces: 14 more browser tests, between "a version is deleted from its page, and is then not found" and "an upload refused because the session was replaced in another tab": 52 in all, of which the docker suite expects at least 51 to be reported as passed.

- [ ] **Step 1: Write the browser tests**

Change `frontend/e2e/ui.spec.ts`:

```diff
@@ -12,6 +12,10 @@ const REPOSITORY = "browser-test-files";
 const RELEASES = "browser-test-releases";
 const GROUP = "browser-test-all";
 const IMAGES = "browser-test-images";
+const TOKEN = "browser-test-build";
+const ROLE = "browser-test-deployers";
+const ALICE = "browser-test-alice";
+const HER_PASSWORD = "chosen-by-alice-herself";
 // A name with what an address gives a meaning to: a space, a fragment, an escape.
 const ODD = "a b#c%.txt";
 const UPLOADS = "**/api/v1/content/*/upload";
@@ -728,6 +732,353 @@ test("a version is deleted from its page, and is then not found", async () => {
   await expect(page.getByRole("heading", { name: "Nothing found" })).toBeVisible();
 });
 
+test("the pages of the account are reached from the user menu, and lead to each other", async () => {
+  await page.goto("/");
+  await page.getByRole("button", { name: /^Account of/ }).click();
+  await page.getByRole("menuitem", { name: "Account" }).click();
+
+  await expect(page).toHaveURL(/\/account\/tokens$/);
+  await expect(page.getByRole("heading", { level: 1, name: "API tokens" })).toBeVisible();
+  await expect(page).toHaveTitle("API tokens · MegooArti");
+  const account = page.getByRole("navigation", { name: "Account" });
+  await expect(account.getByRole("link", { name: "API tokens" })).toHaveAttribute(
+    "aria-current",
+    "page",
+  );
+  await account.getByRole("link", { name: "Password" }).click();
+  await expect(page.getByRole("heading", { level: 1, name: "Change password" })).toBeVisible();
+  await page
+    .getByRole("navigation", { name: "Account" })
+    .getByRole("link", { name: "Preferences" })
+    .click();
+  await expect(page.getByRole("heading", { level: 1, name: "Preferences" })).toBeVisible();
+  await expect(page).toHaveTitle("Preferences · MegooArti");
+});
+
+test("the / key can be turned off, and stays off", async () => {
+  const key = page.getByRole("checkbox", { name: "Go to the search box with the / key" });
+  const box = page.getByRole("searchbox", { name: "Search components" });
+  await expect(key).toBeChecked();
+
+  await key.uncheck();
+  await page.getByRole("heading", { level: 1 }).click();
+  await page.keyboard.press("/");
+  await expect(box).not.toBeFocused();
+  await expect(box).toHaveAttribute("placeholder", "Search"); // it no longer names a key
+
+  // Kept in this browser: a reload does not turn it on again.
+  await page.reload();
+  await expect(key).not.toBeChecked();
+  await page.getByRole("heading", { level: 1 }).click();
+  await page.keyboard.press("/");
+  await expect(box).not.toBeFocused();
+
+  await key.check();
+  await page.getByRole("heading", { level: 1 }).click();
+  await page.keyboard.press("/");
+  await expect(box).toBeFocused();
+});
+
+test("the preferences screen meets WCAG 2.1 AA in both modes", async () => {
+  await expectAccessibleInBothModes();
+});
+
+test("a token is made for a build, shown once, does what it was limited to, and is revoked", async ({
+  playwright,
+  baseURL,
+}) => {
+  await page.goto("/account/tokens");
+  await page.getByLabel("Name", { exact: true }).fill(TOKEN);
+  await page.getByRole("radio", { name: "Only read" }).check();
+  await page.getByRole("button", { name: "Create token" }).click();
+
+  const made = page.getByRole("region", { name: `The token ${TOKEN} is made` });
+  await expect(made.getByRole("heading")).toBeFocused();
+  const secret = (await made.locator("code").textContent()) ?? "";
+  expect(secret).toMatch(/^mga_/);
+  await made.getByRole("button", { name: "Copy the token" }).click();
+  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(secret);
+
+  // The token signs in for its owner, and may only read.
+  const build = await playwright.request.newContext({
+    baseURL,
+    extraHTTPHeaders: { Authorization: `Bearer ${secret}` },
+  });
+  expect((await build.get("/api/v1/content")).status()).toBe(200);
+  const refused = await build.post(`/api/v1/content/${REPOSITORY}/upload`, {
+    multipart: { file: { name: "t.txt", mimeType: "text/plain", buffer: Buffer.from("x") } },
+  });
+  expect(refused.status()).toBe(403);
+
+  // Once the panel is closed the secret is nowhere on the page, and cannot be had again.
+  await made.getByRole("button", { name: "I have copied it" }).click();
+  await expect(page.getByRole("heading", { name: "Your tokens" })).toBeFocused();
+  await expect(page.getByRole("main")).not.toContainText(secret);
+  const row = page.getByRole("row", { name: new RegExp(TOKEN) });
+  await expect(row).toContainText("repository:*:*:read");
+  await expect(row).toContainText(`${secret.slice(0, 8)}…`);
+
+  await row.getByRole("button", { name: `Revoke ${TOKEN}` }).click();
+  await page.getByRole("alertdialog").getByRole("button", { name: "Revoke" }).click();
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    `Revoked the token ${TOKEN}.`,
+  );
+  await expect(page.getByText("You have no token.")).toBeVisible();
+  expect((await build.get("/api/v1/content")).status()).toBe(401);
+  await build.dispose();
+});
+
+test("the tokens screen meets WCAG 2.1 AA in both modes", async () => {
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByText("You have no token.")).toBeVisible();
+  });
+});
+
+test("the administration is in the navigation, in a row that nothing lies over", async () => {
+  const main = page.getByRole("navigation", { name: "Main" });
+  const overlaps = async () => {
+    const [row, box] = await Promise.all([
+      main.boundingBox(),
+      page.getByRole("search", { name: "Search components" }).boundingBox(),
+    ]);
+    if (row === null || box === null) return true;
+    return !(box.y + box.height <= row.y || row.y + row.height <= box.y);
+  };
+  // At the narrowest width that shows the navigation at all, and at a usual one.
+  for (const width of [1024, 1280]) {
+    await page.setViewportSize({ width, height: 720 });
+    await expect(main.getByRole("link", { name: "Anonymous access" })).toBeVisible();
+    expect(await overlaps()).toBe(false);
+    const overflow = await page.evaluate(
+      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
+    );
+    expect(overflow).toBeLessThanOrEqual(0);
+  }
+
+  await main.getByRole("link", { name: "Roles" }).click();
+  await expect(page).toHaveURL(/\/admin\/roles$/);
+  await expect(page.getByRole("heading", { level: 1, name: "Roles" })).toBeVisible();
+  await expect(page).toHaveTitle("Roles · MegooArti");
+  await expect(main.getByRole("link", { name: "Roles" })).toHaveAttribute("aria-current", "page");
+});
+
+test("a role is written row by row, and opens again as it was saved", async () => {
+  await page.getByRole("link", { name: "New role" }).click();
+  await page.getByLabel("Name", { exact: true }).fill(ROLE);
+  await page.getByLabel("Description").fill("May use the releases");
+  await page.getByRole("button", { name: "Add a permission" }).click();
+  const first = page.getByRole("group", { name: "Permission 1" });
+  // The row that was added has the keyboard.
+  await expect(first.getByLabel("About")).toBeFocused();
+  await first.getByLabel("Format").selectOption("maven");
+  await first.getByLabel("Repository").selectOption(RELEASES);
+  await first.getByLabel("Action").selectOption("*");
+  await expect(first).toContainText(`repository:maven:${RELEASES}:*`);
+  await expect(first).toContainText(`Everything in the maven repository ${RELEASES}.`);
+  // What the lists cannot say is typed by hand.
+  await page.getByRole("button", { name: "Add a permission" }).click();
+  const second = page.getByRole("group", { name: "Permission 2" });
+  await second.getByLabel("About").selectOption("typed");
+  await second.getByLabel("Pattern").fill("not a pattern");
+  await page.getByRole("button", { name: "Create role" }).click();
+  // Not saved while a row is no pattern: the keyboard is at it.
+  await expect(second.getByLabel("Pattern")).toBeFocused();
+  await expect(second.getByLabel("Pattern")).toHaveAttribute("aria-invalid", "true");
+  await second.getByLabel("Pattern").fill("repository:raw");
+  await page.getByRole("button", { name: "Create role" }).click();
+
+  await expect(page).toHaveURL(new RegExp(`/admin/roles/${ROLE}$`));
+  await expect(page.getByRole("heading", { level: 1, name: ROLE })).toBeVisible();
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    `Created the role ${ROLE}.`,
+  );
+
+  // Asked of the server again, it is what was written: the lists, and what was typed.
+  await page.reload();
+  const rows = page.getByRole("group", { name: /^Permission \d$/ });
+  await expect(rows).toHaveCount(2);
+  await expect(rows.filter({ hasText: `repository:maven:${RELEASES}:*` })).toHaveCount(1);
+  await expect(rows.getByLabel("Pattern")).toHaveValue("repository:raw");
+});
+
+test("the role screen meets WCAG 2.1 AA in both modes", async () => {
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByRole("group", { name: "Permission 2" })).toBeVisible();
+  });
+});
+
+test("a user is made with a generated password, signs in with it, and may do what the role says", async ({
+  browser,
+  baseURL,
+}) => {
+  await page.goto("/admin/users");
+  await expect(page).toHaveTitle("Users · MegooArti");
+  await page.getByRole("link", { name: "New user" }).click();
+  await page.getByLabel("User name").fill(ALICE);
+  await page.getByLabel("Name", { exact: true }).fill("Alice Example");
+  await page.getByRole("button", { name: "Generate one" }).click();
+  const generated = await page.getByLabel("Password", { exact: true }).inputValue();
+  expect(generated).toMatch(/^[A-HJ-NP-Za-km-z2-9]{20}$/);
+  await page.getByRole("checkbox", { name: ROLE }).check();
+  await page.getByRole("button", { name: "Create user" }).click();
+
+  const created = page.getByRole("region", { name: `The user ${ALICE} is created` });
+  await expect(created.getByRole("heading")).toBeFocused();
+  await expect(created.locator("code")).toHaveText(generated);
+
+  // In a browser of her own: the password works once, and she then chooses her own.
+  const hers = await browser.newContext({ baseURL, colorScheme: "dark" });
+  const alice = await hers.newPage();
+  await alice.goto("/login");
+  await alice.getByLabel("User name").fill(ALICE);
+  await alice.getByLabel("Password").fill(generated);
+  await alice.getByRole("button", { name: "Sign in" }).click();
+  await expect(
+    alice.getByRole("heading", { level: 1, name: "Choose a new password" }),
+  ).toBeVisible();
+  await alice.getByLabel("Current password").fill(generated);
+  await alice.getByLabel("New password", { exact: true }).fill(HER_PASSWORD);
+  await alice.getByLabel("New password, again").fill(HER_PASSWORD);
+  await alice.getByRole("button", { name: "Change password" }).click();
+  await expect(alice.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
+
+  // She sees what her role grants (the repository chosen from the lists, and the raw ones
+  // of the row typed by hand) and no other, may upload, and administers nothing.
+  await expect(alice.getByRole("link", { name: RELEASES, exact: true })).toBeVisible();
+  await expect(alice.getByRole("link", { name: REPOSITORY, exact: true })).toBeVisible();
+  await expect(alice.getByRole("link", { name: IMAGES, exact: true })).toHaveCount(0);
+  const navigation = alice.getByRole("navigation", { name: "Main" });
+  await expect(navigation.getByRole("link", { name: "Upload" })).toBeVisible();
+  await expect(navigation.getByRole("link", { name: "Users" })).toHaveCount(0);
+  await expect(navigation.getByText("Administration")).toHaveCount(0);
+  // The address typed by hand says no, as the API does.
+  await alice.goto("/admin/users");
+  await expect(alice.getByRole("main").getByRole("alert")).toContainText(
+    "You do not have permission to do this.",
+  );
+  await hers.close();
+
+  await created.getByRole("link", { name: `Open ${ALICE}` }).click();
+  await expect(page.getByRole("heading", { level: 1, name: ALICE })).toBeVisible();
+  await expect(page.getByRole("checkbox", { name: ROLE })).toBeChecked();
+});
+
+test("the user screen meets WCAG 2.1 AA in both modes", async () => {
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByRole("checkbox", { name: ROLE })).toBeChecked();
+  });
+});
+
+test("a user who is disabled cannot sign in, and is deleted only by whoever types their name", async ({
+  browser,
+  baseURL,
+}) => {
+  await page.getByRole("radio", { name: "Disabled" }).check();
+  await page.getByRole("button", { name: "Save" }).click();
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    `Saved ${ALICE}.`,
+  );
+  await expect(page.getByRole("button", { name: "Save" })).toBeFocused();
+
+  const hers = await browser.newContext({ baseURL });
+  const alice = await hers.newPage();
+  await alice.goto("/login");
+  await alice.getByLabel("User name").fill(ALICE);
+  await alice.getByLabel("Password").fill(HER_PASSWORD);
+  await alice.getByRole("button", { name: "Sign in" }).click();
+  await expect(alice.locator("form").getByRole("alert")).toBeVisible();
+  await expect(alice).toHaveURL(/\/login$/);
+  await hers.close();
+
+  await page.getByRole("button", { name: "Delete user" }).click();
+  const dialog = page.getByRole("alertdialog", { name: `Delete the user ${ALICE}?` });
+  const confirm = dialog.getByRole("button", { name: "Delete user" });
+  await expect(confirm).toBeDisabled();
+  await dialog.getByLabel(`Type ${ALICE} to go on`).fill(ALICE);
+  await confirm.click();
+
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    `Deleted the user ${ALICE}.`,
+  );
+  await expect(page).toHaveURL(/\/admin\/users$/);
+  await expect(page.getByRole("table", { name: "Users" })).toBeVisible();
+  await expect(page.getByRole("link", { name: ALICE, exact: true })).toHaveCount(0);
+  // The users that are built in are there, and one's own account cannot be deleted.
+  await page.getByRole("link", { name: "admin", exact: true }).click();
+  await expect(page.getByText("This is your own account: you cannot delete it.")).toBeVisible();
+  await expect(page.getByRole("button", { name: "Delete user" })).toHaveCount(0);
+});
+
+test("a role is deleted after asking, and the one that makes an administrator is changed by nobody", async () => {
+  await page.goto(`/admin/roles/${ROLE}`);
+  await page.getByRole("button", { name: "Delete role" }).click();
+  const dialog = page.getByRole("alertdialog", { name: `Delete the role ${ROLE}?` });
+  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
+  await dialog.getByRole("button", { name: "Delete role" }).click();
+
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    `Deleted the role ${ROLE}.`,
+  );
+  await expect(page).toHaveURL(/\/admin\/roles$/);
+  await expect(page.getByRole("link", { name: ROLE, exact: true })).toHaveCount(0);
+
+  await page.getByRole("link", { name: "admin", exact: true }).click();
+  await expect(page.getByText("It grants everything, and cannot be changed.")).toBeVisible();
+  await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
+  await expect(page.getByRole("button", { name: "Delete role" })).toHaveCount(0);
+});
+
+test("anonymous access is turned on only after asking, and the page says what a visitor may do", async ({
+  browser,
+  baseURL,
+}) => {
+  await page
+    .getByRole("navigation", { name: "Main" })
+    .getByRole("link", { name: "Anonymous access" })
+    .click();
+  await expect(page.getByRole("heading", { level: 1, name: "Anonymous access" })).toBeVisible();
+  await expect(page.getByText("Off", { exact: true })).toBeVisible();
+  await expect(page.getByText("Read in every repository.")).toBeVisible();
+  await expect(page.getByRole("link", { name: "Change its roles" })).toBeVisible();
+  const visits = async () => {
+    const fresh = await browser.newContext({ baseURL });
+    const visitor = await fresh.newPage();
+    await visitor.goto("/");
+    await expect(visitor.getByRole("heading", { level: 1 })).toBeVisible();
+    const where = new URL(visitor.url()).pathname;
+    await fresh.close();
+    return where;
+  };
+  expect(await visits()).toBe("/login");
+
+  const turnOn = page.getByRole("button", { name: "Turn on" });
+  await turnOn.click();
+  const dialog = page.getByRole("alertdialog", { name: "Turn anonymous access on?" });
+  await expect(dialog).toContainText("Anyone who can reach this server");
+  // Asked, and answered no: it stays off.
+  await dialog.getByRole("button", { name: "Cancel" }).click();
+  await expect(turnOn).toBeFocused();
+  expect(await visits()).toBe("/login");
+
+  await turnOn.click();
+  await dialog.getByRole("button", { name: "Turn on" }).click();
+  await expect(page.getByText("On", { exact: true })).toBeVisible();
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    "Anonymous access is on.",
+  );
+  expect(await visits()).toBe("/");
+
+  await page.getByRole("button", { name: "Turn off" }).click();
+  await expect(page.getByText("Off", { exact: true })).toBeVisible();
+  expect(await visits()).toBe("/login");
+});
+
+test("the anonymous access screen meets WCAG 2.1 AA in both modes", async () => {
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByText("Read in every repository.")).toBeVisible();
+  });
+});
+
 test("an upload refused because the session was replaced in another tab goes through at the next try", async () => {
   await page.goto(`/upload/${REPOSITORY}`);
   await page.getByLabel("Files", { exact: true }).setInputFiles({
```

Change `backend/tests/test_ui_client.py`:

```diff
@@ -98,7 +98,7 @@ def test_the_ui_in_a_real_browser(stack):
     said = f"exit {result.returncode}\n{result.stdout[-6000:]}\n{result.stderr[-2000:]}"
     assert result.returncode == 0, said
     passed = re.search(r"(\d+) passed", result.stdout)
-    assert passed is not None and int(passed[1]) >= 37, said
+    assert passed is not None and int(passed[1]) >= 51, said
     assert not re.search(r"\d+ (failed|skipped|did not run)", result.stdout), said
 
 
```

- [ ] **Step 2: Run them**

Run (in `backend/`): `uv run pytest -m docker tests/test_ui_client.py -q`
Expected: 11 passed. Should the browser test fail, what Playwright said is in the failure.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e backend/tests/test_ui_client.py
git commit -m "test(frontend): the account and security screens in a real browser"
```

- [ ] **Step 4: Bring the documents up to date**

Change `README.md`:

```diff
@@ -92,6 +92,9 @@ anything must send it in an `X-CSRF-Token` header.
 
 ## Access control
 
+Users, roles, your own API tokens and anonymous access are managed in the web UI
+(Administration, and Account under your name) or through the API, as below.
+
 - **Roles** hold permission patterns such as `admin:users:*` or
   `repository:maven:releases:read`. `*` matches one segment, and a pattern shorter than
   the permission grants everything beneath it, so `repository:maven` covers every Maven
@@ -864,9 +867,9 @@ curl -u alice 'https://repo.example.com/api/v1/search?sha1=2ef7bde608ce5404e97d5
 ## The web UI
 
 The UI is at the root of the installation's address. It has what a person who uses
-the repositories needs: browsing them, search, upload and delete. Administration
-(users, roles, repositories, blob stores) is done through the API for now, and its
-screens follow.
+the repositories needs (browsing them, search, upload and delete), a person's own
+account, and the administration of users, roles and anonymous access. Repositories
+and blob stores are created through the API for now, and their screens follow.
 
 - **Browsing.** A repository opens one folder at a time, with the way there as a path
   above it. Choosing a file shows everything known of it beside the folder: its size,
@@ -895,6 +898,28 @@ screens follow.
 - **What you may not do is not offered.** Without the permission to add there is no
   upload, without the permission to delete no delete. The server decides in every
   case: the screens only leave out what it would refuse.
+- **Your account** is under your name in the header: your API tokens, your password,
+  and your preferences.
+  - **API tokens.** A token gets a name, an expiry (never, 30 days, 90 days, a year,
+    or a day you choose) and a limit: everything you may do, only read, or the
+    permissions you choose. Its secret is shown once, when it is made, with a button
+    that copies it. A token is revoked from the same page.
+  - **Preferences** are kept in the browser: the mode, and whether `/` goes to the
+    search box. They are reached from the mode menu too, by a visitor as well.
+- **Administration** is shown to whoever holds the permission to read each part.
+  - **Users.** Create a user with a password you type or have generated, and tick
+    the roles they hold. A user's page changes their name, email, roles and state,
+    sets a new password, lists and revokes their API tokens, and deletes them after
+    you type their name. Your own account cannot be disabled or deleted there, and a
+    built-in user cannot be deleted.
+  - **Roles.** A role's permissions are rows: choose what a row is about (a
+    repository, or an area of administration), then the format, repository and
+    action from lists. The pattern the row makes is shown with what it grants in
+    words. A pattern the lists cannot make is typed by hand, and a role that was
+    written through the API opens with nothing lost. The `admin` role is shown and
+    cannot be changed.
+  - **Anonymous access** is one switch, which asks before it is turned on, and shows
+    what someone who is not signed in may then do.
 - **Signing in** uses the session cookie the API sets. It is marked `Secure`, so a
   browser keeps it over HTTPS, and over plain HTTP only on the machine itself
   (`localhost`). If you reach the UI over plain HTTP at another name or address,
@@ -911,8 +936,8 @@ screens follow.
   with a link that skips to its content, and meets WCAG 2.1 AA contrast in both modes.
   When a screen changes under the keyboard (a folder is entered, a file is deleted,
   another page of results is shown), the keyboard is put at what changed. `/` reaches
-  the search box from anywhere that is not a place to type; it cannot be turned off
-  yet.
+  the search box from anywhere that is not a place to type, and can be turned off
+  under Preferences.
 
 ## Behind your own reverse proxy
 
```

Change `docs/superpowers/specs/2026-10-12-frontend-design.md`:

```diff
@@ -107,10 +107,10 @@ The values above are those of `frontend/src/styles/tokens.css`, which is the aut
 
 ## 6. The shell
 
-- **Header:** the wordmark, the navigation, and at its end the mode switch and the user menu (or "Sign in").
+- **Header:** the wordmark, and at its end the search box, the mode switch and the user menu (or "Sign in"). From 1024 pixels the navigation is a row of its own under them, which wraps where its items do not fit in one line (plan 10b, A14).
 - **Navigation:** two areas, browsing and administration, each a list of items from the registry (D11). An area with no visible item is not shown. Below 1024 pixels the navigation is behind a menu button.
 - **A skip link** is the first thing focus reaches, and leads to the main content.
-- **The user menu:** the user's name, "Change password", and "Sign out".
+- **The user menu:** the user's name, "Account" (plan 10b; it was "Change password"), and "Sign out".
 - **States:** a screen that is loading shows a skeleton of itself; one with nothing to show says so and what to do; one that failed shows the error (D15) and a way to try again.
 
 Plan 9 registers one item, the home screen. Plan 10 registers the rest.
@@ -309,6 +309,18 @@ A person's own account, and what an administrator does about people: users, role
 - **A screen whose data the caller may not read** says so (the API's `403`), as every screen does. A form whose data they may read but not change is shown with its fields and without the button that saves.
 - **The areas of administration** the rows know are those the API has: users, roles, tokens, settings, blob stores, repositories. The actions on a repository are browse, read, add, edit, delete.
 
+#### Settled while building plan 10b
+
+| # | What | Why |
+| --- | --- | --- |
+| A14 | In a wide window the navigation is a row of its own in the header, under the wordmark and the search box, and wraps where it does not fit. | With the administration's three items beside the browsing ones, the navigation ran under the search box, which then took the clicks meant for "Roles". Plan 10c adds more. A sidebar is the other way to do it, and is put to the product owner. |
+| A15 | Whether an element is on the screen is asked of the browser in one place (`lib/browser.ts`), where a test can stand in for it. | A12 needs it, and the test environment lays nothing out. |
+| A16 | The rows of a role keep to themselves once they are shown: a pattern typed by hand stays a typed row, though it becomes one the lists could say. | Otherwise the field would turn into lists under the hands that are typing in it. |
+| A17 | A row that is added gets the keyboard. Where a thing that had the keyboard goes (a row removed, a token revoked, the panel of a token or a user that was just made), the keyboard is put at what is nearest to it: the button that adds, the list of tokens, the form's first field. | B11 of plan 10a, kept to. |
+| A18 | A new user's password is shown once more after the user is made, with a button that copies it, until the page is left. A password set for an existing user stays in its field for the same reason. | The administrator has to pass it on, and may not have copied it before pressing the button. |
+| A19 | What a visitor may do is shown as the patterns of the anonymous user's roles and of the roles they contain, and of those only what concerns repositories. | The server allows a request without credentials nothing else, whatever the roles say. |
+| A20 | A token's secret is not kept by the store of what was fetched: the request that makes it is forgotten as soon as its answer is handed over. | A5. |
+
 ### 12.4 Repositories and the system (plan 10c, outline)
 
 Repositories (create and edit as S13 says, delete, invalidate a proxy's cache, rebuild an index). Blob stores (create, delete, what they hold). The base URL. System information: the version, the schema's revision and the blob stores' state, which needs a small addition to the API.
```

- [ ] **Step 5: Run everything**

Run: `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: no finding, 656 passed, `Compiled successfully`.

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: no finding; 2756 passed, 1 skipped.

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: 35 passed.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-12-frontend-design.md
git commit -m "docs: the account and security screens of the web UI"
```
