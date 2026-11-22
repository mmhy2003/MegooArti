# MA-1 implementation plan: sidebar layout and the Cyberpunk theme

**Goal.** The web UI's navigation moves into a collapsible sidebar beside a sticky header. Below 1024 px it is a drawer. The colours and typefaces become those of the KB's "Cyberpunk Theme" (rev 3), adjusted only where the project's contrast tests require it.

**Architecture.**
- **Theme.** `frontend/src/styles/tokens.css` stays the only place a colour is written. It takes the KB values under this project's own token names. `globals.css` maps them to Tailwind utilities, holds the three new font families and adds a `rail` custom variant.
- **Shell.** `AppShell` becomes: skip link, a sticky full-height sidebar (from `lg`), then a column with a sticky header and `<main>`. Below `lg` a Radix `Dialog` drawer holds the same navigation.
- **Rail.** The rail choice is kept in `localStorage["megooarti-sidebar"]` by the new `lib/sidebar.ts`. The same nonce'd head script that sets the mode writes it to `<html data-sidebar="rail">` before paint, and CSS follows the attribute.

**What the runner asked for.** Step 1, which adds `megoocolab.toml`, was asked for by the MegooColab runner, not by the design. The browser tests (`pnpm e2e`) need the whole stack (Postgres, backend, frontend, gateway), and the backend's tests need Postgres.

**One refinement of the design's file layout.** The design puts the pre-paint script and the React hook in one `lib/sidebar.ts`. But `app/layout.tsx` is a Server Component that imports the script. Next.js refuses a server-side import of a module that imports `useSyncExternalStore`, and a `"use client"` module would turn the string into a client reference. So the split is the one `lib/theme.ts` and `components/theme-provider.tsx` already have:
- `lib/sidebar.ts` has no React: the key, reading and storing the choice, the attribute, `subscribe` and the script.
- `lib/use-sidebar.ts` (`"use client"`) has the hook.

Nothing anyone sees changes.

## File map

| File | Status | Responsibility |
| --- | --- | --- |
| `megoocolab.toml` | new | Sets `ui` (whole stack) and `db` (Postgres) for the checks |
| `tools/test-services/ui.yml` | new | Compose override: backend and frontend images are always built from the tree |
| `tools/test-services/db.yml` | new | Postgres alone for the backend's tests |
| `scripts/ui-e2e.sh` | new | Reads admin's first password from the runner's stack, waits for the gateway, runs `pnpm e2e` |
| `docs/development.md` | modify | How to run the checks through `megoocolab-runner`. Later: nothing more |
| `frontend/src/styles/tokens.css` | modify | KB values, `neon-violet`/`ink-violet`, `lift`, KB `grid`. Removes `fg-subtle`, magenta and acid |
| `frontend/src/styles/tokens.test.ts` | modify | Contrast matrix on the new names, plus the KB-values tests |
| `frontend/src/styles/globals.css` | modify | `@theme` mapping, `shadow-lift`, fonts, `h1`–`h3`, `label-caps`, grid, selection, `scroll-padding-top`, `@custom-variant rail` |
| 19 components and screens using `fg-subtle` | modify | Use `fg-muted` instead |
| `browse.tsx`, `user-menu.tsx`, `ui/states.tsx`, `app-shell.tsx` | modify | Magenta and acid become violet or cyan |
| `ui/panel.tsx`, `ui/menu.tsx`, `ui/confirm-dialog.tsx` | modify | `shadow-lift`. `PageHeader` in sentence case |
| `frontend/src/fonts/*` | replace | Geist, Geist Mono, Orbitron 700 `woff2` files and their OFL licences |
| `frontend/src/lib/fonts.ts`, `frontend/src/lib/fonts.test.ts` (new) | modify/new | `next/font/local` for the three faces. A test that the files and licences are there |
| `frontend/src/app/layout.tsx` | modify | New font variables. Runs `THEME_SCRIPT` and `SIDEBAR_SCRIPT` in one `<script>` |
| `frontend/src/components/account-nav.tsx` | modify | Sentence case |
| `frontend/src/lib/sidebar.ts`, `sidebar.test.ts` | new | The rail choice and its pre-paint script |
| `frontend/src/lib/use-sidebar.ts` | new | `useSidebarRail()` hook |
| `frontend/src/test/setup.ts` | modify | Clears `data-sidebar` before each test |
| `frontend/src/components/app-shell.tsx`, `shell.test.tsx` | modify | The sidebar, rail, header and drawer |
| `frontend/messages/en.json` | modify | `app.collapseNavigation`, `app.expandNavigation` |
| `frontend/src/components/ui/more.test.tsx` | modify | `PageHeader` is no longer in capitals |
| `frontend/e2e/ui.spec.ts` | modify | Drawer, sidebar-beside-search test, and the rail test that runs before the UI's code |
| `docs/web-ui.md`, `docs/BRD.md`, `docs/superpowers/specs/2026-10-12-frontend-design.md`, `README.md`, `CHANGELOG.md` | modify | Documents |

All frontend commands run from `frontend/`. `pnpm format` runs before every commit; Prettier is checked by `pnpm lint`.

---

## Step 1. Add megoocolab.toml (asked for by the runner) and run the checks that need containers through it

The runner asked for this step, not the design. Two checks need containers:
- the browser tests (`frontend/e2e/`) need a fresh, whole installation;
- the backend's tests need Postgres.

Today the first are reached only through `uv run pytest -m docker`, which runs a stack of its own on fixed ports (18000, 15432). The second need `docker compose up db` on 5432.

**`megoocolab.toml`** (repository root):

```toml
# The containers the checks need, for megoocolab-runner: each run gets its own, on
# free ports, and they are removed when the check ends.
#   megoocolab-runner services run ui -- sh scripts/ui-e2e.sh
#   megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest'

[services.ui]
description = "The whole installation, built from this tree, fresh for the web UI's browser tests"
compose = ["docker-compose.yml", "tools/test-services/ui.yml"]
ports = ["MEGOOARTI_HTTP_PORT", "MEGOOARTI_DB_PORT"]

[services.ui.env]
MEGOOARTI_DB_PASSWORD = "only-for-the-browser-tests"
# The tag the images are built under: one of this run's own, never a release's.
MEGOOARTI_VERSION = "${MEGOOARTI_SERVICES_PROJECT}"
MEGOOARTI_UI_URL = "http://localhost:${MEGOOARTI_HTTP_PORT}"

[services.db]
description = "PostgreSQL for the backend's tests"
compose = ["tools/test-services/db.yml"]
ports = ["DB_PORT"]

[services.db.env]
MEGOOARTI_TEST_DATABASE_URL = "postgresql+asyncpg://megooarti:megooarti@localhost:${DB_PORT}/megooarti_test"
```

**`tools/test-services/ui.yml`**:

```yaml
# Added to docker-compose.yml for the checks (megoocolab.toml, set "ui"): the images
# are built from this working tree each time, never pulled.
services:
  backend:
    pull_policy: build
  frontend:
    pull_policy: build
```

**`tools/test-services/db.yml`**:

```yaml
# PostgreSQL alone, for the backend's tests (megoocolab.toml, set "db").
services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: megooarti
      POSTGRES_PASSWORD: megooarti
      POSTGRES_DB: megooarti
    ports:
      - "127.0.0.1:${DB_PORT}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U megooarti -d megooarti"]
      interval: 2s
      timeout: 3s
      retries: 30
```

**`scripts/ui-e2e.sh`** (LF endings, as `.gitattributes` requires):

```sh
#!/bin/sh
# The web UI's browser tests (frontend/e2e/) against a stack megoocolab-runner started
# from megoocolab.toml's "ui" set, which gives the variables used here:
#
#   megoocolab-runner services run ui -- sh scripts/ui-e2e.sh
#
# The tests begin with the first sign-in of a new installation: the runner makes a
# fresh stack for every run. Chromium must be installed once:
#   cd frontend && pnpm exec playwright install chromium
set -eu
cd "$(dirname "$0")/.."
: "${MEGOOARTI_SERVICES_PROJECT:?run this through: megoocolab-runner services run ui}"
# Not a developer's own .env beside docker-compose.yml.
export COMPOSE_ENV_FILES="$PWD/backend/tests/compose.env"
stack() {
  docker compose --project-name "$MEGOOARTI_SERVICES_PROJECT" \
    -f docker-compose.yml -f tools/test-services/ui.yml "$@"
}

# The password the backend made for admin when it first started.
tries=0
until MEGOOARTI_INITIAL_PASSWORD=$(stack exec -T backend cat /var/lib/megooarti/admin.password 2>/dev/null) \
  && [ -n "$MEGOOARTI_INITIAL_PASSWORD" ]; do
  tries=$((tries + 1))
  if [ "$tries" -ge 90 ]; then echo "the backend wrote no password for admin" >&2; exit 1; fi
  sleep 2
done
export MEGOOARTI_INITIAL_PASSWORD

# Until the gateway answers.
node -e 'const u = process.env.MEGOOARTI_UI_URL + "/healthz"; let n = 0;
(function t() { fetch(u).then((r) => (r.ok ? process.exit(0) : Promise.reject()))
  .catch(() => (++n < 90 ? setTimeout(t, 2000) : process.exit(1))); })();'

cd frontend
export CI=1
exec pnpm e2e
```

**`docs/development.md`**:
- Under "The backend": add that with `megoocolab-runner` the database comes from the `db` set: `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest'`.
- Under "Tests in a real browser": add that they can also be run against a fresh stack of their own with `megoocolab-runner services run ui -- sh scripts/ui-e2e.sh`, which builds the images from the working tree. `uv run pytest -m docker` still runs them as before.

**Prove it**, on the unchanged UI:
- `cd frontend && pnpm install && pnpm exec playwright install chromium`
- `megoocolab-runner services run ui -- sh scripts/ui-e2e.sh` → Playwright reports every test passed (66 or more), none failed or skipped.
- `megoocolab-runner services run db -- sh -c 'cd backend && uv sync && uv run pytest'` → passes.

If a set does not come up, fix the set's files, not the tests.

Commit: `chore(checks): megoocolab.toml, with the whole stack for the browser tests and Postgres for the backend's`

---

## Step 2. Tokens take the KB Cyberpunk values; fg-subtle, magenta and acid go; depth by lift and glow

**Test first**, in `frontend/src/styles/tokens.test.ts`:

1. `TEXT` becomes `["fg", "fg-muted", "ink-cyan", "ink-violet", "ink-ok", "ink-warn", "ink-bad"]`.
2. `SEEN` becomes `["line-strong", "neon-cyan", "neon-violet", "ok", "warn", "bad", "focus", "primary", "danger"]`.
3. Add after `colour()`:

```ts
// The KB's "Cyberpunk Theme", rev 3, under this project's names (MA-1). The light mode's
// ink-cyan, ink-ok, ink-warn and ink-bad are left out: they are the KB's colour darkened
// by the least that can be read on every surface.
const KB: Record<"light" | "dark", Tokens> = {
  light: {
    page: "#f6f3ff", panel: "#ffffff", raised: "#ece6ff", field: "#ffffff",
    line: "#d6ccf5", "line-strong": "#6b5f99", fg: "#1a0b3d", "fg-muted": "#6b5f99",
    primary: "#007a8f", "on-primary": "#ffffff", danger: "#d4004f", "on-danger": "#ffffff",
    "neon-cyan": "#0090a8", "neon-violet": "#6d28d9", "ink-violet": "#6d28d9",
    ok: "#1f8f2c", warn: "#a16207", bad: "#d4004f", focus: "#6d28d9",
    grid: "rgba(80, 40, 200, 0.06)",
  },
  dark: {
    page: "#0e0f13", panel: "#17191f", raised: "#121318", field: "#0e0f13",
    line: "#2a2d36", "line-strong": "#8e94a3", fg: "#eceef3", "fg-muted": "#8e94a3",
    primary: "#22e4ff", "on-primary": "#0e0f13", danger: "#ff3d81", "on-danger": "#0e0f13",
    "neon-cyan": "#22e4ff", "ink-cyan": "#22e4ff", "neon-violet": "#c084fc", "ink-violet": "#c084fc",
    ok: "#5bff9a", "ink-ok": "#5bff9a", warn: "#ffe14d", "ink-warn": "#ffe14d",
    bad: "#ff3d81", "ink-bad": "#ff3d81", focus: "#c084fc",
    grid: "rgba(255, 255, 255, 0.03)",
  },
};
// What the light mode's ink tones were darkened from.
const KB_INK = { "ink-cyan": "#007a8f", "ink-ok": "#1a7a27", "ink-warn": "#a16207", "ink-bad": "#d4004f" };

test.each(["light", "dark"] as const)("the %s mode has the KB theme's colours", (mode) => {
  const ours = Object.fromEntries(Object.keys(KB[mode]).map((name) => [name, MODES[mode][name]]));
  expect(ours).toEqual(KB[mode]);
});

test.each(Object.entries(KB_INK))("the light %s is the KB's, or darker", (name, theirs) => {
  expect(luminance(colour(MODES.light, name))).toBeLessThanOrEqual(luminance(theirs));
});

test("there is one secondary text tone, and no magenta or acid", () => {
  for (const gone of ["fg-subtle", "neon-magenta", "ink-magenta", "neon-acid", "ink-acid"]) {
    expect(Object.keys(MODES.dark)).not.toContain(gone);
    expect(Object.keys(MODES.light)).not.toContain(gone);
  }
});
```

Run `pnpm test src/styles/tokens.test.ts`. It fails: the values differ and `ink-violet` is missing.

**Implement** `tokens.css`. Keep its header comment, and the shared `:root` block and the reduced-motion block (still `glow-sm`/`glow-md: none`; `lift` stays). Both mode blocks hold the same names:

```css
:root,
:root[data-theme="dark"] {
  color-scheme: dark;
  --mg-page: #0e0f13; --mg-panel: #17191f; --mg-raised: #121318; --mg-field: #0e0f13;
  --mg-line: #2a2d36; --mg-line-strong: #8e94a3;
  --mg-fg: #eceef3; --mg-fg-muted: #8e94a3;
  --mg-primary: #22e4ff; --mg-on-primary: #0e0f13; --mg-danger: #ff3d81; --mg-on-danger: #0e0f13;
  --mg-neon-cyan: #22e4ff; --mg-ink-cyan: #22e4ff; --mg-neon-violet: #c084fc; --mg-ink-violet: #c084fc;
  --mg-ok: #5bff9a; --mg-ink-ok: #5bff9a; --mg-warn: #ffe14d; --mg-ink-warn: #ffe14d;
  --mg-bad: #ff3d81; --mg-ink-bad: #ff3d81;
  --mg-focus: #c084fc;
  /* Dark: no shadows, depth from neon glows. */
  --mg-lift: none;
  --mg-glow-sm: 0 0 10px color-mix(in srgb, var(--mg-neon-cyan) 40%, transparent);
  --mg-glow-md: 0 0 0 1px var(--mg-neon-cyan), 0 0 20px color-mix(in srgb, var(--mg-neon-cyan) 55%, transparent);
  --mg-grid: rgba(255, 255, 255, 0.03);
}
:root[data-theme="light"] {
  color-scheme: light;
  --mg-page: #f6f3ff; --mg-panel: #ffffff; --mg-raised: #ece6ff; --mg-field: #ffffff;
  --mg-line: #d6ccf5; --mg-line-strong: #6b5f99;
  --mg-fg: #1a0b3d; --mg-fg-muted: #6b5f99;
  --mg-primary: #007a8f; --mg-on-primary: #ffffff; --mg-danger: #d4004f; --mg-on-danger: #ffffff;
  --mg-neon-cyan: #0090a8; --mg-ink-cyan: #007286; --mg-neon-violet: #6d28d9; --mg-ink-violet: #6d28d9;
  --mg-ok: #1f8f2c; --mg-ink-ok: #197725; --mg-warn: #a16207; --mg-ink-warn: #965b06;
  --mg-bad: #d4004f; --mg-ink-bad: #cf004d;
  --mg-focus: #6d28d9;
  /* Light: soft shadows, no glows. */
  --mg-lift: 0 1px 2px color-mix(in srgb, var(--mg-fg) 8%, transparent), 0 4px 12px color-mix(in srgb, var(--mg-fg) 8%, transparent);
  --mg-glow-sm: 0 1px 3px color-mix(in srgb, var(--mg-fg) 14%, transparent);
  --mg-glow-md: 0 0 0 1px var(--mg-neon-cyan), 0 2px 8px color-mix(in srgb, var(--mg-fg) 16%, transparent);
  --mg-grid: rgba(80, 40, 200, 0.06);
}
```

Write one declaration per line, grouped under the existing comments (Surfaces, Lines, Text, …). The comment on the focus ring stays.

The four light ink values are worked out by hand, about 4.5:1 on `raised`, which is the darkest light surface. If a contrast test still fails, darken that colour's non-zero channels one step at a time until it passes. Never change a value the KB test holds.

**`globals.css`, the `@theme inline` block:**
- remove `fg-subtle`, `neon-magenta`, `ink-magenta`, `neon-acid` and `ink-acid`;
- add `--color-neon-violet` and `--color-ink-violet`;
- add `--shadow-lift: var(--mg-lift);` next to the glows.

**`globals.css`, the base layer:**
- `::selection` uses `var(--mg-ink-violet)`;
- the grid stays `var(--mg-grid)`.

**Components:**
- Replace every `fg-subtle` with `fg-muted`: `rg -l fg-subtle src` lists them (source, repository-settings, blob-stores, authentication, user, sign-in, anonymous-access, certificates, audit, member-list, app-shell, search-box, group-mapping, permission-rows, ui/menu, ui/field, ui/details, ui/breadcrumbs, ui/inputs).
- `app-shell.tsx`: the Wordmark bar becomes `bg-neon-cyan`.
- `user-menu.tsx`: the `UserRound` icon becomes `text-neon-violet`.
- `ui/states.tsx`: the `Inbox` icon becomes `text-neon-violet`.
- `browse.tsx:136`: the folder icon becomes `text-neon-violet`.
- `ui/panel.tsx`: `Panel` gets `shadow-lift`.
- `ui/menu.tsx`: `MenuContent` uses `shadow-lift` instead of `shadow-glow-sm`. Menus stand on `bg-panel`, as now.
- `ui/confirm-dialog.tsx`: `AlertDialog.Content` gets `shadow-lift`.

Afterwards, `rg -n 'fg-subtle|magenta|acid' src` must find nothing.

**Verify.** `pnpm test` passes, including `tokens.test.ts` and `literals.test.ts`. `pnpm lint` and `pnpm typecheck` pass.

Commit: `feat(ui): the Cyberpunk theme's colours, with ink tones darkened where text must be read and a violet focus ring`

---

## Step 3. Typefaces: Geist, Geist Mono and Orbitron 700; titles and navigation in sentence case

**Test first.** New `frontend/src/lib/fonts.test.ts`, with `// @vitest-environment node`:

```ts
import { readdirSync, readFileSync } from "node:fs";
import { expect, test } from "vitest";

const FILES = {
  "geist-latin-wght-normal.woff2": "GEIST-LICENSE.txt",
  "geist-mono-latin-wght-normal.woff2": "GEIST-MONO-LICENSE.txt",
  "orbitron-latin-700-normal.woff2": "ORBITRON-LICENSE.txt",
};

test("the three typefaces are in the repository, each with its licence beside it (UI-14)", () => {
  expect(readdirSync("src/fonts").sort()).toEqual(
    [...Object.keys(FILES), ...Object.values(FILES)].sort(),
  );
  const loaded = readFileSync("src/lib/fonts.ts", "utf8");
  for (const [font, licence] of Object.entries(FILES)) {
    expect(readFileSync(`src/fonts/${font}`).subarray(0, 4).toString("latin1")).toBe("wOF2");
    expect(readFileSync(`src/fonts/${licence}`, "utf8")).toContain("SIL Open Font License");
    expect(loaded).toContain(`../fonts/${font}`);
  }
});
```

In `src/components/ui/more.test.tsx`, the test "is in capitals when it is the screen's own word…" becomes "is written as it is, whether it is the screen's own word or a name". Both `PageHeader` renders now expect `not.toHaveClass("uppercase")`.

Run `pnpm test src/lib/fonts.test.ts src/components/ui/more.test.tsx`. Both fail.

**Fonts.** Copy them in; do not add a dependency. Work in a new empty directory outside the repository, and only copy files out of it:

```sh
mkdir -p /tmp/ma1-fonts && cd /tmp/ma1-fonts
npm pack @fontsource-variable/geist @fontsource-variable/geist-mono @fontsource/orbitron
for f in *.tgz; do mkdir "${f%.tgz}" && tar -xzf "$f" -C "${f%.tgz}"; done
```

From each package's `package/files/`, copy:
- `geist-latin-wght-normal.woff2`
- `geist-mono-latin-wght-normal.woff2`
- `orbitron-latin-700-normal.woff2`

Copy each package's `package/LICENSE` (the OFL text) to `GEIST-LICENSE.txt`, `GEIST-MONO-LICENSE.txt` and `ORBITRON-LICENSE.txt` in `frontend/src/fonts/`.

Delete the three old `woff2` files and `INTER-`, `JETBRAINS-MONO-` and `OXANIUM-LICENSE.txt`.

**`src/lib/fonts.ts`.** Keep the comment on UI-14 and export:
- `geist`: `variable: "--font-geist"`, `weight: "100 900"`. Comment: headings and text.
- `geistMono`: `variable: "--font-geist-mono"`, `weight: "100 900"`. Comment: coordinates, paths, checksums and code.
- `orbitron`: `variable: "--font-orbitron"`, `weight: "700"`. Comment: the wordmark only.

All three use `display: "swap"`.

**`app/layout.tsx`.** Import `geist`, `geistMono` and `orbitron`. `className` becomes `` `${geist.variable} ${geistMono.variable} ${orbitron.variable} antialiased` ``.

**`globals.css`:**
- `--font-display: var(--font-orbitron), ui-sans-serif, system-ui, sans-serif;`
- `--font-sans: var(--font-geist), ui-sans-serif, system-ui, sans-serif;`
- `--font-mono: var(--font-geist-mono), ui-monospace, monospace;`
- `h1, h2, h3`: `font-family: var(--font-sans); letter-spacing: -0.01em;`
- `label-caps`: `font-family: var(--font-sans)`. Weight 600, uppercase and `0.14em` tracking stay. Its comment says it is for buttons, badges and small labels.

**Components:**
- `ui/panel.tsx` `PageHeader`: the `h1` class is `cn("text-2xl font-semibold text-fg", named && "break-words")`, with no uppercase or tracking. The `named` prop's doc says a name may be long and must break.
- `account-nav.tsx`: the link class swaps `label-caps` for `text-sm font-medium`.
- `app-shell.tsx`: in the navigation links, replace `label-caps` with `text-sm font-medium`. The area names keep `label-caps`.
- `Wordmark`: `font-display text-lg font-bold tracking-[0.08em] text-fg uppercase`, with the `bg-neon-cyan shadow-glow-sm` bar.

The screens' own `H2` constants are not changed: the design names only `PageHeader` and the navigation.

**Verify.** `pnpm test`, `pnpm lint`, `pnpm typecheck` and `pnpm build` pass. The build shows `next/font/local` finds the files.

Commit: `feat(ui): Geist, Geist Mono and Orbitron for the wordmark, kept in the repository; titles and navigation in sentence case`

---

## Step 4. The sidebar's rail choice: lib/sidebar.ts, its hook, and the pre-paint script

**Test first.** New `frontend/src/lib/sidebar.test.ts`, in the style of `theme.test.ts`. `runScript = () => new Function(SIDEBAR_SCRIPT)()`, and `shown = () => document.documentElement.getAttribute("data-sidebar")`.

- **"is open until it is collapsed"**: `sidebarIsRail()` is false.
- **"is kept in this browser"**: `setSidebarRail(true)` makes storage `"rail"`, `sidebarIsRail()` true and `shown()` `"rail"`. Then `setSidebarRail(false)` removes the key (`getItem` returns null) and the attribute (`shown()` null).
- **`test.each(["", "RAIL", "open", "true"])` "is open when storage holds %j"**: `sidebarIsRail()` is false.
- **"lasts as long as the page when storage fails"**: mock `Storage.prototype.getItem`, `setItem` and `removeItem` to throw. Then `setSidebarRail(true)` does not throw, `sidebarIsRail()` is true and `shown()` is `"rail"`. Then `vi.restoreAllMocks()` and `setSidebarRail(false)`, which resets the page-only choice.
- **"the script in the head agrees with the module"**: for stored `"rail"`, `null` and `"x"`, set storage and run the script. `shown() === "rail"` equals `sidebarIsRail()`.
- **"the script leaves the page as it is when storage cannot be read"**: `getItem` throws, `runScript` does not throw, and `shown()` is null.
- **"the script is one statement a text cannot break out of"**: it has no `</`, and starts with `(function(){`.
- **"tells whoever listens"**: a listener given to `subscribe` is called once by `setSidebarRail(true)`.

Run `pnpm test src/lib/sidebar.test.ts`. It fails: there is no module.

**`src/lib/sidebar.ts`** has no `"use client"` and no React import:

```ts
/** Whether the sidebar is a rail of icons. No React here, so the page's head can use it. */
export const SIDEBAR_STORAGE = "megooarti-sidebar";
export const RAIL = "rail";
export const SIDEBAR_ATTRIBUTE = "data-sidebar";
const CHANGED = "megooarti-sidebar-changed";
let unkept: boolean | null = null; // where the browser keeps nothing

export function sidebarIsRail(): boolean {
  if (unkept !== null) return unkept;
  try { return window.localStorage.getItem(SIDEBAR_STORAGE) === RAIL; } catch { return false; }
}

export function setSidebarRail(rail: boolean): void {
  try {
    if (rail) window.localStorage.setItem(SIDEBAR_STORAGE, RAIL);
    else window.localStorage.removeItem(SIDEBAR_STORAGE);
    unkept = null;
  } catch { unkept = rail; }
  if (rail) document.documentElement.setAttribute(SIDEBAR_ATTRIBUTE, RAIL);
  else document.documentElement.removeAttribute(SIDEBAR_ATTRIBUTE);
  window.dispatchEvent(new Event(CHANGED));
}

export function subscribe(changed: () => void): () => void { /* "storage" and CHANGED, as lib/preferences.ts */ }

/** Runs in the page's head before paint, as THEME_SCRIPT does. A test holds it to sidebarIsRail. */
export const SIDEBAR_SCRIPT = `(function(){try{if(localStorage.getItem(${JSON.stringify(SIDEBAR_STORAGE)})===${JSON.stringify(RAIL)})document.documentElement.setAttribute(${JSON.stringify(SIDEBAR_ATTRIBUTE)},${JSON.stringify(RAIL)})}catch(e){}})()`;
```

Add the comments the code needs, in the voice of `preferences.ts`.

A `"storage"` event from another tab must also update the attribute, or the other tab's rail would not change width. `subscribe`'s storage handler therefore re-applies the attribute from `sidebarIsRail()` before calling `changed`. Test it: dispatch a `StorageEvent("storage")` after `localStorage.setItem(SIDEBAR_STORAGE, "rail")`, and `shown()` is `"rail"`.

**`src/lib/use-sidebar.ts`**:

```ts
"use client";
import { useCallback, useSyncExternalStore } from "react";
import { setSidebarRail, sidebarIsRail, subscribe } from "@/lib/sidebar";

/** Whether the sidebar is a rail, and a way to say so. On the server it is open. */
export function useSidebarRail(): [boolean, (rail: boolean) => void] {
  const rail = useSyncExternalStore(subscribe, sidebarIsRail, () => false);
  return [rail, useCallback((next: boolean) => setSidebarRail(next), [])];
}
```

**`app/layout.tsx`**: `__html: `${THEME_SCRIPT};${SIDEBAR_SCRIPT}``, with a comment that both correct the markup before paint. `<html>` already has `suppressHydrationWarning`.

**`globals.css`**: after the imports, add `@custom-variant rail (&:where([data-sidebar="rail"] *));` with a comment that it is for the sidebar only, collapsed, set before paint by `lib/sidebar.ts`.

**`src/test/setup.ts`**: in `beforeEach`, next to removing `data-theme`, add `document.documentElement.removeAttribute("data-sidebar");`.

**Verify.** `pnpm test`, `pnpm lint` and `pnpm typecheck` pass.

Commit: `feat(ui): the sidebar's rail is kept in the browser and set by the page's head before paint`

---

## Step 5. AppShell: the sidebar, its rail with tooltips, and the header beside it

This step keeps today's narrow navigation (`#narrow-navigation`, toggled in the header) so everything stays green. Step 6 replaces it with the drawer.

**Messages** (`messages/en.json`, `app`): `"collapseNavigation": "Collapse the navigation"` and `"expandNavigation": "Expand the navigation"`.

**Tests first**, in `src/components/shell.test.tsx`:
- Remove "has the navigation in a row of its own, which wraps where it does not fit".
- Add **"has the navigation in a sidebar beside the content, and search in the header"**:
  - `nav = screen.getAllByRole("navigation", { name: "Main" })[0]`;
  - `nav.closest("#sidebar")` is not null;
  - `within(screen.getByRole("banner")).queryByRole("navigation", { name: "Main" })` is null;
  - `screen.getByRole("main").closest("#sidebar")` is null;
  - the banner has the search box `Search components`.
- Add **"collapses to a rail that keeps every link's name, and remembers it (decision 4)"**:
  - `user.click(getByRole("button", { name: "Collapse the navigation" }))`, which before the click has `aria-expanded="true"` and `aria-controls="sidebar"`;
  - then the button named "Expand the navigation" has `aria-expanded="false"`;
  - `document.documentElement` has `data-sidebar="rail"` and storage `megooarti-sidebar` is `"rail"`;
  - in `#sidebar`, `getByRole("link", { name: "Repositories" })` and `{ name: "Audit log" }` still exist;
  - clicking Expand removes both the attribute and the key.
- Add **"starts as a rail when that was chosen before"**: set `localStorage["megooarti-sidebar"] = "rail"` and render. The button is "Expand the navigation".
- Add **"shows a link's name beside it in the rail, on keyboard focus"**:
  - store `"rail"` and render;
  - `act(() => sidebarLink.focus())` on the Search link;
  - `await screen.findByRole("tooltip")` has text "Search".
- Keep the other tests. `getAllByRole("navigation", { name: "Main" })[0]` is now the sidebar's.
- The bare test also expects `document.getElementById("sidebar")` to be null and no "Collapse the navigation" button.

Run `pnpm test src/components/shell.test.tsx`. The new tests fail.

**Implement `app-shell.tsx`.** Its interface stays `{ session, bare, children }`. The structure, with `areas` as today:

```tsx
<Tooltip.Provider delayDuration={300}>
<div className="flex min-h-dvh">
  {/* skip link, unchanged */}
  {areas.length > 0 ? (
    <div id="sidebar" className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-line bg-panel transition-[width] lg:flex rail:w-16">
      <AppLink href="/" className="flex min-h-16 items-center rounded-sm px-4"><Wordmark collapsible /></AppLink>
      <nav aria-label={t("mainNavigation")} className="min-h-0 flex-1 overflow-y-auto px-2 py-4">
        <Navigation areas={areas} collapsible rail={rail} />
      </nav>
      <button type="button" aria-controls="sidebar" aria-expanded={!rail}
        aria-label={rail ? t("expandNavigation") : t("collapseNavigation")}
        onClick={() => setRail(!rail)}
        className="m-2 inline-flex min-h-10 items-center justify-center gap-2 rounded-sm border border-line-strong text-fg-muted hover:border-neon-cyan hover:text-fg">
        {rail ? <PanelLeftOpen aria-hidden="true" className="size-4" /> : <PanelLeftClose aria-hidden="true" className="size-4" />}
      </button>
    </div>
  ) : null}
  <div className="flex min-w-0 flex-1 flex-col">
    <header className="sticky top-0 z-30 border-b border-line-strong bg-panel">
      <div className="mx-auto flex min-h-16 max-w-7xl items-center gap-4 px-4">
        <AppLink href="/" className={cn("shrink-0 rounded-sm", areas.length > 0 && "lg:hidden")}><Wordmark /></AppLink>
        <div className="ml-auto flex items-center gap-2"> search (not bare), ThemeSwitch, UserMenu, menu button (as today, lg:hidden) </div>
      </div>
      {/* #narrow-navigation exactly as today, until step 6 */}
    </header>
    <main id={MAIN} tabIndex={-1} className="mx-auto w-full max-w-7xl min-w-0 flex-1 px-4 py-8 outline-none">{children}</main>
  </div>
</div>
</Tooltip.Provider>
```

`[rail, setRail] = useSidebarRail()`. Import `Tooltip` from `radix-ui` and `PanelLeftClose` and `PanelLeftOpen` from `lucide-react`.

**Header and sign-out alert.** Keep `relative` semantics: a sticky element is positioned, so the user menu's sign-out alert (`absolute top-full`) still sits under the header.

**`Navigation({ areas, onNavigate, collapsible = false, rail = false })`**:
- Vertical lists: `<ul className="flex flex-col gap-4">`. Each area is `<li className="flex flex-col gap-1">`, with:
  - its name, `<span className={cn("label-caps px-3 text-fg-muted", collapsible && "rail:sr-only")}>`;
  - when `collapsible`, `<span aria-hidden="true" className="mx-3 hidden h-px bg-line rail:block" />`;
  - the inner `<ul className="flex flex-col gap-1">`.
- Link classes as today, minus the `lg:` row ones. The name is `<span className={cn(collapsible && "rail:sr-only")}>`.
- When `collapsible`, each link is wrapped in `<Tooltip.Root open={rail ? undefined : false}><Tooltip.Trigger asChild>{link}</Tooltip.Trigger><Tooltip.Portal><Tooltip.Content side="right" sideOffset={8} className="bevel z-50 border border-line-strong bg-panel px-2 py-1 text-sm text-fg shadow-lift">{name}</Tooltip.Content></Tooltip.Portal></Tooltip.Root>`. The tree is the same whether or not the sidebar is a rail.
- The current item keeps `aria-current="page"`, `border-neon-cyan bg-raised text-ink-cyan`.

**`Wordmark({ collapsible = false })`**: the name is in a `<span className={cn(collapsible && "rail:sr-only")}>`, so the link home keeps its name. The bar shows alone in the rail. `sign-in.tsx` still uses `<Wordmark />`.

**`globals.css`**: in `html`, add `scroll-padding-top: 5rem;` with a comment that it keeps a focused element from going under the sticky header.

**Reduced motion.** `transition-[width]` uses `--default-transition-duration`, which is 0 under reduced motion.

**Verify.** `pnpm test`, `pnpm lint` and `pnpm typecheck` pass. The existing axe test in "names its parts" passes.

Commit: `feat(ui): the navigation is a sidebar beside the header, collapsible to a rail of icons`

---

## Step 6. Below 1024 px the navigation is a drawer (Radix Dialog)

**Tests first**, in `shell.test.tsx`. Replace "opens its navigation from a button where the window is narrow (UI-3)" with:

- **"opens its navigation in a drawer from a button where the window is narrow (UI-3)"**:
  - the button "Open the navigation" has `aria-expanded="false"`, and `screen.queryByRole("dialog")` is null;
  - clicking it makes the button `aria-expanded="true"`;
  - `dialog = screen.getByRole("dialog")` has `within(dialog).getByRole("navigation", { name: "Main" })` and the button "Close the navigation";
  - `await expectAccessible()`;
  - clicking the link `Repositories` in the dialog closes it: the dialog query is null.
- **"closes the drawer by its button, by Escape and by a click outside"**:
  - open, click "Close the navigation", no dialog;
  - open, `user.keyboard("{Escape}")`, no dialog;
  - open, `user.click(document.querySelector("[data-drawer-scrim]"))`, no dialog.
- **"closes the drawer when the window grows wide enough for the sidebar"**:
  - before rendering, replace `window.matchMedia` with a stub. For a query containing `1024` it captures the `change` listener; `matches` is false;
  - open the drawer;
  - `act(() => listener({ matches: true } as MediaQueryListEvent))`;
  - there is no dialog.
- Rewrite "has the search box in its header, and in the navigation of a narrow window":
  - the banner has one `search` (hidden) with classes `hidden md:block`;
  - after the drawer is opened, `within(dialog).getByRole("search", { name: "Search components" })` has class `md:hidden`;
  - typing `guava{Enter}` in the header box still pushes `/search?q=guava`.
- The bare test is unchanged: no navigation, no search, no "Open the navigation".

Run `pnpm test src/components/shell.test.tsx`. These fail.

**Implement in `app-shell.tsx`.** Remove `#narrow-navigation` and the toggle button. In the header's end group, when `areas.length > 0`:

```tsx
<Dialog.Root open={open} onOpenChange={setOpen}>
  <Dialog.Trigger asChild>
    <button type="button" aria-label={t("openNavigation")} className="inline-flex size-10 items-center justify-center rounded-sm border border-line-strong text-fg lg:hidden">
      <MenuIcon aria-hidden="true" className="size-5" />
    </button>
  </Dialog.Trigger>
  <Dialog.Portal>
    <Dialog.Overlay data-drawer-scrim="" className="fixed inset-0 z-40 bg-page/80 lg:hidden" />
    <Dialog.Content id="narrow-navigation" aria-describedby={undefined}
      className="fixed inset-y-0 left-0 z-50 flex w-[min(20rem,85vw)] flex-col gap-4 overflow-y-auto border-r border-line-strong bg-panel p-4 shadow-lift lg:hidden">
      <Dialog.Title className="sr-only">{t("mainNavigation")}</Dialog.Title>
      <div className="flex items-center justify-between gap-2">
        <Wordmark />
        <Dialog.Close asChild>
          <button type="button" aria-label={t("closeNavigation")} className="inline-flex size-10 items-center justify-center rounded-sm border border-line-strong text-fg">
            <X aria-hidden="true" className="size-5" />
          </button>
        </Dialog.Close>
      </div>
      <SearchBox className="md:hidden" />
      <nav aria-label={t("mainNavigation")}><Navigation areas={areas} onNavigate={() => setOpen(false)} /></nav>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
```

- Import `Dialog` from `radix-ui`.
- `Navigation` here is not `collapsible`: the rail does not apply to the drawer.
- Radix's Trigger sets `aria-expanded` and `aria-controls` itself, and Radix gives the focus trap, Escape, outside click and the return of focus.
- Add an effect: `const wide = window.matchMedia("(min-width: 1024px)")`, and a `change` listener that calls `setOpen(false)` when `event.matches`. Clean it up on unmount. Put the query in a `WIDE` constant with a comment saying it is Tailwind's `lg`.
- Radix's scroll-lock style takes the nonce through `get-nonce`, already set in `providers.tsx`.

**`/`.** The key is taken only when a box is on the screen. Below 768 px with the drawer closed, the header box is `display: none` and the drawer's box does not exist.

**Verify.** `pnpm test`, `pnpm lint` and `pnpm typecheck` pass.

Commit: `feat(ui): below 1024 px the navigation is a drawer, with a scrim, a close button and Escape`

---

## Step 7. Browser tests: the drawer, the sidebar beside the search box, and the rail before the UI's code

All edits are in `frontend/e2e/ui.spec.ts`.

**1. "on a narrow screen the navigation is behind a button, and nothing overflows"** (around line 378):
- after `open.click()`, add `await expect(page.getByRole("dialog")).toBeVisible();`;
- after clicking "Close the navigation", add `await expect(page.getByRole("dialog")).toHaveCount(0);`;
- then open it again, `await page.keyboard.press("Escape")`, and expect no dialog;
- the rest is unchanged.

**2.** The tests at around 677 and 893 (search box in the drawer, `/` in a narrow window) keep their steps. Change their comments from "in the navigation" to "in the drawer". Run them as they are.

**3.** Replace "the administration is in the navigation, in a row that nothing lies over" (around line 1049) with "the administration is in the sidebar, beside the header's search box, and nothing overflows":
- for widths `[1024, 1280]`: `Anonymous access` in `main` (the Main navigation) is visible;
- the bounding boxes of `main` and of `page.getByRole("search", { name: "Search components" })` do not intersect: test both axes, `a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y`;
- the overflow is `<= 0`;
- then at a height of 400, `await main.getByRole("link", { name: "Audit log" }).scrollIntoViewIfNeeded()` and expect it visible, which shows the list scrolls by itself;
- reset to 1280×720;
- the click on Roles and its checks stay as they are.

**4.** New test, right after "the skip link is the first stop…": "the sidebar collapses to a rail, which is kept, and shown by the page's head before any of the UI's code has run":

```ts
test("the sidebar collapses to a rail, which is kept, and shown by the page's head before any of the UI's code has run", async () => {
  const main = page.getByRole("navigation", { name: "Main" });
  const wide = (await main.boundingBox())?.width ?? 0;
  await page.getByRole("button", { name: "Collapse the navigation" }).click();
  const expand = page.getByRole("button", { name: "Expand the navigation" });
  await expect(expand).toHaveAttribute("aria-expanded", "false");
  expect(await page.evaluate(() => localStorage.getItem("megooarti-sidebar"))).toBe("rail");
  await expect.poll(async () => (await main.boundingBox())?.width ?? 0).toBeLessThan(wide / 2);
  // In the rail a link keeps its name, and shows it beside it.
  await main.getByRole("link", { name: "Search" }).hover();
  await expect(page.getByRole("tooltip")).toHaveText("Search");

  // With every script file refused, only what is written into the page can run.
  const fresh = await context.newPage();
  await fresh.route("**/*.js", (route) => route.abort());
  await fresh.goto("/", { waitUntil: "domcontentloaded" });
  expect(await fresh.evaluate(() => document.documentElement.dataset.sidebar)).toBe("rail");
  await fresh.close();

  await page.reload();
  await expect(expand).toBeVisible();
  await expectAccessible();
  await expand.click();
  expect(await page.evaluate(() => localStorage.getItem("megooarti-sidebar"))).toBeNull();
});
```

Run `pnpm lint` and `pnpm typecheck`; `tsc` covers `e2e/`.

Then run `megoocolab-runner services run ui -- sh scripts/ui-e2e.sh` from the repository root. Every test passes, none failed or skipped. That includes the axe scans of every screen in both modes on the new palette, and the check that nothing was asked of another origin, which now covers the new fonts.

If an axe contrast violation appears, it names an element. Fix it with tokens only, never a literal colour:
- text using a `neon-*` utility should use the `ink-*` one;
- change a token value only where no KB-value test holds it.

Commit: `test(ui): the drawer, the sidebar beside the search box, and the rail set before the UI's code runs`

---

## Step 8. Documents: the sidebar, the theme and the typefaces

**`docs/web-ui.md`.** Add a bullet before "Light and dark": **The navigation** is a sidebar on the left:
- browsing first, then administration;
- "Collapse the navigation" at its foot narrows it to a rail of icons, each named on hover and on keyboard focus;
- the choice is kept in the browser;
- below 1024 pixels it is a drawer behind the menu button, which closes on Escape, on a click outside and when a link is followed;
- below 768 pixels the search box is in the drawer.

The Search bullet stays: search is still in the header.

**`docs/BRD.md`:**
- **UI-7**: "a neon accent palette (cyan, pink, green, amber and violet) on lavender surfaces in light mode and graphite in dark mode, glow effects in dark mode and soft shadows in light mode, and angular, technical shapes."
- **UI-8**: "a display typeface for the wordmark only, a monospace typeface for coordinates, paths, checksums and code, and a highly legible typeface for headings, navigation, body text and tables."

**`docs/superpowers/specs/2026-10-12-frontend-design.md` section 5:**
- The surfaces/lines/text table becomes the step 2 values. There is no `fg-subtle` row, and `fg-muted` covers hints and placeholders.
- The accents table has rows Cyan (primary), Violet, Success, Warning and Danger, with the neon and ink tones of each mode. Light ink tones are the darkened values from `tokens.css`.
- The paragraph on the focus ring says violet in both modes.
- The type paragraph: Geist for text and headings (−0.01em), Geist Mono for code, Orbitron 700 for the wordmark only, and capitals with wide tracking for buttons, badges and small labels.
- Depth: soft shadows (`lift`) in light, neon glows in dark.
- It still says `tokens.css` is the authority.

**Section 6:**
- **Header**: sticky, above the content, with the search box, the mode switch and the user menu; below 1024 pixels also the menu button and the wordmark.
- **Sidebar**: from 1024 pixels, the wordmark, the navigation and the collapse button; the rail; the choice in `localStorage` and set before paint.
- **Drawer**: below 1024 pixels, a modal dialog.
- Remove the text about the wrapping row (A14).

**`README.md`, Licence paragraph**: "the three typefaces of the web UI, Geist, Geist Mono and Orbitron (SIL Open Font License, in `frontend/src/fonts/`)".

**`CHANGELOG.md`:**
- under 0.1.0 "What there is", the web UI bullet becomes "**A web UI** for all of it, with its navigation in a sidebar that collapses to a rail, usable by keyboard, in light and dark in the Cyberpunk palette, that fetches nothing from another host.";
- under Known issues "In the web UI", remove "at 1024 pixels of width the navigation takes three rows".

**Verify.**
- `rg -n 'Oxanium|JetBrains Mono|Inter\b|fg-subtle|magenta|acid' docs README.md CHANGELOG.md frontend/src` finds nothing about the UI. Words that are not the theme's, such as "interface", are fine.
- `pnpm lint`, since Prettier checks the Markdown the frontend owns.

Commit: `docs: the sidebar, its rail and drawer; the Cyberpunk palette and typefaces`

---

## Final verification

From `frontend/`:
```sh
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```
From the repository root:
```sh
megoocolab-runner services run ui -- sh scripts/ui-e2e.sh
```
All pass. The browser tests report every test passed (66 or more), none failed or skipped.

Then a look by hand in a stack (`make up`):
- light and dark;
- a window of 375, 900 and 1280 pixels;
- Collapse, then a reload: the rail is there at once, with no jump;
- the drawer's Escape and scrim.
