/**
 * Small data-loading hooks.
 *
 * Deliberately not a data-fetching library. The app has one user, no cache
 * invalidation across tabs, and about a dozen endpoints; `useAsync` plus an
 * explicit `reload` covers all of it in thirty lines, and the alternative is a
 * dependency larger than the rest of the client put together.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import type { Subject } from "./api/types";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Run an async loader on mount and whenever `deps` change. */
export function useAsync<T>(loader: () => Promise<T>, deps: readonly unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  // Guards against a slow response from a previous subject landing after a fast
  // one from the current subject and overwriting it.
  const latest = useRef(0);

  useEffect(() => {
    const ticket = ++latest.current;
    setLoading(true);
    loader()
      .then((value) => {
        if (ticket !== latest.current) return;
        setData(value);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (ticket !== latest.current) return;
        setError(caught instanceof Error ? caught.message : "Something went wrong.");
      })
      .finally(() => {
        if (ticket === latest.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, error, loading, reload: useCallback(() => setNonce((n) => n + 1), []) };
}

/**
 * Load a subject, polling while its concept graph is still being generated.
 *
 * Generation is a slow reasoning call kicked off in the background, so the first
 * thing a new subject shows is a pending status. Polling stops the moment the
 * graph is ready or has failed.
 */
export function useSubject(subjectId: string) {
  const state = useAsync(() => api.getSubject(subjectId), [subjectId]);
  const status = state.data?.graph_status;
  const reload = state.reload;

  useEffect(() => {
    if (status !== "pending" && status !== "generating") return;
    const timer = window.setInterval(reload, 2000);
    return () => window.clearInterval(timer);
  }, [status, reload]);

  return { subject: state.data as Subject | null, ...state };
}
