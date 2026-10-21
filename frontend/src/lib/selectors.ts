"use client";

/**
 * Content selectors (spec 10): the expressions selector permissions name, kept by an
 * administrator, and tried against paths before they are trusted with anything.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  Page,
  Preview,
  PreviewOut,
  SelectorContent,
  SelectorCreate,
  SelectorOut,
} from "@/lib/api/types";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

// As many of a list as one page shows (A13).
export const AT_ONCE = 50;
// As many as one request may ask for: the choices of a form.
const EVERY = 200;
const SELECTORS = "content-selectors";

const paged = (page: number) => ({ limit: AT_ONCE, offset: (page - 1) * AT_ONCE });
const one = (name: string) => `/content-selectors/${encodeURIComponent(name)}`;

/** A selector changed what a permission naming it reaches: what roles show may be stale. */
function afterChange(client: QueryClient): Promise<void> {
  return client.invalidateQueries({ queryKey: [SELECTORS] });
}

export function useSelectors(page: number) {
  return useQuery({
    queryKey: [SELECTORS, "list", page],
    queryFn: () => api.get<Page<SelectorOut>>("/content-selectors", { query: paged(page) }),
  });
}

/** The selectors there are, for a form to choose from. `enabled` is false for who may not read them. */
export function useEverySelector(enabled = true) {
  return useQuery({
    queryKey: [SELECTORS, "every"],
    queryFn: () => api.get<Page<SelectorOut>>("/content-selectors", { query: { limit: EVERY } }),
    enabled,
  });
}

/**
 * The names of the selectors there are, for a selector permission's row to choose from:
 * none for whoever may not read them, who types a selector's name instead.
 */
export function useSelectorNames(): string[] {
  const session = useSession();
  const mayRead = session.data !== undefined && allows(session.data, "admin:selectors:read");
  const every = useEverySelector(mayRead);
  return mayRead ? (every.data?.items.map((selector) => selector.name) ?? []) : [];
}

export function useSelector(name: string | null) {
  return useQuery({
    queryKey: [SELECTORS, "one", name],
    queryFn: () => api.get<SelectorOut>(one(name ?? "")),
    enabled: name !== null,
  });
}

export function useCreateSelector() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: SelectorCreate) => api.post<SelectorOut>("/content-selectors", wanted),
    onSuccess: () => afterChange(client),
  });
}

export function useUpdateSelector(name: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (content: SelectorContent) => api.put<SelectorOut>(one(name), content),
    onSuccess: () => afterChange(client),
  });
}

export function useDeleteSelector() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.delete<void>(one(name)),
    onSuccess: (_, name) => {
      client.removeQueries({ queryKey: [SELECTORS, "one", name] });
      return afterChange(client);
    },
  });
}

/** Which of some paths an expression matches, in a repository of a format. Keeps nothing. */
export function usePreview() {
  return useMutation({
    mutationFn: (asked: Preview) => api.post<PreviewOut>("/content-selectors/preview", asked),
  });
}
