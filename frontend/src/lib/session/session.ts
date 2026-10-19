"use client";

/** The session: who is signed in, asked of the API, and the three things that change it. */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api, ApiError, setCsrfToken } from "@/lib/api/client";
import type { Page, SessionInfo, SignInSource } from "@/lib/api/types";
import { leaveTo } from "@/lib/browser";

import { HOME } from "./rules";

export const SESSION_KEY = ["session"] as const;

async function fetchSession(): Promise<SessionInfo> {
  const session = await api.get<SessionInfo>("/auth/session");
  setCsrfToken(session.csrf_token);
  return session;
}

function keep(client: QueryClient, session: SessionInfo): void {
  setCsrfToken(session.csrf_token);
  client.setQueryData(SESSION_KEY, session);
}

/** Everything that was fetched belongs to whoever was signed in. */
function forgetTheRest(client: QueryClient): void {
  client.removeQueries({ predicate: (query) => query.queryKey[0] !== SESSION_KEY[0] });
}

export function useSession() {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: fetchSession,
    // It changes when this page changes it, or when the server ends it, which a
    // refused request reports.
    staleTime: Infinity,
    retry: false,
  });
}

export type Credentials = { username: string; password: string };

/**
 * Signs in. The answer says who signed in; asking for the session afterwards says
 * whether the browser kept the cookie. If it did not, the error's code is
 * `cookie_not_kept`.
 */
/**
 * The sources the sign-in screen offers besides a password: signed in to at a provider.
 * Asked of a server that may have none, or be an older one: then there are none.
 */
export function useSignInSources() {
  return useQuery({
    queryKey: ["sign-in-sources"],
    queryFn: () => api.get<Page<SignInSource>>("/auth/sources", { query: { limit: 200 } }),
    retry: false,
  });
}

export function useSignIn() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (credentials: Credentials): Promise<SessionInfo> => {
      await api.post<SessionInfo>("/auth/login", credentials);
      const session = await fetchSession();
      if (!session.authenticated) throw new ApiError(0, "cookie_not_kept", "");
      return session;
    },
    onSuccess: (session) => {
      forgetTheRest(client);
      keep(client, session);
    },
  });
}

/**
 * Signs out, and loads the home screen afresh: nothing the page held for whoever was
 * signed in is left in memory, and the next visitor starts where any visitor does.
 */
export function useSignOut() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/auth/logout"),
    onSuccess: () => {
      forgetTheRest(client);
      setCsrfToken(null);
      leaveTo(HOME);
    },
  });
}

export type PasswordChange = { current_password: string; new_password: string };

export function useChangePassword() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (change: PasswordChange): Promise<SessionInfo> => {
      await api.put<void>("/me/password", change);
      return fetchSession();
    },
    onSuccess: (session) => keep(client, session),
  });
}

/**
 * For a request the server refused: `401` means the session has ended, a password
 * that must be changed means the session says so now, and a CSRF token that is wrong
 * means the session is another one than this page knows (signed out and in again in
 * another tab). In each case the session is asked for again: what is shown follows
 * from it, and its token is the one to send from then on.
 */
export function sessionMayHaveChanged(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return (
    error.status === 401 ||
    error.code === "password_change_required" ||
    error.code === "csrf_failed"
  );
}

/**
 * The rule itself: after such a refusal, the session is asked for again. The store
 * applies it to every query and mutation. A request made outside the store (an upload,
 * with its progress; a folder deleted piece by piece) applies it by calling this.
 */
export function askAgainIfChanged(client: QueryClient, error: unknown): void {
  if (sessionMayHaveChanged(error)) void client.invalidateQueries({ queryKey: SESSION_KEY });
}
