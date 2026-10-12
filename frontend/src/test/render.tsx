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
