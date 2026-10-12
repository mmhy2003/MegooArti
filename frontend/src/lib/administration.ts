"use client";

/**
 * What an administrator keeps besides people, asked of the API: the repositories as
 * they are set up, the blob stores, and the installation itself.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  BlobStoreCreate,
  BlobStoreOut,
  IndexRebuilt,
  Information,
  Page,
  RepositoryCreate,
  RepositoryOut,
  RepositoryUpdate,
  SettingsOut,
} from "@/lib/api/types";
import { SETTINGS_KEY } from "@/lib/security";

// As many of a list as one page shows.
export const AT_ONCE = 50;
// As many as one request may ask for: the choices of a form.
const EVERY = 200;

const REPOSITORIES = "repositories";
const BLOB_STORES = "blob-stores";
// What the browsing screens fetched (lib/content.ts): a repository that was made,
// changed or deleted is another one there too.
const CONTENT = "content";

const paged = (page: number) => ({ limit: AT_ONCE, offset: (page - 1) * AT_ONCE });
const repository = (name: string) => `/repositories/${encodeURIComponent(name)}`;

function afterRepositoryChange(client: QueryClient): Promise<void> {
  void client.invalidateQueries({ queryKey: [CONTENT] });
  void client.invalidateQueries({ queryKey: ["search"] });
  // A blob store says how much it holds, and who uses it decides whether it can go.
  void client.invalidateQueries({ queryKey: [BLOB_STORES] });
  return client.invalidateQueries({ queryKey: [REPOSITORIES] });
}

// --- Repositories ---------------------------------------------------------------------------

export function useManagedRepositories(page: number) {
  return useQuery({
    queryKey: [REPOSITORIES, "list", page],
    queryFn: () => api.get<Page<RepositoryOut>>("/repositories", { query: paged(page) }),
  });
}

/** The repositories there are, for a group's form to choose its members from. */
export function useEveryManagedRepository() {
  return useQuery({
    queryKey: [REPOSITORIES, "every"],
    queryFn: () => api.get<Page<RepositoryOut>>("/repositories", { query: { limit: EVERY } }),
  });
}

export function useManagedRepository(name: string | null) {
  return useQuery({
    queryKey: [REPOSITORIES, "one", name],
    queryFn: () => api.get<RepositoryOut>(repository(name ?? "")),
    enabled: name !== null,
  });
}

export function useCreateRepository() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: RepositoryCreate) => api.post<RepositoryOut>("/repositories", wanted),
    gcTime: 0, // what was sent may have a remote's secret in it
    onSuccess: () => afterRepositoryChange(client),
  });
}

export function useUpdateRepository(name: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: RepositoryUpdate) => api.put<RepositoryOut>(repository(name), changes),
    gcTime: 0, // as above
    onSuccess: (saved) => {
      // The answer is the repository as it is now: its page shows it without asking again.
      client.setQueryData([REPOSITORIES, "one", name], saved);
      return afterRepositoryChange(client);
    },
  });
}

export function useDeleteRepository() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.delete<void>(repository(name)),
    onSuccess: (_, name) => {
      client.removeQueries({ queryKey: [REPOSITORIES, "one", name] });
      return afterRepositoryChange(client);
    },
  });
}

/** Makes a proxy check everything it cached with its remote again. */
export function useInvalidateCache(name: string) {
  return useMutation({
    mutationFn: () => api.post<void>(`${repository(name)}/invalidate-cache`),
  });
}

/** Goes through a repository again. The answer says what was found; it can take a while. */
export function useRebuildIndex(name: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<IndexRebuilt>(`${repository(name)}/rebuild-index`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: [CONTENT] });
      return client.invalidateQueries({ queryKey: ["search"] });
    },
  });
}

// --- Blob stores ----------------------------------------------------------------------------

export function useBlobStores(page: number) {
  return useQuery({
    queryKey: [BLOB_STORES, "list", page],
    queryFn: () => api.get<Page<BlobStoreOut>>("/blob-stores", { query: paged(page) }),
  });
}

/** The blob stores there are, for a form to choose from. `enabled` is false for who may not read them. */
export function useEveryBlobStore(enabled = true) {
  return useQuery({
    queryKey: [BLOB_STORES, "every"],
    queryFn: () => api.get<Page<BlobStoreOut>>("/blob-stores", { query: { limit: EVERY } }),
    enabled,
  });
}

export function useCreateBlobStore() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: BlobStoreCreate) => api.post<BlobStoreOut>("/blob-stores", wanted),
    onSuccess: () => client.invalidateQueries({ queryKey: [BLOB_STORES] }),
  });
}

export function useDeleteBlobStore() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.delete<void>(`/blob-stores/${encodeURIComponent(name)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: [BLOB_STORES] }),
  });
}

// --- The installation -----------------------------------------------------------------------

export function useInformation() {
  return useQuery({
    queryKey: ["system", "information"],
    queryFn: () => api.get<Information>("/system/information"),
  });
}

/** Sets the address the server gives out as its own, or clears it with null. */
export function useSetBaseUrl() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (baseUrl: string | null) =>
      api.put<SettingsOut>("/settings/base-url", { base_url: baseUrl }),
    onSuccess: (settings) => {
      client.setQueryData(SETTINGS_KEY, settings);
      // Every address the server gives out is built from it.
      return client.invalidateQueries({ queryKey: [CONTENT] });
    },
  });
}
