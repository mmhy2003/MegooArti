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
