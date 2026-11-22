import { describe, expect, it } from 'vitest';
import { ApiError } from '../services/apiClient.ts';
import { describeError } from './errors.ts';

describe('describeError', () => {
  it('adds what to do next for upload and review errors', () => {
    const tooLarge = new ApiError({ status: 413, code: 'file_too_large', message: 'Too large.' });
    expect(describeError(tooLarge)).toMatchObject({ message: 'Too large.', code: 'file_too_large' });
    expect(describeError(tooLarge).hint).toMatch(/upload limit/);
    expect(describeError(new ApiError({ status: 409, code: 'conflict', message: 'Stale.' })).hint).toMatch(/Reload/);
  });

  it('lists plan and request problems from details.errors', () => {
    const plan = new ApiError({
      status: 422,
      code: 'invalid_validation_plan',
      message: 'The plan was rejected.',
      details: { errors: [{ step: 0, code: 'unknown_detector', message: 'Unknown detector x.' }, { code: 'baseline_step_missing' }] },
    });
    expect(describeError(plan).problems).toEqual(['Step 1: Unknown detector x.', 'baseline_step_missing']);
    const request = new ApiError({
      status: 422,
      code: 'request_validation_failed',
      message: 'The request is malformed.',
      details: { errors: [{ loc: ['body', 'expected_version'], msg: 'Field required' }] },
    });
    expect(describeError(request).problems).toEqual(['expected_version: Field required']);
  });

  it('describes values that are not errors', () => {
    expect(describeError(undefined)).toEqual({
      message: 'An unexpected error occurred.',
      hint: null,
      problems: [],
      code: null,
      requestId: null,
      status: null,
    });
  });
});
