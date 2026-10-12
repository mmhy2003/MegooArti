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
    expect(policy["frame-src"]).toEqual(["'none'"]);
    expect(policy["object-src"]).toEqual(["'none'"]);
    expect(policy["base-uri"]).toEqual(["'none'"]);
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
