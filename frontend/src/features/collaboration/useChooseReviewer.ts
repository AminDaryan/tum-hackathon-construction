import { useState } from 'react';
import { chooseReviewer } from '../../services/collaborationService.ts';
import { useCollaboration } from './useCollaboration.ts';

/**
 * Chooses the reviewer name of this browser: an existing one switches to it, a new one joins.
 * `choose(name)` resolves true once the session has the name.
 */
export function useChooseReviewer() {
  const context = useCollaboration();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function choose(name: string) {
    setPending(true);
    setError(null);
    try {
      await chooseReviewer(name);
      context?.session.reload();
      return true;
    } catch (err) {
      setError((err as Error).message);
      return false;
    } finally {
      setPending(false);
    }
  }
  return { choose, pending, error, clearError: () => setError(null) };
}
