"use client";

/**
 * Cleanup policies (cleanup spec 4, 5): what to remove from the repositories they are
 * attached to, what one would remove now, and a repository's cleanup run now.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  CleanupCount,
  Page,
  PolicyContent,
  PolicyCreate,
  PolicyOut,
  Previewing,
  Selected,
} from "@/lib/api/types";

// As many of a list as one page shows (A13).
export const AT_ONCE = 50;
// As many as one request may ask for: the choices of a form.
const EVERY = 200;
const POLICIES = "cleanup-policies";
// The repositories' queries: they show the policies attached, and their last run.
const REPOSITORIES = "repositories";

const paged = (page: number) => ({ limit: AT_ONCE, offset: (page - 1) * AT_ONCE });
const one = (name: string) => `/cleanup-policies/${encodeURIComponent(name)}`;
const repository = (name: string) => `/repositories/${encodeURIComponent(name)}`;

/** A policy changed what repositories show of it. */
function afterChange(client: QueryClient): Promise<unknown> {
  return Promise.all([
    client.invalidateQueries({ queryKey: [POLICIES] }),
    client.invalidateQueries({ queryKey: [REPOSITORIES] }),
  ]);
}

export function usePolicies(page: number) {
  return useQuery({
    queryKey: [POLICIES, "list", page],
    queryFn: () => api.get<Page<PolicyOut>>("/cleanup-policies", { query: paged(page) }),
  });
}

/** The policies there are, for a form to choose from. `enabled` is false for who may not read them. */
export function useEveryPolicy(enabled = true) {
  return useQuery({
    queryKey: [POLICIES, "every"],
    queryFn: () => api.get<Page<PolicyOut>>("/cleanup-policies", { query: { limit: EVERY } }),
    enabled,
  });
}

export function usePolicy(name: string | null) {
  return useQuery({
    queryKey: [POLICIES, "one", name],
    queryFn: () => api.get<PolicyOut>(one(name ?? "")),
    enabled: name !== null,
  });
}

export function useCreatePolicy() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: PolicyCreate) => api.post<PolicyOut>("/cleanup-policies", wanted),
    onSuccess: () => afterChange(client),
  });
}

export function useUpdatePolicy(name: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (content: PolicyContent) => api.put<PolicyOut>(one(name), content),
    onSuccess: () => afterChange(client),
  });
}

export function useDeletePolicy() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.delete<void>(one(name)),
    onSuccess: (_, name) => {
      client.removeQueries({ queryKey: [POLICIES, "one", name] });
      return afterChange(client);
    },
  });
}

/** What a policy, kept or not, would remove from a repository now: none asked while `wanted` is null. */
export function usePolicyPreview(wanted: Previewing | null, page: number) {
  return useQuery({
    queryKey: [POLICIES, "preview", wanted, page],
    queryFn: () =>
      api.post<Page<Selected>>("/cleanup-policies/preview", wanted, { query: paged(page) }),
    enabled: wanted !== null,
  });
}

/** How many components a repository's policies would remove now. */
export function useCleanupCount(name: string, enabled: boolean) {
  return useQuery({
    queryKey: [POLICIES, "count", name],
    queryFn: () => api.post<CleanupCount>(`${repository(name)}/cleanup/preview`),
    enabled,
  });
}

/** Clean a repository up now: the run goes on in the server. */
export function useCleanUpNow(name: string) {
  return useMutation({
    mutationFn: () => api.post<void>(`${repository(name)}/cleanup`),
  });
}

type Criteria = Pick<
  PolicyOut,
  "updated_days" | "downloaded_days" | "release_type" | "asset_pattern"
>;
/** The messages under `cleanup.criteria`, as `useTranslations("cleanup.criteria")` gives them. */
type Say = (
  key: "updated" | "downloaded" | "release" | "prerelease" | "pattern",
  values?: Record<string, string | number>,
) => string;

/** A policy's criteria in words, in the order of the form: "Not updated in 14 days, pre-releases". */
export function criteriaInWords(policy: Criteria, t: Say): string {
  const said: string[] = [];
  if (policy.updated_days != null) said.push(t("updated", { days: policy.updated_days }));
  if (policy.downloaded_days != null) said.push(t("downloaded", { days: policy.downloaded_days }));
  if (policy.release_type != null)
    said.push(t(policy.release_type === "release" ? "release" : "prerelease"));
  if (policy.asset_pattern != null) said.push(t("pattern", { pattern: policy.asset_pattern }));
  const words = said.join(", ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
