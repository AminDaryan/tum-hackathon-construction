import { describe, expect, it, vi } from 'vitest';
import { errorResponse, jsonResponse, mockFetch, type MockCall } from '../test/fetchMock.ts';
import { ACCESS_TOKEN_STORAGE_KEY, getAccessToken, onUnauthorized, setAccessToken } from './accessToken.ts';
import { ApiError, apiClient, apiPath, buildQuery, requestJsonResponse, resolveBaseUrl } from './apiClient.ts';
import { listRunIssues, submitReview } from './issuesService.ts';

describe('apiClient', () => {
  it('sends GET requests below the base URL and parses JSON', async () => {
    const api = mockFetch([{ method: 'GET', path: '/api/v1/documents', respond: { items: [], total: 0 } }]);
    const data = await apiClient.get('/documents', { query: { offset: 0, limit: 50 } });
    expect(data).toEqual({ items: [], total: 0 });
    expect(api.calls).toHaveLength(1);
    expect(api.calls[0].query.toString()).toBe('offset=0&limit=50');
    expect(api.calls[0].headers.get('Accept')).toBe('application/json');
  });

  it('turns the error envelope into an ApiError with code, details and request id', async () => {
    mockFetch([
      {
        method: 'POST',
        path: '/api/v1/issues/iss_1/review',
        respond: errorResponse(409, 'invalid_review_transition', 'Cannot change review status.', {
          details: { current: 'dismissed', target: 'confirmed_error' },
          requestId: 'req_42',
        }),
      },
    ]);
    const failure = submitReview('iss_1', { status: 'confirmed_error', expectedVersion: 1 });
    await expect(failure).rejects.toBeInstanceOf(ApiError);
    await expect(failure).rejects.toMatchObject({
      status: 409,
      code: 'invalid_review_transition',
      message: 'Cannot change review status.',
      details: { current: 'dismissed', target: 'confirmed_error' },
      requestId: 'req_42',
    });
  });

  it('falls back to http_error and the X-Request-ID header without an envelope', async () => {
    mockFetch([
      {
        path: '/api/v1/health',
        respond: new Response('Bad gateway', { status: 502, headers: { 'X-Request-ID': 'req_gw' } }),
      },
    ]);
    await expect(apiClient.get('/health')).rejects.toMatchObject({ status: 502, code: 'http_error', requestId: 'req_gw' });
  });

  it('reports network failures as network_error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(apiClient.get('/health')).rejects.toMatchObject({
      status: 0,
      code: 'network_error',
      details: { cause: 'Failed to fetch' },
    });
  });

  it('re-throws cancellations unchanged', async () => {
    const controller = new AbortController();
    controller.abort();
    mockFetch([{ path: '/api/v1/health', respond: { status: 'ok' } }]);
    await expect(apiClient.get('/health', { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('returns null for empty responses and rejects invalid JSON', async () => {
    mockFetch([
      { path: '/api/v1/empty', respond: new Response(null, { status: 204 }) },
      { path: '/api/v1/broken', respond: new Response('not json', { status: 200 }) },
    ]);
    await expect(apiClient.get('/empty')).resolves.toBeNull();
    await expect(apiClient.get('/broken')).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('sends JSON bodies with the expected version and omits empty review comments', async () => {
    const api = mockFetch([
      { method: 'POST', path: '/api/v1/issues/iss_1/review', respond: (call: MockCall) => jsonResponse({ echo: JSON.parse(call.body) }) },
    ]);
    await expect(
      submitReview('iss_1', { status: 'dismissed', expectedVersion: 3, comment: '   ' }),
    ).resolves.toEqual({ echo: { status: 'dismissed', expected_version: 3 } });
    await submitReview('iss_1', { status: 'false_positive', expectedVersion: 3, comment: ' Checked on site. ' });
    expect(JSON.parse(api.calls[1].body)).toEqual({
      status: 'false_positive',
      expected_version: 3,
      comment: 'Checked on site.',
    });
    expect(api.calls[1].headers.get('Content-Type')).toBe('application/json');
  });

  it('serializes repeated filter parameters and encodes path segments', async () => {
    const api = mockFetch([{ path: '/api/v1/validation-runs/run%2F1/issues', respond: { items: [], total: 0 } }]);
    await listRunIssues('run/1', { filters: { severity: ['high', 'critical'], category: [] }, offset: 50, limit: 50 });
    expect(api.calls[0].query.getAll('severity')).toEqual(['high', 'critical']);
    expect(api.calls[0].query.has('category')).toBe(false);
    expect(api.calls[0].query.get('offset')).toBe('50');
  });
});

describe('request helpers', () => {
  it('builds queries without empty values', () => {
    expect(buildQuery({ a: 1, b: null, c: '', d: ['x', 'y'], e: undefined })).toBe('?a=1&d=x&d=y');
    expect(buildQuery({})).toBe('');
  });

  it('encodes interpolated path segments', () => {
    expect(apiPath`/issues/${'a b/c'}/review`).toBe('/issues/a%20b%2Fc/review');
  });

  it('resolves the base URL from the environment value', () => {
    expect(resolveBaseUrl(undefined)).toBe('/api/v1');
    expect(resolveBaseUrl('http://127.0.0.1:8000/api/v1/')).toBe('http://127.0.0.1:8000/api/v1');
  });

  it('sends the session token as a bearer token and forgets it on 401 unauthorized', async () => {
    const api = mockFetch([
      { path: '/api/v1/documents', respond: errorResponse(401, 'unauthorized', 'A valid access token is required.') },
      { path: '/api/v1/profiles', respond: { items: [] } },
    ]);
    setAccessToken('t0ken');
    expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBe('t0ken');
    const notified = vi.fn();
    const unsubscribe = onUnauthorized(notified);

    await apiClient.get('/profiles', { authToken: 'other' });
    expect(api.calls[0].headers.get('Authorization')).toBe('Bearer other');
    expect(getAccessToken()).toBe('t0ken');

    await expect(apiClient.get('/documents')).rejects.toMatchObject({ status: 401, code: 'unauthorized' });
    expect(api.calls[1].headers.get('Authorization')).toBe('Bearer t0ken');
    expect(notified).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
    unsubscribe();
  });

  it('keeps the token in memory when sessionStorage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Blocked', 'SecurityError');
    });
    setAccessToken('memory-only');
    expect(getAccessToken()).toBe('memory-only');
    setAccessToken(null);
    expect(getAccessToken()).toBeNull();
  });

  it('returns the status and headers with the JSON body when asked', async () => {
    mockFetch([
      {
        method: 'POST',
        path: '/api/v1/datasets/ds_1/validation-runs',
        respond: (call: MockCall) =>
          jsonResponse({ run_id: 'run_1', prefer: call.headers.get('Prefer') }, { status: 202, headers: { Location: '/api/v1/validation-runs/run_1' } }),
      },
    ]);
    const answer = await requestJsonResponse('/datasets/ds_1/validation-runs', {
      method: 'POST',
      json: {},
      headers: { Prefer: 'respond-async' },
    });
    expect(answer.status).toBe(202);
    expect(answer.data).toEqual({ run_id: 'run_1', prefer: 'respond-async' });
    expect(answer.headers.get('Location')).toBe('/api/v1/validation-runs/run_1');
  });
});
