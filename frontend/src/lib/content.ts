"use client";

/** What the repositories hold, asked of the content API: the requests of the browsing screens. */
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  AssetView,
  ComponentDetail,
  FolderDeleted,
  Listing,
  Page,
  RepositoryView,
  SearchResult,
  SessionInfo,
} from "@/lib/api/types";
import { allows } from "@/lib/session/rules";

const CONTENT = "content";
// As many entries of a folder as one request asks for. More come with "Show more".
export const FOLDER_AT_ONCE = 100;
export const RESULTS_AT_ONCE = 50;
// The formats whose hosted repositories take an upload through the API.
const UPLOADABLE = new Set(["raw", "maven", "npm", "pypi", "apt", "yum", "apk"]);

const at = (repository: string) => `/content/${encodeURIComponent(repository)}`;

/** Whether to offer a caller something that needs this action on a repository. */
export function may(
  session: SessionInfo | undefined,
  repository: Pick<RepositoryView, "format" | "name">,
  action: "add" | "edit" | "delete",
): boolean {
  if (!session) return false;
  return allows(session, `repository:${repository.format}:${repository.name}:${action}`);
}

/** Whether to offer an upload to this repository to this caller. */
export function takesUploads(
  session: SessionInfo | undefined,
  repository: RepositoryView,
): boolean {
  if (repository.type !== "hosted" || !UPLOADABLE.has(repository.format)) return false;
  return may(session, repository, "add") || may(session, repository, "edit");
}

export function useRepositories() {
  return useQuery({
    queryKey: [CONTENT, "repositories"],
    queryFn: () => api.get<Page<RepositoryView>>("/content", { query: { limit: 200 } }),
  });
}

export function useRepository(name: string) {
  return useQuery({
    queryKey: [CONTENT, "repository", name],
    queryFn: () => api.get<RepositoryView>(at(name)),
    enabled: name !== "",
  });
}

/** A folder's entries, a piece at a time. `enabled` is false for a group, which has none. */
export function useFolder(repository: string, folder: string, enabled = true) {
  return useInfiniteQuery({
    queryKey: [CONTENT, "tree", repository, folder],
    queryFn: ({ pageParam }) =>
      api.get<Listing>(`${at(repository)}/tree`, {
        query: { path: folder, after: pageParam || undefined, limit: FOLDER_AT_ONCE },
      }),
    initialPageParam: "",
    getNextPageParam: (last) => last.next ?? undefined,
    enabled,
  });
}

export function useAsset(repository: string, path: string | null) {
  return useQuery({
    queryKey: [CONTENT, "asset", repository, path],
    queryFn: () => api.get<AssetView>(`${at(repository)}/asset`, { query: { path } }),
    enabled: path !== null,
  });
}

export function useComponent(repository: string, id: string | null) {
  return useQuery({
    queryKey: [CONTENT, "component", repository, id],
    queryFn: () =>
      api.get<ComponentDetail>(`${at(repository)}/components/${encodeURIComponent(id ?? "")}`),
    enabled: id !== null,
  });
}

/** What a search is asked for: the API's own parameters, each a text or absent. */
export type Wanted = Partial<
  Record<
    | "q"
    | "format"
    | "repository"
    | "namespace"
    | "name"
    | "version"
    | "md5"
    | "sha1"
    | "sha256"
    | "sha512",
    string
  >
>;

export function useSearch(wanted: Wanted, page: number) {
  return useQuery({
    queryKey: ["search", wanted, page],
    queryFn: () =>
      api.get<Page<SearchResult>>("/search", {
        query: { ...wanted, limit: RESULTS_AT_ONCE, offset: (page - 1) * RESULTS_AT_ONCE },
      }),
  });
}

/** After something was stored or deleted, nothing that was fetched of the repository is true. */
export function forget(client: QueryClient, repository: string): Promise<void> {
  client.removeQueries({ queryKey: [CONTENT, "asset", repository] });
  client.removeQueries({ queryKey: [CONTENT, "component", repository] });
  void client.invalidateQueries({ queryKey: ["search"] });
  return client.invalidateQueries({ queryKey: [CONTENT, "tree", repository] });
}

export function useDeleteAsset(repository: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (path: string) => api.delete<void>(`${at(repository)}/asset`, { query: { path } }),
    onSuccess: () => forget(client, repository),
  });
}

export function useDeleteComponent(repository: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.delete<void>(`${at(repository)}/components/${encodeURIComponent(id)}`),
    onSuccess: () => forget(client, repository),
  });
}

export type FolderProgress = { deleted: number; skipped: number };

/**
 * Deletes everything under a folder, in the pieces the API does it in. `onProgress` is
 * told after each piece. It stops between pieces when `signal` says so, and then says
 * how far it got.
 */
export async function deleteFolder(
  repository: string,
  folder: string,
  options: { onProgress?: (progress: FolderProgress) => void; signal?: AbortSignal } = {},
): Promise<FolderProgress & { finished: boolean }> {
  const done = { deleted: 0, skipped: 0 };
  let after: string | null = "";
  while (after !== null) {
    if (options.signal?.aborted) return { ...done, finished: false };
    const piece: FolderDeleted = await api.delete<FolderDeleted>(`${at(repository)}/tree`, {
      query: { path: folder, after: after || undefined },
    });
    done.deleted += piece.deleted;
    done.skipped += piece.skipped;
    options.onProgress?.({ ...done });
    after = piece.next;
  }
  return { ...done, finished: true };
}
