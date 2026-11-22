/**
 * Web Storage access that never throws.
 *
 * Storage can be unavailable (private windows, blocked site data) or full. Callers keep working
 * with in-memory state when a read returns null or a write returns false. `area` chooses
 * localStorage (`local`, the default: kept across sessions) or sessionStorage (`session`: this
 * browser tab only, e.g. for an access token).
 */

type StorageArea = 'local' | 'session';

function storageFor(area: StorageArea): Storage {
  return area === 'session' ? window.sessionStorage : window.localStorage;
}

/** @returns the stored value, or null when missing or unreadable */
export function readStorage(key: string, area: StorageArea = 'local'): string | null {
  try {
    return storageFor(area).getItem(key);
  } catch {
    return null;
  }
}

/**
 * Stores a value; `null`/`undefined` removes the key.
 *
 * @returns whether the value was persisted
 */
export function writeStorage(key: string, value: string | null | undefined, area: StorageArea = 'local'): boolean {
  try {
    const storage = storageFor(area);
    if (value === null || value === undefined) {
      storage.removeItem(key);
    } else {
      storage.setItem(key, value);
    }
    return true;
  } catch {
    return false;
  }
}
