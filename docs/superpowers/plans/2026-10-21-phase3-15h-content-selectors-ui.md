# External Identity: Content Selectors in the Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An administrator keeps content selectors in the web UI, trying each expression against paths before trusting it. The role editor, and a token's custom permissions, offer selector permissions as rows chosen from lists.

**Architecture:**
- **Data.** `lib/selectors.ts` holds the API's hooks for 15g's routes.
- **Screens.** `screens/content-selectors.tsx` holds the list, the new and the one-selector screens, as the roles' screens are built, with a preview panel that posts the expression as typed. Pages live under `/admin/content-selectors`, and the navigation gains Content selectors.
- **The role editor.** `lib/patterns.ts` gains a `selector` row, and `components/permission-rows.tsx` lays it out and says it in words, with the selector chosen from the names `useSelectorNames()` gives.

**Tech Stack:** Next.js (app router), React, TanStack Query, next-intl, Vitest with Testing Library and axe.

**Spec:** [docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md](../specs/2026-10-19-identity-audit-selectors-design.md): section 10 (the screens, 15h), the row of plan 15h in 13, and the "Settled while building plan 15g" table (G1–G15).

## Decisions this plan settles

Task 2 writes these into the spec, as "Settled while building plan 15h".

| # | Decision | Reason |
| --- | --- | --- |
| U1 | The screens are Administration, Content selectors, after Roles, with `admin:selectors:read`: the list at `/admin/content-selectors`, a new one at `/admin/content-selectors/~new` (a selector may be called `new`), one at `/admin/content-selectors/<name>`. A selector is made with a name of the server's rule, said before it is sent, a description and an expression; changed on its page; deleted after a question, and one a role names says which (`409 in_use`). Whoever may only read sees each, and tries it. | Section 10: the screens (15h); as the roles' screens are. |
| U2 | An expression is tried as it is typed, against paths a line each (at most 100) in a repository of a format (Maven unless chosen), and each path is said to match or not; nothing is kept. What the server finds wrong with the expression, saving or trying it, is said at the expression, with its character. | Section 10: a preview against paths. |
| U3 | A role's row, and a token's, may be about some of a repository: `selector:<selector>:<format>:<repository>:<action>`, the selector chosen from those there are (read only by whoever holds `admin:selectors:read`; to others, the one a row holds and Any), then the format, the repository and the action as a repository's row, and said in words (`Add in the maven repository releases, where the content selector acme matches.`). A shorter or another shape is a typed row, kept as it is. The administration areas gain `selectors`. | Section 10: the role editor's rows offer selector permissions. |
| U4 | What else the web UI offers by permission stays by repository permissions: Upload in the navigation, the repositories the upload screen offers, and the browse screens' delete buttons. Whoever holds only selector permissions does those through package clients, the API or MCP. | Section 10 names the screens of 15h only; each of those is its own change. |

## Global Constraints

- **The screens (15h): Content selectors, with a preview against paths; the role editor's rows offer selector permissions** (section 10).
- **A permission `selector:<selector>:<format>:<repository>:<action>` (each part `*` allowed; the actions are the repository permission's)** (section 10).
- **`admin:selectors:read` and `write`; a selector a role names cannot be deleted** (section 10). **An expression that does not parse is refused at its field, saying where** (section 10).
- **Every new list is paged** (API-5). Nothing a role holds is lost by opening it (A3).
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `pnpm` commands in `frontend/`, `uv` and `pytest` commands in `backend/` (with `MEGOOARTI_TEST_DATABASE_URL` set to your test database), and `git` commands in the repository root.

## Review Focus

These are the failures that would hurt a person using this most, each with the test in this plan that pins it.

1. **A role naming a selector that is gone, or that the editor cannot read.** It opens with that selector kept, and is saved unchanged. Pinned by Task 2's `a selector's row gives an action where a content selector matches (spec 10)` (the `gone` row).
2. **An expression that does not parse.** The person learns where at the field, whether they saved it or only tried it. Pinned by Task 1's `say what is wrong with an expression where the server says it is` and `say at the expression why trying it was refused`.
3. **A selector a role names, deleted.** The deletion is refused, and the roles that name it are said. Pinned by Task 1's `are deleted after a question, and one a role names says so`.
4. **A selector's shape the rows cannot say** (`selector:acme`, an action the UI does not know). It stays a typed row, kept as written. Pinned by Task 2's `%s is of no shape a row has, and stays as it was typed`.
5. **Whoever may only read selectors.** They see each one and try it, and are offered nothing that would be refused. Pinned by Task 1's `are shown and tried, and not changed, by whoever may only read them` and `say so when there is none, and offer no new one to whoever may only read`.

---

### Task 1: The Content selectors screens

**Files:**
- Create:
  - `frontend/src/lib/selectors.ts` and `frontend/src/screens/content-selectors.tsx`.
  - The pages `frontend/src/app/(shell)/admin/content-selectors/page.tsx`, `.../[name]/page.tsx` and `.../~new/page.tsx`.
- Modify:
  - `frontend/src/lib/api/types.ts`, `frontend/src/lib/paths.ts`, `frontend/src/lib/navigation.ts`.
  - `frontend/src/components/permission-rows.tsx` (`FORMATS` exported).
  - `frontend/messages/en.json`.
- Test: `frontend/src/screens/content-selectors.test.tsx`; modify `frontend/src/components/shell.test.tsx`, `frontend/src/lib/navigation.test.ts`

**Interfaces:**
- Consumes:
  - 15g's routes `GET`/`POST /content-selectors`, `GET`/`PUT`/`DELETE /content-selectors/{name}` and `POST /content-selectors/preview`, through `schema.d.ts`.
  - The roles screens' parts: `PageHeader`, `Panel`, `Table`, `Pager`, `Breadcrumbs`, `ConfirmDialog`, `TextField`, `TextAreaField`, `SelectField`, `refusalsOf`, `useAttempts`, `usePageFocus`, `useWithinPages`, `isAddressable`.
- Produces:
  - Types: `SelectorOut`, `SelectorCreate`, `SelectorContent`, `Preview`, `PreviewOut`.
  - Paths: `CONTENT_SELECTORS`, `NEW_SELECTOR`, `selectorHref(name)`, `parseSelector(pathname)`.
  - Hooks: `useSelectors(page)`, `useEverySelector(enabled)`, `useSelector(name)`, `useCreateSelector()`, `useUpdateSelector(name)`, `useDeleteSelector()`, `usePreview()`.
  - Screens: `SelectorsScreen`, `NewSelectorScreen`, `SelectorScreen`.
  - `FORMATS` (exported from `permission-rows.tsx`), the navigation item `contentSelectors`, and the messages `selectors.*`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/screens/content-selectors.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { NewSelectorScreen, SelectorScreen, SelectorsScreen } from "./content-selectors";

const page = (items: unknown[]) => ({ items, total: items.length, limit: 50, offset: 0 });
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });

const ACME = {
  id: "s1",
  name: "acme",
  description: "Acme's own",
  expression: 'path =^ "/com/acme/"',
  created_at: "2026-10-21T08:00:00Z",
  updated_at: "2026-10-21T08:00:00Z",
};

function render(screenOf: ReactElement, address: string, routes: Routes, session = ADMIN) {
  const api = mockApi(routes);
  navigation.at(address);
  return { ...renderUi(screenOf, { session }), ...api };
}

describe("the content selectors (spec 10)", () => {
  test("are listed with what each matches, each leading to its page", async () => {
    render(<SelectorsScreen />, "/admin/content-selectors", {
      "GET /content-selectors": { json: page([ACME]) },
    });

    const table = await screen.findByRole("table", { name: "Content selectors" });
    const row = within(table).getAllByRole("row")[1] as HTMLElement;
    expect(within(row).getByRole("link", { name: "acme" })).toHaveAttribute(
      "href",
      "/admin/content-selectors/acme",
    );
    expect(row).toHaveTextContent('path =^ "/com/acme/"');
    expect(screen.getByRole("link", { name: "New content selector" })).toBeVisible();
    await expectAccessible();
  });

  test("say so when there is none, and offer no new one to whoever may only read", async () => {
    render(
      <SelectorsScreen />,
      "/admin/content-selectors",
      { "GET /content-selectors": { json: page([]) } },
      holding("admin:selectors:read"),
    );

    expect(await screen.findByText(/No content selector is made yet/)).toBeVisible();
    expect(screen.queryByRole("link", { name: "New content selector" })).toBeNull();
  });

  test("are made with a name, a description and an expression", async () => {
    const user = userEvent.setup();
    const { calls } = render(<NewSelectorScreen />, "/admin/content-selectors/~new", {
      "POST /content-selectors": (call) => ({
        status: 201,
        json: { ...ACME, ...(call.body as object) },
      }),
    });

    await user.type(screen.getByLabelText(/^Name/), "acme");
    await user.type(screen.getByLabelText("Description"), "Acme's own");
    await user.type(screen.getByLabelText(/^Expression/), 'path =^ "/com/acme/"');
    await user.click(screen.getByRole("button", { name: "Create content selector" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Created the content selector acme."));
    expect(of(calls, "POST")[0]?.body).toEqual({
      name: "acme",
      description: "Acme's own",
      expression: 'path =^ "/com/acme/"',
    });
    expect(navigation.router.push).toHaveBeenCalledWith("/admin/content-selectors/acme");
  });

  test("say what is wrong with an expression where the server says it is", async () => {
    const user = userEvent.setup();
    render(<NewSelectorScreen />, "/admin/content-selectors/~new", {
      "POST /content-selectors": failure(422, "validation_error", "The request is not valid.", [
        { field: "expression", message: "Unexpected '=' (at character 6)" },
      ]),
    });

    await user.type(screen.getByLabelText(/^Name/), "acme");
    const expression = screen.getByLabelText(/^Expression/);
    await user.type(expression, 'path = "/com/"');
    await user.click(screen.getByRole("button", { name: "Create content selector" }));

    await waitFor(() =>
      expect(expression).toHaveAccessibleDescription(/Unexpected '=' \(at character 6\)/),
    );
  });

  test("need a name of the server's rule and an expression before anything is sent", async () => {
    const user = userEvent.setup();
    const { calls } = render(<NewSelectorScreen />, "/admin/content-selectors/~new", {});

    await user.type(screen.getByLabelText(/^Name/), "with space");
    await user.click(screen.getByRole("button", { name: "Create content selector" }));

    expect(screen.getByLabelText(/^Name/)).toHaveAccessibleDescription(/1 to 64 letters/);
    expect(screen.getByLabelText(/^Expression/)).toHaveAccessibleDescription(
      /An expression is needed/,
    );
    expect(of(calls, "POST")).toHaveLength(0);
  });

  test("are tried against paths before they are saved, and say which match", async () => {
    const user = userEvent.setup();
    const { calls } = render(<NewSelectorScreen />, "/admin/content-selectors/~new", {
      "POST /content-selectors/preview": {
        json: {
          paths: [
            { path: "/com/acme/app/1.0/app-1.0.jar", matches: true },
            { path: "/org/other/1.0/other-1.0.jar", matches: false },
          ],
        },
      },
    });

    await user.type(screen.getByLabelText(/^Expression/), 'path =^ "/com/acme/"');
    await user.type(
      screen.getByLabelText(/^Paths to try/),
      "/com/acme/app/1.0/app-1.0.jar{Enter}{Enter}/org/other/1.0/other-1.0.jar",
    );
    await user.click(screen.getByRole("button", { name: "Try the expression" }));

    const tried = await screen.findByRole("list", { name: "What the expression matches" });
    const items = within(tried).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Matches/com/acme/app/1.0/app-1.0.jar");
    expect(items[1]).toHaveTextContent("Does not match/org/other/1.0/other-1.0.jar");
    expect(of(calls, "POST")[0]?.body).toEqual({
      expression: 'path =^ "/com/acme/"',
      format: "maven",
      paths: ["/com/acme/app/1.0/app-1.0.jar", "/org/other/1.0/other-1.0.jar"],
    });
    expect(of(calls, "POST").map((call) => call.path)).toEqual(["/content-selectors/preview"]);
    await expectAccessible();
  });

  test("say at the expression why trying it was refused", async () => {
    const user = userEvent.setup();
    render(<NewSelectorScreen />, "/admin/content-selectors/~new", {
      "POST /content-selectors/preview": failure(422, "validation_error", "Not valid.", [
        { field: "expression", message: "Expected a string in double quotes (at character 9)" },
      ]),
    });

    const expression = screen.getByLabelText(/^Expression/);
    await user.type(expression, "path == maven");
    await user.type(screen.getByLabelText(/^Paths to try/), "/x");
    await user.click(screen.getByRole("button", { name: "Try the expression" }));

    await waitFor(() => expect(expression).toHaveAccessibleDescription(/at character 9/));
  });

  test("are changed on their page, and kept there", async () => {
    const user = userEvent.setup();
    const { calls } = render(<SelectorScreen />, "/admin/content-selectors/acme", {
      "GET /content-selectors/acme": { json: ACME },
      "PUT /content-selectors/acme": (call) => ({ json: { ...ACME, ...(call.body as object) } }),
    });

    const expression = await screen.findByLabelText(/^Expression/);
    expect(expression).toHaveValue('path =^ "/com/acme/"');
    await user.clear(expression);
    await user.type(expression, 'path =^ "/com/"');
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Saved the content selector acme."));
    expect(of(calls, "PUT")[0]?.body).toEqual({
      description: "Acme's own",
      expression: 'path =^ "/com/"',
    });
  });

  test("are shown and tried, and not changed, by whoever may only read them", async () => {
    render(
      <SelectorScreen />,
      "/admin/content-selectors/acme",
      { "GET /content-selectors/acme": { json: ACME } },
      holding("admin:selectors:read"),
    );

    expect(await screen.findByText('path =^ "/com/acme/"')).toBeVisible();
    expect(screen.getByRole("button", { name: "Try the expression" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete content selector" })).toBeNull();
  });

  test("are deleted after a question, and one a role names says so", async () => {
    const user = userEvent.setup();
    let tries = 0;
    render(<SelectorScreen />, "/admin/content-selectors/acme", {
      "GET /content-selectors/acme": { json: ACME },
      "DELETE /content-selectors/acme": () =>
        ++tries === 1
          ? failure(409, "in_use", "Roles name this content selector: acme-readers.")
          : { status: 204 },
    });

    await user.click(await screen.findByRole("button", { name: "Delete content selector" }));
    let dialog = screen.getByRole("alertdialog", { name: "Delete the content selector acme?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete content selector" }));
    expect(await screen.findByText(/Roles name this content selector: acme-readers/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Delete content selector" }));
    dialog = screen.getByRole("alertdialog", { name: "Delete the content selector acme?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete content selector" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Deleted the content selector acme."));
    expect(navigation.router.replace).toHaveBeenCalledWith("/admin/content-selectors");
  });
});
```

Change `frontend/src/components/shell.test.tsx`:

```diff
@@ -75,6 +75,7 @@ describe("the shell", () => {
     expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
       ["Users", "/admin/users"],
       ["Roles", "/admin/roles"],
+      ["Content selectors", "/admin/content-selectors"],
       ["Anonymous access", "/admin/anonymous-access"],
       ["Authentication", "/admin/authentication"],
       ["Certificates", "/admin/certificates"],
@@ -95,6 +96,7 @@ describe("the shell", () => {
       null,
       null,
       null,
+      null,
     ]);
   });
 
```

Change `frontend/src/lib/navigation.test.ts`:

```diff
@@ -81,6 +81,7 @@ describe("the navigation as it is", () => {
     expect(administration(ADMIN)).toEqual([
       ["users", "/admin/users"],
       ["roles", "/admin/roles"],
+      ["contentSelectors", "/admin/content-selectors"],
       ["anonymousAccess", "/admin/anonymous-access"],
       ["authentication", "/admin/authentication"],
       ["certificates", "/admin/certificates"],
@@ -93,6 +94,10 @@ describe("the navigation as it is", () => {
     expect(administration({ ...ADMIN, permissions: ["admin:security:read"] })).toEqual([
       ["authentication", "/admin/authentication"],
     ]);
+    // The content selectors are an area of their own (spec 10).
+    expect(administration({ ...ADMIN, permissions: ["admin:selectors:read"] })).toEqual([
+      ["contentSelectors", "/admin/content-selectors"],
+    ]);
     // The audit log is an area of its own (spec 9).
     expect(administration({ ...ADMIN, permissions: ["admin:audit:read"] })).toEqual([
       ["audit", "/admin/audit"],
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `frontend/`): `pnpm vitest run src/screens/content-selectors.test.tsx src/components/shell.test.tsx src/lib/navigation.test.ts`
Expected: `content-selectors.test.tsx` does not load (there is no `./content-selectors` yet); 2 failed, 42 passed: the navigation has no Content selectors.

- [ ] **Step 3: Write the code**

Change `frontend/src/lib/api/types.ts`:

```diff
@@ -29,6 +29,13 @@ export type PasswordReset = Schemas["PasswordReset"];
 export type RoleOut = Schemas["RoleOut"];
 export type RoleCreate = Schemas["RoleCreate"];
 export type RoleContent = Schemas["RoleContent"];
+/** A content selector: an expression of a format and paths that selector permissions name. */
+export type SelectorOut = Schemas["SelectorOut"];
+export type SelectorCreate = Schemas["SelectorCreate"];
+export type SelectorContent = Schemas["SelectorContent"];
+/** An expression tried against paths, and what it matched. */
+export type Preview = Schemas["Preview"];
+export type PreviewOut = Schemas["PreviewOut"];
 export type SettingsOut = Schemas["SettingsOut"];
 /** The default role, and whether MegooArti's own users sign in (spec 4.1). */
 export type SignInSettings = Schemas["SignInSettings"];
```

Change `frontend/src/lib/paths.ts`:

```diff
@@ -22,6 +22,9 @@ export const NEW_USER = "/admin/users/new" as Route;
 export const ROLES = "/admin/roles" as Route;
 // Where no role's name can be: a role may be called "new", and has `~` in no name.
 export const NEW_ROLE = "/admin/roles/~new" as Route;
+export const CONTENT_SELECTORS = "/admin/content-selectors" as Route;
+// As for a role: a selector may be called "new", and has `~` in no name.
+export const NEW_SELECTOR = "/admin/content-selectors/~new" as Route;
 export const ANONYMOUS_ACCESS = "/admin/anonymous-access" as Route;
 export const AUTHENTICATION = "/admin/authentication" as Route;
 // As for a role: a source may be called "new", and has `~` in no id.
@@ -108,6 +111,10 @@ export function roleHref(name: string): Route {
   return `${ROLES}/${encodeURIComponent(name)}` as Route;
 }
 
+export function selectorHref(name: string): Route {
+  return `${CONTENT_SELECTORS}/${encodeURIComponent(name)}` as Route;
+}
+
 /**
  * An address the API gave, if a link may lead to it: one of `http` or `https`. A file's
  * download address is built from the installation's base URL, which is a setting, and
@@ -192,6 +199,12 @@ export function parseRole(pathname: string): { name: string } | null {
   return name === null ? null : { name };
 }
 
+/** The content selector an address is about. */
+export function parseSelector(pathname: string): { name: string } | null {
+  const name = one(pathname, CONTENT_SELECTORS);
+  return name === null ? null : { name };
+}
+
 /** The repository whose settings an address is about. */
 export function parseRepositorySettings(pathname: string): { name: string } | null {
   const name = one(pathname, MANAGE_REPOSITORIES);
```

Create `frontend/src/lib/selectors.ts`:

```ts
"use client";

/**
 * Content selectors (spec 10): the expressions selector permissions name, kept by an
 * administrator, and tried against paths before they are trusted with anything.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  Page,
  Preview,
  PreviewOut,
  SelectorContent,
  SelectorCreate,
  SelectorOut,
} from "@/lib/api/types";

// As many of a list as one page shows (A13).
export const AT_ONCE = 50;
// As many as one request may ask for: the choices of a form.
const EVERY = 200;
const SELECTORS = "content-selectors";

const paged = (page: number) => ({ limit: AT_ONCE, offset: (page - 1) * AT_ONCE });
const one = (name: string) => `/content-selectors/${encodeURIComponent(name)}`;

/** A selector changed what a permission naming it reaches: what roles show may be stale. */
function afterChange(client: QueryClient): Promise<void> {
  return client.invalidateQueries({ queryKey: [SELECTORS] });
}

export function useSelectors(page: number) {
  return useQuery({
    queryKey: [SELECTORS, "list", page],
    queryFn: () => api.get<Page<SelectorOut>>("/content-selectors", { query: paged(page) }),
  });
}

/** The selectors there are, for a form to choose from. `enabled` is false for who may not read them. */
export function useEverySelector(enabled = true) {
  return useQuery({
    queryKey: [SELECTORS, "every"],
    queryFn: () => api.get<Page<SelectorOut>>("/content-selectors", { query: { limit: EVERY } }),
    enabled,
  });
}

export function useSelector(name: string | null) {
  return useQuery({
    queryKey: [SELECTORS, "one", name],
    queryFn: () => api.get<SelectorOut>(one(name ?? "")),
    enabled: name !== null,
  });
}

export function useCreateSelector() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: SelectorCreate) => api.post<SelectorOut>("/content-selectors", wanted),
    onSuccess: () => afterChange(client),
  });
}

export function useUpdateSelector(name: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (content: SelectorContent) => api.put<SelectorOut>(one(name), content),
    onSuccess: () => afterChange(client),
  });
}

export function useDeleteSelector() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.delete<void>(one(name)),
    onSuccess: (_, name) => {
      client.removeQueries({ queryKey: [SELECTORS, "one", name] });
      return afterChange(client);
    },
  });
}

/** Which of some paths an expression matches, in a repository of a format. Keeps nothing. */
export function usePreview() {
  return useMutation({
    mutationFn: (asked: Preview) => api.post<PreviewOut>("/content-selectors/preview", asked),
  });
}
```

Change `frontend/src/lib/navigation.ts`:

```diff
@@ -5,6 +5,7 @@
 import {
   BadgeCheck,
   Boxes,
+  Filter,
   HardDrive,
   KeyRound,
   ScrollText,
@@ -26,6 +27,7 @@ import {
   AUTHENTICATION,
   BLOB_STORES,
   CERTIFICATES,
+  CONTENT_SELECTORS,
   MANAGE_REPOSITORIES,
   ROLES,
   SYSTEM,
@@ -40,6 +42,7 @@ export type ItemKey =
   | "upload"
   | "users"
   | "roles"
+  | "contentSelectors"
   | "anonymousAccess"
   | "authentication"
   | "certificates"
@@ -91,6 +94,12 @@ export const NAVIGATION: readonly NavArea[] = [
     items: [
       { key: "users", href: USERS, icon: Users, permission: "admin:users:read" },
       { key: "roles", href: ROLES, icon: ShieldCheck, permission: "admin:roles:read" },
+      {
+        key: "contentSelectors",
+        href: CONTENT_SELECTORS,
+        icon: Filter,
+        permission: "admin:selectors:read",
+      },
       {
         key: "anonymousAccess",
         href: ANONYMOUS_ACCESS,
```

Change `frontend/src/components/permission-rows.tsx`:

```diff
@@ -22,7 +22,7 @@ import {
 
 const KINDS: readonly RowKind[] = ["repository", "admin", "all", "typed"];
 // The formats there are, whether or not a repository of each exists yet.
-const FORMATS = ["raw", "maven", "npm", "pypi", "docker", "apt", "yum", "apk", "nuget"];
+export const FORMATS = ["raw", "maven", "npm", "pypi", "docker", "apt", "yum", "apk", "nuget"];
 
 /** A repository, as far as a permission is concerned: what it is called and its format. */
 export type Held = { name: string; format: string };
```

Create `frontend/src/screens/content-selectors.tsx`:

```tsx
"use client";

import { Check, FlaskConical, Plus, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { FORMATS } from "@/components/permission-rows";
import { Alert, StatusTag } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Pager } from "@/components/ui/details";
import { TextAreaField, TextField } from "@/components/ui/field";
import { SelectField } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { isApiError } from "@/lib/api/client";
import type { SelectorOut } from "@/lib/api/types";
import { useAttempts, usePageFocus, useWithinPages } from "@/lib/focus";
import {
  CONTENT_SELECTORS,
  isAddressable,
  NEW_SELECTOR,
  pageHref,
  pageOf,
  parseSelector,
  selectorHref,
} from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import {
  AT_ONCE,
  useCreateSelector,
  useDeleteSelector,
  usePreview,
  useSelector,
  useSelectors,
  useUpdateSelector,
} from "@/lib/selectors";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

// The server's rule for a selector's name, said before the request is made.
const NAME = /^[A-Za-z0-9_.-]{1,64}$/;
const H2 = "mb-4 text-lg font-semibold text-fg uppercase";
// As many paths as one preview takes.
const MOST_PATHS = 100;

function useMayWrite(): boolean {
  const session = useSession();
  return session.data !== undefined && allows(session.data, "admin:selectors:write");
}

/** The content selectors there are (spec 10): what each is called, and what it matches. */
export function SelectorsScreen() {
  const t = useTranslations("selectors");
  const page = pageOf(useSearchParams());
  const selectors = useSelectors(page);
  const mayWrite = useMayWrite();
  const pages =
    selectors.data === undefined ? undefined : Math.ceil(selectors.data.total / AT_ONCE);
  const hrefFor = (target: number) => pageHref(CONTENT_SELECTORS, target);
  const top = usePageFocus<HTMLDivElement>(page, selectors.data !== undefined);
  const beyond = useWithinPages(page, pages, hrefFor);

  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")}>
        {mayWrite ? (
          <Button asChild variant="primary" size="sm">
            <AppLink href={NEW_SELECTOR}>
              <Plus aria-hidden="true" className="size-4" />
              {t("new")}
            </AppLink>
          </Button>
        ) : null}
      </PageHeader>
      {selectors.isError ? (
        <ErrorState error={selectors.error} onRetry={() => void selectors.refetch()} />
      ) : !selectors.data || beyond ? (
        <Panel>
          <LoadingState />
        </Panel>
      ) : selectors.data.items.length === 0 ? (
        <Panel>
          <p className="p-6 text-fg-muted">{t("none")}</p>
        </Panel>
      ) : (
        <Panel>
          {/* Named, and able to take the keyboard: it is put here when a page is turned. */}
          <div
            ref={top}
            tabIndex={-1}
            role="group"
            aria-label={t("title")}
            className="outline-none"
          >
            <Table caption={t("title")}>
              <thead>
                <tr>
                  <Th>{t("columns.name")}</Th>
                  <Th>{t("columns.description")}</Th>
                  <Th>{t("columns.expression")}</Th>
                </tr>
              </thead>
              <tbody>
                {selectors.data.items.map((selector) => (
                  <tr key={selector.name} className="hover:bg-raised">
                    <Td>
                      {isAddressable(selector.name) ? (
                        <AppLink
                          href={selectorHref(selector.name)}
                          className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
                        >
                          {selector.name}
                        </AppLink>
                      ) : (
                        <span className="font-mono font-medium text-fg">{selector.name}</span>
                      )}
                    </Td>
                    <Td className="break-words text-fg-muted">{selector.description}</Td>
                    <Td className="font-mono text-xs break-all">{selector.expression}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
          <Pager page={page} pages={pages ?? 1} hrefFor={hrefFor} />
        </Panel>
      )}
    </>
  );
}

/**
 * Tries an expression against paths, a line each, in a repository of a format: which
 * it matches is said beside each. Nothing is kept. What does not parse is said at the
 * expression, through `onRefused`.
 */
function PreviewPanel({
  expression,
  onRefused,
}: {
  expression: string;
  onRefused: (said: string | undefined) => void;
}) {
  const t = useTranslations("selectors");
  const preview = usePreview();
  const [format, setFormat] = useState("maven");
  const [typed, setTyped] = useState("");
  const paths = typed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const tooMany = paths.length > MOST_PATHS ? t("tooManyPaths", { most: MOST_PATHS }) : undefined;

  function run() {
    if (expression.trim() === "" || paths.length === 0 || tooMany) return;
    preview.mutate(
      { expression, format, paths },
      {
        onSuccess: () => onRefused(undefined),
        onError: (error) => onRefused(refusalsOf(error, ["expression"]).at.expression),
      },
    );
  }

  const refused = refusalsOf(preview.error, ["expression"]);
  return (
    <section aria-labelledby="selector-preview" className="flex flex-col gap-4">
      <h2 id="selector-preview" className={H2}>
        {t("previewTitle")}
      </h2>
      <p className="text-fg-muted">{t("previewIntro")}</p>
      <div className="grid gap-4 sm:grid-cols-[12rem_1fr]">
        <SelectField
          label={t("fields.format")}
          value={format}
          onChange={(event) => setFormat(event.target.value)}
          choices={FORMATS.map((value) => ({ value, label: value }))}
        />
        <TextAreaField
          label={t("fields.paths")}
          hint={t("hints.paths")}
          rows={4}
          spellCheck={false}
          className="font-mono text-sm"
          value={typed}
          error={tooMany}
          onChange={(event) => setTyped(event.target.value)}
        />
      </div>
      <div>
        <Button
          onClick={run}
          busy={preview.isPending}
          disabled={expression.trim() === "" || paths.length === 0}
        >
          <FlaskConical aria-hidden="true" className="size-4" />
          {t("preview")}
        </Button>
      </div>
      {preview.isError && refused.elsewhere ? <ErrorState error={preview.error} /> : null}
      {preview.data ? (
        <ul aria-label={t("previewed")} className="flex flex-col gap-2">
          {preview.data.paths.map((found) => (
            <li key={found.path} className="flex flex-wrap items-center gap-3">
              <StatusTag tone={found.matches ? "success" : "info"}>
                {found.matches ? (
                  <Check aria-hidden="true" className="size-3" />
                ) : (
                  <X aria-hidden="true" className="size-3" />
                )}
                {found.matches ? t("matches") : t("doesNotMatch")}
              </StatusTag>
              <code className="font-mono text-sm break-all">{found.path}</code>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

type Content = { name: string; description: string; expression: string };

/**
 * The form of a selector, new or not: its description and its expression, said wrong
 * where the server says so, and tried against paths before it is saved.
 */
function SelectorForm({
  selector,
  saving,
  error,
  onSave,
  saveLabel,
}: {
  /** The selector as it is, or null for one that is not there yet, which also has a name. */
  selector: SelectorOut | null;
  saving: boolean;
  error: unknown;
  onSave: (content: Content) => void;
  saveLabel: string;
}) {
  const t = useTranslations("selectors");
  const [name, setName] = useState("");
  const [description, setDescription] = useState(selector?.description ?? "");
  const [expression, setExpression] = useState(selector?.expression ?? "");
  const [previewSaid, setPreviewSaid] = useState<string | undefined>();
  const { form, tried: checked, attempt } = useAttempts(error);

  const refused = refusalsOf(error, ["name", "description", "expression"]);
  // A name another selector has: said at the name.
  const taken = isApiError(error) && error.code === "conflict" ? error.message : null;
  const ownName =
    selector !== null
      ? undefined
      : !NAME.test(name)
        ? t("nameRule")
        : isAddressable(name)
          ? undefined
          : t("nameDots");
  const nameProblem = checked ? (ownName ?? taken ?? refused.at.name) : undefined;
  const ownExpression = expression.trim() === "" ? t("expressionNeeded") : undefined;
  const expressionProblem =
    (checked ? (ownExpression ?? refused.at.expression) : undefined) ?? previewSaid;

  function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    if (ownName || ownExpression) return;
    onSave({ name, description: description.trim(), expression: expression.trim() });
  }

  return (
    <div className="flex flex-col gap-8">
      <form ref={form} onSubmit={submit} className="flex flex-col gap-6" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          {selector === null ? (
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
        <TextAreaField
          label={t("fields.expression")}
          hint={t("hints.expression")}
          required
          rows={3}
          spellCheck={false}
          className="font-mono text-sm"
          value={expression}
          error={expressionProblem}
          onChange={(event) => {
            setExpression(event.target.value);
            setPreviewSaid(undefined);
          }}
        />
        {error && taken === null && refused.elsewhere ? <ErrorState error={error} /> : null}
        <div>
          <Button type="submit" variant="primary" busy={saving}>
            {saveLabel}
          </Button>
        </div>
      </form>
      <PreviewPanel expression={expression} onRefused={setPreviewSaid} />
    </div>
  );
}

/** A new content selector. */
export function NewSelectorScreen() {
  const t = useTranslations("selectors");
  const router = useRouter();
  const notify = useNotify();
  const create = useCreateSelector();
  const mayCreate = useMayWrite();
  return (
    <div className="mx-auto max-w-4xl">
      <Breadcrumbs
        label={t("path")}
        crumbs={[
          { name: t("title"), href: CONTENT_SELECTORS },
          { name: t("newTitle"), href: NEW_SELECTOR },
        ]}
      />
      <PageHeader title={t("newTitle")} />
      {mayCreate ? null : <Alert tone="warning">{t("mayNotCreate")}</Alert>}
      <Panel className="p-6" hidden={!mayCreate}>
        <SelectorForm
          selector={null}
          saving={create.isPending}
          error={create.error}
          saveLabel={t("create")}
          onSave={(content) =>
            create.mutate(content, {
              onSuccess: (made) => {
                notify(t("created", { name: made.name }));
                router.push(selectorHref(made.name));
              },
            })
          }
        />
      </Panel>
    </div>
  );
}

function Edit({ selector }: { selector: SelectorOut }) {
  const t = useTranslations("selectors");
  const notify = useNotify();
  const update = useUpdateSelector(selector.name);
  return (
    <Panel className="p-6">
      <SelectorForm
        selector={selector}
        saving={update.isPending}
        error={update.error}
        saveLabel={t("save")}
        onSave={({ description, expression }) =>
          update.mutate(
            { description, expression },
            { onSuccess: () => notify(t("saved", { name: selector.name })) },
          )
        }
      />
    </Panel>
  );
}

/** A selector as it is, for whoever may read and not change it: it can still be tried. */
function Shown({ selector }: { selector: SelectorOut }) {
  const t = useTranslations("selectors");
  return (
    <Panel className="flex flex-col gap-8 p-6">
      <Facts>
        <Fact name={t("fields.description")}>{selector.description}</Fact>
        <Fact name={t("fields.expression")} mono>
          {selector.expression}
        </Fact>
      </Facts>
      <PreviewPanel expression={selector.expression} onRefused={() => undefined} />
    </Panel>
  );
}

/** One content selector: what it matches, trying it, changing it, and deleting it. */
export function SelectorScreen() {
  const t = useTranslations("selectors");
  const router = useRouter();
  const notify = useNotify();
  const where = parseSelector(usePathname());
  const mayWrite = useMayWrite();
  const remove = useDeleteSelector();
  // Once deleted, the selector is not asked for again: there is none to answer with.
  const selector = useSelector(remove.isSuccess ? null : (where?.name ?? null));
  const [asking, setAsking] = useState(false);

  if (where === null) return <NothingHere />;
  if (selector.isError) {
    return <ErrorState error={selector.error} onRetry={() => void selector.refetch()} />;
  }
  if (!selector.data || !selector.isFetchedAfterMount) return <LoadingState />;

  const found = selector.data;
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Breadcrumbs
          label={t("path")}
          crumbs={[
            { name: t("title"), href: CONTENT_SELECTORS },
            { name: found.name, href: selectorHref(found.name) },
          ]}
        />
        <PageHeader named title={found.name} />
      </div>
      {mayWrite ? <Edit selector={found} /> : <Shown selector={found} />}
      {mayWrite ? (
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
                  router.replace(CONTENT_SELECTORS);
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

Create `frontend/src/app/(shell)/admin/content-selectors/page.tsx`:

```tsx
import type { Metadata } from "next";

import { SelectorsScreen } from "@/screens/content-selectors";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.selectors.title };

export default function Page() {
  return <SelectorsScreen />;
}
```

Create `frontend/src/app/(shell)/admin/content-selectors/[name]/page.tsx`:

```tsx
import type { Metadata } from "next";

import { SelectorScreen } from "@/screens/content-selectors";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.selectors.oneTitle };

export default function Page() {
  return <SelectorScreen />;
}
```

Create `frontend/src/app/(shell)/admin/content-selectors/~new/page.tsx`:

```tsx
import type { Metadata } from "next";

import { NewSelectorScreen } from "@/screens/content-selectors";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.selectors.newTitle };

export default function Page() {
  return <NewSelectorScreen />;
}
```

Change `frontend/messages/en.json`:

```diff
@@ -20,6 +20,7 @@
       "upload": "Upload",
       "users": "Users",
       "roles": "Roles",
+      "contentSelectors": "Content selectors",
       "anonymousAccess": "Anonymous access",
       "authentication": "Authentication",
       "certificates": "Certificates",
@@ -630,6 +631,53 @@
     "mayNotCreate": "You may not create roles.",
     "nameDots": "A role cannot be called . or .. : its page would have no address."
   },
+  "selectors": {
+    "title": "Content selectors",
+    "newTitle": "New content selector",
+    "oneTitle": "Content selector",
+    "intro": "Some of what repositories hold, named by its format and its paths. A role's selector permission gives an action on what a selector matches.",
+    "path": "Path",
+    "new": "New content selector",
+    "none": "No content selector is made yet.",
+    "columns": {
+      "name": "Name",
+      "description": "Description",
+      "expression": "Expression"
+    },
+    "fields": {
+      "name": "Name",
+      "description": "Description",
+      "expression": "Expression",
+      "format": "In a repository of",
+      "paths": "Paths to try"
+    },
+    "hints": {
+      "name": "Letters, digits and . _ - , up to 64. It cannot be changed later.",
+      "expression": "As format == \"maven\" and path =^ \"/com/acme/\". == is equal to, =^ starts with, =~ matches a regular expression as a whole; and, or, not and parentheses combine them. A path starts with /.",
+      "paths": "One a line, as /com/acme/app/1.0/app-1.0.jar. At most 100."
+    },
+    "nameRule": "A selector's name is 1 to 64 letters, digits or . _ -",
+    "nameDots": "A selector cannot be called . or .. : its page would have no address.",
+    "expressionNeeded": "An expression is needed.",
+    "previewTitle": "Try it",
+    "previewIntro": "Which of these paths the expression matches, as it is now: nothing is saved.",
+    "preview": "Try the expression",
+    "previewed": "What the expression matches",
+    "matches": "Matches",
+    "doesNotMatch": "Does not match",
+    "tooManyPaths": "At most {most} paths at once.",
+    "create": "Create content selector",
+    "created": "Created the content selector {name}.",
+    "save": "Save",
+    "saved": "Saved the content selector {name}.",
+    "deleteTitle": "Delete this content selector",
+    "deleteIntro": "A selector that a role names cannot be deleted: take it out of the roles first.",
+    "delete": "Delete content selector",
+    "deleteAsk": "Delete the content selector {name}?",
+    "deleteBody": "It is gone for good. This cannot be undone.",
+    "deleted": "Deleted the content selector {name}.",
+    "mayNotCreate": "You may not create content selectors."
+  },
   "anonymous": {
     "title": "Anonymous access",
     "intro": "Whether someone who is not signed in may use this server at all.",
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `frontend/`): `pnpm vitest run src/screens/content-selectors.test.tsx src/components/shell.test.tsx src/lib/navigation.test.ts && pnpm lint && pnpm typecheck`
Expected: 54 passed; `All matched files use Prettier code style!`; the types check.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(ui): Content selectors: listed, made, changed and deleted, each tried against paths before it is trusted"
```

---

### Task 2: Selector permissions in the role editor; the guide; what the plan settled

**Files:**
- Modify:
  - `frontend/src/lib/patterns.ts` (a `selector` row, and the area `selectors`).
  - `frontend/src/components/permission-rows.tsx` (its fields and words).
  - `frontend/src/lib/selectors.ts` (`useSelectorNames`).
  - `frontend/src/screens/roles.tsx`, `frontend/src/screens/tokens.tsx`, `frontend/messages/en.json`.
  - `docs/web-ui.md` and `docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md`.
- Test: modify `frontend/src/lib/account.test.ts`, `frontend/src/components/security.test.tsx`, `frontend/src/screens/security.test.tsx`

**Interfaces:**
- Consumes: Task 1's `useEverySelector`, `FORMATS` and messages; `allows` and `useSession`.
- Produces:
  - The row `{ kind: "selector"; selector; format; name; action }` and `startOf("selector")`.
  - `PermissionRows`'s `selectors?: string[]` and `useSelectorNames(): string[]`.
  - The messages `permissions.kinds.selector`, `permissions.selector`, `permissions.grants.selected`, `anySelector`, `oneSelector`, and the areas `selectors`.

- [ ] **Step 1: Write the failing tests**

Change `frontend/src/lib/account.test.ts`:

```diff
@@ -57,6 +57,15 @@ describe("a permission pattern", () => {
     ["admin:users:write", { kind: "admin", area: "users", action: "write" }],
     ["admin:*:read", { kind: "admin", area: "*", action: "read" }],
     ["admin:*:*", { kind: "admin", area: "*", action: "*" }],
+    ["admin:selectors:write", { kind: "admin", area: "selectors", action: "write" }],
+    [
+      "selector:acme:maven:releases:read",
+      { kind: "selector", selector: "acme", format: "maven", name: "releases", action: "read" },
+    ],
+    [
+      "selector:*:*:*:browse",
+      { kind: "selector", selector: "*", format: "*", name: "*", action: "browse" },
+    ],
   ])("%s is taken apart into a row, and the row makes it again", (pattern, row) => {
     expect(fromPattern(pattern)).toEqual(row);
     expect(toPattern(row)).toBe(pattern);
@@ -74,6 +83,9 @@ describe("a permission pattern", () => {
     "admin:users:read:more",
     "*:users:read",
     "metrics:read",
+    "selector:acme", // shorter: whatever acme matches, everywhere
+    "selector:acme:maven:releases:publish",
+    "selector:acme:maven:releases:read:more",
   ])("%s is of no shape a row has, and stays as it was typed", (pattern) => {
     expect(fromPattern(pattern)).toEqual({ kind: "typed", text: pattern });
     expect(toPattern(fromPattern(pattern))).toBe(pattern);
@@ -86,6 +98,7 @@ describe("a permission pattern", () => {
 
   test("a row starts as the widest of its shape that only reads", () => {
     expect(toPattern(startOf("repository"))).toBe("repository:*:*:read");
+    expect(toPattern(startOf("selector"))).toBe("selector:*:*:*:read");
     expect(toPattern(startOf("admin"))).toBe("admin:*:read");
     expect(toPattern(startOf("all"))).toBe("*");
     expect(toPattern(startOf("typed"))).toBe("");
```

Change `frontend/src/components/security.test.tsx`:

```diff
@@ -32,6 +32,7 @@ function Rows({ initial, checked = false }: { initial: string[]; checked?: boole
         initial={initial}
         onChange={setPatterns}
         repositories={REPOSITORIES}
+        selectors={["acme", "jars"]}
         checked={checked}
       />
       <output aria-label="Patterns">{JSON.stringify(patterns)}</output>
@@ -93,6 +94,41 @@ describe("permissions as rows (A2)", () => {
     ]);
   });
 
+  test("a selector's row gives an action where a content selector matches (spec 10)", async () => {
+    const user = userEvent.setup();
+    renderUi(<Rows initial={["selector:gone:npm:*:edit"]} />);
+
+    expect(within(row(1)).getByLabelText("About")).toHaveValue("selector");
+    // A selector a row holds is one of its choices, though it is not among those there are.
+    expect(options(within(row(1)).getByLabelText("Content selector"))).toEqual([
+      "Any",
+      "gone",
+      "acme",
+      "jars",
+    ]);
+    expect(row(1)).toHaveTextContent(
+      "Edit in every npm repository, where the content selector gone matches.",
+    );
+
+    await user.selectOptions(within(row(1)).getByLabelText("About"), "repository");
+    await user.selectOptions(within(row(1)).getByLabelText("About"), "selector");
+    expect(patterns()).toEqual(["selector:*:*:*:read"]);
+    expect(row(1)).toHaveTextContent(
+      "Read in every repository, where any content selector matches.",
+    );
+
+    await user.selectOptions(within(row(1)).getByLabelText("Content selector"), "acme");
+    await user.selectOptions(within(row(1)).getByLabelText("Format"), "maven");
+    await user.selectOptions(within(row(1)).getByLabelText("Repository"), "releases");
+    await user.selectOptions(within(row(1)).getByLabelText("Action"), "add");
+
+    expect(patterns()).toEqual(["selector:acme:maven:releases:add"]);
+    expect(row(1)).toHaveTextContent(
+      "Add in the maven repository releases, where the content selector acme matches.",
+    );
+    await expectAccessible();
+  });
+
   test("offers every format, whether or not a repository of it exists", () => {
     renderUi(<Rows initial={["repository:*:*:read"]} />);
 
```

Change `frontend/src/screens/security.test.tsx`:

```diff
@@ -714,6 +714,7 @@ describe("a role", () => {
       [`GET /roles/${which?.name}`]: { json: which },
       "GET /roles": { json: page(ROLES) },
       "GET /content": { json: REPOSITORIES },
+      "GET /content-selectors": { json: page([]) },
       "GET /users": { json: page([SELF]) },
       "GET /auth/session": { json: session },
       ...more,
@@ -725,6 +726,7 @@ describe("a role", () => {
     const api = mockApi({
       "GET /roles": { json: page(ROLES) },
       "GET /content": { json: REPOSITORIES },
+      "GET /content-selectors": { json: page([]) },
       "GET /users": { json: page([SELF]) },
       "GET /auth/session": { json: ADMIN },
       "POST /roles": (call) => ({ status: 201, json: role((call.body as { name: string }).name) }),
@@ -756,6 +758,30 @@ describe("a role", () => {
     expect(notices()).toHaveTextContent("Created the role readers.");
   });
 
+  test("offers the content selectors there are to a permission's row (spec 10)", async () => {
+    const user = userEvent.setup();
+    const acme = {
+      id: "s1",
+      name: "acme",
+      description: "",
+      expression: 'path =^ "/com/acme/"',
+      created_at: "2026-10-21T08:00:00Z",
+      updated_at: "2026-10-21T08:00:00Z",
+    };
+    const { calls } = fresh({ "GET /content-selectors": { json: page([acme]) } });
+
+    await user.type(screen.getByLabelText("Name"), "acme-readers");
+    await user.click(screen.getByRole("button", { name: "Add a permission" }));
+    await user.selectOptions(screen.getByLabelText("About"), "selector");
+    await user.selectOptions(await screen.findByLabelText("Content selector"), "acme");
+    await user.click(screen.getByRole("button", { name: "Create role" }));
+
+    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
+    expect((of(calls, "POST")[0]?.body as { permissions: string[] }).permissions).toEqual([
+      "selector:acme:*:*:read",
+    ]);
+  });
+
   test("needs a name of the kind a role has, and one no other role has", async () => {
     const user = userEvent.setup();
     const { calls } = fresh({
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `frontend/`): `pnpm vitest run src/lib/account.test.ts src/components/security.test.tsx src/screens/security.test.tsx`
Expected: 6 failed: a selector's pattern is a typed row, `admin:selectors` is no area, there is no selector row to start, and the role editor offers no selectors.

- [ ] **Step 3: Write the code, the guide and the spec's rows**

Change `frontend/src/lib/patterns.ts`:

```diff
@@ -21,6 +21,7 @@ export const ADMIN_AREAS = [
   "security",
   "certificates",
   "audit",
+  "selectors",
 ] as const;
 export const ADMIN_ACTIONS = ["read", "write"] as const;
 /** What a token that may only read is limited to. */
@@ -35,6 +36,8 @@ export function isValidPattern(pattern: string): boolean {
 
 export type Row =
   | { kind: "repository"; format: string; name: string; action: string }
+  // Some of a repository: what a content selector matches in it (spec 10).
+  | { kind: "selector"; selector: string; format: string; name: string; action: string }
   | { kind: "admin"; area: string; action: string }
   | { kind: "all" }
   | { kind: "typed"; text: string };
@@ -49,6 +52,8 @@ export function toPattern(row: Row): string {
   switch (row.kind) {
     case "repository":
       return `repository:${row.format}:${row.name}:${row.action}`;
+    case "selector":
+      return `selector:${row.selector}:${row.format}:${row.name}:${row.action}`;
     case "admin":
       return `admin:${row.area}:${row.action}`;
     case "all":
@@ -67,8 +72,19 @@ export function fromPattern(pattern: string): Row {
   if (pattern === ANY) return { kind: "all" };
   const typed: Row = { kind: "typed", text: pattern };
   if (!isValidPattern(pattern)) return typed;
-  const [about, second, third, fourth, ...more] = pattern.split(":");
-  if (more.length > 0 || second === undefined || third === undefined) return typed;
+  const [about, second, third, fourth, fifth, ...more] = pattern.split(":");
+  if (
+    about === "selector" &&
+    more.length === 0 &&
+    second !== undefined &&
+    third !== undefined &&
+    fourth !== undefined &&
+    fifth !== undefined &&
+    known(REPOSITORY_ACTIONS, fifth)
+  ) {
+    return { kind: "selector", selector: second, format: third, name: fourth, action: fifth };
+  }
+  if (fifth !== undefined || second === undefined || third === undefined) return typed;
   if (about === "repository" && fourth !== undefined && known(REPOSITORY_ACTIONS, fourth)) {
     return { kind: "repository", format: second, name: third, action: fourth };
   }
@@ -88,6 +104,8 @@ export function startOf(kind: RowKind): Row {
   switch (kind) {
     case "repository":
       return { kind, format: ANY, name: ANY, action: "read" };
+    case "selector":
+      return { kind, selector: ANY, format: ANY, name: ANY, action: "read" };
     case "admin":
       return { kind, area: ANY, action: "read" };
     case "all":
```

Change `frontend/src/components/permission-rows.tsx`:

```diff
@@ -20,7 +20,7 @@ import {
   type RowKind,
 } from "@/lib/patterns";
 
-const KINDS: readonly RowKind[] = ["repository", "admin", "all", "typed"];
+const KINDS: readonly RowKind[] = ["repository", "selector", "admin", "all", "typed"];
 // The formats there are, whether or not a repository of each exists yet.
 export const FORMATS = ["raw", "maven", "npm", "pypi", "docker", "apt", "yum", "apk", "nuget"];
 
@@ -41,7 +41,8 @@ export function usePatternWords(): (pattern: string) => string | null {
     switch (row.kind) {
       case "all":
         return t("grants.all");
-      case "repository": {
+      case "repository":
+      case "selector": {
         const { format, name } = row;
         const where =
           format === ANY && name === ANY
@@ -51,8 +52,13 @@ export function usePatternWords(): (pattern: string) => string | null {
               : format === ANY
                 ? t("grants.everyNamed", { name })
                 : t("grants.oneRepository", { format, name });
-        const action = row.action === ANY ? "any" : (row.action as "read");
-        return t("grants.repository", { action: t(`grants.doing.${action}`), where });
+        const action = t(`grants.doing.${row.action === ANY ? "any" : (row.action as "read")}`);
+        if (row.kind === "repository") return t("grants.repository", { action, where });
+        const which =
+          row.selector === ANY
+            ? t("grants.anySelector")
+            : t("grants.oneSelector", { name: row.selector });
+        return t("grants.selected", { action, where, which });
       }
       case "admin": {
         const action = row.action === ANY ? "any" : (row.action as "read");
@@ -99,12 +105,15 @@ export function PermissionRows({
   initial,
   onChange,
   repositories,
+  selectors = [],
   checked = false,
 }: {
   legend: string;
   initial: string[];
   onChange: (patterns: string[]) => void;
   repositories: Held[];
+  /** The content selectors there are, by their names: none for who may not read them. */
+  selectors?: string[];
   /** Saving was tried: a row that is still empty is now said to be wrong. */
   checked?: boolean;
 }) {
@@ -169,7 +178,15 @@ export function PermissionRows({
                     onChange={(event) => set(id, startOf(event.target.value as RowKind))}
                     choices={KINDS.map((kind) => ({ value: kind, label: t(`kinds.${kind}`) }))}
                   />
-                  {row.kind === "repository" ? (
+                  {row.kind === "selector" ? (
+                    <SelectField
+                      label={t("selector")}
+                      value={row.selector}
+                      onChange={(event) => set(id, { ...row, selector: event.target.value })}
+                      choices={listed(selectors, row.selector, plain)}
+                    />
+                  ) : null}
+                  {row.kind === "repository" || row.kind === "selector" ? (
                     <>
                       <SelectField
                         label={t("format")}
```

Change `frontend/src/lib/selectors.ts`:

```diff
@@ -15,6 +15,8 @@ import type {
   SelectorCreate,
   SelectorOut,
 } from "@/lib/api/types";
+import { allows } from "@/lib/session/rules";
+import { useSession } from "@/lib/session/session";
 
 // As many of a list as one page shows (A13).
 export const AT_ONCE = 50;
@@ -46,6 +48,17 @@ export function useEverySelector(enabled = true) {
   });
 }
 
+/**
+ * The names of the selectors there are, for a selector permission's row to choose from:
+ * none for whoever may not read them, who types a selector's name instead.
+ */
+export function useSelectorNames(): string[] {
+  const session = useSession();
+  const mayRead = session.data !== undefined && allows(session.data, "admin:selectors:read");
+  const every = useEverySelector(mayRead);
+  return mayRead ? (every.data?.items.map((selector) => selector.name) ?? []) : [];
+}
+
 export function useSelector(name: string | null) {
   return useQuery({
     queryKey: [SELECTORS, "one", name],
```

Change `frontend/src/screens/roles.tsx`:

```diff
@@ -24,6 +24,7 @@ import { useRepositories } from "@/lib/content";
 import { useAttempts, usePageFocus, useWithinPages } from "@/lib/focus";
 import { isAddressable, NEW_ROLE, pageHref, pageOf, parseRole, roleHref, ROLES } from "@/lib/paths";
 import { refusalsOf } from "@/lib/refusals";
+import { useSelectorNames } from "@/lib/selectors";
 import {
   AT_ONCE,
   useCreateRole,
@@ -151,6 +152,7 @@ function RoleForm({
 }) {
   const t = useTranslations("roles");
   const repositories = useRepositories();
+  const selectors = useSelectorNames();
   const others = useEveryRole();
   const [name, setName] = useState("");
   const [description, setDescription] = useState(role?.description ?? "");
@@ -214,6 +216,7 @@ function RoleForm({
         initial={permissions}
         onChange={setPermissions}
         repositories={repositories.data?.items ?? []}
+        selectors={selectors}
         checked={checked}
       />
       {refused.at.permissions ? <Alert tone="danger">{refused.at.permissions}</Alert> : null}
```

Change `frontend/src/screens/tokens.tsx`:

```diff
@@ -25,6 +25,7 @@ import { endOfDay } from "@/lib/format";
 import { ACCOUNT_TOKENS, pageHref, pageOf } from "@/lib/paths";
 import { READ_ONLY } from "@/lib/patterns";
 import { refusalsOf } from "@/lib/refusals";
+import { useSelectorNames } from "@/lib/selectors";
 import { AT_ONCE, useCreateToken, useMyTokens, useRevokeToken } from "@/lib/security";
 
 const DAY = 24 * 3600 * 1000;
@@ -82,6 +83,7 @@ function Create({ onCreated }: { onCreated: (token: TokenCreated) => void }) {
   const t = useTranslations("tokens");
   const create = useCreateToken();
   const repositories = useRepositories();
+  const selectors = useSelectorNames();
   const [name, setName] = useState("");
   const [lasts, setLasts] = useState<Lasts>("90");
   const [day, setDay] = useState("");
@@ -168,6 +170,7 @@ function Create({ onCreated }: { onCreated: (token: TokenCreated) => void }) {
               initial={custom}
               onChange={setCustom}
               repositories={repositories.data?.items ?? []}
+              selectors={selectors}
               checked={checked}
             />
             {problems.custom ? <Alert tone="danger">{problems.custom}</Alert> : null}
```

Change `frontend/messages/en.json`:

```diff
@@ -372,7 +372,8 @@
       "repository": "A repository",
       "admin": "Administration",
       "all": "Everything",
-      "typed": "Typed by hand"
+      "typed": "Typed by hand",
+      "selector": "Some of a repository, by a content selector"
     },
     "any": "Any",
     "format": "Format",
@@ -397,7 +398,8 @@
       "repositories": "Repositories",
       "security": "Sign-in",
       "certificates": "Certificates",
-      "audit": "Audit log"
+      "audit": "Audit log",
+      "selectors": "Content selectors"
     },
     "add": "Add a permission",
     "remove": "Remove permission {number}",
@@ -433,10 +435,15 @@
         "repositories": "the repositories",
         "security": "how people sign in",
         "certificates": "the trusted certificates",
-        "audit": "the audit log"
+        "audit": "the audit log",
+        "selectors": "the content selectors"
       },
-      "other": "Whatever this pattern matches."
-    }
+      "other": "Whatever this pattern matches.",
+      "selected": "{action} in {where}, where {which} matches.",
+      "anySelector": "any content selector",
+      "oneSelector": "the content selector {name}"
+    },
+    "selector": "Content selector"
   },
   "tokens": {
     "title": "API tokens",
```

Change `docs/web-ui.md`:

```diff
@@ -60,7 +60,16 @@ repositories, blob stores and the installation's own settings.
     action from lists. The pattern the row makes is shown with what it grants in
     words. A pattern the lists cannot make is typed by hand, and a role that was
     written through the API opens with nothing lost. The `admin` role is shown and
-    cannot be changed.
+    cannot be changed. A row may be about some of a repository, by a content selector:
+    chosen from those there are (or typed, by whoever may not read them), with the
+    format, repository and action, and said in words.
+  - **Content selectors** lists what selector permissions name: each one's name,
+    description and expression. A new one is made with a name, a description and an
+    expression; whatever the server finds wrong with the expression is said at it,
+    with the character where it went wrong. Before it is saved, or by whoever may only
+    read it, an expression is tried against paths, a line each, in a repository of a
+    format, and each path is said to match or not. A selector is deleted after a
+    question; one a role names says which roles do, and is kept.
   - **Anonymous access** is one switch, which asks before it is turned on, and shows
     what someone who is not signed in may then do. If the `anonymous` user is
     disabled, nothing is given though the switch is on, and the page says so.
```

Change `docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md`:

```diff
@@ -247,6 +247,15 @@ Settled here, by the designer:
 | G14 | A pattern that repeats a repetition (`(a+)+`, `(\w+/?)*`) is refused when it is saved: its time on a crafted path doubles with each character, and paths are what anyone sends. A preview's path is at most 1,024 bytes. | The final review: 3.8 seconds on 28 characters. |
 | G15 | A folder's page is filled from further on, up to 20 reads, past what a selector leaves out; the components left out after a pattern's check are passed as one array parameter, however many. | The final review: a reachable folder shown empty; more than 32,767 parameters. |
 
+### Settled while building plan 15h
+
+| # | What | Why |
+| --- | --- | --- |
+| U1 | The screens are Administration, Content selectors, after Roles, with `admin:selectors:read`: the list at `/admin/content-selectors`, a new one at `/admin/content-selectors/~new` (a selector may be called `new`), one at `/admin/content-selectors/<name>`. A selector is made with a name of the server's rule, said before it is sent, a description and an expression; changed on its page; deleted after a question, and one a role names says which (`409 in_use`). Whoever may only read sees each, and tries it. | Section 10: the screens (15h); as the roles' screens are. |
+| U2 | An expression is tried as it is typed, against paths a line each (at most 100) in a repository of a format (Maven unless chosen), and each path is said to match or not; nothing is kept. What the server finds wrong with the expression, saving or trying it, is said at the expression, with its character. | Section 10: a preview against paths. |
+| U3 | A role's row, and a token's, may be about some of a repository: `selector:<selector>:<format>:<repository>:<action>`, the selector chosen from those there are (read only by whoever holds `admin:selectors:read`; to others, the one a row holds and Any), then the format, the repository and the action as a repository's row, and said in words (`Add in the maven repository releases, where the content selector acme matches.`). A shorter or another shape is a typed row, kept as it is. The administration areas gain `selectors`. | Section 10: the role editor's rows offer selector permissions. |
+| U4 | What else the web UI offers by permission stays by repository permissions: Upload in the navigation, the repositories the upload screen offers, and the browse screens' delete buttons. Whoever holds only selector permissions does those through package clients, the API or MCP. | Section 10 names the screens of 15h only; each of those is its own change. |
+
 ## 11. Errors and limits
 
 - Sign-in through an external source answers as a local one does: `401 Invalid credentials.`, throttled alike (SEC-19); what went wrong is logged and audited, not said.
```

- [ ] **Step 4: Run the tests to verify they pass, and every test**

Run (in `frontend/`): `pnpm vitest run src/lib/account.test.ts src/components/security.test.tsx src/screens/security.test.tsx src/screens/content-selectors.test.tsx && pnpm lint && pnpm typecheck`
Expected: 145 passed; `All matched files use Prettier code style!`; the types check.

Then (in `backend/`): `uv run pytest -q tests/test_documents.py`
Expected: 147 passed.

Then every test: (in `frontend/`) `pnpm vitest run`; (in `backend/`) `uv run ruff format --check . && uv run ruff check . && uv run pytest -q`
Expected: Vitest: 946 passed; Ruff: `476 files already formatted`, `All checks passed!`; pytest: 4463 passed, 2 skipped, 117 deselected (the `docker` tests).

- [ ] **Step 5: Commit**

```bash
git add frontend docs
git commit -m "feat(ui): a role's and a token's rows give an action where a content selector matches; docs: the screens, and what plan 15h settled"
```
