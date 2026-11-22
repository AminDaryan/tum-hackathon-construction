/**
 * Sign-in for servers that require an access token (docs/api/rest-api.md, "Security of the local
 * API"). There is no login endpoint: a token is checked by calling a protected endpoint with it.
 */
import { apiClient } from './apiClient.ts';

/**
 * Resolves when the server accepts `token`; rejects with the ApiError otherwise (401
 * `unauthorized` for a wrong token). The session's own token is neither sent nor changed.
 */
export async function verifyAccessToken(token: string, { signal }: { signal?: AbortSignal } = {}): Promise<void> {
  await apiClient.get('/profiles', { authToken: token, signal });
}
