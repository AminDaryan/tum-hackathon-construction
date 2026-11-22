/**
 * Follows a validation run that the server runs in the background (202 Accepted) until it
 * reaches a terminal status. GET /validation-runs/{run_id} is polled about every second at
 * first, backing off by half each time to at most every five seconds. Every request is cancelled
 * through the caller's AbortSignal, so leaving the view stops the polling at once.
 */
import { getValidationRun } from '../../services/validationService.ts';
import { isAbortError } from '../../utils/errors.ts';
import type { ValidationRunDetail } from '../../services/apiTypes.ts';

/** Run statuses after which a run no longer changes (backend/app/models/run.py: RunStatus). */
const TERMINAL_RUN_STATUSES = Object.freeze(new Set(['completed', 'completed_with_errors', 'failed']));

const POLL_DELAYS = Object.freeze({ initialMs: 1000, maxMs: 5000, factor: 1.5 });

/** Failed polls in a row (network errors, 429 and 5xx) tolerated before giving up. */
const MAX_CONSECUTIVE_POLL_FAILURES = 3;

export function isTerminalRunStatus(status: string | null | undefined): boolean {
  return status != null && TERMINAL_RUN_STATUSES.has(status);
}

/**
 * Resolves after `ms`, or rejects with an AbortError as soon as `signal` aborts.
 */
export function abortableDelay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', abort);
      resolve();
    }, ms);
    if (signal?.aborted) abort();
    else signal?.addEventListener('abort', abort, { once: true });
  });
}

function isTransient(error: unknown) {
  const status = (error as { status?: unknown } | null)?.status;
  return status === 0 || status === 429 || (typeof status === 'number' && status >= 500);
}

/**
 * Polls a run until its status is terminal.
 *
 * @param options `wait` and `fetchRun` are replaceable for tests
 * @returns the finished run
 * @throws the last error after {@link MAX_CONSECUTIVE_POLL_FAILURES} transient failures in a
 *   row, any other API error at once, and an AbortError when cancelled
 */
export async function pollValidationRun(
  runId: string,
  {
    signal,
    onUpdate,
    delays = POLL_DELAYS,
    wait = abortableDelay,
    fetchRun = getValidationRun,
  }: {
    signal?: AbortSignal;
    onUpdate?: (run: ValidationRunDetail) => void;
    delays?: { initialMs: number; maxMs: number; factor: number };
    wait?: (ms: number, signal?: AbortSignal) => Promise<void>;
    fetchRun?: typeof getValidationRun;
  } = {},
): Promise<ValidationRunDetail> {
  let delay = delays.initialMs;
  let failures = 0;
  for (;;) {
    await wait(delay, signal);
    delay = Math.min(delays.maxMs, Math.round(delay * delays.factor));
    let run;
    try {
      run = await fetchRun(runId, { signal });
    } catch (error) {
      if (isAbortError(error) || signal?.aborted) throw error;
      failures += 1;
      if (!isTransient(error) || failures >= MAX_CONSECUTIVE_POLL_FAILURES) throw error;
      continue;
    }
    failures = 0;
    onUpdate?.(run);
    if (isTerminalRunStatus(run.status)) return run;
  }
}
