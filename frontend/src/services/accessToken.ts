/**
 * The access token for a server that requires sign-in (GET /health: `auth_required`). It is kept
 * in sessionStorage through safeStorage, so it lasts for this browser tab only, with an in-memory
 * fallback when storage is unavailable. The API client sends it as `Authorization: Bearer ...`.
 * The token is never logged, rendered or put into an error message.
 *
 * A 401 response with the code `unauthorized` means the token is missing, wrong or no longer
 * valid: the API client calls {@link reportUnauthorized}, which forgets the token and tells the
 * session (stores/SessionProvider.tsx) to ask for a new one.
 */
import { readStorage, writeStorage } from '../utils/safeStorage.ts';

export const ACCESS_TOKEN_STORAGE_KEY = 'twb.accessToken';

let memoryToken: string | null = null;
const unauthorizedListeners = new Set<() => void>();

/** @returns the current token, or null when signed out */
export function getAccessToken(): string | null {
  return readStorage(ACCESS_TOKEN_STORAGE_KEY, 'session') ?? memoryToken;
}

/** Remembers the token for this tab; `null` forgets it. */
export function setAccessToken(token: string | null): void {
  const value = typeof token === 'string' && token !== '' ? token : null;
  memoryToken = writeStorage(ACCESS_TOKEN_STORAGE_KEY, value, 'session') ? null : value;
}

/** Forgets the token (sign out). */
export function clearAccessToken(): void {
  setAccessToken(null);
}

/**
 * @param listener called when the server rejected the credentials
 * @returns unsubscribe
 */
export function onUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

/** Forgets the token and notifies the listeners: the server answered 401 `unauthorized`. */
export function reportUnauthorized(): void {
  clearAccessToken();
  unauthorizedListeners.forEach((listener) => listener());
}
