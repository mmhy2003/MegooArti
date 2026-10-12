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
