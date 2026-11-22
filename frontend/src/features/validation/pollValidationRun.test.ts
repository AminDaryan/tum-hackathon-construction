import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../services/apiClient.ts';
import { abortableDelay, isTerminalRunStatus, pollValidationRun } from './pollValidationRun.ts';
import type { ValidationRunDetail } from '../../services/apiTypes.ts';

// Test runs: only the id and status the polling reads.
const running = { run_id: 'run_9', status: 'running' } as ValidationRunDetail;
const completed = { run_id: 'run_9', status: 'completed' } as ValidationRunDetail;

function sequence(...answers: (ValidationRunDetail | Error)[]) {
  const queue = [...answers];
  return vi.fn(async (_runId: string, _options?: { signal?: AbortSignal }) => {
    const next = queue.shift();
    if (next instanceof Error) throw next;
    return next as ValidationRunDetail;
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe('pollValidationRun', () => {
  it('polls about every second, backing off to five seconds, until the run has finished', async () => {
    const delays: number[] = [];
    const fetchRun = sequence(running, running, running, running, running, running, completed);
    const onUpdate = vi.fn();
    const run = await pollValidationRun('run_9', {
      fetchRun,
      onUpdate,
      wait: async (ms) => {
        delays.push(ms);
      },
    });
    expect(run).toBe(completed);
    expect(delays).toEqual([1000, 1500, 2250, 3375, 5000, 5000, 5000]);
    expect(fetchRun).toHaveBeenCalledTimes(7);
    expect(fetchRun.mock.calls[0][0]).toBe('run_9');
    expect(onUpdate).toHaveBeenCalledTimes(7);
    expect(onUpdate).toHaveBeenLastCalledWith(completed);
  });

  it('tolerates a few transient failures and gives up after three in a row', async () => {
    const offline = () => new ApiError({ status: 0, code: 'network_error', message: 'Offline.' });
    const wait = async () => {};
    await expect(
      pollValidationRun('run_9', { wait, fetchRun: sequence(offline(), new ApiError({ status: 503, code: 'http_error', message: 'Busy.' }), completed) }),
    ).resolves.toBe(completed);
    await expect(pollValidationRun('run_9', { wait, fetchRun: sequence(offline(), offline(), offline()) })).rejects.toMatchObject({
      code: 'network_error',
    });
    const missing = new ApiError({ status: 404, code: 'not_found', message: 'Unknown validation run.' });
    const fetchRun = sequence(missing, completed);
    await expect(pollValidationRun('run_9', { wait, fetchRun })).rejects.toBe(missing);
    expect(fetchRun).toHaveBeenCalledTimes(1);
  });

  it('stops at once when the signal aborts', async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const fetchRun = vi.fn();
    const polling = pollValidationRun('run_9', { signal: controller.signal, fetchRun });
    await vi.advanceTimersByTimeAsync(500);
    controller.abort();
    await expect(polling).rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchRun).not.toHaveBeenCalled();
  });
});

describe('helpers', () => {
  it('knows the terminal run statuses and waits with an abortable timer', async () => {
    expect(['completed', 'completed_with_errors', 'failed'].every(isTerminalRunStatus)).toBe(true);
    expect(isTerminalRunStatus('queued') || isTerminalRunStatus('running')).toBe(false);
    vi.useFakeTimers();
    const done = vi.fn();
    abortableDelay(1000).then(done);
    await vi.advanceTimersByTimeAsync(999);
    expect(done).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(done).toHaveBeenCalled();
    const aborted = new AbortController();
    aborted.abort();
    await expect(abortableDelay(1000, aborted.signal)).rejects.toMatchObject({ name: 'AbortError' });
  });
});
