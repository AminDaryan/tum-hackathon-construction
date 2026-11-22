import { useContext } from 'react';
import { SessionContext, type SessionContextValue } from './sessionContext.ts';

/**
 * Server status and sign-in state provided by {@link SessionProvider}.
 *
 * @throws {Error} when used outside the provider
 */
export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error('useSession() must be used inside <SessionProvider>.');
  }
  return value;
}
