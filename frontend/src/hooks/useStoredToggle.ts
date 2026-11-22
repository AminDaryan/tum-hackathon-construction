import { useCallback, useState } from 'react';
import { readStorage, writeStorage } from '../utils/safeStorage.ts';

/**
 * An on/off choice kept in this browser (off until the person turns it on). Storage that cannot
 * be read or written leaves the choice in memory only.
 *
 * @param key the storage key
 */
export function useStoredToggle(key: string): [boolean, (on: boolean) => void] {
  const [on, setOnState] = useState(() => readStorage(key) === '1');
  const setOn = useCallback(
    (next: boolean) => {
      setOnState(next);
      writeStorage(key, next ? '1' : null);
    },
    [key],
  );
  return [on, setOn];
}
