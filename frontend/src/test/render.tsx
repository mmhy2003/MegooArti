import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement, ReactNode } from "react";

import { ThemeProvider } from "@/components/theme-provider";
import { NotificationsProvider } from "@/components/ui/notifications";
import type { SessionInfo } from "@/lib/api/types";
import { createQueryClient } from "@/lib/query";
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
  // The UI's own store, with its rule for a session that changed. Only a second try of
  // what did not arrive is left out: a test says what arrives.
  const client = createQueryClient({ retry: false });
  if (options.session) client.setQueryData(SESSION_KEY, options.session);
  const around = (screen: ReactNode) => (
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      <QueryClientProvider client={client}>
        <ThemeProvider>
          <NotificationsProvider>{screen}</NotificationsProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </NextIntlClientProvider>
  );
  const result = render(around(ui));
  // Rendering again keeps what is around the screen and what was fetched: it is how a
  // test moves the visitor to another address (`navigation.at`, then `rerender`).
  return { ...result, client, rerender: (next) => result.rerender(around(next)) };
}
