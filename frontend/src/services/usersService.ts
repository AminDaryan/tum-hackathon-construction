/**
 * Who is signed in (GET /me) and the user accounts (/users, administrators only); see
 * docs/api/rest-api.md, "Users and roles". An issued access token is returned once and never
 * stored or logged by the interface.
 */
import { apiClient, apiPath } from './apiClient.ts';
import type { IssuedToken, Me, UserAccount } from './apiTypes.ts';

/** Profile fields; a field left out stays as it is. */
export interface ProfileChanges {
  first_name?: string;
  last_name?: string;
  email?: string;
  job_title?: string;
  phone?: string;
}

/** @param options `authToken` checks a token without using or changing the session's own */
export const getMe = ({ signal, authToken }: { signal?: AbortSignal; authToken?: string | null } = {}) =>
  apiClient.get<Me>('/me', { signal, authToken });
/** Changes the signed-in user's own profile fields; answers with GET /me's body. */
export const updateMe = (changes: ProfileChanges, signal?: AbortSignal) =>
  apiClient.patch<Me>('/me', { json: changes, signal });
export const listUsers = (signal?: AbortSignal) => apiClient.get<UserAccount[]>('/users', { signal });
/** `fields`: first_name, last_name, email, job_title, phone and role. */
export const createUser = (fields: ProfileChanges & { first_name: string; role?: UserAccount['role'] }, signal?: AbortSignal) =>
  apiClient.post<IssuedToken>('/users', { json: fields, signal });
export const updateUser = (id: string, changes: ProfileChanges & { role?: UserAccount['role']; active?: boolean }, signal?: AbortSignal) =>
  apiClient.patch<UserAccount>(apiPath`/users/${id}`, { json: changes, signal });
export const deleteUser = (id: string, signal?: AbortSignal) => apiClient.delete<UserAccount[]>(apiPath`/users/${id}`, { signal });
export const issueUserToken = (id: string, signal?: AbortSignal) => apiClient.post<IssuedToken>(apiPath`/users/${id}/token`, { signal });
