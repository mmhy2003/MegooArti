"use client";

/**
 * Who may do what, asked of the API: a person's own tokens, and what an administrator
 * keeps (users, roles, anonymous access). The requests of the account and security
 * screens.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  Asked,
  ConnectedApp,
  Consent,
  Page,
  PasswordReset,
  Redirect,
  RoleContent,
  RoleCreate,
  RoleOut,
  SettingsOut,
  SignInSettings,
  SourceIn,
  SourceOut,
  SourceTested,
  TokenCreate,
  TokenCreated,
  TokenInfo,
  UserCreate,
  UserOut,
  UserUpdate,
} from "@/lib/api/types";
import { SESSION_KEY } from "@/lib/session/session";

// As many of a list as one page shows (A13).
export const AT_ONCE = 50;
// As many roles as one request may ask for: the choices of a form.
const EVERY = 200;

const TOKENS = "tokens";
const APPS = "connected-apps";
const USERS = "users";
const ROLES = "roles";
const SETTINGS = "settings";
const SIGN_IN = "sign-in";
const SOURCES = "auth-sources";
/** Where the settings are kept among what was fetched: whoever changes one puts the answer there. */
export const SETTINGS_KEY = [SETTINGS] as const;

const paged = (page: number) => ({ limit: AT_ONCE, offset: (page - 1) * AT_ONCE });
const user = (id: string) => `/users/${encodeURIComponent(id)}`;
const role = (name: string) => `/roles/${encodeURIComponent(name)}`;

/**
 * After a user or a role changed, what the person who changed it may do can have
 * changed with it (their own roles, or a role they hold): the session is asked again.
 */
function afterSecurityChange(client: QueryClient): Promise<void> {
  void client.invalidateQueries({ queryKey: SESSION_KEY });
  void client.invalidateQueries({ queryKey: [ROLES] });
  return client.invalidateQueries({ queryKey: [USERS] });
}

// --- One's own tokens --------------------------------------------------------------------

export function useMyTokens(page: number) {
  return useQuery({
    queryKey: [TOKENS, "mine", page],
    queryFn: () => api.get<Page<TokenInfo>>("/me/tokens", { query: paged(page) }),
  });
}

/**
 * Creates a token. Its secret is in the answer and nowhere else: the answer is given
 * to whoever called, and is not kept among what was fetched.
 */
export function useCreateToken() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: TokenCreate) => api.post<TokenCreated>("/me/tokens", wanted),
    gcTime: 0,
    onSuccess: () => client.invalidateQueries({ queryKey: [TOKENS, "mine"] }),
  });
}

export function useRevokeToken() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/me/tokens/${encodeURIComponent(id)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: [TOKENS, "mine"] }),
  });
}

// --- Connected apps (OAuth) -------------------------------------------------------------------

export function useMyConnectedApps() {
  return useQuery({
    queryKey: [APPS, "mine"],
    queryFn: () => api.get<Page<ConnectedApp>>("/me/connected-apps", { query: { limit: EVERY } }),
  });
}

export function useRevokeConnectedApp() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/me/connected-apps/${encodeURIComponent(id)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: [APPS, "mine"] }),
  });
}

/** What an application asks of the person signed in: for its consent page. */
export function useConsentRequest(request: string) {
  return useQuery({
    queryKey: ["consent", request],
    queryFn: () => api.get<Asked>("/oauth/consent", { query: { request } }),
    enabled: request !== "",
    retry: false,
  });
}

export function useApprove() {
  return useMutation({
    mutationFn: (answer: Consent) => api.post<Redirect>("/oauth/consent", answer),
  });
}

export function useRefuse() {
  return useMutation({
    mutationFn: (request: string) => api.post<Redirect>("/oauth/refusal", { request }),
  });
}

// --- Users ----------------------------------------------------------------------------------

export function useUsers(page: number) {
  return useQuery({
    queryKey: [USERS, "list", page],
    queryFn: () => api.get<Page<UserOut>>("/users", { query: paged(page) }),
  });
}

export function useUser(id: string | null) {
  return useQuery({
    queryKey: [USERS, "one", id],
    queryFn: () => api.get<UserOut>(user(id ?? "")),
    enabled: id !== null,
  });
}

/**
 * The built-in user a request without credentials acts as, or null if it is not among
 * the users that one request brings.
 */
export function useAnonymousUser(enabled: boolean) {
  return useQuery({
    queryKey: [USERS, "anonymous"],
    queryFn: async () => {
      const users = await api.get<Page<UserOut>>("/users", { query: { limit: EVERY } });
      return users.items.find((one) => one.builtin && one.username === "anonymous") ?? null;
    },
    enabled,
  });
}

export function useCreateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: UserCreate) => api.post<UserOut>("/users", wanted),
    gcTime: 0, // what was sent has a password in it
    onSuccess: () => afterSecurityChange(client),
  });
}

export function useUpdateUser(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: UserUpdate) => api.patch<UserOut>(user(id), changes),
    onSuccess: () => afterSecurityChange(client),
  });
}

export function useResetPassword(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: PasswordReset) => api.put<void>(`${user(id)}/password`, wanted),
    gcTime: 0, // what was sent is a password
    onSuccess: () => afterSecurityChange(client),
  });
}

export function useDeleteUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(user(id)),
    onSuccess: (_, id) => {
      client.removeQueries({ queryKey: [USERS, "one", id] });
      client.removeQueries({ queryKey: [TOKENS, "of", id] });
      return afterSecurityChange(client);
    },
  });
}

export function useUserTokens(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [TOKENS, "of", id],
    queryFn: () => api.get<Page<TokenInfo>>(`${user(id)}/tokens`, { query: { limit: EVERY } }),
    enabled,
  });
}

export function useRevokeUserToken(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (token: string) =>
      api.delete<void>(`${user(id)}/tokens/${encodeURIComponent(token)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: [TOKENS, "of", id] }),
  });
}

export function useUserConnectedApps(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [APPS, "of", id],
    queryFn: () =>
      api.get<Page<ConnectedApp>>(`${user(id)}/connected-apps`, { query: { limit: EVERY } }),
    enabled,
  });
}

export function useRevokeUserConnectedApp(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (app: string) =>
      api.delete<void>(`${user(id)}/connected-apps/${encodeURIComponent(app)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: [APPS, "of", id] }),
  });
}

// --- Roles ----------------------------------------------------------------------------------

export function useRoles(page: number) {
  return useQuery({
    queryKey: [ROLES, "list", page],
    queryFn: () => api.get<Page<RoleOut>>("/roles", { query: paged(page) }),
  });
}

/** The roles there are, for a form to choose from. `enabled` is false for who may not read them. */
export function useEveryRole(enabled = true) {
  return useQuery({
    queryKey: [ROLES, "every"],
    queryFn: () => api.get<Page<RoleOut>>("/roles", { query: { limit: EVERY } }),
    enabled,
  });
}

export function useRole(name: string | null) {
  return useQuery({
    queryKey: [ROLES, "one", name],
    queryFn: () => api.get<RoleOut>(role(name ?? "")),
    enabled: name !== null,
  });
}

export function useCreateRole() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: RoleCreate) => api.post<RoleOut>("/roles", wanted),
    onSuccess: () => afterSecurityChange(client),
  });
}

export function useUpdateRole(name: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (content: RoleContent) => api.put<RoleOut>(role(name), content),
    onSuccess: () => afterSecurityChange(client),
  });
}

export function useDeleteRole() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.delete<void>(role(name)),
    onSuccess: (_, name) => {
      client.removeQueries({ queryKey: [ROLES, "one", name] });
      return afterSecurityChange(client);
    },
  });
}

// --- Settings -------------------------------------------------------------------------------

export function useSettings() {
  return useQuery({
    queryKey: [SETTINGS],
    queryFn: () => api.get<SettingsOut>("/settings"),
  });
}

export function useSetAnonymousAccess() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      api.put<SettingsOut>("/settings/anonymous-access", { enabled }),
    onSuccess: (settings) => client.setQueryData([SETTINGS], settings),
  });
}

// --- How people sign in (spec 4) ------------------------------------------------------------

const source = (id: string) => `/auth-sources/${encodeURIComponent(id)}`;

export function useSignInSettings() {
  return useQuery({
    queryKey: [SIGN_IN],
    queryFn: () => api.get<SignInSettings>("/settings/sign-in"),
  });
}

/** What every signed-in user may do can change with it: the session is asked again. */
export function useSetDefaultRole() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (role: string | null) =>
      api.put<SignInSettings>("/settings/default-role", { default_role: role }),
    onSuccess: (settings) => {
      client.setQueryData([SIGN_IN], settings);
      return client.invalidateQueries({ queryKey: SESSION_KEY });
    },
  });
}

/** Turned off, whoever is signed in as one of MegooArti's own users but `admin` is no longer. */
export function useSetLocalSignIn() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      api.put<SignInSettings>("/settings/local-sign-in", { enabled }),
    onSuccess: (settings) => {
      client.setQueryData([SIGN_IN], settings);
      return client.invalidateQueries({ queryKey: SESSION_KEY });
    },
  });
}

/** Every source, in the order they are asked: there are few, and their order is the point. */
export function useSources() {
  return useQuery({
    queryKey: [SOURCES],
    queryFn: () => api.get<Page<SourceOut>>("/auth-sources", { query: { limit: EVERY } }),
  });
}

export function useUpdateSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, wanted }: { id: string; wanted: SourceIn }) =>
      api.put<SourceOut>(source(id), wanted),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: [USERS] });
      return client.invalidateQueries({ queryKey: [SOURCES] });
    },
  });
}

export function useOrderSources() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) => api.put<Page<SourceOut>>("/auth-sources/order", { ids }),
    onSuccess: (ordered) => client.setQueryData([SOURCES], ordered),
  });
}

/** Its users are disabled, and kept: the users are asked for again. */
export function useDeleteSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(source(id)),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: [USERS] });
      return client.invalidateQueries({ queryKey: [SOURCES] });
    },
  });
}

/** Whether a source answers. What it found is given to whoever asked, and kept nowhere. */
export function useTestSource() {
  return useMutation({
    mutationFn: (id: string) => api.post<SourceTested>(`${source(id)}/test`, {}),
    gcTime: 0,
  });
}
