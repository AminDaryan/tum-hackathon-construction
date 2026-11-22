import { useEffect, useState } from 'react';

/**
 * `value` once it has stayed the same for `delayMs`: a search typed into a field asks the server
 * once when the typing stops, not once per key.
 */
export function useDebouncedValue<Value>(value: Value, delayMs: number): Value {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return settled;
}
