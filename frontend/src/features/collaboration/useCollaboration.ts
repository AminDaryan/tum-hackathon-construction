import { useContext } from 'react';
import { CollaborationContext, type CollaborationValue } from './collaborationContext.ts';

/** The collaboration state (reviewer, joined reviewers, session, inbox), or null outside the provider. */
export function useCollaboration(): CollaborationValue | null {
  return useContext(CollaborationContext);
}
