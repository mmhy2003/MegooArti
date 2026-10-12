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
