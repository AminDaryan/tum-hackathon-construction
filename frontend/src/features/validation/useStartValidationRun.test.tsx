import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { jsonResponse, mockFetch } from '../../test/fetchMock.ts';
import { runDetail } from '../../test/fixtures.ts';
import { useStartValidationRun } from './useStartValidationRun.ts';

const START = '/api/v1/datasets/ds_1/validation-runs';
const RUN = '/api/v1/validation-runs/run_2';
const queued = { ...runDetail, status: 'queued', finished_at: null, detector_reports: [], issue_count: 0 };

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe('useStartValidationRun', () => {
  it('asks for a background run and uses a finished run (201) as it is', async () => {
    const api = mockFetch([{ method: 'POST', path: START, respond: jsonResponse(runDetail, { status: 201 }) }]);
    const onAccepted = vi.fn();
    const onCompleted = vi.fn();
    const { result } = renderHook(() => useStartValidationRun('ds_1', { onAccepted, onCompleted }));

    let finished;
    await act(async () => {
      finished = await result.current.execute();
    });
    expect(finished).toEqual(runDetail);
    expect(api.callsTo('POST', START)[0].headers.get('Prefer')).toBe('respond-async');
    expect(api.callsTo('GET', RUN)).toHaveLength(0);
    expect(onAccepted).toHaveBeenCalledWith(runDetail);
    expect(onCompleted).toHaveBeenCalledWith(runDetail);
    expect(result.current.trackedRun).toBeNull();
  });

  it('follows an accepted run (202) until it has finished', async () => {
    const answers = [{ ...queued, status: 'running' }, runDetail];
    const api = mockFetch([
      { method: 'POST', path: START, respond: jsonResponse(queued, { status: 202, headers: { Location: '/api/v1/validation-runs/run_2' } }) },
      { path: RUN, respond: () => answers.shift() },
    ]);
    const onCompleted = vi.fn();
    const { result } = renderHook(() => useStartValidationRun('ds_1', { onCompleted }));

    let execution;
    act(() => {
      execution = result.current.execute();
    });
    await flush();
    expect(result.current.pending).toBe(true);
    expect(result.current.trackedRun?.status).toBe('queued');
    expect(JSON.parse(api.callsTo('POST', START)[0].body)).toEqual({});

    await flush(999);
    expect(api.callsTo('GET', RUN)).toHaveLength(0);
    await flush(1);
    expect(result.current.trackedRun?.status).toBe('running');
    await flush(1500);
    expect(api.callsTo('GET', RUN)).toHaveLength(2);
    await expect(execution).resolves.toEqual(runDetail);
    expect(result.current.pending).toBe(false);
    expect(result.current.result).toEqual(runDetail);
    expect(result.current.trackedRun).toBeNull();
    expect(onCompleted).toHaveBeenCalledTimes(1);
    expect(onCompleted).toHaveBeenCalledWith(runDetail);
  });

  it('stops polling when the view unmounts', async () => {
    const api = mockFetch([{ method: 'POST', path: START, respond: jsonResponse(queued, { status: 202 }) }]);
    const onCompleted = vi.fn();
    const { result, unmount } = renderHook(() => useStartValidationRun('ds_1', { onCompleted }));
    let execution;
    act(() => {
      execution = result.current.execute();
    });
    await flush();
    expect(result.current.trackedRun?.status).toBe('queued');
    unmount();
    await flush(30_000);
    await expect(execution).resolves.toBeUndefined();
    expect(api.callsTo('GET', RUN)).toHaveLength(0);
    expect(onCompleted).not.toHaveBeenCalled();
  });
});
