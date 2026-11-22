import { getNotifications, getReviewerSession } from '../../services/collaborationService.ts';
import { CollaborationContext } from './collaborationContext.ts';
import { usePolling } from './usePolling.ts';
import type { ReactNode } from 'react';

interface CollaborationProviderProps { children?: ReactNode }

export function CollaborationProvider({ children }: CollaborationProviderProps) {
  const session = usePolling(getReviewerSession, []);
  const reviewer = session.data?.reviewer;
  const inbox = usePolling(getNotifications, [reviewer?.handle], Boolean(reviewer));
  return (
    <CollaborationContext
      value={{
        reviewer,
        reviewers: session.data?.reviewers ?? [],
        bot: session.data?.bot ?? null,
        session,
        inbox,
      }}
    >
      {children}
    </CollaborationContext>
  );
}
