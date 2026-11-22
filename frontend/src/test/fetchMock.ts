/**
 * Route-based stand-in for `fetch`, installed with vi.stubGlobal. The backend is never
 * contacted in tests.
 *
 *   const api = mockFetch([
 *     { method: 'GET', path: '/api/v1/documents', respond: page([documentSummary]) },
 *     { method: 'POST', path: '/api/v1/issues/iss_1/review', respond: (call) => ({ ... }) },
 *   ]);
 *
 * `respond` is a JSON body, a Response, or a function of the call returning either (it may be
 * async). An unmatched request logs a console.error (failing the test through the console
 * guard) and answers 404 with the API's error envelope.
 *
 * GET /api/v1/health, GET /api/v1/me and GET /api/v1/collaboration/session, which the
 * application calls when it starts, and GET /api/v1/projects and GET /api/v1/users, which the
 * sidebar lists, answer with defaults (no projects, no users) unless a test routes them itself.
 */
import { vi } from 'vitest';
import type { Mock } from 'vitest';

export function jsonResponse(
  body: unknown,
  { status = 200, headers = {} }: { status?: number; headers?: Record<string, string> } = {},
): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'req_test', ...headers },
  });
}

/**
 * A response with the API error envelope.
 */
export function errorResponse(
  status: number,
  code: string,
  message: string,
  { details = {}, requestId = 'req_error' }: { details?: object; requestId?: string } = {},
): Response {
  return jsonResponse(
    { error: { code, message, details, request_id: requestId } },
    { status, headers: { 'X-Request-ID': requestId } },
  );
}

/**
 * A request that never settles until its signal aborts (to observe loading states).
 */
export function pendingUntilAborted(call: { signal?: AbortSignal | null }): Promise<never> {
  return new Promise((_, reject) => {
    call.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
  });
}

/**
 * Wraps items in the API's page envelope.
 */
export function page(
  items: unknown[],
  { total = items.length, offset = 0, limit = 50 }: { total?: number; offset?: number; limit?: number } = {},
) {
  return { items, total, offset, limit };
}

/** The health answer of a server without sign-in (routes listed by a test take precedence). */
export const DEFAULT_HEALTH = Object.freeze({
  status: 'ok',
  version: '0.1.0',
  detector_count: 2,
  profiles: ['boq', 'generic'],
  unavailable_detectors: [],
  ai_planner: { configured: false, note: 'Adaptive AI planning is not available in this version; every registered check runs.' },
  default_profile_id: 'boq',
  auth_required: false,
});

/** Who the application acts for on such a server: the local administrator (GET /me). */
export const DEFAULT_ME = Object.freeze({
  kind: 'local',
  name: 'Local administrator',
  email: '',
  role: 'admin',
  user_id: null,
  auth_required: false,
  permissions: ['read', 'write', 'manage_users'],
  account: null,
});

const DEFAULT_ROUTES = [
  { method: 'GET', path: '/api/v1/health', respond: DEFAULT_HEALTH },
  { method: 'GET', path: '/api/v1/me', respond: DEFAULT_ME },
  { method: 'GET', path: '/api/v1/collaboration/session', respond: { reviewer: null, reviewers: [] } },
  { method: 'GET', path: /^\/api\/v1\/collaboration\/issues\/[^/]+\/comments$/, respond: { items: [], task: null } },
  { method: 'GET', path: /^\/api\/v1\/collaboration\/validation-runs\/[^/]+\/tasks$/, respond: { items: [] } },
  // The sidebar lists a few projects and users on every page.
  { method: 'GET', path: '/api/v1/projects', respond: [] },
  { method: 'GET', path: '/api/v1/users', respond: [] },
];

function matches(pattern: string | RegExp, pathname: string) {
  return pattern instanceof RegExp ? pattern.test(pathname) : pattern === pathname;
}

/** One request the stub received. */
export interface MockCall {
  method: string;
  path: string;
  query: URLSearchParams;
  /** the body as sent: a JSON string, FormData or undefined */
  // shortcut: any so tests can JSON.parse or .get() it directly; narrow to string | FormData when tests change.
  body: any;
  headers: Headers;
  signal: AbortSignal | null | undefined;
}

/** the response body, a Response, or a function of the call returning either */
export type MockResponse = ((call: MockCall) => unknown) | {} | null;

export interface MockRoute {
  method?: string;
  path: string | RegExp;
  respond: MockResponse;
}

/** Installs the fetch stub. */
export function mockFetch(routes: MockRoute[]): {
  fetch: Mock;
  calls: MockCall[];
  callsTo: (method: string, path: string | RegExp) => MockCall[];
} {
  const calls: MockCall[] = [];
  const fetchStub = vi.fn(async (input: string | Request, init: RequestInit = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, 'http://localhost');
    const method = (init.method ?? 'GET').toUpperCase();
    const call: MockCall = {
      method,
      path: url.pathname,
      query: url.searchParams,
      body: init.body,
      headers: new Headers(init.headers),
      signal: init.signal,
    };
    calls.push(call);
    if (init.signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError');
    }
    const route = [...routes, ...DEFAULT_ROUTES].find(
      (candidate) => (candidate.method ?? 'GET') === method && matches(candidate.path, url.pathname),
    );
    if (!route) {
      console.error(`Unmatched fetch in test: ${method} ${url.pathname}${url.search}`);
      return errorResponse(404, 'not_found', 'No mock route for this request.');
    }
    const result = typeof route.respond === 'function' ? await route.respond(call) : route.respond;
    return result instanceof Response ? result : jsonResponse(result);
  });
  vi.stubGlobal('fetch', fetchStub);
  return {
    fetch: fetchStub,
    calls,
    callsTo: (method, path) => calls.filter((call) => call.method === method && matches(path, call.path)),
  };
}
