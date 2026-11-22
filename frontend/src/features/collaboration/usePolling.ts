import { useEffect, useState } from 'react';
import { isAbortError } from '../../utils/errors.ts';

/** A resource kept fresh by {@link usePolling}. */
export interface Polled<T> {
  data: T | null;
  error: Error | null;
  reload: () => void;
}

// One in-flight request per resource; hidden tabs stop polling and refresh on returning.
export function usePolling<T>(load: (signal: AbortSignal) => Promise<T>, dependencies: unknown[], enabled = true): Polled<T> {
  const [state, setState] = useState<{ data: T | null; error: Error | null }>({ data: null, error: null });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!enabled) {
      setState({ data: null, error: null });
      return undefined;
    }
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    async function refresh() {
      clearTimeout(timer);
      controller?.abort();
      controller = new AbortController();
      const active = controller;
      try {
        const data = await load(active.signal);
        if (!disposed && !active.signal.aborted) setState({ data, error: null });
      } catch (error) {
        if (!disposed && !active.signal.aborted && !isAbortError(error)) setState((old) => ({ ...old, error: error as Error }));
      } finally {
        if (!disposed && controller === active && !document.hidden) timer = setTimeout(refresh, 3000);
      }
    }
    const visibility = () => {
      if (!document.hidden) refresh();
      else clearTimeout(timer);
    };
    setState({ data: null, error: null });
    if (!document.hidden) refresh();
    document.addEventListener('visibilitychange', visibility);
    return () => {
      disposed = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', visibility);
    };
    // The caller lists the resource identities its loader reads, not the inline loader, which is
    // a new function on every render.
  }, [...dependencies, enabled, revision]);
  return { ...state, reload: () => setRevision((n) => n + 1) };
}
