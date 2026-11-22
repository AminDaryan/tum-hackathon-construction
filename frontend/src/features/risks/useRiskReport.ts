import { useMemo } from 'react';
import { useApiResource } from '../../hooks/useApiResource.ts';
import { getRiskReport } from '../../services/validationService.ts';

/**
 * The risk report of a finished run in its default (priority) order, with a stored discovery
 * run applied when one is given. Reading it never calls a model. `reload()` keeps the report on
 * screen while the new one loads (after a decision, a rejected finding drops out of it).
 */
export function useRiskReport(
  runId: string | null,
  { discoveryRunId = null }: { discoveryRunId?: string | null } = {},
) {
  const resource = useApiResource(
    // Only fetched with a run id (enabled).
    (signal) => getRiskReport(runId!, { discoveryRunId: discoveryRunId ?? undefined }, { signal }),
    [runId, discoveryRunId],
    { enabled: Boolean(runId) },
  );
  const report = resource.data?.run_id === runId ? resource.data : null;
  const all = useMemo(() => (report ? [...(report.risks ?? []), ...(report.record ?? [])] : []), [report]);
  const byId = useMemo(() => new Map(all.map((risk) => [risk.risk_id, risk])), [all]);
  return { report, all, byId, loading: resource.loading, error: resource.error, reload: resource.reload };
}
