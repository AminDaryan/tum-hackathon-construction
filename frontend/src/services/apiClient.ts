/**
 * Central HTTP client. This module is the only place in the frontend that calls `fetch`; the
 * feature services (documents, datasets, validation, issues, catalog, exports) build on it.
 *
 * Every failure surfaces as an {@link ApiError}:
 * - HTTP errors carry the backend's error envelope `{error: {code, message, details, request_id}}`;
 * - responses without an envelope get the code `http_error`;
 * - network failures get the code `network_error` (status 0).
 * Cancellations through an AbortSignal are re-thrown unchanged (`AbortError`) so callers can
 * ignore them.
 *
 * When the session holds an access token (services/accessToken.ts), every request carries it as
 * `Authorization: Bearer <token>`; a 401 with the code `unauthorized` makes the session forget
 * the token and ask for a new one.
 */
import { t } from '../i18n/messages.ts';
import { isAbortError } from '../utils/errors.ts';
import { getAccessToken, reportUnauthorized } from './accessToken.ts';

const DEFAULT_BASE_URL = '/api/v1';

/**
 * REST base URL from `VITE_API_BASE_URL` (default `/api/v1`), without a trailing slash.
 */
export function resolveBaseUrl(value: unknown): string {
  const base = typeof value === 'string' && value.trim() !== '' ? value.trim() : DEFAULT_BASE_URL;
  return base.replace(/\/+$/, '');
}

const API_BASE_URL = resolveBaseUrl(import.meta.env.VITE_API_BASE_URL);

interface ApiErrorInit {
  /** HTTP status, or 0 when no response was received */
  status: number;
  /** stable machine-readable code (e.g. `not_found`, `network_error`) */
  code: string;
  /** human-readable explanation */
  message: string;
  /** structured details from the envelope */
  details?: Record<string, unknown>;
  /** request id for support and server logs */
  requestId?: string | null;
}

/** A failed API call, normalized from the backend error envelope. */
export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  requestId: string | null;

  constructor({ status, code, message, details = {}, requestId = null }: ApiErrorInit) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

/**
 * Builds a path from a template literal, encoding every interpolated value as one path segment.
 *
 * @example apiPath`/documents/${documentId}` // "/documents/doc_1"
 */
export function apiPath(strings: TemplateStringsArray, ...values: unknown[]): string {
  return strings.reduce(
    (path, part, index) =>
      path + part + (index < values.length ? encodeURIComponent(String(values[index])) : ''),
    '',
  );
}

/**
 * Serializes query parameters. Arrays become repeated parameters (`severity=high&severity=low`);
 * `null`, `undefined` and empty strings are omitted.
 *
 * @returns the query string including `?`, or an empty string
 */
export function buildQuery(params: Record<string, unknown> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    const values = Array.isArray(value) ? value : [value];
    for (const item of values) {
      if (item !== undefined && item !== null && item !== '') {
        search.append(key, String(item));
      }
    }
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

interface RequestOptions {
  /** HTTP method (default GET) */
  method?: string;
  /** query parameters, see {@link buildQuery} */
  query?: Record<string, unknown>;
  /** JSON body; sets `Content-Type: application/json` */
  json?: unknown;
  /** multipart body; the browser sets the boundary */
  formData?: FormData;
  /** cancels the request */
  signal?: AbortSignal;
  /** Accept header (default `application/json`) */
  accept?: string;
  /** further request headers (e.g. `Prefer`) */
  headers?: Record<string, string>;
  /**
   * a token to send instead of the session's, e.g. to check a token before signing in with it
   * (null: none); a 401 for such a request leaves the session alone
   */
  authToken?: string | null;
}

/**
 * Sends a request and resolves with the Response when its status is 2xx.
 *
 * @param path API path below the base URL, e.g. `/documents`
 * @throws {ApiError} for HTTP and network failures; AbortError when cancelled
 */
export async function sendRequest(path: string, options: RequestOptions = {}): Promise<Response> {
  const { method = 'GET', query, json, formData, signal, accept = 'application/json', headers: extra = {}, authToken } = options;
  const headers: Record<string, string> = { ...extra, Accept: accept };
  const token = authToken === undefined ? getAccessToken() : authToken;
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  let body: BodyInit | undefined;
  if (formData !== undefined) {
    body = formData;
  } else if (json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(json);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}${buildQuery(query)}`, {
      method,
      headers,
      body,
      signal,
    });
  } catch (error) {
    if (isAbortError(error) || signal?.aborted) {
      throw error;
    }
    throw new ApiError({
      status: 0,
      code: 'network_error',
      message: t('The server could not be reached. Check that the backend is running, then try again.'),
      details: { cause: error instanceof Error ? error.message : String(error) },
    });
  }

  if (!response.ok) {
    const error = await errorFromResponse(response);
    if (error.status === 401 && error.code === 'unauthorized' && authToken === undefined) {
      reportUnauthorized();
    }
    throw error;
  }
  return response;
}

/**
 * Sends a request and parses the JSON body (null for empty or 204 responses). `T` is what the
 * endpoint answers; nothing checks it at runtime.
 */
async function requestJson<T = unknown>(path: string, options?: RequestOptions): Promise<T> {
  return (await requestJsonResponse<T>(path, options)).data;
}

/**
 * Like {@link requestJson}, but also resolves with the HTTP status and the response headers, for
 * endpoints whose status carries meaning (201 finished vs. 202 accepted).
 */
export async function requestJsonResponse<T = unknown>(
  path: string,
  options?: RequestOptions,
): Promise<{ data: T; status: number; headers: Headers }> {
  const response = await sendRequest(path, options);
  const text = response.status === 204 ? '' : await response.text();
  if (text === '') {
    return { data: null as T, status: response.status, headers: response.headers };
  }
  try {
    return { data: JSON.parse(text), status: response.status, headers: response.headers };
  } catch {
    throw new ApiError({
      status: response.status,
      code: 'invalid_response',
      message: t('The server returned a response that is not valid JSON.'),
      requestId: response.headers.get('X-Request-ID'),
    });
  }
}

/** Convenience wrappers used by the feature services. */
export const apiClient = Object.freeze({
  get: <T = unknown>(path: string, options?: RequestOptions) => requestJson<T>(path, { ...options, method: 'GET' }),
  post: <T = unknown>(path: string, options?: RequestOptions) => requestJson<T>(path, { ...options, method: 'POST' }),
  put: <T = unknown>(path: string, options?: RequestOptions) => requestJson<T>(path, { ...options, method: 'PUT' }),
  patch: <T = unknown>(path: string, options?: RequestOptions) => requestJson<T>(path, { ...options, method: 'PATCH' }),
  delete: <T = unknown>(path: string, options?: RequestOptions) => requestJson<T>(path, { ...options, method: 'DELETE' }),
});

/** The backend's error envelope `{error: {...}}`, as far as a response has one. */
interface ErrorEnvelope {
  code?: unknown;
  message?: unknown;
  details?: unknown;
  request_id?: unknown;
}

/** @param response a non-2xx response */
async function errorFromResponse(response: Response): Promise<ApiError> {
  const headerRequestId = response.headers.get('X-Request-ID');
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const envelope = (payload && typeof payload === 'object' ? (payload as { error?: unknown }).error : null) as ErrorEnvelope | null | undefined;
  if (envelope && typeof envelope === 'object' && typeof envelope.code === 'string') {
    return new ApiError({
      status: response.status,
      code: envelope.code,
      message:
        typeof envelope.message === 'string' && envelope.message !== ''
          ? envelope.message
          : statusMessage(response.status),
      details: envelope.details && typeof envelope.details === 'object' ? (envelope.details as Record<string, unknown>) : {},
      requestId: typeof envelope.request_id === 'string' ? envelope.request_id : headerRequestId,
    });
  }
  return new ApiError({
    status: response.status,
    code: 'http_error',
    message: statusMessage(response.status),
    requestId: headerRequestId,
  });
}

function statusMessage(status: number): string {
  return t('The server responded with HTTP {status}.', { status });
}
