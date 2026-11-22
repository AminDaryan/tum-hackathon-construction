import { createContext } from 'react';
import type { NotificationList, Reviewer, ReviewerSession } from '../../services/apiTypes.ts';
import type { Polled } from './usePolling.ts';

export interface CollaborationValue {
  reviewer: Reviewer | null | undefined;
  reviewers: Reviewer[];
  bot: ReviewerSession['bot'] | null;
  session: Polled<ReviewerSession>;
  inbox: Polled<NotificationList>;
}

export const CollaborationContext = createContext<CollaborationValue | null>(null);
