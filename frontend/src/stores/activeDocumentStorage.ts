/**
 * Persistence of the active document id. All storage access goes through safeStorage, so a
 * blocked or full localStorage never breaks the app; the id then lives in memory only.
 */
import { readStorage, writeStorage } from '../utils/safeStorage.ts';

export const ACTIVE_DOCUMENT_STORAGE_KEY = 'twb.activeDocumentId';
const MAX_ID_LENGTH = 200;

/** @returns the remembered document id, or null when none (or an implausible value) is stored */
export function readActiveDocumentId(): string | null {
  const value = readStorage(ACTIVE_DOCUMENT_STORAGE_KEY);
  return typeof value === 'string' && value !== '' && value.length <= MAX_ID_LENGTH ? value : null;
}

/** @param documentId null forgets the active document */
export function writeActiveDocumentId(documentId: string | null): void {
  writeStorage(ACTIVE_DOCUMENT_STORAGE_KEY, documentId);
}
