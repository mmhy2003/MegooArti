/**
 * The one way the UI calls the API: same origin, with the session cookie, and with the
 * CSRF token on whatever changes something. An answer that is not a success becomes an
 * `ApiError`, whatever shape it came in.
 */

export const API_PREFIX = "/api/v1";
export const REQUEST_ID = "X-Request-ID";
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

/** The header that goes with a request that changes something, if there is a session. */
export function csrfHeader(): Record<string, string> {
  return csrfToken === null ? {} : { "X-CSRF-Token": csrfToken };
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

/** The error an answer that is not a success stands for, whatever its body is. */
export function errorOf(status: number, body: unknown, requestId: string | null): ApiError {
  const sent = isRecord(body) && isRecord(body.error) ? body.error : null;
  if (sent === null || typeof sent.code !== "string" || typeof sent.message !== "string") {
    return new ApiError(status, "unexpected_answer", "", [], requestId);
  }
  return new ApiError(status, sent.code, sent.message, details(sent.details), requestId);
}

async function failure(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON: a gateway's own page, or nothing at all.
  }
  return errorOf(response.status, body, response.headers.get(REQUEST_ID));
}

export type RequestOptions = { query?: Query; body?: unknown; signal?: AbortSignal };

export async function request<T>(
  method: Method,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (UNSAFE.has(method)) Object.assign(headers, csrfHeader());

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
