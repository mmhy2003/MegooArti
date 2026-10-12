"use client";

import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { setNonce } from "get-nonce";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";

import { ThemeProvider } from "@/components/theme-provider";
import { NotificationsProvider } from "@/components/ui/notifications";
import { createQueryClient } from "@/lib/query";

import messages from "../../messages/en.json";

let browserClient: QueryClient | undefined;

function getClient(): QueryClient {
  // On the server each request has its own. In the browser there is one for the page.
  if (typeof window === "undefined") return createQueryClient();
  browserClient ??= createQueryClient();
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
        <ThemeProvider>
          <NotificationsProvider>{children}</NotificationsProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </NextIntlClientProvider>
  );
}
