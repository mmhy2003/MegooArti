# Frontend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MegooArti has a web UI at its own address: a Next.js application with the cyberpunk theme in both modes, the components every screen is made of, sign-in, changing a password and the list of repositories, served with the API and the repositories from one address by a gateway.

**Architecture:** The Next.js server renders a shell and nothing else; the browser fetches all data from `/api/v1` with the session cookie. A proxy file gives every page a content security policy with a nonce of its own, so pages are rendered for their request. Colours, type and motion are CSS custom properties, one set for each mode, and Tailwind's own palette is removed so that components can use nothing else. In Compose an nginx gateway is the one published port: the API, the repositories and the registry go to the backend, everything else to the frontend.

**Tech Stack:** Next.js 16.4 (App Router, Turbopack), React 19.3, TypeScript 5.9, Tailwind CSS 4.3 (PostCSS), Radix primitives (`radix-ui`), TanStack Query 5, `next-intl` 4, lucide icons, Vitest 5 with Testing Library and axe, Playwright with `@axe-core/playwright`, pnpm 12, nginx.

**Spec:** [docs/superpowers/specs/2026-10-12-frontend-design.md](../specs/2026-10-12-frontend-design.md), sections 1 to 11. Business requirements: [docs/BRD.md](../../BRD.md) UI-1 to UI-15, NFR-9, NFR-10, NFR-17, TC-2, TC-4, API-1, API-2. Task 9 amends the spec where this plan settles something the spec left open.

**Read first:** Next.js 16 differs from earlier versions in ways that matter here. Its documentation is in `frontend/node_modules/next/dist/docs/` once the project is installed. This plan was written against these pages: `01-app/02-guides/content-security-policy.md`, `preventing-flash-before-hydration.md`, `self-hosting.md`, `client-side-data-fetching/tanstack-query.md`, `testing/vitest.md`, `01-app/01-getting-started/16-proxy.md`, `11-css.md`, `13-fonts.md`, and `02-guides/upgrading/version-16.md`.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | `cacheComponents` and `partialPrefetching` are left off. Every page is rendered for its request. | A nonce can only be put into a page that is rendered for the request, and Next.js says itself that a nonce and prerendered shells do not combine. The starter turns both on. |
| P2 | The policy is set in `src/proxy.ts` (the file that was `middleware.ts` before Next.js 16): scripts with the nonce only, `'strict-dynamic'`, styles from the origin or with the nonce, style attributes allowed, everything else `'self'` or `'none'`. No `upgrade-insecure-requests`: the stack is also served over plain HTTP. | Radix positions menus with style attributes, which cannot carry a nonce and cannot run a script. Radix also writes one style sheet into the page, which gets the nonce through `get-nonce`. |
| P3 | Tailwind is set up with `@tailwindcss/postcss`, as the documentation describes, not with the `@tailwindcss/turbopack` loader of the starter. | The loader is not documented, and the documentation says Turbopack loaders do not handle style sheets. |
| P4 | Tokens are `--mg-*` custom properties in `src/styles/tokens.css`: one block for `:root[data-theme="dark"]` (also the default) and one for `:root[data-theme="light"]`. `globals.css` removes Tailwind's palette, shadows and radii (`--color-*: initial`) and defines utilities from the tokens. | D6. A class naming a Tailwind colour then does not exist. |
| P5 | The fonts are three variable `.woff2` files (Latin) in `src/fonts/`, loaded with `next/font/local`. | D7. `next/font/google` fetches from Google at build time. |
| P6 | The mode is kept in `localStorage` under `megooarti-theme` as `light`, `dark` or `system`. A script in the head sets `data-theme` on `<html>`; a provider keeps it in step afterwards, reading storage and the media query as external stores. | D8. |
| P7 | `NextIntlClientProvider` is given the messages inside a client component, with the locale `en` and the time zone `UTC`. The `next-intl` plugin and its request configuration are not used. | Nothing on the server needs a locale. Imported from a server component, the provider demands the plugin. |
| P8 | The API client is one `request` function: same origin, credentials included, the CSRF token (held in a module variable) on `POST`, `PUT`, `PATCH` and `DELETE`. Every failure becomes an `ApiError` with `status`, `code`, `message`, `details` and `requestId`; `status` 0 with `network_error` when no answer came, `unexpected_answer` when the answer is not the API's. | D3, D15. |
| P9 | `frontend/openapi.json` is the backend's document, written by a backend test when `MEGOOARTI_UPDATE_OPENAPI` is set and compared by it otherwise. `src/lib/api/schema.d.ts` is generated from it by `openapi-typescript`, and a frontend test compares the two. | D14. |
| P10 | What a visitor is shown is a pure function, `decide(session, path, next)`, and where sign-in returns to another, `returnPath`. A component, `SessionGate`, asks for the session and follows them. | Section 7 of the spec is then tested as a table of cases. |
| P11 | Signing in posts the credentials and then asks for the session. If that says nobody is signed in, the failure has the code `cookie_not_kept`. | The cookie is `Secure`, and over plain HTTP a browser keeps it only at `localhost`. Without this the screen would return to itself with no word of why. |
| P12 | Signing out posts the logout and then loads the home screen afresh. | Nothing held in memory for whoever was signed in survives it. |
| P13 | Changing a password is one screen, `/account/password`, for whoever chooses to and for whoever must. For the latter the shell shows no navigation. | The same form and the same request. |
| P14 | The navigation is `NAVIGATION` in `src/lib/navigation.ts`: areas, each with items that name a permission. Plan 9 registers one item. | D11. Plan 10 adds its screens there. |
| P15 | A link within the UI never prefetches (`AppLink`). | A screen is a shell whose data comes from the API, and a visitor who is not signed in should cause no request for a screen they did not ask for. |
| P16 | The frontend image is `node:22-slim` in two stages, runs `node server.js` from the standalone output as the user `node`, and has a health address, `/healthz`. | TC-4, NFR-10. |
| P17 | The gateway is `nginx:stable-alpine` with `gateway/nginx.conf` mounted. It publishes `MEGOOARTI_HTTP_PORT`; the backend is no longer published and trusts forwarded headers from anywhere, since only the gateway reaches it. | D1, D17. Chosen by the product owner: nginx, for development and testing. |
| P18 | The browser tests are Playwright tests in `frontend/e2e/`, started by a `docker`-marked pytest test that passes the stack's address (at `localhost`) and the generated administrator password. | D16. One command runs every real-client test. |
| P19 | Install scripts of dependencies are not run (`allowBuilds` in `pnpm-workspace.yaml`, all `false`). | None is needed, and pnpm 12 refuses to install otherwise. |

## Global Constraints

- **A colour is written in `src/styles/tokens.css` and nowhere else.** Components use the utilities of `globals.css`.
- **Text a person reads is in `messages/en.json`.** No literal text in markup (ESLint refuses it).
- **Nothing is loaded from, or sent to, another origin:** not a font, not an icon, not telemetry.
- **What comes from the API is text.** `dangerouslySetInnerHTML` is used once, for the mode script, whose content is a constant.
- **The Next.js server never calls the backend and reads no cookie.** Data is fetched in the browser.
- **Status is never colour alone:** an icon and a word go with it.
- **Every control has a name, and everything works by keyboard.**
- **Formatting:** Prettier, 100 columns, LF line endings. ESLint and `tsc` are clean.
- **Backend rules still apply to the backend files this plan touches** (tests and Compose): ruff clean, 100 columns, tests never contact a real network host except those marked `docker`.
- **This plan adds no migration and no backend setting.**

**Working directories:** run `pnpm` commands in `frontend/`, `uv` and `pytest` commands in `backend/`, and `git` and `docker compose` commands in the repository root. Backend tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **Text from elsewhere in the page, and an address from elsewhere in the browser:** a repository named as markup; a return path that is another site's, a protocol-relative one, one with a backslash; what the policy lets through (Tasks 3, 6 and 8).
2. **A session that is not what the page thinks:** a cookie the browser did not keep, a session that ended (a `401` on any request), a password that must be changed, sign-out that fails, a visitor with anonymous access, a session that cannot be asked for (Tasks 3, 5 and 6).
3. **Both modes, and neither:** every text tone on every surface, storage that cannot be read, a stored value that is not a mode, a system that asks for reduced motion, a page whose scripts did not load (Tasks 2 and 8).
4. **A keyboard and a screen reader:** where focus starts, where it returns, what a control is called, a dialog that must not destroy on Enter (Tasks 4, 5 and 8).
5. **The gateway under real clients:** an encoded slash in a path, a body of gigabytes, an answer that takes long to start, the address a client is given (Task 7).

---

### Task 1: The project, its tooling and the API client

**Files:**
- Modify: `.gitattributes`
- Create: `frontend/package.json`, `frontend/pnpm-workspace.yaml`, `frontend/pnpm-lock.yaml` (written by `pnpm install`)
- Create: `frontend/tsconfig.json`, `frontend/next.config.ts`, `frontend/postcss.config.mjs`, `frontend/eslint.config.mjs`, `frontend/vitest.config.mts`, `frontend/.prettierrc.json`, `frontend/.prettierignore`, `frontend/.gitignore`, `frontend/AGENTS.md`
- Create: `frontend/src/lib/api/client.ts`, `frontend/src/lib/api/types.ts`, `frontend/src/lib/browser.ts`, `frontend/src/lib/cn.ts`
- Create: `frontend/openapi.json` (written by the backend test), `frontend/src/lib/api/schema.d.ts` (written by `pnpm gen:api`)
- Test: `frontend/src/test/setup.ts`, `frontend/src/test/navigation.ts`, `frontend/src/test/api.ts`
- Test: `frontend/src/lib/api/client.test.ts`, `frontend/src/lib/api/schema.test.ts`
- Test: `backend/tests/test_openapi_snapshot.py`

**Interfaces:**
- Consumes: the backend's `app` test fixture and its OpenAPI document.
- Produces:
  - `api.get/post/put/patch/delete<T>(path, ...)`, `request<T>(method, path, { query, body, signal })`, `ApiError(status, code, message, details, requestId)`, `isApiError`, `setCsrfToken(token | null)`, `API_PREFIX`.
  - `SessionInfo`, `UserSummary`, `RepositoryView`, `Page<T>` in `lib/api/types.ts`.
  - `leaveTo(path)` in `lib/browser.ts`; `cn(...classes)` in `lib/cn.ts`.
  - For tests: `mockApi(routes) -> { calls }`, `failure(status, code, message, details?)`; `navigation` (`at(address)`, `router.push/replace` spies, `pathname`, `search`); `setSystemMode("light" | "dark")`.
  - Scripts: `pnpm test`, `pnpm lint`, `pnpm typecheck`, `pnpm build`, `pnpm gen:api`, `pnpm e2e`.

- [ ] **Step 1: Create the project**

In `.gitattributes`:

Replace

```text
*.md text eol=lf
Dockerfile text eol=lf
```

with

```text
*.md text eol=lf
*.ts text eol=lf
*.tsx text eol=lf
*.mts text eol=lf
*.mjs text eol=lf
*.css text eol=lf
*.json text eol=lf
*.yaml text eol=lf
*.svg text eol=lf
*.conf text eol=lf
*.txt text eol=lf
Dockerfile text eol=lf
.dockerignore text eol=lf
*.woff2 binary
```

`frontend/package.json`:

```json
{
  "name": "megooarti-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint . && prettier --check .",
    "format": "prettier --write .",
    "typecheck": "next typegen && tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest",
    "e2e": "playwright test",
    "gen:api": "openapi-typescript openapi.json --output src/lib/api/schema.d.ts"
  },
  "packageManager": "pnpm@12.11.2",
  "dependencies": {
    "@tanstack/react-query": "^5.104.1",
    "clsx": "^2.1.1",
    "get-nonce": "^1.0.1",
    "lucide-react": "^1.55.0",
    "next": "16.4.0",
    "next-intl": "^4.14.9",
    "radix-ui": "^1.7.0",
    "react": "19.3.0",
    "react-dom": "19.3.0",
    "tailwind-merge": "^3.7.0"
  },
  "devDependencies": {
    "@axe-core/playwright": "^4.13.0",
    "@playwright/test": "^1.64.0",
    "@tailwindcss/postcss": "^4.3.3",
    "@testing-library/dom": "^10.4.2",
    "@testing-library/jest-dom": "^7.0.1",
    "@testing-library/react": "^16.3.3",
    "@testing-library/user-event": "^14.6.7",
    "@types/node": "^22.20.5",
    "@types/react": "^19.3.0",
    "@types/react-dom": "^19.3.0",
    "@vitejs/plugin-react": "^6.1.2",
    "axe-core": "^4.14.0",
    "eslint": "^9.39.5",
    "eslint-config-next": "16.4.0",
    "jsdom": "^30.1.2",
    "openapi-typescript": "^7.13.0",
    "prettier": "^3.9.10",
    "tailwindcss": "^4.3.3",
    "typescript": "^5.9.3",
    "vite-tsconfig-paths": "^6.1.1",
    "vitest": "^5.0.3"
  }
}
```

`frontend/pnpm-workspace.yaml`:

```yaml
# Install scripts of dependencies are not run: none of them is needed, and a script
# that runs at install time is code nobody reviewed.
allowBuilds:
  "@parcel/watcher": false
  "@swc/core": false
  sharp: false
  unrs-resolver: false
```

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "react-jsx",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": [
    "next-env.d.ts",
    "**/*.ts",
    "**/*.tsx",
    "**/*.mts",
    ".next/types/**/*.ts",
    ".next/dev/types/**/*.ts"
  ],
  "exclude": ["node_modules"]
}
```

`frontend/next.config.ts`:

```ts
import type { NextConfig } from "next";

// Sent with every answer. The content security policy is not here: it carries a nonce
// that is new for each request, and is set by src/proxy.ts.
const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "same-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  // A server that runs from one folder, for the container image.
  output: "standalone",
  // Compression and TLS belong to the reverse proxy in front.
  compress: false,
  poweredByHeader: false,
  typedRoutes: true,
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
```

`frontend/postcss.config.mjs`:

```js
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
```

`frontend/eslint.config.mjs`:

```js
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // Text a person reads comes from messages/en.json (UI-4), never from markup.
    files: ["src/**/*.tsx"],
    ignores: ["src/**/*.test.tsx", "src/test/**"],
    rules: {
      "react/jsx-no-literals": ["error", { noStrings: true, ignoreProps: true }],
    },
  },
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "playwright-report/**",
    "test-results/**",
    "src/lib/api/schema.d.ts",
  ]),
]);

export default eslintConfig;
```

`frontend/vitest.config.mts`:

```ts
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Styles are not what these tests look at: tokens.css is read as text by its own test.
    css: false,
    restoreMocks: true,
  },
});
```

`frontend/.prettierrc.json`:

```json
{
  "printWidth": 100,
  "endOfLine": "lf"
}
```

`frontend/.prettierignore`:

```text
.next
node_modules
pnpm-lock.yaml
openapi.json
src/lib/api/schema.d.ts
playwright-report
test-results
AGENTS.md
```

`frontend/.gitignore`:

```text
/node_modules
/.next/
/out/
/coverage
/test-results/
/playwright-report/
*.tsbuildinfo
next-env.d.ts
.env*
```

`frontend/AGENTS.md`:

```markdown
<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
```

- [ ] **Step 2: Install**

Run: `pnpm install`
Expected: it writes `pnpm-lock.yaml` and ends with `Done`. No install script of a dependency runs.

- [ ] **Step 3: Write the failing tests**

`frontend/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { setCsrfToken } from "@/lib/api/client";

import { navigation } from "./navigation";

// The router is Next.js's own. Tests say where the visitor is and see where they are sent.
vi.mock("next/navigation", () => ({
  useRouter: () => navigation.router,
  usePathname: () => navigation.pathname,
  useSearchParams: () => new URLSearchParams(navigation.search),
}));

// Loading another page is the browser's doing. A test sees that it was asked for.
vi.mock("@/lib/browser", () => ({ leaveTo: vi.fn() }));

// jsdom has no media queries: the system's mode is what a test says it is.
let systemIsDark = true;
export function setSystemMode(mode: "light" | "dark"): void {
  systemIsDark = mode === "dark";
}

beforeEach(() => {
  navigation.reset();
  setCsrfToken(null);
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
```

`frontend/src/test/navigation.ts`:

```ts
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
```

`frontend/src/test/api.ts`:

```ts
import { vi } from "vitest";

/** One request the UI made, as a test looks at it. */
export type Call = {
  method: string;
  /** The path and query after `/api/v1`. */
  path: string;
  headers: Record<string, string>;
  body: unknown;
};

/** What the API answers. A function is asked each time, so an answer can change. */
export type Answer =
  | { status?: number; json?: unknown; text?: string; headers?: Record<string, string> }
  | "network-failure";

export type Routes = Record<string, Answer | ((call: Call) => Answer)>;

export function failure(status: number, code: string, message: string, details?: unknown): Answer {
  return {
    status,
    json: { error: { code, message, details: details ?? [] } },
    headers: { "X-Request-ID": "req-123" },
  };
}

/**
 * Stands in for the API. `routes` are keyed by method and path, `"GET /auth/session"`;
 * the query is not part of the key. A request to anything else fails the test.
 */
export function mockApi(routes: Routes): { calls: Call[] } {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), "https://ui.test");
      const method = (init.method ?? "GET").toUpperCase();
      const path = url.pathname.replace(/^\/api\/v1/, "");
      const call: Call = {
        method,
        path: path + url.search,
        headers: { ...(init.headers as Record<string, string>) },
        body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
      };
      calls.push(call);
      const route = routes[`${method} ${path}`];
      if (route === undefined) throw new Error(`no answer set for ${method} ${path}`);
      const answer = typeof route === "function" ? route(call) : route;
      if (answer === "network-failure") throw new TypeError("Failed to fetch");
      const status = answer.status ?? 200;
      const body = answer.text ?? (answer.json === undefined ? null : JSON.stringify(answer.json));
      return new Response(status === 204 ? null : body, { status, headers: answer.headers });
    }),
  );
  return { calls };
}
```

`frontend/src/lib/api/client.test.ts`:

```ts
import { describe, expect, test, vi } from "vitest";

import { failure, mockApi } from "@/test/api";

import { api, ApiError, isApiError, setCsrfToken } from "./client";

async function refusal(action: () => Promise<unknown>): Promise<ApiError> {
  try {
    await action();
  } catch (error) {
    if (isApiError(error)) return error;
    throw error;
  }
  throw new Error("the request did not fail");
}

describe("a request", () => {
  test("goes to the API at this origin, with the session cookie, and returns what it answers", async () => {
    const { calls } = mockApi({ "GET /content": { json: { items: [], total: 0 } } });

    const answer = await api.get("/content", { query: { limit: 200, offset: 0, name: null } });

    expect(answer).toEqual({ items: [], total: 0 });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.path).toBe("/content?limit=200&offset=0");
    expect(calls[0]?.headers.Accept).toBe("application/json");
    const [address, init] = vi.mocked(fetch).mock.calls[0] ?? [];
    expect(address).toBe("/api/v1/content?limit=200&offset=0");
    expect(init?.credentials).toBe("same-origin");
  });

  test("escapes what goes into the query", async () => {
    const { calls } = mockApi({ "GET /search": { json: {} } });

    await api.get("/search", { query: { q: "a&b=c d", path: "com/acme" } });

    expect(calls[0]?.path).toBe("/search?q=a%26b%3Dc+d&path=com%2Facme");
  });

  test("sends a body as JSON", async () => {
    const { calls } = mockApi({ "POST /auth/login": { json: { authenticated: true } } });

    await api.post("/auth/login", { username: "ada", password: "pw" });

    expect(calls[0]?.headers["Content-Type"]).toBe("application/json");
    expect(calls[0]?.body).toEqual({ username: "ada", password: "pw" });
  });

  test("answers nothing for an answer without content", async () => {
    mockApi({ "POST /auth/logout": { status: 204 } });

    expect(await api.post("/auth/logout")).toBeUndefined();
  });
});

describe("the CSRF token", () => {
  test.each(["POST", "PUT", "PATCH", "DELETE"] as const)("goes with a %s", async (method) => {
    const { calls } = mockApi({ [`${method} /thing`]: { status: 204 } });
    setCsrfToken("token-of-the-session");

    await api[method.toLowerCase() as "post" | "put" | "patch" | "delete"]("/thing");

    expect(calls[0]?.headers["X-CSRF-Token"]).toBe("token-of-the-session");
  });

  test("does not go with a request that only reads", async () => {
    const { calls } = mockApi({ "GET /thing": { json: {} } });
    setCsrfToken("token-of-the-session");

    await api.get("/thing");

    expect(calls[0]?.headers).not.toHaveProperty("X-CSRF-Token");
  });

  test("is not sent when there is none", async () => {
    const { calls } = mockApi({ "POST /auth/login": { json: {} } });

    await api.post("/auth/login", {});

    expect(calls[0]?.headers).not.toHaveProperty("X-CSRF-Token");
  });
});

describe("a request that fails", () => {
  test("says what the API said, with its code, its details and the request's ID", async () => {
    const details = [{ field: "body.name", message: "Too long." }];
    mockApi({
      "POST /thing": failure(422, "validation_error", "The request is not valid.", details),
    });

    const error = await refusal(() => api.post("/thing", {}));

    expect(error).toBeInstanceOf(ApiError);
    expect([error.status, error.code, error.message]).toEqual([
      422,
      "validation_error",
      "The request is not valid.",
    ]);
    expect(error.details).toEqual(details);
    expect(error.requestId).toBe("req-123");
  });

  test.each([
    ["a gateway's own page", { status: 502, text: "<html>Bad Gateway</html>" }],
    ["nothing at all", { status: 500, text: "" }],
    ["JSON of another shape", { status: 400, json: { detail: "Not Found" } }],
    ["an error without a code", { status: 400, json: { error: { message: "x" } } }],
    ["an error that is not an object", { status: 400, json: { error: "nope" } }],
  ])("is still an error when the answer is %s", async (_what, answer) => {
    mockApi({ "GET /thing": answer });

    const error = await refusal(() => api.get("/thing"));

    expect([error.status, error.code, error.message]).toEqual([
      answer.status,
      "unexpected_answer",
      "",
    ]);
  });

  test("keeps only what a detail should have", async () => {
    mockApi({
      "GET /thing": failure(422, "validation_error", "No.", [
        { field: "a", message: "one" },
        "not an object",
        { field: 7, message: null },
      ]),
    });

    const error = await refusal(() => api.get("/thing"));

    expect(error.details).toEqual([
      { field: "a", message: "one" },
      { field: undefined, message: "" },
    ]);
  });

  test("says so when no answer came at all", async () => {
    mockApi({ "GET /thing": "network-failure" });

    const error = await refusal(() => api.get("/thing"));

    expect([error.status, error.code]).toEqual([0, "network_error"]);
  });

  test("says so when a success is not JSON", async () => {
    mockApi({ "GET /thing": { status: 200, text: "<html>" } });

    const error = await refusal(() => api.get("/thing"));

    expect([error.status, error.code]).toEqual([200, "unexpected_answer"]);
  });

  test("lets a request that was abandoned end as one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new DOMException("The operation was aborted.", "AbortError");
      }),
    );

    await expect(api.get("/thing")).rejects.toMatchObject({ name: "AbortError" });
  });
});
```

`frontend/src/lib/api/schema.test.ts`:

```ts
// @vitest-environment node
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";
import { expect, test } from "vitest";

const unix = (text: string) => text.replaceAll("\r\n", "\n");

test("the API's types are those of the API document beside them", async () => {
  // openapi.json is the backend's own document, held up to date by a backend test.
  // The types are made from it with `pnpm gen:api`. If this fails, run that.
  const made = astToString(await openapiTS(pathToFileURL("openapi.json")));
  const committed = unix(readFileSync("src/lib/api/schema.d.ts", "utf8"));

  expect(committed.endsWith(unix(made))).toBe(true);
});

test("the document describes what the UI is written against", () => {
  const document = JSON.parse(readFileSync("openapi.json", "utf8"));

  for (const path of ["/api/v1/auth/session", "/api/v1/auth/login", "/api/v1/me/password"]) {
    expect(Object.keys(document.paths)).toContain(path);
  }
  expect(Object.keys(document.components.schemas)).toEqual(
    expect.arrayContaining(["SessionInfo", "RepositoryView"]),
  );
});
```

`backend/tests/test_openapi_snapshot.py`:

```python
"""The copy of the API document that the web UI's types are generated from.

The UI is written against `frontend/openapi.json`. This test fails when the API has
changed and the copy has not, so the two cannot drift apart unnoticed. To bring the
copy up to date, and then the types:

    MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest tests/test_openapi_snapshot.py
    cd ../frontend && pnpm gen:api
"""

import json
import os
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"


def written(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_the_copy_of_the_api_document_is_up_to_date(app):
    current = written(app.openapi())
    if os.environ.get("MEGOOARTI_UPDATE_OPENAPI"):
        SNAPSHOT.write_text(current, encoding="utf-8", newline="\n")

    assert SNAPSHOT.exists(), "frontend/openapi.json is missing: see this file's first lines"
    assert SNAPSHOT.read_text(encoding="utf-8") == current, (
        "The API has changed. Run this test with MEGOOARTI_UPDATE_OPENAPI=1, then "
        "`pnpm gen:api` in frontend/, and commit both files."
    )
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 2 files fail, no test runs: `Failed to resolve import "@/lib/api/client"`.

Run (in `backend/`): `uv run pytest tests/test_openapi_snapshot.py -q`
Expected: 1 failed: `frontend/openapi.json is missing`.

- [ ] **Step 5: Implement**

`frontend/src/lib/api/client.ts`:

```ts
/**
 * The one way the UI calls the API: same origin, with the session cookie, and with the
 * CSRF token on whatever changes something. An answer that is not a success becomes an
 * `ApiError`, whatever shape it came in.
 */

export const API_PREFIX = "/api/v1";
const REQUEST_ID = "X-Request-ID";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type Query = Record<string, string | number | boolean | null | undefined>;
export type ErrorDetail = { field?: string; message: string };

export class ApiError extends Error {
  /** The HTTP status, or 0 if no answer came at all. */
  readonly status: number;
  /** The API's own word for what went wrong: `forbidden`, `validation_error`. */
  readonly code: string;
  readonly details: ErrorDetail[];
  /** Which request it was, for whoever is asked to look into it. */
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: ErrorDetail[] = [],
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

// The session's CSRF token. It is in memory only: it comes with the session, and goes
// with the page.
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

function address(path: string, query?: Query): string {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined) search.set(name, String(value));
  }
  const text = search.toString();
  return `${API_PREFIX}${path}${text ? `?${text}` : ""}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function details(value: unknown): ErrorDetail[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((entry) => ({
    field: typeof entry.field === "string" ? entry.field : undefined,
    message: typeof entry.message === "string" ? entry.message : "",
  }));
}

async function failure(response: Response): Promise<ApiError> {
  const requestId = response.headers.get(REQUEST_ID);
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON: a gateway's own page, or nothing at all.
  }
  const sent = isRecord(body) && isRecord(body.error) ? body.error : null;
  if (sent === null || typeof sent.code !== "string" || typeof sent.message !== "string") {
    return new ApiError(response.status, "unexpected_answer", "", [], requestId);
  }
  return new ApiError(response.status, sent.code, sent.message, details(sent.details), requestId);
}

export type RequestOptions = { query?: Query; body?: unknown; signal?: AbortSignal };

export async function request<T>(
  method: Method,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (UNSAFE.has(method) && csrfToken !== null) headers["X-CSRF-Token"] = csrfToken;

  let response: Response;
  try {
    response = await fetch(address(path, options.query), {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "same-origin",
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network_error", "");
  }
  if (!response.ok) throw await failure(response);
  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(
      response.status,
      "unexpected_answer",
      "",
      [],
      response.headers.get(REQUEST_ID),
    );
  }
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, "body">) =>
    request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">) =>
    request<T>("POST", path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">) =>
    request<T>("PUT", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">) =>
    request<T>("PATCH", path, { ...options, body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, "body">) =>
    request<T>("DELETE", path, options),
};
```

`frontend/src/lib/api/types.ts`:

```ts
/** The API's shapes, by the names the UI uses. They come from the backend's own document. */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type SessionInfo = Schemas["SessionInfo"];
export type UserSummary = Schemas["UserSummary"];
export type RepositoryView = Schemas["RepositoryView"];

/** A page of a list, as every list endpoint answers. */
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
```

`frontend/src/lib/browser.ts`:

```ts
/** What only the browser itself can do. Kept apart so that a test can stand in for it. */

/** Go to an address by loading it afresh: everything this page held in memory is gone. */
export function leaveTo(path: string): void {
  window.location.assign(path);
}
```

`frontend/src/lib/cn.ts`:

```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Class names joined, with a later utility winning over an earlier one for the same property. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 6: Write the copy of the API document, and the types from it**

Run (in `backend/`): `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest tests/test_openapi_snapshot.py -q`
Expected: 1 passed, and `frontend/openapi.json` exists.

Run: `pnpm gen:api`
Expected: `openapi.json → src/lib/api/schema.d.ts`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 22 passed in 2 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding. ESLint says once that there is no `pages` directory; that is so until Task 6.

Run (in `backend/`): `uv run pytest tests/test_openapi_snapshot.py -q`
Expected: 1 passed.

- [ ] **Step 8: Commit**

```bash
git add .gitattributes frontend backend/tests/test_openapi_snapshot.py
git commit -m "feat(frontend): the project, its tooling and the API client"
```

---

### Task 2: Design tokens, typefaces and the mode

**Files:**
- Create: `frontend/src/styles/tokens.css`, `frontend/src/styles/globals.css`
- Create: `frontend/src/fonts/` (three `.woff2` files and their licences)
- Create: `frontend/src/lib/fonts.ts`, `frontend/src/lib/theme.ts`, `frontend/src/components/theme-provider.tsx`
- Test: `frontend/src/styles/tokens.test.ts`, `frontend/src/styles/literals.test.ts`, `frontend/src/lib/theme.test.ts`

**Interfaces:**
- Consumes: `setSystemMode` (Task 1).
- Produces:
  - Utilities: `bg-page`, `bg-panel`, `bg-raised`, `bg-field`, `border-line`, `border-line-strong`, `text-fg`, `text-fg-muted`, `text-fg-subtle`, `bg-primary`, `text-on-primary`, `bg-danger`, `text-on-danger`, `border-neon-cyan|magenta|acid`, `text-ink-cyan|magenta|acid`, `border-ok|warn|bad`, `text-ink-ok|warn|bad`, `shadow-glow-sm`, `shadow-glow`, `rounded-sm`, `bevel`, `label-caps`, `font-display`, `font-sans`, `font-mono`.
  - `oxanium`, `inter`, `jetbrainsMono` (each with `.variable`).
  - `ThemeChoice`, `Mode`, `CHOICES`, `STORAGE_KEY`, `DARK_QUERY`, `isChoice`, `resolve(choice, systemIsDark)`, `storedChoice()`, `storeChoice(choice)`, `applyMode(mode)`, `THEME_SCRIPT`.
  - `ThemeProvider`, `useTheme() -> { choice, mode, choose }`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/styles/tokens.test.ts`:

```ts
// @vitest-environment node
import { readFileSync } from "node:fs";

import { describe, expect, test } from "vitest";

const css = readFileSync("src/styles/tokens.css", "utf8");

type Tokens = Record<string, string>;

/** The tokens of one mode: the first block that is written for it. */
function tokensOf(mode: "dark" | "light"): Tokens {
  const block = new RegExp(`:root\\[data-theme="${mode}"\\]\\s*\\{([^}]*)\\}`).exec(css);
  if (block === null) throw new Error(`no tokens for the ${mode} mode`);
  const found: Tokens = {};
  for (const [, name, value] of (block[1] ?? "").matchAll(/--mg-([a-z-]+):\s*([^;]+);/g)) {
    if (name && value) found[name] = value.trim();
  }
  return found;
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
  const [red = 0, green = 0, blue = 0] = channels.map((value) =>
    value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** The contrast of two colours, as WCAG 2.1 computes it: from 1 to 21. */
function contrast(one: string, other: string): number {
  const [lighter = 0, darker = 0] = [luminance(one), luminance(other)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

const MODES = { dark: tokensOf("dark"), light: tokensOf("light") };
const SURFACES = ["page", "panel", "raised", "field"];
// What is read: 4.5 to 1 on every surface it may stand on (WCAG 2.1 AA, 1.4.3).
const TEXT = [
  "fg",
  "fg-muted",
  "fg-subtle",
  "ink-cyan",
  "ink-magenta",
  "ink-acid",
  "ink-ok",
  "ink-warn",
  "ink-bad",
];
// What is seen, not read: borders of controls, icons, the focus ring. 3 to 1 (1.4.11).
const SEEN = [
  "line-strong",
  "neon-cyan",
  "neon-magenta",
  "neon-acid",
  "ok",
  "warn",
  "bad",
  "focus",
  "primary",
  "danger",
];
// Text on a filled control.
const FILLED = [
  ["on-primary", "primary"],
  ["on-danger", "danger"],
] as const;

function colour(tokens: Tokens, name: string): string {
  const value = tokens[name];
  if (value === undefined || !/^#[0-9a-f]{6}$/.test(value)) {
    throw new Error(`--mg-${name} is not a six-digit colour: ${value}`);
  }
  return value;
}

describe.each(Object.entries(MODES))("the %s mode", (_mode, tokens) => {
  test.each(TEXT.flatMap((text) => SURFACES.map((surface) => [text, surface] as const)))(
    "%s can be read on %s",
    (text, surface) => {
      expect(contrast(colour(tokens, text), colour(tokens, surface))).toBeGreaterThanOrEqual(4.5);
    },
  );

  test.each(SEEN.flatMap((seen) => SURFACES.map((surface) => [seen, surface] as const)))(
    "%s can be seen on %s",
    (seen, surface) => {
      expect(contrast(colour(tokens, seen), colour(tokens, surface))).toBeGreaterThanOrEqual(3);
    },
  );

  test.each(FILLED)("%s can be read on %s", (text, fill) => {
    expect(contrast(colour(tokens, text), colour(tokens, fill))).toBeGreaterThanOrEqual(4.5);
  });

  test("the focus ring is not the colour of what it surrounds", () => {
    for (const other of ["primary", "danger", "line-strong", "neon-cyan"]) {
      expect(colour(tokens, "focus")).not.toBe(colour(tokens, other));
    }
  });
});

test("both modes define the same tokens, and neither is a fallback for the other", () => {
  expect(Object.keys(MODES.light).sort()).toEqual(Object.keys(MODES.dark).sort());
  expect(Object.keys(MODES.dark).length).toBeGreaterThan(25);
  for (const surface of SURFACES) {
    expect(MODES.light[surface]).not.toBe(MODES.dark[surface]);
  }
});

test("the contrast is computed as the standard computes it", () => {
  expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
  expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2); // the well-known near miss
  expect(contrast("#ffffff", "#ffffff")).toBe(1);
});

test("whoever asks for less motion gets none, and no glow", () => {
  const reduced = /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*)\}\s*$/.exec(css);
  expect(reduced).not.toBeNull();
  const block = reduced?.[1] ?? "";
  expect(block).toContain(':root[data-theme="dark"]');
  expect(block).toContain(':root[data-theme="light"]');
  expect(block).toMatch(/--mg-duration-fast:\s*0ms/);
  expect(block).toMatch(/--mg-duration:\s*0ms/);
  expect(block).toMatch(/--mg-glow-sm:\s*none/);
  expect(block).toMatch(/--mg-glow-md:\s*none/);
});
```

`frontend/src/styles/literals.test.ts`:

```ts
// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "vitest";

/** Every source file a colour could be written in, except where the tokens are defined. */
function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name).replaceAll("\\", "/");
    if (entry.isDirectory()) return path === "src/test" ? [] : sources(path);
    const kept = /\.(tsx?|css)$/.test(entry.name) && !/\.(test|d)\.tsx?$/.test(entry.name);
    return kept && path !== "src/styles/tokens.css" ? [path] : [];
  });
}

// A colour written out, in any of the ways CSS and Tailwind have for it.
const LITERALS = [
  /#[0-9a-fA-F]{3,8}\b/, // #0ff, #00e5ff
  /\b(rgb|rgba|hsl|hsla|oklch|oklab|lab|lch|hwb)\(/, // rgb(0 229 255)
  // Tailwind's own palette, which globals.css removes: text-red-500, bg-slate-900/50
  /\b(text|bg|border|ring|outline|fill|stroke|shadow|from|via|to|decoration|divide|accent|caret)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone|black|white)(-\d{2,3})?\b/,
];

test("a colour is written in the tokens and nowhere else (UI-12)", () => {
  const files = sources("src");
  expect(files.length).toBeGreaterThan(5); // it is looking somewhere

  const found = files.flatMap((file) =>
    readFileSync(file, "utf8")
      .split("\n")
      .flatMap((line, index) =>
        LITERALS.some((literal) => literal.test(line))
          ? [`${file}:${index + 1}: ${line.trim()}`]
          : [],
      ),
  );

  expect(found).toEqual([]);
});

test("the check finds what it is there to find", () => {
  const caught = (line: string) => LITERALS.some((literal) => literal.test(line));

  expect(caught('className="text-[#00e5ff]"')).toBe(true);
  expect(caught("color: rgb(0 229 255 / 0.4);")).toBe(true);
  expect(caught('className="bg-slate-900 text-white"')).toBe(true);
  expect(caught('className="border-red-500/50"')).toBe(true);
  expect(caught('className="border-neon-cyan bg-panel text-ink-cyan"')).toBe(false);
  expect(caught('<a href="#main">')).toBe(false);
  expect(caught("background-color: var(--mg-page);")).toBe(false);
});
```

`frontend/src/lib/theme.test.ts`:

```ts
import { describe, expect, test, vi } from "vitest";

import { setSystemMode } from "@/test/setup";

import {
  isChoice,
  resolve,
  STORAGE_KEY,
  storeChoice,
  storedChoice,
  THEME_SCRIPT,
  type ThemeChoice,
} from "./theme";

const shown = () => document.documentElement.getAttribute("data-theme");

/** Runs the script as the page's head does: as it stands, before anything else. */
function runScript(): void {
  new Function(THEME_SCRIPT)();
}

describe("the mode that is shown", () => {
  test.each([
    ["light", true, "light"],
    ["light", false, "light"],
    ["dark", true, "dark"],
    ["dark", false, "dark"],
    ["system", true, "dark"],
    ["system", false, "light"],
  ] as const)("for the choice %s on a system that is dark=%s is %s", (choice, dark, mode) => {
    expect(resolve(choice, dark)).toBe(mode);
  });
});

describe("the choice", () => {
  test("is as the system, until one is made", () => {
    expect(storedChoice()).toBe("system");
  });

  test("is kept in this browser", () => {
    storeChoice("light");

    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");
    expect(storedChoice()).toBe("light");
  });

  test.each(["", "blue", "DARK", '{"mode":"dark"}'])(
    "is as the system when storage holds %j",
    (stored) => {
      window.localStorage.setItem(STORAGE_KEY, stored);

      expect(storedChoice()).toBe("system");
      expect(isChoice(stored)).toBe(false);
    },
  );
});

describe("the script in the page's head", () => {
  const CASES: [ThemeChoice | null, "light" | "dark", string][] = [
    [null, "dark", "dark"],
    [null, "light", "light"],
    ["system", "dark", "dark"],
    ["system", "light", "light"],
    ["light", "dark", "light"],
    ["dark", "light", "dark"],
  ];

  test.each(CASES)("with the choice %s on a %s system shows %s", (choice, system, mode) => {
    if (choice !== null) window.localStorage.setItem(STORAGE_KEY, choice);
    setSystemMode(system);

    runScript();

    expect(shown()).toBe(mode);
    // The same decision as the code that runs later, or the mode would change under the reader.
    expect(resolve(storedChoice(), system === "dark")).toBe(mode);
  });

  test("leaves the page as it is when storage cannot be read", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });

    expect(runScript).not.toThrow();
    expect(shown()).toBeNull();
    expect(storedChoice()).toBe("system");
    expect(() => storeChoice("dark")).not.toThrow();
  });

  test("is one statement that a text cannot break out of", () => {
    expect(THEME_SCRIPT).not.toContain("</");
    expect(THEME_SCRIPT.startsWith("(function(){try{")).toBe(true);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 3 files fail: `ENOENT ... src/styles/tokens.css`, `Failed to resolve import "./theme"`, and the search for literal colours finds too few files to be looking anywhere.

- [ ] **Step 3: Add the typefaces**

The three fonts are published under the SIL Open Font License by the Fontsource project. Fetch them once, outside the project, and copy the Latin variable files and the licences:

```bash
mkdir /tmp/fonts && cd /tmp/fonts && pnpm init
pnpm add @fontsource-variable/oxanium @fontsource-variable/inter @fontsource-variable/jetbrains-mono
N=node_modules/@fontsource-variable
F=<repository>/frontend/src/fonts
mkdir -p $F
cp $N/oxanium/files/oxanium-latin-wght-normal.woff2 $N/inter/files/inter-latin-wght-normal.woff2 \
   $N/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2 $F/
cp $N/oxanium/LICENSE $F/OXANIUM-LICENSE.txt
cp $N/inter/LICENSE $F/INTER-LICENSE.txt
cp $N/jetbrains-mono/LICENSE $F/JETBRAINS-MONO-LICENSE.txt
```

Expected: six files in `frontend/src/fonts/`; the three fonts are 14, 48 and 40 KB.

- [ ] **Step 4: Implement**

`frontend/src/styles/tokens.css`:

```css
/*
 * Design tokens: the only place a colour is written.
 *
 * One set for each mode, with the same names in both. Components use the utilities
 * that globals.css makes from these, never a value of their own. Two tests hold this:
 * one computes the contrast of every text tone on every surface, in both modes, and
 * one fails on a literal colour anywhere else.
 *
 * An accent has two tones. `neon-*` is for borders, glows and icons, where 3 to 1 is
 * enough. `ink-*` is for text, which needs 4.5 to 1.
 */

:root,
:root[data-theme="dark"] {
  color-scheme: dark;

  /* Surfaces */
  --mg-page: #07080d;
  --mg-panel: #0d1018;
  --mg-raised: #151a26;
  --mg-field: #10141e;

  /* Lines */
  --mg-line: #2a3348;
  --mg-line-strong: #5b6a8f;

  /* Text */
  --mg-fg: #e6ebf5;
  --mg-fg-muted: #a3aec4;
  --mg-fg-subtle: #8f9ab3;

  /* What is pressed to go on, and to destroy */
  --mg-primary: #00e5ff;
  --mg-on-primary: #031418;
  --mg-danger: #ff5c7a;
  --mg-on-danger: #1c0308;

  /* Accents */
  --mg-neon-cyan: #00e5ff;
  --mg-ink-cyan: #5cefff;
  --mg-neon-magenta: #ff2bd6;
  --mg-ink-magenta: #ff7ae5;
  --mg-neon-acid: #c6ff00;
  --mg-ink-acid: #d4ff4d;

  /* Status: always beside an icon and a word */
  --mg-ok: #3dffa2;
  --mg-ink-ok: #7dffc0;
  --mg-warn: #ffb020;
  --mg-ink-warn: #ffc65c;
  --mg-bad: #ff5c7a;
  --mg-ink-bad: #ff96a8;

  /* Where the keyboard is: a colour nothing else in a control has */
  --mg-focus: #c6ff00;

  --mg-glow-sm: 0 0 10px color-mix(in srgb, var(--mg-neon-cyan) 40%, transparent);
  --mg-glow-md:
    0 0 0 1px var(--mg-neon-cyan), 0 0 20px color-mix(in srgb, var(--mg-neon-cyan) 55%, transparent);
  --mg-grid: color-mix(in srgb, var(--mg-line) 45%, transparent);
}

:root[data-theme="light"] {
  color-scheme: light;

  /* Surfaces */
  --mg-page: #f2f4f9;
  --mg-panel: #ffffff;
  --mg-raised: #e8ecf5;
  --mg-field: #ffffff;

  /* Lines */
  --mg-line: #c3cbde;
  --mg-line-strong: #6f7b99;

  /* Text */
  --mg-fg: #10131c;
  --mg-fg-muted: #465069;
  --mg-fg-subtle: #566280;

  /* What is pressed to go on, and to destroy */
  --mg-primary: #00728f;
  --mg-on-primary: #ffffff;
  --mg-danger: #c40030;
  --mg-on-danger: #ffffff;

  /* Accents */
  --mg-neon-cyan: #0090ad;
  --mg-ink-cyan: #00647d;
  --mg-neon-magenta: #d400ab;
  --mg-ink-magenta: #a30085;
  --mg-neon-acid: #6c9100;
  --mg-ink-acid: #4a6400;

  /* Status: always beside an icon and a word */
  --mg-ok: #008a4e;
  --mg-ink-ok: #006b3c;
  --mg-warn: #a86a00;
  --mg-ink-warn: #855400;
  --mg-bad: #d6002f;
  --mg-ink-bad: #b00027;

  /* Where the keyboard is: a colour nothing else in a control has */
  --mg-focus: #a30085;

  --mg-glow-sm: 0 0 8px color-mix(in srgb, var(--mg-neon-cyan) 30%, transparent);
  --mg-glow-md:
    0 0 0 1px var(--mg-neon-cyan), 0 0 14px color-mix(in srgb, var(--mg-neon-cyan) 40%, transparent);
  --mg-grid: color-mix(in srgb, var(--mg-line) 55%, transparent);
}

/* The same in both modes. */
:root {
  --mg-radius: 2px;
  --mg-bevel: 8px;
  --mg-duration-fast: 120ms;
  --mg-duration: 200ms;
}

/* Whoever asks for less motion gets none, and no glow (UI-13). */
@media (prefers-reduced-motion: reduce) {
  :root,
  :root[data-theme="dark"],
  :root[data-theme="light"] {
    --mg-duration-fast: 0ms;
    --mg-duration: 0ms;
    --mg-glow-sm: none;
    --mg-glow-md: none;
  }
}
```

`frontend/src/styles/globals.css`:

```css
@import "tailwindcss";
@import "./tokens.css";

/*
 * The utilities components may use. Tailwind's own palette, shadows and radii are
 * taken out, so a class that names one of its colours does not exist: what is left is
 * made from the tokens.
 */
@theme inline {
  --color-*: initial;
  --color-transparent: transparent;
  --color-current: currentColor;

  --color-page: var(--mg-page);
  --color-panel: var(--mg-panel);
  --color-raised: var(--mg-raised);
  --color-field: var(--mg-field);
  --color-line: var(--mg-line);
  --color-line-strong: var(--mg-line-strong);
  --color-fg: var(--mg-fg);
  --color-fg-muted: var(--mg-fg-muted);
  --color-fg-subtle: var(--mg-fg-subtle);
  --color-primary: var(--mg-primary);
  --color-on-primary: var(--mg-on-primary);
  --color-danger: var(--mg-danger);
  --color-on-danger: var(--mg-on-danger);
  --color-neon-cyan: var(--mg-neon-cyan);
  --color-ink-cyan: var(--mg-ink-cyan);
  --color-neon-magenta: var(--mg-neon-magenta);
  --color-ink-magenta: var(--mg-ink-magenta);
  --color-neon-acid: var(--mg-neon-acid);
  --color-ink-acid: var(--mg-ink-acid);
  --color-ok: var(--mg-ok);
  --color-ink-ok: var(--mg-ink-ok);
  --color-warn: var(--mg-warn);
  --color-ink-warn: var(--mg-ink-warn);
  --color-bad: var(--mg-bad);
  --color-ink-bad: var(--mg-ink-bad);
  --color-focus: var(--mg-focus);

  --shadow-*: initial;
  --shadow-glow-sm: var(--mg-glow-sm);
  --shadow-glow: var(--mg-glow-md);

  --radius-*: initial;
  --radius-sm: var(--mg-radius);

  --font-display: var(--font-oxanium), ui-sans-serif, system-ui, sans-serif;
  --font-sans: var(--font-inter), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-jetbrains-mono), ui-monospace, monospace;

  --default-transition-duration: var(--mg-duration-fast);
}

@layer base {
  html {
    background-color: var(--mg-page);
    color: var(--mg-fg);
    font-family: var(--font-sans);
  }

  body {
    min-height: 100dvh;
    /* A faint grid, as on a technical drawing. */
    background-image:
      linear-gradient(var(--mg-grid) 1px, transparent 1px),
      linear-gradient(90deg, var(--mg-grid) 1px, transparent 1px);
    background-size: 40px 40px;
  }

  h1,
  h2,
  h3 {
    font-family: var(--font-display);
    letter-spacing: 0.04em;
  }

  :focus-visible {
    outline: 2px solid var(--mg-focus);
    outline-offset: 2px;
  }

  ::selection {
    background-color: var(--mg-ink-magenta);
    color: var(--mg-page);
  }
}

/* A cut corner where the browser can draw one, a square one elsewhere. */
@utility bevel {
  border-radius: var(--mg-radius);
  @supports (corner-shape: bevel) {
    border-radius: var(--mg-bevel);
    corner-shape: bevel;
  }
}

/* Navigation and small headings: the display face, in capitals, widely spaced. */
@utility label-caps {
  font-family: var(--font-display);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}
```

`frontend/src/lib/fonts.ts`:

```ts
import localFont from "next/font/local";

// The files are in the repository, with their licences beside them: nothing is fetched
// when the UI is built or when it is used (UI-14). Each is a variable font, Latin only.
// A letter outside it is drawn with the system's own font.

/** Headings and navigation. */
export const oxanium = localFont({
  src: "../fonts/oxanium-latin-wght-normal.woff2",
  variable: "--font-oxanium",
  weight: "200 800",
  display: "swap",
});

/** Text and tables. */
export const inter = localFont({
  src: "../fonts/inter-latin-wght-normal.woff2",
  variable: "--font-inter",
  weight: "100 900",
  display: "swap",
});

/** Coordinates, paths, checksums and code. */
export const jetbrainsMono = localFont({
  src: "../fonts/jetbrains-mono-latin-wght-normal.woff2",
  variable: "--font-jetbrains-mono",
  weight: "100 800",
  display: "swap",
});
```

`frontend/src/lib/theme.ts`:

```ts
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
 */
export const THEME_SCRIPT = `(function(){try{var c=localStorage.getItem(${JSON.stringify(
  STORAGE_KEY,
)});var d=c==="dark"||(c!=="light"&&matchMedia(${JSON.stringify(
  DARK_QUERY,
)}).matches);document.documentElement.setAttribute("data-theme",d?"dark":"light")}catch(e){}})()`;
```

`frontend/src/components/theme-provider.tsx`:

```tsx
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import {
  applyMode,
  DARK_QUERY,
  resolve,
  STORAGE_KEY,
  storeChoice,
  storedChoice,
  type Mode,
  type ThemeChoice,
} from "@/lib/theme";

type Theme = { choice: ThemeChoice; mode: Mode; choose: (choice: ThemeChoice) => void };

const ThemeContext = createContext<Theme | null>(null);

// The choice lives in the browser's storage, and the system's mode in a media query.
// Both are outside React, so they are read as external stores. The page's head has
// already set the mode by the time any of this runs.
const CHANGED = "megooarti-theme-changed";

function subscribe(notify: () => void): () => void {
  const system = window.matchMedia(DARK_QUERY);
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === STORAGE_KEY) notify();
  };
  system.addEventListener("change", notify);
  window.addEventListener("storage", onStorage);
  window.addEventListener(CHANGED, notify);
  return () => {
    system.removeEventListener("change", notify);
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(CHANGED, notify);
  };
}

const systemIsDark = () => window.matchMedia(DARK_QUERY).matches;

export function ThemeProvider({ children }: { children: ReactNode }) {
  // On the server nothing is known: "system", and dark, which is what the markup says.
  const choice = useSyncExternalStore<ThemeChoice>(subscribe, storedChoice, () => "system");
  const dark = useSyncExternalStore(subscribe, systemIsDark, () => true);
  const mode = resolve(choice, dark);

  // Before paint, so a change of the system's mode or of the choice never shows late.
  useLayoutEffect(() => applyMode(mode), [mode]);

  const choose = useCallback((next: ThemeChoice) => {
    storeChoice(next);
    window.dispatchEvent(new Event(CHANGED));
  }, []);

  const theme = useMemo(() => ({ choice, mode, choose }), [choice, mode, choose]);
  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
  const theme = useContext(ThemeContext);
  if (theme === null) throw new Error("useTheme is used outside ThemeProvider");
  return theme;
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 205 passed in 5 files. If a contrast test fails, change the colour in `tokens.css`, never the threshold.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): design tokens, typefaces and the mode"
```

---

### Task 3: The session's rules, permissions and the navigation

**Files:**
- Create: `frontend/messages/en.json`, `frontend/src/global.d.ts`
- Create: `frontend/src/lib/session/permissions.ts`, `frontend/src/lib/session/rules.ts`, `frontend/src/lib/session/session.ts`
- Create: `frontend/src/lib/navigation.ts`
- Test: `frontend/src/test/render.tsx`
- Test: `frontend/src/lib/session/permissions.test.ts`, `frontend/src/lib/session/rules.test.ts`, `frontend/src/lib/navigation.test.ts`

**Interfaces:**
- Consumes: `api`, `ApiError`, `setCsrfToken`, `SessionInfo`, `leaveTo` (Task 1); `ThemeProvider` (Task 2).
- Produces:
  - `grants(pattern, permission)`, `anyGrants(patterns, permission)`, `isValidPermission(permission)`.
  - `HOME`, `SIGN_IN`, `CHANGE_PASSWORD`; `Decision`; `decide(session, path, next?)`; `returnPath(wanted)`; `allows(session, permission)`; `isAnonymous(session)`.
  - `SESSION_KEY`; `useSession()`; `useSignIn()`; `useSignOut()`; `useChangePassword()`; `sessionMayHaveChanged(error)`.
  - `NAVIGATION`, `NavArea`, `NavItem`, `visible(areas, session)`, `isCurrent(item, pathname)`.
  - Every message of the UI, typed: a key that does not exist is a type error.
  - For tests: `renderUi(ui, { session? }) -> RenderResult & { client }`; the sessions `ADMIN`, `NOBODY`, `VISITOR`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/test/render.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";

import { ThemeProvider } from "@/components/theme-provider";
import type { SessionInfo } from "@/lib/api/types";
import { SESSION_KEY } from "@/lib/session/session";

import messages from "../../messages/en.json";

/** A person who is signed in and may do everything. */
export const ADMIN: SessionInfo = {
  authenticated: true,
  method: "session",
  user: {
    id: "0190c7c2-0000-7000-8000-000000000001",
    username: "admin",
    display_name: "Ada Admin",
    email: null,
  },
  permissions: ["*"],
  must_change_password: false,
  csrf_token: "csrf-of-this-session",
};

/** Nobody is signed in, and the server has no anonymous access. */
export const NOBODY: SessionInfo = {
  authenticated: false,
  method: null,
  user: null,
  permissions: [],
  must_change_password: false,
  csrf_token: null,
};

/** Nobody is signed in, and the server lets such a visitor browse. */
export const VISITOR: SessionInfo = {
  ...NOBODY,
  method: "anonymous",
  permissions: ["repository:*:*:browse", "repository:*:*:read"],
};

export type Rendered = RenderResult & { client: QueryClient };

/**
 * Renders with what every screen has around it: the texts, the mode, and the data.
 * With `session`, the session is already known, as it is once the shell has asked.
 */
export function renderUi(ui: ReactElement, options: { session?: SessionInfo } = {}): Rendered {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  if (options.session) client.setQueryData(SESSION_KEY, options.session);
  const result = render(
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      <QueryClientProvider client={client}>
        <ThemeProvider>{ui}</ThemeProvider>
      </QueryClientProvider>
    </NextIntlClientProvider>,
  );
  return { ...result, client };
}
```

`frontend/src/lib/session/permissions.test.ts`:

```ts
import { expect, test } from "vitest";

import { anyGrants, grants, isValidPermission } from "./permissions";

// The cases of the backend's own tests (backend/tests/security/test_permissions.py):
// the two must agree, or the UI offers what the API refuses.
test.each([
  ["*", "admin:users:write", true],
  ["admin:users:*", "admin:users:write", true],
  ["admin:users:read", "admin:users:write", false],
  ["admin:users:write", "admin:users:write", true],
  ["repository:*:*:read", "repository:maven:releases:read", true],
  ["repository:*:*:read", "repository:maven:releases:delete", false],
  ["repository:maven", "repository:maven:releases:delete", true],
  ["repository:maven", "repository:npm:internal:read", false],
  ["admin", "admin:settings:write", true],
  ["repository:maven:releases:read:extra", "repository:maven:releases:read", false],
  ["admin:Users:read", "admin:users:read", false],
  ["*:users:read", "admin:users:read", true],
])("the pattern %s grants %s: %s", (pattern, permission, expected) => {
  expect(grants(pattern, permission)).toBe(expected);
});

test("one pattern that grants is enough, and none grants nothing", () => {
  expect(anyGrants(["admin:roles:read", "admin:users:*"], "admin:users:write")).toBe(true);
  expect(anyGrants(["admin:roles:read"], "admin:users:write")).toBe(false);
  expect(anyGrants([], "admin:users:read")).toBe(false);
});

test("a permission is plain words: no wildcard, nothing empty", () => {
  expect(isValidPermission("admin:users:read")).toBe(true);
  expect(isValidPermission("repository:maven:my.repo-1_x:read")).toBe(true);
  for (const odd of ["admin:*:read", "", "admin::read", "admin:us ers", "é"]) {
    expect(isValidPermission(odd)).toBe(false);
  }
});
```

`frontend/src/lib/session/rules.test.ts`:

```ts
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
  ])("%j is not, and the home screen is used", (wanted) => {
    expect(returnPath(wanted)).toBe("/");
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
```

`frontend/src/lib/navigation.test.ts`:

```ts
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 3 files fail: `Failed to resolve import "./permissions"`, `"./rules"`, `"./navigation"`. The 205 earlier tests pass.

- [ ] **Step 3: Implement**

`frontend/messages/en.json`:

```json
{
  "app": {
    "name": "MegooArti",
    "tagline": "Repository and artifact manager",
    "skipToContent": "Skip to the content",
    "loading": "Loading",
    "mainNavigation": "Main",
    "openNavigation": "Open the navigation",
    "closeNavigation": "Close the navigation"
  },
  "nav": {
    "areas": {
      "browse": "Browse",
      "administration": "Administration"
    },
    "items": {
      "repositories": "Repositories"
    }
  },
  "theme": {
    "label": "Mode",
    "current": "Mode: {choice}",
    "light": "Light",
    "dark": "Dark",
    "system": "As the system"
  },
  "account": {
    "menu": "Account of {name}",
    "signedInAs": "Signed in as",
    "changePassword": "Change password",
    "signOut": "Sign out",
    "signIn": "Sign in"
  },
  "signIn": {
    "title": "Sign in",
    "username": "User name",
    "password": "Password",
    "submit": "Sign in",
    "wrong": "The user name or the password is not correct.",
    "tooManyAttempts": "Too many attempts. Wait a little, and try again.",
    "cookieNotKeptTitle": "Your browser did not keep the session",
    "cookieNotKept": "The name and password were right, but the session cookie was not kept. It is marked Secure, and this address is plain HTTP on a host that is not localhost. Use HTTPS, or ask the administrator to set MEGOOARTI_SESSION_COOKIE_SECURE=false."
  },
  "password": {
    "title": "Change password",
    "mustChangeTitle": "Choose a new password",
    "mustChange": "Your password was set for you. Choose your own before going on.",
    "current": "Current password",
    "new": "New password",
    "newHint": "At least {min} characters.",
    "repeat": "New password, again",
    "submit": "Change password",
    "changed": "Your password is changed.",
    "tooShort": "The password must be at least {min} characters long.",
    "notTheSame": "The two new passwords are not the same.",
    "notDifferent": "The new password must be different from the current one."
  },
  "home": {
    "title": "Repositories",
    "intro": "The repositories you can browse.",
    "columns": {
      "name": "Name",
      "format": "Format",
      "type": "Type",
      "status": "Status",
      "address": "Address"
    },
    "online": "Online",
    "offline": "Offline",
    "types": {
      "hosted": "Hosted",
      "proxy": "Proxy",
      "group": "Group"
    },
    "emptyTitle": "No repositories",
    "empty": "There is no repository you can browse. An administrator creates repositories and says who may use them.",
    "more": "Showing {shown} of {total}."
  },
  "copy": {
    "label": "Copy {what}",
    "copied": "Copied",
    "failed": "Could not copy"
  },
  "states": {
    "tryAgain": "Try again",
    "errorTitle": "This did not work",
    "requestId": "Request {id}",
    "code": "Code {code}"
  },
  "errors": {
    "network_error": "The server could not be reached. Check the connection, and try again.",
    "unexpected_answer": "The server answered in a way this page does not understand.",
    "forbidden": "You do not have permission to do this.",
    "unauthorized": "You are not signed in, or your session has ended.",
    "not_found": "This was not found.",
    "internal_error": "The server met a fault. It has been logged.",
    "fallback": "Something went wrong."
  },
  "confirm": {
    "cancel": "Cancel"
  },
  "notFound": {
    "title": "There is nothing at this address",
    "body": "The page may have moved, or the address may be mistyped.",
    "home": "Go to the repositories"
  },
  "crash": {
    "title": "This page stopped working",
    "body": "Something in the page itself failed. Loading it again usually helps.",
    "reload": "Load the page again"
  }
}
```

`frontend/src/global.d.ts`:

```ts
import type messages from "../messages/en.json";

// A message that does not exist is then a type error where it is asked for.
declare module "next-intl" {
  interface AppConfig {
    Locale: "en";
    Messages: typeof messages;
  }
}
```

`frontend/src/lib/session/permissions.ts`:

```ts
/**
 * Whether a caller's permission patterns grant a permission, matched as the backend
 * matches them (`megooarti.security.permissions`). The UI uses this to hide what a
 * caller could not use. It is a courtesy: the API decides.
 */

const SEGMENT = /^[A-Za-z0-9_.-]+$/;

/** A permission that could not shift segments: every part is a plain word. */
export function isValidPermission(permission: string): boolean {
  return permission.split(":").every((part) => SEGMENT.test(part));
}

/** A pattern grants what it is a prefix of, with `*` for any one segment. */
export function grants(pattern: string, permission: string): boolean {
  const granted = pattern.split(":");
  const required = permission.split(":");
  if (granted.length > required.length) return false;
  return granted.every((have, index) => have === "*" || have === required[index]);
}

export function anyGrants(patterns: readonly string[], permission: string): boolean {
  return patterns.some((pattern) => grants(pattern, permission));
}
```

`frontend/src/lib/session/rules.ts`:

```ts
/**
 * What a visitor is shown, decided from the session and the address alone. No React
 * and no requests here: the rules of the design's section 7, as functions.
 */
import type { SessionInfo } from "@/lib/api/types";

import { anyGrants, isValidPermission } from "./permissions";

export const HOME = "/";
export const SIGN_IN = "/login";
export const CHANGE_PASSWORD = "/account/password";
// What only a person who is signed in has.
const ACCOUNT_AREA = "/account";

export type Decision = { show: true } | { show: false; goTo: string };

/** Nobody is signed in, and the server lets such a visitor browse. */
export function isAnonymous(session: SessionInfo): boolean {
  return !session.authenticated && session.method !== null;
}

/** Whether to offer something that needs this permission. */
export function allows(session: SessionInfo, permission: string): boolean {
  if (!isValidPermission(permission)) return false;
  // Whatever roles the anonymous user holds, nobody administers anonymously.
  if (!session.authenticated && permission.startsWith("admin:")) return false;
  return anyGrants(session.permissions, permission);
}

/**
 * Where to go after signing in: the screen that was asked for, if it is one of ours.
 * Anything else, such as another site's address, is the home screen.
 */
export function returnPath(wanted: string | null | undefined): string {
  if (!wanted || !wanted.startsWith("/") || wanted.startsWith("//") || wanted.includes("\\")) {
    return HOME;
  }
  if (wanted === SIGN_IN || wanted.startsWith(`${SIGN_IN}?`)) return HOME;
  return wanted;
}

function signInFor(path: string): string {
  return path === HOME ? SIGN_IN : `${SIGN_IN}?next=${encodeURIComponent(path)}`;
}

/**
 * `path` is the address with its query. `next` is where the sign-in screen was asked
 * to return to.
 */
export function decide(session: SessionInfo, path: string, next: string | null = null): Decision {
  const pathname = path.split("?")[0] ?? path;
  if (pathname === SIGN_IN) {
    if (!session.authenticated) return { show: true };
    const onward = session.must_change_password ? CHANGE_PASSWORD : returnPath(next);
    return { show: false, goTo: onward };
  }
  if (session.authenticated) {
    if (session.must_change_password && pathname !== CHANGE_PASSWORD) {
      return { show: false, goTo: CHANGE_PASSWORD };
    }
    return { show: true };
  }
  const inAccount = pathname === ACCOUNT_AREA || pathname.startsWith(`${ACCOUNT_AREA}/`);
  if (isAnonymous(session) && !inAccount) return { show: true };
  return { show: false, goTo: signInFor(path) };
}
```

`frontend/src/lib/session/session.ts`:

```ts
"use client";

/** The session: who is signed in, asked of the API, and the three things that change it. */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api, ApiError, setCsrfToken } from "@/lib/api/client";
import type { SessionInfo } from "@/lib/api/types";
import { leaveTo } from "@/lib/browser";

import { HOME } from "./rules";

export const SESSION_KEY = ["session"] as const;

async function fetchSession(): Promise<SessionInfo> {
  const session = await api.get<SessionInfo>("/auth/session");
  setCsrfToken(session.csrf_token);
  return session;
}

function keep(client: QueryClient, session: SessionInfo): void {
  setCsrfToken(session.csrf_token);
  client.setQueryData(SESSION_KEY, session);
}

/** Everything that was fetched belongs to whoever was signed in. */
function forgetTheRest(client: QueryClient): void {
  client.removeQueries({ predicate: (query) => query.queryKey[0] !== SESSION_KEY[0] });
}

export function useSession() {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: fetchSession,
    // It changes when this page changes it, or when the server ends it, which a
    // refused request reports.
    staleTime: Infinity,
    retry: false,
  });
}

export type Credentials = { username: string; password: string };

/**
 * Signs in. The answer says who signed in; asking for the session afterwards says
 * whether the browser kept the cookie. If it did not, the error's code is
 * `cookie_not_kept`.
 */
export function useSignIn() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (credentials: Credentials): Promise<SessionInfo> => {
      await api.post<SessionInfo>("/auth/login", credentials);
      const session = await fetchSession();
      if (!session.authenticated) throw new ApiError(0, "cookie_not_kept", "");
      return session;
    },
    onSuccess: (session) => {
      forgetTheRest(client);
      keep(client, session);
    },
  });
}

/**
 * Signs out, and loads the home screen afresh: nothing the page held for whoever was
 * signed in is left in memory, and the next visitor starts where any visitor does.
 */
export function useSignOut() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/auth/logout"),
    onSuccess: () => {
      forgetTheRest(client);
      setCsrfToken(null);
      leaveTo(HOME);
    },
  });
}

export type PasswordChange = { current_password: string; new_password: string };

export function useChangePassword() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (change: PasswordChange): Promise<SessionInfo> => {
      await api.put<void>("/me/password", change);
      return fetchSession();
    },
    onSuccess: (session) => keep(client, session),
  });
}

/**
 * For a request the server refused: `401` means the session has ended, and a
 * password that must be changed means the session says so now. Either way the session
 * is asked for again, and what is shown follows from it.
 */
export function sessionMayHaveChanged(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return error.status === 401 || error.code === "password_change_required";
}
```

`frontend/src/lib/navigation.ts`:

```ts
/**
 * The navigation, as data. A screen is put into the navigation by adding an item here,
 * with the permission its API needs: the item is then shown only to those who hold it.
 */
import { Boxes, type LucideIcon } from "lucide-react";
import type { Route } from "next";

import type { SessionInfo } from "@/lib/api/types";
import { allows } from "@/lib/session/rules";

export type AreaKey = "browse" | "administration";
export type ItemKey = "repositories";

export type NavItem = {
  /** Its name is the message `nav.items.<key>`. */
  key: ItemKey;
  href: Route;
  icon: LucideIcon;
  /** What a caller must hold to be shown it. Without one, everybody is. */
  permission?: string;
};

export type NavArea = {
  /** Its name is the message `nav.areas.<key>`. */
  key: AreaKey;
  items: NavItem[];
};

// Browsing first, then administration (UI-2). Plan 10 adds its screens to both.
export const NAVIGATION: readonly NavArea[] = [
  { key: "browse", items: [{ key: "repositories", href: "/", icon: Boxes }] },
  { key: "administration", items: [] },
];

/** The areas and items to show this caller. An area with nothing in it is left out. */
export function visible(areas: readonly NavArea[], session: SessionInfo): NavArea[] {
  return areas
    .map((area) => ({
      ...area,
      items: area.items.filter(
        (item) => item.permission === undefined || allows(session, item.permission),
      ),
    }))
    .filter((area) => area.items.length > 0);
}

/** Whether an item is where the visitor is: its own address, or anything under it. */
export function isCurrent(item: NavItem, pathname: string): boolean {
  if (item.href === "/") return pathname === "/";
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 250 passed in 8 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/messages frontend/src
git commit -m "feat(frontend): the session's rules, permissions and the navigation"
```

---

### Task 4: The component set

**Files:**
- Create: `frontend/src/lib/errors.ts`
- Create: `frontend/src/components/ui/spinner.tsx`, `button.tsx`, `field.tsx`, `panel.tsx`, `alert.tsx`, `states.tsx`, `menu.tsx`, `confirm-dialog.tsx`, `table.tsx`, `copy-button.tsx`, `link.tsx`
- Test: `frontend/src/test/axe.ts`, `frontend/src/components/ui/ui.test.tsx`

**Interfaces:**
- Consumes: `cn`, `isApiError`, `ApiError` (Task 1); the utilities (Task 2); the messages and `renderUi` (Task 3).
- Produces:
  - `Button({ variant?: "primary" | "secondary" | "ghost" | "danger", size?: "md" | "sm", busy?, asChild? })`.
  - `TextField({ label, hint?, error?, ...input })`.
  - `Panel`, `PageHeader({ title, intro?, children? })`.
  - `Alert({ tone?: "info" | "success" | "warning" | "danger", title? })`, `StatusTag({ tone })`, `Tone`.
  - `LoadingState`, `Skeleton`, `EmptyState({ title, action? })`, `ErrorState({ error, onRetry? })`.
  - `Menu`, `MenuTrigger`, `MenuContent`, `MenuItem`, `MenuLabel`, `MenuSeparator`, `MenuRadioGroup`, `MenuRadioItem`.
  - `ConfirmDialog({ open, onOpenChange, title, confirmLabel, onConfirm, busy? })`.
  - `Table({ caption })`, `Th`, `Td`; `CopyButton({ text, what })`; `AppLink` (never prefetches); `Spinner`.
  - `useErrorText() -> (error) => string`.
  - For tests: `expectAccessible(container?)`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/test/axe.ts`:

```ts
import axe from "axe-core";
import { expect } from "vitest";

/**
 * Fails if what is rendered breaks an accessibility rule: a control without a name, a
 * field without a label, a wrong role. Colour contrast is not judged here, because
 * jsdom draws nothing: the tokens' own test computes it, and the browser tests see it.
 */
export async function expectAccessible(container: Element = document.body): Promise<void> {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
  });
  const found = results.violations.map(
    (violation) => `${violation.id}: ${violation.nodes.map((node) => node.html).join(" | ")}`,
  );
  expect(found).toEqual([]);
}
```

`frontend/src/components/ui/ui.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, test, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import { expectAccessible } from "@/test/axe";
import { renderUi } from "@/test/render";

import { Alert, StatusTag } from "./alert";
import { Button } from "./button";
import { ConfirmDialog } from "./confirm-dialog";
import { CopyButton } from "./copy-button";
import { TextField } from "./field";
import { Menu, MenuContent, MenuItem, MenuRadioGroup, MenuRadioItem, MenuTrigger } from "./menu";
import { PageHeader, Panel } from "./panel";
import { EmptyState, ErrorState, LoadingState } from "./states";
import { Table, Td, Th } from "./table";

describe("a button", () => {
  test("is pressed with the mouse and with the keyboard", async () => {
    const user = userEvent.setup();
    const pressed = vi.fn();
    renderUi(<Button onClick={pressed}>Save</Button>);

    await user.click(screen.getByRole("button", { name: "Save" }));
    await user.keyboard("{Enter}");
    await user.keyboard(" ");

    expect(pressed).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
  });

  test("cannot be pressed again while what it started is under way, and says so", async () => {
    const user = userEvent.setup();
    const pressed = vi.fn();
    renderUi(
      <Button busy onClick={pressed}>
        Save
      </Button>,
    );

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(pressed).not.toHaveBeenCalled();
    expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button")).toBeDisabled();
  });

  test("can be a link that looks like one", async () => {
    renderUi(
      <Button asChild variant="primary">
        <a href="/login">Sign in</a>
      </Button>,
    );

    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("button")).toBeNull();
    await expectAccessible();
  });
});

describe("a field", () => {
  test("has a label, and its hint is read with it", async () => {
    renderUi(<TextField label="New password" hint="At least 8 characters." type="password" />);

    const input = screen.getByLabelText("New password");

    expect(input).toHaveAccessibleDescription("At least 8 characters.");
    expect(input).not.toHaveAttribute("aria-invalid");
    await expectAccessible();
  });

  test("says what is wrong in place of the hint, with an icon beside the words", async () => {
    renderUi(<TextField label="New password" hint="At least 8 characters." error="Too short." />);

    const input = screen.getByLabelText("New password");

    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Too short.");
    expect(screen.queryByText("At least 8 characters.")).toBeNull();
    expect(screen.getByText("Too short.").parentElement?.querySelector("svg")).not.toBeNull();
    await expectAccessible();
  });

  test("two fields with the same label are still two fields", () => {
    renderUi(
      <>
        <TextField label="Password" />
        <TextField label="Password" />
      </>,
    );

    const [first, second] = screen.getAllByLabelText("Password");

    expect(first?.id).not.toBe(second?.id);
  });
});

describe("what a person is told", () => {
  test("a failure interrupts, and anything else waits its turn", async () => {
    renderUi(
      <>
        <Alert tone="danger" title="Not saved">
          The name is taken.
        </Alert>
        <Alert tone="success">Saved.</Alert>
      </>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Not saved");
    expect(screen.getByRole("alert")).toHaveTextContent("The name is taken.");
    expect(screen.getByRole("status")).toHaveTextContent("Saved.");
    await expectAccessible();
  });

  test.each(["info", "success", "warning", "danger"] as const)(
    "a %s is never colour alone: it has an icon and words (UI-15)",
    (tone) => {
      const { container } = renderUi(
        <>
          <Alert tone={tone}>Words</Alert>
          <StatusTag tone={tone}>State</StatusTag>
        </>,
      );

      expect(container.querySelectorAll("svg[aria-hidden='true']")).toHaveLength(2);
      expect(screen.getByText("Words")).toBeVisible();
      expect(screen.getByText("State")).toBeVisible();
    },
  );
});

describe("the states of a screen (UI-5)", () => {
  test("loading says so", async () => {
    renderUi(<LoadingState />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    await expectAccessible();
  });

  test("nothing to show says so, and what could be done", async () => {
    renderUi(
      <EmptyState title="No repositories" action={<Button>Create one</Button>}>
        An administrator creates them.
      </EmptyState>,
    );

    expect(screen.getByRole("heading", { name: "No repositories" })).toBeVisible();
    expect(screen.getByText("An administrator creates them.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Create one" })).toBeVisible();
    await expectAccessible();
  });

  test("a failure says what went wrong, its code and which request it was", async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    const error = new ApiError(409, "redeploy_disabled", "This cannot be replaced.", [], "req-7");
    renderUi(<ErrorState error={error} onRetry={retry} />);

    const alert = screen.getByRole("alert");
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(alert).toHaveTextContent("This cannot be replaced.");
    expect(alert).toHaveTextContent("Code redeploy_disabled");
    expect(alert).toHaveTextContent("Request req-7");
    expect(retry).toHaveBeenCalledOnce();
    await expectAccessible();
  });

  test.each([
    [new ApiError(0, "network_error", ""), "The server could not be reached."],
    [new ApiError(502, "unexpected_answer", ""), "does not understand"],
    [new ApiError(403, "forbidden", "You do not have permission to do this."), "permission"],
    [new ApiError(418, "teapot", ""), "Something went wrong."],
    [new TypeError("x is not a function"), "Something went wrong."],
  ])("a failure the UI has words for uses them: %s", (error, words) => {
    renderUi(<ErrorState error={error} />);

    expect(screen.getByRole("alert")).toHaveTextContent(words);
    expect(screen.getByRole("alert")).not.toHaveTextContent("x is not a function");
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("asking before something is destroyed (UI-5)", () => {
  function Deleting({ onConfirm }: { onConfirm: () => void }) {
    const [open, setOpen] = useState(false);
    return (
      <>
        <Button onClick={() => setOpen(true)}>Delete</Button>
        <ConfirmDialog
          open={open}
          onOpenChange={setOpen}
          title="Delete app-1.0.jar?"
          confirmLabel="Delete it"
          onConfirm={onConfirm}
        >
          It cannot be brought back.
        </ConfirmDialog>
      </>
    );
  }

  test("focus starts on Cancel, so that Enter by habit destroys nothing", async () => {
    const user = userEvent.setup();
    const confirmed = vi.fn();
    renderUi(<Deleting onConfirm={confirmed} />);

    await user.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete app-1.0.jar?" });

    expect(dialog).toHaveAccessibleDescription("It cannot be brought back.");
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus(),
    );
    await expectAccessible();

    await user.keyboard("{Enter}");

    expect(confirmed).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    // Focus goes back to what opened it, so the keyboard is where it was.
    await waitFor(() => expect(screen.getByRole("button", { name: "Delete" })).toHaveFocus());
  });

  test("Escape closes it, and only the button that says so destroys", async () => {
    const user = userEvent.setup();
    const confirmed = vi.fn();
    renderUi(<Deleting onConfirm={confirmed} />);

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(confirmed).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.keyboard("{Tab}{Enter}");

    expect(confirmed).toHaveBeenCalledOnce();
    // It stays until whoever asked closes it: the deletion may still be under way.
    expect(screen.getByRole("alertdialog")).toBeVisible();
  });
});

describe("a menu", () => {
  function Example({ onChoose }: { onChoose: (what: string) => void }) {
    const [mode, setMode] = useState("dark");
    return (
      <Menu>
        <MenuTrigger>Options</MenuTrigger>
        <MenuContent>
          <MenuItem onSelect={() => onChoose("rename")}>Rename</MenuItem>
          <MenuItem onSelect={() => onChoose("delete")}>Delete</MenuItem>
          <MenuRadioGroup value={mode} onValueChange={setMode}>
            <MenuRadioItem value="light">Light</MenuRadioItem>
            <MenuRadioItem value="dark">Dark</MenuRadioItem>
          </MenuRadioGroup>
        </MenuContent>
      </Menu>
    );
  }

  test("is opened and used with the keyboard alone, and gives focus back (UI-6)", async () => {
    const user = userEvent.setup();
    const chosen = vi.fn();
    renderUi(<Example onChoose={chosen} />);

    await user.tab();
    expect(screen.getByRole("button", { name: "Options" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("menu")).toBeVisible();
    await user.keyboard("{ArrowDown}{Enter}");

    expect(chosen).toHaveBeenCalledWith("delete");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByRole("button", { name: "Options" })).toHaveFocus();
  });

  test("says which of its choices is in force", async () => {
    const user = userEvent.setup();
    renderUi(<Example onChoose={() => {}} />);

    await user.click(screen.getByRole("button", { name: "Options" }));
    expect(screen.getByRole("menuitemradio", { name: "Dark" })).toBeChecked();
    await user.click(screen.getByRole("menuitemradio", { name: "Light" }));
    await user.click(screen.getByRole("button", { name: "Options" }));

    expect(screen.getByRole("menuitemradio", { name: "Light" })).toBeChecked();
    expect(screen.getByRole("menuitemradio", { name: "Dark" })).not.toBeChecked();
  });

  test("closes on Escape", async () => {
    const user = userEvent.setup();
    renderUi(<Example onChoose={() => {}} />);

    await user.click(screen.getByRole("button", { name: "Options" }));
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("copying", () => {
  test("puts the text on the clipboard and says that it did", async () => {
    const user = userEvent.setup();
    renderUi(
      <CopyButton text="https://repo.example.com/repository/releases/" what="the address" />,
    );

    await user.click(screen.getByRole("button", { name: "Copy the address" }));

    expect(await navigator.clipboard.readText()).toBe(
      "https://repo.example.com/repository/releases/",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Copied");
    await expectAccessible();
  });

  test("says so when it could not", async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
    renderUi(<CopyButton text="x" what="the address" />);

    await user.click(screen.getByRole("button", { name: "Copy the address" }));

    expect(screen.getByRole("status")).toHaveTextContent("Could not copy");
  });
});

describe("a table and a page", () => {
  test("a table has a name and headers a screen reader can use", async () => {
    renderUi(
      <Panel>
        <PageHeader title="Repositories" intro="What you can browse." />
        <Table caption="Repositories">
          <thead>
            <tr>
              <Th>Name</Th>
              <Th>Format</Th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <Td>releases</Td>
              <Td>maven</Td>
            </tr>
          </tbody>
        </Table>
      </Panel>,
    );

    expect(screen.getByRole("table", { name: "Repositories" })).toBeVisible();
    expect(screen.getAllByRole("columnheader")).toHaveLength(2);
    expect(screen.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
    await expectAccessible();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 1 file fails: `Failed to resolve import "./button"`. The 250 earlier tests pass.

- [ ] **Step 3: Implement**

`frontend/src/lib/errors.ts`:

```ts
"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

import { isApiError } from "@/lib/api/client";

// The failures the UI has its own words for. Anything else is said as the API said it.
const KNOWN = [
  "network_error",
  "unexpected_answer",
  "forbidden",
  "unauthorized",
  "not_found",
  "internal_error",
] as const;
type Known = (typeof KNOWN)[number];

function isKnown(code: string): code is Known {
  return (KNOWN as readonly string[]).includes(code);
}

/** A function that says, for a person, what went wrong. */
export function useErrorText(): (error: unknown) => string {
  const t = useTranslations("errors");
  return useCallback(
    (error: unknown) => {
      if (!isApiError(error)) return t("fallback");
      if (isKnown(error.code)) return t(error.code);
      return error.message || t("fallback");
    },
    [t],
  );
}
```

`frontend/src/components/ui/spinner.tsx`:

```tsx
import { LoaderCircle } from "lucide-react";

import { cn } from "@/lib/cn";

/** Something is under way. It is decoration: what is under way is said in words beside it. */
export function Spinner({ className }: { className?: string }) {
  return (
    <LoaderCircle
      aria-hidden="true"
      className={cn("size-4 shrink-0 motion-safe:animate-spin", className)}
    />
  );
}
```

`frontend/src/components/ui/button.tsx`:

```tsx
import { Slot } from "radix-ui";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

import { Spinner } from "./spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "md" | "sm";

const BASE =
  "bevel label-caps inline-flex items-center justify-center gap-2 border whitespace-nowrap " +
  "transition-[background-color,border-color,box-shadow,color] select-none " +
  "disabled:cursor-not-allowed disabled:opacity-55 aria-disabled:cursor-not-allowed aria-disabled:opacity-55";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "border-primary bg-primary text-on-primary hover:shadow-glow",
  secondary:
    "border-line-strong bg-panel text-fg hover:border-neon-cyan hover:shadow-glow-sm active:bg-raised",
  ghost: "border-transparent bg-transparent text-fg-muted hover:bg-raised hover:text-fg",
  danger: "border-danger bg-danger text-on-danger hover:brightness-110",
};

const SIZES: Record<ButtonSize, string> = {
  md: "min-h-10 px-4 py-2",
  sm: "min-h-8 px-3 py-1",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** The request it started is still going: it cannot be pressed again, and says so. */
  busy?: boolean;
  /** Style the one child as a button, when it is something else: a link. */
  asChild?: boolean;
  children: ReactNode;
};

export function Button({
  variant = "secondary",
  size = "md",
  busy = false,
  asChild = false,
  className,
  children,
  disabled,
  type,
  ...rest
}: ButtonProps) {
  const classes = cn(BASE, VARIANTS[variant], SIZES[size], className);
  if (asChild) {
    return (
      <Slot.Root className={classes} {...rest}>
        {children}
      </Slot.Root>
    );
  }
  return (
    <button
      type={type ?? "button"}
      className={classes}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <Spinner /> : null}
      {children}
    </button>
  );
}
```

`frontend/src/components/ui/field.tsx`:

```tsx
"use client";

import { CircleAlert } from "lucide-react";
import { useId, type InputHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  label: string;
  /** Said under the field while nothing is wrong. */
  hint?: string;
  /** What is wrong with what was typed. It replaces the hint. */
  error?: string | null;
};

/** A labelled input. Its hint and its error are read out with it. */
export function TextField({ label, hint, error, className, ...input }: TextFieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const described = error ? errorId : hint ? hintId : undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="label-caps text-fg-muted">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={described}
        className={cn(
          "min-h-10 rounded-sm border bg-field px-3 py-2 text-fg placeholder:text-fg-subtle",
          "transition-[border-color,box-shadow] focus:shadow-glow-sm",
          error ? "border-bad" : "border-line-strong hover:border-neon-cyan",
        )}
        {...input}
      />
      {error ? (
        <p id={errorId} className="flex items-start gap-1.5 text-sm text-ink-bad">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </p>
      ) : hint ? (
        <p id={hintId} className="text-sm text-fg-subtle">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
```

`frontend/src/components/ui/panel.tsx`:

```tsx
import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

/** A surface that holds one thing: a form, a table, a state. */
export function Panel({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("bevel border border-line bg-panel", className)} {...rest}>
      {children}
    </div>
  );
}

/** The heading of a screen, with what it is for, and its actions at the end. */
export function PageHeader({
  title,
  intro,
  children,
}: {
  title: string;
  intro?: string;
  children?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-wide text-fg uppercase">{title}</h1>
        {intro ? <p className="mt-1 text-fg-muted">{intro}</p> : null}
      </div>
      {children ? <div className="flex flex-wrap gap-2">{children}</div> : null}
    </header>
  );
}
```

`frontend/src/components/ui/alert.tsx`:

```tsx
import { CircleAlert, CircleCheck, Info, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export type Tone = "info" | "success" | "warning" | "danger";

// A tone is never colour alone (UI-15): each has its own icon, and the text says the rest.
const TONES: Record<Tone, { icon: LucideIcon; border: string; ink: string }> = {
  info: { icon: Info, border: "border-neon-cyan", ink: "text-ink-cyan" },
  success: { icon: CircleCheck, border: "border-ok", ink: "text-ink-ok" },
  warning: { icon: TriangleAlert, border: "border-warn", ink: "text-ink-warn" },
  danger: { icon: CircleAlert, border: "border-bad", ink: "text-ink-bad" },
};

export type AlertProps = {
  tone?: Tone;
  title?: string;
  children?: ReactNode;
  className?: string;
};

/**
 * Something the person should know now. A failure or a warning interrupts a screen
 * reader; anything else waits its turn.
 */
export function Alert({ tone = "info", title, children, className }: AlertProps) {
  const { icon: Icon, border, ink } = TONES[tone];
  const urgent = tone === "danger" || tone === "warning";
  return (
    <div
      role={urgent ? "alert" : "status"}
      className={cn("flex gap-3 rounded-sm border-l-4 bg-raised px-4 py-3", border, className)}
    >
      <Icon aria-hidden="true" className={cn("mt-0.5 size-5 shrink-0", ink)} />
      <div className="min-w-0 text-fg">
        {title ? <p className={cn("font-semibold", ink)}>{title}</p> : null}
        {children ? <div className="text-sm break-words">{children}</div> : null}
      </div>
    </div>
  );
}

/** A state in a word, with its icon: "Online", "Offline". */
export function StatusTag({
  tone,
  children,
  className,
}: {
  tone: Tone;
  children: ReactNode;
  className?: string;
}) {
  const { icon: Icon, border, ink } = TONES[tone];
  return (
    <span
      className={cn(
        "label-caps inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5",
        border,
        ink,
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-3.5 shrink-0" />
      {children}
    </span>
  );
}
```

`frontend/src/components/ui/states.tsx`:

```tsx
"use client";

import { Inbox, RotateCw } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { isApiError } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { useErrorText } from "@/lib/errors";

import { Alert } from "./alert";
import { Button } from "./button";
import { Spinner } from "./spinner";

/** The three states every screen has besides its content (UI-5). */

/** Something is being fetched and there is nothing to draw yet. */
export function LoadingState({ className }: { className?: string }) {
  const t = useTranslations("app");
  return (
    <div
      role="status"
      className={cn("flex items-center justify-center gap-3 p-10 text-fg-muted", className)}
    >
      <Spinner className="size-5 text-ink-cyan" />
      <span>{t("loading")}</span>
    </div>
  );
}

/** A grey shape where content will be. Rows of them stand for a list that is on its way. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("h-4 rounded-sm bg-raised motion-safe:animate-pulse", className)}
    />
  );
}

/** There is nothing to show, which is not a failure: say so, and what could be done. */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 p-10 text-center">
      <Inbox aria-hidden="true" className="size-10 text-neon-magenta" />
      <h2 className="text-lg font-semibold text-fg uppercase">{title}</h2>
      {children ? <p className="max-w-prose text-fg-muted">{children}</p> : null}
      {action}
    </div>
  );
}

/**
 * A request failed. What is said: what went wrong, the API's code for it, and which
 * request it was, so that whoever reports it can name it.
 */
export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const t = useTranslations("states");
  const say = useErrorText();
  const api = isApiError(error) ? error : null;
  return (
    <Alert tone="danger" title={t("errorTitle")} className={className}>
      <p>{say(error)}</p>
      {api ? (
        <p className="mt-1 font-mono text-xs text-fg-muted">
          <span>{t("code", { code: api.code })}</span>
          {api.requestId ? (
            <span className="ml-3">{t("requestId", { id: api.requestId })}</span>
          ) : null}
        </p>
      ) : null}
      {onRetry ? (
        <Button size="sm" className="mt-3" onClick={onRetry}>
          <RotateCw aria-hidden="true" className="size-4" />
          {t("tryAgain")}
        </Button>
      ) : null}
    </Alert>
  );
}
```

`frontend/src/components/ui/menu.tsx`:

```tsx
"use client";

import { Check } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

/**
 * A menu that opens from a button. Radix gives it its behaviour: the arrow keys, Home
 * and End, typing to find an item, Escape, and focus returning to the button.
 */

export const Menu = DropdownMenu.Root;
export const MenuTrigger = DropdownMenu.Trigger;
export const MenuRadioGroup = DropdownMenu.RadioGroup;

const ITEM =
  "flex cursor-default items-center gap-2 rounded-sm px-3 py-2 text-sm text-fg outline-none select-none " +
  "data-[highlighted]:bg-raised data-[highlighted]:text-ink-cyan data-[disabled]:opacity-55";

export function MenuContent({
  className,
  children,
  ...rest
}: ComponentProps<typeof DropdownMenu.Content>) {
  return (
    <DropdownMenu.Portal>
      <DropdownMenu.Content
        sideOffset={8}
        align="end"
        className={cn(
          "bevel z-50 min-w-48 border border-line-strong bg-panel p-1 shadow-glow-sm",
          className,
        )}
        {...rest}
      >
        {children}
      </DropdownMenu.Content>
    </DropdownMenu.Portal>
  );
}

export function MenuItem({ className, ...rest }: ComponentProps<typeof DropdownMenu.Item>) {
  return <DropdownMenu.Item className={cn(ITEM, className)} {...rest} />;
}

export function MenuLabel({ className, ...rest }: ComponentProps<typeof DropdownMenu.Label>) {
  return (
    <DropdownMenu.Label
      className={cn("label-caps px-3 py-2 text-fg-subtle", className)}
      {...rest}
    />
  );
}

export function MenuSeparator() {
  return <DropdownMenu.Separator className="my-1 h-px bg-line" />;
}

/** One of several choices of which one is in force: it shows a tick when it is. */
export function MenuRadioItem({
  className,
  children,
  ...rest
}: ComponentProps<typeof DropdownMenu.RadioItem>) {
  return (
    <DropdownMenu.RadioItem className={cn(ITEM, "relative pr-8", className)} {...rest}>
      {children}
      <DropdownMenu.ItemIndicator className="absolute right-3">
        <Check aria-hidden="true" className="size-4 text-ink-cyan" />
      </DropdownMenu.ItemIndicator>
    </DropdownMenu.RadioItem>
  );
}
```

`frontend/src/components/ui/confirm-dialog.tsx`:

```tsx
"use client";

import { AlertDialog } from "radix-ui";
import { useTranslations } from "next-intl";
import { useRef, type ReactNode } from "react";

import { Button } from "./button";

export type ConfirmDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** What is about to happen, as a question or a statement: "Delete app-1.0.jar?" */
  title: string;
  /** What it means: what is lost, and that it cannot be undone. */
  children: ReactNode;
  /** The word on the button that does it: "Delete". */
  confirmLabel: string;
  onConfirm: () => void;
  /** The action is under way: the dialog stays, and its button says so. */
  busy?: boolean;
};

/**
 * Asks before something is destroyed (UI-5). Focus starts on Cancel, so that Enter
 * pressed by habit destroys nothing, and Escape closes it.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  children,
  confirmLabel,
  onConfirm,
  busy = false,
}: ConfirmDialogProps) {
  const t = useTranslations("confirm");
  // What had the keyboard when the dialog opened. Radix gives focus back to a trigger
  // of its own, and this dialog is opened by whatever its screen chooses.
  const opener = useRef<HTMLElement | null>(null);
  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-40 bg-page/80" />
        <AlertDialog.Content
          onOpenAutoFocus={() => {
            opener.current =
              document.activeElement instanceof HTMLElement ? document.activeElement : null;
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            opener.current?.focus();
          }}
          className="bevel fixed top-1/2 left-1/2 z-50 w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 border border-bad bg-panel p-6"
        >
          <AlertDialog.Title className="text-lg font-semibold text-fg uppercase">
            {title}
          </AlertDialog.Title>
          <AlertDialog.Description asChild>
            <div className="mt-2 text-fg-muted">{children}</div>
          </AlertDialog.Description>
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <AlertDialog.Cancel asChild>
              <Button>{t("cancel")}</Button>
            </AlertDialog.Cancel>
            <Button
              variant="danger"
              busy={busy}
              onClick={(event) => {
                event.preventDefault();
                onConfirm();
              }}
            >
              {confirmLabel}
            </Button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
```

`frontend/src/components/ui/table.tsx`:

```tsx
import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/** A table of rows. It scrolls sideways by itself where the window is narrow (UI-3). */
export function Table({
  className,
  caption,
  children,
  ...rest
}: HTMLAttributes<HTMLTableElement> & { caption: string }) {
  return (
    // `relative`, so that what is hidden from sight inside a cell (it is placed
    // absolutely) scrolls with the table, and does not widen the page.
    <div className="relative overflow-x-auto">
      <table className={cn("w-full border-collapse text-left text-sm", className)} {...rest}>
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

export function Th({ className, ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn(
        "label-caps border-b border-line-strong px-4 py-3 text-fg-muted whitespace-nowrap",
        className,
      )}
      {...rest}
    />
  );
}

export function Td({ className, ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("border-b border-line px-4 py-3 text-fg", className)} {...rest} />;
}
```

`frontend/src/components/ui/copy-button.tsx`:

```tsx
"use client";

import { Check, Copy, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";

type Outcome = "idle" | "copied" | "failed";

/** Copies a piece of text: an address, a checksum, a snippet. It says whether it did. */
export function CopyButton({
  text,
  what,
  className,
}: {
  text: string;
  /** What is copied, for the button's name: "the address of maven-releases". */
  what: string;
  className?: string;
}) {
  const t = useTranslations("copy");
  const [outcome, setOutcome] = useState<Outcome>("idle");

  useEffect(() => {
    if (outcome === "idle") return;
    const timer = window.setTimeout(() => setOutcome("idle"), 2000);
    return () => window.clearTimeout(timer);
  }, [outcome]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setOutcome("copied");
    } catch {
      // No permission, or a page that is not served securely.
      setOutcome("failed");
    }
  }

  const Icon = outcome === "copied" ? Check : outcome === "failed" ? X : Copy;
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={t("label", { what })}
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-sm border border-transparent",
        "text-fg-muted hover:border-neon-cyan hover:text-ink-cyan",
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-4" />
      <span role="status" className="sr-only">
        {outcome === "copied" ? t("copied") : outcome === "failed" ? t("failed") : ""}
      </span>
    </button>
  );
}
```

`frontend/src/components/ui/link.tsx`:

```tsx
import NextLink from "next/link";
import type { ComponentProps } from "react";

/**
 * A link within the UI. Next.js would fetch what a link leads to as soon as it is on
 * the screen. Here nothing is fetched until it is followed: a screen is a shell, its
 * data comes from the API, and a visitor who is not signed in should cause no requests
 * for screens they have not asked for.
 */
export function AppLink(props: ComponentProps<typeof NextLink>) {
  return <NextLink prefetch={false} {...props} />;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 277 passed in 9 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): the component set"
```

---

### Task 5: The shell, and the gate before every screen

**Files:**
- Create: `frontend/src/components/theme-switch.tsx`, `user-menu.tsx`, `app-shell.tsx`, `session-gate.tsx`
- Test: `frontend/src/components/shell.test.tsx`

**Interfaces:**
- Consumes: `useTheme`, `CHOICES`, `isChoice` (Task 2); `decide`, `useSession`, `useSignOut`, `NAVIGATION`, `visible`, `isCurrent`, the route constants (Task 3); the components (Task 4); `navigation`, `mockApi`, `leaveTo` as mocked by the test setup (Task 1).
- Produces:
  - `AppShell({ session, bare?, children })`, `Wordmark`.
  - `UserMenu({ session })`, `ThemeSwitch`.
  - `SessionGate({ shell, children })`: asks for the session, then shows its children (inside the shell if `shell`), or goes where `decide` says.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/shell.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { leaveTo } from "@/lib/browser";
import { STORAGE_KEY } from "@/lib/theme";
import { failure, mockApi } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, NOBODY, renderUi, VISITOR } from "@/test/render";
import { setSystemMode } from "@/test/setup";

import { AppShell } from "./app-shell";
import { SessionGate } from "./session-gate";
import { ThemeSwitch } from "./theme-switch";

const shownMode = () => document.documentElement.getAttribute("data-theme");

describe("the shell", () => {
  test("has a way past the navigation as the first thing focus reaches (UI-6)", async () => {
    const user = userEvent.setup();
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });

    await user.tab();

    const skip = screen.getByRole("link", { name: "Skip to the content" });
    expect(skip).toHaveFocus();
    expect(skip).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByRole("main")).toHaveTextContent("Content");
  });

  test("names its parts, and marks where the visitor is", async () => {
    navigation.at("/");
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });

    const [wide] = screen.getAllByRole("navigation", { name: "Main" });
    const current = within(wide as HTMLElement).getByRole("link", { name: "Repositories" });

    expect(current).toHaveAttribute("aria-current", "page");
    expect(within(wide as HTMLElement).getByText("Browse")).toBeVisible();
    expect(screen.getByRole("banner")).toBeVisible();
    await expectAccessible();
  });

  test("shows no area that has nothing in it", () => {
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });

    // Plan 9 has no administration screen yet, so the area is not there to be empty.
    expect(screen.queryByText("Administration")).toBeNull();
  });

  test("opens its navigation from a button where the window is narrow (UI-3)", async () => {
    const user = userEvent.setup();
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
    const button = screen.getByRole("button", { name: "Open the navigation" });
    const narrow = document.getElementById("narrow-navigation");

    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(narrow).not.toBeVisible();

    await user.click(button);

    expect(screen.getByRole("button", { name: "Close the navigation" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(narrow).toBeVisible();

    await user.click(within(narrow as HTMLElement).getByRole("link", { name: "Repositories" }));

    expect(narrow).not.toBeVisible(); // following a link closes it
  });

  test("has no navigation for whoever must change their password first", () => {
    const pending: SessionInfo = { ...ADMIN, must_change_password: true };
    renderUi(
      <AppShell session={pending} bare>
        Content
      </AppShell>,
      { session: pending },
    );

    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("button", { name: "Open the navigation" })).toBeNull();
    expect(screen.getByRole("button", { name: "Account of Ada Admin" })).toBeVisible();
  });
});

describe("the user menu", () => {
  test("says who is signed in, and leads to changing the password", async () => {
    const user = userEvent.setup();
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });

    await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));
    const menu = screen.getByRole("menu");

    expect(menu).toHaveTextContent("Signed in as");
    expect(menu).toHaveTextContent("admin");
    await expectAccessible();

    await user.click(within(menu).getByRole("menuitem", { name: "Change password" }));

    expect(navigation.router.push).toHaveBeenCalledWith("/account/password");
  });

  test("signs out, forgets what was fetched for that person, and starts afresh at home", async () => {
    const user = userEvent.setup();
    const { calls } = mockApi({ "POST /auth/logout": { status: 204 } });
    const { client } = renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
    client.setQueryData(["content", "repositories"], { items: [{ name: "secret" }] });

    await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));

    await waitFor(() => expect(leaveTo).toHaveBeenCalledWith("/"));
    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual(["POST /auth/logout"]);
    expect(client.getQueryData(["content", "repositories"])).toBeUndefined();
  });

  test("stays signed in, and says nothing false, when signing out failed", async () => {
    const user = userEvent.setup();
    mockApi({ "POST /auth/logout": "network-failure" });
    const { client } = renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });

    await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    expect(leaveTo).not.toHaveBeenCalled();
    expect(client.getQueryData(["session"])).toEqual(ADMIN);
  });

  test("is a way to sign in for a visitor", () => {
    renderUi(<AppShell session={VISITOR}>Content</AppShell>, { session: VISITOR });

    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("button", { name: /Account of/ })).toBeNull();
  });

  test("offers no change of password to whoever is already made to change it", async () => {
    const user = userEvent.setup();
    const pending: SessionInfo = { ...ADMIN, must_change_password: true };
    renderUi(
      <AppShell session={pending} bare>
        Content
      </AppShell>,
      { session: pending },
    );

    await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));

    expect(screen.queryByRole("menuitem", { name: "Change password" })).toBeNull();
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeVisible();
  });
});

describe("the mode switch (UI-10)", () => {
  test("follows the system until a choice is made", async () => {
    setSystemMode("light");
    renderUi(<ThemeSwitch />);

    await waitFor(() => expect(shownMode()).toBe("light"));
    expect(screen.getByRole("button", { name: "Mode: As the system" })).toBeVisible();
  });

  test("shows the choice at once and keeps it in this browser", async () => {
    const user = userEvent.setup();
    setSystemMode("dark");
    renderUi(<ThemeSwitch />);

    await user.click(screen.getByRole("button", { name: "Mode: As the system" }));
    expect(screen.getByRole("menuitemradio", { name: "As the system" })).toBeChecked();
    await user.click(screen.getByRole("menuitemradio", { name: "Light" }));

    expect(shownMode()).toBe("light");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");
    expect(screen.getByRole("button", { name: "Mode: Light" })).toBeVisible();
  });

  test("starts from what was chosen before", async () => {
    window.localStorage.setItem(STORAGE_KEY, "light");
    setSystemMode("dark");
    renderUi(<ThemeSwitch />);

    await waitFor(() => expect(shownMode()).toBe("light"));
    expect(screen.getByRole("button", { name: "Mode: Light" })).toBeVisible();
  });
});

describe("the gate before every screen", () => {
  const gated = (shell: boolean) => (
    <SessionGate shell={shell}>
      <p>The screen</p>
    </SessionGate>
  );

  test("says it is loading until the session is known, then shows the screen in the shell", async () => {
    mockApi({ "GET /auth/session": { json: ADMIN } });
    renderUi(gated(true));

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(screen.queryByText("The screen")).toBeNull();

    expect(await screen.findByText("The screen")).toBeVisible();
    expect(screen.getByRole("banner")).toBeVisible();
    expect(navigation.router.replace).not.toHaveBeenCalled();
  });

  test("sends whoever is not signed in to sign in, and remembers where they were going", async () => {
    mockApi({ "GET /auth/session": { json: NOBODY } });
    navigation.at("/search?q=commons");
    renderUi(gated(true));

    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/login?next=%2Fsearch%3Fq%3Dcommons"),
    );
    expect(screen.queryByText("The screen")).toBeNull();
  });

  test("lets a visitor browse where anonymous access is on", async () => {
    mockApi({ "GET /auth/session": { json: VISITOR } });
    renderUi(gated(true));

    expect(await screen.findByText("The screen")).toBeVisible();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeVisible();
  });

  test("sends whoever must change their password there, from anywhere", async () => {
    mockApi({ "GET /auth/session": { json: { ...ADMIN, must_change_password: true } } });
    navigation.at("/");
    renderUi(gated(true));

    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/account/password"),
    );
    expect(screen.queryByText("The screen")).toBeNull();
  });

  test("sends whoever is signed in on from the sign-in screen, to one of our own screens only", async () => {
    mockApi({ "GET /auth/session": { json: ADMIN } });
    navigation.at("/login?next=https%3A%2F%2Fevil.example%2F");
    renderUi(gated(false));

    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/"));
    expect(screen.queryByText("The screen")).toBeNull();
  });

  test("shows the sign-in screen without the shell", async () => {
    mockApi({ "GET /auth/session": { json: NOBODY } });
    navigation.at("/login");
    renderUi(gated(false));

    expect(await screen.findByText("The screen")).toBeVisible();
    expect(screen.queryByRole("banner")).toBeNull();
  });

  test("says so when the session cannot be asked for, and tries again when asked", async () => {
    const user = userEvent.setup();
    let working = false;
    mockApi({
      "GET /auth/session": () =>
        working ? { json: ADMIN } : failure(503, "not_ready", "The database is not reachable."),
    });
    renderUi(gated(true));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The database is not reachable.");
    expect(alert).toHaveTextContent("Request req-123");
    working = true;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("The screen")).toBeVisible();
  });

  test("keeps the session's CSRF token for what comes after", async () => {
    const { calls } = mockApi({
      "GET /auth/session": { json: ADMIN },
      "POST /auth/logout": { status: 204 },
    });
    const user = userEvent.setup();
    renderUi(gated(true));

    await user.click(await screen.findByRole("button", { name: "Account of Ada Admin" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));

    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const signOut = calls.find((call) => call.method === "POST");
    expect(signOut?.headers["X-CSRF-Token"]).toBe("csrf-of-this-session");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 1 file fails: `Failed to resolve import "./theme-switch"`. The 277 earlier tests pass.

- [ ] **Step 3: Implement**

`frontend/src/components/theme-switch.tsx`:

```tsx
"use client";

import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { useTheme } from "@/components/theme-provider";
import {
  Menu,
  MenuContent,
  MenuLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuTrigger,
} from "@/components/ui/menu";
import { CHOICES, isChoice, type ThemeChoice } from "@/lib/theme";

const ICONS: Record<ThemeChoice, LucideIcon> = { light: Sun, dark: Moon, system: Monitor };

/** Light, dark, or as the system says (UI-10). */
export function ThemeSwitch() {
  const t = useTranslations("theme");
  const { choice, choose } = useTheme();
  const Current = ICONS[choice];
  return (
    <Menu>
      <MenuTrigger
        aria-label={t("current", { choice: t(choice) })}
        className="inline-flex size-10 items-center justify-center rounded-sm border border-transparent text-fg-muted hover:border-neon-cyan hover:text-ink-cyan"
      >
        <Current aria-hidden="true" className="size-5" />
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>{t("label")}</MenuLabel>
        <MenuRadioGroup
          value={choice}
          onValueChange={(value) => {
            if (isChoice(value)) choose(value);
          }}
        >
          {CHOICES.map((option) => {
            const Icon = ICONS[option];
            return (
              <MenuRadioItem key={option} value={option}>
                <Icon aria-hidden="true" className="size-4" />
                {t(option)}
              </MenuRadioItem>
            );
          })}
        </MenuRadioGroup>
      </MenuContent>
    </Menu>
  );
}
```

`frontend/src/components/user-menu.tsx`:

```tsx
"use client";

import { KeyRound, LogIn, LogOut, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { AppLink } from "@/components/ui/link";
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import type { SessionInfo } from "@/lib/api/types";
import { CHANGE_PASSWORD, SIGN_IN } from "@/lib/session/rules";
import { useSignOut } from "@/lib/session/session";

/** Who is signed in, and what they can do about it. For a visitor, the way to sign in. */
export function UserMenu({ session }: { session: SessionInfo }) {
  const t = useTranslations("account");
  const router = useRouter();
  const signOut = useSignOut();

  if (session.user === null) {
    return (
      <Button asChild variant="primary" size="sm">
        <AppLink href={SIGN_IN}>
          <LogIn aria-hidden="true" className="size-4" />
          {t("signIn")}
        </AppLink>
      </Button>
    );
  }

  const name = session.user.display_name || session.user.username;
  return (
    <Menu>
      <MenuTrigger
        aria-label={t("menu", { name })}
        className="inline-flex min-h-10 max-w-48 items-center gap-2 rounded-sm border border-line-strong px-3 text-sm text-fg hover:border-neon-cyan"
      >
        <UserRound aria-hidden="true" className="size-4 shrink-0 text-neon-magenta" />
        {/* On a narrow screen the icon stands for it: the button is still named. */}
        <span className="hidden truncate sm:inline">{name}</span>
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>{t("signedInAs")}</MenuLabel>
        <p className="px-3 pb-2 font-mono text-sm break-all text-fg">{session.user.username}</p>
        <MenuSeparator />
        {session.must_change_password ? null : (
          <MenuItem onSelect={() => router.push(CHANGE_PASSWORD)}>
            <KeyRound aria-hidden="true" className="size-4" />
            {t("changePassword")}
          </MenuItem>
        )}
        <MenuItem disabled={signOut.isPending} onSelect={() => signOut.mutate()}>
          <LogOut aria-hidden="true" className="size-4" />
          {t("signOut")}
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}
```

`frontend/src/components/app-shell.tsx`:

```tsx
"use client";

import { Menu as MenuIcon, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { ThemeSwitch } from "@/components/theme-switch";
import { AppLink } from "@/components/ui/link";
import { UserMenu } from "@/components/user-menu";
import type { SessionInfo } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { isCurrent, NAVIGATION, visible, type NavArea } from "@/lib/navigation";

const MAIN = "main";

/** The wordmark: the name, in the display face, with a neon bar before it. */
export function Wordmark() {
  const t = useTranslations("app");
  return (
    <span className="flex items-center gap-2 font-display text-lg font-bold tracking-[0.12em] text-fg uppercase sm:tracking-[0.2em]">
      <span aria-hidden="true" className="h-5 w-1.5 bg-neon-magenta shadow-glow-sm" />
      {t("name")}
    </span>
  );
}

function Navigation({ areas, onNavigate }: { areas: NavArea[]; onNavigate?: () => void }) {
  const t = useTranslations("nav");
  const pathname = usePathname();
  return (
    <ul className="flex flex-col gap-4 lg:flex-row lg:items-center lg:gap-6">
      {areas.map((area) => (
        <li key={area.key} className="flex flex-col gap-1 lg:flex-row lg:items-center lg:gap-2">
          <span className="label-caps text-fg-subtle">{t(`areas.${area.key}`)}</span>
          <ul className="flex flex-col gap-1 lg:flex-row">
            {area.items.map((item) => {
              const current = isCurrent(item, pathname);
              return (
                <li key={item.key}>
                  <AppLink
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={current ? "page" : undefined}
                    className={cn(
                      "label-caps flex min-h-10 items-center gap-2 rounded-sm border px-3",
                      current
                        ? "border-neon-cyan bg-raised text-ink-cyan"
                        : "border-transparent text-fg-muted hover:bg-raised hover:text-fg",
                    )}
                  >
                    <item.icon aria-hidden="true" className="size-4" />
                    {t(`items.${item.key}`)}
                  </AppLink>
                </li>
              );
            })}
          </ul>
        </li>
      ))}
    </ul>
  );
}

/**
 * What every screen is inside: the header with the navigation, and the content. With
 * `bare`, there is no navigation: for whoever must change their password first.
 */
export function AppShell({
  session,
  bare = false,
  children,
}: {
  session: SessionInfo;
  bare?: boolean;
  children: ReactNode;
}) {
  const t = useTranslations("app");
  const [open, setOpen] = useState(false);
  const areas = bare ? [] : visible(NAVIGATION, session);
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href={`#${MAIN}`}
        className="label-caps sr-only z-50 bg-panel px-4 py-3 text-ink-cyan focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        {t("skipToContent")}
      </a>
      <header className="border-b border-line-strong bg-panel">
        <div className="mx-auto flex min-h-16 max-w-7xl items-center gap-4 px-4 lg:gap-8">
          <AppLink href="/" className="shrink-0 rounded-sm">
            <Wordmark />
          </AppLink>
          {areas.length > 0 ? (
            <nav aria-label={t("mainNavigation")} className="hidden min-w-0 flex-1 lg:block">
              <Navigation areas={areas} />
            </nav>
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            <ThemeSwitch />
            <UserMenu session={session} />
            {areas.length > 0 ? (
              <button
                type="button"
                aria-expanded={open}
                aria-controls="narrow-navigation"
                aria-label={open ? t("closeNavigation") : t("openNavigation")}
                onClick={() => setOpen((was) => !was)}
                className="inline-flex size-10 items-center justify-center rounded-sm border border-line-strong text-fg lg:hidden"
              >
                {open ? (
                  <X aria-hidden="true" className="size-5" />
                ) : (
                  <MenuIcon aria-hidden="true" className="size-5" />
                )}
              </button>
            ) : null}
          </div>
        </div>
        {areas.length > 0 ? (
          <nav
            id="narrow-navigation"
            aria-label={t("mainNavigation")}
            hidden={!open}
            className="border-t border-line px-4 py-4 lg:hidden"
          >
            <Navigation areas={areas} onNavigate={() => setOpen(false)} />
          </nav>
        ) : null}
      </header>
      <main
        id={MAIN}
        tabIndex={-1}
        className="mx-auto w-full max-w-7xl min-w-0 flex-1 px-4 py-8 outline-none"
      >
        {children}
      </main>
    </div>
  );
}
```

`frontend/src/components/session-gate.tsx`:

```tsx
"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, type ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { decide } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

function Waiting() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <LoadingState />
    </div>
  );
}

function Gate({ shell, children }: { shell: boolean; children: ReactNode }) {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const query = search.toString();
  const path = query ? `${pathname}?${query}` : pathname;
  const decision = session.data ? decide(session.data, path, search.get("next")) : null;
  const goTo = decision !== null && !decision.show ? decision.goTo : null;

  useEffect(() => {
    // `goTo` is one of our own addresses: `decide` makes it from the rules.
    if (goTo !== null) router.replace(goTo as Route);
  }, [goTo, router]);

  if (session.isError) {
    return (
      <div className="mx-auto flex min-h-dvh max-w-xl items-center px-4">
        <ErrorState
          error={session.error}
          onRetry={() => void session.refetch()}
          className="w-full"
        />
      </div>
    );
  }
  if (!session.data || goTo !== null) return <Waiting />;
  if (!shell) return children;
  return (
    <AppShell session={session.data} bare={session.data.must_change_password}>
      {children}
    </AppShell>
  );
}

/**
 * Stands before every screen: asks who is signed in, and shows the screen, or goes to
 * the one this visitor should see instead (the design's section 7).
 */
export function SessionGate({ shell, children }: { shell: boolean; children: ReactNode }) {
  return (
    // The address's query is only known in the browser.
    <Suspense fallback={<Waiting />}>
      <Gate shell={shell}>{children}</Gate>
    </Suspense>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 298 passed in 10 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): the shell and the gate before every screen"
```

---

### Task 6: Signing in, changing a password, the home screen

**Files:**
- Create: `frontend/src/screens/sign-in.tsx`, `change-password.tsx`, `home.tsx`, `not-found.tsx`
- Create: `frontend/src/proxy.ts`
- Create: `frontend/src/app/layout.tsx`, `providers.tsx`, `not-found.tsx`, `error.tsx`, `global-error.tsx`, `icon.svg`
- Create: `frontend/src/app/(shell)/layout.tsx`, `(shell)/page.tsx`, `(shell)/account/password/page.tsx`
- Create: `frontend/src/app/login/page.tsx`, `frontend/src/app/healthz/route.ts`
- Test: `frontend/src/screens/screens.test.tsx`, `frontend/src/proxy.test.ts`

**Interfaces:**
- Consumes: everything of Tasks 1 to 5.
- Produces:
  - The routes `/` (home), `/login`, `/account/password`, `/healthz`, and the pages for an address with nothing at it and for a screen that threw.
  - `contentSecurityPolicy(nonce, development)`, `proxy(request)`, `config.matcher` in `src/proxy.ts`.
  - `Providers({ nonce, children })`: the messages, the data, the mode, and the nonce for Radix.

- [ ] **Step 1: Write the failing tests**

`frontend/src/screens/screens.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Answer } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, NOBODY, renderUi } from "@/test/render";

import { ChangePasswordScreen } from "./change-password";
import { HomeScreen } from "./home";
import { NotFoundScreen } from "./not-found";
import { SignInScreen } from "./sign-in";

async function fillIn(label: string, text: string) {
  await userEvent.type(screen.getByLabelText(label), text);
}

describe("signing in", () => {
  /** The API of a server where `password` is right for anyone, and the cookie is kept or not. */
  function server({ cookieKept = true }: { cookieKept?: boolean } = {}) {
    let signedIn = false;
    return mockApi({
      "POST /auth/login": (call) => {
        const body = call.body as { password: string };
        if (body.password !== "right") {
          return failure(401, "unauthorized", "The username or password is not correct.");
        }
        signedIn = cookieKept;
        return { json: ADMIN };
      },
      "GET /auth/session": () => ({ json: signedIn ? ADMIN : NOBODY }),
    });
  }

  test("is a form with labels, used by keyboard alone (UI-6)", async () => {
    const user = userEvent.setup();
    const { calls } = server();
    const { client } = renderUi(<SignInScreen />, { session: NOBODY });

    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    expect(screen.getByLabelText("User name")).toHaveFocus();
    await expectAccessible();

    await user.keyboard("ada{Tab}right{Enter}");

    await waitFor(() => expect(client.getQueryData(["session"])).toEqual(ADMIN));
    expect(calls[0]).toMatchObject({
      method: "POST",
      path: "/auth/login",
      body: { username: "ada", password: "right" },
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("cannot be sent with nothing in it", async () => {
    server();
    renderUi(<SignInScreen />, { session: NOBODY });

    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    await fillIn("User name", "ada");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    await fillIn("Password", "x");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  test("says that the name or the password is wrong, and not which", async () => {
    const user = userEvent.setup();
    server();
    const { client } = renderUi(<SignInScreen />, { session: NOBODY });

    await fillIn("User name", "ada");
    await fillIn("Password", "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The user name or the password is not correct.",
    );
    expect(client.getQueryData<SessionInfo>(["session"])?.authenticated).toBe(false);
    expect(screen.getByLabelText("Password")).toHaveValue("wrong"); // nothing typed is lost
    await expectAccessible();
  });

  test("says to wait after too many attempts", async () => {
    const user = userEvent.setup();
    mockApi({
      "POST /auth/login": failure(429, "too_many_attempts", "Too many attempts."),
      "GET /auth/session": { json: NOBODY },
    });
    renderUi(<SignInScreen />, { session: NOBODY });

    await fillIn("User name", "ada");
    await fillIn("Password", "right");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts. Wait a little");
  });

  test("says why when the browser did not keep the session", async () => {
    const user = userEvent.setup();
    server({ cookieKept: false });
    const { client } = renderUi(<SignInScreen />, { session: NOBODY });

    await fillIn("User name", "ada");
    await fillIn("Password", "right");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Your browser did not keep the session");
    expect(alert).toHaveTextContent("MEGOOARTI_SESSION_COOKIE_SECURE=false");
    expect(client.getQueryData<SessionInfo>(["session"])?.authenticated).toBe(false);
  });

  test("says so when the server cannot be reached", async () => {
    const user = userEvent.setup();
    mockApi({ "POST /auth/login": "network-failure" });
    renderUi(<SignInScreen />, { session: NOBODY });

    await fillIn("User name", "ada");
    await fillIn("Password", "right");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The server could not be reached.");
  });
});

describe("changing a password", () => {
  const PENDING: SessionInfo = { ...ADMIN, must_change_password: true };

  function server(answer: Answer = { status: 204 }) {
    let changed = false;
    return mockApi({
      "PUT /me/password": () => {
        if (answer !== "network-failure" && (answer.status ?? 200) < 300) changed = true;
        return answer;
      },
      "GET /auth/session": () => ({ json: changed ? ADMIN : PENDING }),
    });
  }

  async function send(current: string, next: string, repeat = next) {
    await fillIn("Current password", current);
    await fillIn("New password", next);
    await fillIn("New password, again", repeat);
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
  }

  test("sends the two passwords, says it is done, and empties the form", async () => {
    const { calls } = server();
    renderUi(<ChangePasswordScreen />, { session: ADMIN });

    expect(screen.getByRole("heading", { level: 1, name: "Change password" })).toBeVisible();
    expect(screen.getByLabelText("New password")).toHaveAccessibleDescription(
      "At least 8 characters.",
    );
    await expectAccessible();
    await send("the old one", "a new password");

    expect(await screen.findByText("Your password is changed.")).toBeVisible();
    expect(calls[0]).toMatchObject({
      method: "PUT",
      path: "/me/password",
      body: { current_password: "the old one", new_password: "a new password" },
    });
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(navigation.router.replace).not.toHaveBeenCalled();
  });

  test("for whoever was made to: says why they are here, and goes on when it is done", async () => {
    server();
    const { client } = renderUi(<ChangePasswordScreen />, { session: PENDING });

    expect(screen.getByRole("heading", { level: 1, name: "Choose a new password" })).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("Your password was set for you.");
    await send("generated", "my own password");

    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/"));
    expect(client.getQueryData<SessionInfo>(["session"])?.must_change_password).toBe(false);
  });

  test.each([
    ["short", "short", "New password", "at least 8 characters"],
    ["the same one", "the same one", "New password", "must be different"],
    ["a new password", "a new passw0rd", "New password, again", "are not the same"],
  ])(
    "refuses %j before asking the server, at the field that is wrong",
    async (next, repeat, label, words) => {
      const { calls } = server();
      renderUi(<ChangePasswordScreen />, { session: ADMIN });

      await send("the same one", next, repeat);

      const field = screen.getByLabelText(label);
      expect(field).toHaveAttribute("aria-invalid", "true");
      expect(field).toHaveAccessibleDescription(expect.stringContaining(words));
      expect(calls).toHaveLength(0);
    },
  );

  test("puts what the server refuses at the field it is about", async () => {
    server(
      failure(422, "validation_error", "The request is not valid.", [
        { field: "body.current_password", message: "The current password is not correct." },
      ]),
    );
    renderUi(<ChangePasswordScreen />, { session: ADMIN });

    await send("not it", "a new password");

    await waitFor(() =>
      expect(screen.getByLabelText("Current password")).toHaveAccessibleDescription(
        "The current password is not correct.",
      ),
    );
    expect(screen.queryByText("Your password is changed.")).toBeNull();
  });

  test("puts a refusal of the new password at the new password", async () => {
    server(
      failure(422, "validation_error", "The request is not valid.", [
        { field: "password", message: "The password must not be the same as the username." },
      ]),
    );
    renderUi(<ChangePasswordScreen />, { session: ADMIN });

    await send("the old one", "adminadmin");

    await waitFor(() =>
      expect(screen.getByLabelText("New password")).toHaveAccessibleDescription(
        "The password must not be the same as the username.",
      ),
    );
  });

  test("says so when it failed for a reason that is no field's", async () => {
    server(failure(500, "internal_error", "Something failed."));
    renderUi(<ChangePasswordScreen />, { session: ADMIN });

    await send("the old one", "a new password");

    expect(await screen.findByRole("alert")).toHaveTextContent("The server met a fault.");
    expect(screen.getByLabelText("Current password")).toHaveValue("the old one");
  });
});

describe("the home screen", () => {
  const page = (...names: string[]) => ({
    items: names.map((name, index) => ({
      name,
      format: index % 2 ? "npm" : "maven",
      type: ["hosted", "proxy", "group"][index % 3],
      online: index !== 1,
      url: `https://repo.example.com/repository/${name}/`,
      members: null,
    })),
    total: names.length,
    limit: 200,
    offset: 0,
  });

  test("lists the repositories a caller may browse", async () => {
    const { calls } = mockApi({ "GET /content": { json: page("releases", "npmjs", "all") } });
    renderUi(<HomeScreen />, { session: ADMIN });

    await screen.findByText("releases");
    const table = screen.getByRole("table", { name: "Repositories" });
    const rows = within(table).getAllByRole("row").slice(1);

    expect(calls[0]?.path).toBe("/content?limit=200");
    expect(rows.map((row) => within(row).getAllByRole("cell")[0]?.textContent)).toEqual([
      "releases",
      "npmjs",
      "all",
    ]);
    expect(rows[0]).toHaveTextContent("Hosted");
    expect(rows[0]).toHaveTextContent("Online");
    expect(rows[1]).toHaveTextContent("Proxy");
    expect(rows[1]).toHaveTextContent("Offline");
    expect(rows[2]).toHaveTextContent("Group");
    expect(rows[0]).toHaveTextContent("https://repo.example.com/repository/releases/");
    expect(
      within(rows[0] as HTMLElement).getByRole("button", {
        name: "Copy https://repo.example.com/repository/releases/",
      }),
    ).toBeVisible();
    await expectAccessible();
  });

  test("says it is loading, in a shape of what is coming", async () => {
    mockApi({ "GET /content": { json: page("releases") } });
    renderUi(<HomeScreen />, { session: ADMIN });

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(screen.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();

    await screen.findByText("releases");
    expect(screen.queryByText("Loading")).toBeNull();
  });

  test("says so when there is none, and who makes them", async () => {
    mockApi({ "GET /content": { json: page() } });
    renderUi(<HomeScreen />, { session: ADMIN });

    expect(await screen.findByRole("heading", { name: "No repositories" })).toBeVisible();
    expect(screen.getByText(/An administrator creates repositories/)).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
    await expectAccessible();
  });

  test("says what went wrong, and tries again when asked", async () => {
    const user = userEvent.setup();
    let working = false;
    mockApi({
      "GET /content": () =>
        working
          ? { json: page("releases") }
          : failure(403, "forbidden", "You do not have permission to do this."),
    });
    renderUi(<HomeScreen />, { session: ADMIN });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You do not have permission to do this.");
    expect(alert).toHaveTextContent("Code forbidden");
    working = true;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("releases")).toBeVisible();
  });

  test("says when there are more than it shows", async () => {
    mockApi({ "GET /content": { json: { ...page("a", "b"), total: 250 } } });
    renderUi(<HomeScreen />, { session: ADMIN });

    expect(await screen.findByText("Showing 2 of 250.")).toBeVisible();
  });

  test("shows a name as text, whatever is in it", async () => {
    const hostile = '<img src=x onerror="alert(1)">';
    mockApi({ "GET /content": { json: page(hostile) } });
    const { container } = renderUi(<HomeScreen />, { session: ADMIN });

    expect(await screen.findByText(hostile)).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
  });

  test("shows a kind of repository it has no word for as the API named it", async () => {
    const odd = page("x");
    odd.items[0] = { ...odd.items[0]!, type: "mirror" };
    mockApi({ "GET /content": { json: odd } });
    renderUi(<HomeScreen />, { session: ADMIN });

    expect(await screen.findByText("mirror")).toBeVisible();
  });
});

describe("an address with nothing at it", () => {
  test("says so, and leads home", async () => {
    renderUi(<NotFoundScreen />);

    expect(screen.getByRole("heading", { name: "There is nothing at this address" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Go to the repositories" })).toHaveAttribute(
      "href",
      "/",
    );
    await expectAccessible();
  });
});
```

`frontend/src/proxy.test.ts`:

```ts
// @vitest-environment node
import { NextRequest } from "next/server";
import { describe, expect, test } from "vitest";

import { config, contentSecurityPolicy, proxy } from "./proxy";

const POLICY = "Content-Security-Policy";

function directives(policy: string): Record<string, string[]> {
  return Object.fromEntries(
    policy.split("; ").map((directive) => {
      const [name = "", ...values] = directive.split(" ");
      return [name, values];
    }),
  );
}

describe("the content security policy", () => {
  const policy = directives(contentSecurityPolicy("abc123", false));

  test("lets only a script with this request's nonce run", () => {
    expect(policy["script-src"]).toEqual(["'self'", "'nonce-abc123'", "'strict-dynamic'"]);
    expect(policy["script-src"]).not.toContain("'unsafe-inline'");
    expect(policy["script-src"]).not.toContain("'unsafe-eval'");
  });

  test("loads nothing from, sends nothing to and is framed by no other origin", () => {
    expect(policy["default-src"]).toEqual(["'self'"]);
    expect(policy["connect-src"]).toEqual(["'self'"]);
    expect(policy["font-src"]).toEqual(["'self'"]);
    expect(policy["img-src"]).toEqual(["'self'", "data:"]);
    expect(policy["frame-ancestors"]).toEqual(["'none'"]);
    expect(policy["object-src"]).toEqual(["'none'"]);
    expect(policy["base-uri"]).toEqual(["'self'"]);
    expect(policy["form-action"]).toEqual(["'self'"]);
    expect(contentSecurityPolicy("abc123", false)).not.toMatch(/https?:|\*/);
  });

  test("lets a style sheet in only with the nonce, and an attribute as it is", () => {
    expect(policy["style-src"]).toEqual(["'self'", "'nonce-abc123'"]);
    expect(policy["style-src-attr"]).toEqual(["'unsafe-inline'"]);
  });

  test("is looser in development only, where React needs it", () => {
    const development = directives(contentSecurityPolicy("abc123", true));

    expect(development["script-src"]).toContain("'unsafe-eval'");
    expect(development["style-src"]).toEqual(["'self'", "'unsafe-inline'"]);
  });
});

describe("a request for a page", () => {
  const request = () => new NextRequest("https://repo.example.com/login?next=%2F");

  test("is answered with the policy, and a nonce that is new each time", () => {
    const first = proxy(request()).headers.get(POLICY) ?? "";
    const second = proxy(request()).headers.get(POLICY) ?? "";
    const nonce = /'nonce-([A-Za-z0-9+/=]+)'/.exec(first)?.[1] ?? "";

    expect(nonce.length).toBeGreaterThanOrEqual(24);
    expect(first).toBe(contentSecurityPolicy(nonce, false));
    expect(second).not.toBe(first);
  });

  test("hands the nonce on to whatever renders the page", () => {
    const response = proxy(request());
    const nonce = /'nonce-([^']+)'/.exec(response.headers.get(POLICY) ?? "")?.[1];

    // Next.js carries the request headers a proxy sets in headers of this form.
    expect(response.headers.get("x-middleware-request-x-nonce")).toBe(nonce);
    expect(response.headers.get("x-middleware-request-content-security-policy")).toBe(
      response.headers.get(POLICY),
    );
  });
});

test("the policy is set for pages, and not for what a page loads", () => {
  const source = new RegExp(`^${config.matcher[0]?.source}$`);

  for (const page of ["/", "/login", "/account/password", "/browse/releases/com/acme"]) {
    expect(source.test(page)).toBe(true);
  }
  for (const file of ["/_next/static/chunks/app.js", "/_next/image", "/healthz", "/icon.svg"]) {
    expect(source.test(file)).toBe(false);
  }
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 2 files fail: `Failed to resolve import "./home"` and `Cannot find module './proxy'`. The 298 earlier tests pass.

- [ ] **Step 3: Implement**

`frontend/src/screens/sign-in.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Wordmark } from "@/components/app-shell";
import { ThemeSwitch } from "@/components/theme-switch";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { Panel } from "@/components/ui/panel";
import { ErrorState } from "@/components/ui/states";
import { isApiError } from "@/lib/api/client";
import { useSignIn } from "@/lib/session/session";

/** Why signing in did not work, where the screen has its own words for it. */
function Refusal({ error }: { error: unknown }) {
  const t = useTranslations("signIn");
  if (isApiError(error)) {
    if (error.code === "cookie_not_kept") {
      return (
        <Alert tone="danger" title={t("cookieNotKeptTitle")}>
          {t("cookieNotKept")}
        </Alert>
      );
    }
    if (error.status === 401) return <Alert tone="danger">{t("wrong")}</Alert>;
    if (error.status === 429) return <Alert tone="warning">{t("tooManyAttempts")}</Alert>;
  }
  return <ErrorState error={error} />;
}

/**
 * Name and password. Once they are accepted the session says who is signed in, and
 * the gate this screen is behind goes on to the screen that was asked for.
 */
export function SignInScreen() {
  const t = useTranslations("signIn");
  const signIn = useSignIn();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    signIn.mutate({ username, password });
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <div className="flex justify-end p-4">
        <ThemeSwitch />
      </div>
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-6 px-4 pb-24">
        <Wordmark />
        <Panel className="p-6 shadow-glow-sm">
          <h1 className="mb-6 text-xl font-semibold text-fg uppercase">{t("title")}</h1>
          <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
            <TextField
              label={t("username")}
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              autoFocus
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
            <TextField
              label={t("password")}
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            {signIn.isError ? <Refusal error={signIn.error} /> : null}
            <Button
              type="submit"
              variant="primary"
              busy={signIn.isPending}
              disabled={username === "" || password === ""}
            >
              {t("submit")}
            </Button>
          </form>
        </Panel>
      </main>
    </div>
  );
}
```

`frontend/src/screens/change-password.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState } from "@/components/ui/states";
import { isApiError } from "@/lib/api/client";
import { HOME } from "@/lib/session/rules";
import { useChangePassword, useSession } from "@/lib/session/session";

// The server's rule, said before the request is made. The server still decides.
const MIN_LENGTH = 8;

type Problems = { current?: string; next?: string; repeat?: string };

/** Which field a refusal by the server is about, by the names it uses for them. */
function fromServer(error: unknown): Problems | null {
  if (!isApiError(error) || error.code !== "validation_error") return null;
  const problems: Problems = {};
  for (const detail of error.details) {
    if (detail.field?.endsWith("current_password")) problems.current = detail.message;
    else problems.next = detail.message;
  }
  return problems.current || problems.next ? problems : null;
}

/**
 * Changing one's own password. It is also the only screen of a user whose password was
 * set for them, until they have chosen their own.
 */
export function ChangePasswordScreen() {
  const t = useTranslations("password");
  const session = useSession();
  const change = useChangePassword();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [problems, setProblems] = useState<Problems>({});
  // Asked once, when the screen opens: after the change it is no longer true, and the
  // gate has by then gone on to another screen.
  const [forced] = useState(session.data?.must_change_password ?? false);

  function check(): Problems {
    if (next.length < MIN_LENGTH) return { next: t("tooShort", { min: MIN_LENGTH }) };
    if (next === current) return { next: t("notDifferent") };
    if (next !== repeat) return { repeat: t("notTheSame") };
    return {};
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const found = check();
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent("");
          setNext("");
          setRepeat("");
          // Whoever was made to come here goes on to where they were going.
          if (forced) router.replace(HOME);
        },
        onError: (error) => setProblems(fromServer(error) ?? {}),
      },
    );
  }

  const unexplained = change.isError && fromServer(change.error) === null;
  return (
    <div className="mx-auto max-w-lg">
      <PageHeader title={forced ? t("mustChangeTitle") : t("title")} />
      {forced ? (
        <Alert tone="warning" className="mb-6">
          {t("mustChange")}
        </Alert>
      ) : null}
      <Panel className="p-6">
        <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
          <TextField
            label={t("current")}
            name="current-password"
            type="password"
            autoComplete="current-password"
            required
            value={current}
            error={problems.current}
            onChange={(event) => setCurrent(event.target.value)}
          />
          <TextField
            label={t("new")}
            name="new-password"
            type="password"
            autoComplete="new-password"
            required
            value={next}
            hint={t("newHint", { min: MIN_LENGTH })}
            error={problems.next}
            onChange={(event) => setNext(event.target.value)}
          />
          <TextField
            label={t("repeat")}
            name="repeat-password"
            type="password"
            autoComplete="new-password"
            required
            value={repeat}
            error={problems.repeat}
            onChange={(event) => setRepeat(event.target.value)}
          />
          {unexplained ? <ErrorState error={change.error} /> : null}
          {change.isSuccess ? <Alert tone="success">{t("changed")}</Alert> : null}
          <Button
            type="submit"
            variant="primary"
            busy={change.isPending}
            disabled={current === "" || next === "" || repeat === ""}
          >
            {t("submit")}
          </Button>
        </form>
      </Panel>
    </div>
  );
}
```

`frontend/src/screens/home.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { StatusTag } from "@/components/ui/alert";
import { CopyButton } from "@/components/ui/copy-button";
import { PageHeader, Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { Page, RepositoryView } from "@/lib/api/types";

// As many as one request may ask for. An installation has tens of repositories.
const AT_ONCE = 200;

const TYPES = ["hosted", "proxy", "group"] as const;
type KnownType = (typeof TYPES)[number];

function isKnownType(type: string): type is KnownType {
  return (TYPES as readonly string[]).includes(type);
}

function Rows({ repositories }: { repositories: RepositoryView[] }) {
  const t = useTranslations("home");
  return (
    <tbody>
      {repositories.map((repository) => (
        <tr key={repository.name} className="hover:bg-raised">
          <Td className="font-mono font-medium break-all">{repository.name}</Td>
          <Td>{repository.format}</Td>
          <Td>{isKnownType(repository.type) ? t(`types.${repository.type}`) : repository.type}</Td>
          <Td>
            {repository.online ? (
              <StatusTag tone="success">{t("online")}</StatusTag>
            ) : (
              <StatusTag tone="warning">{t("offline")}</StatusTag>
            )}
          </Td>
          <Td>
            <span className="flex items-center gap-1">
              <span className="font-mono text-xs break-all text-fg-muted">{repository.url}</span>
              <CopyButton text={repository.url} what={repository.url} />
            </span>
          </Td>
        </tr>
      ))}
    </tbody>
  );
}

function Loading() {
  return (
    <tbody aria-hidden="true">
      {[0, 1, 2].map((row) => (
        <tr key={row}>
          {[0, 1, 2, 3, 4].map((cell) => (
            <Td key={cell}>
              <Skeleton className={cell === 4 ? "w-56" : "w-20"} />
            </Td>
          ))}
        </tr>
      ))}
    </tbody>
  );
}

/** The repositories a caller may browse: where browsing starts. */
export function HomeScreen() {
  const t = useTranslations("home");
  const app = useTranslations("app");
  const repositories = useQuery({
    queryKey: ["content", "repositories"],
    queryFn: () => api.get<Page<RepositoryView>>("/content", { query: { limit: AT_ONCE } }),
  });
  const page = repositories.data;

  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")} />
      {repositories.isError ? (
        <ErrorState error={repositories.error} onRetry={() => void repositories.refetch()} />
      ) : page && page.items.length === 0 ? (
        <Panel>
          <EmptyState title={t("emptyTitle")}>{t("empty")}</EmptyState>
        </Panel>
      ) : (
        <Panel aria-busy={repositories.isPending || undefined}>
          {repositories.isPending ? (
            <p role="status" className="sr-only">
              {app("loading")}
            </p>
          ) : null}
          <Table caption={t("title")}>
            <thead>
              <tr>
                <Th>{t("columns.name")}</Th>
                <Th>{t("columns.format")}</Th>
                <Th>{t("columns.type")}</Th>
                <Th>{t("columns.status")}</Th>
                <Th>{t("columns.address")}</Th>
              </tr>
            </thead>
            {page ? <Rows repositories={page.items} /> : <Loading />}
          </Table>
          {page && page.total > page.items.length ? (
            <p className="px-4 py-3 text-sm text-fg-muted">
              {t("more", { shown: page.items.length, total: page.total })}
            </p>
          ) : null}
        </Panel>
      )}
    </>
  );
}
```

`frontend/src/screens/not-found.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { AppLink } from "@/components/ui/link";
import { EmptyState } from "@/components/ui/states";

export function NotFoundScreen() {
  const t = useTranslations("notFound");
  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <EmptyState
        title={t("title")}
        action={
          <Button asChild variant="primary">
            <AppLink href="/">{t("home")}</AppLink>
          </Button>
        }
      >
        {t("body")}
      </EmptyState>
    </main>
  );
}
```

`frontend/src/proxy.ts`:

```ts
import { NextResponse, type NextRequest } from "next/server";

/**
 * The content security policy, with a nonce that is new for each request.
 *
 * Only a script that carries the nonce runs. Next.js reads the policy from the request
 * and puts the nonce on its own scripts; the layout puts it on the one script the UI
 * writes itself, which sets the mode. A page is therefore rendered for its request:
 * one built ahead of time could carry no nonce.
 *
 * Nothing is loaded from, sent to or framed by another origin (UI-14).
 */
export function contentSecurityPolicy(nonce: string, development: boolean): string {
  return [
    "default-src 'self'",
    // React needs eval in development only, to rebuild a server error's stack.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' ${development ? "'unsafe-inline'" : `'nonce-${nonce}'`}`,
    // Radix positions a menu with a style attribute. An attribute cannot run a script.
    "style-src-attr 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const policy = contentSecurityPolicy(nonce, process.env.NODE_ENV === "development");

  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", policy);

  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      // Pages. Not the files a page loads, and not the health check.
      source: "/((?!_next/static|_next/image|healthz|favicon.ico|icon.svg).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
```

`frontend/src/app/providers.tsx`:

```tsx
"use client";

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setNonce } from "get-nonce";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";

import { ThemeProvider } from "@/components/theme-provider";
import { isApiError } from "@/lib/api/client";
import { SESSION_KEY, sessionMayHaveChanged } from "@/lib/session/session";

import messages from "../../messages/en.json";

function createClient(): QueryClient {
  // A refused request may mean the session has ended. The session is then asked for
  // again, and what is shown follows from its answer.
  const onError = (error: unknown) => {
    if (sessionMayHaveChanged(error)) void client.invalidateQueries({ queryKey: SESSION_KEY });
  };
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: {
        // What the server refuses, it refuses again. What did not arrive is tried once more.
        retry: (failures, error) => failures < 1 && !(isApiError(error) && error.status > 0),
        refetchOnWindowFocus: false,
      },
    },
  });
  return client;
}

let browserClient: QueryClient | undefined;

function getClient(): QueryClient {
  // On the server each request has its own. In the browser there is one for the page.
  if (typeof window === "undefined") return createClient();
  browserClient ??= createClient();
  return browserClient;
}

export function Providers({ nonce, children }: { nonce?: string; children: ReactNode }) {
  // Radix writes a style sheet of its own into the page when a menu or a dialog opens,
  // to stop the page behind it from scrolling. The policy lets it in only with this
  // request's nonce, which the library takes from here.
  if (nonce) setNonce(nonce);
  return (
    // Every text of the UI. The provider is given them here, in the browser's own
    // code: nothing on the server needs to know a locale. The time zone is named so
    // that the server and the browser would write a date the same way.
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      <QueryClientProvider client={getClient()}>
        <ThemeProvider>{children}</ThemeProvider>
      </QueryClientProvider>
    </NextIntlClientProvider>
  );
}
```

`frontend/src/app/layout.tsx`:

```tsx
import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";

import { inter, jetbrainsMono, oxanium } from "@/lib/fonts";
import { THEME_SCRIPT } from "@/lib/theme";
import "@/styles/globals.css";

import messages from "../../messages/en.json";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: messages.app.name,
  description: messages.app.tagline,
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Set for this request by src/proxy.ts. Reading it is also what makes every page be
  // rendered for its request, which a nonce needs.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html
      lang="en"
      // What the script below corrects before anything is painted.
      data-theme="dark"
      suppressHydrationWarning
      className={`${oxanium.variable} ${inter.variable} ${jetbrainsMono.variable} antialiased`}
    >
      <head>
        <script
          nonce={nonce}
          suppressHydrationWarning
          dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }}
        />
      </head>
      <body>
        <Providers nonce={nonce}>{children}</Providers>
      </body>
    </html>
  );
}
```

`frontend/src/app/(shell)/layout.tsx`:

```tsx
import type { ReactNode } from "react";

import { SessionGate } from "@/components/session-gate";

export default function ShellLayout({ children }: { children: ReactNode }) {
  return <SessionGate shell>{children}</SessionGate>;
}
```

`frontend/src/app/(shell)/page.tsx`:

```tsx
import { HomeScreen } from "@/screens/home";

export default function HomePage() {
  return <HomeScreen />;
}
```

`frontend/src/app/(shell)/account/password/page.tsx`:

```tsx
import { ChangePasswordScreen } from "@/screens/change-password";

export default function ChangePasswordPage() {
  return <ChangePasswordScreen />;
}
```

`frontend/src/app/login/page.tsx`:

```tsx
import { SessionGate } from "@/components/session-gate";
import { SignInScreen } from "@/screens/sign-in";

export default function SignInPage() {
  return (
    <SessionGate shell={false}>
      <SignInScreen />
    </SessionGate>
  );
}
```

`frontend/src/app/not-found.tsx`:

```tsx
import { NotFoundScreen } from "@/screens/not-found";

export default function NotFound() {
  return <NotFoundScreen />;
}
```

`frontend/src/app/error.tsx`:

```tsx
"use client";

import { RotateCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

/** A screen threw while it was being drawn. The rest of the UI is still there. */
export default function ScreenError({ reset }: { error: Error; reset: () => void }) {
  const t = useTranslations("crash");
  return (
    <div className="mx-auto flex min-h-dvh max-w-xl items-center px-4">
      <Alert tone="danger" title={t("title")} className="w-full">
        <p>{t("body")}</p>
        <Button size="sm" className="mt-3" onClick={reset}>
          <RotateCw aria-hidden="true" className="size-4" />
          {t("reload")}
        </Button>
      </Alert>
    </div>
  );
}
```

`frontend/src/app/global-error.tsx`:

```tsx
"use client";

import "@/styles/globals.css";

import messages from "../../messages/en.json";

/**
 * The layout itself threw, so nothing it provides is there: not the translations, not
 * the fonts, not the mode. This page stands entirely on its own.
 */
export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  const t = messages.crash;
  return (
    <html lang="en" data-theme="dark">
      <body>
        <main className="mx-auto flex min-h-dvh max-w-xl flex-col items-start justify-center gap-3 px-4">
          <h1 className="text-xl font-semibold text-fg uppercase">{t.title}</h1>
          <p className="text-fg-muted">{t.body}</p>
          <button
            type="button"
            onClick={reset}
            className="bevel label-caps min-h-10 border border-line-strong bg-panel px-4 text-fg"
          >
            {t.reload}
          </button>
        </main>
      </body>
    </html>
  );
}
```

`frontend/src/app/healthz/route.ts`:

```ts
// For the container's health check: the server is up and answering.
export function GET() {
  return new Response("ok\n", {
    headers: { "Content-Type": "text/plain", "Cache-Control": "no-store" },
  });
}
```

`frontend/src/app/icon.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <path d="M6 2h20l4 4v20l-4 4H6l-4-4V6z" fill="#07080d" stroke="#00e5ff" stroke-width="2"/>
  <path d="M9 23V9l7 8 7-8v14" fill="none" stroke="#ff2bd6" stroke-width="3" stroke-linejoin="bevel"/>
</svg>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 327 passed in 12 files.

- [ ] **Step 5: Lint, check the types and build**

Run: `pnpm lint && pnpm typecheck && pnpm build`
Expected: no finding, and a build whose routes are `/`, `/_not-found`, `/account/password`, `/healthz` and `/login`, each marked `ƒ` (rendered on demand), with `ƒ Proxy`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): signing in, changing a password, the home screen"
```

---

### Task 7: The frontend image, the gateway and Compose

**Files:**
- Create: `frontend/Dockerfile`, `frontend/.dockerignore`
- Create: `gateway/nginx.conf`
- Modify: `docker-compose.yml`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_compose.py`

**Interfaces:**
- Consumes: the built frontend (Task 6); the backend's Compose service and the `stack` fixture of the `docker` tests.
- Produces:
  - The Compose services `frontend` and `gateway`. `MEGOOARTI_HTTP_PORT` is now the gateway's port; the backend is not published.
  - The routes of the gateway: `/api/`, `/repository/`, `/v2/` to the backend, everything else to the frontend.
  - The `stack` fixture builds both images.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_compose.py`, replace

```python
from pathlib import Path

import yaml
```

with

```python
import re
from pathlib import Path

import pytest
import yaml
```

and add to its end:

```python
GATEWAY = (COMPOSE_FILE.parent / "gateway" / "nginx.conf").read_text(encoding="utf-8")


def test_only_the_gateway_is_published_to_the_network():
    published = {
        name: service["ports"] for name, service in services().items() if "ports" in service
    }

    assert set(published) == {"db", "gateway"}
    assert published["gateway"] == ["${MEGOOARTI_HTTP_PORT:-8000}:80"]


def test_the_gateway_waits_for_what_it_stands_in_front_of():
    waited_for = services()["gateway"]["depends_on"]

    assert waited_for == {
        "backend": {"condition": "service_healthy"},
        "frontend": {"condition": "service_healthy"},
    }


def test_the_frontend_is_given_no_secret_and_no_way_to_the_data():
    frontend = services()["frontend"]

    # It renders the shell. The browser, not this container, calls the backend.
    assert set(frontend) == {"build", "healthcheck"}


def test_the_backend_takes_the_gateways_word_for_who_is_calling():
    environment = services()["backend"]["environment"]

    assert environment["MEGOOARTI_FORWARDED_ALLOW_IPS"] == "*"
    assert "ports" not in services()["backend"]  # which is why it can


def test_the_gateway_sends_the_api_the_repositories_and_the_registry_to_the_backend():
    routes = dict(re.findall(r"location (\S+) \{\s*proxy_pass (\$\w+);\s*\}", GATEWAY))

    assert routes == {
        "/api/": "$backend",
        "/repository/": "$backend",
        "/v2/": "$backend",
        "/": "$frontend",
    }


def test_the_gateway_passes_a_path_on_exactly_as_it_was_sent():
    # With anything after the upstream's address nginx decodes the path and writes it
    # again: an npm scope's encoded slash would become a real one.
    assert re.findall(r"proxy_pass ([^;]+);", GATEWAY) == ["$backend"] * 3 + ["$frontend"]
    assert "rewrite" not in GATEWAY


@pytest.mark.parametrize(
    "directive",
    [
        "client_max_body_size 0;",
        "proxy_request_buffering off;",
        "proxy_buffering off;",
        "proxy_http_version 1.1;",
        "proxy_set_header Host $http_host;",
        "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "proxy_set_header X-Forwarded-Proto $scheme;",
        "proxy_read_timeout 600s;",
    ],
)
def test_the_gateway_does_what_artifacts_and_package_clients_need(directive):
    assert directive in GATEWAY
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/test_compose.py -q`
Expected: collection error, `FileNotFoundError: ... gateway/nginx.conf`.

- [ ] **Step 3: Implement**

`frontend/Dockerfile`:

```dockerfile
FROM node:22-slim AS build

ENV NEXT_TELEMETRY_DISABLED=1 \
    CI=1

WORKDIR /app

# pnpm, in the version package.json names.
RUN corepack enable

# Dependencies first, so this layer is reused until the lock file changes.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build


FROM node:22-slim

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

# The server and only what it needs to run: no package manager, no sources.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

# The image's own unprivileged user.
USER node
EXPOSE 3000

CMD ["node", "server.js"]
```

`frontend/.dockerignore`:

```text
node_modules
.next
out
coverage
test-results
playwright-report
e2e
.env*
*.tsbuildinfo
Dockerfile
.dockerignore
```

`gateway/nginx.conf`:

```nginx
# The one address of a MegooArti installation, for development and testing.
#
# The API, the repositories and the registry go to the backend. Everything else is the
# web UI. In production your own reverse proxy does this, and terminates TLS: these are
# the rules to copy. The README says what each is for.

# Docker's own DNS, asked again as containers come and go.
resolver 127.0.0.11 valid=10s;

server {
    listen 80;

    # The names are variables so that nginx asks for the address at each request, and a
    # container that was started again is found.
    set $backend http://backend:8000;
    set $frontend http://frontend:3000;

    proxy_http_version 1.1;
    proxy_set_header Connection "";

    # The backend writes addresses from these: the host and port the client used, the
    # client's own address, and whether it came by HTTPS.
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # An artifact has no size limit here, and goes to the backend as it arrives: it is
    # not written to a file of nginx's first.
    client_max_body_size 0;
    proxy_request_buffering off;

    # An answer goes to the client as the backend produces it.
    proxy_buffering off;

    # A proxy repository may wait this long for its remote.
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;

    # No address is rewritten: `proxy_pass` has no path, so the request's own path goes
    # on exactly as it was sent. An npm scope is an encoded slash and must stay one.
    location /api/ {
        proxy_pass $backend;
    }

    location /repository/ {
        proxy_pass $backend;
    }

    location /v2/ {
        proxy_pass $backend;
    }

    location / {
        proxy_pass $frontend;
    }
}
```

`docker-compose.yml`:

```yaml
name: megooarti

services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: megooarti
      POSTGRES_PASSWORD: megooarti
      POSTGRES_DB: megooarti
    ports:
      # Loopback only: the database is published for development tools, not for the network.
      - "127.0.0.1:${MEGOOARTI_DB_PORT:-5432}:5432"
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U megooarti -d megooarti"]
      interval: 2s
      timeout: 3s
      retries: 30

  # The API, the repositories and the registry. It is reached through the gateway only.
  backend:
    build: ./backend
    environment:
      MEGOOARTI_DATABASE_URL: postgresql://megooarti:megooarti@db:5432/megooarti
      # Only the gateway can reach this container, so what it says of the client is taken.
      MEGOOARTI_FORWARDED_ALLOW_IPS: "*"
      MEGOOARTI_SESSION_COOKIE_SECURE: ${MEGOOARTI_SESSION_COOKIE_SECURE:-true}
    depends_on:
      db:
        condition: service_healthy
    # Must stay longer than MEGOOARTI_SHUTDOWN_GRACE_SECONDS (default 30), or Docker
    # kills the container while requests are still finishing.
    stop_grace_period: 40s
    volumes:
      - backend-data:/var/lib/megooarti
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/status/ready', timeout=3)"
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 20s

  # The web UI. It holds no data and no secret, and never calls the backend: the
  # browser does.
  frontend:
    build: ./frontend
    healthcheck:
      test:
        - CMD
        - node
        - -e
        - "fetch('http://127.0.0.1:3000/healthz').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 10s

  # The one published address. For development and testing: in production your own
  # reverse proxy takes its place, with the rules of gateway/nginx.conf.
  gateway:
    image: nginx:stable-alpine
    depends_on:
      backend:
        condition: service_healthy
      frontend:
        condition: service_healthy
    ports:
      - "${MEGOOARTI_HTTP_PORT:-8000}:80"
    volumes:
      - ./gateway/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--output-document=/dev/null", "http://127.0.0.1/healthz"]
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 5s

volumes:
  db-data:
  backend-data:
```

In `backend/tests/conftest.py`, in the `stack` fixture, replace

```python
    compose("build", "backend")
```

with

```python
    compose("build")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/test_compose.py -q`
Expected: 16 passed.

- [ ] **Step 5: Run every real-client test through the gateway**

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: 24 passed. Maven, npm, pip and Docker now reach the backend through nginx: a failure here is a fault of `gateway/nginx.conf`. It takes about ten minutes; the first run also builds the frontend image.

- [ ] **Step 6: Commit**

```bash
git add frontend/Dockerfile frontend/.dockerignore gateway docker-compose.yml backend/tests
git commit -m "feat: the frontend image, the gateway and Compose"
```

---

### Task 8: The UI in a real browser

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/ui.spec.ts`
- Create: `backend/tests/test_ui_client.py`

**Interfaces:**
- Consumes: the stack of Task 7; every screen of Task 6.
- Produces: `pnpm e2e`, and three `docker`-marked tests: the gateway's routes, the frontend container, and the browser tests.

These tests add no code. They are where contrast, focus and the content security policy are real: the unit tests draw nothing. While this plan was built they found four faults the unit tests could not: a page wider than a narrow screen, a style sheet of Radix that the policy refused, a dialog that did not give focus back, and a sign-out that returned the next visitor to the last one's screen. All four are fixed in the code of the tasks above.

- [ ] **Step 1: Install the browser**

Run: `pnpm exec playwright install chromium`
Expected: Chromium is downloaded, once for this machine.

- [ ] **Step 2: Write the tests**

`frontend/playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

/**
 * Tests in a real browser, against a running installation reached through its gateway.
 *
 * They are run by the backend's `docker` suite (backend/tests/test_ui_client.py), which
 * starts a fresh stack and passes its address and the generated administrator password.
 * To run them by hand against a stack of your own:
 *
 *   MEGOOARTI_UI_URL=http://localhost:8000 MEGOOARTI_INITIAL_PASSWORD=... pnpm e2e
 */
export default defineConfig({
  testDir: "./e2e",
  // One installation and one administrator: the flows follow each other.
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  reporter: [["list"]],
  timeout: 60_000,
  use: {
    // `localhost`, not an IP address: a browser keeps a Secure cookie over plain HTTP
    // only there.
    baseURL: process.env.MEGOOARTI_UI_URL ?? "http://localhost:8000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
```

`frontend/e2e/ui.spec.ts`:

```ts
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

/**
 * The UI as a person meets it, from the first sign-in of a fresh installation on.
 * The tests follow each other: each starts where the one before it ended.
 */

const INITIAL_PASSWORD = process.env.MEGOOARTI_INITIAL_PASSWORD ?? "";
const PASSWORD = "chosen-in-the-browser-test";
const REPOSITORY = "browser-test-files";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;
// Everything the browser asked for, and everything it complained about, in every test.
const requested: string[] = [];
const complaints: string[] = [];

test.beforeAll(async ({ browser, baseURL }) => {
  expect(INITIAL_PASSWORD, "MEGOOARTI_INITIAL_PASSWORD is not set").not.toBe("");
  context = await browser.newContext({ baseURL, colorScheme: "dark" });
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  context.on("request", (request) => requested.push(request.url()));
  page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") complaints.push(message.text());
  });
  page.on("pageerror", (error) => complaints.push(String(error)));
});

test.afterAll(async () => {
  await context.close();
});

const shownMode = () => page.evaluate(() => document.documentElement.dataset.theme);

/** No rule of WCAG 2.1 A or AA is broken on the page as it is now: contrast included. */
async function expectAccessible() {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const found = results.violations.map(
    (violation) => `${violation.id}: ${violation.nodes.map((node) => node.html).join(" | ")}`,
  );
  expect(found).toEqual([]);
}

/** The same check in each mode, leaving the page in the dark one. */
async function expectAccessibleInBothModes() {
  for (const mode of ["light", "dark"] as const) {
    await page.evaluate((chosen) => localStorage.setItem("megooarti-theme", chosen), mode);
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await shownMode()).toBe(mode);
    await expectAccessible();
  }
}

async function signIn(password: string) {
  await page.getByLabel("User name").fill("admin");
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("a visitor who is not signed in is asked to sign in", async () => {
  const response = await page.goto("/");

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
  await expect(page.getByLabel("User name")).toBeFocused();

  const policy = response?.headers()["content-security-policy"] ?? "";
  expect(policy).toContain("default-src 'self'");
  expect(policy).toMatch(/script-src 'self' 'nonce-[^']+' 'strict-dynamic'/);
  expect(policy).not.toContain("unsafe-eval");
  expect(response?.headers()["x-frame-options"]).toBe("DENY");
  expect(response?.headers()["x-content-type-options"]).toBe("nosniff");
});

test("the mode is set by the page's head, before any of the UI's code has run", async ({
  browser,
  baseURL,
}) => {
  for (const system of ["light", "dark"] as const) {
    const bare = await browser.newContext({ baseURL, colorScheme: system });
    const fresh = await bare.newPage();
    // With every script file refused, only what is written into the page can run.
    await fresh.route("**/*.js", (route) => route.abort());
    await fresh.goto("/login", { waitUntil: "domcontentloaded" });

    expect(await fresh.evaluate(() => document.documentElement.dataset.theme)).toBe(system);
    await bare.close();
  }
});

test("the sign-in screen meets WCAG 2.1 AA in both modes", async () => {
  await expectAccessibleInBothModes();
});

test("a wrong password is refused, and nothing typed is lost", async () => {
  await signIn("not-the-password");

  // Within the form: Next.js has an alert of its own, to announce a change of page.
  await expect(page.locator("form").getByRole("alert")).toContainText(
    "The user name or the password is not correct.",
  );
  await expect(page.getByLabel("User name")).toHaveValue("admin");
});

test("the first sign-in is done by keyboard alone, and leads to choosing a password", async () => {
  await page.reload();
  await expect(page.getByLabel("User name")).toBeFocused();
  await page.keyboard.type("admin");
  await page.keyboard.press("Tab");
  await page.keyboard.type(INITIAL_PASSWORD);
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/account\/password$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Choose a new password" }),
  ).toBeVisible();
  // Nothing else can be reached until it is done.
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await page.goto("/");
  await expect(page).toHaveURL(/\/account\/password$/);
});

test("the change-password screen meets WCAG 2.1 AA in both modes", async () => {
  await expectAccessibleInBothModes();
});

test("a password that is too short is refused at its field, without asking the server", async () => {
  await page.getByLabel("Current password").fill(INITIAL_PASSWORD);
  await page.getByLabel("New password", { exact: true }).fill("short");
  await page.getByLabel("New password, again").fill("short");
  await page.getByRole("button", { name: "Change password" }).click();

  await expect(page.getByLabel("New password", { exact: true })).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(page.getByText("The password must be at least 8 characters long.")).toBeVisible();
});

test("choosing a password leads on to the repositories, of which there are none yet", async () => {
  await page.getByLabel("New password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("New password, again").fill(PASSWORD);
  await page.getByRole("button", { name: "Change password" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No repositories" })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Repositories" }),
  ).toHaveAttribute("aria-current", "page");
});

test("a repository made through the API is listed, and its address can be copied", async () => {
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const created = await page.request.post("/api/v1/repositories", {
    headers: { "X-CSRF-Token": session.csrf_token },
    data: { name: REPOSITORY, format: "raw", type: "hosted" },
  });
  expect(created.status()).toBe(201);

  await page.reload();
  const row = page.getByRole("row", { name: new RegExp(REPOSITORY) });

  await expect(row).toContainText("Hosted");
  await expect(row).toContainText("Online");
  const address = new URL(`/repository/${REPOSITORY}/`, page.url()).toString();
  await expect(row).toContainText(address);
  await row.getByRole("button", { name: `Copy ${address}` }).click();
  await expect(row.getByRole("status")).toHaveText("Copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(address);
});

test("the home screen meets WCAG 2.1 AA in both modes", async () => {
  await expectAccessibleInBothModes();
});

test("the mode that is chosen is shown at once, and kept after a reload", async () => {
  await page.getByRole("button", { name: /^Mode:/ }).click();
  await page.getByRole("menuitemradio", { name: "Light" }).click();

  expect(await shownMode()).toBe("light");
  await page.reload();
  await expect(page.getByRole("button", { name: "Mode: Light" })).toBeVisible();
  expect(await shownMode()).toBe("light"); // though the system is dark

  await page.getByRole("button", { name: "Mode: Light" }).click();
  await page.getByRole("menuitemradio", { name: "As the system" }).click();
  expect(await shownMode()).toBe("dark");
});

test("the skip link is the first stop of the keyboard, and leads past the navigation", async () => {
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
  await page.keyboard.press("Tab");

  const skip = page.getByRole("link", { name: "Skip to the content" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
});

test("on a narrow screen the navigation is behind a button, and nothing overflows", async () => {
  await page.setViewportSize({ width: 375, height: 700 });
  const open = page.getByRole("button", { name: "Open the navigation" });

  await expect(open).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  await open.click();
  await expect(
    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Repositories" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close the navigation" }).click();

  // The table scrolls inside its panel: the page itself is never wider than the screen.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 1280, height: 720 });
});

test("an address with nothing at it says so", async () => {
  const response = await page.goto("/no/such/screen");

  expect(response?.status()).toBe(404);
  await expect(
    page.getByRole("heading", { name: "There is nothing at this address" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Go to the repositories" }).click();
  await expect(page).toHaveURL(/\/$/);
});

test("signing out ends the session, and signing in again returns to where one was going", async () => {
  await page.getByRole("button", { name: /^Account of/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();

  await expect(page).toHaveURL(/\/login$/);
  expect((await (await page.request.get("/api/v1/auth/session")).json()).authenticated).toBe(false);

  await page.goto("/account/password");
  await expect(page).toHaveURL(/\/login\?next=%2Faccount%2Fpassword$/);
  await signIn(PASSWORD);

  await expect(page).toHaveURL(/\/account\/password$/);
  await expect(page.getByRole("heading", { level: 1, name: "Change password" })).toBeVisible();
});

test("the sign-in screen cannot be made to send its visitor to another site", async () => {
  await page.getByRole("button", { name: /^Account of/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto("/login?next=https%3A%2F%2Fevil.example%2F");
  await signIn(PASSWORD);

  await expect(page.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/");
});

test("through all of it, nothing was asked of another host, and the browser had no complaint", async ({
  baseURL,
}) => {
  const origin = new URL(baseURL ?? "").origin;
  const elsewhere = requested.filter(
    (address) => !address.startsWith(`${origin}/`) && !address.startsWith("data:"),
  );

  expect(requested.length).toBeGreaterThan(50);
  expect(elsewhere).toEqual([]);
  // The two complaints there should be: the browser itself logs the sign-in that was
  // refused (401) and the address that had nothing at it (404). Anything else, such as
  // something the content security policy stopped, fails this.
  const unexpected = complaints.filter((text) => !/status of 40[14]/.test(text));
  expect(unexpected).toEqual([]);
});
```

`backend/tests/test_ui_client.py`:

```python
"""The web UI in a real browser, and the gateway in front of it, against the built images.

Run with `pytest -m docker`. Besides a Docker daemon this needs Node.js and pnpm, the
frontend's dependencies and a browser for Playwright, once:

    cd frontend && pnpm install && pnpm exec playwright install chromium

The browser tests themselves are in `frontend/e2e/`. They begin with the first sign-in
of a fresh installation, so they need the stack this module starts and the password it
generated.
"""

import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request

import pytest

from tests.containers import DATA_FILE, HTTP_PORT, REPOSITORY_ROOT, compose

pytestmark = pytest.mark.docker

FRONTEND = REPOSITORY_ROOT / "frontend"


def get(path: str) -> tuple[int, str, str]:
    """A request to the published address: (status, content type, body)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{HTTP_PORT}{path}", timeout=30) as response:
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                response.read().decode(),
            )
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read().decode()


@pytest.mark.parametrize(
    ("path", "status", "kind", "said"),
    [
        ("/api/v1/status/ready", 200, "application/json", '"status":"ok"'),
        ("/api/docs", 200, "text/html", "swagger"),
        ("/repository/no-such-repository/file", 404, "application/json", "not_found"),
        ("/v2/", 401, "application/json", "UNAUTHORIZED"),
        ("/login", 200, "text/html", "<html"),
        ("/", 200, "text/html", "<html"),
        ("/healthz", 200, "text/plain", "ok"),
        ("/no/such/screen", 404, "text/html", "<html"),
    ],
    ids=["api", "api-docs", "repository", "registry", "sign-in", "home", "health", "nothing"],
)
def test_the_gateway_sends_each_kind_of_address_to_its_place(stack, path, status, kind, said):
    answered, content_type, body = get(path)

    assert (answered, content_type.partition(";")[0]) == (status, kind)
    assert said.lower() in body.lower()


def test_the_frontend_container_is_not_root_and_is_given_nothing_to_keep(stack):
    user = compose("exec", "-T", "frontend", "id", "-u").stdout.strip()
    environment = compose("exec", "-T", "frontend", "env").stdout

    assert user.isdigit() and user != "0"
    assert "MEGOOARTI_" not in environment
    assert "NEXT_TELEMETRY_DISABLED=1" in environment


def test_the_ui_in_a_real_browser(stack):
    pnpm = shutil.which("pnpm")
    assert pnpm, "pnpm is not installed: see the first lines of this file"
    password = compose("exec", "-T", "backend", "cat", DATA_FILE).stdout.strip()
    assert password
    environment = {
        **os.environ,
        # `localhost`: a browser keeps the session cookie, which is Secure, over plain
        # HTTP only there.
        "MEGOOARTI_UI_URL": f"http://localhost:{HTTP_PORT}",
        "MEGOOARTI_INITIAL_PASSWORD": password,
        "CI": "1",
    }

    result = subprocess.run(
        [pnpm, "exec", "playwright", "test"],
        cwd=FRONTEND,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )

    said = f"exit {result.returncode}\n{result.stdout[-6000:]}\n{result.stderr[-2000:]}"
    assert result.returncode == 0, said
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None and int(passed[1]) >= 17, said
    assert not re.search(r"\d+ (failed|skipped|did not run)", result.stdout), said
```

- [ ] **Step 3: Run them**

Run (in `backend/`): `uv run pytest -m docker tests/test_ui_client.py -q`
Expected: 10 passed. One of them runs the 17 browser tests.

- [ ] **Step 4: Lint**

Run: `pnpm lint && pnpm typecheck` and (in `backend/`) `uv run ruff check . && uv run ruff format --check .`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/playwright.config.ts frontend/e2e backend/tests/test_ui_client.py
git commit -m "test(frontend): the UI in a real browser"
```

---

### Task 9: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-12-frontend-design.md`

**Interfaces:**
- Consumes: the UI, the gateway and the tests as built.
- Produces: the README's sections on the web UI, on running behind a reverse proxy and on developing the UI, and a spec that says what was built.

- [ ] **Step 1: Document the UI and the gateway**

In `README.md`:

Replace

````markdown
This repository currently contains the backend foundation: a FastAPI service with
health endpoints, structured logging and automatic database migrations. Package
formats, security and the web UI arrive in later milestones.

## Quick start

Requires Docker with Compose.

```bash
docker compose up --build --detach --wait
curl http://localhost:8000/api/v1/status/ready
```

The second command prints `{"status":"ok","checks":{"database":"ok","schema":"ok"}}`.
Interactive API documentation is at <http://localhost:8000/api/docs>.
````

with

````markdown
It is two services and a database: a backend (FastAPI) that is the REST API, the
repositories and the Docker registry, and a web UI (Next.js) that uses that API.

## Quick start

Requires Docker with Compose.

```bash
docker compose up --build --detach --wait
curl http://localhost:8000/api/v1/status/ready
```

The second command prints `{"status":"ok","checks":{"database":"ok","schema":"ok"}}`.
The web UI is at <http://localhost:8000>, and interactive API documentation at
<http://localhost:8000/api/docs>. [First sign-in](#first-sign-in) says how to get in.

Compose starts four containers: the database, the backend, the frontend, and a
gateway (nginx) that is the one published address and sends each request to the
backend or the frontend. The gateway is for development and testing. In production,
put [your own reverse proxy](#behind-your-own-reverse-proxy) in its place.
````

Replace

```markdown
Docker Compose also reads `MEGOOARTI_HTTP_PORT` (default `8000`) and
`MEGOOARTI_DB_PORT` (default `5432`) to choose the ports published on the host. Set
`MEGOOARTI_DB_PORT` if another PostgreSQL already uses 5432. The database port is
published on `127.0.0.1` only.
```

with

```markdown
Docker Compose also reads `MEGOOARTI_HTTP_PORT` (default `8000`) and
`MEGOOARTI_DB_PORT` (default `5432`) to choose the ports published on the host. Set
`MEGOOARTI_DB_PORT` if another PostgreSQL already uses 5432. The database port is
published on `127.0.0.1` only. `MEGOOARTI_HTTP_PORT` is the gateway's: the backend and
the frontend are not published. Compose passes `MEGOOARTI_SESSION_COOKIE_SECURE` on to
the backend, and sets `MEGOOARTI_FORWARDED_ALLOW_IPS` to `*` there, because only the
gateway can reach it.

The frontend container has no configuration. It reads `PORT` (default `3000`) and
`HOSTNAME` (default `0.0.0.0`), and nothing else: it holds no secret and never calls
the backend.
```

Replace

````markdown
Sign in with it; you must then choose a new password, after which the file is deleted.

```bash
````

with

````markdown
Sign in with it, as `admin`, at <http://localhost:8000>. You must then choose a new
password, after which the file is deleted. The same with `curl`:

```bash
````

Before

```markdown
## Health endpoints
```

add

```markdown
## The web UI

The UI is at the root of the installation's address. For now it has the foundation
every screen will stand on, and three screens: signing in, changing your password,
and the repositories you may browse. Browsing, search, upload and administration
follow.

- **Signing in** uses the session cookie the API sets. It is marked `Secure`, so a
  browser keeps it over HTTPS, and over plain HTTP only at `localhost`. If you reach
  the UI over plain HTTP at another name or an IP address, signing in will say that
  the browser did not keep the session: use HTTPS, or set
  `MEGOOARTI_SESSION_COOKIE_SECURE=false`.
- **Anonymous access.** If it is on, a visitor who is not signed in sees what the
  anonymous user may browse, and a "Sign in" button. If it is off, the sign-in screen.
- **Light and dark.** The mode switch in the header chooses light, dark, or as the
  system says. The choice is kept in the browser.
- **Nothing is fetched from anywhere else.** Fonts, icons and scripts are served by
  MegooArti itself, so the UI works in a network with no way out. The UI sends a
  strict content security policy: only its own scripts run, and it cannot be framed.
- **Keyboard and screen readers.** Every screen can be used by keyboard alone, starts
  with a link that skips to its content, and meets WCAG 2.1 AA contrast in both modes.

## Behind your own reverse proxy

One address serves everything. Whatever stands in front must send each request to
the right service:

| Path | To | What it is |
| --- | --- | --- |
| `/api/` | backend, port 8000 | The REST API and its documentation |
| `/repository/` | backend, port 8000 | Maven, npm, PyPI and Raw repositories |
| `/v2/` | backend, port 8000 | The Docker registry |
| everything else | frontend, port 3000 | The web UI |

[gateway/nginx.conf](gateway/nginx.conf) is a complete example: it is what Compose
runs, and every real-client test of this project passes through it. Towards the
backend, your proxy must do what it does:

- **Pass the path on exactly as it was sent.** An npm scope arrives as an encoded
  slash (`@scope%2fname`) and must stay one. In nginx that means `proxy_pass` with no
  path after the address.
- **Put no limit on the size of a body** (`client_max_body_size 0`), and do not buffer
  it: an artifact can be gigabytes, and goes to the backend as it arrives
  (`proxy_request_buffering off`). Do not buffer answers either
  (`proxy_buffering off`).
- **Wait long enough.** A proxy repository may take minutes to fetch a large file
  from its remote before the first byte comes back (`proxy_read_timeout 600s`).
- **Send `Host`, `X-Forwarded-For` and `X-Forwarded-Proto`**, and set
  `MEGOOARTI_FORWARDED_ALLOW_IPS` on the backend to your proxy's address. The backend
  writes the addresses it gives to clients (tarball links, the registry's token
  address) from them, unless the base URL is set in the system settings.
- **Terminate TLS**, and add `Strict-Transport-Security` if you want it. The frontend
  leaves compression to you as well.

Do not publish the backend's or the frontend's own port beside it: the session cookie
and the content security policy assume one origin.
```

After

```markdown
| `GET /api/v1/status/ready` | The database is reachable and its schema matches this version; `503` otherwise |
```

add

```markdown
| `GET /healthz` | The frontend is running (it answers `ok`) |
```

After

```markdown
Tests create and use the databases `megooarti_test` and `megooarti_test_migrations`.
Set `MEGOOARTI_TEST_DATABASE_URL` to use a different server.
```

add

````markdown
### The web UI

Requires Node.js 22 and [pnpm](https://pnpm.io/).

```bash
cd frontend
pnpm install
pnpm test                     # unit and component tests
pnpm lint                     # ESLint and Prettier
pnpm typecheck
pnpm build
pnpm exec playwright install chromium   # once: the browser for the tests below
```

To work on a screen, start the stack (`docker compose up --build --detach --wait`),
which serves the built UI at <http://localhost:8000>. `pnpm dev` serves the UI alone
at port 3000, without an API beside it.

- **Tests in a real browser** are in `frontend/e2e/`. They are run by
  `uv run pytest -m docker` in `backend/`, which starts a fresh stack for them: they
  begin with the first sign-in of a new installation. They sign in, change the
  password, use every screen by keyboard, check each screen against WCAG 2.1 AA in
  both modes, and fail if the browser asked anything of another host or reported a
  violation of the content security policy.
- **A colour is written in one file**, `src/styles/tokens.css`, once for each mode. A
  test fails on a colour anywhere else, and another computes the contrast of every
  text tone on every surface.
- **Text is in `messages/en.json`.** ESLint refuses text written into markup.
- **The API's types are generated.** `frontend/openapi.json` is a copy of the
  backend's API document, and a backend test fails when it is out of date. After a
  change to the API:

  ```bash
  cd backend && MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest tests/test_openapi_snapshot.py
  cd ../frontend && pnpm gen:api
  ```

- **Next.js 16 is not the Next.js of earlier years.** Its documentation is in
  `frontend/node_modules/next/dist/docs/`; read the page for what you are about to
  change. `frontend/AGENTS.md` says the same to coding agents.
````

- [ ] **Step 2: Bring the spec in line with what was built**

In `docs/superpowers/specs/2026-10-12-frontend-design.md`:

Replace

```markdown
| `bg` | `#07080d` | `#f2f4f9` | The page |
| `panel` | `#0d1018` | `#ffffff` | Panels, the header |
| `raised` | `#151a26` | `#e8ecf5` | Hover, selected rows, menus |
| `field` | `#10141e` | `#ffffff` | Inputs |
| `line` | `#2a3348` | `#c3cbde` | Borders |
| `line-strong` | `#475474` | `#7f8baa` | Borders of inputs and of what can be pressed |
| `text` | `#e6ebf5` | `#10131c` | Text |
| `text-muted` | `#a3aec4` | `#465069` | Secondary text |
| `text-subtle` | `#8591ab` | `#5a6684` | Hints, placeholders |
```

with

```markdown
| `page` | `#07080d` | `#f2f4f9` | The page |
| `panel` | `#0d1018` | `#ffffff` | Panels, the header |
| `raised` | `#151a26` | `#e8ecf5` | Hover, selected rows, menus |
| `field` | `#10141e` | `#ffffff` | Inputs |
| `line` | `#2a3348` | `#c3cbde` | Borders that only divide |
| `line-strong` | `#5b6a8f` | `#6f7b99` | Borders of inputs and of what can be pressed |
| `fg` | `#e6ebf5` | `#10131c` | Text |
| `fg-muted` | `#a3aec4` | `#465069` | Secondary text |
| `fg-subtle` | `#8f9ab3` | `#566280` | Hints, placeholders |
```

Replace

```markdown
| Cyan (primary) | `#00e5ff` | `#5cefff` | `#00a3c4` | `#00647d` |
| Magenta | `#ff2bd6` | `#ff7ae5` | `#d400ab` | `#a30085` |
| Acid | `#c6ff00` | `#d4ff4d` | `#7ea800` | `#4a6400` |
```

with

```markdown
| Cyan (primary) | `#00e5ff` | `#5cefff` | `#0090ad` | `#00647d` |
| Magenta | `#ff2bd6` | `#ff7ae5` | `#d400ab` | `#a30085` |
| Acid | `#c6ff00` | `#d4ff4d` | `#6c9100` | `#4a6400` |
```

Replace

```markdown
The values above are the starting point. The contrast test (D6) is the authority: a pair that fails it is changed, here and in the code.
```

with

```markdown
The values above are those of `frontend/src/styles/tokens.css`, which is the authority, with the contrast test (D6): a pair that fails it is changed there, and here.
```

After

```markdown
A `401` from any later request means the session has ended: the session is asked for again, and the rules above apply. A `403` with the code `password_change_required` leads to the change-password screen.
```

add

```markdown
Signing out ends the session and then loads the home screen afresh, so that nothing the page held in memory for whoever was signed in is left, and the next visitor starts where any visitor does.
```

Before

```markdown
## 12. The screens of plan 10 (outline)
```

add

```markdown
## 11a. Settled while building plan 9

- **The framework's cached components are off** (`cacheComponents`), and every page is rendered for its request. Next.js 16 can only put a nonce into a page it renders for the request, and says itself that the two do not combine.
- **Radix writes a style sheet of its own** into the page when a menu or a dialog opens. It is let in by the same nonce, which the layout hands to it.
- **The translations are given to the browser's code**, not read on the server: nothing on the server needs a locale, and `next-intl` then needs no configuration of its own.
- **The fonts are loaded with `next/font/local`** from files in the repository. `next/font/google` would fetch them from Google when the UI is built.
- **Tailwind's own palette is removed**, so a class naming one of its colours does not exist. With the test that refuses a literal colour, a component can only use tokens.
- **A confirmation gives focus back to whatever opened it.** Radix does that for a trigger of its own; this dialog is opened by its screen.
- **A table scrolls inside its panel.** Text hidden from sight inside a cell is placed absolutely, and widened the page on a narrow screen until the table's own box contained it. The browser test for a 375-pixel screen found it.
- **The gateway is nginx**, with the routing rules in `gateway/nginx.conf`. `/v2` without its slash is not the registry: every client asks for `/v2/`.
- **The browser tests run at `localhost`**, because a browser keeps a `Secure` cookie over plain HTTP only there.
- **Not in plan 9:** a failed sign-out is not reported on the screen (it needs the notifications plan 10 brings), and the home screen shows the first 200 repositories and says how many there are.
```

- [ ] **Step 3: Run everything**

Run (in `frontend/`): `pnpm test && pnpm lint && pnpm typecheck`
Expected: 327 passed; no finding.

Run (in `backend/`): `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2756 passed, 1 skipped; no finding.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-12-frontend-design.md
git commit -m "docs: the web UI and running behind a reverse proxy"
```
