import { useMemo } from 'react';
import { useApiResource, type ApiResource } from '../../hooks/useApiResource.ts';
import { indexFindings, loadRunFindings, NO_FINDINGS, type FindingsIndex } from './runFindings.ts';

/**
 * The findings of a finished run (`runId`; `null` while there is none or it still runs), with
 * an index of where they are in the tables.
 */
export function useRunFindings(
  runId: string | null,
): ApiResource<Awaited<ReturnType<typeof loadRunFindings>>> & { index: FindingsIndex } {
  // Only loads while there is a run.
  const resource = useApiResource((signal) => loadRunFindings(runId!, { signal }), [runId], {
    enabled: Boolean(runId),
  });
  const index = useMemo(
    () => (resource.data ? indexFindings(resource.data.items) : NO_FINDINGS),
    [resource.data],
  );
  return { ...resource, index };
}
