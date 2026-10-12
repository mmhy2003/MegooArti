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
