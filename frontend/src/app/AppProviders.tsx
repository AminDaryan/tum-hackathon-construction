import { I18nProvider } from '../i18n/I18nProvider.tsx';
import { SessionProvider } from '../stores/SessionProvider.tsx';
import { WorkspaceProvider } from '../stores/WorkspaceProvider.tsx';
import { CollaborationProvider } from '../features/collaboration/CollaborationProvider.tsx';
import type { ReactNode } from 'react';

interface AppProvidersProps {
  children?: ReactNode;
}

/**
 * Application-wide providers (rendered inside the router). The language comes first, so the
 * sign-in dialog speaks it too; then the session, which decides whether protected routes may be
 * called (sign-in) before the workspace loads anything.
 */
export function AppProviders({ children }: AppProvidersProps) {
  return (
    <I18nProvider>
      <SessionProvider>
        <WorkspaceProvider>
          <CollaborationProvider>{children}</CollaborationProvider>
        </WorkspaceProvider>
      </SessionProvider>
    </I18nProvider>
  );
}
