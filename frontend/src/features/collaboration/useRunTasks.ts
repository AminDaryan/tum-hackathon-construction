import { useMemo } from 'react';
import { getRunTasks } from '../../services/collaborationService.ts';
import type { FindingTask } from '../../services/apiTypes.ts';
import { useCollaboration } from './useCollaboration.ts';
import { usePolling } from './usePolling.ts';

/** The tasks on a run's findings by issue id, polled with the rest of the collaboration data. */
export function useRunTasks(runId: string | null | undefined): Map<string, FindingTask> {
  const context = useCollaboration();
  const resource = usePolling((signal) => getRunTasks(runId!, signal), [runId], Boolean(context && runId));
  const items = resource.data?.items;
  return useMemo(() => new Map((items ?? []).map((task) => [task.issue_id, task])), [items]);
}
