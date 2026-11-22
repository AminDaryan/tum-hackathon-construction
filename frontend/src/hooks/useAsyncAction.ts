import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { isAbortError } from '../utils/errors.ts';

interface ActionState<TResult> {
  pending: boolean;
  error: Error | null;
  result: TResult | undefined;
}

export interface AsyncAction<TArgs extends unknown[], TResult> extends ActionState<TResult> {
  execute: (...args: TArgs) => Promise<TResult | undefined>;
  reset: () => void;
}

/**
 * Runs a user-triggered async operation (upload, validation run, review, download) and tracks
 * `{ pending, error, result }`.
 *
 * - One call at a time: `execute` is ignored while a call is pending (no double submission).
 * - The action receives an AbortSignal; unmounting aborts it and drops late results.
 * - `execute` resolves with the result, or `undefined` when the action failed (the error is then
 *   in `error`), so callers can chain follow-up steps without try/catch.
 */
export function useAsyncAction<TArgs extends unknown[], TResult>(
  action: (signal: AbortSignal, ...args: TArgs) => Promise<TResult>,
): AsyncAction<TArgs, TResult> {
  const actionRef = useRef(action);
  const controllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(false);
  const [state, setState] = useState<ActionState<TResult>>(INITIAL);

  useLayoutEffect(() => {
    actionRef.current = action;
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      controllerRef.current?.abort();
    };
  }, []);

  const execute = useCallback(async (...args: TArgs): Promise<TResult | undefined> => {
    if (controllerRef.current) {
      return undefined;
    }
    const controller = new AbortController();
    controllerRef.current = controller;
    setState({ pending: true, error: null, result: undefined });
    try {
      const result = await actionRef.current(controller.signal, ...args);
      if (mountedRef.current && !controller.signal.aborted) {
        setState({ pending: false, error: null, result });
      }
      return result;
    } catch (error) {
      if (mountedRef.current && !isAbortError(error)) {
        setState({ pending: false, error: error as Error, result: undefined });
      }
      return undefined;
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
    }
  }, []);

  const reset = useCallback(() => setState(INITIAL), []);

  return { ...state, execute, reset };
}

const INITIAL = Object.freeze({ pending: false, error: null, result: undefined });
