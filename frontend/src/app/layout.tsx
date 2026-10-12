import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";

import { inter, jetbrainsMono, oxanium } from "@/lib/fonts";
import { THEME_SCRIPT } from "@/lib/theme";
import "@/styles/globals.css";

import messages from "../../messages/en.json";
import { Providers } from "./providers";
import { TITLES } from "./titles";

export const metadata: Metadata = {
  title: TITLES,
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
