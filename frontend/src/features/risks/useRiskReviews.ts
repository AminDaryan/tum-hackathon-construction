import { useCallback, useMemo } from 'react';
import { useApiResource } from '../../hooks/useApiResource.ts';
import type { RiskReview } from '../../services/apiTypes.ts';
import { listRiskReviews, saveRiskReview } from '../../services/validationService.ts';

/**
 * The decisions on the run's risks without a finding: `statuses` (risk id to status), `byId`
 * (risk id to the whole review, with its comment and time) and `save(riskId, status, comment)`,
 * which stores a decision and puts it in place.
 */
export function useRiskReviews(runId: string | null) {
  // Only fetched with a run id (enabled).
  const resource = useApiResource((signal) => listRiskReviews(runId!, { signal }), [runId], { enabled: Boolean(runId) });
  const { setData } = resource;
  const items = useMemo(() => (resource.data?.run_id === runId ? (resource.data?.items ?? []) : []), [resource.data, runId]);
  const byId = useMemo(() => new Map(items.map((review) => [review.risk_id, review])), [items]);
  const statuses = useMemo(() => new Map(items.map((review) => [review.risk_id, review.status])), [items]);
  const save = useCallback(
    async (riskId: string, status: RiskReview['status'], comment = '') => {
      // A decision is only taken on a loaded run.
      const id = runId!;
      const review = await saveRiskReview(id, riskId, { status, comment });
      setData((current) => {
        const others = (current?.items ?? []).filter((item) => item.risk_id !== riskId);
        return { run_id: id, items: [...others, review] };
      });
      return review;
    },
    [runId, setData],
  );
  return { statuses, byId, save, loading: resource.loading };
}
