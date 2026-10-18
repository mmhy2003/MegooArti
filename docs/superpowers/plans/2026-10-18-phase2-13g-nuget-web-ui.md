# NuGet in the Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everything the server does for NuGet can be done, and seen, in the web UI: NuGet in every list of formats, a hosted repository that takes a version once, a proxy's protocol and symbol server, uploads of packages and symbol packages, and how each client is set up to use a repository.

**Architecture:** The frontend's alone: the server already gives a NuGet repository's setup snippets and a version's usage (W10, Z6, S7), which the UI shows as it shows every format's. `repository-form.ts` learns NuGet's settings (the deployment policy the server gives it, a proxy's protocol and symbol server); the settings screen gets their fields and facts; the upload form, the permissions' rows and the list of formats that take an upload get NuGet. Texts are in `messages/en.json`.

**Tech Stack:** Next.js, React, TypeScript, next-intl; Vitest with Testing Library; Playwright through the built images for the browser test.

**Spec:** [docs/superpowers/specs/2026-10-15-nuget-design.md](../specs/2026-10-15-nuget-design.md), the row of plan 13g in section 12, with W7, W10, X6, Z6 and S7.

## Decisions this plan settles

Task 4 writes these into the spec's section 4, as "Settled while building plan 13g".

| # | Decision | Reason |
| --- | --- | --- |
| U2 | NuGet is in every list of formats: the form's, the permissions' rows, and those that take an upload. An upload takes `.nupkg` and `.snupkg` files, several at once, and no directory: each goes where its `.nuspec` says, packages before symbol packages (W7). | W7. |
| U3 | A NuGet repository's page has the setup snippets the server gives (W10, Z6, S7): `dotnet`, `nuget.config`, Chocolatey, PowerShell and Symbols; a version's page its usage. The UI shows them as it shows every format's: it writes none of its own. | One place says how a machine is set up: the server. |
| U4 | The browser test makes a V2 proxy of NuGet in the form, and uploads to a hosted one a package and its symbol package that it writes itself (a zip of stored files, and a portable PDB), and finds the PDB at its key; then the setup snippets and their accessibility. | Section 10's browser tests. |"""

## Global Constraints

- **What the server says is shown, not said again**: the setup snippets and a version's usage come from the browsing API; the UI writes none of a format's own.
- **What cannot change is a fact, not a field**: a NuGet proxy's protocol, once the proxy is made.
- **Every screen meets WCAG 2.1 AA in both modes**, as the browser test checks with axe.
- **Every test of a stack is marked `docker`**: the browser test runs through `tests/test_ui_client.py`.
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `pnpm` commands in `frontend/`, `uv` and `pytest` commands in `backend/`, and `git` commands in the repository root.

## Review Focus

What the tests of this plan do not reach, most likely first. The reviewer reads for these.

1. **A NuGet proxy made before this plan**: one whose `format_config` has no protocol, and one whose symbol server is cleared and saved again.
2. **Switching format and type while the form is filled**: a NuGet proxy's symbol server typed, then the type changed to hosted, or the format to Maven; what is sent.
3. **The server's refusals**: a protocol change refused on a proxy that is there, a symbol server refused, said at the field or above the button.
4. **Uploads of what is not a NuGet package**: a `.zip` renamed, a symbol package without its package, said at the file field.
5. **Snippets on narrow screens**: the long `dotnet` and `dotnet-symbol` commands and `nuget.config` in a figure, on a phone's width.

---

### Task 1: NuGet in the repository form

**Files:**
- Modify: `frontend/src/lib/repository-form.ts`, `frontend/src/screens/repository-settings.tsx`, `frontend/messages/en.json`
- Modify (tests): `frontend/src/lib/repository-form.test.ts`, `frontend/src/screens/administration.test.tsx`

**Interfaces:**
- Consumes: the form's `Draft`, `EMPTY`, `draftOf`, `policyOf`, `problemsOf`, `createBody`, `updateBody`; the screen's `ChoiceGroup`, `TextField`, `Fact`.
- Produces: `FORMATS` with `nuget`; `PROTOCOLS = ["v3", "v2"]`; `Draft.protocol`, `Draft.symbolUrl`; `isNuGetProxy({ format, type }) -> boolean`; the problem `symbolUrlRule`; `policyOf` giving `disable_redeploy` to NuGet; the messages `manage.fields.protocol`, `manage.fields.symbolUrl`, `manage.hints.remoteUrlOf.v3|v2`, `manage.hints.symbolUrl`, `manage.problems.symbolUrlRule`, `manage.protocols`, `manage.protocolsHints`.

- [ ] **Step 1: Write the failing tests**

Change `frontend/src/lib/repository-form.test.ts`:

```diff
@@ -15,6 +15,7 @@ import {
   FORMATS,
   hasMavenSettings,
   hasSigningKey,
+  isNuGetProxy,
   moved,
   policyOf,
   problemsOf,
@@ -423,6 +424,63 @@ describe("APT, YUM and apk", () => {
   });
 });
 
+describe("NuGet", () => {
+  const SYMBOLS = "https://symbols.nuget.org/download/symbols";
+
+  test("is a format a repository can have, hosted by default a version pushed once", () => {
+    expect(FORMATS).toContain("nuget");
+    // As nuget.org takes one: a second push of a version is refused (D6).
+    expect(policyOf(draft({ format: "nuget" }))).toBe("disable_redeploy");
+    expect(createBody(draft({ format: "nuget" })).hosted).toEqual({
+      deployment_policy: "disable_redeploy",
+    });
+    expect(createBody(draft({ format: "nuget" })).format_config).toEqual({});
+    expect(createBody(draft({ format: "nuget", type: "group" })).format_config).toEqual({});
+  });
+
+  test("a proxy is made with its protocol, V3 unless V2 is chosen, and a symbol server if one is given", () => {
+    const proxy = { ...PROXY, format: "nuget" };
+
+    expect(isNuGetProxy(proxy)).toBe(true);
+    expect(isNuGetProxy({ ...proxy, type: "hosted" })).toBe(false);
+    expect(createBody(proxy).format_config).toEqual({ protocol: "v3" });
+    expect(createBody({ ...proxy, protocol: "v2" }).format_config).toEqual({ protocol: "v2" });
+    expect(createBody({ ...proxy, symbolUrl: ` ${SYMBOLS} ` }).format_config).toEqual({
+      protocol: "v3",
+      symbol_url: SYMBOLS,
+    });
+  });
+
+  test("the form of a proxy that is there starts from its protocol and its symbol server, and sends them back", () => {
+    const held = draftOf(
+      stored({
+        format: "nuget",
+        type: "proxy",
+        format_config: { protocol: "v2", symbol_url: SYMBOLS },
+      }),
+    );
+
+    expect([held.protocol, held.symbolUrl]).toEqual(["v2", SYMBOLS]);
+    expect(updateBody(held).format_config).toEqual({ protocol: "v2", symbol_url: SYMBOLS });
+    // One made before there were settings speaks V3, as the server has it.
+    expect(draftOf(stored({ format: "nuget", type: "proxy", format_config: {} })).protocol).toBe(
+      "v3",
+    );
+  });
+
+  test.each([
+    ["", undefined],
+    [SYMBOLS, undefined],
+    ["ftp://symbols.example.org", "symbolUrlRule"],
+    ["https://user:secret@symbols.example.org", "symbolUrlRule"],
+    ["not an address", "symbolUrlRule"],
+  ])("a symbol server %j: %s", (symbolUrl, problem) => {
+    expect(problemsOf({ ...PROXY, format: "nuget", symbolUrl }, true).symbolUrl).toBe(problem);
+    // Of another format it is not the form's.
+    expect(problemsOf({ ...PROXY, symbolUrl }, true).symbolUrl).toBeUndefined();
+  });
+});
+
 describe("the order of a group's members", () => {
   test("a member moves one place up or down", () => {
     expect(moved(["a", "b", "c"], "c", -1)).toEqual(["a", "c", "b"]);
```

Change `frontend/src/screens/administration.test.tsx`:

```diff
@@ -556,7 +556,7 @@ describe("a new repository (R2)", () => {
     const formats = within(screen.getByLabelText("Format"))
       .getAllByRole("option")
       .map((option) => option.textContent);
-    expect(formats).toEqual(expect.arrayContaining(["apt", "yum", "apk"]));
+    expect(formats).toEqual(expect.arrayContaining(["apt", "yum", "apk", "nuget"]));
   });
 
   test("a hosted APT repository is made with the suite that is typed, which is checked first", async () => {
@@ -655,6 +655,87 @@ describe("a new repository (R2)", () => {
     expect(screen.queryByRole("alert")).toBeNull();
   });
 
+  test("a NuGet proxy is made with its protocol and its symbol server, which is checked first", async () => {
+    const user = userEvent.setup();
+    const { calls } = fresh();
+
+    await user.selectOptions(screen.getByLabelText("Format"), "nuget");
+    await user.click(screen.getByRole("radio", { name: "Proxy" }));
+    expect(screen.getByRole("radio", { name: "V3" })).toBeChecked();
+    expect(screen.getByLabelText("Remote address")).toHaveAccessibleDescription(
+      "The feed's service index: https://api.nuget.org/v3/index.json for nuget.org.",
+    );
+    await user.click(screen.getByRole("radio", { name: "V2" }));
+    expect(screen.getByLabelText("Remote address")).toHaveAccessibleDescription(
+      /Chocolatey's, https:\/\/www\.powershellgallery\.com\/api\/v2\/ for the PowerShell Gallery\./,
+    );
+    await user.type(screen.getByLabelText("Name"), "choco-community");
+    // Pasted, as an address is: typed a key at a time, it is slow.
+    await user.click(screen.getByLabelText("Remote address"));
+    await user.paste("https://community.chocolatey.org/api/v2/");
+    const symbols = screen.getByLabelText("Symbol server");
+    await user.click(symbols);
+    await user.paste("ftp://symbols.example.org");
+    await user.click(create());
+    expect(symbols).toHaveAccessibleDescription(
+      "Give an http or https address with a host, and without credentials, a query or a fragment, or none.",
+    );
+    expect(of(calls, "POST")).toHaveLength(0);
+
+    await user.clear(symbols);
+    await user.click(create());
+    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
+    expect(sent(calls)).toMatchObject({
+      format: "nuget",
+      type: "proxy",
+      format_config: { protocol: "v2" },
+    });
+    await expectAccessible();
+  });
+
+  test("a hosted NuGet repository refuses a version pushed twice unless told otherwise", async () => {
+    const user = userEvent.setup();
+    const { calls } = fresh();
+
+    await user.selectOptions(screen.getByLabelText("Format"), "nuget");
+    expect(screen.getByRole("radio", { name: "Disable redeploy" })).toBeChecked();
+    expect(screen.queryByLabelText("Symbol server")).toBeNull();
+    await user.type(screen.getByLabelText("Name"), "nuget-hosted");
+    await user.click(create());
+
+    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
+    expect(sent(calls)).toMatchObject({
+      format: "nuget",
+      hosted: { deployment_policy: "disable_redeploy" },
+      format_config: {},
+    });
+  });
+
+  test("says where the server refuses a protocol or a symbol server", async () => {
+    const user = userEvent.setup();
+    fresh({
+      "POST /repositories": failure(422, "validation_error", "The request is not valid.", [
+        { field: "format_config.symbol_url", message: "Give an http or https address." },
+      ]),
+    });
+
+    await user.selectOptions(screen.getByLabelText("Format"), "nuget");
+    await user.click(screen.getByRole("radio", { name: "Proxy" }));
+    await user.type(screen.getByLabelText("Name"), "nuget-org");
+    await user.click(screen.getByLabelText("Remote address"));
+    await user.paste("https://api.nuget.org/v3/index.json");
+    await user.click(screen.getByLabelText("Symbol server"));
+    await user.paste("https://symbols.example.org");
+    await user.click(create());
+
+    await waitFor(() =>
+      expect(screen.getByLabelText("Symbol server")).toHaveAccessibleDescription(
+        "Give an http or https address.",
+      ),
+    );
+    expect(screen.queryByRole("alert")).toBeNull();
+  });
+
   test("offers the blob stores there are, or the default one where they may not be seen", async () => {
     const first = fresh();
     const choices = () =>
@@ -997,6 +1078,31 @@ describe("the settings of a repository", () => {
     });
   });
 
+  test("of a NuGet proxy show its protocol, chosen once, and keep its symbol server", async () => {
+    const user = userEvent.setup();
+    const held = repository("nuget-org", {
+      ...proxy("nuget-org"),
+      format: "nuget",
+      format_config: { protocol: "v3", symbol_url: "https://symbols.nuget.org/download/symbols" },
+    });
+    const { calls } = settings(held, { "PUT /repositories/nuget-org": { json: held } });
+
+    expect(await screen.findByText("Protocol")).toBeVisible();
+    expect(screen.getByText("V3")).toBeVisible();
+    expect(screen.queryByRole("radio", { name: "V2" })).toBeNull(); // chosen once
+    expect(screen.getByLabelText("Symbol server")).toHaveValue(
+      "https://symbols.nuget.org/download/symbols",
+    );
+    await user.click(screen.getByRole("checkbox", { name: "Online" }));
+    await user.click(save());
+
+    await waitFor(() => expect(of(calls, "PUT")).toHaveLength(1));
+    expect(of(calls, "PUT")[0]?.body).toMatchObject({
+      online: false,
+      format_config: { protocol: "v3", symbol_url: "https://symbols.nuget.org/download/symbols" },
+    });
+  });
+
   test("delete the repository only for whoever types its name, and say what goes with it (R9)", async () => {
     const user = userEvent.setup();
     const { calls } = settings(RELEASES, { "DELETE /repositories/releases": { status: 204 } });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `frontend/`): `pnpm vitest run src/lib/repository-form.test.ts src/screens/administration.test.tsx`
Expected: 11 failed, 138 passed: NuGet is no format of the form's, a hosted one is given `allow_redeploy`, and a proxy has neither a protocol nor a symbol server.

- [ ] **Step 3: Write the code**

Change `frontend/src/lib/repository-form.ts`:

```diff
@@ -9,7 +9,17 @@ import type { RepositoryCreate, RepositoryOut, RepositoryUpdate } from "@/lib/ap
 import { isAddressable } from "@/lib/paths";
 
 /** The formats the server has. Each can be hosted, a proxy or a group. */
-export const FORMATS = ["raw", "maven", "npm", "pypi", "docker", "apt", "yum", "apk"] as const;
+export const FORMATS = [
+  "raw",
+  "maven",
+  "npm",
+  "pypi",
+  "docker",
+  "apt",
+  "yum",
+  "apk",
+  "nuget",
+] as const;
 /** The formats whose indexes are signed: a key of their own, and a remote's keys for a proxy. */
 export const SIGNED: ReadonlySet<string> = new Set(["apt", "yum", "apk"]);
 export const TYPES = ["hosted", "proxy", "group"] as const;
@@ -24,6 +34,8 @@ export const DEFAULT_BLOB_STORE = "default";
 export const DEFAULT_SUITE = "stable";
 /** How many directories down a YUM repository's metadata may be. */
 export const DEPTH_MOST = 5;
+/** The protocols a NuGet proxy speaks to its remote, and serves: chosen once. */
+export const PROTOCOLS = ["v3", "v2"] as const;
 
 // The server's rule for a name, said before the request is made.
 const NAME = /^[A-Za-z0-9_.-]{1,64}$/;
@@ -63,6 +75,10 @@ export type Draft = {
   repodataDepth: string;
   /** A proxy's remote's public keys, as they are pasted. */
   remoteKeys: string;
+  /** A NuGet proxy's protocol: v3 or v2. Chosen once. */
+  protocol: string;
+  /** The symbol server a NuGet proxy passes symbol requests on to; empty for none. */
+  symbolUrl: string;
 };
 
 /** A form for a repository that is not there yet: the server's own defaults. */
@@ -90,6 +106,8 @@ export const EMPTY: Draft = {
   suite: DEFAULT_SUITE,
   repodataDepth: "0",
   remoteKeys: "",
+  protocol: "v3",
+  symbolUrl: "",
 };
 
 const text = (value: unknown, otherwise: string): string =>
@@ -126,20 +144,23 @@ export function draftOf(repository: RepositoryOut): Draft {
       typeof config.repodata_depth === "number" ? config.repodata_depth : EMPTY.repodataDepth,
     ),
     remoteKeys: text(config.remote_keys, EMPTY.remoteKeys),
+    protocol: text(config.protocol, EMPTY.protocol),
+    symbolUrl: text(config.symbol_url, EMPTY.symbolUrl),
   };
 }
 
 /**
  * The deployment policy of a hosted repository: the one that was chosen, or the one the
  * server gives a repository that names none. A Maven repository for releases refuses to
- * replace what was deployed (a release is deployed once); every other one allows it.
+ * replace what was deployed (a release is deployed once), and so does a NuGet one (a
+ * version is pushed once, as nuget.org takes it); every other one allows it.
  */
 export function policyOf(
   draft: Pick<Draft, "format" | "versionPolicy" | "deploymentPolicy">,
 ): string {
   if (draft.deploymentPolicy !== null) return draft.deploymentPolicy;
   const releases = draft.format === "maven" && draft.versionPolicy === "release";
-  return releases ? "disable_redeploy" : "allow_redeploy";
+  return releases || draft.format === "nuget" ? "disable_redeploy" : "allow_redeploy";
 }
 
 /** Whether a combination has settings of the format's own: a Maven repository that stores. */
@@ -157,6 +178,11 @@ export function hasSigningKey(repository: { format: string; type: string }): boo
   return repository.type !== "proxy" && SIGNED.has(repository.format);
 }
 
+/** Whether a combination has a NuGet proxy's settings: its protocol and its symbol server. */
+export function isNuGetProxy(draft: { format: string; type: string }): boolean {
+  return draft.format === "nuget" && draft.type === "proxy";
+}
+
 /** A whole number of at least `minimum`, or null for what is none. */
 function whole(typed: string, minimum: number): number | null {
   if (!/^-?\d{1,9}$/.test(typed.trim())) return null;
@@ -185,7 +211,8 @@ export type Problem =
   | "usernameNeeded"
   | "secretNeeded"
   | "suiteRule"
-  | "depthRule";
+  | "depthRule"
+  | "symbolUrlRule";
 
 export type Problems = Partial<
   Record<
@@ -197,7 +224,8 @@ export type Problems = Partial<
     | "authUsername"
     | "authSecret"
     | "suite"
-    | "repodataDepth",
+    | "repodataDepth"
+    | "symbolUrl",
     Problem
   >
 >;
@@ -225,6 +253,9 @@ export function problemsOf(draft: Draft, creating: boolean): Problems {
     if (draft.authType !== "none" && draft.authSecret === "" && !draft.hasSecret) {
       problems.authSecret = "secretNeeded";
     }
+    if (isNuGetProxy(draft) && draft.symbolUrl.trim() !== "" && !isRemote(draft.symbolUrl)) {
+      problems.symbolUrl = "symbolUrlRule";
+    }
   }
   // Chosen once: a repository that is there has the one it was made with.
   if (creating && draft.type === "hosted") {
@@ -282,6 +313,11 @@ function formatConfig(draft: Draft): Record<string, unknown> {
     return { version_policy: draft.versionPolicy, layout_policy: draft.layoutPolicy };
   }
   if (takesRemoteKeys(draft)) return { remote_keys: draft.remoteKeys };
+  if (isNuGetProxy(draft)) {
+    // Its protocol is sent as it is held: the server refuses to change it.
+    const symbolUrl = draft.symbolUrl.trim();
+    return { protocol: draft.protocol, ...(symbolUrl ? { symbol_url: symbolUrl } : {}) };
+  }
   if (draft.type !== "hosted") return {};
   if (draft.format === "apt") return { suite: draft.suite.trim() };
   if (draft.format === "yum") return { repodata_depth: whole(draft.repodataDepth, 0) ?? 0 };
```

Change `frontend/src/screens/repository-settings.tsx`:

```diff
@@ -50,9 +50,11 @@ import {
   FORMATS,
   hasMavenSettings,
   hasSigningKey,
+  isNuGetProxy,
   LAYOUT_POLICIES,
   policyOf,
   problemsOf,
+  PROTOCOLS,
   takesRemoteKeys,
   TYPES,
   updateBody,
@@ -87,6 +89,8 @@ const REFUSED_AT = [
   "format_config.suite",
   "format_config.repodata_depth",
   "format_config.remote_keys",
+  "format_config.protocol",
+  "format_config.symbol_url",
 ] as const;
 
 function useMay(): (permission: string) => boolean {
@@ -261,9 +265,25 @@ function RepositoryForm({
           <>
             <fieldset className={SECTION}>
               <legend className={LEGEND}>{t("sections.remote")}</legend>
+              {/* Chosen once: a repository that is there shows it as a fact. */}
+              {creating && isNuGetProxy(draft) ? (
+                <ChoiceGroup
+                  legend={t("fields.protocol")}
+                  value={draft.protocol}
+                  onChange={(value) => set({ protocol: value })}
+                  options={option("protocols", PROTOCOLS)}
+                />
+              ) : null}
+              {refused.at["format_config.protocol"] ? (
+                <Alert tone="danger">{refused.at["format_config.protocol"]}</Alert>
+              ) : null}
               <TextField
                 label={t("fields.remoteUrl")}
-                hint={t("hints.remoteUrl")}
+                hint={
+                  isNuGetProxy(draft)
+                    ? t(`hints.remoteUrlOf.${draft.protocol === "v2" ? "v2" : "v3"}`)
+                    : t("hints.remoteUrl")
+                }
                 type="url"
                 required
                 spellCheck={false}
@@ -301,6 +321,18 @@ function RepositoryForm({
                   onChange={(event) => set({ authSecret: event.target.value })}
                 />
               ) : null}
+              {isNuGetProxy(draft) ? (
+                <TextField
+                  label={t("fields.symbolUrl")}
+                  hint={t("hints.symbolUrl")}
+                  type="url"
+                  spellCheck={false}
+                  autoComplete="off"
+                  value={draft.symbolUrl}
+                  error={wrong("symbolUrl", refused.at["format_config.symbol_url"])}
+                  onChange={(event) => set({ symbolUrl: event.target.value })}
+                />
+              ) : null}
               {takesRemoteKeys(draft) ? (
                 <TextAreaField
                   label={t("fields.remoteKeys")}
@@ -652,6 +684,11 @@ export function RepositorySettingsScreen() {
           {found.type === "hosted" && found.format === "yum" ? (
             <Fact name={t("fields.repodataDepth")}>{draftOf(found).repodataDepth}</Fact>
           ) : null}
+          {isNuGetProxy(found) ? (
+            <Fact name={t("fields.protocol")}>
+              {t(`protocols.${draftOf(found).protocol === "v2" ? "v2" : "v3"}`)}
+            </Fact>
+          ) : null}
           {view.data ? (
             <Fact name={t("fields.address")} copy={view.data.url} mono>
               {view.data.url}
```

Change `frontend/messages/en.json`:

```diff
@@ -682,7 +682,9 @@
       "layoutPolicy": "Layout policy",
       "suite": "Suite",
       "repodataDepth": "Depth of the metadata",
-      "remoteKeys": "The remote's public keys"
+      "remoteKeys": "The remote's public keys",
+      "protocol": "Protocol",
+      "symbolUrl": "Symbol server"
     },
     "hints": {
       "name": "Letters, digits and . _ - , up to 64. It is part of every address, and cannot be changed later.",
@@ -705,7 +707,12 @@
         "apt": "ASCII-armoured OpenPGP keys, those the remote signs its Release files with. A group checks what this proxy fetched with them: without them, it cannot be a member of one.",
         "yum": "ASCII-armoured OpenPGP keys, those the remote signs its repomd.xml with, if it does. A group checks what this proxy fetched with them. They are not needed: dnf checks each package's own signature.",
         "apk": "PEM RSA public keys, those the remote signs its indexes with: Alpine's are in /usr/share/apk/keys. A group checks what this proxy fetched with them: without them, it cannot be a member of one."
-      }
+      },
+      "remoteUrlOf": {
+        "v3": "The feed's service index: https://api.nuget.org/v3/index.json for nuget.org.",
+        "v2": "The feed's address: https://community.chocolatey.org/api/v2/ for Chocolatey's, https://www.powershellgallery.com/api/v2/ for the PowerShell Gallery."
+      },
+      "symbolUrl": "Optional. A symbol server whose PDBs this proxy passes on to debuggers, and keeps: https://symbols.nuget.org/download/symbols for nuget.org's packages."
     },
     "sections": {
       "hosted": "What it takes",
@@ -767,7 +774,8 @@
       "usernameNeeded": "Give the user name.",
       "secretNeeded": "Give it: none is stored.",
       "suiteRule": "A suite is 1 to 64 letters, digits or . _ - , and begins with a letter or a digit.",
-      "depthRule": "A whole number from 0 to 5."
+      "depthRule": "A whole number from 0 to 5.",
+      "symbolUrlRule": "Give an http or https address with a host, and without credentials, a query or a fragment, or none."
     },
     "mayNotCreate": "You may not create repositories.",
     "create": "Create repository",
@@ -801,7 +809,15 @@
     "deleteBodyGroup": "Every client that uses its address is refused. Its members are not touched. This cannot be undone.",
     "deleted": "Deleted the repository {name}.",
     "leftOutTitle": "Members left out",
-    "leftOutIntro": "A check found what these proxies fetched wanting. The group answers without each one until it next reaches its remote."
+    "leftOutIntro": "A check found what these proxies fetched wanting. The group answers without each one until it next reaches its remote.",
+    "protocols": {
+      "v3": "V3",
+      "v2": "V2"
+    },
+    "protocolsHints": {
+      "v3": "A feed of NuGet's V3 protocol, as nuget.org's: for dotnet, nuget.exe, choco and PSResourceGet. It cannot be changed later.",
+      "v2": "A feed of the V2 protocol, as the Chocolatey community feed and the PowerShell Gallery: it serves V2 alone. It cannot be changed later."
+    }
   },
   "blobStores": {
     "title": "Blob stores",
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `frontend/`): `pnpm vitest run src/lib/repository-form.test.ts src/screens/administration.test.tsx`
Expected: 149 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src frontend/messages
git commit -m "feat(ui): NuGet in the repository form: a version pushed once, a proxy's protocol and symbol server"
```

---

### Task 2: NuGet in every list, and its uploads

**Files:**
- Modify: `frontend/src/screens/upload.tsx`, `frontend/src/lib/content.ts`, `frontend/src/components/permission-rows.tsx`, `frontend/messages/en.json`
- Modify (tests): `frontend/src/screens/upload.test.tsx`, `frontend/src/components/security.test.tsx`

**Interfaces:**
- Consumes: Task 1's messages file; the upload form's `UPLOADABLE`, `SEVERAL`, `ACCEPTED`.
- Produces: NuGet among the formats that take an upload (`.nupkg,.snupkg`, several at once, no directory), among the permissions' formats, and the messages `upload.intro.nuget` and `upload.hints.files.nuget`.

- [ ] **Step 1: Write the failing tests**

Change `frontend/src/screens/upload.test.tsx`:

```diff
@@ -388,6 +388,23 @@ describe("uploading to APT, YUM and apk", () => {
       ["directory", "v3.24/main/x86_64"],
     ]);
   });
+  test("NuGet takes packages and symbol packages, several at once", async () => {
+    const user = userEvent.setup();
+    const { uploads } = at("nuget", "/upload/nuget-own");
+    const files = await screen.findByLabelText("Files");
+
+    expect(screen.queryByLabelText("Directory")).toBeNull(); // where its .nuspec says
+    expect(files).toHaveAttribute("multiple");
+    expect(files).toHaveAttribute("accept", ".nupkg,.snupkg");
+    expect(files).toHaveAccessibleDescription(".nupkg and .snupkg files.");
+    await user.upload(files, [file("Hello.1.0.0.nupkg"), file("Hello.1.0.0.snupkg")]);
+    await user.click(send());
+
+    expect(uploads[0]?.parts).toEqual([
+      ["file", "file:Hello.1.0.0.nupkg"],
+      ["file", "file:Hello.1.0.0.snupkg"],
+    ]);
+  });
 });
 
 describe("where nothing can be uploaded", () => {
@@ -431,6 +448,7 @@ describe("choosing where to upload", () => {
     repository("debs", "apt"),
     repository("rpms", "yum"),
     repository("alpine", "apk"),
+    repository("nuget-own", "nuget"),
   ];
 
   test("offers the hosted repositories that take one", async () => {
@@ -445,6 +463,7 @@ describe("choosing where to upload", () => {
       "/upload/debs",
       "/upload/rpms",
       "/upload/alpine",
+      "/upload/nuget-own",
     ]);
     await expectAccessible();
   });
```

Change `frontend/src/components/security.test.tsx`:

```diff
@@ -103,6 +103,7 @@ describe("permissions as rows (A2)", () => {
       "docker",
       "maven",
       "npm",
+      "nuget",
       "pypi",
       "raw",
       "yum",
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `frontend/`): `pnpm vitest run src/screens/upload.test.tsx src/components/security.test.tsx`
Expected: 3 failed, 42 passed: NuGet takes no upload, and is not among the permissions' formats.

- [ ] **Step 3: Write the code**

Change `frontend/src/screens/upload.tsx`:

```diff
@@ -27,19 +27,20 @@ import { askAgainIfChanged, useSession } from "@/lib/session/session";
 import { NothingHere } from "@/screens/not-found";
 
 // The formats the form knows: each has its fields, and its texts in the messages.
-const UPLOADABLE = ["raw", "maven", "npm", "pypi", "apt", "yum", "apk"] as const;
+const UPLOADABLE = ["raw", "maven", "npm", "pypi", "apt", "yum", "apk", "nuget"] as const;
 type Uploadable = (typeof UPLOADABLE)[number];
 // Those whose files are put in a directory that is chosen. An APT package's place is
 // its pool path, which the package says.
 const IN_A_DIRECTORY = new Set(["raw", "yum", "apk"]);
 // Those that take several files at once, and the files each takes.
-const SEVERAL = new Set(["raw", "pypi", "apt", "yum", "apk"]);
+const SEVERAL = new Set(["raw", "pypi", "apt", "yum", "apk", "nuget"]);
 const ACCEPTED: Partial<Record<string, string>> = {
   npm: ".tgz,.tar.gz",
   pypi: ".whl,.tar.gz,.zip",
   apt: ".deb",
   yum: ".rpm",
   apk: ".apk",
+  nuget: ".nupkg,.snupkg",
 };
 
 function isUploadable(format: string): format is Uploadable {
```

Change `frontend/src/lib/content.ts`:

```diff
@@ -27,7 +27,7 @@ const CONTENT = "content";
 export const FOLDER_AT_ONCE = 100;
 export const RESULTS_AT_ONCE = 50;
 // The formats whose hosted repositories take an upload through the API.
-const UPLOADABLE = new Set(["raw", "maven", "npm", "pypi", "apt", "yum", "apk"]);
+const UPLOADABLE = new Set(["raw", "maven", "npm", "pypi", "apt", "yum", "apk", "nuget"]);
 
 const at = (repository: string) => `/content/${encodeURIComponent(repository)}`;
 
```

Change `frontend/src/components/permission-rows.tsx`:

```diff
@@ -22,7 +22,7 @@ import {
 
 const KINDS: readonly RowKind[] = ["repository", "admin", "all", "typed"];
 // The formats there are, whether or not a repository of each exists yet.
-const FORMATS = ["raw", "maven", "npm", "pypi", "docker", "apt", "yum", "apk"];
+const FORMATS = ["raw", "maven", "npm", "pypi", "docker", "apt", "yum", "apk", "nuget"];
 
 /** A repository, as far as a permission is concerned: what it is called and its format. */
 export type Held = { name: string; format: string };
```

Change `frontend/messages/en.json`:

```diff
@@ -273,7 +273,8 @@
       "pypi": "Wheels and source distributions. Each one's name says its project and version.",
       "apt": "Debian packages. Each is kept in the pool by its name, version and architecture, and the indexes follow by themselves.",
       "yum": "RPM packages, stored under a directory by their own names. The metadata follows by itself.",
-      "apk": "apk packages, stored in the directory of their architecture. The index follows by itself."
+      "apk": "apk packages, stored in the directory of their architecture. The index follows by itself.",
+      "nuget": "NuGet packages and their symbol packages, each stored where its .nuspec says: packages first, a symbol package beside its package."
     },
     "fields": {
       "directory": "Directory",
@@ -308,7 +309,8 @@
         "pypi": ".whl, .tar.gz or .zip.",
         "apt": ".deb files.",
         "yum": ".rpm files.",
-        "apk": ".apk files."
+        "apk": ".apk files.",
+        "nuget": ".nupkg and .snupkg files."
       },
       "directoryOf": {
         "yum": "Where in the repository the packages go: at least as deep as its metadata.",
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `frontend/`): `pnpm vitest run src/screens/upload.test.tsx src/components/security.test.tsx`
Expected: 45 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src frontend/messages
git commit -m "feat(ui): NuGet's uploads, and NuGet among the formats of permissions"
```

---

### Task 3: In the browser, and the guide

**Files:**
- Modify (tests): `frontend/e2e/ui.spec.ts`
- Modify: `docs/web-ui.md`

**Interfaces:**
- Consumes: Tasks 1 and 2, and the server's NuGet, through the built images; the e2e file's `page`, `createRepository`, `expectAccessibleInBothModes`, and the order of its tests (this one comes after the apk proxy's, before the repositories are listed for accessibility).
- Produces: the constants `NUGET`, `GALLERY`, `PDB_GUID`, `PDB`, and the helpers `crc32`, `zipOf`, `nuspecOf`, which write a NuGet package in the test.

- [ ] **Step 1: Write the test**

It is of what Tasks 1 and 2 made, through the gateway and the built images: a V2 proxy of NuGet made in the form with its symbol server, its protocol a fact once it is made; a hosted one given, by the upload form, a symbol package and its package (chosen in that order) that the test writes, its PDB then at its key; and the repository's page with its Chocolatey, PowerShell and Symbols snippets, accessible in both modes.

Change `frontend/e2e/ui.spec.ts`:

```diff
@@ -27,6 +27,8 @@ const STORED = "browser-test-stored";
 const REMOTE_SECRET = "the-remote-s-own-secret";
 const DEBS = "browser-test-debs";
 const ALPINE = "browser-test-alpine";
+const NUGET = "browser-test-nuget";
+const GALLERY = "browser-test-gallery";
 // A remote's public key, as Alpine publishes its own: PEM RSA.
 const REMOTE_KEY = `-----BEGIN PUBLIC KEY-----
 MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwh4+mF9v0dj392qnTja8
@@ -42,6 +44,82 @@ kQIDAQAB
 const ODD = "a b#c%.txt";
 const UPLOADS = "**/api/v1/content/*/upload";
 
+// --- NuGet packages, made here: a zip of stored files ------------------------------------
+
+const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
+  let c = n;
+  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
+  return c >>> 0;
+});
+
+function crc32(data: Buffer): number {
+  let crc = 0xffffffff;
+  for (const byte of data) crc = (CRC_TABLE[(crc ^ byte) & 0xff] as number) ^ (crc >>> 8);
+  return (crc ^ 0xffffffff) >>> 0;
+}
+
+/** A zip of the files, each stored as it is: what a package's reader reads. */
+function zipOf(files: Record<string, Buffer>): Buffer {
+  const locals: Buffer[] = [];
+  const centrals: Buffer[] = [];
+  let offset = 0;
+  for (const [name, data] of Object.entries(files)) {
+    const nameBytes = Buffer.from(name);
+    const crc = crc32(data);
+    const local = Buffer.alloc(30);
+    local.writeUInt32LE(0x04034b50, 0);
+    local.writeUInt16LE(20, 4);
+    local.writeUInt32LE(crc, 14);
+    local.writeUInt32LE(data.length, 18);
+    local.writeUInt32LE(data.length, 22);
+    local.writeUInt16LE(nameBytes.length, 26);
+    const central = Buffer.alloc(46);
+    central.writeUInt32LE(0x02014b50, 0);
+    central.writeUInt16LE(20, 4);
+    central.writeUInt16LE(20, 6);
+    central.writeUInt32LE(crc, 16);
+    central.writeUInt32LE(data.length, 20);
+    central.writeUInt32LE(data.length, 24);
+    central.writeUInt16LE(nameBytes.length, 28);
+    central.writeUInt32LE(offset, 42);
+    locals.push(local, nameBytes, data);
+    centrals.push(central, nameBytes);
+    offset += 30 + nameBytes.length + data.length;
+  }
+  const directory = Buffer.concat(centrals);
+  const end = Buffer.alloc(22);
+  end.writeUInt32LE(0x06054b50, 0);
+  end.writeUInt16LE(Object.keys(files).length, 8);
+  end.writeUInt16LE(Object.keys(files).length, 10);
+  end.writeUInt32LE(directory.length, 12);
+  end.writeUInt32LE(offset, 16);
+  return Buffer.concat([...locals, directory, end]);
+}
+
+function nuspecOf(id: string, version: string, types = ""): Buffer {
+  return Buffer.from(
+    '<?xml version="1.0" encoding="utf-8"?>' +
+      '<package xmlns="http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd"><metadata>' +
+      `<id>${id}</id><version>${version}</version><authors>MegooArti</authors>` +
+      `<description>Says hello in the browser.</description>${types}</metadata></package>`,
+  );
+}
+
+// A portable PDB, as far as a symbol server reads it: its metadata root, and a #Pdb
+// stream that begins with its id (a GUID, then a stamp).
+const PDB_GUID = "201d67afc77a4cd5a6668a65b7b7382d";
+const PDB = Buffer.concat([
+  Buffer.from("BSJB"),
+  Buffer.from([1, 0, 1, 0, 0, 0, 0, 0, 12, 0, 0, 0]),
+  Buffer.from("PDB v1.0\0\0\0\0"),
+  Buffer.from([0, 0, 1, 0]),
+  Buffer.from([48, 0, 0, 0, 30, 0, 0, 0]),
+  Buffer.from("#Pdb\0\0\0\0"),
+  Buffer.from("af671d207ac7d54ca6668a65b7b7382d", "hex"),
+  Buffer.from([1, 0, 0, 0]),
+  Buffer.from("debug info"),
+]);
+
 test.describe.configure({ mode: "serial" });
 
 let context: BrowserContext;
@@ -1409,6 +1487,69 @@ test("a proxy of apk is given its remote's keys, and keeps them when it is saved
   expect(saved.format_config).toEqual({ remote_keys: REMOTE_KEY });
 });
 
+test("a NuGet proxy is made with its protocol and its symbol server, and a hosted one takes a package and its symbols", async () => {
+  await page.goto("/admin/repositories/~new");
+  await page.getByLabel("Format").selectOption("nuget");
+  await page.getByLabel("Name", { exact: true }).fill(GALLERY);
+  await page.getByRole("radio", { name: "Proxy" }).check();
+  await expect(page.getByRole("radio", { name: "V3" })).toBeChecked();
+  await page.getByRole("radio", { name: "V2" }).check();
+  await page.getByLabel("Remote address").fill("https://www.powershellgallery.com/api/v2/");
+  await page.getByLabel("Symbol server").fill("https://symbols.nuget.org/download/symbols");
+  await page.getByRole("button", { name: "Create repository" }).click();
+
+  await expect(page.getByRole("heading", { level: 1, name: GALLERY })).toBeVisible();
+  // Chosen once: a fact now, and not a choice that would be tried.
+  await expect(page.getByRole("radio", { name: "V2" })).toHaveCount(0);
+  await expect(page.getByText("V2", { exact: true })).toBeVisible();
+  const made = await (await page.request.get(`/api/v1/repositories/${GALLERY}`)).json();
+  expect(made.format_config).toEqual({
+    protocol: "v2",
+    symbol_url: "https://symbols.nuget.org/download/symbols",
+  });
+
+  await createRepository({ name: NUGET, format: "nuget", type: "hosted" });
+  await page.goto(`/upload/${NUGET}`);
+  const symbols = '<packageTypes><packageType name="SymbolsPackage"/></packageTypes>';
+  await page.getByLabel("Files").setInputFiles([
+    {
+      name: "Hello.1.0.0.snupkg",
+      mimeType: "application/octet-stream",
+      buffer: zipOf({
+        "MegooArti.Browser.nuspec": nuspecOf("MegooArti.Browser", "1.0.0", symbols),
+        "lib/net8.0/Hello.pdb": PDB,
+      }),
+    },
+    {
+      name: "Hello.1.0.0.nupkg",
+      mimeType: "application/octet-stream",
+      buffer: zipOf({ "MegooArti.Browser.nuspec": nuspecOf("MegooArti.Browser", "1.0.0") }),
+    },
+  ]);
+  await page.getByRole("button", { name: "Upload" }).click();
+  // Packages first, a symbol package beside its package, whatever order they were chosen in.
+  await expect(page.getByText("2 files stored")).toBeVisible();
+  const key = `hello.pdb/${PDB_GUID}FFFFFFFF/hello.pdb`;
+  expect((await page.request.get(`/repository/${NUGET}/symbols/${key}`)).status()).toBe(200);
+
+  // How each client is given it is on its page, with the address a client is given.
+  await page.goto(`/browse/${NUGET}`);
+  await expect(page.getByRole("heading", { name: "Set up a machine" })).toBeVisible();
+  const origin = new URL(page.url()).origin;
+  await expect(page.getByRole("figure").filter({ hasText: "choco source add" })).toContainText(
+    `${origin}/repository/${NUGET}/`,
+  );
+  await expect(
+    page.getByRole("figure").filter({ hasText: "Register-PSResourceRepository" }),
+  ).toContainText(`${origin}/repository/${NUGET}/index.json`);
+  await expect(page.getByRole("figure").filter({ hasText: "dotnet-symbol" })).toContainText(
+    `${origin}/repository/${NUGET}/symbols/`,
+  );
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByRole("heading", { name: "Set up a machine" })).toBeVisible();
+  });
+});
+
 test("the screens that list and make repositories meet WCAG 2.1 AA in both modes", async () => {
   await page.goto("/admin/repositories");
   await expectAccessibleInBothModes(async () => {
```

- [ ] **Step 2: Write the guide**

Change `docs/web-ui.md`:

```diff
@@ -10,21 +10,24 @@ repositories, blob stores and the installation's own settings.
   type and four checksums (each with a button that copies it), who stored it and when,
   and a download link. Every folder and file has an address of its own, so a link to
   one can be shared. A group lists its members. A proxy shows what has been fetched
-  through it so far. An APT, YUM or apk repository also says how a machine is set up
-  to use it: its key, its address and the account it signs in with, as commands to
-  copy, with what is yours to fill in between angle brackets.
+  through it so far. An APT, YUM, apk or NuGet repository also says how a machine is
+  set up to use it: its key, its address and the account it signs in with, as commands
+  to copy, with what is yours to fill in between angle brackets. A NuGet repository's
+  are for `dotnet` and `nuget.config`, Chocolatey, PowerShell, and a debugger's symbols.
 - **A component's page** says what a package version is, lists its files, and gives
   what to paste into a build or a shell to use it (for Maven, the dependency for
-  Maven and for Gradle), each with a copy button.
+  Maven and for Gradle; for NuGet, `dotnet`, a `PackageReference`, Chocolatey and
+  PowerShell), each with a copy button.
 - **Search** is a box in the header of every screen: press `/` to reach it. The
   results page filters by format, repository, group, name and version, and by a
   file's checksum: paste an MD5, SHA-1, SHA-256 or SHA-512, and its length says which
   it is. A search is in the address, so it can be shared and gone back to. Search
   looks in hosted and proxy repositories: what a group serves is found in its members.
-- **Upload** is offered for a hosted Raw, Maven, npm, PyPI, APT, YUM or apk
+- **Upload** is offered for a hosted Raw, Maven, npm, PyPI, APT, YUM, apk or NuGet
   repository to whoever may add to it, from the repository ("Upload here") and
-  from the navigation. The form has the fields the format needs: none for APT,
-  whose packages say where they go, and a directory for YUM and apk. Files are
+  from the navigation. The form has the fields the format needs: none for APT and
+  NuGet, whose packages say where they go (a NuGet symbol package goes beside its
+  package, whichever is chosen first), and a directory for YUM and apk. Files are
   chosen, or dropped onto a file field. It shows how much has been sent, and can be
   stopped. What the server refuses about a field is said at that field, which then
   has the keyboard; anything else is said above the button. A Docker image is
@@ -67,10 +70,12 @@ repositories, blob stores and the installation's own settings.
     does when the remote fails; a group has its members, put in order with buttons;
     a hosted or proxy Maven repository has a version policy and a layout policy; a
     hosted APT repository has its suite, a hosted YUM repository the depth of its
-    metadata, and a proxy of APT, YUM or apk its remote's public keys, which a group
-    checks it with. What cannot change later (name, format, type, blob store,
-    version policy, suite, depth of the metadata) is shown as it is and not as a
-    field, beside the address the repository's clients use. A proxy's secret is
+    metadata, a proxy of APT, YUM or apk its remote's public keys, which a group
+    checks it with, and a NuGet proxy its protocol (V3, or V2 for the Chocolatey
+    community feed and the PowerShell Gallery) and a symbol server to pass on. A
+    hosted NuGet repository takes a version once unless another policy is chosen. What
+    cannot change later (name, format, type, blob store, version policy, suite, depth
+    of the metadata, a NuGet proxy's protocol) is shown as it is and not as a field, beside the address the repository's clients use. A proxy's secret is
     typed and never shown: leave the field empty to keep the one that is stored. A
     repository's page also shows a proxy's state and last error, has it check
     everything with its remote again, rebuilds the index, and deletes the
```

- [ ] **Step 3: Run the tests**

Run (in `backend/`): `uv run pytest -m docker tests/test_ui_client.py -q`
Expected: 12 passed (the browser's tests are one of them: Playwright's run of `frontend/e2e/`, this task's among them).

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/ui.spec.ts docs/web-ui.md
git commit -m "test(ui): a NuGet proxy made in the form, a package and its symbols uploaded, and the setup snippets; docs: NuGet in the web UI"
```

---

### Task 4: The spec, and every suite

**Files:**
- Modify: `docs/superpowers/specs/2026-10-15-nuget-design.md`

- [ ] **Step 1: Write what this plan settled into the spec**

Change `docs/superpowers/specs/2026-10-15-nuget-design.md`:

```diff
@@ -215,6 +215,15 @@ A package client signs in with an API token: as the `X-NuGet-ApiKey` header (wha
 | S10 | A key is matched without regard to case, and served as it is kept: its name and GUID in lower case, then `FFFFFFFF`. | Symbol servers match keys so; a debugger may ask in the module's own case. |
 | S11 | A proxy's symbol server failing does not count towards leaving the proxy's remote alone (`Source(blocks=False)`, which the engine now honours for a download as for a document); the failure is recorded. | One `503` of symbols.nuget.org blocked the proxy's packages, and debuggers ask for a PDB of every module. |
 
+### Settled while building plan 13g
+
+| # | What | Why |
+| --- | --- | --- |
+| U1 | The repository form has NuGet: a hosted one's deployment policy is `disable_redeploy` until another is chosen, as the server gives one (D6); a proxy chooses its protocol once (V3, the default, or V2), shown as a fact after, and may name a symbol server, checked as a remote's address is, and sent only when one is given; a group of NuGet has its members. The remote's hint says what a V3 and a V2 feed's address is. | X6, Z6 and S4, as an administrator meets them. |
+| U2 | NuGet is in every list of formats: the form's, the permissions' rows, and those that take an upload. An upload takes `.nupkg` and `.snupkg` files, several at once, and no directory: each goes where its `.nuspec` says, packages before symbol packages (W7). | W7. |
+| U3 | A NuGet repository's page has the setup snippets the server gives (W10, Z6, S7): `dotnet`, `nuget.config`, Chocolatey, PowerShell and Symbols; a version's page its usage. The UI shows them as it shows every format's: it writes none of its own. | One place says how a machine is set up: the server. |
+| U4 | The browser test makes a V2 proxy of NuGet in the form, and uploads to a hosted one a package and its symbol package that it writes itself (a zip of stored files, and a portable PDB), and finds the PDB at its key; then the setup snippets and their accessibility. | Section 10's browser tests. |
+
 ## 5. Hosted repositories
 
 - **Push:** `PUT api/v2/package` with the package as `multipart/form-data` (as every client sends it). The server reads the zip's central directory and its `.nuspec` (bounded, section 9): `id`, `version`, `title`, `authors`, `owners`, `description`, `summary`, `releaseNotes`, `copyright`, `language`, `tags`, `projectUrl`, `license` and `licenseUrl`, `icon` and `iconUrl`, `readme`, `requireLicenseAcceptance`, `developmentDependency`, `minClientVersion`, `packageTypes`, and `dependencies` by target framework; and the package's SHA-512. A file that is not a NuGet package, or whose `.nuspec` has no id or no valid version, is refused with `400 invalid_package`. The package is stored at `v3/package/<id>/<version>/<id>.<version>.nupkg` (lower case, E2), and its `.nuspec` beside it.
```

- [ ] **Step 2: Run every suite**

Run (in `frontend/`): `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: each passes; 843 tests.

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: All checks passed; 3890 passed, 2 skipped (this plan changes nothing there).

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: every container test passes, Task 3's among them.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs
git commit -m "docs: what plan 13g settled"
```
