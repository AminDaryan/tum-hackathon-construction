import { useContext } from 'react';
import { WorkspaceContext, type WorkspaceContextValue } from './workspaceContext.ts';

/**
 * Access to the active document state provided by {@link WorkspaceProvider}.
 *
 * @throws {Error} when used outside the provider
 */
export function useWorkspace(): WorkspaceContextValue {
  const value = useContext(WorkspaceContext);
  if (!value) {
    throw new Error('useWorkspace() must be used inside <WorkspaceProvider>.');
  }
  return value;
}
