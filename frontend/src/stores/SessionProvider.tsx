import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { StartingShell } from '../app/StartingShell.tsx';
import { SignInDialog } from '../features/session/SignInDialog.tsx';
import { useApiResource } from '../hooks/useApiResource.ts';
import { t } from '../i18n/messages.ts';
import { useI18n } from '../i18n/useI18n.ts';
import { clearAccessToken, getAccessToken, onUnauthorized, setAccessToken } from '../services/accessToken.ts';
import { getHealth } from '../services/catalogService.ts';
import { getMe } from '../services/usersService.ts';
import { type Permission, SessionContext } from './sessionContext.ts';

/**
 * Loads GET /health once and decides whether the application may call protected routes.
 *
 * - When the tab holds a token, the application renders at once (its requests carry the token).
 * - Otherwise it waits for the health check: a server with `auth_required` gets the sign-in
 *   dialog first, so no protected route is called without a token. When the health check fails,
 *   the application renders as before and its pages report the error.
 * - A 401 `unauthorized` from any request forgets the token and shows the dialog again; the
 *   pages are mounted afresh after signing in, so they reload their data with the new token.
 * - Once the application may call the API, GET /me says who it acts for: a user account, the
 *   administrator of a configured token, or (sign-in off) the local administrator. It is
 *   loaded again whenever the token changes; `can()` reads the role's permissions from it.
 */
export function SessionProvider({ children }: { children?: ReactNode }) {
  // Its loading text is shown outside the page area, so it follows a language switch itself.
  useI18n();
  const health = useApiResource((signal) => getHealth({ signal }), []);
  const [hasToken, setHasToken] = useState(() => Boolean(getAccessToken()));
  const [reason, setReason] = useState<'rejected' | 'signed_out' | null>(null);
  const [tokenVersion, setTokenVersion] = useState(0);

  useEffect(
    () =>
      onUnauthorized(() => {
        setHasToken(false);
        setReason('rejected');
        setTokenVersion((version) => version + 1);
      }),
    [],
  );

  const signIn = useCallback((token: string) => {
    setAccessToken(token);
    setHasToken(true);
    setReason(null);
    setTokenVersion((version) => version + 1);
  }, []);
  const signOut = useCallback(() => {
    clearAccessToken();
    setHasToken(false);
    setReason('signed_out');
    setTokenVersion((version) => version + 1);
  }, []);

  const authRequired = health.data?.auth_required === true;
  // Once the health check answered, or failed (the pages then report their own errors).
  const mayCall = hasToken || Boolean((health.data || health.error) && !authRequired);
  const me = useApiResource((signal) => getMe({ signal }), [tokenVersion], { enabled: mayCall });
  const identity = mayCall ? (me.data ?? null) : null;
  const permissions = identity?.permissions;
  const can = useCallback((permission: Permission) => (permissions ? permissions.includes(permission) : true), [permissions]);
  const value = useMemo(
    () => ({
      health: health.data ?? null,
      authRequired,
      signedIn: hasToken,
      signIn,
      signOut,
      me: identity,
      meError: mayCall ? me.error : null,
      reloadMe: me.reload,
      can,
    }),
    [health.data, authRequired, hasToken, signIn, signOut, identity, mayCall, me.error, me.reload, can],
  );

  let content = children;
  if (!hasToken && (authRequired || reason === 'rejected')) {
    content = <SignInDialog reason={reason} onSignedIn={signIn} />;
  } else if (!hasToken && !health.data && !health.error) {
    content = <StartingShell label={t('Connecting to the server…')} />;
  }
  return <SessionContext.Provider value={value}>{content}</SessionContext.Provider>;
}
