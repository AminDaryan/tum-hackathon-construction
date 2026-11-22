/**
 * Documents: upload, list and detail (docs/api/rest-api.md#documents).
 */
import { apiClient, apiPath, sendRequest } from './apiClient.ts';
import type { DocumentDetail } from './apiTypes.ts';

/** Loads a document with its dataset summary (tables, columns, extraction report). */
export function getDocument(documentId: string, { signal }: { signal?: AbortSignal } = {}): Promise<DocumentDetail> {
  return apiClient.get(apiPath`/documents/${documentId}`, { signal });
}

/** Loads original bytes with the session's authorization; callers own any created object URL. */
export async function getDocumentOriginal(
  documentId: string,
  { signal }: { signal?: AbortSignal } = {},
): Promise<Blob> {
  const response = await sendRequest(apiPath`/documents/${documentId}/original`, { signal });
  return response.blob();
}

/**
 * Uploads a file as multipart/form-data. The server stores the original unchanged, extracts its
 * tables and answers 201 with the document detail (also when extraction itself failed).
 *
 * @param options `profileId` omitted means the server's default profile
 */
export function uploadDocument(
  file: File,
  { profileId, signal }: { profileId?: string | null; signal?: AbortSignal } = {},
): Promise<DocumentDetail> {
  const formData = new FormData();
  formData.append('file', file, file.name);
  if (profileId) {
    formData.append('profile_id', profileId);
  }
  return apiClient.post('/documents', { formData, signal });
}

/**
 * Attaches a design model (IFC) to a bill, replacing one attached before. Its elements link to
 * positions by item number; the next validation run compares their quantities with the bill's.
 */
export function attachModel(
  documentId: string,
  file: File,
  { signal }: { signal?: AbortSignal } = {},
): Promise<DocumentDetail> {
  const formData = new FormData();
  formData.append('file', file, file.name);
  return apiClient.put(apiPath`/documents/${documentId}/model`, { formData, signal });
}

/** Detaches the design model; the next validation run no longer compares with it. */
export function detachModel(documentId: string, { signal }: { signal?: AbortSignal } = {}): Promise<DocumentDetail> {
  return apiClient.delete(apiPath`/documents/${documentId}/model`, { signal });
}
