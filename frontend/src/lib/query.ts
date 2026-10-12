import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { isApiError } from "@/lib/api/client";
import { SESSION_KEY, sessionMayHaveChanged } from "@/lib/session/session";

/**
 * The store of what was fetched, with the one rule every request shares: a refusal
 * that may mean the session has changed makes the session be asked for again, and what
 * is shown then follows from its answer.
 *
 * Not when it is the session's own request that was refused: asking again would be
 * refused again, without end. That failure is shown, with a way to try again.
 */
export function createQueryClient(options: { retry?: boolean } = {}): QueryClient {
  const refused = (error: unknown) => {
    if (sessionMayHaveChanged(error)) void client.invalidateQueries({ queryKey: SESSION_KEY });
  };
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.queryKey[0] !== SESSION_KEY[0]) refused(error);
      },
    }),
    mutationCache: new MutationCache({ onError: refused }),
    defaultOptions: {
      queries: {
        // What the server refuses, it refuses again. What did not arrive is tried once more.
        retry:
          options.retry === false
            ? false
            : (failures, error) => failures < 1 && !(isApiError(error) && error.status > 0),
        refetchOnWindowFocus: false,
      },
    },
  });
  return client;
}
