import { useCallback, useMemo } from 'react';
import { useApiResource } from '../../hooks/useApiResource.ts';
import { getValidationRun, listValidationRuns } from '../../services/validationService.ts';
import type { ValidationIssue } from '../../services/apiTypes.ts';
import { useRunFindings } from '../issues/useRunFindings.ts';

// A failed run has no results to show; only runs that completed count.
const RESULT_STATUSES: ReadonlySet<string> = new Set(['completed', 'completed_with_errors']);

/**
 * The validation runs of a dataset (newest first), the chosen one (`runParam` when it is in the
 * list, else the newest finished one), its detail with the detector reports, and all of its findings with an
 * index of the cells they mark. `replaceIssue` swaps in a reviewed issue.
 */
export function useDocumentRuns(datasetId: string, runParam: string | null) {
  const runs = useApiResource((signal) => listValidationRuns(datasetId, { signal }), [datasetId]);
  const items = useMemo(() => runs.data?.items ?? [], [runs.data]);
  const finished = useMemo(() => items.filter((run) => RESULT_STATUSES.has(run.status)), [items]);
  const runId = finished.some((run) => run.run_id === runParam) ? runParam : (finished[0]?.run_id ?? null);
  // Only fetched with a run id (enabled).
  const detail = useApiResource((signal) => getValidationRun(runId!, { signal }), [runId], { enabled: Boolean(runId) });
  const findings = useRunFindings(runId);
  const { setData } = findings;
  const replaceIssue = useCallback(
    (issue: ValidationIssue) =>
      setData((current) =>
        current
          ? { ...current, items: current.items.map((item) => (item.issue_id === issue.issue_id ? { ...item, ...issue } : item)) }
          : current,
      ),
    [setData],
  );
  return {
    runs: finished,
    runsLoading: runs.loading,
    runsError: runs.error,
    reloadRuns: runs.reload,
    runId,
    run: detail.data?.run_id === runId ? detail.data : null,
    replaceRun: detail.setData,
    reloadRun: detail.reload,
    findings,
    issues: findings.data?.items ?? [],
    replaceIssue,
  };
}
