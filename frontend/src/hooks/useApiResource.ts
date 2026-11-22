import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { isAbortError } from '../utils/errors.ts';

interface ResourceState<T> {
  data: T | undefined;
  error: Error | null;
  loading: boolean;
}

export interface ApiResource<T> extends ResourceState<T> {
  reload: () => void;
  /** an updater may hand back `undefined` (nothing loaded yet) unchanged */
  setData: (next: T | ((current: T | undefined) => T | undefined)) => void;
}

/**
 * Loads data from an async fetcher and tracks `{ data, error, loading }`.
 *
 * - The request runs again whenever a value in `deps` changes and when `reload()` is called.
 * - Each request gets its own AbortSignal. Changing deps, reloading or unmounting aborts the
 *   previous request and discards its result, so a slow response never overwrites a newer one.
 * - When deps change, `data` is cleared so the UI never shows one entity's data under another's
 *   id; `reload()` keeps the current data on screen while the refresh is in flight.
 *
 * @param fetcher performs the request (a service call)
 * @param deps values the request depends on; must keep a fixed length
 * @param options `enabled: false` skips loading (e.g. no id yet)
 */
export function useApiResource<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: ReadonlyArray<unknown>,
  { enabled = true }: { enabled?: boolean } = {},
): ApiResource<T> {
  const fetcherRef = useRef(fetcher);
  const lastDepsRef = useRef<ReadonlyArray<unknown> | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [state, setState] = useState<ResourceState<T>>({ data: undefined, error: null, loading: enabled });

  useLayoutEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    if (!enabled) {
      lastDepsRef.current = null;
      setState(IDLE);
      return undefined;
    }
    const depsChanged = !sameValues(lastDepsRef.current, deps);
    lastDepsRef.current = deps;
    const controller = new AbortController();
    setState((current) => startLoading(current, depsChanged));

    // The request starts in a microtask, so an effect that is cleaned up right away (React
    // StrictMode, quick deps changes) never sends it.
    Promise.resolve()
      .then(() => (controller.signal.aborted ? undefined : fetcherRef.current(controller.signal)))
      .then(
        (data) => {
          if (!controller.signal.aborted) {
            setState({ data, error: null, loading: false });
          }
        },
        (error) => {
          if (!controller.signal.aborted && !isAbortError(error)) {
            setState((current) => ({ data: current.data, error, loading: false }));
          }
        },
      );
    return () => controller.abort();
    // `deps` are spread on purpose: callers declare them like useEffect dependencies, and the
    // latest fetcher is read through a ref so it does not need to be memoized.
  }, [enabled, reloadToken, ...deps]);

  const reload = useCallback(() => setReloadToken((token) => token + 1), []);
  const setData = useCallback((next: T | ((current: T | undefined) => T | undefined)) => {
    setState((current) => ({
      ...current,
      data: typeof next === 'function' ? (next as (current: T | undefined) => T | undefined)(current.data) : next,
    }));
  }, []);

  return { data: state.data, error: state.error, loading: state.loading, reload, setData };
}

const IDLE = Object.freeze({ data: undefined, error: null, loading: false });

function startLoading<T>(current: ResourceState<T>, clearData: boolean): ResourceState<T> {
  const data = clearData ? undefined : current.data;
  if (current.loading && current.error === null && current.data === data) {
    return current;
  }
  return { data, error: null, loading: true };
}

function sameValues(previous: ReadonlyArray<unknown> | null, next: ReadonlyArray<unknown>): boolean {
  return (
    previous !== null &&
    previous.length === next.length &&
    previous.every((value, index) => Object.is(value, next[index]))
  );
}
