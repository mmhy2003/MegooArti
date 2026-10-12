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
